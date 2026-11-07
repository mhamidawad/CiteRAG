import unittest
from citerag.semantic import documents, search, DOCS
class SafetyTests(unittest.TestCase):
    def test_empty_query(self):
        self.assertEqual(search("  "), [])
    def test_query_bound(self):
        with self.assertRaises(ValueError):
            search("a"*4001)
    def test_symlink_excluded(self):
        link=DOCS/"outside-test.txt"
        link.symlink_to("/etc/hostname")
        try:
            self.assertNotIn("docs/outside-test.txt",[p for p,_ in documents()])
        finally:
            link.unlink()
if __name__=="__main__":
    unittest.main()
