#!/usr/bin/env python3
"""Generate the root link hub: /app/ directory, home block, sitemap index, robots.

The root site is the link graph hub for every published content asset:

  * the App Store listing for each verified live app,
  * the English GEO guide page under /ios-app-guide/,
  * the localized support site for that app.

Everything is rendered from the vendored, deterministic snapshot in
``data/link-hub.json`` so CI never depends on a live network fetch.  Refresh
the snapshot locally with ``--refresh`` (needs the published finder catalog and
the local support-network config), review the diff, then commit it.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re
import sys
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "link-hub.json"

BASE = "https://open.cait518.cc"
GUIDE_BASE = f"{BASE}/ios-app-guide"
CATALOG_URL = f"{GUIDE_BASE}/data/verified-ios-app-finder-catalog.json"
CROSSPROMO_PATH = Path.home() / (
    ".growth-runtime/engine/support_network/crosspromo_config.json"
)

# Apple App Store campaign attribution: provider token + per-surface campaign.
PROVIDER_TOKEN = "118326163"
CAMPAIGN_PREFIX = "home_"

CONTACT_EMAIL = "hourstag.app@gmail.com"

HOME_BLOCK_START = "<!-- link-hub:start -->"
HOME_BLOCK_END = "<!-- link-hub:end -->"
HOME_BLOCK_RE = re.compile(
    rf"[ \t]*{re.escape(HOME_BLOCK_START)}.*?{re.escape(HOME_BLOCK_END)}\n?",
    flags=re.DOTALL,
)
HOME_ANCHOR = "</main>\n"

LEGACY_HOST = "https://alice51849.github.io"
APP_BLOCK_START = "<!-- link-hub-app:start -->"
APP_BLOCK_END = "<!-- link-hub-app:end -->"
APP_BLOCK_RE = re.compile(
    rf"\n?{re.escape(APP_BLOCK_START)}.*?{re.escape(APP_BLOCK_END)}",
    flags=re.DOTALL,
)
APP_FOOT_ANCHOR = "\n</div>\n</body>"
APP_ALL_APPS_RE = re.compile(
    r'(<div style="margin-top:8px"><a href=")/(">)'
)
APP_STORE_ID_RE = re.compile(r"https://apps\.apple\.com/[^\"'<> ]*?/id(\d+)")
HTML_LANG_RE = re.compile(r'<html lang="([^"]+)"')
APP_LINK_LABELS = {
    "en": ("English guide", "Support"),
    "zh": ("英文使用指南", "支援中心"),
    "ja": ("英語ガイド", "サポート"),
    "ko": ("영문 가이드", "지원"),
}

LLMS_SECTION_TITLE = "## App guides and support sites"
LLMS_SECTION_RE = re.compile(
    rf"{re.escape(LLMS_SECTION_TITLE)}\n.*?(?=\n## |\Z)",
    flags=re.DOTALL,
)

EXTRA_SITEMAPS = (
    f"{GUIDE_BASE}/sitemap.xml",
    f"{GUIDE_BASE}/resourcesync/resourcelist.xml",
    f"{BASE}/awesome-zhuyin-bopomofo-apps/sitemap.xml",
)
# Declared in robots.txt only: a sitemap index may not nest another index.
INDEX_ONLY_SITEMAPS = (f"{GUIDE_BASE}/sitemap_index.xml",)

AI_CRAWLERS = (
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "PerplexityBot",
    "Perplexity-User",
    "Google-Extended",
    "ClaudeBot",
    "Claude-Web",
    "anthropic-ai",
    "Applebot-Extended",
    "Amazonbot",
    "Bingbot",
    "cohere-ai",
)


class HubError(RuntimeError):
    """The hub inputs or the shared root files are not in a usable state."""


# --------------------------------------------------------------------------
# data snapshot
# --------------------------------------------------------------------------


def load_data(path: Path = DATA_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise HubError("unsupported link hub snapshot")
    apps = data.get("apps")
    support_sites = data.get("support_sites")
    if not isinstance(apps, list) or not apps:
        raise HubError("link hub snapshot has no apps")
    if not isinstance(support_sites, list) or not support_sites:
        raise HubError("link hub snapshot has no support sites")
    seen_keys: set[str] = set()
    seen_ids: set[str] = set()
    for app in apps:
        for field in (
            "key",
            "name",
            "app_store_id",
            "category",
            "category_label_en",
            "category_label_zh",
            "summary_en",
            "summary_zh",
            "purchase_en",
            "purchase_zh",
            "support_slug",
            "guide_path",
        ):
            if not str(app.get(field) or "").strip():
                raise HubError(f"{app.get('key')!r} is missing {field}")
        if not str(app["app_store_id"]).isdigit():
            raise HubError(f"{app['key']!r} has a non-numeric App Store id")
        if app["key"] in seen_keys or app["app_store_id"] in seen_ids:
            raise HubError(f"duplicate app entry: {app['key']!r}")
        if app["support_slug"] not in support_sites:
            raise HubError(f"{app['key']!r} points at an unknown support site")
        seen_keys.add(app["key"])
        seen_ids.add(app["app_store_id"])
    return data


def refresh_data(path: Path = DATA_PATH) -> dict:
    """Rebuild the vendored snapshot from first-party sources (local only)."""

    request = urllib.request.Request(
        CATALOG_URL,
        headers={"User-Agent": f"LumiRootLinkHub/1.0 (+{BASE}/)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        catalog = json.loads(response.read().decode("utf-8"))
    if not isinstance(catalog.get("apps"), list) or not catalog["apps"]:
        raise HubError("verified finder catalog is empty")

    crosspromo = json.loads(CROSSPROMO_PATH.read_text(encoding="utf-8"))
    sites = crosspromo.get("sites")
    if not isinstance(sites, dict) or not sites:
        raise HubError("support network config has no sites")
    app_to_slug: dict[str, str] = {}
    for slug, config in sites.items():
        app_key = config.get("app")
        if not app_key:
            continue
        if app_key in app_to_slug:
            raise HubError(f"two support sites claim {app_key!r}")
        app_to_slug[app_key] = slug

    apps = []
    for record in catalog["apps"]:
        if not record.get("verified_live"):
            continue
        key = str(record["key"])
        slug = app_to_slug.get(key)
        if not slug:
            raise HubError(f"{key!r} has no support site")
        apps.append(
            {
                "key": key,
                "name": str(record["name"]),
                "app_store_id": str(record["app_store_id"]),
                "category": str(record["category"]),
                "category_label_en": str(record["category_labels"]["en"]),
                "category_label_zh": str(record["category_labels"]["zh-Hant"]),
                "summary_en": str(record["summaries"]["en"]),
                "summary_zh": str(record["summaries"]["zh-Hant"]),
                "purchase_en": str(record["purchase_labels"]["en"]),
                "purchase_zh": str(record["purchase_labels"]["zh-Hant"]),
                "support_slug": slug,
                "guide_path": f"en-US/{key}.html",
            }
        )
    apps.sort(key=lambda app: (app["name"].casefold(), app["key"]))
    data = {
        "schema_version": 1,
        "source": {
            "catalog": CATALOG_URL,
            "catalog_date_modified": catalog.get("date_modified", ""),
            "publisher_disclosure": catalog.get("publisher_disclosure", ""),
            "support_network": "support_network/crosspromo_config.json",
        },
        "support_sites": sorted(sites),
        "apps": apps,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=1, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return data


# --------------------------------------------------------------------------
# link builders
# --------------------------------------------------------------------------


def store_url(app: dict) -> str:
    return (
        f"https://apps.apple.com/app/id{app['app_store_id']}"
        f"?pt={PROVIDER_TOKEN}&ct={CAMPAIGN_PREFIX}{app['key']}&mt=8"
    )


def guide_url(app: dict) -> str:
    return f"{GUIDE_BASE}/{app['guide_path']}"


def support_url(app: dict) -> str:
    return f"{BASE}/{app['support_slug']}/"


def support_sitemaps(data: dict) -> list[str]:
    return [f"{BASE}/{slug}/sitemap.xml" for slug in data["support_sites"]]


def _attr(value: str) -> str:
    return html.escape(str(value), quote=True)


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip(" ,.;:—-") + "…"


# --------------------------------------------------------------------------
# renderers
# --------------------------------------------------------------------------


HUB_STYLE = """
:root{--ink:#3c3119;--ink2:#665436;--muted:#857049;--line:#f1e7cf;--bg:#fffaf0;--card:#fffdf8;--a1:#ffc24e;--a2:#f3895a}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,"Noto Sans TC",sans-serif;color:var(--ink);background:var(--bg);line-height:1.62;-webkit-font-smoothing:antialiased}
.wrap{max-width:1040px;margin:0 auto;padding:0 22px}
a{color:#c2622f;text-decoration:none}
a:hover{text-decoration:underline}
header.nav{padding:18px 0;border-bottom:1px solid var(--line)}
header .brand{font-weight:800;font-size:17px;color:var(--ink)}
.hero{padding:34px 0 8px}
h1{font-size:clamp(25px,4.6vw,36px);font-weight:800;letter-spacing:-.01em}
.hero p{color:var(--ink2);max-width:660px;margin-top:10px}
.note{font-size:13.5px;color:var(--muted);margin-top:12px;max-width:660px}
.groups{padding:14px 0 8px}
h2{font-size:20px;font-weight:800;margin:30px 0 12px;padding-top:18px;border-top:1px solid var(--line)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:15px;padding:15px 17px}
.card h3{font-size:16.5px;font-weight:800;margin-bottom:3px}
.meta{font-size:12.5px;color:var(--muted);font-weight:600}
.card p{font-size:14px;color:var(--ink2);margin-top:8px}
.card p.en{font-size:13px;color:var(--muted)}
.links{margin-top:11px;display:flex;flex-wrap:wrap;gap:7px}
.links a{font-size:13px;font-weight:700;border:1px solid var(--line);border-radius:999px;padding:5px 12px;background:#fff}
.links a.store{background:linear-gradient(135deg,var(--a1),var(--a2));border-color:transparent;color:#fff}
.foot{border-top:1px solid var(--line);margin-top:34px;padding:26px 0 40px;color:var(--muted);font-size:13.5px}
.foot a{margin-right:12px}
@media(max-width:560px){.grid{grid-template-columns:1fr}}
""".strip()


def _card(app: dict) -> str:
    return (
        '<article class="card">'
        f"<h3>{html.escape(app['name'])}</h3>"
        f'<p class="meta">{html.escape(app["category_label_zh"])}'
        f" · {html.escape(app['purchase_zh'])}</p>"
        f"<p>{html.escape(_clip(app['summary_zh'], 120))}</p>"
        f'<p class="en">{html.escape(_clip(app["summary_en"], 150))}</p>'
        '<p class="links">'
        f'<a class="store" href="{_attr(store_url(app))}">App Store</a>'
        f'<a href="{_attr(guide_url(app))}">English guide</a>'
        f'<a href="{_attr(support_url(app))}">支援中心</a>'
        "</p>"
        "</article>"
    )


def _grouped(data: dict) -> list[tuple[str, str, list[dict]]]:
    order: list[tuple[str, str]] = []
    buckets: dict[str, list[dict]] = {}
    for app in data["apps"]:
        category = app["category"]
        if category not in buckets:
            buckets[category] = []
            order.append((category, app["category_label_zh"]))
        buckets[category].append(app)
    order.sort(key=lambda item: (-len(buckets[item[0]]), item[0]))
    return [(key, label, buckets[key]) for key, label in order]


def render_item_list(data: dict) -> str:
    items = [
        {
            "@type": "ListItem",
            "position": index,
            "name": app["name"],
            "url": guide_url(app),
        }
        for index, app in enumerate(data["apps"], start=1)
    ]
    return json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": "Lumi Studio iPhone apps",
            "description": (
                "First-party directory of every published Lumi Studio iPhone "
                "app, listed alphabetically. Not an independent ranking."
            ),
            "url": f"{BASE}/app/",
            "numberOfItems": len(items),
            "itemListOrder": "https://schema.org/ItemListUnordered",
            "itemListElement": items,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def render_organization() -> str:
    return json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Lumi Studio",
            "url": f"{BASE}/",
            "description": (
                "An independent Taiwan studio building learning, photo, "
                "productivity, travel, and everyday iPhone apps."
            ),
            "slogan": "Light, made just right.",
            "foundingLocation": "Taiwan",
            "email": CONTACT_EMAIL,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def render_hub_page(data: dict) -> str:
    total = len(data["apps"])
    sections = []
    for _key, label, apps in _grouped(data):
        cards = "\n".join(_card(app) for app in apps)
        sections.append(
            f"<h2>{html.escape(label)}（{len(apps)}）</h2>\n"
            f'<div class="grid">\n{cards}\n</div>'
        )
    body = "\n".join(sections)
    description = (
        f"{total} 款 Lumi Studio iPhone App 的完整目錄：每一款都附 App Store "
        "直達連結、英文使用指南與支援中心。依名稱排序，不是排行榜。"
    )
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>全部 {total} 款 App — 指南與支援｜Lumi Studio</title>
<meta name="description" content="{_attr(description)}">
<link rel="canonical" href="{BASE}/app/">
<link rel="alternate" hreflang="zh-Hant" href="{BASE}/app/">
<link rel="alternate" hreflang="x-default" href="{BASE}/app/">
<meta name="theme-color" content="#fffaf0">
<meta property="og:type" content="website">
<meta property="og:title" content="全部 {total} 款 App — 指南與支援｜Lumi Studio">
<meta property="og:description" content="{_attr(description)}">
<meta property="og:url" content="{BASE}/app/">
<meta property="og:image" content="{BASE}/assets/og.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{BASE}/assets/og.png">
<link rel="icon" href="/assets/icons/lumi-letters-pro.png">
<link rel="apple-touch-icon" href="/assets/icons/lumi-letters-pro.png">
<script type="application/ld+json">
{render_organization()}
</script>
<script type="application/ld+json">
{render_item_list(data)}
</script>
<style>
{HUB_STYLE}
</style>
</head>
<body>
<header class="nav"><div class="wrap"><a class="brand" href="/">Lumi Studio</a></div></header>
<main class="wrap">
<section class="hero">
<h1>全部 {total} 款 App</h1>
<p>每一款都附三個連結：App Store 上架頁、英文使用指南，以及該款專屬的支援中心。名稱依字母排序，這是開發團隊自己維護的目錄，不是排行榜或第三方評比。</p>
<p class="note">功能與購買方式來自我們自己核對的 App Store 上架資料；價格與供應地區可能調整，請以商店頁面顯示的為準。</p>
</section>
<section class="groups">
{body}
</section>
</main>
<footer class="foot"><div class="wrap">
<p><a href="/">回首頁</a><a href="{GUIDE_BASE}/">使用指南總覽</a><a href="/llms.txt">llms.txt</a><a href="/sitemap-index.xml">Sitemap index</a></p>
<p style="margin-top:10px">有問題想問？寫信到 <!--email_off-->{CONTACT_EMAIL}<!--/email_off--> 。</p>
<p style="margin-top:6px">© 2026 Cait518. Lumi Studio.</p>
</div></footer>
</body>
</html>
"""


def render_home_block(data: dict) -> str:
    total = len(data["apps"])
    rows = "\n".join(
        "  <li>"
        f"<b>{html.escape(app['name'])}</b> "
        f'<span>{html.escape(app["category_label_zh"])}'
        f" · {html.escape(app['purchase_zh'])}</span> "
        f'<a href="{_attr(store_url(app))}">App Store</a>'
        f'<a href="{_attr(guide_url(app))}">English guide</a>'
        f'<a href="{_attr(support_url(app))}">支援</a>'
        "</li>"
        for app in data["apps"]
    )
    return (
        f"{HOME_BLOCK_START}\n"
        '<section id="all-apps" class="linkhub">\n'
        "<style>.linkhub{max-width:1040px;margin:0 auto;padding:34px 22px 8px}"
        ".linkhub h2{font-size:22px;font-weight:800}"
        ".linkhub>p{color:var(--ink2);margin:8px 0 4px;max-width:680px}"
        ".linkhub .hint{font-size:13.5px;color:var(--muted)}"
        ".linkhub ul{list-style:none;margin:16px 0 0;padding:0;display:grid;"
        "grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:10px}"
        ".linkhub li{border:1px solid var(--line);border-radius:13px;"
        "padding:11px 14px;background:var(--card);font-size:14px}"
        ".linkhub li b{display:block;font-size:15px}"
        ".linkhub li span{display:block;font-size:12.5px;color:var(--muted);"
        "margin-bottom:6px}"
        ".linkhub li a{font-size:13px;font-weight:700;margin-right:10px}"
        "</style>\n"
        f"<h2>全部 {total} 款 App 的指南與支援</h2>\n"
        "<p>每一款 App 都有 App Store 上架頁、一份英文使用指南，"
        "以及自己的支援中心。以下依名稱排序，不是排行榜。</p>\n"
        '<p class="hint">想看完整介紹卡片，請到 <a href="/app/">App 目錄頁</a>。</p>\n'
        f"<ul>\n{rows}\n</ul>\n"
        "</section>\n"
        f"{HOME_BLOCK_END}\n"
    )


def merge_home(source: str, data: dict) -> str:
    block = render_home_block(data)
    matches = HOME_BLOCK_RE.findall(source)
    if len(matches) > 1:
        raise HubError("home page has more than one link hub block")
    if matches:
        return HOME_BLOCK_RE.sub(lambda _match: block, source, count=1)
    if source.count(HOME_ANCHOR) != 1:
        raise HubError("home page has no unique </main> anchor")
    return source.replace(HOME_ANCHOR, block + HOME_ANCHOR, 1)


def render_sitemap_index(data: dict) -> str:
    locations = [f"{BASE}/sitemap.xml", *EXTRA_SITEMAPS, *support_sitemaps(data)]
    if len(set(locations)) != len(locations):
        raise HubError("sitemap index has duplicate entries")
    lines = "\n".join(
        f"  <sitemap><loc>{html.escape(loc)}</loc></sitemap>"
        for loc in locations
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{lines}\n"
        "</sitemapindex>\n"
    )


def render_robots(data: dict) -> str:
    crawlers = "\n".join(
        f"User-agent: {name}\nAllow: /" for name in AI_CRAWLERS
    )
    sitemaps = "\n".join(
        f"Sitemap: {loc}"
        for loc in (
            f"{BASE}/sitemap-index.xml",
            f"{BASE}/sitemap.xml",
            *EXTRA_SITEMAPS,
            *INDEX_ONLY_SITEMAPS,
        )
    )
    support = "\n".join(f"Sitemap: {loc}" for loc in support_sitemaps(data))
    return f"""User-agent: *
Allow: /

# Agentic Resource Discovery (ARD)
Agentmap: {BASE}/.well-known/ai-catalog.json

# AI assistants & answer engines — explicitly welcome (GEO)
{crawlers}

# Site-wide indexes
{sitemaps}

# Support & help sites (one sitemap per app)
{support}
"""


def render_llms_section(data: dict) -> str:
    lines = [
        LLMS_SECTION_TITLE,
        "",
        (
            "Every app below has a first-party English guide page and its own "
            f"support site. Full directory: {BASE}/app/"
        ),
        "",
    ]
    for app in data["apps"]:
        lines.append(
            f"- {app['name']} — guide: {guide_url(app)} — "
            f"support: {support_url(app)}"
        )
    return "\n".join(lines) + "\n"


def merge_llms(source: str, data: dict) -> str:
    section = render_llms_section(data)
    if LLMS_SECTION_TITLE in source:
        if source.count(LLMS_SECTION_TITLE) != 1:
            raise HubError("llms.txt has more than one guide section")
        merged = LLMS_SECTION_RE.sub(
            lambda _match: section.rstrip("\n"), source, 1
        )
    else:
        merged = source.rstrip("\n") + "\n\n" + section
    return merged.rstrip("\n") + "\n"


def _page_language(source: str) -> str:
    match = HTML_LANG_RE.search(source)
    tag = (match.group(1) if match else "en").split("-")[0].casefold()
    return tag if tag in APP_LINK_LABELS else "en"


def render_app_block(app: dict, language: str) -> str:
    guide_label, support_label = APP_LINK_LABELS[language]
    return (
        f"\n{APP_BLOCK_START}\n"
        '<div style="margin-top:8px">'
        f'<a href="{_attr(guide_url(app))}">{html.escape(guide_label)}</a>'
        " · "
        f'<a href="{_attr(support_url(app))}">{html.escape(support_label)}</a>'
        "</div>\n"
        f"{APP_BLOCK_END}"
    )


def sync_app_page(source: str, by_store_id: dict[str, dict]) -> str:
    """Point one root app page at the canonical host and the hub."""

    updated = source.replace(LEGACY_HOST, BASE)
    updated = APP_ALL_APPS_RE.sub(r"\1/app/\2", updated, count=1)
    ids = set(APP_STORE_ID_RE.findall(updated))
    app = by_store_id.get(next(iter(ids))) if len(ids) == 1 else None
    updated = APP_BLOCK_RE.sub("", updated)
    if app is None:
        return updated
    anchor = updated.rfind(APP_FOOT_ANCHOR)
    if anchor == -1:
        raise HubError("root app page has no footer anchor")
    block = render_app_block(app, _page_language(updated))
    return updated[:anchor] + block + updated[anchor:]


def app_pages(root: Path = ROOT) -> list[Path]:
    hub = (root / "app" / "index.html").resolve()
    return sorted(
        path
        for path in (root / "app").rglob("index.html")
        if path.resolve() != hub
    )


# --------------------------------------------------------------------------
# entrypoint
# --------------------------------------------------------------------------


def build(data: dict, root: Path = ROOT) -> dict[str, str]:
    home = (root / "index.html").read_text(encoding="utf-8")
    llms = (root / "llms.txt").read_text(encoding="utf-8")
    rendered = {
        "app/index.html": render_hub_page(data),
        "index.html": merge_home(home, data),
        "sitemap-index.xml": render_sitemap_index(data),
        "robots.txt": render_robots(data),
        "llms.txt": merge_llms(llms, data),
    }
    by_store_id = {app["app_store_id"]: app for app in data["apps"]}
    for path in app_pages(root):
        relative = path.relative_to(root).as_posix()
        rendered[relative] = sync_app_page(
            path.read_text(encoding="utf-8"), by_store_id
        )
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="rebuild data/link-hub.json from first-party sources first",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if any generated file is out of date",
    )
    args = parser.parse_args()

    data = refresh_data() if args.refresh else load_data()
    rendered = build(data)
    stale = []
    for relative in sorted(rendered):
        path = ROOT / relative
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == rendered[relative]:
            continue
        stale.append(relative)
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered[relative], encoding="utf-8")
    if args.check and stale:
        print("link hub is stale: " + ", ".join(stale), file=sys.stderr)
        return 1
    print(
        f"link hub: apps={len(data['apps'])} "
        f"support_sites={len(data['support_sites'])} "
        f"{'checked' if args.check else 'written'}={len(stale)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
