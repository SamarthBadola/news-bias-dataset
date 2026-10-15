"""Validate annotation files, and optionally promote finished entries to data/gold/.

    python scripts/validate.py data/annotated/art_A1.jsonl                       # check only
    python scripts/validate.py data/annotated/art_A1.jsonl data/annotated/art_A2.jsonl --promote

Checks per row: valid JSON, required fields, no <placeholder> left anywhere, allowed label values,
rationales, span offsets, duplicate ids and URLs, leakage guards. Across files: an id must carry the same
url, title, standfirst and lede for every annotator, so both annotators label identical input.

--promote copies entries into data/gold/<split>.jsonl, where <split> is the entry's own `split` field
(eval, fewshot or pilot). It runs only when there are zero validation problems, and then:
  * a row labeled by one annotator (not in the overlap set) is promoted as it stands;
  * an overlap row is promoted only when both annotators' files are given AND they agree on every axis,
    or one of the two rows carries a non-empty `adjudicated` note saying how the disagreement was resolved;
  * otherwise it stays in annotated/ and is listed as waiting or in conflict.
Gold files are append-only: an id already in gold is skipped, and an id whose content differs is an error.
"""
import argparse
import copy
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REQUIRED = ["id", "url", "url_archive", "retrieved_at", "published", "outlet",
            "syndicated", "article_type", "event_id", "title", "standfirst", "lede",
            "lede_status", "guideline_version", "in_guideline", "pilot",
            "labels", "annotator", "split"]
ARTICLE_TYPES = {"news", "wire", "analysis", "opinion"}
SPAN_FIELDS = {"title", "lede", "standfirst"}
LEDE_MAX_WORDS, LEDE_MIN_WORDS, STANDFIRST_MAX_WORDS = 120, 25, 40
SPLITS = {"eval", "fewshot", "pilot"}
CONFIDENCE = {"low", "medium", "high"}
FINE_TUNED = {"political": {"Left", "Right", "Center"},
              "gender": {"Misogynistic", "Misandrist", "Neutral"}}
COMPARATIVE = ("communal_caste", "cultural")
COMPARATIVE_LABELS = {"biased", "symmetric"}
STATUSES = {"labeled", "no_bundle", "not_applicable"}
SHARED = ("url", "title", "standfirst", "lede")


PLACEHOLDER = re.compile(r"<[^<>]*>")


def find_placeholders(obj, path=""):
    """Yield the path of every string that is a <placeholder>, at any depth."""
    if isinstance(obj, str):
        if PLACEHOLDER.fullmatch(obj.strip()):
            yield path
    elif isinstance(obj, dict):
        for key, val in obj.items():
            yield from find_placeholders(val, f"{path}.{key}" if path else key)
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            yield from find_placeholders(val, f"{path}[{i}]")


