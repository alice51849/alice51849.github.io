#!/usr/bin/env python3
"""Submit the root sitemap to IndexNow with strict retries and validation."""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "alice51849.github.io"
KEY = "6326858eafb428d855f18d778c3c3fb1"
ENDPOINT = "https://api.indexnow.org/indexnow"
USER_AGENT = "LumiRootIndexNow/1.0 (+https://alice51849.github.io/)"


def sitemap_urls(path):
    urls = re.findall(
        r"<loc>([^<]+)</loc>",
        open(path, encoding="utf-8").read(),
    )
    if not urls:
        raise ValueError("sitemap has no URLs")
    if len(urls) > 10_000 or len(set(urls)) != len(urls):
        raise ValueError("sitemap URL count is invalid")
    for url in urls:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != HOST:
            raise ValueError(f"sitemap URL is outside the verified host: {url}")
    return urls


def submit(urls, *, opener=None, sleeper=None, attempts=3):
    opener = urllib.request.urlopen if opener is None else opener
    sleeper = time.sleep if sleeper is None else sleeper
    payload = {
        "host": HOST,
        "key": KEY,
        "keyLocation": f"https://{HOST}/{KEY}.txt",
        "urlList": urls,
    }
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    for attempt in range(attempts):
        try:
            with opener(request, timeout=30) as response:
                if response.status not in {200, 202}:
                    raise RuntimeError(
                        f"IndexNow returned unexpected HTTP {response.status}"
                    )
                return response.status
        except urllib.error.HTTPError as error:
            transient = error.code in {408, 429} or 500 <= error.code <= 599
            if not transient or attempt == attempts - 1:
                raise RuntimeError(
                    f"IndexNow submission failed: HTTP {error.code}"
                ) from error
        except OSError as error:
            if attempt == attempts - 1:
                raise RuntimeError(
                    f"IndexNow submission failed after {attempts} attempts"
                ) from error
        sleeper(10 * (attempt + 1))
    raise AssertionError("unreachable")

def main():
    sm = os.path.join(SITE, "sitemap.xml")
    if not os.path.exists(sm):
        raise FileNotFoundError("sitemap.xml is missing")
    urls = sitemap_urls(sm)
    status = submit(urls)
    print(f"IndexNow {status}: submitted {len(urls)} URLs")

if __name__ == "__main__":
    main()
