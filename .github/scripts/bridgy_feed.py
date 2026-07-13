#!/usr/bin/env python3
"""Generate a one-entry Atom feed for Bridgy Fed from the live app registry."""

from __future__ import annotations

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
    "unblurry": (
        "en",
        "Review common blur causes and try realistic fixes for focus, motion, and low light",
        ("PhotoEditing", "iPhonePhotography", "iOSApps"),
    ),
}
SLUG_RE = re.compile(r"^[a-z0-9-]+$")
ROOT = pathlib.Path(__file__).resolve().parents[2]
FEED_PATH = ROOT / "bridgy-feed.xml"
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


def post_url(url: str, *, today: dt.date) -> str:
    # Preserve the already-published first post; later dates need unique URLs
    # because Bridgy Fed uses the alternate URL instead of the Atom tag ID.
    if today == BASE_DATE:
        return url
    return f"{url}?bridgy={today.isoformat()}"


def render_feed(candidate: dict[str, str], *, today: dt.date) -> bytes:
    timestamp = f"{today.isoformat()}T00:00:00Z"
    slug = candidate["slug"]
    name = candidate["name"]
    url = post_url(candidate["url"], today=today)
    store_url = candidate["store_url"]

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
