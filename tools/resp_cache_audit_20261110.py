#!/usr/bin/env python3
"""Read-only audit of the DS90 translation response cache (station order 2026-11-10).

The cache write gate used to accept any structurally valid audit envelope,
which froze one-off empty answers such as {"corrections":[]} into permanent
replays (item-4 cue-429 deterministic-death case, fixed in commit 5963690 by
audit_response_is_cachable). This tool scans an existing cache directory and
reports every entry it would now consider poison, so the operator can review
the list, take a backup, and clear the flagged entries manually.

SAFETY: this script NEVER writes into, moves, or deletes a cache entry. The
only file it produces is the roll report (default: stdout plus --roll path).

Exit codes: 0 clean, 2 poison entries found, 1 usage/IO error.

Usage:
    python3 tools/resp_cache_audit_20261110.py CACHE_DIR [--roll ROLL.json]
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

KEY_NAME = re.compile(r"^[0-9a-f]{64}\.json$")

CLASSES = (
    "ok_translations",
    "ok_corrections",
    "ok_single_item",
    "ok_tmp_inflight",
    "poison_empty_shell",
    "suspect_unparseable",
    "suspect_other_shape",
    "suspect_name",
)


def classify(text):
    """Classify one raw cached model response.

    An empty shell (no translation item, no correction item) is the failed
    response the new write gate keeps off disk: {} , [] , {"translations":[]}
    and {"corrections":[]} all land in poison_empty_shell. Raw arrays of
    {"index","text"} items are the accepted bare-envelope shapes both call
    sites parse, so they count as ok (their emptiness check happened on the
    way in).
    """
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "suspect_unparseable"
    if isinstance(value, dict):
        for key, ok_class in (("translations", "ok_translations"), ("corrections", "ok_corrections")):
            if key in value:
                items = value[key]
                if isinstance(items, list) and len(items) == 0:
                    return "poison_empty_shell"
                if isinstance(items, list) and all(
                    isinstance(item, dict) and "index" in item for item in items
                ):
                    return ok_class
                return "suspect_other_shape"
        if "index" in value and "text" in value:
            return "ok_single_item"
        if not value:
            return "poison_empty_shell"
        return "suspect_other_shape"
    if isinstance(value, list):
        if not value:
            return "poison_empty_shell"
        if all(isinstance(item, dict) and "index" in item for item in value):
            return "ok_single_item" if len(value) == 1 else "ok_translations"
        return "suspect_other_shape"
    return "suspect_other_shape"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cache_dir")
    parser.add_argument("--roll", default=None, help="write the full roll here (JSON)")
    args = parser.parse_args()

    root = Path(args.cache_dir)
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 1

    entries = []
    counts = {name: 0 for name in CLASSES}
    paths = sorted(root.iterdir(), key=lambda p: p.name)
    for path in paths:
        if not path.is_file():
            continue
        if path.name.startswith("."):
            # transient temp file of a concurrent put (written then renamed);
            # never replayable, informational only
            entry = {"file": path.name, "class": "ok_tmp_inflight", "note": "tmp/partial"}
        else:
            name_class = None if KEY_NAME.match(path.name) else "suspect_name"
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                text = None
                klass = "suspect_unparseable"
                note = f"{error.__class__.__name__}: {error}"
            if text is not None:
                klass = classify(text)
                note = None
            entry = {"file": path.name, "class": klass}
            if note:
                entry["note"] = note
            if name_class and klass != "suspect_unparseable":
                entry["name_class"] = name_class
                klass = "suspect_name"
                entry["class"] = klass
        stat = path.stat()
        entry["size"] = stat.st_size
        entry["mtime"] = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        counts[entry["class"]] += 1
        entries.append(entry)

    poison = [e for e in entries if e["class"].startswith("poison") or e["class"].startswith("suspect")]
    roll = {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "cache_dir": str(root),
        "total": len(entries),
        "counts": counts,
        "poison_count": len(poison),
        "entries": entries,
    }
    if args.roll:
        roll_path = Path(args.roll)
        roll_path.parent.mkdir(parents=True, exist_ok=True)
        roll_path.write_text(json.dumps(roll, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"cache_dir={root} total={len(entries)}")
    for name, count in counts.items():
        if count:
            print(f"  {name}={count}")
    for entry in poison:
        print(f"  FLAG {entry['class']} {entry['file']} size={entry['size']} mtime={entry['mtime']}"
              + (f" note={entry['note']}" if entry.get("note") else ""))
    if poison:
        print(f"poison/suspect={len(poison)} — 报批后先整目录备份再清，勿直接删")
        return 2
    print("clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
