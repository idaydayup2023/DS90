from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from srt_translate.locked_venv import sync_locked_venv


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install DB90 optional dependencies from hashed lock files."
    )
    parser.add_argument(
        "groups",
        nargs="*",
        choices=("asr", "ocr", "imdb"),
        default=("asr", "ocr", "imdb"),
        help="dependency groups to install (default: all)",
    )
    parser.add_argument(
        "--srt-cache-dir",
        type=Path,
        default=ROOT / ".cache" / "srt_translate",
    )
    parser.add_argument(
        "--dir-migrate-cache-dir",
        type=Path,
        default=ROOT / ".cache" / "dir_migrate",
    )
    parser.add_argument(
        "--wheelhouse-root",
        type=Path,
        help="install offline from GROUP subdirectories under this path",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    groups = args.groups or ("asr", "ocr", "imdb")
    specs = {
        "asr": (args.srt_cache_dir / "tools" / "whisper_venv", "asr.lock", 1800),
        "ocr": (args.srt_cache_dir / "tools" / "pgsrip_venv", "ocr.lock", 1200),
        "imdb": (args.dir_migrate_cache_dir / "tools" / "imdb_venv", "imdb.lock", 1200),
    }

    failed = False
    for group in groups:
        venv_dir, lock_name, timeout = specs[group]
        print(f"[{group}] syncing {lock_name} -> {venv_dir}")
        find_links = args.wheelhouse_root / group if args.wheelhouse_root else None
        ok, error = sync_locked_venv(
            venv_dir,
            lock_name,
            timeout=timeout,
            find_links=find_links,
        )
        if ok:
            print(f"[{group}] ready")
        else:
            failed = True
            print(f"[{group}] failed: {error}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
