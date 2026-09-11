#!/usr/bin/env python3
"""Generate canonical root discovery only; never rewrites app/support content or publishes."""

import argparse
import hashlib
import json
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from public_site import PUBLIC_ROOT, PUBLIC_SITE, canonical_public_links, origin_urls

ROOT = Path(__file__).resolve().parents[1]
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
RESOURCE_SYNC_NS = "http://www.openarchives.org/rs/terms/"


def render_resourcesync() -> str:
    collection = f"{PUBLIC_SITE}/resourcesync/bopomofo-collection.jsonld"
    capabilities = f"{PUBLIC_SITE}/resourcesync/capabilitylist.xml"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="{SITEMAP_NS}" xmlns:rs="{RESOURCE_SYNC_NS}">
  <rs:ln rel="describedby" href={quoteattr(collection)} type="application/ld+json"/>
  <rs:md capability="description"/>
  <url>
    <loc>{escape(capabilities)}</loc>
    <rs:md capability="capabilitylist"/>
    <rs:ln rel="describedby" href={quoteattr(collection)} type="application/ld+json"/>
  </url>
</urlset>
"""


def generate(root: Path, *, check: bool = False) -> dict:
    outputs = {
        ".well-known/resourcesync": render_resourcesync(),
        "llms.txt": canonical_public_links((root / "llms.txt").read_text(encoding="utf-8")),
    }
    hashes, changed = {}, []
    for relative, body in outputs.items():
        if origin_urls(body):
            raise ValueError(f"Origin URL leaked into generated discovery: {relative}")
        target = root / relative
        if target.is_symlink():
            raise ValueError(f"Root discovery cannot follow a symlink: {relative}")
        hashes[relative] = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if not target.is_file() or target.read_text(encoding="utf-8") != body:
            changed.append(relative)
    if check and changed:
        raise ValueError("Root discovery is stale: " + ", ".join(changed))
    if not check:
        for relative in changed:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(outputs[relative], encoding="utf-8")
    return {"changed_files": changed, "sha256": hashes, "public_root": PUBLIC_ROOT,
            "origin_urls": 0, "publishing": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(json.dumps(generate(args.root, check=args.check), sort_keys=True))


if __name__ == "__main__":
    main()
