from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from seo_pipeline.analysis.comparison import build_snapshot, snapshot_to_collected
from seo_pipeline.analysis.openai_analysis import OpenAIAnalyzer, deterministic_analysis
from seo_pipeline.analysis.opportunities import detect_opportunities
from seo_pipeline.models.analysis import OpportunityAnalysis
from seo_pipeline.models.provider import CollectedSEOData
from seo_pipeline.models.site import OpportunitySettings, SiteConfig
from seo_pipeline.models.snapshot import SEOSnapshot
from seo_pipeline.periods import PeriodWindow, resolve_period
from seo_pipeline.providers.base import SEOProvider
from seo_pipeline.reports import CustomerReportRenderer, render_internal_markdown
from seo_pipeline.storage.base import SnapshotStore
from seo_pipeline.utils import atomic_write_json, atomic_write_text


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SiteRunResult:
    site_id: str
    domain: str
    success: bool
    output_directory: Path | None = None
    error: str | None = None


class PipelineRunner:
    def __init__(
        self,
        *,
        provider: SEOProvider,
        store: SnapshotStore,
        output_root: Path,
        opportunity_settings: OpportunitySettings,
        analyzer: OpenAIAnalyzer | None = None,
        renderer: CustomerReportRenderer | None = None,
    ) -> None:
        self.provider = provider
        self.store = store
        self.output_root = output_root
        self.opportunity_settings = opportunity_settings
        self.analyzer = analyzer or OpenAIAnalyzer(api_key=None)
        self.renderer = renderer or CustomerReportRenderer()

    def _previous_data(
        self, site: SiteConfig, period: PeriodWindow
    ) -> CollectedSEOData | None:
        stored = self.store.load_previous(site.domain, period.start)
        if stored is not None:
            return snapshot_to_collected(stored)
        if self.provider.name == "mock":
            previous_period = resolve_period(period.previous_start.strftime("%Y-%m"))
            return self.provider.collect(site, previous_period)
        return None

    def run_site(self, site: SiteConfig, period: PeriodWindow) -> SiteRunResult:
        context = {
            "site_id": site.id,
            "domain": site.domain,
            "period": period.key,
            "provider": self.provider.name,
        }
        LOGGER.info("starting site report", extra=context)
        try:
            current = self.provider.collect(site, period)
            previous = self._previous_data(site, period)
            placeholder = deterministic_analysis({}, [])
            snapshot = build_snapshot(
                site=site,
                period=period,
                current=current,
                previous=previous,
                candidates=[],
                analysis=placeholder,
            )
            candidates = detect_opportunities(
                snapshot.keywords,
                snapshot.pages,
                self.opportunity_settings,
            )
            analysis: OpportunityAnalysis
            try:
                analysis = self.analyzer.analyze(
                    site=snapshot.site.model_dump(mode="json"),
                    reporting_period=snapshot.reporting_period.model_dump(mode="json"),
                    metrics=snapshot.metrics,
                    candidates=candidates,
                )
            except Exception as exc:
                LOGGER.warning("OpenAI analysis failed; using deterministic fallback: %s", exc, extra=context)
                analysis = deterministic_analysis(snapshot.metrics, candidates)
                snapshot.warnings.append(
                    f"OpenAI analysis failed ({type(exc).__name__}); deterministic fallback was used."
                )
            snapshot = snapshot.model_copy(
                update={"opportunity_candidates": candidates, "analysis": analysis}
            )

            output_directory = self.output_root / site.domain / period.key
            output_directory.mkdir(parents=True, exist_ok=True)
            json_path = output_directory / "seo-data.json"
            markdown_path = output_directory / "seo-opportunities.md"
            pdf_path = output_directory / "seo-performance-report.pdf"

            # Persist the factual source of truth before rendering either report.
            atomic_write_json(json_path, snapshot.model_dump(mode="json"))
            self.store.save(snapshot)
            atomic_write_text(markdown_path, render_internal_markdown(snapshot))
            self.renderer.render_pdf(snapshot, pdf_path)
            LOGGER.info("completed site report", extra=context)
            return SiteRunResult(
                site_id=site.id,
                domain=site.domain,
                success=True,
                output_directory=output_directory,
            )
        except Exception as exc:
            LOGGER.exception("site report failed", extra=context)
            return SiteRunResult(
                site_id=site.id,
                domain=site.domain,
                success=False,
                error=str(exc),
            )

    def run(self, sites: list[SiteConfig], period: PeriodWindow) -> list[SiteRunResult]:
        return [self.run_site(site, period) for site in sites]

