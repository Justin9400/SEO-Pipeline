from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from typing import Any

import httpx

from seo_pipeline.models.provider import (
    BacklinkObservation,
    CollectedSEOData,
    CollectionSource,
    KeywordObservation,
    PageObservation,
    SearchConsoleObservation,
)
from seo_pipeline.models.site import SiteConfig
from seo_pipeline.periods import PeriodWindow
from seo_pipeline.providers.base import ProviderError


LOGGER = logging.getLogger(__name__)
DEFAULT_ENDPOINT = "https://app.openseo.so/mcp"


class OpenSEOProvider:
    """OpenSEO Streamable HTTP MCP provider.

    Hosted OpenSEO publicly documents an interactive OAuth login but not a
    non-interactive token issuance contract. This client therefore accepts an
    externally provisioned bearer token and keeps all authentication here.
    """

    name = "openseo"

    def __init__(
        self,
        *,
        access_token: str | None = None,
        endpoint: str | None = None,
        timeout_seconds: float = 45.0,
        max_attempts: int = 3,
    ) -> None:
        self.access_token = access_token or os.getenv("OPENSEO_ACCESS_TOKEN")
        self.endpoint = endpoint or os.getenv("OPENSEO_MCP_URL", DEFAULT_ENDPOINT)
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts

    def collect(self, site: SiteConfig, period: PeriodWindow) -> CollectedSEOData:
        if not self.access_token:
            raise ProviderError(
                "OPENSEO_ACCESS_TOKEN is required for production collection. "
                "Hosted OpenSEO documents an interactive OAuth connection; provision a "
                "compatible bearer token outside the pipeline or use --provider mock."
            )
        if not site.openseo_project_id:
            raise ProviderError(
                f"site {site.id!r} needs openseo_project_id in config/sites.yaml"
            )
        return asyncio.run(self._collect_async(site, period))

    async def _collect_async(
        self, site: SiteConfig, period: PeriodWindow
    ) -> CollectedSEOData:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client
        except ImportError as exc:  # pragma: no cover - packaging guard
            raise ProviderError("the MCP Python SDK is not installed") from exc

        headers = {"Authorization": f"Bearer {self.access_token}"}
        timeout = httpx.Timeout(self.timeout_seconds)
        warnings: list[str] = []
        raw_metadata: dict[str, Any] = {"provider": "openseo", "tools": {}}

        async with httpx.AsyncClient(
            headers=headers, timeout=timeout, follow_redirects=True
        ) as http_client:
            try:
                async with streamable_http_client(
                    self.endpoint, http_client=http_client
                ) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        available = {tool.name for tool in (await session.list_tools()).tools}
                        raw_metadata["available_tools"] = sorted(available)

                        async def optional_call(
                            tool_name: str, arguments: dict[str, Any]
                        ) -> dict[str, Any] | None:
                            if tool_name not in available:
                                warnings.append(
                                    f"OpenSEO tool {tool_name!r} is unavailable; related metrics are unknown."
                                )
                                return None
                            try:
                                result = await self._call_with_retry(
                                    session, tool_name, arguments
                                )
                            except Exception as exc:  # partial data is expected
                                LOGGER.warning("OpenSEO tool %s failed: %s", tool_name, exc)
                                warnings.append(
                                    f"OpenSEO tool {tool_name!r} failed: {type(exc).__name__}."
                                )
                                return None
                            structured = getattr(result, "structuredContent", None)
                            if structured is None:
                                structured = getattr(result, "structured_content", None)
                            if isinstance(structured, Mapping):
                                payload = dict(structured)
                                raw_metadata["tools"][tool_name] = {
                                    "available": True,
                                    "keys": sorted(str(key) for key in payload),
                                }
                                return payload
                            warnings.append(
                                f"OpenSEO tool {tool_name!r} returned no structured content."
                            )
                            return None

                        base = {"projectId": site.openseo_project_id}
                        domain_overview = await optional_call(
                            "get_domain_overview",
                            {**base, "domain": site.domain, "includeSubdomains": False},
                        )
                        keyword_payload = await optional_call(
                            "get_domain_keyword_suggestions",
                            {**base, "domain": site.domain},
                        )
                        backlinks_payload = await optional_call(
                            "get_backlinks_overview",
                            {**base, "target": site.domain, "scope": "domain", "hideSpam": True},
                        )
                        gsc_dates = {
                            **base,
                            "startDate": period.start.isoformat(),
                            "endDate": period.end.isoformat(),
                            "rowLimit": 1000,
                            "dataState": "final",
                        }
                        gsc_daily = await optional_call(
                            "get_search_console_performance",
                            {**gsc_dates, "dimensions": ["date"]},
                        )
                        gsc_queries = await optional_call(
                            "get_search_console_performance",
                            {**gsc_dates, "dimensions": ["query"]},
                        )
                        gsc_pages = await optional_call(
                            "get_search_console_performance",
                            {**gsc_dates, "dimensions": ["page"]},
                        )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in {401, 403}:
                    raise ProviderError(
                        "OpenSEO rejected OPENSEO_ACCESS_TOKEN; reconnect OAuth or provision a new token."
                    ) from exc
                raise ProviderError(f"OpenSEO MCP HTTP error {status}") from exc
            except ProviderError:
                raise
            except Exception as exc:
                raise ProviderError(
                    f"could not connect to OpenSEO MCP at {self.endpoint}: {exc}"
                ) from exc

        keywords = self._normalize_keywords(keyword_payload, gsc_queries)
        pages = self._normalize_pages(gsc_pages)
        search_console = self._normalize_gsc_summary(gsc_daily)
        backlinks = self._normalize_backlinks(backlinks_payload, domain_overview)
        gsc_available = any(
            payload and payload.get("ok", True)
            for payload in (gsc_daily, gsc_queries, gsc_pages)
        )
        return CollectedSEOData(
            period_start=period.start,
            period_end=period.end,
            estimated_organic_traffic=_number(domain_overview, "organicTraffic"),
            organic_keyword_count=_integer(domain_overview, "organicKeywords"),
            search_console=search_console,
            keywords=keywords,
            pages=pages,
            backlinks=backlinks,
            sources=[
                CollectionSource(
                    name="openseo", measurement_type="estimated", available=domain_overview is not None
                ),
                CollectionSource(
                    name="google_search_console",
                    measurement_type="first_party",
                    available=gsc_available,
                    detail=None if gsc_available else "Not connected or unavailable through OpenSEO",
                ),
            ],
            warnings=warnings,
            raw_metadata=raw_metadata,
        )

    async def _call_with_retry(
        self, session: Any, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await session.call_tool(tool_name, arguments=arguments)
            except Exception as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    break
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
        assert last_error is not None
        raise last_error

    @staticmethod
    def _normalize_keywords(
        keyword_payload: dict[str, Any] | None,
        gsc_payload: dict[str, Any] | None,
    ) -> list[KeywordObservation]:
        records: dict[str, KeywordObservation] = {}
        for row in _rows(keyword_payload, "keywords"):
            keyword = str(row.get("keyword") or "").strip()
            if not keyword:
                continue
            records[keyword.casefold()] = KeywordObservation(
                keyword=keyword,
                position=_coalesce_number(row, "position", "rank", "rankAbsolute"),
                search_volume=_coalesce_integer(row, "searchVolume", "search_volume", "volume"),
                keyword_difficulty=_coalesce_number(
                    row, "keywordDifficulty", "keyword_difficulty", "difficulty"
                ),
                cpc=_coalesce_number(row, "cpc"),
                intent=_coalesce_string(row, "intent", "mainIntent", "main_intent"),
                estimated_traffic=_coalesce_number(
                    row, "estimatedTraffic", "traffic", "etv"
                ),
                ranking_url=_coalesce_string(row, "url", "rankingUrl", "ranking_url"),
            )
        for row in _rows(gsc_payload, "rows"):
            keys = row.get("keys")
            keyword = str(keys[0]).strip() if isinstance(keys, list) and keys else ""
            if not keyword:
                continue
            key = keyword.casefold()
            current = records.get(key) or KeywordObservation(keyword=keyword)
            records[key] = current.model_copy(
                update={
                    "position": _coalesce_number(row, "position") or current.position,
                    "clicks": _coalesce_number(row, "clicks"),
                    "impressions": _coalesce_number(row, "impressions"),
                    "ctr": _coalesce_number(row, "ctr"),
                }
            )
        return sorted(records.values(), key=lambda row: (row.position is None, row.position or 999, row.keyword))

    @staticmethod
    def _normalize_pages(payload: dict[str, Any] | None) -> list[PageObservation]:
        pages: list[PageObservation] = []
        for row in _rows(payload, "rows"):
            keys = row.get("keys")
            url = str(keys[0]).strip() if isinstance(keys, list) and keys else ""
            if url:
                pages.append(
                    PageObservation(
                        url=url,
                        clicks=_coalesce_number(row, "clicks"),
                        impressions=_coalesce_number(row, "impressions"),
                        ctr=_coalesce_number(row, "ctr"),
                        position=_coalesce_number(row, "position"),
                    )
                )
        return sorted(pages, key=lambda row: row.clicks or 0, reverse=True)

    @staticmethod
    def _normalize_gsc_summary(payload: dict[str, Any] | None) -> SearchConsoleObservation:
        rows = _rows(payload, "rows")
        clicks = sum(_coalesce_number(row, "clicks") or 0 for row in rows)
        impressions = sum(_coalesce_number(row, "impressions") or 0 for row in rows)
        weighted_position_numerator = sum(
            (_coalesce_number(row, "position") or 0)
            * (_coalesce_number(row, "impressions") or 0)
            for row in rows
        )
        if not rows:
            return SearchConsoleObservation()
        return SearchConsoleObservation(
            clicks=clicks,
            impressions=impressions,
            ctr=(clicks / impressions) if impressions else None,
            average_position=(weighted_position_numerator / impressions)
            if impressions
            else None,
        )

    @staticmethod
    def _normalize_backlinks(
        payload: dict[str, Any] | None, domain_overview: dict[str, Any] | None
    ) -> BacklinkObservation:
        summary: Mapping[str, Any] = {}
        if payload:
            overview = payload.get("overview")
            if isinstance(overview, Mapping):
                nested = overview.get("overview")
                if isinstance(nested, Mapping) and isinstance(nested.get("summary"), Mapping):
                    summary = nested["summary"]
                elif isinstance(overview.get("summary"), Mapping):
                    summary = overview["summary"]
        total_backlinks = _coalesce_integer(summary, "backlinks")
        if total_backlinks is None:
            total_backlinks = _integer(domain_overview, "backlinks")
        referring_domains = _coalesce_integer(summary, "referringDomains", "referring_domains")
        if referring_domains is None:
            referring_domains = _integer(domain_overview, "referringDomains")
        return BacklinkObservation(
            total_backlinks=total_backlinks,
            referring_domains=referring_domains,
        )


def _rows(payload: Mapping[str, Any] | None, key: str) -> list[dict[str, Any]]:
    if not payload:
        return []
    value = payload.get(key)
    return [dict(item) for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _coalesce_number(value: Mapping[str, Any] | None, *keys: str) -> float | None:
    if value is None:
        return None
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, bool):
            continue
        if isinstance(candidate, (int, float)):
            return float(candidate)
    return None


def _coalesce_integer(value: Mapping[str, Any] | None, *keys: str) -> int | None:
    number = _coalesce_number(value, *keys)
    return int(number) if number is not None else None


def _coalesce_string(value: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _number(value: Mapping[str, Any] | None, key: str) -> float | None:
    return _coalesce_number(value, key)


def _integer(value: Mapping[str, Any] | None, key: str) -> int | None:
    return _coalesce_integer(value, key)
