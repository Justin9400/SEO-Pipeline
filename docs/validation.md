# Implementation validation

Validated locally with Python 3.12.14 on Windows on 2026-09-19.

- `pytest -q`: **45 passed**. External network is blocked by the test fixture.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: 17 files formatted.
- `git diff --check`: passed.
- Editable installation and the `seo-pipeline` console entry point: verified.
- Wheel build: verified that both month fixtures and HTML/CSS templates are included.
- `seo-pipeline report --site all --provider mock --period 2026-07`: exit 0.
- Both configured sites produced JSON, Markdown, HTML, and a two-page PDF.
- PDF pages were rendered to images and visually inspected for table wrapping,
  page breaks, readable text, and footers. Extracted text was also checked.

The local PDF test runtime used Pango/HarfBuzz/Fribidi/Graphite libraries from
conda-forge plus bundled native dependencies. WeasyPrint's local virtual-environment
DLL names were adjusted for those conda DLL filenames; no runtime patches or native
binaries are part of this repository. Standard production installations should use
the documented WeasyPrint platform setup (Linux recommended for CI).

No real OpenSEO or OpenAI calls were made. Provider validation uses public source
contracts, fake MCP responses, schema checks, pagination/cache/retry tests, and a
fake OpenAI Responses client. A credentialed smoke test remains the operator's
production onboarding step after configuring real projects and secrets.
