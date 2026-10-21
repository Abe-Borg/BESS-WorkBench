"""Rules engine. Status, value, citation, and tags come from this module and the rules file."""

from __future__ import annotations

from bess_workbench.analysis import (
    Analysis,
    AutoRFI,
    CheckResult,
    Rollup,
    Status,
    worst_status,
)
from bess_workbench.calcs import (
    CE_COLUMNS,
    RELAY_FUNCTIONS,
    battery_pair,
    build_points,
    duct_sprinkler,
    fingerprint,
    in_scope_room_ids,
    mass_balance,
    other_duct_required_hr,
    proof_descriptions,
    room_li_ion_kwh,
    room_other_kwh,
    sprinkler_factor,
    sprinkler_rows,
)
from bess_workbench.formatting import fmt_fixed, fmt_num
from bess_workbench.models import FireArea, Project, is_li_ion
from bess_workbench.ruleset import Ruleset

SCREENS = [
    "project",
    "rooms",
    "thresholds",
    "explosion",
    "gas",
    "cause_effect",
    "sprinklers",
    "battery",
    "rfi",
    "reports",
]


def _check(
    rules: Ruleset,
    rule_id: str,
    status: Status,
    message: str,
    value: object,
    extra_tags: list[str] | None = None,
) -> CheckResult:
    meta = rules.rule(rule_id)
    tags: list[str] = []
    for tag in [*meta.tags, *(extra_tags or [])]:
        if tag not in tags:
            tags.append(tag)
    return CheckResult(
        id=rule_id,
        rule_id=rule_id,
        screen=meta.screen,
        status=status,
        title=meta.title,
        message=message,
        value="" if value is None else str(value),
        citation=meta.citation,
        edition=meta.edition,
        tags=tags,
    )


def _fire_area(project: Project, area_id: str) -> FireArea:
    for area in project.fire_areas:
        if area.id == area_id:
            return area
    rooms = [room for room in project.rooms if room.fire_area_id == area_id]
    barrier = min((room.wall_rating_hr for room in rooms), default=0)
    horizontal = min((min(room.floor_rating_hr, room.ceiling_rating_hr) for room in rooms), default=0)
    return FireArea(id=area_id, name=area_id, barrier_hr=barrier, floor_ceiling_hr=horizontal)


def _energy_status(kwh: float, limit: float, band: float) -> Status:
    if kwh > limit + 1e-6:
        return Status.FAIL
    if kwh + 1e-6 >= limit * (1 - band):
        return Status.WARN
    return Status.PASS


def _rollups(project: Project, rules: Ruleset) -> tuple[list[Rollup], list[CheckResult]]:
    limit = float(rules.param("max_kwh_fire_area"))
    band = float(rules.param("fire_area_warn_band"))
    sep_v = float(rules.param("separate_barrier_hr"))
    sep_h = float(rules.param("separate_horizontal_hr"))
    order: list[str] = []
    for room in project.rooms:
        if room.fire_area_id not in order:
            order.append(room.fire_area_id)
    claimed: list[tuple[FireArea, list]] = []
    for area_id in order:
        rooms = [room for room in project.rooms if room.fire_area_id == area_id]
        claimed.append((_fire_area(project, area_id), rooms))

    def qualifies(area: FireArea) -> bool:
        return area.barrier_hr + 1e-9 >= sep_v and area.floor_ceiling_hr + 1e-9 >= sep_h

    rollups: list[Rollup] = []
    invalid: list[tuple[FireArea, list]] = []

    def make(area: FireArea, rooms, valid: bool, checked: bool, note: str, area_id: str | None = None) -> Rollup:
        li = sum(room_li_ion_kwh(project, room.id) for room in rooms)
        other = sum(room_other_kwh(project, room.id) for room in rooms)
        status = _energy_status(li, limit, band) if checked else Status.INFO
        return Rollup(
            fire_area_id=area_id or area.id,
            name=area.name,
            room_ids=[room.id for room in rooms],
            barrier_hr=area.barrier_hr,
            horizontal_hr=area.floor_ceiling_hr,
            separation_valid=valid,
            li_ion_kwh=li,
            other_kwh=other,
            energy_checked=checked,
            energy_status=status,
            note=note,
        )

    if len(claimed) <= 1:
        if claimed:
            area, rooms = claimed[0]
            rollups.append(
                make(
                    area,
                    rooms,
                    True,
                    True,
                    "Single fire area. A two-hour enclosure is the room minimum; three-hour separation is only required when a split is claimed.",
                )
            )
        sep_status = Status.PASS
        sep_message = "No split is claimed, so two-hour rooms stay one combined fire area."
    else:
        valid_count = 0
        for area, rooms in claimed:
            if qualifies(area):
                valid_count += 1
                rollups.append(
                    make(
                        area,
                        rooms,
                        True,
                        True,
                        f"Separated with a {fmt_num(area.barrier_hr)} h barrier and a {fmt_num(area.floor_ceiling_hr)} h floor/ceiling.",
                    )
                )
            else:
                invalid.append((area, rooms))
        if len(invalid) >= 2:
            merged_rooms = [room for _, rooms in invalid for room in rooms]
            names = ", ".join(area.id for area, _ in invalid)
            rollups.append(
                make(
                    FireArea(id="COMBINED", name="Combined 2 h enclosures", barrier_hr=2, floor_ceiling_hr=2),
                    merged_rooms,
                    False,
                    True,
                    f"Claimed areas {names} are not three-hour separations, so their lithium-ion energy is one fire area.",
                    area_id="COMBINED",
                )
            )
        elif len(invalid) == 1:
            area, rooms = invalid[0]
            rollups.append(
                make(
                    area,
                    rooms,
                    False,
                    True,
                    "This area is claimed as separate without a three-hour barrier and a three-hour floor/ceiling.",
                )
            )
        if invalid:
            sep_status = Status.FAIL
            listed = ", ".join(
                f"{area.id} ({fmt_num(area.barrier_hr)} h barrier / {fmt_num(area.floor_ceiling_hr)} h horizontal)"
                for area, _ in invalid
            )
            sep_message = (
                f"Separate fire areas need a {fmt_num(sep_v)} h barrier and a {fmt_num(sep_h)} h floor/ceiling. "
                f"F-1 is the assumed occupancy for that table and can be edited. Not separated: {listed}."
            )
        else:
            sep_status = Status.PASS
            sep_message = "Each claimed fire area has a three-hour barrier and a three-hour floor/ceiling."

    checked = [item for item in rollups if item.energy_checked]
    if not checked:
        energy_status = Status.INFO
        energy_message = "No fire area to total."
        energy_value = "0 kWh"
    else:
        energy_status = worst_status([item.energy_status for item in checked])
        bits = []
        for item in checked:
            band_low = limit * (1 - band)
            bits.append(
                f"{item.fire_area_id}: {fmt_num(item.li_ion_kwh)} kWh lithium-ion "
                f"({item.energy_status.value}; warn band {fmt_num(band_low)}–{fmt_num(limit)} kWh)"
            )
        energy_message = " ".join(bits)
        worst = max(checked, key=lambda item: (item.energy_status == Status.FAIL, item.li_ion_kwh))
        energy_value = f"{fmt_num(worst.li_ion_kwh)} kWh"

    checks = [
        _check(rules, "FP-FA-SEP", sep_status, sep_message, f"{len(claimed)} claimed fire area(s)"),
        _check(rules, "FP-FA-600", energy_status, energy_message, energy_value),
    ]
    return rollups, checks


