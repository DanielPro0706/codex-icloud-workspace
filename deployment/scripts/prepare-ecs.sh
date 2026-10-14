#!/usr/bin/env bash
set -euo pipefail
# Run via existing Workbench administration. Does not alter existing services.
getent passwd icloud-gateway >/dev/null || useradd --create-home --shell /bin/bash icloud-gateway
install -d -o icloud-gateway -g icloud-gateway -m 700 /home/icloud-gateway/.config/rclone /home/icloud-gateway/.ssh /home/icloud-gateway/.local/bin /home/icloud-gateway/install
runuser -u icloud-gateway -- bash <<'USER'
set -euo pipefail
umask 077
cd /home/icloud-gateway/install
v=v1.75.2
file=rclone-${v}-linux-amd64.zip
if [ ! -x /home/icloud-gateway/.local/bin/rclone ]; then
 curl -fS --connect-timeout 10 --max-time 180 "https://downloads.rclone.org/${v}/${file}" -o "$file"
 curl -fsS --connect-timeout 10 --max-time 30 "https://downloads.rclone.org/${v}/SHA256SUMS" -o SHA256SUMS
 grep -E "^[a-f0-9]{64}  ${file}$" SHA256SUMS | sha256sum --check --status
 python3 - "$file" <<'PY'
import zipfile,sys,pathlib
name='rclone-v1.75.2-linux-amd64/rclone'
p=pathlib.Path('/home/icloud-gateway/.local/bin/rclone')
with zipfile.ZipFile(sys.argv[1]) as z: p.write_bytes(z.read(name))
p.chmod(0o700)
PY
fi
/home/icloud-gateway/.local/bin/rclone version
/home/icloud-gateway/.local/bin/rclone help backend iclouddrive
USER
