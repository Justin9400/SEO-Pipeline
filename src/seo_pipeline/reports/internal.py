from __future__ import annotations

import json
from typing import Any

from seo_pipeline.models.snapshot import ComparisonMetric, SEOSnapshot


def _value(value: Any) -> str:
    if value is None:
        return "Not available"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _metric_line(label: str, metric: ComparisonMetric) -> str:
    if metric.current is None:
        return f"{label}: Not available"
    if metric.unit == "position" and metric.absolute_change is not None:
        movement = abs(metric.absolute_change)
        return f"{label}: {metric.direction} {movement:.2f} positions (current {metric.current:.2f})"
    if metric.unit == "percent":
        current = f"{metric.current * 100:.2f}%"
        delta = (
            f"{metric.absolute_change * 100:+.2f} percentage points"
            if metric.absolute_change is not None
            else "comparison unavailable"
        )
        return f"{label}: {current} ({delta})"
    delta = (
        f"{metric.percent_change:+.2f}%"
        if metric.percent_change is not None
        else "comparison unavailable"
    )
    return f"{label}: {_value(metric.current)} ({delta})"


def render_internal_markdown(snapshot: SEOSnapshot) -> str:
    period = snapshot.reporting_period
    sources = [
        str(source.get("name", "unknown"))
        for source in snapshot.data_sources
        if source.get("available", True)
    ]
    lines = [
        "# SEO Trends & Opportunities",
        "",
        f"Domain: {snapshot.site.domain}",
        f"Site ID: {snapshot.site.id}",
        "",
        f"Analysis Period: {period.start.isoformat()} through {period.end.isoformat()}",
        f"Comparison Period: {period.previous_start.isoformat()} through {period.previous_end.isoformat()}",
        "",
        "Data Sources:",
        *[f"- {source}" for source in sources],
        "",
        f"Schema Version: {snapshot.schema_version}",
        "",
        "## Overall Trend",
        "",
        f"SEO_DIRECTION: {snapshot.analysis.overall_direction.value}",
        "",
        _metric_line("Organic clicks", snapshot.metrics["organic_clicks"]),
        _metric_line("Organic impressions", snapshot.metrics["organic_impressions"]),
        _metric_line("Organic CTR", snapshot.metrics["organic_ctr"]),
        _metric_line("Average position", snapshot.metrics["average_position"]),
        _metric_line("Estimated organic traffic", snapshot.metrics["estimated_organic_traffic"]),
        _metric_line("Ranking keywords", snapshot.metrics["ranking_keywords"]),
        "",
        "### Analysis Summary",
        "",
        snapshot.analysis.executive_summary,
        "",
        "## Deterministic Trend Counts",
        "",
        f"- new_keywords: {snapshot.trends.new}",
        f"- lost_keywords: {snapshot.trends.lost}",
        f"- improving_keywords: {snapshot.trends.improving}",
        f"- declining_keywords: {snapshot.trends.declining}",
        f"- unchanged_keywords: {snapshot.trends.unchanged}",
        "",
        "## Prioritized Opportunities",
        "",
    ]
    if not snapshot.opportunity_candidates:
        lines.extend(["No deterministic opportunity candidates met the configured rules.", ""])
    for index, candidate in enumerate(snapshot.opportunity_candidates, start=1):
        lines.extend(
            [
                f"## Opportunity {index}",
                "",
                f"Candidate ID: {candidate.candidate_id}",
                f"Priority: {candidate.priority.value}",
                f"Opportunity Type: {candidate.opportunity_type}",
                f"Score: {candidate.score}/100",
                "",
                f"Title: {candidate.title}",
            ]
        )
        if candidate.keyword:
            lines.append(f"Keyword: {candidate.keyword}")
        if candidate.url:
            lines.append(f"Ranking URL: {candidate.url}")
        lines.extend(["", "### Why this matters", "", candidate.why_flagged, "", "### Evidence", ""])
        for key, value in candidate.evidence.items():
            lines.append(f"- {key}: {_value(value)}")
        lines.extend(["", "### Explainable score", ""])
        for component in candidate.score_components:
            lines.append(f"- {component.factor}: +{component.points} - {component.explanation}")
        lines.extend(["", "### Recommended investigation", ""])
        lines.extend(f"- {item}" for item in candidate.recommended_investigation)
        lines.append("")

    lines.extend(["## Model Contextualization", "", "### Wins", ""])
    lines.extend([f"- {item}" for item in snapshot.analysis.wins] or ["- None identified from available evidence."])
    lines.extend(["", "### Risks", ""])
    lines.extend([f"- {item}" for item in snapshot.analysis.risks] or ["- None identified from available evidence."])
    lines.extend(["", "### Structured model opportunities", ""])
    for opportunity in snapshot.analysis.opportunities:
        lines.extend(
            [
                f"- [{opportunity.priority.value}] {opportunity.title}",
                f"  - type: {opportunity.opportunity_type}",
                f"  - explanation: {opportunity.explanation}",
                f"  - evidence_references: {', '.join(opportunity.evidence_references)}",
                f"  - objective: {opportunity.objective}",
                f"  - recommended_investigation: {json.dumps(opportunity.recommended_investigation, ensure_ascii=False)}",
            ]
        )
    if not snapshot.analysis.opportunities:
        lines.append("- None generated.")
    lines.extend(["", "## Data Availability Warnings", ""])
    lines.extend([f"- {warning}" for warning in snapshot.warnings] or ["- None."])
    lines.extend(
        [
            "",
            "## Interpretation Guardrails",
            "",
            "- OpenSEO traffic and keyword totals are estimates, not first-party traffic measurements.",
            "- Google Search Console clicks, impressions, CTR, and position are first-party metrics when available.",
            "- Candidate scores prioritize investigation; they do not prove causation or a specific on-page defect.",
            "- This pipeline does not inspect or modify website source code.",
            "",
        ]
    )
    return "\n".join(lines)

