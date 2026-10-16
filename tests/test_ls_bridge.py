import json

import pytest

import ls_import as li
import ls_tasks as lt
import make_stubs as ms
import validate as v
from test_make_stubs import fill, raw_row, write_raw


def stub(i=1, **kw):
    s = ms.make_stub(raw_row(i), f"art-{i:04d}", kw.pop("annotator", "A1"), kw.pop("pilot", False), False)
    s.update(kw)
    return s


def res(from_name, kind, **value):
    return {"from_name": from_name, "to_name": "lede", "type": kind, "value": value}


def full_result(political="Left", gender="Neutral", article_type="news", spans=(), standfirst=None):
    out = [res("article_type", "choices", choices=[article_type]),
           res("political", "choices", choices=[political]), res("political_confidence", "choices", choices=["medium"]),
           res("political_rationale", "textarea", text=["Headline frames it as opportunism."]),
           res("gender", "choices", choices=[gender]), res("gender_confidence", "choices", choices=["high"]),
           res("gender_rationale", "textarea", text=["No gendered judgment."])]
    for field, start, text, label in spans:
        out.append(res(f"{field}_spans", "labels", start=start, end=start + len(text), text=text, labels=[label]))
    if standfirst:
        out.append(res("standfirst_sufficient", "choices", choices=[standfirst]))
    return out


def task(rid, result=None, cancelled=False, extra=()):
    ann = [{"id": 1, "was_cancelled": cancelled, "result": result if result is not None else full_result()}, *extra]
    return {"id": 1, "data": {"id": rid}, "annotations": ann}


# ---------- ls_tasks
def test_tasks_contain_only_blinded_fields():
    tasks = lt.build_tasks([stub(1), stub(2)], "A1")
    for t in tasks:
        assert set(t["data"]) == {"id", "title", "lede", "standfirst"}
    blob = json.dumps(tasks).lower()
    assert "thehindu" not in blob and "https://" not in blob and "feed" not in blob


def test_labeled_rows_are_left_out_unless_all_is_requested():
    done = fill(stub(1))
    rows = [done, stub(2)]
    assert [t["data"]["id"] for t in lt.build_tasks(rows, "A1")] == ["art-0002"]
    assert len(lt.build_tasks(rows, "A1", include_all=True)) == 2


def test_order_is_deterministic_per_annotator_and_differs_between_them():
    rows = [stub(i) for i in range(1, 21)]
    a = [t["data"]["id"] for t in lt.build_tasks(rows, "A1")]
    assert a == [t["data"]["id"] for t in lt.build_tasks(rows, "A1")]
    assert a != [t["data"]["id"] for t in lt.build_tasks(rows, "A2")]


def test_standfirst_is_shown_only_for_pilot_rows():
    plain = lt.to_task(stub(1))["data"]["standfirst"]
    pilot = lt.to_task(stub(2, pilot=True))["data"]["standfirst"]
    assert plain == lt.NOT_USED and pilot == "A standfirst."


def test_tasks_cli_writes_json_and_reports_skips(tmp_path, capsys):
    path = tmp_path / "art_A1.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in [fill(stub(1)), stub(2)]) + "\n", encoding="utf-8")
    out = tmp_path / "out" / "tasks.json"
    lt.main(["--stubs", str(path), "--out", str(out)])
    assert [t["data"]["id"] for t in json.loads(out.read_text(encoding="utf-8"))] == ["art-0002"]
    assert "1 rows skipped" in capsys.readouterr().out


# ---------- ls_import
def test_complete_annotation_fills_labels_type_and_confidence():
    new, problems = li.apply_annotation(stub(1), task("art-0001", full_result(article_type="opinion"))["annotations"][0])
    assert problems == [] and new["article_type"] == "opinion"
    assert new["labels"]["political"] == {"label": "Left", "confidence": "medium",
                                          "rationale": "Headline frames it as opportunism.", "spans": []}
    assert new["labels"]["gender"]["label"] == "Neutral"


