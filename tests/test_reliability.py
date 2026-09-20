import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

import seo_pipeline.cli as cli
from seo_pipeline.config import Config, Site
from seo_pipeline.models import Snapshot
from seo_pipeline.periods import month_period
from seo_pipeline.providers import ProviderError
from seo_pipeline.providers.mock import MockProvider
from seo_pipeline.providers.openseo import MCPReader, OpenSEOProvider


def test_openai_failure_keeps_factual_outputs(tmp_path, monkeypatch, capsys):
    def fake_collect(self, site, period, **kwargs):
        result = MockProvider().collect(site, period)
        result.provider = "openseo"
        return result

    def failed_analysis(snapshot):
        raise RuntimeError("SECRET-DO-NOT-LOG")

    monkeypatch.setattr(OpenSEOProvider, "collect", fake_collect)
    monkeypatch.setattr(cli, "run_analysis", failed_analysis)
    assert (
        cli.main(
            [
                "report",
                "--site",
                "example",
                "--period",
                "2026-07",
                "--data-dir",
                str(tmp_path / "data"),
                "--output-dir",
                str(tmp_path / "out"),
            ]
        )
        == 0
    )
    folder = tmp_path / "out/openseo/example.com/2026-07"
    snapshot = Snapshot.model_validate_json((folder / "seo-data.json").read_text())
    assert snapshot.analysis_status == "unavailable_factual_fallback"
    assert (folder / "seo-performance-report.pdf").exists()
    assert "SECRET-DO-NOT-LOG" not in capsys.readouterr().err


def test_backfill_never_uses_live_observations(tmp_path):
    site = Site(
        id="example",
        name="Example",
        domain="example.com",
        openseo_project_id="p",
        gsc_enabled=False,
    )

    class Reader:
        async def call(self, *args):
            pytest.fail("Backfill must not call a paid live tool")

    with pytest.raises(ProviderError, match="No usable"):
        asyncio.run(
            OpenSEOProvider(Config(sites=[site]), tmp_path).collect_with_reader(
                Reader(), site, month_period(), historical=True
            )
        )


@pytest.mark.parametrize("wrong", ["property", "period", "cursor"])
def test_gsc_rejects_mismatched_responses(tmp_path, wrong):
    site = Site(
        id="example", name="Example", domain="example.com", openseo_project_id="p"
    )

    class Reader:
        async def call(self, name, args):
            return {
                "ok": True,
                "siteUrl": "sc-domain:other.com"
                if wrong == "property"
                else "sc-domain:example.com",
                "startDate": "2020-01-01" if wrong == "period" else args["startDate"],
                "endDate": args["endDate"],
                "dimensions": args["dimensions"],
                "rows": [],
                "hasMore": wrong == "cursor",
                "nextStartRow": 0,
            }

    with pytest.raises(ProviderError, match="No usable"):
        asyncio.run(
            OpenSEOProvider(Config(sites=[site]), tmp_path).collect_with_reader(
                Reader(), site, month_period("2026-07"), historical=True
            )
        )


def test_paginated_gsc_and_sampling(tmp_path):
    site = Site(
        id="example", name="Example", domain="example.com", openseo_project_id="p"
    )

    class Reader:
        async def call(self, name, args):
            offset = args["startRow"]
            dimension = args["dimensions"][0]
            return {
                "ok": True,
                "siteUrl": "sc-domain:example.com",
                "startDate": args["startDate"],
                "endDate": args["endDate"],
                "dimensions": [dimension],
                "rows": [
                    {
                        "keys": [f"row-{offset}"],
                        "clicks": 5,
                        "impressions": 50,
                        "ctr": 0.1,
                        "position": 4,
                    }
                ],
                "hasMore": offset == 0,
                "nextStartRow": offset + 1,
            }

    result = asyncio.run(
        OpenSEOProvider(Config(sites=[site]), tmp_path).collect_with_reader(
            Reader(), site, month_period("2026-07"), historical=True
        )
    )
    assert len(result.queries) == 2 and result.metrics["clicks"].value == 10
    assert not result.queries_complete and result.pages_complete


def test_transient_retry_and_timeout_cost_safety(tmp_path, monkeypatch):
    calls = []

    async def no_wait(delay):
        pass

    monkeypatch.setattr(asyncio, "sleep", no_wait)

    class Session:
        async def call_tool(self, name, args):
            calls.append(name)
            if len(calls) == 1:
                response = httpx.Response(
                    503, request=httpx.Request("POST", "https://app.openseo.so/mcp")
                )
                raise httpx.HTTPStatusError(
                    "unavailable", request=response.request, response=response
                )
            return SimpleNamespace(
                isError=False, structuredContent={"organicTraffic": 1}
            )

    async def run():
        reader = MCPReader(Session(), tmp_path)
        reader.schemas = {"get_domain_overview": {"type": "object"}}
        await reader.call("get_domain_overview", {})
        assert len(calls) == 2

        class TimeoutSession:
            async def call_tool(self, *args):
                calls.append("timeout")
                raise httpx.ReadTimeout("ambiguous completion")

        reader = MCPReader(TimeoutSession(), tmp_path / "other")
        reader.schemas = {"get_domain_overview": {"type": "object"}}
        with pytest.raises(httpx.ReadTimeout):
            await reader.call("get_domain_overview", {})
        assert calls.count("timeout") == 1

    asyncio.run(run())


def test_default_month_collects_dated_live_estimates(tmp_path):
    site = Site(
        id="example",
        name="Example",
        domain="example.com",
        openseo_project_id="p",
        gsc_enabled=False,
    )

    class Reader:
        async def call(self, name, args):
            if name == "get_domain_overview":
                return {"organicTraffic": 100, "organicKeywords": 0}
            return {"keywords": [], "totalCount": 0}

    result = asyncio.run(
        OpenSEOProvider(Config(sites=[site]), tmp_path).collect_with_reader(
            Reader(), site, month_period()
        )
    )
    assert result.metrics["estimated_organic_traffic"].period_start is None
    assert (
        result.metrics["estimated_organic_traffic"].observed_at.date()
        == datetime.now(timezone.utc).date()
    )
    assert result.keywords_complete
