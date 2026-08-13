"""체적 변화 리포트 원장 — 구역별 절토·성토의 수신·조회 (ADR-KSI-016 D3).

## change_detection.py 를 확장하지 않고 형제로 둔 이유

두 모듈은 골격이 같다(journal 위 append-only 원장 + 산출물 참조 검증 + live·
재생 공유 게이트). 그런데 **검증 대상과 결과 형태가 다르다**:
``ChangeDetectionStore`` 는 입력이 ``point_cloud`` 인지 보고, 여기는 ``dsm``
인지 본다. 결과도 ``candidateRatio`` vs ``m³`` 로 근본적으로 다르다.

한 저장소에 얹으면 kind 검사와 결과 해석에 조건분기가 섞이고, 소비자는 어느
필드가 언제 유효한지 알 수 없게 된다. 검증된 골격을 복제하는 쪽이 설계
리스크가 낮다 — 복제한 것은 구조지 판단이 아니다.

## 사람은 체적을 주장할 수 없다

수신 권한이 ``PROCESSING_WORK`` 다(어느 Role 에도 매핑되지 않는다). "이 구역이
이만큼 깎였다"를 손으로 원장에 넣는 경로를 만들지 않는다 — 그 숫자는 정산·
분쟁의 근거가 될 수 있고, 근거가 될 수 있는 값일수록 계산된 것이어야 한다
(``defect_candidates.py``·``change_detection.py`` 와 동일 원칙).

## 재방문·재비행을 트리거하지 않는다

이 원장은 사실을 적을 뿐이다. 체적이 크게 변했다고 임무를 자동 발급하지
않는다(ADR-KSI-016 D8 — 폐루프 자동화는 다음 마일스톤).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.volume_change_report import VolumeChangeReport

from ksi_core.api_base import (
    JOURNAL_APPEND_FAILED_DETAIL,
    JOURNAL_SEALED_DETAIL,
    CamelModel,
    iso_utc,
)
from ksi_core.artifact_refs import ArtifactRefIssue, verify_artifact_pair
from ksi_core.auth import Permission, Principal, require_permission
from ksi_core.durable_journal import DurableJournal, JournalSealedError

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.mission_records import MissionStore
    from ksi_core.processing_jobs import ProcessingJobStore

logger = logging.getLogger(__name__)

# 목록 조회 기본 상한. 구현이 아직 in-memory 전량 스캔이어도 wire 계약에 페이지
# 개념을 지금 둔다 — 무제한 반환을 계약으로 굳히면 저장소 교체가 파괴적 변경이
# 된다(``ProcessingJobStore.list_for_site`` 와 같은 이유).
DEFAULT_HISTORY_LIMIT = 50


class VolumeChangeVerdict(StrEnum):
    """수신 판정. ``RECORDED`` 만 durable 기록 성공이다."""

    RECORDED = "RECORDED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    UNKNOWN_ARTIFACT = "UNKNOWN_ARTIFACT"
    ARTIFACT_KIND_MISMATCH = "ARTIFACT_KIND_MISMATCH"
    DUPLICATE_REPORT_ID = "DUPLICATE_REPORT_ID"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_STATUS: dict[VolumeChangeVerdict, int] = {
    VolumeChangeVerdict.RECORDED: 201,
    VolumeChangeVerdict.UNKNOWN_MISSION: 404,
    VolumeChangeVerdict.UNKNOWN_ARTIFACT: 422,
    VolumeChangeVerdict.ARTIFACT_KIND_MISMATCH: 422,
    VolumeChangeVerdict.DUPLICATE_REPORT_ID: 409,
    VolumeChangeVerdict.STORE_UNAVAILABLE: 503,
}


class VolumeChangeRecoveryError(RuntimeError):
    """volume-change journal 재생 실패 — 오염된 원장으로 기동하지 않는다."""


@dataclass(frozen=True, slots=True)
class VolumeChangeRecordResult:
    verdict: VolumeChangeVerdict
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class RecordedVolumeChange:
    report: VolumeChangeReport
    reported_by: str | None
    recorded_at: datetime


class VolumeChangeStore:
    """``DurableJournal`` 위의 체적 변화 원장 — append-only, 덮어쓰지 않는다.

    같은 임무에 리포트가 여러 번 올 수 있다(다른 baseline 과의 비교, 임계값
    변경 재계산) — 전부 남기고 조회는 최신을 낸다.
    """

    def __init__(
        self,
        journal: DurableJournal,
        *,
        mission_store: MissionStore,
        processing_job_store: ProcessingJobStore,
    ) -> None:
        self._journal = journal
        self._mission_store = mission_store
        self._processing_job_store = processing_job_store
        self._lock = threading.Lock()
        self._by_mission: dict[str, list[RecordedVolumeChange]] = {}
        self._ids_by_mission: dict[str, dict[str, VolumeChangeReport]] = {}
        try:
            self._replay(journal)
        except VolumeChangeRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise VolumeChangeRecoveryError(
                f"volume-change journal 재생 실패 — 오염된 레코드: {exc}"
            ) from exc

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw.get("kind")
            if kind == "volume-change-rejected":
                continue
            if kind not in (None, "volume-change-recorded"):
                raise VolumeChangeRecoveryError(f"알 수 없는 journal 레코드 kind: {kind!r}")
            mission_id = raw["missionId"]
            report = VolumeChangeReport.model_validate(raw["report"])
            # 재생도 live 와 같은 게이트를 태운다 — journal 조작으로 해석 불가능한
            # 리포트가 되살아나는 경로를 막는다.
            verdict, detail = self._judge_references(report)
            if verdict is not VolumeChangeVerdict.RECORDED:
                raise VolumeChangeRecoveryError(
                    f"재생: 기록될 수 없는 리포트({verdict.value}: {detail}) — "
                    f"missionId={mission_id} volumeChangeId={report.volume_change_id}"
                )
            self._project(
                mission_id, report, raw.get("reportedBy"), datetime.fromisoformat(raw["ts"])
            )

    def _project(
        self,
        mission_id: str,
        report: VolumeChangeReport,
        reported_by: str | None,
        recorded_at: datetime,
    ) -> None:
        self._by_mission.setdefault(mission_id, []).append(
            RecordedVolumeChange(
                report=report, reported_by=reported_by, recorded_at=recorded_at
            )
        )
        self._ids_by_mission.setdefault(mission_id, {})[report.volume_change_id] = report

    def _judge_references(
        self, report: VolumeChangeReport
    ) -> tuple[VolumeChangeVerdict, str | None]:
        """``baseline``/``current`` 가 실제 등록된 DSM 산출물인가.

        자기 비교는 계약 모델이 이미 막는다(``VolumeChangeReport`` 의
        ``_check_self_consistency``) — 여기서 다시 보지 않는 이유는 검사가 두
        곳에 있으면 한쪽만 고쳐지기 때문이다.

        live 수신과 journal 재생이 같은 함수를 쓴다 — 산출물 존재·kind 검증은
        ``artifact_refs.verify_artifact_pair`` 로 ``change_detection.py`` 와
        공유한다.
        """
        issue = verify_artifact_pair(
            self._processing_job_store,
            report.baseline,
            report.current,
            required_kind=ProcessingArtifactKind.DSM,
            kind_mismatch_detail=lambda label, kind: (
                f"{label} 산출물의 kind 가 {kind.value!r} 다 — 체적 차분의"
                " 입력은 dsm 이어야 한다(표면 함수 z=f(x,y) 의 적분이다)"
            ),
        )
        if issue is None:
            return VolumeChangeVerdict.RECORDED, None
        reason, detail = issue
        verdict = (
            VolumeChangeVerdict.UNKNOWN_ARTIFACT
            if reason is ArtifactRefIssue.UNKNOWN_ARTIFACT
            else VolumeChangeVerdict.ARTIFACT_KIND_MISMATCH
        )
        return verdict, detail

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def record(
        self,
        mission_id: str,
        report: VolumeChangeReport,
        *,
        now: datetime,
        reported_by: str | None = None,
    ) -> VolumeChangeRecordResult:
        with self._lock:
            if self._journal.sealed_reason is not None:
                return VolumeChangeRecordResult(
                    VolumeChangeVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            if self._mission_store.get(mission_id) is None:
                return self._reject(
                    mission_id,
                    report,
                    now,
                    reported_by,
                    VolumeChangeVerdict.UNKNOWN_MISSION,
                    "발급된 적 없는 임무의 체적 리포트는 받지 않는다",
                )
            existing = self._ids_by_mission.get(mission_id, {}).get(report.volume_change_id)
            if existing is not None:
                if existing == report:
                    return VolumeChangeRecordResult(
                        VolumeChangeVerdict.RECORDED,
                        detail="이미 같은 내용으로 기록돼 있다(멱등 재전송)",
                    )
                return self._reject(
                    mission_id,
                    report,
                    now,
                    reported_by,
                    VolumeChangeVerdict.DUPLICATE_REPORT_ID,
                    f"volumeChangeId={report.volume_change_id!r} 는 이미 다른 내용으로"
                    " 기록됐다 — 같은 id 로 다른 결과를 덮어쓸 수 없다",
                )
            verdict, detail = self._judge_references(report)
            if verdict is not VolumeChangeVerdict.RECORDED:
                return self._reject(mission_id, report, now, reported_by, verdict, detail)

            record = {
                "kind": "volume-change-recorded",
                "ts": iso_utc(now),
                "missionId": mission_id,
                "reportedBy": reported_by,
                "report": report.model_dump(by_alias=True, mode="json", exclude_none=False),
            }
            try:
                self._journal.append(record)
            except JournalSealedError:
                return VolumeChangeRecordResult(
                    VolumeChangeVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_APPEND_FAILED_DETAIL,
                )
            self._project(mission_id, report, reported_by, now)
            return VolumeChangeRecordResult(VolumeChangeVerdict.RECORDED)

    def _reject(
        self,
        mission_id: str,
        report: VolumeChangeReport,
        now: datetime,
        reported_by: str | None,
        verdict: VolumeChangeVerdict,
        detail: str | None,
    ) -> VolumeChangeRecordResult:
        record = {
            "kind": "volume-change-rejected",
            "ts": iso_utc(now),
            "missionId": mission_id,
            "volumeChangeId": report.volume_change_id,
            "verdict": verdict.value,
            "detail": detail,
            "reportedBy": reported_by,
        }
        try:
            self._journal.append(record)
        except JournalSealedError:
            return VolumeChangeRecordResult(
                VolumeChangeVerdict.STORE_UNAVAILABLE,
                detail=JOURNAL_APPEND_FAILED_DETAIL,
            )
        return VolumeChangeRecordResult(verdict, detail=detail)

    def latest(self, mission_id: str) -> RecordedVolumeChange | None:
        with self._lock:
            recorded = self._by_mission.get(mission_id)
            return recorded[-1] if recorded else None

    def history(
        self, mission_id: str, *, limit: int | None = None
    ) -> list[RecordedVolumeChange]:
        """최신이 먼저. ``limit`` 은 위쪽(최신)부터 센다."""
        if limit is not None and limit < 0:
            raise ValueError(f"limit 은 음수일 수 없다: {limit}")
        with self._lock:
            recorded = list(reversed(self._by_mission.get(mission_id, ())))
        return recorded if limit is None else recorded[:limit]


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class VolumeChangeResponse(CamelModel):
    verdict: str
    detail: str | None


class VolumeChangeEntry(CamelModel):
    report: dict[str, Any]
    reported_by: str | None
    recorded_at: datetime


class VolumeChangeListView(CamelModel):
    """그 임무의 체적 리포트 이력 — 최신이 먼저.

    ``totalNetM3`` 는 **최신 리포트의** 전 구역 순변화다. 화면이 구역 배열을
    직접 합산하지 않게 서버가 계산해 준다 — 합산 규칙이 두 곳에 있으면 한쪽만
    고쳐지는 순간 화면 숫자와 원장이 갈라진다.
    """

    mission_id: str
    report_count: int
    latest_total_net_m3: float | None
    reports: list[VolumeChangeEntry]


def build_volume_reports_router(store: VolumeChangeStore) -> APIRouter:
    router = APIRouter(prefix="/v1/missions", tags=["volume-changes"])

    @router.post("/{mission_id}/volume-changes", status_code=201)
    def submit_volume_change(
        mission_id: str,
        report: VolumeChangeReport,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> VolumeChangeResponse:
        """체적 리포트 접수 — **처리 워커만** 올린다.

        사람이 손으로 "이 구역이 이만큼 깎였다"를 원장에 주장할 수 없다. 이
        숫자는 정산·분쟁의 근거가 될 수 있고, 그럴수록 계산된 것이어야 한다.
        """
        outcome = store.record(
            mission_id, report, now=datetime.now(UTC), reported_by=principal.principal_id
        )
        response.status_code = _STATUS[outcome.verdict]
        if outcome.verdict is VolumeChangeVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return VolumeChangeResponse(verdict=outcome.verdict.value, detail=outcome.detail)

    @router.get("/{mission_id}/volume-changes", response_model=VolumeChangeListView)
    def list_volume_changes(
        mission_id: str,
        limit: int = Query(default=DEFAULT_HISTORY_LIMIT, ge=1, le=200),  # noqa: B008
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> VolumeChangeListView:
        """그 임무의 체적 리포트 이력(최신 우선).

        결과가 없으면 404 다 — 빈 목록을 주면 "아직 계산 안 됨"과 "변화가
        없음"을 소비자가 구분할 수 없다(``change_detection.py`` 와 동일).
        """
        entries = store.history(mission_id, limit=limit)
        if not entries:
            raise HTTPException(
                status_code=404, detail="해당 임무의 체적 변화 리포트를 찾을 수 없다"
            )
        return VolumeChangeListView(
            mission_id=mission_id,
            report_count=len(store.history(mission_id)),
            latest_total_net_m3=entries[0].report.total_net_m3,
            reports=[
                VolumeChangeEntry(
                    report=entry.report.model_dump(
                        by_alias=True, mode="json", exclude_none=False
                    ),
                    reported_by=entry.reported_by,
                    recorded_at=entry.recorded_at,
                )
                for entry in entries
            ],
        )

    return router


def mount_volume_reports(app: FastAPI, store: VolumeChangeStore) -> None:
    app.include_router(build_volume_reports_router(store))


__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "RecordedVolumeChange",
    "VolumeChangeRecordResult",
    "VolumeChangeRecoveryError",
    "VolumeChangeStore",
    "VolumeChangeVerdict",
    "build_volume_reports_router",
    "mount_volume_reports",
]
