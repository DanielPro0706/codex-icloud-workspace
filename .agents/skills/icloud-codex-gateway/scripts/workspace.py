#!/usr/bin/env python3
"""Scoped iCloud folder checkout, local changes, conflict-checked writeback. No FUSE."""
import argparse,contextlib,fcntl,functools,hashlib,json,os,pathlib,sys,time,urllib.error,urllib.parse,uuid
from gateway import Gateway,relative
P=pathlib.Path
SKIP_DIR={'.git','node_modules','__pycache__','.cache'}
SENSITIVE={'auth.json','rclone.conf','rclone-cn.conf','id_rsa','id_ed25519'}
def digest(b):return hashlib.sha256(b).hexdigest()

@contextlib.contextmanager
def controller_lock(base):
 """Serialize writers to a controller; this does not lock other iCloud devices."""
 base.mkdir(parents=True,exist_ok=True,mode=0o700)
 fd=os.open(base/'writeback.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  yield
 finally:os.close(fd)

def locked_workspace(fn):
 @functools.wraps(fn)
 def wrapped(g,base,*args,**kwargs):
  with controller_lock(base):return fn(g,base,*args,**kwargs)
 return wrapped
def canonical(s):
 s=s.strip('/')
 relative(s)
 if '://' in s:raise ValueError('Expected a relative iCloud folder')
 return s

def safe_file_name(s):
 name=P(s).name
 if name in SENSITIVE or name=='.env' or name.startswith('.env.') or name.endswith(('.pem','.key')):
  raise ValueError('Credential/runtime file requires separate handling: '+s)

def join(root,rel):return '/'.join(x for x in (root,rel) if x)
def href_path(g,href):
 u=urllib.parse.urlsplit(href);base=urllib.parse.urlsplit(g.base)
 if u.netloc and u.netloc!=base.netloc:raise ValueError('Server returned an off-origin path')
 prefix=urllib.parse.unquote(base.path).rstrip('/')+'/'
 decoded=urllib.parse.unquote(u.path)
 if not decoded.startswith(prefix):raise ValueError('Server path outside gateway root')
 return canonical(decoded[len(prefix):])
def list_tree(g,folder,max_files,max_bytes):
 pending=[folder];seen=set();files={};dirs=set();excluded=[];total=0
 while pending:
  directory=pending.pop()
  if directory in seen:raise ValueError('Duplicate/cyclic remote folder')
  seen.add(directory)
  if len(seen)>max_files:raise ValueError('Folder scan limit reached; choose a smaller scope')
  for item in g.listing(directory+'/' if directory else '',depth='1'):
   remote=href_path(g,item['href'])
   if remote==directory:continue
   if not remote.startswith(directory+'/' if directory else ''):raise ValueError('Listing escaped requested folder')
   tail=remote[len(directory)+1:] if directory else remote
   if '/' in tail:raise ValueError('Unexpected recursive directory response')
   rel=remote[len(folder)+1:] if folder else remote
   if item['directory']:
    if tail in SKIP_DIR:excluded.append(rel+'/');continue
    dirs.add(rel);pending.append(remote)
   else:
    if tail=='.DS_Store':excluded.append(rel);continue
    safe_file_name(rel)
    size=int(item['bytes'] or 0);total+=size
    if len(files)>=max_files or total>max_bytes:raise ValueError('Checkout exceeds limits; choose a smaller folder or explicitly increase limits')
    files[rel]={'bytes':size}
 return files,dirs,excluded

def download(g,remote,target,limit):
 target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);h=hashlib.sha256();n=0
 with target.open('xb') as f:
  os.chmod(target,0o600)
  with g.req('GET',remote) as response:
   while True:
    b=response.read(1024*1024)
    if not b:break
    n+=len(b)
    if n>limit:raise ValueError('Download exceeded approved byte limit')
    f.write(b);h.update(b)
 return {'sha256':h.hexdigest(),'bytes':n}

