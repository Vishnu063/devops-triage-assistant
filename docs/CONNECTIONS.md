# Connections and prerequisites

Start with examples/connections.example.json. Keep only tools you intend to use, replace their null fields, and save the result as connections.json in the repository root (ignored by Git). Profile IDs and scopes are listed in INTEGRATIONS.md. This file is operator configuration, not an automatic discovery mechanism.

Use only supported fields from the template plus base_url, headers and basic_auth where needed. Literal password/token fields are rejected. Absolute paths are recommended for project directories, inventories, rule files and private credential files.

## API authentication

API collectors accept headers whose values come from environment variables:

```json
{
  "tools": {
    "github-actions": {
      "base_url": "https://api.github.com",
      "owner": "your-owner",
      "repository": "your-repository",
      "resource": "your-numeric-run-id",
      "headers": {
        "Authorization": {"env": "GITHUB_TOKEN", "prefix": "Bearer "},
        "X-GitHub-Api-Version": {"env": "GITHUB_API_VERSION"}
      }
    }
  }
}
```

Set GITHUB_TOKEN through your normal secure environment mechanism. GITHUB_API_VERSION can contain an appropriate API date such as 2022-11-28. Do not commit tokens, credential files or captured provider responses. Read access must cover the configured resource; retry actions need the relevant write permission.

- GitLab: use PRIVATE-TOKEN from an environment variable, or Authorization with Bearer prefix. base_url is the GitLab origin. project accepts the project ID or URL-encoded-by-the-client project path; supply the original path, not pre-encoded text.
- Datadog: set DD-API-KEY and DD-APPLICATION-KEY header bindings. Choose your correct regional API base URL.
- Grafana: use Authorization with Bearer prefix when required.
- Vault: use X-Vault-Token if your deployment requires authentication for health; the collector never requests a secret value or an unseal key.
- Zabbix: use Authorization with Bearer prefix on versions supporting API-token authentication this way. The body uses host.get with explicit output fields. Older API versions may need a future compatibility adapter.
- SonarQube: configure basic_auth with username_env naming a token variable and password_env naming an environment variable holding the password required by your setup. For token-as-username with empty password, prefer Authorization with Basic prefix and an environment variable containing the pre-encoded credential; no literal credential is stored in JSON.
- Jenkins: configure basic_auth with username_env and password_env for a username and API token. Job names are single path components in this profile; nested folder jobs need a future path-aware profile.
- Azure Pipelines: base_url is https://dev.azure.com; configure organization, project and numeric build ID. Bind Authorization to a suitable environment-provided bearer token or Basic credential for your organization's setup.

Example basic-auth configuration shape:

```json
{
  "base_url": "https://jenkins.example.internal",
  "resource": "your-job",
  "basic_auth": {
    "username_env": "JENKINS_USER",
    "password_env": "JENKINS_API_TOKEN"
  }
}
```

This is the value of the jenkins entry inside tools. Credentials are resolved at request time and never written to a plan.

## Service endpoints

- NGINX needs an access-controlled stub_status location at /status.
- HAProxy needs protected CSV statistics at /stats;csv.
- Envoy readiness uses its protected admin /ready endpoint; do not expose its admin interface publicly.
- Keycloak /health/ready is normally on a management endpoint and health support must be enabled.
- Grafana /api/health, Elasticsearch /_cluster/health, Kibana /api/status, Loki /ready, and Prometheus /api/v1/targets need the relevant service endpoint.
- Logstash monitoring API uses /_node/stats/pipelines.
- Jaeger uses a deployment exposing the query /api/services interface. Teleport uses proxy /webapi/ping.
- Traefik /api/overview requires an intentionally enabled and protected API; do not enable an insecure public API for this tool.

For HTTP-only internal services, create your own trusted SSH tunnel and point base_url at http://127.0.0.1:PORT. This release does not automate tunneling, private CA installation or credential acquisition. HTTPS uses the Python runtime's trusted CA store.

