#!/usr/bin/env python3
"""Validate dB Halo exact-50 localization, generated pages, and sitemaps."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_db_halo_site as generator  # noqa: E402


NOTIFICATION_FALSE_CLAIMS_PATH = (
    ROOT / ".github" / "fixtures" / "db_halo_notification_false_claims.json"
)
PLACEHOLDER_PATTERN = re.compile(
    r"(?:\bTODO\b|\bTBD\b|(?i:lorem ipsum)|\{\{|\}\}|"
    r"(?i:\b(?:nav|support|privacy|meta|section)\.[a-z][a-z0-9_.-]*))"
)
EMAIL_PATTERN = re.compile(
    r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
)
HARDCODED_PRICE_PATTERN = re.compile(
    r"(?i)(?:US\$|\$|USD|EUR|GBP|CAD|AUD|€|£)\s*\d"
)
SCRIPT_PATTERNS = {
    "ar-SA": re.compile(r"[\u0600-\u06ff]"),
    "bn-BD": re.compile(r"[\u0980-\u09ff]"),
    "zh-Hans": re.compile(r"[\u3400-\u9fff]"),
    "zh-Hant": re.compile(r"[\u3400-\u9fff]"),
    "el": re.compile(r"[\u0370-\u03ff]"),
    "gu-IN": re.compile(r"[\u0a80-\u0aff]"),
    "he": re.compile(r"[\u0590-\u05ff]"),
    "hi": re.compile(r"[\u0900-\u097f]"),
    "ja": re.compile(r"[\u3040-\u30ff\u3400-\u9fff]"),
    "kn-IN": re.compile(r"[\u0c80-\u0cff]"),
    "ko": re.compile(r"[\uac00-\ud7af]"),
    "ml-IN": re.compile(r"[\u0d00-\u0d7f]"),
    "mr-IN": re.compile(r"[\u0900-\u097f]"),
    "or-IN": re.compile(r"[\u0b00-\u0b7f]"),
    "pa-IN": re.compile(r"[\u0a00-\u0a7f]"),
    "ru": re.compile(r"[\u0400-\u04ff]"),
    "ta-IN": re.compile(r"[\u0b80-\u0bff]"),
    "te-IN": re.compile(r"[\u0c00-\u0c7f]"),
    "th": re.compile(r"[\u0e00-\u0e7f]"),
    "uk": re.compile(r"[\u0400-\u04ff]"),
    "ur-PK": re.compile(r"[\u0600-\u06ff]"),
}


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def walk_strings(value: Any, path: str = ""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk_strings(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from walk_strings(item, f"{path}.{key}" if path else key)


def load_notification_false_claims() -> dict[str, str]:
    claims = json.loads(
        NOTIFICATION_FALSE_CLAIMS_PATH.read_text(encoding="utf-8")
    )
    if set(claims) != set(generator.OFFICIAL_LOCALES):
        raise ValueError("notification false-claim fixture must be exact-50")
    if any(not isinstance(value, str) or not value for value in claims.values()):
        raise ValueError("notification false-claim fixture contains invalid text")
    return claims


class PageInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.html_attrs: dict[str, str] = {}
        self.canonicals: list[str] = []
        self.alternates: dict[str, list[str]] = {}
        self.csp: list[str] = []
        self.og: dict[str, list[str]] = {}
        self.anchor_hrefs: list[str] = []
        self.fact_ids: list[str] = []
        self.topic_ids: list[str] = []
        self.permission_ids: list[str] = []
        self.scripts = 0
        self._skip_text_depth = 0
        self.visible_text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if tag == "html":
            self.html_attrs = values
        elif tag == "link":
            rel = values.get("rel", "")
            if rel == "canonical":
                self.canonicals.append(values.get("href", ""))
            elif rel == "alternate":
                lang = values.get("hreflang", "")
                self.alternates.setdefault(lang, []).append(
                    values.get("href", "")
                )
        elif tag == "meta":
            if values.get("http-equiv") == "Content-Security-Policy":
                self.csp.append(values.get("content", ""))
            prop = values.get("property", "")
            if prop.startswith("og:"):
                self.og.setdefault(prop, []).append(values.get("content", ""))
        elif tag == "a":
            self.anchor_hrefs.append(values.get("href", ""))
        elif tag == "script":
            self.scripts += 1
            self._skip_text_depth += 1
        elif tag == "style":
            self._skip_text_depth += 1
        if "data-fact" in values:
            self.fact_ids.append(values["data-fact"])
        if "data-topic" in values:
            self.topic_ids.append(values["data-topic"])
        if "data-permission" in values:
            self.permission_ids.append(values["data-permission"])

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_text_depth:
            self._skip_text_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_text_depth and data.strip():
            self.visible_text.append(data.strip())


def local_href_to_path(href: str) -> Path | None:
    if not href.startswith(generator.SITE_PATH):
        return None
    parsed = urlparse(href)
    relative = parsed.path.lstrip("/")
    path = ROOT / relative
    if parsed.path.endswith("/"):
        path /= "index.html"
    return path


def validate_translation_schema(
    translations: dict[str, dict[str, Any]],
    notification_false_claims: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    english = translations["en-US"]
    for locale in generator.OFFICIAL_LOCALES:
        data = translations[locale]
        source_path = generator.LOCALES_ROOT / f"{locale}.json"
        if not data.get("languageName"):
            errors.append(f"{source_path}: missing languageName")
        if len(data.get("support", {}).get("features", [])) != (
            generator.SUPPORT_FEATURE_COUNT
        ):
            errors.append(f"{source_path}: support features must total 6")
        if len(data.get("support", {}).get("quickStart", [])) != (
            generator.SUPPORT_STEP_COUNT
        ):
            errors.append(f"{source_path}: quick-start steps must total 4")
        if len(data.get("support", {}).get("permissions", [])) != (
            generator.SUPPORT_PERMISSION_COUNT
        ):
            errors.append(
                f"{source_path}: permissions must total "
                f"{generator.SUPPORT_PERMISSION_COUNT}"
            )
        false_claim = notification_false_claims[locale]
        if any(
            false_claim in value
            for _field, value in walk_strings(data.get("support", {}))
        ):
            errors.append(
                f"{source_path}: removed notification permission claim returned"
            )
        if len(data.get("support", {}).get("troubleshooting", [])) != (
            generator.SUPPORT_TROUBLESHOOTING_COUNT
        ):
            errors.append(f"{source_path}: troubleshooting items must total 4")
        section_ids = set(data.get("privacy", {}).get("sections", {}))
        if section_ids != set(generator.PRIVACY_FACT_IDS):
            errors.append(
                f"{source_path}: privacy fact IDs differ; "
                f"missing={sorted(set(generator.PRIVACY_FACT_IDS) - section_ids)}, "
                f"extra={sorted(section_ids - set(generator.PRIVACY_FACT_IDS))}"
            )

        for field, value in walk_strings(data):
            if not value.strip():
                errors.append(f"{source_path}:{field}: empty text")
            if PLACEHOLDER_PATTERN.search(value):
                errors.append(f"{source_path}:{field}: placeholder/raw key")
            script_pattern = SCRIPT_PATTERNS.get(locale)
            if (
                script_pattern
                and len(value) >= 40
                and not script_pattern.search(value)
            ):
                errors.append(
                    f"{source_path}:{field}: lacks expected native script"
                )

        if locale not in {"en-AU", "en-CA", "en-GB", "en-US"}:
            english_values = {
                field: value for field, value in walk_strings(english)
            }
            for field, value in walk_strings(data):
                if (
                    field in english_values
                    and len(value.split()) >= 5
                    and value == english_values[field]
                ):
                    errors.append(
                        f"{source_path}:{field}: exact English fallback"
                    )
    return errors


def validate_html(
    path: Path,
    *,
    expected_locale: str,
    expected_dir: str,
    expected_canonical: str,
    expected_x_default: str,
    privacy: bool,
    forbidden_notification_claim: str | None = None,
) -> list[str]:
    errors: list[str] = []
    source = path.read_text(encoding="utf-8")
    inspector = PageInspector()
    inspector.feed(source)
    label = str(path.relative_to(ROOT))

    if inspector.html_attrs.get("lang") != expected_locale:
        errors.append(f"{label}: incorrect html lang")
    if inspector.html_attrs.get("dir") != expected_dir:
        errors.append(f"{label}: incorrect html dir")
    if inspector.canonicals != [expected_canonical]:
        errors.append(f"{label}: incorrect canonical")
    expected_hreflangs = set(generator.OFFICIAL_LOCALES) | {"x-default"}
    if set(inspector.alternates) != expected_hreflangs:
        errors.append(f"{label}: hreflang set is not exact-50 + x-default")
    for hreflang, urls in inspector.alternates.items():
        if len(urls) != 1:
            errors.append(f"{label}: duplicate hreflang {hreflang}")
    if inspector.alternates.get("x-default") != [expected_x_default]:
        errors.append(f"{label}: incorrect x-default")
    required_og = {
        "og:type",
        "og:site_name",
        "og:title",
        "og:description",
        "og:url",
    }
    if set(inspector.og) != required_og:
        errors.append(f"{label}: incomplete or unexpected OpenGraph fields")
    if inspector.og.get("og:url") != [expected_canonical]:
        errors.append(f"{label}: incorrect og:url")
    if len(inspector.csp) != 1:
        errors.append(f"{label}: missing or duplicate CSP")
    else:
        csp = inspector.csp[0]
        for directive in (
            "default-src 'none'",
            "script-src 'none'",
            "connect-src 'none'",
            "object-src 'none'",
            "base-uri 'none'",
        ):
            if directive not in csp:
                errors.append(f"{label}: CSP lacks {directive}")
    if inspector.scripts:
        errors.append(f"{label}: scripts are not allowed")

    visible = " ".join(inspector.visible_text)
    if PLACEHOLDER_PATTERN.search(visible):
        errors.append(f"{label}: visible placeholder/raw key")
    emails = set(EMAIL_PATTERN.findall(source))
    if emails != {generator.EMAIL}:
        errors.append(f"{label}: public email set is {sorted(emails)}")
    if not privacy and HARDCODED_PRICE_PATTERN.search(visible):
        errors.append(f"{label}: support page hard-codes a price")
    if forbidden_notification_claim and forbidden_notification_claim in source:
        errors.append(f"{label}: removed notification permission claim returned")
    if privacy:
        expected_facts = list(generator.PRIVACY_FACT_IDS) + ["contact"]
        if inspector.fact_ids != expected_facts:
            errors.append(f"{label}: privacy fact coverage/order is incomplete")
    else:
        required_topics = {
            "product",
            "features",
            "quick-start",
            "permissions",
            "lifetime-pro",
            "troubleshooting",
            "accuracy",
            "contact",
        }
        if set(inspector.topic_ids) != required_topics:
            errors.append(f"{label}: support topic coverage is incomplete")
        if inspector.permission_ids != list(generator.SUPPORT_PERMISSION_IDS):
            errors.append(
                f"{label}: permission items must be exact "
                f"{list(generator.SUPPORT_PERMISSION_IDS)}"
            )

    for href in inspector.anchor_hrefs:
        if href.startswith(("mailto:", "#")):
            continue
        if href == "/":
            continue
        target = local_href_to_path(href)
        if target is None:
            errors.append(f"{label}: external or invalid anchor {href}")
        elif not target.exists():
            errors.append(f"{label}: broken internal link {href}")
    return errors


def sitemap_locations(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [
        node.text or ""
        for node in root.findall("sm:url/sm:loc", namespace)
    ]


def main() -> None:
    errors: list[str] = []
    translations = generator.load_translations()
    notification_false_claims = load_notification_false_claims()
    errors.extend(
        validate_translation_schema(
            translations,
            notification_false_claims,
        )
    )

    expected_outputs = generator.render_site(translations)
    for path, expected in expected_outputs.items():
        label = str(path.relative_to(ROOT))
        if not path.exists():
            errors.append(f"{label}: missing")
            continue
        actual = path.read_bytes()
        expected_bytes = expected.encode("utf-8")
        if actual != expected_bytes:
            errors.append(
                f"{label}: generated hash mismatch "
                f"{digest(actual)} != {digest(expected_bytes)}"
            )

    expected_html = {
        path.resolve()
        for path in expected_outputs
        if path.suffix == ".html"
    }
    actual_html = {
        path.resolve()
        for path in generator.SITE_ROOT.rglob("*.html")
    }
    if actual_html != expected_html:
        errors.append(
            "db-halo HTML file set differs from generated set; "
            f"missing={sorted(str(p) for p in expected_html - actual_html)}, "
            f"extra={sorted(str(p) for p in actual_html - expected_html)}"
        )

    root_page = generator.SITE_ROOT / "index.html"
    root_source = root_page.read_text(encoding="utf-8")
    root_inspector = PageInspector()
    root_inspector.feed(root_source)
    if root_inspector.html_attrs != {"lang": "en-US", "dir": "ltr"}:
        errors.append("db-halo/index.html: incorrect html attributes")
    if set(root_inspector.alternates) != (
        set(generator.OFFICIAL_LOCALES) | {"x-default"}
    ):
        errors.append("db-halo/index.html: hreflang is not exact-50 + x-default")
    if root_inspector.scripts:
        errors.append("db-halo/index.html: scripts are not allowed")
    for locale in generator.OFFICIAL_LOCALES:
        href = f"{generator.SITE_PATH}/{locale}/"
        if href not in root_inspector.anchor_hrefs:
            errors.append(f"db-halo/index.html: missing chooser link {locale}")

    for locale in generator.OFFICIAL_LOCALES:
        data = translations[locale]
        errors.extend(
            validate_html(
                generator.page_path(locale),
                expected_locale=locale,
                expected_dir=data["dir"],
                expected_canonical=generator.canonical_url(locale),
                expected_x_default=generator.canonical_url(),
                privacy=False,
                forbidden_notification_claim=notification_false_claims[locale],
            )
        )
        errors.extend(
            validate_html(
                generator.page_path(locale, privacy=True),
                expected_locale=locale,
                expected_dir=data["dir"],
                expected_canonical=generator.canonical_url(
                    locale, privacy=True
                ),
                expected_x_default=generator.canonical_url(
                    "en-US", privacy=True
                ),
                privacy=True,
            )
        )

    expected_urls = generator.sitemap_urls()
    site_locations = sitemap_locations(generator.SITE_ROOT / "sitemap.xml")
    if site_locations != expected_urls:
        errors.append("db-halo/sitemap.xml: URL order/content is incomplete")
    if len(site_locations) != len(set(site_locations)):
        errors.append("db-halo/sitemap.xml: duplicate URLs")

    root_index = (ROOT / "index.html").read_text(encoding="utf-8")
    try:
        if generator.merge_root_index(root_index) != root_index:
            errors.append("index.html: dB Halo link block is missing or stale")
    except ValueError as error:
        errors.append(f"index.html: {error}")
    root_sitemap = ROOT / "sitemap.xml"
    root_locations = sitemap_locations(root_sitemap)
    for url in expected_urls:
        if root_locations.count(url) != 1:
            errors.append(f"sitemap.xml: expected exactly one {url}")
    root_sitemap_source = root_sitemap.read_text(encoding="utf-8")
    try:
        if generator.merge_root_sitemap(root_sitemap_source) != root_sitemap_source:
            errors.append("sitemap.xml: dB Halo block is missing or stale")
    except ValueError as error:
        errors.append(f"sitemap.xml: {error}")

    css = (generator.SITE_ROOT / "style.css").read_text(encoding="utf-8")
    if re.search(r"(?i)@import|@font-face|url\(\s*['\"]?https?://", css):
        errors.append("db-halo/style.css: external font or stylesheet reference")

    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors))
        raise SystemExit(1)
    print(
        "PASS: dB Halo exact-50 site has 50 support pages, 50 privacy "
        "pages, deterministic bytes/hashes, valid links, and complete sitemaps."
    )


if __name__ == "__main__":
    main()
