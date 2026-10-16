"""Merge a Label Studio export back into the annotator's stub file.

    python scripts/ls_import.py --export labelstudio/A1_export.json --stubs data/annotated/art_A1.jsonl
    python scripts/ls_import.py --export ... --stubs ... --comparative not_applicable

Export from Label Studio as JSON (the full format, not JSON-MIN or CSV). Tasks are matched to stubs by the
`id` in the task data. Per task, the most recent annotation that was not cancelled is used. A row is updated
only when its political and gender labels, confidences, rationales and the article type are all present;
otherwise it stays untouched and is listed. Span offsets are recomputed from the highlighted text, so they
count Python characters even though the browser counts UTF-16 units.

--comparative sets communal_caste and cultural to the given status for rows where they are still
placeholders. Use it only when you have decided that none of the sampled articles belongs to a comparison
bundle. Rows that already have labels are not overwritten unless --overwrite is given.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from make_stubs import read_jsonl
from validate import find_placeholders

AXES = ("political", "gender")
SPAN_FIELDS = {"title_spans": "title", "lede_spans": "lede"}
SPAN_LABELS = {"political_evidence": "political", "gender_evidence": "gender"}


def latest_annotation(task):
    live = [a for a in task.get("annotations", []) if not a.get("was_cancelled")]
    return live[-1] if live else None


def parse_results(annotation):
    """Flatten Label Studio results into choices, texts and spans."""
    choices, texts, spans = {}, {}, []
    for res in annotation.get("result", []):
        name, kind, value = res.get("from_name"), res.get("type"), res.get("value", {})
        if kind == "choices" and value.get("choices"):
            choices[name] = value["choices"][0]
        elif kind == "textarea" and value.get("text"):
            texts[name] = " ".join(value["text"]).strip()
        elif kind == "labels" and name in SPAN_FIELDS:
            spans.append({"field": SPAN_FIELDS[name], "ls_start": value.get("start", 0),
                          "text": value.get("text", ""), "labels": value.get("labels", [])})
    return choices, texts, spans


def locate(row, span):
    """Character offsets of a highlighted phrase; if it occurs more than once, the occurrence nearest the click."""
    field_text = row[span["field"]]
    phrase = span["text"]
    if not phrase:
        return None
    starts, i = [], field_text.find(phrase)
    while i != -1:
        starts.append(i)
        i = field_text.find(phrase, i + 1)
    if not starts:
        return None
    start = min(starts, key=lambda s: abs(s - span["ls_start"]))
    return start, start + len(phrase)


def apply_annotation(row, annotation, comparative=None):
    """Return (updated_row, problems). The row is unchanged when problems is non-empty."""
    choices, texts, spans = parse_results(annotation)
    problems = []
    for axis in AXES:
        for part, source in (("label", choices.get(axis)), ("confidence", choices.get(f"{axis}_confidence")),
                             ("rationale", texts.get(f"{axis}_rationale"))):
            if not source:
                problems.append(f"{axis} {part} is missing")
    if not choices.get("article_type"):
        problems.append("article type is missing")
    if row.get("pilot") and not choices.get("standfirst_sufficient"):
        problems.append("pilot row: standfirst_sufficient is missing")
    if problems:
        return row, problems

    updated = json.loads(json.dumps(row))
    for axis in AXES:
        item = updated["labels"][axis]
        item.update(label=choices[axis], confidence=choices[f"{axis}_confidence"], rationale=texts[f"{axis}_rationale"])
        item["spans"] = []
    updated["article_type"] = choices["article_type"]
    if row.get("pilot"):
        updated["standfirst_sufficient"] = choices["standfirst_sufficient"] == "yes"
    for span in spans:
        for label in span["labels"]:
            axis = SPAN_LABELS.get(label)
            offsets = locate(updated, span)
            if axis is None:
                problems.append(f"unknown span label '{label}'")
            elif offsets is None:
                problems.append(f"highlighted text not found in {span['field']}: '{span['text'][:40]}'")
            else:
                entry = {"field": span["field"], "start": offsets[0], "end": offsets[1], "text": span["text"]}
                if entry not in updated["labels"][axis]["spans"]:
                    updated["labels"][axis]["spans"].append(entry)
    if problems:
        return row, problems
    if comparative:
        for axis in ("communal_caste", "cultural"):
            if any(p.startswith(f"labels.{axis}") for p in find_placeholders(updated)):
                updated["labels"][axis] = {"status": comparative}
    return updated, []


def merge(rows, tasks, comparative=None, overwrite=False):
    by_id = {r["id"]: i for i, r in enumerate(rows)}
    report = {"updated": [], "skipped_labeled": [], "incomplete": {}, "unknown_id": [], "no_annotation": []}
    for task in tasks:
        rid = task.get("data", {}).get("id")
        if rid not in by_id:
            report["unknown_id"].append(rid)
            continue
        annotation = latest_annotation(task)
        if annotation is None:
            report["no_annotation"].append(rid)
            continue
        idx = by_id[rid]
        already = not any(p.startswith("labels.political") for p in find_placeholders(rows[idx]))
        if already and not overwrite:
            report["skipped_labeled"].append(rid)
            continue
        new_row, problems = apply_annotation(rows[idx], annotation, comparative)
        if problems:
            report["incomplete"][rid] = problems
        else:
            rows[idx] = new_row
            report["updated"].append(rid)
    return rows, report


def write_atomic(path, rows):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export", required=True, help="Label Studio JSON export")
    ap.add_argument("--stubs", required=True, help="the annotator's file in data/annotated/, updated in place")
    ap.add_argument("--comparative", choices=["not_applicable", "no_bundle"],
                    help="status for communal_caste and cultural where still a placeholder")
    ap.add_argument("--overwrite", action="store_true", help="replace labels on rows that already have them")
    args = ap.parse_args(argv)
    tasks = json.loads(Path(args.export).read_text(encoding="utf-8-sig"))
    if not isinstance(tasks, list):
        sys.exit("the export must be a JSON list of tasks (export in the full JSON format)")
    rows = read_jsonl(args.stubs)
    rows, report = merge(rows, tasks, args.comparative, args.overwrite)
    if report["updated"]:
        write_atomic(args.stubs, rows)
    print(f"updated {len(report['updated'])} rows in {args.stubs}")
    for key, label in (("skipped_labeled", "already labeled, left alone (use --overwrite to replace)"),
                       ("no_annotation", "task has no usable annotation yet"),
                       ("unknown_id", "task id not found in the stub file")):
        if report[key]:
            print(f"{len(report[key])} {label}: {', '.join(map(str, report[key]))}")
    for rid, problems in report["incomplete"].items():
        print(f"{rid} not updated: {'; '.join(problems)}")
    return report


if __name__ == "__main__":
    main()