def _threshold_checks(project: Project, rules: Ruleset) -> list[CheckResult]:
    threshold = float(rules.param("li_ion_threshold_kwh"))
    lines = []
    any_in = False
    for room in project.rooms:
        kwh = room_li_ion_kwh(project, room.id)
        in_scope = kwh + 1e-9 >= threshold
        any_in = any_in or in_scope
        lines.append(
            f"{room.name}: {fmt_num(kwh)} kWh {'at or above' if in_scope else 'below'} {fmt_num(threshold)} kWh"
        )
    if not project.rooms:
        status = Status.INFO
        message = "Add a room before the threshold can be applied."
    elif any_in:
        status = Status.PASS
        message = "ESS room rules apply to every room at or above the threshold. " + "; ".join(lines) + "."
    else:
        status = Status.INFO
        message = "No room is at the lithium-ion threshold. " + "; ".join(lines) + "."
    return [_check(rules, "FP-THRESH-20", status, message, f"{fmt_num(threshold)} kWh/room")]


def _room_checks(project: Project, rules: Ruleset) -> list[CheckResult]:
    scope = in_scope_room_ids(project, rules)
    min_hr = float(rules.param("min_room_hr"))
    wall_bad = []
    soft = []
    for room in project.rooms:
        if room.id not in scope:
            continue
        if room.wall_rating_hr + 1e-9 < min_hr:
            wall_bad.append(f"{room.name} wall {fmt_num(room.wall_rating_hr)} h")
        if room.ceiling_rating_hr + 1e-9 < min_hr or room.floor_rating_hr + 1e-9 < min_hr:
            soft.append(
                f"{room.name} floor {fmt_num(room.floor_rating_hr)} h / ceiling {fmt_num(room.ceiling_rating_hr)} h"
            )
    if not scope:
        room_status = Status.INFO
        room_message = "No in-scope room, so the two-hour enclosure check is not applied."
    elif wall_bad:
        room_status = Status.FAIL
        room_message = f"In-scope rooms need a {fmt_num(min_hr)} h enclosure. Below the wall minimum: {', '.join(wall_bad)}."
        if soft:
            room_message += f" Also review floor/ceiling: {', '.join(soft)}."
    elif soft:
        room_status = Status.WARN
        room_message = f"Walls meet {fmt_num(min_hr)} h. Floor or ceiling is lower: {', '.join(soft)}."
    else:
        room_status = Status.PASS
        room_message = f"In-scope room walls are at least {fmt_num(min_hr)} h."
    checks = [_check(rules, "FP-ROOM-2H", room_status, room_message, f"{fmt_num(min_hr)} h")]

    unlisted = [
        group.name
        for group in project.ess_groups
        if group.room_id in scope and group.kwh > 0 and not group.ul_9540_listed
    ]
    if unlisted:
        checks.append(
            _check(
                rules,
                "FP-UL9540",
                Status.FAIL,
                "These in-scope groups are not recorded as UL 9540 listed: " + ", ".join(unlisted) + ". Confirm IFC 1207.3.1 in the adopted edition.",
                "not listed",
            )
        )
    else:
        checks.append(
            _check(
                rules,
                "FP-UL9540",
                Status.PASS if scope else Status.INFO,
                "In-scope groups are recorded as UL 9540 listed." if scope else "No in-scope group to list.",
                "listed" if scope else "n/a",
            )
        )

    missing_space = [group.name for group in project.ess_groups if group.room_id in scope and group.spacing_in is None and group.kwh > 0]
    if missing_space:
        checks.append(
            _check(
                rules,
                "FP-SPACING",
                Status.WARN,
                "Spacing is blank for " + ", ".join(missing_space) + ". This workbook does not apply a code spacing limit.",
                "blank",
            )
        )
    else:
        shown = ", ".join(
            f"{group.name} {fmt_num(group.spacing_in)} in" for group in project.ess_groups if group.spacing_in is not None
        ) or "none entered"
        checks.append(_check(rules, "FP-SPACING", Status.PASS, f"Spacing on file: {shown}.", shown))

    others = [f"{group.name} ({group.chemistry})" for group in project.ess_groups if group.kwh > 0 and not is_li_ion(group.chemistry)]
    if others:
        checks.append(
            _check(
                rules,
                "FP-CHEM-OTHER",
                Status.WARN,
                "These groups are outside the encoded lithium-ion row: " + ", ".join(others) + ". Their energy is not counted in the 600 kWh lithium-ion total.",
                ", ".join(others),
                extra_tags=["NEEDS PE REVIEW"],
            )
        )
    else:
        checks.append(
            _check(rules, "FP-CHEM-OTHER", Status.PASS, "Every group with energy is in the lithium-ion family.", "lithium-ion")
        )

    if not scope:
        smoke_status, smoke_message = Status.INFO, "No in-scope room for smoke detection."
    else:
        missing_smoke = [room.name for room in project.rooms if room.id in scope and not room.smoke_detection]
        if missing_smoke:
            smoke_status = Status.FAIL
            smoke_message = "Smoke detection is not recorded in " + ", ".join(missing_smoke) + "."
        else:
            smoke_status = Status.PASS
            smoke_message = "Smoke detection is recorded in each in-scope room."
    checks.append(_check(rules, "FA-SMOKE", smoke_status, smoke_message, "smoke"))
    return checks


