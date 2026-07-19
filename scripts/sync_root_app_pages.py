#!/usr/bin/env python3
"""Keep root app conversion pages aligned with the verified live catalog."""

from __future__ import annotations

import html
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gen_app_pages as legacy  # noqa: E402


CATALOG_BASE = (
    "https://alice51849.github.io/ios-app-guide/"
    "api/v1/ios-app-catalog/locales"
)
CATALOG_LOCALES = {
    "en": "en-US",
    "zh": "zh-Hant",
    "ja": "ja",
    "ko": "ko",
}
PAGE_FORMAT_VERSION = 3
ALLOWED_PURCHASE_MODELS = {
    "paid_upfront",
    "free_with_lifetime_unlock",
}
SMART_BLOCK_START = "<!-- root-smart-app-banner:start -->"
SMART_BLOCK_END = "<!-- root-smart-app-banner:end -->"
SMART_BLOCK_RE = re.compile(
    rf"\s*{re.escape(SMART_BLOCK_START)}.*?"
    rf"{re.escape(SMART_BLOCK_END)}\s*",
    flags=re.DOTALL,
)
SMART_META_RE = re.compile(
    r'\s*<meta\s+name=["\']apple-itunes-app["\'][^>]*>\s*',
    flags=re.IGNORECASE,
)
VIEWPORT_RE = re.compile(
    r'<meta\s+name=["\']viewport["\'][^>]*>\s*',
    flags=re.IGNORECASE,
)
APP_STORE_URL_RE = re.compile(
    r"https://apps\.apple\.com/"
    r"[^\"'<>\s]*?/id(\d+)(?:\?[^\"'<>\s]*)?",
    flags=re.IGNORECASE,
)
JSON_LD_RE = re.compile(
    r'(<script\s+type=["\']application/ld\+json["\']>\s*)'
    r"(.*?)"
    r"(\s*</script>)",
    flags=re.DOTALL | re.IGNORECASE,
)
APP_NAV_RE = re.compile(
    r"<style>\.applinks\{.*?</nav>",
    flags=re.DOTALL,
)
USER_AGENT = (
    "LumiRootAppPageSync/1.0 "
    "(+https://alice51849.github.io/)"
)
VERIFIED_PAGE_MARKER_PREFIX = "<!-- verified-catalog-page:"

