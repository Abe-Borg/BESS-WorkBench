"""Project file schema for a .bessproj JSON document."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Assignee = Literal["Architect", "Mech", "Elec", "Controls vendor", "Owner", "AHJ"]
RfiStatus = Literal["open", "closed", "deferred"]
RfiSource = Literal["auto", "manual", "ai"]
SetpointBasis = Literal["vent_gas_mix", "single_gas_lel"]
SpeciesSource = Literal["assumed_default", "ul_9540a", "user"]
SensorMount = Literal["high", "low"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Meta(_Model):
    name: str = "Untitled BESS project"
    project_number: str = ""
    client: str = ""
    site: str = ""
    prepared_by: str = ""
    synthetic: bool = False
    notes: str = ""


class CodeBasis(_Model):
    ifc: str = "2024"
    ibc: str = "2024"
    imc: str = "2024"
    nec: str = "2023"
    nfpa_855: str = "2023"
    nfpa_72: str = "2022"
    nfpa_13: str = "2025"
    nfpa_69: str = "2024"
    occupancy: str = "F-1"
    jurisdiction: str = "US"
    ahj_notes: str = ""


class Room(_Model):
    id: str
    name: str
    area_sf: float = 0
    height_ft: float = 0
    wall_rating_hr: float = 2
    floor_rating_hr: float = 2
    ceiling_rating_hr: float = 2
    fire_area_id: str = "FA-1"
    smoke_detection: bool = False


class ESSGroup(_Model):
    id: str
    name: str
    room_id: str
    chemistry: str = "lithium-ion"
    kwh: float = 0
    spacing_in: float | None = None
    ul_9540_listed: bool = False
    ul_9540a_report: bool = False


class FireArea(_Model):
    id: str
    name: str
    barrier_hr: float = 2
    floor_ceiling_hr: float = 2


class DuctSprinkler(_Model):
    k_factor: float = 0
    pressure_psi: float = 7


class Sprinklers(_Model):
    system_type: str = "wet"
    density_gpm_sf: float = 0.3
    hose_gpm: float = 100
    hose_duration_min: float = 60
    duct: DuctSprinkler = Field(default_factory=DuctSprinkler)


class Exhaust(_Model):
    name: str = "Gas exhaust"
    direct_to_exterior: bool = False
    crosses_rated_assembly: bool = True
    rated_shaft: bool = False
    fire_damper: bool = False
    smoke_damper: bool = False
    balancing_damper: bool = False
    backdraft_damper: bool = False
    motorized_damper: bool = True
    motorized_fail_open: bool = False
    damper_proven_open: bool = False
    per_room_isolation_damper: bool = False
    fan_proof: bool = False
    makeup_proof: bool = False
    standby_power_provided: bool = False
    hvac_shutdown_includes_exhaust: bool = False
    other_ducts_penetrate: bool = False
    other_duct_wall_hr: float = 2
    other_duct_damper_hr: float = 0


class Sensor(_Model):
    id: str
    room_id: str
    gas: str
    mount: SensorMount = "high"
    inches_from_ceiling: float | None = None
    inches_aff: float | None = None
    height_justified: bool = False
    justification: str = ""


class Controller(_Model):
    programmable_relays: int = 4
    has_fault_relay: bool = True
    dry_contact_inputs: int = 4
    relay_functions: dict[str, str] = Field(default_factory=dict)


class ReleaseSpecies(_Model):
    name: str
    mass_g: float = 0
    molecular_weight: float | None = None
    lfl_vol_pct: float | None = None
    document: str = ""
    page: int | None = None


class Gas(_Model):
    species: list[str] = Field(default_factory=lambda: ["H2", "DMC"])
    species_source: SpeciesSource = "assumed_default"
    has_9540a_gas_data: bool = False
    setpoint_basis: SetpointBasis = "vent_gas_mix"
    alarm_pct_lfl: float = 10
    design_pct_lfl: float = 25
    monitoring_only: bool = False
    add_alternate: bool = False
    bacnet_only: bool = False
    is_explosion_control: bool = True
    gas_horns_on_fa_nacs: bool = False
    distinct_notification: bool = True
    high_gas_to_facp: bool = True
    relay_landings_shown: bool = False
    supervising_station: bool = True
    low_alarm_starts_exhaust: bool = True
    low_alarm_starts_makeup: bool = True
    latched: bool = True
    manual_reset: bool = True
    controller: Controller = Field(default_factory=Controller)
    sensors: list[Sensor] = Field(default_factory=list)
    release_species: list[ReleaseSpecies] = Field(default_factory=list)
    release_room_volume_ft3: float | None = None
    release_room_id: str = ""


class BatteryInputs(_Model):
    facp_standby_a: float = 0.5
    facp_alarm_a: float = 2.0
    voice_evac: bool = False
    gas_standby_a: float = 0.25
    gas_alarm_a: float = 0.8
    margin_fraction: float = 0.20
    aging_derate: float = 1.25
    temp_derate: float = 1.1


class CauseEffectRow(_Model):
    cause: str
    effects: dict[str, str] = Field(default_factory=dict)
    notes: str = ""


class RFI(_Model):
    number: int
    key: str
    source: RfiSource = "manual"
    rule_id: str = ""
    title: str = ""
    text: str = ""
    assignee: Assignee = "Owner"
    status: RfiStatus = "open"
    due: str = ""
    screen: str = ""
    text_edited: bool = False
    assignee_edited: bool = False
    ai_drafted: bool = False
    auto_closed: bool = False
    user_closed: bool = False


class Provenance(_Model):
    path: str
    source_document: str
    page: int | None = None
    accepted_at: str = ""
    detail: str = ""


class Project(_Model):
    schema_version: str = "1.0.0"
    meta: Meta = Field(default_factory=Meta)
    code_basis: CodeBasis = Field(default_factory=CodeBasis)
    ruleset_id: str = ""
    ruleset_version: str = ""
    rooms: list[Room] = Field(default_factory=list)
    ess_groups: list[ESSGroup] = Field(default_factory=list)
    fire_areas: list[FireArea] = Field(default_factory=list)
    sprinklers: Sprinklers = Field(default_factory=Sprinklers)
    exhaust: Exhaust = Field(default_factory=Exhaust)
    gas: Gas = Field(default_factory=Gas)
    battery: BatteryInputs = Field(default_factory=BatteryInputs)
    cause_effect: list[CauseEffectRow] = Field(default_factory=list)
    cause_effect_manual: bool = False
    cause_effect_fingerprint: str = ""
    rfis: list[RFI] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)
    ai_narrative: str = ""
    ai_narrative_edited: bool = False
    ai_narrative_model: str = ""

    def room(self, room_id: str) -> Room | None:
        for room in self.rooms:
            if room.id == room_id:
                return room
        return None


def is_li_ion(chemistry: str) -> bool:
    text = chemistry.strip().lower().replace("_", " ").replace("-", " ")
    if text in {"lfp", "nmc", "nca", "lto", "li ion", "lithium ion"}:
        return True
    return "lithium" in text


def display_rfi_id(item: RFI) -> str:
    return f"RFI-{item.number:03d}"
