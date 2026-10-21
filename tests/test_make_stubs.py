import json

import pytest

import make_stubs as ms
import validate as v

LEDE = ("Narendra Modi is not letting his failed bid to overhaul parliament go to waste as he turns the "
        "defeat into a campaign pitch in a state that votes on Thursday.")


def raw_row(i, domain="thehindu.com", status="ok", type_hint="", lede=None, lede_hash=None):
    return {"url": f"https://www.{domain}/story-{i}?utm_source=x", "canonical_url": f"https://{domain}/story-{i}",
            "domain": domain, "feed": "Feed", "category": "Lead", "type_hint": type_hint,
            "published_utc": "2026-10-10T10:17:25Z", "retrieved_at": "2026-10-10T11:00:00Z",
            "title": f"Headline {i}", "standfirst": "A standfirst.", "lede": LEDE + f" Variant {i}." if lede is None else lede,
            "lede_words": 30, "lede_status": status, "http_status": 200, "fetch_error": "",
            "agency_hint": ["Bloomberg"] if i == 0 else [], "lede_hash": lede_hash or f"hash{i}"}


def write_raw(tmp_path, rows):
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    (raw / "2026-10-10.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return raw


def cli(tmp_path, *extra):
    return ms.main(["--raw-dir", str(tmp_path / "raw"), "--annotated-dir", str(tmp_path / "annotated"),
                    "--gold-dir", str(tmp_path / "gold"), *extra])


def read(path):
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def fill(stub, annotator=None):
    """What a human does: replace every placeholder with a real value."""
    s = json.loads(json.dumps(stub))
    s.update(url_archive="https://web.archive.org/x", original_source="", syndicated=False, event_id="ev-1")
    if s["article_type"].startswith("<"):
        s["article_type"] = "news"
    if "standfirst_sufficient" in s:
        s["standfirst_sufficient"] = True
    title = s["title"]
    s["labels"]["political"].update(label="Left", confidence="medium", rationale="Headline frames it as opportunism.",
                                    spans=[{"field": "title", "start": 0, "end": 8, "text": title[:8]}])
    s["labels"]["gender"].update(label="Neutral", confidence="high", rationale="No gendered judgment.", spans=[])
    s["labels"]["communal_caste"] = {"status": "not_applicable"}
    s["labels"]["cultural"] = {"status": "not_applicable"}
    if annotator:
        s["annotator"] = annotator
    return s


def test_stub_is_complete_but_rejected_until_placeholders_are_replaced():
    stub = ms.make_stub(raw_row(1), "art-0001", "A1", pilot=False, overlap=False)
    assert v.check_row(1, stub)                       # unfinished stubs never pass validation
    paths = set(v.find_placeholders(stub))
    assert paths == {"article_type", "labels.political.label", "labels.political.confidence",
                     "labels.political.rationale", "labels.gender.label", "labels.gender.confidence",
                     "labels.gender.rationale", "labels.communal_caste.status", "labels.cultural.status"}
    assert v.check_row(1, fill(stub)) == []


def test_syndication_is_prefilled_unless_an_agency_name_needs_confirming():
    plain = ms.make_stub(raw_row(1), "art-0001", "A1", False, False)
    assert plain["syndicated"] is False and plain["original_source"] == ""
    wire = ms.make_stub(raw_row(0), "art-0002", "A1", False, False)      # raw_row(0) mentions Bloomberg
    assert wire["syndicated"] == "<true|false>" and "Bloomberg" in wire["original_source"]
    assert {"syndicated", "original_source"} <= set(v.find_placeholders(wire))


def test_url_archive_and_event_id_start_empty_not_as_placeholders():
    stub = ms.make_stub(raw_row(1), "art-0001", "A1", False, False)
    assert stub["url_archive"] == "" and stub["event_id"] == ""


def test_machine_fields_are_prefilled_from_raw():
    stub = ms.make_stub(raw_row(1), "art-0001", "A1", False, False)
    assert stub["outlet"] == "The Hindu" and stub["published"] == "2026-10-10"
    assert stub["lede_status"] == "ok" and stub["split"] == "eval" and stub["guideline_version"] == ms.GUIDELINE_VERSION
    assert stub["meta"]["lede_hash"] == "hash1" and stub["meta"]["canonical_url"] == "https://thehindu.com/story-1"


def test_unknown_domain_falls_back_to_the_domain_name():
    assert ms.make_stub(raw_row(1, domain="newsite.example"), "art-0001", "A1", False, False)["outlet"] == "newsite.example"


def test_opinion_hint_prefills_article_type_only_when_present():
    assert ms.make_stub(raw_row(1, type_hint="opinion"), "art-0001", "A1", False, False)["article_type"] == "opinion"
    assert ms.make_stub(raw_row(1), "art-0001", "A1", False, False)["article_type"].startswith("<")


def test_pilot_stub_requires_standfirst_flag_and_uses_pilot_split():
    stub = ms.make_stub(raw_row(1), "art-0001", "A1", pilot=True, overlap=False)
    assert stub["split"] == "pilot" and stub["standfirst_sufficient"].startswith("<")
    assert v.check_row(1, fill(stub)) == []


def test_select_only_takes_fetched_unique_unseen_rows(tmp_path):
    rows = [raw_row(1), raw_row(2, status="too_short"), raw_row(3, status="live_blog"),
            raw_row(4, lede_hash="same"), raw_row(5, lede_hash="same"), raw_row(6), raw_row(7)]
    taken = {"https://thehindu.com/story-6"}
    chosen = ms.select(rows, 10, 0, 0, set(), None, taken, {"hash7"})
    got = sorted(r["title"] for r in chosen)
    assert got == ["Headline 1", "Headline 4"] or got == ["Headline 1", "Headline 5"]


def test_select_respects_domain_cap_filters_and_is_deterministic():
    rows = [raw_row(i, domain="thehindu.com") for i in range(10)] + [raw_row(i + 10, domain="ndtv.com") for i in range(10)]
    a = ms.select(rows, 8, 7, 3, set(), None, set(), set())
    b = ms.select(rows, 8, 7, 3, set(), None, set(), set())
    assert [r["title"] for r in a] == [r["title"] for r in b]
    assert sum(r["domain"] == "thehindu.com" for r in a) == 3 and len(a) == 6
    only = ms.select(rows, 20, 0, 0, {"ndtv.com"}, None, set(), set())
    assert {r["domain"] for r in only} == {"ndtv.com"}
    rows[0]["published_utc"] = "2026-01-01T00:00:00Z"
    assert all(r["published_utc"][:10] >= "2026-10-01" for r in ms.select(rows, 20, 0, 0, set(), "2026-10-01", set(), set()))


def test_cli_assigns_sequential_ids_and_never_reuses_them(tmp_path):
    write_raw(tmp_path, [raw_row(i, domain=d) for i, d in enumerate(["thehindu.com", "ndtv.com", "scroll.in", "theprint.in"])])
    first = cli(tmp_path, "--annotator", "A1", "--n", "2", "--per-domain-cap", "0")
    assert [s["id"] for s in first] == ["art-0001", "art-0002"]
    second = cli(tmp_path, "--annotator", "A1", "--n", "5", "--per-domain-cap", "0")
    assert [s["id"] for s in second] == ["art-0003", "art-0004"]      # only two unseen articles remained
    rows = read(tmp_path / "annotated" / "art_A1.jsonl")
    assert len({r["url"] for r in rows}) == 4 and len({r["id"] for r in rows}) == 4


def test_split_option_sets_the_gold_destination_and_pilot_overrides_it(tmp_path):
    write_raw(tmp_path, [raw_row(i) for i in range(1, 5)])
    few = cli(tmp_path, "--annotator", "A1", "--n", "2", "--split", "fewshot", "--per-domain-cap", "0")
    assert {s["split"] for s in few} == {"fewshot"}
    pilot = cli(tmp_path, "--annotator", "A1", "--n", "2", "--pilot", "--per-domain-cap", "0")
    assert {s["split"] for s in pilot} == {"pilot"}
    with pytest.raises(SystemExit):
        cli(tmp_path, "--annotator", "A1", "--pilot", "--split", "fewshot")


def test_overlap_marks_only_the_first_k(tmp_path):
    write_raw(tmp_path, [raw_row(i) for i in range(1, 6)])
    stubs = cli(tmp_path, "--annotator", "A1", "--n", "5", "--overlap", "2", "--per-domain-cap", "0")
    assert [s["overlap_set"] for s in stubs] == [True, True, False, False, False]


def test_second_annotator_clone_gets_identical_input_and_fresh_labels(tmp_path, capsys):
    write_raw(tmp_path, [raw_row(i) for i in range(1, 5)])
    a1 = cli(tmp_path, "--annotator", "A1", "--n", "4", "--overlap", "2", "--per-domain-cap", "0")
    a1_path = tmp_path / "annotated" / "art_A1.jsonl"
    # A1 finishes labeling, then A2's overlap file is cloned from A1's
    a1_path.write_text("\n".join(json.dumps(fill(s)) for s in a1) + "\n", encoding="utf-8")
    clones = cli(tmp_path, "--annotator", "A2", "--clone", str(a1_path))
    assert [c["id"] for c in clones] == ["art-0001", "art-0002"] and all(c["annotator"] == "A2" for c in clones)
    assert all(c["labels"]["political"]["label"].startswith("<") for c in clones)   # A1's labels are not leaked
    a2_path = tmp_path / "annotated" / "art_A2.jsonl"
    a2_path.write_text("\n".join(json.dumps(fill(c)) for c in clones) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        v.main([str(a1_path), str(a2_path)])
    assert exc.value.code == 0 and "0 problems" in capsys.readouterr().out
    assert cli(tmp_path, "--annotator", "A2", "--clone", str(a1_path)) == []      # nothing new the second time


def test_cli_warns_when_too_few_articles(tmp_path, capsys):
    write_raw(tmp_path, [raw_row(1)])
    assert len(cli(tmp_path, "--annotator", "A1", "--n", "5", "--per-domain-cap", "0")) == 1
    assert "only 1 eligible" in capsys.readouterr().out


def test_pick_selects_exact_articles_and_reports_problems(tmp_path, capsys):
    rows = [raw_row(1), raw_row(2), raw_row(3, status="too_short")]
    write_raw(tmp_path, rows)
    stubs = cli(tmp_path, "--annotator", "A1", "--pick", "https://thehindu.com/story-2",
                "--pick", "https://thehindu.com/story-3", "--pick", "https://thehindu.com/missing")
    assert [s["title"] for s in stubs] == ["Headline 2"]
    out = capsys.readouterr().out
    assert "lede_status is too_short" in out and "not in raw" in out
    assert cli(tmp_path, "--annotator", "A1", "--pick", "https://thehindu.com/story-2") == []   # already has an entry


def test_gold_entries_also_reserve_ids_and_urls(tmp_path):
    write_raw(tmp_path, [raw_row(1), raw_row(2)])
    (tmp_path / "gold").mkdir()
    done = ms.make_stub(raw_row(1), "art-0007", "A1", False, False)
    (tmp_path / "gold" / "eval.jsonl").write_text(json.dumps(done) + "\n", encoding="utf-8")
    stubs = cli(tmp_path, "--annotator", "A1", "--n", "5", "--per-domain-cap", "0")
    assert [s["id"] for s in stubs] == ["art-0008"] and stubs[0]["title"] == "Headline 2"


def test_clone_keeps_facts_but_resets_judgments(tmp_path):
    write_raw(tmp_path, [raw_row(1)])
    a1 = cli(tmp_path, "--annotator", "A1", "--n", "1", "--overlap", "1", "--per-domain-cap", "0")
    done = fill(a1[0])
    done.update(url_archive="https://web.archive.org/keep", event_id="ev-keep", adjudicated="old note")
    path = tmp_path / "annotated" / "art_A1.jsonl"
    path.write_text(json.dumps(done) + "\n", encoding="utf-8")
    clone = cli(tmp_path, "--annotator", "A2", "--clone", str(path))[0]
    assert clone["url_archive"].endswith("/keep") and clone["event_id"] == "ev-keep" and clone["syndicated"] is False
    assert clone["article_type"].startswith("<") and "adjudicated" not in clone


def test_raw_files_are_never_modified(tmp_path):
    raw = write_raw(tmp_path, [raw_row(i) for i in range(1, 4)])
    before = (raw / "2026-10-10.jsonl").read_bytes()
    cli(tmp_path, "--annotator", "A1", "--n", "3", "--per-domain-cap", "0")
    assert (raw / "2026-10-10.jsonl").read_bytes() == before


# ---------- same-event detection
def word(i):
    """A unique capitalised pseudo-word, so filler articles share no names."""
    return "Q" + chr(97 + i % 26) + chr(97 + (i // 26) % 26) + chr(97 + (i // 676) % 26) + "x"


def story(i, title, lede="officials said the matter is under review and more details will follow soon."):
    r = raw_row(i)
    r.update(title=title, lede=lede, lede_hash=f"story{i}")
    return r


def pool_with_tiger_group(filler=300):
    tiger = [story(1, "Tiger Shroff attack: Juhu police probe three shooters"),
             story(2, "Salman Khan security raised after Tiger Shroff firing in Juhu"),
             story(3, "Cine workers body writes to Amit Shah over Tiger Shroff Juhu attack"),
             story(4, "Actress Disha Patani visits Tiger Shroff after Juhu firing")]
    fill_rows = [story(100 + i, f"{word(2 * i)} {word(2 * i + 1)} announces new plan") for i in range(filler)]
    return tiger, fill_rows


def test_guard_scores_same_event_far_above_unrelated_stories():
    tiger, fillers = pool_with_tiger_group()
    guard = ms.EventGuard(tiger + fillers, [], cap=2, threshold=12.0)
    a, b, other = (ms.name_tokens(r) for r in (tiger[0], tiger[1], fillers[0]))
    assert guard.score(a, b) >= 12 and guard.score(a, other) < 4
    assert guard.shared(a, b) == ["juhu", "shroff", "tiger"]


@pytest.mark.parametrize("cap,expected", [(1, 1), (2, 2), (0, 4)])
def test_select_limits_stories_per_event(cap, expected):
    tiger, fillers = pool_with_tiger_group()
    rows = tiger + fillers
    guard = ms.EventGuard(rows, [], cap=cap, threshold=12.0)
    chosen = ms.select(rows, len(rows), 0, 0, set(), None, set(), set(), guard)
    assert sum(r["title"] in {t["title"] for t in tiger} for r in chosen) == expected
    assert len(chosen) == len(fillers) + expected


def test_cap_counts_entries_that_already_exist(tmp_path):
    tiger, fillers = pool_with_tiger_group()
    write_raw(tmp_path, tiger + fillers)
    existing = [ms.make_stub(tiger[0], "art-0001", "A1", False, False), ms.make_stub(tiger[1], "art-0002", "A1", False, False)]
    (tmp_path / "annotated").mkdir()
    (tmp_path / "annotated" / "art_A1.jsonl").write_text("\n".join(json.dumps(s) for s in existing) + "\n", encoding="utf-8")
    stubs = cli(tmp_path, "--annotator", "A1", "--n", "400", "--per-domain-cap", "0")
    titles = {s["title"] for s in stubs}
    assert tiger[2]["title"] not in titles and tiger[3]["title"] not in titles and len(stubs) == len(fillers)


def test_event_option_tags_stubs_and_respects_the_cap(tmp_path, capsys):
    tiger, fillers = pool_with_tiger_group(filler=5)
    write_raw(tmp_path, tiger + fillers)
    urls = [t["canonical_url"] for t in tiger[:3]]
    first = cli(tmp_path, "--annotator", "A1", "--event", "tiger-attack-2026-10",
                *[x for u in urls for x in ("--pick", u)])
    assert len(first) == 2 and {s["event_id"] for s in first} == {"tiger-attack-2026-10"}
    assert "allows 2 more stories" in capsys.readouterr().out
    again = cli(tmp_path, "--annotator", "A1", "--event", "tiger-attack-2026-10", "--pick", urls[2])
    assert again == []


def test_review_list_names_stories_that_look_alike(tmp_path, capsys):
    tiger, fillers = pool_with_tiger_group()
    write_raw(tmp_path, tiger + fillers)
    cli(tmp_path, "--annotator", "A1", "--per-event-cap", "0", *[x for t in tiger[:2] for x in ("--pick", t["canonical_url"])])
    out = capsys.readouterr().out
    assert "look like the same story" in out and "art-0001 and art-0002" in out and "juhu, shroff, tiger" in out


def test_review_list_also_compares_against_existing_entries(tmp_path, capsys):
    tiger, fillers = pool_with_tiger_group()
    write_raw(tmp_path, tiger + fillers)
    cli(tmp_path, "--annotator", "A1", "--pick", tiger[0]["canonical_url"])
    capsys.readouterr()
    cli(tmp_path, "--annotator", "A1", "--pick", tiger[3]["canonical_url"])
    assert "art-0002 and art-0001" in capsys.readouterr().out


def test_unrelated_articles_produce_no_review_list(tmp_path, capsys):
    tiger, fillers = pool_with_tiger_group()
    write_raw(tmp_path, tiger + fillers)
    cli(tmp_path, "--annotator", "A1", "--pick", tiger[0]["canonical_url"], "--pick", fillers[0]["canonical_url"])
    assert "look like the same story" not in capsys.readouterr().out


def test_articles_in_both_raw_and_annotated_are_counted_once_when_weighing_names():
    tiger, fillers = pool_with_tiger_group()
    taken = [ms.make_stub(tiger[0], "art-0001", "A1", False, False)]
    once = ms.EventGuard(tiger + fillers, [], 2, 12.0)
    twice = ms.EventGuard(tiger + fillers, taken, 2, 12.0)
    assert once.n == twice.n and once.df["tiger"] == twice.df["tiger"] == 4