COPY = {
    "en": {
        "fit": "Good fit for",
        "verified": "Verified App Store details",
        "direct": "One tap to the correct listing",
        "direct_text": (
            "This first-party page checks the live App Store catalog and "
            "links directly to the listing for your storefront."
        ),
        "price_change": "Pricing can change; confirm the current listing.",
        "what_q": "What is {name} designed for?",
        "price_q": "How much does {name} cost?",
        "once_q": "Is there a one-time purchase option?",
        "where_q": "Where can I download {name}?",
        "fit_q": "Which needs is {name} a good fit for?",
        "where_a": (
            "Use the App Store button on this page to open the verified "
            "listing directly."
        ),
        "once_yes": "Yes. The verified listing includes a one-time option.",
        "paid": (
            "{name} is currently {price} as an upfront App Store purchase."
        ),
        "unlock": (
            "{name} is free to download and includes a verified one-time "
            "lifetime unlock option."
        ),
        "footer_paid": (
            "Made by Lumi Studio — paid upfront on the App Store."
        ),
        "footer_unlock": (
            "Made by Lumi Studio — free to download with a one-time "
            "lifetime unlock option."
        ),
    },
    "zh": {
        "fit": "適合這些需求",
        "verified": "已驗證的 App Store 資訊",
        "direct": "一點直達正確商店頁面",
        "direct_text": (
            "這是開發團隊維護的第一方頁面，會核對 App Store 上架狀態，"
            "並直接連到符合所在地區的商店頁面。"
        ),
        "price_change": "價格可能調整，請以目前商店頁面為準。",
        "what_q": "{name} 適合拿來做什麼？",
        "price_q": "{name} 目前多少錢？",
        "once_q": "有一次性付費選項嗎？",
        "where_q": "要去哪裡下載 {name}？",
        "fit_q": "{name} 適合哪些需求？",
        "where_a": "點這一頁的 App Store 按鈕，即可直達已驗證的商店頁面。",
        "once_yes": "有，經驗證的商店資訊包含一次性付費選項。",
        "paid": "{name} 目前在 App Store 的一次付費價格為 {price}。",
        "unlock": (
            "{name} 可免費下載，並提供經驗證的一次性永久解鎖選項。"
        ),
        "footer_paid": "由 Lumi Studio 製作 — 於 App Store 一次付費下載。",
        "footer_unlock": (
            "由 Lumi Studio 製作 — 免費下載，並提供一次性永久解鎖選項。"
        ),
    },
    "ja": {
        "fit": "こんな用途に",
        "verified": "確認済みのApp Store情報",
        "direct": "正しいストアページへ直接移動",
        "direct_text": (
            "開発元が管理する公式ページです。公開状況を確認し、"
            "お住まいの地域に合うApp Storeページへ直接案内します。"
        ),
        "price_change": "価格は変更される場合があります。現在の表示をご確認ください。",
        "what_q": "{name}は何に役立つアプリですか？",
        "price_q": "{name}の価格はいくらですか？",
        "once_q": "買い切りの選択肢はありますか？",
        "where_q": "{name}はどこでダウンロードできますか？",
        "fit_q": "{name}はどんな用途に向いていますか？",
        "where_a": (
            "このページのApp Storeボタンから、確認済みのストアページを"
            "直接開けます。"
        ),
        "once_yes": "はい。確認済みのストア情報に買い切りの選択肢があります。",
        "paid": "{name}は現在、App Storeで{price}の買い切りアプリです。",
        "unlock": (
            "{name}は無料でダウンロードでき、買い切りの永久アンロックも"
            "用意されています。"
        ),
        "footer_paid": "Lumi Studio制作 — App Storeで買い切り。",
        "footer_unlock": (
            "Lumi Studio制作 — 無料ダウンロード、買い切りの永久アンロックあり。"
        ),
    },
    "ko": {
        "fit": "이런 용도에 적합해요",
        "verified": "확인된 App Store 정보",
        "direct": "내 지역의 정확한 스토어로 바로 이동",
        "direct_text": (
            "개발팀이 직접 관리하는 공식 페이지입니다. 실제 공개 상태를 "
            "확인하고 내 지역에 맞는 App Store 페이지로 연결합니다."
        ),
        "price_change": "가격은 변경될 수 있으니 현재 스토어 표시를 확인하세요.",
        "what_q": "{name} — 어떤 용도의 앱인가요?",
        "price_q": "{name} — 현재 가격은 얼마인가요?",
        "once_q": "일회성 구매 옵션이 있나요?",
        "where_q": "{name} — 어디에서 다운로드하나요?",
        "fit_q": "{name} — 어떤 필요에 잘 맞나요?",
        "where_a": (
            "이 페이지의 App Store 버튼을 누르면 확인된 스토어 페이지로 "
            "바로 이동합니다."
        ),
        "once_yes": "네. 확인된 스토어 정보에 일회성 구매 옵션이 포함됩니다.",
        "paid": (
            "현재 App Store 가격은 {price}이며, 전체 앱을 한 번 구매하는 "
            "방식입니다."
        ),
        "unlock": (
            "무료로 다운로드할 수 있으며 일회성 평생 잠금 해제 "
            "옵션을 제공합니다."
        ),
        "footer_paid": "Lumi Studio 제작 — App Store에서 한 번 구매.",
        "footer_unlock": (
            "Lumi Studio 제작 — 무료 다운로드, 일회성 평생 잠금 해제 옵션 제공."
        ),
    },
}

