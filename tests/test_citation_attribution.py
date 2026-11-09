import unittest
from citerag.native_result import citation_and_claim_checks
class CitationAttributionTests(unittest.TestCase):
    def test_claim_must_be_supported_by_cited_chunk(self):
        rows=[{"source":"docs/a.md","id":"a"*64,"text":"CiteRAG uses LanceDB."},
              {"source":"docs/b.md","id":"b"*64,"text":"The deployment port is 8080."}]
        wrong="The deployment port is 8080.\nSource: docs/a.md\nChunk: "+"a"*64
        self.assertEqual(citation_and_claim_checks(wrong,rows),(True,False))
        right="The deployment port is 8080.\nSource: docs/b.md\nChunk: "+"b"*64
        self.assertEqual(citation_and_claim_checks(right,rows),(True,True))

    def test_numeric_prefix_and_sign_are_not_supported_facts(self):
        for claim,truth in [("The port is 80.","The port is 8080."),
                            ("The value is 1.","The value is 1.5."),
                            ("The value is 10.","The value is -10.")]:
            rows=[{"source":"docs/a.md","id":"a"*64,"text":truth}]
            output=claim+"\nSource: docs/a.md\nChunk: "+"a"*64
            self.assertEqual(citation_and_claim_checks(output,rows),(True,False))
