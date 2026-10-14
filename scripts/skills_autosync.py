#!/usr/bin/env python3
"""Publish only verified portable snapshots; retain old trees and refuse dirty worktrees."""
import argparse,fcntl,json,os,pathlib,shutil,subprocess,time,uuid,urllib.parse
import portable_sync as portable
from safe_fast_forward import fast_forward
P=pathlib.Path

def git(repo,*args):
 env=dict(os.environ,GIT_TERMINAL_PROMPT='0')
 r=subprocess.run(['git','-C',str(repo)]+list(args),env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 if r.returncode:raise ValueError('Git operation failed: '+args[0]+' (no credential output)')
 return r.stdout.strip()

def write_json(path,value):
 temp=path.with_name(path.name+'-'+str(uuid.uuid4())+'.tmp')
 portable.private_write(temp,json.dumps(value).encode());os.replace(temp,path)

def verify_destination(repo,expected,gh):
 if git(repo,'remote','get-url','origin')!=expected:raise ValueError('Repository destination changed; automatic publication stopped')
 url=urllib.parse.urlsplit(expected)
 if url.scheme!='https' or url.hostname!='github.com' or url.username or url.password or url.query or url.fragment:
  raise ValueError('Automatic publication requires the pinned GitHub HTTPS destination')
 name=url.path.strip('/').removesuffix('.git')
 if len(name.split('/'))!=2:raise ValueError('Invalid pinned repository name')
 r=subprocess.run([str(gh),'api','repos/'+name,'--jq','.private'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 if r.returncode or r.stdout.strip()!='true':raise ValueError('Private repository status could not be verified; nothing published')

def finish_pending(repo,runtime,scanner):
 pending=runtime/'pending-push.json'
 if not pending.exists():return
 value=json.loads(pending.read_text());head=git(repo,'rev-parse','HEAD');remote=git(repo,'rev-parse','origin/main')
 if head!=value['commit']:raise ValueError('Pending automatic commit changed; manual review required')
 if remote!=head:
  if remote!=value['parent']:raise ValueError('Remote changed after pending automatic commit; manual review required')
  paths=git(repo,'diff-tree','--no-commit-id','--name-only','-r',head).splitlines()
  if not paths or any(not x.startswith('snapshot/') for x in paths):raise ValueError('Pending automatic commit has unexpected scope')
  if git(repo,'diff','--name-status','--diff-filter=DR','--find-renames',remote,head):raise ValueError('Pending automatic commit contains removals or renames; nothing published')
  r=subprocess.run([str(scanner),'git','--log-opts='+remote+'..'+head,'--redact','--no-banner'],cwd=repo,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  if r.returncode:raise ValueError('Pending automatic commit failed secret scan; nothing published')
  git(repo,'push','origin','HEAD:main')
 retained=runtime/'completed-pushes';retained.mkdir(mode=0o700,exist_ok=True)
 pending.rename(retained/(str(uuid.uuid4())+'.json'))

def publish(repo,bundle,runtime,scanner):
 manifest=portable.validate(bundle)
 if git(repo,'status','--porcelain','--untracked-files=no'):raise ValueError('Tracked repository edits exist; automatic sync stopped')
 if git(repo,'branch','--show-current')!='main':raise ValueError('Automatic sync requires main')
 git(repo,'fetch','origin','main')
 finish_pending(repo,runtime,scanner)
 fast_forward(repo,runtime/'fast-forward-backups',git)
 current=portable.validate(repo/'snapshot')
 if current['id']==manifest['id']:return {'changed':False,'snapshot':manifest['id']}
 missing=set(current['files'])-set(manifest['files'])
 if missing:raise ValueError('Source export lacks previously synchronized files; publication stopped without propagating removals ('+str(len(missing))+' files)')
 known={(x['path'],x['reason']) for x in current.get('omitted',[])}
 if any(x['reason'].startswith('potential embedded credential') and (x['path'],x['reason']) not in known for x in manifest.get('omitted',[])):
  raise ValueError('New potential embedded credential omission requires review; nothing published')
 backup=runtime/'snapshot-backups'/str(uuid.uuid4());backup.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 (repo/'snapshot').rename(backup)
 shutil.copytree(bundle,repo/'snapshot');portable.validate(repo/'snapshot')
 git(repo,'add','--all','--','snapshot')
 r=subprocess.run([str(scanner),'git','--staged','--redact','--no-banner'],cwd=repo,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 if r.returncode:
  git(repo,'restore','--staged','--','snapshot')
  review=runtime/'review'/str(uuid.uuid4());review.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
  (repo/'snapshot').rename(review);backup.rename(repo/'snapshot')
  raise ValueError('Secret scan failed; candidate retained for review and original snapshot restored, nothing published')
 parent=git(repo,'rev-parse','HEAD')
 git(repo,'commit','-m','Sync portable Skills '+manifest['id'],'--','snapshot')
 write_json(runtime/'pending-push.json',{'commit':git(repo,'rev-parse','HEAD'),'parent':parent,'snapshot':manifest['id']})
 git(repo,'push','origin','HEAD:main')
 finish_pending(repo,runtime,scanner)
 return {'changed':True,'snapshot':manifest['id'],'commit':git(repo,'rev-parse','HEAD'),'backup':str(backup)}

def sync_once(home,repo,runtime,scanner,expected_remote=None,gh=None):
 runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
 with (runtime/'lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return {'changed':False,'busy':True}
  if expected_remote:verify_destination(repo,expected_remote,gh)
  bundle=portable.export(home,runtime/'exports',exclude_skills={'icloud-codex-gateway'},emit=False)
  result=publish(repo,bundle,runtime,scanner)
  result.update({'checked_at':time.time(),'status':'ok','project_managed_gateway':'from repository, not overwritten by the home snapshot'})
  write_json(runtime/'status.json',result)
  return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--home',type=P,default=P.home());p.add_argument('--repo',type=P,required=True);p.add_argument('--runtime',type=P,required=True);p.add_argument('--scanner',type=P,required=True);p.add_argument('--expected-remote',required=True);p.add_argument('--gh',type=P,required=True);a=p.parse_args()
 try:
  result=sync_once(a.home.resolve(),a.repo.resolve(),a.runtime.resolve(),a.scanner.resolve(),a.expected_remote,a.gh.resolve())
  if result.get('changed'):print(json.dumps(result))
 except (ValueError,OSError) as e:
  a.runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
  status={'status':'blocked','error':str(e),'checked_at':time.time()};write_json(a.runtime/'status.json',status)
  raise SystemExit(str(e))
