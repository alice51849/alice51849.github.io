#!/usr/bin/env python3
"""Generate a bounded Atom feed for Bridgy Fed from the live app registry."""

from __future__ import annotations

import copy
import datetime as dt
import html
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


BASE_SLOT = dt.datetime(2026, 7, 19, 18, tzinfo=dt.timezone.utc)
CADENCE = dt.timedelta(hours=6)
FEED_ENTRY_LIMIT = 8
STATE_VERSION = 1
SITE = "https://alice51849.github.io"
GUIDE_SITE = f"{SITE}/ios-app-guide"
LINKSET_URL = f"{GUIDE_SITE}/linkset.json"
FEED_URL = f"{SITE}/bridgy-feed.xml"
USER_AGENT = (
    "LumiStudioBridgyFeed/1.0 "
    "(+https://github.com/alice51849/alice51849.github.io)"
)
ATOM = "http://www.w3.org/2005/Atom"
ACTIVITY = "http://activitystrea.ms/spec/1.0/"
ACTIVITY_NOTE = "http://activitystrea.ms/schema/1.0/note"
MAX_POST_LENGTH = 300
XML = "http://www.w3.org/XML/1998/namespace"
APP_STORE_PATH_RE = re.compile(r"^/app/id(\d+)$")
POST_TEMPLATES = {
    "en": (
        "Today's Lumi Studio app guide: {name}. {focus}. "
        "Read the guide and see if it fits."
    ),
    "zh-Hant": (
        "今日 Lumi Studio App 指南：{name}。{focus}。"
        "查看指南，判斷是否適合。"
    ),
    "ja": (
        "本日のLumi Studioアプリガイド：{name}。{focus}。"
        "ガイドで自分に合うか確認できます。"
    ),
    "es": (
        "Guía de hoy de Lumi Studio: {name}. {focus}. "
        "Consulta la guía para ver si se adapta a ti."
    ),
}
STORE_TEXT_LINE = {
    "en": "App Store: {url}",
    "zh-Hant": "App Store：{url}",
    "ja": "App Store：{url}",
    "es": "App Store: {url}",
}
DEFAULT_POST_PROFILE = (
    "en",
    "Explore practical use cases before visiting the App Store",
    ("iOSApps", "IndieApps"),
)
POST_PROFILES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "lumibopomofopro": (
        "zh-Hant",
        "用遊戲練習注音符號與拼讀，陪孩子建立熟悉感",
        ("注音符號", "親子學習", "iOSApp"),
    ),
    "lumibopomofo": (
        "zh-Hant",
        "透過遊戲練習注音與拼讀，配合孩子的學習節奏",
        ("注音", "幼兒學習", "iOSApp"),
    ),
    "aim990": (
        "ja",
        "30日学習計画、弱点ドリル、進捗管理でTOEIC L&R対策を組み立てる",
        ("TOEIC", "英語学習", "iPhoneアプリ"),
    ),
    "cvdesk": (
        "en",
        "Build ATS-friendly resumes and compare job-description keyword coverage",
        ("Resume", "ATS", "JobSearch"),
    ),
    "cyca": (
        "es",
        "Registra ciclos, síntomas y tendencias de forma privada en el iPhone",
        ("CicloMenstrual", "Privacidad", "AppsIOS"),
    ),
    "dailymate": (
        "en",
        "Practice complete phrases for real conversations instead of isolated vocabulary",
        ("LanguageLearning", "TravelLanguage", "iOSApps"),
    ),
    "gmoney": (
        "en",
        "Track expenses and convert currencies in a simple offline budgeting flow",
        ("Budgeting", "TravelFinance", "iOSApps"),
    ),
    "hourstag": (
        "zh-Hant",
        "把價格換算成需要工作的時間，讓消費決定更直覺",
        ("理財", "消費習慣", "iOSApp"),
    ),
    "lockhour": (
        "en",
        "Block distracting apps and plan focused sessions when Screen Time is not enough",
        ("Focus", "DigitalWellbeing", "iOSApps"),
    ),
    "lumiletters": (
        "en",
        "Practice ABCs, phonics, and letter tracing through kid-friendly activities",
        ("Phonics", "EarlyLearning", "KidsApps"),
    ),
    "lumiletterspro": (
        "en",
        "Build early letter confidence with phonics, tracing, and playful activities",
        ("Phonics", "PreschoolLearning", "KidsApps"),
    ),
    "lumimath": (
        "en",
        "Practice numbers and early math through a playful space adventure",
        ("EarlyMath", "KidsLearning", "iOSApps"),
    ),
    "lumimathpro": (
        "en",
        "Explore numbers and early math through child-friendly adventure activities",
        ("EarlyMath", "KidsLearning", "iOSApps"),
    ),
    "lumimission": (
        "en",
        "Turn chores and daily routines into clear, kid-friendly missions",
        ("KidsRoutines", "Parenting", "iOSApps"),
    ),
    "lumimissionpro": (
        "en",
        "Help children follow chores, habits, and routines through playful missions",
        ("KidsRoutines", "Parenting", "iOSApps"),
    ),
    "lumiweather": (
        "en",
        "Help children understand weather and choose practical clothing layers",
        ("KidsWeather", "Parenting", "iOSApps"),
    ),
    "mochi": (
        "en",
        "Keep daily tasks approachable with a cozy checklist and satisfying completion flow",
        ("TodoList", "Productivity", "iOSApps"),
    ),
    "photocream": (
        "en",
        "Explore vintage film looks for iPhone photos with a focused editing workflow",
        ("FilmPhotography", "PhotoEditing", "iOSApps"),
    ),
    "picclear": (
        "en",
        "Review duplicate photos, similar shots, and storage-heavy videos privately",
        ("PhotoCleanup", "iPhoneStorage", "iOSApps"),
    ),
    "scanto": (
        "en",
        "Scan paper into PDFs with on-device OCR, searchable text, and private export tools",
        ("DocumentScanner", "OCR", "iOSApps"),
    ),
    "sereno": (
        "en",
        "Mix white noise and sleep sounds with timers and offline playback",
        ("SleepSounds", "WhiteNoise", "iOSApps"),
    ),
    "snapport": (
        "en",
        "Create passport and ID photos at home with size templates and alignment guides",
        ("PassportPhoto", "TravelPrep", "iOSApps"),
    ),
    "sononote": (
        "en",
        "Turn voice notes and meetings into summaries, decisions, and action items",
        ("VoiceNotes", "Productivity", "iOSApps"),
    ),
    "tripbee": (
        "en",
        "Plan day-by-day itineraries with offline access and a clean travel map",
        ("TripPlanning", "TravelApps", "iOSApps"),
    ),
    "tripbeelite": (
        "en",
        "Keep one upcoming trip, bookings, packing, and daily plans in one focused timeline",
        ("TripPlanning", "TravelPrep", "iOSApps"),
    ),
    "tripplanet": (
        "en",
        "Turn long drives and flights into playful observation missions for young children",
        ("FamilyTravel", "KidsActivities", "iOSApps"),
    ),
    "unblurry": (
        "en",
        "Review common blur causes and try realistic fixes for focus, motion, and low light",
        ("PhotoEditing", "iPhonePhotography", "iOSApps"),
    ),
    "wordmate": (
        "en",
        "Build a personal vocabulary collection with focused review across many languages",
        ("Vocabulary", "LanguageLearning", "iOSApps"),
    ),
}
SLUG_RE = re.compile(r"^[a-z0-9-]+$")
ROOT = pathlib.Path(__file__).resolve().parents[2]
FEED_PATH = ROOT / "bridgy-feed.xml"
STATE_PATH = ROOT / ".github" / "bridgy-rotation-state.json"
ET.register_namespace("", ATOM)
ET.register_namespace("activity", ACTIVITY)


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


