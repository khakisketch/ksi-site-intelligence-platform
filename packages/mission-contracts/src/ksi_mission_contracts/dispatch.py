"""서명된 MissionDispatchEnvelope v1.0/v1.1 검증 경계.

Mission Contract v1.2의 wire 형식은 변경하지 않는다. Core가 장비 ID, 내부 계약
digest, RiskPolicyPack digest, 더 짧거나 같은 TTL을 하나의 Ed25519 서명으로 묶고,
Edge는 이 모듈의 단일 진입점으로 구조·양쪽 digest·양쪽 서명·모든 TTL을 함께
검증한다. 어느 하나라도 실패하면 activation은 불가하다.

## v1.1 — ``kmzSha256`` (ADR-KSI-007 짝 불변식의 첫 기계 검증)

v1.1은 v1.0에 ``kmzSha256`` 하나를 더한다. Core는 발급 원장의 값을 그대로 실어
서명하고, Edge는 따로 내려받은 KMZ 바이트의 sha256이 이 값과 다르면
:class:`DispatchVerdict.KMZ_DIGEST_MISMATCH` 로 **활성화 전체를 거부**한다
(``edge_activation`` 이 그 강제 지점). 바이트가 아니라 digest를 싣는 이유는 봉투가
저널과 1MB 응답 상한 안에 남아야 하기 때문이다.

## 왜 두 버전을 함께 받는가 (v1.0을 거부하지 않는다)

봉투는 TTL 5분짜리 일회성 기록이지만 **dispatch journal은 append-only라 재생 시
과거 봉투 전부를 다시 통과시킨다**(``EdgeDispatchStore._replay`` — 설명할 수 없는
레코드는 Core 기동 자체를 멈춘다). 리터럴을 "1.1" 하나로 좁히면 이미 v1.0 레코드가
쌓인 저널을 가진 Core가 **기동하지 못한다** — 안전과 무관한 이유로 발화하는
fail-closed는 정확히 이 저장소가 피하려는 종류의 실패다.

대신 **발행은 언제나 v1.1**이고(:func:`build_mission_dispatch_envelope`), v1.0은
"kmzSha256 필드가 아예 없는 봉투"로만 유효하다.

그리고 **한 번 서명된 봉투를 이 모델로 재직렬화해 다시 내보내지 않는다.** pydantic
기본 직렬화는 v1.0 봉투에 ``"kmzSha256": null`` 키를 새로 만들고, 서명 대상은 필드
집합이 아니라 정규화된 바이트열이라(ADR-KSI-002 §2) 그 순간 봉투가 자기 서명을
통과하지 못한다. 이건 이 모델이 ``missionContract`` 를 원문 dict 그대로 보존하는
것과 정확히 같은 이유다 — 저장·전달은 원문 dict 로 하고, 모델은 그 원문을 검증하는
데 쓴다(``EdgeDispatchStore._replay`` 와 ``GET /v1/edge-sync/missions/next``).

## sunset — v1.0 수용 범위가 계획보다 넓다 (독립 재검토 2026-08)

원래 의도는 "v1.0은 ``EdgeDispatchStore._replay`` 가 과거 저널 레코드를 설명하기
위해서만 받는다"였다. 그런데 ``schema_version: Literal["1.0", "1.1"]`` 이 모델
필드라 :func:`verify_mission_dispatch_envelope`(Edge의 활성화-시점 wire 검증,
``edge_activation.py``/``edge_dispatch_sync.py`` 가 호출)도 같이 넓어졌다 — Core
개인키로 서명된 v1.0 봉투 하나가 KMZ 결속(ADR-KSI-007)을 건너뛰고 활성화 시 기존
KMZ 를 지우게 만들 수 있다는 뜻이다. TTL 5분 + Core 개인키 서명 필요라 실효 위험은
낮게 평가했다(``_replay`` 쪽 수용은 append-only 저널이 과거 발행분을 다시 통과시켜야
하므로 필연적이지만, wire 검증 쪽은 그렇지 않다). ``verify_mission_dispatch_envelope``
를 v1.1 전용으로 좁히려면 이 모델과 별개로 "구조 검증만 하는 v1.0/v1.1 겸용 모델"과
"서명까지 검증하는 v1.1 전용 모델"을 나눠야 해서 이번 재검토 범위를 넘겼다 — 아직
좁히지 못했다는 사실 자체를 여기 남긴다. v1.1 이 완전히 자리잡아 배포된 모든 Core의
dispatch journal 에서 v1.0 레코드가 TTL 을 넘겨 자연 소멸하면(장비가 재시작 없이도
그 시점 이후로는 이 관용을 더 필요로 하지 않으면) 이 sunset 문단과 함께 v1.0 수용
자체를 제거한다.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from ksi_mission_contracts.models import Ed25519Signature, MissionContractV1_2
from ksi_mission_contracts.risk_policy import RiskPolicyPackV1, risk_policy_pack_digest
from ksi_mission_contracts.runtime_profile import (
    EdgeRuntimeProfileV1,
    edge_runtime_profile_digest,
    edge_runtime_profile_wire_dict,
)
from ksi_mission_contracts.signing import (
    KeyRegistry,
    SignatureVerdict,
    canonical_payload_bytes,
    load_verified_contract,
    sha256_digest,
    sign_contract,
    verify_contract,
)

_PATH_SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
# ``MissionRecord.kmz_sha256`` 과 같은 bare hex 표기(모델 필드 주석 참조).
_KMZ_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class DispatchValidity(_CamelModel):
    not_before: AwareDatetime
    not_after: AwareDatetime

    @model_validator(mode="after")
    def _ordered(self) -> DispatchValidity:
        if self.not_after <= self.not_before:
            raise ValueError("validity.notAfter 는 validity.notBefore 보다 뒤여야 한다")
        return self


class MissionDispatchEnvelopeV1(_CamelModel):
    """``mission-dispatch-envelope.v1.{0,1}.json`` wire 모델(모듈 docstring 참조)."""

    # sunset: "1.0" 은 원래 EdgeDispatchStore._replay 의 과거 저널 레코드 재생
    # 전용으로만 의도했지만, 이 필드가 verify_mission_dispatch_envelope(Edge wire
    # 검증)와 공유돼 그쪽도 함께 넓어졌다 — 아직 좁히지 못했다(모듈 docstring
    # "sunset — v1.0 수용 범위가 계획보다 넓다" 참조).
    schema_version: Literal["1.0", "1.1"] = "1.1"
    dispatch_id: str = Field(pattern=_PATH_SAFE_ID)
    edge_device_id: str = Field(pattern=_PATH_SAFE_ID)
    mission_id: str = Field(min_length=1)
    # 내부 Mission Contract는 **원문 dict 그대로** 보존한다. Pydantic nested model로
    # dump하면 optional None 필드가 새로 생겨 기존 Ed25519 서명 대상이 바뀌므로,
    # 구조 검증은 validator에서 하되 wire 표현은 정상화하지 않는다.
    mission_contract: dict[str, Any]
    mission_contract_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    risk_policy_pack: dict[str, Any]
    risk_policy_pack_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    # The Mission Contract intentionally keeps only artifact identifiers. This
    # signed outer profile carries the concrete model/calibration deployment
    # inputs and is required even when an older capture-only DPK cannot use it.
    edge_runtime_profile: dict[str, Any]
    edge_runtime_profile_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    # v1.1 전용. bare hex 인 것은 의도적이다 — 정본이 Core 발급 원장의
    # ``MissionRecord.kmz_sha256`` 이고 그 표기를 그대로 옮긴다. ``None`` 은
    # "아직 모른다"가 아니라 "이 임무에는 KMZ 가 없다"(계약 단독 발급)는 확정
    # 사실이고, Edge 는 그때 남아 있던 이전 KMZ 를 **지운다**.
    kmz_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    validity: DispatchValidity
    signature: Ed25519Signature

    @model_validator(mode="after")
    def _cross_bindings(self) -> MissionDispatchEnvelopeV1:
        # 버전과 필드 존재는 **양방향**으로 묶는다. v1.1 에서 키를 떨어뜨리는
        # 것만으로 KMZ 대조를 조용히 건너뛸 수 있으면 이 필드는 보증이 아니라
        # 장식이다(그래서 default 가 있어도 "명시되지 않은 v1.1" 은 거부한다).
        declared = "kmz_sha256" in self.model_fields_set
        if self.schema_version == "1.1" and not declared:
            raise ValueError("v1.1 봉투는 kmzSha256 을 반드시 선언해야 한다(null 도 선언이다)")
        if self.schema_version == "1.0" and declared:
            raise ValueError("v1.0 봉투에는 kmzSha256 자리가 없다 — schemaVersion 을 1.1 로 올려라")
        contract = MissionContractV1_2.model_validate(self.mission_contract)
        pack = RiskPolicyPackV1.model_validate(self.risk_policy_pack)
        profile = EdgeRuntimeProfileV1.model_validate(self.edge_runtime_profile)
        if self.mission_id != contract.mission_id:
            raise ValueError("missionId 가 missionContract.missionId 와 다르다")
        if pack.risk_policy_pack_id != contract.policies.risk_policy_pack_id:
            raise ValueError("riskPolicyPackId 가 Mission Contract 정책 참조와 다르다")
        if contract.artifacts.calibration_profile_id != pack.calibration_profile_id:
            raise ValueError("RiskPolicyPack calibrationProfileId가 Mission Contract와 다르다")
        _validate_runtime_bindings(contract, pack, profile)
        return self


class ActivationReceiptV1(_CamelModel):
    """Edge가 Core에 기록을 요청하는 activation 사실. 확정 event가 아니다."""

    schema_version: Literal["1.0"] = "1.0"
    dispatch_id: str = Field(pattern=_PATH_SAFE_ID)
    edge_device_id: str = Field(pattern=_PATH_SAFE_ID)
    mission_id: str = Field(min_length=1)
    mission_contract_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    risk_policy_pack_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    activated_at: AwareDatetime
    runtime_version: str = Field(min_length=1)


class DispatchVerdict(StrEnum):
    VALID = "VALID"
    MALFORMED_DISPATCH = "MALFORMED_DISPATCH"
    INVALID_DISPATCH_SIGNATURE = "INVALID_DISPATCH_SIGNATURE"
    UNKNOWN_DISPATCH_KEY = "UNKNOWN_DISPATCH_KEY"
    REVOKED_DISPATCH_KEY = "REVOKED_DISPATCH_KEY"
    DISPATCH_KEY_EXPIRED = "DISPATCH_KEY_EXPIRED"
    DISPATCH_TTL_EXPIRED = "DISPATCH_TTL_EXPIRED"
    MISSION_CONTRACT_INVALID = "MISSION_CONTRACT_INVALID"
    MISSION_CONTRACT_DIGEST_MISMATCH = "MISSION_CONTRACT_DIGEST_MISMATCH"
    RISK_POLICY_PACK_DIGEST_MISMATCH = "RISK_POLICY_PACK_DIGEST_MISMATCH"
    RISK_POLICY_PACK_EXPIRED = "RISK_POLICY_PACK_EXPIRED"
    EDGE_RUNTIME_PROFILE_DIGEST_MISMATCH = "EDGE_RUNTIME_PROFILE_DIGEST_MISMATCH"
    EDGE_RUNTIME_PROFILE_EXPIRED = "EDGE_RUNTIME_PROFILE_EXPIRED"
    VALIDITY_OUTSIDE_CONTRACT = "VALIDITY_OUTSIDE_CONTRACT"
    DEVICE_MISMATCH = "DEVICE_MISMATCH"
    # Activation-layer refusals (edge_activation.py), reusing this enum the same
    # way MISSION_CONTRACT_INVALID already does — "signature is real, but this
    # local device won't load it now" is a different question than envelope
    # verification, but the two verdict spaces are deliberately not split
    # (single result type for the whole activate_mission_dispatch_file call).
    # Mirrors ActivationRefusal.SUPERSEDED_CONTRACT (consumer.py) on the two
    # dispatch-only axes it cannot see (risk-2026-08-14
    # riskpolicypack-edgeruntimeprofile-no-rollback-defense).
    SUPERSEDED_RISK_POLICY_PACK = "SUPERSEDED_RISK_POLICY_PACK"
    SUPERSEDED_EDGE_RUNTIME_PROFILE = "SUPERSEDED_EDGE_RUNTIME_PROFILE"
    # 위 둘은 **같은 missionId 안에서만** 비교한다. 임무를 갈아 끼우면 비교 축이
    # 사라져 가드가 아예 돌지 않았다(risk
    # rollback-guard-fail-open-and-mission-id-laundering). 봉투의 notBefore 는
    # 서버가 dispatch 를 내보내는 순간 각인하므로 임무와 무관한 순서 근거다 —
    # 이 판정은 그것으로 기체 전체 고수위를 강제한다.
    SUPERSEDED_DISPATCH = "SUPERSEDED_DISPATCH"
    # KMZ 는 서명이 없다 — 그래서 "서명된 봉투가 선언한 digest"가 그 파일의 유일한
    # 진위 근거다. 받은 바이트가 그 digest 와 다르거나(전송 손상·중간자·구 임무
    # 잔존), digest 를 선언한 봉투인데 바이트를 전혀 못 받았으면 활성화 **전체**를
    # 거부한다 — 계약만 활성화하고 경로는 낡은 것을 남기는 것이 정확히 ADR-KSI-007
    # 이 막으려던 상태(짝이 어긋난 산출물 쌍)다.
    KMZ_DIGEST_MISMATCH = "KMZ_DIGEST_MISMATCH"


@dataclass(frozen=True, slots=True)
class DispatchVerificationResult:
    verdict: DispatchVerdict
    envelope: MissionDispatchEnvelopeV1 | None = None
    detail: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.verdict is DispatchVerdict.VALID and self.envelope is not None


def mission_contract_digest(contract: Mapping[str, Any]) -> str:
    """Mission Contract v1.2의 signature 제외 canonical digest."""
    return sha256_digest(canonical_payload_bytes(contract))


def _wire(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json")


def _contract_time(value: str) -> datetime:
    """Mission Contract 모델이 보존하는 RFC3339 문자열을 aware datetime으로 바꾼다."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:  # model validator가 막지만 방어적으로 fail-closed 유지
        raise ValueError("Mission Contract validity가 tz-aware가 아니다")
    return parsed


