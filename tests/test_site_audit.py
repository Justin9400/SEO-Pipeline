import asyncio
from types import SimpleNamespace

import httpx
import pytest

from seo_pipeline.config import Config, Site
from seo_pipeline.models import Collection, Snapshot
from seo_pipeline.periods import month_period
from seo_pipeline.providers.openseo import MCPReader, OpenSEOProvider
from seo_pipeline.providers.site_audit import collect_audit
from seo_pipeline.reports import customer_html, render_pdf


def site():
    return Site(
        id="example",
        name="Example",
        domain="example.com",
        openseo_project_id="project",
        audit={"enabled": True, "max_pages": 100},
    )


class Reader:
    def __init__(self, state="completed", total=1):
        self.state, self.total, self.calls = state, total, []

    async def call(self, name, args):
        self.calls.append((name, args))
        if name == "run_site_audit":
            return {"auditId": "fresh-id"}
        assert args["auditId"] == "fresh-id"
        if name == "get_audit_status":
            return {
                "status": {"id": "fresh-id", "status": self.state, "pagesCrawled": 100}
            }
        return {
            "summary": [{"count": self.total}],
            "issues": [
                {
                    "severity": "critical",
                    "issueType": "broken-internal-link",
                    "title": "Broken internal link",
                    "url": "https://example.com/services",
                    "details": {"targetStatus": 404},
                    "howToFix": "Update the broken link <script>unsafe</script>.",
                }
            ],
        }


def test_completed_audit_and_pdf(tmp_path):
    import pymupdf

    reader = Reader(total=201)
    audit = asyncio.run(collect_audit(reader, site()))
    assert audit.status == "completed" and audit.total_issues == 201
    assert len(audit.warnings) == 2
    assert reader.calls[0][1]["maxPages"] == 100
    assert reader.calls[0][1]["runLighthouse"] is False
    snapshot = Snapshot(
        site=site(),
        reporting_period=month_period("2026-07"),
        collection=Collection(provider="openseo", audit=audit),
    )
    html = customer_html(snapshot)
    assert "&lt;script&gt;" in html and "<script>" not in html
    path = tmp_path / "audit.pdf"
    render_pdf(html, path)
    with pymupdf.open(path) as pdf:
        text = "\n".join(p.get_text() for p in pdf)
    for value in [
        "OpenSEO technical site audit",
        "How to fix:",
        "404",
        "https://example.com/services",
        "fresh-id",
        "page budget",
    ]:
        assert value in text


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_terminal_failure(state):
    reader = Reader(state)
    audit = asyncio.run(collect_audit(reader, site()))
    assert audit.status == state and audit.warnings
    assert len(reader.calls) == 2


def test_timeout(monkeypatch):
    async def timeout(coro, timeout):
        coro.close()
        raise TimeoutError

    monkeypatch.setattr("seo_pipeline.providers.site_audit.asyncio.wait_for", timeout)
    audit = asyncio.run(collect_audit(Reader(), site()))
    assert audit.status == "timed_out" and audit.warnings


def test_polling_and_missing_id(monkeypatch):
    reader = Reader("running")

    async def advance(seconds):
        reader.state = "completed"

    monkeypatch.setattr("seo_pipeline.providers.site_audit.asyncio.sleep", advance)
    assert asyncio.run(collect_audit(reader, site())).status == "completed"
    assert len(reader.calls) == 4

    class Missing:
        async def call(self, *args):
            return {}

    assert asyncio.run(collect_audit(Missing(), site())).status == "unavailable"


def test_audit_calls_uncached_and_start_not_retried(tmp_path):
    class Session:
        def __init__(self):
            self.calls = 0

        async def call_tool(self, name, args):
            self.calls += 1
            if name == "run_site_audit":
                request = httpx.Request("POST", "https://example.com")
                raise httpx.HTTPStatusError(
                    "failed",
                    request=request,
                    response=httpx.Response(503, request=request),
                )
            return SimpleNamespace(
                isError=False, structuredContent={"status": {"status": str(self.calls)}}
            )

    async def run():
        session = Session()
        reader = MCPReader(session, tmp_path)
        reader.schemas = {
            name: {"type": "object"} for name in ["get_audit_status", "run_site_audit"]
        }
        a = await reader.call("get_audit_status", {})
        b = await reader.call("get_audit_status", {})
        assert a != b
        with pytest.raises(Exception, match="HTTP 503"):
            await reader.call("run_site_audit", {})
        assert session.calls == 3
        assert not list(tmp_path.glob("*.json"))

    asyncio.run(run())


def test_historical_collection_never_starts_audit(tmp_path):
    class NoData:
        async def call(self, name, args):
            assert name == "get_search_console_performance"
            return {"ok": False}

    with pytest.raises(Exception, match="No usable"):
        asyncio.run(
            OpenSEOProvider(Config(sites=[site()]), tmp_path).collect_with_reader(
                NoData(), site(), month_period("2026-07"), historical=True
            )
        )


def test_cli_retains_pdf_when_audit_fails(tmp_path, monkeypatch):
    from seo_pipeline.cli import main
    from seo_pipeline.models import AuditResult

    def collect(self, configured_site, period, **kwargs):
        return Collection(
            provider="openseo",
            audit=AuditResult(
                status="failed", max_pages=100, warnings=["Audit failed."]
            ),
        )

    monkeypatch.setattr(OpenSEOProvider, "collect", collect)
    output = tmp_path / "output"
    result = main(
        [
            "report",
            "--provider",
            "openseo",
            "--no-ai",
            "--period",
            "2026-07",
            "--output-dir",
            str(output),
            "--data-dir",
            str(tmp_path / "data"),
        ]
    )
    assert result == 1
    assert list(output.rglob("*.pdf"))
    assert "Audit failed." in next(output.rglob("*.html")).read_text()


def test_wrong_audit_id_rejected():
    class Wrong(Reader):
        async def call(self, name, args):
            response = await super().call(name, args)
            if name == "get_audit_status":
                response["status"]["id"] = "unrelated"
            return response

    reader = Wrong()
    audit = asyncio.run(collect_audit(reader, site()))
    assert audit.status == "unavailable" and not audit.issues
    assert len(reader.calls) == 2
