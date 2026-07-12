#!/usr/bin/env python3
"""Regression tests for the Ping-O-Matic feed notification."""

import io
import os
import pathlib
import sys
import unittest
import urllib.error
import urllib.request
import xmlrpc.client
from unittest import mock


HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import pingomatic_notify as notify


def response(*, failed: bool = False, message: str = "Ping accepted") -> bytes:
    return xmlrpc.client.dumps(
        ({"flerror": failed, "message": message},),
        methodresponse=True,
        allow_none=False,
        encoding="utf-8",
    ).encode("utf-8")


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]


class FeedTests(unittest.TestCase):
    def test_checked_in_feed_is_single_entry_atom(self):
        title = notify.validate_feed(notify.FEED_PATH.read_bytes())
        self.assertIn("independent iOS app guide", title)

    def test_multiple_entries_are_rejected(self):
        content = (
            b'<feed xmlns="http://www.w3.org/2005/Atom">'
            b"<entry><title>One</title></entry>"
            b"<entry><title>Two</title></entry>"
            b"</feed>"
        )
        with self.assertRaisesRegex(notify.NotifyError, "2 entries"):
            notify.validate_feed(content)

    def test_entry_without_html_note_content_is_rejected(self):
        content = (
            b'<feed xmlns="http://www.w3.org/2005/Atom" '
            b'xmlns:activity="http://activitystrea.ms/spec/1.0/">'
            b"<entry><title>One</title>"
            b"<activity:object-type>"
            b"http://activitystrea.ms/schema/1.0/note"
            b"</activity:object-type></entry>"
            b"</feed>"
        )
        with self.assertRaisesRegex(notify.NotifyError, "HTML note content"):
            notify.validate_feed(content)

    def test_waits_until_exact_public_bytes_are_live(self):
        expected = b"new feed"
        opener = mock.Mock(
            side_effect=(FakeResponse(b"old feed"), FakeResponse(expected))
        )
        sleeper = mock.Mock()
        checks = notify.wait_for_live_feed(
            expected,
            attempts=3,
            interval=7,
            opener=opener,
            sleeper=sleeper,
        )
        self.assertEqual(2, checks)
        self.assertEqual(2, opener.call_count)
        sleeper.assert_called_once_with(7)

    def test_non_transient_public_error_is_not_retried(self):
        error = urllib.error.HTTPError(
            notify.FEED_URL,
            403,
            "forbidden",
            {},
            io.BytesIO(b"forbidden"),
        )
        opener = mock.Mock(side_effect=error)
        with self.assertRaisesRegex(notify.FetchError, "HTTP 403"):
            notify.wait_for_live_feed(
                b"expected",
                attempts=3,
                opener=opener,
                sleeper=mock.Mock(),
            )
        self.assertEqual(1, opener.call_count)

    def test_stale_public_feed_has_bounded_checks(self):
        opener = mock.Mock(return_value=FakeResponse(b"old feed"))
        sleeper = mock.Mock()
        with self.assertRaisesRegex(notify.NotifyError, "after 3 checks"):
            notify.wait_for_live_feed(
                b"new feed",
                attempts=3,
                interval=2,
                opener=opener,
                sleeper=sleeper,
            )
        self.assertEqual(3, opener.call_count)
        self.assertEqual([mock.call(2), mock.call(2)], sleeper.call_args_list)


class RpcTests(unittest.TestCase):
    def test_request_uses_official_extended_ping_shape(self):
        params, method = xmlrpc.client.loads(notify.render_ping_request())
        self.assertEqual("weblogUpdates.extendedPing", method)
        self.assertEqual(
            (notify.SITE_NAME, notify.SITE_URL, notify.FEED_URL),
            params,
        )

    def test_success_response_is_accepted(self):
        self.assertEqual("Forwarded to services", notify.parse_ping_response(
            response(message="Forwarded to services")
        ))

    def test_failure_response_is_rejected(self):
        with self.assertRaisesRegex(notify.NotifyError, "Slow down"):
            notify.parse_ping_response(response(failed=True, message="Slow down"))

    def test_send_ping_posts_xml_once(self):
        captured = {}

        def opener(request: urllib.request.Request, *, timeout: int):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse(response(message="Accepted"))

        self.assertEqual("Accepted", notify.send_ping(opener=opener))
        request = captured["request"]
        self.assertEqual(notify.RPC_URL, request.full_url)
        self.assertEqual("POST", request.get_method())
        self.assertEqual(30, captured["timeout"])
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual("text/xml; charset=utf-8", headers["content-type"])

    def test_uncertain_post_is_not_retried(self):
        opener = mock.Mock(side_effect=urllib.error.URLError("connection reset"))
        with self.assertRaisesRegex(notify.NotifyError, "connection reset"):
            notify.send_ping(opener=opener)
        self.assertEqual(1, opener.call_count)


class WiringTests(unittest.TestCase):
    def test_cli_refuses_an_unguarded_notification(self):
        with (
            mock.patch.object(notify, "run") as run,
            mock.patch("sys.stderr"),
        ):
            self.assertEqual(2, notify.main([]))
        run.assert_not_called()

    def test_workflow_only_notifies_after_a_persisted_change(self):
        workflow = (
            notify.ROOT / ".github/workflows/bridgy-feed-daily.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("id: persist", workflow)
        self.assertIn("changed=true", workflow)
        self.assertIn(
            "if: steps.persist.outputs.changed == 'true'",
            workflow,
        )
        self.assertIn(
            "python3 .github/scripts/pingomatic_notify.py --feed-changed",
            workflow,
        )
        self.assertNotIn("[skip ci]", workflow)


if __name__ == "__main__":
    unittest.main()
