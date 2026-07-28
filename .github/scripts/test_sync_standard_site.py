#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import urllib.error

import sync_standard_site as syncer


RKEY = "3mabcdefghi2j"
AT_URI = (
    f"at://{syncer.EXPECTED_DID}/{syncer.COLLECTION}/{RKEY}"
)
DOCUMENT_RKEY = "3mabcdefghi3k"
DOCUMENT_URI = (
    f"at://{syncer.EXPECTED_DID}/{syncer.DOCUMENT_COLLECTION}/"
    f"{DOCUMENT_RKEY}"
)


def payload(
    *,
    uri: str = AT_URI,
    publication_url: str = syncer.PUBLICATION_URL,
) -> dict:
    return {
        "records": [
            {
                "uri": uri,
                "cid": "bafyreiabcdef",
                "value": {
                    "$type": syncer.COLLECTION,
                    "url": publication_url,
                    "name": "Lumi Studio App Guides",
                },
            }
        ]
    }


def document_payload(
    *,
    site: str = AT_URI,
    path: str = "/answers/alpha.html",
    app_key: str = "alpha",
) -> dict:
    return {
        "records": [
            {
                "uri": DOCUMENT_URI,
                "cid": "bafyreidocument",
                "value": {
                    "$type": syncer.DOCUMENT_COLLECTION,
                    "site": site,
                    "path": path,
                    "title": "Alpha guide",
                    "description": "A verified guide.",
                    "textContent": "Publisher-authored guide content.",
                    "tags": [app_key, "iOS"],
                    "publishedAt": "2026-07-27T14:00:00.000Z",
                },
            }
        ]
    }


class FakeResponse:
    def __init__(self, value: object):
        self.body = json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


class StandardSiteSyncTests(unittest.TestCase):
    def test_expected_publication_is_written_once(self):
        def opener(request, timeout):
            self.assertEqual(syncer.records_url(), request.full_url)
            self.assertEqual(30, timeout)
            return FakeResponse(payload())

        with tempfile.TemporaryDirectory() as directory:
            target = (
                Path(directory)
                / ".well-known"
                / syncer.COLLECTION
                / "ios-app-guide"
            )
            uri, changed = syncer.sync(
                target,
                write=True,
                opener=opener,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(AT_URI, uri)
            self.assertTrue(changed)
            self.assertEqual(AT_URI + "\n", target.read_text())
            _, changed = syncer.sync(
                target,
                write=True,
                opener=opener,
                sleeper=lambda _seconds: None,
            )
            self.assertFalse(changed)

    def test_check_only_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "verifier"
            uri, changed = syncer.sync(
                target,
                opener=lambda _request, timeout: FakeResponse(payload()),
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(AT_URI, uri)
            self.assertFalse(changed)
            self.assertFalse(target.exists())

    def test_wrong_identity_or_publication_is_rejected(self):
        cases = (
            payload(
                uri=(
                    "at://did:plc:wrongidentity/"
                    f"{syncer.COLLECTION}/{RKEY}"
                )
            ),
            payload(publication_url="https://example.com"),
            {"records": payload()["records"] * 2},
            {"records": payload()["records"], "cursor": "more"},
        )
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(syncer.SyncError):
                    syncer.publication_at_uri(value)

    def test_missing_publication_never_overwrites_existing_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "verifier"
            target.write_text(AT_URI + "\n", encoding="utf-8")
            with self.assertRaises(syncer.PublicationNotReady):
                syncer.sync(
                    target,
                    write=True,
                    opener=lambda _request, timeout: FakeResponse(
                        {"records": []}
                    ),
                    sleeper=lambda _seconds: None,
                )
            self.assertEqual(AT_URI + "\n", target.read_text())

    def test_transient_fetch_is_retried(self):
        calls = 0

        def opener(request, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise urllib.error.HTTPError(
                    request.full_url,
                    503,
                    "unavailable",
                    {},
                    None,
                )
            return FakeResponse(payload())

        result = syncer.fetch_records(
            opener=opener,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual(payload(), result)
        self.assertEqual(2, calls)

    def test_public_guide_contract_is_materialized_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "standard_site_guide_contract.json"
            contract, changed = syncer.sync_guide_contract(
                AT_URI,
                target,
                write=True,
                opener=lambda _request, timeout: FakeResponse(
                    document_payload()
                ),
                sleeper=lambda _seconds: None,
            )
            self.assertTrue(changed)
            self.assertEqual(
                "https://alice51849.github.io/ios-app-guide/"
                "answers/alpha.html",
                contract["documents"][0]["canonical_url"],
            )
            self.assertEqual("alpha", contract["documents"][0]["app_key"])
            self.assertEqual(
                DOCUMENT_URI, contract["documents"][0]["at_uri"]
            )
            self.assertEqual(
                contract,
                json.loads(target.read_text(encoding="utf-8")),
            )
            _, changed = syncer.sync_guide_contract(
                AT_URI,
                target,
                write=True,
                opener=lambda _request, timeout: FakeResponse(
                    document_payload()
                ),
                sleeper=lambda _seconds: None,
            )
            self.assertFalse(changed)

    def test_guide_contract_rejects_unsafe_or_ambiguous_documents(self):
        cases = (
            document_payload(site="at://did:plc:other/site.standard.publication/x"),
            document_payload(path="/../secret.html"),
            document_payload(app_key="NOT SAFE"),
            {
                "records": (
                    document_payload()["records"]
                    + document_payload()["records"]
                )
            },
        )
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(syncer.SyncError):
                    syncer.guide_contract(AT_URI, value)

    def test_paginated_record_fetch_is_bounded(self):
        urls: list[str] = []

        def opener(request, timeout):
            urls.append(request.full_url)
            if "cursor=" not in request.full_url:
                return FakeResponse(
                    {"records": [{"page": 1}], "cursor": "next-page"}
                )
            return FakeResponse({"records": [{"page": 2}]})

        result = syncer.fetch_all_records(
            syncer.DOCUMENT_COLLECTION,
            opener=opener,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual([{"page": 1}, {"page": 2}], result["records"])
        self.assertEqual(2, len(urls))
        self.assertIn("collection=site.standard.document", urls[0])
        self.assertIn("cursor=next-page", urls[1])

    def test_workflow_persists_both_public_artifacts(self):
        workflow = (
            syncer.ROOT / ".github/workflows/sync-standard-site.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("standard_site_guide_contract.json", workflow)
        self.assertIn('"${targets[@]}"', workflow)


if __name__ == "__main__":
    unittest.main()
