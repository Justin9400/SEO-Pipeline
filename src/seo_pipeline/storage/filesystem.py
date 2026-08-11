from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from seo_pipeline.models.snapshot import SEOSnapshot
from seo_pipeline.utils import atomic_write_json


class FileSystemSnapshotStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, domain: str, period_key: str) -> Path:
        return self.root / domain / period_key / "seo-data.json"

    def save(self, snapshot: SEOSnapshot) -> None:
        period_key = snapshot.reporting_period.start.strftime("%Y-%m")
        atomic_write_json(
            self._path(snapshot.site.domain, period_key),
            snapshot.model_dump(mode="json"),
        )

    def list(self, domain: str) -> list[SEOSnapshot]:
        directory = self.root / domain
        if not directory.exists():
            return []
        snapshots: list[SEOSnapshot] = []
        for path in sorted(directory.glob("????-??/seo-data.json")):
            snapshots.append(
                SEOSnapshot.model_validate(json.loads(path.read_text(encoding="utf-8")))
            )
        return snapshots

    def load_previous(self, domain: str, before: date) -> SEOSnapshot | None:
        candidates = [
            snapshot
            for snapshot in self.list(domain)
            if snapshot.reporting_period.start < before
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda snapshot: snapshot.reporting_period.start)

