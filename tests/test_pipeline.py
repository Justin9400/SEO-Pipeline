import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from seo_pipeline.analysis import analyze, buckets, candidates, delta, movements
from seo_pipeline.cli import main
from seo_pipeline.config import Config, Scoring, Site, load_config
from seo_pipeline.models import Collection, OpportunityAnalysis, Row, Snapshot
from seo_pipeline.openai_analysis import run_analysis, validate_analysis
from seo_pipeline.periods import month_period
from seo_pipeline.providers import ProviderError
from seo_pipeline.providers.mock import MockProvider
from seo_pipeline.reports import (
    customer_html,
    deny_resources,
    internal_markdown,
    render_pdf,
)
from seo_pipeline.storage import FileStore


@pytest.fixture
def pair():
    site = Site(id="example", name="Example Company", domain="example.com")
    provider = MockProvider()
    previous = Snapshot(
        site=site,
        reporting_period=month_period("2026-06"),
        collection=provider.collect(site, month_period("2026-06")),
    )
    current = Snapshot(
        site=site,
        reporting_period=month_period("2026-07"),
        collection=provider.collect(site, month_period("2026-07")),
    )
    analyze(current, previous, Scoring(low_ctr=0.02))
    return current, previous


def test_configuration():
    config = load_config(Path("config/sites.yaml"))
    assert len(config.sites) == 1
    assert config.sites[0].id == "edwardscapes"
    assert config.sites[0].domain == "edwardscapes.com"
    assert config.sites[0].search.location_code == 2840


@pytest.mark.parametrize(
    "domain",
    [
        "https://example.com",
        "../example.com",
        "x",
        "example.com:80",
        "bad_.com",
        "-bad.com",
    ],
)
def test_invalid_domains(domain):
    with pytest.raises(ValidationError):
        Site(id="test", name="Test", domain=domain)


def test_duplicate_configuration():
    site = Site(id="test", name="Test", domain="example.com")
    with pytest.raises(ValidationError, match="Duplicate"):
        Config(sites=[site, site])
    with pytest.raises(ValidationError):
        Scoring(high=20, medium=30)


@pytest.mark.parametrize(
    "today,expected,end",
    [
        (date(2026, 1, 5), "2025-12", date(2025, 12, 31)),
        (date(2024, 3, 1), "2024-02", date(2024, 2, 29)),
        (date(2026, 8, 1), "2026-07", date(2026, 7, 31)),
    ],
)
def test_month_boundaries(today, expected, end):
    period = month_period(today=today)
    assert period.key == expected and period.end == end
    assert period.previous_end < period.start


def test_explicit_current_and_future():
    assert month_period("2026-07", date(2026, 7, 15)).end == date(2026, 7, 15)
    for value in ["2026-08", "2026-7", "2026-13"]:
        with pytest.raises(ValueError):
            month_period(value, date(2026, 7, 15))


@pytest.mark.parametrize(
    "current,previous,expected",
    [
        (125, 100, (25, 25)),
        (0, 100, (-100, -100)),
        (10, 0, (10, None)),
        (0, 0, (0, None)),
        (None, 10, (None, None)),
        (10, None, (None, None)),
    ],
)
def test_deltas(current, previous, expected):
    assert delta(current, previous) == expected


def test_trends_and_buckets(pair):
    s, _ = pair
    by = {r.key: r for r in s.keywords}
    assert by["commercial widget installation"].position_improvement == 3
    assert by["widget maintenance"].status == "DECLINED"
    assert by["widget maintenance"].position_improvement == -5
    assert by["energy efficient widgets"].status == "NEW"
    assert by["legacy widget parts"].status == "LOST"
    assert by["example company"].status == "UNCHANGED"
    assert s.keyword_distribution == {
        "Top 3": 1,
        "Top 10": 2,
        "11-20": 3,
        "21-50": 1,
        "51-100": 1,
    }
    assert s.metrics["average_position"].position_improvement == 1.2
    assert s.metrics["ctr"].percentage_point_change == 0.159


def test_missing_and_truncated_not_lost():
    row = Row(key="widget", source="openseo", position=12)
    assert movements(None, [row])[0].status == "UNKNOWN"
    assert movements([], [row], False, True)[0].status == "UNKNOWN"
    assert movements([row], None)[0].status == "UNKNOWN"
    assert buckets(None) is None
    assert buckets([])["Top 3"] == 0


def test_complete_empty_keyword_comparison(pair):
    current, previous = pair
    current.collection.keywords = []
    previous.collection.keywords = []
    analyze(current, previous, Scoring())
    assert current.keyword_comparison_available
    assert all(not rows for rows in current.trends.values())


def test_scoring_and_opportunities(pair):
    s, _ = pair
    types = {c.opportunity_type for c in s.candidates}
    assert {
        "STRIKING_DISTANCE",
        "LOW_CTR",
        "IMPROVED",
        "DECLINED",
        "NEW",
        "LOST",
        "PAGE_GAIN",
        "PAGE_LOSS",
    } <= types
    for c in s.candidates:
        assert c.score == min(100, sum(c.score_components.values()))
    assert not any(
        c.opportunity_type == "LOW_CTR" for c in candidates(s.queries, Scoring())
    )


def test_serialization_schema(pair):
    s, _ = pair
    assert Snapshot.model_validate_json(s.model_dump_json()) == s
    assert (
        Snapshot.model_json_schema()["properties"]["schema_version"]["const"] == "1.0"
    )
    with pytest.raises(ValidationError):
        Row(key="bad", source="mock", position=0)
    with pytest.raises(ValidationError):
        Row(key="bad", source="mock", ctr=float("nan"))


