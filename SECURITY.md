# Security reporting

Do not include exploitable vulnerabilities or secrets in public issues. Use GitHub private vulnerability reporting if enabled on this repository. If it is unavailable, open a public issue asking the maintainer for a private reporting channel, without including exploit details.

This is an early local DevOps assistant with unverified integration profiles. No production security audit or multi-user deployment certification has been performed. A user's local account can access and alter its own plans; the database is not an authorization boundary against that account or root.

Use dedicated least-privilege accounts. The built-in HTTP transport validates TLS, blocks redirects, bypasses environment proxies, and resolves authentication header values from environment variables. Do not put literal credentials in connection configuration or URLs. Native CLIs retain their own credential/plugin trust model.

Treat SSH configuration, native tool configuration, scanner rules, inventories, project directories and database credential stores as trusted operator-managed inputs. Linux service restart permissions must be restricted to explicitly authorized units. Preserve strict SSH host-key checking. Keep the dashboard on loopback; this release is not intended for public or shared-user hosting.

Some diagnosis profiles invoke scanners or dynamic inventory providers and can update local caches or contact external providers. No cloud resources or production services are intentionally changed by diagnosis. Every supported resource mutation uses a separate, explicitly approved plan; no arbitrary shell/API mutation interface is exposed.

The connection wizard is protected by the dashboard's session token and host/origin checks. It writes validated private configuration, not arbitrary executable commands. Health endpoints have isolated environment-based credentials, do not follow redirects, and retain outcome summaries rather than bodies. Deep log collection is opt-in and persists signature counts, not raw text. Kubernetes rollback requires its own approval and captured identity/revision/template checks. Local incident evidence and alerts are sensitive operational data with no automatic retention policy yet.
