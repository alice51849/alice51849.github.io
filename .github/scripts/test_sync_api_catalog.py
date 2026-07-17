#!/usr/bin/env python3
"""Regression tests for the RFC 9727 API catalog sync."""

import json
import os
import pathlib
import sys
import tempfile
import unittest


HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import sync_api_catalog as catalog


def payload(anchor: str | None = None) -> dict:
    anchor = anchor or f"{catalog.GUIDE_SITE}/api/v1/example"
    return {
        "linkset": [
            {
                "anchor": anchor,
                "service-desc": [
                    {
                        "href": f"{anchor}/openapi.json",
                        "type": (
                            "application/vnd.oai.openapi+json;version=3.1"
                        ),
                    }
                ],
                "service-doc": [
                    {"href": f"{anchor}/", "type": "text/html"}
                ],
                "license": [
                    {
                        "href": "https://creativecommons.org/licenses/by/4.0/",
                        "type": "text/html",
                    }
                ],
            }
        ]
    }


class FakeResponse:
    def __init__(self, document: dict):
        self.body = json.dumps(document).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


class CatalogTests(unittest.TestCase):
    def test_valid_catalog_is_written_once(self):
        document = payload()

        def opener(_request, timeout):
            self.assertEqual(30, timeout)
            return FakeResponse(document)

        with tempfile.TemporaryDirectory() as directory:
            target = pathlib.Path(directory) / ".well-known" / "api-catalog"
            self.assertTrue(
                catalog.sync_catalog(
                    target,
                    opener=opener,
                    sleeper=lambda _seconds: None,
                )
            )
            self.assertEqual(
                document,
                json.loads(target.read_text(encoding="utf-8")),
            )
            self.assertFalse(
                catalog.sync_catalog(
                    target,
                    opener=opener,
                    sleeper=lambda _seconds: None,
                )
            )

    def test_external_or_insecure_anchors_are_rejected(self):
        for anchor in (
            "https://example.com/api/v1/example",
            f"http://alice51849.github.io/ios-app-guide/api/v1/example",
        ):
            with self.subTest(anchor=anchor):
                with self.assertRaises(ValueError):
                    catalog.validate_catalog(payload(anchor))

    def test_missing_openapi_or_docs_are_rejected(self):
        missing_openapi = payload()
        missing_openapi["linkset"][0]["service-desc"][0]["href"] = (
            f"{catalog.GUIDE_SITE}/api/v1/example/schema.json"
        )
        with self.assertRaisesRegex(ValueError, "canonical OpenAPI"):
            catalog.validate_catalog(missing_openapi)

        wrong_media_type = payload()
        wrong_media_type["linkset"][0]["service-desc"][0]["type"] = (
            "application/json"
        )
        with self.assertRaisesRegex(ValueError, "canonical OpenAPI"):
            catalog.validate_catalog(wrong_media_type)

        missing_docs = payload()
        missing_docs["linkset"][0]["service-doc"][0]["href"] = (
            f"{catalog.GUIDE_SITE}/api/"
        )
        with self.assertRaisesRegex(ValueError, "canonical docs"):
            catalog.validate_catalog(missing_docs)


if __name__ == "__main__":
    unittest.main()
