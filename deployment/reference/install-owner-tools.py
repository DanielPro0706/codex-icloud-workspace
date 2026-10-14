
# Historical deployment sequence: review docs before applying to your own server.
import os
if os.environ.get('REFERENCE_DEPLOY_ALLOWED') != '1':
 raise SystemExit('Read deployment/reference/README.md; explicit REFERENCE_DEPLOY_ALLOWED=1 required')
if not os.environ.get('ECS_INSTANCE_ID'):
 raise SystemExit('ECS_INSTANCE_ID must identify your own authorized server')
import subprocess
script=r'''set -euo pipefail
cat > /usr/local/bin/icloud-rotate-gateway <<'HELPER'
#!/usr/bin/python3
import os,sys,pathlib,secrets,subprocess
if not (sys.stdin.isatty() and sys.stdout.isatty()):raise SystemExit('Use your own private SSH terminal')
p=pathlib.Path('/home/icloud-gateway/.config/icloud-gateway/webdav.env')
if p.owner()!='icloud-gateway':raise SystemExit('Unexpected credential owner')
os.umask(0o077)
temp=p.with_name('webdav.env.new')
fd=os.open(str(temp),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:f.write('RCLONE_USER=codex-gateway\nRCLONE_PASS='+secrets.token_urlsafe(32)+'\n')
os.replace(str(temp),str(p))
subprocess.check_call(['sudo','-n','/usr/bin/systemctl','restart','icloud-gateway-webdav.service'])
subprocess.check_call(['sudo','-n','/usr/bin/systemctl','restart','icloud-gateway-picker.service'])
print('Previous gateway credential revoked. Run icloud-cloud-credentials to view the new value privately.')
HELPER
cat > /usr/local/bin/icloud-status <<'HELPER'
#!/bin/bash
set -euo pipefail
systemctl is-active icloud-gateway-tailscale.service icloud-gateway-webdav.service icloud-gateway-picker.service
cat /home/icloud-gateway/.local/state/icloud-gateway/health.json
HELPER
grep -q 'restart icloud-gateway-picker.service' /etc/sudoers.d/icloud-gateway-reconnect || printf '%s\n' 'icloud-gateway ALL=(root) NOPASSWD: /usr/bin/systemctl restart icloud-gateway-picker.service' >> /etc/sudoers.d/icloud-gateway-reconnect
visudo -cf /etc/sudoers.d/icloud-gateway-reconnect
chmod 755 /usr/local/bin/icloud-rotate-gateway /usr/local/bin/icloud-status
'''
r=subprocess.run(['workbench','exec','-i',os.environ['ECS_INSTANCE_ID'],'--command',script],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True);print('Owner recovery/status/credential rotation helpers installed' if r.returncode==0 else r.stderr);raise SystemExit(r.returncode)
