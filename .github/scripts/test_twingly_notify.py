#!/usr/bin/env python3
"""Regression tests for the Twingly Blog Search notification."""

import os
import sys
import unittest
import urllib.error
import urllib.request
import xmlrpc.client
from unittest import mock


HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pingomatic_notify as common
import twingly_notify as twingly
from test_pingomatic_notify import FakeResponse, response


def feed(url: str) -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="{common.ATOM}">
  <entry>
    <title>Example - independent iOS app guide</title>
    <link rel="alternate" type="text/html" href="{url}" />
    <content type="text">Example feed content.</content>
  </entry>
</feed>
""".encode()


class EntryTests(unittest.TestCase):
    def test_checked_in_entry_uses_a_public_guide(self):
        title, url = twingly.entry_details(common.FEED_PATH.read_bytes())
        self.assertIn("independent iOS app guide", title)
        self.assertTrue(url.startswith(f"{common.SITE_URL}ios-app-guide/guides/"))

    def test_external_entry_url_is_rejected(self):
        with self.assertRaisesRegex(common.NotifyError, "outside the guide site"):
            twingly.entry_details(feed("https://example.com/app.html"))

    def test_nested_entry_url_is_rejected(self):
        with self.assertRaisesRegex(common.NotifyError, "outside the guide site"):
            twingly.entry_details(
                feed(f"{common.SITE_URL}ios-app-guide/guides/nested/app.html")
            )

    def test_daily_bridgy_query_is_accepted(self):
        url = (
            f"{common.SITE_URL}ios-app-guide/guides/example.html"
            "?bridgy=2026-07-13"
        )
        _title, parsed_url = twingly.entry_details(feed(url))
        self.assertEqual(url, parsed_url)

    def test_unrecognized_query_is_rejected(self):
        with self.assertRaisesRegex(common.NotifyError, "outside the guide site"):
            twingly.entry_details(
                feed(
                    f"{common.SITE_URL}ios-app-guide/guides/example.html"
                    "?utm_source=test"
                )
            )


class RpcTests(unittest.TestCase):
    def test_request_matches_twingly_extended_ping_documentation(self):
        entry_url = f"{common.SITE_URL}ios-app-guide/guides/example.html"
        params, method = xmlrpc.client.loads(twingly.render_ping_request(entry_url))
        self.assertEqual("weblogUpdates.extendedPing", method)
        self.assertEqual(
            (common.SITE_NAME, common.SITE_URL, entry_url, common.FEED_URL),
            params,
        )

    def test_send_ping_posts_once_to_official_endpoint(self):
        captured = {}

        def opener(request: urllib.request.Request, *, timeout: int):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse(response(message="Thanks for the ping."))

        entry_url = f"{common.SITE_URL}ios-app-guide/guides/example.html"
        self.assertEqual(
            "Thanks for the ping.",
            twingly.send_ping(entry_url, opener=opener),
        )
        self.assertEqual(twingly.RPC_URL, captured["request"].full_url)
        self.assertEqual("POST", captured["request"].get_method())
        self.assertEqual(30, captured["timeout"])

    def test_uncertain_post_is_not_retried(self):
        opener = mock.Mock(side_effect=urllib.error.URLError("connection reset"))
        with self.assertRaisesRegex(common.NotifyError, "connection reset"):
            twingly.send_ping(
                f"{common.SITE_URL}ios-app-guide/guides/example.html",
                opener=opener,
            )
        self.assertEqual(1, opener.call_count)


class WiringTests(unittest.TestCase):
    def test_cli_refuses_an_unguarded_notification(self):
        with (
            mock.patch.object(twingly, "run") as run,
            mock.patch("sys.stderr"),
        ):
            self.assertEqual(2, twingly.main([]))
        run.assert_not_called()

    def test_workflow_runs_twingly_only_after_a_persisted_change(self):
        workflow = (
            common.ROOT / ".github/workflows/bridgy-feed-daily.yml"
        ).read_text(encoding="utf-8")
        condition = "if: steps.persist.outputs.changed == 'true'"
        self.assertEqual(1, workflow.count(condition))
        self.assertIn("python3 .github/scripts/test_twingly_notify.py -q", workflow)
        self.assertIn(
            "python3 .github/scripts/twingly_notify.py --feed-changed",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
