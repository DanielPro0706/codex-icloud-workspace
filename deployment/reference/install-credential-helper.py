
# Historical deployment sequence: review docs before applying to your own server.
import os
if os.environ.get('REFERENCE_DEPLOY_ALLOWED') != '1':
 raise SystemExit('Read deployment/reference/README.md; explicit REFERENCE_DEPLOY_ALLOWED=1 required')
if not os.environ.get('ECS_INSTANCE_ID'):
 raise SystemExit('ECS_INSTANCE_ID must identify your own authorized server')
import subprocess
s=r'''set -euo pipefail
cat > /usr/local/bin/icloud-cloud-credentials <<'HELPER'
#!/usr/bin/python3
import sys,pathlib,base64
if not (sys.stdin.isatty() and sys.stdout.isatty()):
 raise SystemExit('Use your own private SSH terminal; no redirected output')
p=pathlib.Path('/home/icloud-gateway/.config/icloud-gateway/webdav.env')
e=dict(line.split('=',1) for line in p.read_text().splitlines())
value='Basic '+base64.b64encode((e['RCLONE_USER']+':'+e['RCLONE_PASS']).encode()).decode()
print('Gateway URL: https://gateway.example.ts.net/')
print('Cloud Network secret key: ICLOUD_GATEWAY_AUTHORIZATION')
print('Allowed domain: gateway.example.ts.net')
print('Copy the next line into the Cloud Network secret value; do not paste it into chat:')
print(value)
HELPER
chmod 755 /usr/local/bin/icloud-cloud-credentials
'''
r=subprocess.run(['workbench','exec','-i',os.environ['ECS_INSTANCE_ID'],'--command',s],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True);print('Credential helper installed' if r.returncode==0 else r.stderr);raise SystemExit(r.returncode)
