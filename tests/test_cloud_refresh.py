import importlib.util,pathlib,sys,unittest,subprocess
from types import SimpleNamespace
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('cloud_refresh',ROOT/'scripts/cloud_refresh.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class RefreshDiagnosticsTests(unittest.TestCase):
 def test_fetch_timeout_is_bounded_and_redacts_partial_output(self):
  error=subprocess.TimeoutExpired(['git','fetch','origin','main'],60,output='PRIVATE_SENTINEL',stderr='credential=PRIVATE_SENTINEL')
  with patch.object(m.subprocess,'run',side_effect=error) as call:
   with self.assertRaises(SystemExit) as raised:m.run('git','fetch','origin','main')
  self.assertEqual(call.call_args.kwargs['timeout'],60)
  self.assertIn('network-path-unavailable',str(raised.exception))
  self.assertNotIn('PRIVATE_SENTINEL',str(raised.exception))

 def test_changed_origin_stops_before_fetch(self):
  with patch.object(m,'run',return_value='https://example.invalid/another.git') as call:
   with self.assertRaises(SystemExit):m.main()
  self.assertEqual(call.call_args_list,[unittest.mock.call('git','remote','get-url','origin')])

 def failed(self,stderr):
  result=SimpleNamespace(returncode=128,stdout='',stderr=stderr)
  with patch.object(m.subprocess,'run',return_value=result):
   with self.assertRaises(SystemExit) as raised:m.run('git','fetch','origin','main')
  return str(raised.exception)

 def test_proxy_failure_requests_runtime_network_path_without_leaking_url(self):
  message=self.failed('fatal: unable to access https://owner:FAKE_PASSWORD@example.invalid/repo: Failed to connect to proxy port 8080: Could not connect to server')
  self.assertIn('git fetch',message);self.assertIn('exit 128',message)
  self.assertIn('network-path-unavailable',message);self.assertIn('authorized network execution',message)
  self.assertNotIn('FAKE_PASSWORD',message);self.assertNotIn('example.invalid',message)

 def test_authentication_failure_is_not_reported_as_network_retry(self):
  message=self.failed('fatal: Authentication failed for https://owner:FAKE_PASSWORD@example.invalid/repo')
  self.assertIn('authentication',message);self.assertNotIn('Retry',message)
  self.assertNotIn('FAKE_PASSWORD',message)

 def test_readonly_failure_does_not_suggest_network_escalation(self):
  message=self.failed('fatal: cannot open .git/FETCH_HEAD: Read-only file system')
  self.assertIn('filesystem-permission',message);self.assertNotIn('Retry',message)

if __name__=='__main__':unittest.main()
