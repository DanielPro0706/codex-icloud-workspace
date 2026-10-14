import importlib.util,pathlib,sys,unittest,unittest.mock as mock,json
root=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('icloud_gateway_mail',root/'gateway-runtime/mail_notify.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);sys.modules['icloud_gateway_mail']=m
spec=importlib.util.spec_from_file_location('health',root/'gateway-runtime/health.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
class MailAlertTests(unittest.TestCase):
 def setUp(self):
  self.enabled=mock.patch.object(m,"ENABLED",True);self.enabled.start();self.addCleanup(self.enabled.stop)
  self.recipient=mock.patch.object(m,"RECIPIENT","owner@example.test");self.recipient.start();self.addCleanup(self.recipient.stop)
 def test_no_enrollment_never_invokes_mail_cli(self):
  with mock.patch.object(m,"ENABLED",False), mock.patch.object(m,"run") as call:
   self.assertEqual(m.notify("REAUTH_REQUIRED"),{"status":"not_configured"})
   self.assertEqual(m.send("TEST"),(False,"not_configured"));call.assert_not_called()
 def test_exact_pre_authorized_recipient_and_identical_confirmation_arguments(self):
  calls=[]
  def cli(args):
   calls.append(args)
   return (8,{'data':{'confirmation_token':'ctk_fixture'}}) if len(calls)==1 else (0,{'ok':True,'data':{'sent':True}})
  with mock.patch.object(m,'run',side_effect=cli):self.assertEqual(m.send('REAUTH_REQUIRED'),(True,'accepted'))
  self.assertEqual(calls[0][calls[0].index('--to')+1],'owner@example.test');self.assertEqual(calls[1],calls[0]+['--confirmation-token','ctk_fixture'])
  self.assertNotIn('--attachment',calls[0])
  with self.assertRaises(ValueError):m.send('arbitrary-message')
 def test_missing_confirmation_and_auth_failure_never_report_delivery(self):
  with mock.patch.object(m,'run',return_value=(8,{'ok':False})):self.assertEqual(m.send('TEST'),(False,'failed'))
  with mock.patch.object(m,'run',return_value=(3,{'ok':False})):self.assertEqual(m.send('TEST'),(False,'auth_pending'))
 def test_read_health_classification_without_raw_errors(self):
  self.assertEqual(h.classify(0,''),'OK');self.assertEqual(h.classify(1,'invalid session token'),'REAUTH_REQUIRED')
  self.assertEqual(h.classify(1,'HTTP 412: data access on web disabled'),'APPLE_WEB_ACCESS_DISABLED')
  self.assertEqual(h.classify(1,'HTTP 302 domainToUse iCloud.com.cn'),'REGION_INCOMPATIBLE')
  self.assertEqual(h.classify(1,'temporary upstream failure'),'CHECK_FAILED')
if __name__=='__main__':unittest.main()
