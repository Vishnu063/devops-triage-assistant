# DevOps Triage Assistant

Understand live evidence, investigate likely causes, and review a specific repair before approving it.

**v0.3: Linux plus 60 tool profiles, connection setup and incident recovery workflows.** Automated coverage includes profiles, approval controls, health policies, previews, rollback and incident history. Most provider responses and resource mutations use fixtures. Docker also has three passing real acceptance cases in a disposable GitHub CI lab; production and other-tool acceptance remain pending. See [test results and limits](docs/TEST_RESULTS.md) and the [disposable Docker lab](docs/DOCKER_LAB.md).

## What you can do

- Select Linux or one of 60 cloud, container, CI/CD, infrastructure, monitoring, security, access, networking and database profiles.
- Collect scoped live evidence through native CLIs or HTTPS APIs.
- Read what happened, the observed facts, likely explanations, and investigation steps.
- See explicit connection, permission, missing-evidence and compatibility errors instead of a simulated healthy result.
- Review and approve supported repairs in the CLI or local dashboard.
- Keep expiring single-use approvals, exact target/command bindings, state-change protection, cancellation and repair history.

**Profile coverage is specific, not universal.** AWS currently checks one EC2 instance, CDK checks a deployed CloudFormation stack, Kustomize checks local rendering, and Ansible inspects inventory. See the [full coverage table](docs/INTEGRATIONS.md) for every tool's exact scope and required configuration.

## Install

Client: Linux, Python 3.11+, and the native CLI for each selected CLI-based profile. API-based profiles need no extra Python packages. Authentication uses your existing credential stores or environment variables; the assistant does not configure cloud accounts or install third-party tools.

```bash
git clone https://github.com/Vishnu063/devops-triage-assistant.git
cd devops-triage-assistant
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
devops-triage tools
```

No live connection is attempted by `tools`. Configuration templates and tool metadata do not establish connection health.

## Start with Linux

```bash
devops-triage diagnose
devops-triage web
```

Open **http://127.0.0.1:8765**. Checks run only when requested. Linux supports local or trusted SSH targets:

```bash
devops-triage --target ops@your-server --service nginx.service diagnose
```

Remote Linux requires Python 3 and systemd for service inspection. SSH uses existing configuration, noninteractive authentication and strict host-key checking. Service restarts require separately configured, narrowly scoped noninteractive sudo permission for the exact command.

## Configure the other tools

Copy `examples/connections.example.json` to an ignored `connections.json`, fill in the selected tool's fields, and remove entries you do not need. The template contains all 60 profiles with null values so it cannot silently target an example account.

For example, a Docker and Kubernetes configuration can contain:

```json
{
  "tools": {
    "docker": {"context": "default", "resource": "your-container"},
    "kubernetes": {
      "context": "your-explicit-kube-context",
      "namespace": "your-namespace",
      "resource": "your-deployment"
    }
  }
}
```

```bash
devops-triage --config connections.json --tool docker diagnose
devops-triage --config connections.json web
```

The dashboard lists all tools, connection requirements, exact collector scopes and executable actions. Its connection wizard saves validated settings privately and applies them immediately. Credentials are environment-variable references; no arbitrary command field is exposed.

See [connection examples](docs/CONNECTIONS.md) for API authentication, cloud profiles, databases and scanner behavior.

## Connection and incident workflow

Use the connection wizard and explicit read validation, request deeper evidence where supported, review confidence and a fix preview, and inspect the incident timeline and local alert inbox. Optional application probes require consecutive successes. Kubernetes rollback always needs a second approval.

```bash
devops-triage --tool docker setup
devops-triage --tool docker validate
devops-triage --tool docker diagnose --deep
devops-triage correlate linux docker kubernetes --deep
devops-triage timeline
devops-triage alerts
```

See [the full workflow and exact feature boundaries](docs/RECOVERY_WORKFLOW.md). Live validation needs configured authorized systems; no external provider acceptance is implied by automated tests.

## Approved repairs

Executable actions currently include:

