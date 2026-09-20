import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from seo_pipeline.config import Config, Site
from seo_pipeline.periods import month_period
from seo_pipeline.providers import ProviderError
from seo_pipeline.providers.openseo import MCPReader, OpenSEOProvider, ranked_row


def test_missing_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENSEO_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("OPENSEO_API_KEY", raising=False)
    site = Site(id="example", name="Example", domain="example.com")
    with pytest.raises(ProviderError, match="OPENSEO_ACCESS_TOKEN"):
        OpenSEOProvider(Config(sites=[site]), tmp_path).collect(
            site, month_period("2026-07")
        )


def test_nested_keyword_mapping():
    row = ranked_row(
        {
            "keyword_data": {
                "keyword": "widget",
                "keyword_info": {"search_volume": 2400, "cpc": 2.5},
            },
            "ranked_serp_element": {
                "serp_item": {
                    "rank_absolute": 12,
                    "url": "https://example.com/widget",
                    "etv": 34,
                }
            },
        }
    )
    assert row.position == 12 and row.search_volume == 2400
    assert row.keyword_difficulty is None


def test_reader_cache_allowlist_and_schema(tmp_path):
    calls = []

    class Session:
        async def call_tool(self, name, args):
            calls.append(name)
            return SimpleNamespace(
                isError=False, structuredContent={"organicTraffic": 50}
            )

    async def run():
        reader = MCPReader(Session(), tmp_path)
        reader.schemas = {
            "get_domain_overview": {"type": "object", "required": ["domain"]}
        }
        args = {"domain": "example.com"}
        assert (await reader.call("get_domain_overview", args))["organicTraffic"] == 50
        await reader.call("get_domain_overview", args)
        assert len(calls) == 1
        reader.memory.clear()
        await reader.call("get_domain_overview", args)
        assert len(calls) == 1
        with pytest.raises(ProviderError):
            await reader.call("save_keywords", {})
        with pytest.raises(ProviderError):
            await reader.call("get_domain_overview", {})

    asyncio.run(run())


def test_historical_gsc_aggregation_and_pagination(tmp_path):
    site = Site(
        id="example", name="Example", domain="example.com", openseo_project_id="project"
    )
    calls = []

    class Reader:
        async def call(self, name, args):
            calls.append((name, args))
            assert name == "get_search_console_performance"
            dim = args["dimensions"][0]
            rows = [
                {
                    "keys": [
                        "2026-07-01"
                        if dim == "date"
                        else "widget"
                        if dim == "query"
                        else "https://example.com/page"
                    ],
                    "clicks": 10,
                    "impressions": 100,
                    "ctr": 0.1,
                    "position": 5,
                }
            ]
            if dim == "date":
                rows.append(
                    {
                        "keys": ["2026-07-02"],
                        "clicks": 30,
                        "impressions": 300,
                        "ctr": 0.1,
                        "position": 9,
                    }
                )
            return {
                "ok": True,
                "siteUrl": "sc-domain:example.com",
                "startDate": args["startDate"],
                "endDate": args["endDate"],
                "dimensions": [dim],
                "rows": rows,
                "hasMore": False,
            }

    p = OpenSEOProvider(Config(sites=[site]), tmp_path)
    data = asyncio.run(p.collect_with_reader(Reader(), site, month_period("2026-07")))
    assert data.metrics["clicks"].value == 40
    assert data.metrics["average_position"].value == 8
    assert data.metrics["ctr"].value == 0.1
    assert data.keywords is None and not data.queries_complete
    assert len(calls) == 3
    assert all(c[1]["dataState"] == "final" for c in calls)


def test_point_observations_and_partial_failure(tmp_path):
    site = Site(
        id="example",
        name="Example",
        domain="example.com",
        openseo_project_id="project",
        gsc_enabled=False,
    )

    class Reader:
        async def call(self, name, args):
            if name == "get_domain_overview":
                return {
                    "organicTraffic": 1234,
                    "organicKeywords": 100,
                    "backlinks": None,
                    "referringDomains": 12,
                }
            raise ProviderError("Keywords failed")

    p = OpenSEOProvider(Config(sites=[site]), tmp_path)
    period = month_period(datetime.now(timezone.utc).strftime("%Y-%m"))
    data = asyncio.run(p.collect_with_reader(Reader(), site, period))
    metric = data.metrics["estimated_organic_traffic"]
    assert metric.temporal_basis == "point_in_time" and metric.period_start is None
    assert data.metrics["total_backlinks"].value is None
    assert data.keywords is None and data.warnings


def test_no_data_fails(tmp_path):
    site = Site(
        id="example", name="Example", domain="example.com", openseo_project_id="project"
    )

    class Reader:
        async def call(self, *args):
            return {"ok": False}

    with pytest.raises(ProviderError, match="No usable"):
        asyncio.run(
            OpenSEOProvider(Config(sites=[site]), tmp_path).collect_with_reader(
                Reader(), site, month_period("2026-07")
            )
        )
