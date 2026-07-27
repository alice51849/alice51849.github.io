#!/usr/bin/env python3
"""Sync the Standard.site publication verifier from the public ATProto repo."""

from __future__ import annotations

import argparse
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
XRPC_BASE = "https://bsky.social/xrpc"
ROOT = Path(__file__).resolve().parents[2]
TARGET = (
    ROOT
    / ".well-known"
    / "site.standard.publication"
    / "ios-app-guide"
)
AT_URI_RE = re.compile(
    rf"at://{re.escape(EXPECTED_DID)}/{re.escape(COLLECTION)}/"
    r"[234567abcdefghij][234567abcdefghijklmnopqrstuvwxyz]{12}"
)
USER_AGENT = (
    "LumiStudioStandardSiteSync/1.0 "
    "(+https://alice51849.github.io/)"
)


class SyncError(RuntimeError):
    """The public publication record could not be fetched or validated."""


class PublicationNotReady(SyncError):
    """The expected Standard.site publication has not been created yet."""


def records_url() -> str:
    query = urllib.parse.urlencode(
        {
            "repo": EXPECTED_DID,
            "collection": COLLECTION,
            "limit": "100",
        }
    )
    return f"{XRPC_BASE}/com.atproto.repo.listRecords?{query}"


def fetch_records(
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
        records_url(),
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
        fetch_records(opener=opener, sleeper=sleeper)
    )
    body = at_uri + "\n"
    changed = False
    if write:
        changed = atomic_write_if_changed(Path(target), body)
    return at_uri, changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=TARGET)
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
    mode = "updated" if changed else ("current" if args.write else "valid")
    print(f"Standard.site verifier {mode}: {at_uri}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
