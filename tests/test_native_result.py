import json
import unittest
from citerag.native_result import evaluate

class NativeResultTests(unittest.TestCase):
    def trace(self,answer=None,tool='citerag_search',status='completed'):
        chunk='a'*64
        if answer is None:answer='LanceDB [docs/rag.md, chunk '+chunk+']'
        return '\n'.join(json.dumps(e) for e in [
            {'type':'tool_use','part':{'tool':tool,'state':{'status':status,'output':json.dumps({'results':[{'source':'docs/rag.md','id':chunk,'text':'LanceDB is the vector database.'}]})}}},
            {'type':'text','part':{'text':answer}},
            {'type':'step_finish','part':{'reason':'stop'}}])
    def test_native_call_with_real_source_reference_passes(self):
        self.assertEqual(evaluate(self.trace(),0)['status'],'PASS')
    def test_exit_zero_without_answer_fails(self):
        self.assertEqual(evaluate('',0)['status'],'FAIL')
    def test_guessing_tool_name_fails(self):
        self.assertEqual(evaluate(self.trace(tool='rag_search'),0)['status'],'FAIL')
    def test_invented_citation_fails(self):
        self.assertEqual(evaluate(self.trace(answer='LanceDB [docs/other.md, xyz]'),0)['status'],'FAIL')
    def test_failed_tool_and_malformed_event_fail(self):
        self.assertEqual(evaluate(self.trace(status='error'),0)['status'],'FAIL')
        self.assertEqual(evaluate(self.trace()+'\n{bad',0)['status'],'FAIL')
    def test_empty_tool_result_requires_explicit_abstention(self):
        from citerag.native_result import ABSTENTION
        trace='\n'.join(json.dumps(e) for e in [
            {'type':'tool_use','part':{'tool':'citerag_search','state':{'status':'completed','output':json.dumps({'results':[]})}}},
            {'type':'text','part':{'text':ABSTENTION}},
            {'type':'step_finish','part':{'reason':'stop'}}])
        self.assertEqual(evaluate(trace,0)['status'],'PASS')
        self.assertTrue(evaluate(trace,0)['abstained'])
        self.assertEqual(evaluate(trace.replace(ABSTENTION,'An invented answer'),0)['status'],'FAIL')

    def test_malformed_output_cannot_abstain(self):
        from citerag.native_result import ABSTENTION
        events=[{'type':'tool_use','part':{'tool':'citerag_search','state':{'status':'completed','output':'not valid JSON'}}},{'type':'text','part':{'text':ABSTENTION}},{'type':'step_finish','part':{'reason':'stop'}}]
        self.assertEqual(evaluate('\n'.join(map(json.dumps,events)),0)['status'],'FAIL')
    def test_unexpected_tool_fails_acceptance(self):
        extra=json.dumps({'type':'tool_use','part':{'tool':'shell','state':{'status':'completed','output':'done'}}})
        self.assertEqual(evaluate(extra+'\n'+self.trace(),0)['status'],'FAIL')
    def test_trace_redaction_preserves_json_structure(self):
        from citerag.native_result import sanitize_trace
        event={'type':'step_finish','part':{'reason':'stop','tokens':{'input':1556,'output':108}}}
        self.assertEqual(json.loads(sanitize_trace(json.dumps(event))),event)

    def test_nested_tool_json_survives_redaction(self):
        from citerag.native_result import sanitize_trace,evidence_in
        event={'type':'tool_use','part':{'tool':'citerag_search','state':{'status':'completed','output':json.dumps({'results':[{'id':'a'*64,'source':'docs/rag.md','token_start':0,'text':'approved evidence'}]})}}}
        output=json.loads(sanitize_trace(json.dumps(event)))['part']['state']['output']
        self.assertEqual(len(evidence_in(output)),1)
        self.assertEqual(json.loads(output)['results'][0]['token_start'],0)

    def test_false_claim_with_real_citation_fails(self):
        self.assertEqual(evaluate(self.trace(answer='Pinecone [docs/rag.md, chunk '+'a'*64+']'),0)['status'],'FAIL')
    def test_extra_fabricated_citation_fails(self):
        self.assertEqual(evaluate(self.trace(answer='LanceDB [docs/rag.md, chunk '+'a'*64+'] [docs/nonexistent.md, chunk '+'b'*64+']'),0)['status'],'FAIL')
    def test_negated_supported_fact_fails(self):
        self.assertEqual(evaluate(self.trace(answer='LanceDB is not the vector database. [docs/rag.md, chunk '+'a'*64+']'),0)['status'],'FAIL')
    def test_unsupported_paraphrase_is_not_claimed_verified(self):
        self.assertEqual(evaluate(self.trace(answer='This system stores vectors in LanceDB. [docs/rag.md, chunk '+'a'*64+']'),0)['status'],'FAIL')
    def test_key_aware_nested_redaction(self):
        from citerag.native_result import sanitize_trace
        event={'part':{'output':json.dumps({'api_key':'audit-only-placeholder','apiKey':'another-placeholder','authorization':'opaque-placeholder','token_start':0,'tokens':{'input':15}})}}
        result=json.loads(json.loads(sanitize_trace(json.dumps(event)))['part']['output'])
        self.assertEqual(result['api_key'],'[REDACTED]');self.assertEqual(result['apiKey'],'[REDACTED]');self.assertEqual(result['authorization'],'[REDACTED]')
        self.assertEqual(result['token_start'],0);self.assertEqual(result['tokens']['input'],15)

    def test_quoted_source_reference_is_not_a_fabricated_outer_citation(self):
        from citerag.native_result import citation_and_claim_checks
        row={'source':'docs/history.md','id':'a'*64,'text':'Earlier work referenced docs/old.md.'}
        answer='> Earlier work referenced docs/old.md.\nSource: docs/history.md\nChunk: '+'a'*64
        self.assertEqual(citation_and_claim_checks(answer,[row]),(True,True))
    def test_swapped_chunk_ids_fail(self):
        rows=[{'source':'docs/a.md','id':'a'*64,'text':'LanceDB'},{'source':'docs/b.md','id':'b'*64,'text':'MiniLM'}]
        from citerag.native_result import citation_and_claim_checks
        answer='LanceDB [docs/a.md, chunk '+'b'*64+'] [docs/b.md, chunk '+'a'*64+']'
        self.assertFalse(citation_and_claim_checks(answer,rows)[0])
