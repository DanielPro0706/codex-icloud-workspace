import hashlib
import base64
import importlib.util
import json
import os
import pathlib
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('upload_store_tests', ROOT/'gateway-ui/uploads.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)


class Backend:
    def __init__(self):
        self.files = {}
        self.puts = []
        self.fail_after_put = False

    def read(self, remote, target):
        value = self.files.get(remote)
        if value is None:
            return None
        target.write_bytes(value)
        return {'sha256': hashlib.sha256(value).hexdigest(), 'bytes': len(value)}

    def put(self, remote, source):
        self.puts.append(remote)
        self.files[remote] = source.read_bytes()
        if self.fail_after_put:
            raise TimeoutError('lost response')


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT/'work/upload-store-tests'/str(uuid.uuid4())
        self.backend = Backend()
        self.store = u.UploadStore(self.root, self.backend)
        self.payload = bytes(range(256))*301
        self.meta = {'upload_id': str(uuid.uuid4()), 'remote': 'Folder/test.bin',
                     'bytes': len(self.payload), 'sha256': hashlib.sha256(self.payload).hexdigest(),
                     'expected_sha256': None}

    def ready(self):
        self.store.begin(self.meta)
        for index, offset in enumerate(range(0, len(self.payload), u.CHUNK_BYTES)):
            self.store.chunk(self.meta['upload_id'], index, self.payload[offset:offset+u.CHUNK_BYTES])

    def test_resume_chunks_then_verify_remote(self):
        self.ready()
        restored = u.UploadStore(self.root, self.backend)
        self.assertEqual(restored.begin(self.meta)['received'], [0, 1, 2])
        restored.chunk(self.meta['upload_id'], 0, self.payload[:u.CHUNK_BYTES])
        restored.commit(self.meta['upload_id'], background=False)
        self.assertEqual(restored.status(self.meta['upload_id'])['state'], 'verified')
        self.assertEqual(self.backend.files[self.meta['remote']], self.payload)
        restored.commit(self.meta['upload_id'], background=False)
        self.assertEqual(len(self.backend.puts), 1)

    def test_partial_or_changed_chunks_never_commit(self):
        self.store.begin(self.meta)
        with self.assertRaises(u.UploadFault):
            self.store.commit(self.meta['upload_id'], background=False)
        with self.assertRaises(u.UploadFault):
            self.store.chunk(self.meta['upload_id'], 0, b'wrong-size')
        self.ready()
        with self.assertRaises(u.UploadFault):
            self.store.chunk(self.meta['upload_id'], 0, b'x'*u.CHUNK_BYTES)
        self.assertEqual(self.backend.puts, [])

    def test_existing_remote_conflict_preserves_content(self):
        self.ready()
        self.backend.files[self.meta['remote']] = b'other person edit'
        self.store.commit(self.meta['upload_id'], background=False)
        result = self.store.status(self.meta['upload_id'])
        self.assertEqual(result['state'], 'conflict')
        self.assertEqual(self.backend.puts, [])
        self.assertTrue(list((self.root/self.meta['upload_id']).glob('remote-before-*.bin')))

    def test_lost_response_is_recovered_without_second_write(self):
        self.ready()
        self.backend.fail_after_put = True
        self.store.commit(self.meta['upload_id'], background=False)
        self.assertEqual(self.store.status(self.meta['upload_id'])['state'], 'failed')
        self.backend.fail_after_put = False
        self.store.commit(self.meta['upload_id'], background=False)
        self.assertEqual(self.store.status(self.meta['upload_id'])['state'], 'verified')
        self.assertEqual(len(self.backend.puts), 1)

    def test_authorized_overwrite_retains_exact_previous_version(self):
        self.backend.files[self.meta['remote']] = b'previous'
        self.meta['expected_sha256'] = hashlib.sha256(b'previous').hexdigest()
        self.ready()
        self.store.commit(self.meta['upload_id'], background=False)
        backups = list((self.root/self.meta['upload_id']).glob('remote-before-*.bin'))
        self.assertEqual(backups[0].read_bytes(), b'previous')
        self.assertEqual(self.store.status(self.meta['upload_id'])['state'], 'verified')

    def test_rejects_traversal_credentials_and_changed_session_intent(self):
        for remote in ['../escape', '/absolute', 'Folder/../escape', 'Folder/.env',
                       'Folder/id_ed25519', '__codex_gateway_v1__/selection']:
            with self.subTest(remote=remote), self.assertRaises(u.UploadFault):
                self.store.begin(dict(self.meta, remote=remote))
        self.store.begin(self.meta)
        with self.assertRaises(u.UploadFault):
            self.store.begin(dict(self.meta, remote='Elsewhere/file.bin'))
        with self.assertRaises(u.UploadFault):
            self.store.status('../escape')


class HTTPTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT/'gateway-ui'))
        directory = ROOT/'work/upload-http-tests'/str(uuid.uuid4())
        with patch.dict(os.environ, {'RCLONE_USER': 'fixture', 'RCLONE_PASS': 'test-password',
                                    'STATE_DIRECTORY': str(directory)}):
            spec = importlib.util.spec_from_file_location('upload_api_fixture', ROOT/'gateway-ui/selection_api.py')
            self.api = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.api)
        self.backend = Backend()
        self.api.UPLOADS = self.api.UploadStore(directory/'uploads', self.backend)
        self.server = self.api.Server(('127.0.0.1', 0), self.api.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        spec = importlib.util.spec_from_file_location('upload_client_fixture', ROOT/'.agents/skills/icloud-codex-gateway/scripts/gateway.py')
        self.client_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.client_module)
        with patch.dict(os.environ, {'ICLOUD_GATEWAY_URL': 'https://gateway.example.ts.net',
                                    'ICLOUD_GATEWAY_AUTHORIZATION': self.api.AUTH}):
            self.gateway = self.client_module.Gateway()
        self.requests = []
        self.chunk_threads = set()
        self.fail_chunk_once = False
        self.gateway.client = self
        self.gateway.new_client = lambda: self

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def open(self, request, timeout):
        path = urllib.parse.urlsplit(request.full_url).path
        if '/chunks/' in path:
            self.chunk_threads.add(threading.get_ident())
        self.requests.append((request.get_method(), path, len(request.data or b'')))
        local = urllib.request.Request('http://127.0.0.1:%d%s' % (self.server.server_port, path),
            data=request.data, headers=dict(request.header_items()), method=request.get_method())
        response = urllib.request.urlopen(local, timeout=timeout)
        if self.fail_chunk_once and '/chunks/0' in path:
            self.fail_chunk_once = False
            response.read()
            response.close()
            raise TimeoutError('chunk stored but acknowledgement lost')
        return response

    def test_real_client_server_transfer_never_sends_body_over_32k(self):
        payload = bytes(range(256))*4096
        self.gateway.upload('Folder/one-MiB.bin', payload)
        self.assertEqual(self.backend.files['Folder/one-MiB.bin'], payload)
        self.assertEqual(len(self.backend.puts), 1)
        self.assertTrue(all(size <= 32768 for _, _, size in self.requests))
        self.assertGreater(len(self.chunk_threads), 1)
        self.assertLessEqual(len(self.chunk_threads), 4)

    def test_client_resumes_after_lost_chunk_ack(self):
        payload = b'x'*70000
        self.fail_chunk_once = True
        with self.assertRaises(TimeoutError):
            self.gateway.upload('Folder/retry.bin', payload)
        self.gateway.upload('Folder/retry.bin', payload)
        first_parts = [path for method, path, _ in self.requests if method == 'PUT' and path.endswith('/chunks/0')]
        self.assertEqual(len(first_parts), 1)
        self.assertEqual(self.backend.files['Folder/retry.bin'], payload)

    def test_small_and_empty_autosaves_use_durable_protocol(self):
        for name, payload in [('small.txt', b'new save'), ('empty.txt', b'')]:
            self.gateway.upload('Folder/'+name, payload, resumable=True)
            self.assertEqual(self.backend.files['Folder/'+name], payload)
        self.assertTrue(all(path.startswith('/__codex_gateway_v1__/uploads') for _, path, _ in self.requests))

    def test_http_auth_and_origin_guards(self):
        base = 'http://127.0.0.1:%d/__codex_gateway_v1__/uploads' % self.server.server_port
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(base)
        self.assertEqual(caught.exception.code, 401)
        request = urllib.request.Request(base, b'{}', {'Authorization': self.api.AUTH, 'Origin': self.api.ORIGIN})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(self.backend.puts, [])

    def test_oversized_chunk_is_refused_before_storage(self):
        base = 'http://127.0.0.1:%d/__codex_gateway_v1__/uploads/' % self.server.server_port
        request = urllib.request.Request(base+str(uuid.uuid4())+'/chunks/0', b'x'*32769,
                                         {'Authorization': self.api.AUTH}, method='PUT')
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 413)
        self.assertEqual(self.backend.puts, [])


if __name__ == '__main__':
    unittest.main()
