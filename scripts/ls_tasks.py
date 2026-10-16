"""Turn an annotator's stub file into a blinded Label Studio task file.

    python scripts/ls_tasks.py --stubs data/annotated/art_A1.jsonl --out labelstudio/A1_tasks.json

The task file holds only the id, headline, lede and (for pilot rows) the standfirst. The URL, outlet, feed and
every other field stay in the stub file, so annotators cannot see which outlet wrote an article. Tasks are
shuffled, with a different order for each annotator. Rows that already carry labels are left out unless --all.
"""
import argparse
import json
import random
import sys
from pathlib import Path

from make_stubs import read_jsonl
from validate import find_placeholders

BLIND_KEYS = {"id", "title", "lede", "standfirst"}
NOT_USED = "(not used in this batch)"


def is_unlabeled(row):
    return any(p.startswith("labels.political") for p in find_placeholders(row))


def to_task(row):
    standfirst = row.get("standfirst") or "(this article has no standfirst)"
    task = {"data": {"id": row["id"], "title": row["title"], "lede": row["lede"],
                     "standfirst": standfirst if row.get("pilot") else NOT_USED}}
    assert set(task["data"]) == BLIND_KEYS
    return task


def build_tasks(rows, seed, include_all=False):
    chosen = [r for r in rows if include_all or is_unlabeled(r)]
    random.Random(seed).shuffle(chosen)
    return [to_task(r) for r in chosen]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stubs", required=True, help="the annotator's file in data/annotated/")
    ap.add_argument("--out", required=True, help="Label Studio task file to write (JSON)")
    ap.add_argument("--seed", help="shuffle seed; defaults to the annotator's name so each annotator gets their own order")
    ap.add_argument("--all", action="store_true", help="include rows that already have labels")
    args = ap.parse_args(argv)
    rows = read_jsonl(args.stubs)
    if not rows:
        sys.exit(f"no rows in {args.stubs}")
    seed = args.seed or rows[0].get("annotator", "")
    tasks = build_tasks(rows, seed, args.all)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(tasks)} tasks to {args.out} ({len(rows) - len(tasks)} rows skipped: already labeled)")
    return tasks


if __name__ == "__main__":
    main()
