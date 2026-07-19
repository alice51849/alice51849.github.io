#!/usr/bin/env python3
"""Regression tests for public Bridgy Bluesky delivery checks."""

import datetime as dt
import json
import os
import pathlib
import sys
import tempfile
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bridgy_delivery_check as delivery


class FakeResponse:
    def __init__(self, payload: object):
        self.body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def atom(*, published: str, url: str) -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="{delivery.feed.ATOM}">
  <entry>
    <published>{published}</published>
    <link rel="alternate" type="text/html" href="{url}" />
  </entry>
</feed>
""".encode()


class DeliveryTests(unittest.TestCase):
    def test_only_mature_entries_require_delivery(self):
        url = (
            "https://alice51849.github.io/ios-app-guide/guides/example.html"
            "?bridgy=2026-07-19-18"
        )
        recent = delivery.expected_deliveries(
            atom(published="2026-07-19T18:00:00Z", url=url),
            now=dt.datetime(2026, 7, 20, 6, tzinfo=dt.timezone.utc),
        )
        mature = delivery.expected_deliveries(
            atom(published="2026-07-19T18:00:00Z", url=url),
            now=dt.datetime(2026, 7, 20, 12, tzinfo=dt.timezone.utc),
        )
        self.assertEqual(set(), recent)
        self.assertEqual({url}, mature)

    def test_invalid_bridge_url_is_rejected(self):
        with self.assertRaisesRegex(delivery.DeliveryError, "invalid bridge URL"):
            delivery.expected_deliveries(
                atom(
                    published="2026-07-19T00:00:00Z",
                    url="https://example.com/guides/app.html?bridgy=2026-07-19",
                ),
                now=dt.datetime(2026, 7, 20, tzinfo=dt.timezone.utc),
            )

    def test_mature_entry_must_be_in_public_author_feed(self):
        url = (
            "https://alice51849.github.io/ios-app-guide/guides/example.html"
            "?bridgy=2026-07-19"
        )
        content = atom(published="2026-07-19T00:00:00Z", url=url)
        payload = {
            "feed": [
                {"post": {"record": {"bridgyOriginalUrl": url}}},
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "feed.xml"
            path.write_bytes(content)
            confirmed = delivery.run(
                now=dt.datetime(2026, 7, 20, tzinfo=dt.timezone.utc),
                feed_path=path,
                opener=lambda _request, timeout: FakeResponse(payload),
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(1, confirmed)

            with self.assertRaisesRegex(delivery.DeliveryError, "missing"):
                delivery.run(
                    now=dt.datetime(2026, 7, 20, tzinfo=dt.timezone.utc),
                    feed_path=path,
                    opener=lambda _request, timeout: FakeResponse({"feed": []}),
                    sleeper=lambda _seconds: None,
                )

    def test_recent_entry_does_not_call_bluesky(self):
        url = (
            "https://alice51849.github.io/ios-app-guide/guides/example.html"
            "?bridgy=2026-07-19-18"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "feed.xml"
            path.write_bytes(
                atom(published="2026-07-19T18:00:00Z", url=url)
            )

            def unexpected_opener(_request, timeout):
                raise AssertionError(f"unexpected network call: {timeout}")

            self.assertEqual(
                0,
                delivery.run(
                    now=dt.datetime(2026, 7, 20, 6, tzinfo=dt.timezone.utc),
                    feed_path=path,
                    opener=unexpected_opener,
                ),
            )


class WiringTests(unittest.TestCase):
    def test_workflow_checks_delivery_before_generating(self):
        workflow = (
            delivery.feed.ROOT / ".github/workflows/bridgy-feed-daily.yml"
        ).read_text(encoding="utf-8")
        check = "run: python3 .github/scripts/bridgy_delivery_check.py"
        generate = "run: python3 .github/scripts/bridgy_feed.py"
        self.assertIn(check, workflow)
        self.assertLess(workflow.index(check), workflow.index(generate))
        self.assertIn('cron: "5 0,6,12,18 * * *"', workflow)
        self.assertIn(
            "git add bridgy-feed.xml .github/bridgy-rotation-state.json",
            workflow,
        )
        self.assertIn(
            "steps.persist.outputs.feed_changed == 'true'",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
