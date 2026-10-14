#!/bin/zsh
unset HISTFILE
SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)
exec ssh -t -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$SCRIPT_DIR/ssh-known-hosts" -o IdentitiesOnly=yes -i "$HOME/.ssh/id_ed25519" "icloud-gateway@${ICLOUD_SSH_HOST:?Set your own verified gateway SSH hostname}" '/home/icloud-gateway/.local/bin/icloud-browser-credentials'