def _sprinkler_checks(project: Project, rules: Ruleset) -> list[CheckResult]:
    allowed = list(rules.scope.get("sprinkler_systems_allowed", []))
    system = project.sprinklers.system_type
    checks: list[CheckResult] = []
    if system not in allowed:
        checks.append(
            _check(
                rules,
                "FP-SPR-TYPE",
                Status.BLOCKED,
                f"{system} is outside this workbench. Allowed systems are wet, dry, and double-interlock preaction.",
                system,
            )
        )
    else:
        label = {"wet": "wet", "dry": "dry", "double_interlock_preaction": "double-interlock preaction"}.get(system, system)
        checks.append(_check(rules, "FP-SPR-TYPE", Status.PASS, f"System type is {label}.", label))

    rows, summary = sprinkler_rows(project, rules)
    baseline = float(rules.param("sprinkler_density_gpm_sf"))
    missing_report = [group for group in project.ess_groups if group.kwh > 0 and not group.ul_9540a_report]
    if project.sprinklers.density_gpm_sf + 1e-9 < baseline and missing_report:
        design_status = Status.FAIL
        design_message = (
            f"Density {fmt_fixed(project.sprinklers.density_gpm_sf)} gpm/sf is below {fmt_fixed(baseline)} "
            "and a UL 9540A report is not on file for every group with energy. "
            + summary.formula
        )
    elif not rows:
        design_status = Status.INFO
        design_message = "Add a room to size the sprinkler demand."
    else:
        design_status = Status.PASS
        design_message = summary.formula + f". Governing room {summary.governing_room_id or 'n/a'}."
    checks.append(
        _check(
            rules,
            "FP-SPR-DESIGN",
            design_status,
            design_message,
            f"{fmt_fixed(summary.governing_sprinkler_gpm)} gpm",
        )
    )

    factor = sprinkler_factor(system, rules)
    if factor > 1:
        delta = ", ".join(f"{row.room_name} +{fmt_num(row.increase_sf)} sf" for row in rows) or "no rooms"
        checks.append(
            _check(
                rules,
                "FP-SPR-30",
                Status.PASS,
                f"Area factor {fmt_num(factor)} is applied. Added area: {delta}.",
                f"x{fmt_num(factor)}",
            )
        )
    else:
        checks.append(
            _check(
                rules,
                "FP-SPR-30",
                Status.PASS,
                "Wet system: the dry/preaction area increase is not applied. Delta is 0 sf.",
                "delta 0 sf",
            )
        )

    cutoff = float(rules.param("sprinkler_block_kwh"))
    blocked = [group.name for group in project.ess_groups if group.kwh > cutoff and not group.ul_9540a_report]
    if blocked:
        checks.append(
            _check(
                rules,
                "FP-SPR-9540A",
                Status.BLOCKED,
                "Sprinkler sign-off is blocked. Groups above "
                f"{fmt_num(cutoff)} kWh without a UL 9540A report: {', '.join(blocked)}. The density math is still shown.",
                ", ".join(blocked),
            )
        )
    else:
        checks.append(
            _check(
                rules,
                "FP-SPR-9540A",
                Status.PASS,
                f"No group above {fmt_num(cutoff)} kWh is missing a UL 9540A report.",
                "clear",
            )
        )

    c_value = float(rules.param("hazen_williams_c"))
    checks.append(
        _check(
            rules,
            "FP-SPR-C100",
            Status.PASS,
            f"Hazen-Williams C is fixed at {fmt_num(c_value)}. This is a recorded basis, not a hydraulic model.",
            f"C={fmt_num(c_value)}",
        )
    )
    if project.sprinklers.hose_gpm <= 0 or project.sprinklers.hose_duration_min <= 0:
        hose_status = Status.WARN
        hose_message = "Hose allowance flow or duration is zero."
    else:
        hose_status = Status.PASS
        hose_message = (
            f"Hose {fmt_num(project.sprinklers.hose_gpm)} gpm for {fmt_num(project.sprinklers.hose_duration_min)} min. "
            f"Worksheet volume {fmt_num(summary.volume_gal)} gal (governing sprinkler demand plus hose)."
        )
    checks.append(
        _check(
            rules,
            "FP-SPR-HOSE",
            hose_status,
            hose_message,
            f"{fmt_num(project.sprinklers.hose_gpm)} gpm / {fmt_num(project.sprinklers.hose_duration_min)} min",
        )
    )

    duct = duct_sprinkler(project)
    minimum = float(rules.param("duct_min_psi"))
    if duct.k_factor <= 0:
        duct_status = Status.WARN
        duct_message = "Enter the duct sprinkler K-factor. " + duct.formula
    elif duct.pressure_psi + 1e-9 < minimum:
        duct_status = Status.FAIL
        duct_message = f"Duct sprinkler pressure {fmt_fixed(duct.pressure_psi)} psi is below {fmt_num(minimum)} psi. " + duct.formula
    else:
        duct_status = Status.PASS
        duct_message = duct.formula
    checks.append(
        _check(
            rules,
            "FP-SPR-DUCT",
            duct_status,
            duct_message,
            "n/a" if duct.flow_gpm is None else f"{fmt_fixed(duct.flow_gpm)} gpm",
        )
    )

    if missing_report:
        names = ", ".join(f"{group.name} ({fmt_num(group.kwh)} kWh)" for group in missing_report)
        checks.append(
            _check(
                rules,
                "FP-9540A-RFI",
                Status.WARN,
                f"UL 9540A report is not on file for {names}.",
                names,
            )
        )
    else:
        checks.append(_check(rules, "FP-9540A-RFI", Status.PASS, "A UL 9540A report is recorded for every group with energy.", "on file"))
    return checks


def _imc_failed(project: Project, rules: Ruleset) -> bool:
    exhaust = project.exhaust
    if exhaust.fire_damper or exhaust.smoke_damper or exhaust.balancing_damper or exhaust.backdraft_damper:
        return True
    if not exhaust.direct_to_exterior and exhaust.crosses_rated_assembly and not exhaust.rated_shaft:
        return True
    if exhaust.motorized_damper and (not exhaust.motorized_fail_open or not exhaust.damper_proven_open):
        return True
    if exhaust.other_ducts_penetrate:
        required = other_duct_required_hr(exhaust.other_duct_wall_hr)
        if exhaust.other_duct_damper_hr + 1e-9 < required:
            return True
    return False


