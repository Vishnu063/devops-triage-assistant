# Contributing

Use Python 3.11+ and run `python -m unittest discover -s tests -v` before submitting a change.

Work on one integration at a time. Follow the adapter quality gate in docs/ARCHITECTURE.md. Never execute model-generated or user-pasted command text, expand repair privileges silently, collect secret values, or skip approval for a mutation.

For bugs, include the tool/OS versions, sanitized observed evidence, expected behavior, reproduction steps, and whether a mutation was attempted. Never attach private keys, tokens, credentials, complete environment dumps, or unredacted application logs. Report approval bypasses privately using SECURITY.md.

Use fake adapters for mutation tests. Add disposable lab acceptance notes before claiming live recovery support. Describe unsupported cases instead of hiding them behind a generic healthy result.

For v0.2, new test and live-acceptance execution was deferred at the operator's request. Do not describe the 60 new profiles as validated. This source update uses a [skip tests] marker; future unmarked pushes retain the test job, and the suite can also be invoked explicitly through workflow_dispatch. Expand one profile at a time and record exact coverage instead of equating one check with full product support.
