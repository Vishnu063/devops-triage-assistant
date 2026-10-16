"""Persistent single-use approvals, bound to exact target, service state, and expiry."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
from .linux import diagnose


def fingerprint(state):
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


class Engine:
    def __init__(self, adapter, state_dir=None):
        self.adapter = adapter
        root = Path(state_dir or Path.home() / ".local/state/devops-triage")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        self.db = root / "triage.db"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS events (time REAL, plan TEXT, event TEXT, detail TEXT)")
        os.chmod(self.db, 0o600)

    def connect(self):
        return sqlite3.connect(self.db, timeout=10)

    def event(self, db, plan, event, detail=""):
        db.execute("INSERT INTO events VALUES (?, ?, ?, ?)", (time.time(), plan, event, detail))

    def scan(self):
        snapshot = self.adapter.collect()
        return {"target": self.adapter.target, "snapshot": snapshot, "findings": diagnose(snapshot),
                "coverage": "Linux: root disk capacity, available memory, load, allowlisted systemd services"}

    def plan(self, service):
        if service not in self.adapter.services:
            raise ValueError("Service is not allowlisted")
        snapshot = self.adapter.collect()
        state = snapshot.get("services", {}).get(service, {})
        if state.get("LoadState") != "loaded" or state.get("ActiveState") != "failed":
            raise ValueError("A restart plan requires a loaded, failed service")
        p = {"id": uuid.uuid4().hex, "target": self.adapter.target, "service": service,
             "state_hash": fingerprint(state), "expires_at": time.time() + 300,
             "command": ["sudo", "-n", "systemctl", "restart", "--", service],
             "risk": "Restart may interrupt traffic and repeat the underlying failure.",
             "rollback": "A restart has no automatic rollback. Correct configuration or recover using your service runbook.",
             "verification": "The unit must report ActiveState=active after restart; application health still requires separate checks."}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for old_id, raw, status in db.execute("SELECT id, payload, status FROM plans WHERE status IN ('pending','approved','executing')").fetchall():
                old = json.loads(raw)
                if status != "executing" and old["expires_at"] <= time.time():
                    db.execute("UPDATE plans SET status='expired' WHERE id=?", (old_id,))
                    self.event(db, old_id, "expired")
                elif old["target"] == p["target"] and old["service"] == service:
                    raise ValueError("An active plan already exists for this target and service; inspect it with show/history")
            db.execute("INSERT INTO plans VALUES (?, ?, 'pending')", (p["id"], json.dumps(p)))
            self.event(db, p["id"], "planned")
        return p

    def validate(self, p):
        if p["target"] != self.adapter.target or p["service"] not in self.adapter.services:
            raise ValueError("Plan target or allowlist changed")
        if time.time() >= p["expires_at"]:
            raise ValueError("Plan expired; collect a new plan")
        state = self.adapter.collect().get("services", {}).get(p["service"], {})
        if fingerprint(state) != p["state_hash"]:
            raise ValueError("Service state changed; collect a new plan")

    def approve(self, plan_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload, status FROM plans WHERE id=?", (plan_id,)).fetchone()
            if not row or row[1] != "pending":
                raise ValueError("Plan is missing or is no longer pending")
            self.validate(json.loads(row[0]))
            db.execute("UPDATE plans SET status='approved' WHERE id=?", (plan_id,))
            self.event(db, plan_id, "approved")
        return {"id": plan_id, "status": "approved"}

    def apply(self, plan_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload, status FROM plans WHERE id=?", (plan_id,)).fetchone()
            if not row or row[1] != "approved":
                raise ValueError("Explicit approval is required; approvals can only be used once")
            p = json.loads(row[0])
            self.validate(p)
            db.execute("UPDATE plans SET status='executing' WHERE id=?", (plan_id,))
            self.event(db, plan_id, "executing")
        # Consume approval before dispatch. Never automatically retry after timeout/crash.
        try:
            self.adapter.restart(p["service"])
            state = self.adapter.collect().get("services", {}).get(p["service"], {})
            status = "verified" if state.get("ActiveState") == "active" else "needs_attention"
        except RuntimeError:
            status = "needs_attention"
        with self.connect() as db:
            db.execute("UPDATE plans SET status=? WHERE id=?", (status, plan_id))
            self.event(db, plan_id, status)
        return {"id": plan_id, "status": status,
                "note": "Verify application health separately. If interrupted, inspect the target before creating another plan."}

    def history(self):
        with self.connect() as db:
            return [dict(time=t, plan=p, event=e, detail=d) for t, p, e, d in db.execute("SELECT * FROM events ORDER BY time DESC LIMIT 100")]

    def show(self, plan_id):
        with self.connect() as db:
            row = db.execute("SELECT payload, status FROM plans WHERE id=?", (plan_id,)).fetchone()
            if not row:
                raise ValueError("Unknown plan")
            return {**json.loads(row[0]), "status": row[1]}

    def cancel(self, plan_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM plans WHERE id=?", (plan_id,)).fetchone()
            if not row or row[0] not in ("pending", "approved"):
                raise ValueError("Only pending or approved plans can be cancelled")
            db.execute("UPDATE plans SET status='cancelled' WHERE id=?", (plan_id,))
            self.event(db, plan_id, "cancelled")
        return {"id": plan_id, "status": "cancelled"}
