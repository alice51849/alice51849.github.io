#!/usr/bin/env python3
"""Generate exact-50 publisher root pages from verified public catalogs."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import hashlib
import html
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


ROOT = Path(__file__).resolve().parents[1]
BASE = "https://alice51849.github.io"
CHANNEL_PATH = Path(__file__).with_name("publisher_root_channel.json")
PUBLISHER_DATASET_FILENAME = (
    "lumi-studio-publisher-search-intent-catalog.json"
)
PUBLISHER_HTML_FILENAME = (
    "lumi-studio-publisher-search-intent-catalog.html"
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
TAG_RE = re.compile(r"<[^>]+>", flags=re.DOTALL)
SECTION_RE = re.compile(
    r'<section class="card"><h2>(?P<heading>.*?)</h2>'
    r"(?P<body>.*?)</section>",
    flags=re.DOTALL,
)
TABLE_RE = re.compile(
    r"<table><thead><tr>(?P<head>.*?)</tr></thead>"
    r"<tbody>(?P<body>.*?)</tbody></table>",
    flags=re.DOTALL,
)
ROW_RE = re.compile(r"<tr>(.*?)</tr>", flags=re.DOTALL)
TH_RE = re.compile(r"<th>(.*?)</th>", flags=re.DOTALL)
TD_RE = re.compile(r"<td>(.*?)</td>", flags=re.DOTALL)
SAFE_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SAFE_CAMPAIGN_RE = re.compile(r"[a-z0-9_]{1,30}")
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


def _plain_text(fragment: str) -> str:
    value = TAG_RE.sub(" ", fragment)
    return " ".join(html.unescape(value).split())


def _request_text(
    url: str,
    *,
    opener=None,
    sleeper=None,
    attempts: int = 3,
) -> str:
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
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            transient = error.code in {408, 429} or 500 <= error.code <= 599
            if not transient or attempt == attempts - 1:
                raise PublisherRootError(
                    f"public GET failed: HTTP {error.code} {url}"
                ) from error
        except (OSError, UnicodeDecodeError) as error:
            if attempt == attempts - 1:
                raise PublisherRootError(
                    f"public GET failed after {attempts} attempts: {url}"
                ) from error
        sleeper(2 * (attempt + 1))
    raise AssertionError("unreachable")


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
    if (
        payload.get("schema_version") != 1
        or payload.get("expected_app_count") != 46
        or payload.get("expected_locale_count") != 50
        or not isinstance(root_slugs, dict)
        or not isinstance(locales, list)
        or not isinstance(supplements, list)
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
        "publisher_locale_page_base_url",
    ):
        value = payload.get(field)
        if (
            not isinstance(value, str)
            or not value.startswith("https://alice51849.github.io/")
        ):
            raise ValueError(f"invalid publisher root source URL: {field}")
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


def _publisher_locale_ui(
    source: str,
    records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    first_party_heading = ""
    non_ranking_notice = ""
    for match in SECTION_RE.finditer(source):
        paragraphs = re.findall(
            r"<p(?:\s+[^>]*)?>(.*?)</p>",
            match.group("body"),
            flags=re.DOTALL,
        )
        if len(paragraphs) < 2:
            continue
        disclosure = _plain_text(paragraphs[0])
        if "Lumi Studio" in disclosure:
            first_party_heading = _plain_text(match.group("heading"))
            non_ranking_notice = _plain_text(paragraphs[1])
            break
    if (
        len(first_party_heading) < 3
        or len(non_ranking_notice) < 20
    ):
        raise ValueError("localized first-party/non-ranking copy is missing")

    table = TABLE_RE.search(source)
    if table is None:
        raise ValueError("localized publisher table is missing")
    headers = [_plain_text(value) for value in TH_RE.findall(table["head"])]
    if len(headers) != 6 or any(not value for value in headers):
        raise ValueError("localized publisher table headings are invalid")
    rows: dict[str, dict[str, str]] = {}
    for row in ROW_RE.findall(table["body"]):
        cells = [_plain_text(value) for value in TD_RE.findall(row)]
        if len(cells) != 6 or not cells[0]:
            continue
        rows[cells[0]] = {
            "purchase_label": cells[3],
            "guide_label": cells[4],
            "app_store_label": cells[5],
        }
    for record in records.values():
        name = str(record["app_name"])
        labels = rows.get(name)
        if (
            labels is None
            or len(labels["purchase_label"]) < 2
            or len(labels["guide_label"]) < 2
            or len(labels["app_store_label"]) < 2
        ):
            raise ValueError(
                f"localized publisher row labels are missing: {name}"
            )
    return {
        "headers": headers,
        "first_party_heading": first_party_heading,
        "non_ranking_notice": non_ranking_notice,
        "rows": rows,
    }


def load_sources(
    contract: dict[str, Any],
    *,
    finder_path: Path | None = None,
    publisher_dataset_path: Path | None = None,
    localized_catalog_dir: Path | None = None,
    publisher_pages_dir: Path | None = None,
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

    def load_locale(locale: str) -> tuple[str, object, str]:
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
        page_path = (
            publisher_pages_dir
            / locale
            / "data"
            / PUBLISHER_HTML_FILENAME
            if publisher_pages_dir is not None
            else None
        )
        page = (
            page_path.read_text(encoding="utf-8")
            if page_path is not None
            else _request_text(
                (
                    f"{contract['publisher_locale_page_base_url']}/{locale}/"
                    f"data/{PUBLISHER_HTML_FILENAME}"
                ),
                opener=opener,
                sleeper=sleeper,
            )
        )
        return locale, catalog, page

    localized_payloads: dict[str, object] = {}
    publisher_pages: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        for locale, catalog, page in executor.map(
            load_locale,
            contract["official_locales"],
        ):
            localized_payloads[locale] = catalog
            publisher_pages[locale] = page
    localized = _localized_records(
        localized_payloads,
        contract,
        finder,
    )
    ui = {
        locale: _publisher_locale_ui(
            publisher_pages[locale],
            publisher[locale],
        )
        for locale in contract["official_locales"]
    }
    return {
        "finder": finder,
        "localized": localized,
        "publisher": publisher,
        "ui": ui,
        "modified": modified,
    }


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
                    "row": ui["rows"][publisher["app_name"]],
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
    row = ui["rows"][publisher["app_name"]]
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
            "description": row["purchase_label"],
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
<header><a class="brand" href="/">Lumi Studio</a><a href="{html.escape(publisher['canonical_guide_url'], quote=True)}">{html.escape(row['guide_label'])}</a></header>
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
<div class="price"><span>{html.escape(row['purchase_label'])}</span>{price_html}</div>
<div class="actions">
<a class="cta" href="{html.escape(campaign_url, quote=True)}" rel="noopener">{html.escape(str(publisher['app_store_cta_label']))}</a>
<a class="guide" href="{html.escape(str(publisher['canonical_guide_url']), quote=True)}">↗ {html.escape(row['guide_label'])}: {html.escape(str(publisher['app_name']))}</a>
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
        rf"\g<1>{contract['expected_app_count']}\g<2>",
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
            publisher = sources["publisher"][locale][key]
            expected = (
                publisher["app_store_id"],
                publisher["app_store_url"],
                publisher["canonical_guide_url"],
                publisher["publisher_query"],
                publisher["decision_context"],
                publisher["publisher_disclosure"],
                sources["ui"][locale]["non_ranking_notice"],
            )
            if MARKER_PREFIX not in source or any(
                html.escape(str(value), quote=True) not in source
                and html.escape(str(value)) not in source
                for value in expected
            ):
                raise ValueError(
                    f"supplemental publisher page drifted: {key}/{locale}"
                )
            for hreflang in contract["official_locales"]:
                needle = (
                    f'hreflang="{hreflang}" '
                    f'href="{_page_url(slug, hreflang)}"'
                )
                if needle not in source:
                    raise ValueError(
                        f"supplemental hreflang is missing: "
                        f"{key}/{locale}/{hreflang}"
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
            "publisher_locale_page_base": (
                contract["publisher_locale_page_base_url"]
            ),
            "publisher_i18n_source_sha256": (
                contract["publisher_i18n_source_sha256"]
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
    publisher_pages_dir: Path | None = None,
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
        publisher_pages_dir=publisher_pages_dir,
        opener=opener,
        sleeper=sleeper,
    )
    _validate_supplemental_eligibility(contract, sources)
    stats = generate_supplemental_pages(site, contract, sources)
    changed_shared = 0
    if rebuild_home(site, contract, sources):
        changed_shared += 1
    if rebuild_llms(site, contract, sources):
        changed_shared += 1
    stable_today = today or date.today().isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stable_today) is None:
        raise ValueError("invalid publisher root build date")
    if rebuild_sitemap(site, contract, today=stable_today):
        changed_shared += 1
    validate_root_roster(site, contract, sources)
    validate_supplemental_pages(site, contract, sources)
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
        f"supplements={len(contract['supplemental_app_keys'])} "
        f"locales={contract['expected_locale_count']} "
        f"pages={stats['pages']} created={stats['created']} "
        f"updated={stats['updated']} unchanged={stats['unchanged']} "
        f"shared={changed_shared}",
        flush=True,
    )
    return {**stats, "shared": changed_shared}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=ROOT)
    parser.add_argument("--channel", type=Path, default=CHANNEL_PATH)
    parser.add_argument("--finder", type=Path)
    parser.add_argument("--publisher-dataset", type=Path)
    parser.add_argument("--localized-catalog-dir", type=Path)
    parser.add_argument("--publisher-pages-dir", type=Path)
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
        publisher_pages_dir=(
            args.publisher_pages_dir.resolve()
            if args.publisher_pages_dir
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
