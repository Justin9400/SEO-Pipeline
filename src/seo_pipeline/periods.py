from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timezone

from pydantic import BaseModel


PERIOD_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


class PeriodWindow(BaseModel):
    start: date
    end: date
    previous_start: date
    previous_end: date
    generated_at: datetime

    @property
    def key(self) -> str:
        return self.start.strftime("%Y-%m")


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def resolve_period(value: str | None, *, today: date | None = None) -> PeriodWindow:
    reference = today or date.today()
    if value is None:
        year, month = previous_month(reference.year, reference.month)
    else:
        match = PERIOD_RE.fullmatch(value)
        if not match:
            raise ValueError("period must use YYYY-MM and identify a complete calendar month")
        year, month = int(match.group(1)), int(match.group(2))
    start, end = month_bounds(year, month)
    previous_year, previous_month_number = previous_month(year, month)
    previous_start, previous_end = month_bounds(previous_year, previous_month_number)
    return PeriodWindow(
        start=start,
        end=end,
        previous_start=previous_start,
        previous_end=previous_end,
        generated_at=datetime.now(timezone.utc),
    )

