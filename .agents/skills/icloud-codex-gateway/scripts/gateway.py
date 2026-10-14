#!/usr/bin/env python3
"""Private WebDAV client. No redirect, no delete, no secrets in argv or output."""
import argparse,base64,fnmatch,hashlib,json,os,pathlib,socket,ssl,sys,urllib.request,urllib.parse,urllib.error,uuid,xml.etree.ElementTree as ET
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

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
  self.client=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
 def req(self,method,path='',data=None,headers=None):
  h={'Authorization':self.authorization}
  h.update(headers or {})
  return self.client.open(urllib.request.Request(self.base+relative(path),data=data,headers=h,method=method),timeout=45)
 def listing(self,path='',depth='1'):
  with self.req('PROPFIND',path,data=b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/><d:getcontentlength/><d:getetag/></d:prop></d:propfind>',headers={'Depth':depth,'Content-Type':'application/xml'}) as r:
   if r.status!=207:raise ValueError('Server did not return a WebDAV multistatus')
   data=r.read(4_000_001)
   if len(data)>4_000_000:raise ValueError('Directory response too large; use a narrower path')
  root=ET.fromstring(data)
  return [{'href':n.findtext('{DAV:}href'),'directory':n.find('.//{DAV:}collection') is not None,'bytes':n.findtext('.//{DAV:}getcontentlength')} for n in root.findall('{DAV:}response')]

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
 with g.req('PUT',a.remote,data=b,headers=({'Content-Type':'application/octet-stream'} if existing else {'If-None-Match':'*','Content-Type':'application/octet-stream'})) as r:
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
