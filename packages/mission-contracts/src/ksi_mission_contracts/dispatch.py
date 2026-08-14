"""서명된 MissionDispatchEnvelope v1.0 검증 경계.

Mission Contract v1.2의 wire 형식은 변경하지 않는다. Core가 장비 ID, 내부 계약
digest, RiskPolicyPack digest, 더 짧거나 같은 TTL을 하나의 Ed25519 서명으로 묶고,
Edge는 이 모듈의 단일 진입점으로 구조·양쪽 digest·양쪽 서명·모든 TTL을 함께
검증한다. 어느 하나라도 실패하면 activation은 불가하다.
"""

from __future__ import annotations

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
    """``mission-dispatch-envelope.v1.json`` wire 모델."""

    schema_version: Literal["1.0"] = "1.0"
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
    validity: DispatchValidity
    signature: Ed25519Signature

    @model_validator(mode="after")
    def _cross_bindings(self) -> MissionDispatchEnvelopeV1:
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
) -> MissionDispatchEnvelopeV1:
    """Core 전용 발행기. 모든 inner binding을 구성 시점에도 typed로 확인한다."""
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
    unsigned = {
        "schemaVersion": "1.0",
        "dispatchId": dispatch_id,
        "edgeDeviceId": edge_device_id,
        "missionId": contract_model.mission_id,
        "missionContract": contract_wire,
        "missionContractDigest": mission_contract_digest(contract_wire),
        "riskPolicyPack": pack_wire,
        "riskPolicyPackDigest": risk_policy_pack_digest(pack_wire),
        "edgeRuntimeProfile": profile_wire,
        "edgeRuntimeProfileDigest": edge_runtime_profile_digest(profile_wire),
        "validity": _wire(validity),
    }
    return MissionDispatchEnvelopeV1.model_validate(sign_contract(unsigned, private_key, key_id))


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

    outer = verify_contract(raw, registry, expected_schema_version="1.0", now=now)
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
    "mission_contract_digest",
    "verify_mission_dispatch_envelope",
]
