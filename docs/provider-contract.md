# OpenSEO contract and data limits

Verified against the public OpenSEO implementation at commit
`0ffff93101043aad7600a3b6a499a0cd2887ef49` on 2026-09-19.

Sources:

- [Hosted MCP and API-key authentication](https://openseo.so/docs/mcp)
- [Domain overview](https://github.com/every-app/open-seo/blob/0ffff93101043aad7600a3b6a499a0cd2887ef49/src/server/mcp/tools/get-domain-overview.ts)
- [Ranked keyword input and output](https://github.com/every-app/open-seo/blob/0ffff93101043aad7600a3b6a499a0cd2887ef49/src/server/mcp/tools/dataforseo-research-tools.ts)
- [Search Console dates, pagination and fields](https://github.com/every-app/open-seo/blob/0ffff93101043aad7600a3b6a499a0cd2887ef49/src/server/mcp/tools/search-console-tools.ts)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

## Authentication and transport

The application uses the official Python MCP SDK's Streamable HTTP client at
`https://app.openseo.so/mcp`. It initializes a session and discovers the live input
schemas with `tools/list`, including pagination. Arguments are validated against
the discovered schema before any paid call. Only three named research/read tools
are allowed. There is no arbitrary tool execution, crawl, project mutation,
website source access, website deployment, or provider report publishing.

Create an API key in **OpenSEO Settings > API keys**. Put its value in
`OPENSEO_ACCESS_TOKEN` or `OPENSEO_API_KEY`. The isolated `session_for` adapter sends
`Authorization: Bearer <value>`. OAuth refresh is deliberately not implemented;
an OAuth access token will stop working when it expires. API keys are the provider's
documented option for unattended CI. No live credentials or API calls were used
to validate this implementation; contract and transport behavior are tested with
fake responses.

## Tool mapping

| Tool | Normalized data | Limits |
| --- | --- | --- |
| `get_domain_overview` | `organicTraffic`, `organicKeywords`, `backlinks`, `referringDomains` | Current observations; no historical date input; includes subdomains |
| `get_ranked_keywords` | `keyword_data.keyword`, `keyword_info.search_volume/cpc`, `ranked_serp_element.serp_item.rank_absolute/url/etv` | Organic results only; up to 100 per page; offset at most 1000; configurable collection cap |
| `get_search_console_performance` | Date, query and page rows with clicks, impressions, CTR and position | Existing connected project; explicit dates; final web data; pagination up to configured cap |

Domain overview already includes backlink totals, so the adapter does not make an
additional paid backlink call for the same figures. New/lost referring domains
and top linked pages are currently unavailable in the normalized production
collection. They are never inferred from the net referring-domain change.

`openseo_project_id` is required for every production site. No project is created
automatically. The response Search Console property must match the configured
domain. URL-prefix and domain properties are supported for that exact hostname;
configure `www.example.com` explicitly if that is the property being monitored.

## Temporal semantics

The last complete month is the default reporting period. GSC totals are calculated
from **date rows**, not from the truncated query table. Position is weighted by
impressions and CTR is calculated from totals. Search Console dates use Pacific
Time; the report period is a calendar month. Recent final data may lag several days.
Run after that lag and rerun later if needed. Empty date results are unknown,
not automatically zero. Explicit current-month reports are month-to-date and
compare against the complete previous month; the report prints both date ranges.

For the default monthly run and an explicit current-month run, live estimates
are collected and stored with `temporal_basis: point_in_time`, an `observed_at`
timestamp, and null period dates. They describe the date collected, **not a
historical monthly total**. Later reports compare these stored observations.
Older backfills only collect date-addressable GSC data; they do not make paid
live-estimate calls. The first report has no earlier live observation unless a
compatible snapshot already exists. No historical rank endpoint is invented.

The report's keyword list is the provider's market sample, not a promise of every
Google ranking. The adapter requests organic-only results and retains the best
position when multiple URLs represent the same keyword. New/lost detection is
allowed only when the opposite keyword collection is known complete. Query
anonymization means GSC query lists are never treated as exhaustive. Page gains
and losses compare known clicks on matching page URLs. Country/language apply
to provider keyword research; GSC uses the explicit optional three-letter
`gsc_country` filter and selected device. GSC does not have a language filter.

## Failure handling and costs

- HTTP/session/read deadlines prevent indefinite waits.
- Explicit HTTP 429/502/503/504 responses receive bounded backoff (three attempts).
- Ambiguous paid-call timeouts are not retried: the provider may already have
  charged credits. Tool errors and invalid responses are not retried blindly.
- Successful structured responses are cached under `data/raw/<site>/<UTC-date>`
  using a hash of tool and arguments. A same-day rerun reuses them. Cache files
  contain structured SEO data and request arguments, never auth headers or tokens.
- Discovery is repeated on each connection. Changed schemas fail before a call.
- Collection sections fail independently. A site with no usable data fails;
  partial data retains warnings. JSON is saved before model analysis or rendering.
- OpenAI output failures are a recoverable degradation: deterministic factual
  outputs remain available. PDF or complete-site collection failures return 1.

Raw caches and snapshots can contain commercially sensitive SEO data. Keep them
in private storage, outside Git. Delete a site's dated raw-cache directory to
force fresh collection; doing so may incur new provider charges. Do not run two
writers for the same site/period concurrently.
