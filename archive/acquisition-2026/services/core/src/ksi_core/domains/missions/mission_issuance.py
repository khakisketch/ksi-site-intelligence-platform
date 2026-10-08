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

## 무인증 서명 오라클 — 구조적으로 제거 (ADR-KSI-008 §2/§3)

이 라우터는 인증(``MISSIONS_ISSUE``)·site 등록 대조(존재+siteFrame 일치+
임무타입×현장상태 게이트, INV-052)·mission_id 충돌 검사·durable 기록 성공
후에만 201 을 내는 경로 **하나만** 갖는다 — ``mission_store``와 공통
``issuance_committer``는 필수 인자라 인증·미기록 발급이나 prerequisite witness
검증 없는 조립 자체가 성립하지 않는다(원장 risk
mission-issuance-unauthenticated-signing-oracle 해소, "인증 없는 보호 표면은
존재할 수 없다"). ``ksi_core.app.create_app`` 은 서명키가 주어지면
``mission_store``·``site_store``·``auth_registry`` 를 함께 강제한다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from ksi_domain.enums import MissionType
from ksi_mission_contracts.models import (
    Artifacts,
    BatteryPolicy,
    CommunicationLossPolicy,
    EvidencePolicy,
    FlightEnvelope,
    MissionContractV1_2,
    MissionContractV1_3,
    SiteFrame,
    UnknownObstaclePolicy,
)
from ksi_mission_contracts.signing import canonical_payload_bytes, sha256_digest, sign_contract
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ksi_core.domains.missions.mission_atomicity import (
    MissionIssuanceCommitter,
    MissionIssuanceRejected,
)
from ksi_core.domains.missions.mission_records import (
    IssuanceAuthorizationWitness,
    IssuancePreconditionChangedError,
    MissionIssuanceSequenceStore,
    MissionRecord,
    MissionRecordVerdict,
    MissionStore,
    raise_for_mission_record_verdict,
    reject_lone_surrogates,
)
from ksi_core.foundation.durable_journal import JournalSealedError
from ksi_core.identity.auth import Permission, Principal, require_permission

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
    """구역+임무타입 발급 요청 — 사이트별로 실제 달라지는 값만 받는다.

    ``allow_inf_nan=False`` 는 심층 방어다(2026-08-18 재조사) — 현재 이 요청의 실수
    필드들은 전부 필드별 제약(범위·isfinite validator)으로 이미 막혀 있어 유출은
    없지만, 그건 설정이 아니라 필드별 규율에 기댄 방어라 **새 float 필드가 추가되는
    순간 열린다**. 설정으로 두면 잊을 자리가 없다.
    """

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, extra="forbid", allow_inf_nan=False
    )

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
    # 서명된 계약에는 실리지 않는다(MissionRecord.assigned_device_id 문서 참조) —
    # Core 가 INV-010 완료 판정에만 쓰는 운영 메타데이터다. 생략하면(None) 배정을
    # 신고하지 않은 것이고, 그 임무는 인증된 어느 EDGE_DEVICE 든 커버리지를 보고할
    # 수 있다(하위호환 — 기존 발급 흐름을 이 필드 도입이 깨지 않는다).
    assigned_device_id: str | None = Field(default=None, min_length=1)


