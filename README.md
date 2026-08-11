# SEO Metrics Pipeline

A standalone Python 3.12+ pipeline for collecting, comparing, analyzing, and reporting SEO performance across multiple sites. Sites are read-only domain targets: the application does not clone website repositories, inspect site source code, deploy websites, use Cloudflare, or modify monitored sites.

## Architecture

```text
config/sites.yaml
        |
        v
OpenSEO MCP + connected Google Search Console
        |
        v
normalized, versioned Pydantic snapshot
        |
        +--> filesystem history / previous-period comparison
        |
        v
deterministic deltas, keyword trends, and opportunity scores
        |
        +--> OpenAI Responses API Structured Output (optional/fault-tolerant)
        |
        v
customer PDF + internal Markdown + machine-readable JSON
```

Provider responses are normalized before comparisons or rendering. The JSON snapshot is the system of record. The PDF is a customer-facing view, and the Markdown report is private operator/LLM context.

## Local setup

Requirements:

- Python 3.12 or later
- Native libraries required by [WeasyPrint](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html) for your platform

Create an environment and install the project:

```bash
python -m venv .venv
source .venv/bin/activate       # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Copy `.env.example` values into your environment or secret manager. The pipeline does not automatically read `.env` files, which avoids accidental credential loading; export variables through your shell or CI secret system.

## Configure sites

Edit `config/sites.yaml`. Any number of sites can be supplied. Each site has a stable ID, display name, bare domain, market settings, optional targets and competitors, and an OpenSEO project ID for production:

```yaml
sites:
  - id: example
    name: Example Company
    domain: example.com
    enabled: true
    openseo_project_id: your-openseo-project-uuid
    search:
      country: US
      language: en
      device: desktop
    reporting:
      comparison_period: previous_month
```

Credentials never belong in YAML. Duplicate IDs/domains, schemes or paths in domains, malformed YAML, and unknown fields fail validation with actionable messages.

## Run the complete mock pipeline

The included fixtures contain June and July 2026 data for two sites. They make all three outputs testable without OpenSEO or OpenAI credentials:

```bash
seo-pipeline report --site all --period 2026-07 --provider mock
```

Equivalent module invocation:

```bash
python -m seo_pipeline report --site example --period 2026-07 --provider mock
```

Outputs are independent per site:

```text
output/
  example.com/
    2026-07/
      seo-data.json
      seo-performance-report.pdf
      seo-opportunities.md
```

Use `--dry-run` to validate configuration and selection without external requests or filesystem writes. Use `--output-dir` and `--data-dir` to relocate reports and historical snapshots. A failure for one site is logged and reported without deleting successful sites; the overall command exits non-zero if any site fails.

## Production setup

Required environment variables:

- `OPENSEO_ACCESS_TOKEN`: bearer token accepted by the configured OpenSEO MCP endpoint
- `OPENAI_API_KEY`: enables GPT structured analysis

Optional variables:

- `OPENAI_MODEL`: defaults to `gpt-5.6`
- `OPENSEO_MCP_URL`: defaults to `https://app.openseo.so/mcp`
- `SEO_PIPELINE_LOG_LEVEL`: defaults to `INFO`
- `WEASYPRINT_EXECUTABLE`: optional Windows path to WeasyPrint's official standalone executable when Pango/GTK is not installed for the Python library

Run every enabled site for the last fully completed calendar month:

```bash
seo-pipeline report --site all --provider openseo
```

Run one site or an explicit completed month:

```bash
seo-pipeline report --site example --period 2026-07 --provider openseo
```

`--no-ai` skips OpenAI while retaining deterministic detection and all factual reports.

### OpenSEO authentication boundary

The hosted OpenSEO documentation currently describes adding `https://app.openseo.so/mcp` to an MCP client and completing an interactive login. It does not publicly document an unattended token-issuance flow for a standalone scheduled Python process. This project does not fabricate one.

