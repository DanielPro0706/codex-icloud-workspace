#!/usr/bin/env bash
set -euo pipefail
v=1.104.1
base=/opt/icloud-gateway/tailscale/$v
if [ ! -x "$base/tailscaled" ]; then
 install -d -m 755 "$base"
 runuser -u icloud-gateway -- bash -c 'cd /home/icloud-gateway/install && curl -fsS --connect-timeout 10 --max-time 180 https://pkgs.tailscale.com/stable/tailscale_1.104.1_amd64.tgz -o tailscale_1.104.1_amd64.tgz && printf "%s\n" "108d1d96ecf410d305571e173516f27038f870919a9b89c914a167c6d33a4528  tailscale_1.104.1_amd64.tgz" | sha256sum --check --status'
 tar -xzf /home/icloud-gateway/install/tailscale_${v}_amd64.tgz --strip-components=1 -C "$base" tailscale_${v}_amd64/tailscale tailscale_${v}_amd64/tailscaled
 chmod 755 "$base/tailscale" "$base/tailscaled"
fi
unit=/etc/systemd/system/icloud-gateway-tailscale.service
if [ ! -e "$unit" ]; then
 cat > "$unit" <<'EOF'
[Unit]
Description=Private iCloud gateway Tailscale (isolated userspace networking)
Wants=network-online.target
After=network-online.target

[Service]
User=icloud-gateway
Group=icloud-gateway
StateDirectory=icloud-gateway-tailscale
StateDirectoryMode=0700
RuntimeDirectory=icloud-gateway-tailscale
RuntimeDirectoryMode=0700
ExecStart=/opt/icloud-gateway/tailscale/1.104.1/tailscaled --tun=userspace-networking --state=/var/lib/icloud-gateway-tailscale/state --statedir=/var/lib/icloud-gateway-tailscale --socket=/run/icloud-gateway-tailscale/tailscaled.sock
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
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
LogRateLimitIntervalSec=30s
LogRateLimitBurst=100

[Install]
WantedBy=multi-user.target
EOF
fi
systemd-analyze verify "$unit"
systemctl daemon-reload
systemctl enable --now icloud-gateway-tailscale.service
systemctl is-active icloud-gateway-tailscale.service
"$base/tailscale" version
