"""Command line entry point for ``serverless-cost``."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from . import __version__
from .inventory import UsageError, load_usage
from .model import build_bill
from .pricing import PriceSheet, PriceSheetError, default_sheet
from .report import (
    render_comparison_markdown,
    render_comparison_text,
    render_json,
    render_markdown,
    render_sensitivity_markdown,
    render_text,
)
from .scenario import Scenario, ScenarioError, apply_scenario, compare


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="serverless-cost",
        description="Estimate a serverless bill from an invocation CSV.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(command: argparse.ArgumentParser) -> None:
        command.add_argument("--usage", required=True, help="invocation CSV")
        command.add_argument("--prices", help="price sheet JSON (defaults are illustrative)")
        command.add_argument("--no-free-tier", action="store_true",
                             help="price every request and GB-second")

    estimate = sub.add_parser("estimate", help="itemise one month of usage")
    add_common(estimate)
    estimate.add_argument("--format", choices=("text", "markdown", "json"), default="text")

    scenario = sub.add_parser("compare", help="re-price usage under a what-if scenario")
    add_common(scenario)
    scenario.add_argument("--scenario", required=True, help="scenario JSON")
    scenario.add_argument("--format", choices=("text", "markdown", "json"), default="text")

    sensitivity = sub.add_parser("sensitivity", help="bill totals across request multipliers")
    add_common(sensitivity)
    sensitivity.add_argument("--steps", type=int, default=9)
    sensitivity.add_argument("--max-multiplier", type=float, default=2.0)
    sensitivity.add_argument("--format", choices=("text", "markdown", "json"), default="markdown")

    validate = sub.add_parser("validate", help="check the CSV and price sheet without pricing")
    add_common(validate)

    sub.add_parser("sheet", help="print the built-in price sheet")
    return parser


def _load(args) -> tuple[list, PriceSheet]:
    sheet = PriceSheet.load(args.prices) if args.prices else default_sheet()
    return load_usage(args.usage), sheet


def _sensitivity_points(
    usages, sheet: PriceSheet, steps: int, max_multiplier: float, apply_free_tier: bool
) -> list[dict]:
    if steps < 2:
        raise ValueError("--steps must be at least 2")
    if max_multiplier <= 0:
        raise ValueError("--max-multiplier must be positive")
    points: list[dict] = []
    for index in range(steps):
        multiplier = max_multiplier * index / (steps - 1)
        scenario = Scenario(name=f"x{multiplier:.2f}", requests_multiplier=max(multiplier, 0.001))
        bill = build_bill(
            apply_scenario(usages, scenario), sheet, apply_free_tier=apply_free_tier
        )
        points.append(
            {
                "multiplier": round(multiplier, 3),
                "requests": bill.total_requests,
                "total": bill.total,
                "cost_per_million": bill.effective_cost_per_million_requests,
            }
        )
    return points


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "sheet":
        payload = asdict(default_sheet())
        print(json.dumps(payload, indent=2))
        return 0

    try:
        usages, sheet = _load(args)
    except (UsageError, PriceSheetError) as exc:
        print(f"input error: {exc}", file=sys.stderr)
        return 1

    if args.command == "validate":
        print(f"usage ok: {len(usages)} function(s), {sum(u.requests for u in usages):,} requests")
        print(f"price sheet ok: {sheet.currency}, "
              f"{sheet.request_price_per_million}/M requests, "
              f"{sheet.gb_second_price}/GB-s")
        return 0

    apply_free_tier = not args.no_free_tier

    if args.command == "estimate":
        bill = build_bill(usages, sheet, apply_free_tier=apply_free_tier)
        if args.format == "json":
            print(render_json(bill))
        elif args.format == "markdown":
            print(render_markdown(bill))
        else:
            print(render_text(bill))
        return 0

    if args.command == "compare":
        try:
            scenario = Scenario.load(args.scenario)
        except ScenarioError as exc:
            print(f"scenario error: {exc}", file=sys.stderr)
            return 1
        comparison = compare(usages, sheet, scenario, apply_free_tier=apply_free_tier)
        if args.format == "json":
            print(
                json.dumps(
                    {
                        "scenario": asdict(comparison.scenario),
                        "baseline_total": comparison.baseline.total,
                        "scenario_total": comparison.scenario_bill.total,
                        "delta_total": comparison.delta_total,
                        "delta_percent": comparison.delta_percent,
                        "movers": [
                            {
                                "function": mover.function,
                                "baseline": mover.baseline,
                                "scenario": mover.scenario,
                                "delta": mover.delta,
                            }
                            for mover in comparison.movers
                        ],
                    },
                    indent=2,
                )
            )
        elif args.format == "markdown":
            print(render_comparison_markdown(comparison))
        else:
            print(render_comparison_text(comparison))
        return 0

    if args.command == "sensitivity":
        try:
            points = _sensitivity_points(
                usages, sheet, args.steps, args.max_multiplier, apply_free_tier
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if args.format == "json":
            print(json.dumps(points, indent=2))
        elif args.format == "markdown":
            print(render_sensitivity_markdown(points, sheet.currency))
        else:
            for point in points:
                print(
                    f"x{point['multiplier']:<5.2f} {point['requests']:>12,} requests "
                    f"{point['total']:>10,.2f} {sheet.currency}"
                )
        return 0

    return 2
