from __future__ import annotations

import hashlib
from collections.abc import Iterable

from seo_pipeline.models.analysis import (
    OpportunityCandidate,
    Priority,
    ScoreComponent,
)
from seo_pipeline.models.site import OpportunitySettings
from seo_pipeline.models.snapshot import KeywordRecord, PageRecord


def _component(factor: str, points: int, explanation: str) -> ScoreComponent:
    return ScoreComponent(factor=factor, points=points, explanation=explanation)


def _priority(score: int, settings: OpportunitySettings) -> Priority:
    if score >= settings.high_priority_score:
        return Priority.HIGH
    if score >= settings.medium_priority_score:
        return Priority.MEDIUM
    return Priority.LOW


def _candidate_id(opportunity_type: str, identity: str) -> str:
    digest = hashlib.sha1(f"{opportunity_type}:{identity}".encode(), usedforsecurity=False).hexdigest()[:10]
    return f"{opportunity_type.lower()}-{digest}"


def _demand_components(keyword: KeywordRecord) -> list[ScoreComponent]:
    components: list[ScoreComponent] = []
    if keyword.search_volume is not None:
        if keyword.search_volume >= 1000:
            components.append(_component("search_volume", 20, "Search volume is at least 1,000."))
        elif keyword.search_volume >= 250:
            components.append(_component("search_volume", 14, "Search volume is at least 250."))
        elif keyword.search_volume >= 50:
            components.append(_component("search_volume", 8, "Search volume is at least 50."))
    if keyword.impressions is not None:
        if keyword.impressions >= 2500:
            components.append(_component("impressions", 20, "The query has at least 2,500 impressions."))
        elif keyword.impressions >= 500:
            components.append(_component("impressions", 14, "The query has at least 500 impressions."))
        elif keyword.impressions >= 100:
            components.append(_component("impressions", 7, "The query has at least 100 impressions."))
    if keyword.ranking_url:
        components.append(_component("ranking_url", 7, "An existing ranking URL is known."))
    return components


def _build_keyword_candidate(
    keyword: KeywordRecord,
    opportunity_type: str,
    title: str,
    why_flagged: str,
    base_components: Iterable[ScoreComponent],
    settings: OpportunitySettings,
    investigations: list[str],
) -> OpportunityCandidate:
    components = list(base_components) + _demand_components(keyword)
    score = min(100, sum(component.points for component in components))
    evidence = {
        "keyword": keyword.keyword,
        "current_position": keyword.current_position,
        "previous_position": keyword.previous_position,
        "position_change": keyword.position_change,
        "search_volume": keyword.search_volume,
        "impressions": keyword.impressions,
        "clicks": keyword.clicks,
        "ctr": keyword.ctr,
        "ranking_url": keyword.ranking_url,
        "status": keyword.status,
    }
    return OpportunityCandidate(
        candidate_id=_candidate_id(opportunity_type, keyword.keyword),
        priority=_priority(score, settings),
        opportunity_type=opportunity_type,
        title=title,
        keyword=keyword.keyword,
        url=keyword.ranking_url,
        score=score,
        score_components=components,
        evidence=evidence,
        why_flagged=why_flagged,
        recommended_investigation=investigations,
    )


