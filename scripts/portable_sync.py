#!/usr/bin/env python3
"""Explicit snapshot export/import. Never synchronize auth, sessions, caches or deletions."""
import argparse, hashlib, json, os, pathlib, re, shutil, sys, time, tomllib, urllib.parse, ipaddress
P=pathlib.Path
SKIP={'.git','.venv','venv','node_modules','browsers','__pycache__','.cache','cache','dist','build','outputs','work','.DS_Store'}
EXT={'.md','.py','.sh','.js','.mjs','.cjs','.ts','.json','.toml','.yaml','.yml','.txt','.tex','.css','.html','.svg','.png','.jpg','.jpeg','.webp','.woff2','.ttf','.otf','.ps1','.jsonc','.lock','.pdf','.example'}
BADNAME=re.compile(r'(^\.env($|\.)|auth\.json|credential|secret|token|\.pem$|\.key$|\.sqlite|\.db$)',re.I)
SECRET=re.compile(rb'(-----BEGIN (?:[A-Z ]+)?PRIVATE KEY-----|(?:\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,})|(?:AKIA[A-Z0-9]{16})|(?:LTAI[A-Za-z0-9]{16,})|(?:gh[pousr]_[A-Za-z0-9]{30,})|(?:tskey-[A-Za-z0-9_-]{15,}))')
ASSIGN=re.compile(rb'''(?im)["']?(?:api_key|access_key_secret|password|client_secret|bearer_token)["']?\s*[:=]\s*["']([^"'\r\n]{12,})["']''')
SAFE={'model','model_reasoning_effort','model_reasoning_summary','web_search'}
ENV_NAME=re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
MACHINE_PATH=re.compile(r'(^/|^[A-Za-z]:[\\/]|^~|\$\{?(HOME|CODEX_HOME)|/Users/|/Applications/|/Library/)')
def sha(b):return hashlib.sha256(b).hexdigest()
def private_write(p,b):
 p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'wb') as f:f.write(b)
def clean(b):
 if SECRET.search(b):return False
 for m in ASSIGN.finditer(b):
  v=m.group(1).lower()
  if v in {b'sk_live_abc123', b'sk-live-abc123...'} or '你的密码'.encode() in v or '单独的密码'.encode() in v:continue
  if not any(x in v for x in [b'example',b'placeholder',b'your',b'<',b'${',b'process.',b'os.env',b'xxxx']):return False
 return True

def portable_mcp(servers):
 accepted={};omitted=[]
 for name,server in sorted(servers.items()):
  reason=None;out={}
  if not isinstance(server,dict):reason='invalid MCP definition'
  elif 'url' in server:
   u=urllib.parse.urlsplit(str(server['url']));host=u.hostname or ''
   try:local=ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
   except ValueError:local=host in ('localhost','localhost.localdomain') or host.endswith('.local')
   if u.scheme!='https' or not host or u.username or u.password or u.query or u.fragment or local:reason='non-portable or credential-bearing MCP URL'
   else:out['url']=server['url']
  elif 'command' in server:
   command=server['command'];args=server.get('args',[])
   if not isinstance(command,str) or '/' in command or '\\' in command or MACHINE_PATH.search(command):reason='machine-specific MCP executable'
   elif not isinstance(args,list) or any(not isinstance(x,str) or MACHINE_PATH.search(x) for x in args):reason='machine-specific MCP arguments'
   elif any(re.search(r'(^|[-_])(api[-_]?key|password|secret|token|authorization)(=|$)',x,re.I) for x in args):reason='MCP credentials in command arguments'
   elif server.get('cwd'):reason='MCP working directory requires target-specific setup'
   else:out.update({'command':command,'args':args})
  else:reason='unsupported MCP transport'
  if reason:omitted.append({'path':'.codex/config.toml:mcp_servers.'+name,'reason':reason});continue
  names=server.get('env_vars',[])
  if not isinstance(names,list) or any(not isinstance(x,str) or not ENV_NAME.fullmatch(x) for x in names):
   omitted.append({'path':'.codex/config.toml:mcp_servers.'+name,'reason':'non-portable MCP environment source'});continue
  # Export names for target-side provisioning, never source environment values.
  if 'command' in out:
   names=sorted(set(names)|{k for k in server.get('env',{}) if ENV_NAME.fullmatch(k)})
   if names:out['env_vars']=names
  token=server.get('bearer_token_env_var')
  if token:
   if not isinstance(token,str) or not ENV_NAME.fullmatch(token):raise ValueError('Invalid MCP token environment reference')
   out['bearer_token_env_var']=token
  headers=server.get('env_http_headers',{})
  if isinstance(headers,dict) and all(isinstance(k,str) and isinstance(v,str) and ENV_NAME.fullmatch(v) for k,v in headers.items()):
   if headers:out['env_http_headers']=headers
  for key in ('enabled','required','startup_timeout_sec','tool_timeout_sec','enabled_tools','disabled_tools'):
   value=server.get(key)
   if isinstance(value,(str,bool,int)) or isinstance(value,list) and all(isinstance(x,str) for x in value):out[key]=value
  # Fixed headers and raw env fields may contain tokens, so they are never copied.
  if 'http_headers' in server:omitted.append({'path':'.codex/config.toml:mcp_servers.'+name+'.http_headers','reason':'fixed headers require separate target review'})
  b=json.dumps(out,ensure_ascii=False).encode()
  if not clean(b):omitted.append({'path':'.codex/config.toml:mcp_servers.'+name,'reason':'potential embedded MCP credential'});continue
  accepted[name]=out
 return accepted,omitted

