from __future__ import annotations

from seo_pipeline.analysis.comparison import (
    compare_keywords,
    comparison_metric,
    keyword_distribution,
    percent_change,
)
from seo_pipeline.models.provider import KeywordObservation


def test_percent_change() -> None:
    assert percent_change(112, 100) == 12.0


def test_zero_denominator_is_unknown() -> None:
    assert percent_change(10, 0) is None


def test_position_direction_is_reversed() -> None:
    metric = comparison_metric(
        10,
        15,
        source="gsc",
        measurement_type="first_party",
        unit="position",
        lower_is_better=True,
    )
    assert metric.absolute_change == -5
    assert metric.direction == "improved"


def test_keyword_new_lost_and_movement() -> None:
    current = [
        KeywordObservation(keyword="new", position=30),
        KeywordObservation(keyword="gain", position=10),
        KeywordObservation(keyword="loss", position=12),
        KeywordObservation(keyword="same", position=8),
    ]
    previous = [
        KeywordObservation(keyword="gone", position=7),
        KeywordObservation(keyword="gain", position=15),
        KeywordObservation(keyword="loss", position=7),
        KeywordObservation(keyword="same", position=8),
    ]
    rows = {row.keyword: row for row in compare_keywords(current, previous)}
    assert rows["new"].status == "new"
    assert rows["gone"].status == "lost"
    assert rows["gain"].status == "improving"
    assert rows["gain"].position_change == 5
    assert rows["loss"].status == "declining"
    assert rows["same"].status == "unchanged"


def test_ranking_buckets_are_exclusive() -> None:
    rows = compare_keywords(
        [
            KeywordObservation(keyword="a", position=2),
            KeywordObservation(keyword="b", position=7),
            KeywordObservation(keyword="c", position=15),
            KeywordObservation(keyword="d", position=35),
            KeywordObservation(keyword="e", position=88),
        ],
        [],
    )
    buckets = keyword_distribution(rows)
    assert buckets.model_dump() == {
        "top_3": 1,
        "top_10": 1,
        "positions_11_20": 1,
        "positions_21_50": 1,
        "positions_51_100": 1,
    }


def test_missing_values_remain_unknown() -> None:
    metric = comparison_metric(
        None, 4, source="openseo", measurement_type="estimated"
    )
    assert metric.current is None
    assert metric.absolute_change is None
    assert metric.direction == "unknown"