def check_row(n, row):
    errs = []
    add = lambda msg: errs.append(f"line {n} ({row.get('id', '?')}): {msg}")
    for key in REQUIRED:
        if key not in row:
            add(f"missing field '{key}'")
    for path in find_placeholders(row):
        add(f"'{path}' is still a placeholder")
    if not re.fullmatch(r"art-\d{4}", str(row.get("id", ""))):
        add("id must look like art-0001")
    try:
        date.fromisoformat(str(row.get("published", "")))
    except ValueError:
        add("published must be YYYY-MM-DD")
    if row.get("article_type") not in ARTICLE_TYPES:
        add(f"article_type must be one of {sorted(ARTICLE_TYPES)}")
    if row.get("lede_status") != "ok":
        add("lede_status must be 'ok'; live blogs, paywall stubs and failed fetches are not annotated")
    lede_words = len(str(row.get("lede", "")).split())
    if "lede" in row and not isinstance(row["lede"], str):
        add("lede must be text")
    elif "lede" in row and not row["lede"].startswith("<") and not LEDE_MIN_WORDS <= lede_words <= LEDE_MAX_WORDS:
        add(f"lede has {lede_words} words; expected {LEDE_MIN_WORDS} to {LEDE_MAX_WORDS}")
    if len(str(row.get("standfirst", "")).split()) > STANDFIRST_MAX_WORDS:
        add(f"standfirst is longer than {STANDFIRST_MAX_WORDS} words")
    if row.get("pilot") and not isinstance(row.get("standfirst_sufficient"), bool):
        add("pilot items need standfirst_sufficient set to true or false")
    if "standfirst_sufficient" in row and not isinstance(row["standfirst_sufficient"], bool):
        add("standfirst_sufficient must be true or false")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", str(row.get("retrieved_at", ""))) \
            and not str(row.get("retrieved_at", "")).startswith("<"):
        add("retrieved_at must be a UTC timestamp like 2026-10-10T09:30:00Z")
    if row.get("split") not in SPLITS:
        add(f"split must be one of {sorted(SPLITS)}")
    if row.get("syndicated") is True and not row.get("original_source"):
        add("syndicated article needs original_source")
    if (row.get("in_guideline") or row.get("pilot")) and row.get("split") == "eval":
        add("guideline examples and pilot items must not be in the eval split")

    labels = row.get("labels", {})
    for axis, allowed in FINE_TUNED.items():
        item = labels.get(axis)
        if item is None:
            add(f"no entry for axis '{axis}'")
            continue
        if item.get("label") not in allowed:
            add(f"{axis}: label must be one of {sorted(allowed)}")
        if not item.get("rationale"):
            add(f"{axis}: label has no rationale")
        if item.get("confidence") not in CONFIDENCE:
            add(f"{axis}: confidence must be one of {sorted(CONFIDENCE)}")
        for span in item.get("spans", []):
            if span.get("field") not in SPAN_FIELDS:
                add(f"{axis}: span field must be one of {sorted(SPAN_FIELDS)}")
                continue
            text = str(row.get(span["field"], ""))[span.get("start", 0):span.get("end", 0)]
            if text != span.get("text"):
                add(f"{axis}: span offsets select '{text}', not '{span.get('text')}'")
    for axis in COMPARATIVE:
        item = labels.get(axis)
        if item is None:
            add(f"no entry for axis '{axis}'")
            continue
        status = item.get("status")
        if status not in STATUSES:
            add(f"{axis}: status must be one of {sorted(STATUSES)}")
        elif status == "labeled":
            if item.get("label") not in COMPARATIVE_LABELS:
                add(f"{axis}: label must be one of {sorted(COMPARATIVE_LABELS)}")
            if not item.get("rationale"):
                add(f"{axis}: label has no rationale")
            if not re.fullmatch(r"bun-\d{4}", str(item.get("bundle_id", ""))):
                add(f"{axis}: labeled entries need a bundle_id like bun-0001")
    return errs


def load(path):
    rows, problems = [], []
    with open(path, encoding="utf-8-sig") as f:   # tolerate the BOM some Windows editors add
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                problems.append(f"{path} line {n}: not valid JSON ({e}). JSONL needs one complete object per line.")
                continue
            problems += [f"{path} {p}" for p in check_row(n, row)]
            rows.append((n, row))
    ids, urls = {}, {}
    for n, row in rows:
        for seen, key in ((ids, "id"), (urls, "url")):
            if row.get(key) in seen:
                problems.append(f"{path} line {n}: duplicate {key} '{row.get(key)}' (also line {seen[row[key]]})")
            seen[row.get(key)] = n
    return [r for _, r in rows], problems


def label_differences(a, b):
    """Axes on which two annotators' labels differ."""
    diffs = []
    for axis in FINE_TUNED:
        if a["labels"][axis].get("label") != b["labels"][axis].get("label"):
            diffs.append(axis)
    for axis in COMPARATIVE:
        x, y = a["labels"][axis], b["labels"][axis]
        if (x.get("status"), x.get("label")) != (y.get("status"), y.get("label")):
            diffs.append(axis)
    return diffs


def read_gold(gold_dir):
    gold = {}
    for path in sorted(Path(gold_dir).glob("*.jsonl")):
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    gold[row["id"]] = row
    return gold


