from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from seo_pipeline.models.analysis import OpportunityAnalysis, OpportunityCandidate


class SiteIdentity(BaseModel):
    id: str
    name: str
    domain: str


class ReportingPeriod(BaseModel):
    start: date
    end: date
    previous_start: date
    previous_end: date
    generated_at: datetime


class ComparisonMetric(BaseModel):
    current: float | None = None
    previous: float | None = None
    absolute_change: float | None = None
    percent_change: float | None = None
    source: str
    measurement_type: Literal["first_party", "estimated"]
    unit: Literal["count", "percent", "position", "currency", "score"] = "count"
    direction: Literal["improved", "declined", "unchanged", "unknown"] = "unknown"


class KeywordRecord(BaseModel):
    keyword: str
    current_position: float | None = None
    previous_position: float | None = None
    position_change: float | None = None
    search_volume: int | None = None
    keyword_difficulty: float | None = None
    cpc: float | None = None
    search_intent: str | None = None
    estimated_traffic: float | None = None
    ranking_url: str | None = None
    clicks: float | None = None
    impressions: float | None = None
    ctr: float | None = None
    status: Literal["new", "lost", "improving", "declining", "unchanged"]
    source: str = "openseo"
    measurement_type: Literal["first_party", "estimated"] = "estimated"


class PageRecord(BaseModel):
    url: str
    current_clicks: float | None = None
    previous_clicks: float | None = None
    clicks_change: float | None = None
    current_impressions: float | None = None
    previous_impressions: float | None = None
    ctr: float | None = None
    position: float | None = None
    source: str = "google_search_console"
    measurement_type: Literal["first_party", "estimated"] = "first_party"


class KeywordDistribution(BaseModel):
    top_3: int = 0
    top_10: int = 0
    positions_11_20: int = 0
    positions_21_50: int = 0
    positions_51_100: int = 0


class KeywordTrendSummary(BaseModel):
    new: int = 0
    lost: int = 0
    improving: int = 0
    declining: int = 0
    unchanged: int = 0


class BacklinkSummary(BaseModel):
    total_backlinks: ComparisonMetric
    referring_domains: ComparisonMetric
    new_referring_domains: int | None = None
    lost_referring_domains: int | None = None
    top_linked_pages: list[dict[str, Any]] = Field(default_factory=list)


class SEOSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    report_version: str = "0.1.0"
    site: SiteIdentity
    reporting_period: ReportingPeriod
    metrics: dict[str, ComparisonMetric]
    keyword_distribution: KeywordDistribution
    keywords: list[KeywordRecord]
    pages: list[PageRecord]
    backlinks: BacklinkSummary
    trends: KeywordTrendSummary
    opportunity_candidates: list[OpportunityCandidate]
    analysis: OpportunityAnalysis
    data_sources: list[dict[str, Any]]
    warnings: list[str] = Field(default_factory=list)
    collection_metadata: dict[str, Any] = Field(default_factory=dict)

