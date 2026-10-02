"""The committed infra JSON obeys the rules the README states.

These are the invariants that make the OIDC trust workflow-bound and the
roles least-privilege. A placeholder is fine; a wildcard or a second
workflow in a trust is not.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
INFRA = ROOT / "infra"
H = "token.actions.githubusercontent.com"
GATEWAY = json.loads((ROOT / "deploy" / "gateway.json").read_text())
NAME = GATEWAY["container"]


def load(rel: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((INFRA / rel).read_text())
    return data


BUILD_TRUST = load(f"iam/gha-{NAME}-build.trust.json")
DEPLOY_TRUST = load(f"iam/gha-{NAME}-deploy.trust.json")


def condition(trust: dict[str, Any]) -> dict[str, Any]:
    (stmt,) = trust["Statement"]
    assert set(stmt["Condition"]) == {"StringEquals"}, (
        "StringEquals only: no StringLike"
    )
    cond: dict[str, Any] = stmt["Condition"]["StringEquals"]
    return cond


@pytest.mark.parametrize("trust", [BUILD_TRUST, DEPLOY_TRUST], ids=["build", "deploy"])
def test_a_trust_is_one_allow_for_web_identity_with_exact_conditions(
    trust: dict[str, Any],
) -> None:
    (stmt,) = trust["Statement"]
    assert stmt["Effect"] == "Allow"
    assert stmt["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert stmt["Principal"]["Federated"].endswith(f"oidc-provider/{H}")
    cond = condition(trust)
    assert cond[f"{H}:aud"] == "sts.amazonaws.com"
    for key, value in cond.items():
        assert "*" not in str(value) and "?" not in str(value), (
            f"{key} carries a wildcard"
        )
    assert not any("StringLike" in json.dumps(s) for s in trust["Statement"])


def test_each_role_is_pinned_to_exactly_its_own_workflow_file() -> None:
    build = condition(BUILD_TRUST)[f"{H}:sub"]
    deploy = condition(DEPLOY_TRUST)[f"{H}:sub"]
    assert build.endswith("/.github/workflows/build-image.yml@refs/heads/main")
    assert deploy.endswith("/.github/workflows/deploy.yml@refs/heads/main")
    assert build != deploy
    for sub in (build, deploy):
        # the immutable id form and a pinned ref, then the workflow
        assert re.fullmatch(
            r"repo:[^/@]+@[^/@]+/[^/@]+@[^/:]+:ref:refs/heads/[^:]+:job_workflow_ref:[^:]+@refs/heads/[^:]+",
            sub,
        ), sub
        assert (
            ":environment:" not in sub
        )  # GitHub Free has no environments on private repos


def test_the_deploy_role_also_pins_the_owner_and_the_person_who_may_dispatch() -> None:
    build, deploy = condition(BUILD_TRUST), condition(DEPLOY_TRUST)
    assert f"{H}:repository_id" in build and f"{H}:repository_id" in deploy
    assert f"{H}:repository_owner_id" in deploy
    assert f"{H}:actor_id" in deploy
    assert f"{H}:actor_id" not in build  # a push to the default branch has no one actor


def _statements(rel: str) -> list[dict[str, Any]]:
    stmts: list[dict[str, Any]] = load(rel)["Statement"]
    return stmts


def _actions(stmt: dict[str, Any]) -> list[str]:
    a = stmt["Action"]
    return [a] if isinstance(a, str) else list(a)


def test_the_build_role_can_push_one_repository_and_do_nothing_else() -> None:
    stmts = _statements(f"iam/gha-{NAME}-build.policy.json")
    actions = {a for s in stmts for a in _actions(s)}
    assert actions <= {a for a in actions if a.startswith("ecr:")}
    scoped = [s for s in stmts if s["Resource"] != "*"]
    assert len(scoped) == 1
    assert scoped[0]["Resource"].endswith(f":repository/{NAME}")
    unscoped = [s for s in stmts if s["Resource"] == "*"]
    assert [_actions(s) for s in unscoped] == [["ecr:GetAuthorizationToken"]]


def test_the_deploy_role_updates_one_service_and_passes_only_its_two_roles() -> None:
    stmts = _statements(f"iam/gha-{NAME}-deploy.policy.json")
    by_sid = {s["Sid"]: s for s in stmts}
    assert by_sid["UpdateOnlyThisService"]["Resource"].endswith(f"/{NAME}")
    assert "*" not in by_sid["UpdateOnlyThisService"]["Resource"]
    passed = by_sid["PassOnlyThisServicesEcsRoles"]
    assert sorted(r.split("/")[-1] for r in passed["Resource"]) == [
        f"{NAME}-execution-role",
        f"{NAME}-task-role",
    ]
    assert (
        passed["Condition"]["StringEquals"]["iam:PassedToService"]
        == "ecs-tasks.amazonaws.com"
    )
    # the only `Resource: *` actions are the two ECS ones that cannot be resource scoped
    open_ended = {a for s in stmts if s["Resource"] == "*" for a in _actions(s)}
    assert open_ended == {"ecs:RegisterTaskDefinition", "ecs:DescribeTaskDefinition"}
    # no admin-shaped action anywhere
    every = {a for s in stmts for a in _actions(s)}
    assert not any(a.endswith(":*") or a == "*" for a in every)
    assert "ecr:PutImage" not in every  # the deploy role reads images, it never pushes


def test_the_task_role_reads_only_this_gateways_user_secrets_and_decrypts_via_secrets_manager() -> (
    None
):
    stmts = _statements(f"iam/{NAME}-task-role.policy.json")
    read = next(s for s in stmts if s["Action"] == "secretsmanager:GetSecretValue")
    assert "/users/*/" in read["Resource"] and read["Resource"] != "*"
    kms = next(s for s in stmts if s["Action"] == "kms:Decrypt")
    assert kms["Condition"]["StringEquals"]["kms:ViaService"].startswith(
        "secretsmanager."
    )
    assert "SecretARN" in json.dumps(kms["Condition"])


def test_the_ecr_repository_is_immutable_and_the_lifecycle_keeps_ten() -> None:
    repo = load("ecr/repository.json")
    assert repo["repositoryName"] == GATEWAY["ecr_repository"]
    assert repo["imageTagMutability"] == "IMMUTABLE"
    (rule,) = load("ecr/lifecycle-policy.json")["rules"]
    assert rule["selection"]["tagPrefixList"] == ["sha-"]
    assert rule["selection"]["countNumber"] == 10
    assert rule["action"] == {"type": "expire"}


def test_the_census_counts_the_event_the_audit_layer_writes() -> None:
    flt = load("cloudwatch/legacy-auth-metric-filter.json")
    query = load("cloudwatch/legacy-census-query.json")
    for text in (flt["filterPattern"], query["queryString"]):
        assert "mcp_auth" in text and "legacy" in text
    assert flt["logGroupName"] == query["logGroupNames"][0] == f"/ecs/{NAME}"
    # the log group is the one the task definition writes to
    base = json.loads((ROOT / "deploy" / "taskdef.base.json").read_text())
    options = base["containerDefinitions"][0]["logConfiguration"]["options"]
    assert options["awslogs-group"] == flt["logGroupName"]


def test_the_log_fields_the_census_reads_are_written_by_the_audit_layer() -> None:
    source = (ROOT / "src" / "fast_mcp_template" / "http" / "audit.py").read_text()
    assert 'event="mcp_auth"' in source
    assert "auth_path=auth_path" in source and "client_ip=client_ip" in source


def test_every_infra_file_is_valid_json_with_no_secret_value() -> None:
    files = sorted(INFRA.rglob("*.json"))
    assert len(files) >= 9  # the control: the population is not empty
    for path in files:
        text = path.read_text()
        json.loads(text)
        assert not re.search(r"AKIA[0-9A-Z]{16}", text), path
        assert "BEGIN PRIVATE KEY" not in text, path
