#!/usr/bin/env python3

# Historical deployment sequence: review docs before applying to your own server.
import os
if os.environ.get('REFERENCE_DEPLOY_ALLOWED') != '1':
 raise SystemExit('Read deployment/reference/README.md; explicit REFERENCE_DEPLOY_ALLOWED=1 required')
if not os.environ.get('ECS_INSTANCE_ID'):
 raise SystemExit('ECS_INSTANCE_ID must identify your own authorized server')
"""Preflight by default; --apply enables the explicitly approved owner-browser identity policy."""
import base64,pathlib,subprocess,sys

source=pathlib.Path('./gateway-ui')
payloads={n:base64.b64encode((source/n).read_bytes()).decode() for n in ['browser_proxy.py','selection_api.py','index.html','response-headers.json']}
remote=r'''import pathlib,subprocess,json,base64,shutil,uuid,os,socket,time,stat
TS=['/opt/icloud-gateway/tailscale/1.104.1/tailscale','--socket=/run/icloud-gateway-tailscale/tailscaled.sock']
data=PAYLOADS
apply=APPLY
s=json.loads(subprocess.check_output(TS+['status','--json']))
owner=s.get('User',{}).get(str(s.get('Self',{}).get('UserID')),{}).get('LoginName')
if not owner:raise SystemExit('Owner identity unavailable; stopped')
unit=pathlib.Path('/etc/systemd/system/icloud-gateway-picker.service')
old=unit.read_text()
expected={'Group':'icloud-gateway','RuntimeDirectory':'icloud-gateway-picker','RuntimeDirectoryMode':'0750'}
for key,value in expected.items():
 matches=[x.split('=',1)[1] for x in old.splitlines() if x.startswith(key+'=')]
 if matches and matches!=[value]:raise SystemExit('Conflicting service property; stopped: '+key)
serve=subprocess.check_output(TS+['serve','status','--json'])
for name in ['browser_proxy.py','selection_api.py']:compile(base64.b64decode(data[name]).decode(),name,'exec')
state=pathlib.Path('/var/lib/icloud-gateway-picker');ownerfile=state/'browser-owner.json'
if ownerfile.exists() and json.loads(ownerfile.read_text()).get('login')!=owner:raise SystemExit('Existing owner binding differs; stopped')
if not apply:
 print(json.dumps({'preflight':'passed','owner_binding_available':True,'python36_compile':True,'authorization_changed':False,'services_restarted':False}))
 raise SystemExit(0)
backup=pathlib.Path('/var/backups/icloud-gateway/browser-login-'+str(uuid.uuid4()));backup.mkdir(mode=0o700)
shutil.copy2(str(unit),str(backup/'picker.service'))
(backup/'serve.json').write_bytes(serve)
if ownerfile.exists():shutil.copy2(str(ownerfile),str(backup/'browser-owner.json'))
uid=state.stat().st_uid
ownerfile.write_text(json.dumps({'login':owner,'user_id':s.get('Self',{}).get('UserID')}));ownerfile.chmod(0o600);os.chown(str(ownerfile),uid,1000)
folder=pathlib.Path('/opt/icloud-gateway/ui')
for name,value in data.items():
 p=folder/name
 if p.exists():shutil.copy2(str(p),str(backup/name))
 p.write_bytes(base64.b64decode(value));p.chmod(0o644)
lines=old.splitlines();out=[]
for line in lines:
 if line.startswith('Environment=ICLOUD_BROWSER_IDENTITY='):continue
 out.append(line)
 if line=='[Service]':
  for key,value in expected.items():
   if not any(x.startswith(key+'=') for x in lines):out.append(key+'='+value)
  out.append('Environment=ICLOUD_BROWSER_IDENTITY=1')
unit.write_text('\n'.join(out)+'\n')
subprocess.check_call(['systemd-analyze','verify',str(unit)])
subprocess.check_call(['systemctl','daemon-reload'])
subprocess.check_call(['systemctl','restart','icloud-gateway-picker.service'])
path=pathlib.Path('/run/icloud-gateway-picker/browser.sock')
for _ in range(30):
 if path.exists():break
 time.sleep(.2)
if not path.exists() or not stat.S_ISSOCK(path.stat().st_mode):raise SystemExit('Browser socket did not start; backup preserved at '+str(backup))
if path.stat().st_gid!=1000 or path.stat().st_mode&0o777!=0o660:raise SystemExit('Browser socket permissions differ; stopped')
subprocess.check_call(TS+['serve','--bg','--https=443','unix:'+str(path)],stdout=subprocess.DEVNULL)
subprocess.check_call(TS+['serve','--https=443','--set-path=/__codex_gateway_v1__','off'],stdout=subprocess.DEVNULL)
print(json.dumps({'deployed':True,'owner_binding':'fixed server owner account','browser_permissions':'GET/HEAD and same-origin selection/notification POST','webdav_write_auth':'Basic required','socket_mode':'0660','socket_group':1000,'backup':str(backup)}))
'''.replace('PAYLOADS',repr(payloads)).replace('APPLY',repr('--apply' in sys.argv))
quoted="'"+remote.replace("'","'\"'\"'")+"'"
r=subprocess.run(['/usr/local/bin/workbench','--profile',os.environ['WORKBENCH_PROFILE'],'exec','-i',os.environ['ECS_INSTANCE_ID'],'--command','python3 -c '+quoted,'--timeout','45'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
print(r.stdout+r.stderr)
if r.returncode==0:
 evidence='browser-login-deployed.txt' if '--apply' in sys.argv else 'browser-login-preflight.txt'
 pathlib.Path('work/deployment-evidence',evidence).write_text(r.stdout+r.stderr)
raise SystemExit(r.returncode)