def _guide_contexts(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    contexts: dict[str, dict[str, object]] = {}
    for entry in payload["linkset"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("anchor"), str):
            continue
        anchor = entry["anchor"]
        if anchor in contexts:
            raise ValueError(f"linkset contains duplicate anchor: {anchor}")
        contexts[anchor] = entry
    return contexts


def _canonical_store_url(href: str) -> str | None:
    parsed = urllib.parse.urlsplit(href)
    if parsed.netloc != "apps.apple.com":
        return None
    match = APP_STORE_PATH_RE.fullmatch(parsed.path)
    if parsed.scheme != "https" or not match or parsed.fragment:
        raise ValueError(f"live guide has an invalid App Store URL: {href}")
    return f"https://apps.apple.com/app/id{match.group(1)}"


def _store_url(context: dict[str, object], guide_url: str) -> str:
    related = context.get("related")
    if not isinstance(related, list):
        raise ValueError(f"live guide has no related App Store link: {guide_url}")
    stores: list[str] = []
    for item in related:
        if not isinstance(item, dict) or not isinstance(item.get("href"), str):
            continue
        href = item["href"]
        store = _canonical_store_url(href)
        if store is not None:
            stores.append(store)
    if len(stores) != 1:
        raise ValueError(
            f"live guide must have exactly one App Store link: {guide_url}"
        )
    return stores[0]


def parse_candidates(payload: object) -> list[dict[str, str]]:
    entry = _portfolio_entry(payload)
    contexts = _guide_contexts(payload)
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
        context = contexts.get(href)
        if context is None:
            raise ValueError(f"live guide has no linkset context: {href}")
        candidates.append(
            {
                "slug": slug,
                "name": _item_title(item),
                "url": href,
                "store_url": _store_url(context, href),
            }
        )
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


def profile_drift(
    candidates: list[dict[str, str]],
) -> tuple[list[str], list[str]]:
    live_slugs = {candidate["slug"] for candidate in candidates}
    profiles = set(POST_PROFILES)
    return sorted(live_slugs - profiles), sorted(profiles - live_slugs)


def warn_profile_drift(candidates: list[dict[str, str]]) -> None:
    missing, stale = profile_drift(candidates)
    if missing or stale:
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if stale:
            details.append("stale=" + ",".join(stale))
        print(
            "Bridgy profile coverage drifted; using safe defaults: "
            + " ".join(details),
            file=sys.stderr,
        )


def publishing_slot(now: dt.datetime) -> dt.datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("feed time must be timezone-aware")
    now = now.astimezone(dt.timezone.utc)
    return now.replace(
        hour=(now.hour // 6) * 6,
        minute=0,
        second=0,
        microsecond=0,
    )
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


def post_profile(slug: str) -> tuple[str, str, tuple[str, ...]]:
    return POST_PROFILES.get(slug, DEFAULT_POST_PROFILE)


def post_intro(slug: str, name: str) -> str:
    locale, focus, _hashtags = post_profile(slug)
    return POST_TEMPLATES[locale].format(name=name, focus=focus)


def post_text(slug: str, name: str, store_url: str) -> str:
    locale, _focus, hashtags = post_profile(slug)
    store_url = _canonical_store_url(store_url)
    if store_url is None:
        raise ValueError(f"post has an invalid App Store URL: {slug}")
    text = (
        f"{post_intro(slug, name)} "
        f"{' '.join(f'#{tag}' for tag in hashtags)}\n"
        f"{STORE_TEXT_LINE[locale].format(url=store_url)}"
    )
    if len(text) > MAX_POST_LENGTH:
        raise ValueError(
            f"Bridgy post content is {len(text)} characters; "
            f"maximum is {MAX_POST_LENGTH}"
        )
    return text


def post_content(slug: str, name: str, store_url: str) -> str:
    locale, _focus, hashtags = post_profile(slug)
    post_text(slug, name, store_url)
    store_url = _canonical_store_url(store_url)
    if store_url is None:
        raise ValueError(f"post has an invalid App Store URL: {slug}")
    links = " ".join(
        f'<a href="https://bsky.app/hashtag/{urllib.parse.quote(tag, safe="")}">'
        f"#{html.escape(tag)}</a>"
        for tag in hashtags
    )
    store_link = (
        f'<a href="{html.escape(store_url, quote=True)}">'
        f"{html.escape(store_url)}</a>"
    )
    store_line = STORE_TEXT_LINE[locale].format(url=store_link)
    return (
        f"<p>{html.escape(post_intro(slug, name))} {links}"
        f"<br>{store_line}</p>"
    )


def post_url(url: str, *, slot: dt.datetime) -> str:
    token = publishing_slot(slot).strftime("%Y-%m-%d-%H")
    return f"{url}?bridgy={token}"


def _timestamp(slot: dt.datetime) -> str:
    return publishing_slot(slot).isoformat().replace("+00:00", "Z")


def _render_entry(
    feed: ET.Element,
    candidate: dict[str, str],
    *,
    slot: dt.datetime,
) -> ET.Element:
    timestamp = _timestamp(slot)
    slug = candidate["slug"]
    name = candidate["name"]
    url = post_url(candidate["url"], slot=slot)
    store_url = candidate["store_url"]

    entry = ET.SubElement(feed, f"{{{ATOM}}}entry")
    _node(
        entry,
        "id",
        f"tag:alice51849.github.io,{slot.year}:bridgy:"
        f"{publishing_slot(slot).strftime('%Y-%m-%dT%H')}",
    )
    _node(entry, "title", f"{name} — independent iOS app guide")
    object_type = ET.SubElement(entry, f"{{{ACTIVITY}}}object-type")
    object_type.text = ACTIVITY_NOTE
    ET.SubElement(
        entry,
        f"{{{ATOM}}}link",
        {"rel": "alternate", "type": "text/html", "href": url},
    )
    ET.SubElement(
        entry,
        f"{{{ATOM}}}link",
        {
            "rel": "related",
            "type": "text/html",
            "href": store_url,
            "title": f"{name} on the App Store",
        },
    )
    _node(entry, "published", timestamp)
    _node(entry, "updated", timestamp)
    content = _node(
        entry,
        "content",
        post_content(slug, name, store_url),
        type="html",
    )
    locale, _focus, _hashtags = post_profile(slug)
    content.set(f"{{{XML}}}lang", locale)
    summary = _node(
        entry,
        "summary",
        post_text(slug, name, store_url),
    )
    summary.set(f"{{{XML}}}lang", locale)
    return entry


def _parse_timestamp(value: str, *, label: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} has an invalid timestamp: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} timestamp must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def _required_text(entry: ET.Element, name: str) -> str:
    node = entry.find(f"{{{ATOM}}}{name}")
    if node is None or not (node.text or "").strip():
        raise ValueError(f"existing Bridgy entry is missing {name}")
    return (node.text or "").strip()


def _entry_published(entry: ET.Element) -> dt.datetime:
    return _parse_timestamp(
        _required_text(entry, "published"),
        label="existing Bridgy entry",
    )


def _entry_slug(entry: ET.Element) -> str:
    links = [
        node.get("href", "")
        for node in entry.findall(f"{{{ATOM}}}link")
        if node.get("rel") == "alternate"
    ]
    if len(links) != 1:
        raise ValueError(
            "existing Bridgy entry must have exactly one alternate link"
        )
    parsed = urllib.parse.urlparse(links[0])
    if (
        parsed.scheme != "https"
        or parsed.netloc != "alice51849.github.io"
        or not parsed.path.startswith("/ios-app-guide/")
        or not parsed.path.endswith(".html")
    ):
        raise ValueError("existing Bridgy entry has an invalid guide URL")
    slug = pathlib.PurePosixPath(parsed.path).stem
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ValueError("existing Bridgy entry has an invalid app slug")
    return slug


def parse_feed_entries(content: bytes) -> list[ET.Element]:
    if not content:
        return []
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise ValueError("existing Bridgy feed is invalid XML") from error
    if root.tag != f"{{{ATOM}}}feed":
        raise ValueError("existing Bridgy feed has an invalid root element")
    entries = list(root.findall(f"{{{ATOM}}}entry"))
    if len(entries) > FEED_ENTRY_LIMIT:
        raise ValueError("existing Bridgy feed exceeds the entry limit")

    ids: set[str] = set()
    published: set[dt.datetime] = set()
    for entry in entries:
        entry_id = _required_text(entry, "id")
        timestamp = _entry_published(entry)
        _entry_slug(entry)
        if entry_id in ids:
            raise ValueError("existing Bridgy feed has duplicate entry IDs")
        if timestamp in published:
            raise ValueError(
                "existing Bridgy feed has duplicate published timestamps"
            )
        ids.add(entry_id)
        published.add(timestamp)
    return sorted(entries, key=_entry_published, reverse=True)


def _render_feed_entries(entries: list[ET.Element]) -> bytes:
    if not entries:
        raise ValueError("Bridgy feed cannot be empty")
    entries = sorted(entries, key=_entry_published, reverse=True)[
        :FEED_ENTRY_LIMIT
    ]
    feed = ET.Element(f"{{{ATOM}}}feed", {"xml:lang": "en"})
    _node(feed, "id", FEED_URL)
    _node(feed, "title", "Lumi Studio — independent iOS app guides")
    _node(
        feed,
        "subtitle",
        "A six-hour high-intent rotation across every live Lumi Studio app.",
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
    _node(feed, "updated", _required_text(entries[0], "published"))
    author = ET.SubElement(feed, f"{{{ATOM}}}author")
    _node(author, "name", "Lumi Studio")
    _node(author, "uri", f"{SITE}/")
    for entry in entries:
        feed.append(copy.deepcopy(entry))
    ET.indent(feed, space="  ")
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True) + b"\n"


def _rotation_entry(
    slug: str,
    candidates: dict[str, dict[str, str]],
    slot: dt.datetime,
) -> ET.Element:
    container = ET.Element("entries")
    return _render_entry(container, candidates[slug], slot=slot)


def _rotation_slots(entries: list[ET.Element]) -> list[dt.datetime]:
    slots = []
    for entry in entries:
        published = _entry_published(entry)
        if published < BASE_SLOT:
            continue
        if publishing_slot(published) != published:
            raise ValueError(
                "existing Bridgy entry is not aligned to the six-hour cadence"
            )
        slots.append(published)
    return slots


def _initial_rotation_state(
    candidates: list[dict[str, str]],
    entries: list[ET.Element],
) -> dict[str, object]:
    live_slugs = [candidate["slug"] for candidate in candidates]
    recent_slugs = {_entry_slug(entry) for entry in entries}
    rotation_slots = _rotation_slots(entries)
    last_slot = (
        max(rotation_slots)
        if rotation_slots
        else BASE_SLOT - CADENCE
    )
    return {
        "version": STATE_VERSION,
        "last_slot": _timestamp(last_slot),
        "known_slugs": live_slugs,
        "remaining": [
            slug for slug in live_slugs if slug not in recent_slugs
        ],
    }


def _slug_list(value: object, *, label: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and re.fullmatch(r"[a-z0-9-]+", item)
        for item in value
    ):
        raise ValueError(f"Bridgy rotation state has invalid {label}")
    if len(value) != len(set(value)):
        raise ValueError(f"Bridgy rotation state has duplicate {label}")
    return list(value)


def _load_rotation_state(
    candidates: list[dict[str, str]],
    entries: list[ET.Element],
    *,
    path: pathlib.Path,
) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _initial_rotation_state(candidates, entries)
    try:
        state = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("Bridgy rotation state is invalid JSON") from error
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        raise ValueError("Bridgy rotation state has an unsupported version")

    last_slot_raw = state.get("last_slot")
    if not isinstance(last_slot_raw, str):
        raise ValueError("Bridgy rotation state is missing last_slot")
    last_slot = _parse_timestamp(
        last_slot_raw,
        label="Bridgy rotation state",
    )
    if (
        last_slot < BASE_SLOT - CADENCE
        or publishing_slot(last_slot) != last_slot
    ):
        raise ValueError("Bridgy rotation state has an invalid last_slot")

    known_slugs = _slug_list(state.get("known_slugs"), label="known_slugs")
    remaining = _slug_list(state.get("remaining"), label="remaining")
    if not set(remaining).issubset(known_slugs):
        raise ValueError(
            "Bridgy rotation state remaining apps are not in known_slugs"
        )
    rotation_slots = _rotation_slots(entries)
    if rotation_slots and max(rotation_slots) > last_slot:
        raise ValueError("Bridgy feed is ahead of its rotation state")
    if last_slot >= BASE_SLOT and (
        not rotation_slots or max(rotation_slots) != last_slot
    ):
        raise ValueError("Bridgy rotation state is ahead of its feed")

    live_slugs = [candidate["slug"] for candidate in candidates]
    live_set = set(live_slugs)
    remaining = [slug for slug in remaining if slug in live_set]
    remaining.extend(
        slug
        for slug in live_slugs
        if slug not in known_slugs and slug not in remaining
    )
    return {
        "version": STATE_VERSION,
        "last_slot": _timestamp(last_slot),
        "known_slugs": live_slugs,
        "remaining": remaining,
    }


def _serialize_rotation_state(state: dict[str, object]) -> bytes:
    return (
        json.dumps(
            state,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()


def advance_rotation(
    candidates: list[dict[str, str]],
    entries: list[ET.Element],
    state: dict[str, object],
    *,
    now: dt.datetime,
) -> tuple[bytes, bytes, list[dict[str, str]]]:
    candidate_by_slug = {
        candidate["slug"]: candidate for candidate in candidates
    }
    live_slugs = list(candidate_by_slug)
    if not live_slugs:
        raise ValueError("live app guide pool is empty")
    remaining = _slug_list(state.get("remaining"), label="remaining")
    last_slot_raw = state.get("last_slot")
    if not isinstance(last_slot_raw, str):
        raise ValueError("Bridgy rotation state is missing last_slot")
    last_slot = _parse_timestamp(
        last_slot_raw,
        label="Bridgy rotation state",
    )
    latest_slot = publishing_slot(now)
    if latest_slot < last_slot:
        raise ValueError("Bridgy rotation state is ahead of current time")

    existing_slots = {
        _entry_published(entry): _entry_slug(entry) for entry in entries
    }
    selected: list[dict[str, str]] = []
    if latest_slot > last_slot:
        if not remaining:
            remaining = live_slugs.copy()
        slug = remaining.pop(0)
        candidate = candidate_by_slug.get(slug)
        if candidate is None:
            raise ValueError(
                f"Bridgy rotation selected an unavailable app: {slug}"
            )
        existing_slug = existing_slots.get(latest_slot)
        if existing_slug is not None and existing_slug != slug:
            raise ValueError(
                "Bridgy feed conflicts with its persisted rotation state"
            )
        if existing_slug is None:
            entry = _rotation_entry(slug, candidate_by_slug, latest_slot)
            entries.append(entry)
            existing_slots[latest_slot] = slug
        selected.append(candidate)
        last_slot = latest_slot

    state = {
        "version": STATE_VERSION,
        "last_slot": _timestamp(last_slot),
        "known_slugs": live_slugs,
        "remaining": remaining,
    }
    return (
        _render_feed_entries(entries),
        _serialize_rotation_state(state),
        selected,
    )


def render_feed(
    candidates: list[dict[str, str]],
    *,
    now: dt.datetime,
) -> bytes:
    entries: list[ET.Element] = []
    state = _initial_rotation_state(candidates, entries)
    content, _state_content, _selected = advance_rotation(
        candidates,
        entries,
        state,
        now=now,
    )
    return content


def write_feed(content: bytes, *, path: pathlib.Path = FEED_PATH) -> bool:
    try:
        if path.read_bytes() == content:
            return False
    except FileNotFoundError:
        pass
    path.write_bytes(content)
    return True


def run(
    now: dt.datetime | None = None,
    *,
    feed_path: pathlib.Path = FEED_PATH,
    state_path: pathlib.Path = STATE_PATH,
) -> bool:
    now = dt.datetime.now(dt.timezone.utc) if now is None else now
    candidates = fetch_candidates()
    warn_profile_drift(candidates)
    try:
        existing_content = feed_path.read_bytes()
    except FileNotFoundError:
        existing_content = b""
    entries = parse_feed_entries(existing_content)
    state = _load_rotation_state(
        candidates,
        entries,
        path=state_path,
    )
    content, state_content, selected = advance_rotation(
        candidates,
        entries,
        state,
        now=now,
    )
    for candidate in {
        item["slug"]: item for item in selected[-FEED_ENTRY_LIMIT:]
    }.values():
        validate_guide(candidate["url"])
    feed_changed = write_feed(content, path=feed_path)
    state_changed = write_feed(state_content, path=state_path)
    rendered_entries = parse_feed_entries(content)
    current_slug = (
        selected[-1]["slug"]
        if selected
        else _entry_slug(rendered_entries[0])
    )
    slot = publishing_slot(now)
    print(
        "Bridgy feed:"
        f" {'updated' if feed_changed or state_changed else 'current'}"
        f" app={current_slug}"
        f" entries={len(rendered_entries)}"
        f" slot={slot.isoformat()}"
    )
    return feed_changed or state_changed


def main() -> int:
    try:
        run()
        return 0
    except (RequestError, ValueError, KeyError, OSError) as error:
        print(f"Bridgy feed failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
