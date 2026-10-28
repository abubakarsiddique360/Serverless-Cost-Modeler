"""Report renderers. Money is rounded only at the edge, never inside the model."""

from __future__ import annotations

import json
from dataclasses import asdict

from .model import Bill
from .scenario import Comparison


def money(value: float, currency: str = "USD") -> str:
    symbol = {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3"}.get(currency, "")
    return f"{symbol}{value:,.2f}" if symbol else f"{value:,.2f} {currency}"


def _thousands(value: int) -> str:
    return f"{value:,}"


def render_text(bill: Bill, *, title: str = "Serverless monthly estimate") -> str:
    lines = [
        f"{title} ({bill.currency})",
        "=" * 64,
        f"{'function':<24}{'requests':>12}{'GB-s':>13}{'cost':>13}{'share':>7}",
    ]
    for line in bill.lines:
        lines.append(
            f"{line.function[:23]:<24}{_thousands(line.requests):>12}"
            f"{line.gb_seconds:>13,.0f}{money(line.total, bill.currency):>13}{line.share:>6.1f}%"
        )
    lines.append("-" * 64)
    lines.append(
        f"{'TOTAL':<24}{_thousands(bill.total_requests):>12}"
        f"{bill.total_gb_seconds:>13,.0f}{money(bill.total, bill.currency):>13}{'100.0%':>7}"
    )
    lines.append("")
    lines.append(f"Billable requests      {bill.billable_requests:,.0f}")
    lines.append(f"Billable GB-seconds    {bill.billable_gb_seconds:,.0f}")
    lines.append(f"Billable egress        {bill.billable_egress_gb:,.2f} GB")
    lines.append(f"Free tier credit       {money(bill.free_tier_credit, bill.currency)}")
    if bill.minimum_adjustment:
        lines.append(
            f"Minimum charge top-up  {money(bill.minimum_adjustment, bill.currency)}"
        )
    lines.append(
        "Effective cost / Mreq  "
        f"{money(bill.effective_cost_per_million_requests, bill.currency)}"
    )
    driver = bill.biggest_driver
    if driver is not None:
        lines.append(f"Biggest driver         {driver.function} ({driver.share:.1f}% of bill)")
    if not bill.free_tier_applied:
        lines.append("Free tier              not applied (--no-free-tier)")
    return "\n".join(lines)


def render_markdown(bill: Bill, *, title: str = "Serverless monthly estimate") -> str:
    lines = [f"### {title} ({bill.currency})", ""]
    lines.append(
        "| Function | Requests | GB-s | Request cost | Compute cost | Egress | Total | Share |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for line in bill.lines:
        lines.append(
            f"| `{line.function}` | {_thousands(line.requests)} | {line.gb_seconds:,.0f} | "
            f"{money(line.request_cost, bill.currency)} | "
            f"{money(line.compute_cost, bill.currency)} | "
            f"{money(line.egress_cost, bill.currency)} | {money(line.total, bill.currency)} | "
            f"{line.share:.1f}% |"
        )
    lines.append(
        f"| **Total** | **{_thousands(bill.total_requests)}** | "
        f"**{bill.total_gb_seconds:,.0f}** | | | | "
        f"**{money(bill.total, bill.currency)}** | **100.0%** |"
    )
    lines.append("")
    lines.append(
        f"- Free tier credit: {money(bill.free_tier_credit, bill.currency)} "
        f"({'applied' if bill.free_tier_applied else 'not applied'})"
    )
    lines.append(
        f"- Effective cost per million requests: "
        f"{money(bill.effective_cost_per_million_requests, bill.currency)}"
    )
    if bill.minimum_adjustment:
        lines.append(
            f"- Minimum monthly charge added: {money(bill.minimum_adjustment, bill.currency)}"
        )
    return "\n".join(lines)


def render_json(bill: Bill) -> str:
    payload = asdict(bill)
    payload.pop("sheet", None)
    payload["sheet"] = {
        "currency": bill.sheet.currency,
        "request_price_per_million": bill.sheet.request_price_per_million,
        "gb_second_price": bill.sheet.gb_second_price,
        "egress_price_per_gb": bill.sheet.egress_price_per_gb,
        "free_requests_per_month": bill.sheet.free_requests_per_month,
        "free_gb_seconds_per_month": bill.sheet.free_gb_seconds_per_month,
        "free_egress_gb_per_month": bill.sheet.free_egress_gb_per_month,
        "minimum_monthly_charge": bill.sheet.minimum_monthly_charge,
    }
    return json.dumps(payload, indent=2)


def render_comparison_text(comparison: Comparison) -> str:
    baseline = comparison.baseline
    scenario = comparison.scenario_bill
    lines = [
        f"Scenario: {comparison.scenario.name} ({comparison.scenario.describe() or 'no change'})",
        "=" * 72,
        f"Baseline   {money(baseline.total, baseline.currency):>12}   "
        f"{baseline.total_requests:,} requests",
        f"Scenario   {money(scenario.total, scenario.currency):>12}   "
        f"{scenario.total_requests:,} requests",
        f"Delta      {money(comparison.delta_total, baseline.currency):>12}   "
        f"{comparison.delta_percent:+.2f}%",
        "",
        f"{'function':<24}{'baseline':>12}{'scenario':>12}{'delta':>12}",
    ]
    for mover in comparison.movers:
        lines.append(
            f"{mover.function[:23]:<24}{money(mover.baseline, baseline.currency):>12}"
            f"{money(mover.scenario, baseline.currency):>12}"
            f"{money(mover.delta, baseline.currency):>12}"
        )
    return "\n".join(lines)


def render_comparison_markdown(comparison: Comparison) -> str:
    baseline = comparison.baseline
    scenario = comparison.scenario_bill
    lines = [
        f"### Scenario: {comparison.scenario.name}",
        "",
        f"_{comparison.scenario.describe() or 'no change'}_",
        "",
        "| Function | Baseline | Scenario | Delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for mover in comparison.movers:
        lines.append(
            f"| `{mover.function}` | {money(mover.baseline, baseline.currency)} | "
            f"{money(mover.scenario, baseline.currency)} | "
            f"{money(mover.delta, baseline.currency)} |"
        )
    lines.append(
        f"| **Total** | **{money(baseline.total, baseline.currency)}** | "
        f"**{money(scenario.total, scenario.currency)}** | "
        f"**{money(comparison.delta_total, baseline.currency)} "
        f"({comparison.delta_percent:+.2f}%)** |"
    )
    return "\n".join(lines)


def render_sensitivity_markdown(points: list[dict], currency: str = "USD") -> str:
    lines = [
        "### Cost sensitivity to request volume",
        "",
        "| Request multiplier | Requests | Bill total | Cost per million |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for point in points:
        lines.append(
            f"| x{point['multiplier']:.2f} | {point['requests']:,} | "
            f"{money(point['total'], currency)} | {money(point['cost_per_million'], currency)} |"
        )
    return "\n".join(lines)
