# Your first useful result

The goal: understand one incident before choosing a repair. Start without infrastructure; then connect one real target.

## 1. Start the assistant

```bash
git clone https://github.com/Vishnu063/devops-triage-assistant.git
cd devops-triage-assistant
bash start.sh
```

Open **http://127.0.0.1:8765** on the same computer. Linux/WSL, Git and Python 3.11+ are required. The first launch installs the assistant; it does not install native tools or Ollama.

## 2. Try a sample

Click **Docker out of memory**. The result is labeled **SAMPLE DATA**, shows the sample condition, and explains the next check. Choose **Likely cause?** and **What next?**. Expand **Evidence behind this answer** to see its basis.

The runtime OOM flag supports an observed termination, but does not prove what made memory grow. Guided answers preserve this distinction. Samples never connect to infrastructure, persist incident history, create plans or execute fixes.

Other examples: Kubernetes image pull failure and Linux disk pressure. The CLI equivalent is `bash start.sh demo --scenario docker-oom`.

## 3. Connect one real target

Click **Leave sample mode**. Search for **Docker**, select it, and open **Connection wizard**. Enter your actual context and container, save, then **Validate connection**. The banner tells you whether setup is needed, settings are saved or scoped read access has been checked.

Docker must be installed and reachable using your existing permissions. The assistant does not grant daemon access. For Kubernetes, configure an explicit context, namespace and Deployment. See [connection details](CONNECTIONS.md).

## 4. Investigate

Click **Run live checks**. The overview gives finding count, evidence completeness, application health and the next check. **Application health: Not verified** means a valid application probe has not established health; a running process alone is insufficient.

Ask a guided question about summary, causes, checks, changes, safety or health. Optional local AI needs a separately installed [Ollama model](LOCAL_AI.md); guided answers work without one. Chat refers to the latest selected stored incident and never runs commands or gathers additional evidence.

## 5. Review and verify

When a supported repair is available, select **Review**. Read its expected effect, impact, exact operation and verification scope. Approve and run it separately. The result remains visible afterward. Run fresh checks to investigate the new state.

Restarting can repeat a failure. An image pull problem may need a configuration or registry change rather than a restart. Many profiles supply runbooks without executable repairs. See [recovery boundaries](RECOVERY_WORKFLOW.md).

## 6. Share useful feedback

Use **Download filtered summary** for a local JSON summary without target identities, raw evidence or configuration. Review it before sharing. Report the expected behavior, actual behavior, assistant/Python/native-tool versions and reproducible steps using the [issue templates](../.github/ISSUE_TEMPLATE/bug_report.yml). Do not include credentials or private logs.

The project aims to become useful through reproducible fixes and user feedback. Star counts and production suitability are not guarantees. Live acceptance remains specific to the [tested scopes](TEST_RESULTS.md).
