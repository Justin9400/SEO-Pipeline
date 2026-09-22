"""OpenSEO MCP adapter. See docs/provider-contract.md for verified contracts."""

import asyncio
import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import jsonschema
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, ConfigDict, Field

from ..config import Config, Site
from ..models import Collection, Metric, Row
from ..periods import Period, month_period
from ..storage import save_json
from . import ProviderError

ENDPOINT = "https://app.openseo.so/mcp"
ALLOWED = {
    "run_site_audit",
    "get_audit_status",
    "get_audit_issues",
    "get_domain_overview",
    "get_ranked_keywords",
    "get_search_console_performance",
}


class Overview(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    organicTraffic: float | None = Field(default=None, ge=0)
    organicKeywords: float | None = Field(default=None, ge=0)
    backlinks: float | None = Field(default=None, ge=0)
    referringDomains: float | None = Field(default=None, ge=0)


@asynccontextmanager
async def session_for(token: str):
    # Authentication is isolated here; no credentials ever enter config/cache keys.
    async with streamablehttp_client(
        ENDPOINT,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timedelta(seconds=30),
        sse_read_timeout=timedelta(seconds=60),
    ) as (read, write, _):
        async with ClientSession(
            read, write, read_timeout_seconds=timedelta(seconds=60)
        ) as session:
            await session.initialize()
            yield session


class MCPReader:
    def __init__(self, session: ClientSession, cache: Path):
        self.session, self.cache = session, cache
        self.schemas: dict[str, dict] = {}
        self.memory: dict[str, dict] = {}

    async def discover(self) -> None:
        cursor = None
        while True:
            result = await self.session.list_tools(cursor=cursor)
            self.schemas.update(
                {t.name: t.inputSchema for t in result.tools if t.name in ALLOWED}
            )
            cursor = result.nextCursor
            if not cursor:
                break

    async def call(self, name: str, args: dict) -> dict:
        if name not in ALLOWED or name not in self.schemas:
            raise ProviderError(
                f"Required tool {name} is unavailable; verify OpenSEO account scopes/server version"
            )
        try:
            jsonschema.validate(args, self.schemas[name])
        except jsonschema.ValidationError:
            raise ProviderError(
                f"OpenSEO input schema changed for {name}; review provider contract"
            ) from None
        digest = hashlib.sha256(
            json.dumps([name, args], sort_keys=True).encode()
        ).hexdigest()
        path = self.cache / f"{digest}.json"
        cacheable = name not in {
            "run_site_audit",
            "get_audit_status",
            "get_audit_issues",
        }
        if cacheable and digest in self.memory:
            return self.memory[digest]
        if cacheable and path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("tool") == name and cached.get("arguments") == args:
                self.memory[digest] = cached["response"]
                return cached["response"]
        # Only explicit HTTP throttling/server errors are retried. Ambiguous timeouts
        # are not replayed because credit-charging calls may already have completed.
        for attempt in range(3):
            try:
                result = await self.session.call_tool(name, args)
                break
            except httpx.HTTPStatusError as exc:
                if (
                    name == "run_site_audit"
                    or exc.response.status_code not in {429, 502, 503, 504}
                    or attempt == 2
                ):
                    raise ProviderError(
                        f"OpenSEO HTTP {exc.response.status_code}; check credentials, credits, and service availability"
                    ) from None
                await asyncio.sleep(2**attempt)
        if result.isError:
            raise ProviderError(
                f"OpenSEO {name} failed; check project access, integration status, and credits"
            )
        data = result.structuredContent
        if not isinstance(data, dict):
            raise ProviderError(
                f"OpenSEO {name} returned no structured object; review server contract"
            )
        # Persist structured data only: never response headers, auth, or tool text.
        if cacheable:
            save_json(path, {"tool": name, "arguments": args, "response": data})
            self.memory[digest] = data
        return data


def ranked_row(raw: dict[str, Any]) -> Row:
    kd = raw.get("keyword_data", {})
    info = kd.get("keyword_info", {}) or {}
    item = raw.get("ranked_serp_element", {}).get("serp_item", {})
    return Row(
        key=kd["keyword"],
        source="openseo",
        position=item.get("rank_absolute"),
        ranking_url=item.get("url"),
        search_volume=info.get("search_volume"),
        cpc=info.get("cpc"),
        keyword_difficulty=(kd.get("keyword_properties") or {}).get(
            "keyword_difficulty"
        ),
        search_intent=(kd.get("search_intent_info") or {}).get("main_intent"),
        estimated_traffic=item.get("etv"),
    )


class OpenSEOProvider:
    def __init__(self, config: Config, raw_dir: Path):
        self.config, self.raw_dir = config, raw_dir

    def collect(
        self, site: Site, period: Period, *, historical: bool = False
    ) -> Collection:
        token = os.environ.get("OPENSEO_ACCESS_TOKEN") or os.environ.get(
            "OPENSEO_API_KEY"
        )
        if not token:
            raise ProviderError(
                "Set OPENSEO_ACCESS_TOKEN (or OPENSEO_API_KEY) to a key from OpenSEO Settings > API keys"
            )
        if not site.openseo_project_id:
            raise ProviderError(
                "Set openseo_project_id for this site using its existing OpenSEO project"
            )
        try:
            return asyncio.run(
                self._collect(site, period, token, historical=historical)
            )
        except ProviderError:
            raise
        except Exception:
            raise ProviderError(
                "OpenSEO connection or response failed; check token validity, project permission, network, and provider contract"
            ) from None

    async def _collect(
        self, site: Site, period: Period, token: str, *, historical: bool = False
    ) -> Collection:
        async with session_for(token) as session:
            # Daily persistent reuse prevents repeat charges on report reruns.
            cache = (
                self.raw_dir / site.id / datetime.now(timezone.utc).strftime("%Y-%m-%d")
            )
            reader = MCPReader(session, cache)
            await reader.discover()
            return await self.collect_with_reader(
                reader, site, period, historical=historical
            )

    async def collect_with_reader(
        self, reader: MCPReader, site: Site, period: Period, *, historical: bool = False
    ) -> Collection:
        result = Collection(provider="openseo")
        base = {"projectId": site.openseo_project_id}
        market = {
            "locationCode": site.search.location_code,
            "languageCode": site.search.language,
        }
        today = datetime.now(timezone.utc).date()

        def metric(value: float | None, source: str, point: bool = False) -> Metric:
            return Metric(
                value=value,
                source=source,
                measurement_type="estimated" if point else "first_party",
                period_start=None if point else period.start,
                period_end=None if point else period.end,
                temporal_basis="point_in_time" if point else "period",
                observed_at=result.observed_at,
            )

        # The normal monthly report includes live observations explicitly dated
        # at collection time. Older backfills never request or back-date them.
        if not historical and period.key in {
            today.strftime("%Y-%m"),
            month_period(today=today).key,
        }:
            try:
                raw = await reader.call(
                    "get_domain_overview",
                    {**base, **market, "domain": site.domain, "scope": "subdomains"},
                )
                if not any(
                    k in raw
                    for k in (
                        "organicTraffic",
                        "organicKeywords",
                        "backlinks",
                        "referringDomains",
                    )
                ):
                    raise ProviderError("Domain overview schema mismatch")
                overview = Overview.model_validate(raw)
                for name, attr in {
                    "estimated_organic_traffic": "organicTraffic",
                    "ranking_keywords": "organicKeywords",
                    "total_backlinks": "backlinks",
                    "referring_domains": "referringDomains",
                }.items():
                    result.metrics[name] = metric(
                        getattr(overview, attr), "openseo", True
                    )
            except Exception:
                result.warnings.append(
                    "Domain estimates/backlinks unavailable; check OpenSEO project, credits, and schema."
                )
            try:
                rows: dict[str, Row] = {}
                for offset in range(0, self.config.max_keyword_rows, 100):
                    raw = await reader.call(
                        "get_ranked_keywords",
                        {
                            **base,
                            **market,
                            "target": site.domain,
                            "scope": "subdomains",
                            "resultTypes": ["organic"],
                            "limit": min(100, self.config.max_keyword_rows - offset),
                            "offset": offset,
                            "sortBy": "rank",
                        },
                    )
                    items = raw["keywords"]
                    if not isinstance(items, list):
                        raise ProviderError("Keyword rows are not a list")
                    for item in items:
                        row = ranked_row(item)
                        if row.key not in rows or (row.position or float("inf")) < (
                            rows[row.key].position or float("inf")
                        ):
                            rows[row.key] = row
                    total = raw.get("totalCount")
                    if total is not None and offset + len(items) >= total:
                        result.keywords_complete = True
                        break
                    if not items:
                        break
                result.keywords = list(rows.values())
                if not result.keywords_complete:
                    result.warnings.append(
                        "Keyword collection is a bounded sample; unobserved keywords cannot be declared new/lost."
                    )
            except Exception:
                result.warnings.append(
                    "Ranked keywords unavailable; check OpenSEO credits and response schema."
                )
            result.warnings.append(
                "Estimated visibility and backlinks are point-in-time observations, not monthly totals; scope includes subdomains and device is provider-defined."
            )
        else:
            result.warnings.append(
                "Historical domain estimates, keyword ranks, and backlinks are unavailable from the live MCP tools; no current observations were back-dated."
            )
        if site.gsc_enabled:
            filters = [
                {
                    "dimension": "device",
                    "operator": "equals",
                    "expression": site.search.device,
                }
            ]
            if site.search.gsc_country:
                filters.append(
                    {
                        "dimension": "country",
                        "operator": "equals",
                        "expression": site.search.gsc_country,
                    }
                )
            common = {
                **base,
                "startDate": str(period.start),
                "endDate": str(period.end),
                "dataState": "final",
                "type": "web",
                "filters": filters,
            }
            for dimension, attr in [
                ("date", "totals"),
                ("query", "queries"),
                ("page", "pages"),
            ]:
                try:
                    entries = []
                    complete = False
                    offset = 0
                    while offset < self.config.max_gsc_rows:
                        raw = await reader.call(
                            "get_search_console_performance",
                            {
                                **common,
                                "dimensions": [dimension],
                                "rowLimit": 1000,
                                "startRow": offset,
                            },
                        )
                        if (
                            raw.get("ok") is not True
                            or raw.get("startDate") != str(period.start)
                            or raw.get("endDate") != str(period.end)
                            or raw.get("dimensions") != [dimension]
                        ):
                            raise ProviderError(
                                "GSC response unavailable or period/dimensions mismatch"
                            )
                        property_url = raw.get("siteUrl", "")
                        property_domain = (
                            property_url.removeprefix("sc-domain:")
                            if property_url.startswith("sc-domain:")
                            else urlsplit(property_url).hostname
                        )
                        if property_domain != site.domain:
                            raise ProviderError(
                                "GSC property does not match configured domain"
                            )
                        rows = raw["rows"]
                        if not isinstance(rows, list):
                            raise ProviderError("Invalid GSC rows")
                        for r in rows:
                            entries.append(
                                Row(
                                    key=r["keys"][0],
                                    source="google_search_console",
                                    clicks=r["clicks"],
                                    impressions=r["impressions"],
                                    ctr=r["ctr"],
                                    position=r.get("position"),
                                    ranking_url=r["keys"][0]
                                    if dimension == "page"
                                    else None,
                                )
                            )
                        if not raw.get("hasMore", False):
                            complete = True
                            break
                        next_offset = raw.get("nextStartRow")
                        if not isinstance(next_offset, int) or next_offset <= offset:
                            raise ProviderError("Invalid GSC pagination cursor")
                        offset = next_offset
                    if attr == "totals":
                        if not complete or not entries:
                            raise ProviderError("Incomplete or unavailable date totals")
                        clicks = sum(r.clicks for r in entries)
                        impressions = sum(r.impressions for r in entries)
                        values = {
                            "clicks": clicks,
                            "impressions": impressions,
                            "ctr": clicks / impressions if impressions else None,
                            "average_position": sum(
                                r.position * r.impressions for r in entries
                            )
                            / impressions
                            if impressions
                            and all(r.position is not None for r in entries)
                            else None,
                        }
                        result.metrics.update(
                            {
                                k: metric(v, "google_search_console")
                                for k, v in values.items()
                            }
                        )
                    else:
                        setattr(result, attr, entries)
                        # Google suppresses anonymized queries even when pagination ends.
                        setattr(
                            result, attr + "_complete", complete and attr != "queries"
                        )
                except Exception:
                    result.warnings.append(
                        f"Search Console {attr} unavailable; connect the correct property in OpenSEO and verify the requested dates."
                    )
        if site.audit.enabled and not historical:
            from .site_audit import collect_audit

            result.audit = await collect_audit(reader, site)
        if (
            not result.metrics
            and result.keywords is None
            and result.queries is None
            and result.pages is None
            and result.audit is None
        ):
            raise ProviderError(
                "No usable OpenSEO data: check project access, GSC connection, date availability, and credits"
            )
        return Collection.model_validate(result.model_dump())
