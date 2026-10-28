"""Audit news sources for Indian-outlet coverage and snippet quality.

Put your keys in a .env file in the repo root (see .env.example), then run:
    python scripts/api_audit.py --pages 3
    python scripts/api_audit.py --query "custody" --pages 2     # keyword search instead of politics
    python scripts/api_audit.py --rss-file rss_feeds.txt        # outlet RSS feeds (see rss_feeds.example.txt)

Keys read: NEWSDATA_KEY, NEWSAPI_KEY, WORLDNEWS_KEY. A source with no key is skipped.
Real environment variables take priority over the .env file.

Every row is tagged with the ingestion filter it would fail (reject_reason), so the
report shows how much of each source is usable. Nothing is dropped from the CSV.
The allowed outlets live in outlets.txt (see scripts/outlets.py).
"""
import argparse
import csv
import html
import json
import os
import re
import statistics
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import outlets
import safe_fetch

try:
    from defusedxml import ElementTree as ET
except ImportError:  # feeds are untrusted input; install defusedxml to block entity-expansion attacks
    from xml.etree import ElementTree as ET
    print("warning: defusedxml is not installed; run pip install -r requirements.txt")

TARGETS = outlets.load()
TARGET_DOMAINS = set(TARGETS.values())


def reload_targets(path=outlets.DEFAULT_PATH):
    """Re-read outlets.txt (or another file) into TARGETS and TARGET_DOMAINS."""
    global TARGETS, TARGET_DOMAINS
    TARGETS = outlets.load(path)
    TARGET_DOMAINS = set(TARGETS.values())


BLOCKED_DOMAINS = {"news.google.com", "menafn.com", "einpresswire.com", "prnewswire.com",
                   "globenewswire.com", "businesswire.com"}
SPORT_HINTS = re.compile(r"cricket|espn|sportskeeda|/sports?/|\bipl\b", re.I)
OPINION_HINTS = re.compile(r"opinion|editorial|column|viewpoint|op-ed", re.I)
PAID_MARKERS = ("ONLY AVAILABLE IN PAID", "PAID PLAN")


def load_env():
    """Read KEY=VALUE lines from .env (current folder, then repo root) into os.environ."""
    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"]
    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            if value:
                os.environ.setdefault(key.strip(), value)
        print(f"loaded keys from {path}")
        return
    print("no .env file found; using environment variables only")


def get_bytes(url, params=None):
    if params:
        url = f"{url}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (news-bias-audit/0.2)"})
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.read(5_000_000)
    except HTTPError as e:
        print(f"  HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}")
    except URLError as e:
        print(f"  network error: {e.reason}")
    return None


def get_json(url, params=None):
    raw = get_bytes(url, params)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print("  response was not JSON")
        return None


def domain_of(url):
    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def is_target(domain):
    """Exact host match, so food.ndtv.com and sports.ndtv.com are not treated as the news site."""
    return domain in TARGET_DOMAINS


def non_latin_share(text):
    letters = [c for c in text if c.isalpha()]
    return sum(ord(c) > 0x24F for c in letters) / len(letters) if letters else 0.0


def words(text):
    return len(text.split())


def lede_overlap(rec):
    """Share of snippet words that appear in the first 120 body words."""
    if not rec["snippet"] or not rec["body"]:
        return None
    lede = set(" ".join(rec["body"].split()[:120]).lower().split())
    snip = set(rec["snippet"].lower().split())
    return len(snip & lede) / len(snip) if snip else None


def reject_reason(rec, need_snippet=True):
    """First ingestion filter the row fails, or '' if it is usable.
    need_snippet=False skips the snippet checks (the collector reads the lede from the page instead)."""
    d = rec["domain"]
    if non_latin_share(rec["title"]) > 0.2 or non_latin_share(rec["snippet"]) > 0.2:
        return "non_english"
    if need_snippet and not rec["snippet"]:
        return "blank_snippet"
    if need_snippet and rec["snippet"] == rec["title"]:
        return "snippet_is_title"
    if any(d == b or d.endswith("." + b) for b in BLOCKED_DOMAINS):
        return "blocked_domain"
    if d.startswith("sports.") or SPORT_HINTS.search(rec["url"]):
        return "sports"
    if not is_target(d):
        return "off_target"
    return ""


def record(api, outlet, url, title, snippet, body, published, category=""):
    body = body or ""
    if any(m in body.upper() for m in PAID_MARKERS):
        body = ""
    rec = {"api": api, "outlet": outlet or "", "domain": domain_of(url), "url": url or "",
           "title": (title or "").strip(), "snippet": (snippet or "").strip(),
           "body": body.strip(), "published": published or "", "category": (category or "").strip()}
    rec["type_hint"] = ("opinion" if OPINION_HINTS.search(urlparse(rec["url"]).path)
                        or OPINION_HINTS.search(rec["category"]) else "")
    rec["reject_reason"] = reject_reason(rec)
    return rec


