#!/usr/bin/env python3
"""Fetch immutable vendor VEX and retain only exact versioned Debian products."""
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "https://raw.githubusercontent.com/docker-hardened-images/advisories/"
EXPECTED_VENDOR_COMMIT = "be66b8136dad9c86b03615ef62fb8e7f48cf8ca7"
EXPECTED_SHA256 = "c7516bda28b0f5657821a98f39150273b747067f7f4d43cfe542181cc401f203"

def validate_pin(pin):
    sha = pin.get("vendor_commit", "")
    if sha != EXPECTED_VENDOR_COMMIT or pin.get("sha256") != EXPECTED_SHA256:
        raise ValueError("Vendor feed differs from the reviewed immutable pin")
    if pin.get("url") != PREFIX + sha + "/vex/python/dhi-python.vex.json":
        raise ValueError("Unapproved vendor source")
    return sha

def exact_products(document):
    if document.get("author") != "Docker Hardened Images <dhi@docker.com>":
        raise ValueError("Unexpected vendor author")
    statements = []
    for statement in document.get("statements", []):
        if statement.get("status") not in {"not_affected", "fixed"}:
            continue
        products = [product for product in statement.get("products", [])
                    if re.fullmatch(r"pkg:deb/debian/[A-Za-z0-9.+_-]+@[^?\s]+(?:\?[^\s]+)?",
                                    product.get("@id", ""))]
        if products:
            statements.append({**statement, "products": products})
    if not statements:
        raise ValueError("No exact versioned product evidence")
    return {**document, "@id": document["@id"] + "#exact-versioned-debian-products",
            "author": "CiteRAG deterministic vendor-document subset",
            "upstream_author": document["author"], "statements": statements}

def fetch(output):
    pin = json.loads((ROOT / "security/dhi-vex-source.json").read_text())
    sha = validate_pin(pin)
    headers = {"Accept": "application/vnd.github+json"}
    if os.getenv("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    req = urllib.request.Request(
        "https://api.github.com/repos/docker-hardened-images/advisories/commits/" + sha,
        headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        commit = json.load(response)
    if commit.get("sha") != sha or not commit["commit"]["verification"].get("verified"):
        raise ValueError("Vendor commit signature was not verified")
    with urllib.request.urlopen(pin["url"], timeout=30) as response:
        body = response.read(8 * 1024 * 1024)
    if hashlib.sha256(body).hexdigest() != pin["sha256"]:
        raise ValueError("Vendor document digest mismatch")
    document = json.loads(body)
    filtered = exact_products(document)
    output.mkdir(parents=True, exist_ok=True)
    (output / "dhi-python-vendor.vex.json").write_bytes(body)
    (output / "dhi-python-exact.vex.json").write_text(json.dumps(filtered, indent=2) + "\n")
    (output / "vendor-vex-provenance.json").write_text(json.dumps(
        {**pin, "git_signature_verified": True, "selection": "exact versioned Debian PURLs only",
         "statements_retained": len(filtered["statements"]),
         "statement_statuses_changed": False}, indent=2) + "\n")
    return len(filtered["statements"])

if __name__ == "__main__":
    count = fetch(ROOT / "release-evidence")
    print("Verified vendor VEX; retained exact-product statements:", count)
