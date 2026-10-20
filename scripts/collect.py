"""Collect raw articles from outlet RSS feeds into data/raw/.

For each new article in the feeds: apply the ingestion filters, fetch the page politely,
extract the headline-plus-lede annotation input, and append one JSON line to
data/raw/<YYYY-MM-DD>.jsonl as soon as the row is finished. Raw files are append-only.

Usage:
    pip install -r requirements.txt
    python scripts/collect.py --limit 20       # first run: fetch at most 20 new pages
    python scripts/collect.py                  # full pull
    python scripts/collect.py --no-fetch       # dry run: read feeds, fetch nothing, write nothing
    python scripts/collect.py --url https://example.com/a-story   # one-off article that is not in any feed
    python scripts/collect.py --urls-file my_urls.txt             # many one-offs, one URL per line

Fetching rules: robots.txt is honoured (including Crawl-delay), requests to one domain are spaced out,
transient errors are retried, and a domain that keeps failing is skipped for the rest of the run.
Nothing here evades blocks: no robots.txt override, no paywall workaround, no proxy rotation.
A page that cannot be fetched gets a status and is excluded from annotation.

Lede rule (also in the annotation guideline): the first two body paragraphs after boilerplate
and dateline removal, cut to 120 words at the last full sentence if that keeps at least 60 words,
else at 120 words. Standfirst (the RSS description) is cut to 40 words the same way.
"""
import argparse
import hashlib
import importlib.util
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import api_audit as aa
import safe_fetch as sf

LEDE_WORDS, LEDE_MIN_KEEP, LEDE_PARAS = 120, 60, 2
STANDFIRST_WORDS, STANDFIRST_MIN_KEEP = 40, 15
MIN_OK_WORDS = 25

BOILER_LINE = re.compile(
    r"^(updated\s*:|published\s*:|also read|read more|advertisement|listen to this|subscribe|follow us|"
    r"disclaimer|this (report|story|article) (is|has been) (auto|automatically)|"
    r"\(this story|\(with inputs|photo\s*:|image\s*:|\(file photo)", re.I)
BYLINE = re.compile(r"^(by|written by|edited by)\s", re.I)
AGENCY_TAG = r"\((?:PTI|ANI|IANS|Reuters|AFP|UNI)\)"
CITIES = ("New Delhi|Delhi|Mumbai|Kolkata|Chennai|Bengaluru|Bangalore|Hyderabad|Lucknow|Patna|Chandigarh|"
          "Jaipur|Bhopal|Guwahati|Srinagar|Thiruvananthapuram|Washington|London|Beijing|Dubai")
DATE_PART = r"(?:,\s*[A-Za-z]{3,9}\.?\s*\d{1,2})?"
DATELINES = [
    re.compile(rf"^\s*[A-Za-z. ]{{2,30}}{DATE_PART}\s*{AGENCY_TAG}\s*(?::|—|–|-)?\s*"),
    re.compile(rf"^\s*[A-Z][A-Z .]{{2,30}}{DATE_PART}\s*(?::|—|–)\s+"),
    re.compile(rf"^\s*(?:{CITIES}){DATE_PART}\s*(?::|—|–)\s+"),
]
AGENCIES = re.compile(r"\b(Bloomberg|Reuters|PTI|ANI|IANS|AFP|UNI)\b")
LIVE_URL = re.compile(r"live[ -]?(updates?|blog)|/live-", re.I)
LIVE_TITLE = re.compile(r"^\s*live\s*(?:updates?|blog|coverage|:|\||[-–—]\s)", re.I)
TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|igshid|ref|ito|cmpid|mc_cid|mc_eid)$", re.I)


def to_utc_iso(value):
    value = (value or "").strip()
    if not value:
        return ""
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cap_words(text, limit, min_keep):
    words = text.split()
    if len(words) <= limit:
        return " ".join(words)
    cut = " ".join(words[:limit])
    if cut.endswith((".", "?", "!")):
        return cut
    last = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    if last != -1 and len(cut[:last + 1].split()) >= min_keep:
        return cut[:last + 1]
    return cut


def strip_dateline(paragraph):
    for pattern in DATELINES:
        m = pattern.match(paragraph)
        if m and len(paragraph[m.end():].split()) >= 4:
            return paragraph[m.end():].strip()
    return paragraph


