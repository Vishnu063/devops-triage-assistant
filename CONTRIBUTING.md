# Contributing

Use Python 3.11+ and run `python -m unittest discover -s tests -v` before submitting a change.

Work on one integration at a time. Follow the adapter quality gate in docs/ARCHITECTURE.md. Never execute model-generated or user-pasted command text, expand repair privileges silently, collect secret values, or skip approval for a mutation.

For bugs, include the tool/OS versions, sanitized observed evidence, expected behavior, reproduction steps, and whether a mutation was attempted. Never attach private keys, tokens, credentials, complete environment dumps, or unredacted application logs. Report approval bypasses privately using SECURITY.md.

Use fake adapters for mutation tests. Add disposable lab acceptance notes before claiming live recovery support. Describe unsupported cases instead of hiding them behind a generic healthy result.

The 60 profiles now have synthetic-response test coverage. Maintain tests/test_integrations.py when changing parsers, scope, credential bindings or repair behavior. Do not equate fixture coverage with live compatibility or complete product support. Add disposable acceptance evidence for a specific deployed tool version before making such a claim.
