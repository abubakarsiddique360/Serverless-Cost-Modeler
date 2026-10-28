"""Cost model.

Two decisions worth stating out loud:

* The free tier is an account-level allowance, so it is removed from the account totals and
  then credited back to each function in proportion to its gross usage. Every line's
  ``total`` therefore adds up to the account total, and no function can look free by luck
  of being first in a file.
* Cold starts are billed as ordinary GB-seconds: a cold start is just extra duration at the
  configured memory size.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .inventory import FunctionUsage
from .pricing import PriceSheet


@dataclass(frozen=True)
class BillLine:
    function: str
    requests: int
    gb_seconds: float
    egress_gb: float
    request_cost: float
    compute_cost: float
    egress_cost: float
    free_tier_credit: float
    total: float
    share: float

    @property
    def cost_per_million_requests(self) -> float:
        if self.requests == 0:
            return 0.0
        return round(self.total / self.requests * 1_000_000, 6)


@dataclass(frozen=True)
class Bill:
    currency: str
    lines: tuple[BillLine, ...]
    total_requests: int
    total_gb_seconds: float
    total_egress_gb: float
    billable_requests: float
    billable_gb_seconds: float
    billable_egress_gb: float
    subtotal: float
    free_tier_credit: float
    minimum_adjustment: float
    total: float
    free_tier_applied: bool
    sheet: PriceSheet = field(repr=False, default_factory=PriceSheet)

    @property
    def biggest_driver(self) -> BillLine | None:
        return max(self.lines, key=lambda line: line.total, default=None)

    @property
    def effective_cost_per_million_requests(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return round(self.total / self.total_requests * 1_000_000, 6)


def build_bill(
    usages: list[FunctionUsage], sheet: PriceSheet, *, apply_free_tier: bool = True
) -> Bill:
    if not usages:
        raise ValueError("cannot build a bill without usage rows")

    total_requests = sum(item.requests for item in usages)
    total_gb_seconds = round(sum(item.gb_seconds for item in usages), 6)
    total_egress = round(sum(item.egress_gb for item in usages), 6)

    if apply_free_tier:
        billable_requests = max(0.0, total_requests - sheet.free_requests_per_month)
        billable_gb_seconds = max(0.0, total_gb_seconds - sheet.free_gb_seconds_per_month)
        billable_egress = max(0.0, total_egress - sheet.free_egress_gb_per_month)
    else:
        billable_requests = float(total_requests)
        billable_gb_seconds = total_gb_seconds
        billable_egress = total_egress

    request_factor = billable_requests / total_requests if total_requests else 0.0
    compute_factor = billable_gb_seconds / total_gb_seconds if total_gb_seconds else 0.0
    egress_factor = billable_egress / total_egress if total_egress else 0.0

    raw_lines: list[dict] = []
    for item in usages:
        gross_request = item.requests / 1_000_000 * sheet.request_price_per_million
        gross_compute = item.gb_seconds * sheet.gb_second_price
        gross_egress = item.egress_gb * sheet.egress_price_per_gb
        request_cost = gross_request * request_factor
        compute_cost = gross_compute * compute_factor
        egress_cost = gross_egress * egress_factor
        raw_lines.append(
            {
                "function": item.function,
                "requests": item.requests,
                "gb_seconds": item.gb_seconds,
                "egress_gb": item.egress_gb,
                "request_cost": request_cost,
                "compute_cost": compute_cost,
                "egress_cost": egress_cost,
                "gross": gross_request + gross_compute + gross_egress,
                "total": request_cost + compute_cost + egress_cost,
            }
        )

    subtotal = round(sum(line["total"] for line in raw_lines), 6)
    minimum_adjustment = round(max(0.0, sheet.minimum_monthly_charge - subtotal), 6)
    total = round(subtotal + minimum_adjustment, 6)
    free_credit = round(sum(line["gross"] - line["total"] for line in raw_lines), 6)

    lines = tuple(
        BillLine(
            function=line["function"],
            requests=line["requests"],
            gb_seconds=round(line["gb_seconds"], 6),
            egress_gb=round(line["egress_gb"], 6),
            request_cost=round(line["request_cost"], 6),
            compute_cost=round(line["compute_cost"], 6),
            egress_cost=round(line["egress_cost"], 6),
            free_tier_credit=round(line["gross"] - line["total"], 6),
            total=round(line["total"], 6),
            share=round(line["total"] / total * 100, 2) if total else 0.0,
        )
        for line in raw_lines
    )
    lines = tuple(sorted(lines, key=lambda line: line.total, reverse=True))

    return Bill(
        currency=sheet.currency,
        lines=lines,
        total_requests=total_requests,
        total_gb_seconds=total_gb_seconds,
        total_egress_gb=total_egress,
        billable_requests=round(billable_requests, 6),
        billable_gb_seconds=round(billable_gb_seconds, 6),
        billable_egress_gb=round(billable_egress, 6),
        subtotal=subtotal,
        free_tier_credit=free_credit,
        minimum_adjustment=minimum_adjustment,
        total=total,
        free_tier_applied=apply_free_tier,
        sheet=sheet,
    )
