from __future__ import annotations

import argparse
import sys
from pathlib import Path

from seo_pipeline.analysis.openai_analysis import OpenAIAnalyzer
from seo_pipeline.config import ConfigurationError, load_config
from seo_pipeline.logging_config import configure_logging
from seo_pipeline.periods import resolve_period
from seo_pipeline.pipeline import PipelineRunner
from seo_pipeline.providers import MockSEOProvider, OpenSEOProvider
from seo_pipeline.storage import FileSystemSnapshotStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seo-pipeline",
        description="Collect, compare, analyze, and report multi-site SEO performance.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    report = subparsers.add_parser("report", help="Generate SEO reports")
    report.add_argument("--site", default="all", help="Site ID or 'all'")
    report.add_argument("--period", help="Complete calendar month in YYYY-MM format")
    report.add_argument(
        "--output-dir", type=Path, default=Path("output"), help="Report output root"
    )
    report.add_argument(
        "--data-dir", type=Path, default=Path("data/snapshots"), help="Snapshot storage root"
    )
    report.add_argument(
        "--config", type=Path, default=Path("config/sites.yaml"), help="Sites YAML file"
    )
    report.add_argument(
        "--provider", choices=("openseo", "mock"), default="openseo"
    )
    report.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and show selected work without external calls or writes",
    )
    report.add_argument(
        "--no-ai", action="store_true", help="Use deterministic analysis without OpenAI"
    )
    return parser


def _report(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
        sites = config.select_sites(args.site)
        period = resolve_period(args.period)
    except (ConfigurationError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        print(
            f"Dry run: provider={args.provider}, period={period.key}, "
            f"sites={','.join(site.id for site in sites)}"
        )
        return 0

    provider = MockSEOProvider() if args.provider == "mock" else OpenSEOProvider()
    analyzer = OpenAIAnalyzer(api_key="") if args.no_ai or args.provider == "mock" else OpenAIAnalyzer()
    runner = PipelineRunner(
        provider=provider,
        store=FileSystemSnapshotStore(args.data_dir),
        output_root=args.output_dir,
        opportunity_settings=config.opportunities,
        analyzer=analyzer,
    )
    results = runner.run(sites, period)
    failures = [result for result in results if not result.success]
    for result in results:
        if result.success:
            print(f"OK {result.site_id}: {result.output_directory}")
        else:
            print(f"FAILED {result.site_id}: {result.error}", file=sys.stderr)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    if args.command == "report":
        return _report(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

