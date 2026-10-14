#!/usr/bin/env python3
"""Refresh a clean task's trusted repository and discoverable Skills without touching its binding."""
import pathlib,subprocess,os,json
from safe_fast_forward import fast_forward
TRUSTED_ORIGINS={'https://github.com/OWNER/PRIVATE-PORTABLE-REPO','https://github.com/OWNER/PRIVATE-PORTABLE-REPO.git'}
root=pathlib.Path(__file__).resolve().parents[1]
def failure_category(stderr):
 text=stderr.casefold()
 if any(x in text for x in ['read-only file system','permission denied','operation not permitted']):return 'filesystem-permission'
 if any(x in text for x in ['authentication failed','could not read username','invalid username or token']):return 'authentication'
 if any(x in text for x in ['failed to connect','could not connect','could not resolve','network is unreachable','connection refused']):return 'network-path-unavailable'
 return 'operation-failed'

def run(*args):
 try:
  r=subprocess.run(args,cwd=root,env=dict(os.environ,GIT_TERMINAL_PROMPT='0'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=60 if args[:2]==('git','fetch') else 120)
 except subprocess.TimeoutExpired:
  category='network-path-unavailable' if args[:2]==('git','fetch') else 'operation-timeout'
  message='Cloud Skill refresh timed out ('+category+'); existing workspace files preserved.'
  if category=='network-path-unavailable':message+=' Retry this same refresh once through the Cloud runtime authorized network execution path; do not change proxy, VPN or credentials.'
  raise SystemExit(message) from None
 if r.returncode:
  category=failure_category(r.stderr);operation='git '+args[1] if args[0]=='git' and len(args)>1 else args[0]
  message='Cloud Skill refresh failed: %s (exit %s; %s). Existing files preserved.'%(operation,r.returncode,category)
  if category=='network-path-unavailable':message+=' Retry this same refresh once through the Cloud runtime authorized network execution path; do not change proxy, VPN or credentials.'
  raise SystemExit(message)
 return r.stdout.strip()

def main():
 if run('git','remote','get-url','origin') not in TRUSTED_ORIGINS:
  raise SystemExit('Repository origin differs from the trusted private source; no fetch or overwrite')
 dirty=run('git','status','--porcelain','--untracked-files=no')
 if dirty:raise SystemExit('Tracked repository edits exist; no automatic pull or overwrite')
 run('git','fetch','origin','main')
 try:fast_forward(root,root/'work/git-fast-forward-backups',lambda repo,*args:run('git',*args))
 except ValueError as e:raise SystemExit(str(e))
 output=run('python3','scripts/cloud_bootstrap.py','--cloud-root',str(root.parent))
 result=json.loads(output);result['source_commit']=run('git','rev-parse','HEAD');result['existing_workspace_binding']='preserved'
 print(json.dumps(result))

if __name__=='__main__':main()
