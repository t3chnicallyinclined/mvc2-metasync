#!/usr/bin/env python3
"""Serve the replay viewer with caching disabled.

    python serve.py            # then open http://localhost:8099/

Why not `python -m http.server`: we edit sprite.wgsl and the .mjs modules between runs, and the
browser caches both the ES modules and the shader. A stale module surfaces as a nonsense error --
"entry point 'fs_flat_opaque' doesn't exist" when the function is plainly in the file -- and costs a
debugging cycle chasing the wrong thing. Every response here is Cache-Control: no-store, so a plain
refresh always runs the current code.

Also sets the correct MIME type for .mjs and .wgsl, which http.server does not know about.

⚠⚠ THIS MUST BE THREADED, AND THE HANDLER MUST HAVE A TIMEOUT.
The first version used a plain single-threaded socketserver.TCPServer and it WEDGED: the page loaded
a few files and then every later request hung, including a fresh browser and a fresh server process.
Chrome opens speculative pre-connect sockets that carry NO request. A single-threaded server accepts
one of those and then blocks forever in readline() waiting for a request line that never comes -- it
is still listening, so nothing looks wrong from the outside, but it will never serve another byte.
Threads mean a silent socket only occupies one thread, and the timeout means it does not even do
that for long.
"""
import http.server
import os
import socket
import socketserver
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
os.chdir(os.path.dirname(os.path.abspath(__file__)))


class Handler(http.server.SimpleHTTPRequestHandler):
    # A connection that goes quiet must not hold a thread indefinitely.
    timeout = 15

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        '.mjs': 'text/javascript',
        '.js': 'text/javascript',
        '.wgsl': 'text/plain',
        '.pack': 'application/octet-stream',
        '.seq': 'application/octet-stream',
        '.bmp': 'image/bmp',
        '.json': 'application/json',
    }

    def send_head(self):
        # ⚠ SERVE A PRE-COMPRESSED SIBLING IF THERE IS ONE.
        # A sequence is ~338 KB per captured frame raw and ~37 KB gzipped -- 89% off, because the
        # manifest is repetitive JSON (13:1) and the geometry is float32 (8:1). The browser
        # decompresses transparently, so this costs the player nothing and turns an 83 MB download
        # into 9 MB. Pre-compressed, not compressed per request: gzipping 83 MB on every reload would
        # just move the wait.
        path = self.translate_path(self.path)
        gz = path + '.gz'
        if (os.path.exists(gz) and not os.path.isdir(path)
                and 'gzip' in self.headers.get('Accept-Encoding', '')):
            import mimetypes
            ctype = self.extensions_map.get(os.path.splitext(path)[1].lower(),
                                            'application/octet-stream')
            try:
                f = open(gz, 'rb')
            except OSError:
                return super().send_head()
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Encoding', 'gzip')
            self.send_header('Content-Length', str(os.path.getsize(gz)))
            self.end_headers()
            return f
        return super().send_head()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def handle_one_request(self):
        # A pre-connect socket that never sends a request line raises here on timeout. Closing it
        # quietly is correct; letting it propagate prints a traceback per speculative connection.
        try:
            super().handle_one_request()
        except (socket.timeout, TimeoutError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    def log_message(self, fmt, *args):
        # Keep the console readable: only report failures and the big asset fetches.
        msg = fmt % args
        if ' 200 ' not in msg or any(x in msg for x in ('.pack', '.bmp', '.wgsl')):
            sys.stderr.write('  %s\n' % msg)


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True          # a hung connection must never keep the process alive
    allow_reuse_address = True


# A port already in use is almost always a previous run of this script that is still holding it --
# and, before the threading fix, still holding it while serving nothing. Say so instead of dying with
# a bare OSError, because the symptom in the browser ("the page will not load") is identical.
try:
    httpd = Server(('127.0.0.1', PORT), Handler)
except OSError as e:
    sys.exit(f'cannot bind 127.0.0.1:{PORT} ({e}).\n'
             f'  Something is already listening. Find it with:\n'
             f'    powershell "Get-NetTCPConnection -LocalPort {PORT} -State Listen | '
             f'Select OwningProcess"\n'
             f'  then stop that PID, or run:  python serve.py {PORT + 1}')

with httpd:
    print(f'serving {os.getcwd()}')
    print(f'  http://localhost:{PORT}/     (caching disabled — a plain refresh reloads everything)')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nstopped')
