import pytest

import api_audit as aa
import make_stubs as ms
import outlets as ol
import validate as v

RAW = {"url": "https://www.newslaundry.com/2026/10/20/a-story", "canonical_url": "https://newslaundry.com/2026/10/20/a-story",
       "domain": "newslaundry.com", "feed": "manual", "category": "", "type_hint": "", "title": "A story",
       "lede": "word " * 40, "lede_status": "ok", "retrieved_at": "2026-10-25T00:00:00Z",
       "published_utc": "2026-10-20T00:00:00Z", "agency_hint": [], "lede_hash": "h1", "standfirst": ""}


@pytest.fixture
def restore_outlets():
    yield
    aa.reload_targets()


def write(tmp_path, text):
    p = tmp_path / "outlets.txt"
    p.write_text(text, encoding="utf-8")
    return p


# ---------- reading the file
def test_load_reads_names_and_hosts_in_order_and_ignores_comments(tmp_path):
    p = write(tmp_path, "\ufeff# header\n\nNDTV | ndtv.com\n  The Hindu  |  thehindu.com  \n# trailing\n")
    assert list(ol.load(p).items()) == [("NDTV", "ndtv.com"), ("The Hindu", "thehindu.com")]


def test_hosts_are_cleaned_when_loaded(tmp_path):
    assert ol.load(write(tmp_path, "Example | https://WWW.Example.com/some/path?x=1\n")) == {"Example": "example.com"}


@pytest.mark.parametrize("text,fragment", [
    ("NDTV ndtv.com\n", "expected 'Name | host'"),
    (" | ndtv.com\n", "expected 'Name | host'"),
    ("NDTV |\n", "expected 'Name | host'"),
    ("NDTV | not a host\n", "not a usable host"),
    ("NDTV | localhost\n", "not a usable host"),
    ("A | a.com\nA | b.com\n", "'A' is listed twice"),
    ("A | a.com\nB | www.a.com\n", "a.com is already listed as 'A'"),
    ("# only comments\n\n", "lists no outlets"),
])
def test_bad_files_fail_with_a_line_number_or_reason(tmp_path, text, fragment):
    with pytest.raises(ol.OutletsError) as exc:
        ol.load(write(tmp_path, text))
    assert fragment in str(exc.value)


@pytest.mark.parametrize("given,host", [
    ("https://www.Newslaundry.com:443/a?x=1#top", "newslaundry.com"), ("www.thewire.in", "thewire.in"),
    ("  Scroll.IN ", "scroll.in"), ("frontline.thehindu.com/x", "frontline.thehindu.com")])
def test_normalize_host_accepts_urls_and_plain_hosts(given, host):
    assert ol.normalize_host(given) == host


# ---------- adding an outlet
def test_add_appends_a_clean_line_and_keeps_everything_else(tmp_path):
    p = write(tmp_path, "# keep me\nNDTV | ndtv.com")                      # note: no trailing newline
    assert ol.add("Newslaundry", "https://www.newslaundry.com/article/1", p) == "newslaundry.com"
    assert p.read_text(encoding="utf-8") == "# keep me\nNDTV | ndtv.com\nNewslaundry | newslaundry.com\n"


def test_add_refuses_duplicates_and_bad_names(tmp_path):
    p = write(tmp_path, "NDTV | ndtv.com\n")
    for name, host, fragment in [("NDTV", "other.com", "already listed"), ("Other", "https://www.ndtv.com/x", "already listed as 'NDTV'"),
                                 ("A|B", "ab.com", "must not contain"), ("", "ab.com", "non-empty"), ("Bad", "nope", "not a usable host")]:
        with pytest.raises(ol.OutletsError) as exc:
            ol.add(name, host, p)
        assert fragment in str(exc.value)
    assert p.read_text(encoding="utf-8") == "NDTV | ndtv.com\n"            # nothing written on failure


def test_command_line_list_and_add(tmp_path, capsys):
    p = write(tmp_path, "NDTV | ndtv.com\n")
    assert ol.main(["--file", str(p), "list"]) == 0 and "ndtv.com" in capsys.readouterr().out
    assert ol.main(["--file", str(p), "add", "Newslaundry", "https://newslaundry.com/x"]) == 0
    assert "Commit outlets.txt" in capsys.readouterr().out
    assert ol.main(["--file", str(p), "add", "Newslaundry", "https://newslaundry.com/y"]) == 1
    assert "already listed" in capsys.readouterr().out


# ---------- the shipped list
def test_the_shipped_list_loads_and_is_what_the_scripts_use():
    shipped = ol.load()
    assert shipped == aa.TARGETS and len(shipped) >= 20
    assert all(h == h.lower() and not h.startswith("www.") for h in shipped.values())
    assert {"NDTV", "The Hindu", "Frontline"} <= set(shipped)


# ---------- the list actually drives the pipeline
def test_reloading_changes_what_counts_as_an_outlet(tmp_path, restore_outlets):
    row = {"url": "https://newslaundry.com/a", "domain": "newslaundry.com", "title": "T", "snippet": "S"}
    assert aa.reject_reason(row, need_snippet=False) == "off_target"
    aa.reload_targets(write(tmp_path, "Newslaundry | newslaundry.com\n"))
    assert aa.reject_reason(row, need_snippet=False) == ""
    assert not aa.is_target("ndtv.com")


def test_an_outlet_added_to_the_file_flows_through_stubbing_and_validation(tmp_path, capsys, restore_outlets):
    before = ms.pick([RAW], [RAW["url"]], set())
    assert before == [] and "outlets.py add" in capsys.readouterr().out
    stub_before = ms.make_stub(RAW, "art-0099", "A1", False, False)
    assert any("exact target domain" in p and "outlets.py add" in p for p in v.check_row(1, stub_before))

    path = write(tmp_path, "\n".join(f"{n} | {d}" for n, d in aa.TARGETS.items()) + "\n")
    ol.add("Newslaundry", "https://www.newslaundry.com/article", path)
    aa.reload_targets(path)

    assert [r["domain"] for r in ms.pick([RAW], [RAW["url"]], set())] == ["newslaundry.com"]
    stub = ms.make_stub(RAW, "art-0099", "A1", False, False)
    assert stub["outlet"] == "Newslaundry"
    assert not any("target domain" in p for p in v.check_row(1, stub))
