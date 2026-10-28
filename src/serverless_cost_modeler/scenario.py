"""What-if scenarios: scale traffic, memory, duration, egress or cold starts and re-price."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .inventory import FunctionUsage
from .model import Bill, BillLine, build_bill
from .pricing import PriceSheet


class ScenarioError(ValueError):
    """Raised when a scenario file cannot be used."""


FIELDS = (
    "requests_multiplier",
    "memory_multiplier",
    "duration_multiplier",
    "egress_multiplier",
    "cold_start_multiplier",
)


@dataclass(frozen=True)
class Scenario:
    name: str = "scenario"
    requests_multiplier: float = 1.0
    memory_multiplier: float = 1.0
    duration_multiplier: float = 1.0
    egress_multiplier: float = 1.0
    cold_start_multiplier: float = 1.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Scenario:
        if not isinstance(data, dict):
            raise ScenarioError("scenario must be a JSON object")
        unknown = sorted(set(data) - set(FIELDS) - {"name"})
        if unknown:
            raise ScenarioError(f"unknown scenario field(s): {', '.join(unknown)}")
        name = data.get("name", "scenario")
        if not isinstance(name, str) or not name.strip():
            raise ScenarioError("scenario name must be a non-empty string")
        values: dict[str, float] = {}
        for field_name in FIELDS:
            value = data.get(field_name, 1.0)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise ScenarioError(f"{field_name} must be a number greater than zero")
            values[field_name] = float(value)
        return cls(name=name.strip(), **values)

    @classmethod
    def load(cls, path: str | Path) -> Scenario:
        source = Path(path)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ScenarioError(f"scenario not found: {source}") from exc
        except json.JSONDecodeError as exc:
            raise ScenarioError(f"scenario is not valid JSON: {exc}") from exc
        return cls.from_dict(data)

    def describe(self) -> str:
        parts = [
            f"requests x{self.requests_multiplier:g}",
            f"memory x{self.memory_multiplier:g}",
            f"duration x{self.duration_multiplier:g}",
            f"egress x{self.egress_multiplier:g}",
            f"cold starts x{self.cold_start_multiplier:g}",
        ]
        return ", ".join(part for part in parts if not part.endswith("x1"))


@dataclass(frozen=True)
class Mover:
    function: str
    baseline: float
    scenario: float

    @property
    def delta(self) -> float:
        return round(self.scenario - self.baseline, 6)


@dataclass(frozen=True)
class Comparison:
    baseline: Bill
    scenario_bill: Bill
    scenario: Scenario
    movers: tuple[Mover, ...]

    @property
    def delta_total(self) -> float:
        return round(self.scenario_bill.total - self.baseline.total, 6)

    @property
    def delta_percent(self) -> float:
        if self.baseline.total == 0:
            return 0.0
        return round(self.delta_total / self.baseline.total * 100, 2)


def apply_scenario(usages: list[FunctionUsage], scenario: Scenario) -> list[FunctionUsage]:
    scaled: list[FunctionUsage] = []
    for item in usages:
        memory = max(128, round(item.memory_mb * scenario.memory_multiplier))
        scaled.append(
            FunctionUsage(
                function=item.function,
                requests=max(0, round(item.requests * scenario.requests_multiplier)),
                avg_duration_ms=item.avg_duration_ms * scenario.duration_multiplier,
                memory_mb=memory,
                cold_starts=max(
                    0,
                    min(
                        max(0, round(item.requests * scenario.requests_multiplier)),
                        round(item.cold_starts * scenario.cold_start_multiplier),
                    ),
                ),
                avg_cold_start_ms=item.avg_cold_start_ms,
                egress_gb=item.egress_gb * scenario.egress_multiplier,
            )
        )
    return scaled


def compare(
    usages: list[FunctionUsage],
    sheet: PriceSheet,
    scenario: Scenario,
    *,
    apply_free_tier: bool = True,
) -> Comparison:
    baseline = build_bill(usages, sheet, apply_free_tier=apply_free_tier)
    scenario_bill = build_bill(
        apply_scenario(usages, scenario), sheet, apply_free_tier=apply_free_tier
    )
    baseline_by_name: dict[str, BillLine] = {line.function: line for line in baseline.lines}
    scenario_by_name: dict[str, BillLine] = {
        line.function: line for line in scenario_bill.lines
    }
    movers = [
        Mover(
            function=name,
            baseline=baseline_by_name[name].total,
            scenario=scenario_by_name[name].total,
        )
        for name in baseline_by_name
    ]
    movers.sort(key=lambda mover: abs(mover.delta), reverse=True)
    return Comparison(
        baseline=baseline,
        scenario_bill=scenario_bill,
        scenario=scenario,
        movers=tuple(movers),
    )
