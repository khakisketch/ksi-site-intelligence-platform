"""Edge RiskPolicyPack v1.0 계약.

정책 pack은 Mission Contract 안의 ``riskPolicyPackId``가 가리키는 구체적이고
버전 고정된 입력이다. 등록되지 않은 장비나 누락된 형상·불확실성 값에 대해
runtime이 임의 기본값을 만들지 않도록 필요한 값을 모두 required로 둔다.
서명은 이 pack 자체가 아니라 이를 포함한 MissionDispatchEnvelope가 담당한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from ksi_mission_contracts.signing import sha256_digest


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class PolicyValidity(_CamelModel):
    not_before: AwareDatetime
    not_after: AwareDatetime

    @model_validator(mode="after")
    def _ordered(self) -> PolicyValidity:
        if self.not_after <= self.not_before:
            raise ValueError("validity.notAfter 는 validity.notBefore 보다 뒤여야 한다")
        return self


class EquipmentFootprint(_CamelModel):
    length_m: float = Field(gt=0)
    width_m: float = Field(gt=0)
    height_m: float = Field(ge=0)


class PredictionParameters(_CamelModel):
    horizon_seconds: float = Field(gt=0)
    sample_period_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def _sample_fits_horizon(self) -> PredictionParameters:
        if self.sample_period_seconds > self.horizon_seconds:
            raise ValueError("prediction.samplePeriodSeconds 는 horizonSeconds 이하이어야 한다")
        return self


class EquipmentRiskPolicy(_CamelModel):
    equipment_class: str = Field(min_length=1)
    risk_field_policy_id: str = Field(min_length=1)
    footprint: EquipmentFootprint
    prediction: PredictionParameters
    covariance_sigma_multiplier: float = Field(ge=0)
    occlusion_expansion_m: float = Field(ge=0)
    severity: float = Field(ge=0, le=1)


class RiskPolicyPackV1(_CamelModel):
    """``contracts/schemas/risk-policy-pack.v1.json`` 대응 모델."""

    schema_version: Literal["1.0"] = "1.0"
    risk_policy_pack_id: str = Field(min_length=1)
    validity: PolicyValidity
    calibration_profile_id: str = Field(min_length=1)
    equipment_policies: list[EquipmentRiskPolicy] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_classes(self) -> RiskPolicyPackV1:
        classes = [policy.equipment_class for policy in self.equipment_policies]
        if len(classes) != len(set(classes)):
            raise ValueError("equipmentPolicies.equipmentClass 는 pack 안에서 유일해야 한다")
        return self


def risk_policy_pack_wire_dict(pack: RiskPolicyPackV1) -> dict[str, Any]:
    """wire 계약에 맞춘 canonicalizable JSON dict를 반환한다."""
    return pack.model_dump(by_alias=True, mode="json")


def risk_policy_pack_digest(pack: RiskPolicyPackV1 | Mapping[str, Any]) -> str:
    """pack 전체의 SHA-256 digest (서명 envelope가 바인딩하는 값)."""
    if isinstance(pack, RiskPolicyPackV1):
        payload: Mapping[str, Any] = risk_policy_pack_wire_dict(pack)
    else:
        payload = pack
    return sha256_digest(canonical_json_bytes(payload))


__all__ = [
    "EquipmentFootprint",
    "EquipmentRiskPolicy",
    "PolicyValidity",
    "PredictionParameters",
    "RiskPolicyPackV1",
    "risk_policy_pack_digest",
    "risk_policy_pack_wire_dict",
]
