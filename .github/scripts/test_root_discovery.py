#!/usr/bin/env python3
"""Root discovery is source-generated and never changes unrelated app content."""

from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import gen_root_discovery
import gen_link_hub
from public_site import PUBLIC_ROOT, PUBLIC_SITE, ORIGIN_ROOT, canonical_public_links, origin_urls
import sync_standard_site
from test_sync_standard_site import payload, document_payload, AT_URI


class RootDiscoveryTests(unittest.TestCase):
    def test_resourcesync_references_are_exactly_the_three_canonical_urls(self):
        body = gen_root_discovery.render_resourcesync()
        document = ET.fromstring(body)
        urls = [node.text for node in document.iter() if node.tag.endswith("}loc")]
        urls += [node.attrib["href"] for node in document.iter() if "href" in node.attrib]
        self.assertEqual([
            PUBLIC_SITE + "/resourcesync/capabilitylist.xml",
            PUBLIC_SITE + "/resourcesync/bopomofo-collection.jsonld",
            PUBLIC_SITE + "/resourcesync/bopomofo-collection.jsonld",
        ], urls)
        self.assertEqual([], origin_urls(body))
        self.assertNotIn("alice51849.github.io", body)
        self.assertEqual(
            "0aa42115aff3eaf4908f2117ad0a0705ba9f33faa57c23367b1657f6f3f9df80",
            hashlib.sha256(body.encode()).hexdigest(),
        )

    def test_root_well_known_and_bare_origin_urls_are_not_missed(self):
        source = f"{ORIGIN_ROOT}\n{ORIGIN_ROOT}/.well-known/resourcesync\n"
        self.assertEqual(2, len(origin_urls(source)))
        self.assertEqual(f"{PUBLIC_ROOT}\n{PUBLIC_ROOT}/.well-known/resourcesync\n",
                         canonical_public_links(source))

    def test_external_federated_identifiers_are_not_origin_host_links(self):
        identifiers = (
            "https://bsky.app/profile/alice51849.github.io.web.brid.gy\n"
            "https://web.brid.gy/alice51849.github.io\n"
        )
        self.assertEqual([], origin_urls(identifiers))
        self.assertEqual(identifiers, canonical_public_links(identifiers))

    def test_ambiguous_origins_are_rejected_instead_of_silently_rewritten(self):
        for value in (
            "https://user@alice51849.github.io/.well-known/resourcesync",
            "https://alice51849.github.io:444/.well-known/resourcesync",
        ):
            with self.subTest(url=value), self.assertRaises(ValueError):
                canonical_public_links(value)

    def test_two_runs_preserve_all_bytes_and_331_other_files(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as scratch:
            root = Path(scratch)
            (root / "llms.txt").write_text(
                f"# Root\n- Discovery: {ORIGIN_ROOT}/.well-known/api-catalog\n"
                "- Federation: https://web.brid.gy/alice51849.github.io\n"
            )
            previous = {}
            for number in range(331):
                path = root / "historical" / f"app-{number}.html"
                path.parent.mkdir(exist_ok=True)
                path.write_text(f"<p>Historical {number}: {ORIGIN_ROOT}/support/</p>")
                previous[path] = path.read_bytes()
            first = gen_root_discovery.generate(root)
            generated = {relative: ((root / relative).read_bytes(), (root / relative).stat().st_mtime_ns)
                         for relative in first["sha256"]}
            second = gen_root_discovery.generate(root)
            self.assertEqual([], second["changed_files"])
            self.assertEqual(first["sha256"], second["sha256"])
            self.assertEqual(generated, {p: ((root / p).read_bytes(), (root / p).stat().st_mtime_ns)
                                         for p in generated})
            self.assertEqual(previous, {path: path.read_bytes() for path in previous})
            self.assertEqual([], origin_urls((root / "llms.txt").read_text()))
            self.assertEqual([], gen_root_discovery.generate(root, check=True)["changed_files"])

    def test_check_mode_blocks_stale_root_without_writing(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as scratch:
            root = Path(scratch)
            source = f"{ORIGIN_ROOT}/.well-known/resourcesync"
            (root / "llms.txt").write_text(source)
            with self.assertRaisesRegex(ValueError, "stale"):
                gen_root_discovery.generate(root, check=True)
            self.assertEqual(source, (root / "llms.txt").read_text())
            self.assertFalse((root / ".well-known/resourcesync").exists())

    def test_standard_source_requires_real_canonical_publication(self):
        self.assertEqual(PUBLIC_SITE, sync_standard_site.PUBLICATION_URL)
        self.assertEqual(AT_URI, sync_standard_site.publication_at_uri(payload()))
        with self.assertRaises(sync_standard_site.PublicationNotReady):
            sync_standard_site.publication_at_uri(payload(publication_url=ORIGIN_ROOT + "/ios-app-guide"))
        contract = sync_standard_site.guide_contract(AT_URI, document_payload())
        self.assertEqual(PUBLIC_SITE, contract["publication"]["url"])
        self.assertEqual(
            PUBLIC_ROOT + "/.well-known/site.standard.publication/ios-app-guide",
            contract["publication"]["well_known"]["request_url"],
        )
        self.assertEqual([], origin_urls(json.dumps(contract)))

    def test_link_hub_future_regeneration_keeps_root_discovery_canonical(self):
        source = f"# Site\n- Catalog: {ORIGIN_ROOT}/.well-known/api-catalog\n"
        with patch.object(gen_link_hub, "render_llms_section",
                          return_value=gen_link_hub.LLMS_SECTION_TITLE + "\nCanonical section\n"):
            result = gen_link_hub.merge_llms(source, {})
        self.assertIn(PUBLIC_ROOT + "/.well-known/api-catalog", result)
        self.assertEqual([], origin_urls(result))


if __name__ == "__main__":
    unittest.main()