def _explosion_checks(project: Project, rules: Ruleset) -> list[CheckResult]:
    exhaust = project.exhaust
    checks: list[CheckResult] = []
    if exhaust.fire_damper or exhaust.smoke_damper:
        which = []
        if exhaust.fire_damper:
            which.append("fire damper")
        if exhaust.smoke_damper:
            which.append("smoke damper")
        fsd_status = Status.FAIL
        fsd_message = "Gas exhaust is marked with a " + " and ".join(which) + "."
    else:
        fsd_status = Status.PASS
        fsd_message = "No fire damper and no smoke damper on the gas exhaust."
    checks.append(_check(rules, "FP-IMC-FSD", fsd_status, fsd_message, "clear" if fsd_status == Status.PASS else "present"))

    if exhaust.balancing_damper:
        checks.append(_check(rules, "FP-IMC-BAL", Status.FAIL, "A balancing damper is marked on the gas exhaust.", "present"))
    else:
        checks.append(_check(rules, "FP-IMC-BAL", Status.PASS, "No balancing damper on the gas exhaust.", "clear"))

    if exhaust.backdraft_damper:
        checks.append(_check(rules, "FP-IMC-BD", Status.FAIL, "A backdraft damper is marked on the gas exhaust.", "present"))
    else:
        checks.append(_check(rules, "FP-IMC-BD", Status.PASS, "No backdraft damper on the gas exhaust.", "clear"))

    if exhaust.direct_to_exterior:
        checks.append(
            _check(
                rules,
                "FP-IMC-SHAFT",
                Status.PASS,
                "The exhaust terminates at an exterior wall or roof, so a rated shaft is not required for that run.",
                "direct to exterior",
            )
        )
    elif exhaust.crosses_rated_assembly and not exhaust.rated_shaft:
        checks.append(
            _check(
                rules,
                "FP-IMC-SHAFT",
                Status.FAIL,
                "The duct crosses a rated assembly and a rated shaft is not indicated.",
                "shaft missing",
            )
        )
    elif exhaust.crosses_rated_assembly:
        checks.append(_check(rules, "FP-IMC-SHAFT", Status.PASS, "A rated shaft is indicated where the duct crosses a rated assembly.", "shaft"))
    else:
        checks.append(
            _check(rules, "FP-IMC-SHAFT", Status.PASS, "The duct is not marked as crossing a rated assembly.", "no crossing")
        )

    if not exhaust.motorized_damper and exhaust.direct_to_exterior:
        motor_status = Status.PASS
        motor_message = "No motorized damper is indicated on a direct exterior termination."
    elif not exhaust.motorized_damper:
        motor_status = Status.FAIL
        motor_message = "The exhaust is not direct to exterior and no fail-open motorized damper is indicated."
    elif not exhaust.motorized_fail_open or not exhaust.damper_proven_open:
        motor_status = Status.FAIL
        missing = []
        if not exhaust.motorized_fail_open:
            missing.append("fail-open")
        if not exhaust.damper_proven_open:
            missing.append("proven-open to the FACP")
        motor_message = "Motorized damper is missing: " + ", ".join(missing) + "."
    else:
        motor_status = Status.PASS
        motor_message = "Motorized damper fails open and proves open to the FACP."
    checks.append(_check(rules, "FP-IMC-MOTOR", motor_status, motor_message, "motorized damper"))

    if not exhaust.other_ducts_penetrate:
        checks.append(
            _check(rules, "FP-IMC-OTHER", Status.PASS, "No other ducts are flagged through BESS walls.", "none")
        )
    else:
        required = other_duct_required_hr(exhaust.other_duct_wall_hr)
        if exhaust.other_duct_damper_hr + 1e-9 < required:
            checks.append(
                _check(
                    rules,
                    "FP-IMC-OTHER",
                    Status.FAIL,
                    f"Other-duct damper is {fmt_num(exhaust.other_duct_damper_hr)} h in a {fmt_num(exhaust.other_duct_wall_hr)} h wall. Required damper rating is {fmt_num(required)} h.",
                    f"{fmt_num(exhaust.other_duct_damper_hr)} h",
                )
            )
        else:
            checks.append(
                _check(
                    rules,
                    "FP-IMC-OTHER",
                    Status.PASS,
                    f"Other-duct damper {fmt_num(exhaust.other_duct_damper_hr)} h meets {fmt_num(required)} h for a {fmt_num(exhaust.other_duct_wall_hr)} h wall.",
                    f"{fmt_num(exhaust.other_duct_damper_hr)} h",
                )
            )

    if _imc_failed(project, rules):
        imc_status = Status.FAIL
        imc_message = "One or more gas-exhaust duct checks failed. See the IMC line items."
    else:
        imc_status = Status.PASS
        imc_message = "The IMC duct line items pass, which is also FA lead item 10."
    checks.append(_check(rules, "FA-IMC-509", imc_status, imc_message, imc_status.value))

    logic_gaps = []
    if not project.gas.low_alarm_starts_exhaust:
        logic_gaps.append("low alarm does not start exhaust")
    if not project.gas.low_alarm_starts_makeup:
        logic_gaps.append("low alarm does not start makeup air")
    if not project.gas.latched:
        logic_gaps.append("sequence is not latched")
    if not project.gas.manual_reset:
        logic_gaps.append("reset is not manual")
    if logic_gaps:
        checks.append(_check(rules, "FP-EXH-LOGIC", Status.FAIL, "; ".join(logic_gaps).capitalize() + ".", "incomplete"))
    else:
        checks.append(
            _check(
                rules,
                "FP-EXH-LOGIC",
                Status.PASS,
                "Low alarm from either gas starts exhaust and makeup air, latched, with manual reset.",
                "latched",
            )
        )

    if exhaust.hvac_shutdown_includes_exhaust:
        checks.append(
            _check(
                rules,
                "FA-NO-SHUTDOWN",
                Status.FAIL,
                "The HVAC shutdown sequence includes the gas exhaust. Fire alarm must not stop that fan.",
                "stops exhaust",
            )
        )
    else:
        checks.append(
            _check(
                rules,
                "FA-NO-SHUTDOWN",
                Status.PASS,
                "HVAC shutdown is not marked as stopping the gas exhaust.",
                "exhaust stays on",
            )
        )

    hours = float(rules.param("exhaust_standby_hours"))
    if exhaust.standby_power_provided:
        checks.append(
            _check(
                rules,
                "FA-EXH-STANDBY",
                Status.PASS,
                f"Standby power is indicated for the exhaust fan ({fmt_num(hours)} h per the rules file). Verify IFC 1207.6.1.2 and NFPA 855 before issuing.",
                f"{fmt_num(hours)} h",
            )
        )
    else:
        checks.append(
            _check(
                rules,
                "FA-EXH-STANDBY",
                Status.FAIL,
                f"Exhaust-fan standby power is not indicated. The rules file expects {fmt_num(hours)} h, and the subsection still needs PE review.",
                "not provided",
            )
        )

    alarm_max = float(rules.param("alarm_lfl_pct_max"))
    if project.gas.alarm_pct_lfl > alarm_max + 1e-9:
        checks.append(
            _check(
                rules,
                "FP-LFL-10",
                Status.FAIL,
                f"Low-alarm setpoint is {fmt_num(project.gas.alarm_pct_lfl)}% LFL, above {fmt_num(alarm_max)}%.",
                f"{fmt_num(project.gas.alarm_pct_lfl)}%",
            )
        )
    else:
        checks.append(
            _check(
                rules,
                "FP-LFL-10",
                Status.PASS,
                f"Low-alarm setpoint is {fmt_num(project.gas.alarm_pct_lfl)}% LFL (limit {fmt_num(alarm_max)}%). Subsection 9.6.5.6 still needs PE review.",
                f"{fmt_num(project.gas.alarm_pct_lfl)}%",
            )
        )

    design_limit = float(rules.param("design_lfl_pct_limit"))
    design_value = project.gas.design_pct_lfl
    if design_value > design_limit + 1e-9:
        design_status = Status.FAIL
        design_message = f"Design fraction {fmt_num(design_value)}% LFL is above {fmt_num(design_limit)}%."
    elif abs(design_value - design_limit) <= 1e-9:
        design_status = Status.WARN
        design_message = (
            f"Design fraction is exactly {fmt_num(design_limit)}% LFL. "
            "The FP lead states 25 percent and the FA lead states below 25 percent. A PE has to close that conflict."
        )
    else:
        design_status = Status.PASS
        design_message = f"Design fraction {fmt_num(design_value)}% LFL is below {fmt_num(design_limit)}%."
    checks.append(_check(rules, "FP-LFL-25", design_status, design_message, f"{fmt_num(design_value)}%"))

    balance = mass_balance(project, rules)
    if balance is None:
        checks.append(
            _check(
                rules,
                "GAS-MB",
                Status.INFO,
                "No release mass and room volume are entered, so the helper has nothing to compute.",
                "no data",
            )
        )
        checks.append(
            _check(
                rules,
                "FA-SETPOINT-CONV",
                Status.INFO,
                "No release case is available to convert into a mixture percent LFL.",
                "no data",
            )
        )
    else:
        level = balance.mixture_pct_of_lfl
        if level + 1e-9 >= 100:
            mb_status = Status.FAIL
        elif level + 1e-9 >= design_limit:
            mb_status = Status.WARN
        else:
            mb_status = Status.PASS
        detail = ", ".join(
            f"{item.name} {fmt_fixed(item.vol_pct)} vol% ({fmt_fixed(item.pct_of_lfl)}% of its LFL)" for item in balance.species
        )
        checks.append(
            _check(
                rules,
                "GAS-MB",
                mb_status,
                f"{balance.method} Species: {detail}. Mixture {fmt_fixed(balance.mixture_vol_pct)} vol% is {fmt_fixed(level)}% of the mixture LFL ({fmt_fixed(balance.mixture_lfl_vol_pct)} vol%).",
                f"{fmt_fixed(level)}% of mixture LFL",
            )
        )
        checks.append(
            _check(
                rules,
                "FA-SETPOINT-CONV",
                Status.WARN,
                "The helper converted user-entered masses to a mixture percent LFL. Treat that conversion as needing PE review, including any vendor single-gas percent LEL.",
                f"{fmt_fixed(level)}% LFL",
            )
        )
    return checks


