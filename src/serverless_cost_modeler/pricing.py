"""Price sheet: the only place where money numbers live.

The bundled default is an illustrative sheet shaped like a typical per-request /
per-GB-second serverless tariff. It is deliberately not a quote from any vendor;
replace it with your own negotiated rates before trusting a bill.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


class PriceSheetError(ValueError):
    """Raised when a price sheet is missing values or has impossible ones."""


@dataclass(frozen=True)
class PriceSheet:
    currency: str = "USD"
    request_price_per_million: float = 0.40
    gb_second_price: float = 0.0000166667
    egress_price_per_gb: float = 0.12
    free_requests_per_month: int = 2_000_000
    free_gb_seconds_per_month: int = 400_000
    free_egress_gb_per_month: float = 100.0
    minimum_monthly_charge: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PriceSheet:
        if not isinstance(data, dict):
            raise PriceSheetError("price sheet must be a JSON object")
        known = {field.name for field in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise PriceSheetError(f"unknown price sheet field(s): {', '.join(unknown)}")
        merged = asdict(default_sheet())
        merged.update(data)
        try:
            sheet = cls(**merged)
        except TypeError as exc:
            raise PriceSheetError(str(exc)) from exc
        problems = sheet.problems()
        if problems:
            raise PriceSheetError("; ".join(problems))
        return sheet

    @classmethod
    def load(cls, path: str | Path) -> PriceSheet:
        source = Path(path)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise PriceSheetError(f"price sheet not found: {source}") from exc
        except json.JSONDecodeError as exc:
            raise PriceSheetError(f"price sheet is not valid JSON: {exc}") from exc
        return cls.from_dict(data)

    def problems(self) -> list[str]:
        issues: list[str] = []
        if not isinstance(self.currency, str) or len(self.currency) != 3:
            issues.append("currency must be a three letter code")
        for name in (
            "request_price_per_million",
            "gb_second_price",
            "egress_price_per_gb",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                issues.append(f"{name} must be a non-negative number")
        for name in (
            "free_requests_per_month",
            "free_gb_seconds_per_month",
            "free_egress_gb_per_month",
            "minimum_monthly_charge",
        ):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                issues.append(f"{name} must be a non-negative number")
        return issues


def default_sheet() -> PriceSheet:
    return PriceSheet()
