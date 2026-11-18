"""자료 참조로 높이 판정을 요청하는 경로 — 실제 카탈로그·작업 저장소 위, 판정자는 좁은 대역.

판정 규칙 자체는 ``test_external_use_evaluator`` 와 단면 통합 시험이 맡는다. 여기서는 이 경로가
무엇에 닿고(범위), 무엇을 거부하며(DSM 아님·닫힌 작업), 누구에게 열리는지(사람·쓰기 권한)를 본다.
합성 값만 쓴다. 측량 정확도의 증거가 아니다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog
from ksi_core.domains.external.quantity.asset_height_decision import (
    build_asset_height_decision_router,
)
from ksi_core.domains.external.quantity.external_use_decisions import (
    ExternalUseDecisionConflictError,
)
from ksi_event_contracts.external_artifact_validation import (
    DecisionVerdict,
    ExternalUseDecisionV1,
    SealedExternalSubjectV1,
)
from test_spatial_asset_catalog import _NOW, _setup
from test_vertical_reference_declaration_catalog import _dsm_submission, _Inspections, _seal

TOKENS = {
    "operator": ("tok-op", "org-a", Role.ADMIN, None, None),
    "viewer": ("tok-viewer", "org-a", Role.VIEWER, None, None),
    "other": ("tok-other", "org-b", Role.ADMIN, None, None),
}


class FakeEvaluator:
    """판정자 대역: 받은 질문을 기록하고, 요청한 용도는 HEIGHT 뿐임을 확인할 수 있게 한다."""

    def __init__(self) -> None:
        self.asked: list[dict[str, Any]] = []
        self.retained: dict[str, ExternalUseDecisionV1] = {}
        self.conflict = False
        self.declared = False
        self.verdict = DecisionVerdict.ELIGIBLE

    def has_declared_vertical(self, subject: Any, artifact_id: str) -> bool:
        return self.declared

    def existing_single_retry(
        self, subject: Any, *, use: str, principal: Any, idempotency_key: str
    ) -> Any:
        return self.retained.get(idempotency_key)

    def request_single(
        self,
        subject: SealedExternalSubjectV1,
        *,
        use: str,
        idempotency_key: str,
        principal: Any,
        now: Any,
    ) -> ExternalUseDecisionV1:
        if self.conflict:
            raise ExternalUseDecisionConflictError("conflict")
        self.asked.append(
            {"subject": subject, "use": use, "key": idempotency_key, "principal": principal}
        )
        if idempotency_key in self.retained:
            return self.retained[idempotency_key]
        blocked = self.verdict is DecisionVerdict.BLOCKED
        decision = ExternalUseDecisionV1(
            decision_id="external-use-decision-"
            + hashlib.sha256(idempotency_key.encode()).hexdigest()[:32],
            subject=subject,
            subject_digest=subject.canonical_digest(),
            use=cast(Any, use),
            policy_digest=None if blocked else "sha256:" + "1" * 64,
            inspection_report_digest=None if blocked else "sha256:" + "2" * 64,
            evidence_record_digests=(),
            verdict=self.verdict,
            reasons=("VERTICAL_REFERENCE_UNKNOWN",) if blocked else ("HEIGHT_ELIGIBLE",),
            remediations=("OBSERVE_VERTICAL_REFERENCE",)
            if blocked
            else ("CURRENT_DEPENDENCIES_RETAINED",),
            decided_at=_NOW,
        ).sealed()
        self.retained[idempotency_key] = decision
        return decision


class Env:
    def __init__(
        self, tmp_path: Path, kind: str = "dsm", *, sealed: bool = True, observed: bool = True
    ) -> None:
        (_c, order, storage, reconstruction, area_a, _b, work_orders, sites, areas) = _setup(
            tmp_path
        )
        if sealed:
            _seal(order, storage, reconstruction, kind)
        else:
            assert reconstruction.register(
                _dsm_submission(order, kind),
                work_order=order,
                registered_by="catalog-owner",
                now=_NOW,
            ).revision
        self.order, self.area, self.work_orders = order, area_a, work_orders
        self.evaluator = FakeEvaluator()
        inspections = _Inspections()
        inspections.artifact_id = kind
        inspections.mode = "measured_with_vertical" if observed else "measured_without_vertical"
        self.catalog = SpatialAssetCatalog(
            reconstruction=reconstruction,
            work_orders=work_orders,
            sites=sites,
            work_areas=areas,
            inspections=inspections,
        )
        records = [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(token.encode()).hexdigest(),
                principal=Principal(
                    principal_id=name,
                    kind=PrincipalKind.OPERATOR,
                    role=role,
                    device_id=None,
                    organization_id=org,
                ),
            )
            for name, (token, org, role, _s, _a) in TOKENS.items()
        ]
        # 범위가 제한된 운영자: 이 구역에만 닿는다.
        records.append(
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"tok-scoped").hexdigest(),
                principal=Principal(
                    principal_id="scoped",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                    organization_id="org-a",
                    allowed_site_ids=frozenset({order.site_id}),
                    allowed_work_area_ids=frozenset({"some-other-area"}),
                ),
            )
        )
        app = FastAPI()
        mount_auth(app, AuthRegistry(records))
        app.include_router(
            build_asset_height_decision_router(
                cast(Any, self.evaluator), self.catalog, work_orders=work_orders
            )
        )
        self.client = TestClient(app)
        principal = Principal(
            principal_id="operator",
            kind=PrincipalKind.OPERATOR,
            role=Role.ADMIN,
            device_id=None,
            organization_id="org-a",
        )
        items = self.catalog.items(order.site_id, area_a.work_area_id, principal)
        self.asset_ref = items[0].asset_ref
        self.url = (
            f"/v1/sites/{order.site_id}/work-areas/{area_a.work_area_id}"
            f"/spatial-assets/{self.asset_ref}/height-decision"
        )

    def post(self, token: str = "tok-op", key: str | None = "k1", url: str | None = None) -> Any:
        headers = {"Authorization": f"Bearer {token}"}
        if key is not None:
            headers["Idempotency-Key"] = key
        return self.client.post(url or self.url, headers=headers)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def test_a_dsm_gets_a_height_decision_and_only_height_is_asked(env: Env) -> None:
    response = env.post()
    assert response.status_code == 201, response.text
    decision = response.json()["decision"]
    assert decision["use"] == "HEIGHT" and decision["verdict"] == "ELIGIBLE"
    assert decision["decisionId"].startswith("external-use-decision-")
    (asked,) = env.evaluator.asked
    assert asked["use"] == "HEIGHT" and asked["key"] == "k1"
    subject = asked["subject"]
    assert (subject.organization_id, subject.site_id) == ("org-a", env.order.site_id)
    assert (subject.work_order_id, subject.submission_id, subject.revision) == (
        env.order.work_order_id,
        "submission-dsm",
        1,
    )


def test_a_submission_level_eligible_is_not_this_assets_basis_without_its_own_reference(
    tmp_path: Path,
) -> None:
    # 같은 제출의 다른 DSM이 기준을 가져 판정은 ELIGIBLE이지만, 이 자료에는 관측도 선언도 없다.
    bare = Env(tmp_path, observed=False)
    response = bare.post()
    assert response.status_code == 409
    assert "ASSET_VERTICAL_REFERENCE_UNKNOWN" in response.text
    assert "decisionId" not in response.text  # 이 자료의 근거가 아닌 판정을 내보내지 않는다.
    # 이 자료에 현재 선언이 있으면 열린다.
    bare.evaluator.declared = True
    assert bare.post(key="declared").status_code == 201


def test_a_blocked_decision_still_explains_itself_when_the_asset_has_no_reference(
    tmp_path: Path,
) -> None:
    bare = Env(tmp_path, observed=False)
    bare.evaluator.verdict = DecisionVerdict.BLOCKED
    response = bare.post()
    assert response.status_code == 201
    assert response.json()["decision"]["reasons"] == ["VERTICAL_REFERENCE_UNKNOWN"]


def test_a_blocked_decision_is_returned_with_its_reasons(env: Env) -> None:
    env.evaluator.verdict = DecisionVerdict.BLOCKED
    response = env.post()
    assert response.status_code == 201
    decision = response.json()["decision"]
    assert decision["verdict"] == "BLOCKED"
    assert decision["reasons"] == ["VERTICAL_REFERENCE_UNKNOWN"]
    assert decision["remediations"] == ["OBSERVE_VERTICAL_REFERENCE"]


def test_the_same_key_returns_the_same_decision(env: Env) -> None:
    first = env.post(key="same").json()["decision"]["decisionId"]
    again = env.post(key="same").json()["decision"]["decisionId"]
    other = env.post(key="different").json()["decision"]["decisionId"]
    assert first == again and first != other


def test_an_idempotency_conflict_is_a_409(env: Env) -> None:
    env.evaluator.conflict = True
    response = env.post()
    assert response.status_code == 409 and "IDEMPOTENCY_CONFLICT" in response.text


def test_only_a_dsm_can_be_asked(tmp_path: Path) -> None:
    ortho = Env(tmp_path, kind="ortho")
    response = ortho.post()
    assert response.status_code == 409 and "NOT_A_DSM" in response.text
    assert ortho.evaluator.asked == []


def test_an_asset_that_is_registered_but_not_sealed_cannot_be_asked(tmp_path: Path) -> None:
    unsealed = Env(tmp_path, sealed=False)
    response = unsealed.post()
    assert response.status_code == 409 and "EXTERNAL_RECONSTRUCTION_NOT_SEALED" in response.text
    assert unsealed.evaluator.asked == []


def test_a_viewer_and_a_missing_key_are_refused(env: Env) -> None:
    assert env.post(token="tok-viewer").status_code == 403
    assert env.post(key=None).status_code == 422
    assert env.post(key="   ").status_code == 422
    assert env.client.post(env.url).status_code in {401, 403}
    assert env.evaluator.asked == []


def test_other_organizations_and_unknown_assets_see_a_plain_404(env: Env) -> None:
    assert env.post(token="tok-other").status_code == 404
    assert env.post(url=env.url.replace(env.asset_ref, "ksa-v1-" + "c" * 64)).status_code == 404
    assert env.post(url=env.url.replace(env.asset_ref, "not-an-asset")).status_code == 404
    assert env.post(url=env.url.replace(env.area.work_area_id, "wa-other")).status_code == 404
    assert env.evaluator.asked == []


def test_an_operator_scoped_to_another_work_area_cannot_ask(env: Env) -> None:
    # 범위가 제한된 운영자는 허용된 구역의 자료에만 닿는다(기존 판정 경로가 닫혀 있던 이유).
    assert env.post(token="tok-scoped").status_code == 404
    assert env.evaluator.asked == []


def test_a_closed_workflow_refuses_a_new_decision(env: Env) -> None:
    assert env.post(key="kept").status_code == 201

    def closed(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("EXTERNAL_WORKFLOW_CLOSED")

    env.work_orders.guard_new_external_intent = closed
    refused = env.post(key="fresh")
    assert refused.status_code == 409 and "EXTERNAL_WORKFLOW_CLOSED" in refused.text


def test_the_published_openapi_matches_the_mounted_route(env: Env) -> None:
    import yaml
    from fastapi.routing import APIRoute

    root = Path(__file__).resolve().parents[2]
    document = yaml.safe_load((root / "contracts/api/openapi-core.yaml").read_text())
    published = {
        (method.upper(), path)
        for path, item in document["paths"].items()
        if path.endswith("/height-decision")
        for method in item
        if method in {"get", "post", "put", "delete", "patch"}
    }
    router = build_asset_height_decision_router(
        cast(Any, env.evaluator), env.catalog, work_orders=env.work_orders
    )
    mounted = {
        (method, route.path)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in (route.methods or set())
    }
    assert mounted == published and len(mounted) == 1


def test_scoped_operators_may_reach_the_route_because_the_handler_re_checks_scope() -> None:
    from ksi_core.identity import auth

    route = (
        "POST",
        "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-assets/{asset_ref}/height-decision",
    )
    assert route in auth._OIDC_SCOPED_OPERATOR_ROUTE_ALLOWLIST  # noqa: SLF001
    # MCP 허용 목록은 넓히지 않는다.
    assert route not in auth._SPATIAL_DATA_ROUTE_ALLOWLIST  # noqa: SLF001
