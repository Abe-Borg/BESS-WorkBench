import json
from pathlib import Path

import pytest

from bess_workbench.analysis import Status
from bess_workbench.calcs import duct_sprinkler, mass_balance, sprinkler_rows
from bess_workbench.controller import ProjectController, load_project
from bess_workbench.engine import analyze
from bess_workbench.models import ESSGroup, FireArea, Project, ReleaseSpecies, Room
from bess_workbench.paths import sample_file
from bess_workbench.ruleset import load_rules
from bess_workbench.sample_data import build_new_project, build_sample_project

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def rules():
    return load_rules()


def _sample(rules):
    return ProjectController(build_sample_project(rules), rules)


def test_rules_file_is_the_number_source(rules, tmp_path):
    raw = json.loads((ROOT / "rules" / "ifc2024_nfpa855_2023.json").read_text(encoding="utf-8"))
    raw["parameters"]["max_kwh_fire_area"]["value"] = 100
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    edited = load_rules(path)
    project = build_sample_project(edited)
    result = analyze(project, edited)
    assert result.check("FP-FA-600").status == Status.FAIL


def test_catalog_ids_are_used_and_one_line():
    text = (ROOT / "bess_workbench" / "engine.py").read_text(encoding="utf-8")
    rules = load_rules()
    ids = [rule.id for rule in rules.rules]
    assert len(ids) == len(set(ids))
    missing = [rule_id for rule_id in ids if rule_id not in text]
    assert missing == []
    for rule in rules.rules:
        assert "\n" not in rule.summary
        assert len(rule.summary) <= 320
        assert rule.citation
        assert rule.edition
    blob = (ROOT / "rules" / "ifc2024_nfpa855_2023.json").read_text(encoding="utf-8").lower()
    assert "reproduced with permission" not in blob
    assert "all rights reserved" not in blob


def test_sample_story(rules):
    controller = _sample(rules)
    analysis = controller.analysis
    assert analysis.check("FP-FA-600").status == Status.WARN
    assert analysis.check("FP-FA-600").value == "600 kWh"
    assert "ASSUMED" in analysis.check("FP-FA-600").tags
    assert analysis.check("FP-FA-SEP").status == Status.PASS
    assert analysis.check("FA-HARD-MON").status == Status.FAIL
    assert analysis.check("FP-SPR-9540A").status == Status.BLOCKED
    assert analysis.check("FA-HARD-NAC").status == Status.PASS
    assert analysis.proof_required == 6
    assert analysis.proof_on_panel == 4
    assert analysis.proof_on_facp == 2
    assert analysis.screen_status["sprinklers"] == "BLOCKED"
    assert analysis.screen_status["gas"] == "FAIL"
    assert analysis.battery_facp.next_standard_ah == 26
    assert analysis.battery_gas.next_standard_ah == 18
    joined = " ".join(item.text for item in controller.project.rfis)
    for phrase in ("9540A", "monitoring-only", "add-alternate", "landing", "high-gas", "single-gas", "hold-open", "Justify"):
        assert phrase.lower() in joined.lower()
    assert controller.project.meta.synthetic is True
    assert "SYNTHETIC" in controller.project.meta.notes


def test_sample_file_matches_factory_and_is_stable(rules):
    built = _sample(rules).project
    on_disk = load_project(sample_file())
    assert on_disk.model_dump() == built.model_dump()
    again = ProjectController(Project.model_validate_json(built.model_dump_json()), rules)
    assert again.project.model_dump() == built.model_dump()


def test_fire_area_edges(rules):
    def project_with(areas):
        project = build_new_project(rules)
        project.rooms = []
        project.ess_groups = []
        project.fire_areas = []
        for index, (barrier, horizontal, kwh) in enumerate(areas, start=1):
            room_id = f"R{index}"
            project.rooms.append(Room(id=room_id, name=room_id, area_sf=400, height_ft=12, wall_rating_hr=barrier, floor_rating_hr=horizontal, ceiling_rating_hr=horizontal, fire_area_id=f"FA-{index}", smoke_detection=True))
            project.fire_areas.append(FireArea(id=f"FA-{index}", name=f"FA-{index}", barrier_hr=barrier, floor_ceiling_hr=horizontal))
            project.ess_groups.append(
                ESSGroup(
                    id=f"E{index}",
                    name=f"E{index}",
                    room_id=room_id,
                    chemistry="lithium-ion",
                    kwh=kwh,
                    spacing_in=36,
                    ul_9540_listed=True,
                    ul_9540a_report=True,
                )
            )
        return project

    at_cap = build_sample_project(rules)
    at_cap.ess_groups[0].kwh = 150
    assert analyze(at_cap, rules).check("FP-FA-600").status == Status.WARN

    over = build_sample_project(rules)
    over.ess_groups[0].kwh = 151
    assert analyze(over, rules).check("FP-FA-600").status == Status.FAIL

    under = build_sample_project(rules)
    for group in under.ess_groups:
        group.kwh = 100
    assert analyze(under, rules).check("FP-FA-600").status == Status.PASS

    band = build_sample_project(rules)
    for group in band.ess_groups:
        group.kwh = 0
    band.ess_groups[0].kwh = 570
    assert analyze(band, rules).check("FP-FA-600").status == Status.WARN
    band.ess_groups[0].kwh = 569
    assert analyze(band, rules).check("FP-FA-600").status == Status.PASS

    merged = project_with([(2, 2, 400), (2, 2, 400)])
    merged_result = analyze(merged, rules)
    assert merged_result.check("FP-FA-SEP").status == Status.FAIL
    assert merged_result.check("FP-FA-600").status == Status.FAIL
    assert any(item.fire_area_id == "COMBINED" and item.li_ion_kwh == 800 for item in merged_result.rollups)

    separate = project_with([(3, 3, 400), (3, 3, 400)])
    separate_result = analyze(separate, rules)
    assert separate_result.check("FP-FA-SEP").status == Status.PASS
    assert separate_result.check("FP-FA-600").status == Status.PASS


