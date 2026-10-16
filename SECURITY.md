# Security reporting

Do not include exploitable vulnerabilities or secrets in public issues. Use GitHub private vulnerability reporting if enabled on this repository. If it is unavailable, open a public issue asking the maintainer for a private reporting channel, without including exploit details.

This is an early local Linux MVP. No production security audit or multi-user deployment certification has been performed. A user's local account can access and alter its own plans; the database is not an authorization boundary against that account or root.

Treat an SSH host and its configuration as trusted operator-managed inputs. Live systems must use a dedicated least-privilege account, and any service restart permissions must be limited to explicitly authorized units. Preserve strict host-key validation.
