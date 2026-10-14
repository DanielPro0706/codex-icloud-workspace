import pathlib,sys,unittest,uuid,unittest.mock as mock,types,json,base64
root=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'gateway-ui'));import notifications as n
class NotificationTests(unittest.TestCase):
 def store(self):return n.NotificationStore(root/'work/notification-tests'/str(uuid.uuid4()),'/fake-helper')
 def subscription(self,endpoint='https://web.push.apple.com/test'):
  enc=lambda b:base64.urlsafe_b64encode(b).decode().rstrip('=')
  return {'endpoint':endpoint,'keys':{'p256dh':enc(b'\x04'+b'a'*64),'auth':enc(b'a'*16)}}
 def test_provider_validation_and_expired_records_are_retained(self):
  s=self.store()
  for url in ['http://web.push.apple.com/test','https://web.push.apple.com.invalid/test','https://localhost/test','https://web.push.apple.com:8443/test']:
   with self.assertRaises(ValueError):s.subscribe(self.subscription(url))
  registered=s.subscribe(self.subscription());s.unsubscribe(registered['id']);self.assertEqual(s.status()['registered_devices'],0)
  self.assertIn(registered['id'],s.load()['subscriptions'])
 def test_health_deduplication_and_recovery_only_after_failure(self):
  s=self.store();sent=[];s.start=lambda event,msg:sent.append((event,msg))
  s.health('OK','first');self.assertEqual(sent,[])
  s.health('REAUTH_REQUIRED','second');s.health('REAUTH_REQUIRED','third');self.assertEqual(sent[0][0],sent[1][0])
  s.health('OK','fourth');self.assertNotEqual(sent[1][0],sent[2][0]);self.assertIn('已恢复',sent[2][1]['title'])
  with self.assertRaises(ValueError):s.health('unknown','x')
  with self.assertRaises(ValueError):s.health('OK','x',{'status':'raw-token'})
 def test_push_acceptance_never_claims_device_receipt_and_410_disables_without_delete(self):
  s=self.store();ident=s.subscribe(self.subscription())['id'];s.keys=lambda:{'public_key':'fixture-public','private_key':'fixture-private'}
  with mock.patch.object(n.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout=json.dumps({'sent':True,'status':201}))):s.send('event-one',n.payload('REAUTH_REQUIRED'),[ident])
  self.assertEqual(s.load()['subscriptions'][ident]['last_event'],'event-one');self.assertEqual(s.status()['last_push']['accepted_by_push_service'],1)
  self.assertNotIn('received',s.status()['last_push'])
  with mock.patch.object(n.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout=json.dumps({'sent':False,'status':410}))):s.send('event-two',n.payload('OK'),[ident])
  self.assertIn(ident,s.load()['subscriptions']);self.assertFalse(s.load()['subscriptions'][ident]['enabled'])
if __name__=='__main__':unittest.main()
