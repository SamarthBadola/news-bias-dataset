import json

import pytest

import drop_stubs as ds
import make_stubs as ms
from test_make_stubs import fill, raw_row, write_raw


def stub(i):
    return ms.make_stub(raw_row(i), f"art-{i:04d}", "A1", False, False)


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def read(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def run(tmp_path, *args):
    with pytest.raises(SystemExit) as exc:
        ds.main([*args, "--annotated-dir", str(tmp_path / "annotated"), "--gold-dir", str(tmp_path / "gold")])
    return exc.value.code


def test_removes_the_id_from_every_annotator_file(tmp_path, capsys):
    a1, a2 = tmp_path / "annotated" / "art_A1.jsonl", tmp_path / "annotated" / "art_A2.jsonl"
    write(a1, [stub(1), stub(2), stub(3)])
    write(a2, [stub(2), stub(3)])
    assert run(tmp_path, "art-0002") == 0
    assert [r["id"] for r in read(a1)] == ["art-0001", "art-0003"] and [r["id"] for r in read(a2)] == ["art-0003"]
    assert "removed 1 id(s): art-0002" in capsys.readouterr().out


def test_other_rows_are_left_byte_for_byte_identical_in_content(tmp_path):
    a1 = tmp_path / "annotated" / "art_A1.jsonl"
    rows = [stub(1), stub(2)]
    write(a1, rows)
    run(tmp_path, "art-0002")
    assert read(a1) == [rows[0]]


def test_files_without_the_id_are_not_rewritten(tmp_path, capsys):
    a1, a2 = tmp_path / "annotated" / "art_A1.jsonl", tmp_path / "annotated" / "art_A2.jsonl"
    write(a1, [stub(1), stub(2)])
    write(a2, [stub(3)])
    before = a2.read_bytes()
    run(tmp_path, "art-0002")
    assert a2.read_bytes() == before and "art_A2" not in capsys.readouterr().out


def test_unknown_ids_are_reported_with_a_failing_exit_code(tmp_path, capsys):
    write(tmp_path / "annotated" / "art_A1.jsonl", [stub(1)])
    assert run(tmp_path, "art-0099") == 1
    assert "not found" in capsys.readouterr().out


def test_ids_already_in_gold_are_refused(tmp_path, capsys):
    a1 = tmp_path / "annotated" / "art_A1.jsonl"
    write(a1, [stub(1), stub(2)])
    write(tmp_path / "gold" / "eval.jsonl", [dict(stub(2), annotators=["A1"])])
    assert run(tmp_path, "art-0002") == 1
    assert [r["id"] for r in read(a1)] == ["art-0001", "art-0002"] and "already in gold" in capsys.readouterr().out


def test_labeled_rows_need_force(tmp_path, capsys):
    a1 = tmp_path / "annotated" / "art_A1.jsonl"
    write(a1, [fill(stub(1)), stub(2)])
    assert run(tmp_path, "art-0001") == 1 and len(read(a1)) == 2
    assert "already has labels" in capsys.readouterr().out
    assert run(tmp_path, "art-0001", "--force") == 0 and [r["id"] for r in read(a1)] == ["art-0002"]


def test_output_uses_unix_line_endings(tmp_path):
    a1 = tmp_path / "annotated" / "art_A1.jsonl"
    write(a1, [stub(1), stub(2)])
    run(tmp_path, "art-0002")
    assert b"\r\n" not in a1.read_bytes()


def test_removed_highest_id_is_retired_for_future_allocation(tmp_path):
    a1 = tmp_path / "annotated" / "art_A1.jsonl"
    write(a1, [stub(1), stub(2), stub(3)])
    assert run(tmp_path, "art-0003") == 0
    ledger = tmp_path / "annotated" / "retired_ids.txt"
    assert ledger.read_text(encoding="utf-8").splitlines() == ["art-0003"]

    write_raw(tmp_path, [raw_row(4), raw_row(5)])
    made = ms.main(["--raw-dir", str(tmp_path / "raw"), "--annotated-dir", str(tmp_path / "annotated"),
                    "--gold-dir", str(tmp_path / "gold"), "--annotator", "A1", "--n", "1"])
    assert [row["id"] for row in made] == ["art-0004"]