AIM990_SUMMARIES = {
    "en": (
        "TOEIC Listening & Reading study companion for daily practice and "
        "progress review. TOEIC is an ETS trademark; results are not "
        "guaranteed."
    ),
    "zh": (
        "協助安排 TOEIC 聽力與閱讀每日練習及進度檢視的學習工具。"
        "TOEIC 為 ETS 的商標；實際成績因人而異，不保證分數。"
    ),
    "ja": (
        "TOEIC Listening & Readingの日々の練習と進捗確認を支える学習アプリ。"
        "TOEICはETSの商標であり、スコアを保証するものではありません。"
    ),
    "ko": (
        "TOEIC Listening & Reading의 매일 학습과 진도 확인을 돕는 학습 앱입니다. "
        "TOEIC은 ETS의 상표이며 점수를 보장하지 않습니다."
    ),
}
UNBLURRY_SUMMARIES = {
    "en": (
        "Unblurry uses image enhancement to improve the perceived sharpness "
        "and resolution of existing photos. Results depend on the source "
        "image; it cannot recreate details that were never captured."
    ),
    "zh": (
        "Unblurry 可提升既有照片的清晰感與解析度。效果取決於原始影像品質，"
        "無法憑空還原拍攝時未留下的細節。"
    ),
    "ja": (
        "Unblurryは、元の写真を補正して見た目の鮮明さと解像感を高めます。"
        "仕上がりは元画像の品質に左右され、撮影時に記録されなかった細部を"
        "新たに復元することはできません。"
    ),
    "ko": (
        "Unblurry는 기존 사진을 보정해 선명도와 해상감을 높입니다. "
        "결과는 원본 품질에 따라 달라지며, 촬영되지 않은 세부 정보를 "
        "새로 만들어 낼 수는 없습니다."
    ),
}


class RootPageSyncError(RuntimeError):
    """Verified root conversion pages could not be synchronized."""


def app_id_from_url(url: object) -> str:
    if not isinstance(url, str):
        raise ValueError("App Store URL must be a string")
    parsed = urllib.parse.urlsplit(url)
    match = re.search(r"/id(\d+)$", parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "apps.apple.com"
        or not match
    ):
        raise ValueError(f"Invalid App Store URL: {url}")
    return match.group(1)