def save_state(base,state):
 p=base/'manifest.json';stamp=str(time.time_ns())
 if p.exists():
  backup=base/'manifest-backups';backup.mkdir(mode=0o700,exist_ok=True)
  (backup/(stamp+'.json')).write_bytes(p.read_bytes())
 temp=base/('manifest-'+stamp+'.tmp')
 with temp.open('x') as f:
  os.chmod(temp,0o600);json.dump(state,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
 os.replace(temp,p)
 fd=os.open(base,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)

def open_workspace(g,folder,base,max_files,max_bytes):
 folder=canonical(folder);base=base.resolve()
 if (base/'manifest.json').exists():
  state=load_state(base)
  if state['remote_folder']!=folder:raise ValueError('Existing workspace belongs to another folder')
  g.listing(folder+'/' if folder else '',depth='0')
  return {'controller':str(base),'workspace':str(base/'files'),'mode':'checkout-and-writeback','reused':True,'files':len(state['files'])}
 if base.exists() and any(base.iterdir()):raise ValueError('Destination is not empty; preserve it and choose another workspace')
 files,dirs,excluded=list_tree(g,folder,max_files,max_bytes)
 base.mkdir(parents=True,exist_ok=True,mode=0o700);(base/'files').mkdir(mode=0o700,exist_ok=True)
 for d in sorted(dirs):(base/'files'/d).mkdir(parents=True,exist_ok=True,mode=0o700)
 state={'version':1,'remote_folder':folder,'files':{},'excluded':excluded,'max_bytes':max_bytes}
 used=0
 for rel in sorted(files):
  info=download(g,join(folder,rel),base/'files'/rel,max_bytes-used);used+=info['bytes'];state['files'][rel]=info
 save_state(base,state)
 return {'controller':str(base),'workspace':str(base/'files'),'mode':'checkout-and-writeback','files':len(files),'bytes':used,'excluded':excluded}

def load_state(base):
 state_path=base/'manifest.json'
 if state_path.is_symlink():raise ValueError('Symlinked state is not supported')
 s=json.loads(state_path.read_text());canonical(s['remote_folder'])
 for rel in s['files']:
  if canonical(rel)!=rel or not rel:raise ValueError('Unsafe manifest file path')
 return s

def plan(base):
 s=load_state(base);root=base/'files';local={}
 for directory,dirs,names in os.walk(root,followlinks=False):
  for d in dirs:
   if (P(directory)/d).is_symlink():raise ValueError('Symlinked workspace directories are not uploaded')
  dirs[:]=[d for d in dirs if d not in SKIP_DIR]
  for name in names:
   if name=='.DS_Store':continue
   p=P(directory)/name
   if p.is_symlink():raise ValueError('Symlinked files are not uploaded')
   rel=str(p.relative_to(root));safe_file_name(rel);local[rel]=digest(p.read_bytes())
 changes=[]
 for rel in sorted(set(local)|set(s['files'])):
  before=s['files'].get(rel,{}).get('sha256');after=local.get(rel)
  if before==after:continue
  changes.append({'path':rel,'action':'create' if before is None else 'trash' if after is None else 'modify','before':before,'after':after})
 result={'remote_folder':s['remote_folder'],'changes':changes}
 result['plan_sha256']=digest(json.dumps(result,sort_keys=True).encode());return result

def ensure_parents(g,remote):
 for n in range(1,len(remote.split('/'))):
  path='/'.join(remote.split('/')[:n])
  try:
   with g.req('MKCOL',path):pass
  except urllib.error.HTTPError as e:
   if e.code!=405:raise
   entries=g.listing(path,depth='0')
   if not entries or not entries[0]['directory']:raise ValueError('Parent is not a directory')

class WritebackError(ValueError):
 def __init__(self,stage,path,cause,journal,verified):
  self.stage,self.path,self.cause_type=stage,path,type(cause).__name__
  self.journal,self.verified=str(journal),verified
  self.http_status=cause.code if isinstance(cause,urllib.error.HTTPError) else None
  super().__init__('Writeback stopped during '+stage+' for '+path+'; preserve local files and inspect the remote version before retrying')
 def report(self):
  return {'error':'WritebackError','stage':self.stage,'path':self.path,'cause_type':self.cause_type,
          'http_status':self.http_status,'verified_files':self.verified,'journal':self.journal,
          'remote_outcome_unconfirmed':self.stage in ('upload','verify','trash','verify-trash'),
          'message':str(self)}

@locked_workspace
def push(g,base,authorized,approved_plan,allow_trash=False,progress=None):
 if not authorized:raise ValueError('Explicit authorization required before writeback')
 proposed=plan(base)
 if proposed['plan_sha256']!=approved_plan:raise ValueError('Plan changed; review the new plan')
 if any(x['action']=='trash' for x in proposed['changes']) and not allow_trash:raise ValueError('Deleted local files require explicit Trash authorization; no writes performed')
 state=load_state(base);run=str(uuid.uuid4());backup=base/'remote-backups'/run;conflicts=[];complete={}
 journal_dir=base/'writeback-journal'
 if journal_dir.is_symlink():raise ValueError('Symlinked journal directory is not supported')
 journal_dir.mkdir(mode=0o700,exist_ok=True);journal=journal_dir/(run+'.jsonl')
 with journal.open('x') as f:os.chmod(journal,0o600)
 results=[]
 def record(stage,path,**extra):
  event={'stage':stage,'path':path,'time':time.time(),**extra}
  with journal.open('a') as f:
   f.write(json.dumps(event,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
  if progress:progress(event)
 # Check every existing remote version before the first write. This is not an atomic lock against other iCloud clients.
 for c in proposed['changes']:
  remote=join(state['remote_folder'],c['path'])
  record('preflight',c['path'],before=c['before'],after=c['after'])
  try:
   try:current=download(g,remote,backup/c['path'],state['max_bytes'])
   except urllib.error.HTTPError as e:
    if e.code!=404:raise
    current=None
  except (OSError,ValueError) as e:
   record('failed',c['path'],during='preflight',cause_type=type(e).__name__)
   raise WritebackError('preflight',c['path'],e,journal,len(results)) from e
  actual=(current or {}).get('sha256')
  # A previous PUT may have completed even if its response/readback timed out.
  # Adopt only the complete desired hash; zero-byte/partial/other edits remain conflicts.
  if actual==c['after']:complete[c['path']]=current
  elif actual!=c['before']:conflicts.append(c['path'])
 if conflicts:raise ValueError('Remote conflict; no writes performed: '+json.dumps(conflicts,ensure_ascii=False))
 for c in proposed['changes']:
  remote=join(state['remote_folder'],c['path'])
  stage='local-check';recovered=c['path'] in complete
  try:
   if c['action']=='trash':
    if not recovered:
     stage='trash';record(stage,c['path'])
     with g.req('DELETE',remote) as response:
      if response.status not in (200,204):raise ValueError('Unexpected Trash response')
     stage='verify-trash'
     try:
      with g.req('HEAD',remote):pass
     except urllib.error.HTTPError as e:
      if e.code!=404:raise
     else:raise ValueError('File still exists after Trash')
    state['files'].pop(c['path'],None)
   else:
    source=local_target(base,c['path']);payload=source.read_bytes()
    if digest(payload)!=c['after']:raise ValueError('Local file changed after plan review')
    if len(payload)>32*1024*1024:raise ValueError('Per-file upload limit is 32 MiB')
    if recovered:verified=complete[c['path']]
    else:
     stage='mkdir';record(stage,c['path']);ensure_parents(g,remote)
     stage='upload';record(stage,c['path'],bytes=len(payload),before=c['before'],after=c['after'])
     if hasattr(g,'upload'):
      g.upload(remote,payload,c['before'],progress=lambda value:record('transfer',c['path'],progress=value))
     else:
      with g.req('PUT',remote,data=payload,headers={'Content-Type':'application/octet-stream'}) as response:
       if response.status not in (200,201,204):raise ValueError('Unexpected upload response')
     stage='verify';record(stage,c['path'])
     verified=download(g,remote,base/'verification'/str(uuid.uuid4())/c['path'],state['max_bytes'])
     if verified['sha256']!=c['after']:raise ValueError('Remote SHA-256 verification failed')
    state['files'][c['path']]=verified
   stage='save-state';save_state(base,state)
   results.append({'path':c['path'],'action':c['action'],'verified':True,'recovered':recovered})
   record('recovered' if recovered else 'verified',c['path'],after=c['after'])
  except (OSError,ValueError) as e:
   record('failed',c['path'],during=stage,cause_type=type(e).__name__)
   raise WritebackError(stage,c['path'],e,journal,len(results)) from e
 return {'applied':results,'mode':'checkout-and-writeback','backup':str(backup),'journal':str(journal)}

def selection(g):
 with g.req('GET','__codex_gateway_v1__/selection') as response:
  data=json.loads(response.read(16385))
 if data.get('selected'):
  data['folder']=canonical(data['folder'])
 return data

def scope_listing(g,directory,depth='1'):
 rows=[];prefix=directory+'/' if directory else ''
 for item in g.listing(directory+'/' if directory else '',depth=depth):
  remote=href_path(g,item['href'])
  if remote!=directory and (not remote.startswith(prefix) or '/' in remote[len(prefix):]):
   raise ValueError('Listing escaped requested directory')
  rows.append((remote,item))
 return rows

def list_workspace(g,base,folder=''):
 relative(folder);folder=canonical(folder);state=load_state(base);directory=join(state['remote_folder'],folder);entries=[]
 for remote,item in scope_listing(g,directory):
  if remote==directory:continue
  rel=remote[len(state['remote_folder'])+1:] if state['remote_folder'] else remote
  size=int(item['bytes'] or 0)
  if size<0:raise ValueError('Invalid remote size')
  entries.append({'path':rel,'directory':item['directory'],'bytes':None if item['directory'] else size,'downloaded':rel in state['files'] and (base/'files'/rel).is_file()})
 return {'controller':str(base),'workspace':str(base/'files'),'remote_folder':state['remote_folder'],
         'mode':'on-demand-and-writeback' if state.get('mode')=='on-demand' else 'checkout-and-writeback',
         'listed_folder':folder,'entries':entries,'complete':True}

def demand_workspace(g,folder,base,max_bytes):
 folder=canonical(folder);base=base.resolve()
 rows=scope_listing(g,folder,'0')
 if not any(remote==folder and item['directory'] for remote,item in rows):raise ValueError('Selected folder is not a directory')
 if (base/'manifest.json').exists():
  if load_state(base)['remote_folder']!=folder:raise ValueError('Existing workspace belongs to another folder')
 else:
  if base.exists() and any(base.iterdir()):raise ValueError('Destination is not empty; preserve it and choose another workspace')
  base.mkdir(parents=True,exist_ok=True,mode=0o700);(base/'files').mkdir(mode=0o700)
  save_state(base,{'version':2,'mode':'on-demand','remote_folder':folder,'files':{},'excluded':[],'max_bytes':max_bytes})
 return list_workspace(g,base)

def local_target(base,rel):
 relative(rel);rel=canonical(rel)
 if not rel:raise ValueError('Expected a file path')
 safe_file_name(rel)
 if any(part in SKIP_DIR for part in P(rel).parts):raise ValueError('Runtime directory requires separate handling')
 root=base/'files';target=root/rel;p=target
 while p!=root.parent:
  if p.is_symlink():raise ValueError('Symlinked workspace paths are not supported')
  p=p.parent
 if not target.resolve().is_relative_to(root.resolve()):raise ValueError('File escaped workspace')
 return target

@locked_workspace
def fetch(g,base,paths,max_files=1000,max_bytes=256*1024*1024):
 base=base.resolve();state=load_state(base);wanted={}
 if max_files<=0 or max_bytes<=0:raise ValueError('Positive fetch limits required')
 for path in paths:
  relative(path);path=canonical(path);remote=join(state['remote_folder'],path)
  rows=scope_listing(g,remote,'0');item=next((item for name,item in rows if name==remote),None)
  if item is None:raise ValueError('Requested path not found')
  if item['directory']:
   files,_,_=list_tree(g,remote,max_files,max_bytes)
   wanted.update({join(path,rel):info for rel,info in files.items()})
  else:wanted[path]={'bytes':int(item['bytes'] or 0)}
 pending={rel:info for rel,info in wanted.items() if rel not in state['files']}
 if len(pending)>max_files or sum(info['bytes'] for info in pending.values())>max_bytes:raise ValueError('Requested files exceed fetch limits; narrow the requested files')
 for rel,info in wanted.items():
  target=local_target(base,rel)
  if info['bytes']<0:raise ValueError('Invalid remote size')
  if rel in state['files']:
   if not target.is_file():raise ValueError('Tracked local file is missing; preserve the deletion plan or restore it explicitly: '+rel)
  elif target.exists():raise ValueError('Local untracked file already exists; no overwrite: '+rel)
 if (base/'staging').is_symlink():raise ValueError('Symlinked staging directory is not supported')
 results=[];used=0
 for rel in pending:
  target=local_target(base,rel);stage=base/'staging'/str(uuid.uuid4())/rel
  info=download(g,join(state['remote_folder'],rel),stage,max_bytes-used);used+=info['bytes']
  target.parent.mkdir(parents=True,exist_ok=True,mode=0o700);local_target(base,rel)
  # Exclusive link publishes only a complete download, without replacing a concurrent local edit.
  os.link(stage,target);state['files'][rel]=info;save_state(base,state)
  results.append({'path':rel,'bytes':info['bytes'],'sha256':info['sha256']})
 return {'workspace':str(base/'files'),'controller':str(base),'fetched':results,'reused':sorted(set(wanted)-set(pending)),'bytes':used}

def activate(g,base,max_files=1000,max_bytes=256*1024*1024,checkout=False):
 base=base.resolve();binding=base/'selection.json'
 if binding.exists():
  selected=json.loads(binding.read_text())
 else:
  selected=selection(g)
  if not selected.get('selected'):
   return {'selected':False,'message':'Choose a folder on the private gateway page before working with files.'}
  base.mkdir(parents=True,exist_ok=True,mode=0o700)
  with binding.open('x') as f:
   os.chmod(binding,0o600);json.dump(selected,f,ensure_ascii=False)
 result=open_workspace(g,selected['folder'],base/'checkout',max_files,max_bytes) if checkout else demand_workspace(g,selected['folder'],base/'checkout',max_bytes)
 result.update({'selected':True,'remote_folder':selected['folder'],'selection_revision':selected.get('revision')})
 return result

def main():
 p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
 o=sub.add_parser('open');o.add_argument('folder');o.add_argument('--workspace',type=P);o.add_argument('--max-files',type=int,default=1000);o.add_argument('--max-bytes',type=int,default=256*1024*1024);o.add_argument('--checkout',action='store_true')
 d=sub.add_parser('plan');d.add_argument('workspace',type=P)
 u=sub.add_parser('push');u.add_argument('workspace',type=P);u.add_argument('--authorized',action='store_true');u.add_argument('--plan-sha256',required=True);u.add_argument('--allow-trash',action='store_true')
 v=sub.add_parser('selection')
 v=sub.add_parser('activate');v.add_argument('--binding',type=P,default=P(__file__).resolve().parents[4]/'work/icloud-active');v.add_argument('--max-files',type=int,default=1000);v.add_argument('--max-bytes',type=int,default=256*1024*1024);v.add_argument('--checkout',action='store_true')
 v=sub.add_parser('list');v.add_argument('workspace',type=P);v.add_argument('folder',nargs='?',default='')
 v=sub.add_parser('fetch');v.add_argument('workspace',type=P);v.add_argument('paths',nargs='+');v.add_argument('--max-files',type=int,default=1000);v.add_argument('--max-bytes',type=int,default=256*1024*1024)
 a=p.parse_args()
 if a.command=='selection':result=selection(Gateway())
 elif a.command=='activate':result=activate(Gateway(),a.binding,a.max_files,a.max_bytes,a.checkout)
 elif a.command=='list':result=list_workspace(Gateway(),a.workspace.resolve(),a.folder)
 elif a.command=='fetch':result=fetch(Gateway(),a.workspace.resolve(),a.paths,a.max_files,a.max_bytes)
 elif a.command=='open':
  base=a.workspace or P.cwd()/'work/icloud-workspaces'/digest(canonical(a.folder).encode())[:12]
  result=open_workspace(Gateway(),a.folder,base,a.max_files,a.max_bytes) if a.checkout else demand_workspace(Gateway(),a.folder,base,a.max_bytes)
 elif a.command=='plan':result=plan(a.workspace.resolve())
 else:result=push(Gateway(),a.workspace.resolve(),a.authorized,a.plan_sha256,a.allow_trash,
                  progress=lambda event:print(json.dumps({'writeback':event},ensure_ascii=False),file=sys.stderr,flush=True))
 if a.command in ('activate','open') and result.get('controller'):
  controller=P(result['controller'])
  if (controller/'autosave/config.json').exists():
   import autosave
   try:result['autosave']=autosave.start(controller)
   except (ValueError,OSError) as error:result['autosave']={'error':autosave.error_report(error),'resumed':False}
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':
 try:main()
 except WritebackError as e:print(json.dumps(e.report(),ensure_ascii=False),file=sys.stderr);sys.exit(1)
 except urllib.error.HTTPError as e:print(json.dumps({'error':'HTTP','status':e.code}),file=sys.stderr);sys.exit(1)
 except urllib.error.URLError as e:print(json.dumps({'error':'Network','type':type(e.reason).__name__}),file=sys.stderr);sys.exit(1)
 except (ValueError,OSError) as e:print(json.dumps({'error':type(e).__name__,'message':str(e)},ensure_ascii=False),file=sys.stderr);sys.exit(1)
