#!/usr/bin/env python3
"""
Minimal save-sync server for OnscripterYuri web.

The game page uploads/downloads its save archive (zip bytes) with:
    POST /save/{slot}   body: zip bytes, stored as {save_dir}/{slot}.zip
    GET  /save/{slot}   returns the stored zip bytes, 404 if absent
    GET  /              small status text

Usage (pure python stdlib, no dependencies):
    python onsyuri_sync_server.py [--port 8765] [--dir saves]

Notes:
- CORS is fully open, since the game page is usually served from another origin
- if the game page is served over https, this server must be https too
  (browsers block mixed content); plain http is fine for localhost tests
- slots are free-form names (word chars, hyphen, cjk), one zip per slot,
  uploading again overwrites the slot atomically
"""
import argparse
import os
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 64 * 1024 * 1024  # 64MB
SLOT_RE = re.compile(r'^[\w\-]{1,64}$', re.UNICODE)  # word chars (incl. cjk) and hyphen


class SyncHandler(BaseHTTPRequestHandler):
    save_dir = "saves"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def _reply(self, code, body=b"", content_type="text/plain; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")  # wfile.write needs bytes
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _slot(self):
        """validate the slot name from /save/{slot}; replies 400 and returns None if bad"""
        slot = urllib.parse.unquote(self.path[len("/save/"):]).strip("/")
        if not SLOT_RE.match(slot):
            self._reply(400, "bad slot name\n")
            return None
        return slot

    def do_OPTIONS(self):
        self._reply(204)

    def do_GET(self):
        if self.path == "/":
            self._reply(200, "onsyuri save-sync server running\n")
            return
        if not self.path.startswith("/save/"):
            self._reply(404, "not found\n")
            return
        slot = self._slot()
        if slot is None:
            return
        path = os.path.join(self.save_dir, slot + ".zip")
        if not os.path.isfile(path):
            self._reply(404, "no save for this slot\n")
            return
        with open(path, "rb") as f:
            self._reply(200, f.read(), "application/octet-stream")

    def do_POST(self):
        if not self.path.startswith("/save/"):
            self._reply(404, "not found\n")
            return
        slot = self._slot()
        if slot is None:
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self._reply(413, "body too large or empty\n")
            return
        body = self.rfile.read(length)
        os.makedirs(self.save_dir, exist_ok=True)
        zip_path = os.path.join(self.save_dir, slot + ".zip")
        tmp_path = zip_path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(body)
        os.replace(tmp_path, zip_path)  # atomic on the same filesystem
        self._reply(200, "ok\n")

    def log_message(self, fmt, *args):
        print("[sync] %s - %s" % (self.address_string(), fmt % args))


def main():
    parser = argparse.ArgumentParser(description="onsyuri save-sync server")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dir", default="saves", help="directory to store save zips")
    args = parser.parse_args()

    SyncHandler.save_dir = args.dir
    os.makedirs(args.dir, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", args.port), SyncHandler)
    print("onsyuri save-sync server on 0.0.0.0:%d, storing zips in %s/" % (args.port, args.dir))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
