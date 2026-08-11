from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from seo_pipeline.models.site import PipelineConfig


class ConfigurationError(ValueError):
    """Raised when the sites configuration cannot be loaded or validated."""


def load_config(path: Path) -> PipelineConfig:
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"configuration file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"invalid YAML in {path}: {exc}") from exc
    if raw is None:
        raise ConfigurationError(f"configuration file is empty: {path}")
    try:
        return PipelineConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(f"invalid site configuration in {path}:\n{exc}") from exc

