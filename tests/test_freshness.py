import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
from citerag import freshness
from citerag.inference_lock import InferenceBusy

class FreshnessTests(unittest.TestCase):
    def test_active_other_writer_is_deferred(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'lease.json';p.write_text(json.dumps({'active':True,'owner':'other','expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}))
            with self.assertRaises(InferenceBusy):freshness.check_writer_access(owner='self',path=p)
            freshness.check_writer_access(owner='other',path=p)
    def test_failed_refresh_is_visible(self):
        with tempfile.TemporaryDirectory() as d,patch.object(freshness,'ROOT',Path(d)),patch.object(freshness,'check_writer_access'),patch.object(freshness,'inference_lock'),patch.object(freshness,'refresh',side_effect=ValueError('not fresh')):
            result=freshness.prepare_context()
            self.assertEqual(result['status'],'failed')
            self.assertEqual(json.loads((Path(d)/'data/context-refresh-attempt.json').read_text())['reason'],'ValueError')
