#!/usr/bin/env python3
"""Contract tests for the root link hub generator."""

from __future__ import annotations

import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import gen_link_hub as hub  # noqa: E402


def snapshot() -> dict:
    return {
        "schema_version": 1,
        "support_sites": ["alpha-support", "beta-support", "spare-support"],
        "apps": [
            {
                "key": "alpha",
                "name": "Alpha",
                "app_store_id": "1111111111",
                "category": "productivity",
                "category_label_en": "Productivity",
                "category_label_zh": "效率工具",
                "summary_en": "Alpha keeps notes offline.",
                "summary_zh": "Alpha 讓筆記留在裝置上。",
                "purchase_en": "Paid download",
                "purchase_zh": "付費下載",
                "support_slug": "alpha-support",
                "guide_path": "en-US/alpha.html",
            },
            {
                "key": "beta",
                "name": "Beta",
                "app_store_id": "2222222222",
                "category": "kids",
                "category_label_en": "Kids & learning",
                "category_label_zh": "兒童與學習",
                "summary_en": "Beta is a phonics game.",
                "summary_zh": "Beta 是一款字母遊戲。",
                "purchase_en": "Free to start · one-time unlock",
                "purchase_zh": "免費開始 · 一次性解鎖",
                "support_slug": "beta-support",
                "guide_path": "en-US/beta.html",
            },
        ],
    }


class LoadDataTests(unittest.TestCase):
    def test_shipped_snapshot_is_valid(self):
        data = hub.load_data()
        self.assertGreaterEqual(len(data["apps"]), 1)
        for app in data["apps"]:
            self.assertIn(app["support_slug"], data["support_sites"])

    def test_rejects_unknown_support_site(self):
        data = snapshot()
        data["apps"][0]["support_slug"] = "missing-support"
        with self.assertRaises(hub.HubError):
            self._validate(data)

    def test_rejects_duplicate_app(self):
        data = snapshot()
        data["apps"].append(dict(data["apps"][0]))
        with self.assertRaises(hub.HubError):
            self._validate(data)

    def test_rejects_missing_field(self):
        data = snapshot()
        data["apps"][0]["summary_zh"] = "  "
        with self.assertRaises(hub.HubError):
            self._validate(data)

    def _validate(self, data: dict) -> None:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "link-hub.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            hub.load_data(path)


class LinkTests(unittest.TestCase):
    def test_store_url_carries_a_unique_campaign_token(self):
        data = snapshot()
        tokens = {hub.store_url(app) for app in data["apps"]}
        self.assertEqual(len(tokens), len(data["apps"]))
        self.assertEqual(
            hub.store_url(data["apps"][0]),
            "https://apps.apple.com/app/id1111111111"
            "?pt=118326163&ct=home_alpha&mt=8",
        )

    def test_every_published_link_uses_the_canonical_host(self):
        data = hub.load_data()
        for app in data["apps"]:
            self.assertTrue(hub.guide_url(app).startswith(hub.BASE + "/"))
            self.assertTrue(hub.support_url(app).startswith(hub.BASE + "/"))
        for location in hub.support_sitemaps(data):
            self.assertTrue(location.startswith(hub.BASE + "/"))


class HubPageTests(unittest.TestCase):
    def test_hub_page_links_all_three_destinations_per_app(self):
        data = snapshot()
        page = hub.render_hub_page(data)
        self.assertIn(f'<link rel="canonical" href="{hub.BASE}/app/">', page)
        self.assertNotIn("alice51849.github.io", page)
        self.assertIn("<!--email_off-->", page)
        for app in data["apps"]:
            self.assertIn(hub.store_url(app).replace("&", "&amp;"), page)
            self.assertIn(hub.guide_url(app), page)
            self.assertIn(hub.support_url(app), page)

    def test_item_list_counts_every_app(self):
        data = snapshot()
        payload = hub.render_item_list(data)
        self.assertIn('"numberOfItems":2', payload)


class HomeBlockTests(unittest.TestCase):
    HOME = '<html><body><main><p>hi</p>\n</main>\n<footer></footer></body></html>'

    def test_block_is_inserted_once_and_is_idempotent(self):
        data = snapshot()
        first = hub.merge_home(self.HOME, data)
        self.assertEqual(first.count(hub.HOME_BLOCK_START), 1)
        self.assertEqual(first, hub.merge_home(first, data))

    def test_duplicate_blocks_are_rejected(self):
        data = snapshot()
        once = hub.merge_home(self.HOME, data)
        twice = once.replace("</main>", once[
            once.index(hub.HOME_BLOCK_START):
            once.index(hub.HOME_BLOCK_END) + len(hub.HOME_BLOCK_END)
        ] + "\n</main>", 1)
        with self.assertRaises(hub.HubError):
            hub.merge_home(twice, data)

    def test_missing_anchor_is_rejected(self):
        with self.assertRaises(hub.HubError):
            hub.merge_home("<html><body></body></html>", snapshot())


