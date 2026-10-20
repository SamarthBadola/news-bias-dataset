"""Hardened HTTP fetching for untrusted URLs (feed links now, user-submitted article URLs in the platform).

Guards:
  * http and https only, ports 80 and 443 only, no credentials in the URL
  * the host must resolve to public addresses only (blocks loopback, private, link-local and
    cloud-metadata ranges), and every redirect hop is re-checked
  * response size is capped, including after gzip decompression
  * content type is checked, transient errors are retried with backoff (Retry-After honoured)
  * cookies persist per Fetcher, so cookie-then-redirect pages do not loop

Not covered: DNS rebinding between the check and the connection. A deployed service should also
filter egress at the network layer.
"""
import http.cookiejar
import ipaddress
import os
import socket
import time
import zlib
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import (HTTPCookieProcessor, HTTPRedirectHandler, ProxyHandler, Request,
                            build_opener)

ROBOT_TOKEN = "NewsBiasResearch"
ALLOWED_PORTS = {None, 80, 443}
RETRY_STATUS = {429, 500, 502, 503, 504}
HTML_TYPES = {"text/html", "application/xhtml+xml"}
MAX_RETRY_AFTER = 30.0


def default_user_agent():
    contact = os.environ.get("COLLECTOR_CONTACT", "").strip()
    suffix = f"; +{contact}" if contact else ""
    return f"Mozilla/5.0 (compatible; {ROBOT_TOKEN}/0.1; university course project{suffix})"


def check_url(url, resolver=socket.getaddrinfo):
    """Return '' if the URL is safe to request, else a short reason code."""
    p = urlparse(url or "")
    if p.scheme not in ("http", "https"):
        return "blocked_scheme"
    if not p.hostname:
        return "bad_url"
    if p.username or p.password:
        return "blocked_credentials"
    try:
        port = p.port
    except ValueError:
        return "bad_url"
    if port not in ALLOWED_PORTS:
        return "blocked_port"
    try:
        infos = resolver(p.hostname, port or (443 if p.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return "dns_failed"
    if not infos:
        return "dns_failed"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            return "blocked_address"
    return ""


@dataclass
class Fetched:
    url: str
    status: int = 0
    body: bytes = b""
    error: str = ""
    content_type: str = ""
    final_url: str = ""
    retry_after: float = 0.0
    detail: str = ""

    @property
    def ok(self):
        return not self.error and 200 <= self.status < 300


class _CheckedRedirect(HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        problem = check_url(target)
        if problem:
            raise HTTPError(target, 403, f"blocked_redirect:{problem}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _parse_retry_after(value):
    try:
        return min(max(float(value), 0.0), MAX_RETRY_AFTER)
    except (TypeError, ValueError):
        return 0.0


class Fetcher:
    def __init__(self, user_agent=None, timeout=30, max_bytes=3_000_000, retries=2,
                 sleep=time.sleep, use_env_proxy=True):
        self.ua = user_agent or default_user_agent()
        self.timeout, self.max_bytes, self.retries, self.sleep = timeout, max_bytes, retries, sleep
        handlers = [HTTPCookieProcessor(http.cookiejar.CookieJar()), _CheckedRedirect()]
        if not use_env_proxy:
            handlers.append(ProxyHandler({}))
        self.opener = build_opener(*handlers)

    def fetch(self, url, accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.5", require_html=True):
        problem = check_url(url)
        if problem:
            return Fetched(url, error=problem)
        result = Fetched(url, error="network_error")
        for attempt in range(self.retries + 1):
            result = self._once(url, accept, require_html)
            retryable = result.status in RETRY_STATUS or result.error == "network_error"
            if not retryable or attempt == self.retries:
                return result
            self.sleep(result.retry_after or 1.0 * 3 ** attempt)
        return result

    def _once(self, url, accept, require_html):
        req = Request(url, headers={"User-Agent": self.ua, "Accept": accept,
                                    "Accept-Language": "en-IN,en;q=0.8", "Accept-Encoding": "gzip"})
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                ctype = resp.headers.get_content_type()
                raw = resp.read(self.max_bytes + 1)
                if len(raw) > self.max_bytes:
                    return Fetched(url, resp.status, error="too_large", content_type=ctype)
                if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                    try:
                        raw = zlib.decompressobj(zlib.MAX_WBITS | 16).decompress(raw, self.max_bytes + 1)
                    except zlib.error:
                        return Fetched(url, resp.status, error="bad_encoding", content_type=ctype)
                    if len(raw) > self.max_bytes:
                        return Fetched(url, resp.status, error="too_large", content_type=ctype)
                if require_html and ctype not in HTML_TYPES:
                    return Fetched(url, resp.status, error="not_html", content_type=ctype)
                return Fetched(url, resp.status, raw, "", ctype, resp.geturl())
        except HTTPError as e:
            reason = str(e.reason)
            if reason.startswith("blocked_redirect"):
                error = reason
            elif "Redirection to url" in reason:   # urllib itself refuses non-http(s)/ftp redirect schemes
                error = "blocked_redirect:blocked_scheme"
            else:
                error = f"http_{e.code}"
            return Fetched(url, e.code, error=error, retry_after=_parse_retry_after(e.headers.get("Retry-After")))
        except (URLError, TimeoutError, OSError) as e:
            reason = getattr(e, "reason", None) or e
            return Fetched(url, error="network_error", detail=f"{type(reason).__name__}: {reason}"[:200])
