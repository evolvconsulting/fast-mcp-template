# infra: desired state, applied by a person

Everything under `infra/` is the DESIRED state of AWS resources, committed so a reviewer sees it.
Nothing in CI applies it. Every value that names your account is a PLACEHOLDER
(`000000000000`, `OWNER`, `OWNER_ID`, `REPO`, `REPO_ID`, `ACTOR_ID`, `CLUSTER`, `KMS_KEY_ID`):
replace them before applying, and keep `deploy/gateway.json` in step.

## The OIDC workflow-bound pattern (`iam/*.trust.json`)

Two roles, one per workflow, and each trust pins the WORKFLOW FILE, not just the repository:

| Role | Pinned `sub` | Extra conditions | Permissions |
|---|---|---|---|
| build | `...:ref:refs/heads/main:job_workflow_ref:<repo>/.github/workflows/build-image.yml@refs/heads/main` | `aud`, `repository_id` | ECR push to ONE repository |
| deploy | the same, for `deploy.yml` | `aud`, `repository_id`, `repository_owner_id`, `actor_id` (the person who may dispatch) | register a task definition, update ONE service, pass ONLY that service's two roles |

Rules the tests enforce (`tests/test_infra.py`):

- `StringEquals` only, never `StringLike`, never a wildcard: a trust that can match more than one
  workflow, branch or repository is the bug.
- `sub` is the IMMUTABLE form (owner and repository ids), so a renamed or recreated repository
  does not inherit the trust.
- `sub` ends with the one workflow file the role is for, and the two roles name different files.
- the deploy role is not trusted for any other workflow, and has no `environment:` claim
  (GitHub Free has no environments on private repositories).

A separate `job_workflow_ref` condition KEY never matched in AWS STS (measured 2026-10-01 on
fast-mcp-ado), so the workflow is bound through the repository's `sub` template instead. Set it
ONCE, then confirm with the `oidc claims probe` workflow, which also proves both roles REFUSE an
unpinned workflow:

This is the live setting on evolvconsulting/fast-mcp-ado and evolvconsulting/evolv-coder-be (read
with `gh api repos/<owner>/<repo>/actions/oidc/customization/sub` on 2026-10-02:
`use_default=false`, `use_immutable_subject=true`, claim keys `repo`, `ref`, `job_workflow_ref`).

```bash
# Apply (a GitHub write: needs repo admin).
gh api -X PUT repos/OWNER/REPO/actions/oidc/customization/sub \
  -F use_default=false -F use_immutable_subject=true \
  -f 'include_claim_keys[]=repo' -f 'include_claim_keys[]=ref' \
  -f 'include_claim_keys[]=job_workflow_ref'
# Rollback: back to the default template.
gh api -X PUT repos/OWNER/REPO/actions/oidc/customization/sub -F use_default=true
```

Verify the `sub` the probe prints against the trust BEFORE trusting either: the template above
yields `repo:OWNER@OWNER_ID/REPO@REPO_ID:ref:refs/heads/main:job_workflow_ref:OWNER/REPO/.github/workflows/FILE@refs/heads/main`,
the form the trusts in `infra/iam/gha-*.trust.json` expect; if the probe prints anything else,
adjust the trust to it.

## Other files

- `ecr/repository.json`, `ecr/lifecycle-policy.json`: an IMMUTABLE-tag repository that keeps the
  10 newest `sha-` images.
- `iam/*-task-role.policy.json`: the vault read, scoped to `mcp/users/*/<server key>` and to
  decrypt only through Secrets Manager.
- `cloudwatch/`: a metric filter and a Logs Insights query that count, per day, requests still
  using the retiring credential (`mcp_auth` lines with `auth_path = legacy`): the census that
  decides when `3-platform` is safe. Reusable for any "is anyone still using X" retirement.
