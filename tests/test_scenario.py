import json

import pytest

from serverless_cost_modeler.inventory import FunctionUsage
from serverless_cost_modeler.model import build_bill
from serverless_cost_modeler.pricing import PriceSheet
from serverless_cost_modeler.scenario import (
    Scenario,
    ScenarioError,
    apply_scenario,
    compare,
)


def sheet() -> PriceSheet:
    return PriceSheet(request_price_per_million=1.0, gb_second_price=0.00001,
                      egress_price_per_gb=0.1, free_requests_per_month=0,
                      free_gb_seconds_per_month=0, free_egress_gb_per_month=0.0)


def usages():
    return [
        FunctionUsage("a", 1_000_000, 100.0, 512, cold_starts=100,
                      avg_cold_start_ms=1000.0, egress_gb=10),
        FunctionUsage("b", 2_000_000, 300.0, 1024, egress_gb=40),
    ]


def test_scenario_defaults_change_nothing():
    scenario = Scenario.from_dict({})
    scaled = apply_scenario(usages(), scenario)
    assert scaled[0].requests == 1_000_000
    assert scaled[0].memory_mb == 512
    assert scaled[0].gb_seconds == pytest.approx(usages()[0].gb_seconds)


def test_scenario_scales_every_input():
    scenario = Scenario.from_dict(
        {
            "requests_multiplier": 2,
            "memory_multiplier": 2,
            "duration_multiplier": 2,
            "egress_multiplier": 2,
            "cold_start_multiplier": 2,
        }
    )
    scaled = apply_scenario(usages(), scenario)[0]
    assert scaled.requests == 2_000_000
    assert scaled.memory_mb == 1024
    assert scaled.avg_duration_ms == 200.0
    assert scaled.cold_starts == 200
    assert scaled.egress_gb == 20


def test_memory_never_drops_below_128_mb():
    scenario = Scenario.from_dict({"memory_multiplier": 0.01})
    assert apply_scenario(usages(), scenario)[0].memory_mb == 128


def test_unknown_scenario_field_is_rejected():
    with pytest.raises(ScenarioError, match="unknown scenario field"):
        Scenario.from_dict({"requests_multipler": 2})


@pytest.mark.parametrize("value", [0, -1, "two", True])
def test_multipliers_must_be_positive_numbers(value):
    with pytest.raises(ScenarioError, match="greater than zero"):
        Scenario.from_dict({"requests_multiplier": value})


def test_scenario_name_is_required_when_present():
    with pytest.raises(ScenarioError, match="name"):
        Scenario.from_dict({"name": "  "})


def test_describe_lists_only_active_multipliers():
    scenario = Scenario.from_dict({"requests_multiplier": 2, "duration_multiplier": 0.5})
    description = scenario.describe()
    assert "requests x2" in description
    assert "duration x0.5" in description
    assert "memory" not in description


def test_compare_reports_delta_and_movers():
    comparison = compare(usages(), sheet(), Scenario.from_dict({"requests_multiplier": 2}))
    assert comparison.baseline.total < comparison.scenario_bill.total
    assert comparison.delta_total == pytest.approx(
        comparison.scenario_bill.total - comparison.baseline.total
    )
    assert comparison.delta_percent == pytest.approx(
        comparison.delta_total / comparison.baseline.total * 100, abs=0.01
    )
    assert len(comparison.movers) == 2
    assert abs(comparison.movers[0].delta) >= abs(comparison.movers[1].delta)


def test_compare_with_no_change_is_zero():
    comparison = compare(usages(), sheet(), Scenario())
    assert comparison.delta_total == pytest.approx(0.0)
    assert comparison.delta_percent == 0.0


def test_scenario_load(tmp_path):
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps({"name": "peak", "requests_multiplier": 3}), encoding="utf-8")
    assert Scenario.load(path).requests_multiplier == 3


def test_scenario_missing_file(tmp_path):
    with pytest.raises(ScenarioError, match="not found"):
        Scenario.load(tmp_path / "absent.json")


def test_scenario_broken_json(tmp_path):
    path = tmp_path / "scenario.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ScenarioError, match="not valid JSON"):
        Scenario.load(path)


def test_cold_starts_cannot_exceed_scaled_requests():
    scenario = Scenario.from_dict({"requests_multiplier": 0.00001})
    scaled = apply_scenario(usages(), scenario)[0]
    assert scaled.requests == 10
    assert scaled.cold_starts == 10


def test_comparison_uses_the_free_tier_flag():
    comparison = compare(usages(), sheet(), Scenario(), apply_free_tier=False)
    assert comparison.baseline.free_tier_applied is False
    assert comparison.baseline.total == pytest.approx(
        build_bill(usages(), sheet(), apply_free_tier=False).total
    )
