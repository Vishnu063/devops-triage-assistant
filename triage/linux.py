"""Bounded Linux collection. No log bodies, credentials, or shell interpolation."""
import json
import re
import subprocess
import sys

SERVICE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}\.service\Z")
HOST = re.compile(r"(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
# Passed on stdin to the same Python collector locally or over OpenSSH.
COLLECTOR = r'''
import json, os, shutil, subprocess, time
from pathlib import Path
services = SERVICES
out = {"collected_at": time.time(), "hostname": os.uname().nodename,
       "cpu_count": os.cpu_count() or 1, "load1": os.getloadavg()[0],
       "services": {}, "errors": []}
try:
    values = {p[0].rstrip(":"): int(p[1]) for line in Path("/proc/meminfo").read_text().splitlines() if len(p := line.split()) >= 2 and p[1].isdigit()}
    out["memory_used_percent"] = round(100 * (1 - values["MemAvailable"] / values["MemTotal"]), 1)
except (OSError, KeyError, ZeroDivisionError) as exc:
    out["errors"].append("Memory collection unavailable: " + type(exc).__name__)
d = shutil.disk_usage("/")
out["disk_used_percent"] = round(100 * d.used / d.total, 1)
for service in services:
    try:
        p = subprocess.run(["systemctl", "show", service, "--property=LoadState,ActiveState,SubState,Result,InvocationID", "--no-pager"], capture_output=True, text=True, timeout=8)
        if p.returncode:
            out["errors"].append("Cannot inspect " + service)
            continue
        out["services"][service] = dict(line.split("=", 1) for line in p.stdout.splitlines() if "=" in line)
    except (OSError, subprocess.TimeoutExpired):
        out["errors"].append("Service check unavailable: " + service)
print(json.dumps(out))
'''


class Linux:
    def __init__(self, target="local", services=()):
        if target != "local" and not HOST.fullmatch(target):
            raise ValueError("Use local or an SSH host alias / user@hostname")
        if len(services) > 20 or any(not SERVICE.fullmatch(s) for s in services):
            raise ValueError("Allow at most 20 explicit names ending in .service")
        self.target = target
        self.services = tuple(sorted(set(services)))

    def command(self, argv, script=None):
        if self.target == "local":
            cmd = argv
        else:
            # Host keys must already be trusted; never silently accept a new key.
            cmd = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                   "-o", "ConnectTimeout=8", "--", self.target, *argv]
        try:
            p = subprocess.run(cmd, input=script, capture_output=True, text=True,
                               timeout=190 if script else 45)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("Target command unavailable or timed out; inspect target state") from exc
        if p.returncode:
            raise RuntimeError("Target command failed; check SSH access, systemd, and permissions")
        return p.stdout

    def collect(self):
        script = COLLECTOR.replace("SERVICES", repr(self.services), 1)
        self.last_snapshot = json.loads(self.command([sys.executable if self.target == "local" else "python3", "-"], script))
        return self.last_snapshot

    def restart(self, service):
        if service not in self.services or not SERVICE.fullmatch(service):
            raise ValueError("Service is not allowlisted")
        return self.command(["sudo", "-n", "systemctl", "restart", "--", service])


def diagnose(snapshot):
    findings = []
    def add(code, title, evidence, why, steps, service=None):
        findings.append(dict(code=code, title=title, evidence=evidence, likely_cause=why,
                             next_steps=steps, service=service))
    if snapshot.get("disk_used_percent", 0) >= 90:
        add("disk-pressure", "Root filesystem is nearly full", f"Root usage: {snapshot['disk_used_percent']}%",
            "Stored data, logs, or container layers may be growing; this sample does not identify the owner.",
            ["Inspect df -h and df -i", "Find the largest directories with du; investigate growth before deleting anything", "Expand storage or apply the application's retention policy"])
    if snapshot.get("memory_used_percent", 0) >= 90:
        add("memory-pressure", "Available memory is low", f"Memory usage: {snapshot['memory_used_percent']}%",
            "Application growth, cache pressure, or a memory leak are possible; process evidence is needed.",
            ["Inspect free -m and top", "Review cgroup limits and OOM events", "Identify the owner before scaling or restarting"])
    if snapshot.get("load1", 0) > snapshot.get("cpu_count", 1) * 1.5:
        add("high-load", "Load exceeds CPU capacity", f"Load1: {snapshot['load1']}; CPUs: {snapshot['cpu_count']}",
            "Runnable tasks or uninterruptible I/O may be queuing; load alone does not prove CPU saturation.",
            ["Inspect top and vmstat 1 5", "Check CPU utilization and I/O wait", "Inspect busy processes and downstream storage"])
    for name, state in snapshot.get("services", {}).items():
        if state.get("LoadState") == "not-found":
            add("missing-service", f"{name} is not installed", str(state),
                "The unit name may be wrong or the package is absent.", ["Verify the unit name and package installation"])
        elif state.get("ActiveState") == "failed":
            add("failed-service", f"{name} has failed", str(state),
                "The last service invocation failed. Configuration, dependencies, resources, or application errors need investigation.",
                [f"Inspect systemctl status {name}", f"Review journalctl -u {name} locally; redact secrets before sharing", "Correct the underlying issue before approving a restart"], name)
    return findings
