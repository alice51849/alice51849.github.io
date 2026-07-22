#!/usr/bin/env python3
"""Tests for deterministic verified root app page synchronization."""

from __future__ import annotations

import json
import pathlib
import re
import sys
import tempfile
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_root_app_pages as sync  # noqa: E402


def record(
    app_id: str = "1234567890",
    *,
    key: str = "sample",
    locale: str = "en-US",
) -> dict:
    storefront = {
        "en-US": "us",
        "zh-Hant": "tw",
        "ja": "jp",
        "ko": "kr",
    }[locale]
    return {
        "key": key,
        "app_store_id": app_id,
        "name": "Sample App",
        "summary": "A verified summary for a real task.",
        "category": "utilities",
        "search_terms": ["task", "utility", "organize"],
        "purchase_model": "paid_upfront",
        "one_time_option": True,
        "capabilities": {},
        "app_store_url": (
            f"https://apps.apple.com/{storefront}/app/id{app_id}?ct=source"
        ),
        "guide_url": "https://example.com/guide",
        "verified_live": True,
        "storefront_facts": {
            "price": "4.99",
            "currency": "USD",
            "formatted_price": "$4.99",
            "storefront_url": (
                f"https://apps.apple.com/{storefront}/app/id{app_id}"
            ),
        },
    }


def catalog_document(locale: str, app_id: str = "1234567890") -> dict:
    return {
        "locale": locale,
        "record_count": 1,
        "apps": [record(app_id, locale=locale)],
    }