def _validate_runtime_bindings(
    contract: MissionContractV1_2,
    pack: RiskPolicyPackV1,
    profile: EdgeRuntimeProfileV1,
) -> None:
    """Reject every path that lets deployment inputs drift from the signed mission.

    The runtime profile is intentionally not a mutable device preference. It
    must describe the same site/model/calibration frame named by the inner
    contract and the same canonical equipment vocabulary admitted by policy.
    """
    if contract.site_id != profile.site_id:
        raise ValueError("edgeRuntimeProfile.siteId가 Mission Contract와 다르다")
    if contract.artifacts.model_pack_id != profile.model.model_pack_id:
        raise ValueError("edgeRuntimeProfile modelPackId가 Mission Contract와 다르다")
    if contract.artifacts.calibration_profile_id != profile.calibration.calibration_profile_id:
        raise ValueError("edgeRuntimeProfile calibrationProfileId가 Mission Contract와 다르다")
    if pack.calibration_profile_id != profile.calibration.calibration_profile_id:
        raise ValueError("edgeRuntimeProfile calibrationProfileId가 RiskPolicyPack과 다르다")
    if contract.site_frame != profile.calibration.site_frame:
        raise ValueError("edgeRuntimeProfile siteFrame이 Mission Contract와 다르다")
    allowed_equipment = {policy.equipment_class for policy in pack.equipment_policies}
    for binding in profile.model.class_bindings:
        if binding.equipment_class not in allowed_equipment:
            raise ValueError("edgeRuntimeProfile class binding is not admitted by RiskPolicyPack")


