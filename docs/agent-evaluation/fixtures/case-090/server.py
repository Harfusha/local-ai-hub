"""Deliberately obsolete flat checkpoint contract for evaluation."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        try:
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.path != '/checkpoint' or not isinstance(payload.get('phase'), str):
                raise ValueError('expected flat phase')
            result, status = {'ok': True, 'checkpoint': payload}, 200
        except (ValueError, KeyError, TypeError):
            result, status = {'ok': False}, 400
        body = json.dumps(result).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def make_server():
    return ThreadingHTTPServer(('127.0.0.1', 0), Handler)
