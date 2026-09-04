#!/usr/bin/env python3

#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#

#
# Canned insights server for the Robot suite.
# No real server in CI: no network egress, no cost, deterministic.
#
#   python3 insights-stub.py [PORT] [RECORD_FILE]
#

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

RECORD_FILE = sys.argv[2] if len(sys.argv) > 2 else "/tmp/insights-stub.jsonl"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/v1/bundles':
            self._send(404, b'not found')
            return
        length = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(length)
        try:
            bundle = json.loads(body.decode())
        except ValueError:
            bundle = {}
        record = dict(bundle) if isinstance(bundle, dict) else {"bundle": bundle}
        record["auth"] = self.headers.get('Authorization', '')
        with open(RECORD_FILE, 'a') as handle:
            handle.write(json.dumps(record) + "\n")
        payload = json.dumps({"status": "accepted"}).encode()
        self._send(202, payload)

    def do_GET(self):
        if self.path != '/':
            self._send(404, b'not found')
            return
        self._send(200, b'ok')

    def _send(self, status, body):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("insights-stub: " + (fmt % args) + "\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9099
    HTTPServer(('127.0.0.1', port), Handler).serve_forever()
