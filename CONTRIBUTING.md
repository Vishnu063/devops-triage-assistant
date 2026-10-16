# Contributing

Use Python 3.11+ and run `python -m unittest discover -s tests -v` before submitting a change.

Work on one integration at a time. Follow the adapter quality gate in docs/ARCHITECTURE.md. Never execute model-generated or user-pasted command text, expand repair privileges silently, collect secret values, or skip approval for a mutation.

For bugs, include the tool/OS versions, sanitized observed evidence, expected behavior, reproduction steps, and whether a mutation was attempted. Never attach private keys, tokens, credentials, complete environment dumps, or unredacted application logs. Report approval bypasses privately using SECURITY.md.

Use fake adapters for mutation tests. Add disposable lab acceptance notes before claiming live recovery support. Describe unsupported cases instead of hiding them behind a generic healthy result.

The 60 profiles now have synthetic-response test coverage. Maintain tests/test_integrations.py when changing parsers, scope, credential bindings or repair behavior. Do not equate fixture coverage with live compatibility or complete product support. Add disposable acceptance evidence for a specific deployed tool version before making such a claim.


## Help improve the first useful result

Try one sample incident, then one disposable real target you own. Tell us where setup, the explanation or the next action was unclear. Good contributions include reproducible collector compatibility cases, clearer runbooks, accessible UI behavior and tests for stale evidence or unsafe repair proposals. Existing approval and verification controls must remain intact.

Guided investigation and demo tests run with the standard Python suite. Browser checks are separate: install Playwright 1.56.1 and Chromium in a disposable development environment, then run `node tests/browser_smoke.cjs`. The script starts its own loopback dashboard with temporary state; no production account is needed. Set `TRIAGE_BROWSER_ARTIFACTS` to a local output directory to keep desktop/mobile screenshots. It performs read-only local Linux checks, sample walkthroughs and a private filtered-summary download; it never repairs infrastructure.
