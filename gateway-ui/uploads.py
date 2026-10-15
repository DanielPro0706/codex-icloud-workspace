#!/usr/bin/env python3
"""Bounded, resumable uploads behind the existing gateway Basic authentication.

Python 3.6+. No public listener, credential storage, deletion or arbitrary upstream.
Parts and prior remote versions are retained under the service StateDirectory.
"""
import hashlib
import http.client
import json
import os
import pathlib
import re
import shutil
import threading
import time
import urllib.parse
import uuid
import xml.etree.ElementTree as ET

CHUNK_BYTES = 32768
MAX_BYTES = 32 * 1024 * 1024
RETAINED_QUOTA = 1024 * 1024 * 1024
SENSITIVE = {'auth.json', 'rclone.conf', 'rclone-cn.conf', 'id_rsa', 'id_ed25519'}


class UploadFault(ValueError):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


def valid_hash(value, nullable=False):
    return (nullable and value is None) or (isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None)


def valid_remote(value):
    if not isinstance(value, str) or not value or len(value.encode('utf-8')) > 2048:
        raise UploadFault('invalid_remote')
    parts = value.split('/')
    if any(p in ('', '.', '..') for p in parts) or '\\' in value or any(ord(c) < 32 for c in value):
        raise UploadFault('invalid_remote')
    if parts[0] == '__codex_gateway_v1__':
        raise UploadFault('reserved_remote')
    if any(p in SENSITIVE or p.startswith('.env') or p.endswith(('.pem', '.key')) for p in parts):
        raise UploadFault('credential_file_requires_separate_handling')
    return value


def atomic_json(path, value):
    temp = path.with_name(path.name + '.' + str(uuid.uuid4()) + '.tmp')
    with temp.open('x') as stream:
        os.chmod(str(temp), 0o600)
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temp), str(path))


