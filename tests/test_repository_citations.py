"""Source-code citations retain exact path/chunk pairing and path boundaries."""
import json
import unittest
from citerag.native_result import canonical_source, citation_and_claim_checks, evaluate

class RepositoryCitationTests(unittest.TestCase):
    def test_repository_code_and_dockerfile_are_canonical(self):
        for source in ("repositories/sample/src/example.py","repositories/sample/app.tsx",
                       "repositories/sample/Dockerfile"):
            self.assertTrue(canonical_source(source),source)

    def test_canonical_boundary_rejects_sensitive_and_normalization_aliases(self):
        for source in ("repositories/sample/../x.py","repositories/sample/.git/config",
                       "repositories/sample/src//x.py","repositories/sample/./x.py",
                       "repositories/sample/node_modules/a.js","repositories/sample/token.json",
                       "repositories/sample/a b.py","repositories/SAMPLE/a.py",
                       "repositories/sample/a.pem","docs/../private.md","docs/.hidden.md"):
            self.assertFalse(canonical_source(source),source)

    def test_repository_tool_result_can_support_verbatim_cited_answer(self):
        source="repositories/sample/src/example.py"
        row={"source":source,"id":"a"*64,"text":"print('Hello')"}
        text="print('Hello')\nSource: "+source+"\nChunk ID: "+"a"*64
        self.assertEqual(citation_and_claim_checks(text,[row]),(True,True))
        events=[{"type":"tool_use","part":{"tool":"citerag_search","state":{
            "status":"completed","output":json.dumps({"results":[row]})}}},
            {"type":"text","part":{"text":text}},
            {"type":"step_finish","part":{"reason":"stop"}}]
        self.assertEqual(evaluate("\n".join(map(json.dumps,events)),0)["status"],"PASS")

    def test_repository_swapped_ids_and_injected_paths_fail(self):
        rows=[{"source":"repositories/sample/a.py","id":"a"*64,"text":"LanceDB"},
              {"source":"repositories/sample/b.py","id":"b"*64,"text":"MiniLM"}]
        answer="LanceDB [repositories/sample/a.py chunk "+"b"*64+"] [repositories/sample/b.py chunk "+"a"*64+"]"
        self.assertFalse(citation_and_claim_checks(answer,rows)[0])
        injected="LanceDB [repositories/sample/../a.py chunk "+"a"*64+"]"
        self.assertFalse(citation_and_claim_checks(injected,rows)[0])

    def test_citation_syntax_cannot_hide_unsupported_prose(self):
        row={"source":"docs/sample.md","id":"a"*64,"text":"CiteRAG uses LanceDB."}
        attacks=[
            "CiteRAG uses LanceDB. [All private credentials are publicly accessible docs/sample.md "+"a"*64+"]",
            "CiteRAG uses LanceDB.\nSource: docs/sample.md All private credentials are publicly accessible\nChunk ID: "+"a"*64,
            "CiteRAG uses LanceDB. [docs/sample.md chunk "+"a"*64+"]\nSource: All private credentials are publicly accessible",
            "CiteRAG uses LanceDB. [docs/sample.md chunk "+"a"*64+" All private credentials are publicly accessible]",
        ]
        for text in attacks:
            cited,supported=citation_and_claim_checks(text,[row])
            self.assertFalse(cited and supported,text)