## Native cloud and Kubernetes CLIs

Install and authenticate each native CLI independently. Required fields force an explicit account/profile/context where the recipe supports one:

- AWS and CloudWatch/Secrets Manager/CloudFormation/CDK: AWS CLI profile and region. IAM actions are respectively DescribeInstanceStatus, DescribeAlarms, DescribeSecret, or DescribeStacks on the intended scope. No SecretValue or stack outputs are requested.
- Azure VM: Azure CLI subscription, resource group and VM name. Key Vault uses subscription, vault and secret name, and only lists version metadata.
- Google Cloud: project, zone and instance name.
- DigitalOcean: doctl context and droplet ID. OCI: profile, region and instance OCID.
- Docker/Compose: Docker context. Podman: an existing Podman connection. Local Podman without a named connection requires future support.
- Kubernetes/Flux/Tekton/Istio: kubectl context, namespace and resource where applicable. Flux/Tekton CRDs must be installed.
- Helm: kube context, namespace and release. Argo CD: server plus authenticated CLI context; the profile uses grpc-web.
- containerd: explicit socket and namespace. Buildah: an existing working container.

For non-Linux profiles, commands run on the client, and native CLIs contact the configured live API/daemon. --target SSH is reserved for the Linux collector; do not combine it with a non-Linux profile.

## Infrastructure and configuration management

- Terraform/OpenTofu: point directory at an already initialized trusted project. validate does not run apply or initialize providers. Required providers must already be available.
- Pulumi: directory plus explicit stack; stack export is projected to resource identifiers/types and pending-operation types. Inputs, outputs and secret payloads are not retained.
- CDK: profile checks the deployed CloudFormation stack only; it never executes a CDK app.
- Kustomize: directory points to the intended overlay; only manifest kinds/counts are retained. It does not inspect live resources.
- Ansible: inventory is a trusted local inventory path. Dynamic inventory plugins may contact their providers; host variables are discarded. No playbook runs.
- Puppet: resource is a service name. Chef: resource is a node name in the configured knife environment; only ohai_time is retained. Salt: resource is one exact minion ID, and the collector runs test.ping, not a state apply.
- cloud-init: reads local status only and does not rerun boot provisioning.

## Security scanner profiles

Scans occur only if you explicitly request diagnosis for that configured tool. Building/installing the assistant does not run a scan.

- Trivy: image is an explicit image reference. The CLI may contact registries/download its vulnerability database.
- Snyk: directory is a trusted project; the CLI uses its existing authentication and may send dependency metadata to Snyk.
- Gitleaks: directory is explicitly selected. The scan redacts values before JSON projection, and only rule/file/line/fingerprint metadata is retained.
- Semgrep: directory and a trusted local rules path are explicit. Metrics are disabled. Code snippets are not retained.
- SonarQube: project identifies the quality gate to inspect; this does not run an analysis job.

No vulnerability, secret rotation or source-code fix is applied automatically. Follow the supplied runbooks and your normal code review/deployment process.

## Databases and Kafka

- PostgreSQL: configure a libpq service name, with a private pg_service.conf/pgpass and a read-only login. The query reads current database statistics and recovery state.
- MySQL: credentials_file is a private defaults file, not a password. The query reads server mode/version/connection limit.
- Redis: configure host and port; REDISCLI_AUTH supplies authentication. This first profile needs a trusted local/tunneled endpoint because TLS flags are not yet configurable.
- MongoDB: set TRIAGE_MONGODB_URI in the environment. It is used within mongosh, never supplied as an argv URI. The hello command inspects topology role only.
- Kafka: configure bootstrap, topic resource and private credentials_file for client properties. The topic describe command returns leader/replica metadata; it does not alter assignments.

Use trusted credential stores and project directories. Tool plugins, database startup configuration and credential files can affect native behavior; they remain under the operator's control.
