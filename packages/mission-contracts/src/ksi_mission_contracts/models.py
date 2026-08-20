"""MissionContract Pydantic v2 모델 (contracts/schemas/mission-contract.v1.1/v1.2.json SSOT).

camelCase 표현(``alias_generator=to_camel``, ``populate_by_name=True``)이며
``model_config`` ``extra="forbid"``로 스키마 밖 필드를 거부한다. 스키마의 ``const``
필드는 ``Literal``로 좁혀 타입 단계에서 위반을 막는다.

v1.1(``signature={algorithm, digest}``)·v1.2(``signature={algorithm, keyId, digest,
signature}`` — ADR-KSI-002 §4 Ed25519 서명)를 모두 표현하기 위해 signature 모델을
분리하고, 두 스키마 버전을 별도 concrete 모델(``MissionContractV1_1``/
``MissionContractV1_2``)로 둔다.

참고(감사 #70): 중첩 모델(_CamelModel 공통 ``extra="forbid"``)은 v1.1/v1.2 가
공유하므로 **v1.1 모델은 v1.1 JSON 스키마보다 엄격하다**(v1.1 스키마는 중첩
객체에 additionalProperties 를 명시하지 않는다). 이는 의도된 앞당김 강화다 —
더 관대해지는 방향의 불일치가 아니므로 나쁜 데이터를 통과시키지 않는다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from ksi_domain.enums import MissionType
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    """camelCase alias·extra forbid 공통 베이스 (계약 모델 전용)."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class Validity(_CamelModel):
    """계약 TTL 창 — verify_contract가 이 창 밖의 계약을 EXPIRED_CONTRACT로 거부한다."""

    not_before: str
    not_after: str

    @field_validator("not_before", "not_after")
    @classmethod
    def _must_be_tz_aware_rfc3339(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("validity 타임스탬프는 tz-aware RFC3339여야 한다")
        return value


class SiteFrame(_CamelModel):
    """INV-020 — 모든 세계좌표는 CRS·수직기준·unit·transformVersion을 갖는다."""

    crs: str
    vertical_datum: str
    unit: Literal["meter"]
    transform_version: str


# 서버 고정 안전상수 — 요청으로 바꿀 수 없다(INV 계열 원칙). 값은 항공안전법의
# 일반 비행제한 고도이며 2026-08-05 대표자 확정이다. 이 값을 넘는 봉투는 서명
# 계약으로 성립하지 않는다 — "규제 위반 고도의 임무는 발급 자체가 안 된다".
#
# 예외 승인(고도 특례)을 받은 현장이 생기면 이 상수를 현장별 설정으로 바꾸는 게
# 아니라, **그 결정을 다시 받아** 여기를 고친다. 안전 상한을 요청·설정이 뚫을 수
# 있게 만드는 순간 "서버 고정"이라는 성질 자체가 사라진다.
_ABSOLUTE_MAX_ALTITUDE_M = 150.0


class FlightEnvelope(_CamelModel):
    """비행 봉투 — 교차 필드 검증(감사 #50): min>max·비유한·음수 봉투가 서명된
    계약으로 성립하면 Edge 가 그 값을 경계로 읽는 순간 해석이 정의되지 않는다.

    ``altitude_reference``: 고도(min/max)의 수직기준 — 2026-07-29 대표자 확정으로
    **이륙점 상대(relativeToStartPoint)** 단일값이다(자율 재검토 F1, INV-020 —
    수직기준이 다른 산출물끼리의 비교를 계약 레벨에서 봉인). optional 인 이유는
    기존 서명 계약의 하위호환뿐이며, 발급기는 항상 채운다.
    """

    allowed_volumes: list[str]
    excluded_volumes: list[str]
    min_altitude_m: float
    max_altitude_m: float
    minimum_structure_standoff_m: float | None = None
    minimum_person_standoff_m: float | None = None
    altitude_reference: Literal["relativeToStartPoint"] | None = None

    @model_validator(mode="after")
    def _envelope_is_coherent(self) -> FlightEnvelope:
        import math

        for name in ("min_altitude_m", "max_altitude_m"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} 는 finite 여야 한다")
        if self.min_altitude_m > self.max_altitude_m:
            raise ValueError(
                f"minAltitudeM({self.min_altitude_m}) > maxAltitudeM({self.max_altitude_m}) — "
                "역전된 고도 창은 봉투가 아니다"
            )
        if self.max_altitude_m > _ABSOLUTE_MAX_ALTITUDE_M:
            raise ValueError(
                f"maxAltitudeM({self.max_altitude_m}) > 규제 상한"
                f"({_ABSOLUTE_MAX_ALTITUDE_M}m — 항공안전법 일반 비행제한 고도, "
                "서버 고정 안전상수라 요청으로 바꿀 수 없다)"
            )
        for name in ("minimum_structure_standoff_m", "minimum_person_standoff_m"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{name} 는 비음수 finite 여야 한다 ({value!r})")
        return self


class CoveragePolicy(_CamelModel):
    """INV-010 — 필수 위험구역/자산 100%, 접근가능 일반영역 ≥95%."""

    mandatory_hazard_coverage: float
    mandatory_asset_coverage: float
    accessible_general_coverage: float = Field(ge=0.95, le=1.0)

    @field_validator("mandatory_hazard_coverage", "mandatory_asset_coverage")
    @classmethod
    def _must_be_exactly_one(cls, value: float) -> float:
        """스키마 ``const: 1.0``. mypy가 float Literal을 지원하지 않아 런타임 검증으로 강제."""
        if value != 1.0:
            raise ValueError("mandatoryHazardCoverage/mandatoryAssetCoverage는 1.0이어야 한다")
        return value


class CommunicationLossPolicy(_CamelModel):
    """INV-012 — 서버통신 단절 중에도 유효 계약+안전조건 유지 시에만 임무 계속."""

    server_link: Literal["CONTINUE_WHILE_CONTRACT_AND_SAFETY_VALID"]
    rc_command_link: Literal["DELEGATE_TO_DJI_FLIGHT_CONTROLLER"]


class BatteryPolicy(_CamelModel):
    """INV-013 — 배터리 귀환은 예상귀환 에너지 + 현장 Reserve(기본 30%)."""

    mode: Literal["RETURN_ENERGY_PLUS_RESERVE"]
    default_reserve_percent: float = Field(ge=0, le=100)
    site_override_allowed: Literal[True] | None = None


class UnknownObstaclePolicy(_CamelModel):
    initial_action: Literal["SLOW", "HOLD", "STOP"]
    unresolved_action: Literal["RETREAT", "DEFER_AREA", "PARTIAL_RESCAN", "RTH"]


class EvidencePolicy(_CamelModel):
    """INV-030 — Evidence Clip은 Candidate/High/Critical 전후 3/5/10초."""

    candidate_pre_post_seconds: Literal[3]
    high_pre_post_seconds: Literal[5]
    critical_pre_post_seconds: Literal[10]


class Policies(_CamelModel):
    viewpoint_policy_id: str
    risk_policy_pack_id: str
    fallback_policy_id: str
    capture_policy_id: str
    coverage_policy: CoveragePolicy
    communication_loss_policy: CommunicationLossPolicy
    battery_policy: BatteryPolicy
    unknown_obstacle_policy: UnknownObstaclePolicy
    evidence_policy: EvidencePolicy


class Artifacts(_CamelModel):
    world_model_manifest_id: str | None = None
    model_pack_id: str | None = None
    calibration_profile_id: str | None = None


class SignatureV1(_CamelModel):
    """v1.1 signature 블록 — 필드 존재만 표현(암호학적 검증 불가, ADR-KSI-002 맥락)."""

    algorithm: str
    digest: str


class Ed25519Signature(_CamelModel):
    """v1.2+ signature 블록 — ADR-KSI-002 §4 Ed25519 실서명."""

    algorithm: Literal["Ed25519"]
    key_id: str
    digest: str
    signature: str


class _MissionContractBase(_CamelModel):
    """schemaVersion·signature를 제외한 v1.1/v1.2 공통 필드."""

    mission_id: str
    site_id: str
    mission_type: MissionType
    validity: Validity
    site_frame: SiteFrame
    flight_envelope: FlightEnvelope
    objectives: list[str]
    policies: Policies
    artifacts: Artifacts


class IssuanceV1_3(_CamelModel):  # noqa: N801 (스키마 버전 표기 유지)
    """v1.3 발급 순서 근거 — ``(issuerId, siteId)`` durable 단조 수열."""

    issuer_id: str = Field(min_length=1)
    site_sequence: int = Field(gt=0)
    issued_at: str

    @field_validator("issued_at")
    @classmethod
    def _issued_at_must_be_tz_aware(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("issuance.issuedAt 은 tz-aware RFC3339여야 한다")
        return value


class MissionContractV1_1(_MissionContractBase):  # noqa: N801 (스키마 버전 표기 유지)
    """mission-contract.v1.1.json — 서명 필드 존재만 표현(암호학적 검증 불가, 동결본)."""

    schema_version: Literal["1.1"]
    signature: SignatureV1


class MissionContractV1_2(_MissionContractBase):  # noqa: N801 (스키마 버전 표기 유지)
    """mission-contract.v1.2.json — Ed25519 실서명 (ADR-KSI-002, INV-011 강제 지점)."""

    schema_version: Literal["1.2"]
    signature: Ed25519Signature


class MissionContractV1_3(_MissionContractBase):  # noqa: N801 (스키마 버전 표기 유지)
    """mission-contract.v1.3.json — 서명된 발급자·현장별 단조 순서를 포함한다."""

    schema_version: Literal["1.3"]
    issuance: IssuanceV1_3
    signature: Ed25519Signature


MissionContract = MissionContractV1_1 | MissionContractV1_2 | MissionContractV1_3


def parse_mission_contract(data: dict[str, Any]) -> MissionContract:
    """``schemaVersion``에 따라 v1.1/v1.2/v1.3 모델로 분기 파싱한다.

    Raises:
        ValueError: 지원하지 않는 ``schemaVersion``이거나 필드가 없을 때.
    """
    version = data.get("schemaVersion")
    if version == "1.1":
        return MissionContractV1_1.model_validate(data)
    if version == "1.2":
        return MissionContractV1_2.model_validate(data)
    if version == "1.3":
        return MissionContractV1_3.model_validate(data)
    raise ValueError(f"지원하지 않는 schemaVersion: {version!r}")
