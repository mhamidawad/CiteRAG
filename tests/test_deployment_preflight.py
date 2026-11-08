"""Release safety regression checks for missing external agents."""
import unittest
from unittest.mock import patch
from citerag import native, web

class DeploymentPreflightTests(unittest.TestCase):
    @patch.object(native, 'prepare_context')
    @patch.object(native.subprocess, 'run')
    def test_missing_native_runner_fails_without_side_effects(self, spawn, prepare):
        with patch.object(native.Path, 'is_file', return_value=False):
            result = native.answer('Test')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], 'NativeAdapterUnavailable')
        prepare.assert_not_called()
        spawn.assert_not_called()

    def test_live_native_status_not_claimed_verified(self):
        self.assertNotEqual(web.native_status(), 'verified')
