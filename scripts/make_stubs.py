"""Turn collected raw articles into annotation stubs.

    python scripts/make_stubs.py --annotator A1 --n 40 --overlap 20 --pilot
    python scripts/make_stubs.py --annotator A1 --pick https://example.com/a-story
    python scripts/make_stubs.py --annotator A1 --n 6 --split fewshot
    python scripts/make_stubs.py --annotator A2 --clone data/annotated/art_A1.jsonl

A stub is a complete dataset entry. Everything the machine knows is filled in; everything a human must
decide stays a <placeholder>, and validate.py rejects the entry until none are left. Raw files are never
modified. Ids are assigned here in order and never reused (annotated and gold files are both checked).

Only the dataset maintainer runs this, after pulling the latest annotated/ and gold/ files, so two people
never hand out the same id. --clone copies another annotator's overlap rows with the labels reset, so both
annotators label identical input.
"""
import argparse
import copy
import json
import random
import re
import sys
from pathlib import Path

import api_audit as aa
from collect import canonical

GUIDELINE_VERSION = "1.1"
DOMAIN_NAMES = {domain: name for name, domain in aa.TARGETS.items()}
TO_CONFIRM = "<true|false>"


def empty_labels():
    return {
        "political": {"label": "<Left|Right|Center>", "confidence": "<low|medium|high>",
                      "rationale": "<one line: the words or framing that drove the label>", "spans": []},
        "gender": {"label": "<Misogynistic|Misandrist|Neutral>", "confidence": "<low|medium|high>",
                   "rationale": "<one line: the words or framing that drove the label>", "spans": []},
        "communal_caste": {"status": "<labeled|no_bundle|not_applicable>"},
        "cultural": {"status": "<labeled|no_bundle|not_applicable>"},
    }


def read_jsonl(path):
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"  warning: {Path(path).name} line {n} is not valid JSON; ignored")
    return rows


def read_raw(raw_dir):
    """Latest raw row per canonical URL."""
    rows = {}
    for path in sorted(Path(raw_dir).glob("*.jsonl")):
        for row in read_jsonl(path):
            rows[row.get("canonical_url") or canonical(row["url"])] = row
    return list(rows.values())


def scan_taken(*dirs):
    """Highest art id used, plus the URLs and lede hashes already taken, across annotated and gold files."""
    top, urls, hashes = 0, set(), set()
    for d in dirs:
        for path in sorted(Path(d).glob("*.jsonl")):
            for row in read_jsonl(path):
                m = re.fullmatch(r"art-(\d{4})", str(row.get("id", "")))
                top = max(top, int(m.group(1))) if m else top
                urls.add(canonical(row["url"]) if row.get("url") else "")
                hashes.add((row.get("meta") or {}).get("lede_hash", ""))
    return top, urls, hashes - {""}


def select(rows, n, seed, domain_cap, domains, since, taken_urls, taken_hashes):
    pool = [r for r in rows if r.get("lede_status") == "ok" and r.get("lede")]
    if domains:
        pool = [r for r in pool if r["domain"] in domains]
    if since:
        pool = [r for r in pool if (r.get("published_utc") or "")[:10] >= since]
    random.Random(seed).shuffle(pool)
    chosen, per_domain, hashes = [], {}, set(taken_hashes)
    for r in pool:
        cu = r.get("canonical_url") or canonical(r["url"])
        if cu in taken_urls or (r.get("lede_hash") and r["lede_hash"] in hashes):
            continue
        if domain_cap and per_domain.get(r["domain"], 0) >= domain_cap:
            continue
        chosen.append(r)
        per_domain[r["domain"]] = per_domain.get(r["domain"], 0) + 1
        hashes.add(r.get("lede_hash", ""))
        if len(chosen) == n:
            break
    return chosen


def pick(rows, urls, taken_urls):
    """Specific articles chosen by URL, in the order given."""
    by_url = {(r.get("canonical_url") or canonical(r["url"])): r for r in rows}
    chosen = []
    for u in urls:
        cu = canonical(u)
        row = by_url.get(cu)
        if cu in taken_urls:
            print(f"  skipped (already has an entry): {u}")
        elif row is None:
            print(f"  not in raw (run collect.py --url first): {u}")
        elif row.get("lede_status") != "ok":
            print(f"  skipped (lede_status is {row.get('lede_status')}): {u}")
        else:
            chosen.append(row)
    return chosen


def syndication_fields(agency_hint):
    """No agency name in the text means not syndicated; otherwise a human confirms from the page."""
    if agency_hint:
        return "<true|false>", f"<agency name if syndicated, else an empty string; text mentions {', '.join(agency_hint)}>"
    return False, ""


