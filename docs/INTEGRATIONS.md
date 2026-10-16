# Integration coverage

All profiles below have collector and diagnosis code with automated synthetic-response coverage. **Live provider acceptance is still pending for all 60.** The full suite passes 175 tests locally; these tests do not establish compatibility with your deployed tool versions, credentials or environments. See TEST_RESULTS.md. Supported scope is deliberately narrow; this does not mean every error or service of a platform is covered.

Read-only means no intended resource mutation. Native CLIs may update local credential caches, scan databases, or use trusted provider/inventory plugins. Configure only trusted local projects and read-only credentials for diagnosis.

| ID | Tool | Implemented collector scope | Required configuration | Executable repair |
| --- | --- | --- | --- | --- |
| aws | AWS | EC2 instance and system status checks | profile, region, resource | Suggestions/runbook only |
| azure | Microsoft Azure | VM instance view | group, resource, subscription | Suggestions/runbook only |
| gcp | Google Cloud | Compute Engine instance status | project, resource, zone | Suggestions/runbook only |
| digitalocean | DigitalOcean | Droplet status | context, resource | Suggestions/runbook only |
| oci | Oracle Cloud | Compute instance lifecycle | profile, region, resource | Suggestions/runbook only |
| docker | Docker | One container's identity and state | context, resource | restart |
| podman | Podman | One container's identity and state | context, resource | restart |
| containerd | containerd | Task inventory in one namespace | namespace, socket | Suggestions/runbook only |
| compose | Docker Compose | Services in one explicit Compose project | context, directory, project | Suggestions/runbook only |
| buildah | Buildah | Working-container state | resource | Suggestions/runbook only |
| kubernetes | Kubernetes | One Deployment's desired and available replicas | context, namespace, resource | rollout-restart |
| helm | Helm | Release status and revision | context, namespace, resource | Suggestions/runbook only |
| kustomize | Kustomize | Renderability and manifest kind inventory; no manifest bodies retained | directory | Suggestions/runbook only |
| argocd | Argo CD | Application health, sync, and operation phase | resource, server | Suggestions/runbook only |
| flux | Flux | Kustomization readiness and reconciliation revision | context, namespace, resource | Suggestions/runbook only |
| jenkins | Jenkins | Latest build metadata for one job | resource, base_url | Suggestions/runbook only |
| github-actions | GitHub Actions | One workflow run | owner, repository, resource, base_url | rerun-failed |
| gitlab-ci | GitLab CI/CD | One pipeline's status | project, resource, base_url | retry-failed |
| azure-pipelines | Azure Pipelines | One Azure DevOps build | organization, project, resource, base_url | Suggestions/runbook only |
| tekton | Tekton | PipelineRun conditions | context, namespace, resource | Suggestions/runbook only |
| terraform | Terraform | Local initialized configuration validation; no plan/apply | directory | Suggestions/runbook only |
| opentofu | OpenTofu | Local initialized configuration validation; no plan/apply | directory | Suggestions/runbook only |
| pulumi | Pulumi | Selected stack's resource inventory, excluding outputs and inputs | directory, stack | Suggestions/runbook only |
| cloudformation | AWS CloudFormation | Deployed CloudFormation stack status | profile, region, resource | Suggestions/runbook only |
| cdk | AWS CDK | CloudFormation status of one deployed CDK stack | profile, region, resource | Suggestions/runbook only |
| ansible | Ansible | Inventory visibility; no playbooks run | inventory | Suggestions/runbook only |
| puppet | Puppet | One service's observed ensure state | resource | Suggestions/runbook only |
| chef | Chef | One Chef node's last observation time | resource | Suggestions/runbook only |
| salt | Salt | One explicit minion's ping response | resource | Suggestions/runbook only |
| cloud-init | cloud-init | Local boot provisioning status | None | Suggestions/runbook only |
| prometheus | Prometheus | Scrape-target health | base_url | Suggestions/runbook only |
| grafana | Grafana | Grafana API and database health | base_url | Suggestions/runbook only |
| datadog | Datadog | One monitor's overall state | resource, base_url | Suggestions/runbook only |
| zabbix | Zabbix | Configured host enablement and interface availability | resource, base_url | Suggestions/runbook only |
| cloudwatch | Amazon CloudWatch | One alarm's state | profile, region, resource | Suggestions/runbook only |
| elasticsearch | Elasticsearch | Cluster and shard allocation health | base_url | Suggestions/runbook only |
| logstash | Logstash | Pipeline event counters | base_url | Suggestions/runbook only |
| kibana | Kibana | Kibana overall readiness | base_url | Suggestions/runbook only |
| loki | Loki | Loki readiness endpoint | base_url | Suggestions/runbook only |
| jaeger | Jaeger | Query API service inventory | base_url | Suggestions/runbook only |
| trivy | Trivy | Image vulnerability metadata | image | Suggestions/runbook only |
| snyk | Snyk | Project dependency vulnerability metadata | directory | Suggestions/runbook only |
| sonarqube | SonarQube | One project's quality gate | project, base_url | Suggestions/runbook only |
| gitleaks | Gitleaks | Secret finding metadata for an explicit directory | directory | Suggestions/runbook only |
| semgrep | Semgrep | Static findings using explicitly supplied local rules | directory, rules | Suggestions/runbook only |
| vault | HashiCorp Vault | Vault initialization, seal and standby health | base_url | Suggestions/runbook only |
| secrets-manager | AWS Secrets Manager | Secret metadata and rotation settings only | profile, region, resource | Suggestions/runbook only |
| azure-key-vault | Azure Key Vault | Secret version metadata; never reads secret values | resource, subscription, vault | Suggestions/runbook only |
| keycloak | Keycloak | Management-port readiness | base_url | Suggestions/runbook only |
| teleport | Teleport | Proxy web API reachability and version | base_url | Suggestions/runbook only |
| nginx | NGINX | Protected stub_status counters | base_url | Suggestions/runbook only |
| haproxy | HAProxy | Backend/server states from protected CSV statistics | base_url | Suggestions/runbook only |
| traefik | Traefik | Router/service overview errors | base_url | Suggestions/runbook only |
| istio | Istio | istiod control-plane pod readiness | context, namespace | Suggestions/runbook only |
| envoy | Envoy | Protected admin readiness | base_url | Suggestions/runbook only |
| postgresql | PostgreSQL | Current database connection and recovery metadata | service | Suggestions/runbook only |
| mysql | MySQL | Server read-only mode and configured connection limit | credentials_file | Suggestions/runbook only |
| redis | Redis | Memory utilization and eviction policy metadata | host, port | Suggestions/runbook only |
| mongodb | MongoDB | Topology role and writable-primary metadata | None | Suggestions/runbook only |
| kafka | Apache Kafka | One topic's leader and in-sync replica metadata | bootstrap, credentials_file, resource | Suggestions/runbook only |

