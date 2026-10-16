# Test results — 2026-10-16

## Local result

**132 tests passed** on Linux with Python 3.12.14.

Command: `python -m unittest discover -s tests -v`

The first run of the expanded suite exposed failures. The final full run passed after the fixes below; this report describes the final source, not the earlier unverified expansion.

## Coverage and evidence

| Area | What was exercised | Boundary |
| --- | --- | --- |
| 60 tool profiles | One individually named test per profile, handwritten representative responses, selected-field projection, required evidence and findings | Native commands and provider API responses are mocked; this does not validate live provider schemas or installed CLI versions |
| Sensitive data | Fixtures containing secret-like fields, source snippets, manifests and provider outputs | Projection excludes those fixture values; this is not proof that every possible secret string is detected |
| Five tool repair actions | Preconditions, review, approval, dispatch, expected post-action state and replay rejection | Mutations are simulated; no real container, Deployment or CI pipeline is changed |
| Approval boundaries | Missing approval, expiry, changed evidence/command, cancellation, duplicate planning and concurrent execution | Local process/database behavior; not a distributed transaction guarantee |
| HTTP transport | Actual loopback fixture server, header binding, JSON projection, redirect rejection, permission errors and response size limits | Controlled service, not external provider/TLS acceptance |
| Native process transport | Actual Python subprocesses, successful streaming, withheld stderr and output size limits | Does not establish the syntax or behavior of third-party CLIs |
| Web API | Loopback requests, session token, host/origin rejection, tool selection, catalog, stored plans and full simulated approval flow | HTTP/API checks; rendered browser interactions and accessibility were not inspected |
| Linux | Actual local read-only collection plus simulated systemd states and repairs | No real failed systemd unit was restarted; remote SSH acceptance remains pending |

## Package and interface checks

- Built a 0.2.0 wheel successfully and installed the package in an isolated virtual environment.
- Ran the installed CLI outside the repository and listed all 60 profiles.
- Used the installed CLI to collect real local Linux measurements.
- Started the installed dashboard on a temporary loopback port and checked its HTML asset, generated session token, 60-profile catalog, live Linux scan API and rejection of a foreign Origin.
- Checked dashboard JavaScript syntax with `node --check`.
- Built the final wheel again after the fixes.

## Defects fixed

1. Kafka's parser could read the next field name as a nonempty ISR when the ISR list was empty. Numeric-field parsing now preserves empty lists and flags under-replication.
2. Semgrep reports containing scan errors but no matches could produce no findings. Such reports now explicitly indicate incomplete static analysis.
3. Invalid credential environment bindings could raise TypeError instead of an actionable validation error. They now fail validation.
4. Header binding objects could carry ignored literal credential fields. Unsupported nested fields are now rejected before a plan can be created.
5. Native-CLI profiles could accept unused API authentication configuration. These unrelated fields are now rejected rather than persisted in a plan.

## Remaining acceptance work

No credentials or live target configuration were supplied for the external providers. Consequently, this run does not certify live integration behavior for any of the 60 products. Real resource recovery, provider-specific permission scopes, deployed-version compatibility, TLS/private-CA setups, remote SSH, sustained application health, and rendered browser behavior remain unverified.

GitHub Actions runs the same suite on Python 3.11, 3.12 and 3.13 and builds a downloadable wheel. Check the Actions result for the verification commit; a package-only build from an earlier skip-tests commit is not test evidence.
