#!/usr/bin/env python3

# Historical deployment sequence: review docs before applying to your own server.
import os
if os.environ.get('REFERENCE_DEPLOY_ALLOWED') != '1':
 raise SystemExit('Read deployment/reference/README.md; explicit REFERENCE_DEPLOY_ALLOWED=1 required')
if not os.environ.get('ECS_INSTANCE_ID'):
 raise SystemExit('ECS_INSTANCE_ID must identify your own authorized server')
import pathlib,base64,subprocess,sys
payload=base64.b64encode(pathlib.Path(sys.argv[1]).read_bytes()).decode()
script=r'''set -euo pipefail
runuser -u icloud-gateway -- python3 - <<'CHECK'
import pathlib,urllib.request,urllib.error,base64
p=pathlib.Path('/home/icloud-gateway/.config/icloud-gateway/webdav.env');e=dict(x.split('=',1) for x in p.read_text().splitlines());auth='Basic '+base64.b64encode((e['RCLONE_USER']+':'+e['RCLONE_PASS']).encode()).decode()
try:
 urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:18765/__codex_gateway_v1__/',method='PROPFIND',headers={'Authorization':auth,'Depth':'0'}),timeout=30)
except urllib.error.HTTPError as x:
 if x.code!=404:raise
else:raise SystemExit('Reserved route conflicts with an existing iCloud path; stopped')
CHECK
install -d -m 755 /opt/icloud-gateway/ui
python3 - <<'WRITE'
import pathlib,base64
p=pathlib.Path('/opt/icloud-gateway/ui/selection_api.py');p.write_bytes(base64.b64decode('''+repr(payload)+r'''));p.chmod(0o755)
compile(p.read_text(),str(p),'exec')
WRITE
cat > /etc/systemd/system/icloud-gateway-picker.service <<'UNIT'
[Unit]
Description=Private iCloud folder selection for future Cloud tasks
After=icloud-gateway-webdav.service
Wants=icloud-gateway-webdav.service
[Service]
DynamicUser=yes
User=icloud-picker
EnvironmentFile=/home/icloud-gateway/.config/icloud-gateway/webdav.env
StateDirectory=icloud-gateway-picker
StateDirectoryMode=0700
ExecStart=/usr/bin/python3 /opt/icloud-gateway/ui/selection_api.py
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
MemoryMax=128M
[Install]
WantedBy=multi-user.target
UNIT
systemd-analyze verify /etc/systemd/system/icloud-gateway-picker.service
systemctl daemon-reload
systemctl enable --now icloud-gateway-picker.service
systemctl is-active icloud-gateway-picker.service
runuser -u icloud-gateway -- /opt/icloud-gateway/tailscale/1.104.1/tailscale --socket=/run/icloud-gateway-tailscale/tailscaled.sock serve --bg --https=443 --set-path=/__codex_gateway_v1__ http://127.0.0.1:18767
'''
r=subprocess.run(['workbench','exec','-i',os.environ['ECS_INSTANCE_ID'],'--command',script,'--timeout','60'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True);print(r.stdout+r.stderr);sys.exit(r.returncode)