def _fetch_json(
    url: str,
    *,
    opener=None,
    sleeper=None,
    attempts: int = 3,
) -> object:
    opener = urllib.request.urlopen if opener is None else opener
    sleeper = time.sleep if sleeper is None else sleeper
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    for attempt in range(attempts):
        try:
            with opener(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            transient = error.code in {408, 429} or 500 <= error.code <= 599
            if not transient or attempt == attempts - 1:
                raise RootPageSyncError(
                    f"catalog fetch failed: HTTP {error.code}"
                ) from error
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            if attempt == attempts - 1:
                raise RootPageSyncError(
                    f"catalog fetch failed after {attempts} attempts"
                ) from error
        sleeper(10 * (attempt + 1))
    raise AssertionError("unreachable")


def _validate_record(record: object) -> dict:
    if not isinstance(record, dict) or record.get("verified_live") is not True:
        raise ValueError("catalog record is not verified live")
    app_id = record.get("app_store_id")
    if not isinstance(app_id, str) or not app_id.isdigit():
        raise ValueError("catalog record has an invalid App Store ID")
    if app_id_from_url(record.get("app_store_url")) != app_id:
        raise ValueError("catalog record App Store URL does not match its ID")
    if not isinstance(record.get("name"), str) or not record["name"].strip():
        raise ValueError("catalog record name is missing")
    if not isinstance(record.get("summary"), str) or not record["summary"].strip():
        raise ValueError("catalog record summary is missing")
    terms = record.get("search_terms")
    if (
        not isinstance(terms, list)
        or not terms
        or any(not isinstance(term, str) or not term.strip() for term in terms)
    ):
        raise ValueError("catalog record search terms are invalid")
    if record.get("purchase_model") not in ALLOWED_PURCHASE_MODELS:
        raise ValueError("catalog record purchase model is unsupported")
    if record.get("one_time_option") is not True:
        raise ValueError("catalog record lacks the required one-time option")
    facts = record.get("storefront_facts")
    if not isinstance(facts, dict):
        raise ValueError("catalog record storefront facts are missing")
    for key in ("price", "currency", "formatted_price"):
        if not isinstance(facts.get(key), str) or not facts[key]:
            raise ValueError(f"catalog record storefront {key} is invalid")
    return record


def load_catalogs(*, opener=None, sleeper=None) -> dict[str, dict[str, dict]]:
    catalogs = {}
    expected_ids = None
    for lang, locale in CATALOG_LOCALES.items():
        document = _fetch_json(
            f"{CATALOG_BASE}/{locale}.json",
            opener=opener,
            sleeper=sleeper,
        )
        if not isinstance(document, dict) or document.get("locale") != locale:
            raise ValueError(f"unexpected catalog locale for {lang}")
        records = document.get("apps")
        if (
            not isinstance(records, list)
            or document.get("record_count") != len(records)
            or not records
        ):
            raise ValueError(f"catalog coverage is invalid for {locale}")
        by_id = {}
        for record in records:
            record = _validate_record(record)
            app_id = record["app_store_id"]
            if app_id in by_id:
                raise ValueError(f"duplicate App Store ID in {locale}: {app_id}")
            by_id[app_id] = record
        ids = frozenset(by_id)
        if expected_ids is None:
            expected_ids = ids
        elif ids != expected_ids:
            raise ValueError("localized live catalog App IDs differ")
        catalogs[lang] = by_id
    return catalogs


def prepare_live_apps(
    apps: dict[str, dict],
    catalogs: dict[str, dict[str, dict]],
) -> tuple[dict[str, dict], dict[str, str]]:
    live_ids = set(catalogs["en"])
    by_id = {}
    id_to_slug = {}
    for slug, app in apps.items():
        app_id = app_id_from_url(app.get("url"))
        if app_id in by_id:
            raise ValueError(f"duplicate App Store ID in data.js: {app_id}")
        by_id[app_id] = app
        id_to_slug[app_id] = slug
    missing = sorted(live_ids - set(by_id))
    if missing:
        raise ValueError(
            "verified live apps are missing from data.js: " + ", ".join(missing)
        )
    live_apps = {
        id_to_slug[app_id]: by_id[app_id]
        for app_id in sorted(live_ids, key=lambda value: id_to_slug[value])
    }
    live_id_to_slug = {
        app_id: id_to_slug[app_id]
        for app_id in live_ids
    }
    return live_apps, live_id_to_slug


def localized_store_url(record: dict, lang: str) -> str:
    app_id = record["app_store_id"]
    parsed = urllib.parse.urlsplit(record["app_store_url"])
    if app_id_from_url(record["app_store_url"]) != app_id:
        raise ValueError("localized App Store URL does not match its ID")
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "", "")
    )


def safe_summary(record: dict, lang: str) -> str:
    if record.get("key") == "aim990":
        return AIM990_SUMMARIES[lang]
    if record.get("key") == "unblurry":
        return UNBLURRY_SUMMARIES[lang]
    return record["summary"].strip()


def purchase_sentence(record: dict, lang: str) -> str:
    copy = COPY[lang]
    key = "paid" if record["purchase_model"] == "paid_upfront" else "unlock"
    return copy[key].format(
        name=record["name"],
        price=record["storefront_facts"]["formatted_price"],
    )


def purchase_footer(record: dict, lang: str) -> str:
    key = (
        "footer_paid"
        if record["purchase_model"] == "paid_upfront"
        else "footer_unlock"
    )
    return COPY[lang][key]


def join_sentences(lang: str, *sentences: str) -> str:
    separator = " " if lang in {"en", "ko"} else ""
    return separator.join(sentence for sentence in sentences if sentence)


def truncate_meta(value: str, limit: int = 155) -> str:
    if len(value) <= limit:
        return value
    candidate = value[: limit - 1].rstrip(" ,.;:，。；：")
    if " " in candidate:
        candidate = candidate.rsplit(" ", 1)[0]
    return candidate + "…"


