# Test results — v0.4, 2026-10-17

**231 unit/API tests passed locally** on Linux with Python 3.12.14. Normal discovery now finds 235 cases: those 231 plus three opt-in Docker cases and one opt-in Kubernetes case, skipped locally where Docker is unavailable. **All three real Docker acceptance cases passed separately on GitHub CI.** The final full run completed successfully after the feature implementation and fixes.

Command: `python -m unittest discover -s tests -v`

## Operations update

Local discovery: **232 cases, 228 passed, four opt-in acceptance cases skipped** (three Docker and one Kubernetes). The new tests cover ownership-scoped Kubernetes failure types and deployment comparisons, private-body exclusion, denied-versus-missing configuration, bounded/incomplete results, profile target isolation, private profile saves, repair follow-up comparisons, linked escalation outcomes, incident search, CI failure policies, prerequisite guidance and synthetic benchmark behavior.

**Real Kubernetes acceptance passed** on an owned disposable kind v0.33.0 / Kubernetes v1.37.0 cluster: [passing run](https://github.com/Vishnu063/devops-triage-assistant/actions/runs/38963666307). It verified actual probe events, image-pull failures, missing referenced configuration, a mismatching selected Service, and retained revision image comparison. Diagnosis performed no repairs; the owned namespace and cluster were cleaned up. This is scoped lab compatibility, not production certification.

**Real CPU inference completed** with Ollama 0.40.5 and `qwen2.5:0.5b`: [initial measured run](https://github.com/Vishnu063/devops-triage-assistant/actions/runs/38963682749). Linux x86_64, four reported vCPUs: Docker OOM 4.827 s, Kubernetes image 2.200 s, Linux disk 2.808 s. Sampled peak process-tree RSS was 561,311,744 bytes (~535 MiB); peak reported loaded-model size was 458,804,427 bytes (~438 MiB). Sampling can miss peaks or double-count shared pages; these are not universal RAM requirements.

**Human review rejected the initial answers as reliable diagnoses.** They included unsupported healthy/unhealthy application claims, claimed image presence without evidence, mislabeled load average as a percentage and downplayed 96% disk usage. [Raw synthetic-case measurements and review](OLLAMA_INITIAL_BENCHMARK.json) are retained for regression tests. Known contradictory/unsupported patterns are now withheld from normal explanations; guided findings remain available. This is not complete factual validation, and other errors can pass. A completed benchmark is separate from accepted explanation count and does not certify answer quality. The browser suite now also exercises profiles, prerequisite hints, evidence bundles, rechecks, incident search and escalation downloads.

## First-use and investigation update

Local full discovery: **206 cases, 203 passed, three opt-in Docker cases skipped**. Fifteen new tests verify isolated synthetic samples, bounded guided questions, no chat-authorized execution, incomplete evidence and application-health wording, filtered summary export, CLI demo independence, authenticated sample APIs, latest-incident matching, and canonical-topic-only Ollama follow-ups.

The updated wheel built successfully. JavaScript syntax, relative Markdown links and whitespace checks passed. Local browser launch was unavailable because the Chromium download failed. **The real desktop/mobile browser workflow passed** on implementation commit `8b70c64a5ef807bef8143591597021f86d9d71fc`: [passing run and screenshots](https://github.com/Vishnu063/devops-triage-assistant/actions/runs/38957325022). It exercised sample flows, guided questions, integration search, missing-connection errors, the connection wizard, live Linux diagnosis and filtered downloads. Desktop and mobile captures were visually reviewed; no horizontal mobile overflow or browser script errors were reported. This is scoped browser verification, not a full accessibility audit. Python 3.11/3.12/3.13, packaging, documentation and the disposable real Docker lab also passed on this implementation.

## Optional local Ollama update

Local discovery after the AI integration: **191 cases, 188 passed, three opt-in Docker cases skipped**. The additional 13 tests cover filtered evidence privacy, offline fallback, model validation/cloud exclusion, malformed and oversized replies, serialized inference, a real disposable loopback Ollama-compatible endpoint, authenticated opt-in and incident matching, and CLI behavior with and without AI. No actual model was downloaded or run; model quality and real Ollama inference remain pending. The existing Docker acceptance result below predates this AI update.

The updated wheel also built successfully. Dashboard JavaScript syntax and relative documentation links passed checks. See [local AI](LOCAL_AI.md) for settings and limitations.

## Real Docker acceptance

[Passing GitHub run](https://github.com/Vishnu063/devops-triage-assistant/actions/runs/38878641638), source commit `1743f0907b78564558103d4f3754d1576b1fc476`, 2026-10-16. The package job and unit/API jobs on Python 3.11, 3.12 and 3.13 also passed.

The Docker job used an explicitly local Unix socket and owned disposable Python HTTP-server containers. All three cases passed:

- Real inspect metadata, bounded stderr log signatures, private-field exclusion, application health and incident history.
- Real stopped-container diagnosis, rejection before approval, lab-only explicit approval, actual restart, consecutive application health verification, replay rejection and success alert.
- Independent state change invalidating a previously created repair plan.

The first live run failed its recovery health check. The lab had used an automatically assigned Docker host port, which was unsuitable for the fixed endpoint across a restart. Assigning and checking a stable loopback port fixed the lab; no product approval or health logic was bypassed. See DOCKER_LAB.md for isolation, cleanup and opt-in instructions.

This validates this scoped Docker workflow in the CI environment, not arbitrary Docker installations or production availability. No user-owned production container was touched.

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
| Dashboard API | Session/host/origin controls, tool selection, wizard save/validate, timeline, alerts, correlation and existing approval flows | First-use desktop/mobile flows also passed real browser checks with reviewed screenshots; a full accessibility audit remains pending |
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

No authorized user-owned live provider connections were supplied. Beyond the scoped disposable Docker acceptance above, the other 59 products, deployed CLI/API variants, private CA/TLS environments, real Kubernetes rollback, sustained application behavior, remote SSH and rendered browser QA remain unverified. Use the new connection wizard and explicit Validate connection action with disposable authorized targets.

GitHub Actions builds the wheel and runs the suite on Python 3.11, 3.12 and 3.13. Check the Actions result for this verification commit; a previous package-only build does not establish test success.
