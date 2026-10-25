"""Remove stubs from the annotators' files, for example a recipe page or a third story about one event.

    python scripts/drop_stubs.py art-0008
    python scripts/drop_stubs.py art-0002 art-0007 art-0010

Works on every file in data/annotated/. It refuses to touch an id that is already in gold, and refuses a row that
already carries labels unless --force is given. Ids are never reused, so a gap in the numbering is normal.
No quoting tricks are needed, so the same command works in PowerShell, Git Bash and cmd.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from make_stubs import read_jsonl
from validate import find_placeholders, read_gold


def is_labeled(row):
    return not any(p.startswith("labels.political") for p in find_placeholders(row))


def plan(annotated_dir, ids, gold_ids, force):
    """Return (per-file kept rows, removed ids, refusals)."""
    kept, removed, refusals = {}, set(), []
    for path in sorted(Path(annotated_dir).glob("*.jsonl")):
        rows = read_jsonl(path)
        keep = []
        for row in rows:
            rid = row.get("id")
            if rid in ids and rid in gold_ids:
                refusals.append(f"{rid} is already in gold; change gold through a reviewed edit instead")
                keep.append(row)
            elif rid in ids and is_labeled(row) and not force:
                refusals.append(f"{rid} in {path.name} already has labels; add --force to remove it anyway")
                keep.append(row)
            elif rid in ids:
                removed.add(rid)
            else:
                keep.append(row)
        if len(keep) != len(rows):
            kept[path] = keep
    return kept, removed, refusals


def write_lf(path, rows):
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def reserve_ids(path, ids):
    """Persist removed ids before deleting rows so they can never be allocated again."""
    path = Path(path)
    existing = set(path.read_text(encoding="utf-8").splitlines()) if path.exists() else set()
    updated = sorted(existing | set(ids))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{rid}\n" for rid in updated), encoding="utf-8", newline="\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="+", help="entry ids such as art-0008")
    ap.add_argument("--annotated-dir", default="data/annotated")
    ap.add_argument("--gold-dir", default="data/gold")
    ap.add_argument("--force", action="store_true", help="also remove rows that already have labels")
    args = ap.parse_args(argv)
    gold_ids = set(read_gold(args.gold_dir)) if Path(args.gold_dir).is_dir() else set()
    wanted = set(args.ids)
    kept, removed, refusals = plan(args.annotated_dir, wanted, gold_ids, args.force)
    for msg in refusals:
        print(f"not removed: {msg}")
    if removed:
        reserve_ids(Path(args.annotated_dir) / "retired_ids.txt", removed)
    for path, rows in kept.items():
        write_lf(path, rows)
        print(f"updated {path} ({len(rows)} rows left)")
    missing = sorted(wanted - removed - {m.split(" ")[0] for m in refusals})
    if missing:
        print(f"not found in {args.annotated_dir}: {', '.join(missing)}")
    print(f"removed {len(removed)} id(s): {', '.join(sorted(removed)) or 'none'}")
    sys.exit(1 if refusals or missing else 0)


if __name__ == "__main__":
    main()