def _gas_checks(project: Project, rules: Ruleset) -> list[CheckResult]:
    checks: list[CheckResult] = []
    scope = in_scope_room_ids(project, rules) or {room.id for room in project.rooms}
    species = project.gas.species or list(rules.param("default_gases"))
    gaps = []
    for room in project.rooms:
        if room.id not in scope:
            continue
        have = {sensor.gas.strip().upper() for sensor in project.gas.sensors if sensor.room_id == room.id}
        missing = [name for name in species if name.strip().upper() not in have]
        if missing:
            gaps.append(f"{room.name}: {', '.join(missing)}")
    extra = ["ASSUMED"] if project.gas.species_source == "assumed_default" else []
    if gaps:
        checks.append(
            _check(
                rules,
                "FP-SENSOR-COVER",
                Status.FAIL,
                "Missing sensors — " + "; ".join(gaps) + ".",
                "; ".join(gaps),
                extra_tags=extra,
            )
        )
    else:
        source = "the default H2 and DMC list" if project.gas.species_source == "assumed_default" else project.gas.species_source
        checks.append(
            _check(
                rules,
                "FP-SENSOR-COVER",
                Status.PASS,
                f"Each room has a sensor for every gas on {source}.",
                ", ".join(species),
                extra_tags=extra,
            )
        )

    single = project.gas.setpoint_basis == "single_gas_lel" or not project.gas.has_9540a_gas_data
    if project.gas.setpoint_basis == "single_gas_lel" and not project.gas.has_9540a_gas_data:
        single_message = "Setpoints are single-gas percent LEL and UL 9540A gas data is not on file. That is not a vent-gas mixture setpoint."
        single_status = Status.WARN
    elif project.gas.setpoint_basis == "single_gas_lel":
        single_message = "Vendor setpoints are single-gas percent LEL. Convert them to the vent-gas mixture before relying on them."
        single_status = Status.WARN
    elif not project.gas.has_9540a_gas_data:
        single_message = "The mixture basis is selected, but UL 9540A gas data is not on file to support it."
        single_status = Status.WARN
    else:
        single_message = "Setpoints are on a vent-gas mixture basis and UL 9540A gas data is marked on file."
        single_status = Status.PASS
        single = False
    checks.append(_check(rules, "FP-LFL-SINGLE", single_status, single_message, project.gas.setpoint_basis))

    hard = (project.gas.monitoring_only or project.gas.bacnet_only) and project.gas.is_explosion_control
    if hard:
        flags = []
        if project.gas.monitoring_only:
            flags.append("monitoring-only")
        if project.gas.bacnet_only:
            flags.append("BACnet-only")
        checks.append(
            _check(
                rules,
                "FA-HARD-MON",
                Status.FAIL,
                "Hard fail: gas detection is " + " and ".join(flags) + " while it is the explosion control. The life-safety sequence has to be hardwired.",
                ", ".join(flags),
            )
        )
    elif project.gas.add_alternate:
        checks.append(
            _check(
                rules,
                "FA-HARD-MON",
                Status.WARN,
                "Gas detection is flagged as an add-alternate. Confirm it is base-scope hardwired explosion control.",
                "add alternate",
            )
        )
    elif not project.gas.is_explosion_control:
        checks.append(
            _check(
                rules,
                "FA-HARD-MON",
                Status.WARN,
                "Gas detection is not marked as the explosion-control sequence.",
                "not explosion control",
            )
        )
    else:
        checks.append(
            _check(
                rules,
                "FA-HARD-MON",
                Status.PASS,
                "Gas detection is not monitoring-only or BACnet-only, and it is the explosion-control sequence.",
                "hardwired",
            )
        )

    if project.gas.gas_horns_on_fa_nacs:
        checks.append(
            _check(rules, "FA-HARD-NAC", Status.FAIL, "Hard fail: gas horns are on fire-alarm NACs.", "on FA NACs")
        )
    else:
        checks.append(_check(rules, "FA-HARD-NAC", Status.PASS, "Gas horns are not on fire-alarm NACs.", "separate"))

    if not project.gas.distinct_notification:
        checks.append(
            _check(rules, "FA-DISTINCT", Status.FAIL, "Gas notification is not marked distinct from the fire alarm.", "not distinct")
        )
    else:
        checks.append(_check(rules, "FA-DISTINCT", Status.PASS, "Gas notification is marked distinct from the fire alarm.", "distinct"))

    functions = project.gas.controller.relay_functions
    needed = {
        "R1": ("exhaust_makeup_latched", "R1 exhaust and makeup, latched, manual reset"),
        "R2": ("gas_alarm_to_facp", "R2 gas alarm to the FACP"),
        "R3": ("gas_horns_strobes", "R3 gas horns and strobes"),
    }
    missing_fn = [label for relay, (function, label) in needed.items() if functions.get(relay) != function]
    fault_ok = project.gas.controller.has_fault_relay and functions.get("FAULT") == "trouble_to_facp"
    if project.gas.controller.programmable_relays < 3:
        missing_fn.append("fewer than three programmable relays")
    if not fault_ok:
        missing_fn.append("fault relay as trouble to the FACP")
    if missing_fn:
        checks.append(_check(rules, "FA-RELAYS", Status.FAIL, "Relay map is incomplete or misassigned: " + "; ".join(missing_fn) + ".", "incomplete"))
    else:
        described = ", ".join(f"{key}={RELAY_FUNCTIONS.get(value, value)}" for key, value in functions.items())
        checks.append(_check(rules, "FA-RELAYS", Status.PASS, f"Relay map covers R1, R2, R3, and the fault relay. {described}.", "R1/R2/R3/fault"))

    ceiling_limit = float(rules.param("h2_max_inches_from_ceiling"))
    h2_bad = []
    for sensor in project.gas.sensors:
        if sensor.gas.strip().upper() != "H2":
            continue
        if sensor.mount != "high" or sensor.inches_from_ceiling is None or sensor.inches_from_ceiling > ceiling_limit + 1e-9:
            h2_bad.append(sensor.id)
    if not any(sensor.gas.strip().upper() == "H2" for sensor in project.gas.sensors):
        checks.append(_check(rules, "FA-H2-CEILING", Status.WARN, "No hydrogen sensor is on the project.", "none"))
    elif h2_bad:
        checks.append(
            _check(
                rules,
                "FA-H2-CEILING",
                Status.WARN,
                f"These hydrogen sensors are not within {fmt_num(ceiling_limit)} in of the ceiling: {', '.join(h2_bad)}. There is still no fixed code height; justify the location.",
                ", ".join(h2_bad),
            )
        )
    else:
        checks.append(
            _check(
                rules,
                "FA-H2-CEILING",
                Status.PASS,
                f"Hydrogen sensors are high and within {fmt_num(ceiling_limit)} in of the ceiling.",
                f"<= {fmt_num(ceiling_limit)} in",
            )
        )

    dmc_bad = [sensor.id for sensor in project.gas.sensors if sensor.gas.strip().upper() == "DMC" and sensor.mount != "low"]
    if not any(sensor.gas.strip().upper() == "DMC" for sensor in project.gas.sensors):
        checks.append(_check(rules, "FA-DMC-LOW", Status.WARN, "No DMC sensor is on the project.", "none"))
    elif dmc_bad:
        checks.append(_check(rules, "FA-DMC-LOW", Status.WARN, "These DMC sensors are not mounted low: " + ", ".join(dmc_bad) + ".", ", ".join(dmc_bad)))
    else:
        checks.append(_check(rules, "FA-DMC-LOW", Status.PASS, "DMC sensors are mounted low.", "low"))

    unjustified = [sensor.id for sensor in project.gas.sensors if not sensor.height_justified]
    if unjustified:
        checks.append(
            _check(
                rules,
                "FA-HEIGHT-OPEN",
                Status.WARN,
                "Height is still an open item for " + ", ".join(unjustified) + ". Justify each one from UL 9540A data and airflow with exhaust on and with exhaust failed.",
                f"{len(unjustified)} open",
            )
        )
    elif project.gas.sensors:
        checks.append(_check(rules, "FA-HEIGHT-OPEN", Status.PASS, "Every sensor height is marked justified.", "justified"))
    else:
        checks.append(_check(rules, "FA-HEIGHT-OPEN", Status.WARN, "No sensors are entered, so heights cannot be justified.", "no sensors"))

    proofs_ok = project.exhaust.fan_proof and project.exhaust.makeup_proof and project.exhaust.damper_proven_open
    proofs = proof_descriptions(project)
    inputs = project.gas.controller.dry_contact_inputs
    shortfall = max(len(proofs) - max(inputs, 0), 0)
    if not proofs_ok:
        checks.append(
            _check(
                rules,
                "FA-PROOFS",
                Status.FAIL,
                "Fan proof, makeup-air proof, and damper proven-open all have to be indicated. Loss of proof is supervisory.",
                "proofs incomplete",
            )
        )
    elif shortfall:
        checks.append(
            _check(
                rules,
                "FA-PROOFS",
                Status.WARN,
                f"{len(proofs)} proof points and {inputs} gas-panel inputs. {shortfall} proof point(s) move to FACP monitor modules. Loss of proof is supervisory.",
                f"{shortfall} on FACP",
            )
        )
    else:
        checks.append(
            _check(
                rules,
                "FA-PROOFS",
                Status.PASS,
                f"All {len(proofs)} proof points land on the gas panel ({inputs} inputs). Loss of proof is supervisory.",
                f"{len(proofs)} on panel",
            )
        )

    if project.gas.supervising_station:
        checks.append(
            _check(
                rules,
                "FA-SUPERVISING",
                Status.PASS,
                "Gas alarm, trouble, and supervisory are marked for transmission to the supervising station.",
                "yes",
            )
        )
    else:
        checks.append(
            _check(
                rules,
                "FA-SUPERVISING",
                Status.FAIL,
                "Gas alarm, trouble, and supervisory are not marked for the supervising station.",
                "no",
            )
        )

    if project.gas.relay_landings_shown:
        checks.append(_check(rules, "FP-LAND-RFI", Status.PASS, "Relay landings are marked as shown on the controls drawings.", "shown"))
    else:
        checks.append(
            _check(
                rules,
                "FP-LAND-RFI",
                Status.WARN,
                "Relay landings for R1, R2, R3, and the fault relay are not shown.",
                "not shown",
            )
        )

    if project.gas.high_gas_to_facp:
        checks.append(_check(rules, "FP-HIGH-RFI", Status.PASS, "A high-gas signal to the FACP is indicated.", "yes"))
    else:
        checks.append(
            _check(
                rules,
                "FP-HIGH-RFI",
                Status.WARN,
                "No high-gas signal to the FACP is indicated. Local horns are not that signal.",
                "no",
            )
        )
    return checks


