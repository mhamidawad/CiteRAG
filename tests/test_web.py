import unittest
from unittest.mock import patch
from starlette.testclient import TestClient
from citerag import web

class WebTests(unittest.TestCase):
    def setUp(self):
        fresh=patch.object(web,'prepare_context',return_value={'status':'completed'});fresh.start();self.addCleanup(fresh.stop)
        self.client = TestClient(web.app)
    def test_page_and_health(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/api/health').json()['status'], 'ok')
    def test_invalid_question(self):
        self.assertEqual(self.client.post('/api/ask', json={'question': ''}).status_code, 400)
        self.assertEqual(self.client.post('/api/ask', content='bad').status_code, 400)
    def test_busy_is_rejected(self):
        web._generation.acquire()
        try:
            self.assertEqual(self.client.post('/api/ask', json={'question': 'x'}).status_code, 409)
        finally:
            web._generation.release()
    @patch.object(web, 'search', return_value=[{'source':'docs/example.md','id':'abc','text':'Evidence'}])
    @patch.object(web, 'answer', return_value={'status':'completed','answer':'A cited answer','sources':['docs/example.md']})
    def test_completed_job_keeps_evidence(self, answer, search):
        r=self.client.post('/api/ask', json={'question':'Question'})
        self.assertEqual(r.status_code, 202)
        data=self.client.get('/api/jobs/'+r.json()['job_id']).json()
        self.assertEqual(data['state'], 'completed')
        self.assertEqual(data['evidence'][0]['id'], 'abc')
        answer.assert_called_once_with('Question')
    @patch.object(web, 'search', return_value=[])
    @patch.object(web, 'answer', return_value={'status':'failed','error':'TimeoutError'})
    def test_failed_generation_remains_failed(self, answer, search):
        r=self.client.post('/api/ask', json={'question':'Question'})
        self.assertEqual(self.client.get('/api/jobs/'+r.json()['job_id']).json()['state'],'failed')
    def test_unknown_job(self):
        self.assertEqual(self.client.get('/api/jobs/missing').status_code,404)
    def test_context_status_is_available(self):
        result=self.client.get('/api/context')
        self.assertEqual(result.status_code,200)
        self.assertIsInstance(result.json()['imported_documents'],int)
        self.assertIn('not all',result.json()['coverage'])
    @patch.object(web,'search',return_value=[])
    @patch.object(web,'native_answer',return_value={'status':'completed','mode':'native_opencode','answer':'A cited answer','evidence':[{'source':'docs/rag.md','id':'a'*64,'text':'Evidence'}],'sources':['docs/rag.md'],'native_tool_calls':1,'citations_verified':True})
    def test_native_mode_uses_worker_evidence(self,native_answer,search):
        r=self.client.post('/api/ask',json={'question':'Question','use_native':True})
        data=self.client.get('/api/jobs/'+r.json()['job_id']).json()
        self.assertEqual(data['state'],'completed')
        self.assertEqual(data['mode'],'native_opencode')
        self.assertEqual(data['evidence'][0]['source'],'docs/rag.md')
        native_answer.assert_called_once_with('Question')
    @patch.object(web,'search',return_value=[])
    def test_no_evidence_is_reported_without_a_failure(self,search):
        r=self.client.post('/api/ask',json={'question':'Unknown','retrieval_only':True})
        data=self.client.get('/api/jobs/'+r.json()['job_id']).json()
        self.assertEqual(data['status'],'insufficient_evidence')
        self.assertEqual(data['state'],'completed')

    @patch.object(web,'prepare_context',return_value={'status':'failed'})
    @patch.object(web,'answer')
    def test_refresh_failure_blocks_generation(self,answer,fresh):
        r=self.client.post('/api/ask',json={'question':'Question'})
        self.assertEqual(self.client.get('/api/jobs/'+r.json()['job_id']).json()['state'],'failed')
        answer.assert_not_called()
