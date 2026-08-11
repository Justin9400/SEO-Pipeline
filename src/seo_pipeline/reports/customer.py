from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from seo_pipeline.models.snapshot import ComparisonMetric, SEOSnapshot


METRIC_LABELS = {
    "organic_clicks": "Organic Clicks",
    "organic_impressions": "Organic Impressions",
    "organic_ctr": "Organic CTR",
    "average_position": "Average Position",
    "estimated_organic_traffic": "Estimated Organic Traffic",
    "ranking_keywords": "Ranking Keywords",
    "referring_domains": "Referring Domains",
}


def format_number(value: float | None, decimals: int = 0) -> str:
    if value is None:
        return "Not available"
    if decimals:
        return f"{value:,.{decimals}f}"
    return f"{value:,.0f}"


def format_percent(value: float | None) -> str:
    return "Not available" if value is None else f"{value * 100:.2f}%"


def format_metric_value(metric: ComparisonMetric, value: float | None) -> str:
    if value is None:
        return "Not available"
    if metric.unit == "percent":
        return format_percent(value)
    if metric.unit == "position":
        return format_number(value, 1)
    return format_number(value, 0)


def format_change(metric: ComparisonMetric) -> str:
    if metric.absolute_change is None:
        return "Not available"
    if metric.unit == "percent":
        return f"{metric.absolute_change * 100:+.2f} pp"
    if metric.unit == "position":
        if metric.direction == "unchanged":
            return "Unchanged"
        return f"{metric.direction.title()} {abs(metric.absolute_change):.1f}"
    if metric.percent_change is None:
        return f"{metric.absolute_change:+,.0f} (rate unavailable)"
    return f"{metric.percent_change:+.1f}%"


class CustomerReportRenderer:
    def __init__(self) -> None:
        self.environment = Environment(
            loader=PackageLoader("seo_pipeline", "templates/customer_report"),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self.environment.filters.update(
            number=format_number,
            percent=format_percent,
            metric_value=format_metric_value,
            metric_change=format_change,
        )

    def render_html(self, snapshot: SEOSnapshot) -> str:
        template = self.environment.get_template("report.html")
        return template.render(snapshot=snapshot, metric_labels=METRIC_LABELS)

    def render_pdf(self, snapshot: SEOSnapshot, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        html = self.render_html(snapshot)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{path.stem}.", suffix=".pdf", dir=path.parent
        )
        os.close(handle)
        try:
            executable = os.getenv("WEASYPRINT_EXECUTABLE")
            if executable:
                html_handle, html_name = tempfile.mkstemp(
                    prefix=f".{path.stem}.", suffix=".html", dir=path.parent
                )
                try:
                    with os.fdopen(html_handle, "w", encoding="utf-8", newline="\n") as stream:
                        stream.write(html)
                    try:
                        subprocess.run(
                            [executable, html_name, temporary_name],
                            check=True,
                            capture_output=True,
                            text=True,
                            timeout=120,
                        )
                    except subprocess.CalledProcessError as error:
                        detail = (error.stderr or error.stdout or "No diagnostic output").strip()
                        raise RuntimeError(
                            f"Standalone WeasyPrint failed: {detail[-1_000:]}"
                        ) from error
                finally:
                    try:
                        os.unlink(html_name)
                    except FileNotFoundError:
                        pass
            else:
                try:
                    from weasyprint import HTML
                except (ImportError, OSError) as import_error:
                    raise RuntimeError(
                        "WeasyPrint's native libraries are unavailable. Install Pango/GTK "
                        "for the Python library, or set WEASYPRINT_EXECUTABLE to the official "
                        "standalone WeasyPrint executable."
                    ) from import_error
                HTML(string=html, base_url=str(path.parent)).write_pdf(temporary_name)
            os.replace(temporary_name, path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
