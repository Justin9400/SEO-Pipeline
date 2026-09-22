"""Fresh, bounded audits. Never substitute a project's latest unrelated audit."""

import asyncio

from ..config import Site
from ..models import AuditIssue, AuditResult

ISSUE_LIMIT = 200


async def collect_audit(reader, site: Site) -> AuditResult:
    result = AuditResult(max_pages=site.audit.max_pages)

    async def run():
        started = await reader.call(
            "run_site_audit",
            {
                "projectId": site.openseo_project_id,
                "url": f"https://{site.domain}/",
                "maxPages": site.audit.max_pages,
                "runLighthouse": False,
            },
        )
        audit_id = started.get("auditId")
        if not isinstance(audit_id, str) or not audit_id:
            raise ValueError("Missing audit ID")
        result.audit_id = audit_id
        args = {"projectId": site.openseo_project_id, "auditId": audit_id}
        while True:
            status = (await reader.call("get_audit_status", args))["status"]
            if status.get("id") != audit_id:
                raise ValueError("Audit ID mismatch")
            result.pages_crawled = status.get("pagesCrawled")
            state = status["status"]
            if state == "completed":
                break
            if state in {"failed", "cancelled", "canceled"}:
                result.status = state
                result.warnings.append(
                    "OpenSEO did not complete the audit. No complete technical findings are available."
                )
                return
            await asyncio.sleep(10)
        raw = await reader.call("get_audit_issues", {**args, "limit": ISSUE_LIMIT})
        result.total_issues = sum(int(row["count"]) for row in raw["summary"])
        if result.total_issues < 0:
            raise ValueError("Invalid issue count")
        result.issues = [
            AuditIssue(
                severity=row["severity"],
                issue_type=row["issueType"],
                title=row.get("title") or row.get("issue") or row["issueType"],
                url=row["url"],
                details=row.get("details") or {},
                how_to_fix=row.get("howToFix")
                or row.get("how_to_fix")
                or "Review this finding in OpenSEO before making changes.",
            )
            for row in raw["issues"]
        ]
        result.status = "completed"
        if (
            len(result.issues) < result.total_issues
            or len(result.issues) >= ISSUE_LIMIT
        ):
            result.warnings.append(
                f"Issue detail is limited to {ISSUE_LIMIT} rows; consult OpenSEO for any additional findings."
            )
        if (
            result.pages_crawled is not None
            and result.pages_crawled >= result.max_pages
        ):
            result.warnings.append(
                "The crawl reached its configured page budget; additional pages may not have been checked."
            )

    try:
        await asyncio.wait_for(run(), timeout=site.audit.timeout_seconds)
    except TimeoutError:
        result.status = "timed_out"
        result.warnings.append(
            "The audit exceeded the reporting wait limit. It may still be running in OpenSEO; no complete findings are available in this PDF."
        )
    except Exception:
        result.status = "unavailable"
        result.warnings.append(
            "Audit results are unavailable. Check OpenSEO audit capacity, credentials, and tool access. A start request is never automatically retried because it may already have created an audit."
        )
    return result
