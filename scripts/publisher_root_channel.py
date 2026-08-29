#!/usr/bin/env python3
"""Generate exact-50 publisher root pages from verified public catalogs."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from managed_blocks import extract_allowlisted_sitemap_blocks
import sync_root_app_pages as legacy_sync


ROOT = Path(__file__).resolve().parents[1]
BASE = "https://alice51849.github.io"
CHANNEL_PATH = Path(__file__).with_name("publisher_root_channel.json")
PUBLISHER_DATASET_FILENAME = (
    "lumi-studio-publisher-search-intent-catalog.json"
)
MARKER_PREFIX = "<!-- publisher-root-page:"
RTL_LOCALES = frozenset({"ar-SA", "he", "ur-PK"})
ALLOWED_PURCHASE_MODELS = frozenset(
    {"paid_upfront", "free_with_lifetime_unlock"}
)
USER_AGENT = (
    "LumiPublisherRootSync/2.0 "
    "(+https://alice51849.github.io/)"
)
APP_STORE_URL_RE = re.compile(
    r"https://apps\.apple\.com/"
    r"[^\"'<>\s]*?/id(\d+)(?:\?[^\"'<>\s]*)?",
    flags=re.IGNORECASE,
)
APP_NAV_RE = re.compile(
    r"<style>\.applinks\{.*?</nav>",
    flags=re.DOTALL,
)
HOME_OG_COUNT_RE = re.compile(
    r'(<meta property="og:description" content="探索 )\d+'
    r'( 款獨立 iPhone App，查看逐款核實的功能、購買方式與正確 App Store 直達。">)'
)
SAFE_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SAFE_CAMPAIGN_RE = re.compile(r"[a-z0-9_]{1,30}")
UI_APP = "App"
UI_PUBLISHER_QUERY = "Publisher query"
UI_DECISION_CONTEXT = "Decision context"
UI_PURCHASE_MODEL = "Purchase model"
UI_GUIDE = "Guide"
UI_APP_STORE = "App Store"
UI_FIRST_PARTY = "First-party publisher catalog"
UI_NON_RANKING = (
    "The queries are editorial descriptions of intended use cases, not "
    "measured search-volume data, rankings, independent reviews, or user "
    "endorsements."
)
UI_PURCHASE_LABELS = {
    "paid_upfront": "Paid download",
    "free_with_lifetime_unlock": "Free to start · one-time unlock",
}
REQUIRED_UI_STRINGS = frozenset(
    {
        UI_APP,
        UI_PUBLISHER_QUERY,
        UI_DECISION_CONTEXT,
        UI_PURCHASE_MODEL,
        UI_GUIDE,
        UI_APP_STORE,
        UI_FIRST_PARTY,
        UI_NON_RANKING,
        *UI_PURCHASE_LABELS.values(),
    }
)
CATEGORY_SCHEMA = {
    "education": "EducationalApplication",
    "finance": "FinanceApplication",
    "health": "HealthApplication",
    "kids": "EducationalApplication",
    "lifestyle": "LifestyleApplication",
    "photo-utility": "MultimediaApplication",
    "productivity": "BusinessApplication",
    "sleep-sound": "LifestyleApplication",
    "travel": "TravelApplication",
    "utility": "UtilitiesApplication",
}
STATIC_SITEMAP_FILES = (
    ("", "index.html"),
    (".well-known/ai-catalog.json", ".well-known/ai-catalog.json"),
    (
        ".well-known/lumi-app-finder.mcp.json",
        ".well-known/lumi-app-finder.mcp.json",
    ),
    (".well-known/api-catalog", ".well-known/api-catalog"),
    (".well-known/resourcesync", ".well-known/resourcesync"),
    ("tools/unblur-image/", "tools/unblur-image/index.html"),
    ("tools/scan-document/", "tools/scan-document/index.html"),
    ("tools/enhance-photo/", "tools/enhance-photo/index.html"),
    ("tools/clean-up-photo/", "tools/clean-up-photo/index.html"),
)


class PublisherRootError(RuntimeError):
    """Publisher root synchronization failed closed."""


class PublisherRootBlocked(PublisherRootError):
    """One or more apps lack safe publisher-page semantics."""


def _request_bytes(
    url: str,
    *,
    opener=None,
    sleeper=None,
    attempts: int = 3,
) -> bytes:
    opener = urllib.request.urlopen if opener is None else opener
    sleeper = time.sleep if sleeper is None else sleeper
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json,text/html;q=0.9",
            "User-Agent": USER_AGENT,
        },
    )
    for attempt in range(attempts):
        try:
            with opener(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            transient = error.code in {408, 429} or 500 <= error.code <= 599
            if not transient or attempt == attempts - 1:
                raise PublisherRootError(
                    f"public GET failed: HTTP {error.code} {url}"
                ) from error
        except OSError as error:
            if attempt == attempts - 1:
                raise PublisherRootError(
                    f"public GET failed after {attempts} attempts: {url}"
                ) from error
        sleeper(2 * (attempt + 1))
    raise AssertionError("unreachable")


def _request_text(
    url: str,
    *,
    opener=None,
    sleeper=None,
    attempts: int = 3,
) -> str:
    try:
        return _request_bytes(
            url,
            opener=opener,
            sleeper=sleeper,
            attempts=attempts,
        ).decode("utf-8")
    except UnicodeDecodeError as error:
        raise PublisherRootError(
            f"public GET was not UTF-8: {url}"
        ) from error


def _load_json(
    *,
    path: Path | None,
    url: str,
    opener=None,
    sleeper=None,
) -> object:
    try:
        source = (
            path.read_text(encoding="utf-8")
            if path is not None
            else _request_text(url, opener=opener, sleeper=sleeper)
        )
        return json.loads(source)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        location = str(path) if path is not None else url
        raise PublisherRootError(f"invalid JSON source: {location}") from error


def load_contract(path: Path = CHANNEL_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    root_slugs = payload.get("root_slugs")
    locales = payload.get("official_locales")
    supplements = payload.get("supplemental_app_keys")
    management = payload.get("page_management")
    if (
        payload.get("schema_version") != 1
        or payload.get("expected_app_count") != 46
        or payload.get("expected_locale_count") != 50
        or not isinstance(root_slugs, dict)
        or not isinstance(locales, list)
        or not isinstance(supplements, list)
        or not isinstance(management, dict)
    ):
        raise ValueError("invalid publisher root channel contract")
    if (
        len(root_slugs) != 46
        or len(locales) != 50
        or len(set(locales)) != 50
        or len(supplements) != 8
        or len(set(supplements)) != 8
    ):
        raise ValueError("publisher root channel counts are not exact")
    if not set(supplements).issubset(root_slugs):
        raise ValueError("publisher root supplements are outside the roster")
    legacy_keys = management.get("legacy_datajs")
    publisher_keys = management.get("publisher_exact50")
    app_owned = management.get("app_owned_exact50")
    if (
        not isinstance(legacy_keys, list)
        or not isinstance(publisher_keys, list)
        or not isinstance(app_owned, dict)
        or len(legacy_keys) != 35
        or len(publisher_keys) != 8
        or len(app_owned) != 3
        or len(set(legacy_keys)) != len(legacy_keys)
        or len(set(publisher_keys)) != len(publisher_keys)
    ):
        raise ValueError("publisher root management counts are invalid")
    partitions = [
        set(legacy_keys),
        set(publisher_keys),
        set(app_owned),
    ]
    if (
        set(supplements) != partitions[1]
        or any(partitions[i] & partitions[j] for i in range(3) for j in range(i))
        or set().union(*partitions) != set(root_slugs)
    ):
        raise ValueError("publisher root management ownership is ambiguous")
    for key, manifest in app_owned.items():
        if (
            key not in root_slugs
            or not isinstance(manifest, str)
            or not manifest.startswith(f"app/{root_slugs[key]}/")
            or not manifest.endswith("/manifest.json")
            or ".." in Path(manifest).parts
        ):
            raise ValueError(f"invalid app-owned management path: {key}")
    slugs = list(root_slugs.values())
    if len(set(slugs)) != len(slugs):
        raise ValueError("publisher root slugs are not unique")
    for key, slug in root_slugs.items():
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(slug, str)
            or SAFE_SLUG_RE.fullmatch(slug) is None
        ):
            raise ValueError(f"invalid publisher root slug: {key}={slug}")
    for field in (
        "canonical_catalog_url",
        "localized_catalog_base_url",
        "publisher_dataset_url",
    ):
        value = payload.get(field)
        if (
            not isinstance(value, str)
            or not value.startswith("https://alice51849.github.io/")
        ):
            raise ValueError(f"invalid publisher root source URL: {field}")
    i18n_url = payload.get("publisher_i18n_source_url")
    if (
        not isinstance(i18n_url, str)
        or not i18n_url.startswith(
            "https://raw.githubusercontent.com/"
            "alice51849/ios-app-guide/"
        )
    ):
        raise ValueError("invalid publisher i18n source URL")
    digest = payload.get("publisher_i18n_source_sha256")
    if (
        not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
    ):
        raise ValueError("invalid publisher i18n source digest")
    return payload


def _validate_app_store_url(url: object, app_id: str) -> None:
    if not isinstance(url, str):
        raise ValueError("App Store URL must be a string")
    parsed = urllib.parse.urlsplit(url)
    matched = re.search(r"/app/id(\d+)$", parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "apps.apple.com"
        or matched is None
        or matched.group(1) != app_id
    ):
        raise ValueError(f"App Store URL identity mismatch: {url}")


def _validate_campaign_url(url: object, app_id: str) -> None:
    _validate_app_store_url(url, app_id)
    parsed = urllib.parse.urlsplit(str(url))
    query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
    if (
        len(query.get("pt", [])) != 1
        or not query["pt"][0].isdigit()
        or len(query.get("ct", [])) != 1
        or SAFE_CAMPAIGN_RE.fullmatch(query["ct"][0]) is None
        or query.get("mt") != ["8"]
    ):
        raise ValueError(f"App Store campaign URL is incomplete: {url}")


def _validate_guide_url(url: object, locale: str) -> None:
    if not isinstance(url, str):
        raise ValueError("publisher guide URL must be a string")
    parsed = urllib.parse.urlsplit(url)
    prefix = f"/ios-app-guide/{locale}/"
    if (
        parsed.scheme != "https"
        or parsed.netloc != "alice51849.github.io"
        or not parsed.path.startswith(prefix)
        or not parsed.path.endswith(".html")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"publisher guide URL is invalid: {url}")


def _finder_records(
    payload: object,
    contract: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("canonical catalog must be an object")
    apps = payload.get("apps")
    if (
        not isinstance(apps, list)
        or len(apps) != contract["expected_app_count"]
        or payload.get("record_count") != len(apps)
    ):
        raise ValueError("canonical catalog is not exact46")
    records: dict[str, dict[str, Any]] = {}
    for app in apps:
        if not isinstance(app, dict):
            raise ValueError("canonical catalog app is invalid")
        key = app.get("key")
        app_id = app.get("app_store_id")
        if (
            not isinstance(key, str)
            or key in records
            or not isinstance(app_id, str)
            or not app_id.isdigit()
            or app.get("verified_live") is not True
        ):
            raise ValueError(f"canonical catalog identity is invalid: {key}")
        _validate_app_store_url(app.get("canonical_app_store_url"), app_id)
        records[key] = app
    expected = set(contract["root_slugs"])
    if set(records) != expected:
        raise ValueError(
            "canonical/root roster differs: "
            f"missing={sorted(expected - set(records))}, "
            f"extra={sorted(set(records) - expected)}"
        )
    return records


def _localized_records(
    payloads: dict[str, object],
    contract: dict[str, Any],
    finder: dict[str, dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    expected_keys = set(finder)
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for locale in contract["official_locales"]:
        document = payloads.get(locale)
        if (
            not isinstance(document, dict)
            or document.get("locale") != locale
            or not isinstance(document.get("apps"), list)
            or document.get("record_count") != len(document["apps"])
            or len(document["apps"]) != contract["expected_app_count"]
        ):
            raise ValueError(f"localized canonical catalog is invalid: {locale}")
        by_key: dict[str, dict[str, Any]] = {}
        for record in document["apps"]:
            if not isinstance(record, dict):
                raise ValueError(f"localized record is invalid: {locale}")
            key = record.get("key")
            app_id = record.get("app_store_id")
            if (
                not isinstance(key, str)
                or key in by_key
                or key not in finder
                or app_id != finder[key]["app_store_id"]
                or record.get("verified_live") is not True
                or not isinstance(record.get("name"), str)
                or not record["name"].strip()
                or not isinstance(record.get("summary"), str)
                or len(record["summary"].strip()) < 20
                or not isinstance(record.get("search_terms"), list)
                or len(record["search_terms"]) < 3
            ):
                raise ValueError(
                    f"localized canonical identity/content is invalid: "
                    f"{locale}/{key}"
                )
            _validate_campaign_url(record.get("app_store_url"), app_id)
            guide_url = record.get("guide_url")
            if (
                not isinstance(guide_url, str)
                or guide_url
                != (
                    "https://alice51849.github.io/ios-app-guide/"
                    f"{locale}/{key}.html"
                )
            ):
                raise ValueError(
                    f"localized guide URL is invalid: {locale}/{key}"
                )
            facts = record.get("storefront_facts")
            if facts is not None and (
                not isinstance(facts, dict)
                or not isinstance(facts.get("price"), str)
                or not isinstance(facts.get("currency"), str)
                or not isinstance(facts.get("formatted_price"), str)
            ):
                raise ValueError(
                    f"localized storefront facts are invalid: {locale}/{key}"
                )
            by_key[key] = record
        if set(by_key) != expected_keys:
            raise ValueError(f"localized canonical roster differs: {locale}")
        result[locale] = by_key
    return result


def _publisher_records(
    payload: object,
    contract: dict[str, Any],
    finder: dict[str, dict[str, Any]],
) -> tuple[
    dict[str, dict[str, dict[str, Any]]],
    str,
]:
    if (
        not isinstance(payload, dict)
        or payload.get("app_count") != contract["expected_app_count"]
        or payload.get("locale_count") != contract["expected_locale_count"]
        or payload.get("record_count")
        != contract["expected_app_count"] * contract["expected_locale_count"]
        or payload.get("locales") != contract["official_locales"]
        or payload.get("query_origin")
        != "publisher_authored_editorially_localized"
        or payload.get("measured_search_volume") is not False
        or payload.get("is_ranking") is not False
        or not isinstance(payload.get("records"), list)
    ):
        raise ValueError("publisher intent dataset contract is invalid")
    result = {
        locale: {} for locale in contract["official_locales"]
    }
    for record in payload["records"]:
        if not isinstance(record, dict):
            raise ValueError("publisher intent record is invalid")
        locale = record.get("locale")
        key = record.get("app_key")
        if (
            locale not in result
            or key not in finder
            or key in result[locale]
            or record.get("app_store_id") != finder[key]["app_store_id"]
            or record.get("verified_live") is not True
        ):
            raise ValueError(
                f"publisher intent identity is invalid: {locale}/{key}"
            )
        app_id = str(record["app_store_id"])
        try:
            _validate_app_store_url(
                record.get("canonical_app_store_url"),
                app_id,
            )
            _validate_campaign_url(record.get("app_store_url"), app_id)
        except ValueError as error:
            raise ValueError(
                f"publisher intent App Store URL is invalid: "
                f"{locale}/{key}: {error}"
            ) from error
        result[locale][key] = record
    expected = set(finder)
    for locale, records in result.items():
        if set(records) != expected:
            raise ValueError(f"publisher intent roster differs: {locale}")
    modified = payload.get("dateModified")
    if not isinstance(modified, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", modified
    ) is None:
        raise ValueError("publisher intent dateModified is invalid")
    return result, modified


def _publisher_i18n(
    contract: dict[str, Any],
    *,
    path: Path | None,
    opener=None,
    sleeper=None,
) -> tuple[dict[str, dict[str, Any]], str]:
    try:
        source = (
            path.read_bytes()
            if path is not None
            else _request_bytes(
                contract["publisher_i18n_source_url"],
                opener=opener,
                sleeper=sleeper,
            )
        )
    except OSError as error:
        location = (
            str(path)
            if path is not None
            else contract["publisher_i18n_source_url"]
        )
        raise PublisherRootError(
            f"publisher i18n source is unavailable: {location}"
        ) from error
    digest = hashlib.sha256(source).hexdigest()
    if digest != contract["publisher_i18n_source_sha256"]:
        raise PublisherRootError(
            "publisher i18n source digest drifted: "
            f"expected={contract['publisher_i18n_source_sha256']} "
            f"actual={digest}"
        )
    try:
        payload = json.loads(source.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublisherRootError(
            "publisher i18n source is not valid UTF-8 JSON"
        ) from error
    strings = payload.get("strings") if isinstance(payload, dict) else None
    localizations = (
        payload.get("localizations") if isinstance(payload, dict) else None
    )
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("source_locale") != "en-US"
        or not isinstance(strings, list)
        or len(strings) != len(set(strings))
        or not REQUIRED_UI_STRINGS.issubset(strings)
        or not isinstance(localizations, dict)
        or set(localizations) != set(contract["official_locales"])
    ):
        raise ValueError("publisher i18n source contract is invalid")
    expected_strings = set(strings)
    result: dict[str, dict[str, Any]] = {}
    for locale in contract["official_locales"]:
        mapping = localizations[locale]
        if not isinstance(mapping, dict) or set(mapping) != expected_strings:
            raise ValueError(f"publisher i18n locale is incomplete: {locale}")
        for source_text, translated in mapping.items():
            if (
                not isinstance(source_text, str)
                or not isinstance(translated, str)
                or not translated.strip()
                or "\n" in translated
                or "\r" in translated
            ):
                raise ValueError(
                    f"publisher i18n value is invalid: "
                    f"{locale}/{source_text}"
                )
        result[locale] = {
            "headers": [
                mapping[UI_APP],
                mapping[UI_PUBLISHER_QUERY],
                mapping[UI_DECISION_CONTEXT],
                mapping[UI_PURCHASE_MODEL],
                mapping[UI_GUIDE],
                mapping[UI_APP_STORE],
            ],
            "first_party_heading": mapping[UI_FIRST_PARTY],
            "non_ranking_notice": mapping[UI_NON_RANKING],
            "purchase_labels": {
                purchase_model: mapping[source_text]
                for purchase_model, source_text in UI_PURCHASE_LABELS.items()
            },
            "guide_label": mapping[UI_GUIDE],
            "app_store_label": mapping[UI_APP_STORE],
        }
    return result, digest


def load_sources(
    contract: dict[str, Any],
    *,
    finder_path: Path | None = None,
    publisher_dataset_path: Path | None = None,
    localized_catalog_dir: Path | None = None,
    publisher_i18n_path: Path | None = None,
    opener=None,
    sleeper=None,
) -> dict[str, Any]:
    finder_payload = _load_json(
        path=finder_path,
        url=contract["canonical_catalog_url"],
        opener=opener,
        sleeper=sleeper,
    )
    finder = _finder_records(finder_payload, contract)
    publisher_payload = _load_json(
        path=publisher_dataset_path,
        url=contract["publisher_dataset_url"],
        opener=opener,
        sleeper=sleeper,
    )
    publisher, modified = _publisher_records(
        publisher_payload,
        contract,
        finder,
    )
    ui, i18n_digest = _publisher_i18n(
        contract,
        path=publisher_i18n_path,
        opener=opener,
        sleeper=sleeper,
    )

    def load_locale(locale: str) -> tuple[str, object]:
        catalog_path = (
            localized_catalog_dir / f"{locale}.json"
            if localized_catalog_dir is not None
            else None
        )
        catalog = _load_json(
            path=catalog_path,
            url=(
                f"{contract['localized_catalog_base_url']}/{locale}.json"
            ),
            opener=opener,
            sleeper=sleeper,
        )
        return locale, catalog

    localized_payloads: dict[str, object] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        for locale, catalog in executor.map(
            load_locale,
            contract["official_locales"],
        ):
            localized_payloads[locale] = catalog
    localized = _localized_records(
        localized_payloads,
        contract,
        finder,
    )
    return {
        "finder": finder,
        "localized": localized,
        "publisher": publisher,
        "ui": ui,
        "publisher_i18n_digest": i18n_digest,
        "modified": modified,
    }


def load_datajs_cards(
    site: Path,
    contract: dict[str, Any],
    sources: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    cards_by_slug = legacy_sync.legacy.parse_datajs(
        site / "assets" / "data.js"
    )
    key_by_id = {
        record["app_store_id"]: key
        for key, record in sources["finder"].items()
    }
    cards: dict[str, dict[str, Any]] = {}
    for slug, card in cards_by_slug.items():
        try:
            app_id = legacy_sync.app_id_from_url(card.get("url"))
        except ValueError as error:
            raise PublisherRootBlocked(
                f"BLOCKED data.js card has an invalid App Store URL: {slug}"
            ) from error
        key = key_by_id.get(app_id)
        if key is None:
            raise PublisherRootBlocked(
                f"BLOCKED data.js contains a non-canonical app: {slug}/{app_id}"
            )
        if key in cards:
            raise PublisherRootBlocked(
                f"BLOCKED data.js duplicates canonical app key: {key}"
            )
        expected_slug = contract["root_slugs"][key]
        if slug != expected_slug:
            raise PublisherRootBlocked(
                "BLOCKED data.js/root slug drift: "
                f"{key} expected={expected_slug} actual={slug}"
            )
        cards[key] = card
    expected = set(contract["root_slugs"])
    if set(cards) != expected:
        raise PublisherRootBlocked(
            "BLOCKED visible cards are not exact46: "
            f"missing={sorted(expected - set(cards))}, "
            f"extra={sorted(set(cards) - expected)}"
        )
    return cards


def _legacy_page_path(site: Path, slug: str, lang: str) -> Path:
    if lang == "en":
        return site / "app" / slug / "index.html"
    return site / "app" / slug / lang / "index.html"


def sync_legacy_pages(
    site: Path,
    contract: dict[str, Any],
    sources: dict[str, Any],
    cards: dict[str, dict[str, Any]],
) -> dict[str, int]:
    legacy_keys = contract["page_management"]["legacy_datajs"]
    external_keys = (
        set(contract["page_management"]["publisher_exact50"])
        | set(contract["page_management"]["app_owned_exact50"])
    )
    legacy_apps: dict[str, dict[str, Any]] = {}
    catalogs: dict[str, dict[str, dict[str, Any]]] = {
        lang: {} for lang in legacy_sync.CATALOG_LOCALES
    }
    changed = 0
    seen_paths: set[Path] = set()
    for key in legacy_keys:
        card = cards[key]
        slug = contract["root_slugs"][key]
        legacy_apps[slug] = card
        app_id = sources["finder"][key]["app_store_id"]
        for lang, locale in legacy_sync.CATALOG_LOCALES.items():
            record = sources["localized"][locale][key]
            catalogs[lang][app_id] = record
            path = _legacy_page_path(site, slug, lang)
            resolved = path.resolve()
            if resolved in seen_paths:
                raise ValueError(f"duplicate legacy page write: {path}")
            seen_paths.add(resolved)
            if not path.is_file():
                raise PublisherRootBlocked(
                    f"BLOCKED legacy-managed page is missing: {path}"
                )
            if legacy_sync.sync_page(path, record, lang):
                changed += 1

    original_root = legacy_sync.ROOT
    legacy_sync.ROOT = site
    try:
        legacy_sync.validate_all_pages(
            legacy_apps,
            catalogs,
            externally_managed_slugs=frozenset(
                contract["root_slugs"][key] for key in external_keys
            ),
        )
    finally:
        legacy_sync.ROOT = original_root
    return {
        "apps": len(legacy_keys),
        "pages": len(legacy_keys) * len(legacy_sync.CATALOG_LOCALES),
        "updated": changed,
    }


def validate_app_owned_pages(
    site: Path,
    contract: dict[str, Any],
    sources: dict[str, Any],
) -> None:
    official_locales = set(contract["official_locales"])
    canonical_ids = {
        record["app_store_id"] for record in sources["finder"].values()
    }
    for key, relative_manifest in contract["page_management"][
        "app_owned_exact50"
    ].items():
        manifest_path = site / relative_manifest
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            raise PublisherRootBlocked(
                f"BLOCKED app-owned manifest is unavailable: {relative_manifest}"
            ) from error
        app_id = sources["finder"][key]["app_store_id"]
        slug = contract["root_slugs"][key]
        locales = manifest.get("locales")
        if (
            str(manifest.get("appId", "")) != app_id
            or not isinstance(locales, list)
            or set(locales) != official_locales
            or len(locales) != len(official_locales)
            or manifest.get("slug", slug) != slug
        ):
            raise PublisherRootBlocked(
                f"BLOCKED app-owned manifest drifted: {key}"
            )
        paths = [
            _page_path(site, slug, None),
            *(
                _page_path(site, slug, locale)
                for locale in contract["official_locales"]
            ),
        ]
        for path in paths:
            if not path.is_file():
                raise PublisherRootBlocked(
                    f"BLOCKED app-owned exact50 page is missing: {path}"
                )
            ids = set(APP_STORE_URL_RE.findall(
                path.read_text(encoding="utf-8")
            ))
            if app_id not in ids or not ids.issubset(canonical_ids):
                raise PublisherRootBlocked(
                    f"BLOCKED app-owned page identity drifted: {path}"
                )


def _validate_supplemental_eligibility(
    contract: dict[str, Any],
    sources: dict[str, Any],
) -> None:
    blocked: list[str] = []
    for key in contract["supplemental_app_keys"]:
        for locale in contract["official_locales"]:
            catalog = sources["localized"][locale][key]
            publisher = sources["publisher"][locale][key]
            ui = sources["ui"][locale]
            reasons: list[str] = []
            if (
                publisher.get("query_origin")
                != "publisher_authored_editorially_localized"
            ):
                reasons.append("query origin is not publisher-authored")
            if publisher.get("measured_search_volume") is not False:
                reasons.append("measured-search-volume claim is unsafe")
            if publisher.get("is_ranking") is not False:
                reasons.append("ranking semantics are unsafe")
            if publisher.get("one_time_option") is not True:
                reasons.append("one-time option is not verified")
            if publisher.get("purchase_model") not in ALLOWED_PURCHASE_MODELS:
                reasons.append("purchase model is unsupported")
            if len(str(publisher.get("publisher_query", "")).strip()) < 10:
                reasons.append("publisher query is too thin")
            if len(str(publisher.get("decision_context", "")).strip()) < 20:
                reasons.append("decision context is too thin")
            disclosure = str(
                publisher.get("publisher_disclosure", "")
            ).strip()
            if "Lumi Studio" not in disclosure or len(disclosure) < 20:
                reasons.append("first-party disclosure is missing")
            if len(ui["non_ranking_notice"]) < 20:
                reasons.append("native non-ranking notice is missing")
            try:
                _validate_guide_url(
                    publisher.get("canonical_guide_url"),
                    locale,
                )
            except ValueError as error:
                reasons.append(str(error))
            try:
                _validate_campaign_url(
                    publisher.get("app_store_url"),
                    catalog["app_store_id"],
                )
            except ValueError as error:
                reasons.append(str(error))
            if reasons:
                blocked.append(f"{key}/{locale}: {', '.join(reasons)}")
    if blocked:
        raise PublisherRootBlocked(
            "BLOCKED publisher-root apps; no pages were written: "
            + "; ".join(blocked)
        )


def _write_if_changed(path: Path, content: str) -> bool:
    try:
        if path.read_text(encoding="utf-8") == content:
            return False
    except (FileNotFoundError, UnicodeDecodeError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _truncate_meta(value: str, limit: int = 155) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    candidate = value[: limit - 1].rstrip(" ,.;:，。；：")
    if " " in candidate:
        candidate = candidate.rsplit(" ", 1)[0]
    return candidate + "…"


def _page_url(slug: str, locale: str | None) -> str:
    suffix = "" if locale is None else f"{locale}/"
    return f"{BASE}/app/{slug}/{suffix}"


def _page_path(site: Path, slug: str, locale: str | None) -> Path:
    if locale is None:
        return site / "app" / slug / "index.html"
    return site / "app" / slug / locale / "index.html"


def _page_marker(
    key: str,
    locale: str,
    canonical: str,
    publisher: dict[str, Any],
    catalog: dict[str, Any],
    ui: dict[str, Any],
) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "key": key,
                "locale": locale,
                "canonical": canonical,
                "publisher": publisher,
                "catalog": catalog,
                "ui": {
                    "first_party_heading": ui["first_party_heading"],
                    "non_ranking_notice": ui["non_ranking_notice"],
                    "purchase_label": ui["purchase_labels"][
                        publisher["purchase_model"]
                    ],
                    "guide_label": ui["guide_label"],
                    "app_store_label": ui["app_store_label"],
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"{MARKER_PREFIX}{key}:{locale}:{digest} -->"


def render_page(
    *,
    key: str,
    slug: str,
    locale: str,
    canonical_locale: str | None,
    contract: dict[str, Any],
    publisher: dict[str, Any],
    catalog: dict[str, Any],
    ui: dict[str, Any],
    modified: str,
) -> str:
    app_id = catalog["app_store_id"]
    campaign_url = publisher["app_store_url"]
    _validate_campaign_url(campaign_url, app_id)
    canonical = _page_url(slug, canonical_locale)
    direction = "rtl" if locale in RTL_LOCALES else "ltr"
    hreflang = "\n".join(
        (
            '<link rel="alternate" '
            f'hreflang="{html.escape(item, quote=True)}" '
            f'href="{html.escape(_page_url(slug, item), quote=True)}">'
        )
        for item in contract["official_locales"]
    )
    hreflang += (
        "\n<link rel=\"alternate\" hreflang=\"x-default\" "
        f'href="{html.escape(_page_url(slug, None), quote=True)}">'
    )
    purchase_label = ui["purchase_labels"][publisher["purchase_model"]]
    search_terms = [
        str(term).strip()
        for term in catalog["search_terms"][:10]
        if isinstance(term, str) and term.strip()
    ]
    terms_html = "".join(
        f"<li>{html.escape(term)}</li>" for term in search_terms
    )
    summary = str(catalog["summary"]).strip()
    decision = str(publisher["decision_context"]).strip()
    summary_html = ""
    if " ".join(summary.casefold().split()) != " ".join(
        decision.casefold().split()
    ):
        summary_html = f"<p>{html.escape(summary)}</p>"
    storefront_facts = catalog.get("storefront_facts")
    if not isinstance(storefront_facts, dict):
        storefront_facts = {}
    price = str(storefront_facts.get("formatted_price", "")).strip()
    price_html = (
        f"<strong>{html.escape(price)}</strong>" if price else ""
    )
    title = str(publisher["publisher_query"]).strip()
    description = _truncate_meta(decision)
    marker = _page_marker(
        key,
        locale,
        canonical,
        publisher,
        catalog,
        ui,
    )
    schema = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": publisher["app_name"],
        "description": decision,
        "operatingSystem": "iOS",
        "applicationCategory": CATEGORY_SCHEMA.get(
            str(catalog.get("category")),
            "UtilitiesApplication",
        ),
        "inLanguage": locale,
        "url": canonical,
        "installUrl": campaign_url,
        "downloadUrl": campaign_url,
        "sameAs": [
            publisher["canonical_guide_url"],
            publisher["canonical_app_store_url"],
        ],
        "publisher": {
            "@type": "Organization",
            "name": "Lumi Studio",
            "url": BASE,
        },
        "offers": {
            "@type": "Offer",
            "url": campaign_url,
            "description": purchase_label,
        },
        "additionalProperty": [
            {
                "@type": "PropertyValue",
                "name": "query_origin",
                "value": "publisher_authored_editorially_localized",
            },
            {
                "@type": "PropertyValue",
                "name": "is_ranking",
                "value": False,
            },
            {
                "@type": "PropertyValue",
                "name": "measured_search_volume",
                "value": False,
            },
        ],
    }
    if price:
        schema["offers"].update(
            {
                "price": storefront_facts["price"],
                "priceCurrency": storefront_facts["currency"],
            }
        )
    hue = int(hashlib.sha256(key.encode()).hexdigest()[:2], 16)
    hue2 = (hue + 54) % 360
    return f"""<!doctype html>
