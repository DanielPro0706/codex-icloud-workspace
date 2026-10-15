import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import test_workspace as fixtures
import workspace as w


class RecoveryTests(unittest.TestCase):
 def fresh(self):return fixtures.WorkspaceTests.fresh(self)
 def test_lost_put_response_is_recovered_by_hash_without_second_put(self):
  base, gateway = self.fresh()
  (base/'files/new.bin').write_bytes(b'completed upload')
  original = gateway.req
  def lost_response(method, path='', data=None, headers=None):
   response = original(method, path, data, headers)
   if method == 'PUT':
    raise TimeoutError('The read operation timed out')
   return response
  gateway.req = lost_response
  plan = w.plan(base)
  with self.assertRaises(w.WritebackError) as caught:
   w.push(gateway, base, True, plan['plan_sha256'])
  self.assertEqual(caught.exception.stage, 'upload')
  self.assertEqual(caught.exception.path, 'new.bin')
  self.assertEqual(len(gateway.writes), 1)
  gateway.req = original
  result = w.push(gateway, base, True, w.plan(base)['plan_sha256'])
  self.assertEqual(len(gateway.writes), 1)
  self.assertTrue(result['applied'][0]['recovered'])
  self.assertEqual(w.plan(base)['changes'], [])
  self.assertTrue(list((base/'writeback-journal').glob('*.jsonl')))

 def test_partial_remote_is_preserved_and_never_treated_as_complete(self):
  base, gateway = self.fresh()
  (base/'files/new.bin').write_bytes(b'complete')
  original = gateway.req
  def partial(method, path='', data=None, headers=None):
   if method == 'PUT':
    gateway.files[path] = b''
    gateway.writes.append(path)
    raise TimeoutError('The read operation timed out')
   return original(method, path, data, headers)
  gateway.req = partial
  with self.assertRaises(w.WritebackError):
   w.push(gateway, base, True, w.plan(base)['plan_sha256'])
  gateway.req = original
  with self.assertRaisesRegex(ValueError, 'Remote conflict'):
   w.push(gateway, base, True, w.plan(base)['plan_sha256'])
  self.assertEqual(len(gateway.writes), 1)
  self.assertEqual(gateway.files['Folder/new.bin'], b'')
  self.assertEqual((base/'files/new.bin').read_bytes(), b'complete')
  self.assertTrue(list((base/'remote-backups').glob('*/new.bin')))

 def test_readback_timeout_reports_stage_and_recovers_completed_file(self):
  base, gateway = self.fresh()
  (base/'files/new.bin').write_bytes(b'complete')
  original = gateway.req
  def failed_readback(method, path='', data=None, headers=None):
   if method == 'GET' and path == 'Folder/new.bin' and gateway.writes:
    raise TimeoutError('read timed out')
   return original(method, path, data, headers)
  gateway.req = failed_readback
  with self.assertRaises(w.WritebackError) as caught:
   w.push(gateway, base, True, w.plan(base)['plan_sha256'])
  self.assertEqual(caught.exception.stage, 'verify')
  gateway.req = original
  w.push(gateway, base, True, w.plan(base)['plan_sha256'])
  self.assertEqual(len(gateway.writes), 1)
  self.assertEqual(w.plan(base)['changes'], [])

 def test_resumable_commit_progress_is_retained_in_journal(self):
  base, gateway = self.fresh()
  (base/'files/new.bin').write_bytes(b'x'*7000)
  def upload(remote, payload, expected_sha256=None, progress=None):
   progress({'phase':'commit','state':'committing','stage':'upload','upload_id':'fixture'})
   gateway.req('PUT', remote, payload)
  gateway.upload = upload
  result = w.push(gateway, base, True, w.plan(base)['plan_sha256'])
  events = [json.loads(line) for line in pathlib.Path(result['journal']).read_text().splitlines()]
  self.assertTrue(any(event.get('progress', {}).get('stage') == 'upload' for event in events))


if __name__ == '__main__':
 unittest.main()
