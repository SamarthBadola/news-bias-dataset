import argparse
import json
from collections import Counter

import pytest

import api_audit as aa
import collect as c
import safe_fetch as sf

FILLER = ("The opposition parties have criticised the decision and demanded a discussion in Parliament, "
          "while the government maintained that the process followed all constitutional requirements. ")


def html(title, paras):
    body = "".join(f"<p>{p}</p>" for p in paras)
    return (f"<html><head><title>{title}</title></head><body><nav>Home | India</nav><article><h1>{title}</h1>"
            f"{body}</article><footer>Follow us on social media</footer></body></html>").encode()


GOOD = html("Budget defended", ["By Staff Reporter",
                                 "NEW DELHI: Prime Minister Narendra Modi on Saturday defended the budget. " + FILLER,
                                 "Congress said the interview was an attempt to manage headlines. " + FILLER,
                                 "A third paragraph that must not appear in the lede. " + FILLER])


class FakeFetcher:
    """Maps URL -> Fetched; unknown URLs return 404. Records every call."""

    def __init__(self, pages=None, robots=None):
        self.pages = pages or {}
        self.robots = robots or {}
        self.calls = []

    def fetch(self, url, **kw):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            host = url.split("/")[2]
            return self.robots.get(host, sf.Fetched(url, 404, error="http_404"))
        page = self.pages.get(url)
        if isinstance(page, Exception):
            raise page
        return page or sf.Fetched(url, 404, error="http_404")


def ok(url, body):
    return sf.Fetched(url, 200, body, "", "text/html", url)


def row(url, title="A headline", domain=None):
    domain = domain or url.split("/")[2].removeprefix("www.")
    return {"url": url, "domain": domain, "title": title, "lede": "", "lede_words": 0,
            "lede_status": "not_fetched", "http_status": None, "fetch_error": "", "agency_hint": [], "lede_hash": ""}


# ---------- pure helpers
def test_to_utc_iso_normalises_formats_and_zones():
    assert c.to_utc_iso("Sat, 10 Oct 2026 15:47:25 +0530") == "2026-10-10T10:17:25Z"
    assert c.to_utc_iso("2026-10-10T15:49:44+05:30") == "2026-10-10T10:19:44Z"
    assert c.to_utc_iso("Sat, 10 Oct 2026 09:16:48 +0000") == "2026-10-10T09:16:48Z"
    assert c.to_utc_iso("garbage") == "" and c.to_utc_iso(None) == ""


@pytest.mark.parametrize("text,starts", [
    ("NEW DELHI: The government on Friday said it would table the bill.", "The government"),
    ("New Delhi: The government on Friday said it would table the bill.", "The government"),
    ("Mumbai, Oct 10 (PTI) The state government announced a relief package today.", "The state"),
    ("Trump: Said the war would end soon according to aides who spoke.", "Trump: Said"),
    ("Congress leaders were detained on Saturday during the protest in the capital.", "Congress leaders"),
])
def test_strip_dateline(text, starts):
    assert c.strip_dateline(text).startswith(starts)


def test_cap_words_prefers_sentence_boundary_and_respects_limit():
    text = " ".join(["word"] * 70) + ". " + " ".join(["more"] * 70) + "."
    out = c.cap_words(text, 120, 60)
    assert out.endswith("word.") and len(out.split()) == 70
    assert c.cap_words("short text here", 120, 60) == "short text here"
    no_boundary = " ".join(["w"] * 200)
    assert len(c.cap_words(no_boundary, 120, 60).split()) == 120


def test_build_lede_drops_byline_and_boilerplate_keeps_two_paragraphs():
    text = "\n".join(["By Staff Reporter", "Disclaimer: This report is auto-generated from a wire feed.",
                      "Advertisement", "First real paragraph " + FILLER, "Second real paragraph " + FILLER,
                      "Third paragraph " + FILLER])
    lede = c.build_lede(text)
    assert lede.startswith("First real paragraph") and "Second real" in lede and "Third" not in lede
    assert "Staff Reporter" not in lede and "Disclaimer" not in lede


def test_build_lede_keeps_sentences_that_merely_start_with_by():
    text = "By Sunday, the opposition had walked out of the House over the bill and the speaker adjourned it.\n" + FILLER
    assert c.build_lede(text).startswith("By Sunday")


def test_build_lede_caps_at_120_words():
    assert len(c.build_lede("\n".join([FILLER * 3, FILLER * 3])).split()) <= 120


@pytest.mark.parametrize("a,b", [
    ("https://www.Example.com/story/?utm_source=x&id=7#top", "https://example.com/story?id=7"),
    ("https://example.com/a/", "https://example.com/a"),
    ("https://example.com/a?fbclid=1&utm_medium=2", "https://example.com/a"),
])
def test_canonical_strips_tracking_but_keeps_real_params(a, b):
    assert c.canonical(a) == b