class AppPageTests(unittest.TestCase):
    PAGE = (
        '<!DOCTYPE html>\n<html lang="zh-Hant">\n<head>\n'
        '<link rel="canonical" href="https://alice51849.github.io/app/alpha/zh/">\n'
        "</head>\n<body>\n"
        '<a href="https://apps.apple.com/us/app/id1111111111">Get</a>\n'
        '<div class="foot">\n<div>Made by Lumi Studio</div>\n'
        '<div style="margin-top:8px"><a href="/">All apps</a> · '
        '<a href="https://apps.apple.com/us/app/id1111111111">App Store</a></div>\n'
        "</div>\n</body>\n</html>\n"
    )

    def by_id(self):
        return {app["app_store_id"]: app for app in snapshot()["apps"]}

    def test_host_and_hub_links_are_applied_once(self):
        synced = hub.sync_app_page(self.PAGE, self.by_id())
        self.assertNotIn("alice51849.github.io", synced)
        self.assertIn(f'href="{hub.BASE}/app/alpha/zh/"', synced)
        self.assertIn('<a href="/app/">All apps</a>', synced)
        self.assertEqual(synced.count(hub.APP_BLOCK_START), 1)
        self.assertIn("支援中心", synced)
        self.assertEqual(synced, hub.sync_app_page(synced, self.by_id()))

    def test_the_page_keeps_exactly_one_app_store_id(self):
        synced = hub.sync_app_page(self.PAGE, self.by_id())
        self.assertEqual({"1111111111"}, set(hub.APP_STORE_ID_RE.findall(synced)))

    def test_unknown_app_only_gets_the_host_rewrite(self):
        page = self.PAGE.replace("1111111111", "9999999999")
        synced = hub.sync_app_page(page, self.by_id())
        self.assertNotIn(hub.APP_BLOCK_START, synced)
        self.assertNotIn("alice51849.github.io", synced)

    def test_hub_page_is_never_treated_as_an_app_page(self):
        self.assertNotIn(ROOT / "app" / "index.html", hub.app_pages())


class DiscoveryTests(unittest.TestCase):
    def test_sitemap_index_lists_guides_and_every_support_site(self):
        data = hub.load_data()
        document = hub.render_sitemap_index(data)
        locations = document.count("<sitemap>")
        self.assertEqual(
            locations,
            1 + len(hub.EXTRA_SITEMAPS) + len(data["support_sites"]),
        )
        self.assertIn(f"{hub.GUIDE_BASE}/sitemap.xml", document)
        for location in hub.support_sitemaps(data):
            self.assertIn(location, document)
        self.assertNotIn("sitemap_index.xml", document)

    def test_robots_allows_everyone_and_declares_every_sitemap(self):
        data = hub.load_data()
        robots = hub.render_robots(data)
        self.assertTrue(robots.startswith("User-agent: *\nAllow: /\n"))
        self.assertNotIn("Disallow:", robots)
        self.assertIn(f"Sitemap: {hub.BASE}/sitemap-index.xml", robots)
        self.assertIn(f"Sitemap: {hub.GUIDE_BASE}/sitemap_index.xml", robots)
        for location in hub.support_sitemaps(data):
            self.assertIn(f"Sitemap: {location}", robots)

    def test_llms_section_is_idempotent(self):
        data = snapshot()
        base = "# Site\n\n## Apps\n\n- Alpha\n\n## Other\n\n- thing\n"
        once = hub.merge_llms(base, data)
        self.assertIn(hub.LLMS_SECTION_TITLE, once)
        self.assertEqual(once, hub.merge_llms(once, data))
        self.assertIn("## Other", once)


class RepositoryStateTests(unittest.TestCase):
    def test_generated_files_are_current(self):
        data = hub.load_data()
        for relative, expected in hub.build(data).items():
            path = ROOT / relative
            self.assertTrue(path.is_file(), relative)
            self.assertEqual(
                expected,
                path.read_text(encoding="utf-8"),
                f"{relative} is stale; run scripts/gen_link_hub.py",
            )


if __name__ == "__main__":
    unittest.main()