def toml_value(value):
 if isinstance(value,dict):return '{ '+', '.join(json.dumps(k,ensure_ascii=False)+' = '+toml_value(v) for k,v in sorted(value.items()))+' }'
 if isinstance(value,list):return '['+', '.join(toml_value(v) for v in value)+']'
 return json.dumps(value,ensure_ascii=False)

def export(home,out,exclude_skills=(),emit=True):
 files={}; modes={}; omitted=[]
 for folder in ['.codex/skills','.agents/skills']:
  root=home/folder
  if not root.is_dir():continue
  for skill in sorted(root.iterdir()):
   if skill.name in exclude_skills or skill.name.startswith('.') or skill.is_symlink() or not (skill/'SKILL.md').is_file():continue
   for base,dirs,names in os.walk(skill,followlinks=False):
    dirs[:]=[d for d in dirs if d not in SKIP and not d.startswith('.') and not (P(base)/d).is_symlink()]
    for name in names:
     f=P(base)/name; rel=str(f.relative_to(home))
     if name == '.config.local.toml' or f.is_symlink() or BADNAME.search(name) or (f.suffix not in EXT and name not in ['LICENSE','Makefile','VERSION','.gitignore']) or f.stat().st_size>5_000_000:
      omitted.append({'path':rel,'reason':'excluded type/name/size/symlink'});continue
     b=f.read_bytes()
     if not clean(b):omitted.append({'path':rel,'reason':'potential embedded credential; manual review required'});continue
     files[rel]=b; modes[rel]=0o700 if f.stat().st_mode & 0o111 else 0o600
 p=home/'.codex/AGENTS.md'
 if p.is_file() and not p.is_symlink():
  b=p.read_bytes()
  if not clean(b):raise SystemExit('AGENTS contains potential credential; export stopped')
  files['.codex/AGENTS.md']=b
 p=home/'.codex/config.toml'
 if p.is_file():
  d=tomllib.loads(p.read_text()); portable={k:v for k,v in d.items() if k in SAFE and isinstance(v,(str,bool,int))}
  lines=[k+' = '+toml_value(v) for k,v in sorted(portable.items())]
  servers,skipped=portable_mcp(d.get('mcp_servers',{}));omitted.extend(skipped)
  for name,server in servers.items():
   lines.extend(['','[mcp_servers.'+json.dumps(name,ensure_ascii=False)+']'])
   lines.extend(k+' = '+toml_value(v) for k,v in sorted(server.items()))
  b=('\n'.join(lines)+'\n').encode();tomllib.loads(b.decode())
  files['.codex/config.portable.toml']=b
 hashes={k:sha(v) for k,v in sorted(files.items())}
 # Omission changes are part of the immutable export identity too: reusing a
 # content-only snapshot must not hide a newly detected credential omission.
 omitted.sort(key=lambda x:(x['path'],x['reason']))
 ident=sha(json.dumps({'files':hashes,'modes':modes,'omitted':omitted},sort_keys=True).encode())[:20]; dest=out/ident
 if dest.exists():
  validate(dest)
  if emit:print(json.dumps({'reused':str(dest),'files':len(files)}))
  return dest
 dest.mkdir(parents=True,mode=0o700)
 for k,b in files.items():private_write(dest/'files'/k,b)
 private_write(dest/'manifest.json',json.dumps({'version':1,'id':ident,'files':hashes,'modes':modes,'omitted':omitted},ensure_ascii=False,indent=2).encode())
 if emit:print(json.dumps({'snapshot':str(dest),'files':len(files),'omitted':len(omitted)},ensure_ascii=False))
 return dest

