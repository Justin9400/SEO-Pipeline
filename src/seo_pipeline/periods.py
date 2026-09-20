import calendar
import re
from datetime import date, datetime, timedelta, timezone

from pydantic import model_validator

from .config import Model


class Period(Model):
    start: date
    end: date
    previous_start: date
    previous_end: date

    @model_validator(mode="after")
    def valid_months(self):
        if (
            self.start.day != 1
            or self.end < self.start
            or (self.start.year, self.start.month) != (self.end.year, self.end.month)
        ):
            raise ValueError(
                "Reporting period must start on the first and end in the same month"
            )
        if self.previous_end != self.start - timedelta(
            days=1
        ) or self.previous_start != self.previous_end.replace(day=1):
            raise ValueError("Comparison must be the complete preceding calendar month")
        return self

    @property
    def key(self) -> str:
        return self.start.strftime("%Y-%m")


def month_period(value: str | None = None, today: date | None = None) -> Period:
    today = today or datetime.now(timezone.utc).date()
    if value is None:
        first = today.replace(day=1)
        year, month = (
            (first.year - 1, 12) if first.month == 1 else (first.year, first.month - 1)
        )
    else:
        if not re.fullmatch(r"\d{4}-\d{2}", value):
            raise ValueError("Period must be YYYY-MM")
        year, month = map(int, value.split("-"))
    start = date(year, month, 1)
    if start > today:
        raise ValueError("Future periods are not supported")
    py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
    return Period(
        start=start,
        end=min(today, date(year, month, calendar.monthrange(year, month)[1])),
        previous_start=date(py, pm, 1),
        previous_end=date(py, pm, calendar.monthrange(py, pm)[1]),
    )
