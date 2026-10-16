"""The same persistent approval lifecycle for explicitly supported tool repairs."""
import json
import time
import uuid
from .engine import Engine


class ToolEngine(Engine):
    def scan(self):
        p = self.adapter.profile
        try:
            snapshot = self.adapter.collect()
        except (RuntimeError, ValueError) as exc:
            return {"target": self.adapter.target, "tool": self.adapter.tool,
                    "snapshot": {"collected_at": time.time(), "errors": [str(exc)], "observations": {}},
                    "findings": [{"code": "collection-failed", "title": "Live evidence could not be collected",
                        "evidence": str(exc), "likely_cause": "A connection, credential, permission, scope, or tool compatibility issue needs investigation.",
                        "next_steps": ["Review the connection error", "Confirm the configured resource and native CLI/API prerequisites"], "service": None}],
                    "coverage": p["scope"], "guidance": p["guidance"], "actions": []}
        actions = []
        if self.adapter.repair_allowed(snapshot):
            actions.append({"id": p["repair"]["id"], "risk": p["repair"]["risk"]})
        return {"target": self.adapter.target, "tool": self.adapter.tool, "snapshot": snapshot,
                "findings": self.adapter.findings(snapshot), "coverage": p["scope"],
                "guidance": p["guidance"], "actions": actions}

    def plan(self, action):
        spec = self.adapter.profile["repair"]
        if not spec or action != spec["id"]:
            raise ValueError("No executable repair is implemented for that action; follow the investigation runbook")
        snapshot = self.adapter.collect()
        if not self.adapter.repair_allowed(snapshot):
            raise ValueError("Fresh evidence does not satisfy the repair precondition")
        p = {"id": uuid.uuid4().hex, "target": self.adapter.target, "service": self.adapter.tool,
             "tool": self.adapter.tool, "action": action, "configuration": self.adapter.config,
             "state_hash": self.adapter.state_hash(snapshot), "expires_at": time.time() + 300,
             **self.adapter.repair_description(), "risk": spec["risk"],
             "rollback": "No automatic rollback. Follow the tool-specific recovery runbook.",
             "verification": "Configured state probe only. Validate application behavior and sustained health separately."}
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for old_id, raw, status in db.execute("SELECT id,payload,status FROM plans WHERE status IN ('pending','approved','executing')").fetchall():
                old = json.loads(raw)
                if status != "executing" and old["expires_at"] <= time.time():
                    db.execute("UPDATE plans SET status='expired' WHERE id=?", (old_id,))
                    self.event(db, old_id, "expired")
                elif old["target"] == p["target"] and old["service"] == p["service"]:
                    raise ValueError("An active plan already exists; inspect or cancel it before creating another")
            db.execute("INSERT INTO plans VALUES (?,?,'pending')", (p["id"], json.dumps(p)))
            self.event(db, p["id"], "planned", self.adapter.tool)
        return p

    def validate(self, p):
        if p.get("tool") != self.adapter.tool or p["target"] != self.adapter.target:
            raise ValueError("Selected tool or target configuration changed")
        if time.time() >= p["expires_at"]:
            raise ValueError("Plan expired; create a new plan")
        if p.get("action") != (self.adapter.profile["repair"] or {}).get("id"):
            raise ValueError("Repair definition is no longer available")
        if any(p.get(key) != value for key, value in self.adapter.repair_description().items()):
            raise ValueError("Repair command changed; create a new plan")
        snapshot = self.adapter.collect()
        if not self.adapter.repair_allowed(snapshot) or self.adapter.state_hash(snapshot) != p["state_hash"]:
            raise ValueError("Live evidence changed; review a fresh plan")

    def apply(self, plan_id):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload,status FROM plans WHERE id=?", (plan_id,)).fetchone()
            if not row or row[1] != "approved":
                raise ValueError("An unused explicit approval is required")
            p = json.loads(row[0])
            self.validate(p)
            db.execute("UPDATE plans SET status='executing' WHERE id=?", (plan_id,))
            self.event(db, plan_id, "executing", self.adapter.tool)
        status = "needs_attention"
        failure_reason = "The post-action state did not satisfy the configured probe within its observation window."
        try:
            self.adapter.execute_repair()
            for attempt in range(self.adapter.profile["repair"].get("polls", 1)):
                if attempt:
                    time.sleep(2)
                if self.adapter.verify(self.adapter.collect()):
                    status = "verified"
                    break
        except (RuntimeError, ValueError) as exc:
            failure_reason = str(exc)
        except OSError:
            failure_reason = "Local transport or state access failed; inspect live state before retrying."
        with self.connect() as db:
            db.execute("UPDATE plans SET status=? WHERE id=?", (status, plan_id))
            self.event(db, plan_id, status, self.adapter.tool + (": " + failure_reason if status != "verified" else ""))
        return {"id": plan_id, "status": status,
                "failure_reason": failure_reason if status != "verified" else None,
                "next_steps": self.adapter.profile["guidance"] + ["Inspect the target's actual state and application health before another action."],
                "note": "Verification is limited to the configured state probe. Inspect actual outcome before any new repair; no automatic rollback or retry."}
