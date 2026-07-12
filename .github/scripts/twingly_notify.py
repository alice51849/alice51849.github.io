#!/usr/bin/env python3
"""Notify Twingly Blog Search after the public daily Atom feed is deployed."""

from __future__ import annotations

import argparse
import pathlib
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import xmlrpc.client

import pingomatic_notify as common


RPC_URL = "https://rpc.twingly.com/"
GUIDE_PREFIX = "/ios-app-guide/guides/"


def entry_details(content: bytes) -> tuple[str, str]:
    title = common.validate_feed(content)
    root = ET.fromstring(content)
    entry = root.find(f"{{{common.ATOM}}}entry")
    if entry is None:
        raise common.NotifyError("Twingly feed entry is missing")
    links = [
        link
        for link in entry.findall(f"{{{common.ATOM}}}link")
        if link.attrib.get("rel") == "alternate"
        and link.attrib.get("type") == "text/html"
    ]
    if len(links) != 1:
        raise common.NotifyError(
            f"Twingly feed entry has {len(links)} HTML alternate links; expected one"
        )
    url = links[0].attrib.get("href", "")
    parsed = urllib.parse.urlsplit(url)
    site = urllib.parse.urlsplit(common.SITE_URL)
    relative = parsed.path[len(GUIDE_PREFIX) :]
    if (
        parsed.scheme != "https"
        or parsed.netloc != site.netloc
        or not parsed.path.startswith(GUIDE_PREFIX)
        or not relative.endswith(".html")
        or "/" in relative
        or parsed.query
        or parsed.fragment
    ):
        raise common.NotifyError(f"Twingly entry URL is outside the guide site: {url}")
    return title, url


def render_ping_request(entry_url: str) -> bytes:
    return xmlrpc.client.dumps(
        (common.SITE_NAME, common.SITE_URL, entry_url, common.FEED_URL),
        methodname="weblogUpdates.extendedPing",
        allow_none=False,
        encoding="utf-8",
    ).encode("utf-8")


def send_ping(entry_url: str, *, opener=None, timeout: int = 30) -> str:
    return common.post_ping_request(
        RPC_URL,
        render_ping_request(entry_url),
        service="Twingly",
        opener=opener,
        timeout=timeout,
    )


def run(*, feed_path: pathlib.Path = common.FEED_PATH) -> str:
    try:
        expected = feed_path.read_bytes()
    except OSError as error:
        raise common.NotifyError(f"Cannot read local Atom feed: {error}") from error
    title, entry_url = entry_details(expected)
    checks = common.wait_for_live_feed(expected, label="Twingly")
    message = send_ping(entry_url)
    print(
        f"Twingly: accepted entry={title!r} url={entry_url} "
        f"live_checks={checks} message={message!r}"
    )
    return message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--feed-changed",
        action="store_true",
        help="confirm that this invocation follows a persisted feed change",
    )
    args = parser.parse_args(argv)
    if not args.feed_changed:
        print("Twingly refused: --feed-changed is required", file=sys.stderr)
        return 2
    try:
        run()
        return 0
    except (common.NotifyError, ValueError) as error:
        print(f"Twingly failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
