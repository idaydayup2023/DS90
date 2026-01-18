from __future__ import annotations

import argparse
import sys

sys.dont_write_bytecode = True

from .config import ensure_dirs, load_config
from .logging_util import setup_logging
from .orchestrator import run_once


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dir_migrate")
    p.add_argument("--config", required=True, help="path to config json")
    p.add_argument("--once", action="store_true", help="run one scan then exit")
    p.add_argument("--dry-run", action="store_true", help="only print plan, do not move files")
    p.add_argument("--apply", action="store_true", help="perform moves")
    p.add_argument("--limit", type=int, default=None, help="limit number of videos")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    ensure_dirs(cfg)
    setup_logging()
    if args.dry_run:
        cfg = cfg.with_execution(dry_run=True, apply=False, limit=args.limit)
    if args.apply:
        cfg = cfg.with_execution(dry_run=False, apply=True, limit=args.limit)
    try:
        summary = run_once(cfg)
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"dir_migrate failed: {e}", file=sys.stderr)
        return 2
    if summary.failed:
        return 2
    return 0
