#!/usr/bin/env python3
"""Private WebDAV client. No redirect, no delete, no secrets in argv or output."""
import argparse,base64,concurrent.futures,fnmatch,hashlib,json,os,pathlib,socket,ssl,sys,threading,time,urllib.request,urllib.parse,urllib.error,uuid,xml.etree.ElementTree as ET
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

class UploadSessionError(ValueError):
 def __init__(self,state):
  self.state=state.get('state');self.error=state.get('error');self.stage=state.get('stage')
  super().__init__('Resumable upload stopped: '+json.dumps({key:state.get(key) for key in ('upload_id','state','stage','error')}))

def relative(value):
 if value.startswith('/') or any(x in ('..','.') for x in value.split('/')) or '\\' in value or any(ord(x)<32 for x in value):raise ValueError('Use a relative path with no traversal or control characters')
 return urllib.parse.quote(value,safe='/')
class Gateway:
 def __init__(self):
  self.base=os.environ.get('ICLOUD_GATEWAY_URL','').rstrip('/')+'/'
  u=urllib.parse.urlsplit(self.base)
  if u.scheme!='https' or not u.hostname or not u.hostname.endswith('.ts.net') or u.username or u.password or u.query or u.fragment or u.port not in (None,443):raise ValueError('ICLOUD_GATEWAY_URL must be an HTTPS Tailscale hostname on port 443')
  self.user=os.environ.get('ICLOUD_GATEWAY_USER');self.password=os.environ.get('ICLOUD_GATEWAY_PASSWORD')
  self.authorization=os.environ.get('ICLOUD_GATEWAY_AUTHORIZATION')
  if not self.authorization:
   if not self.user or not self.password:raise ValueError('Missing independent gateway credentials')
   self.authorization='Basic '+base64.b64encode((self.user+':'+self.password).encode()).decode()
  self.client=self.new_client()
 def new_client(self):
  return urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
 def req(self,method,path='',data=None,headers=None,_client=None):
  h={'Authorization':self.authorization}
  h.update(headers or {})
  return (_client or self.client).open(urllib.request.Request(self.base+relative(path),data=data,headers=h,method=method),timeout=45)
 def listing(self,path='',depth='1'):
  with self.req('PROPFIND',path,data=b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:getcontentlength/><d:getetag/></d:prop></d:propfind>',headers={'Depth':depth,'Content-Type':'application/xml'}) as r:
   if r.status!=207:raise ValueError('Server did not return a WebDAV multistatus')
   data=r.read(4_000_001)
   if len(data)>4_000_000:raise ValueError('Directory response too large; use a narrower path')
  root=ET.fromstring(data)
  return [{'href':n.findtext('{DAV:}href'),'directory':n.find('.//{DAV:}collection') is not None,'bytes':n.findtext('.//{DAV:}getcontentlength')} for n in root.findall('{DAV:}response')]

 def json_request(self,method,path,value=None):
  data=None if value is None else json.dumps(value,sort_keys=True).encode()
  with self.req(method,path,data=data,headers={'Content-Type':'application/json'}) as response:
   raw=response.read(131073)
   if len(raw)>131072:raise ValueError('Upload status response too large')
   return json.loads(raw)

 def upload(self,remote,payload,expected_sha256=None,headers=None,progress=None,resumable=False):
  """Use bounded application chunks for large bodies; do not alter proxy/CA/VPN."""
  if len(payload)>32*1024*1024:raise ValueError('Upload exceeds this client limit of 32 MiB')
  if len(payload)<=65536 and not resumable:
   with self.req('PUT',remote,data=payload,headers=headers or {'Content-Type':'application/octet-stream'}) as response:
    if response.status not in (200,201,204):raise ValueError('Unexpected upload status')
   return
  prefix='__codex_gateway_v1__/uploads'
  capability=self.json_request('GET',prefix)
  if capability.get('protocol')!='resumable-upload-v1' or capability.get('chunk_bytes')!=32768 or capability.get('max_bytes')!=32*1024*1024:
   raise ValueError('Gateway resumable upload capability unavailable; large upload not started')
  sha=hashlib.sha256(payload).hexdigest()
  intent={'remote':remote,'bytes':len(payload),'sha256':sha,'expected_sha256':expected_sha256}
  intent['upload_id']=str(uuid.uuid5(uuid.NAMESPACE_URL,self.base+json.dumps(intent,sort_keys=True)))
  session=self.json_request('POST',prefix,intent)
  for key,value in intent.items():
   if session.get(key)!=value:raise ValueError('Upload session intent mismatch')
  upload_path=prefix+'/'+intent['upload_id'];chunk_size=capability['chunk_bytes']
  count=(len(payload)+chunk_size-1)//chunk_size;received=session.get('received')
  if not isinstance(received,list) or any(type(i) is not int or not 0<=i<count for i in received):
   raise ValueError('Invalid upload session progress')
  received=set(received);clients=threading.local();completed=len(received)
  def send_chunk(index):
   # Each worker owns its opener; no mutable HTTP handler is shared across threads.
   if not hasattr(clients,'opener'):clients.opener=self.new_client()
   block=payload[index*chunk_size:(index+1)*chunk_size]
   with self.req('PUT',upload_path+'/chunks/'+str(index),data=block,
                 headers={'Content-Type':'application/octet-stream'},_client=clients.opener) as response:
    raw=response.read(4097)
    if len(raw)>4096:raise ValueError('Chunk acknowledgement too large')
    ack=json.loads(raw)
   if ack.get('upload_id')!=intent['upload_id'] or ack.get('index')!=index or ack.get('bytes')!=len(block) or ack.get('sha256')!=hashlib.sha256(block).hexdigest():
    raise ValueError('Chunk acknowledgement mismatch')
  pool=concurrent.futures.ThreadPoolExecutor(max_workers=4)
  futures=[pool.submit(send_chunk,index) for index in range(count) if index not in received]
  try:
   for future in concurrent.futures.as_completed(futures):
    future.result();completed+=1
    if progress and (completed%8==0 or completed==count):
     progress({'phase':'chunks','completed':completed,'total':count,'upload_id':intent['upload_id']})
  except BaseException:
   for future in futures:future.cancel()
   raise
  finally:
   # Let in-flight acknowledgements finish; never start commit after a failed part.
   pool.shutdown(wait=True)
  # An uncertain chunk/commit response is never blindly repeated. The stable ID
  # permits a later user-authorized retry to inspect and reuse durable progress.
  state=self.json_request('POST',upload_path+'/commit',{})
  deadline=time.monotonic()+600;last=None
  while True:
   marker=(state.get('state'),state.get('stage'))
   if progress and marker!=last:
    progress({'phase':'commit','state':marker[0],'stage':marker[1],'upload_id':intent['upload_id']});last=marker
   if state.get('state')=='verified':
    if state.get('sha256')!=sha or state.get('bytes')!=len(payload):raise ValueError('Upload result mismatch')
    return
   if state.get('state') in ('conflict','failed'):
    raise UploadSessionError(state)
   if time.monotonic()>=deadline:raise TimeoutError('Upload still unconfirmed; retained session '+intent['upload_id'])
   time.sleep(2)
   state=self.json_request('GET',upload_path)

def listed_path(g,href):
 u=urllib.parse.urlsplit(href);base=urllib.parse.urlsplit(g.base)
 if u.netloc and u.netloc!=base.netloc:raise ValueError('Listing returned an off-origin path')
 prefix=urllib.parse.unquote(base.path).rstrip('/')+'/'
 path=urllib.parse.unquote(u.path)
 if not path.startswith(prefix):raise ValueError('Listing outside gateway root')
 result=path[len(prefix):].strip('/');relative(result);return result

def search(g,folder,pattern,max_entries=100000,max_directories=10000):
 folder=folder.strip('/');relative(folder);pending=[folder];visited=set();matches=[];count=0
 while pending:
  directory=pending.pop()
  if directory in visited:raise ValueError('Duplicate directory listing')
  visited.add(directory)
  if len(visited)>max_directories:raise ValueError('Search directory limit reached; narrow the folder or explicitly increase the limit')
  for entry in g.listing(directory+'/' if directory else '',depth='1'):
   path=listed_path(g,entry['href'])
   if path==directory:continue
   prefix=directory+'/' if directory else ''
   if not path.startswith(prefix) or '/' in path[len(prefix):]:raise ValueError('Listing escaped requested directory')
   count+=1
   if count>max_entries:raise ValueError('Search entry limit reached; partial results are not presented as complete')
   if fnmatch.fnmatchcase(path.rsplit('/',1)[-1].casefold(),pattern.casefold()):matches.append({'path':path,'directory':entry['directory'],'bytes':entry['bytes']})
   if entry['directory']:pending.append(path)
 return {'folder':folder,'pattern':pattern,'complete':True,'directories_scanned':len(visited),'entries_scanned':count,'matches':sorted(matches,key=lambda x:x['path'])}

def mkdir(g,path,authorized):
 if not authorized:raise ValueError('Explicit user authorization required for this directory')
 path=path.strip('/');relative(path)
 if not path:raise ValueError('An exact non-root directory is required')
 with g.req('MKCOL',path) as r:
  if r.status!=201:raise ValueError('Unexpected directory creation response')
 entries=g.listing(path+'/',depth='0')
 if len(entries)!=1 or not entries[0]['directory'] or listed_path(g,entries[0]['href'])!=path:raise ValueError('Directory verification failed')
 return {'directory':path,'created':True,'verified':True}

def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True)
 s.add_parser('check');l=s.add_parser('list');l.add_argument('path',nargs='?',default='')
 f=s.add_parser('search');f.add_argument('pattern');f.add_argument('--folder',default='');f.add_argument('--max-entries',type=int,default=100000);f.add_argument('--max-directories',type=int,default=10000)
 m=s.add_parser('mkdir');m.add_argument('remote');m.add_argument('--authorized',action='store_true')
 d=s.add_parser('download');d.add_argument('remote');d.add_argument('local',type=pathlib.Path)
 u=s.add_parser('upload');u.add_argument('local',type=pathlib.Path);u.add_argument('remote');u.add_argument('--authorized',action='store_true');u.add_argument('--overwrite-authorized',action='store_true');u.add_argument('--expected-sha256')
 a=p.parse_args();g=Gateway()
 if a.cmd=='check':entries=g.listing(depth='1');print(json.dumps({'authenticated_webdav':'PASS','root_listing_entries':len(entries)}));return
 if a.cmd=='list':print(json.dumps(g.listing(a.path),ensure_ascii=False,indent=2));return
 if a.cmd=='search':print(json.dumps(search(g,a.folder,a.pattern,a.max_entries,a.max_directories),ensure_ascii=False,indent=2));return
 if a.cmd=='mkdir':print(json.dumps(mkdir(g,a.remote,a.authorized),ensure_ascii=False,indent=2));return
 if a.cmd=='download':
  h=hashlib.sha256();n=0
  # Exclusive create prevents accidental overwrites. On failure keep the partial file for inspection.
  with a.local.open('xb') as f:
   os.chmod(a.local,0o600)
   with g.req('GET',a.remote) as r:
    while True:
     b=r.read(1024*1024)
     if not b:break
     f.write(b);h.update(b);n+=len(b)
  print(json.dumps({'bytes':n,'sha256':h.hexdigest(),'path':str(a.local)}));return
 if not a.authorized:raise ValueError('Explicit user authorization required for this exact upload')
 if not a.remote or a.remote.endswith('/'):raise ValueError('An exact file destination is required')
 existing=False
 try:
  with g.req('HEAD',a.remote):pass
 except urllib.error.HTTPError as e:
  if e.code!=404:raise
 else:
  existing=True
  if not a.overwrite_authorized or not a.expected_sha256:raise ValueError('Existing destination requires explicit overwrite authorization and --expected-sha256')
  with g.req('GET',a.remote) as r:old=r.read(32*1024*1024+1)
  if len(old)>32*1024*1024:raise ValueError('Existing file exceeds backup limit')
  if hashlib.sha256(old).hexdigest()!=a.expected_sha256:raise ValueError('Remote version changed; refusing overwrite')
  backup=pathlib.Path.cwd()/'work/gateway-backups'/str(uuid.uuid4())
  backup.mkdir(parents=True,mode=0o700)
  original=backup/'original.bin'
  with original.open('xb') as f:os.chmod(original,0o600);f.write(old)
  print(json.dumps({'previous_version_backup':str(original),'sha256':a.expected_sha256}))
 if a.local.stat().st_size>32*1024*1024:raise ValueError('Upload exceeds this client limit of 32 MiB')
 b=a.local.read_bytes();digest=hashlib.sha256(b).hexdigest()
 upload_headers={'Content-Type':'application/octet-stream'} if existing else {'If-None-Match':'*','Content-Type':'application/octet-stream'}
 if hasattr(g,'upload'):
  g.upload(a.remote,b,a.expected_sha256 if existing else None,headers=upload_headers,
           progress=lambda value:print(json.dumps({'upload_progress':value}),file=sys.stderr,flush=True))
 else:
  with g.req('PUT',a.remote,data=b,headers=upload_headers) as r:
   if r.status not in (200,201,204):raise ValueError('Unexpected upload status')
 h=hashlib.sha256()
 with g.req('GET',a.remote) as r:
  while True:
   part=r.read(1024*1024)
   if not part:break
   h.update(part)
 if h.hexdigest()!=digest:raise ValueError('Uploaded content failed SHA-256 verification')
 print(json.dumps({'upload':'verified','sha256':digest,'bytes':len(b)}))

if __name__=='__main__':
 try:main()
 except urllib.error.HTTPError as e:print(json.dumps({'error':'HTTP','status':e.code}),file=sys.stderr);sys.exit(1)
 except urllib.error.URLError as e:print(json.dumps({'error':'DNS/TLS/network','type':type(e.reason).__name__}),file=sys.stderr);sys.exit(1)
 except (ValueError,OSError,ET.ParseError) as e:print(json.dumps({'error':type(e).__name__,'message':str(e)}),file=sys.stderr);sys.exit(1)
