"""Offline validation for the 20 logical GitHub Actions preflight artifacts."""
import json
import tempfile
import unittest
from pathlib import Path
from tasks import verify_worker_preflight as verify
from tasks.worker_preflight import slot


def fixtures():
    records=[]
    for index in range(20):
        role, shard, source=slot(index,20)
        records.append({"slot":index,"total":20,"role":role,"shard":shard,
                        "source":source,"status":"preflight_pass",
                        "ai_inference":False,"writes_to_repository":False})
    return records


class WorkerResultsTests(unittest.TestCase):
    def test_exact_twenty(self):
        result=verify.validate(fixtures())
        self.assertEqual(result["status"],"PASS")
        self.assertEqual(result["verified_slots"],20)
        self.assertFalse(result["cloud_worker_claim"])

    def test_missing_duplicate_rejected(self):
        with self.assertRaises(verify.EvidenceError):
            verify.validate(fixtures()[:-1])
        rows=fixtures()
        rows[19]=rows[0]
        with self.assertRaises(verify.EvidenceError):
            verify.validate(rows)

    def test_unauthorized_writes_and_ai_rejected(self):
        rows=fixtures()
        rows[4]["ai_inference"]=True
        with self.assertRaises(verify.EvidenceError):
            verify.validate(rows)
        rows=fixtures()
        rows[5]["writes_to_repository"]=True
        with self.assertRaises(verify.EvidenceError):
            verify.validate(rows)

    def test_extra_keys_and_fake_source_rejected(self):
        rows=fixtures()
        rows[4]["source"]="docs/incorrect.md"
        with self.assertRaises(verify.EvidenceError):
            verify.validate(rows)
        rows=fixtures()
        rows[4]["extra"]="unapproved"
        with self.assertRaises(verify.EvidenceError):
            verify.validate(rows)

    def test_filesystem_manifest(self):
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)
            for record in fixtures():
                p=directory/f"slot-{record['slot']}.json"
                p.write_text(json.dumps(record))
            self.assertEqual(verify.verify_directory(directory)["verified_slots"],20)
            (directory/"slot-4.json").unlink()
            with self.assertRaises(verify.EvidenceError):
                verify.verify_directory(directory)