def _ce_checks(project: Project, rules: Ruleset) -> list[CheckResult]:
    stop_rows = [row.cause for row in project.cause_effect if row.effects.get("Stop exhaust") == "X"]
    if stop_rows:
        stop = _check(
            rules,
            "CE-STOP",
            Status.FAIL,
            "The matrix stops gas exhaust on: " + "; ".join(stop_rows) + ".",
            "stops exhaust",
        )
    else:
        stop = _check(rules, "CE-STOP", Status.PASS, "No matrix row stops the gas exhaust.", "exhaust stays on")
    if project.cause_effect_manual and project.cause_effect_fingerprint and project.cause_effect_fingerprint != fingerprint(project):
        source = _check(
            rules,
            "CE-SOURCE",
            Status.WARN,
            "The matrix was edited by hand and the room, sensor, or exhaust inputs have changed since that edit.",
            "stale",
        )
    elif project.cause_effect_manual:
        source = _check(rules, "CE-SOURCE", Status.PASS, "The matrix is user-edited and still matches the current room list.", "edited")
    else:
        source = _check(
            rules,
            "CE-SOURCE",
            Status.PASS,
            "The matrix is generated from the lead sequence and refreshes until someone edits a cell.",
            "generated",
        )
    return [stop, source]


def _battery_checks(project: Project, rules: Ruleset) -> list[CheckResult]:
    facp, gas = battery_pair(project, rules)
    alarm_min = float(rules.param("facp_voice_alarm_minutes" if project.battery.voice_evac else "facp_alarm_minutes"))
    voice = "voice evacuation, 15 min alarm" if project.battery.voice_evac else "5 min alarm"
    checks = [
        _check(
            rules,
            "FA-BATT-FACP",
            Status.PASS,
            f"FACP worksheet is 24 h standby + {fmt_num(alarm_min)} min ({voice}). {facp.formula}. Next standard size: {facp.next_standard_ah or 'above the catalog'} Ah.",
            f"{fmt_fixed(facp.required_ah)} Ah",
        ),
        _check(
            rules,
            "FA-BATT-GAS",
            Status.PASS,
            f"Gas panel worksheet is 24 h standby + 2 h alarm. {gas.formula}. Next standard size: {gas.next_standard_ah or 'above the catalog'} Ah. Verify IFC 1207.6.1.2 and NFPA 855.",
            f"{fmt_fixed(gas.required_ah)} Ah",
        ),
    ]
    problems = []
    if project.battery.margin_fraction + 1e-9 < float(rules.param("battery_margin_fraction")):
        problems.append(
            f"entered margin {fmt_num(project.battery.margin_fraction * 100)}% is below 20%; the worksheet used 20%"
        )
    if project.battery.aging_derate + 1e-9 < 1:
        problems.append("aging derate was below 1 and was raised to 1 so capacity is not increased")
    if project.battery.temp_derate + 1e-9 < 1:
        problems.append("temperature derate was below 1 and was raised to 1 so capacity is not increased")
    if facp.next_standard_ah is None or gas.next_standard_ah is None:
        problems.append("required ampere-hours exceed the largest standard size in the rules file")
    if problems:
        checks.append(_check(rules, "FA-BATT-MARGIN", Status.FAIL, "; ".join(problems).capitalize() + ".", "adjusted"))
    else:
        checks.append(
            _check(
                rules,
                "FA-BATT-MARGIN",
                Status.PASS,
                f"Margin {fmt_num(facp.margin_used * 100)}%, aging x{fmt_fixed(facp.aging_used)}, temperature x{fmt_fixed(facp.temp_used)}.",
                f"{fmt_num(facp.margin_used * 100)}%",
            )
        )
    return checks


