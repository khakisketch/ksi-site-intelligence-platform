"""변화 영역 자동 추출 요청 원장 — "이 설계 대비 잔량 리포트에서 변화 영역을 뽑아라" (M4-E).

``design_conformance_requests.py`` 의 형제이되 **훨씬 얇다** — 새로 업로드받을
바이트가 없다. 이 요청은 이미 기록(RECORDED)된 :class:`~ksi_event_contracts.
design_conformance_report.DesignConformanceReport` 의 ``diffRaster`` 를 다시
읽을 뿐이라, 검증할 새 입력도 발급할 새 업로드 URL 도 없다.

## 계산 전에 막는 것 — 딱 하나

**RECORDED 상태의 설계 대비 잔량 리포트만 입력이다.** 그 리포트가 없으면
(``UNKNOWN_DESIGN_CONFORMANCE``) 뽑을 diffRaster 자체가 없다.

## 자동 트리거는 만들지 않는다

이 저장소의 다른 모든 계산 트리거(``comparison_requests``·``design_
conformance_requests``)가 지키는 "``MISSIONS_ISSUE`` 권한자가 매번 지시를
구성한다" 원칙을 그대로 지킨다 — 설계 대비 잔량 기록 성공 시 자동으로 이
요청을 만들지 않는다. 순수 수동 POST 만 연다(M4-E 확정 설계 §8).

## 같은 리포트 재요청은 멱등이다

같은 ``designConformanceId`` 로 다시 POST 하면 이미 있는 요청을 그대로
돌려준다(``ALREADY_REQUESTED``) — 재전송이 요청을 복제하지 않는다.

## 워커 전용 입력 엔드포인트가 반드시 필요한 이유

``auth.py`` 의 ``_PROCESSING_WORKER_PERMISSIONS`` 는 ``PROCESSING_WORK``
하나뿐이고 ``MISSIONS_READ`` 가 없다 — 그래서 기존 사람용 설계 대비 잔량
조회 엔드포인트(``MISSIONS_READ``)를 워커가 부를 수 없다. ``/input`` 은
``PROCESSING_WORK`` + lease 확인으로 그 틈을 메운다(``design_conformance_
requests.py`` 의 ``/input`` 과 같은 자리).

## 추출 기준값은 policy-owned 다 — 요청에 스냅샷을 남기지 않는다

``comparison_policy``/``design_conformance`` 의 ``ComparisonPolicy`` 는 요청
생성 시점에 값으로 스냅샷된다. 이 요청은 그렇게 하지 않는다 — M4-E 확정
설계가 채택한 기반안이 "정책값 안"(추출 파라미터는 고정 정책값이고, 요청은
그 값을 복사하지 않는다)이기 때문이다. ``/input`` 은 매 호출마다
``current_region_extraction_policy()`` 를 새로 불러 준다. 리포트 기록 판정도
같은 함수를 매번 새로 불러 대조한다(``region_extraction_reports.py``) — 값이
바뀌면 그 순간부터 새 기준으로 판정된다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from ksi_event_contracts.design_conformance_report import DiffRasterRef
from ksi_event_contracts.processing_job import ProcessingJobStatus
from ksi_event_contracts.region_extraction_policy import (
    RegionExtractionPolicy,
    current_region_extraction_policy,
)

from ksi_core.api_base import JOURNAL_SEALED_DETAIL, CamelModel, iso_utc
from ksi_core.auth import (
    Permission,
    Principal,
    current_request_organization_id,
    require_permission,
)
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.evidence import DEFAULT_VIEW_TTL, EvidenceStorage, EvidenceStorageError
from ksi_core.leasing import JobLease, LeaseDenialReason, check_lease, is_claimable, next_lease
from ksi_core.processing_jobs import DEFAULT_LEASE_TTL

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.design_conformance_reports import DesignConformanceStore
    from ksi_core.mission_records import MissionStore

_NOT_FOUND_DETAIL = "해당 변화 영역 추출 요청을 찾을 수 없다"

_ACTIVE_STATUSES = frozenset({ProcessingJobStatus.QUEUED, ProcessingJobStatus.RUNNING})

# ``design_conformance_requests._ALLOWED_TRANSITIONS`` 와 같은 표다 — CANCELLED
# 는 여기도 없다(정체된 RUNNING 은 lease 만료로 회수되고, 이 계산은 값싼
# 후처리라 분 단위도 안 된다).
_ALLOWED_TRANSITIONS: dict[ProcessingJobStatus, frozenset[ProcessingJobStatus]] = {
    ProcessingJobStatus.QUEUED: frozenset({ProcessingJobStatus.RUNNING}),
    ProcessingJobStatus.RUNNING: frozenset(
        {ProcessingJobStatus.SUCCEEDED, ProcessingJobStatus.FAILED}
    ),
    ProcessingJobStatus.SUCCEEDED: frozenset(),
    ProcessingJobStatus.FAILED: frozenset(),
}


class IllegalRegionExtractionTransitionError(ValueError):
    """전이표에 없는 변화 영역 추출 요청 상태 전이."""


def assert_region_extraction_transition(
    before: ProcessingJobStatus, after: ProcessingJobStatus
) -> None:
    """전이 적법성 — live 경로와 재생 경로가 같은 함수를 쓴다."""
    if after not in _ALLOWED_TRANSITIONS[before]:
        suffix = (
            " — 종료된 요청의 결론은 고쳐 쓰지 않는다" if not _ALLOWED_TRANSITIONS[before] else ""
        )
        raise IllegalRegionExtractionTransitionError(
            f"변화 영역 추출 요청 상태를 {before.value} 에서 {after.value} 로 바꿀 수 없다{suffix}"
        )


class RegionExtractionRequestVerdict(StrEnum):
    """생성/조회/lease/전이 판정 — 문자열 메시지로 분기하지 않는다."""

    CREATED = "CREATED"
    #: 같은 designConformanceId 의 요청이 이미 있다 — 재전송이 요청을 복제하지 않는다.
    ALREADY_REQUESTED = "ALREADY_REQUESTED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    #: 이 임무에 그 designConformanceId 로 RECORDED 된 설계 대비 잔량 리포트가 없다.
    UNKNOWN_DESIGN_CONFORMANCE = "UNKNOWN_DESIGN_CONFORMANCE"
    UNKNOWN_REQUEST = "UNKNOWN_REQUEST"
    REQUEST_NOT_ACTIVE = "REQUEST_NOT_ACTIVE"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"

    # ── lease ────────────────────────────────────────────────────────────
    LEASED = "LEASED"
    LEASE_RENEWED = "LEASE_RENEWED"
    LEASE_HELD_BY_ANOTHER = "LEASE_HELD_BY_ANOTHER"
    LEASE_REQUIRED = "LEASE_REQUIRED"

    # ── 전이 ─────────────────────────────────────────────────────────────
    TRANSITIONED = "TRANSITIONED"
    ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"

    # ── 입력 ─────────────────────────────────────────────────────────────
    INPUT_READY = "INPUT_READY"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


_STATUS: dict[RegionExtractionRequestVerdict, int] = {
    RegionExtractionRequestVerdict.CREATED: 201,
    RegionExtractionRequestVerdict.ALREADY_REQUESTED: 200,
    RegionExtractionRequestVerdict.UNKNOWN_MISSION: 404,
    RegionExtractionRequestVerdict.UNKNOWN_DESIGN_CONFORMANCE: 404,
    RegionExtractionRequestVerdict.UNKNOWN_REQUEST: 404,
    RegionExtractionRequestVerdict.REQUEST_NOT_ACTIVE: 409,
    RegionExtractionRequestVerdict.STORE_UNAVAILABLE: 503,
    RegionExtractionRequestVerdict.LEASED: 201,
    RegionExtractionRequestVerdict.LEASE_RENEWED: 200,
    RegionExtractionRequestVerdict.LEASE_HELD_BY_ANOTHER: 409,
    RegionExtractionRequestVerdict.LEASE_REQUIRED: 409,
    RegionExtractionRequestVerdict.TRANSITIONED: 200,
    RegionExtractionRequestVerdict.ILLEGAL_TRANSITION: 409,
    RegionExtractionRequestVerdict.INPUT_READY: 200,
    RegionExtractionRequestVerdict.STORAGE_UNAVAILABLE: 503,
}


class RegionExtractionRequestRecoveryError(RuntimeError):
    """region-extraction-requests journal 재생 실패 — 오염된 원장으로 기동하지 않는다."""


def build_region_extraction_request_id(design_conformance_id: str, sequence: int) -> str:
    """``{designConformanceId}-rex{n}`` — M4-E 확정 설계 §8."""
    return f"{design_conformance_id}-rex{sequence}"


def change_region_set_id_of(request_id: str) -> str:
    """리포트 id 를 요청 id 에서 **결정적으로** 도출한다 — 지금은 같은 문자열이다.

    ``design_conformance_id_of`` 와 같은 이유·같은 항등이다:
    :class:`~ksi_event_contracts.change_region_report.ChangeRegionSetReport`
    에는 ``requestId`` 필드가 없으므로, Core 가 제출된 리포트를 어느 요청의
    것인지 되짚는 유일한 경로가 이 도출이다.
    """
    return request_id


@dataclass(frozen=True, slots=True)
class RegionExtractionRequestRecord:
    """변화 영역 추출 요청 1건의 projection — 지시 + 운영 메타."""

    request_id: str
    mission_id: str
    design_conformance_id: str
    status: ProcessingJobStatus
    requested_at: datetime
    requested_by: str
    updated_at: datetime
    detail: str | None = None
    lease: JobLease | None = None

    @property
    def change_region_set_id(self) -> str:
        return change_region_set_id_of(self.request_id)


@dataclass(frozen=True, slots=True)
class RegionExtractionRequestResult:
    verdict: RegionExtractionRequestVerdict
    detail: str | None = None
    record: RegionExtractionRequestRecord | None = None


def _require_tz_aware(value: datetime, *, param: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{param} 은 tz-aware 여야 한다")


def _require_aware_iso(raw: Any, field_name: str, request_id: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None:
        raise RegionExtractionRequestRecoveryError(
            f"재생: {field_name} 이 tz-naive 다 — requestId={request_id}"
        )
    return value


class RegionExtractionRequestStore:
    """``DurableJournal`` 위의 변화 영역 추출 요청 원장 — append-only, 덮어쓰지 않는다."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        mission_store: MissionStore,
        design_conformance_report_store: DesignConformanceStore,
    ) -> None:
        self._journal = journal
        self._mission_store = mission_store
        self._design_conformance_report_store = design_conformance_report_store
        self._lock = threading.Lock()
        self._requests: dict[str, RegionExtractionRequestRecord] = {}
        self._by_design_conformance_id: dict[str, str] = {}
        self._sequence: dict[str, int] = {}
        try:
            self._replay(journal)
        except RegionExtractionRequestRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise RegionExtractionRequestRecoveryError(
                f"region-extraction-requests journal 재생 실패 — 오염된 레코드: {exc}"
            ) from exc

    def _visible_in_request(self, record: RegionExtractionRequestRecord) -> bool:
        """변화 영역 추출 요청도 Mission의 조직 scope 밖에서는 존재하지 않는다."""

        return (
            current_request_organization_id() is None
            or self._mission_store.get(record.mission_id) is not None
        )

    def mission_is_visible(self, mission_id: str) -> bool:
        return self._mission_store.get(mission_id) is not None

    # ── 재생 ─────────────────────────────────────────────────────────────

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw.get("kind")
            if kind == "region-extraction-request-created":
                self._replay_created(raw)
            elif kind == "region-extraction-request-leased":
                self._replay_lease(raw)
            elif kind == "region-extraction-request-transitioned":
                self._replay_transition(raw)
            else:
                raise RegionExtractionRequestRecoveryError(
                    f"알 수 없는 journal 레코드 kind: {kind!r}"
                )

    def _replay_created(self, raw: dict[str, Any]) -> None:
        """생성 레코드 재생 — **live 와 같은 게이트를 다시 태운다.**

        journal 조작으로 "RECORDED 된 적 없는 설계 대비 잔량을 가리키는 요청"이
        되살아나는 경로는 이 재검사가 막는다(``design_conformance_requests.
        _replay_created`` 원칙).
        """
        request_id = raw["requestId"]
        design_conformance_id = raw["designConformanceId"]
        verdict, detail = self._resolve(
            mission_id=raw["missionId"], design_conformance_id=design_conformance_id
        )
        if verdict is not RegionExtractionRequestVerdict.CREATED:
            raise RegionExtractionRequestRecoveryError(
                f"재생: 기록될 수 없는 요청({verdict.value}: {detail}) — requestId={request_id}"
            )
        requested_at = _require_aware_iso(raw["ts"], "ts", request_id)
        record = RegionExtractionRequestRecord(
            request_id=request_id,
            mission_id=raw["missionId"],
            design_conformance_id=design_conformance_id,
            status=ProcessingJobStatus.QUEUED,
            requested_at=requested_at,
            requested_by=raw["requestedBy"],
            updated_at=requested_at,
        )
        self._project(record)
        sequence = int(request_id.rsplit("-rex", 1)[-1])
        self._sequence[design_conformance_id] = max(
            self._sequence.get(design_conformance_id, 0), sequence
        )

    def _replay_lease(self, raw: dict[str, Any]) -> None:
        request_id = raw["requestId"]
        record = self._requests.get(request_id)
        if record is None:
            raise RegionExtractionRequestRecoveryError(
                f"재생: 미지 requestId lease 레코드 — {request_id}"
            )
        if record.status not in _ACTIVE_STATUSES:
            raise RegionExtractionRequestRecoveryError(
                f"재생: 종료된 요청({record.status.value})에 lease 레코드가 있다 — {request_id}"
            )
        self._requests[request_id] = replace(
            record,
            lease=JobLease(
                worker_id=raw["workerId"],
                granted_at=_require_aware_iso(raw["ts"], "ts", request_id),
                expires_at=_require_aware_iso(raw["expiresAt"], "expiresAt", request_id),
            ),
        )

    def _replay_transition(self, raw: dict[str, Any]) -> None:
        request_id = raw["requestId"]
        record = self._requests.get(request_id)
        if record is None:
            raise RegionExtractionRequestRecoveryError(
                f"재생: 미지 requestId 전이 레코드 — {request_id}"
            )
        after = ProcessingJobStatus(raw["targetStatus"])
        assert_region_extraction_transition(record.status, after)
        self._requests[request_id] = replace(
            record,
            status=after,
            detail=raw.get("detail"),
            updated_at=_require_aware_iso(raw["ts"], "ts", request_id),
        )

    def _project(self, record: RegionExtractionRequestRecord) -> None:
        self._requests[record.request_id] = record
        self._by_design_conformance_id[record.design_conformance_id] = record.request_id

    # ── 생성 게이트 (live·재생 공유) ─────────────────────────────────────

    def _resolve(
        self, *, mission_id: str, design_conformance_id: str
    ) -> tuple[RegionExtractionRequestVerdict, str | None]:
        if self._mission_store.get(mission_id) is None:
            return (
                RegionExtractionRequestVerdict.UNKNOWN_MISSION,
                "발급된 적 없는 임무에는 변화 영역 추출 요청을 만들 수 없다",
            )
        entry = self._design_conformance_report_store.get(mission_id, design_conformance_id)
        if entry is None:
            return (
                RegionExtractionRequestVerdict.UNKNOWN_DESIGN_CONFORMANCE,
                f"designConformanceId={design_conformance_id!r} 인 설계 대비 잔량 리포트가 "
                "이 임무에 기록돼 있지 않다 — 뽑을 diffRaster 자체가 없다",
            )
        return RegionExtractionRequestVerdict.CREATED, None

    # ── live 경로 ────────────────────────────────────────────────────────

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def create(
        self,
        mission_id: str,
        *,
        design_conformance_id: str,
        requested_by: str,
        now: datetime,
    ) -> RegionExtractionRequestResult:
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return RegionExtractionRequestResult(
                    RegionExtractionRequestVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            verdict, detail = self._resolve(
                mission_id=mission_id, design_conformance_id=design_conformance_id
            )
            if verdict is not RegionExtractionRequestVerdict.CREATED:
                return RegionExtractionRequestResult(verdict, detail=detail)

            existing_id = self._by_design_conformance_id.get(design_conformance_id)
            if existing_id is not None:
                return RegionExtractionRequestResult(
                    RegionExtractionRequestVerdict.ALREADY_REQUESTED,
                    detail="이 설계 대비 잔량 리포트의 변화 영역 추출 요청이 이미 있다",
                    record=self._requests[existing_id],
                )

            sequence = self._sequence.get(design_conformance_id, 0) + 1
            request_id = build_region_extraction_request_id(design_conformance_id, sequence)
            record = RegionExtractionRequestRecord(
                request_id=request_id,
                mission_id=mission_id,
                design_conformance_id=design_conformance_id,
                status=ProcessingJobStatus.QUEUED,
                requested_at=now,
                requested_by=requested_by,
                updated_at=now,
            )
            raw = {
                "kind": "region-extraction-request-created",
                "ts": iso_utc(now),
                "requestId": request_id,
                "missionId": mission_id,
                "designConformanceId": design_conformance_id,
                "requestedBy": requested_by,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return RegionExtractionRequestResult(
                    RegionExtractionRequestVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            self._project(record)
            self._sequence[design_conformance_id] = sequence
            return RegionExtractionRequestResult(
                RegionExtractionRequestVerdict.CREATED, record=record
            )

    def get(self, request_id: str) -> RegionExtractionRequestRecord | None:
        with self._lock:
            record = self._requests.get(request_id)
        return record if record is not None and self._visible_in_request(record) else None

    def get_by_change_region_set_id(
        self, change_region_set_id: str
    ) -> RegionExtractionRequestRecord | None:
        """리포트가 가리키는 요청 — 도출이 한 곳에만 있게 하는 관문(``design_
        conformance_requests.get_by_design_conformance_id`` 와 같은 자리)."""
        return self.get(change_region_set_id)

    def list_for_mission(self, mission_id: str) -> list[RegionExtractionRequestRecord]:
        if (
            current_request_organization_id() is not None
            and self._mission_store.get(mission_id) is None
        ):
            return []
        with self._lock:
            records = [r for r in self._requests.values() if r.mission_id == mission_id]
        return sorted(records, key=lambda r: (r.requested_at, r.request_id), reverse=True)

    def list_pending(
        self, *, now: datetime, limit: int = 50
    ) -> list[RegionExtractionRequestRecord]:
        """``QUEUED`` + lease 만료된 ``RUNNING`` — ``leasing.is_claimable`` 재사용."""
        if limit < 0:
            raise ValueError(f"limit 은 음수일 수 없다: {limit}")
        with self._lock:
            records = [
                r for r in self._requests.values() if is_claimable(r.status, r.lease, now)
            ]
        if current_request_organization_id() is not None:
            records = [r for r in records if self._visible_in_request(r)]
        return sorted(records, key=lambda r: (r.requested_at, r.request_id))[:limit]

    @staticmethod
    def _check_lease_locked(
        record: RegionExtractionRequestRecord, *, worker_id: str, now: datetime
    ) -> tuple[RegionExtractionRequestVerdict, str] | None:
        denial = check_lease(record.lease, worker_id=worker_id, now=now)
        if denial is LeaseDenialReason.MISSING_OR_EXPIRED:
            return (
                RegionExtractionRequestVerdict.LEASE_REQUIRED,
                "이 요청의 lease 를 먼저 잡아야 한다",
            )
        if denial is LeaseDenialReason.HELD_BY_ANOTHER:
            assert record.lease is not None  # noqa: S101 -- HELD_BY_ANOTHER 는 lease 가 있을 때만
            return (
                RegionExtractionRequestVerdict.LEASE_HELD_BY_ANOTHER,
                f"다른 워커({record.lease.worker_id})가 {iso_utc(record.lease.expires_at)} 까지 "
                "이 요청을 쥐고 있다 — 만료 후 다시 시도한다",
            )
        return None

    def acquire_lease(
        self,
        request_id: str,
        *,
        worker_id: str,
        now: datetime,
        ttl: timedelta = DEFAULT_LEASE_TTL,
    ) -> RegionExtractionRequestResult:
        """요청 하나를 쥔다. 같은 워커의 재호출은 갱신(heartbeat)."""
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return RegionExtractionRequestResult(
                    RegionExtractionRequestVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            record = self._requests.get(request_id)
            if record is None or not self._visible_in_request(record):
                return RegionExtractionRequestResult(
                    RegionExtractionRequestVerdict.UNKNOWN_REQUEST, detail=_NOT_FOUND_DETAIL
                )
            if record.status not in _ACTIVE_STATUSES:
                return RegionExtractionRequestResult(
                    RegionExtractionRequestVerdict.REQUEST_NOT_ACTIVE,
                    detail=f"요청이 {record.status.value} 상태다 — 끝난 요청은 잡을 수 없다",
                )
            current = record.lease
            denial = check_lease(current, worker_id=worker_id, now=now)
            renewing = current is not None and denial is None
            if denial is LeaseDenialReason.HELD_BY_ANOTHER:
                assert current is not None  # noqa: S101
                return RegionExtractionRequestResult(
                    RegionExtractionRequestVerdict.LEASE_HELD_BY_ANOTHER,
                    detail=(
                        f"다른 워커({current.worker_id})가 {iso_utc(current.expires_at)} 까지 "
                        "이 요청을 쥐고 있다 — 만료 후 다시 시도한다"
                    ),
                    record=record,
                )
            new_lease = next_lease(
                worker_id=worker_id,
                now=now,
                ttl=ttl,
                granted_at=current.granted_at if renewing and current else None,
            )
            raw = {
                "kind": "region-extraction-request-leased",
                "ts": iso_utc(now),
                "requestId": request_id,
                "workerId": worker_id,
                "expiresAt": iso_utc(new_lease.expires_at),
                "renewal": renewing,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return RegionExtractionRequestResult(
                    RegionExtractionRequestVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            updated = replace(record, lease=new_lease)
            self._requests[request_id] = updated
            return RegionExtractionRequestResult(
                RegionExtractionRequestVerdict.LEASE_RENEWED
                if renewing
                else RegionExtractionRequestVerdict.LEASED,
                record=updated,
            )

    def transition(
        self,
        request_id: str,
        target: ProcessingJobStatus,
        *,
        detail: str | None,
        actor: str,
        now: datetime,
    ) -> RegionExtractionRequestResult:
        _require_tz_aware(now, param="now")
        with self._lock:
            if self._journal.sealed_reason is not None:
                return RegionExtractionRequestResult(
                    RegionExtractionRequestVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            record = self._requests.get(request_id)
            if record is None or not self._visible_in_request(record):
                return RegionExtractionRequestResult(
                    RegionExtractionRequestVerdict.UNKNOWN_REQUEST, detail=_NOT_FOUND_DETAIL
                )
            denied = self._check_lease_locked(record, worker_id=actor, now=now)
            if denied is not None:
                verdict, detail_msg = denied
                return RegionExtractionRequestResult(verdict, detail=detail_msg, record=record)
            try:
                assert_region_extraction_transition(record.status, target)
            except IllegalRegionExtractionTransitionError as exc:
                return RegionExtractionRequestResult(
                    RegionExtractionRequestVerdict.ILLEGAL_TRANSITION,
                    detail=str(exc),
                    record=record,
                )
            raw = {
                "kind": "region-extraction-request-transitioned",
                "ts": iso_utc(now),
                "requestId": request_id,
                "targetStatus": target.value,
                "detail": detail,
                "actor": actor,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return RegionExtractionRequestResult(
                    RegionExtractionRequestVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            updated = replace(record, status=target, detail=detail, updated_at=now)
            self._requests[request_id] = updated
            return RegionExtractionRequestResult(
                RegionExtractionRequestVerdict.TRANSITIONED, record=updated
            )


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class RegionExtractionRequestView(CamelModel):
    """요청 1건의 조회 표현."""

    request_id: str
    change_region_set_id: str
    mission_id: str
    design_conformance_id: str
    status: ProcessingJobStatus
    requested_at: datetime
    requested_by: str
    updated_at: datetime
    detail: str | None
    lease_worker_id: str | None
    lease_expires_at: datetime | None


class RegionExtractionRequestMutationResponse(CamelModel):
    verdict: str
    request: RegionExtractionRequestView | None = None
    detail: str | None = None


class RegionExtractionRequestListResponse(CamelModel):
    requests: list[RegionExtractionRequestView]


class PendingRegionExtractionRequestView(CamelModel):
    """워커가 다음에 잡을 후보 1건 — 최소 노출(``PendingComparisonRequestView`` 동형)."""

    request_id: str
    requested_at: datetime


class PendingRegionExtractionRequestListResponse(CamelModel):
    requests: list[PendingRegionExtractionRequestView]


class RegionExtractionTransitionRequest(CamelModel):
    target_status: ProcessingJobStatus
    detail: str | None = None


class RegionExtractionInputView(CamelModel):
    """워커가 실제로 계산하는 데 필요한 것 — diffRaster presigned GET + 그 참조 자체.

    이 요청은 새 래스터를 만들지 않는다 — ``diffRaster``·``diffRasterId``·
    ``thresholdM``·``crs`` 는 전부 원본 설계 대비 잔량 리포트에서 그대로 가져온
    값이다. ``extractionPolicy`` 만 다르다 — policy-owned 기반안에 따라 매
    호출마다 ``current_region_extraction_policy()`` 를 새로 계산해 준다(모듈
    docstring).
    """

    request_id: str
    mission_id: str
    status: ProcessingJobStatus
    design_conformance_id: str
    change_region_set_id: str
    diff_raster_id: str
    diff_raster_url: str
    diff_raster: DiffRasterRef
    threshold_m: float
    crs: str
    extraction_policy: RegionExtractionPolicy


class RegionExtractionInputResponse(CamelModel):
    verdict: str
    input: RegionExtractionInputView | None = None
    detail: str | None = None


def _to_view(record: RegionExtractionRequestRecord) -> RegionExtractionRequestView:
    return RegionExtractionRequestView(
        request_id=record.request_id,
        change_region_set_id=record.change_region_set_id,
        mission_id=record.mission_id,
        design_conformance_id=record.design_conformance_id,
        status=record.status,
        requested_at=record.requested_at,
        requested_by=record.requested_by,
        updated_at=record.updated_at,
        detail=record.detail,
        lease_worker_id=record.lease.worker_id if record.lease is not None else None,
        lease_expires_at=record.lease.expires_at if record.lease is not None else None,
    )


def build_region_extraction_requests_router(
    store: RegionExtractionRequestStore,
    design_conformance_report_store: DesignConformanceStore,
    storage: EvidenceStorage,
) -> APIRouter:
    router = APIRouter(tags=["region-extraction-requests"])

    @router.post(
        "/v1/missions/{mission_id}/design-conformance/{design_conformance_id}"
        "/region-extraction-requests",
        response_model=RegionExtractionRequestMutationResponse,
        status_code=201,
    )
    def create_region_extraction_request(
        mission_id: str,
        design_conformance_id: str,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_ISSUE)),  # noqa: B008
    ) -> RegionExtractionRequestMutationResponse:
        """"이 설계 대비 잔량 리포트에서 변화 영역을 뽑아라"는 지시 접수 —
        **사람이 발급**한다(자동 트리거 없음, 모듈 docstring)."""
        result = store.create(
            mission_id,
            design_conformance_id=design_conformance_id,
            requested_by=principal.principal_id,
            now=datetime.now(UTC),
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is RegionExtractionRequestVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return RegionExtractionRequestMutationResponse(
            verdict=result.verdict.value,
            request=_to_view(result.record) if result.record is not None else None,
            detail=result.detail,
        )

    @router.get(
        "/v1/missions/{mission_id}/region-extraction-requests",
        response_model=RegionExtractionRequestListResponse,
    )
    def list_region_extraction_requests(
        mission_id: str,
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> RegionExtractionRequestListResponse:
        """그 임무의 변화 영역 추출 요청 이력(최신 우선)."""
        if not store.mission_is_visible(mission_id):
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
        return RegionExtractionRequestListResponse(
            requests=[_to_view(r) for r in store.list_for_mission(mission_id)]
        )

    @router.get(
        "/v1/region-extraction-requests",
        response_model=PendingRegionExtractionRequestListResponse,
    )
    def list_pending_region_extraction_requests(
        limit: int = Query(default=50, ge=1, le=200),  # noqa: B008
        _principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> PendingRegionExtractionRequestListResponse:
        """워커 pull 표면 — ``QUEUED`` + lease 만료된 ``RUNNING``, 오래된 것부터(FIFO)."""
        return PendingRegionExtractionRequestListResponse(
            requests=[
                PendingRegionExtractionRequestView(
                    request_id=r.request_id, requested_at=r.requested_at
                )
                for r in store.list_pending(now=datetime.now(UTC), limit=limit)
            ]
        )

    @router.post(
        "/v1/region-extraction-requests/{request_id}/lease",
        response_model=RegionExtractionRequestMutationResponse,
        status_code=201,
    )
    def acquire_region_extraction_lease(
        request_id: str,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> RegionExtractionRequestMutationResponse:
        result = store.acquire_lease(
            request_id, worker_id=principal.principal_id, now=datetime.now(UTC)
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is RegionExtractionRequestVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return RegionExtractionRequestMutationResponse(
            verdict=result.verdict.value,
            request=_to_view(result.record) if result.record is not None else None,
            detail=result.detail,
        )

    @router.get(
        "/v1/region-extraction-requests/{request_id}/input",
        response_model=RegionExtractionInputResponse,
    )
    def get_region_extraction_input(
        request_id: str,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> RegionExtractionInputResponse:
        """워커가 diffRaster 바이트를 읽는 유일한 경로 — lease 를 쥔 워커만 통과한다."""
        record = store.get(request_id)
        if record is None:
            response.status_code = 404
            return RegionExtractionInputResponse(
                verdict=RegionExtractionRequestVerdict.UNKNOWN_REQUEST.value,
                detail=_NOT_FOUND_DETAIL,
            )
        denied = RegionExtractionRequestStore._check_lease_locked(
            record, worker_id=principal.principal_id, now=datetime.now(UTC)
        )
        if denied is not None:
            verdict, detail = denied
            response.status_code = _STATUS[verdict]
            return RegionExtractionInputResponse(verdict=verdict.value, detail=detail)

        entry = design_conformance_report_store.get(
            record.mission_id, record.design_conformance_id
        )
        if entry is None:  # pragma: no cover -- 생성 게이트가 이미 존재를 보장했다(불변 원장)
            response.status_code = _STATUS[
                RegionExtractionRequestVerdict.UNKNOWN_DESIGN_CONFORMANCE
            ]
            return RegionExtractionInputResponse(
                verdict=RegionExtractionRequestVerdict.UNKNOWN_DESIGN_CONFORMANCE.value,
                detail="참조하는 설계 대비 잔량 리포트를 더 이상 찾을 수 없다",
            )
        object_key = design_conformance_report_store.diff_raster_object_key(entry)
        if object_key is None:  # pragma: no cover -- 기록된 리포트는 항상 요청을 갖는다
            response.status_code = 404
            return RegionExtractionInputResponse(
                verdict=RegionExtractionRequestVerdict.UNKNOWN_DESIGN_CONFORMANCE.value,
                detail="차분 래스터의 자리를 찾을 수 없다",
            )
        try:
            diff_raster_url = storage.presigned_get(object_key, ttl=DEFAULT_VIEW_TTL)
        except EvidenceStorageError:
            response.status_code = _STATUS[RegionExtractionRequestVerdict.STORAGE_UNAVAILABLE]
            response.headers["Retry-After"] = "30"
            return RegionExtractionInputResponse(
                verdict=RegionExtractionRequestVerdict.STORAGE_UNAVAILABLE.value,
                detail="차분 래스터 다운로드 URL 발급에 실패했다 — 잠시 후 재시도한다",
            )

        return RegionExtractionInputResponse(
            verdict=RegionExtractionRequestVerdict.INPUT_READY.value,
            input=RegionExtractionInputView(
                request_id=record.request_id,
                mission_id=record.mission_id,
                status=record.status,
                design_conformance_id=record.design_conformance_id,
                change_region_set_id=record.change_region_set_id,
                diff_raster_id=entry.report.diff_raster.diff_raster_id,
                diff_raster_url=diff_raster_url,
                diff_raster=entry.report.diff_raster,
                threshold_m=entry.report.diff_raster.threshold_m,
                crs=entry.report.crs,
                extraction_policy=current_region_extraction_policy(),
            ),
        )

    @router.post(
        "/v1/region-extraction-requests/{request_id}/transitions",
        response_model=RegionExtractionRequestMutationResponse,
    )
    def transition_region_extraction_request(
        request_id: str,
        request: RegionExtractionTransitionRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> RegionExtractionRequestMutationResponse:
        """워커만 전이한다 — RUNNING/SUCCEEDED/FAILED 는 계산을 돌린 주체만 아는 사실이다."""
        result = store.transition(
            request_id,
            request.target_status,
            detail=request.detail,
            actor=principal.principal_id,
            now=datetime.now(UTC),
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is RegionExtractionRequestVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return RegionExtractionRequestMutationResponse(
            verdict=result.verdict.value,
            request=_to_view(result.record) if result.record is not None else None,
            detail=result.detail,
        )

    return router


def mount_region_extraction_requests(
    app: FastAPI,
    store: RegionExtractionRequestStore,
    design_conformance_report_store: DesignConformanceStore,
    storage: EvidenceStorage,
) -> None:
    app.include_router(
        build_region_extraction_requests_router(store, design_conformance_report_store, storage)
    )


__all__ = [
    "PendingRegionExtractionRequestListResponse",
    "PendingRegionExtractionRequestView",
    "RegionExtractionInputResponse",
    "RegionExtractionInputView",
    "RegionExtractionRequestListResponse",
    "RegionExtractionRequestMutationResponse",
    "RegionExtractionRequestRecord",
    "RegionExtractionRequestRecoveryError",
    "RegionExtractionRequestResult",
    "RegionExtractionRequestStore",
    "RegionExtractionRequestVerdict",
    "RegionExtractionRequestView",
    "RegionExtractionTransitionRequest",
    "IllegalRegionExtractionTransitionError",
    "assert_region_extraction_transition",
    "build_region_extraction_request_id",
    "build_region_extraction_requests_router",
    "change_region_set_id_of",
    "mount_region_extraction_requests",
]