## Executable repair boundary

Only Docker/Podman container restart, Kubernetes Deployment rollout restart, GitHub Actions failed-job rerun, and GitLab failed-pipeline retry are implemented as mutations. Other profiles diagnose and provide tool-specific investigation steps. Linux retains its allowlisted failed-systemd-service restart. A failed Kubernetes recovery can now offer a separately approved rollback to its captured revision; see RECOVERY_WORKFLOW.md.

Every implemented action requires a reviewed plan, explicit approval, a matching fresh evidence fingerprint, a matching connection configuration, and unexpired single-use approval. Rerunning a pipeline can trigger deployment jobs; the plan calls out this risk. No repair has automatic rollback. The captured-revision rollback path is a separate expiring plan that requires a second approval.

Kubernetes probes for up to six samples separated by two seconds. A rollout can take longer, in which case needs_attention requires manual inspection rather than another automatic restart. Container state verification observes running state. Optional application health policies add consecutive endpoint/status or JSON-condition probes; they still do not establish sustained business behavior. CI rerun verification checks scheduling, not successful pipeline completion.

## API compatibility and trust

Profiles are based on common CLI/HTTP interfaces and tested with handwritten representative responses. They have not been validated against deployed provider versions. Missing CLIs, incompatible response schemas, empty projections, authorization failures, timeouts, oversized results and unsupported responses are surfaced rather than represented as healthy.

API URLs require HTTPS except localhost/loopback tunnels. TLS validation stays enabled, redirects are blocked, and environment HTTP proxies are not used. Native CLIs use their normal credential/configuration stores and explicit context selectors where supported. Do not put passwords, tokens or credential-bearing URLs in configuration.

## Interface references

- Docker inspect: https://docs.docker.com/reference/cli/docker/inspect/
- Flux Kustomization conditions: https://fluxcd.io/flux/components/kustomize/kustomizations/
- cloud-init status JSON: https://docs.cloud-init.io/en/latest/reference/cli.html
- Gitleaks CLI: https://github.com/gitleaks/gitleaks

References describe interfaces; synthetic tests are not evidence of live provider acceptance.
