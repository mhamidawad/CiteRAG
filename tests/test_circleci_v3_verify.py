"""Strict, offline, no CircleCI credentials or API calls."""
import unittest
from tasks import circleci_v3_verify as v
from tasks.circleci_worker import slot

class V3AcceptanceTests(unittest.TestCase):
 def fixtures(self):
  rows=[]
  for i in range(20):
   role,shard,source=slot(i,20)
   rows.append({"slot":i,"total":20,"role":role,"shard":shard,"source":source,
                "status":"preflight_pass","ai_inference":False,"writes_to_repository":False})
  return rows
 def test_exact_twenty(self):
  self.assertEqual(v.validate_shards(self.fixtures()),list(range(20)))
 def test_no_missing_or_duplicate(self):
  records=self.fixtures()
  with self.assertRaises(v.EvidenceError):v.validate_shards(records[:-1])
  records[19]=records[0]
  with self.assertRaises(v.EvidenceError):v.validate_shards(records)
 def test_reject_faked_inference_or_writes(self):
  records=self.fixtures();records[9]["ai_inference"]=True
  with self.assertRaises(v.EvidenceError):v.validate_shards(records)
  records=self.fixtures();records[5]["writes_to_repository"]=True
  with self.assertRaises(v.EvidenceError):v.validate_shards(records)
 def test_reject_mismatched_source(self):
  records=self.fixtures();records[4]["source"]="docs/other.md"
  with self.assertRaises(v.EvidenceError):v.validate_shards(records)
 def test_artifact_urls_limited(self):
  self.assertTrue(v.approved_url("https://circleci.com/api/v3/jobs/x/artifacts"))
  for url in ("http://circleci.com/a","https://circleci.com.evil.example/a","http://127.0.0.1:80/a","file:///etc/passwd"):
   self.assertFalse(v.approved_url(url))