def test_canonical_distinguishes_articles_that_differ_by_query_id():
    assert c.canonical("https://x.com/read?id=1") != c.canonical("https://x.com/read?id=2")


@pytest.mark.parametrize("url,title,expected", [
    ("https://x.com/live-updates/abc", "Protest news", True),
    ("https://x.com/news/1", "LIVE UPDATES: protest in Delhi", True),
    ("https://x.com/news/1", "Live: PM addresses the nation", True),
    ("https://x.com/news/1", "Live-in relationship: HC says adults may choose", False),
    ("https://x.com/news/1", "Alive and well, says minister", False),
    ("https://x.com/news/olive-oil-prices", "Olive oil prices fall", False),
])
def test_is_live(url, title, expected):
    assert c.is_live(url, title) is expected


# ---------- robots
def robots_response(host, status, text=""):
    return {host: sf.Fetched(f"https://{host}/robots.txt", status, text.encode(), "" if status == 200 else f"http_{status}")}


def test_robots_policies():
    f = FakeFetcher(robots={
        **robots_response("a.com", 200, "User-agent: *\nDisallow: /private\nCrawl-delay: 4\n"),
        **robots_response("b.com", 404), **robots_response("c.com", 403), **robots_response("d.com", 503),
        "e.com": sf.Fetched("x", 0, error="network_error")})
    r = c.Robots(f)
    assert r.allowed("https://a.com/news/1") and not r.allowed("https://a.com/private/x")
    assert r.crawl_delay("https://a.com/news/1") == 4
    assert r.allowed("https://b.com/x")                  # 404: no robots file
    assert not r.allowed("https://c.com/x")              # 403: treated as disallow
    assert not r.allowed("https://d.com/x")              # 5xx: cannot verify
    assert not r.allowed("https://e.com/x")              # network error: cannot verify
    r.allowed("https://a.com/news/2")
    assert f.calls.count("https://a.com/robots.txt") == 1   # cached


# ---------- page processing
def collector(pages, **kw):
    return c.Collector(fetcher=FakeFetcher(pages, kw.pop("robots", None)), delay=0, **kw)


def test_process_ok_extracts_lede_and_hints():
    url = "https://thehindu.com/a1"
    r = collector({url: ok(url, GOOD)}).process(row(url))
    assert r["lede_status"] == "ok" and r["lede"].startswith("Prime Minister Narendra Modi")
    assert "third paragraph" not in r["lede"] and r["lede_words"] <= 120 and r["lede_hash"]


def test_process_statuses():
    pages = {"https://x.com/stub": ok("https://x.com/stub", html("T", ["Subscribe to read the full story."])),
             "https://x.com/live-updates/1": ok("https://x.com/live-updates/1", GOOD),
             "https://x.com/empty": ok("https://x.com/empty", b"<html></html>")}
    col = collector(pages)
    assert col.process(row("https://x.com/stub"))["lede_status"] == "too_short"
    assert col.process(row("https://x.com/live-updates/1"))["lede_status"] == "live_blog"
    assert col.process(row("https://x.com/empty"))["lede_status"] == "extract_failed"
    missing = col.process(row("https://x.com/gone"))
    assert missing["lede_status"] == "fetch_failed" and missing["http_status"] == 404


def test_robots_blocked_rows_are_not_fetched():
    f = FakeFetcher(robots=robots_response("x.com", 200, "User-agent: *\nDisallow: /\n"))
    r = c.Collector(fetcher=f, delay=0).process(row("https://x.com/a"))
    assert r["lede_status"] == "robots_blocked" and "https://x.com/a" not in f.calls


def test_circuit_breaker_skips_a_domain_after_repeated_blocks_and_resets_on_success():
    limited = sf.Fetched("u", 429, error="http_429")
    pages = {f"https://blocked.com/{i}": limited for i in range(8)}
    col = collector(pages, max_failures=3)
    statuses = [col.process(row(f"https://blocked.com/{i}"))["lede_status"] for i in range(5)]
    assert statuses == ["fetch_failed"] * 3 + ["domain_skipped"] * 2
    # a success resets the counter
    pages2 = {"https://flaky.com/1": limited, "https://flaky.com/2": limited,
              "https://flaky.com/3": ok("https://flaky.com/3", GOOD), "https://flaky.com/4": limited}
    col2 = collector(pages2, max_failures=3)
    out = [col2.process(row(f"https://flaky.com/{i}"))["lede_status"] for i in range(1, 5)]
    assert "domain_skipped" not in out


def test_404s_do_not_trip_the_breaker():
    col = collector({}, max_failures=2)
    statuses = [col.process(row(f"https://x.com/{i}"))["lede_status"] for i in range(5)]
    assert set(statuses) == {"fetch_failed"}


