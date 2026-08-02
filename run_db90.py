from __future__ import annotations

import sys

from dir_migrate.cli import main as migrate_main
from srt_translate.cli import main as subtitles_main


HELP = """usage: db90 <command> [options]

DB90 version2 standalone media tool

commands:
  subtitles   scan, extract, translate, and upload subtitles
  migrate     plan or apply media-library directory migration

examples:
  db90 subtitles --config config.json --once --dry-run
  db90 migrate --config config.json --once --dry-run

Run `db90 <command> --help` for command-specific options.
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print(HELP, end="")
        return 0
    if args[0] in ("-V", "--version", "version"):
        print("DB90 version2 0.1.0")
        return 0

    command, command_args = args[0], args[1:]
    if command in ("subtitles", "subtitle", "srt"):
        return subtitles_main(command_args)
    if command in ("migrate", "migration", "dir-migrate"):
        return migrate_main(command_args)

    print(f"db90: unknown command: {command}", file=sys.stderr)
    print("Run `db90 --help` for available commands.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
