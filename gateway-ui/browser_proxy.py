#!/usr/bin/env python3
"""Owner-only Serve identity for browser reads; Basic remains required for WebDAV writes."""
import email.header
import hmac
import http.client
import json
import os
import pathlib
import socket
import socketserver
import struct
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler

ORIGIN = 'https://gateway.example.ts.net'
PREFIX = '/__codex_gateway_v1__'
OWNER_POSTS = {PREFIX + '/selection', PREFIX + '/notifications/subscribe',
               PREFIX + '/notifications/unsubscribe', PREFIX + '/notifications/test'}
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade'}


def identity(value):
    if len(value) > 1024:
        return ''
    try:
        return ''.join(part.decode(charset or 'ascii') if isinstance(part, bytes) else part
                       for part, charset in email.header.decode_header(value))
    except (ValueError, UnicodeError, LookupError):
        return ''


def mode(method, path, headers, owner, basic, trusted):
    origins = headers.get_all('Origin') or []
    if len(origins) > 1 or (origins and origins[0] != ORIGIN):
        return 'forbidden'
    if headers.get('Sec-Fetch-Site') == 'cross-site':
        navigation = method in ('GET', 'HEAD') and headers.get('Sec-Fetch-Mode') == 'navigate' and headers.get('Sec-Fetch-User') == '?1'
        if not navigation:
            return 'forbidden'
    values = headers.get_all('Tailscale-User-Login') or []
    match = trusted and owner and len(values) == 1 and identity(values[0]) == owner
    if match and method in ('GET', 'HEAD') and path != PREFIX + '/health-event' and not (path == PREFIX + '/uploads' or path.startswith(PREFIX + '/uploads/')):
        return 'owner'
    if match and method == 'POST' and path in OWNER_POSTS and origins == [ORIGIN]:
        return 'owner'
    auth = headers.get_all('Authorization') or []
    if len(auth) == 1 and hmac.compare_digest(auth[0].encode(), basic.encode()):
        return 'basic'
    return 'unauthorized'


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.connection.settimeout(120)

    def log_message(self, *args):
        pass

    def reject(self, code, message):
        body = json.dumps({'error': message}).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        if code == 401:
            self.send_header('WWW-Authenticate', 'Basic realm=""')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)
        self.close_connection = True

    def authorization(self):
        target = urllib.parse.urlsplit(self.path)
        if target.scheme or target.netloc or not target.path.startswith('/') or '\\' in target.path:
            return 'forbidden'
        return mode(self.command, target.path, self.headers, self.server.owner,
                    self.server.basic, self.server.trusted_peer(self.connection))

    def handle_expect_100(self):
        if self.authorization() not in ('owner', 'basic'):
            self.reject(401, 'authentication required')
            return False
        self.send_response_only(100)
        self.end_headers()
        return True

    def dispatch(self):
        auth = self.authorization()
        if auth not in ('owner', 'basic'):
            self.reject(403 if auth == 'forbidden' else 401, 'request forbidden' if auth == 'forbidden' else 'authentication required')
            return
        lengths = self.headers.get_all('Content-Length') or []
        encodings = self.headers.get_all('Transfer-Encoding') or []
        try:
            if len(lengths) > 1 or len(encodings) > 1 or (lengths and encodings):
                raise ValueError()
            length = int(lengths[0]) if lengths else 0
            if length < 0 or (encodings and encodings[0].lower() != 'chunked'):
                raise ValueError()
        except ValueError:
            self.reject(400, 'invalid request framing')
            return
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == PREFIX + '/browser-auth' and self.command in ('GET', 'HEAD'):
            body = json.dumps({'method': 'tailscale' if auth == 'owner' else 'gateway-key',
                               'automatic_browser_login': auth == 'owner'}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)
            self.close_connection = True
            return
        picker = parsed.path == PREFIX or parsed.path.startswith(PREFIX + '/')
        upstream = http.client.HTTPConnection('127.0.0.1', self.server.picker_port if picker else self.server.webdav_port, timeout=120)
        sent = False
        try:
            upstream.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            connection_headers = {x.strip().lower() for x in self.headers.get('Connection', '').split(',')}
            for name, value in self.headers.items():
                key = name.lower()
                if key in HOP | connection_headers | {'authorization', 'host', 'expect', 'content-length'} or key.startswith('tailscale-'):
                    continue
                upstream.putheader(name, value)
            upstream.putheader('Host', urllib.parse.urlsplit(ORIGIN).netloc)
            upstream.putheader('Authorization', self.server.basic)
            upstream.putheader('Connection', 'close')
            if encodings:
                upstream.putheader('Transfer-Encoding', 'chunked')
            elif lengths:
                upstream.putheader('Content-Length', str(length))
            upstream.endheaders()
            if encodings:
                self.forward_chunks(upstream)
            else:
                remaining = length
                while remaining:
                    data = self.rfile.read(min(65536, remaining))
                    if not data:
                        raise ValueError('truncated body')
                    upstream.send(data)
                    remaining -= len(data)
            response = upstream.getresponse()
            if auth == 'owner' and response.status == 401:
                self.reject(503, 'gateway authentication is updating; retry shortly')
                return
            self.send_response(response.status)
            sent = True
            response_connection = {x.strip().lower() for x in response.getheader('Connection', '').split(',')}
            for name, value in response.getheaders():
                key = name.lower()
                if key not in HOP | response_connection and not key.startswith('access-control-'):
                    self.send_header(name, value)
            self.send_header('Connection', 'close')
            self.end_headers()
            if self.command != 'HEAD':
                while True:
                    data = response.read(65536)
                    if not data:
                        break
                    self.wfile.write(data)
        except (OSError, ValueError, http.client.HTTPException):
            if not sent:
                self.reject(502, 'gateway forwarding failed')
        finally:
            self.close_connection = True
            upstream.close()

    def forward_chunks(self, upstream):
        while True:
            line = self.rfile.readline(8193)
            value = line.split(b';', 1)[0].strip()
            if len(line) > 8192 or not value or any(c not in b'0123456789abcdefABCDEF' for c in value):
                raise ValueError('invalid chunk')
            size = int(value, 16)
            if size == 0:
                total = 0
                while True:
                    trailer = self.rfile.readline(8193)
                    total += len(trailer)
                    if total > 8192 or not trailer:
                        raise ValueError('invalid trailer')
                    if trailer == b'\r\n':
                        break
                upstream.send(b'0\r\n\r\n')
                return
            upstream.send(('%x\r\n' % size).encode())
            remaining = size
            while remaining:
                data = self.rfile.read(min(65536, remaining))
                if not data:
                    raise ValueError('truncated chunk')
                upstream.send(data)
                remaining -= len(data)
            if self.rfile.read(2) != b'\r\n':
                raise ValueError('invalid chunk terminator')
            upstream.send(b'\r\n')

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_PROPFIND = do_PROPPATCH = do_MKCOL = do_MOVE = do_COPY = do_PATCH = do_LOCK = do_UNLOCK = dispatch

    def do_OPTIONS(self):
        if self.headers.get('Origin'):
            self.reject(403, 'cross-origin access disabled')
        else:
            self.dispatch()


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def verify_request(self, request, client_address):
        return self.trusted_peer(request)

    def trusted_peer(self, connection):
        try:
            _, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            return uid in (0, 1000)
        except (OSError, AttributeError):
            return False


def start(directory, basic):
    config = json.loads((pathlib.Path(directory) / 'browser-owner.json').read_text())
    owner = config.get('login')
    if not isinstance(owner, str) or not owner or len(owner) > 1024:
        raise ValueError('invalid browser owner binding')
    path = pathlib.Path('/run/icloud-gateway-picker/browser.sock')
    if path.exists():
        raise ValueError('existing browser socket; stopped')
    server = Server(str(path), Handler)
    os.chmod(str(path), 0o660)
    server.owner, server.basic = owner, basic
    server.picker_port, server.webdav_port = 18767, 18765
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
