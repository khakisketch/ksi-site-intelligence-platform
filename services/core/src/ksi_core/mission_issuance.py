"""Mission Contract 발급 — 구역+임무타입 정의의 두 산출물 중 절반 (ADR-KSI-007).

ADR-KSI-007: "구역을 그리고 임무 종류를 고른다"는 행위 하나가 서로 다른 소비자를
향한 두 산출물을 낸다 — ① M4D용 웨이포인트(WPML/KMZ, 이 모듈의 범위 밖) ②
Manifold용 Mission Contract(이 모듈). 이 모듈은 ②만 구현한다.

## 안전 상수는 클라이언트가 지정하지 않는다

Policies 중 coveragePolicy 필수치(1.0/1.0)·communicationLossPolicy·batteryPolicy·
unknownObstaclePolicy·evidencePolicy는 FINAL_DECISION_LEDGER_v1.0(§안전·완료,
§사건과증거)이 이미 확정한 값이다 — 발급 요청 바디에 그 값을 다시 입력받으면
호출자가 실수로(또는 의도적으로) 안전 하한을 낮춘 계약을 서명받을 길이 열린다.
그래서 이 서버가 상수로 고정 적용하고, 요청은 사이트별로 실제 다른 값(구역·
정책팩 ID·좌표계 등)만 받는다.

## 알려진 잔여 한계 — 서명 키 공급 (미결정)

이 모듈은 이미 로드된 :class:`Ed25519PrivateKey` 객체를 주입받을 뿐, 그 키가
어디서·어떻게 나오는지(개발: 임시 생성 / 운영: 비밀 관리소 등)는 결정하지
않는다 — 프로덕션 키 수명주기는 별도 ADR 대상이다(edge_sync.py의 "잔여 한계"
절과 같은 패턴 — 여기서 추측하지 않는다).

## 알려진 잔여 한계 — 무인증 서명 오라클

``/v1/missions/contracts``·``/v1/missions/plans`` 는 서명키가 주입된 조립에서
**호출자 인증 없이** 유효한 Mission Contract 서명을 발급한다 — 이 모듈은 요청
바디의 정당성(그 사이트·그 임무를 요청할 권한이 그 호출자에게 있는가)을 검증
하지 않는다. 이 경계를 이 모듈이 스스로 해소하지 않는다 — 해소는 S2 인증
도입이 이 경계 앞에 서는 것이다(원장 risk mission-issuance-unauthenticated-
signing-oracle). 그 전까지는 이 엔드포인트를 신뢰 경계 밖에 직접 노출하지
않는 운영이 전제다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from ksi_domain.enums import MissionType
from ksi_mission_contracts.models import (
    Artifacts,
    BatteryPolicy,
    CommunicationLossPolicy,
    EvidencePolicy,
    FlightEnvelope,
    MissionContractV1_2,
    SiteFrame,
    UnknownObstaclePolicy,
)
from ksi_mission_contracts.signing import sign_contract
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi import FastAPI

# FINAL_DECISION_LEDGER_v1.0 §안전·완료·사건과증거 — 서버 고정 상수(요청으로 변경 불가).
_COMMUNICATION_LOSS_POLICY = CommunicationLossPolicy(
    server_link="CONTINUE_WHILE_CONTRACT_AND_SAFETY_VALID",
    rc_command_link="DELEGATE_TO_DJI_FLIGHT_CONTROLLER",
)
_BATTERY_POLICY = BatteryPolicy(
    mode="RETURN_ENERGY_PLUS_RESERVE", default_reserve_percent=30, site_override_allowed=True
)
_UNKNOWN_OBSTACLE_POLICY = UnknownObstaclePolicy(initial_action="SLOW", unresolved_action="RETREAT")
_EVIDENCE_POLICY = EvidencePolicy(
    candidate_pre_post_seconds=3, high_pre_post_seconds=5, critical_pre_post_seconds=10
)

_MAX_VALID_FOR_HOURS = 168.0  # 7일 상한 — 무기한 계약 발급 방지(현장 재방문 주기 밖)


class MissionIssuanceRequest(BaseModel):
    """구역+임무타입 발급 요청 — 사이트별로 실제 달라지는 값만 받는다."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    mission_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    mission_type: MissionType
    site_frame: SiteFrame
    flight_envelope: FlightEnvelope
    objectives: list[str] = Field(min_length=1)
    viewpoint_policy_id: str = Field(min_length=1)
    risk_policy_pack_id: str = Field(min_length=1)
    fallback_policy_id: str = Field(min_length=1)
    capture_policy_id: str = Field(min_length=1)
    accessible_general_coverage: float = Field(default=0.95, ge=0.95, le=1.0)
    artifacts: Artifacts = Field(default_factory=Artifacts)
    valid_for_hours: float = Field(default=24.0, gt=0.0, le=_MAX_VALID_FOR_HOURS)