def is_boilerplate(paragraph):
    words = paragraph.split()
    if len(words) < 5 or BOILER_LINE.match(paragraph):
        return True
    return bool(BYLINE.match(paragraph)) and len(words) <= 12   # "By Name Surname", not "By Sunday, the..."


def build_lede(text):
    kept = []
    for para in (p.strip() for p in text.split("\n")):
        if not para or is_boilerplate(para):
            continue
        kept.append(strip_dateline(para) if not kept else para)
        if len(kept) == LEDE_PARAS:
            break
    return cap_words(" ".join(kept), LEDE_WORDS, LEDE_MIN_KEEP)


def agency_hint(text):
    return sorted(set(AGENCIES.findall(text[:400] + " " + text[-400:])))


def norm_hash(text, max_words=None):
    words = re.sub(r"[^a-z0-9 ]", "", text.lower()).split()
    if max_words:
        words = words[:max_words]
    return hashlib.sha1(" ".join(words).encode()).hexdigest()[:16]


def canonical(url):
    p = urlparse(url)
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query) if not TRACKING.match(k)))
    return urlunparse((p.scheme, host, p.path.rstrip("/"), "", query, ""))


def is_live(url, title):
    return bool(LIVE_URL.search(url) or LIVE_TITLE.match(title))


class Robots:
    """robots.txt policy per host. Anything we cannot verify counts as disallowed for this run."""

    def __init__(self, fetcher):
        self.fetcher = fetcher
        self.cache = {}

    def _load(self, base):
        res = self.fetcher.fetch(base + "/robots.txt", accept="text/plain,*/*;q=0.5", require_html=False)
        if res.status in (401, 403):
            return "disallow"
        if 400 <= res.status < 500:
            return "allow"
        if res.error or res.status != 200:
            return "disallow"
        rp = RobotFileParser()
        rp.parse(res.body.decode("utf-8", "replace").splitlines())
        return rp

    def _policy(self, url):
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self.cache:
            self.cache[base] = self._load(base)
        return self.cache[base]

    def allowed(self, url):
        policy = self._policy(url)
        if policy == "allow":
            return True
        if policy == "disallow":
            return False
        return policy.can_fetch(sf.ROBOT_TOKEN, url)

    def crawl_delay(self, url):
        policy = self._policy(url)
        if isinstance(policy, RobotFileParser):
            return policy.crawl_delay(sf.ROBOT_TOKEN) or 0
        return 0


class Collector:
    def __init__(self, fetcher=None, delay=1.0, max_failures=5):
        self.fetcher = fetcher or sf.Fetcher()
        self.robots = Robots(self.fetcher)
        self.delay = delay
        self.max_failures = max_failures
        self.last_hit = {}
        self.failures = Counter()

    def _wait(self, domain, url):
        gap = max(self.delay, self.robots.crawl_delay(url))
        wait = self.last_hit.get(domain, 0) + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last_hit[domain] = time.monotonic()

    def process(self, row):
        """Fetch the page and fill the lede fields."""
        if self.failures[row["domain"]] >= self.max_failures:
            row["lede_status"] = "domain_skipped"
            return row
        if not self.robots.allowed(row["url"]):
            row["lede_status"] = "robots_blocked"
            return row
        self._wait(row["domain"], row["url"])
        res = self.fetcher.fetch(row["url"])
        row["http_status"] = res.status
        if res.error:
            row["lede_status"] = "fetch_failed"
            row["fetch_error"] = res.error
            row["fetch_detail"] = res.detail
            blockish = res.status in (403, 429) or res.error in ("network_error", "too_large") or res.status >= 500
            self.failures[row["domain"]] = self.failures[row["domain"]] + 1 if blockish else 0
            return row
        self.failures[row["domain"]] = 0
        if row.get("origin") == "manual":
            meta = extract_meta(res.body)
            row["title"] = row["title"] or meta["title"]
            row["standfirst"] = cap_words(meta["description"], STANDFIRST_WORDS, STANDFIRST_MIN_KEEP)
            row["published_utc"] = row["published_utc"] or to_utc_iso(meta["date"])
            if not row["title"]:
                row["lede_status"] = "extract_failed"
                return row
        text = extract_text(res.body)
        if not text:
            row["lede_status"] = "extract_failed"
            return row
        row["lede"] = build_lede(text)
        row["lede_words"] = len(row["lede"].split())
        row["agency_hint"] = agency_hint(text)
        row["lede_hash"] = norm_hash(row["lede"], 60)
        if is_live(row["url"], row["title"]):
            row["lede_status"] = "live_blog"
        elif row["lede_words"] < MIN_OK_WORDS:
            row["lede_status"] = "too_short"
        else:
            row["lede_status"] = "ok"
        return row


