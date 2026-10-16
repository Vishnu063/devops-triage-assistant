# Disposable Docker acceptance lab

The `Disposable Docker acceptance` GitHub Actions job exercises the actual Docker collector and repair path on a GitHub-hosted Ubuntu runner. It creates no cloud infrastructure and needs no production credentials.

## What it checks

1. A real running Python HTTP-server container: inspect metadata, application health, bounded stderr log signatures, private-field exclusion and incident history.
2. A stopped owned container: diagnosis, reviewable restart plan, rejection before approval, a lab-only explicit approval, a real restart, consecutive application health verification, replay rejection and a success alert.
3. A real stale plan: independently start the owned container and verify that changed live state prevents approval/execution of the old plan.

The application endpoint uses an explicitly assigned loopback host port. An automatically allocated Docker port is unsuitable for a stable configured health URL because its assignment can change across restarts. The test verifies that the endpoint remains unchanged after recovery.

## Isolation

- Tests are disabled unless `TRIAGE_RUN_DOCKER_LAB=1`.
- The lab requires an actual local Unix socket at `/var/run/docker.sock`; it never selects a production or remote Docker context.
- Each test creates a uniquely named Docker context explicitly bound to that local socket.
- Containers have unique names and ownership labels. Cleanup checks the exact created container ID and label before removing anything.
- No host directories, production secrets or privileged container settings are used. Only a loopback HTTP port is published.
- Approval is automated only inside these test cases for resources they created. The application still requires explicit approval for normal operator repairs.
- The runner is disposable. The tests also clean up their own containers and contexts. They never prune arbitrary Docker resources.

## Run it yourself

Use only a disposable Linux development host with Docker and the local socket available. The tests pull/use the official `python:3.12-alpine` image; allow registry access and some local CPU/storage.

```bash
python -m pip install .
TRIAGE_RUN_DOCKER_LAB=1 python -m unittest discover -s tests -p test_live_docker.py -v
```

Without the opt-in flag, normal test discovery reports these three cases as skipped. An explicitly requested lab fails rather than silently skipping when its prerequisites are missing.

Passing this lab validates the tested Docker restart and endpoint workflow in this environment. It does not certify every Docker version, Podman, Kubernetes, AWS, or production availability behavior. See TEST_RESULTS.md for the actual recorded outcome.
