"""Regenerate the README assets from the example inventory.

Usage:  python scripts/render_assets.py
Writes: docs/estimate.json, docs/images/estimate-report.png,
        docs/images/cost-breakdown.svg, docs/images/growth-curve.svg
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from serverless_cost_modeler.cli import _sensitivity_points  # noqa: E402
from serverless_cost_modeler.inventory import load_usage  # noqa: E402
from serverless_cost_modeler.model import Bill, build_bill  # noqa: E402
from serverless_cost_modeler.pricing import PriceSheet  # noqa: E402
from serverless_cost_modeler.report import render_json, render_text  # noqa: E402
from serverless_cost_modeler.scenario import Scenario, compare  # noqa: E402

BG = "#0d1117"
CHROME = "#161b22"
FG = "#e6edf3"
MUTED = "#8b949e"
ACCENT = "#3fb950"


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("consola.ttf", "cour.ttf", "DejaVuSansMono.ttf"):
        candidate = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def render_terminal(text: str, out_path: Path, title: str) -> None:
    font = load_font(15)
    lines = text.expandtabs(4).splitlines() or [""]
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    char_width = probe.textlength("M", font=font)
    line_height = 22
    pad = 22
    width = int(max(len(line) for line in lines) * char_width) + pad * 2
    image = Image.new("RGB", (max(width, 700), pad * 2 + len(lines) * line_height + 44), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, image.width, 34], fill=CHROME)
    for index, color in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        draw.ellipse([16 + index * 22, 10, 28 + index * 22, 22], fill=color)
    draw.text((92, 9), title, font=load_font(13), fill=MUTED)

    for row, line in enumerate(lines):
        color = "#79c0ff" if row == 0 else FG
        if line.startswith("TOTAL"):
            color = ACCENT
        elif line.startswith("function"):
            color = MUTED
        elif "Biggest driver" in line:
            color = "#d29922"
        draw.text((pad, 50 + row * line_height), line, font=font, fill=color)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)


def render_breakdown(bill: Bill, out_path: Path) -> None:
    lines = list(reversed(bill.lines))
    names = [line.function for line in lines]
    requests_part = [line.request_cost for line in lines]
    compute_part = [line.compute_cost for line in lines]
    egress_part = [line.egress_cost for line in lines]

    fig, (ax_stack, ax_share) = plt.subplots(
        1, 2, figsize=(13.2, 4.8), gridspec_kw={"width_ratios": [1.15, 1]}
    )
    fig.patch.set_facecolor("#ffffff")

    ax_stack.barh(names, requests_part, color="#2f81f7", label="requests")
    ax_stack.barh(names, compute_part, left=requests_part, color="#3fb950",
                  label="GB-seconds")
    ax_stack.barh(names, egress_part,
                  left=[a + b for a, b in zip(requests_part, compute_part, strict=True)],
                  color="#d29922", label="egress")
    ax_stack.set_xlabel(f"monthly cost ({bill.currency})")
    ax_stack.set_title("Where the bill comes from", fontsize=11, loc="left")
    ax_stack.legend(fontsize=8, frameon=False, loc="lower right")
    ax_stack.grid(axis="x", linestyle=":", alpha=0.45)
    for spine in ("top", "right"):
        ax_stack.spines[spine].set_visible(False)

    ordered = sorted(bill.lines, key=lambda line: line.total, reverse=True)
    shares = [line.share for line in ordered]
    label_names = [line.function for line in ordered]
    colors = ["#2f81f7" if share < 25 else "#d29922" if share < 40 else "#f85149"
              for share in shares]
    ax_share.barh(list(reversed(label_names)), list(reversed(shares)), color=list(reversed(colors)))
    ax_share.set_xlabel("share of bill (%)")
    ax_share.set_title("Concentration: the two slowest functions are half the bill",
                       fontsize=11, loc="left")
    ax_share.grid(axis="x", linestyle=":", alpha=0.45)
    for spine in ("top", "right"):
        ax_share.spines[spine].set_visible(False)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, format=out_path.suffix.lstrip(".") or "svg", transparent=False)
    plt.close(fig)


def render_growth(usages, sheet: PriceSheet, out_path: Path) -> list[dict]:
    points = _sensitivity_points(usages, sheet, 13, 2.0, True)
    no_free = _sensitivity_points(usages, sheet, 13, 2.0, False)

    fig, ax = plt.subplots(figsize=(8.6, 4.3))
    fig.patch.set_facecolor("#ffffff")
    ax.plot([p["multiplier"] for p in points], [p["total"] for p in points],
            marker="o", markersize=3.5, color="#2f81f7", label="with free tier")
    ax.plot([p["multiplier"] for p in no_free], [p["total"] for p in no_free],
            marker="s", markersize=3.0, color="#d29922", linestyle="--",
            label="no free tier")
    ax.set_xlabel("request volume multiplier (1.0 = today)")
    ax.set_ylabel(f"monthly bill ({sheet.currency})")
    ax.set_title("Cost sensitivity to traffic growth", fontsize=11, loc="left")
    ax.grid(linestyle=":", alpha=0.45)
    ax.legend(fontsize=8, frameon=False)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, format=out_path.suffix.lstrip(".") or "svg", transparent=False)
    plt.close(fig)
    return points


def main() -> int:
    images = ROOT / "docs" / "images"
    images.mkdir(parents=True, exist_ok=True)
    usages = load_usage(ROOT / "examples" / "invocations.csv")
    sheet = PriceSheet.load(ROOT / "examples" / "price-sheet.json")
    bill = build_bill(usages, sheet)

    (ROOT / "docs" / "estimate.json").write_text(
        json.dumps(json.loads(render_json(bill)), indent=2), encoding="utf-8"
    )

    header = "serverless-cost estimate --usage examples/invocations.csv\n\n"
    render_terminal(header + render_text(bill), images / "estimate-report.png",
                    "serverless-cost estimate  -  itemised monthly bill")

    render_breakdown(bill, images / "cost-breakdown.svg")
    render_growth(usages, sheet, images / "growth-curve.svg")

    scenario = Scenario.load(ROOT / "examples" / "scenario.json")
    comparison = compare(usages, sheet, scenario)
    (ROOT / "docs" / "scenario.json").write_text(
        json.dumps(
            {
                "scenario": scenario.name,
                "baseline_total": comparison.baseline.total,
                "scenario_total": comparison.scenario_bill.total,
                "delta_total": comparison.delta_total,
                "delta_percent": comparison.delta_percent,
                "movers": [
                    {"function": mover.function, "baseline": mover.baseline,
                     "scenario": mover.scenario, "delta": mover.delta}
                    for mover in comparison.movers[:4]
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"total={bill.total:.2f} {bill.currency} driver={bill.biggest_driver.function} "
        f"scenario={comparison.scenario_bill.total:.2f} ({comparison.delta_percent:+.1f}%)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