def detect_keyword_opportunities(
    keywords: list[KeywordRecord], settings: OpportunitySettings
) -> list[OpportunityCandidate]:
    candidates: list[OpportunityCandidate] = []
    for keyword in keywords:
        position = keyword.current_position
        if (
            position is not None
            and settings.striking_distance_min <= position <= settings.striking_distance_max
        ):
            proximity = max(8, 28 - int(position))
            candidates.append(
                _build_keyword_candidate(
                    keyword,
                    "STRIKING_DISTANCE",
                    f"Page-one opportunity for {keyword.keyword}",
                    "The query ranks within the configured striking-distance range.",
                    [
                        _component("ranking_proximity", proximity, f"Current position is {position:g}."),
                        _component(
                            "recent_direction",
                            12 if (keyword.position_change or 0) > 0 else 4,
                            "Recent ranking movement is improving."
                            if (keyword.position_change or 0) > 0
                            else "No recent improvement bonus was applied.",
                        ),
                    ],
                    settings,
                    [
                        "Review search intent alignment",
                        "Review title and SERP presentation",
                        "Review page content coverage",
                        "Review internal linking",
                        "Compare the page with current high-ranking results",
                    ],
                )
            )
        if (
            keyword.impressions is not None
            and keyword.impressions >= settings.high_impression_threshold
            and keyword.ctr is not None
            and keyword.ctr <= settings.low_ctr_threshold
            and position is not None
            and position <= 20
        ):
            candidates.append(
                _build_keyword_candidate(
                    keyword,
                    "HIGH_IMPRESSION_LOW_CTR",
                    f"SERP presentation opportunity for {keyword.keyword}",
                    "Impressions exceed the configured threshold while CTR is below the configured heuristic.",
                    [
                        _component("eligible_position", 18, f"Current position is {position:g}."),
                        _component("ctr_gap", 24, f"CTR is {keyword.ctr:.2%}."),
                    ],
                    settings,
                    [
                        "Review the query intent and SERP composition",
                        "Review title and description presentation",
                        "Check whether the ranking URL is the intended landing page",
                    ],
                )
            )
        if keyword.status == "declining" and keyword.position_change is not None:
            magnitude = abs(keyword.position_change)
            candidates.append(
                _build_keyword_candidate(
                    keyword,
                    "RANKING_LOSS",
                    f"Ranking decline for {keyword.keyword}",
                    f"The ranking declined by {magnitude:g} positions.",
                    [_component("decline_magnitude", min(35, 12 + int(magnitude * 3)), f"Decline magnitude is {magnitude:g}." )],
                    settings,
                    [
                        "Confirm the decline across devices and locations",
                        "Review current SERP competitors and intent",
                        "Check whether demand or seasonality changed",
                        "Review the ranking page's relevance and internal support",
                    ],
                )
            )
        elif keyword.status == "improving" and keyword.position_change is not None:
            candidates.append(
                _build_keyword_candidate(
                    keyword,
                    "RANKING_GAIN",
                    f"Ranking momentum for {keyword.keyword}",
                    f"The ranking improved by {keyword.position_change:g} positions.",
                    [_component("gain_magnitude", min(28, 8 + int(keyword.position_change * 2)), "Positive ranking momentum." )],
                    settings,
                    [
                        "Confirm the improvement is sustained",
                        "Identify related queries that may benefit from the same page",
                        "Review internal links that support the ranking URL",
                    ],
                )
            )
        elif keyword.status == "new":
            candidates.append(
                _build_keyword_candidate(
                    keyword,
                    "NEW_KEYWORD",
                    f"New visibility for {keyword.keyword}",
                    "The query appears in the current period but not the previous period.",
                    [_component("new_visibility", 18, "Newly observed ranking keyword.")],
                    settings,
                    ["Confirm relevance", "Monitor whether the ranking persists", "Review the ranking URL's intent alignment"],
                )
            )
        elif keyword.status == "lost":
            candidates.append(
                _build_keyword_candidate(
                    keyword,
                    "LOST_KEYWORD",
                    f"Lost visibility for {keyword.keyword}",
                    "The query appeared in the previous period but is absent now.",
                    [_component("lost_visibility", 30, "Previously observed visibility was lost.")],
                    settings,
                    ["Confirm the loss in current SERPs", "Check whether the prior ranking URL still matches intent", "Review competing results"],
                )
            )
    return candidates


def detect_page_opportunities(
    pages: list[PageRecord], settings: OpportunitySettings
) -> list[OpportunityCandidate]:
    candidates: list[OpportunityCandidate] = []
    for page in pages:
        change = page.clicks_change
        if change is None or change == 0:
            continue
        opportunity_type = "PAGE_GAIN" if change > 0 else "PAGE_LOSS"
        magnitude = abs(change)
        components = [
            _component(
                "click_change",
                min(45, 12 + int(magnitude / 10)),
                f"Organic clicks changed by {change:+g}.",
            )
        ]
        if (page.current_impressions or 0) >= settings.high_impression_threshold:
            components.append(_component("impressions", 18, "The page has meaningful impressions."))
        score = min(100, sum(component.points for component in components))
        candidates.append(
            OpportunityCandidate(
                candidate_id=_candidate_id(opportunity_type, page.url),
                priority=_priority(score, settings),
                opportunity_type=opportunity_type,
                title=("Page gaining organic clicks" if change > 0 else "Page losing organic clicks"),
                url=page.url,
                score=score,
                score_components=components,
                evidence={
                    "url": page.url,
                    "current_clicks": page.current_clicks,
                    "previous_clicks": page.previous_clicks,
                    "clicks_change": page.clicks_change,
                    "current_impressions": page.current_impressions,
                },
                why_flagged="Search Console clicks changed materially between periods.",
                recommended_investigation=[
                    "Review the page's query mix",
                    "Check whether impressions or CTR drove the change",
                    "Compare the page's average position between periods",
                ],
            )
        )
    return candidates


def detect_opportunities(
    keywords: list[KeywordRecord],
    pages: list[PageRecord],
    settings: OpportunitySettings,
    *,
    limit: int = 30,
) -> list[OpportunityCandidate]:
    candidates = detect_keyword_opportunities(keywords, settings)
    candidates.extend(detect_page_opportunities(pages, settings))
    return sorted(
        candidates,
        key=lambda candidate: (-candidate.score, candidate.opportunity_type, candidate.candidate_id),
    )[:limit]

