"""CLI entry point for spnews."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from .config import Settings, get_settings
from .db import dumps_json, get_status_summary, init_db
from .pipeline import run_full_pipeline, run_generate, run_ingest_and_embed
from .site import build_site, build_site_from_reports
from .sources import ALL_SPORT_KEYS


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("trafilatura").setLevel(logging.WARNING)


def _add_sports_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-s",
        "--sports",
        nargs="+",
        choices=list(ALL_SPORT_KEYS),
        default=None,
        help="Target sports (default: all)",
    )


def _deploy_cf_pages(dist_dir: Path, project_name: str, settings: Settings) -> None:
    env = os.environ.copy()
    if settings.cloudflare_api_token:
        env["CLOUDFLARE_API_TOKEN"] = settings.cloudflare_api_token
    if settings.cloudflare_account_id:
        env["CLOUDFLARE_ACCOUNT_ID"] = settings.cloudflare_account_id
    cmd = [
        "npx",
        "--yes",
        "wrangler",
        "pages",
        "deploy",
        str(dist_dir),
        f"--project-name={project_name}",
    ]
    print(f"Deploying to Cloudflare Pages: {' '.join(cmd)}")
    subprocess.run(cmd, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="spnews",
        description="Automated sports daily news aggregator & static site generator",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="Initialize PostgreSQL tables and pgvector extension")

    p_ingest = sub.add_parser("ingest", help="Fetch RSS feeds and embed pending articles")
    _add_sports_arg(p_ingest)

    p_gen = sub.add_parser("generate", help="Cluster, enrich, and summarize pending articles")
    _add_sports_arg(p_gen)
    p_gen.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without committing events/reports or marking articles processed",
    )
    p_gen.add_argument("--llm-base-url", type=str, default=None, help="Override LLM_BASE_URL")
    p_gen.add_argument("--llm-model", type=str, default=None, help="Override LLM_MODEL")
    p_gen.add_argument("-o", "--output-json", type=str, default=None, help="Write report JSON")
    p_gen.add_argument(
        "--preview-dir",
        type=str,
        default=None,
        help="Render a standalone static HTML preview of this report into a folder",
    )

    p_build = sub.add_parser("build", help="Render static site and RSS feed from PostgreSQL")
    p_build.add_argument("-o", "--output-dir", type=str, default="dist", help="Output directory")
    p_build.add_argument("--deploy", action="store_true", help="Deploy output dir via wrangler pages")
    p_build.add_argument(
        "--cf-project", type=str, default=None, help="Cloudflare Pages project name"
    )

    p_run = sub.add_parser("run", help="Full daily pipeline: ingest -> generate -> build")
    _add_sports_arg(p_run)
    p_run.add_argument("--dry-run", action="store_true", help="Dry-run generate (ingest still runs)")
    p_run.add_argument("--skip-build", action="store_true", help="Skip static site build")
    p_run.add_argument("-o", "--output-dir", type=str, default="dist", help="Static output directory")
    p_run.add_argument("--deploy", action="store_true", help="Deploy dist/ via wrangler pages")
    p_run.add_argument(
        "--cf-project", type=str, default=None, help="Cloudflare Pages project name"
    )

    sub.add_parser("status", help="Show database counts and recent runs")

    args = parser.parse_args()
    _setup_logging(args.verbose)
    settings = get_settings()

    if args.cmd == "init-db":
        init_db(settings)
        print("PostgreSQL schema initialized.")
        return

    if args.cmd == "status":
        summary = get_status_summary(settings.spnews_database_url)
        print(dumps_json(summary))
        return

    if args.cmd == "ingest":
        init_db(settings)
        stats = asyncio.run(run_ingest_and_embed(settings, sports=args.sports))
        print(dumps_json(stats))
        return

    if args.cmd == "generate":
        report_json, stats = asyncio.run(
            run_generate(
                settings,
                sports=args.sports,
                dry_run=args.dry_run,
                llm_base_url=args.llm_base_url,
                llm_model=args.llm_model,
            )
        )
        if args.output_json:
            out_p = Path(args.output_json)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Saved report JSON to {out_p}")
        if args.preview_dir:
            res = build_site_from_reports(
                [report_json], output_dir=Path(args.preview_dir), site_url=settings.site_url
            )
            print(f"Preview site built: {res}")
        print(dumps_json(stats))
        return

    if args.cmd == "build":
        res = build_site(settings, output_dir=Path(args.output_dir))
        if args.deploy:
            _deploy_cf_pages(
                Path(args.output_dir),
                args.cf_project or settings.cf_pages_project,
                settings,
            )
        print(dumps_json(res))
        return

    if args.cmd == "run":
        report_json, stats = asyncio.run(
            run_full_pipeline(settings, sports=args.sports, dry_run=args.dry_run)
        )
        if not args.skip_build and not args.dry_run:
            stats["build"] = build_site(settings, output_dir=Path(args.output_dir))
            if args.deploy:
                _deploy_cf_pages(
                    Path(args.output_dir),
                    args.cf_project or settings.cf_pages_project,
                    settings,
                )
        elif args.dry_run and not args.skip_build:
            stats["preview_build"] = build_site_from_reports(
                [report_json], output_dir=Path(args.output_dir), site_url=settings.site_url
            )
        print(dumps_json(stats))
        return

    sys.exit(1)


if __name__ == "__main__":
    main()
