import pytest

import api_audit as aa

pytest.importorskip("defusedxml")


def parse(xml):
    return aa.ET.fromstring(xml.encode())


def first_item(root):
    return next(el for el in root.iter() if el.tag.rsplit("}", 1)[-1] in ("item", "entry"))


def test_item_link_prefers_feedburner_origlink():
    root = parse('<rss xmlns:feedburner="http://rssnamespace.org/feedburner/ext/1.0"><channel><item>'
                 '<link>https://feedproxy.google.com/~r/x</link><feedburner:origLink>https://www.ndtv.com/a</feedburner:origLink>'
                 '</item></channel></rss>')
    assert aa.item_link(first_item(root)) == "https://www.ndtv.com/a"


def test_item_link_falls_back_to_guid_url_only():
    good = parse("<rss><channel><item><guid>https://x.com/a</guid></item></channel></rss>")
    bad = parse("<rss><channel><item><guid>tag:x.com,2026:123</guid></item></channel></rss>")
    assert aa.item_link(first_item(good)) == "https://x.com/a"
    assert aa.item_link(first_item(bad)) == ""


def test_atom_link_prefers_alternate_over_self():
    root = parse('<feed xmlns="http://www.w3.org/2005/Atom"><entry><link rel="self" href="https://x.com/feed/1"/>'
                 '<link rel="alternate" href="https://x.com/story/1"/></entry></feed>')
    assert aa.item_link(first_item(root)) == "https://x.com/story/1"


def test_entity_expansion_bomb_is_rejected():
    bomb = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
            '<rss><channel><item><title>&b;</title></item></channel></rss>')
    with pytest.raises((aa.ET.ParseError, ValueError)):
        aa.ET.fromstring(bomb.encode())


def test_fetch_rss_skips_bad_feeds_and_reads_good_ones(tmp_path, monkeypatch, capsys):
    (tmp_path / "f.txt").write_text("# comment\nGood | https://good.example/rss\nBad | https://bad.example/rss\n"
                                    "Down | https://down.example/rss\n")
    feeds = {"https://good.example/rss": b"<rss><channel><item><title><![CDATA[Story]]></title>"
                                          b"<link>https://www.thehindu.com/a</link><description>&lt;p&gt;Desc&lt;/p&gt;</description>"
                                          b"<category>Opinion</category></item></channel></rss>",
             "https://bad.example/rss": b"<not xml"}
    monkeypatch.setattr(aa, "get_feed_bytes", lambda url: feeds.get(url))
    recs = aa.fetch_rss(str(tmp_path / "f.txt"))
    assert len(recs) == 1 and recs[0]["title"] == "Story" and recs[0]["snippet"] == "Desc"
    assert recs[0]["type_hint"] == "opinion" and recs[0]["domain"] == "thehindu.com"
    assert "Bad: not valid XML" in capsys.readouterr().out


def rec(url, title="Title", snippet="A snippet"):
    return aa.record("rss", "Feed", url, title, snippet, "", "", "")


def test_reject_reason_order_and_snippet_toggle():
    assert rec("https://www.thehindu.com/a").reject_reason if False else aa.reject_reason(rec("https://www.thehindu.com/a")) == ""
    assert aa.reject_reason(rec("https://www.thehindu.com/a", snippet="")) == "blank_snippet"
    assert aa.reject_reason(rec("https://www.thehindu.com/a", snippet="Title")) == "snippet_is_title"
    assert aa.reject_reason(rec("https://www.thehindu.com/a", snippet=""), need_snippet=False) == ""
    assert aa.reject_reason(rec("https://sports.ndtv.com/cricket/a")) == "sports"
    assert aa.reject_reason(rec("https://news.google.com/a")) == "blocked_domain"
    assert aa.reject_reason(rec("https://blog.example/a")) == "off_target"
    assert aa.reject_reason(rec("https://www.thehindu.com/a", title="हिंदी शीर्षक", snippet="हिंदी विवरण")) == "non_english"


def test_sports_subdomain_is_not_a_target_outlet():
    assert aa.is_target("ndtv.com") and not aa.is_target("sports.ndtv.com") and not aa.is_target("ndtvprofit.com")
