import base64,email.message,hashlib,http.client,importlib.util,pathlib,socketserver,threading,unittest
from http.server import BaseHTTPRequestHandler,HTTPServer

p=pathlib.Path(__file__).resolve().parents[1]/'gateway-ui/browser_proxy.py'
spec=importlib.util.spec_from_file_location('browser_proxy_test_module',p)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
BASIC='Basic '+base64.b64encode(b'fixture:synthetic-password').decode()
OWNER='owner@example.invalid'
def headers(**values):
 h=email.message.Message()
 for key,value in values.items():h[key.replace('_','-')]=value
 return h

class PolicyTests(unittest.TestCase):
 def test_owner_browser_does_not_need_basic(self):
  h=headers(Tailscale_User_Login=OWNER)
  self.assertEqual(m.mode('GET','/',h,OWNER,BASIC,True),'owner')
  self.assertEqual(m.mode('GET','/',h,OWNER,BASIC,False),'unauthorized')
 def test_other_identity_and_tagged_client_need_basic(self):
  for h in [headers(),headers(Tailscale_User_Login='other@example.invalid')]:
   self.assertEqual(m.mode('GET','/',h,OWNER,BASIC,True),'unauthorized')
   h['Authorization']=BASIC
   self.assertEqual(m.mode('PROPFIND','/',h,OWNER,BASIC,True),'basic')
 def test_browser_identity_cannot_write_webdav_or_health(self):
  h=headers(Tailscale_User_Login=OWNER,Origin=m.ORIGIN)
  for method,path in [('PUT','/file'),('DELETE','/file'),('PROPFIND','/'),('POST',m.PREFIX+'/health-event')]:
   self.assertEqual(m.mode(method,path,h,OWNER,BASIC,True),'unauthorized')
  self.assertEqual(m.mode('POST',m.PREFIX+'/selection',h,OWNER,BASIC,True),'owner')
  del h['Origin']
  self.assertEqual(m.mode('POST',m.PREFIX+'/selection',h,OWNER,BASIC,True),'unauthorized')
 def test_cross_origin_and_duplicate_identity_are_refused(self):
  h=headers(Tailscale_User_Login=OWNER,Origin='https://other.example.invalid',Authorization=BASIC)
  self.assertEqual(m.mode('GET','/',h,OWNER,BASIC,True),'forbidden')
  del h['Origin'];h['Tailscale-User-Login']=OWNER;del h['Authorization']
  self.assertEqual(m.mode('GET','/',h,OWNER,BASIC,True),'unauthorized')
 def test_passive_cross_site_reads_are_refused(self):
  h=headers(Tailscale_User_Login=OWNER,Sec_Fetch_Site='cross-site')
  self.assertEqual(m.mode('GET','/',h,OWNER,BASIC,True),'forbidden')
  h['Sec-Fetch-Mode']='navigate';h['Sec-Fetch-User']='?1'
  self.assertEqual(m.mode('GET','/',h,OWNER,BASIC,True),'owner')

