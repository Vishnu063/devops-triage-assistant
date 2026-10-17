# Pre-deployment review

Check a proposed Kubernetes Deployment **before applying it**, without a cluster, Ollama, credentials or API keys:

```bash
bash start.sh preflight examples/preflight-deployment.json
bash start.sh preflight deployment.json --fail-on warning
```

The included example deliberately uses a mutable tag so you can see a warning. The command prints JSON and never deploys, repairs, contacts a registry, or executes manifest content. It works independently of your saved connection configuration. This first version is a CLI feature.

## Input

Supply an `apps/v1` Deployment JSON object or a Kubernetes `v1/List` JSON object containing 1–100 objects and at least one Deployment. Maximum file size: 1 MiB. Include related Service, Secret or ConfigMap objects if desired. Output uses object indexes, fixed explanations and finding codes; it omits names, images, configuration values and manifest bodies. Avoid adding Secret values: object presence is all this review uses.

JSON is supported directly; YAML, Helm templates, Compose files, StatefulSets and Jobs are not reviewed as workloads. If you already have kubectl, you can convert an ordinary Deployment YAML locally with:

```bash
kubectl create --dry-run=client --validate=false -f deployment.yaml -o json > deployment.json
bash start.sh preflight deployment.json
```

The assistant does not run that conversion. Review your kubectl configuration and input separately. Render Helm templates through your existing trusted workflow and supply the resulting Deployment JSON.

## Checks and limits

| Check | Meaning |
| --- | --- |
| Image reference | Missing image, whitespace, URL schemes or unresolved template syntax is flagged. Images without a sha256 digest get a mutable-image warning. This is a heuristic, not a complete OCI image parser or registry existence check. |
| Deployment selector | Evaluates matchLabels and In/NotIn/Exists/DoesNotExist expressions against the proposed pod template. |
| Configuration references | Required Secret/ConfigMap objects absent from the supplied namespace are **unverified**, not reported missing from the cluster. Optional references are allowed. Required keys, values, RBAC and admission remain unverified even when an object is included. |
| Service selector | Warns when a supplied same-namespace Service does not select a Deployment's template. A Service might intentionally belong to a different workload; review intent. No port or endpoint validation. |
| Readiness and requests | Warns about missing explicit readiness probes or CPU/memory requests. Does not validate probe behavior, quantities or available node capacity. |
| Availability | Flags zero/single replicas, Recreate, all-replica unavailability, and effective zero/zero rolling budgets. Percentage budgets use Kubernetes rounding. No uptime guarantee or simulation of scheduling, quotas, disruption budgets or autoscalers. |

No baseline comparison with live state is performed. This is not full Kubernetes schema validation. Review `unverified` even when no findings match your CI policy. Unsupported structures produce `status: incomplete`; objects other than Deployments, Services and configuration objects are counted but not validated. A reviewed status means the supported heuristics ran, not that deployment is safe.

The rollout and readiness rules follow the official [Deployment documentation](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/) and [probe documentation](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-probes/).

## CI exit codes

| Code | Meaning |
| --- | --- |
| 0 | No finding matched the selected policy. Unverified live checks may remain. |
| 1 | Input/file/JSON error or no supported Deployment. |
| 2 | An invalid or unsupported structure prevented complete heuristic review. Takes precedence over findings, even with `--fail-on none`. |
| 3 | Findings matched `--fail-on critical` (default), `warning` (warning or critical), or `any`. |

`--fail-on none` prints findings without policy failure; structural incompleteness still exits 2. Use the exit status directly in your existing CI job:

```yaml
- name: Review proposed Deployment
  run: devops-triage preflight deployment.json --fail-on warning
```

Keep your normal schema, security, registry and environment validation. Run this command against the same rendered artifact you intend to deploy.