class WebDAVBackend:
    """Use the existing loopback service; never accept a caller-supplied URL."""
    def __init__(self, authorization):
        self.authorization = authorization

    def request(self, method, remote, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', 18765, timeout=180)
        values = {'Authorization': self.authorization, 'Connection': 'close'}
        values.update(headers or {})
        try:
            connection.request(method, '/' + urllib.parse.quote(remote, safe='/'), body, values)
            return connection, connection.getresponse()
        except Exception:
            connection.close()
            raise

    def read(self, remote, target):
        connection, response = self.request('GET', remote)
        try:
            if response.status == 404:
                return None
            if response.status != 200:
                raise UploadFault('upstream_read_http_' + str(response.status), 502)
            digest, count = hashlib.sha256(), 0
            with target.open('xb') as stream:
                os.chmod(str(target), 0o600)
                while True:
                    block = response.read(CHUNK_BYTES)
                    if not block:
                        break
                    count += len(block)
                    if count > MAX_BYTES:
                        raise UploadFault('remote_backup_exceeds_limit', 409)
                    stream.write(block)
                    digest.update(block)
            return {'sha256': digest.hexdigest(), 'bytes': count}
        finally:
            connection.close()

    def put(self, remote, source):
        parts = remote.split('/')
        for index in range(1, len(parts)):
            directory = '/'.join(parts[:index])
            connection, response = self.request('MKCOL', directory)
            status = response.status
            response.read(4096)
            connection.close()
            if status == 405:
                connection, response = self.request('PROPFIND', directory, headers={'Depth': '0'})
                try:
                    data = response.read(1000001)
                    if response.status != 207 or len(data) > 1000000 or ET.fromstring(data).find('.//{DAV:}collection') is None:
                        raise UploadFault('parent_is_not_directory', 409)
                finally:
                    connection.close()
            elif status != 201:
                raise UploadFault('upstream_mkdir_http_' + str(status), 502)
        with source.open('rb') as stream:
            connection, response = self.request('PUT', remote, stream,
                {'Content-Type': 'application/octet-stream', 'Content-Length': str(source.stat().st_size)})
            try:
                if response.status not in (200, 201, 204):
                    raise UploadFault('upstream_write_http_' + str(response.status), 502)
                response.read(4096)
            finally:
                connection.close()


class UploadStore:
    def __init__(self, root, backend):
        self.root, self.backend = pathlib.Path(root), backend
        self.guard = threading.RLock()
        self.locks, self.jobs, self.targets = {}, {}, {}
        self.worker_limit = threading.Semaphore(1)

    def folder(self, upload_id):
        try:
            if str(uuid.UUID(upload_id)) != upload_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise UploadFault('invalid_upload_id')
        if self.root.is_symlink() or (self.root/upload_id).is_symlink():
            raise UploadFault('unsafe_storage', 409)
        return self.root/upload_id

    def lock(self, upload_id):
        self.folder(upload_id)
        with self.guard:
            return self.locks.setdefault(upload_id, threading.RLock())

    def load(self, upload_id):
        path = self.folder(upload_id)/'state.json'
        if path.is_symlink():
            raise UploadFault('unsafe_storage', 409)
        if not path.is_file():
            raise UploadFault('upload_not_found', 404)
        return json.loads(path.read_text())

    def save(self, upload_id, state):
        state['updated_at'] = time.time()
        atomic_json(self.folder(upload_id)/'state.json', state)

    def public(self, state):
        return {key: state.get(key) for key in ('upload_id', 'remote', 'bytes', 'sha256',
            'expected_sha256', 'state', 'stage', 'error', 'chunk_bytes', 'received', 'updated_at')}

    def status(self, upload_id):
        with self.lock(upload_id):
            return self.public(self.load(upload_id))

    def begin(self, intent):
        if not isinstance(intent, dict):
            raise UploadFault('invalid_intent')
        upload_id = intent.get('upload_id')
        folder = self.folder(upload_id)
        remote = valid_remote(intent.get('remote'))
        size = intent.get('bytes')
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_BYTES:
            raise UploadFault('invalid_size')
        if not valid_hash(intent.get('sha256')) or 'expected_sha256' not in intent or not valid_hash(intent['expected_sha256'], True):
            raise UploadFault('invalid_hash')
        wanted = {key: intent[key] for key in ('upload_id', 'remote', 'bytes', 'sha256', 'expected_sha256')}
        with self.guard, self.lock(upload_id):
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if (folder/'state.json').exists():
                state = self.load(upload_id)
                if any(state[key] != value for key, value in wanted.items()):
                    raise UploadFault('upload_intent_changed', 409)
                return self.public(state)
            # Nothing is silently cleaned up. Refuse new sessions when retained data needs maintenance.
            reserved = sum(json.loads(p.read_text()).get('bytes', 0) for p in self.root.glob('*/state.json'))
            if reserved + size > RETAINED_QUOTA or shutil.disk_usage(str(self.root)).free < size*3 + 100*1024*1024:
                raise UploadFault('retained_storage_full', 507)
            folder.mkdir(mode=0o700)
            state = dict(wanted, state='receiving', stage='chunks', error=None,
                         chunk_bytes=CHUNK_BYTES, received=[])
            self.save(upload_id, state)
            return self.public(state)

    def chunk(self, upload_id, index, body):
        with self.lock(upload_id):
            state = self.load(upload_id)
            if not isinstance(index, int) or index < 0 or index*CHUNK_BYTES >= state['bytes']:
                raise UploadFault('invalid_chunk_index')
            expected = min(CHUNK_BYTES, state['bytes'] - index*CHUNK_BYTES)
            if len(body) != expected:
                raise UploadFault('invalid_chunk_size')
            part = self.folder(upload_id)/('part-%06d.bin' % index)
            if part.is_symlink():
                raise UploadFault('unsafe_storage', 409)
            if part.exists():
                if part.read_bytes() != body:
                    raise UploadFault('chunk_changed', 409)
            else:
                if state['state'] != 'receiving':
                    raise UploadFault('upload_not_receiving', 409)
                temp = part.with_name(part.name + '.' + str(uuid.uuid4()) + '.tmp')
                with temp.open('xb') as stream:
                    os.chmod(str(temp), 0o600)
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(str(temp), str(part))
            if index not in state['received']:
                state['received'] = sorted(state['received'] + [index])
                self.save(upload_id, state)
            return {'upload_id': upload_id, 'index': index, 'bytes': len(body),
                    'sha256': hashlib.sha256(body).hexdigest()}

    def commit(self, upload_id, background=True):
        with self.lock(upload_id):
            state = self.load(upload_id)
            count = (state['bytes'] + CHUNK_BYTES - 1)//CHUNK_BYTES
            if state['received'] != list(range(count)):
                raise UploadFault('missing_chunks', 409)
            if self.jobs.get(upload_id):
                return self.public(state)
            # Even a previously verified upload rechecks the remote before confirming a retry.
            state.update(state='committing', stage='queued', error=None)
            self.save(upload_id, state)
            self.jobs[upload_id] = True
        if background:
            worker = threading.Thread(target=self.finish, args=(upload_id,))
            worker.daemon = True
            worker.start()
        else:
            self.finish(upload_id)
        return self.status(upload_id)

    def finish(self, upload_id):
        folder = self.folder(upload_id)
        stage = 'assemble'
        try:
            with self.worker_limit:
                state = self.load(upload_id)
                assembled = folder/'assembled.bin'
                if assembled.is_symlink():
                    raise UploadFault('unsafe_storage', 409)
                target = assembled if assembled.exists() else folder/('assembling-' + str(uuid.uuid4()) + '.bin')
                digest, total = hashlib.sha256(), 0
                if target == assembled:
                    with assembled.open('rb') as stream:
                        for block in iter(lambda: stream.read(CHUNK_BYTES), b''):
                            digest.update(block)
                            total += len(block)
                else:
                    with target.open('xb') as stream:
                        os.chmod(str(target), 0o600)
                        for index in state['received']:
                            part = folder/('part-%06d.bin' % index)
                            if part.is_symlink():
                                raise UploadFault('unsafe_storage', 409)
                            block = part.read_bytes()
                            stream.write(block)
                            digest.update(block)
                            total += len(block)
                if total != state['bytes'] or digest.hexdigest() != state['sha256']:
                    raise UploadFault('assembled_hash_mismatch', 409)
                if target != assembled:
                    os.rename(str(target), str(assembled))
                with self.guard:
                    target_lock = self.targets.setdefault(state['remote'], threading.Lock())
                with target_lock:
                    stage = 'preflight'
                    state.update(stage=stage)
                    self.save(upload_id, state)
                    current = self.backend.read(state['remote'], folder/('remote-before-' + str(uuid.uuid4()) + '.bin'))
                    actual = (current or {}).get('sha256')
                    if actual != state['sha256']:
                        if actual != state['expected_sha256']:
                            raise UploadFault('remote_conflict', 409)
                        stage = 'upload'
                        state.update(stage=stage)
                        self.save(upload_id, state)
                        self.backend.put(state['remote'], assembled)
                    stage = 'verify'
                    state.update(stage=stage)
                    self.save(upload_id, state)
                    verified = self.backend.read(state['remote'], folder/('remote-after-' + str(uuid.uuid4()) + '.bin'))
                    if not verified or verified['sha256'] != state['sha256'] or verified['bytes'] != state['bytes']:
                        raise UploadFault('remote_hash_mismatch', 409)
                    state.update(state='verified', stage='verified', error=None)
                    self.save(upload_id, state)
        except Exception as error:
            with self.lock(upload_id):
                state = self.load(upload_id)
                state.update(state='conflict' if isinstance(error, UploadFault) and error.code == 'remote_conflict' else 'failed',
                    stage=stage, error=error.code if isinstance(error, UploadFault) else type(error).__name__)
                self.save(upload_id, state)
        finally:
            with self.lock(upload_id):
                self.jobs.pop(upload_id, None)


def handle(handler, store):
    """Return True only for upload routes. Caller must authenticate first."""
    route = handler.route()
    if route != '/uploads' and not route.startswith('/uploads/'):
        return False
    try:
        if handler.command == 'GET':
            if route == '/uploads':
                handler.reply(200, {'protocol': 'resumable-upload-v1', 'chunk_bytes': CHUNK_BYTES, 'max_bytes': MAX_BYTES})
            else:
                pieces = route.split('/')
                if len(pieces) != 3:
                    raise UploadFault('not_found', 404)
                handler.reply(200, store.status(pieces[2]))
            return True
        if handler.headers.get('Origin'):
            raise UploadFault('browser_upload_not_enabled', 403)
        lengths = handler.headers.get_all('Content-Length') or []
        if len(lengths) != 1 or handler.headers.get('Transfer-Encoding'):
            raise UploadFault('fixed_length_required')
        length = int(lengths[0])
        limit = CHUNK_BYTES if handler.command == 'PUT' else 4096
        if not 0 <= length <= limit:
            raise UploadFault('request_too_large', 413)
        body = handler.rfile.read(length)
        if len(body) != length:
            raise UploadFault('truncated_body')
        pieces = route.split('/')
        if handler.command == 'POST' and route == '/uploads':
            handler.reply(200, store.begin(json.loads(body.decode('utf-8'))))
        elif handler.command == 'PUT' and len(pieces) == 5 and pieces[3] == 'chunks':
            handler.reply(200, store.chunk(pieces[2], int(pieces[4]), body))
        elif handler.command == 'POST' and len(pieces) == 4 and pieces[3] == 'commit':
            if body != b'{}':
                raise UploadFault('empty_commit_required')
            handler.reply(202, store.commit(pieces[2]))
        else:
            raise UploadFault('not_found', 404)
    except UploadFault as error:
        handler.reply(error.status, {'error': error.code})
    except (ValueError, TypeError, UnicodeError):
        handler.reply(400, {'error': 'invalid_upload_request'})
    except Exception as error:
        handler.reply(503, {'error': type(error).__name__})
    return True
