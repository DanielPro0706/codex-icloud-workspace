#!/usr/bin/env python3
"""Read-only iCloud health, sanitized state, server-side email and Web Push alerts."""
import base64,datetime,json,pathlib,subprocess,sys,urllib.request,urllib.error
from icloud_gateway_mail import notify
BASE=pathlib.Path('/home/icloud-gateway')

def classify(code,error):
 if code==0:return 'OK'
 text=error.lower()
 if any(x in text for x in ('trust token','reauth','invalid session token','2fa','authentication failed','invalid credentials','session expired')):return 'REAUTH_REQUIRED'
 if '412' in text and 'data access on web' in text:return 'APPLE_WEB_ACCESS_DISABLED'
 if '302' in text and 'domaintouse' in text:return 'REGION_INCOMPATIBLE'
 return 'CHECK_FAILED'

def main():
 state=BASE/'.local/state/icloud-gateway';state.mkdir(parents=True,exist_ok=True,mode=0o700)
 args=[str(BASE/'.local/bin/rclone-cn9399'),'--config',str(BASE/'.config/rclone/rclone-cn.conf'),'lsf','Codex:','--max-depth','1','--dirs-only','--retries','1','--low-level-retries','1','--contimeout','10s','--timeout','30s']
 result={'checked_at':datetime.datetime.utcnow().isoformat()+'Z'}
 try:
  r=subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=60,universal_newlines=True);result.update({'exit_code':r.returncode,'status':classify(r.returncode,r.stderr)})
 except subprocess.TimeoutExpired:result['status']='NETWORK_TIMEOUT'
 p=state/'health.json';p.write_text(json.dumps(result));p.chmod(0o600)
 try:mail=notify(result['status'])
 except Exception:mail={'status':'failed'}
 result['mail']=mail
 try:
  env=dict(x.split('=',1) for x in (BASE/'.config/icloud-gateway/webdav.env').read_text().splitlines());auth='Basic '+base64.b64encode((env['RCLONE_USER']+':'+env['RCLONE_PASS']).encode()).decode()
  request=urllib.request.Request('http://127.0.0.1:18767/health-event',data=json.dumps(result).encode(),headers={'Authorization':auth,'Content-Type':'application/json'})
  with urllib.request.urlopen(request,timeout=15) as response:result['web_push_event_recorded']=response.status==202
 except Exception:result['web_push_event_recorded']=False
 p.write_text(json.dumps(result));p.chmod(0o600);print(json.dumps(result));return 0 if result['status']=='OK' else 1
if __name__=='__main__':sys.exit(main())
