"""Configured live transports and tool-specific structured diagnosis."""
import base64
import csv
import io
import json
import os
from pathlib import Path
import re
import subprocess
import selectors
import signal
from string import Template
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from .catalog import PROFILES
from .engine import fingerprint

LIMIT = 1024 * 1024
TOKEN_PATTERN = re.compile(r"\$([a-z][a-z0-9_]*)")
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def redact(value):
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)(password|token|secret|api[_-]?key)\s*[=:]\s*[^\s,;]+", r"\1=[REDACTED]", value)
        value = re.sub(r"(?i)(https?://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", value)
        value = re.sub(r"(?:AKIA|ASIA)[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9_]+", "[REDACTED]", value)
        return value[:1000]
    return value


def select(value, path):
    parts = path.split(".") if path else []
    def descend(current, remaining):
        if not remaining:
            if isinstance(current, list):
                return [v for child in current for v in descend(child, [])]
            return [current] if isinstance(current, (str, int, float, bool)) or current is None else []
        head, *tail = remaining
        if head == "*":
            children = current.values() if isinstance(current, dict) else current if isinstance(current, list) else []
            return [v for child in children for v in descend(child, tail)]
        if isinstance(current, dict) and head in current:
            return descend(current[head], tail)
        return []
    return descend(value, parts)


def requirements(profile):
    # Native Mongo shell program is literal JavaScript, not a config template.
    inputs = [profile.get("endpoint") or "", profile.get("cwd") or ""]
    inputs += [s for s in profile.get("command") or [] if "process.env" not in s]
    if profile.get("body"):
        inputs.append(json.dumps(profile["body"]))
    return sorted(set(TOKEN_PATTERN.findall(" ".join(inputs))))


def load_configuration(path):
    if path is None:
        return {}
    p = Path(path).expanduser()
    if p.stat().st_size > LIMIT:
        raise ValueError("Configuration exceeds 1 MiB")
    value = json.loads(p.read_text())
    if not isinstance(value, dict) or not isinstance(value.get("tools", {}), dict):
        raise ValueError("Expected a JSON object with a tools object")
    tools = value.get("tools", {})
    if any(key not in PROFILES or not isinstance(config, dict) for key, config in tools.items()):
        raise ValueError("Every tools entry must use a known tool ID and a configuration object")
    return tools


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward authentication to an alternate origin.
        return None


