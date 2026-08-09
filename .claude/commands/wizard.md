---
description: Walk through the one-time setup steps only a logged-in human can do
---

Everything in this repo is configured except the steps below, which need a browser and
a logged-in human. Work through them one at a time with the user, and verify each
before moving on.

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

## 2. Decide the repository's visibility

The repo is **private** on a Free plan, which blocks two things the setup otherwise
wants:

- **Branch protection / required status checks** — cannot require `ci` to be green before merge.
- **Auto-merge** — `allow_auto_merge` cannot be enabled, so Renovate's `platformAutomerge` will fall back to merging via the API once checks pass rather than queueing.

Both work on a public repo, or on private with GitHub Pro. Ask the user which they
want. If they make it public:

```console
gh repo edit MartinBernstorff/pydantic-codegen --visibility public --accept-visibility-change-consequences
gh api -X PATCH repos/MartinBernstorff/pydantic-codegen -F allow_auto_merge=true
gh api -X PUT repos/MartinBernstorff/pydantic-codegen/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": {"strict": true, "contexts": ["checks"]},
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

Do not change visibility without the user explicitly saying so — it is public and
irreversible in effect.

Already configured, no action needed: squash-only merges, PR title as the squash
subject, delete branch on merge.

## 3. Onboard Renovate

The Renovate GitHub App is installed on the account, but it must also have access to
*this* repository. Check <https://github.com/settings/installations> → Renovate →
Repository access.

Renovate then opens an onboarding PR. `renovate.json` is already committed, so that PR
should be a no-op configuration confirmation — merge it.

Verify: the Dependency Dashboard issue appears in the repo.
