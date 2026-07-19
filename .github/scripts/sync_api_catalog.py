#!/usr/bin/env python3
"""Sync root API and agent discovery catalogs from verified public sources."""

from __future__ import annotations

import json
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request


SITE = "https://alice51849.github.io"
GUIDE_SITE = f"{SITE}/ios-app-guide"
SOURCE_URL = f"{GUIDE_SITE}/.well-known/api-catalog"
APP_INDEX_URL = f"{GUIDE_SITE}/api/v1/ios-app-catalog/index.json"
MCP_SOURCE_URL = (
    "https://raw.githubusercontent.com/alice51849/lumi-mcp/main/server.json"
)
ROOT = pathlib.Path(__file__).resolve().parents[2]
TARGET = ROOT / ".well-known" / "api-catalog"
AI_CATALOG_TARGET = ROOT / ".well-known" / "ai-catalog.json"
MCP_CARD_TARGET = ROOT / ".well-known" / "lumi-app-finder.mcp.json"
OPENAPI_MEDIA_TYPE = "application/vnd.oai.openapi+json;version=3.1"
MCP_MEDIA_TYPE = "application/mcp-server-card+json"
MCP_CARD_URL = f"{SITE}/.well-known/lumi-app-finder.mcp.json"
MCP_REGISTRY_URL = (
    "https://registry.modelcontextprotocol.io/v0.1/servers/"
    "io.github.alice51849%2Flumi-app-finder/versions/latest"
)
MCP_IDENTIFIER = "urn:air:alice51849.github.io:mcp:lumi-app-finder"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
SEMVER_RE = re.compile(r"\d+\.\d+\.\d+")
OFFICIAL_LOCALES = (
    "ar-SA",
    "bn-BD",
    "ca",
    "cs",
    "da",
    "de-DE",
    "el",
    "en-AU",
    "en-CA",
    "en-GB",
    "en-US",
    "es-ES",
    "es-MX",
    "fi",
    "fr-CA",
    "fr-FR",
    "gu-IN",
    "he",
    "hi",
    "hr",
    "hu",
    "id",
    "it",
    "ja",
    "kn-IN",
    "ko",
    "ml-IN",
    "mr-IN",
    "ms",
    "nl-NL",
    "no",
    "or-IN",
    "pa-IN",
    "pl",
    "pt-BR",
    "pt-PT",
    "ro",
    "ru",
    "sk",
    "sl-SI",
    "sv",
    "ta-IN",
    "te-IN",
    "th",
    "tr",
    "uk",
    "ur-PK",
    "vi",
    "zh-Hans",
    "zh-Hant",
)
OFFICIAL_LOCALE_SET = frozenset(OFFICIAL_LOCALES)
USER_AGENT = (
    "LumiStudioDiscoveryCatalogSync/1.0 "
    "(+https://github.com/alice51849/alice51849.github.io)"
)


class CatalogSyncError(RuntimeError):
    """The source catalog could not be fetched or validated."""


