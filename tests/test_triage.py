import copy
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from triage.engine import Engine
from triage.linux import Linux, diagnose
from triage.web import make_handler


class FakeLinux:
    target = "test-host"
    services = ("example.service",)
    def __init__(self):
        self.calls = 0
        self.fail = False
        self.stuck = False
        self.state = {"hostname": "test", "collected_at": 1, "cpu_count": 2, "load1": 0.2,
                      "disk_used_percent": 20, "memory_used_percent": 30, "errors": [],
                      "services": {"example.service": {"LoadState": "loaded", "ActiveState": "failed", "InvocationID": "old"}}}
    def collect(self):
        return copy.deepcopy(self.state)
    def restart(self, service):
        self.calls += 1
        if self.fail:
            raise RuntimeError("timeout")
        if not self.stuck:
            self.state["services"][service]["ActiveState"] = "active"


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.adapter = FakeLinux()
        self.engine = Engine(self.adapter, self.tmp.name)
    def plan(self):
        return self.engine.plan("example.service")["id"]
    def test_apply_without_approval_never_runs(self):
        with self.assertRaises(ValueError): self.engine.apply(self.plan())
        self.assertEqual(self.adapter.calls, 0)
    def test_success_is_verified_and_single_use(self):
        pid = self.plan()
        self.engine.approve(pid)
        self.assertEqual(self.engine.apply(pid)["status"], "verified")
        with self.assertRaises(ValueError): self.engine.apply(pid)
        self.assertEqual(self.adapter.calls, 1)
        self.assertEqual([e["event"] for e in reversed(self.engine.history())], ["planned", "approved", "executing", "verified"])
    def test_approval_survives_process_restart(self):
        pid = self.plan()
        self.engine.approve(pid)
        other = Engine(self.adapter, self.tmp.name)
        self.assertEqual(other.apply(pid)["status"], "verified")
    def test_expiry_blocks_approval(self):
        pid = self.plan()
        with patch("triage.engine.time.time", return_value=10**12):
            with self.assertRaises(ValueError): self.engine.approve(pid)
        self.assertEqual(self.adapter.calls, 0)
    def test_expiry_blocks_execution(self):
        pid = self.plan()
        self.engine.approve(pid)
        with patch("triage.engine.time.time", return_value=10**12):
            with self.assertRaises(ValueError): self.engine.apply(pid)
        self.assertEqual(self.adapter.calls, 0)
    def test_state_change_blocks_approval(self):
        pid = self.plan()
        self.adapter.state["services"]["example.service"]["InvocationID"] = "new"
        with self.assertRaises(ValueError): self.engine.approve(pid)
    def test_state_change_after_approval_blocks_apply(self):
        pid = self.plan()
        self.engine.approve(pid)
        self.adapter.state["services"]["example.service"]["ActiveState"] = "active"
        with self.assertRaises(ValueError): self.engine.apply(pid)
        self.assertEqual(self.adapter.calls, 0)
    def test_target_change_blocks_apply(self):
        pid = self.plan()
        self.engine.approve(pid)
        self.adapter.target = "different-host"
        with self.assertRaises(ValueError): self.engine.apply(pid)
    def test_allowlist_change_blocks_apply(self):
        pid = self.plan()
        self.engine.approve(pid)
        self.adapter.services = ()
        with self.assertRaises(ValueError): self.engine.apply(pid)
    def test_timeout_does_not_retry(self):
        pid = self.plan()
        self.engine.approve(pid)
        self.adapter.fail = True
        self.assertEqual(self.engine.apply(pid)["status"], "needs_attention")
        with self.assertRaises(ValueError): self.engine.apply(pid)
        self.assertEqual(self.adapter.calls, 1)
    def test_failed_verification_needs_attention(self):
        pid = self.plan()
        self.engine.approve(pid)
        self.adapter.stuck = True
        self.assertEqual(self.engine.apply(pid)["status"], "needs_attention")
    def test_unknown_plan_rejected(self):
        for fn in (self.engine.approve, self.engine.apply, self.engine.show):
            with self.assertRaises(ValueError): fn("missing")
    def test_unapproved_service_rejected(self):
        with self.assertRaises(ValueError): self.engine.plan("other.service")
    def test_healthy_service_has_no_restart_plan(self):
        self.adapter.state["services"]["example.service"]["ActiveState"] = "active"
        with self.assertRaises(ValueError): self.plan()
    def test_duplicate_active_plan_rejected(self):
        self.plan()
        with self.assertRaises(ValueError): self.plan()
    def test_expired_plan_can_be_replaced(self):
        old = self.plan()
        with patch("triage.engine.time.time", return_value=10**12):
            self.assertNotEqual(old, self.plan())
        self.assertEqual(self.engine.show(old)["status"], "expired")
    def test_concurrent_apply_runs_once(self):
        pid = self.plan()
        self.engine.approve(pid)
        def run(_):
            try: return self.engine.apply(pid)["status"]
            except ValueError: return "blocked"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, range(2)))
        self.assertEqual(sorted(results), ["blocked", "verified"])
        self.assertEqual(self.adapter.calls, 1)
    def test_cancel_approved_plan_blocks_apply_and_allows_new_plan(self):
        pid = self.plan()
        self.engine.approve(pid)
        self.engine.cancel(pid)
        with self.assertRaises(ValueError): self.engine.apply(pid)
        self.assertNotEqual(pid, self.plan())
        self.assertEqual(self.adapter.calls, 0)
    def test_private_state_permissions(self):
        self.assertEqual(Path(self.tmp.name).stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.engine.db.stat().st_mode & 0o777, 0o600)


