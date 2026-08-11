from __future__ import annotations

from datetime import timezone

from seo_pipeline import SCHEMA_VERSION, __version__
from seo_pipeline.models.analysis import OpportunityAnalysis
from seo_pipeline.models.provider import (
    BacklinkObservation,
    CollectedSEOData,
    CollectionSource,
    KeywordObservation,
    PageObservation,
    SearchConsoleObservation,
)
from seo_pipeline.models.site import SiteConfig
from seo_pipeline.models.snapshot import (
    BacklinkSummary,
    ComparisonMetric,
    KeywordDistribution,
    KeywordRecord,
    KeywordTrendSummary,
    PageRecord,
    ReportingPeriod,
    SEOSnapshot,
    SiteIdentity,
)
from seo_pipeline.periods import PeriodWindow


def percent_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round(((current - previous) / abs(previous)) * 100, 2)


def comparison_metric(
    current: float | None,
    previous: float | None,
    *,
    source: str,
    measurement_type: str,
    unit: str = "count",
    lower_is_better: bool = False,
) -> ComparisonMetric:
    absolute = None if current is None or previous is None else round(current - previous, 4)
    change = percent_change(current, previous)
    if absolute is None:
        direction = "unknown"
    elif abs(absolute) < 1e-9:
        direction = "unchanged"
    elif (absolute < 0) if lower_is_better else (absolute > 0):
        direction = "improved"
    else:
        direction = "declined"
    return ComparisonMetric(
        current=current,
        previous=previous,
        absolute_change=absolute,
        percent_change=change,
        source=source,
        measurement_type=measurement_type,
        unit=unit,
        direction=direction,
    )


def ranking_bucket(position: float | None) -> str | None:
    if position is None or position <= 0 or position > 100:
        return None
    if position <= 3:
        return "top_3"
    if position <= 10:
        return "top_10"
    if position <= 20:
        return "positions_11_20"
    if position <= 50:
        return "positions_21_50"
    return "positions_51_100"


def keyword_distribution(keywords: list[KeywordRecord]) -> KeywordDistribution:
    counts = {
        "top_3": 0,
        "top_10": 0,
        "positions_11_20": 0,
        "positions_21_50": 0,
        "positions_51_100": 0,
    }
    for keyword in keywords:
        bucket = ranking_bucket(keyword.current_position)
        if bucket:
            counts[bucket] += 1
    return KeywordDistribution(**counts)


def compare_keywords(
    current: list[KeywordObservation], previous: list[KeywordObservation]
) -> list[KeywordRecord]:
    current_by_keyword = {row.keyword.casefold(): row for row in current}
    previous_by_keyword = {row.keyword.casefold(): row for row in previous}
    records: list[KeywordRecord] = []
    for key in sorted(current_by_keyword.keys() | previous_by_keyword.keys()):
        current_row = current_by_keyword.get(key)
        previous_row = previous_by_keyword.get(key)
        current_position = current_row.position if current_row else None
        previous_position = previous_row.position if previous_row else None
        if current_row is None:
            status = "lost"
        elif previous_row is None:
            status = "new"
        elif current_position is None and previous_position is not None:
            status = "lost"
        elif current_position is not None and previous_position is None:
            status = "new"
        elif current_position is None or previous_position is None:
            status = "unchanged"
        else:
            position_delta = previous_position - current_position
            if position_delta > 0.05:
                status = "improving"
            elif position_delta < -0.05:
                status = "declining"
            else:
                status = "unchanged"
        row = current_row or previous_row
        assert row is not None
        position_change = (
            round(previous_position - current_position, 2)
            if current_position is not None and previous_position is not None
            else None
        )
        records.append(
            KeywordRecord(
                keyword=row.keyword,
                current_position=current_position,
                previous_position=previous_position,
                position_change=position_change,
                search_volume=row.search_volume,
                keyword_difficulty=row.keyword_difficulty,
                cpc=row.cpc,
                search_intent=row.intent,
                estimated_traffic=row.estimated_traffic,
                ranking_url=row.ranking_url,
                clicks=current_row.clicks if current_row else None,
                impressions=current_row.impressions if current_row else None,
                ctr=current_row.ctr if current_row else None,
                status=status,
                measurement_type="first_party"
                if current_row and current_row.impressions is not None
                else "estimated",
            )
        )
    return sorted(
        records,
        key=lambda row: (
            row.status == "lost",
            row.current_position is None,
            row.current_position or 999,
            row.keyword,
        ),
    )


