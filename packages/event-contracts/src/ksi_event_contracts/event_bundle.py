"""EventBundle v1.2 Pydantic v2 모델 (contracts/schemas/event-bundle.v1.2.json SSOT).

camelCase 표현(``alias_generator=to_camel``, ``populate_by_name=True``), ``model_config``
``extra="forbid"``. ``lineage``는 필수 필드다 — INV-042: 모든 결과는 Mission/Model/
Policy/Calibration Version 계보를 가진다.

## v1.2 — standalone classification lineage (INV-031)

v1.1 의 EventBundle 은 ``entities`` 에 entity_id 문자열만 담았다 — WorldEntity 와
분리되어 Core 에 단독 전송되면 "이 이벤트의 대상 class 가 어느 ontology 의 어떤
원시 분류에서 왔는가"를 bundle 만으로 알 수 없다(분류 계보 단절). v1.2 는
``lineage.classification`` (entity_id → :class:`ClassificationLineage`)을 **필수**로
하여 EventBundle 단독으로도 canonical class·ontology version·원시 출처·검증 가능한
entity fingerprint 를 갖는다. 자유 dict 중복 저장이 아니라 WorldEntity 의
:class:`~ksi_event_contracts.world_entity.ClassificationSource` 계약을 재사용한다.

``entity_fingerprint`` 생성·검증 규칙: 생성은
:func:`ksi_event_contracts.assembly.world_entity_fingerprint` (entity_id 를 제외한
내용 기반 sha256) 뿐이다. 수신자는 대응 WorldEntity 확보 시 같은 함수로 재계산해
대조한다 — 불일치는 "bundle 이 가리키는 entity 가 그 entity 가 아니다"이다.

## INV-030 강화 (2026-08-16) — clip 길이 교차검증 + EVIDENCE_DEGRADED

``ClipPolicy.pre_seconds``/``post_seconds`` 는 이전엔 무제약 float(음수·NaN 허용)
였고, evidence 저장 실패를 기록할 스키마 필드가 없었다. 이번 변경:

- ``ClipPolicy`` 필드에 finite·비음수 제약을 걸고, :class:`EventBundle` 에
  ``severity`` 대비 INV-030 표(3/5/10초) 교차검증 model_validator 를 추가했다.
- ``Evidence.storage_status`` (:class:`EvidenceStorageStatus`, 값
  ``EVIDENCE_DEGRADED`` 하나)를 추가해 저장 실패를 침묵 성공과 구분한다.

**보류된 결정**: 이 스키마 계열은 v1.0→v1.1 에서 순수 additive(옵션 필드만
추가) 변경조차 매번 schemaVersion 을 올렸다(선례). 그 관례를 그대로 따르면
이번 것도 v1.3 이어야 하지만, 그러면 ``schema_version: Literal`` 이 깨져 이
저장소 전역의 ``"schemaVersion": "1.2"`` 하드코딩 fixture(15개 이상,
``tests/contract/`` 다수 + AsyncAPI 문서)가 전부 갱신 대상이 된다 — 이 좁은
수정 범위를 넘는 저장소 전역 변경이라 여기서 임의로 단행하지 않았다.
**대신** ``schema_version`` 은 ``"1.2"`` 로 유지하고 ``storage_status`` 를
additive-optional 필드로만 추가했다(``extra="forbid"`` 라서 이 필드 자체는
모델에 선언해야 통과하지만, 부재 시 기존 payload 는 그대로 유효하다). v1.3
정식 채번 여부는 스키마 소유자의 별도 결정이 필요하다.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from ksi_domain.enums import EventStatus, Severity
from ksi_domain.ontology import REGISTERED_ONTOLOGY_VERSIONS
from pydantic import Field, field_validator, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.world_entity import ClassificationSource

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


# INV-030 — Evidence Clip 전후 길이(초) 표(SSOT). Candidate/High/Critical = 3/5/10초.
# MEDIUM 은 §17.2 상 재검증 경로라 클립 정책이 정의돼 있지 않다(감사 #26·#37 —
# 표에 없는 severity 로 임의 길이를 지어내면 초판처럼 CRITICAL 이 축소된 클립을
# 받는 드리프트가 재발한다). ``ksi_perception.pipeline`` 은 이 표를 재사용한다 —
# 별도 사본을 두면 그 자체가 드리프트 재발 지점이 된다(이 모델이 유일한 SSOT).
EVIDENCE_CLIP_SECONDS: dict[Severity, float] = {
    Severity.CANDIDATE: 3.0,
    Severity.HIGH: 5.0,
    Severity.CRITICAL: 10.0,
}


class ClipPolicy(_CamelModel):
    """INV-030 강제 지점.

    필드 제약(finite·비음수)은 여기서 본다. ``severity`` 대비 정확한 3/5/10초
    일치는 이 모델이 아니라 :class:`EventBundle` 의 model_validator
    (``_clip_policy_matches_severity``)가 본다 — ``severity`` 는 형제 필드로
    ``EventBundle`` 에만 있어(``Evidence``·``ClipPolicy`` 는 그 값을 모른다),
    교차검증은 그 상위 모델에서만 가능하다.
    """

    pre_seconds: float = Field(ge=0, allow_inf_nan=False)
    post_seconds: float = Field(ge=0, allow_inf_nan=False)


class EvidenceStorageStatus(StrEnum):
    """INV-030 — evidence 아티팩트 저장 실패는 숨기지 않고 이 상태로 명시 기록한다."""

    EVIDENCE_DEGRADED = "EVIDENCE_DEGRADED"


class Evidence(_CamelModel):
    """INV-030 — 저장 실패는 숨기지 않고 ``EVIDENCE_DEGRADED``(bundle_digest 등)로 기록."""

    context_images: list[str] | None = None
    detail_images: list[str] | None = None
    clips: list[str] | None = None
    trajectory_artifact: str | None = None
    clip_policy: ClipPolicy | None = None
    risk_field_artifact: str | None = None
    viewpoint_history_artifact: str | None = None
    bundle_digest: str | None = None
    edge_signature: str | None = None
    # INV-030 — 스토리지 업로드 실패를 침묵 성공으로 뭉개지 않는다. 프로듀서가
    # 업로드 실패를 감지하면 여기 EVIDENCE_DEGRADED 를 명시 기록한다(부재=정상
    # 저장 — "시도해서 실패"와 "애초에 만들 게 없었다"를 구분하는 필드다).
    storage_status: EvidenceStorageStatus | None = None


class ClassificationLineage(_CamelModel):
    """Entity 1개의 분류 계보 — EventBundle 이 단독으로 들고 다니는 검증 가능 단위.

    malformed 계보(공백 class·미등록 ontology 버전·빈 원시 출처·비정형 fingerprint)
    는 schema 검증에서 거부된다 — assembly gate 이전에 모델 계층이 이미 막는다.
    """

    entity_class: str
    ontology_version: str
    source: ClassificationSource
    entity_fingerprint: str

    @field_validator("entity_class")
    @classmethod
    def _class_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("entity_class 는 공백일 수 없다")
        return value

    @field_validator("ontology_version")
    @classmethod
    def _version_registered(cls, value: str) -> str:
        if value not in REGISTERED_ONTOLOGY_VERSIONS:
            raise ValueError(
                f"미등록 ontology 버전 {value!r} — 등록: {sorted(REGISTERED_ONTOLOGY_VERSIONS)}"
            )
        return value

    @field_validator("entity_fingerprint")
    @classmethod
    def _fingerprint_hex64(cls, value: str) -> str:
        if not _HEX64.fullmatch(value):
            raise ValueError(
                "entity_fingerprint 는 world_entity_fingerprint 산출(hex64)이어야 한다"
            )
        return value

    @model_validator(mode="after")
    def _source_nonempty(self) -> ClassificationLineage:
        if not self.source.source_class_ids or not self.source.source_class_names:
            raise ValueError("classification source 의 원시 id/이름이 비어 있다 — 계보가 아니다")
        return self


class Lineage(_CamelModel):
    """INV-042 — 모든 결과는 Mission/Model/Policy/Calibration Version 계보를 가진다.

    v1.2: ``classification`` (entity_id → :class:`ClassificationLineage`) 필수 —
    EventBundle 단독 전송에서도 분류 계보가 끊기지 않는다(INV-031).
    """

    edge_version: str
    model_versions: dict[str, Any]
    policy_version: str
    calibration_profile_id: str
    classification: dict[str, ClassificationLineage]


class Timing(_CamelModel):
    candidate_latency_ms: float | None = None
    local_alert_latency_ms: float | None = None
    server_notification_latency_ms: float | None = None


class EventBundle(_CamelModel):
    """EventBundle v1.2 — 상태전이는 :func:`ksi_domain.enums.assert_event_transition` 을 경유."""

    schema_version: Literal["1.2"] = "1.2"
    event_id: str
    mission_id: str
    site_id: str
    event_type: str
    severity: Severity | None = None
    occurred_at: datetime
    status: EventStatus
    entities: list[str]
    spatial_context: dict[str, Any]
    reasoning: dict[str, Any]
    evidence: Evidence
    lineage: Lineage
    review: dict[str, Any] | None = None
    timing: Timing | None = None

    @model_validator(mode="after")
    def _classification_covers_entities(self) -> EventBundle:
        """entities 와 lineage.classification 키의 정확 일치 — 누락도 잉여도 계보 단절이다.

        누락: 그 entity 의 이벤트가 분류 계보 없이 흐른다(v1.1 결함 재발). 잉여:
        bundle 에 없는 entity 의 계보가 위장 편승한다(검증 불가 데이터의 무단 진입).
        """
        entity_ids = set(self.entities)
        lineage_ids = set(self.lineage.classification)
        if entity_ids != lineage_ids:
            missing = sorted(entity_ids - lineage_ids)
            surplus = sorted(lineage_ids - entity_ids)
            raise ValueError(
                f"classification lineage 불일치 — 누락 {missing}, 잉여 {surplus}"
            )
        return self

    @model_validator(mode="after")
    def _clip_policy_matches_severity(self) -> EventBundle:
        """INV-030 — ``evidence.clip_policy`` 가 실리면 severity 표(3/5/10초)와 정확히
        일치해야 한다. ``severity`` 는 이 모델의 형제 필드라 여기서만 교차검증할 수
        있다(``Evidence``/``ClipPolicy`` 단독으로는 severity 를 볼 수 없다).

        알려진 한계: ``severity`` 가 아직 배정되지 않아 ``None`` 이면(예: 이른 단계
        산출물) 이 교차검증을 건너뛴다 — 그 경우 :class:`ClipPolicy` 의 필드 제약
        (finite·비음수)만 적용되고, 길이가 실제 severity 정책과 맞는지는 severity 가
        채워지는 시점(재검증 없이는) 보장되지 않는다.
        """
        clip_policy = self.evidence.clip_policy
        if clip_policy is None or self.severity is None:
            return self
        expected = EVIDENCE_CLIP_SECONDS.get(self.severity)
        if expected is None:
            raise ValueError(
                f"severity {self.severity.value} 의 Evidence Clip 정책이 정의돼 있지 "
                f"않다(INV-030 표: {sorted(s.value for s in EVIDENCE_CLIP_SECONDS)}) — "
                "clip_policy 를 실을 수 없다"
            )
        if clip_policy.pre_seconds != expected or clip_policy.post_seconds != expected:
            raise ValueError(
                f"evidence.clipPolicy 가 INV-030 표와 불일치 — severity "
                f"{self.severity.value} 는 전후 {expected}초여야 하는데 "
                f"preSeconds={clip_policy.pre_seconds}, postSeconds={clip_policy.post_seconds}"
            )
        return self


def event_bundle_wire_dict(bundle: EventBundle) -> dict[str, Any]:
    """EventBundle 의 wire 직렬화 규약 SSOT — ``by_alias + mode="json" + exclude_none``.

    실측(2026-07-29, 감사 #28): ``exclude_none`` 없이 dump 하면 optional 필드가
    ``null`` 로 방출되어 event-bundle.v1.2.json 을 10건 위반한다 — 스키마 기준
    소비자(외부 연동·후속 Core 구현)가 Edge 산출물을 전량 거부하게 되는 drift.
    JSON 계약에서 optional 은 "부재"가 표준이므로 wire 는 이 함수만 쓴다.
    (수신측 Pydantic 은 부재/명시 어느 쪽도 수용하므로 하위 호환에 영향 없음.)
    """
    return bundle.model_dump(by_alias=True, mode="json", exclude_none=True)
