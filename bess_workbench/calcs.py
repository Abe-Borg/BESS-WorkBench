"""Pure calculations. No UI and no pass/fail wording beyond the numbers."""

from __future__ import annotations

import json
import math

from bess_workbench.analysis import (
    BatteryResult,
    DuctResult,
    IOPoint,
    MassBalance,
    SpeciesRelease,
    SprinklerRow,
    SprinklerSummary,
)
from bess_workbench.formatting import fmt_fixed, fmt_num
from bess_workbench.models import CauseEffectRow, Project, is_li_ion
from bess_workbench.ruleset import Ruleset

CE_COLUMNS = [
    "Start exhaust",
    "Start makeup air",
    "Latch, manual reset",
    "Gas alarm to FACP",
    "Gas horns and strobes",
    "Trouble to FACP",
    "Supervisory to FACP",
    "Release door hold-opens",
    "Keep exhaust running",
    "Stop exhaust",
]

RELAY_FUNCTIONS = {
    "exhaust_makeup_latched": "Exhaust and makeup, latched, manual reset",
    "gas_alarm_to_facp": "Gas alarm to FACP",
    "gas_horns_strobes": "Gas horns and strobes",
    "trouble_to_facp": "Trouble to FACP",
    "high_gas_to_facp": "High gas to FACP",
    "spare": "Spare",
}


def room_li_ion_kwh(project: Project, room_id: str) -> float:
    return sum(group.kwh for group in project.ess_groups if group.room_id == room_id and is_li_ion(group.chemistry))


def room_other_kwh(project: Project, room_id: str) -> float:
    return sum(group.kwh for group in project.ess_groups if group.room_id == room_id and not is_li_ion(group.chemistry))


def in_scope_room_ids(project: Project, rules: Ruleset) -> set[str]:
    threshold = float(rules.param("li_ion_threshold_kwh"))
    return {room.id for room in project.rooms if room_li_ion_kwh(project, room.id) + 1e-9 >= threshold}


def sprinkler_factor(system_type: str, rules: Ruleset) -> float:
    allowed_increase = {"dry", "double_interlock_preaction"}
    if system_type in allowed_increase:
        return float(rules.param("dry_di_area_factor"))
    return 1.0


def sprinkler_rows(project: Project, rules: Ruleset) -> tuple[list[SprinklerRow], SprinklerSummary]:
    cap = float(rules.param("sprinkler_area_cap_sf"))
    factor = sprinkler_factor(project.sprinklers.system_type, rules)
    density = float(project.sprinklers.density_gpm_sf)
    rows: list[SprinklerRow] = []
    for room in project.rooms:
        base = min(max(room.area_sf, 0), cap)
        design = base * factor
        increase = design - base
        rows.append(
            SprinklerRow(
                room_id=room.id,
                room_name=room.name,
                room_area_sf=room.area_sf,
                base_area_sf=base,
                increase_sf=increase,
                design_area_sf=design,
                density_gpm_sf=density,
                sprinkler_gpm=density * design,
            )
        )
    governing = max(rows, key=lambda row: row.sprinkler_gpm) if rows else None
    if governing is not None:
        for row in rows:
            row.governing = row.room_id == governing.room_id
    hose = float(project.sprinklers.hose_gpm)
    duration = float(project.sprinklers.hose_duration_min)
    gov_gpm = governing.sprinkler_gpm if governing else 0
    total = gov_gpm + hose
    c_factor = float(rules.param("hazen_williams_c"))
    formula = (
        f"design area = min(room, {fmt_num(cap)} sf) x {fmt_num(factor)}; "
        f"sprinkler gpm = {fmt_num(density)} gpm/sf x design area; "
        f"worksheet total = governing {fmt_fixed(gov_gpm)} gpm + hose {fmt_fixed(hose)} gpm"
    )
    summary = SprinklerSummary(
        system_type=project.sprinklers.system_type,
        area_factor=factor,
        governing_room_id=governing.room_id if governing else "",
        governing_sprinkler_gpm=gov_gpm,
        hose_gpm=hose,
        total_gpm=total,
        duration_min=duration,
        volume_gal=total * duration,
        c_factor=c_factor,
        formula=formula,
    )
    return rows, summary


def duct_sprinkler(project: Project) -> DuctResult:
    k_factor = float(project.sprinklers.duct.k_factor)
    pressure = float(project.sprinklers.duct.pressure_psi)
    if k_factor <= 0:
        return DuctResult(
            k_factor=k_factor,
            pressure_psi=pressure,
            flow_gpm=None,
            formula="Enter a K-factor. q = K * sqrt(p).",
        )
    flow = k_factor * math.sqrt(max(pressure, 0))
    formula = f"q = K * sqrt(p) = {fmt_fixed(k_factor)} * sqrt({fmt_fixed(pressure)}) = {fmt_fixed(flow)} gpm"
    return DuctResult(k_factor=k_factor, pressure_psi=pressure, flow_gpm=flow, formula=formula)


