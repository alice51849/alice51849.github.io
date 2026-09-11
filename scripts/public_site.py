"""Canonical public identities for the root deployment, independent of its Pages origin."""

import re
from urllib.parse import urlsplit, urlunsplit

PUBLIC_ROOT = "https://open.cait518.cc"
PUBLIC_SITE = f"{PUBLIC_ROOT}/ios-app-guide"
ORIGIN_ROOT = "https://alice51849.github.io"


def canonical_public_links(text: str) -> str:
    """Project actual owned URL authorities; never rewrite a federated profile identifier."""
    def replace(match):
        value = match.group()
        clean = value.rstrip(").,;!")
        parts = urlsplit(clean)
        if parts.hostname != urlsplit(ORIGIN_ROOT).hostname:
            return value
        if parts.scheme != "https" or parts.username or parts.password or parts.port:
            raise ValueError("Ambiguous owned origin URL")
        target = urlsplit(PUBLIC_ROOT)
        return urlunsplit((target.scheme, target.netloc, parts.path, parts.query, parts.fragment)) + value[len(clean):]

    return re.sub(r'https://[^\s<>"\'\\]+', replace, text)


def origin_urls(text: str) -> list[str]:
    return [
        value.rstrip(").,;!")
        for value in re.findall(r'https://[^\s<>"\'\\]+', text)
        if urlsplit(value.rstrip(").,;!")).hostname == urlsplit(ORIGIN_ROOT).hostname
    ]
