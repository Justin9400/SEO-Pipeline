from __future__ import annotations

from pathlib import Path

from seo_pipeline.analysis.openai_analysis import OpenAIAnalyzer
from seo_pipeline.config import load_config
from seo_pipeline.models.site import SiteConfig
from seo_pipeline.periods import resolve_period
from seo_pipeline.pipeline import PipelineRunner
from seo_pipeline.providers.base import ProviderError
from seo_pipeline.providers.mock import MockSEOProvider
from seo_pipeline.storage.filesystem import FileSystemSnapshotStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StubRenderer:
    def render_pdf(self, snapshot, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4\n% test fixture\n")


def _runner(tmp_path: Path, provider) -> PipelineRunner:
    config = load_config(PROJECT_ROOT / "config" / "sites.yaml")
    return PipelineRunner(
        provider=provider,
        store=FileSystemSnapshotStore(tmp_path / "data"),
        output_root=tmp_path / "output",
        opportunity_settings=config.opportunities,
        analyzer=OpenAIAnalyzer(api_key=""),
        renderer=StubRenderer(),
    )


def test_mock_multi_site_run_creates_three_artifacts_per_site(tmp_path: Path) -> None:
    config = load_config(PROJECT_ROOT / "config" / "sites.yaml")
    results = _runner(tmp_path, MockSEOProvider()).run(
        config.select_sites("all"), resolve_period("2026-07")
    )
    assert all(result.success for result in results)
    for domain in ("example.com", "secondsite.com"):
        directory = tmp_path / "output" / domain / "2026-07"
        assert {path.name for path in directory.iterdir()} == {
            "seo-data.json",
            "seo-opportunities.md",
            "seo-performance-report.pdf",
        }


class OneSiteFailsProvider(MockSEOProvider):
    def collect(self, site: SiteConfig, period):
        if site.id == "second-site":
            raise ProviderError("simulated provider failure")
        return super().collect(site, period)


def test_provider_failure_is_isolated_between_sites(tmp_path: Path) -> None:
    config = load_config(PROJECT_ROOT / "config" / "sites.yaml")
    results = _runner(tmp_path, OneSiteFailsProvider()).run(
        config.select_sites("all"), resolve_period("2026-07")
    )
    assert results[0].success is True
    assert results[1].success is False
    assert (tmp_path / "output" / "example.com" / "2026-07" / "seo-data.json").exists()
    assert not (tmp_path / "output" / "secondsite.com" / "2026-07").exists()


def test_mock_provider_validates_fixture_period(example_site: SiteConfig) -> None:
    data = MockSEOProvider().collect(example_site, resolve_period("2026-07"))
    assert data.search_console.clicks == 6482
    assert data.estimated_organic_traffic == 12340