def make_stub(raw, art_id, annotator, pilot, overlap, guideline_version=GUIDELINE_VERSION, split="eval"):
    syndicated, original_source = syndication_fields(raw.get("agency_hint") or [])
    stub = {
        "id": art_id,
        "url": raw["url"],
        "url_archive": "",
        "retrieved_at": raw["retrieved_at"],
        "published": (raw.get("published_utc") or "")[:10] or "<YYYY-MM-DD>",
        "outlet": DOMAIN_NAMES.get(raw["domain"], raw["domain"]),
        "original_source": original_source,
        "syndicated": syndicated,
        "article_type": "opinion" if raw.get("type_hint") == "opinion" else "<news|wire|analysis|opinion>",
        "event_id": "",
        "title": raw["title"],
        "standfirst": raw.get("standfirst", ""),
        "lede": raw["lede"],
        "lede_status": "ok",
        "guideline_version": guideline_version,
        "in_guideline": False,
        "pilot": pilot,
    }
    if pilot:
        stub["standfirst_sufficient"] = TO_CONFIRM
    stub.update({
        "labels": empty_labels(),
        "annotator": annotator,
        "overlap_set": overlap,
        "split": "pilot" if pilot else split,
        "meta": {"feed": raw.get("feed", ""), "category": raw.get("category", ""),
                 "agency_hint": raw.get("agency_hint", []), "lede_hash": raw.get("lede_hash", ""),
                 "canonical_url": raw.get("canonical_url", "")},
    })
    return stub


def clone_stub(source_row, annotator):
    """Same input and same facts about the article, fresh judgments, new annotator."""
    stub = copy.deepcopy(source_row)
    stub["labels"] = empty_labels()
    stub["annotator"] = annotator
    stub.pop("standfirst_sufficient", None)
    if stub.get("pilot"):
        stub["standfirst_sufficient"] = TO_CONFIRM
    stub["article_type"] = "<news|wire|analysis|opinion>"
    for key in ("adjudicated",):
        stub.pop(key, None)
    return stub


def append_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--annotator", required=True, help="A1 or A2; output goes to <annotated-dir>/art_<annotator>.jsonl")
    ap.add_argument("--n", type=int, default=20, help="how many new articles to sample from raw")
    ap.add_argument("--pick", action="append", help="use this specific article (a URL already in raw); repeatable")
    ap.add_argument("--overlap", type=int, default=0, help="mark the first K articles as the shared overlap set")
    ap.add_argument("--pilot", action="store_true", help="pilot batch: split=pilot and standfirst_sufficient required")
    ap.add_argument("--split", choices=["eval", "fewshot"], default="eval",
                    help="where finished entries go in data/gold/ (pilot batches always go to pilot)")
    ap.add_argument("--clone", help="another annotator's file: copy its overlap rows with the labels reset")
    ap.add_argument("--domain", action="append", help="only sample these domains (repeatable)")
    ap.add_argument("--since", help="only articles published on or after YYYY-MM-DD")
    ap.add_argument("--per-domain-cap", type=int, default=5, help="max sampled per outlet in one run (0 = no cap)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--raw-dir", default="data/raw")
    ap.add_argument("--annotated-dir", default="data/annotated")
    ap.add_argument("--gold-dir", default="data/gold")
    args = ap.parse_args(argv)
    if args.pilot and args.split != "eval":
        ap.error("--pilot entries always use the pilot split; drop --split")

    out_path = Path(args.annotated_dir) / f"art_{args.annotator}.jsonl"
    existing = read_jsonl(out_path) if out_path.exists() else []
    have_ids = {r.get("id") for r in existing}

    if args.clone:
        stubs = [clone_stub(r, args.annotator) for r in read_jsonl(args.clone)
                 if r.get("overlap_set") and r.get("id") not in have_ids]
        if not stubs:
            print("no new overlap rows to clone")
            return []
    else:
        top, taken_urls, taken_hashes = scan_taken(args.annotated_dir, args.gold_dir)
        rows = read_raw(args.raw_dir)
        if args.pick:
            picked = pick(rows, args.pick, taken_urls)
        else:
            picked = select(rows, args.n, args.seed, args.per_domain_cap, set(args.domain or []),
                            args.since, taken_urls, taken_hashes)
            if len(picked) < args.n:
                print(f"only {len(picked)} eligible articles found (asked for {args.n}); collect more or relax the filters")
        stubs = [make_stub(r, f"art-{top + i:04d}", args.annotator, args.pilot, i <= args.overlap, split=args.split)
                 for i, r in enumerate(picked, 1)]
    append_jsonl(out_path, stubs)
    print(f"wrote {len(stubs)} stubs to {out_path}")
    for s in stubs[:3]:
        print(f"  {s['id']}  {s['outlet']:<18} {s['title'][:70]}")
    return stubs


if __name__ == "__main__":
    sys.exit(0 if main() is not None else 1)
