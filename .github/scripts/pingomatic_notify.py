#!/usr/bin/env python3
"""Notify Ping-O-Matic after the public daily Atom feed is deployed."""

from __future__ import annotations

import argparse
import http.client
import pathlib
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import xml.parsers.expat
import xmlrpc.client


SITE_NAME = "Lumi Studio independent iOS app guides"
SITE_URL = "https://alice51849.github.io/"
FEED_URL = f"{SITE_URL}bridgy-feed.xml"
RPC_URL = "https://rpc.pingomatic.com/"
USER_AGENT = (
    "LumiStudioFeedNotifier/1.0 "
    "(+https://github.com/alice51849/alice51849.github.io)"
)
ATOM = "http://www.w3.org/2005/Atom"
ROOT = pathlib.Path(__file__).resolve().parents[2]
FEED_PATH = ROOT / "bridgy-feed.xml"


class NotifyError(RuntimeError):
    """The feed was not ready or an update service rejected the notification."""


class FetchError(NotifyError):
    """A public-feed fetch failed."""

    def __init__(self, message: str, *, transient: bool):
        super().__init__(message)
        self.transient = transient


def _error_body(error: urllib.error.HTTPError) -> str:
    try:
        raw = error.read(2048)
    finally:
        error.close()
    return raw.decode("utf-8", errors="replace").strip()


def validate_feed(content: bytes) -> str:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        raise NotifyError(f"Local Atom feed is invalid: {error}") from error
    if root.tag != f"{{{ATOM}}}feed":
        raise NotifyError("Local feed is not Atom")
    entries = root.findall(f"{{{ATOM}}}entry")
    if len(entries) != 1:
        raise NotifyError(f"Local Atom feed has {len(entries)} entries; expected one")
    title = entries[0].findtext(f"{{{ATOM}}}title")
    if not isinstance(title, str) or not title.strip():
        raise NotifyError("Local Atom entry is missing a title")
    return title.strip()


def fetch_live_feed(*, opener=None, timeout: int = 20) -> bytes:
    opener = urllib.request.urlopen if opener is None else opener
    request = urllib.request.Request(
        FEED_URL,
        headers={
            "Accept": "application/atom+xml, application/xml;q=0.9",
            "Cache-Control": "no-cache",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        body = _error_body(error)
        transient = error.code in {408, 429} or 500 <= error.code <= 599
        raise FetchError(
            f"Public Atom fetch failed: HTTP {error.code}: {body[:200]}",
            transient=transient,
        ) from error
    except (
        urllib.error.URLError,
        OSError,
        http.client.HTTPException,
    ) as error:
        raise FetchError(
            f"Public Atom fetch failed: {error}",
            transient=True,
        ) from error


def wait_for_live_feed(
    expected: bytes,
    *,
    attempts: int = 30,
    interval: int = 10,
    label: str = "Ping-O-Matic",
    opener=None,
    sleeper=None,
) -> int:
    if attempts < 1:
        raise ValueError("attempts must be positive")
    sleeper = time.sleep if sleeper is None else sleeper
    last_error = "public feed still serves the previous entry"
    for attempt in range(1, attempts + 1):
        try:
            live = fetch_live_feed(opener=opener)
        except FetchError as error:
            if not error.transient:
                raise
            last_error = str(error)
        else:
            if live == expected:
                return attempt
            last_error = "public feed still serves the previous entry"
        if attempt < attempts:
            print(
                f"{label}: {last_error}; checking again in {interval}s",
                file=sys.stderr,
            )
            sleeper(interval)
    raise NotifyError(
        f"Public Atom feed did not deploy after {attempts} checks: {last_error}"
    )


def render_ping_request() -> bytes:
    return xmlrpc.client.dumps(
        (SITE_NAME, SITE_URL, FEED_URL),
        methodname="weblogUpdates.extendedPing",
        allow_none=False,
        encoding="utf-8",
    ).encode("utf-8")


def parse_ping_response(content: bytes, *, service: str = "Ping-O-Matic") -> str:
    try:
        params, _method = xmlrpc.client.loads(content)
    except xmlrpc.client.Fault as error:
        raise NotifyError(
            f"{service} XML-RPC fault {error.faultCode}: {error.faultString}"
        ) from error
    except (
        xmlrpc.client.ResponseError,
        xml.parsers.expat.ExpatError,
    ) as error:
        raise NotifyError(f"{service} returned invalid XML-RPC: {error}") from error
    if len(params) != 1 or not isinstance(params[0], dict):
        raise NotifyError(f"{service} returned an unexpected XML-RPC result")
    result = params[0]
    if result.get("flerror") not in (False, 0):
        message = result.get("message")
        detail = message.strip() if isinstance(message, str) else "unknown error"
        raise NotifyError(f"{service} rejected the update: {detail}")
    message = result.get("message")
    if not isinstance(message, str) or not message.strip():
        raise NotifyError(f"{service} success response is missing a message")
    return message.strip()


def post_ping_request(
    rpc_url: str,
    body: bytes,
    *,
    service: str,
    opener=None,
    timeout: int = 30,
) -> str:
    opener = urllib.request.urlopen if opener is None else opener
    request = urllib.request.Request(
        rpc_url,
        data=body,
        headers={
            "Accept": "text/xml",
            "Content-Type": "text/xml; charset=utf-8",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            content = response.read(65537)
    except urllib.error.HTTPError as error:
        body = _error_body(error)
        raise NotifyError(
            f"{service} request failed: HTTP {error.code}: {body[:200]}"
        ) from error
    except (
        urllib.error.URLError,
        OSError,
        http.client.HTTPException,
    ) as error:
        # Do not retry an uncertain POST; duplicate update pings are worse than one miss.
        raise NotifyError(f"{service} request failed: {error}") from error
    if len(content) > 65536:
        raise NotifyError(f"{service} response exceeded 64 KiB")
    return parse_ping_response(content, service=service)


def send_ping(*, opener=None, timeout: int = 30) -> str:
    return post_ping_request(
        RPC_URL,
        render_ping_request(),
        service="Ping-O-Matic",
        opener=opener,
        timeout=timeout,
    )


def run() -> str:
    try:
        expected = FEED_PATH.read_bytes()
    except OSError as error:
        raise NotifyError(f"Cannot read local Atom feed: {error}") from error
    title = validate_feed(expected)
    checks = wait_for_live_feed(expected)
    message = send_ping()
    print(
        f"Ping-O-Matic: accepted entry={title!r} live_checks={checks} "
        f"message={message!r}"
    )
    return message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--feed-changed",
        action="store_true",
        help="confirm that this invocation follows a persisted feed change",
    )
    args = parser.parse_args(argv)
    if not args.feed_changed:
        print(
            "Ping-O-Matic refused: --feed-changed is required",
            file=sys.stderr,
        )
        return 2
    try:
        run()
        return 0
    except (NotifyError, ValueError) as error:
        print(f"Ping-O-Matic failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