def build_mission_dispatch_envelope(
    *,
    dispatch_id: str,
    edge_device_id: str,
    mission_contract: Mapping[str, Any],
    risk_policy_pack: RiskPolicyPackV1 | Mapping[str, Any],
    edge_runtime_profile: EdgeRuntimeProfileV1 | Mapping[str, Any],
    validity: DispatchValidity,
    private_key: Ed25519PrivateKey,
    key_id: str,
    kmz_sha256: str | None = None,
) -> MissionDispatchEnvelopeV1:
    """Core 전용 발행기. 모든 inner binding을 구성 시점에도 typed로 확인한다.

    ``kmz_sha256`` 은 발급 원장(``MissionRecord.kmz_sha256``)의 값을 그대로 받는다 —
    이 함수는 KMZ 를 다시 만들거나 해싱하지 않는다. ``None`` 은 계약 단독 발급이라는
    확정 사실이고, 발행되는 봉투는 **언제나 v1.1** 이라 그 사실이 서명 안에 실린다
    (모듈 docstring "왜 두 버전을 함께 받는가").
    """
    contract_model = MissionContractV1_2.model_validate(dict(mission_contract))
    pack_model = (
        risk_policy_pack
        if isinstance(risk_policy_pack, RiskPolicyPackV1)
        else RiskPolicyPackV1.model_validate(dict(risk_policy_pack))
    )
    profile_model = (
        edge_runtime_profile
        if isinstance(edge_runtime_profile, EdgeRuntimeProfileV1)
        else EdgeRuntimeProfileV1.model_validate(dict(edge_runtime_profile))
    )
    _validate_runtime_bindings(contract_model, pack_model, profile_model)
    contract_wire = dict(mission_contract)
    pack_wire = _wire(pack_model)
    profile_wire = edge_runtime_profile_wire_dict(profile_model)
    contract_not_before = _contract_time(contract_model.validity.not_before)
    contract_not_after = _contract_time(contract_model.validity.not_after)
    if (
        validity.not_before < contract_not_before
        or validity.not_after > contract_not_after
        or validity.not_before < pack_model.validity.not_before
        or validity.not_after > pack_model.validity.not_after
        or validity.not_before < profile_model.validity.not_before
        or validity.not_after > profile_model.validity.not_after
    ):
        raise ValueError(
            "dispatch validity는 Mission Contract/RiskPolicyPack/"
            "EdgeRuntimeProfile validity 안에 있어야 한다"
        )
    if kmz_sha256 is not None and not _KMZ_SHA256_RE.fullmatch(kmz_sha256):
        raise ValueError("kmzSha256 은 소문자 64자리 hex 여야 한다")
    unsigned = {
        "schemaVersion": "1.1",
        "dispatchId": dispatch_id,
        "edgeDeviceId": edge_device_id,
        "missionId": contract_model.mission_id,
        "missionContract": contract_wire,
        "missionContractDigest": mission_contract_digest(contract_wire),
        "riskPolicyPack": pack_wire,
        "riskPolicyPackDigest": risk_policy_pack_digest(pack_wire),
        "edgeRuntimeProfile": profile_wire,
        "edgeRuntimeProfileDigest": edge_runtime_profile_digest(profile_wire),
        "kmzSha256": kmz_sha256,
        "validity": _wire(validity),
    }
    return MissionDispatchEnvelopeV1.model_validate(sign_contract(unsigned, private_key, key_id))


