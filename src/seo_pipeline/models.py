from datetime import date, datetime, timezone
from typing import Literal

from pydantic import Field, model_validator

from .config import Model, Site
from .periods import Period

Source = Literal["openseo", "google_search_console", "mock"]


class Metric(Model):
    value: float | None = Field(default=None, ge=0)
    source: Source
    measurement_type: Literal["estimated", "first_party", "synthetic"]
    period_start: date | None = None
    period_end: date | None = None
    observed_at: datetime | None = None
    temporal_basis: Literal["period", "point_in_time"] = "period"


class Row(Model):
    key: str = Field(min_length=1)
    source: Source
    position: float | None = Field(default=None, ge=1)
    ranking_url: str | None = None
    search_volume: float | None = Field(default=None, ge=0)
    keyword_difficulty: float | None = Field(default=None, ge=0, le=100)
    cpc: float | None = Field(default=None, ge=0)
    search_intent: str | None = None
    estimated_traffic: float | None = Field(default=None, ge=0)
    clicks: float | None = Field(default=None, ge=0)
    impressions: float | None = Field(default=None, ge=0)
    ctr: float | None = Field(default=None, ge=0, le=1)


class AuditIssue(Model):
    severity: Literal["critical", "warning", "info"]
    issue_type: str
    title: str
    url: str
    details: dict = Field(default_factory=dict)
    how_to_fix: str


class AuditResult(Model):
    status: str = "unavailable"
    audit_id: str | None = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    max_pages: int
    pages_crawled: int | None = None
    total_issues: int | None = None
    issues: list[AuditIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Collection(Model):
    audit: AuditResult | None = None
    metrics: dict[str, Metric] = Field(default_factory=dict)
    keywords: list[Row] | None = None
    queries: list[Row] | None = None
    pages: list[Row] | None = None
    keywords_complete: bool = False
    queries_complete: bool = False
    pages_complete: bool = False
    warnings: list[str] = Field(default_factory=list)
    provider: Literal["mock", "openseo"]
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def unique_rows(self):
        for name in ("keywords", "queries", "pages"):
            rows = getattr(self, name)
            if rows is not None and len({r.key for r in rows}) != len(rows):
                raise ValueError(f"Duplicate {name} keys")
        return self


class Delta(Model):
    current: float | None
    previous: float | None
    absolute_change: float | None
    percent_change: float | None
    percentage_point_change: float | None = None
    position_improvement: float | None = None
    provenance: Metric
    previous_provenance: Metric | None = None


class Movement(Model):
    key: str
    source: Source
    current: Row | None
    previous: Row | None
    status: Literal["NEW", "LOST", "IMPROVED", "DECLINED", "UNCHANGED", "UNKNOWN"]
    position_improvement: float | None = None
    clicks_change: float | None = None


class Candidate(Model):
    id: str
    priority: Literal["HIGH", "MEDIUM", "LOW"]
    opportunity_type: str
    score: int
    score_components: dict[str, int]
    evidence: Movement
    reason: str
    recommended_investigation: list[str]


class Insight(Model):
    candidate_id: str
    priority: Literal["HIGH", "MEDIUM", "LOW"]
    opportunity_type: str
    title: str
    explanation: str
    evidence_references: list[str]
    recommended_investigation: list[str]
    objective: str


class OpportunityAnalysis(Model):
    executive_summary: str
    overall_direction: Literal[
        "POSITIVE", "NEGATIVE", "MIXED", "STABLE", "INSUFFICIENT_DATA"
    ]
    wins: list[str]
    risks: list[str]
    opportunities: list[Insight]


class Snapshot(Model):
    schema_version: Literal["1.0"] = "1.0"
    site: Site
    reporting_period: Period
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    collection: Collection
    metrics: dict[str, Delta] = Field(default_factory=dict)
    keyword_distribution: dict[str, int] | None = None
    keyword_comparison_available: bool = False
    keywords: list[Movement] = Field(default_factory=list)
    queries: list[Movement] = Field(default_factory=list)
    pages: list[Movement] = Field(default_factory=list)
    trends: dict[str, list[str]] = Field(default_factory=dict)
    candidates: list[Candidate] = Field(default_factory=list)
    direction: str = "INSUFFICIENT_DATA"
    analysis: OpportunityAnalysis | None = None
    analysis_status: str = "not_requested"
