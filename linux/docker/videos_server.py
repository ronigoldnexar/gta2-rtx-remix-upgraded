#!/usr/bin/env python3
"""Static file server with HTTP Range support (so browsers can seek in the mp4 files).
Usage: videos_server.py <dir> <port>"""
import os, sys, re, http.server, socketserver
ROOT = os.path.abspath(sys.argv[1]); PORT = int(sys.argv[2])
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=ROOT, **k)
    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path) or 'Range' not in self.headers: return super().send_head()
        try: f = open(path, 'rb')
        except OSError: self.send_error(404); return None
        size = os.fstat(f.fileno()).st_size
        m = re.match(r'bytes=(\d*)-(\d*)', self.headers['Range'])
        start = int(m.group(1) or 0); end = int(m.group(2) or size - 1); end = min(end, size - 1)
        if start > end: self.send_error(416); f.close(); return None
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(path))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(end - start + 1))
        self.end_headers(); f.seek(start); self._end = end - start + 1; return f
    def copyfile(self, src, dst):
        n = getattr(self, '_end', None)
        if n is None: return super().copyfile(src, dst)
        while n > 0:
            b = src.read(min(1 << 16, n)); 
            if not b: break
            dst.write(b); n -= len(b)
    def end_headers(self):
        if 'Range' not in self.headers: self.send_header('Accept-Ranges', 'bytes')
        super().end_headers()
    def log_message(self, *a): pass
class S(socketserver.ThreadingMixIn, http.server.HTTPServer): daemon_threads = True; allow_reuse_address = True
S(('0.0.0.0', PORT), H).serve_forever()
