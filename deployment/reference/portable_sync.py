#!/usr/bin/env python3
"""Explicit snapshot export/import. Never synchronize auth, sessions, caches or deletions."""
import argparse, hashlib, json, os, pathlib, re, shutil, sys, time, tomllib
P=pathlib.Path
SKIP={'.git','.venv','venv','node_modules','browsers','__pycache__','.cache','cache','dist','build','outputs','work','.DS_Store'}
EXT={'.md','.py','.sh','.js','.mjs','.cjs','.ts','.json','.toml','.yaml','.yml','.txt','.tex','.css','.html','.svg','.png','.jpg','.jpeg','.webp','.woff2','.ttf','.otf','.ps1','.jsonc','.lock','.pdf','.example'}
BADNAME=re.compile(r'(^\.env($|\.)|auth\.json|credential|secret|token|\.pem$|\.key$|\.sqlite|\.db$)',re.I)
SECRET=re.compile(rb'(-----BEGIN (?:[A-Z ]+)?PRIVATE KEY-----|(?:\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,})|(?:AKIA[A-Z0-9]{16})|(?:LTAI[A-Za-z0-9]{16,})|(?:gh[pousr]_[A-Za-z0-9]{30,})|(?:tskey-[A-Za-z0-9_-]{15,}))')
ASSIGN=re.compile(rb'''(?im)["']?(?:api_key|access_key_secret|password|client_secret|bearer_token)["']?\s*[:=]\s*["']([^"'\r\n]{12,})["']''')
SAFE={'model','model_reasoning_effort','model_reasoning_summary','web_search'}
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

def export(home,out):
 files={}; modes={}; omitted=[]
 for folder in ['.codex/skills','.agents/skills']:
  root=home/folder
  if not root.is_dir():continue
  for skill in sorted(root.iterdir()):
   if skill.name.startswith('.') or skill.is_symlink() or not (skill/'SKILL.md').is_file():continue
   for base,dirs,names in os.walk(skill,followlinks=False):
    dirs[:]=[d for d in dirs if d not in SKIP and not d.startswith('.') and not (P(base)/d).is_symlink()]
    for name in names:
     f=P(base)/name; rel=str(f.relative_to(home))
     if f.is_symlink() or BADNAME.search(name) or (f.suffix not in EXT and name not in ['LICENSE','Makefile','VERSION','.gitignore']) or f.stat().st_size>5_000_000:
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
  b=('\n'.join(k+' = '+json.dumps(v,ensure_ascii=False) for k,v in sorted(portable.items()))+'\n').encode()
  files['.codex/config.portable.toml']=b
 hashes={k:sha(v) for k,v in sorted(files.items())}
 ident=sha(json.dumps({'files':hashes,'modes':modes},sort_keys=True).encode())[:20]; dest=out/ident
 if dest.exists():
  validate(dest); print(json.dumps({'reused':str(dest),'files':len(files)}));return
 dest.mkdir(parents=True,mode=0o700)
 for k,b in files.items():private_write(dest/'files'/k,b)
 private_write(dest/'manifest.json',json.dumps({'version':1,'id':ident,'files':hashes,'modes':modes,'omitted':omitted},ensure_ascii=False,indent=2).encode())
 print(json.dumps({'snapshot':str(dest),'files':len(files),'omitted':len(omitted)},ensure_ascii=False))

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
