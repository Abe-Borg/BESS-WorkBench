"""Results produced by the rules engine. These are not stored in the project file."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from bess_workbench.models import Assignee


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    BLOCKED = "BLOCKED"
    INFO = "INFO"


SEVERITY = {
    Status.PASS: 0,
    Status.INFO: 1,
    Status.WARN: 2,
    Status.FAIL: 3,
    Status.BLOCKED: 4,
}


def worst_status(statuses: list[Status]) -> Status:
    if not statuses:
        return Status.INFO
    return max(statuses, key=lambda item: SEVERITY[item])


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    rule_id: str
    screen: str
    status: Status
    title: str
    message: str
    value: str
    citation: str
    edition: str
    tags: list[str] = Field(default_factory=list)


class Rollup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fire_area_id: str
    name: str
    room_ids: list[str]
    barrier_hr: float
    horizontal_hr: float
    separation_valid: bool
    li_ion_kwh: float
    other_kwh: float
    energy_checked: bool
    energy_status: Status
    note: str


class SprinklerRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room_id: str
    room_name: str
    room_area_sf: float
    base_area_sf: float
    increase_sf: float
    design_area_sf: float
    density_gpm_sf: float
    sprinkler_gpm: float
    governing: bool = False


class SprinklerSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_type: str
    area_factor: float
    governing_room_id: str = ""
    governing_sprinkler_gpm: float = 0
    hose_gpm: float = 0
    total_gpm: float = 0
    duration_min: float = 0
    volume_gal: float = 0
    c_factor: float = 100
    formula: str = ""


class DuctResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    k_factor: float
    pressure_psi: float
    flow_gpm: float | None
    formula: str


class IOPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    point_id: str
    description: str
    kind: str
    landing: str
    normal_state: str
    offnormal_state: str


class BatteryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    raw_ah: float
    margin_used: float
    aging_used: float
    temp_used: float
    required_ah: float
    next_standard_ah: float | None
    formula: str


class SpeciesRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    moles: float
    volume_ft3: float
    vol_pct: float
    lfl_vol_pct: float
    pct_of_lfl: float


class MassBalance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    species: list[SpeciesRelease]
    mixture_lfl_vol_pct: float
    mixture_vol_pct: float
    mixture_pct_of_lfl: float
    room_volume_ft3: float
    method: str


class AutoRFI(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    rule_id: str
    title: str
    text: str
    assignee: Assignee
    screen: str


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checks: list[CheckResult]
    rollups: list[Rollup]
    sprinkler_rows: list[SprinklerRow]
    sprinkler_summary: SprinklerSummary
    duct: DuctResult
    points: list[IOPoint]
    proof_required: int
    proof_on_panel: int
    proof_on_facp: int
    battery_facp: BatteryResult
    battery_gas: BatteryResult
    mass_balance: MassBalance | None
    auto_rfis: list[AutoRFI]
    screen_status: dict[str, str]

    def check(self, rule_id: str) -> CheckResult:
        for item in self.checks:
            if item.id == rule_id:
                return item
        raise KeyError(rule_id)
