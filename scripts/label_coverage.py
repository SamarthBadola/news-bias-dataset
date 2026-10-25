"""Report class coverage in annotated or gold JSONL files without changing labels.

    python scripts/label_coverage.py data/gold/eval.jsonl
    python scripts/label_coverage.py --min-per-class 8 data/annotated/art_A1.jsonl

The default floor is an operational coverage goal for a small course project, not a claim of statistical precision.
"""
import argparse
import json
from collections import Counter


CLASSES = {
    "political": ("Left", "Center", "Right"),
    "gender": ("Misogynistic", "Misandrist", "Neutral"),
}
COMPARATIVE = ("communal_caste", "cultural")


def read_rows(path):
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"warning: {path} line {line_no}: invalid JSON ({exc})")
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def label_counts(rows, axis, classes):
    counts = Counter()
    pending = 0
    for row in rows:
        value = (row.get("labels") or {}).get(axis, {}).get("label")
        if value in classes:
            counts[value] += 1
        else:
            pending += 1
    return counts, pending


def report(path, min_per_class=8):
    rows = read_rows(path)
    print(f"\n{path}: {len(rows)} rows")
    for axis, classes in CLASSES.items():
        counts, pending = label_counts(rows, axis, classes)
        summary = ", ".join(f"{label}={counts[label]}" for label in classes)
        gaps = [f"{label} needs {min_per_class - counts[label]}" for label in classes
                if counts[label] < min_per_class]
        suffix = f"; below floor: {', '.join(gaps)}" if gaps else "; floor met"
        print(f"  {axis}: {summary}; pending={pending}{suffix}")
    for axis in COMPARATIVE:
        statuses = Counter((row.get("labels") or {}).get(axis, {}).get("status", "pending") for row in rows)
        labels = Counter((row.get("labels") or {}).get(axis, {}).get("label")
                         for row in rows if (row.get("labels") or {}).get(axis, {}).get("status") == "labeled")
        print(f"  {axis}: bundles={dict(labels)}; statuses={dict(statuses)}")
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", help="annotated or gold JSONL files, reported separately")
    parser.add_argument("--min-per-class", type=int, default=8,
                        help="coverage floor for each political and gender class (default: 8)")
    args = parser.parse_args(argv)
    if args.min_per_class < 1:
        parser.error("--min-per-class must be at least 1")
    for path in args.files:
        report(path, args.min_per_class)


if __name__ == "__main__":
    main()
