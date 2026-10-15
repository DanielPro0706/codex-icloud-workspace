#!/usr/bin/env python3
"""Private, authenticated folder selection for future Cloud tasks. Python 3.6+."""
import base64,datetime,hmac,json,os,pathlib,threading,uuid,urllib.request,urllib.parse,urllib.error,xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler,HTTPServer
from socketserver import ThreadingMixIn
from notifications import NotificationStore
from uploads import UploadStore,WebDAVBackend,handle as handle_upload
ORIGIN='https://gateway.example.ts.net'
STATE=pathlib.Path(os.environ.get('STATE_DIRECTORY','/var/lib/icloud-gateway-picker'))/'selection.json'
AUTH='Basic '+base64.b64encode((os.environ['RCLONE_USER']+':'+os.environ['RCLONE_PASS']).encode()).decode()
LOCK=threading.Lock()
NOTIFICATIONS=NotificationStore(STATE.parent,os.environ.get('ICLOUD_WEBPUSH_HELPER','/opt/icloud-gateway/ui/webpush-helper'))
ASSETS=pathlib.Path(__file__).resolve().parent
UPLOADS=UploadStore(STATE.parent/'uploads',WebDAVBackend(AUTH))

def current():
 if STATE.exists():return json.loads(STATE.read_text())
 return {'selected':False,'folder':None,'revision':None}

def canonical(folder):
 if not isinstance(folder,str):raise ValueError('folder must be a string')
 folder=folder.strip('/')
 if any(c in folder for c in ['\\','\x00','\n','\r']) or any(p in ('.','..') for p in folder.split('/')):raise ValueError('invalid folder path')
 return folder

def validate_folder(folder):
 url='http://127.0.0.1:18765/'+urllib.parse.quote(folder,safe='/')+'/'
 request=urllib.request.Request(url,method='PROPFIND',headers={'Authorization':AUTH,'Depth':'0'})
 with urllib.request.urlopen(request,timeout=30) as r:
  if r.status!=207:raise ValueError('directory validation failed')
  data=r.read(1_000_001)
  if len(data)>1_000_000:raise ValueError('response too large')
  if ET.fromstring(data).find('.//{DAV:}collection') is None:raise ValueError('path is not a directory')

class Handler(BaseHTTPRequestHandler):
 server_version='PrivateWorkspace'
 def log_message(self,*args):pass
 def reply(self,code,data):
  b=json.dumps(data,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(b)
 def route(self):
  path=urllib.parse.urlsplit(self.path).path
  prefix='/__codex_gateway_v1__/'
  return '/'+path[len(prefix):] if path.startswith(prefix) else path
 def asset(self):
  path=self.route()
  names={'/sw.js':('sw.js','application/javascript'),'/manifest.webmanifest':('manifest.webmanifest','application/manifest+json'),'/icon.svg':('icon.svg','image/svg+xml')}
  if path not in names:return False
  name,content_type=names[path];b=(ASSETS/name).read_bytes();self.send_response(200);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-cache');self.send_header('X-Content-Type-Options','nosniff')
  if path=='/sw.js':self.send_header('Service-Worker-Allowed','/')
  self.end_headers();self.wfile.write(b);return True
 def allowed(self):
  if not hmac.compare_digest(self.headers.get('Authorization','').encode('utf-8'),AUTH.encode('ascii')):
   self.send_response(401);self.send_header('WWW-Authenticate','Basic realm=""');self.send_header('Content-Length','0');self.end_headers();return False
  if self.route() not in ['/selection','/notifications','/notifications/config','/notifications/status','/notifications/subscribe','/notifications/unsubscribe','/notifications/test','/health-event','/uploads'] and not self.route().startswith('/uploads/'):
   self.reply(404,{'error':'not found'});return False
  return True
 def do_GET(self):
  if self.asset():return
  if not self.allowed():return
  if handle_upload(self,UPLOADS):return
  try:
   route=self.route()
   if route=='/selection':
    with LOCK:self.reply(200,current())
   elif route=='/notifications':
    b=(ASSETS/'notifications.html').read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(b)))
    for key,value in json.loads((ASSETS/'notification-headers.json').read_text()).items():self.send_header(key,value)
    self.end_headers();self.wfile.write(b)
   elif route=='/notifications/config':self.reply(200,NOTIFICATIONS.config())
   elif route=='/notifications/status':self.reply(200,NOTIFICATIONS.status())
   else:self.reply(405,{'error':'POST required'})
  except Exception as e:self.reply(503,{'error':type(e).__name__})
 def do_POST(self):
  if not self.allowed():return
  if handle_upload(self,UPLOADS):return
  origin=self.headers.get('Origin')
  if origin and origin!=ORIGIN:self.reply(403,{'error':'wrong origin'});return
  if self.headers.get('Content-Type','').split(';')[0]!='application/json':self.reply(415,{'error':'JSON required'});return
  try:
   length=int(self.headers.get('Content-Length','0'))
   if not 0<length<=4096:raise ValueError('invalid request size')
   body=json.loads(self.rfile.read(length));route=self.route()
   if route=='/notifications/subscribe':self.reply(200,NOTIFICATIONS.subscribe(body.get('subscription')));return
   if route=='/notifications/unsubscribe':self.reply(200,NOTIFICATIONS.unsubscribe(body.get('id')));return
   if route=='/notifications/test':self.reply(202,NOTIFICATIONS.test());return
   if route=='/health-event':self.reply(202,NOTIFICATIONS.health(body.get('status'),body.get('checked_at'),body.get('mail')));return
   if route!='/selection':self.reply(405,{'error':'GET required'});return
   folder=body.get('folder')
   if 'expected_revision' not in body:raise ValueError('expected_revision required')
   if folder is not None:folder=canonical(folder);validate_folder(folder)
   with LOCK:
    old=current()
    if body['expected_revision']!=old.get('revision'):self.reply(409,{'error':'selection changed; reload and choose again'});return
    new={'selected':folder is not None,'folder':folder,'revision':str(uuid.uuid4()),'updated_at':datetime.datetime.utcnow().isoformat()+'Z'}
    STATE.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    tmp=STATE.with_name('selection-'+new['revision']+'.tmp')
    with tmp.open('x') as f:os.chmod(str(tmp),0o600);json.dump(new,f,ensure_ascii=False)
    os.replace(str(tmp),str(STATE));self.reply(200,new)
  except urllib.error.HTTPError as e:self.reply(502,{'error':'iCloud directory validation failed','upstream_status':e.code})
  except (ValueError,KeyError):self.reply(400,{'error':'invalid selection request'})
  except Exception as e:self.reply(503,{'error':type(e).__name__})
 def do_PUT(self):
  if not self.allowed():return
  if not handle_upload(self,UPLOADS):self.reply(405,{'error':'method not allowed'})
 def do_OPTIONS(self):self.reply(403,{'error':'cross-origin access disabled'})
class Server(ThreadingMixIn,HTTPServer):daemon_threads=True
if __name__=='__main__':
 if os.environ.get('ICLOUD_BROWSER_IDENTITY')=='1':
  from browser_proxy import start as start_browser_proxy
  browser_proxy=start_browser_proxy(STATE.parent,AUTH)
 Server(('127.0.0.1',18767),Handler).serve_forever()
