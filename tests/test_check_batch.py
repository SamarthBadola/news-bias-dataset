import json

import pytest

import check_batch as cb
import ls_tasks as lt
from test_ls_bridge import full_result, stub
from test_make_stubs import fill


def tasks_for(rows, shuffled=True):
    out = lt.build_tasks(rows, "A1" if shuffled else "x")
    if not shuffled:
        out = [lt.to_task(r) for r in rows]
    return out


def rows(n=6, **kw):
    return [stub(i, **kw) for i in range(1, n + 1)]


def ann(result=None, lead=30.0, user=1, cancelled=False):
    return {"id": 1, "was_cancelled": cancelled, "completed_by": user, "lead_time": lead,
            "result": result if result is not None else full_result()}


def etask(rid, *anns):
    return {"id": 1, "data": {"id": rid}, "annotations": list(anns)}


def has(messages, fragment):
    return any(fragment in m for m in messages)


# ---------- tasks
def test_a_fresh_task_file_passes():
    errors, warnings, info = cb.check_tasks(rows(), tasks_for(rows()))
    assert errors == [] and warnings == [] and "6 tasks for 6 unlabeled stubs" in info[0]


def test_extra_fields_in_a_task_are_an_error():
    r = rows()
    t = tasks_for(r)
    t[0]["data"]["url"] = "https://example.com"
    assert has(cb.check_tasks(r, t)[0], "expected exactly")


def test_duplicate_and_unknown_ids_are_errors():
    r = rows()
    t = tasks_for(r)
    t.append(json.loads(json.dumps(t[0])))
    t.append({"data": {"id": "art-9999", "title": "x", "lede": "y", "standfirst": "(not used in this batch)"}})
    errors = cb.check_tasks(r, t)[0]
    assert has(errors, "appears 2 times") and has(errors, "art-9999 is not in the stub file")


def test_a_stub_without_a_task_means_the_task_file_is_stale():
    r = rows()
    assert has(cb.check_tasks(r, tasks_for(r)[:-1])[0], "missing from the task file")


def test_labeled_rows_in_the_task_file_are_a_warning():
    r = rows()
    t = tasks_for(r)
    r[0] = fill(r[0])
    assert has(cb.check_tasks(r, t)[1], "already has labels")


def test_url_or_domain_in_the_text_is_an_error():
    r = rows()
    t = tasks_for(r)
    t[0]["data"]["lede"] += " Read more at thehindu.com/story"
    assert has(cb.check_tasks(r, t)[0], "reveals the outlet")


def test_outlet_name_in_the_text_is_a_warning_not_an_error():
    r = rows()
    t = tasks_for(r)
    t[0]["data"]["lede"] += " The Hindu reported the same."
    errors, warnings, _ = cb.check_tasks(r, t)
    assert errors == [] and has(warnings, "outlet name 'The Hindu'")


def test_unshuffled_tasks_are_flagged():
    r = rows()
    assert has(cb.check_tasks(r, tasks_for(r, shuffled=False))[1], "not shuffled")


def test_standfirst_visibility_must_match_pilot_status():
    r = rows(pilot=True)
    t = tasks_for(r)
    t[0]["data"]["standfirst"] = "(not used in this batch)"
    assert has(cb.check_tasks(r, t)[0], "standfirst is shown for a non-pilot row or hidden for a pilot row")
    assert cb.check_tasks(r, tasks_for(r))[0] == []


@pytest.mark.parametrize("bad", [[], None])
def test_empty_or_non_list_task_files_are_errors(bad):
    assert cb.check_tasks(rows(), bad)[0]


# ---------- export
def test_a_complete_export_is_ready_to_import():
    r = rows()
    errors, warnings, info = cb.check_export(r, [etask(x["id"], ann()) for x in r])
    assert errors == [] and warnings == []
    assert has(info, "6 of 6 tasks are complete and ready to import") and has(info, "median time per task: 30 seconds")


def test_json_min_and_non_list_exports_are_rejected():
    r = rows()
    assert has(cb.check_export(r, [{"id": "art-0001", "political": "Left"}])[0], "JSON-MIN")
    assert has(cb.check_export(r, None)[0], "full JSON format")


