import json

import pytest

from serverless_cost_modeler.inventory import FunctionUsage
from serverless_cost_modeler.model import build_bill
from serverless_cost_modeler.pricing import PriceSheet, PriceSheetError, default_sheet


def sheet(**overrides) -> PriceSheet:
    base = dict(
        currency="USD",
        request_price_per_million=1.0,
        gb_second_price=0.00001,
        egress_price_per_gb=0.1,
        free_requests_per_month=0,
        free_gb_seconds_per_month=0,
        free_egress_gb_per_month=0.0,
        minimum_monthly_charge=0.0,
    )
    base.update(overrides)
    return PriceSheet(**base)


def test_single_function_cost_is_exact():
    usage = FunctionUsage("worker", 1_000_000, 1000.0, 1024, egress_gb=1000.0)
    bill = build_bill([usage], sheet())
    line = bill.lines[0]
    assert line.request_cost == pytest.approx(1.0)
    assert line.compute_cost == pytest.approx(10.0)
    assert line.egress_cost == pytest.approx(100.0)
    assert line.total == pytest.approx(111.0)
    assert bill.total == pytest.approx(111.0)
    assert bill.free_tier_credit == pytest.approx(0.0)


def test_free_tier_is_subtracted_from_totals():
    usage = FunctionUsage("worker", 1_000_000, 1000.0, 1024, egress_gb=1000.0)
    bill = build_bill([usage], sheet(free_requests_per_month=2_000_000,
                                     free_gb_seconds_per_month=400_000,
                                     free_egress_gb_per_month=100.0))
    assert bill.billable_requests == 0
    assert bill.billable_gb_seconds == pytest.approx(600_000)
    assert bill.billable_egress_gb == pytest.approx(900)
    assert bill.total == pytest.approx(6.0 + 90.0)
    assert bill.free_tier_credit == pytest.approx(1.0 + 4.0 + 10.0)


def test_all_free_usage_costs_nothing_and_shares_are_zero():
    usage = FunctionUsage("tiny", 1000, 100.0, 256)
    bill = build_bill([usage], default_sheet())
    assert bill.total == 0.0
    assert bill.lines[0].share == 0.0


def test_per_function_lines_sum_to_subtotal():
    usages = [
        FunctionUsage("a", 1_000_000, 200.0, 512, egress_gb=50),
        FunctionUsage("b", 3_000_000, 400.0, 1024, cold_starts=1000,
                      avg_cold_start_ms=1500.0, egress_gb=250),
    ]
    bill = build_bill(usages, default_sheet())
    assert sum(line.total for line in bill.lines) == pytest.approx(bill.subtotal, abs=1e-5)
    assert bill.total == pytest.approx(bill.subtotal)


def test_free_tier_allocation_is_proportional():
    usages = [
        FunctionUsage("small", 1_000_000, 100.0, 1024),
        FunctionUsage("large", 3_000_000, 100.0, 1024),
    ]
    bill = build_bill(usages, default_sheet())
    assert bill.billable_requests == pytest.approx(2_000_000)
    request_costs = {line.function: line.request_cost for line in bill.lines}
    assert request_costs["small"] == pytest.approx(0.2)
    assert request_costs["large"] == pytest.approx(0.6)


def test_no_free_tier_switch_prices_everything():
    usage = FunctionUsage("worker", 1_000_000, 1000.0, 1024)
    bill = build_bill([usage], sheet(free_requests_per_month=5_000_000,
                                     free_gb_seconds_per_month=5_000_000),
                      apply_free_tier=False)
    assert bill.billable_requests == 1_000_000
    assert bill.total == pytest.approx(11.0)
    assert bill.free_tier_applied is False


def test_minimum_charge_tops_up_a_small_bill():
    usage = FunctionUsage("tiny", 1000, 100.0, 256)
    bill = build_bill([usage], sheet(minimum_monthly_charge=5.0))
    assert 0 < bill.subtotal < 5.0
    assert bill.minimum_adjustment == pytest.approx(5.0 - bill.subtotal)
    assert bill.total == pytest.approx(5.0)


def test_biggest_driver_and_cost_per_million():
    usages = [
        FunctionUsage("cheap", 10_000_000, 10.0, 128),
        FunctionUsage("expensive", 1_000_000, 900.0, 2048),
    ]
    bill = build_bill(usages, sheet())
    assert bill.biggest_driver.function == "expensive"
    assert bill.effective_cost_per_million_requests == pytest.approx(
        bill.total / 11_000_000 * 1_000_000
    )


def test_lines_are_sorted_by_cost():
    usages = [
        FunctionUsage("cheap", 1_000_000, 10.0, 128),
        FunctionUsage("pricey", 1_000_000, 500.0, 2048),
    ]
    bill = build_bill(usages, sheet())
    assert [line.function for line in bill.lines] == ["pricey", "cheap"]


def test_empty_usage_is_refused():
    with pytest.raises(ValueError, match="without usage"):
        build_bill([], sheet())


def test_price_sheet_defaults_are_valid():
    assert default_sheet().problems() == []


def test_price_sheet_rejects_unknown_field(tmp_path):
    path = tmp_path / "sheet.json"
    path.write_text(json.dumps({"request_price_per_million": 1.0, "typo": 2}), encoding="utf-8")
    with pytest.raises(PriceSheetError, match="unknown price sheet field"):
        PriceSheet.load(path)


@pytest.mark.parametrize("field", ["gb_second_price", "free_requests_per_month"])
def test_price_sheet_rejects_negative_values(field):
    with pytest.raises(PriceSheetError):
        PriceSheet.from_dict({field: -1})


def test_price_sheet_rejects_bad_currency():
    with pytest.raises(PriceSheetError, match="three letter"):
        PriceSheet.from_dict({"currency": "dollars"})


def test_price_sheet_merges_defaults(tmp_path):
    path = tmp_path / "sheet.json"
    path.write_text(json.dumps({"currency": "EUR"}), encoding="utf-8")
    loaded = PriceSheet.load(path)
    assert loaded.currency == "EUR"
    assert loaded.request_price_per_million == default_sheet().request_price_per_million
