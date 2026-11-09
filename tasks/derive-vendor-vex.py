#!/usr/bin/env python3
"""Derive only exact installed-package VEX matches from signed DHI statements."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
DEB_PURL = re.compile(r"^pkg:deb/debian/([A-Za-z0-9.+_-]+)(?:@([^?\s]+))?(?:\?([^\s]+))?$")


def parse_deb_purl(value):
    match = DEB_PURL.fullmatch(value or "")
    if not match:
        return None
    name, version, qualifiers = match.groups()
    return name, unquote(version) if version else None


def statement_matches(statement, package_name, installed_version, source_name=None):
    if statement.get("status") not in {"fixed", "not_affected"}:
        return False
    direct_products = set()
    subcomponents = set()
    for product in statement.get("products", []):
        if not isinstance(product, dict):
            continue
        parsed = parse_deb_purl(product.get("@id"))
        if parsed and parsed[1]:
            direct_products.add(parsed)
        for component in product.get("subcomponents", []):
            if isinstance(component, dict):
                parsed_component = parse_deb_purl(component.get("@id"))
                if parsed_component and parsed_component[1]:
                    subcomponents.add(parsed_component)
    # Trivy's own dpkg package inventory identifies the source package. The
    # vendor's versioned source PURL must match the exact installed binary version.
    if source_name and (source_name, installed_version) in direct_products:
        return True
    if (package_name, installed_version) in direct_products:
        return True
    # A vendor-named binary subcomponent is accepted only if it is versioned.
    return (package_name, installed_version) in subcomponents


def derive(raw_report, vendor_document):
    if vendor_document.get("author") != "Docker Hardened Images <dhi@docker.com>":
        raise ValueError("Unexpected vendor author")
    statements = vendor_document.get("statements")
    if not isinstance(statements, list):
        raise ValueError("Vendor statements missing")

    packages = {}
    for result in raw_report.get("Results", []):
        for package in result.get("Packages") or []:
            purl = (package.get("Identifier") or {}).get("PURL")
            parsed = parse_deb_purl(purl)
            if not parsed or not parsed[1]:
                continue
            packages[purl] = {"name": parsed[0], "version": parsed[1],
                              "source_name": package.get("SrcName")}

    findings = {}
    for result in raw_report.get("Results", []):
        for finding in result.get("Vulnerabilities") or []:
            purl = (finding.get("PkgIdentifier") or {}).get("PURL")
            package = packages.get(purl)
            if (finding.get("Severity") not in {"HIGH", "CRITICAL"} or not package
                    or finding.get("InstalledVersion") != package["version"]):
                continue
            key = (finding.get("VulnerabilityID"), purl)
            findings[key] = package

    output_statements = []
    matched_findings = set()
    for (cve, purl), package in sorted(findings.items()):
        matches = [statement for statement in statements
                   if (statement.get("vulnerability") or {}).get("name") == cve
                   and statement_matches(statement, package["name"], package["version"],
                                         package["source_name"])]
        for original in matches:
            matched_findings.add((cve, purl))
            identifier = hashlib.sha256((cve + "\0" + purl +
                "\0" + str(original.get("@id", ""))).encode()).hexdigest()[:20]
            # Retain vendor disposition and rationale, with only the exact PURL
            # reported by Trivy as a derived product.
            output_statements.append({**original,
                "@id": str(original.get("@id", "urn:dhi-vex")) + "#citerag-" + identifier,
                "products": [{"@id": purl}]})

    derived = {key: value for key, value in vendor_document.items()
               if key not in {"statements", "author", "upstream_author"}}
    derived.update({"@id": str(vendor_document.get("@id", "urn:dhi-vex")) + "#citerag-trivy-exact",
        "author": "CiteRAG deterministic Trivy PURL subset",
        "upstream_author": vendor_document["author"],
        "statements": output_statements})
    finding_keys = set(findings)
    return derived, {"raw_high_critical_findings": len(finding_keys),
        "exact_vendor_matches": len(matched_findings),
        "unmatched_high_critical_findings": len(finding_keys - matched_findings)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-report", type=Path, required=True)
    parser.add_argument("--vendor-document", type=Path,
                        default=ROOT / "release-evidence/dhi-python-vendor.vex.json")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "release-evidence/dhi-python-exact.vex.json")
    args = parser.parse_args(argv)
    raw = json.loads(args.raw_report.read_text())
    vendor = json.loads(args.vendor_document.read_text())
    derived, counts = derive(raw, vendor)
    args.output.write_text(json.dumps(derived, indent=2) + "\n")
    provenance_path = args.output.parent / "vendor-vex-provenance.json"
    provenance = json.loads(provenance_path.read_text())
    provenance.update(counts)
    provenance["matching_rule"] = "signed vendor status; Trivy dpkg SrcName links binary to versioned vendor source PURL; exact installed version; output exact Trivy PURL"
    provenance["derived_vex_sha256"] = hashlib.sha256(args.output.read_bytes()).hexdigest()
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
