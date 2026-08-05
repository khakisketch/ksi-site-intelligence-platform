"""3D 재구성 처리 작업의 발급·영속·상태전이 (ADR-KSI-012, INV-050).

``source_media.py`` 가 봉인한 번들을 받아 처리 작업 1건을 만든다. 계약 자체는
``contracts/schemas/processing-job.v1.json``(및 그 Python 표현
:mod:`ksi_event_contracts.processing_job`)이 SSOT이고, 그 계약이 명시적으로
"범위 밖"이라 미뤄둔 두 가지를 이 모듈이 정한다 — **상태 전이 규칙**과
**발급 게이트**다.

## 입력은 요청이 아니라 봉인된 번들에서 온다

``input.imageCount``·``totalMegapixels``·``sourceBundleDigest`` 를 요청이 실어
보낼 수 없다(:class:`ProcessingJobRequest` 에 필드가 없고 ``extra="forbid"``
가 위조를 거부한다). Core 가 :class:`~ksi_core.source_media.SourceMediaBundle`
에서 직접 집계한다 — ``imageCount`` 는 등록된 미디어 수, ``totalMegapixels``
는 신고 해상도의 합이다. 봉인되지 않은 번들로는 발급하지 않는다: 봉인 전에는
장수도 digest 도 아직 확정되지 않은 값이라, 그 위에서 계산한 과금 근거는
발급 직후 달라질 수 있다.

**단, totalMegapixels 는 여전히 업로더의 신고값에서 유도된다**(B1 이 해상도를
검증하지 않는다). 그래서 이 값은 과금 확정 근거가 아니라 견적이고, 발급 시점
``billing`` 은 청구하지 않은 상태로 기록한다(아래).

## 발급 시점에 과금하지 않는다

계약은 ``billing`` 을 필수로 요구하지만, 발급 시점에 크레딧을 확정하면
"아직 아무것도 처리하지 않았고 입력 화소 수도 미검증인 상태"에서 청구액이
굳는다. 그래서 발급 레코드의 billing 은 ``creditsCharged=0`` ·
``rateBasis="unmetered-at-issue"`` 다 — 0 이라는 값이 "무료"가 아니라 "아직
재지 않았다"를 뜻하고, 그 사실이 필드 이름에 적혀 있다. 실제 계측은 전
바이트를 읽어 화소를 재계산한 워커가 종료를 보고할 때(B3) 이뤄진다.

## INV-050 은 현장 값으로만 판정한다

``executionLocus=vendor_cloud`` 는 그 임무가 속한 **현장**의
``site.dataResidency.egressAllowed`` 가 참일 때만 발급된다. 요청이 아니라
``SiteRecord`` 를 읽는다(``sites.py`` "데이터 반출 허용은 현장의 속성이다").
현장이 반출을 선언하지 않았으면(``None``) 거부다 — 미선언은 미허용이다.

## 임무당 활성 작업은 1건

``QUEUED``·``RUNNING`` 인 작업이 있는 동안 같은 임무에 두 번째 작업을 만들지
않는다. 같은 사양(provider·engine·params)으로 재요청하면 기존 작업을 그대로
돌려주고(멱등 — 네트워크 재시도가 작업을 복제하지 않는다), 다른 사양이면
``ACTIVE_JOB_EXISTS`` 로 거부한다. 종료된 뒤에는 재처리를 위해 새 작업을
만들 수 있다(다른 엔진·다른 파라미터로 다시 돌리는 것이 정상 운용이다).

## 상태 전이

``QUEUED → RUNNING → SUCCEEDED|FAILED`` · ``QUEUED|RUNNING → CANCELLED``.
종료 상태(``SUCCEEDED``·``FAILED``·``CANCELLED``)에서 나가는 전이는 없다 —
끝난 작업의 결론을 나중에 고쳐 쓸 수 없다. 재생(``_replay``)도 live 와 같은
전이표를 다시 태운다(``sites._apply_transitioned`` 와 동일 원칙): journal 을
손으로 고쳐 FAILED 를 SUCCEEDED 로 바꿀 수 없다.

## 이 모듈이 다루지 않는 것

- **워커 lease·heartbeat.** ``RUNNING`` 전이가 한 번만 성공한다는 것이 지금의
  유일한 상호배제다. 죽은 워커의 작업을 회수하는 만료·갱신은 워커 실행 경로와
  함께 설계한다(B3).
- **워커 인증.** 지금 상태 전이는 사람 권한(``MISSIONS_ISSUE``)으로 열려
  있다. 처리 워커 전용 Principal 종류는 B3 범위다 — ``EDGE_DEVICE`` 를
  재사용하지 않는다(비행 장비용이고 권한 집합이 다르다).
- **산출물 등록.** ``ProcessingArtifact``(INV-051)는 B3 에서 붙는다.

## 알려진 공백 — ``SUCCEEDED`` 는 아직 근거 없이 주장될 수 있다

``RUNNING → SUCCEEDED`` 전이는 지금 산출물 존재를 요구하지 않는다.
``ProcessingArtifact`` 원장이 아직 없어서 대조할 대상이 없기 때문이다 —
이 저장소가 커버리지 보고에서 닫았던 것과 **같은 클래스의 결함**이 여기서는
아직 열려 있다("완료 판정의 권위를 CoverageReport 로", ADR-KSI-011 D3).

그래서 이 상태를 완료의 증거로 읽는 소비자를 지금 만들지 않는다. B3 에서
산출물 원장이 생기면 ``SUCCEEDED`` 전이에 "이 작업의 산출물이 최소 1건
등록돼 있다"는 게이트를 건다. 원장에 리스크로 등록돼 있다
(``processing-success-claim-unbacked``).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from ksi_event_contracts.processing_job import (
    Billing,
    DataResidency,
    ExecutionLocus,
    LicenseBasis,
    ProcessingInput,
    ProcessingJob,
    ProcessingJobStatus,
    ProcessingProvider,
    processing_job_wire_dict,
)
from ksi_mission_contracts.signing import canonical_payload_bytes, sha256_digest
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ksi_core.auth import Permission, Principal, require_permission
from ksi_core.durable_journal import DurableJournal, JournalSealedError

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.sites import SiteStore
    from ksi_core.source_media import SourceMediaStore

logger = logging.getLogger(__name__)

_NOT_FOUND_DETAIL = "해당 처리 작업을 찾을 수 없다"
_STORE_UNAVAILABLE_DETAIL = "journal 봉인됨 — 재시작 필요"

# 발급 시점 billing 의 rateBasis. "아직 재지 않았다"를 값 자체가 말한다 —
# creditsCharged=0 만으로는 온프렘 무료 실행과 구분되지 않는다.
UNMETERED_AT_ISSUE = "unmetered-at-issue"

_ACTIVE_STATUSES = frozenset({ProcessingJobStatus.QUEUED, ProcessingJobStatus.RUNNING})

# 상태 전이표 — 계약(processing_job.py)이 "범위 밖"으로 미뤄둔 규칙의 SSOT.
_ALLOWED_TRANSITIONS: dict[ProcessingJobStatus, frozenset[ProcessingJobStatus]] = {
    ProcessingJobStatus.QUEUED: frozenset(
        {ProcessingJobStatus.RUNNING, ProcessingJobStatus.CANCELLED}
    ),
    ProcessingJobStatus.RUNNING: frozenset(
        {
            ProcessingJobStatus.SUCCEEDED,
            ProcessingJobStatus.FAILED,
            ProcessingJobStatus.CANCELLED,
        }
    ),
    ProcessingJobStatus.SUCCEEDED: frozenset(),
    ProcessingJobStatus.FAILED: frozenset(),
    ProcessingJobStatus.CANCELLED: frozenset(),
}


class IllegalJobTransitionError(ValueError):
    """전이표에 없는 처리 작업 상태 전이."""


def assert_job_transition(
    before: ProcessingJobStatus, after: ProcessingJobStatus
) -> None:
    """전이 적법성 — live 경로와 재생 경로가 **같은 함수**를 쓴다.

    ``sites.assert_site_transition`` 과 같은 역할이다. 두 경로가 각자 조건문을
    갖고 있으면 한쪽만 고쳐지고, 그 순간 journal 이 불법 상태를 조용히
    되살리는 경로가 열린다.
    """
    if after not in _ALLOWED_TRANSITIONS[before]:
        raise IllegalJobTransitionError(
            f"처리 작업 상태를 {before.value} 에서 {after.value} 로 바꿀 수 없다"
            + (
                " — 종료된 작업의 결론은 고쳐 쓰지 않는다"
                if not _ALLOWED_TRANSITIONS[before]
                else ""
            )
        )


class ProcessingJobVerdict(StrEnum):
    """발급/전이 판정. ``ISSUED`` 와 ``ALREADY_ISSUED`` 를 나눠 재시도를 구분한다."""

    ISSUED = "ISSUED"
    # 같은 사양의 재요청 — 새 작업을 만들지 않고 기존 작업을 돌려준다.
    ALREADY_ISSUED = "ALREADY_ISSUED"
    TRANSITIONED = "TRANSITIONED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    UNKNOWN_JOB = "UNKNOWN_JOB"
    # 번들이 없거나 아직 봉인되지 않았다 — 장수·digest 가 확정되지 않은 상태.
    BUNDLE_NOT_SEALED = "BUNDLE_NOT_SEALED"
    # INV-050 — 반출 미허용 현장의 벤더 클라우드 실행.
    EGRESS_NOT_ALLOWED = "EGRESS_NOT_ALLOWED"
    ACTIVE_JOB_EXISTS = "ACTIVE_JOB_EXISTS"
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_STATUS: dict[ProcessingJobVerdict, int] = {
    ProcessingJobVerdict.ISSUED: 201,
    ProcessingJobVerdict.ALREADY_ISSUED: 200,
    ProcessingJobVerdict.TRANSITIONED: 200,
    ProcessingJobVerdict.UNKNOWN_MISSION: 404,
    ProcessingJobVerdict.UNKNOWN_JOB: 404,
    ProcessingJobVerdict.BUNDLE_NOT_SEALED: 422,
    ProcessingJobVerdict.EGRESS_NOT_ALLOWED: 422,
    ProcessingJobVerdict.ACTIVE_JOB_EXISTS: 409,
    ProcessingJobVerdict.ILLEGAL_TRANSITION: 409,
    ProcessingJobVerdict.STORE_UNAVAILABLE: 503,
}


class ProcessingJobRecoveryError(RuntimeError):
    """처리 작업 journal 재생 실패 — 오염된 원장으로 기동하지 않는다(fail-closed)."""


@dataclass(frozen=True, slots=True)
class JobSpec:
    """호출자가 정하는 것 — **무엇으로 어디서** 돌릴지.

    입력(장수·화소·digest)은 여기 없다. 그건 봉인된 번들이 정하고 Core 가
    집계한다(모듈 docstring). ``engine_version``·``engine_digest`` 는 지시이지
    자기 증명이 아니다 — 실제로 그 엔진이 돌았는지는 종료 보고 시점에
    대조한다(B3).
    """

    provider: ProcessingProvider
    engine_version: str
    engine_digest: str
    execution_locus: ExecutionLocus
    license_basis: LicenseBasis
    processing_params: dict[str, Any]

    def fingerprint(self) -> str:
        """멱등 재요청 판정용 지문 — 같은 사양이면 같은 값.

        ``processing_params`` 가 중첩 dict 라 문자열 결합으로는 안정적으로
        비교되지 않는다. 이 저장소의 유일한 문서화 정규화를 재사용한다
        (``source_media.compute_source_bundle_digest`` 와 같은 근거,
        ADR-KSI-002 §2/§3).
        """
        payload = {
            "provider": self.provider.value,
            "engineVersion": self.engine_version,
            "engineDigest": self.engine_digest,
            "executionLocus": self.execution_locus.value,
            "licenseBasis": self.license_basis.model_dump(by_alias=True, mode="json"),
            "processingParams": self.processing_params,
        }
        return sha256_digest(canonical_payload_bytes(payload))


@dataclass(frozen=True, slots=True)
class ProcessingJobRecord:
    """처리 작업 1건의 projection — 계약 필드 + 운영 메타(누가·언제)."""

    job_id: str
    mission_id: str
    site_id: str
    spec: JobSpec
    data_residency: DataResidency
    input: ProcessingInput
    status: ProcessingJobStatus
    issued_at: datetime
    issued_by: str
    updated_at: datetime
    # 종료 상태에서만 채워진다 — 왜 그렇게 끝났는지.
    terminal_detail: str | None = None
    # 발급 시점에는 UNMETERED_AT_ISSUE 로 고정된다(모듈 docstring).
    billing: Billing | None = None

    def to_contract(self) -> ProcessingJob:
        """계약 모델로 투영한다 — 어댑터로 나가는 payload 의 SSOT.

        여기서 :class:`ProcessingJob` 의 validator 가 INV-050 을 한 번 더
        태운다. 이 저장소의 게이트와 중복이지만, 중복이 요점이다 — 계약을
        구성하는 모든 경로가 같은 규칙에 걸린다.
        """
        return ProcessingJob(
            job_id=self.job_id,
            mission_id=self.mission_id,
            provider=self.spec.provider,
            engine_version=self.spec.engine_version,
            engine_digest=self.spec.engine_digest,
            execution_locus=self.spec.execution_locus,
            data_residency=self.data_residency,
            license_basis=self.spec.license_basis,
            input=self.input,
            processing_params=self.spec.processing_params,
            billing=(
                self.billing
                if self.billing is not None
                else Billing(
                    credits_charged=0.0,
                    rate_basis=UNMETERED_AT_ISSUE,
                    metered_at=self.issued_at,
                )
            ),
            status=self.status,
        )


@dataclass(frozen=True, slots=True)
class ProcessingJobResult:
    verdict: ProcessingJobVerdict
    record: ProcessingJobRecord | None = None
    detail: str | None = None


def build_job_id(mission_id: str, sequence: int) -> str:
    """``{missionId}-pj{n}`` — 임무 안에서 결정적이고 사람이 읽을 수 있다.

    ``mission_id`` 는 이미 경로-안전이 강제된 값이므로(mission_records
    ``validate_mission_identifiers``) 여기서 만들어진 jobId 도 경로-안전이다.
    """
    return f"{mission_id}-pj{sequence}"


def _require_tz_aware(value: datetime, *, param: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{param} 은 tz-aware 여야 한다")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _require_aware_iso(raw: Any, field_name: str, job_id: str) -> datetime:
    if not isinstance(raw, str):
        raise ProcessingJobRecoveryError(
            f"재생: {field_name} 가 문자열이 아니다({type(raw).__name__}) — jobId={job_id}"
        )
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ProcessingJobRecoveryError(
            f"재생: {field_name} 가 ISO 시각이 아니다({raw!r}) — jobId={job_id}"
        ) from exc
    if parsed.tzinfo is None:
        raise ProcessingJobRecoveryError(
            f"재생: {field_name} 가 naive datetime — jobId={job_id}"
        )
    return parsed


def _compute_input(*, media: tuple[Any, ...], source_bundle_digest: str) -> ProcessingInput:
    """봉인된 번들에서 계약 ``input`` 을 집계한다 — 요청은 이 값에 관여하지 않는다.

    ``total_megapixels`` 는 등록 시 **신고된** 해상도의 합이다(B1 은 검증하지
    않는다). 그래서 이 값은 과금 확정이 아니라 견적이고, 재계산·대조는 전
    바이트를 읽는 워커의 몫이다.
    """
    total_pixels = sum(record.width * record.height for record in media)
    return ProcessingInput(
        image_count=len(media),
        total_megapixels=total_pixels / 1_000_000,
        source_bundle_digest=source_bundle_digest,
    )


class ProcessingJobStore:
    """``DurableJournal`` 위의 처리 작업 저장소(``source_media.py`` 형태 대칭).

    동시성: 판정+append+projection 을 한 임계구역으로 묶는다 — "활성 작업 1건"
    은 이 잠금 안에서만 성립하는 불변식이다.
    """

    def __init__(
        self,
        journal: DurableJournal,
        *,
        source_media_store: SourceMediaStore,
        site_store: SiteStore,
    ) -> None:
        self._journal = journal
        self._source_media = source_media_store
        self._sites = site_store
        self._lock = threading.Lock()
        self._jobs: dict[str, ProcessingJobRecord] = {}
        # missionId → 발급된 작업 수(다음 jobId 순번의 근거)
        self._sequence: dict[str, int] = {}
        try:
            self._replay(journal)
        except ProcessingJobRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise ProcessingJobRecoveryError(
                f"processing-job journal 재생 실패 — 오염된 레코드: {exc}"
            ) from exc

    # ── 재생 ────────────────────────────────────────────────────────────
    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw["kind"]
            if kind == "processing-job-issued":
                self._replay_issued(raw)
            elif kind == "processing-job-transitioned":
                self._replay_transition(raw)
            else:  # pragma: no cover - 방어적, journal 오염이 아닌 이상 도달 불가
                raise ProcessingJobRecoveryError(f"알 수 없는 journal 레코드 kind: {kind!r}")

    def _replay_issued(self, raw: dict[str, Any]) -> None:
        job_id = raw["jobId"]
        if job_id in self._jobs:
            raise ProcessingJobRecoveryError(f"재생: jobId 중복 발급 레코드 — jobId={job_id}")
        try:
            residency = DataResidency.model_validate(raw["dataResidency"])
            license_basis = LicenseBasis.model_validate(raw["licenseBasis"])
            job_input = ProcessingInput.model_validate(raw["input"])
            spec = JobSpec(
                provider=ProcessingProvider(raw["provider"]),
                engine_version=raw["engineVersion"],
                engine_digest=raw["engineDigest"],
                execution_locus=ExecutionLocus(raw["executionLocus"]),
                license_basis=license_basis,
                processing_params=raw["processingParams"],
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise ProcessingJobRecoveryError(
                f"재생: 발급 레코드가 계약을 만족하지 않는다 — jobId={job_id}: {exc}"
            ) from exc
        if (
            spec.execution_locus is ExecutionLocus.VENDOR_CLOUD
            and not residency.egress_allowed
        ):
            # live 는 이 조합을 절대 발급하지 않는다 — 있다면 journal 조작이거나
            # 발급 게이트가 깨진 것이다(source_media._replay_seal 과 같은 원칙).
            raise ProcessingJobRecoveryError(
                f"재생: INV-050 위반 레코드 — 반출 미허용 현장의 vendor_cloud 작업: jobId={job_id}"
            )
        record = ProcessingJobRecord(
            job_id=job_id,
            mission_id=raw["missionId"],
            site_id=raw["siteId"],
            spec=spec,
            data_residency=residency,
            input=job_input,
            status=ProcessingJobStatus.QUEUED,
            issued_at=_require_aware_iso(raw["ts"], "ts", job_id),
            issued_by=raw["issuedBy"],
            updated_at=_require_aware_iso(raw["ts"], "ts", job_id),
        )
        self._jobs[job_id] = record
        self._sequence[record.mission_id] = max(
            self._sequence.get(record.mission_id, 0), raw["sequence"]
        )

    def _replay_transition(self, raw: dict[str, Any]) -> None:
        job_id = raw["jobId"]
        current = self._jobs.get(job_id)
        if current is None:
            raise ProcessingJobRecoveryError(f"재생: 미지 jobId 전이 레코드 — jobId={job_id}")
        before = ProcessingJobStatus(raw["before"])
        if before is not current.status:
            raise ProcessingJobRecoveryError(
                f"재생 상태 불일치 — jobId={job_id} before={before.value} "
                f"projection={current.status.value}"
            )
        after = ProcessingJobStatus(raw["after"])
        try:
            assert_job_transition(before, after)
        except IllegalJobTransitionError as exc:
            raise ProcessingJobRecoveryError(
                f"재생: 불법 전이 레코드 — jobId={job_id}: {exc}"
            ) from exc
        self._jobs[job_id] = replace(
            current,
            status=after,
            updated_at=_require_aware_iso(raw["ts"], "ts", job_id),
            terminal_detail=raw.get("detail"),
        )

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    # ── 공개 API ────────────────────────────────────────────────────────
    def issue(
        self, mission_id: str, spec: JobSpec, *, issued_by: str, now: datetime
    ) -> ProcessingJobResult:
        """봉인된 번들 위에 처리 작업을 발급한다.

        게이트 순서는 **싼 것부터**다 — 번들 존재/봉인 → INV-050 → 활성 작업
        중복. 반출 위반을 활성 작업 검사보다 먼저 보는 이유는, 두 번째 요청이
        409 를 받아 "중복만 아니면 통과할 것"으로 오해되지 않게 하기 위해서다.
        """
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return ProcessingJobResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            bundle = self._source_media.get(mission_id)
            if bundle is None:
                return ProcessingJobResult(
                    ProcessingJobVerdict.UNKNOWN_MISSION,
                    detail="해당 임무의 원본 미디어 번들이 없다 — 사진을 먼저 올린다",
                )
            if not bundle.is_sealed or bundle.source_bundle_digest is None:
                return ProcessingJobResult(
                    ProcessingJobVerdict.BUNDLE_NOT_SEALED,
                    detail=(
                        "번들이 아직 봉인되지 않았다 — 봉인 전에는 장수·digest 가 "
                        "확정되지 않아 처리 입력이 성립하지 않는다"
                    ),
                )

            site = self._sites.get(bundle.site_id)
            residency = _residency_of(site)
            if (
                spec.execution_locus is ExecutionLocus.VENDOR_CLOUD
                and not residency.egress_allowed
            ):
                return ProcessingJobResult(
                    ProcessingJobVerdict.EGRESS_NOT_ALLOWED,
                    detail=(
                        f"INV-050 — 현장 {bundle.site_id} 은 데이터 반출이 허용되지 "
                        "않았다(미선언 포함). 벤더 클라우드 처리 작업을 만들 수 없다"
                    ),
                )

            active = self._active_job_locked(mission_id)
            if active is not None:
                if active.spec.fingerprint() == spec.fingerprint():
                    # 같은 사양 재요청 — 네트워크 재시도가 작업을 복제하지 않는다.
                    # journal 에 다시 쓰지 않는다(새로 기록할 사실이 없다).
                    return ProcessingJobResult(
                        ProcessingJobVerdict.ALREADY_ISSUED, record=active
                    )
                return ProcessingJobResult(
                    ProcessingJobVerdict.ACTIVE_JOB_EXISTS,
                    detail=(
                        f"이 임무에 진행 중인 처리 작업이 있다({active.job_id}, "
                        f"{active.status.value}) — 끝나거나 취소된 뒤에 새 작업을 만든다"
                    ),
                )

            job_input = _compute_input(
                media=bundle.media, source_bundle_digest=bundle.source_bundle_digest
            )
            sequence = self._sequence.get(mission_id, 0) + 1
            job_id = build_job_id(mission_id, sequence)
            raw: dict[str, Any] = {
                "kind": "processing-job-issued",
                "ts": _iso(now),
                "jobId": job_id,
                "sequence": sequence,
                "missionId": mission_id,
                "siteId": bundle.site_id,
                "provider": spec.provider.value,
                "engineVersion": spec.engine_version,
                "engineDigest": spec.engine_digest,
                "executionLocus": spec.execution_locus.value,
                "dataResidency": residency.model_dump(by_alias=True, mode="json"),
                "licenseBasis": spec.license_basis.model_dump(by_alias=True, mode="json"),
                "input": job_input.model_dump(by_alias=True, mode="json"),
                "processingParams": spec.processing_params,
                "issuedBy": issued_by,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return ProcessingJobResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            record = ProcessingJobRecord(
                job_id=job_id,
                mission_id=mission_id,
                site_id=bundle.site_id,
                spec=spec,
                data_residency=residency,
                input=job_input,
                status=ProcessingJobStatus.QUEUED,
                issued_at=now,
                issued_by=issued_by,
                updated_at=now,
            )
            self._jobs[job_id] = record
            self._sequence[mission_id] = sequence
            return ProcessingJobResult(ProcessingJobVerdict.ISSUED, record=record)

    def transition(
        self,
        job_id: str,
        target: ProcessingJobStatus,
        *,
        detail: str | None,
        actor: str,
        now: datetime,
    ) -> ProcessingJobResult:
        """작업 상태를 전이한다 — 전이표는 :func:`assert_job_transition` SSOT."""
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return ProcessingJobResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            current = self._jobs.get(job_id)
            if current is None:
                return ProcessingJobResult(
                    ProcessingJobVerdict.UNKNOWN_JOB, detail=_NOT_FOUND_DETAIL
                )
            try:
                assert_job_transition(current.status, target)
            except IllegalJobTransitionError as exc:
                return ProcessingJobResult(
                    ProcessingJobVerdict.ILLEGAL_TRANSITION, detail=str(exc)
                )
            raw: dict[str, Any] = {
                "kind": "processing-job-transitioned",
                "ts": _iso(now),
                "jobId": job_id,
                "before": current.status.value,
                "after": target.value,
                "detail": detail,
                "actor": actor,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return ProcessingJobResult(
                    ProcessingJobVerdict.STORE_UNAVAILABLE, detail=_STORE_UNAVAILABLE_DETAIL
                )
            updated = replace(current, status=target, updated_at=now, terminal_detail=detail)
            self._jobs[job_id] = updated
            return ProcessingJobResult(ProcessingJobVerdict.TRANSITIONED, record=updated)

    def _active_job_locked(self, mission_id: str) -> ProcessingJobRecord | None:
        for record in self._jobs.values():
            if record.mission_id == mission_id and record.status in _ACTIVE_STATUSES:
                return record
        return None

    def get(self, job_id: str) -> ProcessingJobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_for_mission(self, mission_id: str) -> list[ProcessingJobRecord]:
        """``(issued_at, job_id)`` 결정적 정렬 — 목록 순서가 재기동마다 흔들리지 않는다."""
        with self._lock:
            records = [r for r in self._jobs.values() if r.mission_id == mission_id]
        return sorted(records, key=lambda r: (r.issued_at, r.job_id))


def _residency_of(site: Any) -> DataResidency:
    """현장의 반출 선언 — 미선언은 **반출 불가**로 읽는다(fail-closed).

    현장 자체가 조회되지 않는 경우도 같다. 임무 번들이 site_id 를 갖고 있는데
    그 현장이 없다면 원장이 이상한 것이고, 그 상태에서 반출을 허용할 근거는
    어디에도 없다.
    """
    if site is None or site.data_residency is None:
        return DataResidency(egress_allowed=False, jurisdiction="UNDECLARED")
    return DataResidency.model_validate(site.data_residency)


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class LicenseBasisRequest(_CamelModel):
    license_id: str = Field(min_length=1)
    tier: str = Field(min_length=1)
    attribution_required: bool


class ProcessingJobRequest(_CamelModel):
    """발급 요청 — **무엇으로 어디서** 돌릴지만 담는다.

    ``input``·``dataResidency``·``billing``·``status`` 필드가 의도적으로 없다.
    입력은 봉인된 번들이, 반출 허용은 현장이, 과금은 종료 보고가 정한다 —
    ``extra="forbid"`` 가 body 에 실어 보낸 위조를 거부한다(``sites.py``
    ``SiteTransitionRequest`` 의 ``actor`` 와 같은 관용구).
    """

    provider: ProcessingProvider
    engine_version: str = Field(min_length=1)
    engine_digest: str = Field(min_length=1)
    execution_locus: ExecutionLocus
    license_basis: LicenseBasisRequest
    processing_params: dict[str, Any] = Field(default_factory=dict)


class ProcessingJobTransitionRequest(_CamelModel):
    """상태 전이 요청 — ``actor`` 는 Principal 에서만 취득한다."""

    target_status: ProcessingJobStatus
    detail: str | None = None


class ProcessingJobView(_CamelModel):
    """작업 1건의 조회 표현 — 계약 payload + 운영 메타.

    ``contract`` 는 어댑터로 나가는 payload 그대로다(``processing_job_wire_dict``).
    화면이 계약 필드를 다시 조립하지 않게 한 벌로 싣는다 — 재조립하는 순간
    화면이 계약과 갈린다.
    """

    job_id: str
    mission_id: str
    site_id: str
    status: str
    issued_at: datetime
    issued_by: str
    updated_at: datetime
    detail: str | None
    # 발급 시점 화소 합은 업로더 **신고값**의 합이다(B1 은 검증하지 않는다).
    # 이 사실을 필드로 노출해 화면이 "검증된 과금 근거"로 읽지 않게 한다.
    input_verified: bool
    contract: dict[str, Any]


class ProcessingJobListResponse(_CamelModel):
    jobs: list[ProcessingJobView]


class ProcessingJobMutationResponse(_CamelModel):
    verdict: str
    job: ProcessingJobView | None = None
    detail: str | None = None


def _to_view(record: ProcessingJobRecord) -> ProcessingJobView:
    return ProcessingJobView(
        job_id=record.job_id,
        mission_id=record.mission_id,
        site_id=record.site_id,
        status=record.status.value,
        issued_at=record.issued_at,
        issued_by=record.issued_by,
        updated_at=record.updated_at,
        detail=record.terminal_detail,
        # 항상 false(B2 범위) — 전 바이트를 읽어 sha256·해상도를 대조하는 워커가
        # B3 에서 붙으면 그때 참이 될 수 있다. "검증된 척"하는 기본값을 쓰지 않는다.
        input_verified=False,
        contract=processing_job_wire_dict(record.to_contract()),
    )


def build_processing_jobs_router(store: ProcessingJobStore) -> APIRouter:
    router = APIRouter(tags=["processing-jobs"])

    @router.post(
        "/v1/missions/{mission_id}/processing-jobs",
        response_model=ProcessingJobMutationResponse,
        status_code=201,
    )
    def issue_processing_job(
        mission_id: str,
        request: ProcessingJobRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_ISSUE)),  # noqa: B008
    ) -> ProcessingJobMutationResponse:
        spec = JobSpec(
            provider=request.provider,
            engine_version=request.engine_version,
            engine_digest=request.engine_digest,
            execution_locus=request.execution_locus,
            license_basis=LicenseBasis(
                license_id=request.license_basis.license_id,
                tier=request.license_basis.tier,
                attribution_required=request.license_basis.attribution_required,
            ),
            processing_params=request.processing_params,
        )
        result = store.issue(
            mission_id, spec, issued_by=principal.principal_id, now=datetime.now(UTC)
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is ProcessingJobVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return ProcessingJobMutationResponse(
            verdict=result.verdict.value,
            job=_to_view(result.record) if result.record is not None else None,
            detail=result.detail,
        )

    @router.get(
        "/v1/missions/{mission_id}/processing-jobs",
        response_model=ProcessingJobListResponse,
    )
    def list_processing_jobs(
        mission_id: str,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> ProcessingJobListResponse:
        del principal
        return ProcessingJobListResponse(
            jobs=[_to_view(r) for r in store.list_for_mission(mission_id)]
        )

    @router.get("/v1/processing-jobs/{job_id}", response_model=ProcessingJobView)
    def get_processing_job(
        job_id: str,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> ProcessingJobView:
        del principal
        record = store.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
        return _to_view(record)

    @router.post(
        "/v1/processing-jobs/{job_id}/transitions",
        response_model=ProcessingJobMutationResponse,
    )
    def transition_processing_job(
        job_id: str,
        request: ProcessingJobTransitionRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_ISSUE)),  # noqa: B008
    ) -> ProcessingJobMutationResponse:
        result = store.transition(
            job_id,
            request.target_status,
            detail=request.detail,
            actor=principal.principal_id,
            now=datetime.now(UTC),
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is ProcessingJobVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return ProcessingJobMutationResponse(
            verdict=result.verdict.value,
            job=_to_view(result.record) if result.record is not None else None,
            detail=result.detail,
        )

    return router


def mount_processing_jobs(app: FastAPI, store: ProcessingJobStore) -> None:
    """앱에 처리 작업 라우터를 장착한다."""
    app.state.processing_job_store = store
    app.include_router(build_processing_jobs_router(store))


__all__ = [
    "UNMETERED_AT_ISSUE",
    "IllegalJobTransitionError",
    "JobSpec",
    "ProcessingJobListResponse",
    "ProcessingJobMutationResponse",
    "ProcessingJobRecord",
    "ProcessingJobRecoveryError",
    "ProcessingJobRequest",
    "ProcessingJobResult",
    "ProcessingJobStore",
    "ProcessingJobTransitionRequest",
    "ProcessingJobVerdict",
    "ProcessingJobView",
    "assert_job_transition",
    "build_job_id",
    "build_processing_jobs_router",
    "mount_processing_jobs",
]
