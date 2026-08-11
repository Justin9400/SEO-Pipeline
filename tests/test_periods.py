from __future__ import annotations

from datetime import date

import pytest

from seo_pipeline.periods import resolve_period


def test_default_period_is_last_completed_month() -> None:
    period = resolve_period(None, today=date(2026, 8, 10))
    assert (period.start, period.end) == (date(2026, 7, 1), date(2026, 7, 31))


def test_january_crosses_year_boundary() -> None:
    period = resolve_period("2026-01")
    assert period.previous_start == date(2025, 12, 1)
    assert period.previous_end == date(2025, 12, 31)


def test_leap_year_february() -> None:
    period = resolve_period("2024-02")
    assert period.end == date(2024, 2, 29)
    assert period.previous_end == date(2024, 1, 31)


def test_different_month_lengths() -> None:
    april = resolve_period("2026-04")
    assert april.end.day == 30
    assert april.previous_end.day == 31


def test_invalid_period_format() -> None:
    with pytest.raises(ValueError, match="YYYY-MM"):
        resolve_period("2026-7")

