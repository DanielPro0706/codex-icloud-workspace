#!/usr/bin/env python3
"""Apple reauthentication in the owner's terminal, with protected recovery backup."""
import datetime
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import uuid

BASE = pathlib.Path('/home/icloud-gateway')


def reconnect(base, run=subprocess.run):
    config = base / '.config/rclone/rclone-cn.conf'
    info = config.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('Unexpected authentication file owner or type; stopped')
    if info.st_mode & 0o077:
        raise ValueError('Authentication file must have private permissions; stopped')
    folder = base / '.local/state/icloud-gateway/auth-backups'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.is_symlink() or folder.stat().st_uid != os.getuid():
        raise ValueError('Unsafe backup directory; stopped')
    folder.chmod(0o700)
    backup = folder / ('rclone-cn-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + str(uuid.uuid4()) + '.conf')
    with backup.open('xb') as output, config.open('rb') as source:
        backup.chmod(0o600)
        shutil.copyfileobj(source, output)
    print('Protected authentication backup saved:', backup)
    rclone = [str(base / '.local/bin/rclone-cn9399'), '--config', str(config)]
    if run(rclone + ['config', 'reconnect', 'Codex:']).returncode:
        print('Apple reauthentication did not complete; gateway was not restarted.')
        return 1
    check = run(rclone + ['lsf', 'Codex:', '--max-depth', '1', '--dirs-only'],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if check.returncode:
        print('Apple root-read verification failed; gateway was not restarted.')
        return 1
    if run(['sudo', '-n', '/usr/bin/systemctl', 'restart', 'icloud-gateway-webdav.service']).returncode:
        print('Apple root read passed, but gateway restart failed. Run icloud-status.')
        return 1
    health = run(['/usr/bin/python3', '/usr/local/libexec/icloud-gateway-health.py'])
    if health.returncode:
        print('Gateway restarted; immediate health/notification check needs attention. Run icloud-status.')
        return 1
    print('Apple authentication, root read and immediate health check passed.')
    return 0


def main():
    if os.getuid() != 1000 or not all(s.isatty() for s in (sys.stdin, sys.stdout, sys.stderr)):
        raise SystemExit('Use your own private gateway-account SSH terminal; no redirected output')
    os.umask(0o077)
    os.environ.pop('HISTFILE', None)
    try:
        return reconnect(BASE)
    except (OSError, ValueError):
        print('Reauthentication helper could not complete; existing backups are retained. Run icloud-status.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
