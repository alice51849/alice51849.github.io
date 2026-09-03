#!/usr/bin/env python3
"""Generate the exact-50 localized dB Halo support and privacy site."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import re
from typing import Any

from managed_blocks import (
    DB_HALO_SITEMAP_END,
    DB_HALO_SITEMAP_START,
    exact_block_span,
)


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "db-halo"
LOCALES_ROOT = SITE_ROOT / "locales"
BASE_URL = "https://open.cait518.cc"
SITE_PATH = "/db-halo"
EMAIL = "hourstag.app@gmail.com"
LASTMOD = "2026-08-29"

OFFICIAL_LOCALES = (
    "ar-SA",
    "bn-BD",
    "ca",
    "zh-Hans",
    "zh-Hant",
    "hr",
    "cs",
    "da",
    "nl-NL",
    "en-AU",
    "en-CA",
    "en-GB",
    "en-US",
    "fi",
    "fr-CA",
    "fr-FR",
    "de-DE",
    "el",
    "gu-IN",
    "he",
    "hi",
    "hu",
    "id",
    "it",
    "ja",
    "kn-IN",
    "ko",
    "ms",
    "ml-IN",
    "mr-IN",
    "no",
    "or-IN",
    "pl",
    "pt-BR",
    "pt-PT",
    "pa-IN",
    "ro",
    "ru",
    "sk",
    "sl-SI",
    "es-MX",
    "es-ES",
    "sv",
    "ta-IN",
    "te-IN",
    "th",
    "tr",
    "uk",
    "ur-PK",
    "vi",
)
RTL_LOCALES = {"ar-SA", "he", "ur-PK"}

SUPPORT_FEATURE_COUNT = 6
SUPPORT_STEP_COUNT = 4
SUPPORT_PERMISSION_IDS = ("microphone", "photos", "health")
SUPPORT_PERMISSION_COUNT = len(SUPPORT_PERMISSION_IDS)
SUPPORT_TROUBLESHOOTING_COUNT = 4
PRIVACY_FACT_IDS = (
    "no-account-ads-analytics-tracking",
    "live-audio-memory-only",
    "sleep-events-and-explicit-aac",
    "photos-picker-local-processing",
    "healthkit-write-only",
    "local-history-calibration-trial",
    "apple-platform-services",
    "user-directed-files-share",
    "support-email-exception",
    "deletion-and-retention",
    "children-medical-workplace",
    "effective-and-updated",
)

ROOT_INDEX_LINK = '<a href="/db-halo/">dB Halo</a>'
ROOT_INDEX_START = "    <!-- db-halo-link:start -->"
ROOT_INDEX_END = "    <!-- db-halo-link:end -->"
ROOT_INDEX_INSERTION_ANCHOR = '    <div class="copy">'
ROOT_INDEX_HREF_RE = re.compile(
    r"""href\s*=\s*(["'])/db-halo/\1""",
    flags=re.IGNORECASE,
)
ROOT_SITEMAP_START = DB_HALO_SITEMAP_START
ROOT_SITEMAP_END = DB_HALO_SITEMAP_END


def escape(value: str) -> str:
    return html.escape(value, quote=True)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_translations() -> dict[str, dict[str, Any]]:
    paths = sorted(LOCALES_ROOT.glob("*.json"))
    found = {path.stem for path in paths}
    expected = set(OFFICIAL_LOCALES)
    if found != expected:
        missing = sorted(expected - found)
        extra = sorted(found - expected)
        raise ValueError(
            f"Locale sources must be exact-50; missing={missing}, extra={extra}"
        )

    translations: dict[str, dict[str, Any]] = {}
    for locale in OFFICIAL_LOCALES:
        path = LOCALES_ROOT / f"{locale}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("locale") != locale:
            raise ValueError(f"{path}: locale field must equal {locale}")
        expected_dir = "rtl" if locale in RTL_LOCALES else "ltr"
        if data.get("dir") != expected_dir:
            raise ValueError(f"{path}: dir must equal {expected_dir}")
        translations[locale] = data
    return translations


def canonical_url(locale: str | None = None, *, privacy: bool = False) -> str:
    if locale is None:
        return f"{BASE_URL}{SITE_PATH}/"
    suffix = "privacy/" if privacy else ""
    return f"{BASE_URL}{SITE_PATH}/{locale}/{suffix}"


def page_path(locale: str, *, privacy: bool = False) -> Path:
    if privacy:
        return SITE_ROOT / locale / "privacy" / "index.html"
    return SITE_ROOT / locale / "index.html"


def sitemap_urls() -> list[str]:
    urls = [canonical_url()]
    for locale in OFFICIAL_LOCALES:
        urls.append(canonical_url(locale))
        urls.append(canonical_url(locale, privacy=True))
    return urls


def hreflang_links(*, privacy: bool) -> str:
    lines = []
    for locale in OFFICIAL_LOCALES:
        lines.append(
            '  <link rel="alternate" hreflang="{}" href="{}">'.format(
                locale, canonical_url(locale, privacy=privacy)
            )
        )
    x_default = (
        canonical_url("en-US", privacy=True) if privacy else canonical_url()
    )
    lines.append(
        f'  <link rel="alternate" hreflang="x-default" href="{x_default}">'
    )
    return "\n".join(lines)


def language_menu(
    translations: dict[str, dict[str, Any]],
    current_locale: str | None,
    *,
    privacy: bool,
    label: str,
) -> str:
    links = []
    for locale in OFFICIAL_LOCALES:
        data = translations[locale]
        suffix = "/privacy/" if privacy else "/"
        current = ' aria-current="page"' if locale == current_locale else ""
        links.append(
            '<a lang="{locale}" dir="{direction}" href="{path}"{current}>'
            "{name}</a>".format(
                locale=locale,
                direction=data["dir"],
                path=f"{SITE_PATH}/{locale}{suffix}",
                current=current,
                name=escape(data["languageName"]),
            )
        )
    return (
        '<details class="language-menu">'
        f"<summary>{escape(label)}</summary>"
        '<div class="language-grid">'
        + "".join(links)
        + "</div></details>"
    )


def head(
    *,
    locale: str,
    direction: str,
    title: str,
    description: str,
    privacy: bool,
) -> str:
    css_path = "../../style.css" if privacy else "../style.css"
    canonical = canonical_url(locale, privacy=privacy)
    return f"""<!doctype html>
<html lang="{locale}" dir="{direction}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'self'; img-src 'self' data:; font-src 'none'; script-src 'none'; connect-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'; manifest-src 'none'; upgrade-insecure-requests">
  <title>{escape(title)}</title>
  <meta name="description" content="{escape(description)}">
  <meta name="theme-color" content="#f8f5ff">
  <link rel="canonical" href="{canonical}">
{hreflang_links(privacy=privacy)}
  <link rel="sitemap" type="application/xml" href="{css_path.replace('style.css', 'sitemap.xml')}">
  <link rel="stylesheet" href="{css_path}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="dB Halo">
  <meta property="og:title" content="{escape(title)}">
  <meta property="og:description" content="{escape(description)}">
  <meta property="og:url" content="{canonical}">
</head>"""


def header(
    data: dict[str, Any],
    translations: dict[str, dict[str, Any]],
    *,
    locale: str,
    privacy: bool,
) -> str:
    ui = data["ui"]
    support_href = f"{SITE_PATH}/{locale}/"
    privacy_href = f"{SITE_PATH}/{locale}/privacy/"
    nav_links = (
        f'<a href="{support_href}">{escape(ui["support"])}</a>'
        if privacy
        else f'<a href="{privacy_href}">{escape(ui["privacy"])}</a>'
    )
    return f"""<body>
  <a class="skip-link" href="#main-content">{escape(ui["skip"])}</a>
  <header class="site-header">
    <div class="shell nav">
      <a class="brand" href="{support_href}" aria-label="{escape(ui["brandHome"])}">
        <span class="brand-mark" aria-hidden="true"><span></span></span>
        <span>dB Halo</span>
      </a>
      <nav class="nav-links" aria-label="{escape(ui["navigation"])}">
        {nav_links}
        <a href="mailto:{EMAIL}">{escape(ui["email"])}</a>
      </nav>
    </div>
    <div class="shell locale-row">
      {language_menu(translations, locale, privacy=privacy, label=ui["language"])}
    </div>
  </header>"""


def footer(data: dict[str, Any], *, locale: str, privacy: bool) -> str:
    ui = data["ui"]
    support_href = f"{SITE_PATH}/{locale}/"
    privacy_href = f"{SITE_PATH}/{locale}/privacy/"
    return f"""  <footer>
    <div class="shell footer-row">
      <span>&copy; 2026 Lumi Studio</span>
      <nav aria-label="{escape(ui["footerNavigation"])}">
        <a href="{support_href}">{escape(ui["support"])}</a>
        <a href="{privacy_href}">{escape(ui["privacy"])}</a>
        <a href="/">{escape(ui["allApps"])}</a>
      </nav>
    </div>
  </footer>
</body>
</html>
"""


def render_support(
    locale: str,
    data: dict[str, Any],
    translations: dict[str, dict[str, Any]],
) -> str:
    support = data["support"]
    features = "\n".join(
        f"""        <article class="feature-card">
          <h3>{escape(item["title"])}</h3>
          <p>{escape(item["body"])}</p>
        </article>"""
        for item in support["features"]
    )
    steps = "\n".join(
        f"<li>{escape(item)}</li>" for item in support["quickStart"]
    )
    if len(support["permissions"]) != SUPPORT_PERMISSION_COUNT:
        raise ValueError(
            f"{locale}: permissions must total {SUPPORT_PERMISSION_COUNT}"
        )
    permissions = "\n".join(
        f'<li data-permission="{permission_id}">{escape(item)}</li>'
        for permission_id, item in zip(
            SUPPORT_PERMISSION_IDS,
            support["permissions"],
        )
    )
    troubleshooting = "\n".join(
        f"<li>{escape(item)}</li>" for item in support["troubleshooting"]
    )
    badges = "".join(
        f"<li>{escape(item)}</li>" for item in support["badges"]
    )
    title = f'{support["title"]} | dB Halo'
    return (
        head(
            locale=locale,
            direction=data["dir"],
            title=title,
            description=support["metaDescription"],
            privacy=False,
        )
        + "\n"
        + header(
            data,
            translations,
            locale=locale,
            privacy=False,
        )
        + f"""
  <main id="main-content">
    <section class="hero shell" data-topic="product">
      <div class="hero-copy">
        <p class="eyebrow">{escape(support["kicker"])}</p>
        <h1>{escape(support["title"])}</h1>
        <p class="lead">{escape(support["intro"])}</p>
        <ul class="trust-list">{badges}</ul>
      </div>
      <div class="halo-stage" aria-hidden="true">
        <div class="halo-ring">
          <div class="halo-core"><strong>64</strong><span>dB</span></div>
          <i class="wave wave-one"></i><i class="wave wave-two"></i><i class="wave wave-three"></i>
        </div>
      </div>
    </section>

    <section class="section shell" data-topic="features">
      <p class="eyebrow">{escape(support["featuresEyebrow"])}</p>
      <h2>{escape(support["featuresTitle"])}</h2>
      <div class="feature-grid">
{features}
      </div>
    </section>

    <section class="section shell split">
      <article class="panel" data-topic="quick-start">
        <p class="eyebrow">01</p>
        <h2>{escape(support["quickStartTitle"])}</h2>
        <ol>{steps}</ol>
      </article>
      <article class="panel" data-topic="permissions">
        <p class="eyebrow">02</p>
        <h2>{escape(support["permissionsTitle"])}</h2>
        <ul>{permissions}</ul>
      </article>
      <article class="panel" data-topic="lifetime-pro">
        <p class="eyebrow">03</p>
        <h2>{escape(support["proTitle"])}</h2>
        <p>{escape(support["proBody"])}</p>
      </article>
      <article class="panel" data-topic="troubleshooting">
        <p class="eyebrow">04</p>
        <h2>{escape(support["troubleshootingTitle"])}</h2>
        <ul>{troubleshooting}</ul>
      </article>
    </section>

    <section class="section shell">
      <article class="notice" data-topic="accuracy">
        <div>
          <p class="eyebrow">{escape(support["accuracyEyebrow"])}</p>
          <h2>{escape(support["accuracyTitle"])}</h2>
        </div>
        <p>{escape(support["accuracyBody"])}</p>
      </article>
    </section>

    <section class="section shell contact-panel" data-topic="contact">
      <div>
        <p class="eyebrow">{escape(support["contactEyebrow"])}</p>
        <h2>{escape(support["contactTitle"])}</h2>
        <p>{escape(support["contactBody"])}</p>
        <p><a class="email-text" dir="ltr" href="mailto:{EMAIL}">{EMAIL}</a></p>
      </div>
      <a class="primary-button" href="mailto:{EMAIL}">{escape(support["contactButton"])}</a>
    </section>
  </main>
"""
        + footer(data, locale=locale, privacy=False)
    )


def render_privacy(
    locale: str,
    data: dict[str, Any],
    translations: dict[str, dict[str, Any]],
) -> str:
    privacy = data["privacy"]
    sections = "\n".join(
        f"""      <section class="policy-section" data-fact="{fact_id}">
        <h2>{escape(privacy["sections"][fact_id]["title"])}</h2>
        <p>{escape(privacy["sections"][fact_id]["body"])}</p>
      </section>"""
        for fact_id in PRIVACY_FACT_IDS
    )
    title = f'{privacy["title"]} | dB Halo'
    return (
        head(
            locale=locale,
            direction=data["dir"],
            title=title,
            description=privacy["metaDescription"],
            privacy=True,
        )
        + "\n"
        + header(
            data,
            translations,
            locale=locale,
            privacy=True,
        )
        + f"""
  <main id="main-content" class="shell policy">
    <header class="policy-hero">
      <p class="eyebrow">{escape(privacy["kicker"])}</p>
      <h1>{escape(privacy["title"])}</h1>
      <p class="lead">{escape(privacy["intro"])}</p>
      <p class="date-line"><time datetime="{LASTMOD}">{escape(privacy["dateLine"])}</time></p>
    </header>
    <div class="policy-stack">
{sections}
      <section class="policy-section contact-policy" data-fact="contact">
        <h2>{escape(privacy["contactTitle"])}</h2>
        <p>{escape(privacy["contactBody"])}</p>
        <p><a class="email-text" dir="ltr" href="mailto:{EMAIL}">{EMAIL}</a></p>
        <a class="primary-button" href="mailto:{EMAIL}">{escape(privacy["contactButton"])}</a>
      </section>
    </div>
  </main>
"""
        + footer(data, locale=locale, privacy=True)
    )


def render_root(translations: dict[str, dict[str, Any]]) -> str:
    language_links = []
    for locale in OFFICIAL_LOCALES:
        data = translations[locale]
        language_links.append(
            '<a lang="{locale}" dir="{direction}" href="{path}">'
            "<span>{name}</span><small>{locale}</small></a>".format(
                locale=locale,
                direction=data["dir"],
                path=f"{SITE_PATH}/{locale}/",
                name=escape(data["languageName"]),
            )
        )
    links = "\n".join(language_links)
    return f"""<!doctype html>
<html lang="en-US" dir="ltr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'self'; img-src 'self' data:; font-src 'none'; script-src 'none'; connect-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'; manifest-src 'none'; upgrade-insecure-requests">
  <title>dB Halo Support &amp; Privacy</title>
  <meta name="description" content="Choose a language for dB Halo product help, support, and the privacy policy.">
  <meta name="theme-color" content="#f8f5ff">
  <link rel="canonical" href="{canonical_url()}">
{hreflang_links(privacy=False)}
  <link rel="sitemap" type="application/xml" href="sitemap.xml">
  <link rel="stylesheet" href="style.css">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="dB Halo">
  <meta property="og:title" content="dB Halo Support &amp; Privacy">
  <meta property="og:description" content="Choose your language for product help and privacy information.">
  <meta property="og:url" content="{canonical_url()}">
</head>
<body>
  <a class="skip-link" href="#main-content">Skip to language choices</a>
  <header class="site-header">
    <div class="shell nav">
      <a class="brand" href="{SITE_PATH}/" aria-label="dB Halo language home">
        <span class="brand-mark" aria-hidden="true"><span></span></span>
        <span>dB Halo</span>
      </a>
      <nav class="nav-links" aria-label="Site navigation">
        <a href="/">All apps</a>
        <a href="mailto:{EMAIL}">Email support</a>
      </nav>
    </div>
  </header>
  <main id="main-content" class="shell chooser">
    <div class="chooser-copy">
      <p class="eyebrow">Support &amp; privacy</p>
      <h1>Choose your language</h1>
      <p class="lead">Open localized dB Halo help and privacy information. English (US) is available at <a href="{SITE_PATH}/en-US/">the default support page</a>.</p>
    </div>
    <nav class="language-chooser" aria-label="Available languages">
{links}
    </nav>
  </main>
  <footer>
    <div class="shell footer-row">
      <span>&copy; 2026 Lumi Studio</span>
      <nav aria-label="Footer navigation"><a href="/">All apps</a></nav>
    </div>
  </footer>
</body>
</html>
"""


def render_site(
    translations: dict[str, dict[str, Any]],
) -> dict[Path, str]:
    outputs: dict[Path, str] = {
        SITE_ROOT / "index.html": render_root(translations),
        SITE_ROOT / "sitemap.xml": render_site_sitemap(),
    }
    for locale in OFFICIAL_LOCALES:
        data = translations[locale]
        outputs[page_path(locale)] = render_support(
            locale, data, translations
        )
        outputs[page_path(locale, privacy=True)] = render_privacy(
            locale, data, translations
        )
    return outputs


def render_site_sitemap() -> str:
    rows = "\n".join(
        f"  <url><loc>{url}</loc><lastmod>{LASTMOD}</lastmod></url>"
        for url in sitemap_urls()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{rows}\n"
        "</urlset>\n"
    )


def root_sitemap_block() -> str:
    rows = "\n".join(
        f"  <url><loc>{url}</loc><lastmod>{LASTMOD}</lastmod></url>"
        for url in sitemap_urls()
    )
    return f"{ROOT_SITEMAP_START}\n{rows}\n{ROOT_SITEMAP_END}"


def root_index_block() -> str:
    return (
        f"{ROOT_INDEX_START}\n"
        '    <nav class="applinks db-halo-link" '
        f'aria-label="dB Halo support">{ROOT_INDEX_LINK}</nav>\n'
        f"{ROOT_INDEX_END}"
    )


def merge_root_index(source: str) -> str:
    span = exact_block_span(
        source,
        start_marker=ROOT_INDEX_START,
        end_marker=ROOT_INDEX_END,
        label="Root index dB Halo link block",
    )
    if span is not None:
        outside = source[: span[0]] + source[span[1] :]
        if ROOT_INDEX_HREF_RE.search(outside):
            raise ValueError("Root index contains a dB Halo link outside its block")
        return source[: span[0]] + root_index_block() + source[span[1] :]

    href_count = len(ROOT_INDEX_HREF_RE.findall(source))
    if href_count > 1:
        raise ValueError("Root index contains duplicate dB Halo links")
    if href_count == 1:
        if source.count(ROOT_INDEX_LINK) != 1:
            raise ValueError("Root index contains an unmanaged dB Halo link")
        source = source.replace(ROOT_INDEX_LINK, "", 1)
    if source.count(ROOT_INDEX_INSERTION_ANCHOR) != 1:
        raise ValueError("Root index footer insertion anchor must appear once")
    return source.replace(
        ROOT_INDEX_INSERTION_ANCHOR,
        root_index_block() + "\n" + ROOT_INDEX_INSERTION_ANCHOR,
        1,
    )


def merge_root_sitemap(source: str) -> str:
    block = root_sitemap_block()
    span = exact_block_span(
        source,
        start_marker=ROOT_SITEMAP_START,
        end_marker=ROOT_SITEMAP_END,
        label="Root sitemap dB Halo block",
    )
    if span is not None:
        outside = source[: span[0]] + source[span[1] :]
        if any(url in outside for url in sitemap_urls()):
            raise ValueError("Root sitemap contains dB Halo URLs outside its block")
        return source[: span[0]] + block + source[span[1] :]
    closing = "</urlset>"
    if source.count(closing) != 1:
        raise ValueError("Root sitemap must contain one </urlset>")
    if any(url in source for url in sitemap_urls()):
        raise ValueError("Root sitemap contains unmanaged dB Halo URLs")
    insertion = block + "\n"
    return source.replace(closing, insertion + closing, 1)


def write_text(path: Path, content: str) -> bool:
    encoded = content.encode("utf-8")
    if path.exists() and path.read_bytes() == encoded:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return True


def generate() -> dict[str, str]:
    translations = load_translations()
    outputs = render_site(translations)
    root_index_path = ROOT / "index.html"
    root_sitemap_path = ROOT / "sitemap.xml"
    merged_root_index = merge_root_index(
        root_index_path.read_text(encoding="utf-8")
    )
    merged_root_sitemap = merge_root_sitemap(
        root_sitemap_path.read_text(encoding="utf-8")
    )

    for path, content in outputs.items():
        write_text(path, content)
    write_text(root_index_path, merged_root_index)
    write_text(root_sitemap_path, merged_root_sitemap)
    return {
        str(path.relative_to(ROOT)): sha256_text(content)
        for path, content in outputs.items()
    }


def check() -> None:
    translations = load_translations()
    errors: list[str] = []
    for path, expected in render_site(translations).items():
        if not path.exists():
            errors.append(f"missing {path.relative_to(ROOT)}")
            continue
        actual = path.read_bytes()
        expected_bytes = expected.encode("utf-8")
        if actual != expected_bytes:
            errors.append(
                f"stale {path.relative_to(ROOT)} "
                f"(expected {hashlib.sha256(expected_bytes).hexdigest()}, "
                f"got {hashlib.sha256(actual).hexdigest()})"
            )

    root_index = (ROOT / "index.html").read_text(encoding="utf-8")
    try:
        if merge_root_index(root_index) != root_index:
            errors.append("root index dB Halo link block is missing or stale")
    except ValueError as error:
        errors.append(str(error))
    root_sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    try:
        if merge_root_sitemap(root_sitemap) != root_sitemap:
            errors.append("root sitemap dB Halo block is missing or stale")
    except ValueError as error:
        errors.append(str(error))
    if errors:
        raise SystemExit("\n".join(errors))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify generated files without writing them.",
    )
    args = parser.parse_args()
    if args.check:
        check()
        print("dB Halo generated files are current.")
    else:
        hashes = generate()
        print(f"Generated {len(hashes)} dB Halo files.")


if __name__ == "__main__":
    main()
