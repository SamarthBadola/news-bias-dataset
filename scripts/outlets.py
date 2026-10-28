"""The allowed-outlet list, kept in outlets.txt so it can change without touching code.

    python scripts/outlets.py list
    python scripts/outlets.py add "Newslaundry" https://www.newslaundry.com/some/article

An article is accepted by the collector, the stub generator and the validator only when its host is on this list.
`add` takes a plain host or a full article URL and writes the clean host. Commit outlets.txt on its own.
"""
import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "outlets.txt"
HOST = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")


class OutletsError(ValueError):
    pass


def normalize_host(text):
    """'https://www.Example.com/a/b?x=1' and 'example.com' both become 'example.com'."""
    value = text.strip().lower()
    if "://" not in value:
        value = "//" + value
    host = (urlparse(value).hostname or "")
    host = host[4:] if host.startswith("www.") else host
    if not HOST.fullmatch(host):
        raise OutletsError(f"'{text}' is not a usable host name")
    return host


def load(path=DEFAULT_PATH):
    """Return {name: host}, in file order. Malformed lines and duplicates are errors with line numbers."""
    outlets, hosts = {}, {}
    for n, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, raw = (part.strip() for part in line.partition("|"))
        if not sep or not name or not raw:
            raise OutletsError(f"{path} line {n}: expected 'Name | host', got '{line}'")
        try:
            host = normalize_host(raw)
        except OutletsError as e:
            raise OutletsError(f"{path} line {n}: {e}") from None
        if name in outlets:
            raise OutletsError(f"{path} line {n}: the name '{name}' is listed twice")
        if host in hosts:
            raise OutletsError(f"{path} line {n}: {host} is already listed as '{hosts[host]}'")
        outlets[name] = host
        hosts[host] = name
    if not outlets:
        raise OutletsError(f"{path} lists no outlets")
    return outlets


def add(name, host_or_url, path=DEFAULT_PATH):
    """Append an outlet. Returns the clean host."""
    name = name.strip()
    if not name or "|" in name:
        raise OutletsError("the outlet name must be non-empty and must not contain '|'")
    host = normalize_host(host_or_url)
    current = load(path)
    if name in current:
        raise OutletsError(f"the name '{name}' is already listed ({current[name]})")
    for existing_name, existing_host in current.items():
        if existing_host == host:
            raise OutletsError(f"{host} is already listed as '{existing_name}'")
    text = Path(path).read_text(encoding="utf-8")
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(("" if text.endswith("\n") else "\n") + f"{name} | {host}\n")
    return host


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=str(DEFAULT_PATH))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a = sub.add_parser("add")
    a.add_argument("name")
    a.add_argument("host_or_url")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "list":
            for name, host in load(args.file).items():
                print(f"{name:<24} {host}")
            return 0
        host = add(args.name, args.host_or_url, args.file)
    except OutletsError as e:
        print(f"error: {e}")
        return 1
    print(f"added {args.name} ({host}). Commit outlets.txt on its own, for example: chore: allow {args.name} articles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
