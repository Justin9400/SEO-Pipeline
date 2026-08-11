from __future__ import annotations

import json
import os
from typing import Any

from seo_pipeline.models.analysis import (
    AnalysisOpportunity,
    OpportunityAnalysis,
    OpportunityCandidate,
    OverallDirection,
)
from seo_pipeline.models.snapshot import ComparisonMetric


SYSTEM_PROMPT = """You analyze already-calculated SEO reporting data.

Rules:
- Never invent SEO metrics.
- Only make quantitative claims supported by the supplied structured data.
- Do not recalculate metrics that application code already calculated.
- Do not claim access to website source code.
- Do not claim to know why a ranking changed unless the supplied evidence supports it.
- Distinguish correlation from causation.
- Preserve the exact keyword, URL, and numeric evidence associated with recommendations.
- Say when evidence is insufficient.
- Recommend what should be investigated or optimized; never pretend changes were made.
- Treat estimated provider metrics separately from first-party Search Console metrics.
"""


def infer_direction(metrics: dict[str, ComparisonMetric]) -> OverallDirection:
    directional = [
        metrics[name].direction
        for name in ("organic_clicks", "organic_impressions", "estimated_organic_traffic")
        if name in metrics and metrics[name].direction != "unknown"
    ]
    if not directional:
        return OverallDirection.INSUFFICIENT_DATA
    improved = directional.count("improved")
    declined = directional.count("declined")
    if improved and not declined:
        return OverallDirection.POSITIVE
    if declined and not improved:
        return OverallDirection.NEGATIVE
    return OverallDirection.MIXED


def _change_phrase(label: str, metric: ComparisonMetric) -> str | None:
    if metric.current is None:
        return None
    current = f"{metric.current:,.0f}" if metric.unit == "count" else f"{metric.current:,.2f}"
    if metric.percent_change is None:
        return f"{label} was {current}; a comparable percentage change is unavailable."
    verb = "increased" if metric.percent_change > 0 else "decreased" if metric.percent_change < 0 else "was unchanged"
    if metric.percent_change == 0:
        return f"{label} was unchanged at {current}."
    return f"{label} {verb} {abs(metric.percent_change):.1f}% to {current}."


def deterministic_analysis(
    metrics: dict[str, ComparisonMetric], candidates: list[OpportunityCandidate]
) -> OpportunityAnalysis:
    summary_parts = [
        phrase
        for name, label in (
            ("organic_clicks", "Organic clicks"),
            ("organic_impressions", "Organic impressions"),
            ("estimated_organic_traffic", "Estimated organic traffic"),
        )
        if name in metrics and (phrase := _change_phrase(label, metrics[name]))
    ]
    executive_summary = " ".join(summary_parts[:3]) or "Comparable SEO performance data is not yet available."
    wins = [candidate.title for candidate in candidates if candidate.opportunity_type in {"RANKING_GAIN", "NEW_KEYWORD", "PAGE_GAIN"}][:5]
    risks = [candidate.title for candidate in candidates if candidate.opportunity_type in {"RANKING_LOSS", "LOST_KEYWORD", "PAGE_LOSS"}][:5]
    opportunities = [
        AnalysisOpportunity(
            priority=candidate.priority,
            opportunity_type=candidate.opportunity_type,
            title=candidate.title,
            explanation=candidate.why_flagged,
            evidence_references=[candidate.candidate_id],
            recommended_investigation=candidate.recommended_investigation,
            objective="Validate the evidence and improve qualified organic visibility or traffic.",
        )
        for candidate in candidates[:12]
    ]
    return OpportunityAnalysis(
        executive_summary=executive_summary,
        overall_direction=infer_direction(metrics),
        wins=wins,
        risks=risks,
        opportunities=opportunities,
        evidence_insufficient=[] if summary_parts else ["No comparable core metrics were available."],
    )


class OpenAIAnalyzer:
    def __init__(self, *, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY") if api_key is None else api_key
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5.6")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def analyze(
        self,
        *,
        site: dict[str, Any],
        reporting_period: dict[str, Any],
        metrics: dict[str, ComparisonMetric],
        candidates: list[OpportunityCandidate],
    ) -> OpportunityAnalysis:
        if not self.api_key:
            return deterministic_analysis(metrics, candidates)
        from openai import OpenAI

        payload = {
            "site": site,
            "reporting_period": reporting_period,
            "metrics": {name: metric.model_dump(mode="json") for name, metric in metrics.items()},
            "deterministic_candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        }
        client = OpenAI(api_key=self.api_key, timeout=60.0, max_retries=2)
        response = client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "Contextualize and prioritize this factual SEO dataset.\n" + json.dumps(payload),
                },
            ],
            text_format=OpportunityAnalysis,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise RuntimeError("OpenAI returned no parsed opportunity analysis")
        return OpportunityAnalysis.model_validate(parsed)
