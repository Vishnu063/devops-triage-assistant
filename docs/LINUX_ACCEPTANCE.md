# Linux acceptance checklist

Automated unit/API checks and real local read-only collection pass in the development environment. The steps below are pending operator acceptance; they have not been run on your server.

Use an isolated disposable Linux VM with systemd, a harmless test service, Python 3.11+ on the client, Python 3 on the target, and trusted SSH host keys. Do not use a production service to exercise failure injection.

1. Compare reported root disk, memory, and load against df, free, and uptime. Note collection timing differences.
2. Confirm SSH succeeds with a pretrusted key; unknown host keys and unavailable identities must fail without prompting or silently trusting keys.
3. Select only your harmless test unit via --service. Verify missing and active units cannot produce a failed-service restart plan.
4. Arrange for that unit to be failed using the lab's own runbook. Diagnose and compare evidence with systemctl show and the journal.
5. Create a plan. Check exact target, service, command, expiry, risk, and rollback limitation in both interfaces.
6. Attempt apply before approval; it must fail without running sudo/systemctl restart.
7. Approve, then change the service state independently. Apply must reject the stale plan.
8. Create and approve a fresh plan; let it expire. Apply must reject it.
9. Approve another fresh plan and run it with a narrowly scoped sudo rule. Observe one restart and a fresh systemd-state verification. Check application health yourself.
10. Replay apply and attempt a concurrent second apply; neither may restart the unit again.
11. Simulate missing sudo permission and command timeout in the lab. Expect needs_attention and no automatic retry. Inspect actual state before proceeding.
12. Cancel a pending/approved plan and verify it cannot execute.
13. Try the dashboard at desktop and mobile widths. Review keyboard focus, findings, plan contents, error display, cancellation, and final repair results.
14. Confirm no journal bodies, application secrets, SSH private keys, or credentials appear in reports or repository files.

Record OS, Python/systemd/OpenSSH versions, date, results, and remaining limitations before calling this integration accepted. The assistant cannot certify arbitrary Linux distributions from one development environment.
