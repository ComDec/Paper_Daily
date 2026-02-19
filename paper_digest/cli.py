from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timezone
from pathlib import Path

from paper_digest.config import load_config
from paper_digest.pipeline import run_pipeline


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="paper-digest",
        description="Fetch, filter, score, and render a daily preprint digest.",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to YAML config file (default: config.yaml).",
    )
    parser.add_argument(
        "--date",
        type=_parse_date,
        default=None,
        help="Target date in UTC (YYYY-MM-DD). Defaults to today UTC.",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=None,
        help="Override config run.days_back.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute even if output JSON already exists.",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    cfg = load_config(Path(args.config))
    target_date = args.date or datetime.now(timezone.utc).date()
    days_back = cfg.run.days_back if args.days_back is None else args.days_back

    run_pipeline(cfg, target_date=target_date, days_back=days_back, force=args.force)
    return 0
