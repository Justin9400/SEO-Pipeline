from __future__ import annotations

from pathlib import Path

import pytest

from seo_pipeline.analysis.comparison import build_snapshot
from seo_pipeline.analysis.openai_analysis import deterministic_analysis
from seo_pipeline.analysis.opportunities import detect_opportunities
from seo_pipeline.config import load_config
from seo_pipeline.models.site import SiteConfig
from seo_pipeline.periods import resolve_period
from seo_pipeline.providers.mock import MockSEOProvider


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def example_site() -> SiteConfig:
    return load_config(PROJECT_ROOT / "config" / "sites.yaml").select_sites("example")[0]


@pytest.fixture
def example_snapshot(example_site: SiteConfig):
    config = load_config(PROJECT_ROOT / "config" / "sites.yaml")
    provider = MockSEOProvider()
    period = resolve_period("2026-07")
    current = provider.collect(example_site, period)
    previous = provider.collect(example_site, resolve_period("2026-06"))
    snapshot = build_snapshot(
        site=example_site,
        period=period,
        current=current,
        previous=previous,
        candidates=[],
        analysis=deterministic_analysis({}, []),
    )
    candidates = detect_opportunities(snapshot.keywords, snapshot.pages, config.opportunities)
    return snapshot.model_copy(
        update={
            "opportunity_candidates": candidates,
            "analysis": deterministic_analysis(snapshot.metrics, candidates),
        }
    )

