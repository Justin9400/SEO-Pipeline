from typing import Protocol

from ..config import Site
from ..models import Collection
from ..periods import Period


class ProviderError(RuntimeError):
    """A sanitized, actionable provider failure."""


class SEOProvider(Protocol):
    def collect(self, site: Site, period: Period) -> Collection: ...
