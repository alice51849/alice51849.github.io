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
        self.assertEqual("text", content.attrib["type"])
        self.assertIn("Lumi", content.text)
        self.assertIn("#iOSApps #IndieApps", content.text)
        self.assertLessEqual(len(content.text), 300)

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
        content = entries[0].findtext(f"{{{feed.ATOM}}}content")
        self.assertIn("#iOSApps #IndieApps", content)


if __name__ == "__main__":
    unittest.main()
