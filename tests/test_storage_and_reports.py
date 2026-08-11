from __future__ import annotations

import json
from pathlib import Path

from seo_pipeline.models.snapshot import SEOSnapshot
from seo_pipeline.reports.customer import CustomerReportRenderer
from seo_pipeline.reports.internal import render_internal_markdown
from seo_pipeline.storage.filesystem import FileSystemSnapshotStore


def test_json_serialization_and_schema_validation(example_snapshot: SEOSnapshot) -> None:
    payload = example_snapshot.model_dump_json()
    reloaded = SEOSnapshot.model_validate_json(payload)
    assert reloaded.schema_version == "1.0"
    assert reloaded.site.domain == "example.com"


def test_previous_snapshot_lookup(tmp_path: Path, example_snapshot: SEOSnapshot) -> None:
    store = FileSystemSnapshotStore(tmp_path)
    store.save(example_snapshot)
    found = store.load_previous("example.com", example_snapshot.reporting_period.end.replace(day=31))
    assert found is not None
    assert found.reporting_period.start == example_snapshot.reporting_period.start


def test_customer_html_generation(example_snapshot: SEOSnapshot) -> None:
    html = CustomerReportRenderer().render_html(example_snapshot)
    assert "SEO PERFORMANCE REPORT" in html
    assert "Estimated Organic Traffic" in html
    assert "Not available" in html
    assert "Google Search Console (first-party)" in html


def test_internal_markdown_is_structured(example_snapshot: SEOSnapshot) -> None:
    markdown = render_internal_markdown(example_snapshot)
    assert markdown.startswith("# SEO Trends & Opportunities")
    assert "SEO_DIRECTION:" in markdown
    assert "Opportunity Type: STRIKING_DISTANCE" in markdown
    assert "### Evidence" in markdown
    assert "Interpretation Guardrails" in markdown


def test_snapshot_file_is_valid_json(tmp_path: Path, example_snapshot: SEOSnapshot) -> None:
    store = FileSystemSnapshotStore(tmp_path)
    store.save(example_snapshot)
    path = tmp_path / "example.com" / "2026-07" / "seo-data.json"
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == "1.0"

