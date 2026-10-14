
# Historical deployment sequence: review docs before applying to your own server.
import os
if os.environ.get('REFERENCE_DEPLOY_ALLOWED') != '1':
 raise SystemExit('Read deployment/reference/README.md; explicit REFERENCE_DEPLOY_ALLOWED=1 required')
if not os.environ.get('ECS_INSTANCE_ID'):
 raise SystemExit('ECS_INSTANCE_ID must identify your own authorized server')
import pathlib,subprocess,base64
code=pathlib.Path('deployment/reference/health-check.py').read_bytes()
script="""set -euo pipefail
install -d -m 755 /usr/local/libexec
install -d -m 700 -o icloud-gateway -g icloud-gateway /home/icloud-gateway/.local/state/icloud-gateway
python3 - <<'WRITE'
import pathlib,base64
p=pathlib.Path('/usr/local/libexec/icloud-gateway-health.py');p.write_bytes(base64.b64decode('"""+base64.b64encode(code).decode()+"""'));p.chmod(0o755)
WRITE
cat > /etc/systemd/system/icloud-gateway-health.service <<'UNIT'
[Unit]
Description=Read-only iCloud authentication health check
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
User=icloud-gateway
Group=icloud-gateway
ExecStart=/usr/bin/python3 /usr/local/libexec/icloud-gateway-health.py
Environment=XDG_CACHE_HOME=/var/cache/icloud-gateway
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/icloud-gateway/.config/rclone /home/icloud-gateway/.local/state/icloud-gateway /var/cache/icloud-gateway
PrivateTmp=yes
PrivateDevices=yes
TimeoutStartSec=90
MemoryMax=256M
UNIT
cat > /etc/systemd/system/icloud-gateway-health.timer <<'UNIT'
[Unit]
Description=Check iCloud authentication twice daily
[Timer]
OnCalendar=*-*-* 01,13:00:00 UTC
RandomizedDelaySec=10m
Persistent=true
Unit=icloud-gateway-health.service
[Install]
WantedBy=timers.target
UNIT
cat > /etc/sudoers.d/icloud-gateway-reconnect <<'SUDO'
icloud-gateway ALL=(root) NOPASSWD: /usr/bin/systemctl restart icloud-gateway-webdav.service
SUDO
chmod 440 /etc/sudoers.d/icloud-gateway-reconnect
visudo -cf /etc/sudoers.d/icloud-gateway-reconnect
cat > /usr/local/bin/icloud-reconnect <<'HELPER'
#!/bin/bash
set -euo pipefail
test "$(id -un)" = icloud-gateway
test -t 0 && test -t 1 || { echo 'Use your own interactive SSH terminal'; exit 1; }
umask 077
unset HISTFILE
/home/icloud-gateway/.local/bin/rclone-cn9399 --config /home/icloud-gateway/.config/rclone/rclone-cn.conf config reconnect Codex:
/home/icloud-gateway/.local/bin/rclone-cn9399 --config /home/icloud-gateway/.config/rclone/rclone-cn.conf lsf Codex: --max-depth 1 --dirs-only >/dev/null
sudo -n /usr/bin/systemctl restart icloud-gateway-webdav.service
echo 'Apple authentication and root read verified; gateway restarted.'
HELPER
chmod 755 /usr/local/bin/icloud-reconnect
systemd-analyze verify /etc/systemd/system/icloud-gateway-health.service /etc/systemd/system/icloud-gateway-health.timer
systemctl daemon-reload
systemctl enable --now icloud-gateway-health.timer
systemctl start icloud-gateway-health.service
cat /home/icloud-gateway/.local/state/icloud-gateway/health.json
"""
r=subprocess.run(['workbench','exec','-i',os.environ['ECS_INSTANCE_ID'],'--command',script,'--timeout','120'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True);pathlib.Path('work/deployment-evidence/health-install.txt').write_text(r.stdout+r.stderr);print(r.stdout+r.stderr);raise SystemExit(r.returncode)
