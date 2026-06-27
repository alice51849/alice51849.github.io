#!/usr/bin/env python3
"""讀 sitemap.xml 把所有 URL 提交給 IndexNow(通知 Bing/Yandex 等搜尋引擎索引)。"""
import os, re, json, urllib.request, urllib.error

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = "alice51849.github.io"
KEY = "6326858eafb428d855f18d778c3c3fb1"

def main():
    sm = os.path.join(SITE, "sitemap.xml")
    if not os.path.exists(sm):
        print("no sitemap"); return
    urls = re.findall(r"<loc>([^<]+)</loc>", open(sm).read())
    if not urls:
        print("no urls"); return
    payload = {"host": HOST, "key": KEY,
               "keyLocation": f"https://{HOST}/{KEY}.txt", "urlList": urls}
    body = json.dumps(payload).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"IndexNow {r.status}: 提交 {len(urls)} URL")
    except urllib.error.HTTPError as e:
        print(f"IndexNow HTTP {e.code} ({len(urls)} urls)")
    except Exception as e:
        print(f"IndexNow err: {e}")

if __name__ == "__main__":
    main()
