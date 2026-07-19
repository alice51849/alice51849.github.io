#!/usr/bin/env python3
"""Verify mature Atom entries reached the public Bridgy Bluesky profile."""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import bridgy_feed as feed


BLUESKY_HANDLE = "alice51849.github.io.web.brid.gy"
BLUESKY_API = (
    "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?"
    + urllib.parse.urlencode({"actor": BLUESKY_HANDLE, "limit": 100})
)
DELIVERY_GRACE = dt.timedelta(hours=18)
GUIDE_PATH_RE = re.compile(r"^/ios-app-guide/guides/[a-z0-9-]+\.html$")
BRIDGY_QUERY_RE = re.compile(
    r"^bridgy=\d{4}-\d{2}-\d{2}(?:-(?:00|06|12|18))?$"
)


class DeliveryError(RuntimeError):
    """A mature feed entry is missing from the public bridge."""


def _utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("delivery check time must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


def _published(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DeliveryError(f"Atom entry has an invalid published time: {value}") from error
    return _utc(parsed)


def _entry_url(entry: ET.Element) -> str:
    links = [
        link.attrib.get("href", "")
        for link in entry.findall(f"{{{feed.ATOM}}}link")
        if link.attrib.get("rel") == "alternate"
        and link.attrib.get("type") == "text/html"
    ]
    if len(links) != 1:
        raise DeliveryError("Atom entry must have one HTML alternate URL")
    url = links[0]
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "alice51849.github.io"
        or not GUIDE_PATH_RE.fullmatch(parsed.path)
        or not BRIDGY_QUERY_RE.fullmatch(parsed.query)
        or parsed.fragment
    ):
        raise DeliveryError(f"Atom entry has an invalid bridge URL: {url}")
    return url


def expected_deliveries(
    content: bytes,
    *,
    now: dt.datetime,
) -> set[str]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise DeliveryError(f"Atom feed is invalid: {error}") from error
    entries = root.findall(f"{{{feed.ATOM}}}entry")
    if not 1 <= len(entries) <= feed.FEED_ENTRY_LIMIT:
        raise DeliveryError(
            f"Atom feed has {len(entries)} entries; "
            f"expected 1-{feed.FEED_ENTRY_LIMIT}"
        )
    cutoff = _utc(now) - DELIVERY_GRACE
    expected = set()
    for entry in entries:
        published = entry.findtext(f"{{{feed.ATOM}}}published")
        if not isinstance(published, str):
            raise DeliveryError("Atom entry is missing its published time")
        url = _entry_url(entry)
        if _published(published) <= cutoff:
            expected.add(url)
    return expected


def delivered_urls(payload: object) -> set[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("feed"), list):
        raise DeliveryError("Bluesky author feed has an invalid structure")
    delivered = set()
    for item in payload["feed"]:
        if not isinstance(item, dict):
            continue
        post = item.get("post")
        record = post.get("record") if isinstance(post, dict) else None
        url = record.get("bridgyOriginalUrl") if isinstance(record, dict) else None
        if isinstance(url, str):
            delivered.add(url)
    return delivered


def fetch_deliveries(*, opener=None, sleeper=None) -> set[str]:
    request = urllib.request.Request(
        BLUESKY_API,
        headers={"Accept": "application/json", "User-Agent": feed.USER_AGENT},
    )
    raw = feed.request_bytes(
        request,
        label="Public Bridgy Bluesky feed",
        opener=opener,
        sleeper=sleeper,
    )
    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise DeliveryError("Bluesky author feed returned invalid JSON") from error
    return delivered_urls(payload)


def run(
    *,
    now: dt.datetime | None = None,
    feed_path: pathlib.Path = feed.FEED_PATH,
    opener=None,
    sleeper=None,
) -> int:
    now = dt.datetime.now(dt.timezone.utc) if now is None else now
    expected = expected_deliveries(feed_path.read_bytes(), now=now)
    if not expected:
        print("Bridgy delivery: no entries are old enough to verify")
        return 0
    delivered = fetch_deliveries(opener=opener, sleeper=sleeper)
    missing = sorted(expected - delivered)
    if missing:
        raise DeliveryError(
            "Public Bluesky bridge is missing mature feed entries: "
            + ", ".join(missing)
        )
    print(f"Bridgy delivery: confirmed={len(expected)}")
    return len(expected)


def main() -> int:
    try:
        run()
        return 0
    except (
        DeliveryError,
        feed.RequestError,
        OSError,
        ValueError,
    ) as error:
        print(f"Bridgy delivery check failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
