import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Search(Model):
    country: str = Field(default="US", pattern=r"^[A-Z]{2}$")
    language: str = Field(default="en", pattern=r"^[a-z]{2,3}$")
    device: Literal["desktop", "mobile", "tablet"] = "desktop"
    location_code: int = Field(default=2840, gt=0)
    gsc_country: str | None = Field(default=None, pattern=r"^[a-z]{3}$")


class Reporting(Model):
    comparison_period: Literal["previous_month"] = "previous_month"


class AuditConfig(Model):
    enabled: bool = False
    max_pages: int = Field(default=100, ge=1, le=500)
    timeout_seconds: int = Field(default=900, ge=30, le=1800)


class Site(Model):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=150)
    domain: str
    enabled: bool = True
    search: Search = Field(default_factory=Search)
    reporting: Reporting = Field(default_factory=Reporting)
    target_keywords: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    openseo_project_id: str | None = Field(default=None, min_length=1)
    gsc_enabled: bool = True
    audit: AuditConfig = Field(default_factory=AuditConfig)

    @field_validator("domain")
    @classmethod
    def domain_valid(cls, value: str) -> str:
        value = value.lower().rstrip(".")
        if len(value) > 253 or not re.fullmatch(
            r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", value
        ):
            raise ValueError("Use a public domain without protocol, port, or path")
        return value


class Scoring(Model):
    min_impressions: int = Field(default=500, ge=1)
    min_volume: int = Field(default=100, ge=1)
    low_ctr: float | None = Field(default=None, ge=0, le=1)
    max_ctr_position: float = Field(default=10, ge=1)
    high: int = Field(default=60, ge=1, le=100)
    medium: int = Field(default=30, ge=0, le=100)

    @model_validator(mode="after")
    def ordered(self):
        if self.high <= self.medium:
            raise ValueError("high must exceed medium")
        return self


class Config(Model):
    sites: list[Site] = Field(min_length=1)
    scoring: Scoring = Field(default_factory=Scoring)
    max_keyword_rows: int = Field(default=500, ge=100, le=1100)
    max_gsc_rows: int = Field(default=10000, ge=1000, le=100000)

    @model_validator(mode="after")
    def unique(self):
        for field in ("id", "domain"):
            values = [getattr(site, field) for site in self.sites]
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate site {field}")
        return self


def load_config(path: Path) -> Config:
    return Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