def kmz_bytes_match_envelope(
    envelope: MissionDispatchEnvelopeV1, kmz_bytes: bytes | None
) -> bool:
    """받은 KMZ 바이트가 서명된 봉투가 선언한 것인가 — 판정 하나를 한 곳에만 둔다.

    네 경우가 전부다:

    - digest 선언 없음(계약 단독) + 바이트 없음 → 참(정상. 기존 KMZ 는 지워진다)
    - digest 선언 없음 + 바이트 있음 → **거짓**. 서명이 "이 임무엔 KMZ 가 없다"고
      말하는데 파일이 하나 있으면 그 파일의 출처를 설명하는 서명이 없다.
    - digest 선언 + 바이트 없음 → 거짓(못 받은 것과 안 받아도 되는 것은 다르다)
    - digest 선언 + 바이트 있음 → sha256 이 정확히 같을 때만 참

    비교는 :func:`hmac.compare_digest` 로 한다. 타이밍이 여기서 비밀을 새게 하는
    현실적 경로는 없지만, digest 비교의 기본형을 이 저장소 안에서 하나로 둔다.
    """
    if envelope.kmz_sha256 is None:
        return kmz_bytes is None
    if kmz_bytes is None:
        return False
    return hmac.compare_digest(hashlib.sha256(kmz_bytes).hexdigest(), envelope.kmz_sha256)