class ToolAdapter:
    def __init__(self, tool, config):
        if tool not in PROFILES:
            raise ValueError("Unknown integration; run devops-triage tools")
        if not isinstance(config, dict):
            raise ValueError("Tool configuration must be an object")
        self.tool = tool
        self.profile = PROFILES[tool]
        allowed = set(requirements(self.profile)) | {"application_health"}
        if tool == "kubernetes": allowed |= {"service"}
        if self.profile["endpoint"]:
            allowed |= {"base_url", "headers", "basic_auth"}
        if set(config) - allowed:
            raise ValueError("Unsupported configuration fields; store credentials in environment variables or native credential stores")
        if not isinstance(config.get("headers", {}), dict):
            raise ValueError("headers must be an object of environment-variable bindings")
        for name, binding in config.get("headers", {}).items():
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9-]+", name) or name.lower() in ("host", "content-length", "transfer-encoding", "connection"):
                raise ValueError("Invalid authentication header name")
            if not isinstance(binding, dict) or set(binding) - {"env", "prefix"} or not isinstance(binding.get("env"), str) or not ENV_NAME.fullmatch(binding["env"]):
                raise ValueError("Header bindings accept only env and optional prefix; literal credential fields are rejected")
            if binding.get("prefix", "") not in ("", "Bearer ", "token ", "Basic "):
                raise ValueError("Only standard authentication prefixes are supported")
        basic = config.get("basic_auth")
        if basic is not None and (not isinstance(basic, dict) or set(basic) != {"username_env", "password_env"} or any(not isinstance(v, str) or not ENV_NAME.fullmatch(v) for v in basic.values())):
            raise ValueError("basic_auth must name username_env and password_env environment variables")
        if "application_health" in config:
            from .health import validate_health
            validate_health(config["application_health"])
        if tool == "kubernetes" and "service" in config and (not isinstance(config['service'],str) or not re.fullmatch(r'[a-z0-9]([-a-z0-9.]*[a-z0-9])?',config['service']) or len(config['service'])>253):
            raise ValueError('service must be one explicit Kubernetes Service name')
        self.config = dict(config)
        for key in requirements(self.profile):
            value = config.get(key)
            if not isinstance(value, (str, int)) or not str(value).strip() or str(value).startswith("REPLACE_"):
                raise ValueError(f"{tool} requires configuration field: {key}")
            value = str(value)
            if len(value) > 4096 or value.startswith("-") or any(ord(c) < 32 for c in value):
                raise ValueError(f"Invalid configuration field: {key}")
            self.config[key] = value
        for key in ("directory", "credentials_file", "inventory", "rules"):
            if key in self.config:
                self.config[key] = str(Path(self.config[key]).expanduser().resolve())
        if tool == "salt" and not re.fullmatch(r"[A-Za-z0-9_.-]+", self.config["resource"]):
            raise ValueError("Salt requires one exact minion ID, not a wildcard target")
        if self.profile["endpoint"]:
            self.base_url = self.validate_base_url(config.get("base_url", ""))
        self.target = tool + ":" + fingerprint(self.config)[:20]
        self.services = ()

    @staticmethod
    def validate_base_url(value):
        if not isinstance(value, str):
            raise ValueError("base_url must be a string")
        parsed = urlsplit(value)
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use an explicit base_url without userinfo, query, or fragment")
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1")):
            raise ValueError("HTTPS is required except for local or SSH-tunneled endpoints")
        return value.rstrip("/")

    def render(self, text, url=False):
        if "process.env" in text:
            return text
        values = {k: quote(str(v), safe="") if url else str(v) for k, v in self.config.items() if isinstance(v, (str, int))}
        return Template(text).substitute(values)

    def render_body(self, value):
        if isinstance(value, dict):
            return {k: self.render_body(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.render_body(v) for v in value]
        return self.render(value) if isinstance(value, str) else value

    def headers(self):
        headers = {"Accept": "application/json", "User-Agent": "devops-triage-assistant/0.2"}
        for name, binding in self.config.get("headers", {}).items():
            if not re.fullmatch(r"[A-Za-z0-9-]+", name) or name.lower() in ("host", "content-length", "transfer-encoding", "connection"):
                raise ValueError("Invalid authentication header name")
            if not isinstance(binding, dict) or not isinstance(binding.get("env"), str) or not ENV_NAME.fullmatch(binding["env"]):
                raise ValueError("Headers must reference environment variables, never literal tokens")
            secret = os.environ.get(binding["env"])
            if not secret:
                raise ValueError("A configured credential environment variable is missing")
            prefix = binding.get("prefix", "")
            if prefix not in ("", "Bearer ", "token ", "Basic "):
                raise ValueError("Only standard authentication prefixes are supported")
            value = prefix + secret
            if any(ord(c) < 32 for c in value):
                raise ValueError("Invalid credential header")
            headers[name] = value
        basic = self.config.get("basic_auth")
        if basic:
            user = os.environ.get(basic.get("username_env", ""))
            password = os.environ.get(basic.get("password_env", ""))
            if not user or not password:
                raise ValueError("Basic authentication environment variables are missing")
            headers["Authorization"] = "Basic " + base64.b64encode((user + ":" + password).encode()).decode()
        return headers

    def request(self, endpoint, method="GET", body=None, health_codes=(200,)):
        url = self.base_url + self.render(endpoint, url=True)
        data = None if body is None else json.dumps(self.render_body(body)).encode()
        headers = self.headers()
        if data is not None:
            headers["Content-Type"] = "application/json"
        # Avoid environment proxies forwarding internal service credentials elsewhere.
        from urllib.request import ProxyHandler
        opener = build_opener(ProxyHandler({}), NoRedirect())
        try:
            response = opener.open(Request(url, data=data, headers=headers, method=method), timeout=20)
        except HTTPError as exc:
            if exc.code not in health_codes:
                exc.close()
                raise RuntimeError(self.http_error(exc.code)) from None
            response = exc
        except (URLError, TimeoutError, OSError):
            raise RuntimeError("Endpoint unreachable or TLS validation failed. Check routing, tunnel, certificates, and service readiness.") from None
        with response:
            raw = response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise RuntimeError("Response exceeded 1 MiB; narrow the configured scope")
            return raw.decode("utf-8"), response.code

    @staticmethod
    def http_error(code):
        if code in (401, 403):
            return f"HTTP {code}: authentication or permission denied. Check credential scope without sharing token values."
        if code == 404:
            return "HTTP 404: endpoint/resource not found. Check the resource ID, API version, base URL, and permissions."
        if code == 429:
            return "HTTP 429: rate limited. Check provider quotas and wait before an operator-triggered retry."
        return f"HTTP {code}: service request failed. Inspect provider/service status and API compatibility."

    def command(self, recipe, *, repair=False, include_stderr=False, read_timeout=None):
        argv = [self.render(item) for item in recipe]
        cwd = self.render(self.profile["cwd"]) if self.profile["cwd"] else None
        env = dict(os.environ, AWS_PAGER="", PAGER="cat", GIT_TERMINAL_PROMPT="0", CI="true")
        limit = 120 if repair else 60
        if read_timeout is not None:
            if repair or type(read_timeout) is not int or not 1<=read_timeout<=60:raise ValueError('Invalid read timeout')
            limit=read_timeout
        try:
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        except FileNotFoundError:
            raise RuntimeError("Required native CLI or configured project directory is missing. Install/configure it separately.") from None
        except OSError:
            raise RuntimeError("Cannot launch the required CLI; check permissions and installation.") from None
        streams = selectors.DefaultSelector()
        output = {"stdout": bytearray(), "stderr": bytearray()}
        for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
            streams.register(stream, selectors.EVENT_READ, name)
        deadline = time.monotonic() + limit
        try:
            while streams.get_map():
                if time.monotonic() >= deadline:
                    raise RuntimeError("Command timed out. Its outcome may be unknown; inspect live state before retrying.")
                for key, _ in streams.select(timeout=min(0.25, max(0, deadline - time.monotonic()))):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        streams.unregister(key.fileobj)
                        continue
                    output[key.data].extend(chunk)
                    if sum(len(value) for value in output.values()) > LIMIT:
                        raise RuntimeError("CLI output exceeded 1 MiB; narrow the configured scope")
            remaining = max(0.01, deadline - time.monotonic())
            try:
                returncode = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                raise RuntimeError("Command timed out; inspect live outcome before retrying") from None
        finally:
            streams.close()
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            process.stdout.close()
            process.stderr.close()
        if returncode not in ([0] if repair else self.profile["ok"]):
            error = output["stderr"].decode("utf-8", errors="replace").lower()
            if any(x in error for x in ("unauthorized", "forbidden", "accessdenied", "authentication", "permission denied")):
                raise RuntimeError("Native CLI authentication/permission failed. Check the explicit account/context and credential scope.")
            raise RuntimeError(f"Native CLI returned exit code {returncode}. Review local CLI diagnostics; stderr is withheld to protect secrets.")
        return (output["stdout"] + (output["stderr"] if include_stderr else bytearray())).decode("utf-8"), returncode

    def parse(self, raw):
        kind = self.profile["parser"]
        if kind in ("json", "jsonlines"):
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                if kind != "jsonlines":
                    raise ValueError("CLI/API returned invalid JSON; check tool version and output mode") from None
                obj = [json.loads(line) for line in raw.splitlines() if line.strip()]
            if kind == "jsonlines" and isinstance(obj, dict):
                obj = [obj]
            projected = {key: select(obj, path) for key, path in self.profile["fields"].items()}
            if self.tool == "kubernetes" and isinstance(obj, dict):
                revision = obj.get("metadata", {}).get("annotations", {}).get("deployment.kubernetes.io/revision")
                projected["revision"] = [revision] if revision is not None else []
                template = obj.get("spec", {}).get("template")
                projected["template_hash"] = [fingerprint(template)] if template is not None else []
            if self.tool == "gitleaks":
                if not isinstance(obj, list):
                    raise ValueError("Expected a Gitleaks finding array")
                projected["finding_count"] = [len(obj)]
            elif self.tool == "trivy":
                if not isinstance(obj, dict) or "Results" not in obj:
                    raise ValueError("Expected a Trivy image vulnerability report")
                projected["finding_count"] = [sum(len(result.get("Vulnerabilities") or []) for result in obj.get("Results") or [])]
            elif self.tool == "semgrep":
                if not isinstance(obj, dict) or "results" not in obj:
                    raise ValueError("Expected a Semgrep result report")
                projected["finding_count"] = [len(obj["results"])]
                projected["scan_error_count"] = [len(obj.get("errors", []))]
            return projected
        if kind in ("ready", "envoy"):
            return {"ready": [raw.strip().lower() == ("live" if kind == "envoy" else "ready")]}
        if kind == "tasks":
            rows = [line.split() for line in raw.splitlines()[1:] if line.strip()]
            return {"task": [r[0] for r in rows], "state": [r[-1] for r in rows]}
        if kind == "manifest":
            kinds = re.findall(r"(?m)^kind:\s*([A-Za-z0-9]+)\s*$", raw)
            return {"kind": kinds, "document_count": [len(kinds)]}
        if kind == "inventory":
            obj = json.loads(raw)
            hosts = set(obj.get("_meta", {}).get("hostvars", {}))
            for key, group in obj.items():
                if key != "_meta" and isinstance(group, dict):
                    hosts.update(group.get("hosts", []))
            return {"groups": [k for k in obj if k != "_meta"], "host_count": [len(hosts)]}
        if kind == "puppet":
            found = re.findall(r"ensure\s*=>\s*['\"]([^'\"]+)['\"]", raw)
            return {"ensure": found}
        if kind == "salt":
            obj = json.loads(raw)
            return {"responsive": [value is True for value in obj.values()], "minion_count": [len(obj)]}
        if kind == "logstash":
            obj = json.loads(raw)
            pipelines = obj.get("pipelines", {})
            return {"pipeline": list(pipelines), "events_in": [p.get("events", {}).get("in", 0) for p in pipelines.values()], "events_out": [p.get("events", {}).get("out", 0) for p in pipelines.values()]}
        if kind == "nginx":
            active = re.search(r"Active connections:\s*(\d+)", raw)
            if not active:
                raise ValueError("Expected NGINX stub_status, not an HTML page or unrelated response")
            return {"active_connections": [int(active.group(1))]}
        if kind == "haproxy":
            rows = list(csv.DictReader(io.StringIO(raw.lstrip("# "))))
            if not rows or "status" not in rows[0]:
                raise ValueError("Expected HAProxy CSV statistics with a status column")
            return {"backend": [r.get("pxname", "") for r in rows], "server": [r.get("svname", "") for r in rows], "state": [r["status"].split()[0] for r in rows]}
        if kind in ("csv", "tsv"):
            rows = list(csv.DictReader(io.StringIO(raw), delimiter="," if kind == "csv" else "\t"))
            allowed = {"in_recovery", "numbackends", "deadlocks", "read_only", "version", "max_connections"}
            return {key: [row[key] for row in rows] for key in allowed if rows and key in rows[0]}
        if kind == "redis":
            text = json.loads(raw)
            if not isinstance(text, str):
                raise ValueError("Expected Redis INFO text in JSON output mode")
            values = dict(line.split(":", 1) for line in text.splitlines() if ":" in line and not line.startswith("#"))
            return {key: [values[key]] for key in ("used_memory", "maxmemory", "maxmemory_policy", "mem_fragmentation_ratio") if key in values}
        if kind == "kafka":
            rows = []
            for line in raw.splitlines():
                if re.search(r"\bPartition:\s*\d+", line):
                    def field(name):
                        match = re.search(r"\b" + name + r":[ \t]*([0-9,-]*)", line)
                        return match.group(1) if match else ""
                    replicas, isr = field("Replicas"), field("Isr")
                    rows.append((field("Partition"), int(field("Leader") or -1), len([v for v in isr.split(",") if v]) < len([v for v in replicas.split(",") if v])))
            return {"partition": [r[0] for r in rows], "leader": [r[1] for r in rows], "under_replicated": [r[2] for r in rows]}
        raise ValueError("Unsupported parser")

    def collect(self):
        profile = self.profile
        if self.tool == "mongodb" and not os.environ.get("TRIAGE_MONGODB_URI"):
            raise RuntimeError("Set TRIAGE_MONGODB_URI in the environment before checking MongoDB")
        if profile["command"]:
            raw, code = self.command(profile["command"])
        else:
            raw, code = self.request(profile["endpoint"], profile["method"], profile["body"], profile["health_codes"])
        try:
            observations = self.parse(raw)
        except (TypeError, KeyError, AttributeError, IndexError):
            raise ValueError("Response schema is incompatible with this profile; inspect the native tool/API version locally") from None
        essential = {
            "aws": ["instance", "state"], "azure": ["name", "status"], "gcp": ["id", "status"],
            "digitalocean": ["id", "status"], "oci": ["id", "state"], "docker": ["id", "state"],
            "podman": ["id", "state"], "buildah": ["id"], "kubernetes": ["uid", "desired"],
            "helm": ["release", "status"], "argocd": ["sync", "health"], "flux": ["uid", "conditions"],
            "jenkins": ["number", "building"], "github-actions": ["id", "status"],
            "gitlab-ci": ["id", "status"], "azure-pipelines": ["id", "status"], "tekton": ["uid", "conditions"],
            "terraform": ["valid"], "opentofu": ["valid"], "cloudformation": ["id", "status"],
            "cdk": ["id", "status"], "puppet": ["ensure"], "chef": ["observed"],
            "salt": ["responsive"], "cloud-init": ["status"], "prometheus": ["status"],
            "grafana": ["database"], "datadog": ["id", "state"], "zabbix": ["id"],
            "cloudwatch": ["alarm"], "elasticsearch": ["status"], "kibana": ["version"],
            "loki": ["ready"], "vault": ["initialized", "sealed"], "secrets-manager": ["id"],
            "azure-key-vault": ["id"], "keycloak": ["status"], "teleport": ["version"],
            "nginx": ["active_connections"], "haproxy": ["state"], "traefik": ["http_router_errors"],
            "istio": ["pod", "phase"], "envoy": ["ready"], "postgresql": ["in_recovery"],
            "mysql": ["read_only"], "redis": ["used_memory"], "mongodb": ["ok"], "kafka": ["partition"]
        }.get(self.tool, [])
        missing = [key for key in essential if not observations.get(key) or all(v is None for v in observations[key])]
        truncated = any(len(v) > 200 for v in observations.values())
        observations = {k: v[:200] for k, v in observations.items()}
        snapshot = {"tool": self.tool, "collected_at": time.time(), "observations": redact(observations),
                "transport_code": code, "truncated": truncated,
                "errors": (["Expected evidence missing: " + ", ".join(missing)] if missing else []) + (["Evidence truncated; scope is too broad"] if truncated else []),
                "empty": not any(observations.values()), "missing_evidence": missing}
        self.last_snapshot = snapshot
        return snapshot

    def findings(self, snapshot):
        obs = snapshot["observations"]
        findings = []
        for item in self.profile["rules"]:
            values = obs.get(item["path"], [])
            op, expected = item["op"], item["expected"]
            if op == "in":
                triggered = any(v in expected for v in values)
            elif op == "not_in":
                triggered = bool(values) and any(v not in expected for v in values)
            elif op == "nonempty":
                triggered = bool(values)
            elif op == "gt":
                triggered = any(isinstance(v, (int, float)) and v > expected for v in values)
            elif op == "less_than_field":
                desired = obs.get(expected, [])
                # Kubernetes omits availableReplicas when zero.
                actual = values[0] if values else 0
                triggered = bool(desired) and isinstance(actual, (int, float)) and isinstance(desired[0], (int, float)) and actual < desired[0]
            else:
                triggered = False
            if triggered:
                findings.append(dict(code=self.tool + ":" + item["path"], title=item["title"],
                    evidence=json.dumps({item["path"]: values}), likely_cause=item["cause"],
                    next_steps=item["steps"], service=None))
        if any(isinstance(v, (int, float)) and v > 0 for v in obs.get("scan_error_count", [])):
            findings.append(dict(code="scan-incomplete", title="Static analysis could not inspect all requested source", evidence=json.dumps({"error_count": obs["scan_error_count"], "error_types": obs.get("error_type", [])}), likely_cause="Parser, rule, permission or scan execution errors prevented complete analysis.", next_steps=["Review the reported scanner error types locally", "Correct the rules, language support or input access before treating the scan as complete"], service=None))
        if snapshot.get("missing_evidence"):
            findings.append(dict(code="missing-evidence", title="Expected evidence is missing", evidence=", ".join(snapshot["missing_evidence"]), likely_cause="The resource may be absent, permission-limited, or using an incompatible response schema.", next_steps=["Confirm the configured resource, API/CLI version and read permissions"], service=None))
        if snapshot["truncated"]:
            findings.append(dict(code="incomplete",title="Result was truncated",evidence="More than 200 projected values in a field",likely_cause="The configured scope is too broad for a bounded response.",next_steps=["Narrow the resource/project scope"],service=None))
        if snapshot["empty"]:
            findings.append(dict(code="no-evidence",title="No scoped evidence was returned",evidence="All projected fields are empty",likely_cause="The resource may be absent, API output may differ, or visibility may be restricted.",next_steps=["Check the configured resource and permissions","Confirm deployed tool version and collector scope"],service=None))
        return findings

    def repair_allowed(self, snapshot):
        repair = self.profile["repair"]
        if not repair or snapshot["empty"] or snapshot["truncated"] or snapshot.get("missing_evidence"):
            return False
        obs = snapshot["observations"]
        actual = obs.get(repair["allowed_field"], [])
        if "below_field" in repair:
            desired = obs.get(repair["below_field"], [])
            current = actual[0] if actual else 0
            return bool(desired) and isinstance(current, (int, float)) and isinstance(desired[0], (int, float)) and current < desired[0]
        return bool(actual) and any(value in repair["allowed_values"] for value in actual)

    def state_hash(self, snapshot):
        return fingerprint(snapshot["observations"])

    def repair_description(self):
        spec = self.profile["repair"]
        if spec.get("command"):
            return {"command": [self.render(s) for s in spec["command"]]}
        return {"method": spec["method"], "url": self.base_url + self.render(spec["endpoint"], url=True)}

    def execute_repair(self):
        spec = self.profile["repair"]
        if spec.get("command"):
            self.command(spec["command"], repair=True)
        else:
            self.request(spec["endpoint"], spec["method"], body={}, health_codes=(200,201,202,204))

    def verify(self, snapshot):
        repair = self.profile["repair"]
        obs = snapshot["observations"]
        if snapshot["empty"] or snapshot["truncated"] or snapshot.get("missing_evidence"):
            return False
        values = obs.get(repair["verify_field"], [])
        if "compare_field" in repair:
            desired = obs.get(repair["compare_field"], [])
            observed = obs.get("observed", [])
            generation = obs.get("generation", [])
            return bool(desired and values and observed and generation) and all(isinstance(v, (int, float)) for v in (desired[0], values[0], observed[0], generation[0])) and values[0] >= desired[0] and observed[0] >= generation[0]
        return bool(values) and all(v in repair["verify_values"] for v in values)


def catalog(configurations):
    result = []
    for key, p in PROFILES.items():
        missing = [field for field in requirements(p) if not configurations.get(key, {}).get(field)]
        if p["endpoint"] and not configurations.get(key, {}).get("base_url"):
            missing.append("base_url")
        result.append({"id": key, "name": p["name"], "category": p["category"], "scope": p["scope"],
                       "maturity": p["maturity"], "configured": key in configurations and not missing,
                       "missing": missing, "repair": p["repair"]["id"] if p["repair"] else None})
    return result