def test_sprinkler_math_and_blocks(rules):
    project = build_sample_project(rules)
    project.rooms = [Room(id="R1", name="R1", area_sf=1000, height_ft=12, wall_rating_hr=2, floor_rating_hr=2, ceiling_rating_hr=2, fire_area_id="FA-1", smoke_detection=True)]
    project.sprinklers.system_type = "dry"
    project.sprinklers.density_gpm_sf = 0.3
    rows, summary = sprinkler_rows(project, rules)
    assert rows[0].base_area_sf == 1000
    assert rows[0].increase_sf == pytest.approx(300)
    assert rows[0].design_area_sf == pytest.approx(1300)
    assert rows[0].sprinkler_gpm == pytest.approx(390)
    assert summary.area_factor == pytest.approx(1.3)

    project.sprinklers.system_type = "double_interlock_preaction"
    rows, _summary = sprinkler_rows(project, rules)
    assert rows[0].increase_sf == pytest.approx(300)

    blocked = build_sample_project(rules)
    assert analyze(blocked, rules).check("FP-SPR-9540A").status == Status.BLOCKED
    for group in blocked.ess_groups:
        group.ul_9540a_report = True
    assert analyze(blocked, rules).check("FP-SPR-9540A").status == Status.PASS

    low = build_sample_project(rules)
    low.sprinklers.density_gpm_sf = 0.2
    assert analyze(low, rules).check("FP-SPR-DESIGN").status == Status.FAIL

    foam = build_sample_project(rules)
    foam.sprinklers.system_type = "foam"
    assert analyze(foam, rules).check("FP-SPR-TYPE").status == Status.BLOCKED

    duct = build_sample_project(rules)
    assert analyze(duct, rules).check("FP-SPR-DUCT").status == Status.PASS
    duct.sprinklers.duct.pressure_psi = 6
    failed = analyze(duct, rules)
    assert failed.check("FP-SPR-DUCT").status == Status.FAIL
    assert duct_sprinkler(duct).flow_gpm == pytest.approx(5.6 * (6 ** 0.5))


