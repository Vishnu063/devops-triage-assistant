# Test results — v0.3, 2026-10-16

**175 tests passed locally** on Linux with Python 3.12.14. The final full run completed successfully after the feature implementation and fixes.

Command: `python -m unittest discover -s tests -v`

## Coverage

| Area | Evidence | Boundary |
| --- | --- | --- |
| 60 tool profiles | Individually named tests with handwritten representative responses, metadata projection, findings and missing-evidence checks | Provider responses/native CLI results are simulated; not live compatibility acceptance |
| Existing repairs | Five tool repair lifecycles plus Linux approval, expiry, state/target changes, cancellation, replay and concurrency checks | Resource mutations are simulated |
| Connection wizard | Required-field schema, private atomic save, preservation of other entries, runtime update, invalid credentials/configuration rejection and creation of a new configuration through the CLI | No credential acquisition or third-party CLI installation |
| Permission validation | Read collector validation and non-mutating Kubernetes authorization review behavior | Real external permission scopes remain unverified |
| Application health | Actual disposable HTTP endpoint, consecutive success, intermittent failure, JSON assertions, redirect rejection, bounded policy settings and missing-credential behavior | Local HTTP fixtures, not remote private-CA/provider acceptance |
| Preview and policy | Exact operation/before-state preview, explicit dry-run limitation and changed health policy rejection | A preview is not a simulation of provider effects |
| Rollback | Captured Kubernetes revision/template, separate approval, exact undo command, state/template verification, replay rejection, missing history and evidence drift | Simulated Deployment; no real cluster was changed |
| Evidence and confidence | Signature-only log extraction, unsupported-deep-collector reporting, differences between samples and cautious multi-source hypotheses | No proof of topology or causation from correlation alone |
| Timeline and alerts | Persistent evidence records, local deduplication, acknowledgement and authenticated HTTP endpoints | Local/on-demand alerts, not email/Slack delivery or unattended monitoring |
| Privacy and transports | Projection exclusions, malformed credential validation, actual bounded Python subprocesses, stderr handling, actual loopback requests, redirects and response limits | Not an exhaustive security audit |
| Dashboard API | Session/host/origin controls, tool selection, wizard save/validate, timeline, alerts, correlation and existing approval flows | Rendered browser behavior and accessibility were not visually inspected |
| Linux | Actual local read-only measurements and simulated systemd failures | Remote SSH and real failed-unit restarts remain pending |

## Installed-package checks

- Built and installed the 0.3.0 wheel in an isolated virtual environment.
- Started the installed dashboard outside the repository with a new private configuration file.
- Exercised the real HTTP connection wizard, private file save, immediate 60-profile catalog update, live local Linux scan, configured disposable application health endpoint, incident timeline, local alert API and selected-source correlation.
- Confirmed new configuration file permissions are 0600.
- Checked dashboard JavaScript syntax with Node.
- Real resource mutations were not performed.

## Previously fixed regression cases remain covered

The suite retains checks for Kafka empty-ISR parsing, Semgrep scan errors, malformed environment bindings, literal credential fields hidden in header objects and unused native-profile authentication settings. The original Linux/approval and 60-profile tests remain in the suite.

## Remaining acceptance work

No authorized live external provider connections were supplied. Therefore, live behavior for the 60 products, deployed CLI/API versions, private CA/TLS environments, actual recovery/rollback, sustained application behavior, remote SSH and rendered browser QA remain unverified. Use the new connection wizard and explicit Validate connection action with disposable authorized targets.

GitHub Actions builds the wheel and runs the suite on Python 3.11, 3.12 and 3.13. Check the Actions result for this verification commit; a previous package-only build does not establish test success.
