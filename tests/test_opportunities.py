from __future__ import annotations

from seo_pipeline.analysis.opportunities import detect_opportunities
from seo_pipeline.models.site import OpportunitySettings
from seo_pipeline.models.snapshot import KeywordRecord


def test_striking_distance_detection() -> None:
    keyword = KeywordRecord(
        keyword="commercial widget",
        current_position=12,
        previous_position=15,
        position_change=3,
        search_volume=2400,
        impressions=3800,
        clicks=80,
        ctr=0.021,
        ranking_url="https://example.com/widgets",
        status="improving",
    )
    candidates = detect_opportunities([keyword], [], OpportunitySettings())
    striking = next(c for c in candidates if c.opportunity_type == "STRIKING_DISTANCE")
    assert striking.priority.value == "HIGH"
    assert striking.score_components
    assert striking.evidence["current_position"] == 12


def test_high_impression_low_ctr_uses_configured_threshold() -> None:
    keyword = KeywordRecord(
        keyword="weak ctr",
        current_position=8,
        impressions=600,
        ctr=0.01,
        status="unchanged",
    )
    candidates = detect_opportunities([keyword], [], OpportunitySettings())
    assert any(c.opportunity_type == "HIGH_IMPRESSION_LOW_CTR" for c in candidates)


def test_opportunity_scores_are_deterministic() -> None:
    keyword = KeywordRecord(
        keyword="repeatable",
        current_position=18,
        previous_position=22,
        position_change=4,
        search_volume=500,
        impressions=900,
        ranking_url="https://example.com/repeatable",
        status="improving",
    )
    first = detect_opportunities([keyword], [], OpportunitySettings())
    second = detect_opportunities([keyword], [], OpportunitySettings())
    assert [item.model_dump() for item in first] == [item.model_dump() for item in second]