UNSUPPORTED_TERM_TOKENS = {
    "offline": ("offline", "離線", "オフライン", "오프라인"),
    "no_ads": ("no ads", "ad-free", "無廣告", "広告なし", "광고 없음"),
    "no_account": (
        "no account",
        "免帳號",
        "アカウント不要",
        "계정 불필요",
    ),
    "no_tracking": (
        "no tracking",
        "無追蹤",
        "追跡なし",
        "추적 없음",
    ),
}


def safe_terms(record: dict) -> list[str]:
    capabilities = record.get("capabilities")
    if not isinstance(capabilities, dict):
        capabilities = {}
    blocked = []
    for capability, tokens in UNSUPPORTED_TERM_TOKENS.items():
        if capabilities.get(capability) is not True:
            blocked.extend(token.casefold() for token in tokens)
    return [
        term
        for term in record["search_terms"]
        if not any(token in term.casefold() for token in blocked)
    ]


def catalog_content(app: dict, record: dict, lang: str) -> dict:
    copy = COPY[lang]
    name = record["name"]
    summary = safe_summary(record, lang)
    terms = safe_terms(record)
    if not terms:
        raise ValueError(f"catalog record has no safe search terms: {record['key']}")
    fit_text = " · ".join(terms[:8])
    meta = truncate_meta(f"{name} — {summary}")
    content = {
        "_catalog_category": record["category"],
        "meta": meta,
        "hero_line": (
            (app.get("sub_i18n", {}) or {}).get(lang)
            or summary.splitlines()[0]
        ),
        "intro": summary,
        "features_heading": copy["fit"],
        "sections": [
            {
                "h": copy["verified"],
                "p": join_sentences(
                    lang,
                    purchase_sentence(record, lang),
                    copy["price_change"],
                ),
            },
            {"h": copy["direct"], "p": copy["direct_text"]},
            {"h": copy["fit"], "p": fit_text},
        ],
        "features": terms[:6],
        "faqs": [
            {
                "q": copy["what_q"].format(name=name),
                "a": summary,
            },
            {
                "q": copy["price_q"].format(name=name),
                "a": join_sentences(
                    lang,
                    purchase_sentence(record, lang),
                    copy["price_change"],
                ),
            },
            {"q": copy["once_q"], "a": copy["once_yes"]},
            {
                "q": copy["where_q"].format(name=name),
                "a": copy["where_a"],
            },
            {
                "q": copy["fit_q"].format(name=name),
                "a": fit_text,
            },
        ],
    }
    digest = hashlib.sha256(
        json.dumps(
            {"format_version": PAGE_FORMAT_VERSION, "content": content},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()[:16]
    content["generation_marker"] = (
        f"{VERIFIED_PAGE_MARKER_PREFIX}{digest} -->"
    )
    return content


def smart_banner_block(app_id: str) -> str:
    if not app_id.isdigit():
        raise ValueError("Smart App Banner ID must be numeric")
    return "\n".join(
        (
            SMART_BLOCK_START,
            f'<meta name="apple-itunes-app" content="app-id={app_id}">',
            SMART_BLOCK_END,
        )
    )


def _update_schema(
    source: str,
    record: dict,
    lang: str,
    store_url: str,
) -> str:
    matched = False

    def replace(match: re.Match) -> str:
        nonlocal matched
        payload = json.loads(match.group(2))
        items = payload if isinstance(payload, list) else [payload]
        application = next(
            (
                item
                for item in items
                if isinstance(item, dict)
                and item.get("@type") == "SoftwareApplication"
            ),
            None,
        )
        if application is None:
            raise ValueError("page JSON-LD lacks SoftwareApplication")
        facts = record["storefront_facts"]
        application["installUrl"] = store_url
        application["downloadUrl"] = store_url
        application["offers"] = {
            "@type": "Offer",
            "price": facts["price"],
            "priceCurrency": facts["currency"],
            "url": store_url,
            "description": purchase_sentence(record, lang),
        }
        matched = True
        return (
            match.group(1)
            + json.dumps(payload, ensure_ascii=False, indent=0)
            + match.group(3)
        )

    updated = JSON_LD_RE.sub(replace, source, count=1)
    if not matched:
        raise ValueError("page has no JSON-LD block")
    return updated


def sync_page(path: Path, record: dict, lang: str) -> bool:
    app_id = record["app_store_id"]
    store_url = localized_store_url(record, lang)
    source = path.read_text(encoding="utf-8")
    existing_ids = set(APP_STORE_URL_RE.findall(source))
    if existing_ids and existing_ids != {app_id}:
        raise ValueError(
            f"page App Store IDs do not match {app_id}: {path}"
        )
    source = APP_STORE_URL_RE.sub(store_url, source)
    source = SMART_META_RE.sub("\n", SMART_BLOCK_RE.sub("\n", source))
    viewport = VIEWPORT_RE.search(source)
    if not viewport:
        raise ValueError(f"page has no viewport metadata: {path}")
    source = (
        source[: viewport.end()].rstrip()
        + "\n"
        + smart_banner_block(app_id)
        + "\n"
        + source[viewport.end() :].lstrip()
    )
    for old in (value["made"] for value in legacy.LANGS.values()):
        source = source.replace(old, purchase_footer(record, lang))
    source = _update_schema(source, record, lang, store_url)
    validate_page_source(source, record, lang, path)
    original = path.read_text(encoding="utf-8")
    if source == original:
        return False
    path.write_text(source, encoding="utf-8")
    return True


def validate_page_source(
    source: str,
    record: dict,
    lang: str,
    path: Path | str,
) -> None:
    app_id = record["app_store_id"]
    expected_banner = (
        f'<meta name="apple-itunes-app" content="app-id={app_id}">'
    )
    if source.count(expected_banner) != 1:
        raise ValueError(f"page Smart App Banner is invalid: {path}")
    if VERIFIED_PAGE_MARKER_PREFIX not in source:
        raise ValueError(f"page is not based on verified catalog facts: {path}")
    store_url = localized_store_url(record, lang)
    if source.count(store_url) < 3:
        raise ValueError(f"page lacks direct App Store links: {path}")
    linked_ids = set(APP_STORE_URL_RE.findall(source))
    if linked_ids != {app_id}:
        raise ValueError(f"page contains a wrong App Store ID: {path}")
    schema_match = JSON_LD_RE.search(source)
    if not schema_match:
        raise ValueError(f"page lacks JSON-LD: {path}")
    payload = json.loads(schema_match.group(2))
    items = payload if isinstance(payload, list) else [payload]
    application = next(
        item
        for item in items
        if isinstance(item, dict)
        and item.get("@type") == "SoftwareApplication"
    )
    facts = record["storefront_facts"]
    if application.get("downloadUrl") != store_url:
        raise ValueError(f"page JSON-LD download URL drifted: {path}")
    offers = application.get("offers")
    if (
        not isinstance(offers, dict)
        or offers.get("price") != facts["price"]
        or offers.get("priceCurrency") != facts["currency"]
    ):
        raise ValueError(f"page JSON-LD price drifted: {path}")


def page_path(slug: str, lang: str) -> Path:
    root_slug = legacy.ICON.get(slug, slug)
    if lang == "en":
        return ROOT / "app" / root_slug / "index.html"
    return ROOT / "app" / root_slug / lang / "index.html"


def rebuild_home_nav(
    path: Path,
    apps: dict[str, dict],
    catalogs: dict[str, dict[str, dict]],
) -> bool:
    links = []
    for slug, app in apps.items():
        app_id = app_id_from_url(app["url"])
        name = catalogs["en"][app_id]["name"].split(":")[0].strip()
        root_slug = legacy.ICON.get(slug, slug)
        links.append((name.casefold(), root_slug, name))
    links.sort()
    style = (
        '<style>.applinks{margin:20px auto 0;max-width:780px;display:flex;'
        'flex-wrap:wrap;gap:7px 15px;justify-content:center;'
        'border-top:1px solid var(--line);padding-top:16px}'
        '.applinks a{font-size:12.5px;color:var(--muted);'
        'text-decoration:none}.applinks a:hover{color:var(--ink2)}</style>'
    )
    nav = '<nav class="applinks" aria-label="All apps">' + "".join(
        f'<a href="/app/{html.escape(root_slug, quote=True)}/">'
        f"{html.escape(name)}</a>"
        for _sort, root_slug, name in links
    ) + "</nav>"
    source = path.read_text(encoding="utf-8")
    updated, count = APP_NAV_RE.subn(style + nav, source, count=1)
    if count != 1:
        raise ValueError("home page app navigation block is missing")
    if updated == source:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def rebuild_llms(
    path: Path,
    apps: dict[str, dict],
    catalogs: dict[str, dict[str, dict]],
) -> bool:
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
    for _slug, app in apps.items():
        app_id = app_id_from_url(app["url"])
        record = catalogs["en"][app_id]
        lines.append(
            (
                record["name"].casefold(),
                f"- {record['name']} — {safe_summary(record, 'en')} — "
                f"{localized_store_url(record, 'en')}",
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
    if updated == source:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def validate_all_pages(
    apps: dict[str, dict],
    catalogs: dict[str, dict[str, dict]],
) -> None:
    expected = set()
    for slug, app in apps.items():
        app_id = app_id_from_url(app["url"])
        for lang in CATALOG_LOCALES:
            path = page_path(slug, lang)
            expected.add(path.resolve())
            if not path.is_file():
                raise ValueError(f"verified live app page is missing: {path}")
            validate_page_source(
                path.read_text(encoding="utf-8"),
                catalogs[lang][app_id],
                lang,
                path,
            )
    actual = {
        path.resolve()
        for path in (ROOT / "app").glob("*/index.html")
    }
    actual.update(
        path.resolve()
        for path in (ROOT / "app").glob("*/*/index.html")
    )
    unexpected = sorted(actual - expected)
    if unexpected:
        raise ValueError(
            "non-live root app pages remain: "
            + ", ".join(str(path.relative_to(ROOT)) for path in unexpected)
        )


def main() -> None:
    catalogs = load_catalogs()
    source_apps = legacy.parse_datajs(ROOT / "assets" / "data.js")
    apps, id_to_slug = prepare_live_apps(source_apps, catalogs)
    changed = 0
    created = 0
    for app_id, slug in sorted(id_to_slug.items(), key=lambda item: item[1]):
        for lang in CATALOG_LOCALES:
            record = catalogs[lang][app_id]
            app = dict(apps[slug])
            app["name"] = record["name"]
            app["name_i18n"] = {lang: record["name"]}
            app["sub_i18n"] = {
                lang: record.get("subtitle")
                or (app.get("sub_i18n") or {}).get(lang, "")
            }
            app["category"] = record["category"]
            path = page_path(slug, lang)
            existed = path.exists()
            source = path.read_text(encoding="utf-8") if existed else ""
            content = catalog_content(app, record, lang)
            expected_marker = content["generation_marker"]
            needs_catalog_build = (
                not existed
                or expected_marker not in source
            )
            if needs_catalog_build:
                legacy.build_page(
                    slug,
                    app,
                    content,
                    lang,
                )
                if not existed:
                    created += 1
            if sync_page(path, record, lang):
                changed += 1
    if rebuild_home_nav(ROOT / "index.html", apps, catalogs):
        changed += 1
    if rebuild_llms(ROOT / "llms.txt", apps, catalogs):
        changed += 1
    sitemap_count = legacy.rebuild_sitemap(apps)
    validate_all_pages(apps, catalogs)
    print(
        f"root app sync: apps={len(apps)} locales={len(CATALOG_LOCALES)} "
        f"pages={len(apps) * len(CATALOG_LOCALES)} created={created} "
        f"updated={changed} sitemap={sitemap_count}"
    )


if __name__ == "__main__":
    main()
