"""Question echoes are not answers; explicit code navigation remains supported."""
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from citerag import semantic
from citerag.quotes import evidence_quote

class RelevanceContractTests(unittest.TestCase):
    question = "Which vector database does this project use?"
    def row(self,source,text,kind="project_document"):
        return {"id":hashlib.sha256(source.encode()).hexdigest(),"source":source,"text":text,
                "kind":kind,"project":"citerag","_distance":0.1}
    def test_question_only_placeholder_has_zero_factual_coverage(self):
        row=self.row("repositories/citerag/citerag/web.html",
                     '<input placeholder = "Which vector database does this project use?">',"source_code")
        self.assertEqual(semantic.evidence_coverage(self.question,row),0)
        with self.assertRaises(ValueError):evidence_quote(self.question,row)
    def test_prompt_does_not_contaminate_selected_verbatim_evidence(self):
        row=self.row("docs/architecture.md",
                     "Which vector database does this project use? The vector database is LanceDB.")
        self.assertEqual(semantic.evidence_coverage(self.question,row),1)
        quote=evidence_quote(self.question,row)
        self.assertEqual(quote,"The vector database is LanceDB.")
        self.assertNotIn("?",quote)
    def test_explicit_placeholder_source_query_keeps_code_evidence(self):
        query="Find the vector database question placeholder in web.html"
        row=self.row("repositories/citerag/citerag/web.html",
                     '<input placeholder = "Which vector database does this project use?">',"source_code")
        self.assertGreater(semantic.evidence_coverage(query,row),0.5)
        self.assertIn("Which vector database",evidence_quote(query,row))
        self.assertEqual(semantic.source_relevance_weight(query,row),1)
    def test_source_path_alone_does_not_substantiate_factual_answer(self):
        row=self.row("docs/vector-database.md","The application starts on localhost.")
        self.assertEqual(semantic.evidence_coverage(self.question,row),0)
    def test_search_prefers_factual_doc_over_echoes_and_fixture_answers(self):
        echo=self.row("repositories/citerag/citerag/web.html",
                      '<input placeholder = "Which vector database does this project use?">',"source_code")
        fixture=self.row("repositories/citerag/tests/test_example.py",
                         'expected = "The vector database is ExampleDB."',"source_code")
        fact=self.row("docs/architecture.md","The vector database is LanceDB.")
        rows=[echo,fixture,fact]
        class Result:
            def __init__(self,items):self.items=items
            def distance_type(self,*args):return self
            def where(self,*args,**kwargs):return self
            def limit(self,*args):return self
            def to_list(self):return self.items
        class Table:
            schema=SimpleNamespace(names=["corpus_version"])
            def search(self,*args):return Result(rows)
            def head(self,n):return SimpleNamespace(to_pylist=lambda:[{"corpus_version":"test"}])
        db=SimpleNamespace(open_table=lambda name:Table())
        vector=SimpleNamespace(tolist=lambda:[0.0,1.0])
        model=SimpleNamespace(encode=lambda *args,**kwargs:vector)
        with tempfile.TemporaryDirectory() as temporary,patch.object(semantic,"ROOT",Path(temporary)),patch.object(semantic,"model",return_value=model),patch.object(semantic,"keyword_ids",return_value=[r["id"] for r in rows]),patch("citerag.repository_sources.configured_sources",return_value={}),patch.dict("sys.modules",{"lancedb":SimpleNamespace(connect=lambda path:db)}):
            result=semantic.search(self.question,5)
        self.assertEqual(result[0]["source"],"docs/architecture.md")
        self.assertNotIn(echo["source"],[r["source"] for r in result])
        self.assertIn(fixture["source"],[r["source"] for r in result])

if __name__=="__main__":unittest.main()
