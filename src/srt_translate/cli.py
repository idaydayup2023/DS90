from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from .config import ensure_dirs, load_config
from .orchestrator import run_once
from .store import StateStore
import dir_migrate.config as dm_config  # Import dir_migrate config


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="srt_translate")
    p.add_argument("--config", required=True, help="path to config json")
    p.add_argument("--once", action="store_true", help="run one scan then exit")
    p.add_argument("--force", action="store_true", help="force regenerate ai.srt")
    p.add_argument("--dry-run", action="store_true", help="do not upload artifacts")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    
    # Load dir_migrate config
    try:
        migrate_cfg = dm_config.load_config(args.config)
        # Sync execution flags only if explicitly provided via CLI
        # Otherwise respect the values in config.json
        if args.dry_run:
            migrate_cfg = migrate_cfg.with_execution(dry_run=True, apply=False)
        elif args.force:
            # If force is requested for srt_translate, we assume user wants to apply changes
            # But we still respect the dry_run setting in migrate_cfg if not overridden
            pass 
    except Exception as e:
        print(f"Warning: failed to load dir_migrate config: {e}", file=sys.stderr)
        migrate_cfg = None

    ensure_dirs(cfg)

    try:
        with StateStore(cfg.paths.state_db_path) as store:
            summary = run_once(cfg, store=store, force=args.force, dry_run=args.dry_run, migrate_cfg=migrate_cfg)
            if summary.failed:
                return 2
    except KeyboardInterrupt:
        return 130

    return 0
