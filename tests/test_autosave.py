"""Exercise saves, interrupted transfers and restart against the writeback contract."""
import json
import pathlib
import sys
import time
import unittest
import urllib.error

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import test_workspace as fixtures
import workspace as w
import autosave as a


class AutosaveTests(unittest.TestCase):
    def fresh(self):
        return fixtures.WorkspaceTests.fresh(self)

    def enable(self, base, paths=('a.txt',), generated=()):
        return a.enable(base, paths, generated, authorized=True, settle=2)

    def settle(self, base, gateway, start=100):
        a.cycle(base, gateway, now=start)
        return a.cycle(base, gateway, now=start+3)

    def test_stable_save_scoped_and_no_delete(self):
        base, g = self.fresh()
        self.enable(base)
        (base/'files/a.txt').write_text('saved automatically')
        (base/'files/unapproved.txt').write_text('must stay local')
        a.cycle(base, g, now=100)
        self.assertEqual(g.writes, [])
        a.cycle(base, g, now=103)
        self.assertEqual(g.files['Folder/a.txt'], b'saved automatically')
        self.assertEqual(g.writes, ['Folder/a.txt'])
        (base/'files/a.txt').rename(base/'kept-a.txt')
        self.settle(base, g, 110)
        self.assertEqual(g.trash, [])
        self.assertEqual(a.status(base)['files']['a.txt']['state'], 'missing-local')

    def test_generated_file_needs_exact_ready_hash(self):
        base, g = self.fresh()
        self.enable(base, (), ('result.pdf',))
        (base/'files/result.pdf').write_bytes(b'first generation')
        self.settle(base, g)
        self.assertEqual(g.writes, [])
        a.ready(base, ['result.pdf'])
        (base/'files/result.pdf').write_bytes(b'changed after validation')
        self.settle(base, g, 110)
        self.assertEqual(g.writes, [])
        a.ready(base, ['result.pdf'])
        self.settle(base, g, 120)
        self.assertEqual(g.files['Folder/result.pdf'], b'changed after validation')

    def test_network_retry_survives_restart(self):
        base, g = self.fresh()
        self.enable(base)
        (base/'files/a.txt').write_bytes(b'new')
        original = g.req
        def offline(*args, **kwargs):
            raise urllib.error.URLError('offline')
        g.req = offline
        self.settle(base, g)
        report = a.status(base)
        self.assertEqual(report['files']['a.txt']['state'], 'retry')
        self.assertEqual(g.writes, [])
        g.req = original
        a.cycle(base, g, now=10000)
        self.assertEqual(g.files['Folder/a.txt'], b'new')
        self.assertEqual(a.status(base)['files']['a.txt']['state'], 'synced')

    def test_lost_response_then_new_save_keeps_both_versions(self):
        base, g = self.fresh()
        self.enable(base)
        (base/'files/a.txt').write_bytes(b'version one')
        original = g.req
        def lost(method, path='', data=None, headers=None):
            result = original(method, path, data, headers)
            if method == 'PUT':
                raise TimeoutError('lost response')
            return result
        g.req = lost
        self.settle(base, g)
        (base/'files/a.txt').write_bytes(b'version two')
        g.req = original
        a.cycle(base, g, now=10000)
        self.assertEqual(len(g.writes), 1)
        self.assertEqual(g.files['Folder/a.txt'], b'version one')
        self.settle(base, g, 10010)
        self.assertEqual(g.files['Folder/a.txt'], b'version two')
        self.assertEqual(len(g.writes), 2)
        self.assertEqual(a.status(base)['files']['a.txt']['sha256'], w.digest(b'version two'))
        snapshots = list((base/'autosave/jobs').glob('*/snapshot/files/a.txt'))
        self.assertEqual({p.read_bytes() for p in snapshots}, {b'version one', b'version two'})

    def test_remote_conflict_blocks_without_overwriting(self):
        base, g = self.fresh()
        self.enable(base)
        (base/'files/a.txt').write_bytes(b'local')
        g.files['Folder/a.txt'] = b'other device'
        self.settle(base, g)
        a.cycle(base, g, now=10000)
        self.assertEqual(g.writes, [])
        self.assertEqual(a.status(base)['files']['a.txt']['state'], 'blocked')

    def test_partial_upload_never_automatically_overwrites_partial(self):
        base, g = self.fresh()
        self.enable(base)
        (base/'files/a.txt').write_bytes(b'complete')
        original = g.req
        def partial(method, path='', data=None, headers=None):
            if method == 'PUT':
                g.files[path] = b'part'
                g.writes.append(path)
                raise TimeoutError('upload broke')
            return original(method, path, data, headers)
        g.req = partial
        self.settle(base, g)
        g.req = original
        a.cycle(base, g, now=10000)
        self.assertEqual(len(g.writes), 1)
        self.assertEqual(g.files['Folder/a.txt'], b'part')
        self.assertEqual(a.status(base)['files']['a.txt']['state'], 'blocked')

    def test_scope_auth_safety_and_pause(self):
        base, g = self.fresh()
        with self.assertRaises(ValueError):
            a.enable(base, ['a.txt'], [], authorized=False)
        with self.assertRaises(ValueError):
            self.enable(base, ['../outside'])
        with self.assertRaises(ValueError):
            self.enable(base, ['.env'])
        self.enable(base)
        (base/'files/a.txt').write_text('pending')
        a.pause(base)
        self.settle(base, g)
        self.assertEqual(g.writes, [])
        self.enable(base)
        self.settle(base, g, 200)
        self.assertEqual(g.files['Folder/a.txt'], b'pending')

    def test_local_edit_during_upload_is_not_marked_synced(self):
        base, g = self.fresh()
        self.enable(base)
        (base/'files/a.txt').write_bytes(b'first')
        original = g.req
        def concurrent_edit(method, path='', data=None, headers=None):
            if method == 'PUT':
                (base/'files/a.txt').write_bytes(b'second')
            return original(method, path, data, headers)
        g.req = concurrent_edit
        self.settle(base, g)
        self.assertEqual(g.files['Folder/a.txt'], b'first')
        self.assertEqual((base/'files/a.txt').read_bytes(), b'second')
        self.assertNotEqual(a.status(base)['files']['a.txt']['state'], 'synced')
        g.req = original
        self.settle(base, g, 200)
        self.assertEqual(g.files['Folder/a.txt'], b'second')

    def test_manual_push_excludes_queue_worker_by_controller_lock(self):
        base, g = self.fresh()
        self.enable(base)
        (base/'files/a.txt').write_bytes(b'new')
        with w.controller_lock(base):
            with self.assertRaises(BlockingIOError):
                w.push(g, base, True, w.plan(base)['plan_sha256'])

    def test_credential_failure_is_blocked_not_retried(self):
        base, g = self.fresh()
        self.enable(base)
        def denied(method, path='', data=None, headers=None):
            raise urllib.error.HTTPError(path, 401, 'denied', None, None)
        g.req = denied
        (base/'files/a.txt').write_text('new')
        self.settle(base, g)
        self.assertEqual(a.status(base)['files']['a.txt']['state'], 'blocked')

    def test_credential_recovery_needs_explicit_retry(self):
        base, g = self.fresh()
        self.enable(base)
        original = g.req
        def denied(method, path='', data=None, headers=None):
            raise urllib.error.HTTPError(path, 401, 'denied', None, None)
        g.req = denied
        (base/'files/a.txt').write_text('new')
        self.settle(base, g)
        g.req = original
        a.cycle(base, g, now=1000)
        self.assertEqual(g.writes, [])
        a.retry(base, ['a.txt'])
        a.cycle(base, g, now=1001)
        self.assertEqual(g.files['Folder/a.txt'], b'new')

    def test_restart_after_verified_snapshot_rechecks_remote(self):
        base, g = self.fresh()
        self.enable(base)
        (base/'files/a.txt').write_text('new')
        self.settle(base, g)
        state = a.read_json(base/'autosave/state.json')
        job_id = state['files']['a.txt']['job_id']
        job = a.load_job(base, job_id, 'a.txt')
        job['state'] = 'uploading'
        a.atomic_json(base/'autosave/jobs'/job_id/'job.json', job)
        a.cycle(base, g, now=200)
        self.assertEqual(len(g.writes), 1)
        self.assertEqual(a.status(base)['files']['a.txt']['state'], 'synced')

    def test_quota_blocks_before_upload_and_keeps_source(self):
        from unittest.mock import patch
        base, g = self.fresh()
        self.enable(base)
        (base/'files/a.txt').write_text('new')
        with patch.object(a, 'MAX_RETAINED', 1):
            self.settle(base, g)
        self.assertEqual(g.writes, [])
        self.assertEqual((base/'files/a.txt').read_text(), 'new')
        self.assertEqual(a.status(base)['files']['a.txt']['state'], 'blocked')

    def test_worker_lock_released_without_pid_killing(self):
        base, g = self.fresh()
        self.enable(base)
        with a.worker_lock(base):
            self.assertTrue(a.worker_running(base))
        self.assertFalse(a.worker_running(base))

    def test_extra_snapshot_file_cannot_broaden_authorized_scope(self):
        base, g = self.fresh()
        self.enable(base)
        (base/'files/a.txt').write_text('new')
        original = g.req
        g.req = lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError('offline'))
        self.settle(base, g)
        info = a.read_json(base/'autosave/state.json')['files']['a.txt']
        snapshot = base/'autosave/jobs'/info['job_id']/'snapshot'
        (snapshot/'files/unapproved.txt').write_text('must not be sent')
        g.req = original
        a.cycle(base, g, now=10000)
        self.assertEqual(g.writes, [])
        self.assertEqual(a.status(base)['files']['a.txt']['state'], 'blocked')

    def test_detached_worker_start_pause_and_restart(self):
        from unittest.mock import patch
        base, g = self.fresh()
        self.enable(base)
        environment = {'ICLOUD_GATEWAY_URL': 'https://gateway.example.ts.net',
                       'ICLOUD_GATEWAY_AUTHORIZATION': 'Basic Zml4dHVyZTpwYXNz'}
        try:
            with patch.dict(a.os.environ, environment):
                first = a.start(base)
                self.assertTrue(first['worker_running'])
                self.assertTrue(a.start(base)['worker_running'])
                deadline = time.monotonic()+8
                while not a.status(base)['all_synced'] and time.monotonic() < deadline:
                    time.sleep(.1)
                self.assertTrue(a.status(base)['all_synced'])
                pid = a.status(base)['heartbeat']['pid']
                a.pause(base)
                deadline = time.monotonic()+8
                while a.worker_running(base) and time.monotonic() < deadline:
                    time.sleep(.1)
                self.assertFalse(a.worker_running(base))
                self.enable(base)
                self.assertTrue(a.start(base)['worker_running'])
                deadline = time.monotonic()+8
                while a.status(base)['heartbeat']['pid'] == pid and time.monotonic() < deadline:
                    time.sleep(.1)
                self.assertNotEqual(a.status(base)['heartbeat']['pid'], pid)
        finally:
            a.pause(base)


if __name__ == '__main__':
    unittest.main()
