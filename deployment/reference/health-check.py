#!/usr/bin/env python3
"""Read-only check. Persist only status/codes/timestamps, never Apple errors or listings."""
import datetime,json,pathlib,subprocess,sys
base=pathlib.Path('/home/icloud-gateway');state=base/'.local/state/icloud-gateway';state.mkdir(parents=True,exist_ok=True,mode=0o700)
args=[str(base/'.local/bin/rclone-cn9399'),'--config',str(base/'.config/rclone/rclone-cn.conf'),'lsf','Codex:','--max-depth','1','--dirs-only','--retries','1','--low-level-retries','1','--contimeout','10s','--timeout','30s']
result={'checked_at':datetime.datetime.utcnow().isoformat()+'Z'}
try:
 r=subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=60,universal_newlines=True)
 result['exit_code']=r.returncode;result['status']='OK' if r.returncode==0 else 'CHECK_FAILED'
 if r.returncode:
  if any(x in r.stderr.lower() for x in ['trust token','reauth','invalid session token','2fa']):result['status']='REAUTH_REQUIRED'
  elif '412' in r.stderr and 'data access on web' in r.stderr:result['status']='APPLE_WEB_ACCESS_DISABLED'
  elif '302' in r.stderr and 'domainToUse' in r.stderr:result['status']='REGION_INCOMPATIBLE'
except subprocess.TimeoutExpired:result['status']='NETWORK_TIMEOUT'
p=state/'health.json';p.write_text(json.dumps(result));p.chmod(0o600)
print(json.dumps(result));sys.exit(0 if result['status']=='OK' else 1)
