"""Read the invocation CSV and reject the rows that would silently corrupt a bill."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

REQUIRED_COLUMNS = (
    "function",
    "requests",
    "avg_duration_ms",
    "memory_mb",
)
OPTIONAL_DEFAULTS = {
    "cold_starts": 0,
    "avg_cold_start_ms": 0.0,
    "egress_gb": 0.0,
}


class UsageError(ValueError):
    """Raised when the usage file cannot be read as an invocation inventory."""


@dataclass(frozen=True)
class FunctionUsage:
    function: str
    requests: int
    avg_duration_ms: float
    memory_mb: int
    cold_starts: int = 0
    avg_cold_start_ms: float = 0.0
    egress_gb: float = 0.0

    @property
    def gb_seconds(self) -> float:
        warm = self.requests * (self.avg_duration_ms / 1000.0) * (self.memory_mb / 1024.0)
        cold = self.cold_starts * (self.avg_cold_start_ms / 1000.0) * (self.memory_mb / 1024.0)
        return round(warm + cold, 6)

    @property
    def warm_gb_seconds(self) -> float:
        return round(
            self.requests * (self.avg_duration_ms / 1000.0) * (self.memory_mb / 1024.0), 6
        )

    @property
    def cold_start_gb_seconds(self) -> float:
        return round(
            self.cold_starts * (self.avg_cold_start_ms / 1000.0) * (self.memory_mb / 1024.0), 6
        )


def load_usage(path: str | Path) -> list[FunctionUsage]:
    source = Path(path)
    if not source.exists():
        raise UsageError(f"usage file not found: {source}")
    with source.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise UsageError("usage file is empty")
        header = [name.strip() for name in reader.fieldnames]
        missing = [name for name in REQUIRED_COLUMNS if name not in header]
        if missing:
            raise UsageError(f"missing required column(s): {', '.join(missing)}")
        reader.fieldnames = header
        records: list[FunctionUsage] = []
        errors: list[str] = []
        for line_number, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue
            try:
                records.append(_parse_row(row))
            except UsageError as exc:
                errors.append(f"line {line_number}: {exc}")
        if errors:
            raise UsageError("; ".join(errors))
    if not records:
        raise UsageError("usage file contains no functions")
    duplicates = _duplicates(record.function for record in records)
    if duplicates:
        raise UsageError(f"duplicate function name(s): {', '.join(sorted(duplicates))}")
    return records


def _parse_row(row: dict[str, str]) -> FunctionUsage:
    name = (row.get("function") or "").strip()
    if not name:
        raise UsageError("function name is empty")
    requests = _int(row.get("requests"), "requests")
    memory_mb = _int(row.get("memory_mb"), "memory_mb")
    if memory_mb < 128 or memory_mb > 10240:
        raise UsageError("memory_mb must be between 128 and 10240")
    duration = _float(row.get("avg_duration_ms"), "avg_duration_ms")
    if duration <= 0:
        raise UsageError("avg_duration_ms must be positive")
    if duration > 900_000:
        raise UsageError("avg_duration_ms exceeds the 15 minute execution limit")
    cold_starts = _int(_get(row, "cold_starts", 0), "cold_starts")
    if cold_starts > requests:
        raise UsageError("cold_starts cannot exceed requests")
    cold_ms = _float(_get(row, "avg_cold_start_ms", 0.0), "avg_cold_start_ms")
    if cold_ms < 0 or cold_ms > 60_000:
        raise UsageError("avg_cold_start_ms must be between 0 and 60000")
    egress = _float(_get(row, "egress_gb", 0.0), "egress_gb")
    if egress < 0:
        raise UsageError("egress_gb must not be negative")
    return FunctionUsage(
        function=name,
        requests=requests,
        avg_duration_ms=duration,
        memory_mb=memory_mb,
        cold_starts=cold_starts,
        avg_cold_start_ms=cold_ms,
        egress_gb=egress,
    )


def _get(row: dict[str, str], key: str, default):
    value = row.get(key)
    if value is None or str(value).strip() == "":
        return default
    return value


def _int(value, name: str) -> int:
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        raise UsageError(f"{name} must be a number, got {value!r}") from None
    if number < 0:
        raise UsageError(f"{name} must not be negative")
    if number != int(number):
        raise UsageError(f"{name} must be a whole number")
    return int(number)


def _float(value, name: str) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        raise UsageError(f"{name} must be a number, got {value!r}") from None


def _duplicates(values) -> set[str]:
    seen: set[str] = set()
    duplicated: set[str] = set()
    for value in values:
        if value in seen:
            duplicated.add(value)
        seen.add(value)
    return duplicated