class LinuxTests(unittest.TestCase):
    def test_input_injection_rejected(self):
        for host in ("-oProxyCommand=evil", "host;id", "x$(id)", "user@host bad"):
            with self.assertRaises(ValueError): Linux(host)
        for name in ("--help", "a.service;id", "a\n.service", "a.service/../../"):
            with self.assertRaises(ValueError): Linux(services=[name])
    def test_remote_uses_strict_ssh_and_argv(self):
        adapter = Linux("dev@my-host", ["example.service"])
        with patch("triage.linux.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "{}", "")) as run:
            adapter.collect()
        args = run.call_args.args[0]
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertEqual(args[-3:], ["dev@my-host", "python3", "-"])
        self.assertNotIn("shell", run.call_args.kwargs)
    def test_unauthorized_restart_never_dispatches(self):
        with patch("triage.linux.subprocess.run") as run:
            with self.assertRaises(ValueError): Linux().restart("example.service")
            run.assert_not_called()
    def test_unavailable_command_reports_failure(self):
        with patch("triage.linux.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaises(RuntimeError): Linux().collect()
    def test_real_readonly_local_collection(self):
        report = Linux().collect()
        self.assertIn("disk_used_percent", report)
        self.assertIn("memory_used_percent", report)
        self.assertEqual(report["services"], {})
    def test_diagnosis_is_evidence_based(self):
        state = FakeLinux().collect()
        state.update(disk_used_percent=95, memory_used_percent=96, load1=5)
        self.assertEqual({f["code"] for f in diagnose(state)}, {"disk-pressure", "memory-pressure", "high-load", "failed-service"})
    def test_missing_unit_cannot_offer_restart(self):
        state = FakeLinux().collect()
        state["services"]["example.service"]["LoadState"] = "not-found"
        finding = diagnose(state)[0]
        self.assertEqual(finding["code"], "missing-service")
        self.assertIsNone(finding["service"])
    def test_healthy_thresholds_have_no_findings(self):
        state = FakeLinux().collect()
        state["services"] = {}
        state.update(disk_used_percent=89, memory_used_percent=89, load1=3)
        self.assertEqual(diagnose(state), [])


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.adapter = FakeLinux()
        self.engine = Engine(self.adapter, self.tmp.name)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.engine, "secret", 1))
        self.port = self.server.server_address[1]
        self.server.RequestHandlerClass = make_handler(self.engine, "secret", self.port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
    def request(self, route, data=None, headers=None, method="POST"):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        hdr = {"X-Triage-Token": "secret", "Content-Type": "application/json"}
        if headers: hdr.update(headers)
        conn.request(method, route, body=json.dumps(data or {}) if method == "POST" else None, headers=hdr)
        r = conn.getresponse()
        body = r.read().decode()
        status = r.status
        conn.close()
        return status, body
    def test_cross_origin_blocked(self):
        self.assertEqual(self.request("/api/scan", headers={"Origin": "https://attacker.example"})[0], 403)
    def test_dns_rebinding_host_blocked(self):
        self.assertEqual(self.request("/", headers={"Host": "attacker.example"}, method="GET")[0], 403)
    def test_invalid_token_blocked(self):
        self.assertEqual(self.request("/api/scan", headers={"X-Triage-Token": "wrong"})[0], 403)
    def test_unknown_route(self):
        self.assertEqual(self.request("/api/unknown")[0], 404)
    def test_dashboard_embeds_session_and_no_placeholders(self):
        code, body = self.request("/", method="GET")
        self.assertEqual(code, 200)
        self.assertNotIn("__TOKEN__", body)
    def test_readonly_scan(self):
        code, body = self.request("/api/scan")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["target"], "test-host")
        self.assertEqual(self.adapter.calls, 0)
    def test_full_approval_flow(self):
        code, raw = self.request("/api/plan", {"service": "example.service"})
        self.assertEqual(code, 200)
        pid = json.loads(raw)["id"]
        self.assertEqual(self.request("/api/apply", {"id": pid})[0], 400)
        self.assertEqual(self.request("/api/approve", {"id": pid})[0], 200)
        code, raw = self.request("/api/apply", {"id": pid})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(raw)["status"], "verified")
        self.assertEqual(self.request("/api/apply", {"id": pid})[0], 400)
        self.assertEqual(self.adapter.calls, 1)


if __name__ == "__main__":
    unittest.main()
