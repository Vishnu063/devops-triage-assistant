"""Loopback-only multi-tool dashboard; not a shared internet control plane."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from .integrations import catalog


def make_handler(engine, token, port, factory=None, configurations=None):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {f"http://{host}" for host in allowed_hosts}

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(210)

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
            return self.headers.get("Host") in allowed_hosts and self.headers.get("Origin") in (None, *allowed_origins)

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
                if self.path == "/api/tools":
                    return self.respond(200, {"default": getattr(engine.adapter, "tool", "linux"), "tools": catalog(configurations or {})})
                selected = body.get("tool", getattr(engine.adapter, "tool", "linux"))
                if not isinstance(selected, str):
                    raise ValueError("Tool ID must be a string")
                active = factory(selected) if factory else engine
                if self.path == "/api/scan":
                    result = active.scan()
                elif self.path == "/api/history":
                    result = active.history()
                elif self.path == "/api/plan":
                    action = body.get("action", body.get("service"))
                    if not isinstance(action, str):
                        raise ValueError("Action must be a string")
                    result = active.plan(action)
                elif self.path in ("/api/approve", "/api/apply", "/api/cancel", "/api/show"):
                    plan_id = body.get("id")
                    if not isinstance(plan_id, str) or len(plan_id) != 32:
                        raise ValueError("A valid plan ID is required")
                    result = getattr(active, self.path.rsplit("/", 1)[1])(plan_id)
                else:
                    return self.respond(404, {"error": "Not found"})
                self.respond(200, result)
            except (ValueError, KeyError, TypeError, RuntimeError) as exc:
                self.respond(400, {"error": str(exc)})
            except OSError:
                self.respond(503, {"error": "Local state or target unavailable"})

    return Handler


def serve(engine, port, factory=None, configurations=None):
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    token = secrets.token_hex(32)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(engine, token, port, factory, configurations))
    server.daemon_threads = True
    print(f"Dashboard: http://127.0.0.1:{port} — default target: {engine.adapter.target}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
