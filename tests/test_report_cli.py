import json

import pytest

from serverless_cost_modeler.cli import main
from serverless_cost_modeler.inventory import FunctionUsage
from serverless_cost_modeler.model import build_bill
from serverless_cost_modeler.pricing import default_sheet
from serverless_cost_modeler.report import (
    money,
    render_comparison_markdown,
    render_comparison_text,
    render_json,
    render_markdown,
    render_sensitivity_markdown,
    render_text,
)
from serverless_cost_modeler.scenario import Scenario, compare

USAGE = """function,requests,avg_duration_ms,memory_mb,cold_starts,avg_cold_start_ms,egress_gb
api-orders,4000000,142,512,920,2100,64
image-thumbnail,900000,640,1024,120,3200,420
"""


@pytest.fixture()
def usage_file(tmp_path):
    path = tmp_path / "usage.csv"
    path.write_text(USAGE, encoding="utf-8")
    return path


@pytest.fixture()
def bill():
    usages = [
        FunctionUsage("api-orders", 4_000_000, 142.0, 512, 920, 2100.0, 64.0),
        FunctionUsage("image-thumbnail", 900_000, 640.0, 1024, 120, 3200.0, 420.0),
    ]
    return build_bill(usages, default_sheet())


def test_money_formats_known_and_unknown_currencies():
    assert money(1234.5) == "$1,234.50"
    assert money(1234.5, "JPY") == "1,234.50 JPY"


def test_text_report_has_totals_and_driver(bill):
    text = render_text(bill)
    assert "TOTAL" in text
    assert "Biggest driver" in text
    assert "Free tier credit" in text


def test_markdown_report_has_all_lines(bill):
    markdown = render_markdown(bill)
    assert markdown.count("|") > 10
    assert "`api-orders`" in markdown
    assert "Effective cost per million requests" in markdown


def test_json_report_round_trips(bill):
    payload = json.loads(render_json(bill))
    assert payload["total"] == pytest.approx(bill.total)
    assert payload["lines"][0]["function"] == bill.lines[0].function
    assert payload["sheet"]["currency"] == "USD"


def test_comparison_renderers(bill):
    comparison = compare(
        [FunctionUsage("api-orders", 4_000_000, 142.0, 512)], default_sheet(),
        Scenario.from_dict({"name": "peak", "requests_multiplier": 2}),
    )
    text = render_comparison_text(comparison)
    assert "Baseline" in text and "Scenario" in text
    assert f"{comparison.delta_percent:+.2f}%" in text
    markdown = render_comparison_markdown(comparison)
    assert "### Scenario: peak" in markdown


def test_sensitivity_markdown():
    points = [
        {"multiplier": 0.5, "requests": 1000, "total": 1.0, "cost_per_million": 1000.0}
    ]
    assert "x0.50" in render_sensitivity_markdown(points)


def test_cli_estimate_text(usage_file, capsys):
    assert main(["estimate", "--usage", str(usage_file)]) == 0
    assert "TOTAL" in capsys.readouterr().out


def test_cli_estimate_json(usage_file, capsys):
    assert main(["estimate", "--usage", str(usage_file), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] > 0


def test_cli_validate(usage_file, capsys):
    assert main(["validate", "--usage", str(usage_file)]) == 0
    assert "usage ok" in capsys.readouterr().out


def test_cli_validate_missing_file(tmp_path, capsys):
    assert main(["validate", "--usage", str(tmp_path / "no.csv")]) == 1
    assert "input error" in capsys.readouterr().err


def test_cli_sheet_prints_defaults(capsys):
    assert main(["sheet"]) == 0
    assert json.loads(capsys.readouterr().out)["currency"] == "USD"


def test_cli_compare(usage_file, tmp_path, capsys):
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps({"name": "peak", "requests_multiplier": 2}),
                        encoding="utf-8")
    assert main(["compare", "--usage", str(usage_file), "--scenario", str(scenario)]) == 0
    assert "Scenario: peak" in capsys.readouterr().out


def test_cli_compare_bad_scenario(usage_file, tmp_path, capsys):
    scenario = tmp_path / "scenario.json"
    scenario.write_text("{}", encoding="utf-8")
    assert main(["compare", "--usage", str(usage_file), "--scenario", str(scenario)]) == 0
    scenario.write_text(json.dumps({"requests_multiplier": 0}), encoding="utf-8")
    assert main(["compare", "--usage", str(usage_file), "--scenario", str(scenario)]) == 1
    assert "scenario error" in capsys.readouterr().err


def test_cli_sensitivity_marks_up(usage_file, capsys):
    assert main(["sensitivity", "--usage", str(usage_file), "--steps", "3"]) == 0
    assert "Cost sensitivity" in capsys.readouterr().out


def test_cli_sensitivity_json(usage_file, capsys):
    assert main(["sensitivity", "--usage", str(usage_file), "--steps", "4",
                 "--format", "json"]) == 0
    points = json.loads(capsys.readouterr().out)
    assert len(points) == 4
    assert points[0]["requests"] < points[-1]["requests"]


def test_cli_sensitivity_rejects_bad_steps(usage_file, capsys):
    assert main(["sensitivity", "--usage", str(usage_file), "--steps", "1"]) == 2
    assert "--steps" in capsys.readouterr().err
