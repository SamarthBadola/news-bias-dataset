import json
from pathlib import Path

import pytest

import validate as v

LEDE = ("Narendra Modi is not letting his failed bid to overhaul parliament go to waste as he turns the "
        "defeat into a campaign pitch in a state that votes on Thursday.")


TITLE = "Modi now using women card"
START = TITLE.index("women card")


def base_row():
    return {
        "id": "art-0001", "url": "https://theprint.in/x", "url_archive": "https://web.archive.org/x",
        "retrieved_at": "2026-10-10T09:30:00Z", "published": "2026-04-20", "outlet": "ThePrint",
        "original_source": "Bloomberg", "syndicated": True, "article_type": "wire", "event_id": "ev-1",
        "title": TITLE, "standfirst": "", "lede": LEDE, "lede_status": "ok",
        "guideline_version": "1.1", "in_guideline": False, "pilot": False,
        "labels": {
            "political": {"label": "Left", "confidence": "medium", "rationale": "Headline frames it as opportunism.",
                          "spans": [{"field": "title", "start": START, "end": START + 10, "text": "women card"}]},
            "gender": {"label": "Neutral", "confidence": "high", "rationale": "No gendered judgment."},
            "communal_caste": {"status": "not_applicable"}, "cultural": {"status": "not_applicable"}},
        "annotator": "A1", "split": "eval"}


def errors(row):
    return v.check_row(1, row)


def test_baseline_row_is_valid():
    assert errors(base_row()) == []


def mutate(path, value):
    row = base_row()
    target = row
    for key in path[:-1]:
        target = target[key]
    if value is None:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return row


@pytest.mark.parametrize("path,value,fragment", [
    (["lede_status"], "too_short", "lede_status must be 'ok'"),
    (["lede_status"], "live_blog", "lede_status must be 'ok'"),
    (["lede"], "word " * 130, "expected 25 to 120"),
    (["lede"], "too short", "expected 25 to 120"),
    (["lede"], None, "missing field 'lede'"),
    (["lede"], 12345, "lede must be text"),
    (["lede"], "<PASTE the lede>", "placeholder"),
    (["standfirst"], "word " * 41, "standfirst is longer"),
    (["id"], "pol-0007", "id must look like art-0001"),
    (["published"], "20/04/2026", "published must be YYYY-MM-DD"),
    (["retrieved_at"], "yesterday", "UTC timestamp"),
    (["article_type"], "editorial", "article_type must be one of"),
    (["split"], "train", "split must be one of"),
    (["original_source"], "", "needs original_source"),
    (["pilot"], True, "standfirst_sufficient"),
    (["labels", "political", "label"], "Centre", "label must be one of"),
    (["labels", "political", "rationale"], "", "no rationale"),
    (["labels", "political", "rationale"], "<one line>", "labels.political.rationale' is still a placeholder"),
    (["labels", "gender", "confidence"], "<low|medium|high>", "labels.gender.confidence' is still a placeholder"),
    (["labels", "cultural"], {"status": "<labeled|no_bundle|not_applicable>"}, "labels.cultural.status' is still a placeholder"),
    (["event_id"], "<short event slug>", "event_id' is still a placeholder"),
    (["labels", "political", "confidence"], "sure", "confidence must be one of"),
    (["labels", "political", "spans"], [{"field": "title", "start": 0, "end": 5, "text": "women"}], "span offsets"),
    (["labels", "political", "spans"], [{"field": "body", "start": 0, "end": 5, "text": "x"}], "span field"),
    (["labels", "gender", "label"], "Neutral ", "label must be one of"),
    (["labels", "communal_caste"], {"status": "labeled", "label": "maybe", "rationale": "r", "bundle_id": "bun-0001"}, "label must be one of"),
    (["labels", "cultural"], {"status": "labeled", "label": "biased", "rationale": "r"}, "bundle_id"),
    (["labels", "cultural"], {"status": "skipped"}, "status must be one of"),
])
def test_invalid_rows_are_rejected(path, value, fragment):
    assert any(fragment in e for e in errors(mutate(path, value))), errors(mutate(path, value))


def test_guideline_and_pilot_items_cannot_sit_in_eval():
    row = base_row()
    row["in_guideline"] = True
    assert any("must not be in the eval split" in e for e in errors(row))
    row = base_row()
    row.update(pilot=True, split="eval", standfirst_sufficient=True)
    assert any("must not be in the eval split" in e for e in errors(row))


def test_pilot_item_with_standfirst_flag_is_valid():
    row = base_row()
    row.update(pilot=True, split="pilot", standfirst_sufficient=False)
    assert errors(row) == []


def test_comparative_axis_labeled_is_valid():
    row = base_row()
    row["labels"]["communal_caste"] = {"status": "labeled", "label": "biased", "rationale": "r", "bundle_id": "bun-0001"}
    assert errors(row) == []


def write(path, rows, bom=False):
    text = "\n".join(json.dumps(r) for r in rows) + "\n"
    Path(path).write_text(("\ufeff" if bom else "") + text, encoding="utf-8")


def test_load_reports_invalid_json_line_and_duplicates(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text(json.dumps(base_row()) + "\n{not json}\n" + json.dumps(base_row()) + "\n", encoding="utf-8")
    _, problems = v.load(str(p))
    joined = "\n".join(problems)
    assert "not valid JSON" in joined and "duplicate id" in joined and "duplicate url" in joined


def test_load_tolerates_a_utf8_bom(tmp_path):
    p = tmp_path / "a.jsonl"
    write(p, [base_row()], bom=True)
    rows, problems = v.load(str(p))
    assert problems == [] and len(rows) == 1


def run_main(paths, capsys):
    with pytest.raises(SystemExit) as exc:
        v.main([str(p) for p in paths])
    return exc.value.code, capsys.readouterr().out


def test_annotators_must_label_identical_input(tmp_path, capsys):
    a1, a2 = tmp_path / "a1.jsonl", tmp_path / "a2.jsonl"
    write(a1, [base_row()])
    other = base_row()
    other.update(annotator="A2", lede=LEDE + " An extra sentence added after fetching.")
    write(a2, [other])
    code, out = run_main([a1, a2], capsys)
    assert code == 1 and "'lede' differs" in out


def test_matching_annotator_files_pass(tmp_path, capsys):
    a1, a2 = tmp_path / "a1.jsonl", tmp_path / "a2.jsonl"
    write(a1, [base_row()])
    second = base_row()
    second["annotator"] = "A2"
    write(a2, [second])
    code, out = run_main([a1, a2], capsys)
    assert code == 0 and "0 problems" in out


def test_docs_example_has_every_required_field_and_only_the_lede_is_a_placeholder():
    path = Path(__file__).resolve().parent.parent / "docs" / "example-entry.json"
    row = json.loads(path.read_text(encoding="utf-8"))
    assert not [k for k in v.REQUIRED if k not in row and k != "annotator"]
    assert set(v.find_placeholders(row)) == {"lede"}
