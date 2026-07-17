#!/usr/bin/env python3
"""Sync the RFC 9727 API catalog from the generated iOS App Guide."""

from __future__ import annotations

import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request


SITE = "https://alice51849.github.io"
GUIDE_SITE = f"{SITE}/ios-app-guide"
SOURCE_URL = f"{GUIDE_SITE}/.well-known/api-catalog"
ROOT = pathlib.Path(__file__).resolve().parents[2]
TARGET = ROOT / ".well-known" / "api-catalog"
OPENAPI_MEDIA_TYPE = "application/vnd.oai.openapi+json;version=3.1"
USER_AGENT = (
    "LumiStudioApiCatalogSync/1.0 "
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
    if attempts < 1:
        raise ValueError("attempts must be positive")
    opener = urllib.request.urlopen if opener is None else opener
    sleeper = time.sleep if sleeper is None else sleeper
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/linkset+json, application/json;q=0.9",
            "User-Agent": USER_AGENT,
        },
    )
    for attempt in range(attempts):
        try:
            with opener(request, timeout=30) as response:
                raw = response.read()
            return validate_catalog(json.loads(raw.decode("utf-8")))
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


def sync_catalog(
    target: pathlib.Path = TARGET,
    *,
    opener=None,
    sleeper=None,
) -> bool:
    document = fetch_catalog(opener=opener, sleeper=sleeper)
    content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if target.exists() and target.read_text(encoding="utf-8") == content:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(target)
    return True


def main() -> None:
    changed = sync_catalog()
    print("Updated RFC 9727 API catalog." if changed else "API catalog is current.")


if __name__ == "__main__":
    main()
