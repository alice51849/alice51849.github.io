#!/usr/bin/env python3
"""Sync the Standard.site publication verifier from the public ATProto repo."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request


EXPECTED_DID = "did:plc:kboucnzkxzmqmatvhes4xlt4"
PUBLICATION_URL = "https://alice51849.github.io/ios-app-guide"
COLLECTION = "site.standard.publication"
DOCUMENT_COLLECTION = "site.standard.document"
XRPC_BASE = "https://bsky.social/xrpc"
ROOT = Path(__file__).resolve().parents[2]
TARGET = (
    ROOT
    / ".well-known"
    / "site.standard.publication"
    / "ios-app-guide"
)
CONTRACT_TARGET = ROOT / "standard_site_guide_contract.json"
AT_URI_RE = re.compile(
    rf"at://{re.escape(EXPECTED_DID)}/{re.escape(COLLECTION)}/"
    r"[234567abcdefghij][234567abcdefghijklmnopqrstuvwxyz]{12}"
)
DOCUMENT_AT_URI_RE = re.compile(
    rf"at://{re.escape(EXPECTED_DID)}/{re.escape(DOCUMENT_COLLECTION)}/"
    r"[234567abcdefghij][234567abcdefghijklmnopqrstuvwxyz]{12}"
)
APP_KEY_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,127}")
MAX_RECORDS = 5_000
USER_AGENT = (
    "LumiStudioStandardSiteSync/1.0 "
    "(+https://alice51849.github.io/)"
)


class SyncError(RuntimeError):
    """The public publication record could not be fetched or validated."""


class PublicationNotReady(SyncError):
    """The expected Standard.site publication has not been created yet."""


class DocumentsNotReady(SyncError):
    """The publication exists but has no verified documents yet."""


def records_url(collection: str = COLLECTION, cursor: str = "") -> str:
    query_values = {
        "repo": EXPECTED_DID,
        "collection": collection,
        "limit": "100",
    }
    if cursor:
        query_values["cursor"] = cursor
    query = urllib.parse.urlencode(query_values)
    return f"{XRPC_BASE}/com.atproto.repo.listRecords?{query}"


def fetch_records(
    *,
    collection: str = COLLECTION,
    cursor: str = "",
    opener=None,
    sleeper=None,
    attempts: int = 3,
) -> dict:
    if attempts < 1:
        raise ValueError("attempts must be positive")
    opener = urllib.request.urlopen if opener is None else opener
    sleeper = time.sleep if sleeper is None else sleeper
    request = urllib.request.Request(
        records_url(collection, cursor),
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    for attempt in range(attempts):
        try:
            with opener(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise SyncError("ATProto listRecords returned a non-object")
            return payload
        except urllib.error.HTTPError as error:
            transient = error.code in {408, 429} or 500 <= error.code <= 599
            if not transient or attempt == attempts - 1:
                raise SyncError(
                    f"ATProto listRecords failed: HTTP {error.code}"
                ) from error
        except SyncError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            if attempt == attempts - 1:
                raise SyncError(
                    f"ATProto listRecords failed after {attempts} attempts"
                ) from error
        sleeper(10 * (attempt + 1))
    raise AssertionError("unreachable")


def fetch_all_records(
    collection: str,
    *,
    opener=None,
    sleeper=None,
) -> dict:
    records: list[object] = []
    cursor = ""
    seen_cursors: set[str] = set()
    while True:
        payload = fetch_records(
            collection=collection,
            cursor=cursor,
            opener=opener,
            sleeper=sleeper,
        )
        page = payload.get("records")
        if not isinstance(page, list):
            raise SyncError("ATProto listRecords response has no records array")
        if len(records) + len(page) > MAX_RECORDS:
            raise SyncError("ATProto record listing exceeds the safety limit")
        records.extend(page)
        next_cursor = payload.get("cursor")
        if next_cursor is None:
            return {"records": records}
        if (
            not isinstance(next_cursor, str)
            or not next_cursor
            or next_cursor in seen_cursors
        ):
            raise SyncError("ATProto listRecords returned an invalid cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def publication_at_uri(payload: object) -> str:
    if not isinstance(payload, dict):
        raise SyncError("ATProto response must be an object")
    records = payload.get("records")
    if not isinstance(records, list):
        raise SyncError("ATProto response has no records array")
    if payload.get("cursor"):
        raise SyncError("Publication records exceed the bounded response")

    matches: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            raise SyncError("ATProto publication record must be an object")
        uri = record.get("uri")
        value = record.get("value")
        if not isinstance(value, dict):
            raise SyncError("ATProto publication value must be an object")
        if value.get("url") != PUBLICATION_URL:
            continue
        if (
            not isinstance(uri, str)
            or AT_URI_RE.fullmatch(uri) is None
            or value.get("$type") != COLLECTION
            or not isinstance(value.get("name"), str)
            or not value["name"].strip()
            or not isinstance(record.get("cid"), str)
            or not record["cid"].strip()
        ):
            raise SyncError("Expected publication record is invalid")
        matches.append(uri)
    if not matches:
        raise PublicationNotReady("Standard.site publication is not ready")
    if len(matches) != 1:
        raise SyncError("Expected exactly one Standard.site publication")
    return matches[0]


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise SyncError(f"{label} must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SyncError(f"{label} must be an RFC 3339 timestamp") from error
    if parsed.tzinfo is None:
        raise SyncError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _canonical_document_url(path: object) -> str:
    if not isinstance(path, str) or len(path) > 2_048:
        raise SyncError("Standard.site document path must be bounded")
    parsed = urllib.parse.urlsplit(path)
    if (
        not path.startswith("/")
        or path.startswith("//")
        or not path.endswith(".html")
        or parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or "%" in path
        or "\\" in path
        or any(part in {"", ".", ".."} for part in path[1:].split("/"))
    ):
        raise SyncError("Standard.site document path is unsafe")
    return PUBLICATION_URL.rstrip("/") + path


def guide_contract(publication_uri: str, payload: object) -> dict:
    if AT_URI_RE.fullmatch(publication_uri) is None:
        raise SyncError("Publication AT-URI is invalid")
    if not isinstance(payload, dict):
        raise SyncError("ATProto document response must be an object")
    records = payload.get("records")
    if not isinstance(records, list) or payload.get("cursor"):
        raise SyncError("ATProto document response is not a bounded record array")

    documents: list[dict[str, str]] = []
    generated_candidates: list[tuple[datetime, str]] = []
    seen_canonicals: set[str] = set()
    seen_uris: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise SyncError("ATProto document record must be an object")
        uri = record.get("uri")
        value = record.get("value")
        if (
            not isinstance(uri, str)
            or DOCUMENT_AT_URI_RE.fullmatch(uri) is None
            or not isinstance(record.get("cid"), str)
            or not record["cid"].strip()
            or not isinstance(value, dict)
            or value.get("$type") != DOCUMENT_COLLECTION
        ):
            raise SyncError("ATProto document record is invalid")
        if value.get("site") != publication_uri:
            continue
        canonical = _canonical_document_url(value.get("path"))
        tags = value.get("tags")
        if (
            not isinstance(tags, list)
            or not tags
            or not all(isinstance(tag, str) and tag for tag in tags)
            or APP_KEY_RE.fullmatch(tags[0]) is None
        ):
            raise SyncError("Standard.site document has an invalid app key")
        if canonical in seen_canonicals or uri in seen_uris:
            raise SyncError("Standard.site documents contain duplicate identities")
        seen_canonicals.add(canonical)
        seen_uris.add(uri)
        published_at = value.get("publishedAt")
        published_time = _timestamp(published_at, "Document publishedAt")
        generated_candidates.append((published_time, str(published_at)))
        if "updatedAt" in value:
            updated_at = value["updatedAt"]
            generated_candidates.append(
                (_timestamp(updated_at, "Document updatedAt"), str(updated_at))
            )
        documents.append(
            {
                "canonical_url": canonical,
                "app_key": tags[0],
                "at_uri": uri,
                "link_tag": (
                    f'<link rel="{DOCUMENT_COLLECTION}" href="{uri}">'
                ),
            }
        )
    if not documents:
        raise DocumentsNotReady(
            "Standard.site publication has no verified documents yet"
        )

    documents.sort(key=lambda item: item["canonical_url"])
    _, generated_at = max(generated_candidates)
    body = publication_uri + "\n"
    endpoint_path = "/.well-known/site.standard.publication/ios-app-guide"
    return {
        "contract_version": 1,
        "generated_at": generated_at,
        "publication": {
            "url": PUBLICATION_URL,
            "at_uri": publication_uri,
            "well_known": {
                "request_url": "https://alice51849.github.io" + endpoint_path,
                "request_path": endpoint_path,
                "content_type": "text/plain; charset=utf-8",
                "body": body,
                "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "deploy_at_origin_root": True,
            },
            "discovery_link_tag": (
                f'<link rel="{COLLECTION}" href="{publication_uri}">'
            ),
        },
        "documents": documents,
    }


def atomic_write_if_changed(target: Path, body: str) -> bool:
    target = Path(target)
    if target.exists() and target.read_text(encoding="utf-8") == body:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f".{target.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    )
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o644,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return True


def sync(
    target: Path = TARGET,
    *,
    write: bool = False,
    opener=None,
    sleeper=None,
) -> tuple[str, bool]:
    at_uri = publication_at_uri(
        fetch_all_records(
            COLLECTION,
            opener=opener,
            sleeper=sleeper,
        )
    )
    body = at_uri + "\n"
    changed = False
    if write:
        changed = atomic_write_if_changed(Path(target), body)
    return at_uri, changed


def sync_guide_contract(
    publication_uri: str,
    target: Path = CONTRACT_TARGET,
    *,
    write: bool = False,
    opener=None,
    sleeper=None,
) -> tuple[dict, bool]:
    contract = guide_contract(
        publication_uri,
        fetch_all_records(
            DOCUMENT_COLLECTION,
            opener=opener,
            sleeper=sleeper,
        ),
    )
    changed = False
    if write:
        body = json.dumps(contract, ensure_ascii=False, indent=2) + "\n"
        changed = atomic_write_if_changed(Path(target), body)
    return contract, changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=TARGET)
    parser.add_argument(
        "--contract-target",
        type=Path,
        default=CONTRACT_TARGET,
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Atomically update the verifier; default is check-only.",
    )
    args = parser.parse_args()
    try:
        at_uri, changed = sync(args.target, write=args.write)
    except PublicationNotReady as error:
        if args.target.exists():
            raise
        print(f"Standard.site verifier skipped: {error}")
        return 0
    try:
        contract, contract_changed = sync_guide_contract(
            at_uri,
            args.contract_target,
            write=args.write,
        )
    except DocumentsNotReady as error:
        if args.contract_target.exists():
            raise
        contract = None
        contract_changed = False
        print(f"Standard.site Guide contract skipped: {error}")
    mode = "updated" if changed else ("current" if args.write else "valid")
    print(f"Standard.site verifier {mode}: {at_uri}")
    if contract is not None:
        contract_mode = (
            "updated"
            if contract_changed
            else ("current" if args.write else "valid")
        )
        print(
            "Standard.site Guide contract "
            f"{contract_mode}: {len(contract['documents'])} documents"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
