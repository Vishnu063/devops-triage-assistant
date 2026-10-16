"""Loopback-only multi-tool dashboard; not a shared internet control plane."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from .integrations import catalog
from .evidence import correlate
from . import ai
from .investigation import demo_report, overview, answer, share_summary, QUESTIONS


def make_handler(engine, token, port, factory=None, configurations=None, wizard=None):
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
                if size < 2 or size > 32768 or self.headers.get("Transfer-Encoding"):
                    return self.respond(400, {"error": "Invalid body size"})
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError("Body must be a JSON object")
                if body.get("demo") is True and self.path not in ("/api/demo", "/api/investigate"):
                    raise ValueError("Sample mode cannot access live actions; leave sample mode first")
                if self.path == "/api/tools":
                    return self.respond(200, {"default": getattr(engine.adapter, "tool", "linux"), "tools": catalog(configurations or {})})
                if self.path == "/api/ai/status":
                    return self.respond(200, ai.status())
                if self.path == "/api/demo":
                    report = demo_report(body.get("scenario", "docker-oom"))
                    report['overview'] = overview(report)
                    return self.respond(200, report)
                if self.path == "/api/investigate" and body.get("demo") is True:
                    report = demo_report(body.get("scenario", "docker-oom"))
                    return self.respond(200, answer(report, body.get("question")))
                selected = body.get("tool", getattr(engine.adapter, "tool", "linux"))
                if not isinstance(selected, str):
                    raise ValueError("Tool ID must be a string")
                if self.path in ("/api/connection/schema", "/api/connection/save"):
                    if wizard is None:raise ValueError("Connection wizard is unavailable")
                    if self.path.endswith("schema"):
                        return self.respond(200,wizard.schema(selected))
                    if not isinstance(body.get("config"),dict):raise ValueError("Connection config must be an object")
                    return self.respond(200,wizard.save(selected,body["config"]))
                active = factory(selected) if factory else engine
                if self.path in ("/api/investigate", "/api/summary"):
                    _, report = active.store.latest(active.adapter.target)
                    if not report or not body.get("incident") or report.get("incident_id") != body["incident"]:
                        raise ValueError("Run fresh checks for this target before investigating it")
                    if self.path == "/api/summary":
                        result = share_summary(report)
                    else:
                        result = answer(report, body.get("question"))
                        if body.get("ai") is True:
                            if body.get("enabled") is not True:
                                raise ValueError("Enable local AI explicitly before requesting it")
                            if result['intent'] is None:
                                raise ValueError("Choose one of the six guided topics for an AI follow-up")
                            result['ai'] = ai.explain(report, body.get("model", ai.DEFAULT_MODEL), QUESTIONS[result['intent']])
                elif self.path == "/api/ai/explain":
                    if body.get("enabled") is not True:
                        raise ValueError("Enable local AI explicitly before requesting an explanation")
                    _, report = active.store.latest(active.adapter.target)
                    if not report or not body.get("incident") or report.get("incident_id") != body["incident"]:
                        raise ValueError("Run fresh checks for this target before asking AI")
                    result = ai.explain(report, body.get("model", ai.DEFAULT_MODEL))
                elif self.path == "/api/scan":
                    result = active.scan(deep=True) if body.get("deep") else active.scan()
                    result["overview"] = overview(result)
                elif self.path == "/api/validate":
                    result = active.validate_connection()
                elif self.path == "/api/timeline":
                    incident=body.get("incident")
                    if incident is not None and not isinstance(incident,str):raise ValueError("Incident ID must be a string")
                    result = active.store.timeline(incident)
                elif self.path == "/api/alerts":
                    ack=body.get("acknowledge")
                    if ack is not None and not isinstance(ack,str):raise ValueError("Alert ID must be a string")
                    result = active.store.alerts(ack)
                elif self.path == "/api/correlate":
                    selected_tools=body.get("tools")
                    if not isinstance(selected_tools,list) or not 1<=len(selected_tools)<=4 or any(not isinstance(tool,str) for tool in selected_tools) or len(set(selected_tools))!=len(selected_tools):
                        raise ValueError("Choose one to four distinct configured tools")
                    if not factory:raise ValueError("Correlation requires a configured engine factory")
                    result=correlate([factory(tool).scan(deep=bool(body.get("deep"))) for tool in selected_tools],active.store)
                elif self.path == "/api/rollback":
                    if not isinstance(body.get("id"),str):raise ValueError("Parent plan ID is required")
                    result=active.rollback_plan(body["id"])
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


def serve(engine, port, factory=None, configurations=None, wizard=None):
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    token = secrets.token_hex(32)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(engine, token, port, factory, configurations, wizard))
    server.daemon_threads = True
    print(f"Dashboard: http://127.0.0.1:{port} — default target: {engine.adapter.target}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
