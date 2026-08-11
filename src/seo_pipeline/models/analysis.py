from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Priority(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class OverallDirection(StrEnum):
    POSITIVE = "POSITIVE"
    MIXED = "MIXED"
    NEGATIVE = "NEGATIVE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ScoreComponent(BaseModel):
    factor: str
    points: int
    explanation: str


class OpportunityCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    priority: Priority
    opportunity_type: str
    title: str
    keyword: str | None = None
    url: str | None = None
    score: int = Field(ge=0, le=100)
    score_components: list[ScoreComponent]
    evidence: dict[str, Any]
    why_flagged: str
    recommended_investigation: list[str]


class AnalysisOpportunity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: Priority
    opportunity_type: str
    title: str
    explanation: str
    evidence_references: list[str]
    recommended_investigation: list[str]
    objective: str


class OpportunityAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executive_summary: str
    overall_direction: OverallDirection
    wins: list[str]
    risks: list[str]
    opportunities: list[AnalysisOpportunity]
    evidence_insufficient: list[str] = Field(default_factory=list)

