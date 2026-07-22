#!/usr/bin/env python3
"""Generate the 50-locale WiFi Aid Lite marketing, support, and privacy pages."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


SITE_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = SITE_ROOT / "app" / "wifi-aid-lite"
DEFAULT_SOURCE = (
    Path.home()
    / "39_WiFiAidLite"
    / "storefront"
    / "website_localizations.json"
)
APP_STORE_URL = "https://apps.apple.com/app/id6793414462"
BASE_URL = "https://alice51849.github.io/app/wifi-aid-lite"
ICON_URL = "/assets/icons/wifi-aid-lite.png"
SUPPORT_EMAIL = "hourstag.app@gmail.com"
LOCALES = {
    "ar-SA", "bn-BD", "ca", "zh-Hans", "zh-Hant", "hr", "cs", "da",
    "nl-NL", "en-AU", "en-CA", "en-GB", "en-US", "fi", "fr-CA",
    "fr-FR", "de-DE", "el", "gu-IN", "he", "hi", "hu", "id", "it",
    "ja", "kn-IN", "ko", "ms", "ml-IN", "mr-IN", "no", "or-IN", "pl",
    "pt-BR", "pt-PT", "pa-IN", "ro", "ru", "sk", "sl-SI", "es-MX",
    "es-ES", "sv", "ta-IN", "te-IN", "th", "tr", "uk", "ur-PK", "vi",
}
REQUIRED_FIELDS = {
    "languageName",
    "direction",
    "marketingTitle",
    "marketingIntro",
    "supportTitle",
    "supportIntro",
    "contactLabel",
    "privacyTitle",
    "privacyIntro",
    "dataCollection",
    "locationUse",
    "diagnostics",
    "storage",
    "purchases",
    "lastUpdated",
}


STYLE = """
:root{--ink:#10252c;--muted:#4d6870;--line:rgba(112,177,178,.3);--glass:rgba(255,255,255,.72);--a:#08a79d;--b:#1876d2;--bg:#edfafa}
*{box-sizing:border-box;margin:0;padding:0}
body{min-height:100vh;color:var(--ink);background:radial-gradient(circle at 10% 5%,#d8fff5 0,transparent 36%),radial-gradient(circle at 95% 10%,#d9eaff 0,transparent 38%),linear-gradient(160deg,#f7ffff,#eaf6fa);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans",sans-serif;line-height:1.65;-webkit-font-smoothing:antialiased}
a{color:#087b84;text-decoration:none}
.wrap{width:min(900px,calc(100% - 36px));margin:auto}
nav{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:20px 0}
.brand{color:var(--ink);font-weight:850;letter-spacing:-.02em}
select{max-width:190px;border:1px solid var(--line);border-radius:12px;background:rgba(255,255,255,.8);color:var(--ink);padding:8px 10px}
.hero{text-align:center;padding:38px 0 32px}
.icon{width:112px;height:112px;border-radius:25px;box-shadow:0 18px 45px rgba(19,104,134,.2)}
h1{font-size:clamp(30px,6vw,48px);line-height:1.1;letter-spacing:-.035em;margin:20px 0 10px}
h2{font-size:clamp(22px,4vw,31px);line-height:1.25;letter-spacing:-.02em;margin-bottom:14px}
.lead{max-width:690px;margin:0 auto;color:var(--muted);font-size:clamp(17px,2.5vw,20px)}
.cta{display:inline-flex;margin-top:24px;padding:13px 25px;border-radius:14px;color:white;font-weight:800;background:linear-gradient(135deg,var(--a),var(--b));box-shadow:0 12px 28px rgba(14,124,151,.25)}
.panel{margin:18px 0;padding:clamp(22px,5vw,38px);border:1px solid var(--line);border-radius:28px;background:var(--glass);box-shadow:0 18px 55px rgba(20,85,105,.09);backdrop-filter:blur(22px);-webkit-backdrop-filter:blur(22px)}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:18px}
.card{padding:18px;border:1px solid var(--line);border-radius:18px;background:rgba(255,255,255,.66);color:var(--muted)}
.contact{display:inline-flex;margin-top:18px;padding:12px 20px;border-radius:13px;color:white;font-weight:800;background:linear-gradient(135deg,var(--a),var(--b))}
.links{display:flex;justify-content:center;gap:18px;flex-wrap:wrap;padding:25px 0 42px;color:var(--muted)}
.small{font-size:14px;color:var(--muted);margin-top:16px}
@media(max-width:620px){.grid{grid-template-columns:1fr}.wrap{width:min(100% - 24px,900px)}nav{align-items:flex-start}.panel{border-radius:22px}}
"""


def esc(value):
    return html.escape(str(value), quote=True)


def alternate_links(localizations, page_name, root_page=False):
    links = []
    for locale in localizations:
        suffix = f"{locale}/{page_name}" if page_name else f"{locale}/"
        links.append(
            f'<link rel="alternate" hreflang="{esc(locale)}" '
            f'href="{BASE_URL}/{suffix}">'
        )
    default_url = (
        f"{BASE_URL}/{page_name}" if page_name else f"{BASE_URL}/"
    )
    links.append(
        f'<link rel="alternate" hreflang="x-default" href="{default_url}">'
    )
    return "\n".join(links)


def language_picker(localizations, current, page_name, root_page=False):
    options = []
    for locale, values in localizations.items():
        if root_page and locale == "en-US":
            target = page_name or "./"
        else:
            target = f"{locale}/{page_name}" if page_name else f"{locale}/"
            if not root_page:
                target = f"../{target}"
        selected = " selected" if locale == current else ""
        options.append(
            f'<option value="{esc(target)}"{selected}>'
            f'{esc(values["languageName"])}</option>'
        )
    return (
        '<select onchange="if(this.value)location.href=this.value">'
        + "".join(options)
        + "</select>"
    )


def shell(
    *,
    locale,
    values,
    title,
    description,
    canonical,
    alternates,
    picker,
    content,
):
    direction = values["direction"]
    return f"""<!doctype html>
<html lang="{esc(locale)}" dir="{esc(direction)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(canonical)}">
{alternates}
<meta name="theme-color" content="#edfafa">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:image" content="https://alice51849.github.io{ICON_URL}">
<meta property="og:url" content="{esc(canonical)}">
<link rel="icon" href="{ICON_URL}">
<link rel="apple-touch-icon" href="{ICON_URL}">
<style>{STYLE}</style>
</head>
<body>
<div class="wrap">
<nav><a class="brand" href="/">✦ Lumi Studio</a>{picker}</nav>
{content}
<div class="links">
<a href="{esc(APP_STORE_URL)}">App Store</a>
<a href="support.html">{esc(values["supportTitle"])}</a>
<a href="privacy.html">{esc(values["privacyTitle"])}</a>
</div>
</div>
</body>
</html>
"""


def marketing_page(locale, values, localizations, *, root_page=False):
    base = f"{BASE_URL}/" if root_page else f"{BASE_URL}/{locale}/"
    picker = language_picker(
        localizations, locale, "", root_page=root_page
    )
    cards = "".join(
        f'<div class="card">{esc(text)}</div>'
        for text in (
            values["dataCollection"],
            values["locationUse"],
            values["diagnostics"],
            values["storage"],
            values["purchases"],
        )
    )
    schema = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": "WiFi Aid Lite",
            "operatingSystem": "iOS",
            "applicationCategory": "UtilitiesApplication",
            "description": values["marketingIntro"],
            "url": base,
            "downloadUrl": APP_STORE_URL,
            "image": (
                "https://alice51849.github.io/assets/icons/wifi-aid-lite.png"
            ),
            "offers": {
                "@type": "Offer",
                "price": "0",
                "priceCurrency": "USD",
                "description": values["purchases"],
            },
            "publisher": {
                "@type": "Organization",
                "name": "Lumi Studio",
                "url": "https://alice51849.github.io/",
            },
        },
        ensure_ascii=False,
    )
    content = f"""
<main>
<section class="hero">
<img class="icon" src="{ICON_URL}" alt="WiFi Aid Lite" width="112" height="112">
<h1>WiFi Aid Lite</h1>
<p class="lead">{esc(values["marketingTitle"])}</p>
<a class="cta" href="{esc(APP_STORE_URL)}">App Store</a>
</section>
<section class="panel">
<h2>{esc(values["marketingTitle"])}</h2>
<p class="lead">{esc(values["marketingIntro"])}</p>
<div class="grid">{cards}</div>
</section>
</main>
<script type="application/ld+json">{schema}</script>
"""
    return shell(
        locale=locale,
        values=values,
        title=f"WiFi Aid Lite — {values['marketingTitle']}",
        description=values["marketingIntro"],
        canonical=base,
        alternates=alternate_links(
            localizations, "", root_page=root_page
        ),
        picker=picker,
        content=content,
    )


def support_page(locale, values, localizations, *, root_page=False):
    canonical = (
        f"{BASE_URL}/support.html"
        if root_page else f"{BASE_URL}/{locale}/support.html"
    )
    picker = language_picker(
        localizations, locale, "support.html", root_page=root_page
    )
    content = f"""
<main>
<section class="hero">
<img class="icon" src="{ICON_URL}" alt="WiFi Aid Lite" width="112" height="112">
<h1>{esc(values["supportTitle"])}</h1>
<p class="lead">{esc(values["supportIntro"])}</p>
<a class="contact" href="mailto:{SUPPORT_EMAIL}">{esc(values["contactLabel"])}</a>
</section>
<section class="panel">
<div class="grid">
<div class="card">{esc(values["diagnostics"])}</div>
<div class="card">{esc(values["locationUse"])}</div>
<div class="card">{esc(values["storage"])}</div>
<div class="card">{esc(values["purchases"])}</div>
</div>
</section>
</main>
"""
    return shell(
        locale=locale,
        values=values,
        title=f"{values['supportTitle']} — WiFi Aid Lite",
        description=values["supportIntro"],
        canonical=canonical,
        alternates=alternate_links(
            localizations, "support.html", root_page=root_page
        ),
        picker=picker,
        content=content,
    )


def privacy_page(locale, values, localizations, *, root_page=False):
    canonical = (
        f"{BASE_URL}/privacy.html"
        if root_page else f"{BASE_URL}/{locale}/privacy.html"
    )
    picker = language_picker(
        localizations, locale, "privacy.html", root_page=root_page
    )
    paragraphs = "".join(
        f'<div class="card">{esc(text)}</div>'
        for text in (
            values["dataCollection"],
            values["locationUse"],
            values["diagnostics"],
            values["storage"],
            values["purchases"],
        )
    )
    content = f"""
<main>
<section class="hero">
<img class="icon" src="{ICON_URL}" alt="WiFi Aid Lite" width="112" height="112">
<h1>{esc(values["privacyTitle"])}</h1>
<p class="lead">{esc(values["privacyIntro"])}</p>
</section>
<section class="panel">
<div class="grid">{paragraphs}</div>
<p class="small">{esc(values["lastUpdated"])}</p>
</section>
</main>
"""
    return shell(
        locale=locale,
        values=values,
        title=f"{values['privacyTitle']} — WiFi Aid Lite",
        description=values["privacyIntro"],
        canonical=canonical,
        alternates=alternate_links(
            localizations, "privacy.html", root_page=root_page
        ),
        picker=picker,
        content=content,
    )


def generate(source):
    localizations = json.loads(source.read_text(encoding="utf-8"))
    if set(localizations) != LOCALES:
        raise RuntimeError(
            "WiFi Aid Lite website locales differ: "
            f"missing={sorted(LOCALES - set(localizations))}, "
            f"extra={sorted(set(localizations) - LOCALES)}"
        )
    for locale, values in localizations.items():
        missing = sorted(
            field
            for field in REQUIRED_FIELDS
            if not str(values.get(field, "")).strip()
        )
        if missing:
            raise RuntimeError(f"{locale}: empty website fields {missing}")
        expected_direction = "rtl" if locale in {"ar-SA", "he", "ur-PK"} else "ltr"
        if values.get("direction") != expected_direction:
            raise RuntimeError(f"{locale}: incorrect text direction")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    generated = []
    for locale, values in localizations.items():
        locale_root = OUTPUT_ROOT / locale
        locale_root.mkdir(parents=True, exist_ok=True)
        pages = {
            "index.html": marketing_page(locale, values, localizations),
            "support.html": support_page(locale, values, localizations),
            "privacy.html": privacy_page(locale, values, localizations),
        }
        for name, content in pages.items():
            path = locale_root / name
            path.write_text(content, encoding="utf-8")
            generated.append(path)

    default = localizations["en-US"]
    root_pages = {
        "index.html": marketing_page(
            "en-US", default, localizations, root_page=True
        ),
        "support.html": support_page(
            "en-US", default, localizations, root_page=True
        ),
        "privacy.html": privacy_page(
            "en-US", default, localizations, root_page=True
        ),
    }
    for name, content in root_pages.items():
        path = OUTPUT_ROOT / name
        path.write_text(content, encoding="utf-8")
        generated.append(path)
    manifest = {
        "appId": "6793414462",
        "locales": list(localizations),
        "pageCount": len(generated),
    }
    (OUTPUT_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    if not args.source.is_file():
        raise RuntimeError(f"Localization source is missing: {args.source}")
    print(json.dumps(generate(args.source), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
