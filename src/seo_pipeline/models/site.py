from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$",
    re.IGNORECASE,
)


def normalize_domain(value: str) -> str:
    normalized = value.strip().lower().rstrip(".")
    if normalized.startswith(("http://", "https://")) or "/" in normalized:
        raise ValueError("use a bare domain without a scheme, path, or trailing slash")
    if normalized.startswith("www."):
        normalized = normalized[4:]
    if not DOMAIN_RE.fullmatch(normalized):
        raise ValueError(f"invalid domain: {value!r}")
    return normalized


class SearchSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country: str = Field(default="US", min_length=2, max_length=3)
    language: str = Field(default="en", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    device: Literal["desktop", "mobile"] = "desktop"

    @field_validator("country")
    @classmethod
    def uppercase_country(cls, value: str) -> str:
        return value.upper()


class ReportingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comparison_period: Literal["previous_month"] = "previous_month"


class SiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    domain: str
    enabled: bool = True
    openseo_project_id: str | None = None
    search: SearchSettings = Field(default_factory=SearchSettings)
    reporting: ReportingSettings = Field(default_factory=ReportingSettings)
    target_keywords: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        return normalize_domain(value)

    @field_validator("competitors")
    @classmethod
    def validate_competitors(cls, values: list[str]) -> list[str]:
        normalized = [normalize_domain(value) for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("competitor domains must be unique")
        return normalized

    @field_validator("target_keywords")
    @classmethod
    def validate_keywords(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("target keywords must be unique")
        return normalized


class OpportunitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    high_priority_score: int = Field(default=70, ge=1, le=100)
    medium_priority_score: int = Field(default=40, ge=1, le=99)
    striking_distance_min: int = Field(default=11, ge=1, le=100)
    striking_distance_max: int = Field(default=20, ge=1, le=100)
    high_impression_threshold: int = Field(default=500, ge=1)
    low_ctr_threshold: float = Field(default=0.025, gt=0, lt=1)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "OpportunitySettings":
        if self.medium_priority_score >= self.high_priority_score:
            raise ValueError("medium priority score must be below high priority score")
        if self.striking_distance_min >= self.striking_distance_max:
            raise ValueError("striking distance minimum must be below maximum")
        return self


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sites: list[SiteConfig]
    opportunities: OpportunitySettings = Field(default_factory=OpportunitySettings)

    @model_validator(mode="after")
    def validate_sites(self) -> "PipelineConfig":
        ids = [site.id for site in self.sites]
        domains = [site.domain for site in self.sites]
        duplicate_ids = sorted({value for value in ids if ids.count(value) > 1})
        duplicate_domains = sorted({value for value in domains if domains.count(value) > 1})
        if duplicate_ids:
            raise ValueError(f"duplicate site IDs: {', '.join(duplicate_ids)}")
        if duplicate_domains:
            raise ValueError(f"duplicate site domains: {', '.join(duplicate_domains)}")
        return self

    def select_sites(self, selector: str) -> list[SiteConfig]:
        if selector == "all":
            return [site for site in self.sites if site.enabled]
        for site in self.sites:
            if site.id == selector:
                if not site.enabled:
                    raise ValueError(f"site {selector!r} is disabled")
                return [site]
        raise ValueError(f"unknown site ID: {selector!r}")

