---
description: Walk through the one-time setup steps only a logged-in human can do
---

Everything in this repo is configured except the steps below, which need a browser and
a logged-in human. Work through them one at a time with the user, and verify each
before moving on.

Already done, no action needed: the repo is public, squash-only merges with the PR
title as the squash subject, delete branch on merge, auto-merge enabled, and `main`
protected behind the `checks` status check.

## 1. Register the PyPI trusted publisher

Without this, `release` builds a wheel and then fails at the upload step.

Open <https://pypi.org/manage/account/publishing/> and add a **pending publisher**
(the project does not exist on PyPI yet, so it must be the pending form):

| Field | Value |
| --- | --- |
| PyPI Project Name | `pydantic-codegen` |
| Owner | `MartinBernstorff` |
| Repository name | `pydantic-codegen` |
| Workflow name | `release.yml` |
| Environment name | *(leave blank)* |

Verify: `curl -s -o /dev/null -w '%{http_code}' https://pypi.org/pypi/pydantic-codegen/json`
returns `404` until the first release lands, then `200`.

## 2. Onboard Renovate

The Renovate GitHub App is installed on the account, but it must also have access to
*this* repository. Check <https://github.com/settings/installations> → Renovate →
Repository access.

Renovate then opens an onboarding PR. `renovate.json` is already committed, so that PR
should be a no-op configuration confirmation — merge it.

Verify: the Dependency Dashboard issue appears in the repo.
