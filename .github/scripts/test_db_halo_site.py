#!/usr/bin/env python3
"""Regression tests for the deterministic dB Halo exact-50 site."""

from __future__ import annotations

import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_db_halo_site as generator  # noqa: E402
import validate_db_halo_site as validator  # noqa: E402


class DBHaloSiteTests(unittest.TestCase):
    def test_sources_and_html_have_exact_three_real_permission_items(self):
        translations = generator.load_translations()
        notification_false_claims = validator.load_notification_false_claims()
        for locale in generator.OFFICIAL_LOCALES:
            with self.subTest(locale=locale):
                permissions = translations[locale]["support"]["permissions"]
                self.assertEqual(generator.SUPPORT_PERMISSION_COUNT, len(permissions))
                false_claim = notification_false_claims[locale]
                self.assertFalse(
                    any(
                        false_claim in value
                        for _field, value in validator.walk_strings(
                            translations[locale]["support"]
                        )
                    )
                )

                rendered = generator.render_support(
                    locale,
                    translations[locale],
                    translations,
                )
                rendered_inspector = validator.PageInspector()
                rendered_inspector.feed(rendered)
                self.assertEqual(
                    list(generator.SUPPORT_PERMISSION_IDS),
                    rendered_inspector.permission_ids,
                )
                self.assertNotIn(
                    "notifications",
                    rendered_inspector.permission_ids,
                )
                self.assertNotIn(false_claim, rendered)

                generated_inspector = validator.PageInspector()
                generated_inspector.feed(
                    generator.page_path(locale).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    list(generator.SUPPORT_PERMISSION_IDS),
                    generated_inspector.permission_ids,
                )
                self.assertNotIn(
                    "notifications",
                    generated_inspector.permission_ids,
                )
                self.assertNotIn(
                    false_claim,
                    generator.page_path(locale).read_text(encoding="utf-8"),
                )

    def test_requested_ecosystem_titles_are_exact(self):
        translations = generator.load_translations()
        self.assertEqual(
            "Watch、小组件与快捷指令",
            translations["zh-Hans"]["support"]["features"][5]["title"],
        )
        self.assertEqual(
            "Watch, 위젯, 단축어",
            translations["ko"]["support"]["features"][5]["title"],
        )

    def test_root_index_merge_is_idempotent_and_strict(self):
        source = (
            "<html><body><footer>\n"
            '    <nav class="applinks"><a href="/app/example/">Example</a></nav>\n'
            '    <div class="copy">Copyright</div>\n'
            "</footer></body></html>\n"
        )
        merged = generator.merge_root_index(source)
        self.assertEqual(merged, generator.merge_root_index(merged))
        self.assertEqual(1, merged.count(generator.ROOT_INDEX_START))
        self.assertEqual(1, merged.count(generator.ROOT_INDEX_END))
        self.assertEqual(1, merged.count(generator.ROOT_INDEX_LINK))

        malformed = merged.replace(
            generator.ROOT_INDEX_END,
            generator.ROOT_INDEX_START,
        )
        with self.assertRaises(ValueError):
            generator.merge_root_index(malformed)

        duplicate = merged.replace(
            generator.ROOT_INDEX_END,
            generator.ROOT_INDEX_END
            + "\n"
            + generator.root_index_block(),
        )
        with self.assertRaises(ValueError):
            generator.merge_root_index(duplicate)

        unmanaged = source.replace(
            generator.ROOT_INDEX_INSERTION_ANCHOR,
            "<a href='/db-halo/'>Unmanaged</a>\n"
            + generator.ROOT_INDEX_INSERTION_ANCHOR,
        )
        with self.assertRaises(ValueError):
            generator.merge_root_index(unmanaged)

    def test_root_sitemap_merge_is_idempotent_and_strict(self):
        source = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            "</urlset>\n"
        )
        merged = generator.merge_root_sitemap(source)
        self.assertEqual(merged, generator.merge_root_sitemap(merged))

        duplicate = merged.replace(
            generator.ROOT_SITEMAP_END,
            generator.ROOT_SITEMAP_END
            + "\n"
            + generator.root_sitemap_block(),
        )
        with self.assertRaises(ValueError):
            generator.merge_root_sitemap(duplicate)

        unmanaged = source.replace(
            "</urlset>",
            "  <url><loc>"
            + generator.sitemap_urls()[0]
            + "</loc><lastmod>2026-08-29</lastmod></url>\n"
            + "</urlset>",
        )
        with self.assertRaises(ValueError):
            generator.merge_root_sitemap(unmanaged)


if __name__ == "__main__":
    unittest.main()
