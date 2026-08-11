from __future__ import annotations

from typing import Protocol

from seo_pipeline.models.provider import CollectedSEOData
from seo_pipeline.models.site import SiteConfig
from seo_pipeline.periods import PeriodWindow


class ProviderError(RuntimeError):
    """A provider could not collect usable SEO data."""


class SEOProvider(Protocol):
    name: str

    def collect(self, site: SiteConfig, period: PeriodWindow) -> CollectedSEOData:
        """Collect and normalize one site's data for one reporting period."""