def test_previous_lookup(tmp_path, pair):
    current, previous = pair
    store = FileStore(tmp_path, "mock")
    assert store.load_previous(current.site, current.reporting_period) is None
    store.save(previous)
    assert store.load_previous(current.site, current.reporting_period) == previous
    assert len(store.list(current.site)) == 1
    assert (
        FileStore(tmp_path, "openseo").load_previous(
            current.site, current.reporting_period
        )
        is None
    )
    bad = current.site.model_copy(update={"name": "Changed"})
    with pytest.raises(ValueError, match="mismatch"):
        store.load_previous(bad, current.reporting_period)


def test_reports_escape_missing(pair):
    current, _ = pair
    current.site.name = '<script>alert("x")</script>'
    html = customer_html(current)
    assert "&lt;script&gt;" in html and "<script>" not in html
    assert "Estimated organic traffic" in html and "DEMONSTRATION" in html
    md = internal_markdown(current)
    assert "SEO_DIRECTION: POSITIVE" in md and "Position Improvement: 3" in md
    assert "Evidence ID:" in md and "Recommended investigation" in md
    current.collection = Collection(provider="mock")
    current.metrics = {}
    current.queries = []
    current.pages = []
    current.keyword_distribution = None
    assert "Not available" in customer_html(current)
    with pytest.raises(ValueError):
        deny_resources("file:///secret")


def test_pdf_real_text(tmp_path, pair):
    import pymupdf

    path = tmp_path / "report.pdf"
    render_pdf(customer_html(pair[0]), path)
    with pymupdf.open(path) as doc:
        text = "\n".join(p.get_text() for p in doc)
        assert "SEO performance" in text
        assert "Data sources" in text
        assert "SEO improvement recommendations" in text
        assert "Recommended action:" in text
        assert pair[0].candidates[0].evidence.key in text
        assert 3 <= len(doc) <= 6


def test_mock_multisite(tmp_path):
    args = [
        "report",
        "--config",
        "tests/fixtures/sites.yaml",
        "--site",
        "all",
        "--provider",
        "mock",
        "--period",
        "2026-07",
        "--output-dir",
        str(tmp_path / "out"),
        "--data-dir",
        str(tmp_path / "data"),
    ]
    assert main(args) == 0
    for domain in ["example.com", "secondsite.com"]:
        folder = tmp_path / "out" / "mock" / domain / "2026-07"
        assert all(
            (folder / name).exists()
            for name in [
                "seo-data.json",
                "seo-performance-report.pdf",
                "seo-opportunities.md",
            ]
        )
        assert (
            json.loads((folder / "seo-data.json").read_text())["analysis_status"]
            == "not_requested"
        )


def test_site_isolation(tmp_path, monkeypatch):
    original = MockProvider.collect

    def collect(self, site, period):
        if site.id == "example":
            raise ProviderError("Simulated failure")
        return original(self, site, period)

    monkeypatch.setattr(MockProvider, "collect", collect)
    assert (
        main(
            [
                "report",
                "--config",
                "tests/fixtures/sites.yaml",
                "--dry-run",
                "--period",
                "2026-07",
                "--output-dir",
                str(tmp_path / "out"),
                "--data-dir",
                str(tmp_path / "data"),
            ]
        )
        == 1
    )
    assert (
        tmp_path / "out/mock/secondsite.com/2026-07/seo-performance-report.pdf"
    ).exists()


def test_render_failure_preserves_data(tmp_path, monkeypatch):
    import seo_pipeline.cli as cli

    monkeypatch.setattr(
        cli,
        "write_reports",
        lambda *args: (_ for _ in ()).throw(RuntimeError("secret must not be logged")),
    )
    assert (
        main(
            [
                "report",
                "--config",
                "tests/fixtures/sites.yaml",
                "--site",
                "example",
                "--provider",
                "mock",
                "--period",
                "2026-07",
                "--output-dir",
                str(tmp_path / "out"),
                "--data-dir",
                str(tmp_path / "data"),
            ]
        )
        == 1
    )
    assert (tmp_path / "out/mock/example.com/2026-07/seo-data.json").exists()


def test_structured_analysis_and_reference_validation(pair):
    s, _ = pair
    analysis = OpportunityAnalysis(
        executive_summary="Visibility is improving, with areas to investigate.",
        overall_direction=s.direction,
        wins=[],
        risks=[],
        opportunities=[],
    )
    captured = {}

    def parse(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(output_parsed=analysis)

    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    assert run_analysis(s, client) == analysis
    assert captured["text_format"] is OpportunityAnalysis
    analysis.wins = ["invented"]
    with pytest.raises(ValueError):
        validate_analysis(analysis, s)
    analysis.wins = []
    analysis.executive_summary = "Clicks rose 999%."
    with pytest.raises(ValueError):
        validate_analysis(analysis, s)


def test_bad_config_cli(tmp_path):
    config = tmp_path / "bad.yaml"
    config.write_text("sites: [invalid")
    assert main(["report", "--config", str(config)]) == 2


def test_customer_recommendations_without_model(pair):
    current, _ = pair
    assert current.analysis is None
    html = customer_html(current)
    assert "SEO improvement recommendations" in html
    assert html.count("Recommended action:") == 5
    candidate = current.candidates[0]
    assert candidate.reason in html
    candidate.evidence.key = "<script>unsafe</script>"
    html = customer_html(current)
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in html
    assert "<script>" not in html
    current.candidates = []
    assert "No supported improvement candidates" in customer_html(current)
