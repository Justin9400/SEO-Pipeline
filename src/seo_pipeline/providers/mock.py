from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from seo_pipeline.models.provider import CollectedSEOData
from seo_pipeline.models.site import SiteConfig
from seo_pipeline.periods import PeriodWindow
from seo_pipeline.providers.base import ProviderError


class MockSEOProvider:
    name = "mock"

    def __init__(self, fixture_root: Path | None = None) -> None:
        self.fixture_root = fixture_root

    def _fixture_text(self, site_id: str, period_key: str) -> str:
        relative = Path(site_id) / f"{period_key}.json"
        if self.fixture_root is not None:
            path = self.fixture_root / relative
            try:
                return path.read_text(encoding="utf-8")
            except FileNotFoundError as exc:
                raise ProviderError(f"mock fixture not found: {path}") from exc
        resource = files("seo_pipeline").joinpath("fixtures", "mock", *relative.parts)
        try:
            return resource.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ProviderError(
                f"mock fixture not found for site {site_id!r}, period {period_key}"
            ) from exc

    def collect(self, site: SiteConfig, period: PeriodWindow) -> CollectedSEOData:
        raw = json.loads(self._fixture_text(site.id, period.key))
        data = CollectedSEOData.model_validate(raw)
        if data.period_start != period.start or data.period_end != period.end:
            raise ProviderError(
                f"mock fixture dates for {site.id!r} do not match requested period {period.key}"
            )
        return data

