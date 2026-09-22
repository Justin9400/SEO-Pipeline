import argparse
import json
import logging
import sys
from pathlib import Path

from .analysis import analyze
from .config import load_config
from .models import Snapshot
from .openai_analysis import run_analysis
from .periods import month_period
from .providers import ProviderError
from .providers.mock import MockProvider
from .providers.openseo import OpenSEOProvider
from .reports import write_reports
from .storage import FileStore, atomic_text

LOG = logging.getLogger("seo_pipeline")


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "level": record.levelname,
                "event": record.getMessage(),
                "site": getattr(record, "site", None),
            }
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Multi-site SEO reporting and audits")
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report")
    report.add_argument("--site", default="all")
    report.add_argument("--config", type=Path, default=Path("config/sites.yaml"))
    report.add_argument("--period", help="YYYY-MM; defaults to the last complete month")
    report.add_argument("--provider", choices=["mock", "openseo"], default="openseo")
    report.add_argument("--output-dir", type=Path, default=Path("output"))
    report.add_argument("--data-dir", type=Path, default=Path("data"))
    report.add_argument(
        "--dry-run",
        action="store_true",
        help="Use synthetic data and never contact external services",
    )
    report.add_argument(
        "--no-ai", action="store_true", help="Use deterministic analysis only"
    )
    args = parser.parse_args(argv)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JSONFormatter())
    LOG.handlers = [handler]
    LOG.setLevel(logging.INFO)
    LOG.propagate = False
    # SDK HTTP logs may include URLs and auth diagnostics. Never enable them here.
    try:
        config = load_config(args.config)
        period = month_period(args.period)
        sites = [
            s
            for s in config.sites
            if s.enabled and (args.site == "all" or s.id == args.site)
        ]
        if not sites:
            raise ValueError("No enabled site matches --site")
    except Exception:
        LOG.error(
            "Invalid configuration or period; check YAML fields, unique IDs/domains, enabled sites, and YYYY-MM"
        )
        return 2
    provider_name = "mock" if args.dry_run else args.provider
    provider = (
        MockProvider()
        if provider_name == "mock"
        else OpenSEOProvider(config, args.data_dir / "raw")
    )
    store = FileStore(args.data_dir / "snapshots", provider_name)
    failures = 0
    for site in sites:
        folder = args.output_dir / provider_name / site.domain / period.key
        try:
            collected = provider.collect(site, period)
            snapshot = Snapshot(
                site=site, reporting_period=period, collection=collected
            )
            # Save factual collection before any comparison, LLM, or renderer can fail.
            store.save(snapshot)
            folder.mkdir(parents=True, exist_ok=True)
            atomic_text(folder / "seo-data.json", snapshot.model_dump_json(indent=2))
            previous = store.load_previous(site, period)
            if previous is None and provider_name == "mock":
                prior_period = month_period(period.previous_start.strftime("%Y-%m"))
                previous = Snapshot(
                    site=site,
                    reporting_period=prior_period,
                    collection=provider.collect(site, prior_period),
                )
                store.save(previous)
            elif previous is None and site.gsc_enabled:
                # GSC can be backfilled exactly; live estimates cannot.
                try:
                    prior_period = month_period(period.previous_start.strftime("%Y-%m"))
                    previous = Snapshot(
                        site=site,
                        reporting_period=prior_period,
                        collection=provider.collect(
                            site, prior_period, historical=True
                        ),
                    )
                    store.save(previous)
                except ProviderError:
                    snapshot.collection.warnings.append(
                        "Previous-period collection unavailable; changes are unknown."
                    )
            analyze(snapshot, previous, config.scoring)
            if provider_name == "openseo" and not args.no_ai:
                try:
                    snapshot.analysis = run_analysis(snapshot)
                    snapshot.analysis_status = "validated"
                except Exception:
                    snapshot.analysis_status = "unavailable_factual_fallback"
                    LOG.warning(
                        "OpenAI analysis unavailable; factual outputs retained",
                        extra={"site": site.id},
                    )
            store.save(snapshot)
            atomic_text(folder / "seo-data.json", snapshot.model_dump_json(indent=2))
            write_reports(snapshot, folder)
            if collected.audit and collected.audit.status != "completed":
                failures += 1
                LOG.error(
                    "Technical audit incomplete; PDF includes its status",
                    extra={"site": site.id},
                )
            LOG.info("Reports generated", extra={"site": site.id})
        except ProviderError as exc:
            failures += 1
            LOG.error(str(exc), extra={"site": site.id})
        except Exception:
            failures += 1
            LOG.error(
                "Report failed; factual data retained if collected. Check snapshot consistency, output permissions, and WeasyPrint native libraries.",
                extra={"site": site.id},
            )
    return 1 if failures else 0