<html lang="{html.escape(locale, quote=True)}" dir="{direction}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-itunes-app" content="app-id={app_id}">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description, quote=True)}">
<meta name="robots" content="index,follow,max-image-preview:large">
<link rel="canonical" href="{html.escape(canonical, quote=True)}">
{hreflang}
<meta property="og:type" content="website">
<meta property="og:site_name" content="Lumi Studio">
<meta property="og:title" content="{html.escape(title, quote=True)}">
<meta property="og:description" content="{html.escape(description, quote=True)}">
<meta property="og:url" content="{html.escape(canonical, quote=True)}">
<meta name="twitter:card" content="summary">
<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False, separators=(",", ":"))}</script>
<style>
:root{{--ink:#201f2b;--muted:#676375;--line:rgba(76,67,112,.16);--a:hsl({hue} 84% 66%);--b:hsl({hue2} 84% 64%);--paper:rgba(255,255,255,.78)}}
*{{box-sizing:border-box}}html{{background:#f8f7fc}}body{{min-height:100vh;margin:0;color:var(--ink);background:radial-gradient(circle at 8% 4%,color-mix(in srgb,var(--a) 22%,transparent),transparent 32rem),radial-gradient(circle at 94% 8%,color-mix(in srgb,var(--b) 22%,transparent),transparent 34rem),linear-gradient(150deg,#fff 0%,#f7f5ff 52%,#f3f7ff 100%);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",sans-serif;line-height:1.62;-webkit-font-smoothing:antialiased}}
a{{color:#6540b8;text-decoration:none}}a:hover{{text-decoration:underline}}.shell{{width:min(900px,calc(100% - 38px));margin:auto}}header{{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:22px 0}}.brand{{color:var(--ink);font-weight:800}}.hero{{padding:34px 0 24px}}.mark{{display:grid;width:68px;height:68px;place-items:center;border-radius:22px;color:#fff;background:linear-gradient(135deg,var(--a),var(--b));box-shadow:0 18px 46px color-mix(in srgb,var(--a) 28%,transparent);font-size:29px;font-weight:750}}h1{{margin:20px 0 10px;font-size:clamp(35px,7vw,62px);font-weight:720;letter-spacing:-.035em;line-height:1.05}}.query{{max-width:38ch;margin:0;color:var(--muted);font-size:clamp(18px,3vw,24px)}}.grid{{display:grid;grid-template-columns:1.3fr .7fr;gap:16px;padding:12px 0 28px}}.card{{padding:24px;border:1px solid var(--line);border-radius:24px;background:var(--paper);box-shadow:0 22px 70px rgba(55,42,100,.09);backdrop-filter:blur(20px)}}.card h2{{margin:0 0 10px;font-size:18px}}.card p{{margin:0;color:var(--muted)}}.card p+p{{margin-top:10px}}.terms{{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 0;padding:0;list-style:none}}.terms li{{padding:7px 12px;border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.7);color:var(--muted);font-size:14px}}.price{{display:flex;align-items:baseline;justify-content:space-between;gap:12px}}.price strong{{font-size:22px}}.actions{{display:grid;gap:10px;margin-top:20px}}.cta{{display:flex;min-height:48px;align-items:center;justify-content:center;padding:12px 18px;border-radius:16px;color:#fff;background:linear-gradient(135deg,var(--a),var(--b));font-weight:800;box-shadow:0 12px 28px color-mix(in srgb,var(--a) 24%,transparent)}}.cta:hover{{color:#fff;text-decoration:none;transform:translateY(-1px)}}.guide{{display:block;padding:12px 0;font-weight:700}}.disclosure{{grid-column:1/-1}}footer{{display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap;padding:28px 0 42px;border-top:1px solid var(--line);color:var(--muted);font-size:14px}}@media(max-width:720px){{.grid{{grid-template-columns:1fr}}.hero{{padding-top:20px}}}}
</style>
</head>
<body>
{marker}
<div class="shell" data-app-key="{html.escape(key, quote=True)}" data-query-origin="publisher_authored_editorially_localized" data-ranking="false">
<header><a class="brand" href="/">Lumi Studio</a><a href="{html.escape(publisher['canonical_guide_url'], quote=True)}">{html.escape(ui['guide_label'])}</a></header>
<main>
<section class="hero">
<div class="mark" aria-hidden="true">{html.escape(str(publisher['app_name']).strip()[:1])}</div>
<h1>{html.escape(str(publisher['app_name']))}</h1>
<p class="query">{html.escape(title)}</p>
</section>
<section class="grid">
<article class="card">
<h2>{html.escape(ui['headers'][2])}</h2>
<p>{html.escape(decision)}</p>
{summary_html}
<ul class="terms" aria-label="{html.escape(ui['headers'][1], quote=True)}">{terms_html}</ul>
</article>
<aside class="card">
<div class="price"><span>{html.escape(purchase_label)}</span>{price_html}</div>
<div class="actions">
<a class="cta" href="{html.escape(campaign_url, quote=True)}" rel="noopener">{html.escape(str(publisher['app_store_cta_label']))}</a>
<a class="guide" href="{html.escape(str(publisher['canonical_guide_url']), quote=True)}">↗ {html.escape(ui['guide_label'])}: {html.escape(str(publisher['app_name']))}</a>
</div>
</aside>
<aside class="card disclosure">
<h2>{html.escape(ui['first_party_heading'])}</h2>
<p>{html.escape(str(publisher['publisher_disclosure']))}</p>
<p>{html.escape(ui['non_ranking_notice'])}</p>
</aside>
</section>
</main>
<footer><span>© Lumi Studio · {html.escape(str(publisher['app_name']))}</span><span>{html.escape(modified)}</span></footer>
</div>
</body>
</html>
"""


def generate_supplemental_pages(
    site: Path,
    contract: dict[str, Any],
    sources: dict[str, Any],
) -> dict[str, int]:
    _validate_supplemental_eligibility(contract, sources)
    created = 0
    updated = 0
    unchanged = 0
    for key in contract["supplemental_app_keys"]:
        slug = contract["root_slugs"][key]
        targets: list[tuple[str, str | None]] = [
            ("en-US", None),
            *(
                (locale, locale)
                for locale in contract["official_locales"]
            ),
        ]
        for locale, canonical_locale in targets:
            path = _page_path(site, slug, canonical_locale)
            existed = path.is_file()
            content = render_page(
                key=key,
                slug=slug,
                locale=locale,
                canonical_locale=canonical_locale,
                contract=contract,
                publisher=sources["publisher"][locale][key],
                catalog=sources["localized"][locale][key],
                ui=sources["ui"][locale],
                modified=sources["modified"],
            )
            if _write_if_changed(path, content):
                if existed:
                    updated += 1
                else:
                    created += 1
            else:
                unchanged += 1
    return {
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "pages": len(contract["supplemental_app_keys"])
        * (len(contract["official_locales"]) + 1),
    }


def rebuild_home(
    site: Path,
    contract: dict[str, Any],
    sources: dict[str, Any],
    cards: dict[str, dict[str, Any]],
) -> bool:
    links = []
    for key, slug in contract["root_slugs"].items():
        name = sources["publisher"]["en-US"][key]["app_name"]
        links.append((str(name).casefold(), slug, str(name)))
    links.sort()
    style = (
        '<style>.applinks{margin:20px auto 0;max-width:780px;display:flex;'
        'flex-wrap:wrap;gap:7px 15px;justify-content:center;'
        'border-top:1px solid var(--line);padding-top:16px}'
        '.applinks a{font-size:12.5px;color:var(--muted);'
        'text-decoration:none}.applinks a:hover{color:var(--ink2)}</style>'
    )
    nav = '<nav class="applinks" aria-label="All apps">' + "".join(
        f'<a href="/app/{html.escape(slug, quote=True)}/">'
        f"{html.escape(name)}</a>"
        for _sort, slug, name in links
    ) + "</nav>"
    path = site / "index.html"
    source = path.read_text(encoding="utf-8")
    updated, count = APP_NAV_RE.subn(style + nav, source, count=1)
    if count != 1:
        raise ValueError("home page app navigation block is missing")
    updated, count = HOME_OG_COUNT_RE.subn(
        rf"\g<1>{len(cards)}\g<2>",
        updated,
        count=1,
    )
    if count != 1:
        raise ValueError("home page Open Graph app count is missing")
    return _write_if_changed(path, updated)


def rebuild_llms(
    site: Path,
    contract: dict[str, Any],
    sources: dict[str, Any],
) -> bool:
    path = site / "llms.txt"
    source = path.read_text(encoding="utf-8")
    before, separator, rest = source.partition("## Apps\n")
    if not separator:
        raise ValueError("llms.txt Apps section is missing")
    _old_apps, separator, after = rest.partition(
        "## Machine-readable app discovery\n"
    )
    if not separator:
        raise ValueError("llms.txt discovery section is missing")
    lines = []
    for key in contract["root_slugs"]:
        record = sources["publisher"]["en-US"][key]
        lines.append(
            (
                str(record["app_name"]).casefold(),
                f"- {record['app_name']} — {record['decision_context']} — "
                f"{record['app_store_url']}",
            )
        )
    lines.sort()
    updated = (
        before
        + "## Apps\n\n"
        + "\n".join(line for _sort, line in lines)
        + "\n\n## Machine-readable app discovery\n"
        + after
    )
    return _write_if_changed(path, updated)


def _dirty_paths(site: Path) -> set[str]:
    status = subprocess.run(
        ["git", "status", "--porcelain", "-z"],
        cwd=site,
        check=False,
        capture_output=True,
    )
    if status.returncode != 0:
        return set()
    dirty = set()
    for entry in status.stdout.split(b"\0"):
        if len(entry) < 4:
            continue
        path = entry[3:].decode("utf-8")
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1]
        dirty.add(path)
    return dirty


def rebuild_sitemap(
    site: Path,
    contract: dict[str, Any],
    *,
    today: str,
) -> bool:
    path = site / "sitemap.xml"
    source = path.read_text(encoding="utf-8")
    previous = dict(
        re.findall(
            r"<url><loc>([^<]+)</loc>"
            r"<lastmod>(\d{4}-\d{2}-\d{2})</lastmod></url>",
            source,
        )
    )
    managed_blocks = extract_allowlisted_sitemap_blocks(source)
    dirty_paths = _dirty_paths(site)
    entries: dict[str, Path] = {}
    for suffix, relative in STATIC_SITEMAP_FILES:
        file_path = site / relative
        if file_path.is_file():
            entries[f"{BASE}/{suffix}"] = file_path
    for slug in contract["root_slugs"].values():
        root_page = _page_path(site, slug, None)
        if root_page.is_file():
            entries[_page_url(slug, None)] = root_page
        for locale in contract["official_locales"]:
            locale_page = _page_path(site, slug, locale)
            if locale_page.is_file():
                entries[_page_url(slug, locale)] = locale_page
    body = []
    for url in sorted(entries):
        relative = entries[url].relative_to(site).as_posix()
        lastmod = (
            today
            if relative in dirty_paths or url not in previous
            else previous[url]
        )
        body.append(
            f"  <url><loc>{html.escape(url)}</loc>"
            f"<lastmod>{lastmod}</lastmod></url>"
        )
    body.extend(managed_blocks)
    updated = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(body)
        + "\n</urlset>\n"
    )
    return _write_if_changed(path, updated)


def validate_root_roster(
    site: Path,
    contract: dict[str, Any],
    sources: dict[str, Any],
) -> None:
    expected_slugs = set(contract["root_slugs"].values())
    actual_slugs = {
        path.parent.name
        for path in (site / "app").glob("*/index.html")
    }
    if actual_slugs != expected_slugs:
        raise ValueError(
            "publisher root roster differs: "
            f"missing={sorted(expected_slugs - actual_slugs)}, "
            f"extra={sorted(actual_slugs - expected_slugs)}"
        )
    for key, slug in contract["root_slugs"].items():
        source = _page_path(site, slug, None).read_text(encoding="utf-8")
        app_id = sources["finder"][key]["app_store_id"]
        if app_id not in APP_STORE_URL_RE.findall(source):
            raise ValueError(
                f"publisher root page lacks its App Store identity: {key}"
            )


def validate_home_consistency(
    site: Path,
    contract: dict[str, Any],
    cards: dict[str, dict[str, Any]],
) -> None:
    source = (site / "index.html").read_text(encoding="utf-8")
    og_match = re.search(
        r'property="og:description" content="探索 (\d+) 款獨立 iPhone App',
        source,
    )
    nav_match = APP_NAV_RE.search(source)
    if og_match is None or nav_match is None:
        raise ValueError("home count or app navigation is missing")
    nav_slugs = re.findall(
        r'<a href="/app/([a-z0-9-]+)/">',
        nav_match.group(0),
    )
    root_slugs = {
        path.parent.name
        for path in (site / "app").glob("*/index.html")
    }
    expected_slugs = set(contract["root_slugs"].values())
    counts = {
        "visible_cards": len(cards),
        "og": int(og_match.group(1)),
        "applinks": len(nav_slugs),
        "root_pages": len(root_slugs),
    }
    if (
        set(cards) != set(contract["root_slugs"])
        or set(nav_slugs) != expected_slugs
        or len(nav_slugs) != len(set(nav_slugs))
        or root_slugs != expected_slugs
        or set(counts.values()) != {contract["expected_app_count"]}
        or "const appCount=()=>String(window.APPS.length);" not in source
    ):
        raise PublisherRootBlocked(
            f"BLOCKED home/data.js/root counts differ: {counts}"
        )


class _RenderedPageInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.smart_app_ids: list[str] = []
        self.canonical_urls: list[str] = []
        self.alternates: dict[str, str] = {}
        self.anchors: list[dict[str, str]] = []
        self.json_ld_sources: list[str] = []
        self.visible_text: list[str] = []
        self._script_type = ""
        self._script_parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "meta" and values.get("name") == "apple-itunes-app":
            matched = re.search(r"(?:^|,)\s*app-id=(\d+)", values["content"])
            if matched:
                self.smart_app_ids.append(matched.group(1))
        elif tag == "link":
            rel = set(values.get("rel", "").split())
            if "canonical" in rel:
                self.canonical_urls.append(values.get("href", ""))
            if "alternate" in rel and values.get("hreflang"):
                self.alternates[values["hreflang"]] = values.get("href", "")
        elif tag == "a":
            self.anchors.append(
                {
                    "href": values.get("href", ""),
                    "class": values.get("class", ""),
                }
            )
        elif tag == "script":
            self._script_type = values.get("type", "")
            self._script_parts = []

    def handle_data(self, data: str) -> None:
        if self._script_type:
            self._script_parts.append(data)
        elif data.strip():
            self.visible_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            if self._script_type == "application/ld+json":
                self.json_ld_sources.append("".join(self._script_parts))
            self._script_type = ""
            self._script_parts = []


def _software_application(source: str) -> dict[str, Any]:
    inspector = _RenderedPageInspector()
    inspector.feed(source)
    inspector.close()
    applications = []
    for raw in inspector.json_ld_sources:
        payload = json.loads(raw)
        items = payload if isinstance(payload, list) else [payload]
        applications.extend(
            item
            for item in items
            if isinstance(item, dict)
            and item.get("@type") == "SoftwareApplication"
        )
    if len(applications) != 1:
        raise ValueError("publisher page must contain one SoftwareApplication")
    return applications[0]


def validate_rendered_page(
    source: str,
    *,
    key: str,
    slug: str,
    locale: str,
    canonical_locale: str | None,
    contract: dict[str, Any],
    publisher: dict[str, Any],
    catalog: dict[str, Any],
    ui: dict[str, Any],
) -> None:
    inspector = _RenderedPageInspector()
    inspector.feed(source)
    inspector.close()
    app_id = str(publisher["app_store_id"])
    campaign_url = str(publisher["app_store_url"])
    canonical_url = _page_url(slug, canonical_locale)
    found_ids = set(APP_STORE_URL_RE.findall(source))
    if found_ids != {app_id}:
        raise ValueError(
            f"publisher page contains another App Store ID: {key}/{locale}"
        )
    if inspector.smart_app_ids != [app_id]:
        raise ValueError(
            f"publisher page Smart App Banner drifted: {key}/{locale}"
        )
    if inspector.canonical_urls != [canonical_url]:
        raise ValueError(
            f"publisher page canonical URL drifted: {key}/{locale}"
        )
    expected_alternates = {
        item: _page_url(slug, item)
        for item in contract["official_locales"]
    }
    expected_alternates["x-default"] = _page_url(slug, None)
    if inspector.alternates != expected_alternates:
        raise ValueError(
            f"publisher page hreflang drifted: {key}/{locale}"
        )
    cta_hrefs = [
        anchor["href"]
        for anchor in inspector.anchors
        if "cta" in anchor["class"].split()
    ]
    if cta_hrefs != [campaign_url]:
        raise ValueError(
            f"publisher page CTA href drifted: {key}/{locale}"
        )
    application = _software_application(source)
    expected_same_as = [
        publisher["canonical_guide_url"],
        publisher["canonical_app_store_url"],
    ]
    if (
        application.get("installUrl") != campaign_url
        or application.get("downloadUrl") != campaign_url
        or application.get("sameAs") != expected_same_as
    ):
        raise ValueError(
            f"publisher page JSON-LD links drifted: {key}/{locale}"
        )
    offers = application.get("offers")
    purchase_label = ui["purchase_labels"][publisher["purchase_model"]]
    if (
        not isinstance(offers, dict)
        or offers.get("@type") != "Offer"
        or offers.get("url") != campaign_url
        or offers.get("description") != purchase_label
    ):
        raise ValueError(
            f"publisher page JSON-LD offer drifted: {key}/{locale}"
        )
    storefront = catalog.get("storefront_facts")
    if isinstance(storefront, dict) and (
        offers.get("price") != storefront["price"]
        or offers.get("priceCurrency") != storefront["currency"]
    ):
        raise ValueError(
            f"publisher page JSON-LD price drifted: {key}/{locale}"
        )
    if not isinstance(storefront, dict) and (
        "price" in offers or "priceCurrency" in offers
    ):
        raise ValueError(
            f"publisher page JSON-LD unavailable price drifted: {key}/{locale}"
        )
    visible = " ".join(" ".join(inspector.visible_text).split())
    expected_visible = (
        publisher["app_store_cta_label"],
        publisher["publisher_query"],
        publisher["decision_context"],
        publisher["publisher_disclosure"],
        ui["non_ranking_notice"],
        purchase_label,
    )
    if MARKER_PREFIX not in source or any(
        " ".join(str(value).split()) not in visible
        for value in expected_visible
    ):
        raise ValueError(
            f"publisher page visible content drifted: {key}/{locale}"
        )


def validate_supplemental_pages(
    site: Path,
    contract: dict[str, Any],
    sources: dict[str, Any],
) -> None:
    expected_locales = set(contract["official_locales"])
    for key in contract["supplemental_app_keys"]:
        slug = contract["root_slugs"][key]
        locale_dirs = {
            path.parent.name
            for path in (site / "app" / slug).glob("*/index.html")
        }
        if locale_dirs != expected_locales:
            raise ValueError(
                f"supplemental page is not exact50: {key} "
                f"missing={sorted(expected_locales - locale_dirs)} "
                f"extra={sorted(locale_dirs - expected_locales)}"
            )
        targets: list[tuple[str, str | None]] = [
            ("en-US", None),
            *(
                (locale, locale)
                for locale in contract["official_locales"]
            ),
        ]
        for locale, canonical_locale in targets:
            path = _page_path(site, slug, canonical_locale)
            source = path.read_text(encoding="utf-8")
            validate_rendered_page(
                source,
                key=key,
                slug=slug,
                locale=locale,
                canonical_locale=canonical_locale,
                contract=contract,
                publisher=sources["publisher"][locale][key],
                catalog=sources["localized"][locale][key],
                ui=sources["ui"][locale],
            )


def raw_get_plan(
    contract: dict[str, Any],
    sources: dict[str, Any],
) -> dict[str, Any]:
    requests = []
    for key in contract["supplemental_app_keys"]:
        slug = contract["root_slugs"][key]
        targets: list[tuple[str, str | None]] = [
            ("en-US", None),
            *(
                (locale, locale)
                for locale in contract["official_locales"]
            ),
        ]
        for locale, canonical_locale in targets:
            publisher = sources["publisher"][locale][key]
            requests.append(
                {
                    "method": "GET",
                    "app_key": key,
                    "locale": locale,
                    "url": _page_url(slug, canonical_locale),
                    "expected_status": 200,
                    "expected_final_url": _page_url(
                        slug,
                        canonical_locale,
                    ),
                    "expected_app_store_id": publisher["app_store_id"],
                    "expected_campaign_url": publisher["app_store_url"],
                    "expected_canonical_url": _page_url(
                        slug,
                        canonical_locale,
                    ),
                }
            )
    return {
        "schema_version": 1,
        "audit_kind": "publisher-root-post-deploy-raw-get-plan",
        "deployment_performed": False,
        "public_exposure_claimed": False,
        "request_count": len(requests),
        "apps": len(contract["supplemental_app_keys"]),
        "locales_per_app": len(contract["official_locales"]),
        "root_alias_per_app": 1,
        "sources": {
            "canonical_catalog": contract["canonical_catalog_url"],
            "localized_catalog_base": (
                contract["localized_catalog_base_url"]
            ),
            "publisher_dataset": contract["publisher_dataset_url"],
            "publisher_i18n_source": (
                contract["publisher_i18n_source_url"]
            ),
            "publisher_i18n_source_sha256": (
                sources["publisher_i18n_digest"]
            ),
        },
        "requests": requests,
    }


def run(
    *,
    site: Path = ROOT,
    channel_path: Path = CHANNEL_PATH,
    finder_path: Path | None = None,
    publisher_dataset_path: Path | None = None,
    localized_catalog_dir: Path | None = None,
    publisher_i18n_path: Path | None = None,
    raw_get_plan_path: Path | None = None,
    today: str | None = None,
    opener=None,
    sleeper=None,
) -> dict[str, int]:
    contract = load_contract(channel_path)
    sources = load_sources(
        contract,
        finder_path=finder_path,
        publisher_dataset_path=publisher_dataset_path,
        localized_catalog_dir=localized_catalog_dir,
        publisher_i18n_path=publisher_i18n_path,
        opener=opener,
        sleeper=sleeper,
    )
    cards = load_datajs_cards(site, contract, sources)
    _validate_supplemental_eligibility(contract, sources)
    legacy_stats = sync_legacy_pages(site, contract, sources, cards)
    stats = generate_supplemental_pages(site, contract, sources)
    changed_shared = 0
    if rebuild_home(site, contract, sources, cards):
        changed_shared += 1
    if rebuild_llms(site, contract, sources):
        changed_shared += 1
    stable_today = today or date.today().isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stable_today) is None:
        raise ValueError("invalid publisher root build date")
    if rebuild_sitemap(site, contract, today=stable_today):
        changed_shared += 1
    validate_root_roster(site, contract, sources)
    validate_app_owned_pages(site, contract, sources)
    validate_supplemental_pages(site, contract, sources)
    validate_home_consistency(site, contract, cards)
    if raw_get_plan_path is not None:
        _write_if_changed(
            raw_get_plan_path,
            json.dumps(
                raw_get_plan(contract, sources),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
    print(
        "PUBLISHER_ROOT_SYNC "
        f"canonical={contract['expected_app_count']} "
        f"legacy={legacy_stats['apps']}/{legacy_stats['pages']} "
        f"supplements={len(contract['supplemental_app_keys'])} "
        f"app_owned={len(contract['page_management']['app_owned_exact50'])} "
        f"locales={contract['expected_locale_count']} "
        f"pages={stats['pages']} created={stats['created']} "
        f"updated={stats['updated']} unchanged={stats['unchanged']} "
        f"legacy_updated={legacy_stats['updated']} shared={changed_shared}",
        flush=True,
    )
    return {
        **stats,
        "legacy_apps": legacy_stats["apps"],
        "legacy_pages": legacy_stats["pages"],
        "legacy_updated": legacy_stats["updated"],
        "app_owned": len(
            contract["page_management"]["app_owned_exact50"]
        ),
        "shared": changed_shared,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=ROOT)
    parser.add_argument("--channel", type=Path, default=CHANNEL_PATH)
    parser.add_argument("--finder", type=Path)
    parser.add_argument("--publisher-dataset", type=Path)
    parser.add_argument("--localized-catalog-dir", type=Path)
    parser.add_argument("--publisher-i18n", type=Path)
    parser.add_argument("--raw-get-plan", type=Path)
    parser.add_argument("--today")
    args = parser.parse_args()
    run(
        site=args.site.resolve(),
        channel_path=args.channel.resolve(),
        finder_path=args.finder.resolve() if args.finder else None,
        publisher_dataset_path=(
            args.publisher_dataset.resolve()
            if args.publisher_dataset
            else None
        ),
        localized_catalog_dir=(
            args.localized_catalog_dir.resolve()
            if args.localized_catalog_dir
            else None
        ),
        publisher_i18n_path=(
            args.publisher_i18n.resolve()
            if args.publisher_i18n
            else None
        ),
        raw_get_plan_path=(
            args.raw_get_plan.resolve()
            if args.raw_get_plan
            else None
        ),
        today=args.today,
    )


if __name__ == "__main__":
    main()