def issue_mission_contract(
    request: MissionIssuanceRequest,
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
    issued_at: datetime | None = None,
) -> MissionContractV1_2:
    """서명된 MissionContract(v1.2)를 만든다 — 구조 검증까지 통과한 모델만 반환한다."""
    now = issued_at if issued_at is not None else datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("issued_at 은 tz-aware 여야 한다")
    not_after = now + timedelta(hours=request.valid_for_hours)

    unsigned: dict[str, Any] = {
        "schemaVersion": "1.2",
        "missionId": request.mission_id,
        "siteId": request.site_id,
        "missionType": request.mission_type.value,
        "validity": {"notBefore": now.isoformat(), "notAfter": not_after.isoformat()},
        "siteFrame": request.site_frame.model_dump(by_alias=True, mode="json", exclude_none=True),
        # altitudeReference 는 요청값과 무관하게 서버가 고정한다(2026-07-29 대표자
        # 확정 — 봉투 고도의 수직기준은 이륙점 상대. 안전 상수 고정과 같은 원칙).
        "flightEnvelope": {
            **request.flight_envelope.model_dump(by_alias=True, mode="json", exclude_none=True),
            "altitudeReference": "relativeToStartPoint",
        },
        "objectives": list(request.objectives),
        "policies": {
            "viewpointPolicyId": request.viewpoint_policy_id,
            "riskPolicyPackId": request.risk_policy_pack_id,
            "fallbackPolicyId": request.fallback_policy_id,
            "capturePolicyId": request.capture_policy_id,
            "coveragePolicy": {
                "mandatoryHazardCoverage": 1.0,
                "mandatoryAssetCoverage": 1.0,
                "accessibleGeneralCoverage": request.accessible_general_coverage,
            },
            "communicationLossPolicy": _COMMUNICATION_LOSS_POLICY.model_dump(
                by_alias=True, mode="json", exclude_none=True
            ),
            "batteryPolicy": _BATTERY_POLICY.model_dump(
                by_alias=True, mode="json", exclude_none=True
            ),
            "unknownObstaclePolicy": _UNKNOWN_OBSTACLE_POLICY.model_dump(
                by_alias=True, mode="json", exclude_none=True
            ),
            "evidencePolicy": _EVIDENCE_POLICY.model_dump(
                by_alias=True, mode="json", exclude_none=True
            ),
        },
        "artifacts": request.artifacts.model_dump(by_alias=True, mode="json", exclude_none=True),
    }
    signed = sign_contract(unsigned, private_key, key_id)
    return MissionContractV1_2.model_validate(signed)


def build_mission_issuance_router(*, private_key: Ed25519PrivateKey, key_id: str) -> APIRouter:
    router = APIRouter(prefix="/v1/missions", tags=["missions"])

    @router.post("/contracts", status_code=201)
    def issue_contract(request: MissionIssuanceRequest) -> dict[str, Any]:
        """구역+임무타입으로부터 서명된 MissionContract(v1.2)를 발급한다.

        안전 관련 정책 상수는 요청으로 지정할 수 없다 — 모듈 docstring 참조.
        """
        contract = issue_mission_contract(request, private_key=private_key, key_id=key_id)
        return contract.model_dump(by_alias=True, mode="json", exclude_none=True)

    return router


def mount_mission_issuance(app: FastAPI, *, private_key: Ed25519PrivateKey, key_id: str) -> None:
    """앱에 Mission Contract 발급 라우터를 장착한다."""
    app.include_router(build_mission_issuance_router(private_key=private_key, key_id=key_id))
