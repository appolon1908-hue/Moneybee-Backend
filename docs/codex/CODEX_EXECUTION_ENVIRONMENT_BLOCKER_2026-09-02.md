# Codex execution environment blocker — 2026-09-02

## Status

```text
MISSION_PUBLISHED=YES
MISSION_PR=45
EXECUTION_ISSUE=44
BACKEND_PR_TRIGGERED=YES
FRONTEND_PR_TRIGGERED=YES
CODE_REVIEW_AVAILABLE=YES
BACKEND_CODE_EXECUTION_ENVIRONMENT=MISSING
FRONTEND_CODE_EXECUTION_ENVIRONMENT=MISSING
REPOSITORY_CODE_MODIFICATION_STARTED=NO
SERVER_CONTACT_AUTHORIZED=NO
```

The full repository-to-production mission has been published and addressed to Codex. GitHub accepted the mission comments, but Codex responded to the execution commands in both repositories with:

```text
To use Codex here, create an environment for this repo.
```

Codex review remains available and is running against the release PRs, but Codex cannot take the requested code-modification task until an execution environment exists for each repository.

## Required account-side setup

In ChatGPT, open **Codex**, then **Environments** or **Manage Environments**, and create one environment for each repository:

```text
MoneyBee Backend
appolon1908-hue/Moneybee-Backend

MoneyBee Frontend
appolon1908-hue/Moneybee-frontend-
```

The GitHub connector installation must be authorized for both repositories. Each environment must permit Codex to check out the repository, install dependencies, run the existing test/build commands, and push commits to the active PR branch under the repository's normal permissions. Do not grant a bypass around protected `main`.

Official setup reference:

https://help.openai.com/en/articles/11390924

Direct environment settings used by the GitHub Codex bot:

https://chatgpt.com/codex/cloud/settings/environments

## Environment safety rules

- Create repository-development environments first; do not add production SSH access to these environments.
- Do not store production database, Keycloak administrator, provider, OpenBao, SMTP, payment, lender, DocuSign, Odoo, or n8n credentials in a general repository environment.
- Do not add a GitHub token with branch-protection bypass authority.
- Keep server access blocked until the repositories are exact-head green, merged through normal protections, and the immutable release lock is complete.
- Any later server execution identity must be dedicated, least-privilege, separately approved, and unable to alter SSH configuration.

## Commands to retrigger after environments are created

Post this on backend PR #42:

```text
@codex address all unresolved review feedback on this PR and the four failing exact-head tests. Apply the fixes directly to this PR branch, add or strengthen regression tests, run the complete repository gates, push the resulting commits, and follow issue #44 and mission PR #45. Do not merge or deploy.
```

Post this on frontend PR #27:

```text
@codex address all unresolved review feedback on this PR. Apply the fixes directly to this PR branch with focused tests, then follow backend issue appolon1908-hue/Moneybee-Backend#44 and mission PR appolon1908-hue/Moneybee-Backend#45. Re-lock to the final backend merge SHA before certification. Do not merge or deploy.
```

Post this on backend issue #44 after both repository environments exist:

```text
@codex Execute the complete repository-to-production mission in PR #45 now. Start with backend PR #42, then frontend PR #27. Do not contact 49.12.145.107 until REPOSITORY_PHASE_CERTIFIED=YES and the immutable release lock is complete.
```

## Unblock criteria

```text
BACKEND_CODEX_ENVIRONMENT=CREATED_AND_TESTED
FRONTEND_CODEX_ENVIRONMENT=CREATED_AND_TESTED
BACKEND_PR_COMMAND_ACCEPTED_WITHOUT_ENVIRONMENT_ERROR=YES
FRONTEND_PR_COMMAND_ACCEPTED_WITHOUT_ENVIRONMENT_ERROR=YES
ISSUE_44_EXECUTION_COMMAND_ACCEPTED=YES
```

Until those criteria are met, the authoritative source lock must remain deployment-authorized `false` and server-contact-authorized `false`.