# ---------- run(): persistence, dedup, resumability
def feed_item(url, title, feed="Feed"):
    return aa.record("rss", feed, url, title, "standfirst text here", "", "Sat, 10 Oct 2026 15:47:25 +0530", "")


@pytest.fixture
def args(tmp_path):
    (tmp_path / "feeds.txt").write_text("x | https://x\n")
    return argparse.Namespace(feeds=str(tmp_path / "feeds.txt"), out_dir=str(tmp_path / "raw"), max_per_feed=50,
                              delay=0, limit=0, max_failures=5, no_fetch=False, url=None, urls_file=None)


def read_rows(args):
    from pathlib import Path
    return [json.loads(line) for f in sorted(Path(args.out_dir).glob("*.jsonl")) for line in open(f, encoding="utf-8")]


def test_run_writes_rows_and_second_run_dedups(args, monkeypatch):
    urls = [f"https://www.thehindu.com/a{i}" for i in range(3)]
    monkeypatch.setattr(aa, "fetch_rss", lambda path, limit=50: [feed_item(u, f"Story {i}") for i, u in enumerate(urls)])
    fake = FakeFetcher({u: ok(u, GOOD) for u in urls})
    assert len(c.run(args, c.Collector(fetcher=fake, delay=0))) == 3
    before = len(fake.calls)
    assert c.run(args, c.Collector(fetcher=fake, delay=0)) == []
    assert len(fake.calls) == before and len(read_rows(args)) == 3


def test_same_title_on_different_domains_is_kept_but_same_domain_is_deduped(args, monkeypatch):
    items = [feed_item("https://www.thehindu.com/a", "Top headlines today"),
             feed_item("https://www.ndtv.com/b", "Top headlines today"),
             feed_item("https://www.thehindu.com/c", "Top headlines today")]
    monkeypatch.setattr(aa, "fetch_rss", lambda path, limit=50: items)
    fake = FakeFetcher({i["url"]: ok(i["url"], GOOD) for i in items})
    written = c.run(args, c.Collector(fetcher=fake, delay=0))
    assert sorted(r["domain"] for r in written) == ["ndtv.com", "thehindu.com"]


def test_transient_failures_are_not_saved_and_are_retried_next_run(args, monkeypatch):
    url = "https://www.thehindu.com/a"
    monkeypatch.setattr(aa, "fetch_rss", lambda path, limit=50: [feed_item(url, "Story")])
    down = FakeFetcher({url: sf.Fetched(url, 0, error="network_error")})
    assert c.run(args, c.Collector(fetcher=down, delay=0)) == [] and read_rows(args) == []
    up = FakeFetcher({url: ok(url, GOOD)})
    assert [r["lede_status"] for r in c.run(args, c.Collector(fetcher=up, delay=0))] == ["ok"]


def test_permanent_failures_are_saved_so_they_are_not_retried_forever(args, monkeypatch):
    url = "https://www.thehindu.com/gone"
    monkeypatch.setattr(aa, "fetch_rss", lambda path, limit=50: [feed_item(url, "Story")])
    fake = FakeFetcher({})
    assert c.run(args, c.Collector(fetcher=fake, delay=0))[0]["lede_status"] == "fetch_failed"
    assert c.run(args, c.Collector(fetcher=fake, delay=0)) == []


def test_limit_leaves_unprocessed_articles_for_the_next_run(args, monkeypatch):
    urls = [f"https://www.thehindu.com/a{i}" for i in range(4)]
    monkeypatch.setattr(aa, "fetch_rss", lambda path, limit=50: [feed_item(u, f"Story {i}") for i, u in enumerate(urls)])
    fake = FakeFetcher({u: ok(u, GOOD) for u in urls})
    args.limit = 2
    assert len(c.run(args, c.Collector(fetcher=fake, delay=0))) == 2
    args.limit = 0
    assert len(c.run(args, c.Collector(fetcher=fake, delay=0))) == 2
    assert len(read_rows(args)) == 4


def test_crash_midway_keeps_rows_already_finished(args, monkeypatch):
    urls = [f"https://www.thehindu.com/a{i}" for i in range(4)]
    monkeypatch.setattr(aa, "fetch_rss", lambda path, limit=50: [feed_item(u, f"Story {i}") for i, u in enumerate(urls)])
    pages = {urls[0]: ok(urls[0], GOOD), urls[1]: ok(urls[1], GOOD), urls[2]: RuntimeError("boom")}
    with pytest.raises(RuntimeError):
        c.run(args, c.Collector(fetcher=FakeFetcher(pages), delay=0))
    assert len(read_rows(args)) == 2


