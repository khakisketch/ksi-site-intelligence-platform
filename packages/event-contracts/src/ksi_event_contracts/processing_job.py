"""ProcessingJob — 3D 재구성 처리 작업 계약 (ADR-KSI-012, ADR-KSI-013).

## 왜 이 계약이 필요한가

`services/processing-controller`는 빈 골격으로 예약돼 있고(ADR-KSI-004와 같은
패턴), 어댑터가 무엇을 갈아끼울 수 있는지·어디서 실행될 수 있는지·언제 데이터
반출이 허용되는지는 ADR-KSI-012·ADR-KSI-013가 정했다. 이 모듈은 그 결정을 코드
표면(계약 스키마)으로 고정한다 — 사람이 기억해서 지키는 규칙이 아니라 job 생성
시점에 기계가 강제하는 규칙으로 옮긴다.

## INV-050 — 실행 위치 × 반출 허용

`executionLocus == vendor_cloud`(예: DJI FlightHub 2, 상용 SaaS 엔진)인데 그
현장의 `dataResidency.egressAllowed`가 참이 아니면 이 모델은 구성되지 않는다
(:meth:`ProcessingJob._vendor_cloud_requires_egress`). 실행 후 사후 통제가 아니라
생성 시점 게이트다 — `contracts/schemas/processing-job.v1.json`의 `allOf`가 같은
규칙을 JSON Schema 레벨에서도 강제하므로, 이 계약을 우회해 원시 dict로 조립한
페이로드도(예: 다른 언어 클라이언트) 동일하게 걸린다.

## 이 계약이 다루지 않는 것

- **처리 상태 전이 규칙.** `status`는 값 집합만 고정하고 QUEUED→RUNNING 같은
  전이 검증은 처리 워커 구현 시 별도로 정한다(범위 밖).
- **Mission Contract 확장.** `missionId`는 참조일 뿐이다 — 서명 Mission Contract
  (`contracts/schemas/mission-contract.v1.2.json`)에는 처리 정보를 넣지 않는다.
  계약은 비행 권한이고 후처리는 비행이 끝난 뒤에 존재하는 별개 사건이다
  (CLAUDE.md `Control boundaries`).

계약 정본은 ``contracts/schemas/processing-job.v1.json``이고 이 모듈은 그 스키마의
Python 표현이다 — 필드가 갈라지면 `tests/contract/test_processing_contracts.py`가
잡는다.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from ksi_event_contracts._base import _CamelModel

_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"


class ProcessingProvider(StrEnum):
    """3D 재구성 엔진 어댑터 (ADR-KSI-012 D1 — 기본값 ODM, D3 — 검토·보류·기각 대안)."""

    ODM = "odm"
    PIX4D_ENGINE = "pix4d_engine"
    DJI_FLIGHTHUB = "dji_flighthub"
    METASHAPE_SPL = "metashape_spl"
    CUSTOMER_WORKSTATION = "customer_workstation"


class ExecutionLocus(StrEnum):
    """처리 실행 위치 (ADR-KSI-010 운영 표면의 판정 대상 — INV-050이 이 값을 강제 조건으로 쓴다)."""

    SITE_ONPREM = "site_onprem"
    KSI_SERVER_GPU = "ksi_server_gpu"
    CUSTOMER_WORKSTATION = "customer_workstation"
    VENDOR_CLOUD = "vendor_cloud"


class ProcessingJobStatus(StrEnum):
    """작업 진행 상태 — 전이 규칙은 이 계약의 범위 밖이다(처리 워커 구현 시 정의)."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DataResidency(_CamelModel):
    """INV-050 강제 지점의 데이터 절반 — 이 현장의 반출 허용 여부."""

    egress_allowed: bool
    jurisdiction: str = Field(min_length=1)


class LicenseBasis(_CamelModel):
    """산출물 렌더링 단계가 읽는 라이선스 표기 의무(ADR-KSI-012 D3).

    Pix4D "Powered by Pix4D" 공개 표기, Metashape Service Provider License 여부 등을
    사람이 기억해 화면에 붙이는 대신 이 필드를 코드가 읽고 렌더링한다.
    """

    license_id: str = Field(min_length=1)
    tier: str = Field(min_length=1)
    attribution_required: bool


class ProcessingInput(_CamelModel):
    """과금 크레딧의 SSOT이자 재현성 앵커.

    ``image_count`` 만 세면 원가와 어긋난다 — ADR-KSI-012 D4의 크레딧 산식은
    해상도(MP) × 장수이므로 ``total_megapixels`` 를 함께 고정한다.
    """

    image_count: int = Field(ge=1)
    total_megapixels: float = Field(gt=0)
    source_bundle_digest: str = Field(pattern=_DIGEST_PATTERN)


class Billing(_CamelModel):
    """ADR-KSI-012 D4 과금 뼈대의 실측 기록.

    고객 장비(온프렘)에서 돌리면 소모 0, KSI 서버에서 돌리면 해상도×장수에
    비례한다 — ``credits_charged == 0`` 은 온프렘 실행의 정상값이다.
    """

    credits_charged: float = Field(ge=0)
    rate_basis: str = Field(min_length=1)
    metered_at: datetime


class ProcessingJob(_CamelModel):
    """3D 재구성 처리 작업 1건 — ``contracts/schemas/processing-job.v1.json`` SSOT."""

    job_id: str = Field(min_length=1)
    mission_id: str = Field(min_length=1)
    provider: ProcessingProvider
    engine_version: str = Field(min_length=1)
    engine_digest: str = Field(min_length=1)
    execution_locus: ExecutionLocus
    data_residency: DataResidency
    license_basis: LicenseBasis
    input: ProcessingInput
    processing_params: dict[str, Any] = Field(default_factory=dict)
    billing: Billing
    status: ProcessingJobStatus | None = None

    @model_validator(mode="after")
    def _vendor_cloud_requires_egress_allowed(self) -> ProcessingJob:
        """INV-050 — 벤더 클라우드 실행인데 반출 허용이 아니면 job이 성립하지 않는다.

        ``contracts/schemas/processing-job.v1.json`` 의 ``allOf`` 가 wire 페이로드
        레벨에서 같은 규칙을 강제하고, 이 validator는 Python 쪽 생성 경로(예:
        services/processing-controller 가 이 모델을 직접 구성하는 경우)에서 같은
        위반을 조기에 막는다 — 실행 후 사후 통제가 아니라 생성 시점 게이트다.
        """
        if (
            self.execution_locus is ExecutionLocus.VENDOR_CLOUD
            and not self.data_residency.egress_allowed
        ):
            raise ValueError(
                "INV-050 위반: executionLocus=vendor_cloud 인데 "
                "dataResidency.egressAllowed=false — 반출 미허용 현장에서 벤더 "
                "클라우드 처리 job은 생성될 수 없다"
            )
        return self


def processing_job_wire_dict(job: ProcessingJob) -> dict[str, Any]:
    """ProcessingJob의 wire 직렬화 규약 — ``by_alias + mode="json" + exclude_none``.

    ``status`` 만 optional(``None`` 이면 미배정)이라 이 규약으로 충분하다 — 다른
    모든 필드는 필수라서 None 이 될 수 없다(event_bundle_wire_dict와 같은 근거,
    JSON 계약에서 optional은 "부재"가 표준이다).
    """
    return job.model_dump(by_alias=True, mode="json", exclude_none=True)
