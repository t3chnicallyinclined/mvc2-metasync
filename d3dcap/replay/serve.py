#!/usr/bin/env python3
"""Serve the replay viewer with caching disabled.

    python serve.py            # then open http://localhost:8099/

Why not `python -m http.server`: we edit sprite.wgsl and the .mjs modules between runs, and the
browser caches both the ES modules and the shader. A stale module surfaces as a nonsense error --
"entry point 'fs_flat_opaque' doesn't exist" when the function is plainly in the file -- and costs a
debugging cycle chasing the wrong thing. Every response here is Cache-Control: no-store, so a plain
refresh always runs the current code.

Also sets the correct MIME type for .mjs and .wgsl, which http.server does not know about.
"""
import http.server
import os
import socketserver
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
os.chdir(os.path.dirname(os.path.abspath(__file__)))


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        '.mjs': 'text/javascript',
        '.js': 'text/javascript',
        '.wgsl': 'text/plain',
        '.pack': 'application/octet-stream',
        '.bmp': 'image/bmp',
        '.json': 'application/json',
    }

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def log_message(self, fmt, *args):
        # Keep the console readable: only report failures and the big asset fetches.
        msg = fmt % args
        if ' 200 ' not in msg or any(x in msg for x in ('.pack', '.bmp', '.wgsl')):
            sys.stderr.write('  %s\n' % msg)


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(('127.0.0.1', PORT), Handler) as httpd:
    print(f'serving {os.getcwd()}')
    print(f'  http://localhost:{PORT}/     (caching disabled — a plain refresh reloads everything)')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nstopped')