class FakeResponse:
    def __init__(self, document: object):
        self.body = json.dumps(document).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class RootAppPageSyncTests(unittest.TestCase):
    def test_app_id_requires_a_direct_https_app_store_url(self):
        self.assertEqual(
            "1234567890",
            sync.app_id_from_url(
                "https://apps.apple.com/tw/app/sample/id1234567890?uo=4"
            ),
        )
        with self.assertRaisesRegex(ValueError, "Invalid App Store URL"):
            sync.app_id_from_url(
                "http://apps.apple.com/app/id1234567890"
            )

    def test_catalogs_require_identical_verified_live_ids(self):
        sources = {
            f"{sync.CATALOG_BASE}/{locale}.json": catalog_document(locale)
            for locale in sync.CATALOG_LOCALES.values()
        }

        def opener(request, timeout):
            self.assertEqual(30, timeout)
            return FakeResponse(sources[request.full_url])

        catalogs = sync.load_catalogs(
            opener=opener,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual({"1234567890"}, set(catalogs["en"]))

        sources[f"{sync.CATALOG_BASE}/ko.json"] = catalog_document(
            "ko",
            "9999999999",
        )
        with self.assertRaisesRegex(ValueError, "App IDs differ"):
            sync.load_catalogs(
                opener=opener,
                sleeper=lambda _seconds: None,
            )

    def test_live_app_missing_from_data_is_rejected(self):
        catalogs = {
            lang: {"1234567890": record(locale=locale)}
            for lang, locale in sync.CATALOG_LOCALES.items()
        }
        with self.assertRaisesRegex(ValueError, "missing from data.js"):
            sync.prepare_live_apps({}, catalogs)

    def test_existing_page_gets_banner_storefront_and_real_price(self):
        app_record = record()
        old_url = "https://apps.apple.com/tw/app/sample/id1234567890?uo=4"
        payload = [
            {
                "@context": "https://schema.org",
                "@type": "SoftwareApplication",
                "name": "Sample App",
                "installUrl": old_url,
                "downloadUrl": old_url,
                "offers": {
                    "@type": "Offer",
                    "price": "0",
                    "priceCurrency": "USD",
                },
            },
            {"@context": "https://schema.org", "@type": "FAQPage"},
        ]
        source = f"""<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width">
<script type="application/ld+json">
{json.dumps(payload)}
</script>
</head><body>
<!-- verified-catalog-page:0000000000000000 -->
<a href="{old_url}">Download</a>
<a href="{old_url}">App Store</a>
Made by Lumi Studio — pay once, no ads, privacy-first.
</body></html>
"""
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "index.html"
            path.write_text(source, encoding="utf-8")
            self.assertTrue(sync.sync_page(path, app_record, "en"))
            updated = path.read_text(encoding="utf-8")
            expected_url = sync.localized_store_url(app_record, "en")
            self.assertIn(
                '<meta name="apple-itunes-app" '
                'content="app-id=1234567890">',
                updated,
            )
            self.assertGreaterEqual(updated.count(expected_url), 3)
            self.assertNotIn("?uo=4", updated)
            self.assertIn('"price": "4.99"', updated)
            self.assertIn(
                "paid upfront on the App Store",
                updated,
            )
            self.assertFalse(sync.sync_page(path, app_record, "en"))

    def test_aim990_fallback_does_not_guarantee_results(self):
        app_record = record(key="aim990")
        app_record["search_terms"].append("offline study")
        app_record["capabilities"] = {"offline": False}
        summary = sync.safe_summary(app_record, "en")
        self.assertIn("not guaranteed", summary)
        self.assertNotIn("achieve", summary.casefold())
        self.assertNotIn(
            "offline study",
            sync.catalog_content({"sub_i18n": {}}, app_record, "en")[
                "features"
            ],
        )

    def test_unblurry_fallback_states_restoration_limits(self):
        app_record = record(key="unblurry")
        summary = sync.safe_summary(app_record, "en")
        self.assertIn("cannot recreate details", summary)
        self.assertNotIn("crystal clear", summary.casefold())

    def test_store_url_uses_local_storefront_without_false_attribution(self):
        en_url = sync.localized_store_url(record(locale="en-US"), "en")
        zh_url = sync.localized_store_url(record(locale="zh-Hant"), "zh")
        self.assertEqual(
            "https://apps.apple.com/us/app/id1234567890",
            en_url,
        )
        self.assertEqual(
            "https://apps.apple.com/tw/app/id1234567890",
            zh_url,
        )
        self.assertNotIn("ct=", en_url)
        self.assertNotIn("pt=", en_url)

    def test_sitemap_lastmod_uses_dirty_state_then_history(self):
        class Result:
            def __init__(self, stdout="", returncode=0):
                self.stdout = stdout
                self.returncode = returncode

        def dirty_runner(args, **_kwargs):
            if args[1] == "status":
                return Result(" M tools/example/index.html\n")
            return Result("2025-01-02\n")

        def clean_runner(args, **_kwargs):
            if args[1] == "status":
                return Result()
            return Result("2025-01-02\n")

        path = sync.legacy.SITE + "/tools/example/index.html"
        self.assertEqual(
            "2026-07-20",
            sync.legacy._sitemap_lastmod(
                path,
                "2024-01-01",
                "2026-07-20",
                runner=dirty_runner,
            ),
        )
        self.assertEqual(
            "2025-01-02",
            sync.legacy._sitemap_lastmod(
                path,
                "2024-01-01",
                "2026-07-20",
                runner=clean_runner,
            ),
        )

    def test_sitemap_includes_root_resourcesync_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            site = pathlib.Path(directory)
            resource = site / ".well-known" / "resourcesync"
            resource.parent.mkdir()
            resource.write_text("<urlset/>", encoding="utf-8")
            with (
                mock.patch.object(sync.legacy, "SITE", str(site)),
                mock.patch.object(
                    sync.legacy,
                    "BASE",
                    "https://alice51849.github.io",
                ),
            ):
                sync.legacy.rebuild_sitemap({})
            sitemap = (site / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn(
            "<loc>https://alice51849.github.io/.well-known/resourcesync</loc>",
            sitemap,
        )

    def test_korean_copy_avoids_brand_name_particle_errors(self):
        app_record = record(locale="ko")
        app_record["name"] = "TripBee Lite: 여행 플래너"
        content = sync.catalog_content(
            {"sub_i18n": {"ko": "여행 하나에 집중"}},
            app_record,
            "ko",
        )
        serialized = json.dumps(content, ensure_ascii=False)
        self.assertNotIn("플래너은", serialized)
        self.assertNotIn("플래너는", serialized)
        self.assertEqual("이런 용도에 적합해요", content["features_heading"])
        self.assertRegex(
            content["generation_marker"],
            r"^<!-- verified-catalog-page:[0-9a-f]{16} -->$",
        )

    def test_homepage_count_is_dynamic_and_static_seo_is_synchronized(self):
        source = (sync.ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn(
            "const appCount=()=>String(window.APPS.length);",
            source,
        )
        self.assertEqual(
            12,
            source.split("const appCount", 1)[0].count("{count}"),
        )
        self.assertNotIn("Explore 28 Apps", source)
        match = re.search(
            r'property="og:description" content="探索 (\d+) 款獨立 iPhone App',
            source,
        )
        self.assertIsNotNone(match)
        self.assertEqual(
            len(sync.legacy.parse_datajs(sync.ROOT / "assets" / "data.js")),
            int(match.group(1)),
        )

        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "index.html"
            path.write_text(
                '<meta property="og:description" content="探索 28 款獨立 '
                'iPhone App，查看逐款核實的功能、購買方式與正確 App Store 直達。">',
                encoding="utf-8",
            )
            self.assertTrue(sync.sync_homepage_app_count(path, 30))
            self.assertIn("探索 30 款獨立 iPhone App", path.read_text())
            self.assertFalse(sync.sync_homepage_app_count(path, 30))


if __name__ == "__main__":
    unittest.main()
