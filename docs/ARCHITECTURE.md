# Architecture and repair contract

The CLI and local browser call the same Python engine. The Linux adapter collects bounded live evidence locally or via OpenSSH. A deterministic rule set maps evidence into findings, hypotheses, and investigation steps. It never treats a hypothesis as a proven root cause.

Repair flow:

1. Collect read-only service state and validate the explicit service allowlist.
2. Store a plan with target, service, exact command, observed-state fingerprint, expiry, risk, and verification criteria.
3. Display the plan and receive explicit operator approval.
4. Revalidate target, allowlist, expiry, and service state.
5. Atomically consume the approval before dispatch. Duplicate applications fail closed.
6. Run a fixed argv command without a local shell; strict input validation also prevents remote shell metacharacters in SSH command arguments.
7. Collect fresh service state and record verified or needs_attention. Never automatically retry.

SQLite transactions serialize local plan changes; an active plan prevents duplicate planning for the same target and service. A network timeout means the remote outcome may be unknown. No database transaction can make a remote command exactly-once across all failure modes; the engine deliberately chooses no automatic retries.

The browser has no arbitrary target selection, command input, or credential entry. POST APIs require a per-process session token, an allowed Host, and an absent or matching Origin. Responses disable caching and framing. Dynamic evidence uses textContent, not HTML interpolation. This is local account isolation, not an authentication system for shared hosting.

## Adapter quality gate

Before adding another integration, require:

- A narrow read-only collector with bounded timeouts and explicit scope.
- Findings that cite collected facts and name missing evidence.
- Fixed, allowlisted repair actions and a documented blast radius.
- A target/state-bound, expiring approval contract for every mutation.
- Tool-specific verification and honest rollback limitations.
- Fixtures for common failure cases, negative approval tests, and disposable live acceptance results.
- Documentation listing supported versions, prerequisites, unsupported cases, and permission requirements.

Provider responses and logs are untrusted data. Future LLM-generated explanations may describe evidence; model output must never become an executable command. Future adapters should generalize the currently service-specific plan schema rather than pretending Linux service restarts cover other systems.

## Multi-tool expansion (v0.2)

catalog.py holds 60 individually scoped recipes and rule sets. integrations.py renders fixed argv/URL templates from startup configuration, performs bounded native CLI or HTTPS requests, projects only selected fields, and evaluates rules against observed facts. Non-Linux native commands run on the client using their normal credential stores; Linux retains its local/SSH transport.

ToolEngine reuses the SQLite approval/history lifecycle and adds tool/configuration fingerprints, tool-specific preconditions, exact mutation requests and bounded state verification. Supported executable actions are intentionally fewer than diagnosis profiles; missing repair support produces a runbook, not an arbitrary shell escape.

CLI and browser use the same factory. A browser tool selector chooses an already configured profile; it cannot supply connection endpoints, tokens, arbitrary commands or target credentials. Configuration changes require a server restart. Header credentials are resolved from the environment and excluded from persisted plans. Existing local account isolation and loopback-only deployment boundaries still apply.

This expansion was implemented without new test execution at the operator's request. No production readiness or full platform coverage is implied. The existing Linux test suite predates these changes; no new cross-tool acceptance evidence exists.