def _project_checks(project: Project, rules: Ruleset) -> list[CheckResult]:
    if project.code_basis.jurisdiction.strip().upper() != "US":
        scope = _check(
            rules,
            "SCOPE-US",
            Status.BLOCKED,
            f"Jurisdiction '{project.code_basis.jurisdiction}' is outside this workbench. US projects only.",
            project.code_basis.jurisdiction,
        )
    else:
        scope = _check(rules, "SCOPE-US", Status.PASS, "Jurisdiction is the United States.", "US")
    drifted = []
    for key, expected in rules.editions.items():
        actual = getattr(project.code_basis, key, None)
        if actual is None:
            continue
        if str(actual).strip() != str(expected).strip():
            drifted.append(f"{key} is {actual} (rules file expects {expected})")
    if project.ruleset_version and project.ruleset_version != rules.version:
        drifted.append(f"project ruleset {project.ruleset_version} vs file {rules.version}")
    if drifted:
        edition = _check(
            rules,
            "CODE-EDITION",
            Status.WARN,
            "Edition or ruleset drift: " + "; ".join(drifted) + ". The engine still uses the numbers in the rules file.",
            rules.version,
            extra_tags=["NEEDS PE REVIEW"],
        )
    else:
        edition = _check(
            rules,
            "CODE-EDITION",
            Status.PASS,
            "Recorded editions match the rules file "
            + ", ".join(f"{key} {value}" for key, value in rules.editions.items())
            + f". Ruleset {rules.ruleset_id} {rules.version}. NEC is recorded only; this workbook does not size conductors.",
            rules.version,
        )
    return [scope, edition]


