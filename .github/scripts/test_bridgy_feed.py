#!/usr/bin/env python3
"""Regression tests for the dedicated Bridgy Fed Atom feed."""

import datetime as dt
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from unittest import mock


HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bridgy_feed as feed


def payload(*slugs: str) -> dict[str, object]:
    return {
        "linkset": [
            {
                "anchor": f"{feed.GUIDE_SITE}/index.html",
                "item": [
                    {
                        "href": f"{feed.GUIDE_SITE}/guides/{slug}.html",
                        "title*": [{"value": slug.title(), "language": "en"}],
                    }
                    for slug in slugs
                ],
            }
        ]
    }


class FakeResponse:
    def __init__(self, body: bytes = b"ok"):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


class CandidateTests(unittest.TestCase):
    def test_all_linkset_items_are_candidates(self):
        candidates = feed.parse_candidates(payload("one", "two", "three"))
        self.assertEqual(["one", "two", "three"], [item["slug"] for item in candidates])

    def test_external_url_is_rejected(self):
        external = payload("one")
        external["linkset"][0]["item"][0]["href"] = "https://example.com/one.html"
        with self.assertRaisesRegex(ValueError, "outside the guide site"):
            feed.parse_candidates(external)

    def test_rotation_is_fair_and_repeats_after_full_cycle(self):
        candidates = feed.parse_candidates(payload("one", "two", "three"))
        selected = [
            feed.select_candidate(
                candidates,
                today=feed.BASE_DATE + dt.timedelta(days=offset),
            )["slug"]
            for offset in range(4)
        ]
        self.assertEqual(["one", "two", "three", "one"], selected)


class AtomTests(unittest.TestCase):
    def test_feed_has_exactly_one_stable_entry(self):
        candidate = feed.parse_candidates(payload("lumi"))[0]
        first = feed.render_feed(candidate, today=feed.BASE_DATE)
        second = feed.render_feed(candidate, today=feed.BASE_DATE)
        self.assertEqual(first, second)

        root = ET.fromstring(first)
        entries = root.findall(f"{{{feed.ATOM}}}entry")
        self.assertEqual(1, len(entries))
        self.assertEqual(
            f"{feed.GUIDE_SITE}/guides/lumi.html",
            entries[0].find(f"{{{feed.ATOM}}}link").attrib["href"],
        )
        self.assertIn(
            ":2026-07-12:lumi",
            entries[0].findtext(f"{{{feed.ATOM}}}id"),
        )
        content = entries[0].find(f"{{{feed.ATOM}}}content")
        self.assertEqual(
            feed.ACTIVITY_NOTE,
            entries[0].findtext(f"{{{feed.ACTIVITY}}}object-type"),
        )
        self.assertEqual("html", content.attrib["type"])
        self.assertIn("Lumi", content.text)
        self.assertEqual(2, content.text.count("<a "))
        self.assertIn(">#iOSApps</a>", content.text)
        self.assertIn(">#IndieApps</a>", content.text)
        self.assertEqual("en", content.attrib[f"{{{feed.XML}}}lang"])
        self.assertLessEqual(len(feed.post_text("lumi", "Lumi")), 300)

    def test_revenue_market_profiles_are_localized(self):
        cases = {
            "lumibopomofopro": ("zh-Hant", "注音符號", "#親子學習"),
            "hourstag": ("zh-Hant", "工作", "#消費習慣"),
            "aim990": ("ja", "30日学習計画", "#英語学習"),
            "cyca": ("es", "Registra ciclos", "#Privacidad"),
        }
        for slug, (locale, phrase, hashtag) in cases.items():
            with self.subTest(slug=slug):
                text = feed.post_text(slug, "Example")
                content = feed.post_content(slug, "Example")
                self.assertEqual(locale, feed.post_profile(slug)[0])
                self.assertIn(phrase, text)
                self.assertIn(hashtag, text)
                self.assertIn(hashtag, content)
                self.assertLessEqual(len(text), feed.MAX_POST_LENGTH)

    def test_all_current_live_apps_have_curated_profiles(self):
        self.assertEqual(
            {
                "aim990",
                "cvdesk",
                "cyca",
                "gmoney",
                "hourstag",
                "lockhour",
                "lumibopomofo",
                "lumibopomofopro",
                "lumiletters",
                "lumiletterspro",
                "lumimath",
                "lumimathpro",
                "lumimission",
                "lumimissionpro",
                "lumiweather",
                "mochi",
                "photocream",
                "picclear",
                "scanto",
                "sereno",
                "snapport",
                "sononote",
                "tripbee",
                "unblurry",
            },
            set(feed.POST_PROFILES),
        )

    def test_curated_copy_avoids_pricing_and_subscription_claims(self):
        blocked = (
            "subscription",
            "pay once",
            "one-time",
            "free",
            "訂閱",
            "免費",
            "サブスク",
            "suscripción",
        )
        for slug in feed.POST_PROFILES:
            text = feed.post_text(slug, "Example").lower()
            with self.subTest(slug=slug):
                self.assertFalse(any(term in text for term in blocked))

    def test_unknown_future_app_uses_safe_fallback(self):
        text = feed.post_text("future-app", "Future App")
        self.assertIn("Today's Lumi Studio app guide", text)
        self.assertIn("#iOSApps #IndieApps", text)

    def test_next_day_replaces_instead_of_backfilling(self):
        candidate = feed.parse_candidates(payload("lumi"))[0]
        first = ET.fromstring(feed.render_feed(candidate, today=feed.BASE_DATE))
        second = ET.fromstring(
            feed.render_feed(
                candidate,
                today=feed.BASE_DATE + dt.timedelta(days=1),
            )
        )
        self.assertEqual(1, len(first.findall(f"{{{feed.ATOM}}}entry")))
        self.assertEqual(1, len(second.findall(f"{{{feed.ATOM}}}entry")))
        self.assertNotEqual(
            first.findtext(f"{{{feed.ATOM}}}entry/{{{feed.ATOM}}}id"),
            second.findtext(f"{{{feed.ATOM}}}entry/{{{feed.ATOM}}}id"),
        )
        first_link = first.find(f"{{{feed.ATOM}}}entry/{{{feed.ATOM}}}link")
        second_link = second.find(f"{{{feed.ATOM}}}entry/{{{feed.ATOM}}}link")
        self.assertEqual(
            f"{feed.GUIDE_SITE}/guides/lumi.html",
            first_link.attrib["href"],
        )
        self.assertEqual(
            f"{feed.GUIDE_SITE}/guides/lumi.html?bridgy=2026-07-13",
            second_link.attrib["href"],
        )

    def test_repeated_app_uses_a_new_daily_bridgy_url(self):
        candidate = feed.parse_candidates(payload("lumi"))[0]
        first_repeat = ET.fromstring(
            feed.render_feed(
                candidate,
                today=feed.BASE_DATE + dt.timedelta(days=1),
            )
        )
        second_repeat = ET.fromstring(
            feed.render_feed(
                candidate,
                today=feed.BASE_DATE + dt.timedelta(days=2),
            )
        )
        first_url = first_repeat.find(
            f"{{{feed.ATOM}}}entry/{{{feed.ATOM}}}link"
        ).attrib["href"]
        second_url = second_repeat.find(
            f"{{{feed.ATOM}}}entry/{{{feed.ATOM}}}link"
        ).attrib["href"]
        self.assertNotEqual(first_url, second_url)

    def test_post_content_over_bluesky_limit_is_rejected(self):
        candidate = feed.parse_candidates(payload("lumi"))[0]
        candidate["name"] = "x" * feed.MAX_POST_LENGTH
        with self.assertRaisesRegex(ValueError, "maximum is 300"):
            feed.render_feed(candidate, today=feed.BASE_DATE)

    def test_write_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "feed.xml"
            self.assertTrue(feed.write_feed(b"content\n", path=path))
            self.assertFalse(feed.write_feed(b"content\n", path=path))