def compare_pages(
    current: list[PageObservation], previous: list[PageObservation]
) -> list[PageRecord]:
    current_by_url = {row.url: row for row in current}
    previous_by_url = {row.url: row for row in previous}
    rows: list[PageRecord] = []
    for url in current_by_url.keys() | previous_by_url.keys():
        current_row = current_by_url.get(url)
        previous_row = previous_by_url.get(url)
        current_clicks = current_row.clicks if current_row else None
        previous_clicks = previous_row.clicks if previous_row else None
        rows.append(
            PageRecord(
                url=url,
                current_clicks=current_clicks,
                previous_clicks=previous_clicks,
                clicks_change=(
                    round(current_clicks - previous_clicks, 2)
                    if current_clicks is not None and previous_clicks is not None
                    else None
                ),
                current_impressions=current_row.impressions if current_row else None,
                previous_impressions=previous_row.impressions if previous_row else None,
                ctr=current_row.ctr if current_row else None,
                position=current_row.position if current_row else None,
            )
        )
    return sorted(
        rows,
        key=lambda row: (
            -(row.current_clicks or 0),
            -(abs(row.clicks_change) if row.clicks_change is not None else 0),
            row.url,
        ),
    )


def summarize_keyword_trends(keywords: list[KeywordRecord]) -> KeywordTrendSummary:
    counts = {name: 0 for name in ("new", "lost", "improving", "declining", "unchanged")}
    for keyword in keywords:
        counts[keyword.status] += 1
    return KeywordTrendSummary(**counts)


def build_snapshot(
    *,
    site: SiteConfig,
    period: PeriodWindow,
    current: CollectedSEOData,
    previous: CollectedSEOData | None,
    candidates: list,
    analysis: OpportunityAnalysis,
) -> SEOSnapshot:
    prior = previous or CollectedSEOData(
        period_start=period.previous_start,
        period_end=period.previous_end,
    )
    metrics = {
        "organic_clicks": comparison_metric(
            current.search_console.clicks,
            prior.search_console.clicks,
            source="google_search_console",
            measurement_type="first_party",
        ),
        "organic_impressions": comparison_metric(
            current.search_console.impressions,
            prior.search_console.impressions,
            source="google_search_console",
            measurement_type="first_party",
        ),
        "organic_ctr": comparison_metric(
            current.search_console.ctr,
            prior.search_console.ctr,
            source="google_search_console",
            measurement_type="first_party",
            unit="percent",
        ),
        "average_position": comparison_metric(
            current.search_console.average_position,
            prior.search_console.average_position,
            source="google_search_console",
            measurement_type="first_party",
            unit="position",
            lower_is_better=True,
        ),
        "estimated_organic_traffic": comparison_metric(
            current.estimated_organic_traffic,
            prior.estimated_organic_traffic,
            source="openseo",
            measurement_type="estimated",
        ),
        "ranking_keywords": comparison_metric(
            float(current.organic_keyword_count)
            if current.organic_keyword_count is not None
            else None,
            float(prior.organic_keyword_count)
            if prior.organic_keyword_count is not None
            else None,
            source="openseo",
            measurement_type="estimated",
        ),
        "referring_domains": comparison_metric(
            float(current.backlinks.referring_domains)
            if current.backlinks.referring_domains is not None
            else None,
            float(prior.backlinks.referring_domains)
            if prior.backlinks.referring_domains is not None
            else None,
            source="openseo",
            measurement_type="estimated",
        ),
    }
    keywords = compare_keywords(current.keywords, prior.keywords)
    pages = compare_pages(current.pages, prior.pages)
    backlinks = BacklinkSummary(
        total_backlinks=comparison_metric(
            float(current.backlinks.total_backlinks)
            if current.backlinks.total_backlinks is not None
            else None,
            float(prior.backlinks.total_backlinks)
            if prior.backlinks.total_backlinks is not None
            else None,
            source="openseo",
            measurement_type="estimated",
        ),
        referring_domains=metrics["referring_domains"],
        new_referring_domains=current.backlinks.new_referring_domains,
        lost_referring_domains=current.backlinks.lost_referring_domains,
        top_linked_pages=current.backlinks.top_linked_pages,
    )
    warnings = list(current.warnings)
    if previous is None:
        warnings.append("No previous snapshot was available; comparison values may be unavailable.")
    return SEOSnapshot(
        schema_version=SCHEMA_VERSION,
        report_version=__version__,
        site=SiteIdentity(id=site.id, name=site.name, domain=site.domain),
        reporting_period=ReportingPeriod(
            start=period.start,
            end=period.end,
            previous_start=period.previous_start,
            previous_end=period.previous_end,
            generated_at=period.generated_at.astimezone(timezone.utc),
        ),
        metrics=metrics,
        keyword_distribution=keyword_distribution(keywords),
        keywords=keywords,
        pages=pages,
        backlinks=backlinks,
        trends=summarize_keyword_trends(keywords),
        opportunity_candidates=candidates,
        analysis=analysis,
        data_sources=[source.model_dump(mode="json") for source in current.sources],
        warnings=warnings,
        collection_metadata=current.raw_metadata,
    )