def validate(bundle):
 m=json.loads((bundle/'manifest.json').read_text())
 for rel,digest in m['files'].items():
  r=P(rel)
  if r.is_absolute() or '..' in r.parts or not (rel.startswith('.codex/skills/') or rel.startswith('.agents/skills/') or rel in ['.codex/AGENTS.md','.codex/config.portable.toml']):raise ValueError('unsafe manifest path')
  f=bundle/'files'/r
  if f.is_symlink() or not f.resolve().is_relative_to((bundle/'files').resolve()) or sha(f.read_bytes())!=digest:raise ValueError('snapshot hash/path mismatch')
 return m

def import_(home,bundle,apply):
 m=validate(bundle); state=home/'.codex/portable-sync-state.json'
 previous=json.loads(state.read_text()).get('files',{}) if state.exists() else {}
 conflicts=[]; changes=[]
 for rel,digest in m['files'].items():
  p=home/rel
  if p.is_symlink() or not p.resolve().is_relative_to(home.resolve()):conflicts.append(rel);continue
  actual=sha(p.read_bytes()) if p.is_file() else None
  if actual==digest:continue
  if p.exists() and (not p.is_file() or actual!=previous.get(rel)):conflicts.append(rel);continue
  changes.append(rel)
 print(json.dumps({'apply':apply,'changes':len(changes),'conflicts':conflicts,'deletions':0},ensure_ascii=False))
 if conflicts:raise SystemExit(2)
 if not apply:return
 stamp=time.strftime('%Y%m%dT%H%M%S')+'-'+str(time.time_ns())
 backup=home/'.codex/portable-backups'/stamp
 for rel in changes:
  p=home/rel
  if p.exists():
   private_write(backup/rel,p.read_bytes())
   # Preserve old version, atomically replace only a previously managed file.
   tmp=p.with_name(p.name+'.portable-'+stamp)
   private_write(tmp,(bundle/'files'/rel).read_bytes());os.replace(tmp,p)
  else:private_write(p,(bundle/'files'/rel).read_bytes())
  p.chmod(0o700 if m.get('modes',{}).get(rel)==0o700 else 0o600)
 # config.portable.toml remains a reviewable profile; never replace active config.toml.
 if state.exists():private_write(backup/'portable-sync-state.json',state.read_bytes())
 tmp=state.with_name('portable-sync-state.'+stamp+'.json');private_write(tmp,json.dumps({'files':m['files'],'snapshot':m['id']},indent=2).encode());os.replace(tmp,state)
 print(json.dumps({'imported':m['id'],'backup':str(backup),'active_config_unchanged':True}))

if __name__=='__main__':
 a=argparse.ArgumentParser();s=a.add_subparsers(dest='command',required=True)
 e=s.add_parser('export');e.add_argument('--home',type=P,default=P.home());e.add_argument('--out',type=P,required=True)
 i=s.add_parser('import');i.add_argument('--home',type=P,default=P.home());i.add_argument('--bundle',type=P,required=True);i.add_argument('--apply',action='store_true')
 v=s.add_parser('verify');v.add_argument('--bundle',type=P,required=True)
 x=a.parse_args()
 if x.command=='export':export(x.home.resolve(),x.out.resolve())
 elif x.command=='import':import_(x.home.resolve(),x.bundle.resolve(),x.apply)
 else:validate(x.bundle.resolve());print('manifest hashes and paths verified')
