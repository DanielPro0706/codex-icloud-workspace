#!/usr/bin/env python3
"""Scoped, restartable save queue. Credentials stay in the process environment.

The watcher runs in the Cloud task, not on ECS. VM suspension pauses it. Files,
immutable snapshots and queue state must remain available to resume that queue.
"""
import argparse
import contextlib
import errno
import fcntl
import json
import os
import pathlib
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import uuid

import workspace as w
from gateway import Gateway, UploadSessionError

P = pathlib.Path
MAX_FILE = 32 * 1024 * 1024
MAX_RETAINED = 256 * 1024 * 1024
GENERATED = {'.pdf', '.png', '.jpg', '.jpeg', '.webp', '.zip', '.docx', '.pptx', '.xlsx'}
INTERMEDIATE = {'.aux', '.log', '.toc', '.out', '.fls', '.fdb_latexmk', '.synctex', '.tmp', '.swp'}
TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}


def directory(path):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Symlinked queue paths are not supported')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def read_json(path, default=None):
    if path.is_symlink():
        raise ValueError('Symlinked queue state is not supported')
    if not path.exists() and default is not None:
        return default
    return json.loads(path.read_text())


def atomic_json(path, value):
    directory(path.parent)
    if path.is_symlink():
        raise ValueError('Symlinked queue state is not supported')
    temp = path.with_name(path.name + '.' + str(uuid.uuid4()) + '.tmp')
    with temp.open('x') as stream:
        os.chmod(temp, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def event(base, kind, **fields):
    path = directory(base/'autosave')/'events.jsonl'
    fd = os.open(path, os.O_CREAT|os.O_APPEND|os.O_WRONLY|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as stream:
        stream.write(json.dumps({'time': time.time(), 'event': kind, **fields}, ensure_ascii=False)+'\n')
        stream.flush()
        os.fsync(stream.fileno())


def validate_path(base, path):
    if not path or w.canonical(path) != path or '//' in path:
        raise ValueError('An exact relative file path is required')
    for part in P(path).parts:
        w.safe_file_name(part)
    target = w.local_target(base, path)
    if target.is_dir() or target.suffix in INTERMEDIATE or target.name.endswith('.synctex.gz'):
        raise ValueError('Only deliverable files can be watched')
    return target


def config(base):
    value = read_json(base/'autosave/config.json')
    if value['remote_folder'] != w.load_state(base)['remote_folder']:
        raise ValueError('Queue binding changed; no upload authorized')
    for path in value['paths']:
        validate_path(base, path)
    return value


@contextlib.contextmanager
def settings_lock(base):
    fd = os.open(directory(base/'autosave')/'settings.lock', os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def enable(base, paths, generated, authorized=False, settle=5):
    if not authorized:
        raise ValueError('User authorization for these exact destinations is required')
    if not paths and not generated:
        raise ValueError('Specify exact authorized files')
    if not 1 <= settle <= 300:
        raise ValueError('Stable-save delay must be between 1 and 300 seconds')
    with settings_lock(base):
        manifest = w.load_state(base)
        directory(base/'autosave')
        cfg = read_json(base/'autosave/config.json', {
            'version': 1, 'remote_folder': manifest['remote_folder'], 'paths': {}, 'ready': {}})
        if cfg['remote_folder'] != manifest['remote_folder']:
            raise ValueError('Queue belongs to another remote folder')
        for path in paths:
            target = validate_path(base, path)
            if target.suffix.lower() in GENERATED:
                raise ValueError('Generated deliverables require --generated and ready after validation')
            cfg['paths'][path] = 'save'
        for path in generated:
            validate_path(base, path)
            cfg['paths'][path] = 'generated'
        if len(cfg['paths']) > 1000:
            raise ValueError('Autosave scope exceeds 1000 files; narrow the task')
        cfg['settle_seconds'] = settle
        atomic_json(base/'autosave/config.json', cfg)
        atomic_json(base/'autosave/control.json', {'enabled': True})
        event(base, 'enabled', paths=list(paths), generated=list(generated))
    return status(base)


def pause(base):
    config(base)
    atomic_json(base/'autosave/control.json', {'enabled': False})
    event(base, 'paused')
    return {'enabled': False, 'in_flight': 'An already running file may finish; later files stay queued.'}


def ready(base, paths):
    with settings_lock(base):
        cfg = config(base)
        for path in paths:
            if cfg['paths'].get(path) != 'generated':
                raise ValueError('File is not an authorized generated deliverable: '+path)
            payload = read_stable(validate_path(base, path))
            cfg['ready'][path] = w.digest(payload)
        atomic_json(base/'autosave/config.json', cfg)
        event(base, 'generated-ready', paths=paths)
    return status(base)


def signature(path):
    stat = path.stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def read_stable(path):
    before = signature(path)
    if before[2] > MAX_FILE:
        raise ValueError('Per-file upload limit is 32 MiB')
    fd = os.open(path, os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        payload = stream.read(MAX_FILE+1)
    if signature(path) != before or len(payload) != before[2]:
        raise BlockingIOError('File is still being saved')
    return payload


def capacity(base, size):
    total = 0
    for path in (base/'autosave').rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlinked queue storage is not supported')
        if path.is_file():
            total += path.stat().st_size
    if total + size * 4 > MAX_RETAINED:
        raise ValueError('Retained queue storage limit reached; preserve files and review storage')
    if shutil.disk_usage(base).free < max(64*1024*1024, size*4):
        raise ValueError('Insufficient free disk space for safe writeback')


def retryable(error):
    if isinstance(error, w.WritebackError):
        return retryable(error.__cause__)
    if isinstance(error, urllib.error.HTTPError):
        return error.code in TRANSIENT_HTTP
    if isinstance(error, UploadSessionError):
        return error.state == 'failed' and (
            error.error in {'TimeoutError', 'ConnectionError', 'ConnectionResetError', 'RemoteDisconnected'}
            or error.error in {'upstream_read_http_'+str(n) for n in TRANSIENT_HTTP}
            or error.error in {'upstream_write_http_'+str(n) for n in TRANSIENT_HTTP}
            or error.error in {'upstream_put_http_'+str(n) for n in TRANSIENT_HTTP})
    if isinstance(error, urllib.error.URLError):
        return not isinstance(error.reason, (ValueError, ssl.SSLCertVerificationError))
    return isinstance(error, (TimeoutError, ConnectionError)) or (
        isinstance(error, OSError) and error.errno in {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ETIMEDOUT})


def error_report(error):
    if isinstance(error, w.WritebackError):
        return error.report()
    if isinstance(error, UploadSessionError):
        return {'type': type(error).__name__, 'state': error.state, 'stage': error.stage, 'code': error.error}
    if isinstance(error, urllib.error.HTTPError):
        return {'type': 'HTTP', 'status': error.code}
    # Do not log arbitrary upstream error text, URLs, headers or credentials.
    return {'type': type(error).__name__, 'reason': str(error) if isinstance(error, ValueError) else 'Operation did not complete'}


class QueueGateway(Gateway):
    def upload(self, remote, payload, expected_sha256=None, headers=None, progress=None):
        # Small automatic writes also get durable staging and server preflight.
        return super().upload(remote, payload, expected_sha256, headers, progress, resumable=True)


def load_job(base, job_id, path):
    if str(uuid.UUID(job_id)) != job_id:
        raise ValueError('Invalid queue job identifier')
    folder = base/'autosave/jobs'/job_id
    for parent in (folder, *folder.parents):
        if parent.is_symlink():
            raise ValueError('Symlinked queue storage is not supported')
    job = read_json(folder/'job.json')
    if job['id'] != job_id or job['path'] != path:
        raise ValueError('Queue job scope mismatch')
    return job


def retry(base, paths):
    with w.controller_lock(base):
        cfg = config(base)
        state = read_json(base/'autosave/state.json')
        for path in paths:
            if path not in cfg['paths']:
                raise ValueError('File is outside autosave authorization')
            info = state['files'].get(path, {})
            if not info.get('job_id'):
                continue
            job = load_job(base, info['job_id'], path)
            if job['state'] not in ('blocked', 'retry'):
                raise ValueError('Only stopped jobs can be explicitly retried')
            job.update(state='queued', retry_at=0)
            atomic_json(base/'autosave/jobs'/job['id']/'job.json', job)
            event(base, 'retry-requested', path=path, job_id=job['id'])
    return status(base)


def process_job(base, g, job, now):
    folder = base/'autosave/jobs'/job['id']
    snapshot = folder/'snapshot'
    path = job['path']
    try:
        manifest = w.load_state(base)
        if w.load_state(snapshot)['remote_folder'] != manifest['remote_folder']:
            raise ValueError('Snapshot remote scope differs from authorized controller')
        current = manifest['files'].get(path, {}).get('sha256')
        if current not in (job['before'], job['after']):
            raise ValueError('Controller baseline changed; queued version requires review')
        capacity(base, job['bytes'])
        job.update(state='uploading', attempts=job['attempts']+1, updated_at=now)
        atomic_json(folder/'job.json', job)
        proposed = w.plan(snapshot)
        if proposed['changes']:
            if len(proposed['changes']) != 1 or any(
                    change['path'] != path or change['before'] != job['before']
                    or change['after'] != job['after'] or change['action'] == 'trash'
                    for change in proposed['changes']):
                raise ValueError('Queued snapshot differs from the authorized immutable version')
            w.push(g, snapshot, True, proposed['plan_sha256'], progress=lambda item: event(
                base, 'transfer', job_id=job['id'], path=path, progress=item))
        else:
            # A process may have stopped after snapshot verification but before
            # updating the parent manifest. Reconfirm the remote on recovery.
            verified = w.download(g, w.join(manifest['remote_folder'], path),
                folder/'recovery'/str(uuid.uuid4())/'remote.bin', MAX_FILE)
            if verified['sha256'] != job['after']:
                raise ValueError('Remote changed after previous verification; review required')
        verified = w.load_state(snapshot)['files'].get(path)
        if not verified or verified['sha256'] != job['after']:
            raise ValueError('Snapshot verification is incomplete')
        manifest['files'][path] = verified
        w.save_state(base, manifest)
        job.update(state='synced', verified_at=time.time(), error=None)
        event(base, 'verified', path=path, job_id=job['id'], sha256=job['after'])
    except (ValueError, OSError) as error:
        retry = retryable(error)
        job.update(state='retry' if retry else 'blocked', error=error_report(error),
                   retry_at=now+min(300, 5*2**min(job['attempts'], 6)))
        event(base, job['state'], path=path, job_id=job['id'], error=job['error'])
    atomic_json(folder/'job.json', job)


def cycle(base, g, now=None):
    now = time.time() if now is None else now
    with w.controller_lock(base):
        cfg = config(base)
        if not read_json(base/'autosave/control.json')['enabled']:
            return {'paused': True}
        qpath = base/'autosave/state.json'
        state = read_json(qpath, {'version': 1, 'files': {}})
        manifest = w.load_state(base)
        # Capture all eligible files before processing one network job. This
        # keeps one writer and prevents an offline file from starving its peers.
        for path, mode in cfg['paths'].items():
            info = state['files'].setdefault(path, {})
            active = info.get('job_id')
            if active:
                job = load_job(base, active, path)
                if job['state'] != 'synced':
                    continue
                info.pop('job_id', None)
            try:
                target = validate_path(base, path)
                if not target.exists():
                    info.update(state='missing-local')
                    continue
                sig = signature(target)
                if info.get('signature') != sig:
                    info.update(signature=sig, since=now, state='settling')
                    continue
                if now-info['since'] < cfg['settle_seconds']:
                    continue
                if sig[2] > MAX_FILE:
                    raise ValueError('Per-file upload limit is 32 MiB')
                payload = read_stable(target)
                after = w.digest(payload)
                before = manifest['files'].get(path, {}).get('sha256')
                if after == before:
                    info.update(state='synced', sha256=after)
                    continue
                if mode == 'generated' and cfg['ready'].get(path) != after:
                    info.update(state='awaiting-ready', sha256=after)
                    continue
                capacity(base, len(payload))
                job_id = str(uuid.uuid4())
                folder = directory(base/'autosave/jobs'/job_id)
                snapshot = folder/'snapshot'
                destination = directory(snapshot/'files'/P(path).parent)/P(path).name
                with destination.open('xb') as stream:
                    os.chmod(destination, 0o600)
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                baseline = {} if before is None else {path: manifest['files'][path]}
                w.save_state(snapshot, {'version': 1, 'remote_folder': cfg['remote_folder'],
                                       'files': baseline, 'max_bytes': MAX_FILE, 'excluded': []})
                job = {'id': job_id, 'path': path, 'before': before, 'after': after, 'bytes': len(payload),
                       'state': 'queued', 'attempts': 0, 'created_at': now, 'retry_at': 0}
                atomic_json(folder/'job.json', job)
                info.update(job_id=job_id, state='queued')
                event(base, 'queued', job_id=job_id, path=path, sha256=after)
            except BlockingIOError:
                info.update(state='settling', since=now)
            except (ValueError, OSError) as error:
                info.update(state='blocked', error=error_report(error))
        atomic_json(qpath, state)
        candidates = []
        for path, info in state['files'].items():
            if path not in cfg['paths']:
                continue
            if info.get('job_id'):
                job = load_job(base, info['job_id'], path)
                if job['state'] in ('queued', 'uploading', 'retry') and job.get('retry_at', 0) <= now:
                    candidates.append(job)
        if candidates:
            job = min(candidates, key=lambda value: (value.get('retry_at', 0), value['created_at']))
            # Check pause again before beginning the network operation.
            if read_json(base/'autosave/control.json')['enabled']:
                process_job(base, g, job, now)
        atomic_json(base/'autosave/heartbeat.json', {'checked_at': time.time(), 'pid': os.getpid()})
    return status(base)


@contextlib.contextmanager
def worker_lock(base):
    fd = os.open(directory(base/'autosave')/'worker.lock', os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def worker_running(base):
    try:
        with worker_lock(base):
            return False
    except BlockingIOError:
        return True


def status(base):
    cfg = config(base)
    state = read_json(base/'autosave/state.json', {'files': {}})
    result = {}
    for path, mode in cfg['paths'].items():
        info = dict(state['files'].get(path, {'state': 'waiting-for-scan'}))
        if info.get('job_id'):
            job = load_job(base, info['job_id'], path)
            info.update({key: job[key] for key in ('state', 'attempts', 'retry_at', 'after') if key in job})
            if job['state'] == 'synced':
                info['sha256'] = job['after']
            if job.get('error'):
                info['error'] = job['error']
        target = validate_path(base, path)
        if not target.exists():
            info['local'] = 'missing'
            if info['state'] == 'synced':
                info['state'] = 'missing-local'
        elif info['state'] == 'missing-local':
            info['state'] = 'local-change-pending'
        elif info['state'] == 'awaiting-ready' and cfg['ready'].get(path) == info.get('sha256'):
            info['state'] = 'ready-pending'
        elif info['state'] == 'synced' and signature(target) != info.get('signature'):
            info['state'] = 'local-change-pending'
        info['mode'] = mode
        result[path] = info
    return {'controller': str(base), 'remote_folder': cfg['remote_folder'],
            'enabled': read_json(base/'autosave/control.json')['enabled'],
            'worker_running': worker_running(base), 'files': result,
            'heartbeat': read_json(base/'autosave/heartbeat.json', {}),
            'queue_directory': str(base/'autosave'),
            'all_synced': bool(result) and all(info['state'] == 'synced' for info in result.values())}


def watch(base, poll=2):
    with worker_lock(base):
        event(base, 'worker-started', pid=os.getpid())
        g = QueueGateway()
        while read_json(base/'autosave/control.json')['enabled']:
            try:
                cycle(base, g)
            except BlockingIOError:
                pass  # A manual fetch/push owns the controller; try later.
            except (ValueError, OSError) as error:
                event(base, 'worker-blocked', error=error_report(error))
                return 2
            time.sleep(poll)
        event(base, 'worker-paused', pid=os.getpid())
    return 0


def start(base):
    config(base)
    if not read_json(base/'autosave/control.json')['enabled']:
        return status(base)
    if not worker_running(base):
        # Validate credentials without logging them. They are inherited only,
        # never serialized into the queue, argv, config or reusable snapshot.
        QueueGateway()
        log = base/'autosave/worker.log'
        fd = os.open(log, os.O_CREAT|os.O_APPEND|os.O_WRONLY|os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'ab') as stream:
            process = subprocess.Popen([sys.executable, str(P(__file__).resolve()), 'watch', str(base)],
                stdin=subprocess.DEVNULL, stdout=stream, stderr=stream, start_new_session=True)
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            if worker_running(base) or process.poll() is not None:
                break
            time.sleep(0.1)
        if not worker_running(base):
            raise ValueError('Watcher did not start; inspect its retained log')
    return status(base)


def wait(base, timeout=600):
    if timeout <= 0 or timeout > 3600:
        raise ValueError('Wait timeout must be between 1 and 3600 seconds')
    start(base)
    deadline = time.monotonic()+timeout
    while True:
        report = status(base)
        if report['all_synced']:
            return report
        if not report['enabled']:
            raise ValueError('Autosave is paused; pending files remain local')
        if any(info['state'] in ('blocked', 'awaiting-ready', 'missing-local') for info in report['files'].values()):
            raise ValueError('Queue needs attention; inspect autosave status before claiming writeback')
        if not report['worker_running']:
            raise ValueError('Watcher stopped; inspect retained worker log and restart')
        if time.monotonic() >= deadline:
            raise TimeoutError('Autosave wait timed out; worker and pending files are retained')
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('enable', 'ready', 'retry', 'start', 'watch', 'once', 'status', 'pause', 'wait'):
        command = sub.add_parser(name)
        command.add_argument('controller', type=P)
        if name == 'enable':
            command.add_argument('--path', action='append', default=[])
            command.add_argument('--generated', action='append', default=[])
            command.add_argument('--authorized', action='store_true')
            command.add_argument('--settle', type=float, default=5)
        if name in ('ready', 'retry'):
            command.add_argument('paths', nargs='+')
        if name == 'wait':
            command.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args()
    base = args.controller.resolve()
    if args.command == 'enable':
        enable(base, args.path, args.generated, args.authorized, args.settle)
        result = start(base)
    elif args.command == 'ready':
        ready(base, args.paths)
        result = start(base)
    elif args.command == 'retry':
        retry(base, args.paths)
        result = start(base)
    elif args.command == 'watch':
        sys.exit(watch(base))
    elif args.command == 'once':
        result = cycle(base, QueueGateway())
    elif args.command == 'wait':
        result = wait(base, args.timeout)
    else:
        result = globals()[args.command](base)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        print(json.dumps({'error': error_report(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
