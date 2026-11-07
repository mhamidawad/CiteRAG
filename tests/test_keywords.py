import tempfile
import unittest
from pathlib import Path
from citerag.semantic import build_keywords, keyword_ids

class KeywordTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'index.sqlite3'
        build_keywords([{'id':'a'*64,'source':'docs/opencode.json','text':'provider routing'},{'id':'b'*64,'source':'docs/history.md','text':'old session decisions'}],'current',self.path)
    def test_exact_filename(self):
        self.assertEqual(keyword_ids('opencode.json','current',path=self.path)[0],'a'*64)
    def test_stale_index_is_ignored(self):
        self.assertEqual(keyword_ids('opencode','new-corpus',path=self.path),[])
    def test_no_evidence_and_syntax_are_safe(self):
        self.assertEqual(keyword_ids('unknownterm OR " ; DROP TABLE chunks; --','current',path=self.path),[])
        self.assertTrue(keyword_ids('routing','current',path=self.path))
    def test_rebuild_removes_deleted_chunks(self):
        build_keywords([{'id':'b'*64,'source':'docs/history.md','text':'old session decisions'}],'next',self.path)
        self.assertEqual(keyword_ids('opencode','next',path=self.path),[])

    def test_scope_is_applied_before_keyword_result_limit(self):
        self.assertEqual(keyword_ids('routing history','current',limit=1,path=self.path,allowed_ids=['b'*64]),['b'*64])
        self.assertEqual(keyword_ids('routing','current',path=self.path,allowed_ids=[]),[])
