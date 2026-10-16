# First run: from setup to useful evidence

Use Linux or Ubuntu in WSL with Git and Python 3.11+. The assistant does not install Docker, Kubernetes, cloud CLIs, or credentials.

## Install and see the available tools

```bash
git clone https://github.com/Vishnu063/devops-triage-assistant.git
cd devops-triage-assistant
bash start.sh tools
```

The first run creates `.venv` and installs this checkout. Listing tools does not connect to providers and is a useful way to confirm installation without inspecting a live system.

## Choose one connection

```bash
bash start.sh
```

Open **http://127.0.0.1:8765** on this computer. Choose a tool, open **Connection wizard**, enter its explicit target, save, then choose **Validate connection**. Do not configure all 60 profiles at once. A profile's presence means it is implemented; it does not prove that your account, permissions, version, or target is compatible.

For a remote installation, keep the dashboard on loopback and use the SSH tunnel documented in the [README](../README.md). Press Ctrl+C in the launcher terminal to stop the dashboard.

## Read the first diagnosis

Request diagnosis for the selected target. Read the observed facts, missing evidence, likely explanations, and next investigation steps. A failed connection or missing permission needs correction before relying on the report. Review [integration scope](INTEGRATIONS.md) to understand exactly what the selected profile observes.

The CLI equivalent for a configured Docker target is:

```bash
bash start.sh --config connections.json --tool docker validate
bash start.sh --config connections.json --tool docker diagnose
```

These commands use your configured Docker resource. Configure an authorized disposable target before trying operational actions. Validation and diagnosis are reads, but native tools may contact their configured providers.

## Decide whether a repair is justified

Start with diagnosis. When a supported repair is needed, inspect the exact plan and target before approving. Approval and execution are separate steps. An unavailable action on a diagnosis-only profile is expected; follow its runbook instead.

After an attempted repair, check the timeline and reported verification scope. Running container state alone does not prove application recovery. If execution is interrupted or times out, inspect the target before requesting another action.

[Repair and recovery workflow](RECOVERY_WORKFLOW.md) · [Test evidence and limits](TEST_RESULTS.md)

## Get help with a useful report

Include your OS, Python version, commit, selected integration, exact command or dashboard step, and redacted error. Do not attach credentials, private connection files, or complete live reports. Use the repository's **Report a problem** issue form.


## See a result before connecting anything

Click **Docker out of memory**, **Kubernetes image pull** or **Linux disk full** at the top of the dashboard. These are clearly marked synthetic examples. Ask one of the six guided questions to see the observed evidence, possible cause and next checks. No connection, AI model, cloud resource or repair is needed.

Choose **Leave sample mode** when ready. Use the integration search to find one tool, follow **Setup checklist**, save its connection and validate read access. The connection banner distinguishes missing settings, saved settings, checked access and collected evidence. A collector's successful read does not establish full tool health.

After checks, the overview separates finding count, collection completeness and application health. Use **What next?** for concrete investigation steps. AI is optional and disabled by default. Finish or cancel a pending repair plan before switching incidents.
