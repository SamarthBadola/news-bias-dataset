"""Look inside data/raw/: rows per outlet and lede status, plus the rows that need attention.

    python scripts/inspect_raw.py                       # counts, then every row that is not ok
    python scripts/inspect_raw.py --status too_short    # only those rows
    python scripts/inspect_raw.py --status ok --n 3     # read a few ledes before trusting the extraction
"""
import argparse
from collections import Counter

from make_stubs import read_raw


def summarize(rows):
    table = {}
    for r in rows:
        table.setdefault(r["domain"], Counter())[r.get("lede_status", "?")] += 1
    return table


def summarize_feeds(rows):
    """Count extraction outcomes by configured source feed, not only by article host."""
    table = {}
    for row in rows:
        feed = row.get("feed") or row.get("domain", "unknown")
        table.setdefault(feed, Counter())[row.get("lede_status", "?")] += 1
    return table


def select_rows(rows, status, n):
    wanted = [r for r in rows if (r.get("lede_status") == status if status else r.get("lede_status") != "ok")]
    shown, per_group = [], Counter()
    for r in wanted:
        key = (r["domain"], r.get("lede_status"))
        if per_group[key] < n:
            per_group[key] += 1
            shown.append(r)
    return shown


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", default="data/raw")
    ap.add_argument("--status", help="show only rows with this lede_status (default: everything except ok)")
    ap.add_argument("--n", type=int, default=3, help="rows to show per outlet and status")
    args = ap.parse_args(argv)
    rows = read_raw(args.raw_dir)
    print(f"{len(rows)} rows in {args.raw_dir}\n")
    for domain, counts in sorted(summarize(rows).items()):
        print(f"  {domain:<34} {dict(counts)}")
    print("\nby source feed:")
    for feed, counts in sorted(summarize_feeds(rows).items()):
        print(f"  {feed:<34} {dict(counts)}")
    shown = select_rows(rows, args.status, args.n)
    label = args.status or "not ok"
    print(f"\nrows with status {label} ({len(shown)} shown, up to {args.n} per outlet and status):")
    for r in shown:
        problem = r.get("fetch_error") or ""
        detail = f" ({r['fetch_detail']})" if r.get("fetch_detail") else ""
        print(f"\n  [{r['domain']}] {r.get('lede_status')}  words={r.get('lede_words', 0)}  {problem}{detail}")
        print(f"  {r['url']}")
        print(f"  title: {r['title'][:90]}")
        if r.get("lede"):
            print(f"  lede:  {r['lede'][:220]}")
    return shown


if __name__ == "__main__":
    main()