def _outer_verdict(verdict: SignatureVerdict) -> DispatchVerdict:
    return {
        SignatureVerdict.INVALID_SIGNATURE: DispatchVerdict.INVALID_DISPATCH_SIGNATURE,
        SignatureVerdict.UNKNOWN_KEY: DispatchVerdict.UNKNOWN_DISPATCH_KEY,
        SignatureVerdict.REVOKED_KEY: DispatchVerdict.REVOKED_DISPATCH_KEY,
        SignatureVerdict.KEY_EXPIRED: DispatchVerdict.DISPATCH_KEY_EXPIRED,
        SignatureVerdict.EXPIRED_CONTRACT: DispatchVerdict.DISPATCH_TTL_EXPIRED,
    }.get(verdict, DispatchVerdict.MALFORMED_DISPATCH)


def verify_mission_dispatch_envelope(
    data: Mapping[str, Any],
    registry: KeyRegistry,
    *,
    expected_edge_device_id: str | None = None,
    now: datetime | None = None,
) -> DispatchVerificationResult:
    """구조·outer 서명·inner 계약·양쪽 digest·TTL·장비 binding을 fail-closed 검증한다."""
    try:
        raw = dict(data)
        envelope = MissionDispatchEnvelopeV1.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 -- 모든 untrusted wire 입력은 typed 거부
        return DispatchVerificationResult(DispatchVerdict.MALFORMED_DISPATCH, detail=str(exc))

    # 버전은 모델이 이미 {"1.0","1.1"} 로 좁혔다 — 여기서 그 값을 그대로 쓰는 것은
    # 신뢰가 아니라 이미 통과한 검증의 재사용이다(임의 문자열은 위에서 걸린다).
    outer = verify_contract(
        raw, registry, expected_schema_version=envelope.schema_version, now=now
    )
    if not outer.is_valid:
        return DispatchVerificationResult(_outer_verdict(outer.verdict), detail=outer.detail)

    raw_contract = raw.get("missionContract")
    raw_pack = raw.get("riskPolicyPack")
    raw_profile = raw.get("edgeRuntimeProfile")
    if (
        not isinstance(raw_contract, Mapping)
        or not isinstance(raw_pack, Mapping)
        or not isinstance(raw_profile, Mapping)
    ):
        return DispatchVerificationResult(DispatchVerdict.MALFORMED_DISPATCH)
    try:
        actual_contract_digest = mission_contract_digest(raw_contract)
    except (TypeError, ValueError) as exc:
        return DispatchVerificationResult(DispatchVerdict.MALFORMED_DISPATCH, detail=str(exc))
    if actual_contract_digest != envelope.mission_contract_digest:
        return DispatchVerificationResult(DispatchVerdict.MISSION_CONTRACT_DIGEST_MISMATCH)
    try:
        actual_pack_digest = risk_policy_pack_digest(raw_pack)
    except (TypeError, ValueError) as exc:
        return DispatchVerificationResult(DispatchVerdict.MALFORMED_DISPATCH, detail=str(exc))
    if actual_pack_digest != envelope.risk_policy_pack_digest:
        return DispatchVerificationResult(DispatchVerdict.RISK_POLICY_PACK_DIGEST_MISMATCH)
    try:
        actual_profile_digest = edge_runtime_profile_digest(raw_profile)
    except (TypeError, ValueError) as exc:
        return DispatchVerificationResult(DispatchVerdict.MALFORMED_DISPATCH, detail=str(exc))
    if actual_profile_digest != envelope.edge_runtime_profile_digest:
        return DispatchVerificationResult(DispatchVerdict.EDGE_RUNTIME_PROFILE_DIGEST_MISMATCH)

    loaded_contract = load_verified_contract(raw_contract, registry, now=now)
    if not loaded_contract.is_valid or loaded_contract.model is None:
        return DispatchVerificationResult(
            DispatchVerdict.MISSION_CONTRACT_INVALID, detail=loaded_contract.detail
        )

    effective_now = now if now is not None else datetime.now(UTC)
    if effective_now.tzinfo is None:
        return DispatchVerificationResult(
            DispatchVerdict.MALFORMED_DISPATCH, detail="now는 tz-aware여야 한다"
        )
    inner_contract = loaded_contract.model
    inner_not_before = _contract_time(inner_contract.validity.not_before)
    inner_not_after = _contract_time(inner_contract.validity.not_after)
    pack_model = RiskPolicyPackV1.model_validate(raw_pack)
    profile_model = EdgeRuntimeProfileV1.model_validate(raw_profile)
    policy_validity = pack_model.validity
    if (
        envelope.validity.not_before < inner_not_before
        or envelope.validity.not_after > inner_not_after
        or envelope.validity.not_before < policy_validity.not_before
        or envelope.validity.not_after > policy_validity.not_after
        or envelope.validity.not_before < profile_model.validity.not_before
        or envelope.validity.not_after > profile_model.validity.not_after
    ):
        return DispatchVerificationResult(DispatchVerdict.VALIDITY_OUTSIDE_CONTRACT)
    if not (policy_validity.not_before <= effective_now <= policy_validity.not_after):
        return DispatchVerificationResult(DispatchVerdict.RISK_POLICY_PACK_EXPIRED)
    if not (profile_model.validity.not_before <= effective_now <= profile_model.validity.not_after):
        return DispatchVerificationResult(DispatchVerdict.EDGE_RUNTIME_PROFILE_EXPIRED)
    if expected_edge_device_id is not None and envelope.edge_device_id != expected_edge_device_id:
        return DispatchVerificationResult(DispatchVerdict.DEVICE_MISMATCH)
    return DispatchVerificationResult(DispatchVerdict.VALID, envelope=envelope)


__all__ = [
    "ActivationReceiptV1",
    "DispatchValidity",
    "DispatchVerdict",
    "DispatchVerificationResult",
    "MissionDispatchEnvelopeV1",
    "build_mission_dispatch_envelope",
    "kmz_bytes_match_envelope",
    "mission_contract_digest",
    "verify_mission_dispatch_envelope",
]
