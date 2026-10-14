#!/bin/zsh
unset HISTFILE
SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)
exec ssh -t -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$SCRIPT_DIR/ssh-known-hosts" -o IdentitiesOnly=yes -i "$HOME/.ssh/id_ed25519" "icloud-gateway@${ICLOUD_SSH_HOST:?Set your own verified gateway SSH hostname}" 'umask 077; unset HISTFILE; /home/icloud-gateway/.local/bin/rclone-cn9399 --config /home/icloud-gateway/.config/rclone/rclone-cn.conf config reconnect Codex:'
