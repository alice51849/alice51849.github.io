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
import urllib.parse
import xml.etree.ElementTree as ET
from unittest import mock


HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bridgy_feed as feed


STORE_URL = "https://apps.apple.com/app/id7000000000"


def payload(*slugs: str) -> dict[str, object]:
    portfolio = {
        "anchor": f"{feed.GUIDE_SITE}/index.html",
        "item": [
            {
                "href": f"{feed.GUIDE_SITE}/guides/{slug}.html",
                "title*": [{"value": slug.title(), "language": "en"}],
            }
            for slug in slugs
        ],
    }
    contexts = [
        {
            "anchor": f"{feed.GUIDE_SITE}/guides/{slug}.html",
            "related": [
                {
                    "href": (
                        f"https://apps.apple.com/app/id{7000000000 + index}"
                        "?ct=iag_linkset"
                    ),
                    "type": "text/html",
                },
                {
                    "href": f"{feed.GUIDE_SITE}/stories/{slug}.html",
                    "type": "text/html",
                },
            ],
        }
        for index, slug in enumerate(slugs)
    ]
    return {
        "linkset": [portfolio, *contexts]
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
        self.assertEqual(
            [
                "https://apps.apple.com/app/id7000000000",
                "https://apps.apple.com/app/id7000000001",
                "https://apps.apple.com/app/id7000000002",
            ],
            [item["store_url"] for item in candidates],
        )

    def test_external_url_is_rejected(self):
        external = payload("one")
        external["linkset"][0]["item"][0]["href"] = "https://example.com/one.html"
        with self.assertRaisesRegex(ValueError, "outside the guide site"):
            feed.parse_candidates(external)

    def test_missing_or_conflicting_app_store_link_is_rejected(self):
        missing = payload("one")
        missing["linkset"][1]["related"] = []
        with self.assertRaisesRegex(ValueError, "exactly one App Store link"):
            feed.parse_candidates(missing)

        conflicting = payload("one")
        conflicting["linkset"][1]["related"].append(
            {"href": "https://apps.apple.com/app/id7999999999"}
        )
        with self.assertRaisesRegex(ValueError, "exactly one App Store link"):
            feed.parse_candidates(conflicting)

        duplicated = payload("one")
        duplicated["linkset"][1]["related"].append(
            {"href": f"{STORE_URL}?ct=second_source"}
        )
        with self.assertRaisesRegex(ValueError, "exactly one App Store link"):
            feed.parse_candidates(duplicated)

    def test_malformed_app_store_link_is_rejected(self):
        malformed = payload("one")
        malformed["linkset"][1]["related"][0]["href"] = (
            "https://apps.apple.com/app/not-an-id"
        )
        with self.assertRaisesRegex(ValueError, "invalid App Store URL"):
            feed.parse_candidates(malformed)

    def test_rotation_is_fair_and_repeats_after_full_cycle(self):
        candidates = feed.parse_candidates(payload("one", "two", "three"))
        entries = []
        state = feed._initial_rotation_state(candidates, entries)
        selected = []
        for offset in range(4):
            content, state_content, current = feed.advance_rotation(
                candidates,
                entries,
                state,
                now=feed.BASE_SLOT + feed.CADENCE * offset,
            )
            selected.extend(current)
            entries = feed.parse_feed_entries(content)
            state = json.loads(state_content)
        self.assertEqual(
            ["one", "two", "three", "one"],
            [item["slug"] for item in selected],
        )

    def test_four_daily_slots_cover_twenty_eight_apps_in_one_week(self):
        candidates = feed.parse_candidates(
            payload(*(f"app-{index}" for index in range(28)))
        )
        entries = []
        state = feed._initial_rotation_state(candidates, entries)
        selected = []
        for offset in range(28):
            content, state_content, current = feed.advance_rotation(
                candidates,
                entries,
                state,
                now=feed.BASE_SLOT + feed.CADENCE * offset,
            )
            selected.extend(current)
            entries = feed.parse_feed_entries(content)
            state = json.loads(state_content)
        self.assertEqual(28, len({item["slug"] for item in selected}))
        self.assertEqual(
            feed.FEED_ENTRY_LIMIT,
            len(feed.parse_feed_entries(content)),
        )

    def test_live_app_profile_drift_does_not_stop_rotation(self):
        candidates = feed.parse_candidates(payload("one"))
        with mock.patch.dict(
            feed.POST_PROFILES,
            {"one": feed.DEFAULT_POST_PROFILE},
            clear=True,
        ):
            self.assertEqual(([], []), feed.profile_drift(candidates))
        missing, stale = feed.profile_drift(candidates)
        self.assertEqual(["one"], missing)
        self.assertIn("wordmate", stale)
        with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            feed.warn_profile_drift(candidates)
        self.assertIn("using safe defaults", stderr.getvalue())
        self.assertEqual(
            feed.DEFAULT_POST_PROFILE,
            feed.post_profile("one"),
        )


class AtomTests(unittest.TestCase):
    def test_feed_starts_with_one_stable_entry(self):
        candidates = feed.parse_candidates(payload("lumi"))
        first = feed.render_feed(candidates, now=feed.BASE_SLOT)
        second = feed.render_feed(candidates, now=feed.BASE_SLOT)
        self.assertEqual(first, second)

        root = ET.fromstring(first)
        entries = root.findall(f"{{{feed.ATOM}}}entry")
        self.assertEqual(1, len(entries))
        self.assertEqual(
            f"{feed.GUIDE_SITE}/guides/lumi.html?bridgy=2026-07-19-18",
            entries[0].find(f"{{{feed.ATOM}}}link").attrib["href"],
        )
        related = entries[0].find(
            f"{{{feed.ATOM}}}link[@rel='related']"
        )
        self.assertEqual(STORE_URL, related.attrib["href"])
        self.assertIn(
            ":2026-07-19T18",
            entries[0].findtext(f"{{{feed.ATOM}}}id"),
        )
        content = entries[0].find(f"{{{feed.ATOM}}}content")
        self.assertEqual(
            feed.ACTIVITY_NOTE,
            entries[0].findtext(f"{{{feed.ACTIVITY}}}object-type"),
        )
        self.assertEqual("html", content.attrib["type"])
        self.assertIn("Lumi", content.text)
        self.assertEqual(3, content.text.count("<a "))
        self.assertIn(">#iOSApps</a>", content.text)
        self.assertIn(">#IndieApps</a>", content.text)
        self.assertIn(
            f'App Store: <a href="{STORE_URL}">{STORE_URL}</a>',
            content.text,
        )
        self.assertEqual("en", content.attrib[f"{{{feed.XML}}}lang"])
        summary = entries[0].findtext(f"{{{feed.ATOM}}}summary")
        self.assertIn(f"App Store: {STORE_URL}", summary)
        self.assertLessEqual(len(feed.post_text("lumi", "Lumi", STORE_URL)), 300)

    def test_revenue_market_profiles_are_localized(self):
        cases = {
            "lumibopomofopro": ("zh-Hant", "注音符號", "#親子學習"),
            "hourstag": ("zh-Hant", "工作", "#消費習慣"),
            "aim990": ("ja", "30日学習計画", "#英語学習"),
            "cyca": ("es", "Registra ciclos", "#Privacidad"),
        }
        for slug, (locale, phrase, hashtag) in cases.items():
            with self.subTest(slug=slug):
                text = feed.post_text(slug, "Example", STORE_URL)
                content = feed.post_content(slug, "Example", STORE_URL)
                self.assertEqual(locale, feed.post_profile(slug)[0])
                self.assertIn(phrase, text)
                self.assertIn(hashtag, text)
                self.assertIn(hashtag, content)
                self.assertIn(STORE_URL, text)
                self.assertIn(STORE_URL, content)
                self.assertLessEqual(len(text), feed.MAX_POST_LENGTH)

    def test_all_current_live_apps_have_curated_profiles(self):
        self.assertEqual(
            {
                "aim990",
                "cvdesk",
                "cyca",
                "dailymate",
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
                "tripbeelite",
                "tripplanet",
                "unblurry",
                "wordmate",
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
            text = feed.post_text(slug, "Example", STORE_URL).lower()
            with self.subTest(slug=slug):
                self.assertFalse(any(term in text for term in blocked))

    def test_all_profiles_leave_room_for_app_name_and_store_link(self):
        for slug in feed.POST_PROFILES:
            with self.subTest(slug=slug):
                text = feed.post_text(slug, "x" * 40, STORE_URL)
                self.assertLessEqual(len(text), feed.MAX_POST_LENGTH)

    def test_unknown_future_app_uses_safe_fallback(self):
        text = feed.post_text("future-app", "Future App", STORE_URL)
        self.assertIn("Today's Lumi Studio app guide", text)
        self.assertIn("#iOSApps #IndieApps", text)
        self.assertIn(STORE_URL, text)

    def test_next_slot_retains_a_bounded_delivery_window(self):
        candidates = feed.parse_candidates(payload("lumi"))
        first_content, state_content, _selected = feed.advance_rotation(
            candidates,
            [],
            feed._initial_rotation_state(candidates, []),
            now=feed.BASE_SLOT,
        )
        first_entries = feed.parse_feed_entries(first_content)
        second_content, _state_content, _selected = feed.advance_rotation(
            candidates,
            first_entries,
            json.loads(state_content),
            now=feed.BASE_SLOT + feed.CADENCE,
        )
        first = ET.fromstring(first_content)
        second = ET.fromstring(second_content)
        self.assertEqual(1, len(first.findall(f"{{{feed.ATOM}}}entry")))
        self.assertEqual(2, len(second.findall(f"{{{feed.ATOM}}}entry")))
        self.assertNotEqual(
            first.findtext(f"{{{feed.ATOM}}}entry/{{{feed.ATOM}}}id"),
            second.findtext(f"{{{feed.ATOM}}}entry/{{{feed.ATOM}}}id"),
        )
        first_link = first.find(f"{{{feed.ATOM}}}entry/{{{feed.ATOM}}}link")
        second_link = second.find(f"{{{feed.ATOM}}}entry/{{{feed.ATOM}}}link")
        self.assertEqual(
            f"{feed.GUIDE_SITE}/guides/lumi.html?bridgy=2026-07-19-18",
            first_link.attrib["href"],
        )
        self.assertEqual(
            f"{feed.GUIDE_SITE}/guides/lumi.html?bridgy=2026-07-20-00",
            second_link.attrib["href"],
        )

    def test_persisted_rotation_preserves_history_when_candidates_reorder(self):
        candidates = feed.parse_candidates(payload("one", "two", "three"))
        first_content, first_state, selected = feed.advance_rotation(
            candidates,
            [],
            feed._initial_rotation_state(candidates, []),
            now=feed.BASE_SLOT,
        )
        first_entries = feed.parse_feed_entries(first_content)
        second_content, second_state, selected = feed.advance_rotation(
            candidates,
            first_entries,
            json.loads(first_state),
            now=feed.BASE_SLOT + feed.CADENCE,
        )
        self.assertEqual(["two"], [item["slug"] for item in selected])
        history_entries = feed.parse_feed_entries(second_content)
        before = {
            entry.findtext(f"{{{feed.ATOM}}}id"): ET.tostring(entry)
            for entry in history_entries
        }

        reordered = feed.parse_candidates(payload("three", "one", "two"))
        with tempfile.TemporaryDirectory() as directory:
            state_path = pathlib.Path(directory) / "rotation.json"
            state_path.write_bytes(second_state)
            persisted = feed._load_rotation_state(
                reordered,
                history_entries,
                path=state_path,
            )
        third_content, _third_state, selected = feed.advance_rotation(
            reordered,
            history_entries,
            persisted,
            now=feed.BASE_SLOT + feed.CADENCE * 2,
        )
        self.assertEqual(["three"], [item["slug"] for item in selected])
        third_entries = feed.parse_feed_entries(third_content)
        after = {
            entry.findtext(f"{{{feed.ATOM}}}id"): ET.tostring(entry)
            for entry in third_entries
        }
        for entry_id, serialized in before.items():
            self.assertEqual(serialized, after[entry_id])

    def test_missed_slots_publish_only_the_current_entry(self):
        candidates = feed.parse_candidates(payload("one", "two", "three"))
        content, state_content, selected = feed.advance_rotation(
            candidates,
            [],
            feed._initial_rotation_state(candidates, []),
            now=feed.BASE_SLOT + feed.CADENCE * 10,
        )
        self.assertEqual(["one"], [item["slug"] for item in selected])
        entries = feed.parse_feed_entries(content)
        self.assertEqual(1, len(entries))
        self.assertEqual(
            feed.BASE_SLOT + feed.CADENCE * 10,
            feed._entry_published(entries[0]),
        )
        self.assertEqual(
            "2026-07-22T06:00:00Z",
            json.loads(state_content)["last_slot"],
        )

    def test_live_app_additions_and_removals_reconcile_the_queue(self):
        candidates = feed.parse_candidates(payload("one", "two"))
        content, state_content, _selected = feed.advance_rotation(
            candidates,
            [],
            feed._initial_rotation_state(candidates, []),
            now=feed.BASE_SLOT,
        )
        entries = feed.parse_feed_entries(content)
        changed = feed.parse_candidates(payload("two", "three"))
        with tempfile.TemporaryDirectory() as directory:
            state_path = pathlib.Path(directory) / "rotation.json"
            state_path.write_bytes(state_content)
            state = feed._load_rotation_state(
                changed,
                entries,
                path=state_path,
            )
        self.assertEqual(["two", "three"], state["remaining"])

        content, state_content, selected = feed.advance_rotation(
            changed,
            entries,
            state,
            now=feed.BASE_SLOT + feed.CADENCE,
        )
        self.assertEqual(["two"], [item["slug"] for item in selected])
        content, _state_content, selected = feed.advance_rotation(
            changed,
            feed.parse_feed_entries(content),
            json.loads(state_content),
            now=feed.BASE_SLOT + feed.CADENCE * 2,
        )
        self.assertEqual(["three"], [item["slug"] for item in selected])

    def test_persisted_rotation_is_idempotent_within_one_slot(self):
        candidates = feed.parse_candidates(payload("one", "two"))
        content, state_content, selected = feed.advance_rotation(
            candidates,
            [],
            feed._initial_rotation_state(candidates, []),
            now=feed.BASE_SLOT,
        )
        self.assertEqual(["one"], [item["slug"] for item in selected])
        repeated_content, repeated_state, selected = feed.advance_rotation(
            candidates,
            feed.parse_feed_entries(content),
            json.loads(state_content),
            now=feed.BASE_SLOT,
        )
        self.assertEqual([], selected)
        self.assertEqual(content, repeated_content)
        self.assertEqual(state_content, repeated_state)

    def test_initial_state_does_not_repeat_a_legacy_feed_app(self):
        candidates = feed.parse_candidates(payload("hourstag", "next-app"))
        candidate_by_slug = {
            candidate["slug"]: candidate for candidate in candidates
        }
        entries = [
            feed._rotation_entry(
                "hourstag",
                candidate_by_slug,
                feed.BASE_SLOT - feed.CADENCE * 3,
            )
        ]
        state = feed._initial_rotation_state(candidates, entries)
        self.assertEqual(["next-app"], state["remaining"])
        self.assertEqual(
            "2026-07-19T12:00:00Z",
            state["last_slot"],
        )

    def test_repeated_app_uses_a_new_slot_url(self):
        candidates = feed.parse_candidates(payload("lumi"))
        first_repeat = ET.fromstring(
            feed.render_feed(
                candidates,
                now=feed.BASE_SLOT + feed.CADENCE,
            )
        )
        second_repeat = ET.fromstring(
            feed.render_feed(
                candidates,
                now=feed.BASE_SLOT + feed.CADENCE * 2,
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
        candidates = feed.parse_candidates(payload("lumi"))
        candidates[0]["name"] = "x" * feed.MAX_POST_LENGTH
        with self.assertRaisesRegex(ValueError, "maximum is 300"):
            feed.render_feed(candidates, now=feed.BASE_SLOT)

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
            feed_path = pathlib.Path(directory) / "bridgy-feed.xml"
            state_path = pathlib.Path(directory) / "rotation.json"
            with (
                mock.patch.object(feed, "fetch_candidates", return_value=candidates),
                mock.patch.object(feed, "warn_profile_drift"),
                mock.patch.object(feed, "validate_guide") as validate,
            ):
                changed = feed.run(
                    now=feed.BASE_SLOT,
                    feed_path=feed_path,
                    state_path=state_path,
                )
            self.assertTrue(feed_path.exists())
            self.assertTrue(state_path.exists())
        self.assertTrue(changed)
        validate.assert_called_once_with(candidates[0]["url"])


class WiringTests(unittest.TestCase):
    def test_home_page_advertises_only_the_dedicated_feed(self):
        index = (feed.ROOT / "index.html").read_text(encoding="utf-8")
        self.assertEqual(1, index.count('type="application/atom+xml"'))
        self.assertIn('href="https://alice51849.github.io/bridgy-feed.xml"', index)
        self.assertIn('property="og:image"', index)
        self.assertIn(
            "https://bsky.app/profile/alice51849.github.io.web.brid.gy",
            index,
        )
        self.assertIn('hero_cta1:"探索 {count} 款作品"', index)
        self.assertIn('hero_cta1:"Explore {count} Apps"', index)
        self.assertIn("50-locale catalog", index)
        self.assertIn("guide coverage varies by app", index)
        for claim in (
            "無廣告",
            "沒有訂閱",
            "No ads",
            "No subscriptions",
            "広告なし",
            "サブスクなし",
            "광고 없음",
            "구독 없음",
            "50 語指南",
            "50-locale guides",
            "50地域のガイド",
            "50개 지역 가이드",
        ):
            self.assertNotIn(claim, index)

        llms = (feed.ROOT / "llms.txt").read_text(encoding="utf-8")
        self.assertIn("Bridged Bluesky app guides", llms)
        self.assertIn("ActivityPub app guide profile", llms)

    def test_checked_in_feed_is_valid_and_bounded(self):
        root = ET.parse(feed.FEED_PATH).getroot()
        entries = root.findall(f"{{{feed.ATOM}}}entry")
        self.assertGreaterEqual(len(entries), 1)
        self.assertLessEqual(len(entries), feed.FEED_ENTRY_LIMIT)
        entry = entries[0]
        self.assertEqual(
            feed.ACTIVITY_NOTE,
            entry.findtext(f"{{{feed.ACTIVITY}}}object-type"),
        )
        alternate = entry.find(f"{{{feed.ATOM}}}link[@rel='alternate']")
        self.assertIsNotNone(alternate)
        slug = pathlib.PurePosixPath(
            urllib.parse.urlsplit(alternate.attrib["href"]).path
        ).stem
        locale, _focus, hashtags = feed.post_profile(slug)

        related = entry.find(f"{{{feed.ATOM}}}link[@rel='related']")
        self.assertIsNotNone(related)
        store_url = related.attrib["href"]
        self.assertRegex(store_url, r"^https://apps\.apple\.com/app/id\d+$")

        content = entry.find(f"{{{feed.ATOM}}}content")
        self.assertEqual("html", content.attrib["type"])
        self.assertEqual(locale, content.attrib[f"{{{feed.XML}}}lang"])
        for hashtag in hashtags:
            self.assertIn(f">#{hashtag}</a>", content.text)
        self.assertEqual(2, content.text.count(store_url))

        summary = entry.find(f"{{{feed.ATOM}}}summary")
        self.assertEqual(locale, summary.attrib[f"{{{feed.XML}}}lang"])
        self.assertEqual(1, summary.text.count(store_url))


if __name__ == "__main__":
    unittest.main()
