import unittest
from contextlib import nullcontext
from unittest.mock import patch
from citerag.answer import answer

class AbstentionTests(unittest.TestCase):
    @patch('citerag.answer.search',return_value=[])
    @patch('citerag.answer.httpx.Client')
    def test_missing_evidence_never_sends_generation(self,inspect,search):
        with patch('citerag.answer.inference_lock',return_value=nullcontext()):
            result=answer('unsupported question')
        self.assertEqual(result['status'],'insufficient_evidence')
        self.assertEqual(result['sources'],[])
        inspect.assert_not_called()
