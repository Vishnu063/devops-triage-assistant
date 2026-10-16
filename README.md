# DevOps Triage Assistant

[Reviewer walkthrough](INTERVIEW.md) · [Portfolio](https://github.com/Vishnu063/Vishnu063/blob/main/PORTFOLIO.md)

Understand live evidence, investigate likely causes, and review a specific repair before approving it.

**v0.3: Linux plus 60 tool profiles, connection setup and incident recovery workflows.** Automated coverage includes profiles, approval controls, health policies, previews, rollback and incident history. Most provider responses and resource mutations use fixtures. Docker also has three passing real acceptance cases in a disposable GitHub CI lab; production and other-tool acceptance remain pending. See [test results and limits](docs/TEST_RESULTS.md) and the [disposable Docker lab](docs/DOCKER_LAB.md).

**New here? [Follow the first-run guide](docs/FIRST_RUN.md)** to check installation, configure one connection, and understand the first diagnosis.

## What you can do

- Select Linux or one of 60 cloud, container, CI/CD, infrastructure, monitoring, security, access, networking and database profiles.
- Collect scoped live evidence through native CLIs or HTTPS APIs.
- Read what happened, the observed facts, likely explanations, and investigation steps.
- See explicit connection, permission, missing-evidence and compatibility errors instead of a simulated healthy result.
- Review and approve supported repairs in the CLI or local dashboard.
- Keep expiring single-use approvals, exact target/command bindings, state-change protection, cancellation and repair history.

**Profile coverage is specific, not universal.** AWS currently checks one EC2 instance, CDK checks a deployed CloudFormation stack, Kustomize checks local rendering, and Ansible inspects inventory. See the [full coverage table](docs/INTEGRATIONS.md) for every tool's exact scope and required configuration.

## Easy installation

**Requires Linux (or Ubuntu in WSL), Git, and Python 3.11+.** Run these three commands:

```bash
git clone https://github.com/Vishnu063/devops-triage-assistant.git
cd devops-triage-assistant
bash start.sh
```

The launcher creates a local Python environment, installs the assistant, and starts the dashboard. No manual activation or system-wide pip installation is needed. The first run needs internet access; later starts reuse the installation.

Open **http://127.0.0.1:8765** on the same computer. Select a tool, open **Connection wizard**, save its settings, and click **Validate connection**. Linux checks are available immediately; other tools need their native CLI or API credentials. The launcher installs only the assistant.

**Next time:** run `bash start.sh` from this folder. Press **Ctrl+C** to stop. CLI commands work through the same launcher:

```bash
bash start.sh diagnose
bash start.sh tools
bash start.sh --tool docker setup
bash start.sh --tool docker validate
```

To use the `devops-triage` commands shown below directly, activate the environment with `source .venv/bin/activate`. This is optional when using `bash start.sh`.

### Installation help

| Problem | What to do |
| --- | --- |
| Python is missing or older than 3.11 | Install Python 3.11+; for a specific executable, run `TRIAGE_PYTHON=python3.12 bash start.sh`. |
| Python cannot create the environment on Ubuntu/Debian | Run `sudo apt install python3-venv` (or the venv package matching your Python version), then retry. |
| Installation fails | Check the pip error and your internet access, then rerun `bash start.sh`. |
| Port 8765 is busy | Run `bash start.sh web --port 8766`, then open `http://127.0.0.1:8766`. |
| Running on a remote server | On your computer, run `ssh -L 8765:127.0.0.1:8765 user@server`, then open the local dashboard URL. |

No live connection is attempted by `tools`. Configuration templates and tool metadata do not establish connection health. Authentication uses your existing credential stores or environment variables.

## Optional free local AI (no API key)

Use **Ollama with `qwen2.5:0.5b`** for short explanations of diagnostic findings. AI is off by default. The assistant still diagnoses and handles approved repairs when Ollama is absent.

1. Install [Ollama](https://ollama.com/download) on the same computer as the assistant. Start its local service (`ollama serve` if it is not already running).
2. Download the small model once:

```bash
ollama pull qwen2.5:0.5b
```

3. Start the dashboard with `bash start.sh`, run live checks, and open **Local AI explanation**. Click **Check Ollama**, enable local AI, then **Explain latest findings**. You can enter another installed local model name.

For the CLI:

```bash
bash start.sh diagnose --ai
bash start.sh --tool docker diagnose --deep --ai
```

`diagnose --ai-model MODEL --ai` selects another installed model. Connections and native tools still need their normal setup.

The default model download is approximately **398 MB**; runtime RAM is higher and depends on the machine. This integration requests CPU mode, a 2,048-token context, a short response and immediate model unloading after completion. No GPU or paid AI API is required. A small model has limited DevOps reasoning ability and can give incorrect suggestions. Normal diagnosis is the best option on very low-memory machines.

Only finding codes, numeric Linux metrics, log signature counts and health/collection flags are sent to `127.0.0.1:11434`. Raw logs, credentials, target names, configuration and free-text evidence are excluded. This intentionally limits how specific AI advice can be. AI output is displayed as untrusted plain text and cannot create, approve or execute repair plans. Requests are manual, serialized and bounded; failures leave the original report available. No model is downloaded automatically, and cloud-backed models are excluded. Model/API checks use automated fixtures and a real loopback HTTP test; real model inference and answer quality have **not** been acceptance-tested here.

See [local AI setup and troubleshooting](docs/LOCAL_AI.md).

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

Use the dashboard's **Connection wizard** to configure one tool at a time. It saves a private `connections.json` for you. For manual setup, copy `examples/connections.example.json` to `connections.json`, fill in your tool's fields, and remove unused entries. The template uses null values so it cannot silently target an example account.

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
- Native CLIs and their configuration/plugins must be trusted. Scanner profiles can download vulnerability databases or contact their analysis provider. No external LLM is used. Optional AI explanations use only a separately installed local Ollama model.

## Build and development status

CI builds a wheel and runs the automated suite on Python 3.11, 3.12 and 3.13 for normal pushes/PRs. The suite includes 60 individually named synthetic-response profile tests, tool repair/approval tests, bounded native-process transport tests and real loopback HTTP tests. A separate CI job opts into three real Docker diagnosis/recovery cases on owned disposable containers. A manual run can enable `run_tests`. The earlier `[skip tests]` marker is absent from this verification update.

See [integration coverage](docs/INTEGRATIONS.md), [architecture](docs/ARCHITECTURE.md), [roadmap](docs/ROADMAP.md), [contributing](CONTRIBUTING.md), and [security reporting](SECURITY.md).
