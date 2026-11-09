"""VEX derivation is constrained by signed vendor source and Trivy's exact package identity."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

fetch = load("vendor_vex_fetch", ROOT / "tasks/fetch-vendor-vex.py")
derive = load("vendor_vex_derive", ROOT / "tasks/derive-vendor-vex.py")


class VendorVexTests(unittest.TestCase):
    def test_only_the_reviewed_signed_feed_pin_is_accepted(self):
        pin = {"vendor_commit": fetch.EXPECTED_VENDOR_COMMIT,
               "url": fetch.PREFIX + fetch.EXPECTED_VENDOR_COMMIT + "/vex/python/dhi-python.vex.json",
               "sha256": fetch.EXPECTED_SHA256, "vendor_commit_verified": True}
        self.assertEqual(fetch.validate_pin(pin), fetch.EXPECTED_VENDOR_COMMIT)
        for key, value in (("vendor_commit", "a"*40), ("sha256", "b"*64),
                           ("url", "https://example.invalid/vex.json")):
            altered = dict(pin); altered[key] = value
            with self.assertRaises(ValueError): fetch.validate_pin(altered)

    def test_source_package_vendor_statement_matches_exact_trivy_binary_purl(self):
        purl = "pkg:deb/debian/libsqlite3-0@3.46.1-7%2Bdeb13u2%2Bdhi3?arch=amd64&distro=debian-13.7"
        vendor = {"@id":"urn:dhi", "author":"Docker Hardened Images <dhi@docker.com>",
          "statements":[
            {"@id":"sqlite", "vulnerability":{"name":"CVE-2026-1"},
             "status":"not_affected", "status_notes":"backport verified",
             "products":[{"@id":"pkg:deb/debian/sqlite3@3.46.1-7%2Bdeb13u2%2Bdhi3"}]},
            {"@id":"wrong-version", "vulnerability":{"name":"CVE-2026-1"},
             "status":"not_affected", "products":[
               {"@id":"pkg:deb/debian/sqlite3@3.45.1-1"}]},
            {"@id":"wrong-package", "vulnerability":{"name":"CVE-2026-1"},
             "status":"not_affected", "products":[
               {"@id":"pkg:deb/debian/expat@3.46.1-7%2Bdeb13u2%2Bdhi3"}]},
            {"@id":"wrong-status", "vulnerability":{"name":"CVE-2026-1"},
             "status":"under_investigation", "products":[
               {"@id":"pkg:deb/debian/sqlite3@3.46.1-7%2Bdeb13u2%2Bdhi3"}]}]}
        raw={"Results":[{"Packages":[{
          "Name":"libsqlite3-0","Version":"3.46.1-7+deb13u2+dhi3",
          "SrcName":"sqlite3","SrcVersion":"3.46.1",
          "Identifier":{"PURL":purl}}],"Vulnerabilities":[{
          "VulnerabilityID":"CVE-2026-1","PkgName":"libsqlite3-0",
          "InstalledVersion":"3.46.1-7+deb13u2+dhi3","Severity":"HIGH",
          "Status":"affected","PkgIdentifier":{"PURL":purl}}]}]}
        selected, counts = derive.derive(raw,vendor)
        self.assertEqual(counts,{"raw_high_critical_findings":1,"exact_vendor_matches":1,
                                 "unmatched_high_critical_findings":0})
        self.assertEqual(len(selected["statements"]),1)
        row=selected["statements"][0]
        self.assertEqual(row["products"],[{"@id":purl}])
        self.assertEqual(row["status"],"not_affected")
        self.assertEqual(row["status_notes"],"backport verified")
        self.assertNotIn("subcomponents",json.dumps(row))

    def test_unversioned_vendor_product_or_missing_source_identity_never_matches(self):
        purl="pkg:deb/debian/libsqlite3-0@1.0?arch=amd64"
        vendor={"author":"Docker Hardened Images <dhi@docker.com>","statements":[
          {"vulnerability":{"name":"CVE-1"},"status":"fixed",
           "products":[{"@id":"pkg:deb/debian/sqlite3"},
                       {"@id":"pkg:oci/dhi.io%2Fpython",
                        "subcomponents":[{"@id":"pkg:deb/debian/libsqlite3-0"}]}]}]}
        raw={"Results":[{"Packages":[{"Name":"libsqlite3-0","Version":"1.0",
          "SrcName":None,"Identifier":{"PURL":purl}}],"Vulnerabilities":[{
          "VulnerabilityID":"CVE-1","InstalledVersion":"1.0","Severity":"HIGH",
          "PkgIdentifier":{"PURL":purl}}]}]}
        selected,counts=derive.derive(raw,vendor)
        self.assertEqual(selected["statements"],[])
        self.assertEqual(counts["unmatched_high_critical_findings"],1)

    def test_wrong_vendor_author_fails_closed(self):
        with self.assertRaises(ValueError):
            derive.derive({"Results":[]},{"author":"unknown","statements":[]})


if __name__ == "__main__":
    unittest.main()
