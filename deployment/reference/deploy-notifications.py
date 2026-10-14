#!/usr/bin/env python3

# Historical deployment sequence: review docs before applying to your own server.
import os
if os.environ.get('REFERENCE_DEPLOY_ALLOWED') != '1':
 raise SystemExit('Read deployment/reference/README.md; explicit REFERENCE_DEPLOY_ALLOWED=1 required')
if not os.environ.get('ECS_INSTANCE_ID'):
 raise SystemExit('ECS_INSTANCE_ID must identify your own authorized server')
import pathlib,base64,json,subprocess,sys
repo=pathlib.Path(sys.argv[1]);files={}
for name in ['selection_api.py','notifications.py','sw.js','manifest.webmanifest','icon.svg','notifications.html','notification-headers.json']:
 files['/opt/icloud-gateway/ui/'+name]=base64.b64encode((repo/'gateway-ui'/name).read_bytes()).decode()
files['/usr/local/libexec/icloud-gateway-health.py']=base64.b64encode((repo/'gateway-runtime/health.py').read_bytes()).decode()
files['/usr/local/libexec/icloud_gateway_mail.py']=base64.b64encode((repo/'gateway-runtime/mail_notify.py').read_bytes()).decode()
payload=base64.b64encode(json.dumps(files).encode()).decode()
script=r"""set -euo pipefail
printf '%s\n' '47a50db5a5e16b4959b5c8531227fbbfa1d20a78621b9a0c32d8ba547ea198d4  /home/icloud-gateway/install/webpush-helper-linux-amd64' | sha256sum -c -
install -m 755 /home/icloud-gateway/install/webpush-helper-linux-amd64 /opt/icloud-gateway/ui/webpush-helper
python3 - <<'WRITE'
import pathlib,base64,json,shutil,time
files=json.loads(base64.b64decode('"""+payload+r"""'));backup=pathlib.Path('/var/backups/icloud-gateway')/('notifications-'+str(int(time.time())));backup.mkdir(parents=True,mode=0o700)
for target,encoded in files.items():
 p=pathlib.Path(target)
 if p.exists():shutil.copy2(str(p),str(backup/p.name))
 p.write_bytes(base64.b64decode(encoded));p.chmod(0o644)
 if p.suffix=='.py':compile(p.read_text(),str(p),'exec')
p=pathlib.Path('/etc/systemd/system/icloud-gateway-health.service');old=p.read_text();shutil.copy2(str(p),str(backup/p.name));
if '/home/icloud-gateway/.local/share/agently-cli' not in old:old=old.replace(' /var/cache/icloud-gateway',' /var/cache/icloud-gateway /home/icloud-gateway/.local/share/agently-cli')
old=old.replace('TimeoutStartSec=90','TimeoutStartSec=180');p.write_text(old)
p=pathlib.Path('/etc/systemd/system/icloud-gateway-health.timer');old=p.read_text();shutil.copy2(str(p),str(backup/p.name));old=old.replace('Check iCloud authentication twice daily','Check iCloud authentication and notify on state changes').replace('OnCalendar=*-*-* 01,13:00:00 UTC','OnCalendar=*:0/15').replace('RandomizedDelaySec=10m','RandomizedDelaySec=60s');p.write_text(old)
WRITE
systemd-analyze verify /etc/systemd/system/icloud-gateway-picker.service /etc/systemd/system/icloud-gateway-health.service /etc/systemd/system/icloud-gateway-health.timer
systemctl daemon-reload
systemctl restart icloud-gateway-picker.service icloud-gateway-health.timer
systemctl is-active icloud-gateway-picker.service icloud-gateway-webdav.service icloud-gateway-tailscale.service
"""
r=subprocess.run(['workbench','exec','-i',os.environ['ECS_INSTANCE_ID'],'--command',script,'--timeout','60'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);print(r.stdout+r.stderr);sys.exit(r.returncode)
