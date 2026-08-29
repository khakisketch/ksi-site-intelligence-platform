"""적대적 입력 조사의 **범위**를 시점이 아니라 게이트로 고정한다.

## 왜 이 파일이 생겼나

``test_validation_error_rendering.py`` 는 2026-08-18 전수 조사가 찾은 500 유출
4개 클래스를 횡단으로 막는다. 그 조사의 근거는 원장에 "라우터 20개 전수 조사"로
적혔다 — **시점 주장**이다.

시점 주장의 수명은 다음 병합까지다. 실제로 그 조사 직후 다른 갈래에서 커버리지
보고·증거 라우터가 새로 장착됐고, 병합하는 순간 "전수"라는 말은 사실이 아니게
됐다(2026-08-18 병합 준비 중 독립 조사에서 지적). 수정 자체는 공용 베이스에
걸려 있어 새 라우터도 자동으로 덮이지만, **덮였는지 아무도 확인하지 않았다**는
것이 문제다.

그래서 이 파일은 주장을 게이트로 바꾼다: 본문을 받는 ``/v1`` 라우트 목록을
얼려 두고, 새 라우트가 장착되면 실패한다. 실패 메시지가 요구하는 것은
"목록에 한 줄 추가"가 아니라 **그 라우트를 적대적 입력으로 실제로 두드려 보고
근거와 함께 등재하라**는 것이다.

## 이 게이트가 막지 못하는 것

라우트가 **사라지는** 것은 막지 않는다(목록에서 빼면 그만이다). 또 등재된
라우트가 실제로 조사됐는지도 강제하지 못한다 — 사람이 근거를 적는 자리이지
기계가 검증하는 자리가 아니다. 기계가 하는 일은 **모르고 지나가는 것을 막는
것** 하나다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.app_assembly import assemble_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal

#: 본문을 받는 ``/v1`` 라우트 — 값은 "무엇으로 조사됐나"의 근거다.
#:
#: 새 라우트를 여기 넣기 전에 해야 할 일: ``test_validation_error_rendering.py``
#: 의 ``_HOSTILE_BODIES`` 를 그 라우트에 실제로 쏴 보고(``raise_server_exceptions
#: =False`` 로), 500 이 아니라 422 로 그려지는지 확인한다. 계약 모델이 공용
#: 베이스(``_CamelModel``/``CamelModel``)를 상속하면 비유한 실수·lone surrogate 는
#: 그 층에서 막히므로 대개 "베이스 상속"이 근거가 된다.
#: 되풀이되는 근거 셋 — 줄마다 같은 문장을 베끼면 목록이 읽히지 않는다.
_BASE = "공용 계약 베이스 상속 — 비유한 실수·lone surrogate 가 그 층에서 막힌다(개별 발사 미확인)"
_NO_BODY = "본문 없음(경로 파라미터만) — 본문 검증 층에 닿지 않는다"

#: 적대적 입력을 **실제로 쏴 본** 라우트들의 근거.
_FIRED_DIRECTLY = "횡단 게이트가 적대적 본문 6종을 이 라우트로 직접 쏜다"
_REGRESSION_COORD_OVERFLOW = "좌표 오버플로 typed 거부 회귀 있음"
_REGRESSION_SUBNORMAL_FOCAL = "초점거리 subnormal typed 거부 회귀 있음"
_REGRESSION_PAYLOAD_DEPTH = "payload 중첩 깊이 상한 회귀 있음(F4)"
_REGRESSION_CONTRACT_BASE = "계약 베이스 상속 교정 회귀 있음(F2)"
_REGRESSION_RATIO_FOLD = "진척 비율 typed 접기 회귀 있음(F6)"
_REGRESSION_SURROGATE = "lone surrogate 사전 거부 회귀 있음"
_REGRESSION_NON_FINITE = "비유한 실수 거부 회귀 있음"
_REGRESSION_POLYGON_DEPTH = "폴리곤 중첩 깊이 상한 회귀 있음"
_REGRESSION_CRS_WHITELIST = "좌표계 화이트리스트 거부 회귀 있음"

REVIEWED_WRITE_ROUTES: dict[tuple[str, str], str] = {
    (
        "POST",
        "/v1/checkpoint-validations/{validation_id}/observations",
    ): _FIRED_DIRECTLY,
    ("POST", "/v1/checkpoint-validations/{validation_id}/seal"): _NO_BODY,
    (
        "POST",
        "/v1/checkpoint-validations/{validation_id}/verification-failure",
    ): _FIRED_DIRECTLY,
    ("POST", "/v1/comparison-requests/{request_id}/lease"): _NO_BODY,
    ("POST", "/v1/comparison-requests/{request_id}/transitions"): _BASE,
    ("POST", "/v1/design-conformance-requests/{request_id}/diff-raster-upload-url"): _NO_BODY,
    ("POST", "/v1/design-conformance-requests/{request_id}/diff-raster-verification"): _BASE,
    ("POST", "/v1/design-conformance-requests/{request_id}/lease"): _NO_BODY,
    ("POST", "/v1/design-conformance-requests/{request_id}/transitions"): _BASE,
    ("POST", "/v1/design-surfaces/{design_surface_id}/observations"): _BASE,
    ("POST", "/v1/design-surfaces/{design_surface_id}/normalization-failure"): _FIRED_DIRECTLY,
    ("POST", "/v1/design-surfaces/{design_surface_id}/verification-failure"): _BASE,
    ("POST", "/v1/edge-sync/event-bundles"): _REGRESSION_PAYLOAD_DEPTH,
    ("POST", "/v1/edge-sync/events/{event_key}/evidence"): _BASE,
    ("POST", "/v1/edge-sync/missions/{dispatch_id}/activation-receipts"): _BASE,
    ("POST", "/v1/edge-sync/missions/{dispatch_id}/flight-start-receipts"): _BASE,
    ("POST", "/v1/equipment-support"): _BASE,
    ("PATCH", "/v1/equipment-support/{class_id}"): _BASE,
    ("POST", "/v1/events/{event_key}/evidence"): _BASE,
    ("POST", "/v1/events/{event_key}/transitions"): _BASE,
    ("POST", "/v1/gateway-sync/heartbeats"): _FIRED_DIRECTLY,
    ("POST", "/v1/gateway-sync/operation-receipts"): _FIRED_DIRECTLY,
    ("POST", "/v1/missions/contracts"): _BASE,
    ("POST", "/v1/missions/plans"): _REGRESSION_SUBNORMAL_FOCAL,
    ("POST", "/v1/missions/{mission_id}/change-detection"): _BASE,
    ("POST", "/v1/missions/{mission_id}/comparison-preflight"): _FIRED_DIRECTLY,
    ("POST", "/v1/missions/{mission_id}/comparison-requests"): _BASE,
    ("POST", "/v1/missions/{mission_id}/capture-quality-report"): _FIRED_DIRECTLY,
    ("POST", "/v1/missions/{mission_id}/coverage-report"): _BASE,
    ("POST", "/v1/missions/{mission_id}/defect-candidates"): _REGRESSION_CONTRACT_BASE,
    ("POST", "/v1/missions/{mission_id}/design-conformance"): _REGRESSION_RATIO_FOLD,
    ("POST", "/v1/missions/{mission_id}/design-conformance-requests"): _BASE,
    (
        "POST",
        "/v1/missions/{mission_id}/design-conformance/{design_conformance_id}/progress-baseline",
    ): _BASE,
    (
        "POST",
        "/v1/missions/{mission_id}/design-conformance/{design_conformance_id}/region-extraction-requests",
    ): _NO_BODY,
    ("POST", "/v1/missions/{mission_id}/execution-transitions"): _REGRESSION_SURROGATE,
    ("POST", "/v1/missions/{mission_id}/flight-artifacts/pilot-export"): _FIRED_DIRECTLY,
    ("POST", "/v1/missions/{mission_id}/processing-jobs"): _BASE,
    ("POST", "/v1/missions/{mission_id}/region-extraction"): _BASE,
    ("POST", "/v1/missions/{mission_id}/source-media"): _BASE,
    ("POST", "/v1/missions/{mission_id}/source-media/ground-control"): _REGRESSION_CRS_WHITELIST,
    ("POST", "/v1/missions/{mission_id}/source-media/seal"): _NO_BODY,
    ("POST", "/v1/missions/{mission_id}/source-media/verify"): _BASE,
    ("POST", "/v1/missions/{mission_id}/volume-changes"): _BASE,
    ("POST", "/v1/observation-work-orders/{work_order_id}/approve"): _FIRED_DIRECTLY,
    (
        "POST",
        "/v1/observation-work-orders/{work_order_id}/reobservation-drafts",
    ): _FIRED_DIRECTLY,
    ("POST", "/v1/processing-jobs/{job_id}/artifacts"): _BASE,
    (
        "POST",
        "/v1/processing-jobs/{job_id}/artifacts/{artifact_id}/checkpoint-validations",
    ): _FIRED_DIRECTLY,
    ("POST", "/v1/processing-jobs/{job_id}/artifacts/upload-url"): _BASE,
    ("POST", "/v1/processing-jobs/{job_id}/lease"): _NO_BODY,
    ("POST", "/v1/processing-jobs/{job_id}/transitions"): _BASE,
    ("POST", "/v1/region-extraction-requests/{request_id}/lease"): _NO_BODY,
    ("POST", "/v1/region-extraction-requests/{request_id}/transitions"): _BASE,
    ("POST", "/v1/reobservation-drafts/{draft_id}/approve"): _FIRED_DIRECTLY,
    ("POST", "/v1/sites"): _FIRED_DIRECTLY,
    ("PUT", "/v1/sites/{site_id}/aoi"): _REGRESSION_COORD_OVERFLOW,
    ("PUT", "/v1/sites/{site_id}/acquisition-profile"): _FIRED_DIRECTLY,
    ("POST", "/v1/sites/{site_id}/design-surfaces"): _REGRESSION_CRS_WHITELIST,
    ("POST", "/v1/sites/{site_id}/design-surfaces/{design_surface_id}/seal"): _NO_BODY,
    ("POST", "/v1/sites/{site_id}/equipment-states"): _REGRESSION_NON_FINITE,
    ("POST", "/v1/sites/{site_id}/observation-schedules"): _FIRED_DIRECTLY,
    ("POST", "/v1/sites/{site_id}/observation-work-orders"): _FIRED_DIRECTLY,
    ("PUT", "/v1/sites/{site_id}/model-age-policy"): _BASE,
    ("POST", "/v1/sites/{site_id}/spatial-model/staleness-sweep"): _NO_BODY,
    ("POST", "/v1/sites/{site_id}/transitions"): _BASE,
    ("POST", "/v1/sites/{site_id}/work-areas"): _REGRESSION_POLYGON_DEPTH,
    ("POST", "/v1/sites/{site_id}/work-areas/{work_area_id}/archive"): _NO_BODY,
}

_TOKEN = "hostile-coverage-admin"  # noqa: S105 -- 테스트 고정값


class _StubStorage:
    """포트 계약만 만족하는 대역 — 이 게이트는 **장착 여부**만 보므로 동작은 필요 없다.

    스토리지를 안 주면 재구성·증거·비교 표면이 통째로 안 달려서(assemble_app 의
    조건부 조립) 게이트가 절반만 보게 된다.
    """

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        del content_type, ttl
        return f"https://stub.invalid/{object_key}"

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        del ttl
        return f"https://stub.invalid/{object_key}"

    def put_bytes(self, object_key: str, payload: bytes, *, content_type: str) -> None:
        del object_key, payload, content_type

    def get_bytes(self, object_key: str) -> bytes:
        del object_key
        return b""

    def delete(self, object_key: str) -> None:
        del object_key


def _auth_registry() -> AuthRegistry:
    import hashlib

    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_TOKEN.encode()).hexdigest(),
                principal=Principal(
                    principal_id="op-admin",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            )
        ]
    )


def _mounted_write_routes() -> set[tuple[str, str]]:
    """**가장 많이 장착되는** 조립에서 본문을 받는 /v1 라우트 전수."""
    with tempfile.TemporaryDirectory() as tmp:
        opened: list[DurableJournal] = []

        def journal(name: str) -> DurableJournal:
            item = DurableJournal(Path(tmp) / name)
            opened.append(item)
            return item

        try:
            app = assemble_app(
                Path(tmp),
                journal=journal,
                opened=opened,
                edge_sync_snapshot_every=100,
                auth_registry=_auth_registry(),
                evidence_storage=_StubStorage(),
                # 서명키가 없으면 계약·짝 발급 라우트가 통째로 안 달린다 —
                # 그 둘이야말로 이 게이트가 놓치면 안 되는 표면이다.
                mission_signing_key=Ed25519PrivateKey.generate(),
                mission_signing_key_id="gate-key",
            )
            spec = app.openapi()
        finally:
            for item in opened:
                item.close()

    return {
        (method.upper(), path)
        for path, operations in spec["paths"].items()
        if path.startswith("/v1")
        for method in operations
        if method in ("post", "put", "patch")
    }


def test_every_mounted_write_route_has_been_considered() -> None:
    """새로 장착된 라우트가 적대적 입력 조사를 **모르고 지나가지** 않는다.

    이 게이트가 없으면 "전수 조사했다"는 원장의 근거가 다음 병합에서 조용히
    낡는다 — 실제로 그렇게 낡았고(커버리지 보고·증거 라우터), 그 사실을 아무도
    표시하지 않았다.
    """
    mounted = _mounted_write_routes()
    unreviewed = sorted(mounted - set(REVIEWED_WRITE_ROUTES))
    assert not unreviewed, (
        "본문을 받는 /v1 라우트가 적대적 입력 조사 목록에 없다 — 목록에 한 줄 "
        "추가하기 전에 test_validation_error_rendering.py 의 _HOSTILE_BODIES 를 "
        f"그 라우트에 실제로 쏴 보고 422 로 그려지는지 확인하라: {unreviewed}"
    )


def test_the_list_does_not_outlive_its_routes() -> None:
    """사라진 라우트가 목록에 남아 "조사했다"는 인상만 남기지 않게 한다."""
    mounted = _mounted_write_routes()
    stale = sorted(set(REVIEWED_WRITE_ROUTES) - mounted)
    assert not stale, (
        "목록에는 있는데 조립에 없는 라우트다 — 표면이 사라졌으면 목록에서도 "
        f"지워야 근거가 현재를 말한다: {stale}"
    )


def test_every_entry_states_its_basis() -> None:
    """근거 없는 등재는 목록을 통과 도장으로 만든다."""
    empty = sorted(route for route, basis in REVIEWED_WRITE_ROUTES.items() if not basis.strip())
    assert not empty, f"근거가 비어 있는 등재: {empty}"
