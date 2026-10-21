"""Turn a model extraction into review rows and accepted project fields."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from bess_workbench.models import ESSGroup, Project, Provenance, ReleaseSpecies, Sensor


class ExtractedGas(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""
    mass_g: float | None = None
    volume_ft3: float | None = None
    lfl_vol_pct: float | None = None
    molecular_weight: float | None = None
    page: int | None = None


class ExtractedKwh(BaseModel):
    model_config = ConfigDict(extra="ignore")
    room_hint: str = ""
    kwh: float | None = None
    page: int | None = None


class ExtractedSensor(BaseModel):
    model_config = ConfigDict(extra="ignore")
    gas: str = ""
    room_hint: str = ""
    mount: str = ""
    height_note: str = ""
    page: int | None = None


class ExtractedRelay(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = ""
    function: str = ""
    page: int | None = None


class Extraction(BaseModel):
    model_config = ConfigDict(extra="ignore")
    gases: list[ExtractedGas] = Field(default_factory=list)
    lfl_alarm_pct: float | None = None
    lfl_design_pct: float | None = None
    kwh_entries: list[ExtractedKwh] = Field(default_factory=list)
    sensors: list[ExtractedSensor] = Field(default_factory=list)
    relays: list[ExtractedRelay] = Field(default_factory=list)
    monitoring_only: bool | None = None
    add_alternate: bool | None = None
    notes: list[str] = Field(default_factory=list)
    document_name: str = ""


class ReviewField(BaseModel):
    key: str
    label: str
    value: str
    page: int | None = None


def parse_json_payload(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("Extraction was not a JSON object.")
    return payload


def extraction_from_text(text: str, document_name: str = "") -> Extraction:
    data = parse_json_payload(text)
    data["document_name"] = document_name
    return Extraction.model_validate(data)


def flatten_for_review(extraction: Extraction) -> list[ReviewField]:
    rows: list[ReviewField] = []
    if extraction.monitoring_only is not None:
        rows.append(ReviewField(key="flag:monitoring_only", label="Monitoring only", value=str(extraction.monitoring_only).lower(), page=None))
    if extraction.add_alternate is not None:
        rows.append(ReviewField(key="flag:add_alternate", label="Add alternate", value=str(extraction.add_alternate).lower(), page=None))
    if extraction.lfl_alarm_pct is not None:
        rows.append(ReviewField(key="lfl:alarm", label="Alarm % LFL", value=str(extraction.lfl_alarm_pct), page=None))
    if extraction.lfl_design_pct is not None:
        rows.append(ReviewField(key="lfl:design", label="Design % LFL", value=str(extraction.lfl_design_pct), page=None))
    for index, gas in enumerate(extraction.gases):
        if not gas.name:
            continue
        bits = [gas.name]
        if gas.mass_g is not None:
            bits.append(f"{gas.mass_g} g")
        if gas.lfl_vol_pct is not None:
            bits.append(f"LFL {gas.lfl_vol_pct}%")
        rows.append(ReviewField(key=f"gas:{index}", label=f"Gas {gas.name}", value=", ".join(bits), page=gas.page))
    for index, entry in enumerate(extraction.kwh_entries):
        if entry.kwh is None:
            continue
        rows.append(ReviewField(key=f"kwh:{index}", label=f"Energy {entry.room_hint or index + 1}", value=str(entry.kwh), page=entry.page))
    for index, sensor in enumerate(extraction.sensors):
        if not sensor.gas:
            continue
        rows.append(
            ReviewField(
                key=f"sensor:{index}",
                label=f"Sensor {sensor.gas}",
                value=" ".join(part for part in (sensor.room_hint, sensor.mount, sensor.height_note) if part),
                page=sensor.page,
            )
        )
    for index, relay in enumerate(extraction.relays):
        if not relay.name:
            continue
        rows.append(ReviewField(key=f"relay:{index}", label=f"Relay {relay.name}", value=relay.function, page=relay.page))
    return rows


def _stamp(project: Project, path: str, document: str, page: int | None, detail: str, now: datetime) -> None:
    project.provenance.append(
        Provenance(
            path=path,
            source_document=document,
            page=page,
            accepted_at=now.replace(microsecond=0).isoformat(),
            detail=detail,
        )
    )


def _match_room(project: Project, hint: str) -> str:
    text = hint.strip().lower()
    for room in project.rooms:
        if text and (text in room.id.lower() or text in room.name.lower()):
            return room.id
    return project.rooms[0].id if project.rooms else ""


def apply_accepted(
    project: Project,
    extraction: Extraction,
    keys: list[str],
    document_name: str,
    now: datetime | None = None,
) -> Project:
    updated = project.model_copy(deep=True)
    moment = now or datetime.now(timezone.utc)
    document = document_name or extraction.document_name or "document"
    selected = set(keys)
    for key in selected:
        if key == "flag:monitoring_only" and extraction.monitoring_only is not None:
            updated.gas.monitoring_only = extraction.monitoring_only
            _stamp(updated, "gas.monitoring_only", document, None, str(extraction.monitoring_only), moment)
        elif key == "flag:add_alternate" and extraction.add_alternate is not None:
            updated.gas.add_alternate = extraction.add_alternate
            _stamp(updated, "gas.add_alternate", document, None, str(extraction.add_alternate), moment)
        elif key == "lfl:alarm" and extraction.lfl_alarm_pct is not None:
            updated.gas.alarm_pct_lfl = extraction.lfl_alarm_pct
            _stamp(updated, "gas.alarm_pct_lfl", document, None, str(extraction.lfl_alarm_pct), moment)
        elif key == "lfl:design" and extraction.lfl_design_pct is not None:
            updated.gas.design_pct_lfl = extraction.lfl_design_pct
            _stamp(updated, "gas.design_pct_lfl", document, None, str(extraction.lfl_design_pct), moment)
        elif key.startswith("gas:"):
            gas = extraction.gases[int(key.split(":")[1])]
            name = gas.name.strip()
            if name and name.upper() not in {item.upper() for item in updated.gas.species}:
                updated.gas.species.append(name)
            updated.gas.species_source = "ul_9540a"
            updated.gas.has_9540a_gas_data = True
            release = next((item for item in updated.gas.release_species if item.name.upper() == name.upper()), None)
            if release is None:
                release = ReleaseSpecies(name=name)
                updated.gas.release_species.append(release)
            if gas.mass_g is not None:
                release.mass_g = gas.mass_g
            if gas.molecular_weight is not None:
                release.molecular_weight = gas.molecular_weight
            if gas.lfl_vol_pct is not None:
                release.lfl_vol_pct = gas.lfl_vol_pct
            release.document = document
            release.page = gas.page
            _stamp(updated, f"gas.release_species.{name}", document, gas.page, name, moment)
        elif key.startswith("kwh:"):
            entry = extraction.kwh_entries[int(key.split(":")[1])]
            if entry.kwh is None:
                continue
            room_id = _match_room(updated, entry.room_hint)
            group = next((item for item in updated.ess_groups if item.room_id == room_id), None)
            if group is None and room_id:
                group = ESSGroup(id=f"ESS-{room_id}", name=f"ESS {room_id}", room_id=room_id, kwh=entry.kwh)
                updated.ess_groups.append(group)
            if group is not None:
                group.kwh = entry.kwh
                _stamp(updated, f"ess_groups.{group.id}.kwh", document, entry.page, str(entry.kwh), moment)
        elif key.startswith("sensor:"):
            sensor = extraction.sensors[int(key.split(":")[1])]
            room_id = _match_room(updated, sensor.room_hint)
            mount = "low" if sensor.mount.strip().lower() == "low" else "high"
            new_id = f"{room_id}-{sensor.gas}-{len(updated.gas.sensors) + 1}"
            updated.gas.sensors.append(
                Sensor(id=new_id, room_id=room_id, gas=sensor.gas, mount=mount, justification=sensor.height_note, height_justified=bool(sensor.height_note))
            )
            _stamp(updated, f"gas.sensors.{new_id}", document, sensor.page, sensor.gas, moment)
        elif key.startswith("relay:"):
            relay = extraction.relays[int(key.split(":")[1])]
            name = relay.name.strip().upper()
            if name in updated.gas.controller.relay_functions or name.startswith("R") or name == "FAULT":
                updated.gas.controller.relay_functions[name] = relay.function or updated.gas.controller.relay_functions.get(name, "spare")
                updated.gas.relay_landings_shown = True
                _stamp(updated, f"gas.controller.relay_functions.{name}", document, relay.page, relay.function, moment)
    return updated
