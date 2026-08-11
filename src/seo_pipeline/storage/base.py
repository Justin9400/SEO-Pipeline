from __future__ import annotations

from datetime import date
from typing import Protocol

from seo_pipeline.models.snapshot import SEOSnapshot


class SnapshotStore(Protocol):
    def save(self, snapshot: SEOSnapshot) -> None: ...

    def load_previous(self, domain: str, before: date) -> SEOSnapshot | None: ...

    def list(self, domain: str) -> list[SEOSnapshot]: ...

