#!/usr/bin/env python3

# Historical deployment sequence: review docs before applying to your own server.
import os
if os.environ.get('REFERENCE_DEPLOY_ALLOWED') != '1':
 raise SystemExit('Read deployment/reference/README.md; explicit REFERENCE_DEPLOY_ALLOWED=1 required')
if not os.environ.get('ECS_INSTANCE_ID'):
 raise SystemExit('ECS_INSTANCE_ID must identify your own authorized server')
import pathlib,base64,json,subprocess,sys
source=pathlib.Path(sys.argv[1]).resolve()
html=base64.b64encode((source/'index.html').read_bytes()).decode()
headers=base64.b64encode((source/'response-headers.json').read_bytes()).decode()
remote="""set -euo pipefail
install -d -m 755 /opt/icloud-gateway/ui
python3 - <<'DEPLOY'
import pathlib,base64,json,shlex,shutil,time
folder=pathlib.Path('/opt/icloud-gateway/ui');stamp=str(int(time.time()));backup=pathlib.Path('/var/backups/icloud-gateway')/('ui-'+stamp);backup.mkdir(parents=True,mode=0o700,exist_ok=True)
for name,data in [('index.html','"""+html+"""'),('response-headers.json','"""+headers+"""')]:
 p=folder/name
 if p.exists():shutil.copy2(str(p),str(backup/name))
 p.write_bytes(base64.b64decode(data));p.chmod(0o644)
unit=pathlib.Path('/etc/systemd/system/icloud-gateway-webdav.service');old=unit.read_text();lines=old.splitlines();out=[]
for line in lines:
 if line.startswith('ExecStart='):
  args=shlex.split(line[len('ExecStart='):]);clean=[];i=0
  while i<len(args):
   if args[i] in ('--template','--response-header'):i+=2;continue
   clean.append(args[i]);i+=1
  clean+=['--template',str(folder/'index.html')]
  for k,v in json.loads((folder/'response-headers.json').read_text()).items():clean+=['--response-header',k+': '+v]
  def quote(x):return '"'+x.replace('\\\\','\\\\\\\\').replace('"','\\\\"').replace('%','%%')+'"'
  line='ExecStart='+' '.join(quote(a) for a in clean)
 out.append(line)
new='\\n'.join(out)+'\\n'
if new!=old:shutil.copy2(str(unit),str(backup/'webdav.service'));unit.write_text(new)
DEPLOY
systemd-analyze verify /etc/systemd/system/icloud-gateway-webdav.service
systemctl daemon-reload
systemctl restart icloud-gateway-webdav.service
systemctl is-active icloud-gateway-webdav.service
"""
r=subprocess.run(['workbench','exec','-i',os.environ['ECS_INSTANCE_ID'],'--command',remote,'--timeout','45'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True);print(r.stdout+r.stderr);sys.exit(r.returncode)
