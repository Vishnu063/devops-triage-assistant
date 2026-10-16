# Connection and recovery workflow (v0.3)

## Eight additions and their boundaries

| Feature | Implemented behavior | Boundary |
| --- | --- | --- |
| Connection wizard | CLI setup and browser forms, required fields, environment-based API authentication, private atomic save, immediate runtime update | It does not acquire credentials or install CLIs. Linux SSH/service settings remain startup flags. |
| Live validation | Explicit read-only collector check, missing CLI/credential/permission errors, configured application probe; Kubernetes can-i authorization review for deployment patch | Other mutation permissions are not exercised. A passing collector does not certify all permissions or tool health. |
| Deeper diagnosis | Baseline metrics/state, changes since previous scan, opt-in Docker/Podman log signatures and Kubernetes Deployment events/log signatures, correlation of up to four chosen sources | No inferred topology. Deep collection is not yet available for all tools. Raw log lines and event messages are not persisted. |
| Confidence | Confirmed observations, possible causes, corroborated evidence, explanation of missing causal evidence | No fabricated probability or automatic claim of proven root cause. |
| Fix preview | Captured before-state, exact operation, impact, expected verification and health policy | Descriptive preview, not a provider dry run or guarantee. |
| Rollback | Separately planned/approved restoration of a captured Kubernetes Deployment revision after failed recovery | No automatic rollback, no rollback for restart-only containers/Linux or CI retries, no schema/database reversal. |
| Application health | Bounded GET probes, expected statuses, optional JSON assertion, consecutive success requirement, isolated credential references | Checks only the configured endpoint and assertion, not complete business behavior. |
| Timeline and alerts | Persistent scan/change/plan/approval/outcome/rollback records, local alert inbox, deduplication and acknowledgement | On-demand operation; no background monitoring or external email/Slack messages. History is local and not tamper-proof against its owner. |

## Start the wizard

```bash
devops-triage --tool docker setup
devops-triage --config connections.json --tool docker validate
devops-triage --config connections.json web
```

A missing file can be created by setup or the browser wizard. An existing connections.json in the current directory is loaded by default. Explicit --config selects a different file. Saves use a temporary private file and atomic replacement; other tool entries are preserved. Save does not connect or attempt a repair. Use Validate connection separately.

In the browser, select a tool, open Connection wizard, enter required fields, and optionally provide an application health URL. API authentication JSON uses environment-variable references only. Native CLI tools use their existing credential stores. Saving applies to the running dashboard; direct edits to the file require restarting the dashboard.

## Application health policy

Add application_health inside a tool's connection object:

```json
{
  "context": "your-context",
  "namespace": "your-namespace",
  "resource": "your-deployment",
  "application_health": {
    "url": "https://your-app.example/health",
    "expected_status": [200],
    "json_path": "status",
    "equals": "ok",
    "attempts": 3,
    "successes": 2,
    "timeout": 3,
    "interval": 1
  }
}
```

Timeout is per request and capped at five seconds; attempts are capped at five. Two consecutive successes out of three samples is the default. Omitting json_path checks status only. HTTPS is required except loopback HTTP/tunnels. Redirects are blocked. HTTP bodies are not retained. Optional headers use the same env/prefix binding syntax as API connections, and provider credentials are never automatically forwarded to the application.

For Linux, use `--health-url https://your-app.example/health` alongside --target/--service. With no endpoint configured, results explicitly report that application health is not verified. Health policy changes invalidate old approval plans.

If a state repair reports success but the application probe fails, the final plan status becomes needs_attention and a local warning alert is recorded. The timeline retains both the infrastructure result and application-level result.

## Gather and correlate evidence

```bash
devops-triage --tool docker diagnose --deep
devops-triage correlate linux docker kubernetes --deep
devops-triage timeline
devops-triage alerts
```

Use --config when the connection file is not the default. Deep collection is explicit and may require separate logs/events permissions. Docker/Podman capture signature counts from at most the last 100 log lines; Kubernetes captures bounded workload log signatures and Deployment-owned event metadata. Missing data is reported. Messages, source snippets, runtime environment values and raw log text are not stored in incidents.

Changes are differences between collected samples. They do not identify the actor, exact change time or causal relationship. Correlation only uses the sources you select; confirm they represent related workloads and investigate the causal sequence yourself.

## Review, approve and recover

```bash
devops-triage --tool kubernetes plan rollout-restart
devops-triage --tool kubernetes approve PLAN_ID
devops-triage --tool kubernetes apply PLAN_ID
```

The preview shows the exact operation and impact. The approval is expiring and single-use, and live evidence is rechecked. An outcome records state verification, application health and its incident ID. No subsequent repair is automatically retried.

### Separately approved Kubernetes rollback

A failed recovery may offer rollback_available when the original revision, UID, generation and template hash were captured and the observed Deployment is exactly one generation beyond that plan. No later generation or template change may intervene.

```bash
devops-triage --tool kubernetes rollback FAILED_PLAN_ID
devops-triage --tool kubernetes show ROLLBACK_PLAN_ID
devops-triage --tool kubernetes approve ROLLBACK_PLAN_ID
devops-triage --tool kubernetes apply ROLLBACK_PLAN_ID
```

Planning captures the exact `kubectl rollout undo ... --to-revision=N` operation and requires a second approval. Execution is consumed before dispatch. Verification requires restoration of the original template hash, observed generation/available replicas, and configured application health. Missing revision history, unknown outcomes, changed evidence or failed verification require manual investigation; the assistant never chooses another revision or runs a fallback shell command.

Kubernetes must still retain the captured revision. The assistant cannot restore garbage-collected ReplicaSets, external secrets, database migrations or resources outside that Deployment. Competing administrators/automation can race any check; coordinate changes with a single incident owner.

## Alerts and history

The dashboard displays unread local alerts after scans and recovery results. Open Alerts to acknowledge messages. Success creates informational recovery alerts; failures and findings create warnings. Identical target/message alerts are deduplicated for ten minutes. No notification is sent to another person or external service.

The Incident timeline displays recorded evidence, differences, previews, approvals, execution requests, repair results and rollback results. Each record is bounded, but the database currently has no automatic retention/rotation; manage it as private operational data.

## Validation status

Feature behavior is covered by automated synthetic-resource and disposable loopback endpoint tests. These tests do not substitute for live provider acceptance, real production recovery or rendered browser QA. Configure authorized disposable targets and use Validate connection before proposing a repair.
