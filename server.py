"""Local dev server for gukto-news: serves the static site and the /api/news route."""
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = 5600
sys.path.insert(0, os.path.join(ROOT, "api"))
import news  # noqa: E402


class Handler(news.handler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/news":
            return super().do_GET()
        return self.serve_static()

    def serve_static(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            path = "/index.html"
        fs_path = os.path.normpath(os.path.join(ROOT, path.lstrip("/")))
        if not fs_path.startswith(ROOT) or not os.path.isfile(fs_path):
            self.send_response(404)
            self._cors()
            self.end_headers()
            self.wfile.write(b"Not found")
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
        }.get(os.path.splitext(fs_path)[1], "application/octet-stream")
        with open(fs_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    print(f"Serving {ROOT} on http://localhost:{PORT}")
    ThreadingHTTPServer(("localhost", PORT), Handler).serve_forever()
