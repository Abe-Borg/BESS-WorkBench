"""Blank project and the synthetic four-room sample."""

from __future__ import annotations

from bess_workbench.models import (
    ESSGroup,
    Exhaust,
    FireArea,
    Gas,
    Project,
    ReleaseSpecies,
    Room,
    Sensor,
)
from bess_workbench.ruleset import Ruleset


def default_relay_functions(count: int = 4) -> dict[str, str]:
    functions = {
        "R1": "exhaust_makeup_latched",
        "R2": "gas_alarm_to_facp",
        "R3": "gas_horns_strobes",
    }
    for index in range(4, count + 1):
        functions[f"R{index}"] = "spare"
    functions["FAULT"] = "trouble_to_facp"
    return functions


def _sensors_for(room_id: str, justified: bool = False) -> list[Sensor]:
    return [
        Sensor(
            id=f"{room_id}-H2",
            room_id=room_id,
            gas="H2",
            mount="high",
            inches_from_ceiling=6,
            height_justified=justified,
        ),
        Sensor(
            id=f"{room_id}-DMC",
            room_id=room_id,
            gas="DMC",
            mount="low",
            inches_aff=18,
            height_justified=justified,
        ),
    ]


def _apply_ruleset(project: Project, rules: Ruleset) -> Project:
    project.ruleset_id = rules.ruleset_id
    project.ruleset_version = rules.version
    project.sprinklers.density_gpm_sf = float(rules.param("sprinkler_density_gpm_sf"))
    project.sprinklers.hose_gpm = float(rules.param("hose_allowance_gpm"))
    project.sprinklers.hose_duration_min = float(rules.param("hose_duration_min"))
    project.gas.alarm_pct_lfl = float(rules.param("alarm_lfl_pct_max"))
    project.gas.design_pct_lfl = float(rules.param("design_lfl_pct_limit"))
    project.gas.species = list(rules.param("default_gases"))
    project.battery.margin_fraction = float(rules.param("battery_margin_fraction"))
    project.battery.aging_derate = float(rules.param("default_aging_derate"))
    project.battery.temp_derate = float(rules.param("default_temp_derate"))
    project.gas.controller.relay_functions = default_relay_functions(project.gas.controller.programmable_relays)
    return project


def build_new_project(rules: Ruleset) -> Project:
    project = Project(
        meta={"name": "Untitled BESS project", "prepared_by": ""},
        rooms=[
            Room(id="ROOM-1", name="BESS Room 1", area_sf=400, height_ft=12, fire_area_id="FA-1"),
        ],
        ess_groups=[
            ESSGroup(id="ESS-1", name="ESS-1", room_id="ROOM-1", chemistry="lithium-ion", kwh=0),
        ],
        fire_areas=[FireArea(id="FA-1", name="Fire area 1", barrier_hr=2, floor_ceiling_hr=2)],
    )
    project.gas.sensors = _sensors_for("ROOM-1")
    project.sprinklers.duct.k_factor = 5.6
    project.sprinklers.duct.pressure_psi = 7
    return _apply_ruleset(project, rules)


def build_sample_project(rules: Ruleset) -> Project:
    rooms = []
    groups = []
    sensors: list[Sensor] = []
    for index in range(1, 5):
        room_id = f"UPS-{index}"
        rooms.append(
            Room(
                id=room_id,
                name=f"UPS BESS Room {index}",
                area_sf=800,
                height_ft=14,
                wall_rating_hr=2,
                floor_rating_hr=2,
                ceiling_rating_hr=2,
                fire_area_id="FA-1",
                smoke_detection=True,
            )
        )
        groups.append(
            ESSGroup(
                id=f"ESS-{index}",
                name=f"UPS string {index}",
                room_id=room_id,
                chemistry="lithium-ion",
                kwh=150,
                spacing_in=36,
                ul_9540_listed=True,
                ul_9540a_report=False,
            )
        )
        sensors.extend(_sensors_for(room_id, justified=False))
    project = Project(
        meta={
            "name": "Sample - 4 Room UPS BESS",
            "project_number": "SYN-DC-001",
            "client": "Synthetic Hyperscale (not a real owner)",
            "site": "Synthetic campus, United States",
            "prepared_by": "BESS WorkBench sample",
            "synthetic": True,
            "notes": (
                "SYNTHETIC teaching file, not a real facility. Intentional findings: the fire area is at the "
                "600 kWh cap (warn); gas detection is monitoring-only (hard fail) and an add-alternate; "
                "UL 9540A is missing (sprinkler sign-off blocked); relay landings are not shown; there is no "
                "high-gas signal to the FACP; setpoints are single-gas percent LEL; sensor heights are not "
                "justified; the gas panel has 4 inputs and 6 proof points, so 2 move to FACP monitor modules."
            ),
        },
        code_basis={
            "occupancy": "F-1",
            "jurisdiction": "US",
            "ahj_notes": "SYNTHETIC AHJ. No authority has reviewed this file.",
        },
        rooms=rooms,
        ess_groups=groups,
        fire_areas=[FireArea(id="FA-1", name="UPS BESS fire area", barrier_hr=2, floor_ceiling_hr=2)],
        exhaust=Exhaust(
            name="Shared gas exhaust",
            direct_to_exterior=False,
            crosses_rated_assembly=True,
            rated_shaft=True,
            fire_damper=False,
            smoke_damper=False,
            balancing_damper=False,
            backdraft_damper=False,
            motorized_damper=True,
            motorized_fail_open=True,
            damper_proven_open=True,
            per_room_isolation_damper=True,
            fan_proof=True,
            makeup_proof=True,
            standby_power_provided=True,
            hvac_shutdown_includes_exhaust=False,
            other_ducts_penetrate=False,
            other_duct_wall_hr=2,
            other_duct_damper_hr=1.5,
        ),
    )
    project.gas = Gas(
        species=["H2", "DMC"],
        species_source="assumed_default",
        has_9540a_gas_data=False,
        setpoint_basis="single_gas_lel",
        monitoring_only=True,
        add_alternate=True,
        bacnet_only=False,
        is_explosion_control=True,
        gas_horns_on_fa_nacs=False,
        distinct_notification=True,
        high_gas_to_facp=False,
        relay_landings_shown=False,
        supervising_station=True,
        low_alarm_starts_exhaust=True,
        low_alarm_starts_makeup=True,
        latched=True,
        manual_reset=True,
        sensors=sensors,
        release_species=[],
        release_room_volume_ft3=None,
        release_room_id="UPS-1",
    )
    project.gas.controller.programmable_relays = 4
    project.gas.controller.has_fault_relay = True
    project.gas.controller.dry_contact_inputs = 4
    project.sprinklers.system_type = "wet"
    project.sprinklers.duct.k_factor = 5.6
    project.sprinklers.duct.pressure_psi = 7
    return _apply_ruleset(project, rules)


def blank_release(name: str) -> ReleaseSpecies:
    return ReleaseSpecies(name=name, mass_g=0)
