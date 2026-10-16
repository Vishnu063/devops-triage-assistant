# Integration roadmap

Quality takes precedence over breadth. Linux is the baseline in development, with local automated validation complete and disposable remote acceptance pending. **0 of the 60 additional tools are implemented.** None of the entries below is a functioning connector yet.

Each tool will have a separate collector, evidence-based diagnosis, scoped repair policy, explicit approval, verification, tests, documentation, and live lab acceptance. Linux service checks do not count as a Docker/Kubernetes/cloud integration.

## First queue

Linux acceptance → Docker → Kubernetes → Jenkins → AWS → Terraform. Complete one integration's quality gate before starting the next. Kubernetes work will then support Helm/Kustomize investigations, and common transport/approval contracts can be generalized from validated adapters.

| Category | Tool | Status |
| --- | --- | --- |
| Cloud | AWS | Planned |
| Cloud | Microsoft Azure | Planned |
| Cloud | Google Cloud | Planned |
| Cloud | DigitalOcean | Planned |
| Cloud | Oracle Cloud | Planned |
| Containers | Docker | Next after Linux acceptance |
| Containers | Podman | Planned |
| Containers | containerd | Planned |
| Containers | Docker Compose | Planned |
| Containers | Buildah | Planned |
| Kubernetes | Kubernetes | Planned |
| Kubernetes | Helm | Planned |
| Kubernetes | Kustomize | Planned |
| Kubernetes | Argo CD | Planned |
| Kubernetes | Flux | Planned |
| CI/CD | Jenkins | Planned |
| CI/CD | GitHub Actions | Planned |
| CI/CD | GitLab CI/CD | Planned |
| CI/CD | Azure Pipelines | Planned |
| CI/CD | Tekton | Planned |
| Infrastructure as Code | Terraform | Planned |
| Infrastructure as Code | OpenTofu | Planned |
| Infrastructure as Code | Pulumi | Planned |
| Infrastructure as Code | AWS CloudFormation | Planned |
| Infrastructure as Code | AWS CDK | Planned |
| Configuration | Ansible | Planned |
| Configuration | Puppet | Planned |
| Configuration | Chef | Planned |
| Configuration | Salt | Planned |
| Configuration | cloud-init | Planned |
| Monitoring | Prometheus | Planned |
| Monitoring | Grafana | Planned |
| Monitoring | Datadog | Planned |
| Monitoring | Zabbix | Planned |
| Monitoring | Amazon CloudWatch | Planned |
| Logs and tracing | Elasticsearch | Planned |
| Logs and tracing | Logstash | Planned |
| Logs and tracing | Kibana | Planned |
| Logs and tracing | Loki | Planned |
| Logs and tracing | Jaeger | Planned |
| Security | Trivy | Planned |
| Security | Snyk | Planned |
| Security | SonarQube | Planned |
| Security | Gitleaks | Planned |
| Security | Semgrep | Planned |
| Secrets and access | HashiCorp Vault | Planned |
| Secrets and access | AWS Secrets Manager | Planned |
| Secrets and access | Azure Key Vault | Planned |
| Secrets and access | Keycloak | Planned |
| Secrets and access | Teleport | Planned |
| Networking | NGINX | Planned |
| Networking | HAProxy | Planned |
| Networking | Traefik | Planned |
| Networking | Istio | Planned |
| Networking | Envoy | Planned |
| Databases and messaging | PostgreSQL | Planned |
| Databases and messaging | MySQL | Planned |
| Databases and messaging | Redis | Planned |
| Databases and messaging | MongoDB | Planned |
| Databases and messaging | Apache Kafka | Planned |

Cloud platforms contain many services. Implementing one AWS service will not establish coverage of every AWS service. Version/service support will be recorded per adapter.