def fetch_newsdata(key, pages, query, category):
    recs, token = [], None
    for _ in range(pages):
        params = {"apikey": key, "country": "in", "language": "en"}
        if query:
            params["q"] = query
        if category:
            params["category"] = category
        if token:
            params["page"] = token
        j = get_json("https://newsdata.io/api/1/latest", params)
        if not j or "results" not in j:
            if j:
                print(f"  unexpected response: {str(j)[:200]}")
            break
        if not recs and j["results"]:
            print(f"  fields returned: {sorted(j['results'][0].keys())}")
        for a in j["results"]:
            recs.append(record("newsdata", a.get("source_name") or a.get("source_id"), a.get("link"),
                               a.get("title"), a.get("description"), a.get("content"), a.get("pubDate")))
        token = j.get("nextPage")
        if not token:
            break
        time.sleep(1)
    return recs


def fetch_newsapi(key, per_domain, query):
    recs = []
    start = (date.today() - timedelta(days=3)).isoformat()
    print(f"  one request per outlet: {len(TARGET_DOMAINS)} requests (free plan allows 100/day)")
    for domain in sorted(TARGET_DOMAINS):
        params = {"domains": domain, "language": "en", "sortBy": "publishedAt", "from": start,
                  "pageSize": per_domain, "apiKey": key}
        if query:
            params["q"] = query
        j = get_json("https://newsapi.org/v2/everything", params)
        if not j or "articles" not in j:
            if j:
                print(f"  {domain}: unexpected response: {str(j)[:200]}")
            continue
        if not recs and j["articles"]:
            print(f"  fields returned: {sorted(j['articles'][0].keys())}")
        for a in j["articles"]:
            recs.append(record("newsapi", (a.get("source") or {}).get("name"), a.get("url"),
                               a.get("title"), a.get("description"), a.get("content"), a.get("publishedAt")))
        time.sleep(1)
    return recs


def fetch_worldnews(key, pages, query):
    params = {"source-countries": "in", "language": "en", "number": min(100, 20 * pages),
              "sort": "publish-time", "sort-direction": "DESC", "api-key": key}
    if query:
        params["text"] = query
    j = get_json("https://api.worldnewsapi.com/search-news", params)
    if not j or "news" not in j:
        if j:
            print(f"  unexpected response: {str(j)[:200]}")
        return []
    if j["news"]:
        print(f"  fields returned: {sorted(j['news'][0].keys())}")
    return [record("worldnews", "", a.get("url"), a.get("title"), a.get("summary"),
                   a.get("text"), a.get("publish_date")) for a in j["news"]]


_FETCHER = None
_LAST_FEED_HIT = {}
FEED_GAP = 1.0
_sleep = time.sleep


def get_feed_bytes(url):
    """Fetch a feed through the hardened fetcher. Returns bytes, or None after printing the reason."""
    global _FETCHER
    if _FETCHER is None:
        _FETCHER = safe_fetch.Fetcher()
    host = domain_of(url)
    wait = _LAST_FEED_HIT.get(host, 0) + FEED_GAP - time.monotonic()
    if wait > 0:
        _sleep(wait)
    _LAST_FEED_HIT[host] = time.monotonic()
    res = _FETCHER.fetch(url, accept="application/rss+xml,application/atom+xml,application/xml;q=0.9,*/*;q=0.5",
                         require_html=False)
    if res.error:
        print(f"  {res.error}" + (f" (HTTP {res.status})" if res.status else "") + (f": {res.detail}" if res.detail else ""))
        return None
    return res.body


def strip_html(text):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())


def child_text(el, *names):
    for child in el:
        local = child.tag.rsplit("}", 1)[-1]
        if local in names:
            if local == "link" and child.get("href"):
                if child.get("rel") in (None, "alternate"):
                    return child.get("href")
                continue
            return child.text or ""
    return ""


def item_link(item):
    link = (child_text(item, "origLink") or child_text(item, "link")).strip()
    if not link:
        guid = child_text(item, "guid").strip()
        link = guid if guid.startswith(("http://", "https://")) else ""
    return link


def read_feed_list(path):
    feeds = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "|" in line:
            name, _, url = line.partition("|")
            feeds.append((name.strip(), url.strip()))
    return feeds


def fetch_rss(path, limit=50):
    recs = []
    for name, url in read_feed_list(path):
        print(f"  {name}: fetching")
        raw = get_feed_bytes(url)
        if raw is None:
            continue
        try:
            root = ET.fromstring(raw)
        except (ET.ParseError, ValueError) as e:
            print(f"  {name}: not valid XML or blocked by the XML safety check ({e})")
            continue
        items = [el for el in root.iter() if el.tag.rsplit("}", 1)[-1] in ("item", "entry")][:limit]
        print(f"  {name}: {len(items)} items")
        for it in items:
            recs.append(record(
                "rss", name, item_link(it), strip_html(child_text(it, "title")),
                strip_html(child_text(it, "description", "summary")),
                strip_html(child_text(it, "encoded", "content")),
                child_text(it, "pubDate", "published", "updated"),
                strip_html(child_text(it, "category"))))
    return recs


