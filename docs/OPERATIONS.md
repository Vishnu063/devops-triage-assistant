# Everyday incident workflow

Use **Check setup → Validate connection → Collect evidence bundle → Investigate → Review repair → Compare**. None of the investigation, comparison, search or reporting features authorize a repair.

## Deeper Kubernetes checks

Configure an explicit context, namespace and Deployment. The optional `service` field names one Service to compare against that Deployment's template labels:

```json
{
  "tools": {
    "kubernetes": {
      "context": "your-context",
      "namespace": "your-namespace",
      "resource": "your-deployment",
      "service": "your-service"
    }
  }
}
```

```bash
bash start.sh --tool kubernetes bundle
```

The collector follows controller owner UIDs from the Deployment to ReplicaSets and pods. It distinguishes image-pull backoff, crash loops, recorded OOM termination, container configuration failures, unscheduled pods, probe-failure event signatures, scheduler resource-shortage signatures, missing required referenced Secrets/ConfigMaps and a mismatching explicitly configured Service selector.

This requires scoped read permissions for the Deployment, ReplicaSets, pods, events, logs and any explicitly inspected Service or configuration objects. Secret and ConfigMap checks request **names only** in CLI output. They establish object existence, not key/value validity. Optional missing references are not treated as required-object failures. Permission failures are reported as unknown rather than missing. Pod references added through admission or service accounts, CSI resources, Secret contents, registry authentication tests, endpoint traffic and node-capacity prediction are outside this collector's scope.

Checks are bounded by the 1 MiB transport limit, 100 items in each selected list, 20 owned pods, 20 distinct configuration references, event reads for the Deployment and at most five owned pods, a 40-second deep-collection budget, and a short per-command deadline. Broader, changing or permission-limited evidence is explicitly incomplete. Event messages and raw log bodies are discarded after extracting known signatures. Historical events may describe an earlier state; their presence does not prove the issue persists now.

### Recent deployment comparison

When the Deployment revision and an older owned ReplicaSet are retained, the bundle compares the current template with the newest lower revision. It reports image changes, resource/probe/configuration-reference hashes and template changes. It records the prior ReplicaSet creation time and Deployment creation time. These **are not exact change or outage timestamps** and do not prove a change caused the incident. Garbage-collected revisions cannot be reconstructed. No manifest, environment values or configuration values are exported.

## Before and after

Every scan retains a pointer to the previous sample of the same exact target. The dashboard shows resolved, new and remaining finding codes, collection completeness, timestamps and application-health flags. **Check again and compare** collects a fresh sample explicitly; choose this after a manual fix.

```bash
bash start.sh compare
bash start.sh recheck
bash start.sh recheck --before INCIDENT_ID --deep
```

`compare --before ID --after ID` compares stored samples; both must belong to the same target/profile. `recheck` collects fresh evidence. Supported repairs and rollbacks also attempt a follow-up sample when a baseline incident exists. Follow-up collection failures do not erase the original repair outcome. A vanished finding with incomplete evidence does not prove recovery. Application health stays unverified without a configured passing endpoint policy.

## Saved environments

Save a copy through **Save an environment profile**, label it development, staging or production, then select and edit its target settings. Production is prominently marked. Copies initially contain the same target settings; change them deliberately before live checks. Labels are metadata, not RBAC or protection against a wrongly configured context.

```bash
bash start.sh profiles --save team-staging --environment staging
bash start.sh --profile team-staging --tool docker setup
bash start.sh --profile team-staging --tool docker diagnose
```

The default profile preserves the existing top-level `tools` document. Named profiles live under `profiles.NAME = {"environment":"staging","tools":{...}}` in the same private, atomically written configuration file. CLI `--profile` chooses a saved profile; dashboard selection lasts for that server session. A later launch defaults to `default` unless `--profile` is supplied. Selected connection settings are shared by clients of the same local server, which is designed for one operator.

Named profiles add a namespace to target identity, so even identical tool settings cannot transfer an approval between profiles. The dashboard blocks profile changes while a nonexpired plan is pending/approved or any plan is executing. Existing exact-target, fresh-state and single-use approval checks still apply.

## Actionable setup checks

```bash
bash start.sh --tool kubernetes doctor
```

**Check setup** identifies missing configuration fields and missing native CLIs without authenticating or connecting to providers. After a failed scan, the report adds permission, routing/TLS and schema guidance from sanitized error categories. `doctor` is a prerequisite check; a successful result is not live validation. Never solve a read error by blindly granting administrator access.

## Incident search and escalation

```bash
bash start.sh incidents --query oom
bash start.sh incidents --status verified
bash start.sh handoff
```

Search covers the latest 500 scans on the exact selected target/profile, returns at most 50 matches, and considers up to 2,000 recent recorded repair results for status filters. Queries match finding codes or incident IDs, not raw logs. A verified result establishes only its recorded state/application probe scope. Absence of a recorded result does not prove that nothing happened.

**Download escalation report** produces a filtered JSON handoff with finding codes, collection and application-health flags, recorded repair results and unresolved questions. Follow-up samples link back to their recorded repair outcome. It omits target identities, commands, environment values, configuration and raw evidence/log bodies. Review any report before sharing. The evidence bundle retains full allowed diagnostic metadata privately; the handoff deliberately contains less detail.

## CI exit codes

```bash
bash start.sh --tool docker diagnose --fail-on critical
bash start.sh --tool kubernetes diagnose --deep --fail-on any
```

| Code | Meaning |
| --- | --- |
| 0 | No finding matched the requested failure policy; this does not certify application health. |
| 1 | Invalid arguments/configuration or an unrecoverable local command/state error. |
| 2 | Baseline or requested deep evidence is incomplete; this takes precedence over findings. Existing health/validation/recovery commands also use 2 when verification fails. |
| 3 | A finding matched `--fail-on warning`, `critical` or `any`. |

`--fail-on none` is the backward-compatible default: findings are reported without failing the process, while incomplete evidence still exits 2. `warning` matches warning and critical findings. Triage critical labels cover failed application probes/services, stopped or unhealthy Docker/Podman containers, unavailable/deadline-failed Deployments, certain Kubernetes deployment blockers and OOM findings. Other rule findings default to warning. This is a local policy classification, not a provider SLA or vulnerability severity standard. `bundle` exits 2 if the requested evidence is incomplete.

## Real local-model benchmark

```bash
bash start.sh ai-benchmark
bash start.sh ai-benchmark --cases 1 --model qwen2.5:0.5b
```

The command runs up to three synthetic incident explanations on an already installed local model. It never downloads a model or uses private infrastructure evidence. It records wall time, Ollama token/timing metrics and sampled reported loaded-model size. On Linux, optional `--ollama-pid PID` samples RSS for that explicitly supplied owned process and descendants; shared pages may be double counted and short peaks may be missed. Without a PID, RSS is null. These numbers are not a universal minimum RAM requirement.

The dashboard's **Benchmark one sample** requires local AI opt-in. Topic keyword presence is only a smoke check; every answer needs human review for unsupported claims and unsafe advice. A completed HTTP response is not a quality certification. The **Local Ollama acceptance benchmark** GitHub workflow downloads the official runtime and the small model on an owned disposable CPU runner, records the runtime/model versions and uploads its results. It does not enable cloud inference. See [test results](TEST_RESULTS.md) for measured runs and their limits.
