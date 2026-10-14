#!/usr/bin/env bash
# Run during setup/maintenance, not at the start of ordinary file tasks.
# Read the Cloud runtime/networking guidance before network-dependent commands.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cloud_root="${CODEX_PORTABLE_CLOUD_ROOT:-/workspace}"
cd "$repo_dir"
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
test -z "$(git status --porcelain --untracked-files=no)"
mkdir -p "$cloud_root/tools/bin" "$cloud_root/retained"
CODEX_PORTABLE_CLOUD_ROOT="$cloud_root" python3 - <<'PY'
import hashlib, os, pathlib, tarfile, urllib.request
root = pathlib.Path(os.environ['CODEX_PORTABLE_CLOUD_ROOT']) / 'tools'
archive = root / 'go1.23.12.linux-amd64.tar.gz'
expected = 'd3847fef834e9db11bf64e3fb34db9c04db14e068eeb064f49af747010454f90'
if not archive.exists():
    # Preserve partial downloads for diagnosis, and never replace a different archive.
    import uuid
    candidate = root / ('go-download-' + uuid.uuid4().hex + '.tgz')
    with urllib.request.urlopen('https://dl.google.com/go/go1.23.12.linux-amd64.tar.gz', timeout=60) as source:
        with candidate.open('xb') as target:
            import shutil
            shutil.copyfileobj(source, target)
    if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected:
        raise SystemExit('Go archive checksum mismatch; candidate preserved')
    candidate.rename(archive)
if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
    raise SystemExit('Existing Go archive differs; preserved for review')
if not (root / 'go/bin/go').exists():
    if (root / 'go').exists():
        raise SystemExit('Existing partial Go directory preserved; review before installation')
    if not hasattr(tarfile, 'data_filter'):
        raise SystemExit('A Python release with tarfile data-filter support is required')
    with tarfile.open(archive) as bundle:
        bundle.extractall(root, filter='data')
PY
export PATH="$cloud_root/tools/go/bin:$cloud_root/tools/bin:$PATH"
export GOCACHE="$cloud_root/.cache/go-build" GOPATH="$cloud_root/.cache/gopath" GOTOOLCHAIN=local
test "$(go version)" = "go version go1.23.12 linux/amd64"
python3 scripts/portable_sync.py verify --bundle snapshot
python3 scripts/cloud_bootstrap.py --cloud-root "$cloud_root"
python3 scripts/cloud_doctor.py --cloud-root "$cloud_root" --publication --dependencies
python3 -m unittest discover -s tests
cd gateway-ui/webpush-helper
go mod download
go mod verify
go test -mod=readonly ./...
retained_build="$(mktemp -d "$cloud_root/retained/cloud-install.XXXXXXXX")"
if test -f "$cloud_root/tools/bin/webpush-helper"; then
    cp -p "$cloud_root/tools/bin/webpush-helper" "$retained_build/webpush-helper.before"
fi
go build -mod=readonly -o "$cloud_root/tools/bin/webpush-helper" .
echo "Setup checks passed. This does not publish the environment or prove VPN connectivity."