def extract_meta(body):
    """Title, description and date from the page itself (used for one-off URLs that have no feed entry)."""
    import trafilatura
    doc = trafilatura.extract_metadata(body)
    if doc is None:
        return {"title": "", "description": "", "date": ""}
    return {"title": (doc.title or "").strip(), "description": (doc.description or "").strip(),
            "date": (doc.date or "").strip()}


def extract_text(body):
    import trafilatura
    return trafilatura.extract(body, include_comments=False, include_tables=False, favor_precision=True) or ""


TRANSIENT_ERRORS = {"network_error", "dns_failed"}


def is_transient(row):
    """Failures worth retrying on a later run. Blocked addresses, robots refusals and 4xx stay permanent."""
    if row["lede_status"] == "domain_skipped":
        return True
    return row["lede_status"] == "fetch_failed" and (
        row.get("fetch_error") in TRANSIENT_ERRORS or row.get("http_status") == 429
        or (row.get("http_status") or 0) >= 500)


def load_seen(out_dir):
    """URLs and (domain, title) keys already collected. Corrupt lines are skipped with a warning."""
    urls, titles = set(), set()
    for path in sorted(Path(out_dir).glob("*.jsonl")):
        with open(path, encoding="utf-8-sig") as f:
            for n, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    print(f"  warning: {path.name} line {n} is not valid JSON; ignored")
                    continue
                urls.add(row.get("canonical_url", ""))
                titles.add((row.get("domain", ""), norm_hash(row.get("title", ""))))
    return urls, titles


def new_rows(items, seen_urls, seen_titles, now, stats=None):
    """Rows worth fetching. If a dict is passed as stats it is filled with per-feed outcome counts."""
    rows, skipped = [], Counter()
    for it in items:
        reason = aa.reject_reason(it, need_snippet=False)
        cu = canonical(it["url"])
        key = (it["domain"], norm_hash(it["title"]))
        if not reason and (cu in seen_urls or key in seen_titles):
            reason = "duplicate"
        if stats is not None:
            stats.setdefault(it["outlet"], Counter())[reason or "usable"] += 1
        if reason:
            skipped[reason] += 1
            continue
        seen_urls.add(cu)
        seen_titles.add(key)
        rows.append({
            "url": it["url"], "canonical_url": cu, "domain": it["domain"], "feed": it["outlet"],
            "category": it["category"], "type_hint": it["type_hint"],
            "published_utc": to_utc_iso(it["published"]), "retrieved_at": now, "title": it["title"],
            "standfirst": cap_words(it["snippet"], STANDFIRST_WORDS, STANDFIRST_MIN_KEEP),
            "lede": "", "lede_words": 0, "lede_status": "not_fetched", "http_status": None,
            "fetch_error": "", "fetch_detail": "", "agency_hint": [], "lede_hash": "", "origin": "rss"})
    return rows, skipped


def interleave(rows):
    """Round-robin across domains, so a small trial run touches many outlets instead of just the first feed."""
    buckets = {}
    for r in rows:
        buckets.setdefault(r["domain"], []).append(r)
    ordered = []
    while any(buckets.values()):
        for domain in buckets:
            if buckets[domain]:
                ordered.append(buckets[domain].pop(0))
    return ordered


def print_feed_report(stats, items):
    print("\nper feed (items read, usable, rejected):")
    for feed, counts in stats.items():
        total = sum(counts.values())
        rejected = {k: v for k, v in counts.items() if k != "usable"}
        flag = "   <-- check this feed" if counts.get("usable", 0) == 0 else ""
        print(f"  {feed:<32} {total:>3} read, {counts.get('usable', 0):>3} usable  {rejected or ''}{flag}")
    off = Counter(it["domain"] for it in items if aa.reject_reason(it, need_snippet=False) == "off_target")
    if off:
        print("most common off-target domains (add an outlet to TARGETS in api_audit.py if one belongs):")
        for domain, n in off.most_common(8):
            print(f"  {domain}: {n}")