The `OpenSEOProvider` uses the official MCP Python SDK and Streamable HTTP transport, discovers tools at runtime, and passes `OPENSEO_ACCESS_TOKEN` as a bearer token. Authentication is isolated in that provider so a future OAuth refresh-token, service-account, or OpenSEO API-key contract can replace it without changing comparison, storage, analysis, or report code. Until OpenSEO provisions a compatible unattended credential, use interactive OpenSEO clients for token acquisition or run mock mode.

Documented read operations used when available:

- `get_domain_overview`
- `get_domain_keyword_suggestions`
- `get_backlinks_overview`
- `get_search_console_performance` for daily totals, queries, and pages

Missing GSC or backlink data remains `null`/`Not available`; it is never invented as zero.

## Output contracts

### `seo-data.json`

The versioned, normalized source of truth. It retains current and previous values, deltas, percent changes, measurement type, provider provenance, keyword/page records, explainable opportunity scores, warnings, and validated structured analysis.

### `seo-performance-report.pdf`

A consistent customer-facing month-over-month report rendered from semantic Jinja2 HTML/CSS through WeasyPrint. It clearly labels first-party Search Console metrics versus estimated provider metrics and renders missing data as `Not available`.

### `seo-opportunities.md`

Private semantic Markdown for a human operator or downstream LLM. It contains explicit period/source context, deterministic trend counts, structured evidence, score components, prioritized investigations, model contextualization, and interpretation guardrails.

Historical snapshots are stored separately under `data/snapshots/<domain>/<YYYY-MM>/seo-data.json`. The storage interface can be replaced by S3/R2 later without changing the reporting pipeline; this version intentionally performs no Cloudflare access.

## Deterministic analysis

Python, not the LLM, calculates:

- absolute and percentage changes with zero-denominator handling
- ranking movement where `15 -> 10` is a positive five-position improvement
- exclusive ranking buckets
- new, lost, improving, declining, and unchanged keywords
- page gains/losses
- striking-distance and high-impression/low-CTR candidates
- explainable candidate scores and HIGH/MEDIUM/LOW thresholds

The OpenAI integration uses the official Responses API and Pydantic Structured Outputs. If the call fails, the factual snapshot is preserved and a deterministic analysis is used so the PDF and Markdown can still be generated.

## Tests

```bash
pytest
```

The normal suite mocks all external services. It covers configuration validation, date boundaries and leap years, deterministic calculations, keyword status/buckets, missing data, scoring, schema round-trips, snapshot lookup, both report formats, two-site execution, and per-site provider failure isolation.

## GitHub Actions

The application is a normal CLI and is not coupled to Actions. A future scheduled or `workflow_dispatch` job only needs Python setup, `pip install .`, the repository's own output/history persistence decision, and these secrets:

- `OPENAI_API_KEY`
- `OPENSEO_ACCESS_TOKEN`

Exact reporting command:

```bash
seo-pipeline report --site all --provider openseo
```

No website-repository token, Cloudflare token, or deployment credential is required.

## Troubleshooting

- **`OPENSEO_ACCESS_TOKEN is required`**: provision a bearer token compatible with the hosted MCP endpoint, or use `--provider mock`.
- **OpenSEO rejects the token**: reconnect the OpenSEO OAuth integration and provision a fresh unattended-compatible token. Tokens are never logged.
- **No OpenSEO project**: set the site's non-secret `openseo_project_id` in `config/sites.yaml`.
- **GSC values are unavailable**: connect the relevant property to the configured OpenSEO project. The report will preserve other successful metrics.
- **Backlinks are unavailable**: verify the OpenSEO/DataForSEO backlink entitlement. Unknown values remain distinct from zero.
- **PDF rendering fails**: install the native libraries listed in the WeasyPrint installation guide for the runner OS. On Windows, the official standalone release is supported by setting `WEASYPRINT_EXECUTABLE` to its `weasyprint.exe` path.
- **A month has no comparison**: retain the previous snapshot under `data/snapshots`, or run mock fixtures with the documented `2026-07` period.

## Security and scope

- Secrets come only from environment variables or CI secrets.
- Structured logs never include token values.
- `.env`, output, history, raw caches, and virtual environments are gitignored.
- The pipeline only reads SEO/search data for configured public domains.
- It has no website-source, deployment, Cloudflare, or monitored-repository integration.