def _door_check(rules: Ruleset) -> CheckResult:
    return _check(
        rules,
        "FA-DOOR",
        Status.WARN,
        "Confirm door and frame ratings match the barrier (2 h door in a 2 h wall, 3 h door in a 3 h wall) and that hold-open devices release on a fire-alarm signal.",
        "open coordination item",
    )


def _lead_rfis(project: Project, rules: Ruleset, checks: list[CheckResult]) -> list[AutoRFI]:
    by_id = {item.id: item for item in checks}
    specs: list[AutoRFI] = []

    def add(rule_id: str, key: str, text: str, assignee: str) -> None:
        meta = rules.rule(rule_id)
        specs.append(AutoRFI(key=key, rule_id=rule_id, title=meta.title, text=text, assignee=assignee, screen=meta.screen))

    missing = [group for group in project.ess_groups if group.kwh > 0 and not group.ul_9540a_report]
    if missing and by_id["FP-9540A-RFI"].status != Status.PASS:
        names = ", ".join(group.name for group in missing)
        add(
            "FP-9540A-RFI",
            "lead:9540a",
            f"Provide the UL 9540A report for {names}. Sprinkler density cannot be reduced without it, and groups above the workbench cutoff block sprinkler sign-off.",
            "Owner",
        )
    if project.gas.monitoring_only or project.gas.bacnet_only or project.gas.add_alternate:
        bits = []
        if project.gas.monitoring_only:
            bits.append("monitoring-only")
        if project.gas.bacnet_only:
            bits.append("BACnet-only")
        if project.gas.add_alternate:
            bits.append("an add-alternate")
        add(
            "FA-HARD-MON",
            "lead:monitoring",
            "Gas detection is marked as " + " and ".join(bits) + ". Confirm it is base-scope, hardwired explosion control and not a monitoring-only or add-alternate system.",
            "Controls vendor",
        )
    if not project.gas.relay_landings_shown:
        add(
            "FP-LAND-RFI",
            "lead:landings",
            "Show relay landings for R1 (exhaust and makeup), R2 (gas alarm to the FACP), R3 (gas horns and strobes), and the fault relay (trouble to the FACP).",
            "Controls vendor",
        )
    if not project.gas.high_gas_to_facp:
        add(
            "FP-HIGH-RFI",
            "lead:highgas",
            "Provide a high-gas signal to the FACP. Local horns and strobes do not replace that signal.",
            "Elec",
        )
    if by_id["FP-LFL-SINGLE"].status != Status.PASS:
        add(
            "FP-LFL-SINGLE",
            "lead:singlegas",
            by_id["FP-LFL-SINGLE"].message + " Provide UL 9540A gas species and volumes, or a mixture setpoint a PE will accept.",
            "Controls vendor",
        )
    for sensor in project.gas.sensors:
        if sensor.height_justified:
            continue
        add(
            "FA-HEIGHT-OPEN",
            f"lead:height:{sensor.id}",
            f"Justify the mounting height of {sensor.gas} sensor {sensor.id} in {sensor.room_id} from the UL 9540A gas data and the airflow with exhaust on and with exhaust failed.",
            "Controls vendor",
        )
    add(
        "FA-DOOR",
        "lead:door",
        by_id["FA-DOOR"].message,
        "Architect",
    )
    return specs


_SCREEN_ASSIGNEE = {
    "project": "AHJ",
    "rooms": "Owner",
    "thresholds": "Owner",
    "explosion": "Mech",
    "gas": "Controls vendor",
    "cause_effect": "Controls vendor",
    "sprinklers": "Owner",
    "battery": "Elec",
    "rfi": "Architect",
    "reports": "Owner",
}


def _auto_rfis(project: Project, rules: Ruleset, checks: list[CheckResult]) -> list[AutoRFI]:
    specs = _lead_rfis(project, rules, checks)
    covered = {item.rule_id for item in specs}
    for check in checks:
        if check.status == Status.PASS or check.rule_id in covered:
            continue
        specs.append(
            AutoRFI(
                key=f"check:{check.id}",
                rule_id=check.rule_id,
                title=check.title,
                text=f"{check.status.value}: {check.message}",
                assignee=_SCREEN_ASSIGNEE.get(check.screen, "Owner"),
                screen=check.screen,
            )
        )
    return specs


def analyze(project: Project, rules: Ruleset) -> Analysis:
    checks: list[CheckResult] = []
    checks.extend(_project_checks(project, rules))
    checks.extend(_room_checks(project, rules))
    rollups, rollup_checks = _rollups(project, rules)
    checks.extend(_threshold_checks(project, rules))
    checks.extend(rollup_checks)
    checks.extend(_explosion_checks(project, rules))
    checks.extend(_gas_checks(project, rules))
    checks.extend(_ce_checks(project, rules))
    checks.extend(_sprinkler_checks(project, rules))
    checks.extend(_battery_checks(project, rules))
    checks.append(_door_check(rules))

    rows, summary = sprinkler_rows(project, rules)
    points, required, on_panel, on_facp = build_points(project)
    facp, gas = battery_pair(project, rules)
    screen_status = {screen: worst_status([item.status for item in checks if item.screen == screen]).value for screen in SCREENS}
    return Analysis(
        checks=checks,
        rollups=rollups,
        sprinkler_rows=rows,
        sprinkler_summary=summary,
        duct=duct_sprinkler(project),
        points=points,
        proof_required=required,
        proof_on_panel=on_panel,
        proof_on_facp=on_facp,
        battery_facp=facp,
        battery_gas=gas,
        mass_balance=mass_balance(project, rules),
        auto_rfis=_auto_rfis(project, rules, checks),
        screen_status=screen_status,
    )


def ensure_fire_areas(project: Project) -> None:
    known = {area.id for area in project.fire_areas}
    for room in project.rooms:
        if room.fire_area_id and room.fire_area_id not in known:
            project.fire_areas.append(
                FireArea(
                    id=room.fire_area_id,
                    name=room.fire_area_id,
                    barrier_hr=room.wall_rating_hr,
                    floor_ceiling_hr=min(room.floor_rating_hr, room.ceiling_rating_hr),
                )
            )
            known.add(room.fire_area_id)


# Re-exported for callers that fingerprint outside the engine.
__all__ = ["CE_COLUMNS", "SCREENS", "analyze", "ensure_fire_areas", "fingerprint"]