def _https_url(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{label} must be an absolute HTTPS URL")
    return value


def _fetch_json(
    url: str,
    *,
    accept: str = "application/json",
    opener=None,
    sleeper=None,
    attempts: int = 3,
) -> object:
    if attempts < 1:
        raise ValueError("attempts must be positive")
    _https_url(url, "source URL")
    opener = urllib.request.urlopen if opener is None else opener
    sleeper = time.sleep if sleeper is None else sleeper
    request = urllib.request.Request(
        url,
        headers={"Accept": accept, "User-Agent": USER_AGENT},
    )
    for attempt in range(attempts):
        try:
            with opener(request, timeout=30) as response:
                raw = response.read()
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as error:
            transient = error.code in {408, 429} or 500 <= error.code <= 599
            if not transient or attempt == attempts - 1:
                raise CatalogSyncError(
                    f"catalog fetch failed: HTTP {error.code}"
                ) from error
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            if attempt == attempts - 1:
                raise CatalogSyncError(
                    f"catalog fetch failed after {attempts} attempts"
                ) from error
        sleeper(10 * (attempt + 1))
    raise AssertionError("unreachable")


def validate_catalog(document: object) -> dict:
    if not isinstance(document, dict) or set(document) != {"linkset"}:
        raise ValueError("catalog must contain only an RFC 9264 linkset")
    entries = document["linkset"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("catalog linkset must not be empty")

    anchors: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or set(entry) != {
            "anchor",
            "service-desc",
            "service-doc",
            "license",
        }:
            raise ValueError(f"invalid catalog entry at index {index}")
        anchor = _https_url(entry["anchor"], f"linkset[{index}].anchor")
        if not anchor.startswith(f"{GUIDE_SITE}/api/v1/"):
            raise ValueError(f"catalog anchor is outside the guide API: {anchor}")
        if anchor in anchors:
            raise ValueError(f"duplicate catalog anchor: {anchor}")
        anchors.add(anchor)

        for relation in ("service-desc", "service-doc", "license"):
            targets = entry[relation]
            if not isinstance(targets, list) or not targets:
                raise ValueError(
                    f"linkset[{index}].{relation} must be a non-empty list"
                )
            for target_index, target in enumerate(targets):
                if not isinstance(target, dict):
                    raise ValueError(
                        f"linkset[{index}].{relation}[{target_index}] "
                        "must be an object"
                    )
                _https_url(
                    target.get("href"),
                    f"linkset[{index}].{relation}[{target_index}].href",
                )
                if not isinstance(target.get("type"), str):
                    raise ValueError(
                        f"linkset[{index}].{relation}[{target_index}].type "
                        "must be a string"
                    )

        descriptions = entry["service-desc"]
        if (
            len(descriptions) != 1
            or descriptions[0]["href"] != f"{anchor}/openapi.json"
            or descriptions[0]["type"] != OPENAPI_MEDIA_TYPE
        ):
            raise ValueError(f"catalog entry lacks canonical OpenAPI: {anchor}")
        if not any(
            target["href"] == f"{anchor}/"
            for target in entry["service-doc"]
        ):
            raise ValueError(f"catalog entry lacks canonical docs: {anchor}")
    return document


def fetch_catalog(
    url: str = SOURCE_URL,
    *,
    opener=None,
    sleeper=None,
    attempts: int = 3,
) -> dict:
    return validate_catalog(
        _fetch_json(
            url,
            accept="application/linkset+json, application/json;q=0.9",
            opener=opener,
            sleeper=sleeper,
            attempts=attempts,
        )
    )


def _write_json_if_changed(target: pathlib.Path, document: dict) -> bool:
    content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if target.exists() and target.read_text(encoding="utf-8") == content:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(target)
    return True


def sync_catalog(
    target: pathlib.Path = TARGET,
    *,
    opener=None,
    sleeper=None,
) -> bool:
    document = fetch_catalog(opener=opener, sleeper=sleeper)
    return _write_json_if_changed(target, document)


def validate_app_index(document: object) -> dict:
    if not isinstance(document, dict):
        raise ValueError("app catalog index must be an object")
    expected_schema = (
        f"{GUIDE_SITE}/api/v1/ios-app-catalog/index.schema.json"
    )
    if document.get("$schema") != expected_schema:
        raise ValueError("app catalog schema URL drifted")
    if document.get("api_version") != "1.2.0":
        raise ValueError("app catalog API contract drifted")
    if not SHA256_RE.fullmatch(str(document.get("content_digest", ""))):
        raise ValueError("app catalog content digest is invalid")
    if document.get("license") != (
        "https://creativecommons.org/licenses/by/4.0/"
    ):
        raise ValueError("app catalog license drifted")
    record_count = document.get("record_count")
    locale_count = document.get("locale_count")
    locales = document.get("locales")
    if not isinstance(record_count, int) or record_count < 1:
        raise ValueError("app catalog must contain verified live apps")
    if (
        locale_count != len(OFFICIAL_LOCALES)
        or not isinstance(locales, list)
    ):
        raise ValueError("app catalog must cover all 50 Apple locales")
    locale_names = [
        item.get("locale") for item in locales if isinstance(item, dict)
    ]
    if (
        len(locale_names) != len(OFFICIAL_LOCALES)
        or set(locale_names) != OFFICIAL_LOCALE_SET
    ):
        raise ValueError("app catalog locale coverage is not canonical")
    expected_base = f"{GUIDE_SITE}/api/v1/ios-app-catalog"
    for item, locale in zip(locales, locale_names):
        if not isinstance(locale, str) or not locale:
            raise ValueError("app catalog contains an invalid locale")
        if item.get("url") != f"{expected_base}/locales/{locale}.json":
            raise ValueError("app catalog locale URL drifted")
        if item.get("feed") != f"{expected_base}/feeds/{locale}.json":
            raise ValueError("app catalog locale feed drifted")
    if document.get("ordering") != "alphabetical_by_app_name_not_a_ranking":
        raise ValueError("app catalog must retain its non-ranking disclosure")
    if document.get("availability_verification") != {
        "source": "Apple iTunes Lookup API",
        "markets": ["US", "TW", "JP", "GB"],
        "retirement_rule": "Retire after three consecutive verified misses",
    }:
        raise ValueError("app availability verification evidence drifted")
    if document.get("openapi") != (
        f"{GUIDE_SITE}/api/v1/ios-app-catalog/openapi.json"
    ):
        raise ValueError("app catalog OpenAPI URL drifted")
    return document


def validate_mcp_card(document: object, app_index: dict) -> dict:
    if not isinstance(document, dict):
        raise ValueError("MCP server card must be an object")
    if document.get("name") != "io.github.alice51849/lumi-app-finder":
        raise ValueError("unexpected MCP server name")
    if document.get("title") != "Lumi App Finder":
        raise ValueError("unexpected MCP server title")
    if document.get("websiteUrl") != f"{GUIDE_SITE}/":
        raise ValueError("MCP website URL drifted")
    version = document.get("version")
    if not isinstance(version, str) or not SEMVER_RE.fullmatch(version):
        raise ValueError("MCP server version must be semantic")
    description = document.get("description")
    if not isinstance(description, str):
        raise ValueError("MCP server description is missing")
    for value in (app_index["record_count"], app_index["locale_count"]):
        if str(value) not in description:
            raise ValueError("MCP card coverage is stale")
    repository = document.get("repository")
    if not isinstance(repository, dict) or repository.get("url") != (
        "https://github.com/alice51849/lumi-mcp"
    ):
        raise ValueError("MCP repository URL drifted")
    packages = document.get("packages")
    if not isinstance(packages, list) or len(packages) != 1:
        raise ValueError("MCP card must expose one installable package")
    package = packages[0]
    if not isinstance(package, dict):
        raise ValueError("MCP package must be an object")
    if package.get("registryType") != "mcpb":
        raise ValueError("MCP package must use the mcpb registry type")
    package_url = _https_url(package.get("identifier"), "MCP package URL")
    expected_release = (
        "https://github.com/alice51849/lumi-mcp/releases/download/"
        f"v{version}/"
    )
    if not package_url.startswith(expected_release) or not package_url.endswith(
        ".mcpb"
    ):
        raise ValueError("MCP package URL drifted")
    if not SHA256_RE.fullmatch(str(package.get("fileSha256", ""))):
        raise ValueError("MCP package SHA-256 is invalid")
    if package.get("transport") != {"type": "stdio"}:
        raise ValueError("MCP package transport drifted")
    root_metadata = document.get("_meta")
    if not isinstance(root_metadata, dict):
        raise ValueError("MCP publisher metadata is missing")
    metadata = root_metadata.get(
        "io.modelcontextprotocol.registry/publisher-provided"
    )
    if not isinstance(metadata, dict) or metadata.get("coverage") != (
        f"{app_index['record_count']} verified live iOS apps across all "
        f"{app_index['locale_count']} Apple locales"
    ):
        raise ValueError("MCP publisher coverage metadata is stale")
    if metadata.get("catalog") != (
        f"{GUIDE_SITE}/data/"
        "lumi-studio-publisher-search-intent-catalog.json"
    ):
        raise ValueError("MCP publisher catalog URL drifted")
    return document


def agent_catalog_document(mcp_card: dict, app_index: dict) -> dict:
    app_count = app_index["record_count"]
    locale_count = app_index["locale_count"]
    return {
        "specVersion": "1.0",
        "host": {
            "displayName": "Lumi Studio",
            "documentationUrl": f"{GUIDE_SITE}/about.html",
        },
        "entries": [
            {
                "identifier": MCP_IDENTIFIER,
                "displayName": "Lumi App Finder",
                "type": MCP_MEDIA_TYPE,
                "url": MCP_CARD_URL,
                "description": (
                    "First-party task and buyer-need discovery across "
                    f"{app_count} verified live Lumi Studio iOS apps and "
                    f"all {locale_count} Apple locales, returning localized "
                    "context and direct App Store links; text relevance is "
                    "not an independent ranking."
                ),
                "tags": [
                    "iOS",
                    "iPhone",
                    "iPad",
                    "App Store",
                    "app discovery",
                    "localized apps",
                    "first-party publisher",
                ],
                "capabilities": [
                    "SearchPublisherCatalog",
                    "MatchBuyerNeed",
                    "FilterByAppleLocale",
                    "ReturnDirectAppStoreLinks",
                ],
                "representativeQueries": [
                    (
                        "find a privacy-conscious iPhone app for my task "
                        "with a direct App Store link"
                    ),
                    "推薦符合我需求、可直接前往 App Store 下載的 iPhone App",
                    "用途に合うiPhoneアプリをApp Storeの直接リンク付きで探して",
                    (
                        "encuentra una app para iPhone que se adapte a mi "
                        "necesidad con enlace directo al App Store"
                    ),
                    (
                        "ابحث عن تطبيق iPhone يناسب مهمتي مع رابط مباشر "
                        "إلى App Store"
                    ),
                ],
                "version": mcp_card["version"],
                "metadata": {
                    "appCount": app_count,
                    "localeCount": locale_count,
                    "catalogUrl": (
                        f"{GUIDE_SITE}/data/"
                        "lumi-studio-publisher-search-intent-catalog.json"
                    ),
                    "mcpRegistryUrl": MCP_REGISTRY_URL,
                    "publisherDisclosure": (
                        "First-party publisher catalog; relevance matches "
                        "are not independent rankings."
                    ),
                },
            }
        ],
    }


def validate_agent_catalog(
    document: object,
    mcp_card: dict,
    app_index: dict,
) -> dict:
    if not isinstance(document, dict) or set(document) != {
        "specVersion",
        "host",
        "entries",
    }:
        raise ValueError("ARD manifest root properties are invalid")
    if document["specVersion"] != "1.0":
        raise ValueError("ARD specVersion must be 1.0")
    host = document["host"]
    if host != {
        "displayName": "Lumi Studio",
        "documentationUrl": f"{GUIDE_SITE}/about.html",
    }:
        raise ValueError("ARD host metadata drifted")
    entries = document["entries"]
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("ARD manifest must expose one canonical MCP resource")
    entry = entries[0]
    if not isinstance(entry, dict):
        raise ValueError("ARD resource must be an object")
    if entry.get("identifier") != MCP_IDENTIFIER:
        raise ValueError("ARD resource identifier drifted")
    if entry.get("type") != MCP_MEDIA_TYPE:
        raise ValueError("ARD resource media type drifted")
    if entry.get("url") != MCP_CARD_URL or "data" in entry:
        raise ValueError("ARD resource must reference the root MCP card")
    if entry.get("version") != mcp_card["version"]:
        raise ValueError("ARD and MCP versions differ")
    queries = entry.get("representativeQueries")
    if (
        not isinstance(queries, list)
        or not 2 <= len(queries) <= 5
        or any(
            not isinstance(query, str)
            or not query.strip()
            or "\n" in query
            for query in queries
        )
        or len(set(queries)) != len(queries)
    ):
        raise ValueError("ARD representative queries are invalid")
    metadata = entry.get("metadata")
    if not isinstance(metadata, dict) or (
        metadata.get("appCount") != app_index["record_count"]
        or metadata.get("localeCount") != app_index["locale_count"]
    ):
        raise ValueError("ARD coverage metadata is stale")
    if any(
        value is not None
        and not isinstance(value, (str, int, float, bool))
        for value in metadata.values()
    ):
        raise ValueError("ARD metadata values must be scalar")
    for key in ("catalogUrl", "mcpRegistryUrl"):
        _https_url(metadata.get(key), f"ARD metadata.{key}")
    _https_url(host["documentationUrl"], "ARD host documentation")
    _https_url(entry["url"], "ARD resource URL")
    return document


def sync_agent_catalog(
    ai_target: pathlib.Path = AI_CATALOG_TARGET,
    mcp_target: pathlib.Path = MCP_CARD_TARGET,
    *,
    opener=None,
    sleeper=None,
) -> tuple[str, ...]:
    app_index = validate_app_index(
        _fetch_json(
            APP_INDEX_URL,
            opener=opener,
            sleeper=sleeper,
        )
    )
    mcp_card = validate_mcp_card(
        _fetch_json(
            MCP_SOURCE_URL,
            opener=opener,
            sleeper=sleeper,
        ),
        app_index,
    )
    manifest = validate_agent_catalog(
        agent_catalog_document(mcp_card, app_index),
        mcp_card,
        app_index,
    )
    changed = []
    if _write_json_if_changed(mcp_target, mcp_card):
        changed.append(mcp_target.name)
    if _write_json_if_changed(ai_target, manifest):
        changed.append(ai_target.name)
    return tuple(changed)


def main() -> None:
    api_changed = sync_catalog()
    agent_changed = sync_agent_catalog()
    print(
        "Updated RFC 9727 API catalog."
        if api_changed
        else "API catalog is current."
    )
    print(
        f"Updated ARD resources: {', '.join(agent_changed)}."
        if agent_changed
        else "ARD resources are current."
    )


if __name__ == "__main__":
    main()
