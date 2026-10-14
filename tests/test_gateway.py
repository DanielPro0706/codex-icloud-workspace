import importlib.util,pathlib,os,io,unittest,uuid,hashlib,contextlib,urllib.error,sys
from unittest.mock import patch
root=pathlib.Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location('gateway',root/'.agents/skills/icloud-codex-gateway/scripts/gateway.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Response(io.BytesIO):status=207
class GatewayTests(unittest.TestCase):
 def test_rejects_nonprivate_or_insecure_endpoints(self):
  for url in ['http://service.ts.net','https://example.com','https://x.ts.net:8443','https://user:pass@x.ts.net']:
   with self.subTest(url=url),patch.dict(os.environ,{'ICLOUD_GATEWAY_URL':url},clear=True):
    with self.assertRaises(ValueError):m.Gateway()
 def test_network_secret_placeholder_passed_unchanged(self):
  with patch.dict(os.environ,{'ICLOUD_GATEWAY_URL':'https://gateway.example.ts.net','ICLOUD_GATEWAY_AUTHORIZATION':'vault-placeholder'},clear=True):g=m.Gateway()
  class Client:
   def open(self,req,timeout):
    assert req.get_header('Authorization')=='vault-placeholder'
    assert req.get_method()=='PROPFIND'
    return Response(b'<d:multistatus xmlns:d="DAV:"><d:response><d:href>/</d:href></d:response></d:multistatus>')
  g.client=Client();self.assertEqual(g.listing(depth='0')[0]['href'],'/')
 def test_paths_cannot_escape_base(self):
  for x in ['../file','a/../../file','/file','a\\file','x\n']:
   with self.assertRaises(ValueError):m.relative(x)
  self.assertEqual(m.relative('a b/c'),'a%20b/c')

 def test_upload_authorization_and_stale_version_guards(self):
  folder=root/'work/gateway-client-tests'/str(uuid.uuid4());folder.mkdir(parents=True)
  source=folder/'source.bin';source.write_bytes(b'new content')
  class Fake:
   data=b'original content'
   writes=0
   def req(self,method,path='',data=None,headers=None):
    if method=='PUT':self.data=data;self.writes+=1
    response=io.BytesIO(self.data if method=='GET' else b'');response.status=201 if method=='PUT' else 200;return response
  fake=Fake();previous=pathlib.Path.cwd();os.chdir(folder)
  try:
   cases=[[],['--authorized'],['--authorized','--overwrite-authorized','--expected-sha256','0'*64]]
   for flags in cases:
    with patch.object(m,'Gateway',return_value=fake),patch.object(sys,'argv',['gateway.py','upload',str(source.resolve()),'doc.txt']+flags):
     with self.assertRaises(ValueError):m.main()
    self.assertEqual(fake.writes,0)
   expected=hashlib.sha256(fake.data).hexdigest();output=io.StringIO()
   with patch.object(m,'Gateway',return_value=fake),patch.object(sys,'argv',['gateway.py','upload',str(source.resolve()),'doc.txt','--authorized','--overwrite-authorized','--expected-sha256',expected]),contextlib.redirect_stdout(output):m.main()
   self.assertEqual(fake.data,b'new content');self.assertEqual(fake.writes,1)
   backups=list(folder.glob('work/gateway-backups/*/original.bin'));self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),b'original content')
  finally:os.chdir(previous)

if __name__=='__main__':unittest.main()