class Backend(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_PUT(self):
  if self.headers.get('Transfer-Encoding')=='chunked':
   parts=[]
   while True:
    length=int(self.rfile.readline().strip(),16)
    if not length:self.rfile.readline();break
    parts.append(self.rfile.read(length));self.rfile.read(2)
   data=b''.join(parts)
  else:data=self.rfile.read(int(self.headers.get('Content-Length','0')))
  self.server.payload=data;self.server.auth=self.headers.get('Authorization');self.server.seen_path=self.path
  self.server.content_type=self.headers.get('Content-Type');self.server.origin=self.headers.get('Origin')
  self.send_response(201);self.send_header('Content-Length','0');self.end_headers()
 do_POST=do_PUT
 def do_GET(self):
  self.server.seen_path=self.path
  self.send_response(200);self.send_header('Transfer-Encoding','chunked');self.send_header('Access-Control-Allow-Origin','*');self.end_headers()
  for b in [b'chunked ',b'response']:
   self.wfile.write(('%x\r\n'%len(b)).encode()+b+b'\r\n')
  self.wfile.write(b'0\r\n\r\n')
 def do_OPTIONS(self):
  self.send_response(204);self.send_header('DAV','1,2');self.send_header('Content-Length','0');self.end_headers()

class Front(socketserver.ThreadingMixIn,HTTPServer):daemon_threads=True
class StreamTests(unittest.TestCase):
 def setUp(self):
  self.backend=HTTPServer(('127.0.0.1',0),Backend)
  self.front=Front(('127.0.0.1',0),m.Handler)
  self.front.owner,self.front.basic=OWNER,BASIC
  self.front.webdav_port=self.front.picker_port=self.backend.server_port
  self.front.trusted_peer=lambda connection:True
  for s in [self.backend,self.front]:threading.Thread(target=s.serve_forever,daemon=True).start()
 def tearDown(self):
  for s in [self.front,self.backend]:s.shutdown();s.server_close()
 def connect(self):return http.client.HTTPConnection('127.0.0.1',self.front.server_port,timeout=5)
 def test_large_basic_upload_preserves_bytes_and_headers(self):
  payload=b'fixture data\n'*250000;c=self.connect()
  c.request('PUT','/scope/file?x=1',payload,{'Authorization':BASIC,'Connection':'Content-Length'})
  self.assertEqual(c.getresponse().status,201);c.close()
  self.assertEqual(hashlib.sha256(self.backend.payload).digest(),hashlib.sha256(payload).digest())
  self.assertEqual(self.backend.auth,BASIC);self.assertEqual(self.backend.seen_path,'/scope/file?x=1')
 def test_chunked_upload_and_response_preserve_data(self):
  c=self.connect();c.request('PUT','/file',iter([b'first',b'second']),{'Authorization':BASIC},encode_chunked=True)
  self.assertEqual(c.getresponse().status,201);c.close();self.assertEqual(self.backend.payload,b'firstsecond')
  c=self.connect();c.request('GET','/',headers={'Tailscale-User-Login':OWNER});r=c.getresponse()
  self.assertEqual(r.read(),b'chunked response');self.assertIsNone(r.getheader('Transfer-Encoding'));self.assertIsNone(r.getheader('Access-Control-Allow-Origin'));c.close()
 def test_framing_conflict_is_refused_before_backend_write(self):
  c=self.connect();c.putrequest('PUT','/file');c.putheader('Authorization',BASIC);c.putheader('Content-Length','1');c.putheader('Transfer-Encoding','chunked');c.endheaders()
  self.assertEqual(c.getresponse().status,400);c.close();self.assertFalse(hasattr(self.backend,'payload'))
 def test_owner_post_retains_picker_route_and_payload(self):
  body=b'{"folder":"synthetic","expected_revision":"fixture"}'
  c=self.connect();c.request('POST',m.PREFIX+'/selection',body,{'Tailscale-User-Login':OWNER,'Origin':m.ORIGIN,'Content-Type':'application/json'});r=c.getresponse();self.assertEqual(r.status,201);r.read();c.close()
  self.assertEqual(self.backend.seen_path,m.PREFIX+'/selection');self.assertEqual(self.backend.payload,body)
  self.assertEqual(self.backend.content_type,'application/json');self.assertEqual(self.backend.origin,m.ORIGIN)
 def test_basic_dav_options_work_but_browser_preflight_is_refused(self):
  c=self.connect();c.request('OPTIONS','/',headers={'Authorization':BASIC});r=c.getresponse();self.assertEqual(r.status,204);self.assertEqual(r.getheader('DAV'),'1,2');r.read();c.close()
  c=self.connect();c.request('OPTIONS','/',headers={'Authorization':BASIC,'Origin':m.ORIGIN});r=c.getresponse();self.assertEqual(r.status,403);r.read();c.close()

if __name__=='__main__':unittest.main()
