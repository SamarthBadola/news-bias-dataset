import json

import inspect_raw as ir


def write(tmp_path, rows):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "2026-10-10.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return str(raw)


def r(i, domain, status, **kw):
    base = {"url": f"https://{domain}/{i}", "canonical_url": f"https://{domain}/{i}", "domain": domain,
            "title": f"Title {i}", "lede": "Lede text " * 5 if status == "ok" else "", "lede_words": 10,
            "lede_status": status, "fetch_error": "", "fetch_detail": ""}
    base.update(kw)
    return base


def test_summary_counts_statuses_per_domain(tmp_path, capsys):
    raw = write(tmp_path, [r(1, "a.com", "ok"), r(2, "a.com", "too_short"), r(3, "b.com", "ok")])
    ir.main(["--raw-dir", raw])
    out = capsys.readouterr().out
    assert "3 rows" in out and "a.com" in out and "'too_short': 1" in out


def test_default_view_lists_only_rows_that_are_not_ok(tmp_path):
    raw = write(tmp_path, [r(1, "a.com", "ok"), r(2, "a.com", "too_short"), r(3, "b.com", "fetch_failed", fetch_error="network_error",
                                                                          fetch_detail="ConnectionResetError: reset")])
    shown = ir.main(["--raw-dir", raw])
    assert {x["lede_status"] for x in shown} == {"too_short", "fetch_failed"}


def test_status_filter_and_per_group_limit(tmp_path, capsys):
    raw = write(tmp_path, [r(i, "a.com", "ok") for i in range(5)])
    shown = ir.main(["--raw-dir", raw, "--status", "ok", "--n", "2"])
    assert len(shown) == 2 and "lede:" in capsys.readouterr().out


def test_failure_details_are_shown(tmp_path, capsys):
    raw = write(tmp_path, [r(1, "a.com", "fetch_failed", fetch_error="network_error", fetch_detail="ConnectionResetError: reset")])
    ir.main(["--raw-dir", raw])
    assert "ConnectionResetError: reset" in capsys.readouterr().out
