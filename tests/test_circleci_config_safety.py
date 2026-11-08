"""The 20 read-only shards must never imply deployment."""
import unittest
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]

class CircleCIConfigSafetyTests(unittest.TestCase):
    def test_only_manual_readonly_preflight(self):
        config=yaml.safe_load((ROOT/'.circleci/config.yml').read_text())
        self.assertEqual(set(config['parameters']),{'run_workers'})
        self.assertIs(config['parameters']['run_workers']['default'],False)
        self.assertEqual(set(config['jobs']),{'supervisor_worker_preflight'})
        job=config['jobs']['supervisor_worker_preflight']
        self.assertEqual(job['parallelism'],20)
        self.assertEqual(job['resource_class'],'small')
        self.assertEqual(len(job['steps']),3)
        self.assertEqual([list(x)[0] if isinstance(x,dict) else x for x in job['steps']],['checkout','run','store_artifacts'])
        self.assertEqual(job['steps'][1]['run']['command'],'python tasks/circleci_worker.py')
        self.assertEqual(set(config['workflows']),{'manual_supervisor_preflight'})
        self.assertEqual(config['workflows']['manual_supervisor_preflight']['jobs'],['supervisor_worker_preflight'])
        self.assertNotIn('deploy',str(config).lower())
        self.assertNotIn('release',str(config).lower())

if __name__=='__main__':
    unittest.main()