def test_span_offsets_are_recomputed_from_the_highlighted_text():
    s = stub(1)
    phrase = s["title"].split()[0]
    ann = task("art-0001", full_result(spans=[("title", 999, phrase, "political_evidence")]))["annotations"][0]
    new, problems = li.apply_annotation(s, ann)
    span = new["labels"]["political"]["spans"][0]
    assert problems == [] and (span["start"], span["end"]) == (0, len(phrase)) and s["title"][span["start"]:span["end"]] == phrase


def test_repeated_phrase_uses_the_occurrence_nearest_the_click():
    s = stub(1)
    s["lede"] = "The government said it would act. The government later reversed course on the plan."
    second = s["lede"].index("The government later")
    ann = task("art-0001", full_result(spans=[("lede", second + 1, "The government", "gender_evidence")]))["annotations"][0]
    new, _ = li.apply_annotation(s, ann)
    assert new["labels"]["gender"]["spans"][0]["start"] == second


def test_offsets_count_characters_even_when_the_browser_counts_utf16_units():
    s = stub(1)
    s["lede"] = "\U0001F525 Crowds gathered outside the court as the verdict was read out loud to the public."
    ann = task("art-0001", full_result(spans=[("lede", 3, "Crowds gathered", "political_evidence")]))["annotations"][0]   # JS offset 3 (emoji = 2 units)
    new, _ = li.apply_annotation(s, ann)
    span = new["labels"]["political"]["spans"][0]
    assert s["lede"][span["start"]:span["end"]] == "Crowds gathered" and span["start"] == 2


def test_missing_parts_leave_the_row_untouched():
    partial = [r for r in full_result() if r["from_name"] != "gender_rationale"]
    s = stub(1)
    new, problems = li.apply_annotation(s, {"result": partial})
    assert new is s and problems == ["gender rationale is missing"]
    no_type = [r for r in full_result() if r["from_name"] != "article_type"]
    assert li.apply_annotation(s, {"result": no_type})[1] == ["article type is missing"]


def test_unknown_span_label_and_missing_phrase_are_reported():
    s = stub(1)
    bad_label = task("art-0001", full_result(spans=[("title", 0, "Headline", "other")]))["annotations"][0]
    assert "unknown span label 'other'" in li.apply_annotation(s, bad_label)[1][0]
    absent = task("art-0001", full_result(spans=[("title", 0, "not in the title", "political_evidence")]))["annotations"][0]
    assert "not found in title" in li.apply_annotation(s, absent)[1][0]


def test_pilot_rows_need_the_standfirst_answer():
    s = stub(1, pilot=True)
    assert li.apply_annotation(s, {"result": full_result()})[1] == ["pilot row: standfirst_sufficient is missing"]
    new, problems = li.apply_annotation(s, {"result": full_result(standfirst="no")})
    assert problems == [] and new["standfirst_sufficient"] is False


def test_latest_uncancelled_annotation_wins():
    older = {"id": 1, "was_cancelled": False, "result": full_result(political="Right")}
    newer = {"id": 2, "was_cancelled": False, "result": full_result(political="Center")}
    cancelled = {"id": 3, "was_cancelled": True, "result": full_result(political="Left")}
    t = {"data": {"id": "art-0001"}, "annotations": [older, newer, cancelled]}
    rows, report = li.merge([stub(1)], [t])
    assert rows[0]["labels"]["political"]["label"] == "Center" and report["updated"] == ["art-0001"]


def test_merge_reports_unknown_unannotated_and_incomplete_tasks():
    rows = [stub(1), stub(2), stub(3)]
    tasks = [task("art-0001"), task("art-9999"), {"data": {"id": "art-0002"}, "annotations": []},
             task("art-0003", [res("political", "choices", choices=["Left"])])]
    rows, report = li.merge(rows, tasks)
    assert report["updated"] == ["art-0001"] and report["unknown_id"] == ["art-9999"]
    assert report["no_annotation"] == ["art-0002"] and "art-0003" in report["incomplete"]


