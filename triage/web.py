"""Local dashboard, not an internet-facing or multi-user control plane."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets


def make_handler(engine, token, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {f"http://{host}" for host in allowed_hosts}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, status, value, html=False):
            body = value.encode() if html else json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'nonce-" + token + "'; style-src 'nonce-" + token + "'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def trusted(self):
            if self.headers.get("Host") not in allowed_hosts:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin in allowed_origins

        def do_GET(self):
            if not self.trusted():
                return self.respond(403, {"error": "Untrusted host or origin"})
            if self.path == "/":
                page = Path(__file__).with_name("dashboard.html").read_text()
                return self.respond(200, page.replace("__TOKEN__", token), html=True)
            self.respond(404, {"error": "Not found"})

        def do_POST(self):
            if not self.trusted() or not secrets.compare_digest(self.headers.get("X-Triage-Token", ""), token):
                return self.respond(403, {"error": "Invalid session token or origin"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 2 or size > 4096 or self.headers.get("Transfer-Encoding"):
                    return self.respond(400, {"error": "Invalid body size"})
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError("Body must be a JSON object")
                if self.path == "/api/scan":
                    result = engine.scan()
                elif self.path == "/api/history":
                    result = engine.history()
                elif self.path == "/api/plan":
                    result = engine.plan(body["service"])
                elif self.path == "/api/approve":
                    result = engine.approve(body["id"])
                elif self.path == "/api/apply":
                    result = engine.apply(body["id"])
                elif self.path == "/api/cancel":
                    result = engine.cancel(body["id"])
                else:
                    return self.respond(404, {"error": "Not found"})
                self.respond(200, result)
            except (ValueError, KeyError, TypeError, RuntimeError) as exc:
                self.respond(400, {"error": str(exc)})
            except OSError:
                self.respond(503, {"error": "Local state or target unavailable"})

    return Handler


def serve(engine, port):
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    token = secrets.token_hex(32)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(engine, token, port))
    server.daemon_threads = True
    print(f"Dashboard: http://127.0.0.1:{port} — target: {engine.adapter.target}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
