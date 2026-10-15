import gzip
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import safe_fetch as sf


def fake_resolver(ip):
    def resolve(host, port, proto=0):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    return resolve


@pytest.mark.parametrize("url,expected", [
    ("file:///etc/passwd", "blocked_scheme"),
    ("ftp://example.com/x", "blocked_scheme"),
    ("gopher://example.com/", "blocked_scheme"),
    ("http://example.com:8080/x", "blocked_port"),
    ("http://user:pw@example.com/x", "blocked_credentials"),
    ("http:///nohost", "bad_url"),
    ("", "blocked_scheme"),
])
def test_check_url_rejects_unsafe_shapes(url, expected):
    assert sf.check_url(url, resolver=fake_resolver("93.184.216.34")) == expected


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "192.168.0.5", "172.16.9.9", "169.254.169.254",
                                "0.0.0.0", "::1", "fe80::1", "::ffff:127.0.0.1", "fc00::1"])
def test_check_url_blocks_non_public_addresses(ip):
    assert sf.check_url("https://news.example/x", resolver=fake_resolver(ip)) == "blocked_address"


def test_check_url_allows_public_address():
    assert sf.check_url("https://news.example/x", resolver=fake_resolver("93.184.216.34")) == ""


def test_check_url_blocks_if_any_resolved_address_is_private():
    def mixed(host, port, proto=0):
        return [(socket.AF_INET, 1, 6, "", ("93.184.216.34", port)), (socket.AF_INET, 1, 6, "", ("10.0.0.1", port))]
    assert sf.check_url("https://news.example/x", resolver=mixed) == "blocked_address"


def test_check_url_reports_dns_failure():
    def boom(host, port, proto=0):
        raise socket.gaierror("no such host")
    assert sf.check_url("https://nope.invalid/x", resolver=boom) == "dns_failed"


# ---- live behaviour against a local server (address check relaxed for 127.0.0.1 only)
class Handler(BaseHandler := BaseHTTPRequestHandler):
    hits = {}

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="text/html", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        Handler.hits[self.path] = Handler.hits.get(self.path, 0) + 1
        n = Handler.hits[self.path]
        if self.path == "/ok":
            self._send(200, b"<html>hello</html>")
        elif self.path == "/gzip":
            self._send(200, gzip.compress(b"<html>zipped</html>"), headers={"Content-Encoding": "gzip"})
        elif self.path == "/bomb":
            self._send(200, gzip.compress(b"a" * 5_000_000), headers={"Content-Encoding": "gzip"})
        elif self.path == "/big":
            self._send(200, b"x" * 2_000)
        elif self.path == "/pdf":
            self._send(200, b"%PDF", ctype="application/pdf")
        elif self.path == "/flaky":
            self._send(503) if n < 3 else self._send(200, b"<html>finally</html>")
        elif self.path == "/limited":
            self._send(429, headers={"Retry-After": "7"})
        elif self.path == "/forbidden":
            self._send(403)
        elif self.path == "/cookie":
            if "session=1" in (self.headers.get("Cookie") or ""):
                self._send(200, b"<html>with cookie</html>")
            else:
                self._send(302, headers={"Set-Cookie": "session=1", "Location": "/cookie"})
        elif self.path == "/to-internal":
            self._send(302, headers={"Location": "http://10.0.0.5/admin"})
        elif self.path == "/to-file":
            self._send(302, headers={"Location": "file:///etc/passwd"})
        else:
            self._send(404)


@pytest.fixture(scope="module")
def server():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture
def fetcher(monkeypatch):
    real = sf.check_url
    monkeypatch.setattr(sf, "check_url", lambda url, **kw: "" if url.startswith("http://127.0.0.1") else real(url, **kw))
    sleeps = []
    f = sf.Fetcher(max_bytes=1_000, sleep=sleeps.append, use_env_proxy=False)
    f.sleeps = sleeps
    return f


def test_fetches_html(server, fetcher):
    res = fetcher.fetch(server + "/ok")
    assert res.ok and res.body == b"<html>hello</html>" and res.content_type == "text/html"


def test_decompresses_gzip(server, fetcher):
    assert fetcher.fetch(server + "/gzip").body == b"<html>zipped</html>"


def test_gzip_bomb_is_capped(server, fetcher):
    assert fetcher.fetch(server + "/bomb").error == "too_large"


def test_oversized_body_is_rejected(server, fetcher):
    assert fetcher.fetch(server + "/big").error == "too_large"


def test_non_html_rejected_unless_allowed(server, fetcher):
    assert fetcher.fetch(server + "/pdf").error == "not_html"
    assert fetcher.fetch(server + "/pdf", require_html=False).ok


def test_retries_transient_errors_with_backoff(server, fetcher):
    res = fetcher.fetch(server + "/flaky")
    assert res.ok and fetcher.sleeps == [1.0, 3.0]


def test_honours_retry_after_and_gives_up(server, fetcher):
    res = fetcher.fetch(server + "/limited")
    assert res.status == 429 and fetcher.sleeps == [7.0, 7.0]


def test_does_not_retry_403(server, fetcher):
    res = fetcher.fetch(server + "/forbidden")
    assert res.error == "http_403" and fetcher.sleeps == []


def test_cookie_redirect_loop_resolves(server, fetcher):
    assert fetcher.fetch(server + "/cookie").body == b"<html>with cookie</html>"


def test_redirect_to_private_address_is_blocked(server, fetcher):
    assert fetcher.fetch(server + "/to-internal").error == "blocked_redirect:blocked_address"


def test_redirect_to_file_scheme_is_blocked(server, fetcher):
    assert fetcher.fetch(server + "/to-file").error == "blocked_redirect:blocked_scheme"


def test_loopback_is_blocked_without_the_test_override():
    assert sf.Fetcher(use_env_proxy=False).fetch("http://127.0.0.1/ok").error == "blocked_address"
    assert sf.Fetcher(use_env_proxy=False).fetch("http://localhost/ok").error == "blocked_address"
