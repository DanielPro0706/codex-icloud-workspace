import importlib.util,pathlib,struct,base64,unittest
root=pathlib.Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location('phone',root/'gateway-runtime/register_phone_key.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class PhoneKeyTests(unittest.TestCase):
 def key(self,extra=b''):
  algorithm=b'ssh-ed25519';blob=struct.pack('>I',len(algorithm))+algorithm+struct.pack('>I',32)+b'a'*32+extra
  return 'ssh-ed25519 '+base64.b64encode(blob).decode()
 def test_public_key_validation_and_fingerprint_without_private_material(self):
  key,fingerprint=m.parse_public_key(self.key()+' phone owner');self.assertEqual(key,self.key());self.assertTrue(fingerprint.startswith('SHA256:'))
  for text in ['-----BEGIN OPENSSH PRIVATE KEY-----','ssh-rsa AAAA',self.key(b'extra'),'ssh-ed25519 ????']:
   with self.assertRaises(ValueError):m.parse_public_key(text)
if __name__=='__main__':unittest.main()
