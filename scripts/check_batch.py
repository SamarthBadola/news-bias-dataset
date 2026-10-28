"""Read-only checks on either side of Label Studio. Nothing is written.

    python scripts/check_batch.py tasks  --stubs data/annotated/art_A1.jsonl --tasks labelstudio/A1_tasks.json
    python scripts/check_batch.py export --stubs data/annotated/art_A1.jsonl --export labelstudio/A1_export.json

tasks   Run before importing the task file into Label Studio. Confirms that it matches your unlabeled stubs
        exactly and that nothing in it reveals the outlet (URL, domain or outlet name in the text).
export  Run after exporting and before ls_import.py. Confirms the export is the full JSON format, belongs to this
        stub file, is complete, comes from one annotator, and looks like real reading (lead times, label mix).

Exit code 1 means at least one ERROR. Warnings need a human look but do not block.
"""
import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from ls_import import apply_annotation, latest_annotation, parse_results
from ls_tasks import BLIND_KEYS, is_unlabeled
from make_stubs import read_jsonl

FAST_SECONDS = 5
SKEW_SHARE = 0.9
SKEW_MIN_ROWS = 10


def host(url):
    h = urlparse(url or "").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def load_json_list(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return data if isinstance(data, list) else None


def check_tasks(stubs, tasks):
    errors, warnings, info = [], [], []
    if not tasks:
        return ["the task file is empty or not a JSON list"], warnings, info
    by_id = {s["id"]: s for s in stubs}
    ids = []
    for t in tasks:
        data = t.get("data") if isinstance(t, dict) else None
        if not isinstance(data, dict):
            errors.append("a task has no data object")
            continue
        if set(data) != BLIND_KEYS:
            errors.append(f"{data.get('id', '?')}: task fields are {sorted(data)}; expected exactly {sorted(BLIND_KEYS)}")
        ids.append(data.get("id"))
    for rid, n in Counter(ids).items():
        if n > 1:
            errors.append(f"{rid} appears {n} times in the task file")
    for rid in ids:
        if rid not in by_id:
            errors.append(f"{rid} is not in the stub file")
    wanted = {s["id"] for s in stubs if is_unlabeled(s)}
    for rid in sorted(wanted - set(ids)):
        errors.append(f"{rid} is unlabeled in the stub file but missing from the task file (stale task file?)")
    for rid in sorted(set(ids) & (set(by_id) - wanted)):
        warnings.append(f"{rid} already has labels but is in the task file (stale task file?)")
    for t in tasks:
        data = t.get("data", {})
        stub = by_id.get(data.get("id"))
        if not stub:
            continue
        text = " ".join(str(data.get(k, "")) for k in ("title", "lede", "standfirst")).lower()
        domain, url = host(stub["url"]), stub["url"].lower()
        if domain and domain in text or url in text:
            errors.append(f"{stub['id']}: the URL or domain ({domain}) appears in the text, which reveals the outlet")
        outlet = stub.get("outlet", "")
        if outlet and outlet != domain and re.search(rf"\b{re.escape(outlet)}\b", text, re.I):
            warnings.append(f"{stub['id']}: the outlet name '{outlet}' appears in the text; decide whether that breaks blinding")
        if bool(stub.get("pilot")) != (data.get("standfirst") not in ("(not used in this batch)", None)):
            errors.append(f"{stub['id']}: the standfirst is shown for a non-pilot row or hidden for a pilot row")
    task_order = [i for i in ids if i in wanted]
    file_order = [s["id"] for s in stubs if s["id"] in wanted]
    if len(task_order) >= 5 and task_order == file_order:
        warnings.append("task order is identical to the stub file order, so the tasks were not shuffled")
    info.append(f"{len(tasks)} tasks for {len(wanted)} unlabeled stubs; {sum(bool(s.get('pilot')) for s in stubs if s['id'] in set(ids))} pilot")
    return errors, warnings, info


def user_of(annotation):
    who = annotation.get("completed_by")
    return (who.get("id") or who.get("email")) if isinstance(who, dict) else who


def check_export(stubs, tasks):
    errors, warnings, info = [], [], []
    if tasks is None:
        return ["the export is not a JSON list; export in the full JSON format"], warnings, info
    if tasks and all("annotations" not in t for t in tasks):
        return ["no task has an 'annotations' list. This looks like JSON-MIN or CSV; export again as plain JSON"], warnings, info
    by_id = {s["id"]: s for s in stubs}
    users, lead_times, labels, pilot_answers = set(), [], {"political": Counter(), "gender": Counter()}, Counter()
    unannotated, cancelled, ready, incomplete, unknown, no_spans, labeled_already = [], 0, 0, {}, [], 0, []
    for t in tasks:
        rid = t.get("data", {}).get("id")
        cancelled += sum(bool(a.get("was_cancelled")) for a in t.get("annotations", []))
        ann = latest_annotation(t)
        if rid not in by_id:
            unknown.append(rid)
            continue
        if ann is None:
            unannotated.append(rid)
            continue
        if not is_unlabeled(by_id[rid]):
            labeled_already.append(rid)
        users.add(user_of(ann))
        if isinstance(ann.get("lead_time"), (int, float)):
            lead_times.append((ann["lead_time"], rid))
        _, problems = apply_annotation(by_id[rid], ann)
        if problems:
            incomplete[rid] = problems
            continue
        ready += 1
        choices, _, spans = parse_results(ann)
        labels["political"][choices["political"]] += 1
        labels["gender"][choices["gender"]] += 1
        no_spans += not spans
        if by_id[rid].get("pilot"):
            pilot_answers[choices.get("standfirst_sufficient")] += 1
    for rid in unknown:
        errors.append(f"{rid} is not in this stub file; is this another annotator's export?")
    for rid, problems in incomplete.items():
        errors.append(f"{rid} is incomplete: {'; '.join(problems)}")
    if len(users) > 1:
        warnings.append(f"annotations come from {len(users)} different users ({sorted(map(str, users))}); one export should hold one annotator")
    if unannotated:
        warnings.append(f"{len(unannotated)} task(s) have no annotation yet: {', '.join(map(str, unannotated))}")
    if labeled_already:
        warnings.append(f"{len(labeled_already)} row(s) already have labels and will be skipped unless you pass --overwrite: {', '.join(labeled_already)}")
    fast = sorted((s, r) for s, r in lead_times if s < FAST_SECONDS)
    if fast:
        warnings.append(f"{len(fast)} task(s) were labeled in under {FAST_SECONDS} seconds: {', '.join(r for _, r in fast)}")
    for axis, counts in labels.items():
        total = sum(counts.values())
        if total >= SKEW_MIN_ROWS and counts.most_common(1)[0][1] / total >= SKEW_SHARE:
            warnings.append(f"{axis}: {counts.most_common(1)[0][0]} is {counts.most_common(1)[0][1]} of {total} labels; check this is real and not a habit")
    if cancelled:
        info.append(f"{cancelled} skipped or cancelled annotation(s) were ignored")
    if lead_times:
        info.append(f"median time per task: {statistics.median(s for s, _ in lead_times):.0f} seconds")
    info.append(f"{ready} of {len(tasks)} tasks are complete and ready to import; {no_spans} have no highlighted words")
    for axis, counts in labels.items():
        info.append(f"{axis}: {dict(counts)}")
    if pilot_answers:
        info.append(f"pilot standfirst_sufficient answers: {dict(pilot_answers)}")
    return errors, warnings, info


def report(errors, warnings, info):
    for e in errors:
        print(f"ERROR: {e}")
    for w in warnings:
        print(f"warning: {w}")
    for i in info:
        print(f"info: {i}")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    t = sub.add_parser("tasks")
    t.add_argument("--stubs", required=True)
    t.add_argument("--tasks", required=True)
    e = sub.add_parser("export")
    e.add_argument("--stubs", required=True)
    e.add_argument("--export", required=True)
    args = ap.parse_args(argv)
    stubs = read_jsonl(args.stubs)
    if args.mode == "tasks":
        result = check_tasks(stubs, load_json_list(args.tasks))
    else:
        result = check_export(stubs, load_json_list(args.export))
    sys.exit(report(*result))


if __name__ == "__main__":
    main()
