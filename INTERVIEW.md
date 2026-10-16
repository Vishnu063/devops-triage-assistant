# DevOps Triage Assistant: reviewer guide

A local diagnostic CLI/dashboard with 60 tool profiles and explicitly approved actions for selected integrations.

## Start the review

List tools without connecting, explain one collector's exact scope, and walk through a supported repair plan. Fixture coverage is not provider acceptance.

| Source | Review focus |\n| --- | --- |\n| [pyproject.toml](pyproject.toml) | Implementation, assumptions, and operational boundaries |\n| [.github/workflows/ci.yml](.github/workflows/ci.yml) | Triggers, credentials, failure handling, and deploy conditions |\n| [.github/workflows/docs.yml](.github/workflows/docs.yml) | Triggers, credentials, failure handling, and deploy conditions |\n| [scripts/check_docs.py](scripts/check_docs.py) | Implementation, assumptions, and operational boundaries |\n| [tests/test_experience.py](tests/test_experience.py) | Behavior covered, fixtures used, and remaining gaps |\n| [tests/test_integrations.py](tests/test_integrations.py) | Behavior covered, fixtures used, and remaining gaps |

## First demonstration

From a checked-out repository, start with:

```bash
bash start.sh tools
```

The launcher may install the local package on first use. Listing tool profiles does not contact their providers.

## A useful interview walkthrough

1. State the problem and the specific part you implemented or changed.
2. Open the source above and follow one request, release, or failure from start to finish.
3. Show a reproducible result, including an actual failure and the observation that confirms recovery.
4. Explain one tradeoff and one limitation. Distinguish a local test from a live deployment.

## Evidence and limits

This guide is based on the default-branch source inspected on 16 October 2026. It is a source review, not a fresh deployment or a certification of every feature. Existing CI runs and tests should be checked at the commit being demonstrated. Do not present screenshots, inherited code, planned features, or old README statements as proof of a current deployment.