def test_an_export_from_another_stub_file_is_an_error():
    r = rows(3)
    assert has(cb.check_export(r, [etask("art-0099", ann())])[0], "another annotator's export")


def test_incomplete_annotations_are_errors_with_the_reason():
    r = rows(2)
    partial = [x for x in full_result() if x["from_name"] != "gender_rationale"]
    errors = cb.check_export(r, [etask("art-0001", ann(partial)), etask("art-0002", ann())])[0]
    assert has(errors, "art-0001 is incomplete: gender rationale is missing")


def test_unannotated_tasks_are_listed_as_a_warning():
    r = rows(3)
    warnings = cb.check_export(r, [etask("art-0001", ann()), etask("art-0002"), etask("art-0003", ann(cancelled=True))])[1]
    assert has(warnings, "2 task(s) have no annotation yet: art-0002, art-0003")


def test_annotations_from_two_users_are_flagged_including_dict_users():
    r = rows(2)
    warnings = cb.check_export(r, [etask("art-0001", ann(user=1)), etask("art-0002", ann(user={"id": 2, "email": "x@y.z"}))])[1]
    assert has(warnings, "2 different users")


def test_very_fast_tasks_are_flagged():
    r = rows(3)
    warnings = cb.check_export(r, [etask("art-0001", ann(lead=2.0)), etask("art-0002", ann(lead=40)), etask("art-0003", ann(lead=3.5))])[1]
    assert has(warnings, "2 task(s) were labeled in under 5 seconds: art-0001, art-0003")


def test_a_one_sided_label_mix_is_flagged_only_with_enough_rows():
    r = rows(10)
    export = [etask(x["id"], ann(full_result(political="Left", gender="Neutral"))) for x in r]
    warnings = cb.check_export(r, export)[1]
    assert has(warnings, "political: Left is 10 of 10") and has(warnings, "gender: Neutral is 10 of 10")
    small = rows(4)
    assert not has(cb.check_export(small, [etask(x["id"], ann()) for x in small])[1], "is 4 of 4")


def test_cancelled_annotations_are_ignored_and_counted():
    r = rows(1)
    t = etask("art-0001", ann(full_result(political="Right")), ann(full_result(political="Left"), cancelled=True))
    _, _, info = cb.check_export(r, [t])
    assert has(info, "1 skipped or cancelled") and has(info, "'Right': 1")


def test_rows_that_already_have_labels_are_noted():
    r = rows(2)
    r[0] = fill(r[0])
    warnings = cb.check_export(r, [etask("art-0001", ann()), etask("art-0002", ann())])[1]
    assert has(warnings, "will be skipped unless you pass --overwrite: art-0001")


def test_pilot_answers_are_summarised():
    r = rows(2, pilot=True)
    export = [etask("art-0001", ann(full_result(standfirst="yes"))), etask("art-0002", ann(full_result(standfirst="no")))]
    errors, _, info = cb.check_export(r, export)
    assert errors == [] and has(info, "standfirst_sufficient answers: {'yes': 1, 'no': 1}")


# ---------- command line
def write(tmp_path, rows_, name):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(x) for x in rows_) + "\n", encoding="utf-8")
    return str(p)


def test_cli_exit_codes_for_tasks_and_export(tmp_path, capsys):
    r = rows()
    stubs = write(tmp_path, r, "stubs.jsonl")
    good = tmp_path / "tasks.json"
    good.write_text(json.dumps(tasks_for(r)), encoding="utf-8")
    with pytest.raises(SystemExit) as ok:
        cb.main(["tasks", "--stubs", stubs, "--tasks", str(good)])
    assert ok.value.code == 0 and "0 error(s)" in capsys.readouterr().out
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(tasks_for(r)[:-1]), encoding="utf-8")
    with pytest.raises(SystemExit) as fail:
        cb.main(["tasks", "--stubs", stubs, "--tasks", str(bad)])
    assert fail.value.code == 1
    export = tmp_path / "export.json"
    export.write_text(json.dumps([etask(x["id"], ann()) for x in r]), encoding="utf-8")
    with pytest.raises(SystemExit) as fine:
        cb.main(["export", "--stubs", stubs, "--export", str(export)])
    assert fine.value.code == 0