def issue_mission_contract(
    request: MissionIssuanceRequest,
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
    issued_at: datetime | None = None,
    schema_version: Literal["1.2", "1.3"] = "1.2",
    issuer_id: str | None = None,
    site_sequence: int | None = None,
) -> MissionContractV1_2 | MissionContractV1_3:
    """서명된 MissionContract v1.2/v1.3을 만든다.

    v1.3의 issuer/sequence는 라우터가 Core 설정과 durable allocator에서만 공급한다.
    """
    now = issued_at if issued_at is not None else datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("issued_at 은 tz-aware 여야 한다")
    not_after = now + timedelta(hours=request.valid_for_hours)

    if schema_version == "1.3":
        if not issuer_id or site_sequence is None or site_sequence <= 0:
            raise ValueError("v1.3은 Core issuer_id와 양의 durable site_sequence가 필요하다")
    elif issuer_id is not None or site_sequence is not None:
        raise ValueError("v1.2에는 issuance 설정을 실을 수 없다")

    unsigned: dict[str, Any] = {
        "schemaVersion": schema_version,
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
    if schema_version == "1.3":
        unsigned["issuance"] = {
            "issuerId": issuer_id,
            "siteSequence": site_sequence,
            "issuedAt": now.isoformat(),
        }
    signed = sign_contract(unsigned, private_key, key_id)
    if schema_version == "1.3":
        return MissionContractV1_3.model_validate(signed)
    return MissionContractV1_2.model_validate(signed)


def build_mission_issuance_router(
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
    mission_store: MissionStore,
    issuance_committer: MissionIssuanceCommitter,
    writer_version: Literal["1.2", "1.3"] = "1.2",
    issuer_id: str | None = None,
    sequence_store: MissionIssuanceSequenceStore | None = None,
) -> APIRouter:
    if writer_version == "1.3" and (not issuer_id or sequence_store is None):
        raise ValueError("Mission Contract v1.3 writer는 issuer_id와 sequence_store가 필요하다")
    router = APIRouter(prefix="/v1/missions", tags=["missions"])

    @router.post("/contracts", status_code=201)
    def issue_contract_recorded(
        request: MissionIssuanceRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_ISSUE)),  # noqa: B008
    ) -> dict[str, Any]:
        """구역+임무타입으로부터 서명된 MissionContract(v1.2)를 발급·durable 기록한다.

        발급 레코드가 durable 기록되기 전에는 201 을 반환하지 않는다(ADR-KSI-008
        §3 — 고아 발급 금지). 요청 siteFrame 은 등록된 site 의 것과 정확히
        일치해야 한다(SITE_FRAME_MISMATCH — ADR-KSI-007 짝 무결성). 안전 관련
        정책 상수는 요청으로 지정할 수 없다(모듈 docstring 참조). lone surrogate
        문자열은 서명 정규화를 500 으로 깨뜨리므로 서명 전에 422 로 거부한다
        (재검토 P2 item④).
        """
        request_payload = request.model_dump(by_alias=True, mode="json", exclude_none=True)
        reject_lone_surrogates(request_payload)
        request_digest = sha256_digest(canonical_payload_bytes(request_payload))
        issued_at = datetime.now(UTC)
        precheck = issuance_committer.capture_site_authorization(
            organization_id=principal.organization_id,
            site_id=request.site_id,
            mission_id=request.mission_id,
            mission_type=request.mission_type,
            requested_site_frame=request.site_frame.model_dump(
                by_alias=True, mode="json", exclude_none=True
            ),
            request_digest=request_digest,
            captured_at=issued_at,
        )
        if isinstance(precheck, MissionRecordVerdict):
            if precheck is MissionRecordVerdict.MISSION_ID_CONFLICT:
                existing = mission_store.get_scoped(
                    request.mission_id, organization_id=principal.organization_id
                )
                if (
                    existing is not None
                    and existing.artifact_kind == "contract"
                    and existing.issuance_request_digest == request_digest
                ):
                    response.status_code = 200
                    return existing.contract
            raise_for_mission_record_verdict(precheck)
        assert isinstance(precheck, IssuanceAuthorizationWitness)  # noqa: S101
        witness = precheck
        try:
            witness = issuance_committer.attach_acquisition(witness, evaluated_at=issued_at)
        except MissionIssuanceRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        site_sequence: int | None = None
        if writer_version == "1.3":
            assert issuer_id is not None  # noqa: S101 -- 조립 시 검증
            assert sequence_store is not None  # noqa: S101 -- 조립 시 검증
            try:
                site_sequence = sequence_store.reserve(
                    issuer_id=issuer_id,
                    site_id=request.site_id,
                    reserved_at=issued_at,
                )
            except JournalSealedError as exc:
                raise HTTPException(status_code=503, detail="STORE_UNAVAILABLE") from exc
        contract = issue_mission_contract(
            request,
            private_key=private_key,
            key_id=key_id,
            issued_at=issued_at,
            schema_version=writer_version,
            issuer_id=issuer_id,
            site_sequence=site_sequence,
        )
        contract_payload = contract.model_dump(by_alias=True, mode="json", exclude_none=True)

        record = MissionRecord(
            mission_id=request.mission_id,
            site_id=request.site_id,
            mission_type=request.mission_type.value,
            artifact_kind="contract",
            contract=contract_payload,
            kmz_sha256=None,
            route_pattern=None,
            waypoint_count=None,
            planned_coverage_ratio=None,
            issued_at=issued_at,
            issued_by=principal.principal_id,
            organization_id=principal.organization_id,
            assigned_device_id=request.assigned_device_id,
            issuance_schema_version="1.0",
            issuance_request_digest=request_digest,
            authorization_witness=witness,
        )
        try:
            verdict = issuance_committer.commit(record, witness)
        except IssuancePreconditionChangedError as exc:
            existing = mission_store.get_scoped(
                request.mission_id, organization_id=principal.organization_id
            )
            if (
                existing is not None
                and existing.artifact_kind == "contract"
                and existing.issuance_request_digest == request_digest
            ):
                response.status_code = 200
                return existing.contract
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if verdict is MissionRecordVerdict.MISSION_ID_CONFLICT:
            existing = mission_store.get_scoped(
                request.mission_id, organization_id=principal.organization_id
            )
            if (
                existing is not None
                and existing.artifact_kind == "contract"
                and existing.issuance_request_digest == request_digest
            ):
                response.status_code = 200
                return existing.contract
        raise_for_mission_record_verdict(verdict)
        return contract_payload

    return router


def mount_mission_issuance(
    app: FastAPI,
    *,
    private_key: Ed25519PrivateKey,
    key_id: str,
    mission_store: MissionStore,
    issuance_committer: MissionIssuanceCommitter,
    writer_version: Literal["1.2", "1.3"] = "1.2",
    issuer_id: str | None = None,
    sequence_store: MissionIssuanceSequenceStore | None = None,
) -> None:
    """앱에 Mission Contract 발급 라우터를 장착한다.

    인증·site 등록 대조(존재+siteFrame 일치+임무타입×현장상태 게이트, INV-052)·
    durable 기록이 강제되는 경로 하나뿐이다(ADR-KSI-008 §3 — 무인증·미기록
    발급이 가능한 조립은 성립하지 않는다).
    """
    app.include_router(
        build_mission_issuance_router(
            private_key=private_key,
            key_id=key_id,
            mission_store=mission_store,
            issuance_committer=issuance_committer,
            writer_version=writer_version,
            issuer_id=issuer_id,
            sequence_store=sequence_store,
        )
    )
