#!/usr/bin/env python3
"""Regression tests for the RFC 9727 API catalog sync."""

import json
import os
import pathlib
import sys
import tempfile
import unittest
import urllib.parse


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


def app_index(record_count: int = 28, locale_count: int = 50) -> dict:
    locales = list(catalog.OFFICIAL_LOCALES[:locale_count])
    return {
        "$schema": (
            f"{catalog.GUIDE_SITE}/api/v1/ios-app-catalog/"
            "index.schema.json"
        ),
        "api_version": "1.2.0",
        "content_digest": "b" * 64,
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "record_count": record_count,
        "locale_count": locale_count,
        "ordering": "alphabetical_by_app_name_not_a_ranking",
        "availability_verification": {
            "source": "Apple iTunes Lookup API",
            "markets": ["US", "TW", "JP", "GB"],
            "retirement_rule": (
                "Retire after three consecutive verified misses"
            ),
        },
        "openapi": (
            f"{catalog.GUIDE_SITE}/api/v1/ios-app-catalog/openapi.json"
        ),
        "locales": [
            {
                "locale": locale,
                "url": (
                    f"{catalog.GUIDE_SITE}/api/v1/ios-app-catalog/"
                    f"locales/{locale}.json"
                ),
                "feed": (
                    f"{catalog.GUIDE_SITE}/api/v1/ios-app-catalog/"
                    f"feeds/{locale}.json"
                ),
            }
            for locale in locales
        ],
    }


def mcp_card(record_count: int = 28, locale_count: int = 50) -> dict:
    return {
        "$schema": (
            "https://static.modelcontextprotocol.io/schemas/"
            "2025-12-11/server.schema.json"
        ),
        "name": "io.github.alice51849/lumi-app-finder",
        "title": "Lumi App Finder",
        "description": (
            f"Find iOS apps by task across {record_count} live apps and "
            f"{locale_count} Apple locales, with direct App Store links."
        ),
        "websiteUrl": f"{catalog.GUIDE_SITE}/",
        "repository": {
            "url": "https://github.com/alice51849/lumi-mcp",
            "source": "github",
        },
        "version": "1.0.0",
        "packages": [
            {
                "registryType": "mcpb",
                "identifier": (
                    "https://github.com/alice51849/lumi-mcp/releases/"
                    "download/v1.0.0/lumi-app-finder.mcpb"
                ),
                "fileSha256": "a" * 64,
                "transport": {"type": "stdio"},
            }
        ],
        "_meta": {
            "io.modelcontextprotocol.registry/publisher-provided": {
                "catalog": (
                    f"{catalog.GUIDE_SITE}/data/"
                    "lumi-studio-publisher-search-intent-catalog.json"
                ),
                "coverage": (
                    f"{record_count} verified live iOS apps across all "
                    f"{locale_count} Apple locales"
                ),
                "disclosure": (
                    "First-party publisher catalog; text relevance is not "
                    "an independent ranking."
                ),
            }
        },
    }


def registry_payload(
    card: dict | None = None,
    *,
    status: str = "active",
    is_latest: bool = True,
) -> dict:
    return {
        "servers": [
            {
                "server": card or mcp_card(),
                "_meta": {
                    catalog.MCP_OFFICIAL_META_KEY: {
                        "status": status,
                        "isLatest": is_latest,
                    }
                },
            }
        ],
        "metadata": {"count": 1},
    }


class FakeResponse:
    def __init__(self, document: object):
        self.body = json.dumps(document).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