| Integration | Action |
| --- | --- |
| Linux | Restart an allowlisted, loaded, failed systemd service |
| Docker | Restart one configured container in a failed/non-running state |
| Podman | Restart one configured container in a failed/non-running state |
| Kubernetes | Rollout restart one configured Deployment with unavailable replicas |
| GitHub Actions | Rerun failed jobs of one failed/timed-out run |
| GitLab CI/CD | Retry failed jobs in one failed pipeline |

**The other profiles provide diagnosis and runbooks; they do not execute fixes yet.** Kubernetes can also propose a separately approved rollback to a captured revision after failed recovery; see the recovery workflow. Pipeline retries may execute deployment jobs and incur costs. Container/deployment restarts can interrupt service and repeat the original failure. No action has automatic rollback.

```bash
devops-triage --config connections.json --tool docker plan restart
devops-triage --config connections.json --tool docker show PLAN_ID
devops-triage --config connections.json --tool docker approve PLAN_ID
devops-triage --config connections.json --tool docker apply PLAN_ID
```

Replace `PLAN_ID` with the generated ID. `approve` displays the full plan and requires typing its ID. Approval alone does not execute the action. In the dashboard use **Review action → Approve this exact plan → Run approved action**.

A plan expires five minutes after creation. Fresh evidence, the tool, connection scope and command must still match at approval and execution. An approval is consumed before dispatch. Concurrent duplicate execution is blocked locally. Timeouts are never automatically retried.

```bash
devops-triage --config connections.json --tool docker cancel PLAN_ID
devops-triage history
```

After a page reload, use repair history and **Review stored plan** to recover a plan. Select its integration first. An interrupted execution stays consumed; inspect the actual target before another attempt. There is no administrative recovery command for a plan stuck executing.

## What verification means

`verified` requires the configured state probe and, when supplied, the application health policy. Without an application endpoint, the result explicitly covers state only. A container running state is not full application health, and CI retry verification establishes scheduling rather than successful completion. If a rollout is still progressing after the observation window, the result is `needs_attention`.

External changes can occur between state inspection and command execution. Use a single incident owner and your normal change controls. This is not an exactly-once distributed transaction system or a production-certified control plane.

## Privacy and permissions

- Use read-only accounts for diagnosis and add narrowly scoped mutation permissions only for selected actions.
- API URLs require HTTPS; loopback HTTP is supported for local services or SSH tunnels. TLS checks stay enabled. Redirects and environment HTTP proxies are not used by the API transport.
- Authentication headers refer to environment variables; do not place secret values in configuration. Database native credential files must be private and user-managed.
- Only selected metadata fields are retained. Secret values, Kubernetes manifests, application log bodies and scanner code snippets are not included in reports. Raw stdout is held transiently for parsing and raw stderr is withheld from reports.
- CLI/API responses are capped at 1 MiB. Displayed field values are capped at 200 per field; truncated evidence cannot authorize a repair.
- Plans and history are local in `~/.local/state/devops-triage/`, with private directory/database permissions. Local history is not tamper-proof against the account owner or root and has no rotation policy yet.
- Keep the dashboard on loopback. It has no shared-user authentication, RBAC or public hosting support.
- Native CLIs and their configuration/plugins must be trusted. Scanner profiles can download vulnerability databases or contact their analysis provider. No external LLM is used.

## Build and development status

CI builds a wheel and runs the automated suite on Python 3.11, 3.12 and 3.13 for normal pushes/PRs. The suite includes 60 individually named synthetic-response profile tests, tool repair/approval tests, bounded native-process transport tests and real loopback HTTP tests. A separate CI job opts into three real Docker diagnosis/recovery cases on owned disposable containers. A manual run can enable `run_tests`. The earlier `[skip tests]` marker is absent from this verification update.

See [integration coverage](docs/INTEGRATIONS.md), [architecture](docs/ARCHITECTURE.md), [roadmap](docs/ROADMAP.md), [contributing](CONTRIBUTING.md), and [security reporting](SECURITY.md).
