from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class KeywordObservation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    keyword: str
    position: float | None = None
    search_volume: int | None = None
    keyword_difficulty: float | None = None
    cpc: float | None = None
    intent: str | None = None
    estimated_traffic: float | None = None
    ranking_url: str | None = None
    clicks: float | None = None
    impressions: float | None = None
    ctr: float | None = None


class PageObservation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    clicks: float | None = None
    impressions: float | None = None
    ctr: float | None = None
    position: float | None = None


class SearchConsoleObservation(BaseModel):
    clicks: float | None = None
    impressions: float | None = None
    ctr: float | None = None
    average_position: float | None = None


class BacklinkObservation(BaseModel):
    total_backlinks: int | None = None
    referring_domains: int | None = None
    new_referring_domains: int | None = None
    lost_referring_domains: int | None = None
    top_linked_pages: list[dict[str, Any]] = Field(default_factory=list)


class CollectionSource(BaseModel):
    name: str
    measurement_type: Literal["first_party", "estimated"]
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    available: bool = True
    detail: str | None = None


class CollectedSEOData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_start: date
    period_end: date
    estimated_organic_traffic: float | None = None
    organic_keyword_count: int | None = None
    search_console: SearchConsoleObservation = Field(default_factory=SearchConsoleObservation)
    keywords: list[KeywordObservation] = Field(default_factory=list)
    pages: list[PageObservation] = Field(default_factory=list)
    backlinks: BacklinkObservation = Field(default_factory=BacklinkObservation)
    sources: list[CollectionSource] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

