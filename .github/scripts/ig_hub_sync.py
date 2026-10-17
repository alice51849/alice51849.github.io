#!/usr/bin/env python3
"""Mirror the Instagram profile-link hub to /ig/ (https://open.cait518.cc/ig/).

Instagram links only from the profile, so the profile link points here. The page is built in the public
ios-app-guide repo (.github/scripts/ig_bio_hub.py) every time an Instagram post is recorded: the apps of the
newest posts first, then every app, each one tap from the App Store. This copies the committed page from
ios-app-guide main (GitHub contents API, no CDN cache) to ig/index.html when it changed, after the same checks
the builder runs: the hub marker, every App Store button with pt=118326163 and ct=ig_bio_<app>, no external
script, frame or form, no plain-http link. A page that fails them is not written (the live page stays) and the
run fails, so a broken build never reaches the profile link.

    python3 .github/scripts/ig_hub_sync.py            # fetch, check, write ig/index.html if changed
    python3 .github/scripts/ig_hub_sync.py --check FILE
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "ig" / "index.html"
SOURCE = ("https://api.github.com/repos/alice51849/ios-app-guide/contents/"
          ".github/growth/ig-hub/index.html?ref=main")
MARKER = '<meta name="lumi-ig-hub" content="1">'
APP_STORE = re.compile(r'href="(https://apps\.apple\.com/[^"]+)"')
GOOD_APP_STORE = re.compile(r"https://apps\.apple\.com/(?:[a-z]{2}/)?app/id\d+\?pt=118326163"
                            r"&amp;ct=ig_bio_[a-z0-9]{1,23}&amp;mt=8")
GOOD_PLAY = re.compile(r"https://play\.google\.com/store/apps/details\?id=[A-Za-z0-9_.]+"
                       r"&amp;referrer=utm_source%3Dig_bio_[a-z0-9]{1,23}%26utm_campaign%3D[a-z0-9_]+")
MIN_APPS = 10
MAX_BYTES = 600_000


def problems(page: str, min_links: int = MIN_APPS) -> list[str]:
    out = []
    if MARKER not in page:
        out.append("the hub marker is missing")
    if not page.lstrip().lower().startswith("<!doctype html>"):
        out.append("not an HTML page")
    if len(page.encode("utf-8")) > MAX_BYTES:
        out.append(f"page is over {MAX_BYTES} bytes")
    stores = APP_STORE.findall(page)
    if len(stores) < min_links:
        out.append(f"only {len(stores)} App Store buttons")
    bad = [u for u in stores if not GOOD_APP_STORE.fullmatch(u)]
    if bad:
        out.append(f"App Store links without pt / ct=ig_bio_<app>: {bad[:3]}")
    plays = re.findall(r'href="(https://play\.google\.com/[^"]+)"', page)
    bad = [u for u in plays if not GOOD_PLAY.fullmatch(u)]
    if bad:
        out.append(f"Google Play links without the ig_bio referrer: {bad[:3]}")
    if re.search(r"<script[^>]+src=|<iframe|<form|<object|<embed|javascript:", page, re.I):
        out.append("external script, frame, form or javascript: link in the page")
    if re.search(r"""(?:href|src)=["']http://""", page, re.I):
        out.append("plain http link")
    for host in re.findall(r"""(?:href|src)=["']https://([^/"']+)""", page):
        if host not in ("apps.apple.com", "play.google.com", "open.cait518.cc") and not host.endswith(".mzstatic.com"):
            out.append(f"link to an unexpected host: {host}")
            break
    return out


def fetch(url: str = SOURCE, token: str | None = None, opener=urllib.request.urlopen) -> str:
    headers = {"Accept": "application/vnd.github.raw", "User-Agent": "lumi-ig-hub-sync/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with opener(urllib.request.Request(url, headers=headers), timeout=30) as resp:
        return resp.read().decode("utf-8")


def sync(page: str, out: Path = OUT) -> bool:
    """Write the page when it differs; True when written. Raises ValueError when it fails the checks."""
    bad = problems(page)
    if bad:
        raise ValueError("; ".join(bad))
    if out.exists() and out.read_text(encoding="utf-8") == page:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", metavar="FILE", help="only check a local page")
    args = ap.parse_args(argv)
    if args.check:
        bad = problems(Path(args.check).read_text(encoding="utf-8"))
        for p in bad:
            print(f"::error::ig hub: {p}")
        return 1 if bad else 0
    try:
        page = fetch(token=os.environ.get("GITHUB_TOKEN") or None)
    except (urllib.error.URLError, OSError) as exc:
        print(f"::error::ig hub: cannot read the hub page from ios-app-guide ({exc})")
        return 1
    try:
        written = sync(page)
    except ValueError as exc:
        print(f"::error::ig hub: the built page fails the checks, the live page stays: {exc}")
        return 1
    stores = len(APP_STORE.findall(page))
    latest = re.search(r'<meta name="lumi-ig-hub-latest" content="([^"]*)">', page)
    print(f"ig hub: {'updated' if written else 'already current'} ig/index.html ({len(page)} bytes, "
          f"{stores} App Store buttons, newest post {latest.group(1) if latest else '-'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
