import json
from pathlib import Path

import pytest

import validate as v
from test_validate import base_row, write


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """Default paths such as data/gold must never point at the real repository data."""
    monkeypatch.chdir(tmp_path)


def row(rid="art-0001", annotator="A1", **changes):
    r = base_row()
    r.update(id=rid, url=f"https://theprint.in/{rid}", annotator=annotator, **changes)
    return r


def run(tmp_path, files, capsys, *extra):
    gold = tmp_path / "gold"
    with pytest.raises(SystemExit) as exc:
        v.main([*map(str, files), "--promote", "--gold-dir", str(gold), *extra])
    return exc.value.code, capsys.readouterr().out, gold


def gold_rows(gold, split="eval"):
    path = gold / f"{split}.jsonl"
    return [json.loads(line) for line in open(path, encoding="utf-8")] if path.exists() else []


def test_single_annotator_row_is_promoted_to_the_split_named_in_the_entry(tmp_path, capsys):
    a1 = tmp_path / "a1.jsonl"
    write(a1, [row("art-0001"), row("art-0002", pilot=True, split="pilot", standfirst_sufficient=True),
               row("art-0003", split="fewshot")])
    code, out, gold = run(tmp_path, [a1], capsys)
    assert code == 0
    assert [r["id"] for r in gold_rows(gold, "eval")] == ["art-0001"]
    assert [r["id"] for r in gold_rows(gold, "pilot")] == ["art-0002"]
    assert [r["id"] for r in gold_rows(gold, "fewshot")] == ["art-0003"]
    g = gold_rows(gold)[0]
    assert g["annotators"] == ["A1"] and g["agreement"] == "single" and "annotator" not in g
    assert g["annotations"]["A1"] == g["labels"] and g["promoted_at"].endswith("Z")


def test_check_only_mode_never_writes_gold(tmp_path, capsys):
    a1 = tmp_path / "a1.jsonl"
    write(a1, [row()])
    with pytest.raises(SystemExit) as exc:
        v.main([str(a1), "--gold-dir", str(tmp_path / "gold")])
    assert exc.value.code == 0 and not (tmp_path / "gold").exists()


def test_validation_problems_block_all_promotion(tmp_path, capsys):
    a1 = tmp_path / "a1.jsonl"
    bad = row("art-0002")
    bad["labels"]["political"]["label"] = "<Left|Right|Center>"
    write(a1, [row("art-0001"), bad])
    code, out, gold = run(tmp_path, [a1], capsys)
    assert code == 1 and "nothing promoted" in out and not gold.exists()


def test_overlap_row_waits_when_only_one_annotator_file_is_given(tmp_path, capsys):
    a1 = tmp_path / "a1.jsonl"
    write(a1, [row("art-0001", overlap_set=True), row("art-0002")])
    code, out, gold = run(tmp_path, [a1], capsys)
    assert code == 0 and "waiting for the second annotator" in out
    assert [r["id"] for r in gold_rows(gold)] == ["art-0002"]


def test_agreeing_overlap_row_is_promoted_once_with_both_annotations(tmp_path, capsys):
    a1, a2 = tmp_path / "a1.jsonl", tmp_path / "a2.jsonl"
    write(a1, [row(overlap_set=True)])
    second = row(annotator="A2", overlap_set=True)
    second["labels"]["political"]["rationale"] = "Different wording, same label."
    write(a2, [second])
    code, out, gold = run(tmp_path, [a1, a2], capsys)
    g = gold_rows(gold)
    assert code == 0 and len(g) == 1 and g[0]["agreement"] == "full" and g[0]["annotators"] == ["A1", "A2"]
    assert set(g[0]["annotations"]) == {"A1", "A2"}


def test_disagreement_is_held_back_until_adjudicated(tmp_path, capsys):
    a1, a2 = tmp_path / "a1.jsonl", tmp_path / "a2.jsonl"
    write(a1, [row(overlap_set=True)])
    other = row(annotator="A2", overlap_set=True)
    other["labels"]["political"]["label"] = "Center"
    write(a2, [other])
    code, out, gold = run(tmp_path, [a1, a2], capsys)
    assert code == 0 and "annotators disagree on political" in out and not gold_rows(gold)
    other["adjudicated"] = "Agreed Center after discussing the headline wording."
    write(a2, [other])
    code, out, gold = run(tmp_path, [a1, a2], capsys)
    g = gold_rows(gold)[0]
    assert code == 0 and g["agreement"] == "adjudicated" and g["labels"]["political"]["label"] == "Center"
    assert g["adjudication_note"].startswith("Agreed Center") and "adjudicated" not in g
    assert g["annotations"]["A1"]["political"]["label"] == "Left"        # both originals are kept


def test_comparative_axis_disagreement_counts(tmp_path, capsys):
    a1, a2 = tmp_path / "a1.jsonl", tmp_path / "a2.jsonl"
    one = row(overlap_set=True)
    one["labels"]["cultural"] = {"status": "labeled", "label": "biased", "rationale": "r", "bundle_id": "bun-0001"}
    two = row(annotator="A2", overlap_set=True)
    two["labels"]["cultural"] = {"status": "labeled", "label": "symmetric", "rationale": "r", "bundle_id": "bun-0001"}
    write(a1, [one])
    write(a2, [two])
    _, out, gold = run(tmp_path, [a1, a2], capsys)
    assert "disagree on cultural" in out and not gold_rows(gold)


def test_promoting_twice_is_idempotent(tmp_path, capsys):
    a1 = tmp_path / "a1.jsonl"
    write(a1, [row()])
    run(tmp_path, [a1], capsys)
    code, out, gold = run(tmp_path, [a1], capsys)
    assert code == 0 and "already in gold" in out and len(gold_rows(gold)) == 1


def test_changed_content_for_an_id_already_in_gold_is_an_error(tmp_path, capsys):
    a1 = tmp_path / "a1.jsonl"
    write(a1, [row()])
    run(tmp_path, [a1], capsys)
    changed = row()
    changed["labels"]["political"]["label"] = "Right"
    write(a1, [changed])
    code, out, gold = run(tmp_path, [a1], capsys)
    assert code == 1 and "already in gold with different content" in out and len(gold_rows(gold)) == 1


def test_two_annotators_on_a_non_overlap_row_is_an_error(tmp_path, capsys):
    a1, a2 = tmp_path / "a1.jsonl", tmp_path / "a2.jsonl"
    write(a1, [row()])
    write(a2, [row(annotator="A2")])
    code, out, gold = run(tmp_path, [a1, a2], capsys)
    assert code == 1 and "overlap_set is false" in out and not gold.exists()


def test_errors_prevent_any_gold_write_even_for_good_rows(tmp_path, capsys):
    a1, a2 = tmp_path / "a1.jsonl", tmp_path / "a2.jsonl"
    write(a1, [row("art-0001"), row("art-0002")])
    write(a2, [row("art-0002", annotator="A2")])
    code, out, gold = run(tmp_path, [a1, a2], capsys)
    assert code == 1 and not gold_rows(gold)


def test_gold_files_are_append_only(tmp_path, capsys):
    a1 = tmp_path / "a1.jsonl"
    write(a1, [row("art-0001")])
    run(tmp_path, [a1], capsys)
    write(a1, [row("art-0001"), row("art-0002")])
    _, _, gold = run(tmp_path, [a1], capsys)
    assert [r["id"] for r in gold_rows(gold)] == ["art-0001", "art-0002"]
    assert Path(gold / "eval.jsonl").read_text(encoding="utf-8").count("\n") == 2