def _battery(
    name: str,
    standby_a: float,
    standby_h: float,
    alarm_a: float,
    alarm_h: float,
    margin: float,
    aging: float,
    temp: float,
    sizes: list[float],
) -> BatteryResult:
    raw = standby_a * standby_h + alarm_a * alarm_h
    required = raw * (1 + margin) * aging * temp
    nxt = next((size for size in sizes if size + 1e-9 >= required), None)
    formula = (
        f"({fmt_fixed(standby_a)} A x {fmt_fixed(standby_h)} h) + "
        f"({fmt_fixed(alarm_a)} A x {fmt_fixed(alarm_h)} h) = {fmt_fixed(raw)} Ah; "
        f"x {fmt_fixed(1 + margin)} margin x {fmt_fixed(aging)} aging x {fmt_fixed(temp)} temp "
        f"= {fmt_fixed(required)} Ah"
    )
    return BatteryResult(
        name=name,
        raw_ah=raw,
        margin_used=margin,
        aging_used=aging,
        temp_used=temp,
        required_ah=required,
        next_standard_ah=nxt,
        formula=formula,
    )


def battery_pair(project: Project, rules: Ruleset) -> tuple[BatteryResult, BatteryResult]:
    sizes = [float(item) for item in rules.param("standard_battery_ah")]
    minimum_margin = float(rules.param("battery_margin_fraction"))
    margin = max(float(project.battery.margin_fraction), minimum_margin)
    aging = max(float(project.battery.aging_derate), 1.0)
    temp = max(float(project.battery.temp_derate), 1.0)
    alarm_min = float(rules.param("facp_voice_alarm_minutes" if project.battery.voice_evac else "facp_alarm_minutes"))
    facp = _battery(
        "FACP",
        project.battery.facp_standby_a,
        float(rules.param("facp_standby_hours")),
        project.battery.facp_alarm_a,
        alarm_min / 60.0,
        margin,
        aging,
        temp,
        sizes,
    )
    gas = _battery(
        "Gas panel",
        project.battery.gas_standby_a,
        float(rules.param("gas_standby_hours")),
        project.battery.gas_alarm_a,
        float(rules.param("gas_alarm_hours")),
        margin,
        aging,
        temp,
        sizes,
    )
    return facp, gas


def _gas_property(rules: Ruleset, name: str) -> tuple[float | None, float | None]:
    table = rules.param("gas_properties") or {}
    key = name.strip().upper()
    for candidate, props in table.items():
        if str(candidate).upper() == key:
            return props.get("mw"), props.get("lfl_vol_pct")
    return None, None


def mass_balance(project: Project, rules: Ruleset) -> MassBalance | None:
    volume = project.gas.release_room_volume_ft3
    species_in = [item for item in project.gas.release_species if item.mass_g > 0]
    if volume is None or volume <= 0 or not species_in:
        return None
    molar = float(rules.param("molar_volume_ft3"))
    computed: list[SpeciesRelease] = []
    for item in species_in:
        default_mw, default_lfl = _gas_property(rules, item.name)
        mw = item.molecular_weight or default_mw
        lfl = item.lfl_vol_pct or default_lfl
        if not mw or not lfl or mw <= 0 or lfl <= 0:
            continue
        moles = item.mass_g / mw
        gas_volume = moles * molar
        vol_pct = gas_volume / volume * 100
        computed.append(
            SpeciesRelease(
                name=item.name,
                moles=moles,
                volume_ft3=gas_volume,
                vol_pct=vol_pct,
                lfl_vol_pct=lfl,
                pct_of_lfl=vol_pct / lfl * 100,
            )
        )
    if not computed:
        return None
    total_gas = sum(item.volume_ft3 for item in computed)
    mixture_vol = total_gas / volume * 100
    le_chatelier = 1 / sum((item.volume_ft3 / total_gas) / item.lfl_vol_pct for item in computed)
    return MassBalance(
        species=computed,
        mixture_lfl_vol_pct=le_chatelier,
        mixture_vol_pct=mixture_vol,
        mixture_pct_of_lfl=mixture_vol / le_chatelier * 100,
        room_volume_ft3=volume,
        method=(
            "Ideal gas at 70 F and 1 atm using the ruleset molar volume. "
            "Mixture LFL is Le Chatelier on the combustible gases only. "
            "This setpoint conversion needs PE review."
        ),
    )


def proof_descriptions(project: Project) -> list[str]:
    proofs: list[str] = []
    if project.exhaust.fan_proof:
        proofs.append("Exhaust fan proof")
    if project.exhaust.makeup_proof:
        proofs.append("Makeup air proof")
    if project.exhaust.damper_proven_open:
        if project.exhaust.per_room_isolation_damper:
            for room in project.rooms:
                proofs.append(f"Damper proven open — {room.name}")
        else:
            proofs.append("Damper proven open")
    return proofs


