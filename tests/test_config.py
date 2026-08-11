from __future__ import annotations

from pathlib import Path

import pytest

from seo_pipeline.config import ConfigurationError, load_config
from seo_pipeline.models.site import PipelineConfig, SiteConfig


def test_configuration_parsing(example_site: SiteConfig) -> None:
    assert example_site.domain == "example.com"
    assert example_site.search.country == "US"


def test_duplicate_site_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate site IDs"):
        PipelineConfig.model_validate(
            {
                "sites": [
                    {"id": "same", "name": "One", "domain": "one.example"},
                    {"id": "same", "name": "Two", "domain": "two.example"},
                ]
            }
        )


@pytest.mark.parametrize("domain", ["https://example.com", "example", "bad domain.com"])
def test_invalid_domains_are_rejected(domain: str) -> None:
    with pytest.raises(ValueError, match="domain"):
        SiteConfig(id="bad", name="Bad", domain=domain)


def test_malformed_yaml_has_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "sites.yaml"
    path.write_text("sites: [", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="invalid YAML"):
        load_config(path)


def test_site_selection_excludes_disabled() -> None:
    config = PipelineConfig.model_validate(
        {
            "sites": [
                {"id": "yes", "name": "Yes", "domain": "yes.example", "enabled": True},
                {"id": "no", "name": "No", "domain": "no.example", "enabled": False},
            ]
        }
    )
    assert [site.id for site in config.select_sites("all")] == ["yes"]
    with pytest.raises(ValueError, match="disabled"):
        config.select_sites("no")