class RequestTests(unittest.TestCase):
    def test_transient_error_is_retried(self):
        error = urllib.error.HTTPError(
            feed.LINKSET_URL,
            429,
            "rate limited",
            {},
            io.BytesIO(b"rate limited"),
        )
        opener = mock.Mock(side_effect=(error, FakeResponse(b"{}")))
        sleeper = mock.Mock()
        request = mock.Mock()
        result = feed.request_bytes(
            request,
            label="test",
            opener=opener,
            sleeper=sleeper,
        )
        self.assertEqual(b"{}", result)
        self.assertEqual(2, opener.call_count)
        sleeper.assert_called_once_with(10)

    def test_run_validates_selected_live_guide(self):
        candidates = feed.parse_candidates(payload("one", "two"))
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "bridgy-feed.xml"
            write_feed = feed.write_feed
            with (
                mock.patch.object(feed, "fetch_candidates", return_value=candidates),
                mock.patch.object(feed, "validate_guide") as validate,
                mock.patch.object(
                    feed,
                    "write_feed",
                    side_effect=lambda content: write_feed(content, path=path),
                ),
            ):
                changed = feed.run(today=feed.BASE_DATE)
        self.assertTrue(changed)
        validate.assert_called_once_with(candidates[0]["url"])


class WiringTests(unittest.TestCase):
    def test_home_page_advertises_only_the_dedicated_feed(self):
        index = (feed.ROOT / "index.html").read_text(encoding="utf-8")
        self.assertEqual(1, index.count('type="application/atom+xml"'))
        self.assertIn('href="https://alice51849.github.io/bridgy-feed.xml"', index)
        self.assertIn('property="og:image"', index)

    def test_checked_in_feed_is_valid_and_single_entry(self):
        root = ET.parse(feed.FEED_PATH).getroot()
        entries = root.findall(f"{{{feed.ATOM}}}entry")
        self.assertEqual(1, len(entries))
        self.assertEqual(
            feed.ACTIVITY_NOTE,
            entries[0].findtext(f"{{{feed.ACTIVITY}}}object-type"),
        )
        content = entries[0].find(f"{{{feed.ATOM}}}content")
        self.assertEqual("html", content.attrib["type"])
        self.assertEqual("zh-Hant", content.attrib[f"{{{feed.XML}}}lang"])
        self.assertIn(">#注音符號</a>", content.text)
        self.assertIn(">#親子學習</a>", content.text)


if __name__ == "__main__":
    unittest.main()
