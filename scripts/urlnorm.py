"""One definition of 'the same article URL', shared by the collector, stub generator and validator."""
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|igshid|ref|ito|cmpid|mc_cid|mc_eid)$", re.I)


def canonical(url):
    """Lowercase host without www, no fragment or trailing slash, tracking parameters removed."""
    p = urlparse(url)
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query) if not TRACKING.match(k)))
    return urlunparse((p.scheme, host, p.path.rstrip("/"), "", query, ""))
