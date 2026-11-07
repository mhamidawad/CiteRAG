import tempfile
import unittest
from pathlib import Path
from citerag.cli import ingest, search, DOCS

class RetrievalTests(unittest.TestCase):
    def test_ingest_and_search(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "test.sqlite3"
            self.assertGreaterEqual(ingest(db, DOCS), 1)
            self.assertTrue(any("docs/" in p for p, _ in search(db, "OpenCode")))
            self.assertEqual(search(db, ""), [])
    def test_reject_external_source(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                ingest(Path(d) / "db.sqlite3", d)
    def test_search_injection_is_not_sql(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "db.sqlite3"
            ingest(db, DOCS)
            with self.assertRaises(Exception):
                search(db, "' OR 1=1 --")

if __name__ == "__main__":
    unittest.main()