def build_gold_row(rid, rows, now):
    """Return (gold_row, None) or (None, (kind, detail)) where kind is waiting, conflict or error."""
    annotators = [r["annotator"] for r in rows]
    if len(set(annotators)) != len(annotators):
        return None, ("error", f"{rid}: the same annotator appears twice")
    if len({r.get("split") for r in rows}) > 1:
        return None, ("error", f"{rid}: annotators set different splits")
    overlap = any(r.get("overlap_set") for r in rows)
    if not overlap and len(rows) > 1:
        return None, ("error", f"{rid}: labeled by {len(rows)} annotators but overlap_set is false")
    note_row = next((r for r in rows if str(r.get("adjudicated", "")).strip()), None)
    if overlap and len(rows) < 2:
        return None, ("waiting", f"{rid}: overlap row, waiting for the second annotator's file")
    if overlap:
        diffs = label_differences(rows[0], rows[1])
        if diffs and not note_row:
            return None, ("conflict", f"{rid}: annotators disagree on {', '.join(diffs)}; discuss, then add an "
                                      "`adjudicated` note to the row with the final labels")
        agreement = "adjudicated" if diffs else "full"
    else:
        agreement = "single"
    final = copy.deepcopy(note_row if (overlap and note_row and agreement == "adjudicated") else rows[0])
    final.pop("annotator", None)
    note = final.pop("adjudicated", None)
    final["annotators"] = sorted(annotators)
    final["agreement"] = agreement
    final["annotations"] = {r["annotator"]: r["labels"] for r in rows}
    if note:
        final["adjudication_note"] = note
    final["promoted_at"] = now
    return final, None


def promote(by_id, gold_dir):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    gold = read_gold(gold_dir)
    new, notices, errors, skipped = [], [], [], 0
    for rid, versions in by_id.items():
        row, issue = build_gold_row(rid, [r for _, r in versions], now)
        if issue:
            (errors if issue[0] == "error" else notices).append(issue)
            continue
        if rid in gold:
            same = {k: v for k, v in gold[rid].items() if k != "promoted_at"} == \
                   {k: v for k, v in row.items() if k != "promoted_at"}
            if same:
                skipped += 1
            else:
                errors.append(("error", f"{rid}: already in gold with different content; change gold through a reviewed edit"))
            continue
        new.append(row)
    if errors:
        return {"written": {}, "notices": notices, "errors": [e[1] for e in errors], "skipped": skipped}
    written = {}
    for row in new:
        path = Path(gold_dir) / f"{row['split']}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        written[row["split"]] = written.get(row["split"], 0) + 1
    return {"written": written, "notices": notices, "errors": [], "skipped": skipped}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="annotated JSONL files (give both annotators' files for overlap rows)")
    ap.add_argument("--promote", action="store_true", help="copy finished entries into <gold-dir>/<split>.jsonl")
    ap.add_argument("--gold-dir", default="data/gold")
    args = ap.parse_args(argv)

    problems, by_id = [], {}
    for path in args.files:
        rows, probs = load(path)
        problems += probs
        for row in rows:
            by_id.setdefault(row.get("id"), []).append((path, row))
    for rid, versions in by_id.items():
        base_path, base = versions[0]
        for path, row in versions[1:]:
            for key in SHARED:
                if row.get(key) != base.get(key):
                    problems.append(f"{rid}: '{key}' differs between {base_path} and {path}")
    for p in problems:
        print(p)
    print(f"{sum(len(v) for v in by_id.values())} rows in {len(args.files)} file(s), {len(problems)} problems")
    if problems:
        if args.promote:
            print("nothing promoted: fix the problems above first")
        sys.exit(1)
    if args.promote:
        result = promote(by_id, args.gold_dir)
        for msg in result["errors"]:
            print(f"error: {msg}")
        for _, msg in result["notices"]:
            print(f"not promoted: {msg}")
        if result["errors"]:
            print("nothing promoted: fix the errors above first")
            sys.exit(1)
        for split, count in sorted(result["written"].items()):
            print(f"promoted {count} to {Path(args.gold_dir) / (split + '.jsonl')}")
        if result["skipped"]:
            print(f"{result['skipped']} already in gold, skipped")
        if not result["written"]:
            print("nothing new to promote")
    sys.exit(0)


if __name__ == "__main__":
    main()