def manual_rows(urls, seen_urls, now):
    """Rows for articles chosen by hand. No feed filters apply; the fetch guards and robots.txt still do."""
    rows, skipped = [], Counter()
    for url in urls:
        cu = canonical(url)
        if cu in seen_urls:
            skipped["duplicate"] += 1
            continue
        seen_urls.add(cu)
        rows.append({
            "url": url, "canonical_url": cu, "domain": aa.domain_of(url), "feed": "manual", "category": "",
            "type_hint": "opinion" if aa.OPINION_HINTS.search(urlparse(url).path) else "",
            "published_utc": "", "retrieved_at": now, "title": "", "standfirst": "",
            "lede": "", "lede_words": 0, "lede_status": "not_fetched", "http_status": None,
            "fetch_error": "", "fetch_detail": "", "agency_hint": [], "lede_hash": "", "origin": "manual"})
    return rows, skipped


def read_url_list(path):
    return [ln.strip() for ln in Path(path).read_text(encoding="utf-8-sig").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def run(args, collector=None):
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    seen_urls, seen_titles = load_seen(out_dir)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    urls_file = getattr(args, "urls_file", None)
    manual = list(getattr(args, "url", None) or []) + (read_url_list(urls_file) if urls_file else [])
    if manual:
        items = manual
        rows, skipped = manual_rows(manual, seen_urls, now)
    else:
        print(f"reading feeds from {args.feeds}...")
        items = aa.fetch_rss(args.feeds, limit=args.max_per_feed)
        stats = {}
        rows, skipped = new_rows(items, seen_urls, seen_titles, now, stats)
        print_feed_report(stats, items)
    if args.no_fetch:
        print(f"\ndry run: {len(items)} items, {len(rows)} would be collected; nothing fetched or written")
        print("skipped before fetching:", dict(skipped))
        return []
    if args.limit:
        rows = interleave(rows)[:args.limit]
    collector = collector or Collector(delay=args.delay, max_failures=args.max_failures)
    out_path = out_dir / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    written, retry_later = [], []
    try:
        with open(out_path, "a", encoding="utf-8") as f:
            for i, row in enumerate(rows, 1):
                collector.process(row)
                if is_transient(row):
                    retry_later.append(row)
                else:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    f.flush()
                    written.append(row)
                if i % 10 == 0:
                    print(f"  processed {i} of {len(rows)}...")
    except KeyboardInterrupt:
        print("\ninterrupted; rows finished so far are already saved")
    print(f"\nitems read: {len(items)}; rows written: {len(written)} to {out_path}")
    print("skipped before fetching:", dict(skipped))
    print("lede status:", dict(Counter(r["lede_status"] for r in written)))
    if retry_later:
        print(f"{len(retry_later)} rows hit temporary errors and were NOT saved; the next run retries them")
    by_domain = {}
    for r in written:
        by_domain.setdefault(r["domain"], Counter())[r["lede_status"]] += 1
    for d, c in sorted(by_domain.items()):
        print(f"  {d}: {dict(c)}")
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feeds", default="rss_feeds.txt")
    ap.add_argument("--url", action="append", help="collect this one article instead of reading feeds; repeatable")
    ap.add_argument("--urls-file", help="file with one article URL per line, collected instead of reading feeds")
    ap.add_argument("--out-dir", default="data/raw")
    ap.add_argument("--max-per-feed", type=int, default=30)
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests to one domain")
    ap.add_argument("--limit", type=int, default=0, help="process at most this many new articles (0 = all)")
    ap.add_argument("--max-failures", type=int, default=5, help="consecutive failures before a domain is skipped")
    ap.add_argument("--no-fetch", action="store_true", help="dry run: read feeds only, fetch and write nothing")
    args = ap.parse_args()
    if not args.no_fetch:
        if importlib.util.find_spec("trafilatura") is None:
            sys.exit("trafilatura is not installed. Run: pip install -r requirements.txt")
    if not (args.url or args.urls_file) and not Path(args.feeds).is_file():
        sys.exit(f"feed list not found: {args.feeds}")
    run(args)


if __name__ == "__main__":
    main()
