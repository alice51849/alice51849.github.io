#!/usr/bin/env python3
"""Tests for deterministic verified root app page synchronization."""

from __future__ import annotations

import hashlib
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
import publisher_root_channel as publisher  # noqa: E402
import generate_db_halo_site as db_halo  # noqa: E402
from managed_blocks import extract_allowlisted_sitemap_blocks  # noqa: E402


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

    def test_daily_sync_preserves_db_halo_footer_link_and_exact_sitemap_block(self):
        homepage = """<!doctype html>
<html><body><footer>
<style>.applinks{old}</style><nav class="applinks"><a href="/app/old/">Old</a></nav>
    <div class="copy"><span>Copyright</span></div>
</footer></body></html>
"""
        managed_homepage = db_halo.merge_root_index(homepage)
        app = {"url": record()["app_store_url"]}
        catalogs = {"en": {"1234567890": record()}}
        orphan = (
            "  <url><loc>https://alice51849.github.io/app/orphan/</loc>"
            "<lastmod>2026-06-30</lastmod></url>"
        )
        managed_sitemap_block = db_halo.root_sitemap_block()

        with tempfile.TemporaryDirectory() as directory:
            site = pathlib.Path(directory)
            homepage_path = site / "index.html"
            homepage_path.write_text(managed_homepage, encoding="utf-8")
            self.assertTrue(
                sync.rebuild_home_nav(
                    homepage_path,
                    {"sample": app},
                    catalogs,
                )
            )
            synced_homepage = homepage_path.read_text(encoding="utf-8")
            self.assertEqual(
                synced_homepage,
                db_halo.merge_root_index(synced_homepage),
            )
            nav_match = sync.APP_NAV_RE.search(synced_homepage)
            self.assertIsNotNone(nav_match)
            self.assertGreater(
                synced_homepage.index(db_halo.ROOT_INDEX_START),
                nav_match.end(),
            )
            self.assertEqual(1, synced_homepage.count(db_halo.ROOT_INDEX_LINK))

            sitemap_path = site / "sitemap.xml"
            sitemap_path.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                f"{orphan}\n{managed_sitemap_block}\n</urlset>\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(sync.legacy, "SITE", str(site)),
                mock.patch.object(
                    sync.legacy,
                    "BASE",
                    "https://alice51849.github.io",
                ),
            ):
                sync.legacy.rebuild_sitemap({})
                first = sitemap_path.read_text(encoding="utf-8")
                self.assertEqual(
                    (managed_sitemap_block,),
                    extract_allowlisted_sitemap_blocks(first),
                )
                self.assertNotIn(orphan, first)
                sync.legacy.rebuild_sitemap({})
                self.assertEqual(first, sitemap_path.read_text(encoding="utf-8"))

    def test_sitemap_rebuild_rejects_duplicate_or_malformed_db_halo_markers(self):
        block = db_halo.root_sitemap_block()
        cases = {
            "duplicate": f"{block}\n{block}",
            "missing-end": db_halo.ROOT_SITEMAP_START,
            "missing-start": db_halo.ROOT_SITEMAP_END,
            "reversed": (
                f"{db_halo.ROOT_SITEMAP_END}\n"
                f"{db_halo.ROOT_SITEMAP_START}"
            ),
            "wrong-indentation": (
                f"<!-- db-halo:start -->\n"
                f"{db_halo.ROOT_SITEMAP_END}"
            ),
            "unknown-pair": (
                "  <!-- db-halo:begin -->\n"
                "  <!-- db-halo:finish -->"
            ),
        }
        for label, markers in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                site = pathlib.Path(directory)
                sitemap_path = site / "sitemap.xml"
                source = (
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                    f"{markers}\n</urlset>\n"
                )
                sitemap_path.write_text(source, encoding="utf-8")
                with (
                    mock.patch.object(sync.legacy, "SITE", str(site)),
                    self.assertRaises(ValueError),
                ):
                    sync.legacy.rebuild_sitemap({})
                self.assertEqual(source, sitemap_path.read_text(encoding="utf-8"))

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
        current_count = int(match.group(1))
        contract_count = publisher.load_contract()["expected_app_count"]
        legacy_count = len(
            sync.legacy.parse_datajs(sync.ROOT / "assets" / "data.js")
        )
        self.assertIn(current_count, {legacy_count, contract_count})

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

    def test_only_explicit_prelaunch_app_pages_may_be_non_live(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            allowed = root / "app" / "daily-mate-lite" / "index.html"
            allowed.parent.mkdir(parents=True)
            allowed.write_text("<html></html>", encoding="utf-8")
            with mock.patch.object(sync, "ROOT", root):
                sync.validate_all_pages(
                    {},
                    {lang: {} for lang in sync.CATALOG_LOCALES},
                )

            unexpected = root / "app" / "stale-app" / "index.html"
            unexpected.parent.mkdir(parents=True)
            unexpected.write_text("<html></html>", encoding="utf-8")
            with (
                mock.patch.object(sync, "ROOT", root),
                self.assertRaisesRegex(ValueError, "non-live root app pages"),
            ):
                sync.validate_all_pages(
                    {},
                    {lang: {} for lang in sync.CATALOG_LOCALES},
                )


def synthetic_publisher_sources(contract: dict) -> dict:
    finder = {}
    localized = {}
    publisher_records = {}
    ui = {}
    for index, key in enumerate(contract["root_slugs"], start=1):
        app_id = str(7000000000 + index)
        finder[key] = {
            "key": key,
            "app_store_id": app_id,
            "canonical_app_store_url": (
                f"https://apps.apple.com/app/id{app_id}"
            ),
            "verified_live": True,
        }
    for locale in contract["official_locales"]:
        token = locale.replace("-", "_").lower()
        localized[locale] = {}
        publisher_records[locale] = {}
        rows = {}
        for key, app in finder.items():
            app_id = app["app_store_id"]
            name = f"{key} {locale}"
            campaign = (
                f"https://apps.apple.com/us/app/id{app_id}"
                f"?pt=118326163&ct=iag_data_{token}&mt=8"
            )
            guide = (
                "https://alice51849.github.io/ios-app-guide/"
                f"{locale}/{key}.html"
            )
            localized[locale][key] = {
                "key": key,
                "app_store_id": app_id,
                "name": name,
                "summary": (
                    f"{name} provides a verified localized task context "
                    "without invented product claims."
                ),
                "category": "utility",
                "search_terms": [
                    f"{locale} task",
                    f"{locale} workflow",
                    f"{locale} utility",
                ],
                "purchase_model": "free_with_lifetime_unlock",
                "one_time_option": True,
                "app_store_url": campaign,
                "guide_url": guide,
                "verified_live": True,
                "storefront_facts": {
                    "price": "0",
                    "currency": "USD",
                    "formatted_price": "Free",
                },
            }
            publisher_records[locale][key] = {
                "locale": locale,
                "app_key": key,
                "app_name": name,
                "app_store_id": app_id,
                "publisher_query": (
                    f"{name} verified publisher task and decision page"
                ),
                "decision_context": (
                    f"{name} is presented for its verified intended task "
                    "with a direct first-party source."
                ),
                "purchase_model": "free_with_lifetime_unlock",
                "one_time_option": True,
                "canonical_guide_url": guide,
                "canonical_app_store_url": (
                    f"https://apps.apple.com/app/id{app_id}"
                ),
                "app_store_url": campaign,
                "app_store_cta_label": f"Get {name} on the App Store",
                "publisher_disclosure": (
                    "This is first-party material published by Lumi Studio."
                ),
                "query_origin": (
                    "publisher_authored_editorially_localized"
                ),
                "measured_search_volume": False,
                "is_ranking": False,
                "verified_live": True,
            }
            rows[name] = {
                "purchase_label": "Free to start · one-time unlock",
                "guide_label": "Guide",
                "app_store_label": "App Store",
            }
        ui[locale] = {
            "headers": [
                "App",
                "Publisher query",
                "Decision context",
                "Purchase model",
                "Guide",
                "App Store",
            ],
            "first_party_heading": "First-party publisher catalog",
            "non_ranking_notice": (
                "Editorial intended-use context, not measured search "
                "volume, rankings, reviews, or endorsements."
            ),
            "rows": rows,
        }
    return {
        "finder": finder,
        "localized": localized,
        "publisher": publisher_records,
        "ui": ui,
        "modified": "2026-08-30",
    }


def write_publisher_site_fixture(
    root: pathlib.Path,
    contract: dict,
    sources: dict,
) -> None:
    app_root = root / "app"
    app_root.mkdir(parents=True)
    supplements = set(contract["supplemental_app_keys"])
    for key, slug in contract["root_slugs"].items():
        if key in supplements:
            continue
        app_id = sources["finder"][key]["app_store_id"]
        path = app_root / slug / "index.html"
        path.parent.mkdir(parents=True)
        path.write_text(
            f'<a href="https://apps.apple.com/app/id{app_id}">App Store</a>',
            encoding="utf-8",
        )
    (root / "index.html").write_text(
        '<meta property="og:description" content="探索 38 款獨立 iPhone App，'
        '查看逐款核實的功能、購買方式與正確 App Store 直達。">'
        '<style>.applinks{old}</style><nav class="applinks"></nav>',
        encoding="utf-8",
    )
    (root / "llms.txt").write_text(
        "# Lumi Studio\n\n## Apps\n\nold\n\n"
        "## Machine-readable app discovery\n\ncatalog\n",
        encoding="utf-8",
    )
    (root / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        "</urlset>\n",
        encoding="utf-8",
    )


def tree_digest(root: pathlib.Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class PublisherRootChannelTests(unittest.TestCase):
    def test_contract_is_exact46_with_the_eight_audited_supplements(self):
        contract = publisher.load_contract()
        self.assertEqual(46, len(contract["root_slugs"]))
        self.assertEqual(50, len(contract["official_locales"]))
        self.assertEqual(
            {
                "battai",
                "caldaily",
                "moneytag",
                "notesstudio100",
                "onepageppt",
                "savetag",
                "shotinbox",
                "snapportlite",
            },
            set(contract["supplemental_app_keys"]),
        )
        self.assertEqual(
            "onepage-ppt",
            contract["root_slugs"]["onepageppt"],
        )
        self.assertEqual(
            "100-notes-studio",
            contract["root_slugs"]["notesstudio100"],
        )

    def test_publisher_html_yields_native_first_party_and_row_labels(self):
        records = {
            "sample": {
                "app_name": "Sample App",
                "publisher_disclosure": (
                    "Native first-party disclosure by Lumi Studio."
                ),
            }
        }
        source = """
<section class="card"><h2>Native publisher heading</h2>
<p>Native first-party disclosure by Lumi Studio.</p>
<p>Native editorial context; not a ranking or endorsement.</p></section>
<table><thead><tr>
<th>App</th><th>Query</th><th>Context</th>
<th>Purchase</th><th>Guide</th><th>App Store</th>
</tr></thead><tbody><tr>
<td><strong>Sample App</strong></td><td>Query</td><td>Context</td>
<td>Pay once</td><td><a>Guide</a></td><td><a>App Store</a></td>
</tr></tbody></table>
"""
        ui = publisher._publisher_locale_ui(source, records)
        self.assertEqual(
            "Native publisher heading",
            ui["first_party_heading"],
        )
        self.assertIn("not a ranking", ui["non_ranking_notice"])
        self.assertEqual(
            "Pay once",
            ui["rows"]["Sample App"]["purchase_label"],
        )

    def test_exact50_generation_home_roster_plan_and_second_run_are_stable(self):
        contract = publisher.load_contract()
        sources = synthetic_publisher_sources(contract)
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            write_publisher_site_fixture(root, contract, sources)
            first = publisher.generate_supplemental_pages(
                root,
                contract,
                sources,
            )
            self.assertEqual(408, first["pages"])
            self.assertEqual(408, first["created"])
            self.assertTrue(
                publisher.rebuild_home(root, contract, sources)
            )
            self.assertTrue(
                publisher.rebuild_llms(root, contract, sources)
            )
            self.assertTrue(
                publisher.rebuild_sitemap(
                    root,
                    contract,
                    today="2026-08-30",
                )
            )
            publisher.validate_root_roster(root, contract, sources)
            publisher.validate_supplemental_pages(
                root,
                contract,
                sources,
            )
            plan = publisher.raw_get_plan(contract, sources)
            self.assertEqual(408, plan["request_count"])
            self.assertFalse(plan["deployment_performed"])
            self.assertFalse(plan["public_exposure_claimed"])
            first_digest = tree_digest(root)

            second = publisher.generate_supplemental_pages(
                root,
                contract,
                sources,
            )
            self.assertEqual(408, second["unchanged"])
            self.assertFalse(
                publisher.rebuild_home(root, contract, sources)
            )
            self.assertFalse(
                publisher.rebuild_llms(root, contract, sources)
            )
            self.assertFalse(
                publisher.rebuild_sitemap(
                    root,
                    contract,
                    today="2026-08-30",
                )
            )
            self.assertEqual(first_digest, tree_digest(root))

    def test_unsafe_publisher_semantics_block_before_writing(self):
        contract = publisher.load_contract()
        sources = synthetic_publisher_sources(contract)
        key = contract["supplemental_app_keys"][0]
        sources["publisher"]["en-US"][key]["is_ranking"] = True
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            with self.assertRaisesRegex(
                publisher.PublisherRootBlocked,
                r"BLOCKED.*unsafe",
            ):
                publisher.generate_supplemental_pages(
                    root,
                    contract,
                    sources,
                )
            self.assertFalse((root / "app").exists())

    def test_campaign_requires_provider_campaign_and_media_tokens(self):
        with self.assertRaisesRegex(ValueError, "campaign URL"):
            publisher._validate_campaign_url(
                "https://apps.apple.com/us/app/id1234567890",
                "1234567890",
            )
        publisher._validate_campaign_url(
            "https://apps.apple.com/us/app/id1234567890"
            "?pt=118326163&ct=iag_data_en_us&mt=8",
            "1234567890",
        )


if __name__ == "__main__":
    unittest.main()
