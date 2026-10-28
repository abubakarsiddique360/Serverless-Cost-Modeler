import pytest

from serverless_cost_modeler.inventory import FunctionUsage, UsageError, load_usage


def write_csv(tmp_path, text):
    path = tmp_path / "usage.csv"
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


VALID = """function,requests,avg_duration_ms,memory_mb
api-orders,1000,142,512
api-catalog,2000,88,384
"""


def test_loads_required_columns_only(tmp_path):
    usages = load_usage(write_csv(tmp_path, VALID))
    assert [item.function for item in usages] == ["api-orders", "api-catalog"]
    assert usages[0].cold_starts == 0
    assert usages[0].egress_gb == 0.0


def test_missing_column_is_reported(tmp_path):
    path = write_csv(tmp_path, "function,requests\napi,10\n")
    with pytest.raises(UsageError, match="missing required column"):
        load_usage(path)


def test_missing_file(tmp_path):
    with pytest.raises(UsageError, match="not found"):
        load_usage(tmp_path / "nope.csv")


def test_empty_file(tmp_path):
    with pytest.raises(UsageError, match="empty"):
        load_usage(write_csv(tmp_path, ""))


def test_non_numeric_requests_is_reported_with_line_number(tmp_path):
    path = write_csv(
        tmp_path,
        "function,requests,avg_duration_ms,memory_mb\napi,not-a-number,10,256\n",
    )
    with pytest.raises(UsageError, match="line 2"):
        load_usage(path)


@pytest.mark.parametrize(
    "row,expected",
    [
        ("api,10,10,64", "memory_mb must be between 128 and 10240"),
        ("api,10,0,256", "avg_duration_ms must be positive"),
        ("api,10,abc,256", "avg_duration_ms must be a number"),
        ("api,10.5,10,256", "requests must be a whole number"),
        ("api,-1,10,256", "requests must not be negative"),
        ("api,10,10,256,20", "cold_starts cannot exceed requests"),
    ],
)
def test_row_validation(tmp_path, row, expected):
    header = "function,requests,avg_duration_ms,memory_mb,cold_starts\n"
    path = write_csv(tmp_path, header + row)
    with pytest.raises(UsageError, match=expected):
        load_usage(path)


def test_execution_limit_is_enforced(tmp_path):
    header = "function,requests,avg_duration_ms,memory_mb\n"
    path = write_csv(tmp_path, header + "slow,1,900001,256")
    with pytest.raises(UsageError, match="15 minute"):
        load_usage(path)


def test_duplicate_functions_are_rejected(tmp_path):
    path = write_csv(tmp_path, VALID + "api-orders,1,1,256\n")
    with pytest.raises(UsageError, match="duplicate function"):
        load_usage(path)


def test_blank_lines_are_skipped(tmp_path):
    path = write_csv(tmp_path, VALID + "\n\n")
    assert len(load_usage(path)) == 2


def test_gb_seconds_includes_cold_starts():
    usage = FunctionUsage("api", 1_000_000, 1000.0, 1024, cold_starts=10_000,
                          avg_cold_start_ms=2000.0)
    assert usage.warm_gb_seconds == 1_000_000.0
    assert usage.cold_start_gb_seconds == 20_000.0
    assert usage.gb_seconds == 1_020_000.0