class CatalogTests(unittest.TestCase):
    def test_registry_url_uses_supported_search_endpoint(self):
        parsed = urllib.parse.urlsplit(catalog.MCP_REGISTRY_URL)
        self.assertEqual("https", parsed.scheme)
        self.assertEqual("registry.modelcontextprotocol.io", parsed.netloc)
        self.assertEqual("/v0.1/servers", parsed.path)
        self.assertEqual(
            {
                "search": ["io.github.alice51849/lumi-app-finder"],
                "version": ["latest"],
                "limit": ["10"],
            },
            urllib.parse.parse_qs(parsed.query),
        )

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

    def test_agent_catalog_is_generated_once_from_verified_sources(self):
        sources = {
            catalog.APP_INDEX_URL: app_index(),
            catalog.MCP_SOURCE_URL: mcp_card(),
            catalog.MCP_REGISTRY_URL: registry_payload(),
        }

        def opener(request, timeout):
            self.assertEqual(30, timeout)
            return FakeResponse(sources[request.full_url])

        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / ".well-known"
            ai_target = root / "ai-catalog.json"
            mcp_target = root / "lumi-app-finder.mcp.json"
            changed = catalog.sync_agent_catalog(
                ai_target,
                mcp_target,
                opener=opener,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(
                ("lumi-app-finder.mcp.json", "ai-catalog.json"),
                changed,
            )
            self.assertEqual(
                (),
                catalog.sync_agent_catalog(
                    ai_target,
                    mcp_target,
                    opener=opener,
                    sleeper=lambda _seconds: None,
                ),
            )
            manifest = json.loads(ai_target.read_text(encoding="utf-8"))
            entry = manifest["entries"][0]
            self.assertEqual(catalog.MCP_IDENTIFIER, entry["identifier"])
            self.assertEqual(catalog.MCP_MEDIA_TYPE, entry["type"])
            self.assertEqual(catalog.MCP_CARD_URL, entry["url"])
            self.assertEqual(28, entry["metadata"]["appCount"])
            self.assertEqual(50, entry["metadata"]["localeCount"])
            self.assertEqual(
                catalog.MCP_REGISTRY_URL,
                entry["metadata"]["mcpRegistryUrl"],
            )
            self.assertEqual(5, len(entry["representativeQueries"]))
            self.assertEqual(
                [
                    "SearchPublisherCatalog",
                    "MatchBuyerNeed",
                    "FilterByAppleLocale",
                    "ReturnDirectAppStoreLinks",
                ],
                entry["capabilities"],
            )
            self.assertEqual(
                mcp_card(),
                json.loads(mcp_target.read_text(encoding="utf-8")),
            )

    def test_stale_mcp_coverage_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "coverage is stale"):
            catalog.validate_mcp_card(mcp_card(27), app_index())

    def test_registry_requires_one_active_latest_card(self):
        for document in (
            registry_payload(status="deprecated"),
            registry_payload(is_latest=False),
            {"servers": [], "metadata": {"count": 0}},
        ):
            with self.subTest(document=document):
                with self.assertRaisesRegex(
                    ValueError,
                    "exactly one active latest",
                ):
                    catalog.validate_mcp_registry(
                        document,
                        mcp_card(),
                        app_index(),
                    )

    def test_registry_and_source_cards_must_match(self):
        source = mcp_card()
        source["version"] = "1.0.1"
        source["packages"][0]["identifier"] = source["packages"][0][
            "identifier"
        ].replace("v1.0.0", "v1.0.1")
        with self.assertRaisesRegex(ValueError, "source card differs"):
            catalog.validate_mcp_registry(
                registry_payload(),
                source,
                app_index(),
            )

        source = mcp_card()
        source["icons"] = [
            {
                "src": "https://example.com/icon.png",
                "mimeType": "image/png",
            }
        ]
        with self.assertRaisesRegex(ValueError, "source card differs"):
            catalog.validate_mcp_registry(
                registry_payload(),
                source,
                app_index(),
            )

    def test_registry_pagination_uses_opaque_cursor(self):
        calls = []

        def opener(request, timeout):
            self.assertEqual(30, timeout)
            calls.append(request.full_url)
            if len(calls) == 1:
                return FakeResponse(
                    {
                        "servers": [{"server": {"name": "other/server"}}],
                        "metadata": {"nextCursor": "opaque/cursor+1"},
                    }
                )
            return FakeResponse(registry_payload())

        result = catalog.fetch_mcp_registry(
            opener=opener,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual(2, len(result["servers"]))
        self.assertEqual(2, len(calls))
        self.assertEqual(
            ["opaque/cursor+1"],
            urllib.parse.parse_qs(
                urllib.parse.urlsplit(calls[1]).query
            )["cursor"],
        )

    def test_agent_catalog_rejects_invalid_value_or_reference(self):
        index = app_index()
        card = mcp_card()
        manifest = catalog.agent_catalog_document(card, index)
        manifest["entries"][0]["data"] = {}
        with self.assertRaisesRegex(ValueError, "must reference"):
            catalog.validate_agent_catalog(manifest, card, index)

    def test_agent_catalog_rejects_incomplete_locale_coverage(self):
        document = app_index(locale_count=49)
        with self.assertRaisesRegex(ValueError, "all 50 Apple locales"):
            catalog.validate_app_index(document)

    def test_agent_catalog_rejects_noncanonical_locale_coverage(self):
        document = app_index()
        document["locales"][0] = {
            "locale": "fake-locale",
            "url": (
                f"{catalog.GUIDE_SITE}/api/v1/ios-app-catalog/"
                "locales/fake-locale.json"
            ),
            "feed": (
                f"{catalog.GUIDE_SITE}/api/v1/ios-app-catalog/"
                "feeds/fake-locale.json"
            ),
        }
        with self.assertRaisesRegex(ValueError, "not canonical"):
            catalog.validate_app_index(document)

    def test_agent_catalog_rejects_unverified_availability(self):
        document = app_index()
        document["availability_verification"]["source"] = "Unknown"
        with self.assertRaisesRegex(ValueError, "evidence drifted"):
            catalog.validate_app_index(document)

    def test_agent_catalog_rejects_non_scalar_metadata(self):
        index = app_index()
        card = mcp_card()
        manifest = catalog.agent_catalog_document(card, index)
        manifest["entries"][0]["metadata"]["invalid"] = ["nested"]
        with self.assertRaisesRegex(ValueError, "must be scalar"):
            catalog.validate_agent_catalog(manifest, card, index)


if __name__ == "__main__":
    unittest.main()
