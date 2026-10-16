# DevOps Triage Assistant

Understand a live incident, review the evidence, and approve a specific repair before it runs.

**Status: early Linux MVP, not a production-ready autonomous agent.** Linux is the first integration; the [60-tool roadmap](docs/ROADMAP.md) records the remaining scope honestly. This release uses deterministic rules and does not send evidence to an AI provider.

## What works today

- Collect live Linux root filesystem usage, available memory, load, and explicitly selected systemd service states.
- Connect to the machine running the tool or a trusted host through OpenSSH.
- Explain observed problems, likely causes, uncertainty, and investigation steps.
- Propose a restart only for an allowlisted, loaded service currently in `failed` state.
- Review target, exact command, interruption risk, verification, and rollback limitations before approval.
- Store expiring, single-use approvals and local repair history in a private SQLite database.
- Block unapproved repairs, changed service state, changed targets, expired plans, concurrent duplicate execution, and services outside the allowlist.
- Use the same engine through the CLI and a loopback-only web dashboard.

No restart happens during diagnosis or planning. No deletion, arbitrary command execution, package installation, or automatic retries are offered.

## Quick start

Requires **Linux and Python 3.11+**. Systemd is required for service checks and repairs. No cloud subscription or AI API key is needed.

```bash
git clone https://github.com/Vishnu063/devops-triage-assistant.git
cd devops-triage-assistant
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
devops-triage diagnose
devops-triage web
```

Open **http://127.0.0.1:8765**. Click **Run live checks**. The dashboard displays collected measurements, not demo data. Without `--service`, no service repair is possible.

### Inspect a live server

Configure a working SSH key and verify its host key through your normal trusted process first. The assistant uses existing OpenSSH configuration, noninteractive authentication, and strict host-key checking. The remote machine needs Linux and `python3`.

```bash
devops-triage --target ops@your-server --service nginx.service diagnose
devops-triage --target ops@your-server --service nginx.service web
```

The dashboard stays on your local machine; its checks execute on the configured server. Hosts are selected at startup, not from browser-supplied input. SSH aliases or `user@hostname` are supported; configure nondefault ports, jump hosts, or IPv6 endpoints in `~/.ssh/config`.

### Review and run a repair

Use a disposable lab first. Replace `PLAN_ID` with the ID printed by `plan`; these commands do not supply approval automatically.

```bash
devops-triage --target ops@your-server --service nginx.service plan nginx.service
devops-triage --target ops@your-server --service nginx.service show PLAN_ID
devops-triage --target ops@your-server --service nginx.service approve PLAN_ID
devops-triage --target ops@your-server --service nginx.service apply PLAN_ID
devops-triage history
```

`approve` displays the complete plan and asks you to type its full ID. In the dashboard, use **Review restart plan → Approve this exact plan → Run approved restart**. You can cancel a pending or approved plan with `devops-triage cancel PLAN_ID` or the dashboard's **Cancel plan** button.

A restart requires narrowly scoped, preconfigured noninteractive sudo permission for the exact systemctl command on the target. The assistant does not grant permissions or request/store sudo passwords. Do not give it blanket sudo access.

Plans expire five minutes after creation. Approval does not refresh expiry. At approval and immediately before execution, the service state must still match the planned state. Only one pending/approved/executing plan per target and service is allowed. An expired plan can be replaced. Execution is consumed before dispatch so an interrupted request cannot silently retry a repair.

### Verification and recovery

`verified` means systemd reported `ActiveState=active` in the immediate post-restart sample. It **does not** establish endpoint health, dependency health, sustained availability, or recovery of user traffic. Long-running oneshot services may need a different verification policy and are not covered by this restart workflow.

`needs_attention` means dispatch failed/timed out or the unit did not report active. Inspect the target and the service runbook before another attempt. If the assistant crashes during execution, the plan remains `executing` and cannot be reused. Reconcile target state and preserve history; there is currently no built-in administrative recovery command for that state.

A restart has **no automatic rollback**. Configuration repair, deployment rollback, and application health probes are future integrations. Check-to-execution races cannot be eliminated against external administrators or other automation; use a maintenance window and a single incident owner.

## Quality checks

```bash
python -m unittest discover -s tests -v
```

CI installs the package and runs the suite on Python 3.11, 3.12, and 3.13. Tests cover approval bypass attempts, expiry, state changes, target and allowlist changes, concurrency, cancellation, timeout handling, HTTP origin/host/token controls, and live local read-only collection. Mutation tests use a fake adapter and never restart a real service.

Remote SSH and actual service restarts still require acceptance testing against your disposable server. See [Linux acceptance checklist](docs/LINUX_ACCEPTANCE.md). Browser rendering has not yet been manually verified.

## Privacy and deployment boundaries

- Collection is on demand, not continuous monitoring. Thresholds are fixed at 90% root disk usage, 90% memory usage, and load1 above 1.5 × logical CPUs.
- Service names, host identity, resource measurements, and state fingerprints are processed locally. Journal bodies, process environments, secret values, and application log contents are not collected.
- Plans and audit events live under `~/.local/state/devops-triage/` by default. Override with `--state-dir` on a trusted, user-owned local directory. Database permission is 0600 and directory permission is 0700.
- Run under a dedicated unprivileged account. Local audit history is not tamper-proof against its owner or root and has no rotation policy yet.
- The dashboard binds only to `127.0.0.1`. Keep it local; this release has no multi-user login, RBAC, TLS termination, or internet-facing deployment support. Do not expose it through a public reverse proxy.
- SSH trust/configuration and target authorization remain under the operator's control. Do not run against systems you are not authorized to administer.

See [architecture](docs/ARCHITECTURE.md), [contributing](CONTRIBUTING.md), and [security reporting](SECURITY.md).