def snapshot_to_collected(snapshot: SEOSnapshot) -> CollectedSEOData:
    """Reconstruct the prior period's current observations from a stored snapshot."""
    metrics = snapshot.metrics
    return CollectedSEOData(
        period_start=snapshot.reporting_period.start,
        period_end=snapshot.reporting_period.end,
        estimated_organic_traffic=metrics["estimated_organic_traffic"].current,
        organic_keyword_count=(
            int(metrics["ranking_keywords"].current)
            if metrics["ranking_keywords"].current is not None
            else None
        ),
        search_console=SearchConsoleObservation(
            clicks=metrics["organic_clicks"].current,
            impressions=metrics["organic_impressions"].current,
            ctr=metrics["organic_ctr"].current,
            average_position=metrics["average_position"].current,
        ),
        keywords=[
            KeywordObservation(
                keyword=row.keyword,
                position=row.current_position,
                search_volume=row.search_volume,
                keyword_difficulty=row.keyword_difficulty,
                cpc=row.cpc,
                intent=row.search_intent,
                estimated_traffic=row.estimated_traffic,
                ranking_url=row.ranking_url,
                clicks=row.clicks,
                impressions=row.impressions,
                ctr=row.ctr,
            )
            for row in snapshot.keywords
            if row.current_position is not None
        ],
        pages=[
            PageObservation(
                url=row.url,
                clicks=row.current_clicks,
                impressions=row.current_impressions,
                ctr=row.ctr,
                position=row.position,
            )
            for row in snapshot.pages
            if row.current_clicks is not None or row.current_impressions is not None
        ],
        backlinks=BacklinkObservation(
            total_backlinks=(
                int(snapshot.backlinks.total_backlinks.current)
                if snapshot.backlinks.total_backlinks.current is not None
                else None
            ),
            referring_domains=(
                int(snapshot.backlinks.referring_domains.current)
                if snapshot.backlinks.referring_domains.current is not None
                else None
            ),
        ),
        sources=[
            CollectionSource(
                name=str(source.get("name", "unknown")),
                measurement_type=source.get("measurement_type", "estimated"),
                available=bool(source.get("available", True)),
            )
            for source in snapshot.data_sources
        ],
    )

