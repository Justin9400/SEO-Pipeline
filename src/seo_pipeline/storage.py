import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

from .config import Site
from .models import Snapshot
from .periods import Period


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as f:
            name = f.name
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


class SnapshotStore(Protocol):
    def save(self, snapshot: Snapshot) -> None: ...
    def load_previous(self, site: Site, period: Period) -> Snapshot | None: ...
    def list(self, site: Site) -> list[Path]: ...


class FileStore:
    def __init__(self, root: Path, provider: str):
        self.root = root / provider

    def path(self, domain: str, month: str) -> Path:
        return self.root / domain / month / "seo-data.json"

    def save(self, snapshot: Snapshot) -> None:
        atomic_text(
            self.path(snapshot.site.domain, snapshot.reporting_period.key),
            snapshot.model_dump_json(indent=2),
        )

    def load_previous(self, site: Site, period: Period) -> Snapshot | None:
        path = self.path(site.domain, period.previous_start.strftime("%Y-%m"))
        if not path.exists():
            return None
        snapshot = Snapshot.model_validate_json(path.read_text(encoding="utf-8"))
        if (
            snapshot.site != site
            or snapshot.reporting_period.start != period.previous_start
            or snapshot.reporting_period.end != period.previous_end
            or snapshot.collection.provider != self.root.name
        ):
            raise ValueError(
                "Previous snapshot identity, period, or search configuration mismatch"
            )
        return snapshot

    def list(self, site: Site) -> list[Path]:
        return sorted((self.root / site.domain).glob("????-??/seo-data.json"))


def save_json(path: Path, value: dict) -> None:
    atomic_text(path, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))
