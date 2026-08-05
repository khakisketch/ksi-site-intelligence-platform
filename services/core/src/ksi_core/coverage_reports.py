"""CoverageReport 수신·완료 판정·조회 — INV-010 의 강제 지점 (MASTER_PRD §15.5).

## 이 모듈이 채우는 자리

INV-010 은 임무 완료 기준(위험구역 100%·자산 100%·일반영역 ≥95%)을 정하면서
강제 지점을 "CoverageReport 완료 게이트"로 지목했는데, 그 게이트가 **없었다.**
그동안 커버리지에 대해 서버가 가진 유일한 숫자는 발급 시점의
``plannedCoverageRatio`` 뿐이었고, 그건 요청자가 준 간격을 그대로 믿은 계획
추정치다. 이 모듈이 "실제로 무엇을 관찰했나"를 받아 완료를 판정한다.

## 서버는 기체의 완료 주장을 그대로 믿지 않는다

보고서의 ``summary.completionState`` 는 기체가 계산한 값이다. 서버는 Cell 분류
(위험구역/자산/일반)를 갖고 있지 않아 비율을 **재계산할 수는 없지만**, 그 비율이
주장을 뒷받침하는지는 검사할 수 있다:

1. ``COMPLETED`` 인데 요약 비율이 INV-010 임계 미만 → ``UNSUPPORTED_COMPLETION``
2. ``COMPLETED`` 인데 사유 없는 미관찰 Cell(``NOT_OBSERVED``)이 남음 →
   ``UNEXPLAINED_GAP`` (PRD "모든 미관찰 Cell에 원인코드와 후속처리 기록")
3. 미지 ``missionId`` → ``UNKNOWN_MISSION`` / 임무의 site 와 불일치 →
   ``SITE_MISMATCH``

이건 확정 이벤트를 Edge 가 주장할 수 없게 한 것(``events.py`` INV-021 게이트)과
같은 원칙이다 — **서버가 검증할 수 없는 종단 판정을 조용히 수용하지 않는다.**
반대로 ``COMPLETED_WITH_GAPS``·``ABORTED_SAFE``·``FAILED`` 는 그 자체가 "완료가
아니다"를 말하므로 임계 검사를 걸지 않는다(공백을 정직하게 신고한 보고서를
거부하면 신고를 안 하게 만든다).

## 영속·감사

``DurableJournal`` 위의 append-only 원장이다. 같은 임무에 대한 보고서가 여러 번
올 수 있고(부분→최종, 재비행), **덮어쓰지 않고 전부 남긴다** — "언제 무엇을 봤다고
했는가"가 사고 조사의 입력이기 때문이다. 조회는 최신 보고서를 낸다.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from ksi_event_contracts.coverage_report import CompletionState, CoverageReport
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from ksi_core.auth import Permission, Principal, PrincipalKind, require_permission
from ksi_core.durable_journal import DurableJournal, JournalSealedError

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.mission_records import MissionStore

logger = logging.getLogger(__name__)

_NOT_FOUND_DETAIL = "해당 임무의 커버리지 보고를 찾을 수 없다"


class CoverageReportVerdict(StrEnum):
    """보고 수신 판정. ``RECORDED`` 만 durable 기록 성공이다."""

    RECORDED = "RECORDED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    SITE_MISMATCH = "SITE_MISMATCH"
    UNSUPPORTED_COMPLETION = "UNSUPPORTED_COMPLETION"
    UNEXPLAINED_GAP = "UNEXPLAINED_GAP"
    NO_COVERAGE_EVIDENCE = "NO_COVERAGE_EVIDENCE"
    SELF_CONTRADICTORY_SUMMARY = "SELF_CONTRADICTORY_SUMMARY"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_STATUS: dict[CoverageReportVerdict, int] = {
    CoverageReportVerdict.RECORDED: 201,
    CoverageReportVerdict.UNKNOWN_MISSION: 404,
    CoverageReportVerdict.SITE_MISMATCH: 422,
    CoverageReportVerdict.UNSUPPORTED_COMPLETION: 422,
    CoverageReportVerdict.UNEXPLAINED_GAP: 422,
    CoverageReportVerdict.NO_COVERAGE_EVIDENCE: 422,
    CoverageReportVerdict.SELF_CONTRADICTORY_SUMMARY: 422,
    CoverageReportVerdict.INVALID_TIMESTAMP: 422,
    CoverageReportVerdict.STORE_UNAVAILABLE: 503,
}


class CoverageReportRecoveryError(RuntimeError):
    """coverage journal 재생 실패 — 오염된 원장으로 기동하지 않는다(fail-closed)."""


@dataclass(frozen=True, slots=True)
class CoverageReportResult:
    verdict: CoverageReportVerdict
    detail: str | None = None
    report: CoverageReport | None = None


def judge_report(report: CoverageReport) -> tuple[CoverageReportVerdict, str | None]:
    """보고서 자체의 정합만 판정한다(임무 대조는 저장소가 한다).

    ``COMPLETED`` 주장에만 임계·공백 검사를 건다 — 나머지 종료 상태는 그 자체가
    "완료가 아니다"를 말하므로, 공백을 정직하게 신고한 보고서를 거부하면 신고를
    안 하게 만든다.
    """
    if report.timestamp.tzinfo is None:
        return (
            CoverageReportVerdict.INVALID_TIMESTAMP,
            "timestamp 는 tz-aware(offset 포함) 여야 한다",
        )
    if report.summary.completion_state is not CompletionState.COMPLETED:
        return CoverageReportVerdict.RECORDED, None

    if not report.cells:
        # 관찰 증거 0건으로 완료를 주장할 수 없다(독립 재검토 B-1). 스키마에
        # minItems 가 없어 빈 배열이 통과했고, 그러면 "무엇을 봤길래 완료인가"에
        # 원장이 답하지 못한다.
        return (
            CoverageReportVerdict.NO_COVERAGE_EVIDENCE,
            "COMPLETED 주장인데 Cell 이 하나도 없다 — 관찰 증거 없이 완료할 수 없다",
        )
    if report.contradicts_full_coverage():
        # 서버가 Cell 분류를 몰라도 판정 가능한 **자체 모순**이다 — 세 비율이 모두
        # 100% 인데 관찰 안 된 Cell 이 있으면 어떤 가중치에서도 성립하지 않는다.
        unobserved = report.unobserved_cells()
        return (
            CoverageReportVerdict.SELF_CONTRADICTORY_SUMMARY,
            f"요약이 전 구역 100% 를 말하는데 관찰되지 않은 Cell 이 {len(unobserved)}개 "
            f"있다 — 어떤 가중치에서도 모순이다. 예: {unobserved[:3]}",
        )
    if not report.meets_completion_thresholds():
        summary = report.summary
        return (
            CoverageReportVerdict.UNSUPPORTED_COMPLETION,
            "COMPLETED 주장이 요약 비율로 뒷받침되지 않는다(INV-010) — "
            f"위험구역 {summary.mandatory_hazard_ratio:.4f} · "
            f"자산 {summary.mandatory_asset_ratio:.4f} · "
            f"일반영역 {summary.accessible_general_ratio:.4f}",
        )
    gaps = report.unexplained_gap_cells()
    if gaps:
        return (
            CoverageReportVerdict.UNEXPLAINED_GAP,
            f"COMPLETED 인데 사유 없는 미관찰 Cell 이 {len(gaps)}개 남았다 — "
            "모든 미관찰 Cell 은 원인코드를 가져야 한다(MASTER_PRD §15.5). "
            f"예: {gaps[:3]}",
        )
    return CoverageReportVerdict.RECORDED, None


class CoverageReportStore:
    """``DurableJournal`` 위의 보고 원장 — append-only, 덮어쓰지 않는다.

    동시성: FastAPI sync 라우트는 스레드풀에서 돌므로 판정+append+projection 을
    한 임계구역으로 묶는다(다른 저장소 관습 대칭).
    """

    def __init__(self, journal: DurableJournal, *, mission_store: MissionStore) -> None:
        self._journal = journal
        self._mission_store = mission_store
        self._lock = threading.Lock()
        # mission_id → 그 임무의 보고서들(수신 순서 보존)
        self._by_mission: dict[str, list[CoverageReport]] = {}
        try:
            self._replay(journal)
        except CoverageReportRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise CoverageReportRecoveryError(
                f"coverage journal 재생 실패 — 오염된 레코드: {exc}"
            ) from exc

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            report = CoverageReport.model_validate(raw["report"])
            # 재생도 live 와 같은 게이트를 태운다 — journal 조작으로 근거 없는
            # COMPLETED 가 되살아나는 경로를 막는다(events.py 재생 게이트와 대칭).
            verdict, detail = judge_report(report)
            if verdict is not CoverageReportVerdict.RECORDED:
                raise CoverageReportRecoveryError(
                    f"재생: 기록될 수 없는 보고서({verdict.value}: {detail}) — "
                    f"missionId={report.mission_id}"
                )
            self._by_mission.setdefault(report.mission_id, []).append(report)

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def record(
        self, report: CoverageReport, *, now: datetime, reported_by: str | None = None
    ) -> CoverageReportResult:
        """보고 1건을 판정·durable 기록한다. 실패는 typed verdict 로 돌려준다.

        ``reported_by``: 제출한 Principal id. "언제 무엇을 봤다고 했는가"가 감사
        입력이라면 "누가 그렇게 말했는가"도 같이 남아야 한다(독립 재검토 B-3).
        """
        with self._lock:
            if self._journal.sealed_reason is not None:
                return CoverageReportResult(
                    CoverageReportVerdict.STORE_UNAVAILABLE,
                    detail="journal 봉인됨 — 재시작 필요",
                )
            mission = self._mission_store.get(report.mission_id)
            if mission is None:
                # 발급된 적 없는 임무의 보고는 받지 않는다 — 계약 없이 관찰
                # 결과만 원장에 남으면 "무슨 근거로 날았나"에 답할 수 없다.
                return CoverageReportResult(
                    CoverageReportVerdict.UNKNOWN_MISSION, detail=_NOT_FOUND_DETAIL
                )
            if mission.site_id != report.site_id:
                return CoverageReportResult(
                    CoverageReportVerdict.SITE_MISMATCH,
                    detail="보고서의 siteId 가 임무 발급 기록과 다르다",
                )
            verdict, detail = judge_report(report)
            if verdict is not CoverageReportVerdict.RECORDED:
                return CoverageReportResult(verdict, detail=detail)

            record = {
                "kind": "coverage-reported",
                "ts": now.astimezone(UTC).isoformat(),
                "missionId": report.mission_id,
                "siteId": report.site_id,
                "completionState": report.summary.completion_state.value,
                "reportedBy": reported_by,
                "report": report.model_dump(by_alias=True, mode="json", exclude_none=True),
            }
            try:
                self._journal.append(record)
            except JournalSealedError:
                return CoverageReportResult(
                    CoverageReportVerdict.STORE_UNAVAILABLE,
                    detail="durable 기록 실패 — journal 봉인(재시작 필요)",
                )
            self._by_mission.setdefault(report.mission_id, []).append(report)
            return CoverageReportResult(CoverageReportVerdict.RECORDED, report=report)

    def latest(self, mission_id: str) -> CoverageReport | None:
        """그 임무의 최신 보고 — 없으면 ``None``."""
        with self._lock:
            reports = self._by_mission.get(mission_id)
            return reports[-1] if reports else None

    def history(self, mission_id: str) -> list[CoverageReport]:
        """수신 순서를 보존한 전체 보고 이력(덮어쓰지 않는다)."""
        with self._lock:
            return list(self._by_mission.get(mission_id, ()))


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class CoverageReportResponse(_CamelModel):
    verdict: str
    detail: str | None = None
    report: dict[str, Any] | None = None


class CoverageReportView(_CamelModel):
    """조회 응답 — 최신 보고 + 이 임무에 대해 몇 건이 접수됐는지."""

    mission_id: str
    report_count: int
    latest: dict[str, Any]


def _require_reporting_device(
    mission_id: str,
    principal: Principal = Depends(require_permission(Permission.EDGE_SYNC_INGEST)),  # noqa: B008
) -> Principal:
    """보고는 **장비만** 올린다 — 운영자가 커버리지를 손으로 주장할 수 없다.

    ``mission_id`` 를 인자로 받는 이유는 FastAPI 가 경로 파라미터를 주입해 이
    의존성이 라우트와 같은 시그니처를 갖게 하기 위해서다(값은 쓰지 않는다).

    **알려진 공백(독립 재검토 B-3)**: 어느 장비가 그 임무를 수행했는지는 검사하지
    않는다 — ``MissionRecord`` 에 device 필드가 없어 대조할 대상 자체가 없다.
    따라서 인증된 장비면 **다른 장비의 임무도 닫을 수 있다**(edge-sync 의
    ``DEVICE_MISMATCH`` 대칭이 여기엔 없다). 임무에 장비를 배정하는 개념이 아직
    제품에 없어서 생긴 공백이고, 그 개념을 만드는 것은 제품 결정이다. 지금은
    **제출 주체를 원장에 남겨** 최소한 "누가 그렇게 말했는가"에는 답할 수 있게 한다.
    """
    if principal.kind is not PrincipalKind.EDGE_DEVICE:
        raise HTTPException(status_code=403, detail="권한이 부족하다")
    return principal


def build_coverage_reports_router(store: CoverageReportStore) -> APIRouter:
    router = APIRouter(prefix="/v1/missions", tags=["coverage"])

    @router.post("/{mission_id}/coverage-report", status_code=201)
    def submit_coverage_report(
        mission_id: str,
        report: CoverageReport,
        response: Response,
        principal: Principal = Depends(_require_reporting_device),  # noqa: B008
    ) -> CoverageReportResponse:
        """비행 후 커버리지 보고 접수 — 완료 판정의 입력(INV-010).

        경로의 ``mission_id`` 와 본문의 ``missionId`` 가 다르면 422 다 — 둘 중
        어느 쪽이 진짜인지 서버가 고르지 않는다.
        """
        if report.mission_id != mission_id:
            raise HTTPException(
                status_code=422,
                detail="경로의 missionId 와 본문의 missionId 가 다르다",
            )
        result = store.record(
            report, now=datetime.now(UTC), reported_by=principal.principal_id
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is CoverageReportVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return CoverageReportResponse(
            verdict=result.verdict.value,
            detail=result.detail,
            report=(
                result.report.model_dump(by_alias=True, mode="json", exclude_none=True)
                if result.report is not None
                else None
            ),
        )

    @router.get("/{mission_id}/coverage-report", response_model=CoverageReportView)
    def get_coverage_report(
        mission_id: str,
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> CoverageReportView:
        """그 임무의 **최신** 보고. 이력 건수를 함께 낸다(덮어쓰지 않으므로)."""
        latest = store.latest(mission_id)
        if latest is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
        return CoverageReportView(
            mission_id=mission_id,
            report_count=len(store.history(mission_id)),
            latest=latest.model_dump(by_alias=True, mode="json", exclude_none=True),
        )

    return router


def mount_coverage_reports(app: FastAPI, store: CoverageReportStore) -> None:
    app.include_router(build_coverage_reports_router(store))
