#!/usr/bin/env python3
"""Generate a one-entry Atom feed for Bridgy Fed from the live app registry."""

from __future__ import annotations

import datetime as dt
import http.client
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


BASE_DATE = dt.date(2026, 7, 12)
SITE = "https://alice51849.github.io"
GUIDE_SITE = f"{SITE}/ios-app-guide"
LINKSET_URL = f"{GUIDE_SITE}/linkset.json"
FEED_URL = f"{SITE}/bridgy-feed.xml"
USER_AGENT = (
    "LumiStudioBridgyFeed/1.0 "
    "(+https://github.com/alice51849/alice51849.github.io)"
)
ATOM = "http://www.w3.org/2005/Atom"
MAX_POST_LENGTH = 300
SLUG_RE = re.compile(r"^[a-z0-9-]+$")
ROOT = pathlib.Path(__file__).resolve().parents[2]
FEED_PATH = ROOT / "bridgy-feed.xml"
ET.register_namespace("", ATOM)


class RequestError(RuntimeError):
    """A remote request failed or returned unusable data."""


def _error_body(error: urllib.error.HTTPError) -> str:
    try:
        raw = error.read(2048)
    except Exception:
        return ""
    finally:
        error.close()
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace").strip()
    return str(raw).strip()


def request_bytes(
    request: urllib.request.Request,
    *,
    label: str,
    timeout: int = 30,
    attempts: int = 3,
    opener=None,
    sleeper=None,
    retry_delays: tuple[int, ...] = (10, 30),
) -> bytes:
    if attempts < 1:
        raise ValueError("attempts must be positive")
    opener = urllib.request.urlopen if opener is None else opener
    sleeper = time.sleep if sleeper is None else sleeper
    for attempt in range(attempts):
        try:
            with opener(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            body = _error_body(error)
            transient = error.code in {408, 429} or 500 <= error.code <= 599
            if not transient:
                raise RequestError(
                    f"{label} failed: HTTP {error.code}: {body[:200]}"
                ) from error
            if attempt == attempts - 1:
                raise RequestError(
                    f"{label} failed after {attempts} attempts: "
                    f"HTTP {error.code}: {body[:200]}"
                ) from error
            delay = retry_delays[min(attempt, len(retry_delays) - 1)]
            print(
                f"{label}: transient HTTP {error.code}; retrying in {delay}s",
                file=sys.stderr,
            )
            sleeper(delay)
        except (
            urllib.error.URLError,
            OSError,
            http.client.HTTPException,
        ) as error:
            if attempt == attempts - 1:
                raise RequestError(
                    f"{label} failed after {attempts} attempts: {error}"
                ) from error
            delay = retry_delays[min(attempt, len(retry_delays) - 1)]
            print(
                f"{label}: transient {type(error).__name__}; retrying in {delay}s",
                file=sys.stderr,
            )
            sleeper(delay)
    raise RequestError(f"{label} failed unexpectedly")


def _portfolio_entry(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or not isinstance(payload.get("linkset"), list):
        raise ValueError("linkset has an invalid top-level structure")
    anchors = {f"{GUIDE_SITE}/", f"{GUIDE_SITE}/index.html"}
    entries = [
        entry
        for entry in payload["linkset"]
        if isinstance(entry, dict)
        and entry.get("anchor") in anchors
        and isinstance(entry.get("item"), list)
    ]
    if len(entries) != 1:
        raise ValueError("linkset must contain one portfolio guide entry")
    return entries[0]


def _item_title(item: dict[str, object]) -> str:
    titles = item.get("title*")
    if not isinstance(titles, list):
        raise ValueError("live guide is missing title metadata")
    for title in titles:
        if isinstance(title, dict) and isinstance(title.get("value"), str):
            value = title["value"].strip()
            if value:
                return value
    raise ValueError("live guide title is empty")


def parse_candidates(payload: object) -> list[dict[str, str]]:
    entry = _portfolio_entry(payload)
    guide = urllib.parse.urlsplit(GUIDE_SITE)
    prefix = f"{guide.path.rstrip('/')}/guides/"
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in entry["item"]:
        if not isinstance(item, dict) or not isinstance(item.get("href"), str):
            raise ValueError("portfolio guide entry contains an invalid item")
        href = item["href"]
        parsed = urllib.parse.urlsplit(href)
        if (
            parsed.scheme != "https"
            or parsed.netloc != guide.netloc
            or not parsed.path.startswith(prefix)
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"live guide URL is outside the guide site: {href}")
        relative = parsed.path[len(prefix) :]
        if "/" in relative or not relative.endswith(".html"):
            raise ValueError(f"live guide URL has an invalid path: {href}")
        slug = relative[:-5]
        if not SLUG_RE.fullmatch(slug):
            raise ValueError(f"live guide has an invalid slug: {slug}")
        if slug in seen:
            raise ValueError(f"live guide is duplicated: {slug}")
        candidates.append({"slug": slug, "name": _item_title(item), "url": href})
        seen.add(slug)
    if not candidates:
        raise ValueError("linkset contains no live app guides")
    return candidates


def fetch_candidates(*, opener=None, sleeper=None) -> list[dict[str, str]]:
    request = urllib.request.Request(
        LINKSET_URL,
        headers={"Accept": "application/linkset+json", "User-Agent": USER_AGENT},
    )
    raw = request_bytes(
        request,
        label="Live app linkset",
        opener=opener,
        sleeper=sleeper,
    )
    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RequestError("Live app linkset returned invalid JSON") from error
    return parse_candidates(payload)


def select_candidate(
    candidates: list[dict[str, str]],
    *,
    today: dt.date,
) -> dict[str, str]:
    if not candidates:
        raise ValueError("live app guide pool is empty")
    offset = (today - BASE_DATE).days
    if offset < 0:
        raise ValueError(f"feed schedule predates {BASE_DATE.isoformat()}")
    return candidates[offset % len(candidates)]


def validate_guide(
    url: str,
    *,
    opener=None,
    sleeper=None,
) -> None:
    request = urllib.request.Request(
        url,
        headers={"Accept": "text/html", "User-Agent": USER_AGENT},
        method="HEAD",
    )
    request_bytes(
        request,
        label="Selected live app guide",
        opener=opener,
        sleeper=sleeper,
    )


def _node(parent: ET.Element, name: str, text: str, **attributes: str) -> ET.Element:
    element = ET.SubElement(parent, f"{{{ATOM}}}{name}", attributes)
    element.text = text
    return element


def post_content(name: str) -> str:
    content = (
        f"Today's Lumi Studio app guide: {name}. Explore practical use cases "
        "and see whether it fits your needs before visiting the App Store. "
        "#iOSApps #IndieApps"
    )
    if len(content) > MAX_POST_LENGTH:
        raise ValueError(
            f"Bridgy post content is {len(content)} characters; "
            f"maximum is {MAX_POST_LENGTH}"
        )
    return content


def render_feed(candidate: dict[str, str], *, today: dt.date) -> bytes:
    timestamp = f"{today.isoformat()}T00:00:00Z"
    slug = candidate["slug"]
    name = candidate["name"]
    url = candidate["url"]

    feed = ET.Element(f"{{{ATOM}}}feed", {"xml:lang": "en"})
    _node(feed, "id", FEED_URL)
    _node(feed, "title", "Lumi Studio — one independent iOS app guide daily")
    _node(
        feed,
        "subtitle",
        "A low-frequency rotation across every currently public Lumi Studio app.",
    )
    ET.SubElement(
        feed,
        f"{{{ATOM}}}link",
        {"rel": "self", "type": "application/atom+xml", "href": FEED_URL},
    )
    ET.SubElement(
        feed,
        f"{{{ATOM}}}link",
        {"rel": "alternate", "type": "text/html", "href": f"{SITE}/"},
    )
    _node(feed, "updated", timestamp)
    author = ET.SubElement(feed, f"{{{ATOM}}}author")
    _node(author, "name", "Lumi Studio")
    _node(author, "uri", f"{SITE}/")

    entry = ET.SubElement(feed, f"{{{ATOM}}}entry")
    _node(entry, "id", f"tag:alice51849.github.io,{today.year}:bridgy:{today}:{slug}")
    _node(entry, "title", f"{name} — independent iOS app guide")
    ET.SubElement(
        entry,
        f"{{{ATOM}}}link",
        {"rel": "alternate", "type": "text/html", "href": url},
    )
    _node(entry, "published", timestamp)
    _node(entry, "updated", timestamp)
    _node(
        entry,
        "content",
        post_content(name),
        type="text",
    )
    _node(
        entry,
        "summary",
        f"Explore the public guide for {name}, with practical use cases "
        "and a direct App Store link.",
    )
    ET.indent(feed, space="  ")
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True) + b"\n"


def write_feed(content: bytes, *, path: pathlib.Path = FEED_PATH) -> bool:
    try:
        if path.read_bytes() == content:
            return False
    except FileNotFoundError:
        pass
    path.write_bytes(content)
    return True


def run(today: dt.date | None = None) -> bool:
    today = dt.datetime.now(dt.timezone.utc).date() if today is None else today
    candidate = select_candidate(fetch_candidates(), today=today)
    validate_guide(candidate["url"])
    changed = write_feed(render_feed(candidate, today=today))
    print(
        "Bridgy feed:"
        f" {'updated' if changed else 'current'}"
        f" app={candidate['slug']}"
        f" entries=1"
        f" date={today.isoformat()}"
    )
    return changed


def main() -> int:
    try:
        run()
        return 0
    except (RequestError, ValueError, KeyError, OSError) as error:
        print(f"Bridgy feed failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
