#!/usr/bin/env bash
set -euo pipefail
# Run with Go 1.26.9 available on PATH. Keep module/build caches outside portable snapshots.
bundle=$(cd "$(dirname "$0")/.." && pwd)
source_dir=${1:?Supply a new or existing rclone v1.75.2 source checkout}
if [ ! -d "$source_dir/.git" ]; then
 git clone --depth 1 --branch v1.75.2 https://github.com/rclone/rclone.git "$source_dir"
fi
test "$(git -C "$source_dir" rev-parse HEAD)" = "$(git -C "$source_dir" rev-parse v1.75.2^{commit})"
if git -C "$source_dir" diff --quiet; then
 git -C "$source_dir" apply --check "$bundle/patches/rclone-v1.75.2-china.patch"
 git -C "$source_dir" apply "$bundle/patches/rclone-v1.75.2-china.patch"
else
 python3 - "$source_dir" "$bundle/patches/rclone-v1.75.2-china.patch" <<'PYVERIFY'
import pathlib,subprocess,sys
actual=subprocess.check_output(['git','-C',sys.argv[1],'diff'])
assert actual==pathlib.Path(sys.argv[2]).read_bytes(), 'Existing source changes differ from the reviewed patch'
PYVERIFY
fi
cp "$bundle/patches/region_test.go" "$source_dir/backend/iclouddrive/api/region_test.go"
go -C "$source_dir" test ./backend/iclouddrive/... -count=1
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go -C "$source_dir" build -trimpath -ldflags '-s -w -X github.com/rclone/rclone/fs.Version=v1.75.2-cn9399-local.1' -o rclone-cn9399 .
