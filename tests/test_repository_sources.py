"""Acceptance of approved Git source isolation, redaction, bounds and provenance."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from citerag import repository_sources as sources
from citerag import semantic

class RepositorySourcesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Source test")
        (self.root/"hello.py").write_text('def greet():\n    return "hello"\n')
        self.git("add", ".")
        self.git("commit", "-qm", "Initial source")
        self.env = patch.dict(os.environ, {"CITERAG_REPOSITORY_SOURCES":json.dumps({"sample":str(self.root)})})
        self.env.start()
    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()
    def git(self, *args):
        return subprocess.run(["git","-C",str(self.root),*args],check=True,capture_output=True)
    def track(self,name,body):
        path=self.root/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(body if isinstance(body,bytes) else body.encode())
        self.git("add","--",name)
    def test_index_version_four_and_head_revision_are_supported(self):
        self.track("src/foo.py", "first")
        self.track("src/far.py", "second")
        self.git("update-index", "--index-version=4")
        indexed, revision = sources._git_inventory(self.root)
        expected = self.git("rev-parse", "HEAD").stdout.decode().strip()
        self.assertIn(b"src/foo.py", indexed)
        self.assertIn(b"src/far.py", indexed)
        self.assertEqual(revision, expected)
        self.assertEqual(set(dict(sources.repository_documents())),
                         {"repositories/sample/hello.py",
                          "repositories/sample/src/far.py",
                          "repositories/sample/src/foo.py"})

    def test_only_tracked_source_and_safe_stable_citation(self):
        (self.root/"untracked.py").write_text("unapproved")
        self.track("main.ts","export const ready = true;")
        docs=dict(sources.repository_documents())
        self.assertEqual(set(docs),{"repositories/sample/hello.py","repositories/sample/main.ts"})
        status=sources.source_status()[0]
        self.assertEqual(status["documents"],2)
        self.assertEqual(len(status["revision"]),40)
        self.assertNotIn(str(self.root),json.dumps(status))
    def test_hidden_sensitive_dependencies_binary_and_symlinks_excluded(self):
        for name in [".env","node_modules/lib/a.js","data/dump.txt","secrets.json","keys/private-key.txt"]:
            self.track(name,"do not index")
        self.track("bad.py",b"binary\0text")
        self.track("image.png",b"pixels")
        self.track("space name.py","uncitable")
        self.track("unicode-\u00e9.py","uncitable")
        outside=Path(self.tmp.name)/"outside.py"
        outside.write_text("outside secret")
        (self.root/"escape.py").symlink_to(outside)
        self.git("add","escape.py")
        (self.root/"indirect").symlink_to(Path(self.tmp.name),target_is_directory=True)
        # A tracked file replaced with a symlinked parent must also be rejected.
        self.track("replace/a.py","tracked")
        (self.root/"replace/a.py").unlink()
        (self.root/"replace").rmdir()
        (self.root/"replace").symlink_to(Path(self.tmp.name),target_is_directory=True)
        docs=dict(sources.repository_documents())
        self.assertEqual(set(docs),{"repositories/sample/hello.py"})
    def test_redacts_credentials_before_yielding(self):
        self.track("client.py",'api_key = "SYNTHETIC-ONLY-credential-value-123"\nanswer = 42\n')
        text=dict(sources.repository_documents())["repositories/sample/client.py"]
        self.assertNotIn("SYNTHETIC-ONLY",text)
        self.assertIn("[REDACTED]",text)
        self.assertIn("answer = 42",text)
    def test_deleted_and_untracked_paths_absent_after_refresh(self):
        self.assertEqual(len(list(sources.repository_documents())),1)
        (self.root/"hello.py").unlink()
        self.assertEqual(list(sources.repository_documents()),[])
    def test_invalid_names_roots_and_nested_root_fail_closed(self):
        for config in [{"bad/name":str(self.root)},{"valid":"relative/path"},{"valid":"/"}]:
            with self.subTest(config=config),patch.dict(os.environ,{"CITERAG_REPOSITORY_SOURCES":json.dumps(config)}):
                with self.assertRaises(ValueError):list(sources.repository_documents())
        (self.root/"nested").mkdir()
        with patch.dict(os.environ,{"CITERAG_REPOSITORY_SOURCES":json.dumps({"valid":str(self.root/"nested")})}):
            with self.assertRaises(ValueError):list(sources.repository_documents())
    def test_symlink_root_rejected(self):
        link=Path(self.tmp.name)/"linked"
        link.symlink_to(self.root,target_is_directory=True)
        with patch.dict(os.environ,{"CITERAG_REPOSITORY_SOURCES":json.dumps({"valid":str(link)})}):
            with self.assertRaises(ValueError):list(sources.repository_documents())
    def test_budget_rejects_whole_repository_without_partial_yield(self):
        self.track("two.py","abcdefgh")
        with patch.object(sources,"MAX_TOTAL_BYTES",3):
            generator=sources.repository_documents()
            with self.assertRaises(ValueError):next(generator)
        with patch.object(sources,"MAX_FILES",1):
            with self.assertRaises(ValueError):list(sources.repository_documents())
    def test_oversize_files_are_excluded(self):
        self.track("big.py","x"*100)
        with patch.object(sources,"MAX_FILE_BYTES",50):
            self.assertNotIn("repositories/sample/big.py",dict(sources.repository_documents()))
    def test_docs_and_repository_share_total_corpus_budget(self):
        docs=Path(self.tmp.name)/"docs"
        docs.mkdir()
        (docs/"large.txt").write_text("a"*250000)
        for n in range(7):
            (docs/("large%d.txt"%n)).write_text("a"*250000)
        with patch.object(semantic,"DOCS",docs),patch.object(semantic,"ROOT",Path(self.tmp.name)):
            with self.assertRaises(ValueError):list(semantic.documents())
    def test_semantic_includes_repository_provenance_and_shared_budget(self):
        class Tokenizer:
            def encode(self,text,**kwargs):return text.split()
            def decode(self,tokens,**kwargs):return " ".join(tokens)
        class Model:tokenizer=Tokenizer()
        docs=Path(self.tmp.name)/"docs"
        docs.mkdir()
        with patch.object(semantic,"DOCS",docs),patch.object(semantic,"ROOT",Path(self.tmp.name)),patch.object(semantic,"model",return_value=Model()):
            rows=list(semantic.chunks())
        self.assertTrue(rows)
        self.assertEqual(rows[0]["project"],"sample")
        self.assertEqual(rows[0]["kind"],"source_code")
        self.assertEqual(len(rows[0]["id"]),64)
        self.assertEqual(len(rows[0]["source_sha256"]),64)

if __name__=="__main__":unittest.main()
