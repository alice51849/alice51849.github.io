#!/usr/bin/env python3
"""Regression tests for the Instagram profile-link hub mirror (ig_hub_sync.py); no network."""

import io
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import ig_hub_sync as hub  # noqa: E402


def button(app: str, ios: int, country: str = "") -> str:
    store = f"https://apps.apple.com/{country}app/id{ios}?pt=118326163&amp;ct=ig_bio_{app}&amp;mt=8"
    return f'<li class="app" data-app="{app}"><a class="main" href="{store}">{app}</a></li>'


def page(n: int = 12, extra: str = "") -> str:
    rows = "".join(button(f"app{i}", 6700000000 + i, "tw/" if i == 0 else "") for i in range(n))
    play = ('<a class="gp" href="https://play.google.com/store/apps/details?id=com.alice51849.App0'
            '&amp;referrer=utm_source%3Dig_bio_app0%26utm_campaign%3Dapp0">Google Play</a>')
    icon = '<img class="ic" src="https://is1-ssl.mzstatic.com/image/thumb/x/100x100bb.jpg" alt="">'
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            '<meta name="lumi-ig-hub" content="1"><meta name="lumi-ig-hub-latest" content="2026-10-17T03:01:21Z">'
            f"</head><body><main><ul>{icon}{rows}{play}</ul>"
            '<footer><a href="https://open.cait518.cc/">Lumi Studio</a></footer>'
            f"{extra}</main><script>(function(){{}})();</script></body></html>\n")


class ChecksTest(unittest.TestCase):
    def test_a_built_hub_page_passes(self):
        self.assertEqual(hub.problems(page()), [])

    def test_pages_that_must_never_reach_the_profile_link_are_refused(self):
        cases = {
            "no marker": page().replace('<meta name="lumi-ig-hub" content="1">', ""),
            "too few apps": page(n=3),
            "untracked store link": page().replace("ct=ig_bio_app3", "ct=other"),
            "no provider token": page().replace("pt=118326163&amp;", "", 1),
            "foreign script": page(extra='<script src="https://cdn.example/t.js"></script>'),
            "frame": page(extra='<iframe src="https://example.com"></iframe>'),
            "form": page(extra='<form action="https://example.com"></form>'),
            "plain http": page(extra='<a href="http://example.com">x</a>'),
            "other host": page(extra='<a href="https://example.com/x">x</a>'),
            "untracked play": page().replace("utm_source%3Dig_bio_app0", "utm_source%3Dx"),
            "not html": page().replace("<!doctype html>", "", 1),
        }
        for why, text in cases.items():
            self.assertTrue(hub.problems(text), why)


class SyncTest(unittest.TestCase):
    def test_writes_only_a_changed_page_and_never_a_bad_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ig" / "index.html"
            self.assertTrue(hub.sync(page(), out))
            self.assertFalse(hub.sync(page(), out))              # unchanged: nothing to commit
            self.assertTrue(hub.sync(page(n=13), out))
            with self.assertRaises(ValueError):
                hub.sync(page(n=2), out)
            self.assertEqual(out.read_text(encoding="utf-8"), page(n=13))   # the live page stays

    def test_fetch_asks_the_contents_api_for_the_raw_file_of_main(self):
        seen = {}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(req, timeout=0):
            seen["url"], seen["headers"] = req.full_url, dict(req.header_items())
            return Resp(page().encode("utf-8"))

        self.assertEqual(hub.fetch(token="t0k", opener=opener), page())
        self.assertIn("/repos/alice51849/ios-app-guide/contents/.github/growth/ig-hub/index.html?ref=main", seen["url"])
        self.assertEqual(seen["headers"].get("Accept"), "application/vnd.github.raw")
        self.assertEqual(seen["headers"].get("Authorization"), "Bearer t0k")

    def test_main_fails_loudly_and_keeps_the_page_when_the_source_cannot_be_read(self):
        def broken(*a, **k):
            raise urllib.error.URLError("down")

        original = hub.fetch
        hub.fetch = lambda token=None: broken()
        try:
            out = io.StringIO()
            sys.stdout, saved = out, sys.stdout
            try:
                self.assertEqual(hub.main([]), 1)
            finally:
                sys.stdout = saved
            self.assertIn("::error::", out.getvalue())
        finally:
            hub.fetch = original


if __name__ == "__main__":
    unittest.main()
