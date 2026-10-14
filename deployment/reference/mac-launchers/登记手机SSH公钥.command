#!/bin/zsh
set -euo pipefail
unset HISTFILE
SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)
echo '请先在手机 SSH 客户端生成 ED25519 密钥，只复制公钥。'
echo '此窗口会连接已有 ECS；Mac SSH 私钥口令只在自己的终端输入。'
exec ssh -t -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$SCRIPT_DIR/ssh-known-hosts" -o IdentitiesOnly=yes -i "$HOME/.ssh/id_ed25519" "icloud-gateway@${ICLOUD_SSH_HOST:?Set your own verified gateway SSH hostname}" '/home/icloud-gateway/.local/bin/icloud-register-phone-key'
