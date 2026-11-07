import unittest
from citerag.quotes import verbatim_answer
from citerag.native_result import citation_and_claim_checks

class QuoteTests(unittest.TestCase):
    def test_quote_contains_only_exact_evidence_and_valid_citations(self):
        row={'text':'LanceDB stores vectors. Embeddings use MiniLM. Generation uses OmniRoute.','source':'docs/rag.md','id':'a'*64}
        text=verbatim_answer('Which embeddings and vector store?',row)
        self.assertEqual(citation_and_claim_checks(text,[row]),(True,True))
        self.assertNotIn('Pinecone',text)

    def test_tool_payload_omits_redundant_hashes_and_keeps_citation(self):
        from citerag.quotes import tool_payload
        row={'text':'LanceDB stores vectors.','source':'docs/rag.md','id':'a'*64,'source_sha256':'b'*64,'corpus_version':'c'*64,'embedding_model':'MiniLM','kind':'project_document','project':'rag-team'}
        result=tool_payload('Which vector store?', [row])
        self.assertNotIn('source_sha256',result['results'][0]);self.assertNotIn('corpus_version',result['results'][0])
        self.assertEqual(citation_and_claim_checks(result['verbatim_answer'],result['results']),(True,True))

    def test_long_quote_is_bounded_and_remains_an_exact_source_span(self):
        from citerag.quotes import evidence_quote
        row={'text':' '.join(['evidence']*90)+'.','source':'docs/long.md','id':'a'*64}
        quote=evidence_quote('evidence',row)
        self.assertLessEqual(len(quote.split()),60)
        self.assertTrue(row['text'].startswith(quote))