def test_labeled_rows_are_not_overwritten_unless_asked():
    done = fill(stub(1))
    original = done["labels"]["political"]["label"]
    t = task("art-0001", full_result(political="Right"))
    rows, report = li.merge([done], [t])
    assert report["skipped_labeled"] == ["art-0001"] and rows[0]["labels"]["political"]["label"] == original
    rows, report = li.merge([done], [t], overwrite=True)
    assert rows[0]["labels"]["political"]["label"] == "Right"


def test_comparative_flag_only_touches_placeholders():
    rows, _ = li.merge([stub(1)], [task("art-0001")], comparative="not_applicable")
    assert rows[0]["labels"]["communal_caste"] == {"status": "not_applicable"}
    assert rows[0]["labels"]["cultural"] == {"status": "not_applicable"}
    s = stub(2)
    s["labels"]["cultural"] = {"status": "labeled", "label": "biased", "rationale": "r", "bundle_id": "bun-0001"}
    rows, _ = li.merge([s], [task("art-0002")], comparative="no_bundle")
    assert rows[0]["labels"]["cultural"]["status"] == "labeled" and rows[0]["labels"]["communal_caste"]["status"] == "no_bundle"


def test_import_cli_updates_the_file_atomically_and_keeps_other_rows(tmp_path, capsys):
    path = tmp_path / "art_A1.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in [stub(1), stub(2)]) + "\n", encoding="utf-8")
    export = tmp_path / "export.json"
    export.write_text(json.dumps([task("art-0001")]), encoding="utf-8")
    li.main(["--export", str(export), "--stubs", str(path)])
    rows = [json.loads(line) for line in open(path, encoding="utf-8")]
    assert rows[0]["labels"]["political"]["label"] == "Left" and rows[1]["labels"]["political"]["label"].startswith("<")
    assert not list(tmp_path.glob("*.tmp")) and "updated 1 rows" in capsys.readouterr().out


def test_import_cli_rejects_a_non_list_export(tmp_path):
    export = tmp_path / "export.json"
    export.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    (tmp_path / "s.jsonl").write_text(json.dumps(stub(1)) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        li.main(["--export", str(export), "--stubs", str(tmp_path / "s.jsonl")])


# ---------- the whole pipeline, as the README describes it
def test_pipeline_raw_to_stubs_to_label_studio_to_gold(tmp_path, capsys):
    write_raw(tmp_path, [raw_row(i, domain=d) for i, d in enumerate(["thehindu.com", "ndtv.com", "scroll.in"], 1)])
    annotated, gold = tmp_path / "annotated", tmp_path / "gold"
    stubs = ms.main(["--raw-dir", str(tmp_path / "raw"), "--annotated-dir", str(annotated), "--gold-dir", str(gold),
                     "--annotator", "A1", "--n", "3", "--per-domain-cap", "0"])
    a1 = annotated / "art_A1.jsonl"
    assert [s["id"] for s in stubs] == ["art-0001", "art-0002", "art-0003"]

    tasks_path = tmp_path / "tasks.json"
    lt.main(["--stubs", str(a1), "--out", str(tasks_path)])
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    assert len(tasks) == 3 and "https://" not in tasks_path.read_text(encoding="utf-8")

    export = [task(t["data"]["id"], full_result(spans=[("title", 0, "Headline", "political_evidence")])) for t in tasks]
    export_path = tmp_path / "export.json"
    export_path.write_text(json.dumps(export), encoding="utf-8")
    li.main(["--export", str(export_path), "--stubs", str(a1), "--comparative", "not_applicable"])

    with pytest.raises(SystemExit) as exc:
        v.main([str(a1), "--promote", "--gold-dir", str(gold)])
    out = capsys.readouterr().out
    assert exc.value.code == 0 and "0 problems" in out and "promoted 3" in out
    promoted = [json.loads(line) for line in open(gold / "eval.jsonl", encoding="utf-8")]
    assert [r["id"] for r in promoted] == ["art-0001", "art-0002", "art-0003"]
    assert all(r["labels"]["political"]["spans"][0]["text"] == "Headline" for r in promoted)