def test_scope_room_and_gas_failures(rules):
    project = build_sample_project(rules)
    project.code_basis.jurisdiction = "UK"
    assert analyze(project, rules).check("SCOPE-US").status == Status.BLOCKED

    project = build_sample_project(rules)
    project.code_basis.ifc = "2021"
    edition = analyze(project, rules).check("CODE-EDITION")
    assert edition.status == Status.WARN
    assert "NEEDS PE REVIEW" in edition.tags

    project = build_sample_project(rules)
    project.rooms[0].wall_rating_hr = 1
    assert analyze(project, rules).check("FP-ROOM-2H").status == Status.FAIL

    project = build_sample_project(rules)
    project.ess_groups[0].ul_9540_listed = False
    assert analyze(project, rules).check("FP-UL9540").status == Status.FAIL

    project = build_sample_project(rules)
    project.ess_groups[0].chemistry = "lead-acid"
    other = analyze(project, rules).check("FP-CHEM-OTHER")
    assert other.status == Status.WARN
    assert "NEEDS PE REVIEW" in other.tags

    project = build_sample_project(rules)
    project.gas.gas_horns_on_fa_nacs = True
    assert analyze(project, rules).check("FA-HARD-NAC").status == Status.FAIL

    project = build_sample_project(rules)
    project.gas.distinct_notification = False
    assert analyze(project, rules).check("FA-DISTINCT").status == Status.FAIL

    project = build_sample_project(rules)
    project.exhaust.hvac_shutdown_includes_exhaust = True
    shutdown = ProjectController(project, rules).analysis
    assert shutdown.check("FA-NO-SHUTDOWN").status == Status.FAIL
    assert shutdown.check("CE-STOP").status == Status.FAIL

    project = build_sample_project(rules)
    project.exhaust.fire_damper = True
    project.exhaust.balancing_damper = True
    project.exhaust.backdraft_damper = True
    project.exhaust.rated_shaft = False
    dampers = analyze(project, rules)
    assert dampers.check("FP-IMC-FSD").status == Status.FAIL
    assert dampers.check("FP-IMC-BAL").status == Status.FAIL
    assert dampers.check("FP-IMC-BD").status == Status.FAIL
    assert dampers.check("FP-IMC-SHAFT").status == Status.FAIL
    assert dampers.check("FA-IMC-509").status == Status.FAIL

    project = build_sample_project(rules)
    project.exhaust.other_ducts_penetrate = True
    project.exhaust.other_duct_wall_hr = 3
    project.exhaust.other_duct_damper_hr = 1.5
    assert analyze(project, rules).check("FP-IMC-OTHER").status == Status.FAIL
    project.exhaust.other_duct_damper_hr = 3
    assert analyze(project, rules).check("FP-IMC-OTHER").status == Status.PASS

    project = build_sample_project(rules)
    project.gas.sensors[0].inches_from_ceiling = 24
    assert analyze(project, rules).check("FA-H2-CEILING").status == Status.WARN
    project.gas.sensors[1].mount = "high"
    assert analyze(project, rules).check("FA-DMC-LOW").status == Status.WARN

    project = build_sample_project(rules)
    for sensor in project.gas.sensors:
        sensor.height_justified = True
        sensor.justification = "9540A plume with exhaust on and failed"
    assert analyze(project, rules).check("FA-HEIGHT-OPEN").status == Status.PASS

    project = build_sample_project(rules)
    project.rooms[0].smoke_detection = False
    assert analyze(project, rules).check("FA-SMOKE").status == Status.FAIL

    project = build_sample_project(rules)
    project.gas.alarm_pct_lfl = 15
    project.gas.design_pct_lfl = 30
    levels = analyze(project, rules)
    assert levels.check("FP-LFL-10").status == Status.FAIL
    assert levels.check("FP-LFL-25").status == Status.FAIL
    assert "NEEDS PE REVIEW" in levels.check("FP-LFL-10").tags
    assert "ASSUMED" in levels.check("FP-LFL-25").tags


def test_battery_margin_and_mass_balance(rules):
    project = build_sample_project(rules)
    project.battery.margin_fraction = 0.1
    project.battery.aging_derate = 0.5
    result = analyze(project, rules)
    assert result.check("FA-BATT-MARGIN").status == Status.FAIL
    assert result.battery_facp.margin_used == pytest.approx(0.2)
    assert result.battery_facp.aging_used == pytest.approx(1.0)

    project = build_sample_project(rules)
    project.gas.release_room_volume_ft3 = 10000
    project.gas.release_species = [ReleaseSpecies(name="H2", mass_g=10, molecular_weight=2.016, lfl_vol_pct=4.0)]
    balance = mass_balance(project, rules)
    moles = 10 / 2.016
    volume = moles * 0.853
    vol_pct = volume / 10000 * 100
    expected = vol_pct / 4.0 * 100
    assert balance.species[0].pct_of_lfl == pytest.approx(expected)
    assert balance.mixture_pct_of_lfl == pytest.approx(expected)

    project.gas.release_species.append(ReleaseSpecies(name="DMC", mass_g=90.08, molecular_weight=90.08, lfl_vol_pct=4.22))
    mixed = mass_balance(project, rules)
    v_h2 = (10 / 2.016) * 0.853
    v_dmc = (90.08 / 90.08) * 0.853
    total = v_h2 + v_dmc
    lfl = 1 / ((v_h2 / total) / 4.0 + (v_dmc / total) / 4.22)
    mixture = (total / 10000 * 100) / lfl * 100
    assert mixed.mixture_lfl_vol_pct == pytest.approx(lfl)
    assert mixed.mixture_pct_of_lfl == pytest.approx(mixture)
    assert analyze(project, rules).check("FA-SETPOINT-CONV").status == Status.WARN
    assert "NEEDS PE REVIEW" in analyze(project, rules).check("FA-SETPOINT-CONV").tags


def test_new_project_opens(rules):
    controller = ProjectController(build_new_project(rules), rules)
    assert controller.analysis.check("SCOPE-US").status == Status.PASS
    assert controller.project.gas.controller.relay_functions["R1"] == "exhaust_makeup_latched"
    assert controller.project.gas.controller.relay_functions["FAULT"] == "trouble_to_facp"