def build_points(project: Project) -> tuple[list[IOPoint], int, int, int]:
    points: list[IOPoint] = []
    for sensor in project.gas.sensors:
        points.append(
            IOPoint(
                point_id=sensor.id,
                description=f"{sensor.gas} sensor in {sensor.room_id}",
                kind="sensor",
                landing=f"Gas panel sensor channel {sensor.id}",
                normal_state="Normal",
                offnormal_state="Low alarm / high alarm / fault",
            )
        )
    functions = project.gas.controller.relay_functions
    for index in range(1, project.gas.controller.programmable_relays + 1):
        key = f"R{index}"
        function = functions.get(key, "spare")
        points.append(
            IOPoint(
                point_id=key,
                description=RELAY_FUNCTIONS.get(function, function),
                kind="relay",
                landing=key,
                normal_state="De-energized",
                offnormal_state="Energized on the mapped cause",
            )
        )
    if project.gas.controller.has_fault_relay:
        function = functions.get("FAULT", "trouble_to_facp")
        points.append(
            IOPoint(
                point_id="FAULT",
                description=RELAY_FUNCTIONS.get(function, function),
                kind="relay",
                landing="FAULT",
                normal_state="Normal",
                offnormal_state="Trouble to FACP",
            )
        )
    proofs = proof_descriptions(project)
    inputs = max(project.gas.controller.dry_contact_inputs, 0)
    on_panel = min(len(proofs), inputs)
    on_facp = max(len(proofs) - inputs, 0)
    for index, description in enumerate(proofs):
        if index < inputs:
            landing = f"Gas panel IN{index + 1}"
        else:
            landing = f"FACP monitor module MM{index - inputs + 1}"
        points.append(
            IOPoint(
                point_id=f"P{index + 1}",
                description=description,
                kind="proof",
                landing=landing,
                normal_state="Proved",
                offnormal_state="Supervisory on loss of proof",
            )
        )
    return points, len(proofs), on_panel, on_facp


def _marks(**flags: bool) -> dict[str, str]:
    return {column: ("X" if flags.get(column, False) else "") for column in CE_COLUMNS}


def build_cause_effect(project: Project) -> list[CauseEffectRow]:
    keep = {
        "Start exhaust": True,
        "Start makeup air": True,
        "Latch, manual reset": True,
        "Keep exhaust running": True,
    }
    low = _marks(**keep, **{"Gas alarm to FACP": True})
    high = _marks(**keep, **{"Gas alarm to FACP": True, "Gas horns and strobes": True})
    fault = _marks(**{"Trouble to FACP": True, "Keep exhaust running": True})
    proof = _marks(**{"Supervisory to FACP": True, "Keep exhaust running": True})
    smoke = _marks(**{"Release door hold-opens": True, "Keep exhaust running": True})
    rows = [
        CauseEffectRow(
            cause="Low gas alarm (H2 or DMC)",
            effects=low,
            notes="Either gas. Latched. Manual reset at the gas panel. Does not use fire-alarm NACs.",
        ),
        CauseEffectRow(
            cause="High gas alarm (H2 or DMC)",
            effects=high,
            notes="Horns and strobes are the gas system, distinct from the fire alarm.",
        ),
        CauseEffectRow(
            cause="Gas detector fault",
            effects=fault,
            notes="Fault relay to FACP as trouble.",
        ),
        CauseEffectRow(
            cause="Exhaust fan proof loss",
            effects=proof,
            notes="Supervisory. Do not stop the remaining exhaust path.",
        ),
        CauseEffectRow(
            cause="Makeup air proof loss",
            effects=proof,
            notes="Supervisory.",
        ),
        CauseEffectRow(
            cause="Damper not proven open",
            effects=proof,
            notes="Supervisory. Damper is fail-open.",
        ),
        CauseEffectRow(
            cause="Smoke / fire alarm in the BESS room",
            effects=smoke,
            notes="Releases door hold-opens. Does not stop gas exhaust.",
        ),
        CauseEffectRow(
            cause="Manual reset",
            effects=_marks(),
            notes="Clears the latch only after the gas condition is clear. Reset does not itself stop a running fan.",
        ),
    ]
    if project.exhaust.hvac_shutdown_includes_exhaust:
        rows.append(
            CauseEffectRow(
                cause="HVAC shutdown (as currently specified)",
                effects=_marks(**{"Stop exhaust": True}),
                notes="This row is the specified sequence and it is not permitted.",
            )
        )
    return rows


def fingerprint(project: Project) -> str:
    payload = {
        "rooms": [room.id for room in project.rooms],
        "sensors": [sensor.id for sensor in project.gas.sensors],
        "inputs": project.gas.controller.dry_contact_inputs,
        "shutdown": project.exhaust.hvac_shutdown_includes_exhaust,
        "isolation": project.exhaust.per_room_isolation_damper,
    }
    return json.dumps(payload, sort_keys=True)


def other_duct_required_hr(wall_hr: float) -> float:
    return 3.0 if wall_hr + 1e-9 >= 3 else 1.5
