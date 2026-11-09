"""Pinned model revisions bind loading, cache reuse and corpus identity."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from citerag import semantic

class EmbeddingRevisionTests(unittest.TestCase):
    def test_loader_requests_immutable_revision_even_without_main_ref(self):
        constructor=Mock(return_value=object())
        torch=SimpleNamespace(set_num_threads=Mock())
        with patch.object(semantic,"_model",None),patch.dict("sys.modules",{
            "torch":torch,"sentence_transformers":SimpleNamespace(SentenceTransformer=constructor)}):
            semantic.model()
        self.assertEqual(constructor.call_args.kwargs["revision"],semantic.REVISION)
        self.assertTrue(constructor.call_args.kwargs["local_files_only"])
    def test_mutable_revision_is_rejected_before_loading(self):
        with patch.object(semantic,"_model",None),patch.object(semantic,"REVISION","main"):
            with self.assertRaises(ValueError):semantic.model()
    def test_revision_change_reembeds_instead_of_reusing_old_vectors(self):
        class DB:
            rows=[]
            def table_names(self):return ["documents"] if self.rows else []
            def open_table(self,name):
                return SimpleNamespace(to_arrow=lambda:SimpleNamespace(to_pylist=lambda:self.rows))
            def create_table(self,name,rows,mode):self.rows=[dict(r) for r in rows]
        db=DB()
        encode=Mock(side_effect=lambda texts,**kwargs:[SimpleNamespace(tolist=lambda:[1.0,0.0]) for text in texts])
        model=SimpleNamespace(get_sentence_embedding_dimension=lambda:2,encode=encode)
        def chunks():
            return iter([{"id":"a"*64,"source":"docs/fact.md","text":"Vector database is LanceDB."}])
        with tempfile.TemporaryDirectory() as temporary,patch.object(semantic,"ROOT",Path(temporary)),patch.object(semantic,"chunks",side_effect=chunks),patch.object(semantic,"model",return_value=model),patch.object(semantic,"build_keywords"),patch("citerag.freshness.check_writer_access"),patch.dict("sys.modules",{"lancedb":SimpleNamespace(connect=lambda path:db)}):
            first=semantic.ingest()
            second=semantic.ingest()
            with patch.object(semantic,"REVISION","b"*40):
                changed=semantic.ingest()
        self.assertEqual(first["new_embeddings"],1)
        self.assertEqual(second["new_embeddings"],0)
        self.assertEqual(second["reused_embeddings"],1)
        self.assertEqual(changed["new_embeddings"],1)
        self.assertEqual(changed["reused_embeddings"],0)
        self.assertNotEqual(first["corpus_version"],changed["corpus_version"])
        self.assertEqual(db.rows[0]["embedding_revision"],"b"*40)

if __name__=="__main__":unittest.main()