def test_dry_run_fetches_and_writes_nothing(args, monkeypatch, capsys):
    monkeypatch.setattr(aa, "fetch_rss", lambda path, limit=50: [feed_item("https://www.thehindu.com/a", "Story")])
    args.no_fetch = True
    fake = FakeFetcher()
    assert c.run(args, c.Collector(fetcher=fake, delay=0)) == [] and fake.calls == [] and read_rows(args) == []
    assert "dry run" in capsys.readouterr().out


def test_load_seen_skips_corrupt_lines_and_reads_bom(tmp_path):
    good = json.dumps({"canonical_url": "https://a.com/x", "domain": "a.com", "title": "T"})
    (tmp_path / "2026-10-10.jsonl").write_text("\ufeff" + good + "\n{broken\n\n", encoding="utf-8")
    urls, titles = c.load_seen(tmp_path)
    assert urls == {"https://a.com/x"} and ("a.com", c.norm_hash("T")) in titles


def test_filters_drop_sports_aggregators_and_off_target_before_fetching():
    items = [feed_item("https://sports.ndtv.com/cricket/x", "Cricket"), feed_item("https://news.google.com/a", "Agg"),
             feed_item("https://random-blog.example/a", "Blog"), feed_item("https://www.thehindu.com/ok", "Fine")]
    rows, skipped = c.new_rows(items, set(), set(), "2026-10-10T00:00:00Z")
    assert [r["domain"] for r in rows] == ["thehindu.com"]
    assert skipped == Counter({"sports": 1, "blocked_domain": 1, "off_target": 1})


# ---------- one-off URLs
PAGE_WITH_META = (b"<html><head><title>After the bill fails | Example</title>"
                  b'<meta name="description" content="A short summary of the story written by the publisher.">'
                  b'<meta property="article:published_time" content="2026-04-20T08:30:00+05:30">'
                  b"</head><body><article><h1>After the bill fails</h1><p>"
                  + (FILLER * 2).encode() + b"</p><p>" + FILLER.encode() + b"</p></article></body></html>")


def test_manual_url_gets_title_standfirst_and_date_from_the_page(args):
    url = "https://theprint.in/politics/after-the-bill-fails/2909555/"
    args.url = [url]
    fake = FakeFetcher({url: ok(url, PAGE_WITH_META)})
    written = c.run(args, c.Collector(fetcher=fake, delay=0))
    assert len(written) == 1
    r = written[0]
    assert r["origin"] == "manual" and r["feed"] == "manual" and r["lede_status"] == "ok"
    assert r["title"].startswith("After the bill fails") and r["standfirst"].startswith("A short summary")
    assert r["published_utc"].startswith("2026-04-2")


def test_manual_url_is_not_collected_twice(args):
    url = "https://theprint.in/a-story"
    args.url = [url, url + "?utm_source=x"]
    fake = FakeFetcher({url: ok(url, PAGE_WITH_META), url + "?utm_source=x": ok(url, PAGE_WITH_META)})
    assert len(c.run(args, c.Collector(fetcher=fake, delay=0))) == 1
    assert c.run(args, c.Collector(fetcher=fake, delay=0)) == []


def test_manual_url_bypasses_feed_filters_but_not_the_ssrf_guard(args):
    ok_url = "https://sports.example-blog.org/cricket/story"   # would be dropped by the feed filters
    bad = "http://169.254.169.254/latest/meta-data/"
    args.url = [ok_url, bad]
    fake = FakeFetcher({ok_url: ok(ok_url, PAGE_WITH_META), bad: sf.Fetched(bad, 0, error="blocked_address")})
    written = c.run(args, c.Collector(fetcher=fake, delay=0))
    by = {r["url"]: r for r in written}
    assert by[ok_url]["lede_status"] == "ok"
    assert by[bad]["lede_status"] == "fetch_failed" and by[bad]["fetch_error"] == "blocked_address"


def test_urls_file_skips_comments_and_blank_lines(tmp_path):
    f = tmp_path / "urls.txt"
    f.write_text("# bundle candidates\n\nhttps://a.example/1\n  https://b.example/2  \n")
    assert c.read_url_list(f) == ["https://a.example/1", "https://b.example/2"]


@pytest.mark.parametrize("status,error,transient", [
    ("fetch_failed", "network_error", True), ("fetch_failed", "dns_failed", True), ("fetch_failed", "http_503", True),
    ("fetch_failed", "http_429", True), ("domain_skipped", "", True),
    ("fetch_failed", "blocked_address", False), ("fetch_failed", "http_404", False), ("fetch_failed", "http_403", False),
    ("fetch_failed", "not_html", False), ("robots_blocked", "", False), ("ok", "", False)])
def test_only_temporary_failures_are_retried(status, error, transient):
    http = int(error.split("_")[1]) if error.startswith("http_") else 0
    assert c.is_transient({"lede_status": status, "fetch_error": error, "http_status": http}) is transient