def median(values):
    return statistics.median(values) if values else None


def report(name, recs):
    print(f"\n=== {name} ===")
    n = len(recs)
    if not n:
        print("no articles returned")
        return
    on_target = [r for r in recs if is_target(r["domain"])]
    usable = [r for r in recs if not r["reject_reason"]]
    print(f"articles fetched: {n}; from target outlets (excluding sports subdomains): "
          f"{len(on_target)} ({100 * len(on_target) / n:.0f}%)")
    print(f"usable after ingestion filters: {len(usable)} ({100 * len(usable) / n:.0f}%)")
    print("rejected for (first failing filter):",
          dict(Counter(r["reject_reason"] for r in recs if r["reject_reason"])))
    print("top domains:", ", ".join(f"{d} ({c})" for d, c in Counter(r["domain"] for r in recs).most_common(8)))
    snips = [r for r in recs if r["snippet"]]
    print(f"snippet: {n - len(snips)} blank; median {median([len(r['snippet']) for r in snips])} chars, "
          f"{median([words(r['snippet']) for r in snips])} words; "
          f"{sum(r['snippet'].endswith(('...', '…')) for r in snips)} end in an ellipsis; "
          f"{sum(not r['snippet'].rstrip().endswith(('.', '!', '?', '\"', '”', '’', '...', '…')) for r in snips)} "
          "lack terminal punctuation")
    bodies = [r for r in recs if r["body"]]
    print(f"body available on {len(bodies)} of {n}; median {median([len(r['body']) for r in bodies])} chars")
    overlaps = [o for o in (lede_overlap(r) for r in recs) if o is not None]
    if overlaps:
        print(f"snippet words found in first 120 body words, median share: {median(overlaps):.2f} "
              "(near 1.0 means the snippet is mostly lede text)")
    print(f"opinion-looking URLs or categories: {sum(r['type_hint'] == 'opinion' for r in recs)}")


def dedupe(recs):
    seen, unique = set(), []
    for r in recs:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)
    return unique


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=3, help="pages per API (NewsAPI: articles per outlet = 10 x pages)")
    ap.add_argument("--query", default="", help="keyword search; use for gender or communal stories")
    ap.add_argument("--category", default="politics",
                    help="NewsData.io category; pass '' to disable (ignored when --query is set)")
    ap.add_argument("--rss-file", default="rss_feeds.txt", help="file of 'Name | feed URL' lines")
    ap.add_argument("--tag", default="", help="label added to the output file name, e.g. politics or custody")
    args = ap.parse_args()
    load_env()
    category = "" if args.query else args.category
    jobs = [
        ("NewsData.io", "NEWSDATA_KEY", lambda k: fetch_newsdata(k, args.pages, args.query, category)),
        ("NewsAPI.org", "NEWSAPI_KEY", lambda k: fetch_newsapi(k, 10 * args.pages, args.query)),
        ("World News API", "WORLDNEWS_KEY", lambda k: fetch_worldnews(k, args.pages, args.query)),
    ]
    all_recs = []
    for name, env, fetch in jobs:
        key = os.environ.get(env)
        if not key:
            print(f"skipping {name}: {env} not set")
            continue
        print(f"fetching {name}...")
        recs = dedupe(fetch(key))
        report(name, recs)
        all_recs += recs
    if Path(args.rss_file).is_file():
        print(f"fetching RSS feeds from {args.rss_file}...")
        recs = dedupe(fetch_rss(args.rss_file))
        report("RSS", recs)
        all_recs += recs
    else:
        print(f"skipping RSS: {args.rss_file} not found (copy rss_feeds.example.txt and fill it in)")
    if not all_recs:
        sys.exit("no data collected")
    os.makedirs("audit_out", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = f"audit_out/samples_{stamp}{'_' + args.tag if args.tag else ''}.csv"
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["api", "outlet", "domain", "target_outlet", "published", "url", "title", "snippet",
                    "snippet_words", "body_chars", "lede_overlap", "category", "type_hint", "reject_reason"])
        for r in all_recs:
            ov = lede_overlap(r)
            w.writerow([r["api"], r["outlet"], r["domain"], is_target(r["domain"]), r["published"], r["url"],
                        r["title"], r["snippet"], words(r["snippet"]), len(r["body"]),
                        "" if ov is None else f"{ov:.2f}", r["category"], r["type_hint"], r["reject_reason"]])
    print(f"\nwrote {out_path} ({len(all_recs)} rows)")


if __name__ == "__main__":
    main()
