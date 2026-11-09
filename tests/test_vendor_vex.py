"""Tests for immutable and narrow vendor VEX selection."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vendor_vex", ROOT / "tasks/fetch-vendor-vex.py")
vex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vex)


class VendorVexTests(unittest.TestCase):
    def test_only_the_reviewed_signed_feed_pin_is_accepted(self):
        pin = {"vendor_commit": vex.EXPECTED_VENDOR_COMMIT,
               "url": vex.PREFIX + vex.EXPECTED_VENDOR_COMMIT + "/vex/python/dhi-python.vex.json",
               "sha256": vex.EXPECTED_SHA256, "vendor_commit_verified": True}
        self.assertEqual(vex.validate_pin(pin), vex.EXPECTED_VENDOR_COMMIT)
        for key, value in (("vendor_commit", "a"*40), ("sha256", "b"*64),
                           ("url", "https://example.invalid/vex.json")):
            altered = dict(pin); altered[key] = value
            with self.assertRaises(ValueError):
                vex.validate_pin(altered)

    def test_global_unversioned_subcomponent_and_nonfixed_products_are_excluded(self):
        doc = {"@id":"urn:test", "author":"Docker Hardened Images <dhi@docker.com>",
               "statements":[
                 {"status":"fixed", "products":[{"@id":"pkg:deb/debian/sqlite3@3.46.1-7%2Bdeb13u2"}]},
                 {"status":"not_affected", "products":[{"@id":"pkg:deb/debian/sqlite3"}]},
                 {"status":"fixed", "products":[{"@id":"pkg:deb/debian/sqlite3?arch=amd64"}]},
                 {"status":"fixed", "products":[{"@id":"pkg:generic/python"}]},
                 {"status":"under_investigation", "products":[{"@id":"pkg:deb/debian/libc6@2.36"}]},
                 {"status":"fixed", "products":[{"@id":"pkg:deb/debian/libc6@2.36"}],
                  "notes":"vendor evidence retained unchanged"}]}
        selected = vex.exact_products(doc)
        self.assertEqual(len(selected["statements"]), 2)
        self.assertEqual(selected["statements"][0]["products"][0]["@id"],
                         "pkg:deb/debian/sqlite3@3.46.1-7%2Bdeb13u2")
        self.assertEqual(selected["statements"][0]["status"], "fixed")
        self.assertEqual(selected["statements"][1]["status"], "fixed")
        self.assertEqual(selected["statements"][1]["notes"], "vendor evidence retained unchanged")
        self.assertEqual(selected["upstream_author"], doc["author"])

    def test_wrong_vendor_author_fails_closed(self):
        with self.assertRaises(ValueError):
            vex.exact_products({"@id":"urn:test", "author":"unknown", "statements":[]})


if __name__ == "__main__":
    unittest.main()
