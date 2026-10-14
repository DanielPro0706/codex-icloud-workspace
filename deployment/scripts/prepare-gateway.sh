#!/usr/bin/env bash
set -euo pipefail
# Never start a server before authenticated read-only verification passes.
runuser -u icloud-gateway -- /home/icloud-gateway/.local/bin/rclone-cn9399 --config /home/icloud-gateway/.config/rclone/rclone-cn.conf lsf Codex: --max-depth 1 --dirs-only --retries 1 --low-level-retries 1 --timeout 30s >/dev/null
install -d -m 700 -o icloud-gateway -g icloud-gateway /home/icloud-gateway/.config /home/icloud-gateway/.local /home/icloud-gateway/.local/state /home/icloud-gateway/.config/icloud-gateway
runuser -u icloud-gateway -- python3 - <<'PYGEN'
import pathlib,secrets,os
p=pathlib.Path('/home/icloud-gateway/.config/icloud-gateway');p.mkdir(mode=0o700,parents=True,exist_ok=True)
f=p/'webdav.env'
if not f.exists():
 fd=os.open(str(f),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as stream:stream.write('RCLONE_USER=codex-gateway\nRCLONE_PASS='+secrets.token_urlsafe(32)+'\n')
print('Independent gateway credential present; value not displayed')
PYGEN
unit=/etc/systemd/system/icloud-gateway-webdav.service
if [ ! -e "$unit" ]; then
cat > "$unit" <<'UNIT'
[Unit]
Description=Private iCloud Drive WebDAV gateway
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=3600
StartLimitBurst=3
[Service]
User=icloud-gateway
Group=icloud-gateway
EnvironmentFile=/home/icloud-gateway/.config/icloud-gateway/webdav.env
ExecStart=/home/icloud-gateway/.local/bin/rclone-cn9399 serve webdav Codex: --config /home/icloud-gateway/.config/rclone/rclone-cn.conf --addr 127.0.0.1:18765 --dir-cache-time 30s --log-level ERROR
Restart=on-failure
RestartSec=300
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/icloud-gateway/.config/rclone
CacheDirectory=icloud-gateway
Environment=XDG_CACHE_HOME=/var/cache/icloud-gateway
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
MemoryMax=512M
CPUQuota=50%
LogRateLimitIntervalSec=30s
LogRateLimitBurst=50
[Install]
WantedBy=multi-user.target
UNIT
fi
systemd-analyze verify "$unit"
systemctl daemon-reload
systemctl enable --now icloud-gateway-webdav.service
systemctl is-active icloud-gateway-webdav.service
