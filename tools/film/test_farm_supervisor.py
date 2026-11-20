"""Offline safety checks. No browser, network, farm files, or GPU access."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
import farm_supervisor as fs


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.farm = self.root / 'renders/farm'
        self.farm.mkdir(parents=True)
        self.patches = [patch.object(fs, 'ROOT', self.root), patch.object(fs, 'FARM', self.farm), patch.object(fs, 'HERE', self.root / 'tools/film')]
        for p in self.patches:
            p.start()
        self.s = fs.Supervisor(True)
        self.s.log = Mock()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_dry_action_has_no_subprocess_or_files(self):
        with patch.object(fs.subprocess, 'run', side_effect=AssertionError):
            self.assertTrue(self.s.drive('new', 'g4cf3', 'G4 GPU'))
            self.s.drain('g4cf3')
        self.assertEqual(list(self.farm.iterdir()), [])

    def test_heartbeat_does_not_verify_repair(self):
        now = time.time()
        self.s.state['verify'] = {'g4cf1': now - 200}
        self.s.alert = Mock()
        self.assertTrue(self.s.verify('g4cf1', [(now, 'worker g4cf1 state running')], now))
        self.s.alert.assert_called_once()
        self.assertFalse(self.s.verify('g4cf1', [(now, 'claim cf_01 -> g4cf1')], now))

    def test_orphan_never_released_from_stale_heartbeat(self):
        self.s.api = Mock(side_effect=AssertionError)
        self.s.release_orphans({'g4cf1': {'state': 'idle', 'seen': 1, 'current': []}},
                               {'cf_01': {'worker': 'g4cf1', 'at': 1}}, 10000)
        self.assertEqual(self.s.orphans, {})

    def test_orphan_requires_two_snapshots_and_preserves_receipt(self):
        now = time.time()
        c = {'worker': 'g4cf1', 'at': now - 1000, 'lease_until': now + 600, 'status': 'claimed'}
        folder = self.root / 'renders/cf_01'; folder.mkdir()
        (folder / 'claim.json').write_text(json.dumps(c))
        status = {'g4cf1': {'state': 'idle', 'seen': now, 'current': []}}
        self.s.api = Mock(return_value=status)
        self.s.release_orphans(status, {'cf_01': c}, now)
        self.s.api.assert_not_called()
        (folder / 'job.json').write_text('{"status":"completed"}')
        self.s.release_orphans(status, {'cf_01': c}, now + 61)
        self.s.api.assert_called_once_with('/status')
        self.assertTrue((folder / 'job.json').exists())

    def test_bad_browser_output_never_logged(self):
        result = Mock(returncode=1, stdout=b'credential', stderr=b'credential')
        with patch.object(fs.subprocess, 'run', return_value=result):
            self.assertIsNone(self.s.probe())
        self.assertNotIn('credential', str(self.s.log.call_args_list))

    def test_server_failure_stops_without_browser(self):
        self.s.api = Mock(side_effect=OSError)
        self.s.probe = Mock(side_effect=AssertionError)
        self.s.tick()
        self.assertTrue(self.s.dead)

    def test_vsr_partial_upload_not_complete(self):
        path = self.root / 'renders/lab/vsr'; path.mkdir(parents=True)
        (path / 'sc_01.mp4').write_bytes(b'truncated')
        (path / 'sc_01.json').write_text('{"output_sha256":"incorrect"}')
        self.assertFalse(self.s.vsr_valid('sc_01'))

    def test_log_midnight_rollover(self):
        path = self.root / 'log'
        path.write_text('23:59:59 saved old\n00:00:01 saved new\n')
        data = fs.events(path, time.time())
        self.assertEqual(data[1][0] - data[0][0], 2)


if __name__ == '__main__':
    unittest.main()
