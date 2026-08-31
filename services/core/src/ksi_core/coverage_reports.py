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

거부 판정(``UNKNOWN_MISSION``·``SITE_MISMATCH``·``NO_COVERAGE_EVIDENCE`` 등, ``RECORDED``
아닌 전부)도 ``kind: coverage-report-rejected`` 로 durable 기록한다 — "근거 없는 완료
주장을 서버가 거부했다"는 사실 자체가 감사 입력이라 조기 반환으로 소멸시키지 않는다
(risk coverage-report-rejection-not-auditable). 재생 시에는 건너뛴다 — 완료 판정 권위는
``RECORDED`` 만 갖는다.

## Coverage Recovery 신호 (MASTER_PRD §15.2)

조회 응답의 ``recoveryRecommended`` 는 :meth:`CoverageReport.needs_coverage_recovery`
를 그대로 노출한다 — 자동 재발급을 트리거하지 않는 **권고 신호**다. 실제 재커버는
운영자/오퍼레이터가 원본 site AOI 로 ``POST /v1/missions/plans``(SPATIAL_REFRESH)
를 그대로 재사용해 발급한다. 폴리곤 gap(AOI − 기존커버) 계산은 하지 않는다 —
Cell 지오메트리 저장소가 이 코드베이스에 아직 없어(``CoverageCell.geometry_ref``
미해석) 정밀 재커버 구역 계산은 별도 데이터모델 결정이 선행돼야 한다. 이벤트 분기로
인한 실시간 촬영공백 보완(비행 중 Edge/Manifold 소관, ``03_EDGE_AUTONOMY.md`` 의
``COVERAGE_RECOVERY`` 상태)은 이 모듈의 범위 밖이다 — 하드웨어 종속(Track A/B와
동일 계열).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Response
from ksi_domain.enums import MissionExecutionStatus
from ksi_event_contracts.coverage_report import CompletionState, CoverageReport

from ksi_core.api_base import (
    JOURNAL_APPEND_FAILED_DETAIL,
    JOURNAL_SEALED_DETAIL,
    CamelModel,
    iso_utc,
)
from ksi_core.auth import (
    Permission,
    Principal,
    PrincipalKind,
    current_request_organization_id,
    require_permission,
)
from ksi_core.durable_journal import DurableJournal, JournalSealedError

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.mission_execution import MissionExecutionStore
    from ksi_core.mission_records import MissionRecord, MissionStore

logger = logging.getLogger(__name__)

_NOT_FOUND_DETAIL = "해당 임무의 커버리지 보고를 찾을 수 없다"


class CoverageReportVerdict(StrEnum):
    """보고 수신 판정. ``RECORDED`` 만 durable 기록 성공이다."""

    RECORDED = "RECORDED"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    SITE_MISMATCH = "SITE_MISMATCH"
    # 임무가 assignedDeviceId 를 신고했는데 보고 장비가 그 장비가 아니다 —
    # edge_sync.py 의 DEVICE_MISMATCH 와 동형(모듈 docstring _require_reporting_
    # device "알려진 공백" 참조, 이 verdict 가 그 공백을 닫는다).
    DEVICE_NOT_ASSIGNED = "DEVICE_NOT_ASSIGNED"
    UNSUPPORTED_COMPLETION = "UNSUPPORTED_COMPLETION"
    UNEXPLAINED_GAP = "UNEXPLAINED_GAP"
    NO_COVERAGE_EVIDENCE = "NO_COVERAGE_EVIDENCE"
    SELF_CONTRADICTORY_SUMMARY = "SELF_CONTRADICTORY_SUMMARY"
    # 칸 총수<2 인데 비율이 0과 1 사이 — has_impossible_fractional_ratio() 참조.
    INSUFFICIENT_CELLS_FOR_RATIO = "INSUFFICIENT_CELLS_FOR_RATIO"
    # accessibleGeneralRatio 가 발급 경로의 plannedCoverageRatio(이상적 조건 상한)
    # 를 넘는다 — 계획대로만 날았다는 전제 하에 불가능하다.
    EXCEEDS_PLANNED_COVERAGE = "EXCEEDS_PLANNED_COVERAGE"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_STATUS: dict[CoverageReportVerdict, int] = {
    CoverageReportVerdict.RECORDED: 201,
    CoverageReportVerdict.UNKNOWN_MISSION: 404,
    CoverageReportVerdict.SITE_MISMATCH: 422,
    # edge_sync.py DEVICE_MISMATCH 와 같은 상태코드 — 인증은 됐지만(401 아님)
    # 이 자원에 대해서는 아니다(403).
    CoverageReportVerdict.DEVICE_NOT_ASSIGNED: 403,
    CoverageReportVerdict.UNSUPPORTED_COMPLETION: 422,
    CoverageReportVerdict.UNEXPLAINED_GAP: 422,
    CoverageReportVerdict.NO_COVERAGE_EVIDENCE: 422,
    CoverageReportVerdict.SELF_CONTRADICTORY_SUMMARY: 422,
    CoverageReportVerdict.INSUFFICIENT_CELLS_FOR_RATIO: 422,
    CoverageReportVerdict.EXCEEDS_PLANNED_COVERAGE: 422,
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
    if report.has_impossible_fractional_ratio():
        summary = report.summary
        return (
            CoverageReportVerdict.INSUFFICIENT_CELLS_FOR_RATIO,
            f"칸이 {len(report.cells)}개인데 위험구역 {summary.mandatory_hazard_ratio:.4f}·"
            f"자산 {summary.mandatory_asset_ratio:.4f}·일반영역 "
            f"{summary.accessible_general_ratio:.4f} 중 하나가 0과 1 사이다 — 칸이 2개 "
            "미만이면 0.0/1.0 외의 비율은 산술적으로 만들 수 없다",
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


# planned_coverage_ratio 는 lawnmower 경로 생성기가 스캔선 기하(각도·간격·중복)로
# 계산한 값이다 — 단순 직렬화 잔차가 아니라 **두 독립된 기하 계산** 사이의 오차라
# packages/event-contracts 의 _RATIO_EPS(1e-9, 직렬화 잔차용)로는 부족하다. 실측
# 확인(2026-08-18, test_aol2_reobservation.py 재현): 같은 논리적 "1.0" 이 계획
# 경로에서 0.9999999260359301 로 나와 신고값 1.0 과 7.4e-8 차이가 났다 — 이 패키지의
# 기하 계산 오차 허용 관례(geometry.py _EPSILON_M·coverage.py _FOLD_EPSILON_M·
# terrain.py _HORIZONTAL_EPSILON_M, 전부 1e-6)와 같은 값을 쓴다.
_PLANNED_COVERAGE_EPS = 1e-6


def _exceeds_planned_coverage(report: CoverageReport, mission: MissionRecord) -> bool:
    """계획 커버 추정치를 초과한 일반영역 관찰을 주장하는가.

    ``mission.planned_coverage_ratio`` 는 발급 시점에 lawnmower 경로 생성기가
    이상적 촬영 조건을 가정해 계산한 **상한**이다(``mission_plans.py`` 가 발급
    게이트에서 이미 이 값을 ``accessibleGeneralCoverage`` 요구치와 대조해 뒀다).
    계획된 경로만 날았다는 전제 하에, 실제 관찰이 그 상한을 넘는
    ``accessibleGeneralRatio`` 를 주장하면 불가능하다.

    hazard/asset 비율에는 적용하지 않는다 — 그 둘은 서버가 Cell 분류를 갖고
    있지 않아 이 추정치와 다른 계산 기반이다(``CoverageSummary`` docstring).

    ``planned_coverage_ratio`` 가 ``None`` 이면(perimeter 패턴·계약 전용 발급)
    ``False`` 를 돌려준다 — 유도 불가는 거부 사유가 아니다.
    """
    if mission.planned_coverage_ratio is None:
        return False
    return report.summary.accessible_general_ratio > (
        mission.planned_coverage_ratio + _PLANNED_COVERAGE_EPS
    )


@dataclass(frozen=True, slots=True)
class RecordedCoverageReport:
    """보고 1건 + "누가 그렇게 말했는가"(``reported_by``, 독립 재검토 B-3).

    ``report`` 만으로는 제출 주체가 사라진다 — journal 엔벨로프(``reportedBy``)에는
    남지만, 조회 API 가 :class:`CoverageReport` 만 돌려주면 감사 입력이 저장은 되고
    노출은 안 되는 반쪽짜리가 된다. 이 dataclass 가 그 둘을 함께 들고 다닌다.
    """

    report: CoverageReport
    reported_by: str | None


@dataclass(frozen=True, slots=True)
class RejectedCoverageReport:
    """서버가 거부한 보고 1건 — 무엇을, 왜, 누가, 언제.

    보고 본문 자체는 담지 않는다. 거부된 주장을 조회 표면에 그대로 실으면 그
    숫자들이 화면에서 사실처럼 읽힐 자리가 생긴다 — 감사에 필요한 것은 "이 임무에
    대해 이런 사유로 거부가 있었다"이지 거부된 주장의 내용이 아니다(원문이 필요하면
    journal 을 본다).
    """

    mission_id: str
    site_id: str | None
    verdict: CoverageReportVerdict
    detail: str | None
    reported_by: str | None
    rejected_at: datetime


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
        self._by_mission: dict[str, list[RecordedCoverageReport]] = {}
        # mission_id → 거부 판정 이력. 수용 상태와 **분리해서** 들고 있는다 —
        # RECORDED 만 완료 판정 권위를 갖는다는 규칙은 그대로다(모듈 docstring).
        self._rejections_by_mission: dict[str, list[RejectedCoverageReport]] = {}
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

    def mission_is_visible(self, mission_id: str) -> bool:
        """Mission 원장의 조직 scope를 coverage·거부 감사 이력에도 적용한다."""

        return self._mission_store.get(mission_id) is not None

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw.get("kind")
            if kind == "coverage-report-rejected":
                # 거부 판정 감사기록(risk coverage-report-rejection-not-auditable) —
                # 수용 상태(_by_mission)에 반영하지 않는다. RECORDED 만 완료 판정 권위를
                # 가진다. 다만 **조회 가능한 곳에는 실어야** 한다: 저장만 하고 어떤 GET
                # 으로도 못 보면 "서버가 근거 없는 완료를 막았다"는 사실이 운영자·감사자
                # 에게 끝내 도달하지 않는다.
                self._rejections_by_mission.setdefault(raw["missionId"], []).append(
                    RejectedCoverageReport(
                        mission_id=raw["missionId"],
                        site_id=raw.get("siteId"),
                        verdict=CoverageReportVerdict(raw["verdict"]),
                        detail=raw.get("detail"),
                        reported_by=raw.get("reportedBy"),
                        rejected_at=datetime.fromisoformat(raw["ts"]),
                    )
                )
                continue
            if kind not in (None, "coverage-reported"):
                raise CoverageReportRecoveryError(f"알 수 없는 journal 레코드 kind: {kind!r}")
            report = CoverageReport.model_validate(raw["report"])
            # 재생은 judge_report 의 자체정합 게이트(①~④: UNSUPPORTED_COMPLETION·
            # UNEXPLAINED_GAP·NO_COVERAGE_EVIDENCE·SELF_CONTRADICTORY_SUMMARY)만
            # live 와 동일하게 태운다 — journal 조작으로 근거 없는 COMPLETED 가
            # 되살아나는 경로를 막는다(events.py 재생 게이트와 대칭). live 의 임무
            # 대조(⑤: UNKNOWN_MISSION·SITE_MISMATCH, 같은 이유로 DEVICE_NOT_ASSIGNED
            # 도)는 **의도적으로** 재생하지 않는다 — 그건 수신 시점 게이트이고,
            # 임무 원장은 이 원장과 따로 회전·보관 정책을 타서 재생 시점엔 없을 수
            # 있다. 이미 접수된 기록을 나중에(다른 원장의 상태 변화로) 부정하지
            # 않는다(INV-010, 독립 재검토 B-2 — 예전엔 이 문서 자체가 "재생도 같은
            # 강도"라고 과장했다가 정정됐다; test_replay_restores_history 가 이
            # 비대칭을 고정한다).
            verdict, detail = judge_report(report)
            if verdict is not CoverageReportVerdict.RECORDED:
                raise CoverageReportRecoveryError(
                    f"재생: 기록될 수 없는 보고서({verdict.value}: {detail}) — "
                    f"missionId={report.mission_id}"
                )
            recorded = RecordedCoverageReport(report=report, reported_by=raw.get("reportedBy"))
            self._by_mission.setdefault(report.mission_id, []).append(recorded)

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def record(
        self,
        report: CoverageReport,
        *,
        now: datetime,
        reported_by: str | None = None,
        device_id: str | None = None,
    ) -> CoverageReportResult:
        """보고 1건을 판정·durable 기록한다. 실패는 typed verdict 로 돌려준다.

        ``reported_by``: 제출한 Principal id. "언제 무엇을 봤다고 했는가"가 감사
        입력이라면 "누가 그렇게 말했는가"도 같이 남아야 한다(독립 재검토 B-3).

        ``device_id``: 보고를 올린 EDGE_DEVICE 의 장비 id(``Principal.device_id``,
        ``reported_by``=principal_id 와 다른 값일 수 있다). 임무가
        ``assigned_device_id`` 를 신고했는데 이 값과 다르면 거부한다(INV-010).
        ``None`` 이면 대조를 건너뛴다 — 호출자가 장비 신원을 안 넘긴 것으로,
        기존(대조 없음) 테스트·호출부를 이 매개변수 추가가 깨지 않게 한다.
        """
        with self._lock:
            if self._journal.sealed_reason is not None:
                return CoverageReportResult(
                    CoverageReportVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_SEALED_DETAIL,
                )
            mission = self._mission_store.get(report.mission_id)
            if mission is None:
                # 발급된 적 없는 임무의 보고는 받지 않는다 — 계약 없이 관찰
                # 결과만 원장에 남으면 "무슨 근거로 날았나"에 답할 수 없다.
                return self._reject(
                    report,
                    now,
                    reported_by,
                    CoverageReportVerdict.UNKNOWN_MISSION,
                    _NOT_FOUND_DETAIL,
                )
            if mission.site_id != report.site_id:
                return self._reject(
                    report,
                    now,
                    reported_by,
                    CoverageReportVerdict.SITE_MISMATCH,
                    "보고서의 siteId 가 임무 발급 기록과 다르다",
                )
            if (
                mission.assigned_device_id is not None
                and device_id is not None
                and mission.assigned_device_id != device_id
            ):
                # 배정을 신고 안 한 임무(assigned_device_id is None)는 여전히
                # 어느 장비든 받는다 — 이 대조는 배정이 실제로 선언된 임무에만
                # 걸린다(모듈 docstring "알려진 공백"이 좁아지는 자리다).
                return self._reject(
                    report,
                    now,
                    reported_by,
                    CoverageReportVerdict.DEVICE_NOT_ASSIGNED,
                    f"이 임무에 배정된 장비는 {mission.assigned_device_id!r} 다 — "
                    f"보고 장비 {device_id!r} 는 배정되지 않았다",
                )
            if report.summary.completion_state is CompletionState.COMPLETED and (
                _exceeds_planned_coverage(report, mission)
            ):
                # 이건 임무 원장(다른 원장)의 값과의 대조라 SITE_MISMATCH·
                # DEVICE_NOT_ASSIGNED 와 같은 "수신 시점 게이트" 지위다 — 재생 시에는
                # 재검사하지 않는다(위 _replay 는 그대로 둔다, 이미 그 두 게이트를
                # 재생하지 않는 것과 동일 원칙).
                return self._reject(
                    report,
                    now,
                    reported_by,
                    CoverageReportVerdict.EXCEEDS_PLANNED_COVERAGE,
                    "COMPLETED 주장의 accessibleGeneralRatio"
                    f"({report.summary.accessible_general_ratio:.4f})가 발급 경로의 "
                    f"plannedCoverageRatio({mission.planned_coverage_ratio:.4f})를 "
                    "초과한다 — 계획된 경로로는 도달할 수 없다",
                )
            verdict, detail = judge_report(report)
            if verdict is not CoverageReportVerdict.RECORDED:
                return self._reject(report, now, reported_by, verdict, detail)

            record = {
                "kind": "coverage-reported",
                "ts": iso_utc(now),
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
                    detail=JOURNAL_APPEND_FAILED_DETAIL,
                )
            self._by_mission.setdefault(report.mission_id, []).append(
                RecordedCoverageReport(report=report, reported_by=reported_by)
            )
            return CoverageReportResult(CoverageReportVerdict.RECORDED, report=report)

    def _reject(
        self,
        report: CoverageReport,
        now: datetime,
        reported_by: str | None,
        verdict: CoverageReportVerdict,
        detail: str | None,
    ) -> CoverageReportResult:
        """거부 판정도 감사기록에 남긴다(risk coverage-report-rejection-not-auditable).

        ``self._lock`` 을 쥔 :meth:`record` 안에서만 호출된다. 수용 상태
        (``_by_mission``)에는 반영하지 않는다 — RECORDED 만 완료 판정 권위를 가진다.
        """
        record = {
            "kind": "coverage-report-rejected",
            "ts": iso_utc(now),
            "missionId": report.mission_id,
            "siteId": report.site_id,
            "verdict": verdict.value,
            "detail": detail,
            "reportedBy": reported_by,
            "report": report.model_dump(by_alias=True, mode="json", exclude_none=True),
        }
        try:
            self._journal.append(record)
        except JournalSealedError:
            return CoverageReportResult(
                CoverageReportVerdict.STORE_UNAVAILABLE,
                detail=JOURNAL_APPEND_FAILED_DETAIL,
            )
        self._rejections_by_mission.setdefault(report.mission_id, []).append(
            RejectedCoverageReport(
                mission_id=report.mission_id,
                site_id=report.site_id,
                verdict=verdict,
                detail=detail,
                reported_by=reported_by,
                rejected_at=now.astimezone(UTC),
            )
        )
        return CoverageReportResult(verdict, detail=detail)

    def latest(self, mission_id: str) -> CoverageReport | None:
        """그 임무의 최신 보고 — 없으면 ``None``."""
        recorded = self.latest_recorded(mission_id)
        return recorded.report if recorded is not None else None

    def latest_recorded(self, mission_id: str) -> RecordedCoverageReport | None:
        """그 임무의 최신 보고 + 제출 주체 — 없으면 ``None``."""
        if (
            current_request_organization_id() is not None
            and not self.mission_is_visible(mission_id)
        ):
            return None
        with self._lock:
            reports = self._by_mission.get(mission_id)
            return reports[-1] if reports else None

    def mission_planned_general_ratio(self, mission_id: str) -> float | None:
        """이 임무의 계획 일반영역 커버 추정치 — 없으면 ``None``(대사 불가)."""
        with self._lock:
            mission = self._mission_store.get(mission_id)
            return mission.planned_coverage_ratio if mission is not None else None

    def rejections(self, mission_id: str) -> list[RejectedCoverageReport]:
        """그 임무에 대해 서버가 **거부한** 보고들(수신 순서 보존).

        "서버가 근거 없는 완료 주장을 막았다"는 사실 자체가 감사 입력이다 —
        장비가 반복적으로 허위 완료를 주장해도 이 목록이 없으면 사람은 알 수 없다.
        """
        if (
            current_request_organization_id() is not None
            and not self.mission_is_visible(mission_id)
        ):
            return []
        with self._lock:
            return list(self._rejections_by_mission.get(mission_id, ()))

    def history(self, mission_id: str) -> list[CoverageReport]:
        """수신 순서를 보존한 전체 보고 이력(덮어쓰지 않는다)."""
        if (
            current_request_organization_id() is not None
            and not self.mission_is_visible(mission_id)
        ):
            return []
        with self._lock:
            return [r.report for r in self._by_mission.get(mission_id, ())]

    def recorded_history(self, mission_id: str) -> list[RecordedCoverageReport]:
        """보고 본문과 제출 주체를 함께 보존한 append-only 이력 사본.

        보고서 내보내기 감사는 ``latest``만 다시 읽으면 안 된다. 내보낸 뒤 같은
        임무에 부분→최종 보고가 추가돼도 과거 문서의 근거가 사라진 것이 아니기
        때문이다. 호출자는 이 수신 순서 prefix를 snapshot으로 묶고 replay 때 같은
        prefix가 남아 있는지 검증한다.
        """
        if (
            current_request_organization_id() is not None
            and not self.mission_is_visible(mission_id)
        ):
            return []
        with self._lock:
            return list(self._by_mission.get(mission_id, ()))


class CoverageReportResponse(CamelModel):
    verdict: str
    detail: str | None = None
    report: dict[str, Any] | None = None


RATIO_ATTRIBUTION_NOTE = (
    "이 세 비율은 기체가 계산해 신고한 값입니다. 서버는 구역 분류(위험구역/자산/"
    "일반)를 갖고 있지 않아 재계산하지 못합니다(INV-010)."
)

PLANNED_GENERAL_COVERAGE_UNAVAILABLE_REASON = (
    "이 임무의 발급 경로에 계획 커버 추정치가 없습니다"
    " (perimeter 경로이거나 계약 단독 발급일 수 있습니다)"
)


class CoverageReportView(CamelModel):
    """조회 응답 — 최신 보고 + 이 임무에 대해 몇 건이 접수됐는지 + 누가 보고했는지."""

    mission_id: str
    report_count: int
    latest: dict[str, Any]
    # 제출한 Principal id(대개 장비 id) — 없으면(구 journal 재생 등) null(독립 재검토 B-3).
    reported_by: str | None
    # Coverage Recovery 권고(MASTER_PRD §15.2) — CoverageReport.needs_coverage_recovery().
    # 자동 재발급을 트리거하지 않는다: 운영자/오퍼레이터가 이 신호를 보고 원본 site
    # AOI 로 SPATIAL_REFRESH 임무를 POST /v1/missions/plans 에 재발급한다.
    recovery_recommended: bool
    # 귀속 — 이 비율이 기체 신고값이라는 사실은 항상 참이라 항상 채워진다.
    ratio_attribution_note: str
    # 대사 — 계획 커버 추정치. 없으면(perimeter 패턴·계약 전용 발급) None 이고
    # planned_general_coverage_unavailable_reason 이 대신 채워진다. UI 는 이 원 숫자를
    # "비행 결과" 캡션에 반복하지 않는다(page.tsx:239 의 기존 원칙 — 계획과 실측을
    # 나란히 두지 않는다) — 프로그램적 소비(추후 감사·내보내기)를 위해 API 에는 남긴다.
    planned_general_coverage_ratio: float | None
    planned_general_coverage_unavailable_reason: str | None


class CoverageRejectionView(CamelModel):
    """거부된 보고 1건 — 무엇을, 왜, 누가, 언제(본문은 싣지 않는다)."""

    verdict: str
    detail: str | None
    reported_by: str | None
    rejected_at: datetime


class CoverageRejectionListView(CamelModel):
    """그 임무에 대해 서버가 거부한 보고들.

    거부가 0건인 것은 404 가 아니라 빈 목록이다 — "이 임무에는 거부가 없었다"는
    그 자체로 답이고, 404 로 주면 "임무가 없다"와 구분되지 않는다.
    """

    mission_id: str
    rejection_count: int
    rejections: list[CoverageRejectionView]


def _require_reporting_device(
    mission_id: str,
    principal: Principal = Depends(require_permission(Permission.EDGE_SYNC_INGEST)),  # noqa: B008
) -> Principal:
    """보고는 **장비만** 올린다 — 운영자가 커버리지를 손으로 주장할 수 없다.

    ``mission_id`` 를 인자로 받는 이유는 FastAPI 가 경로 파라미터를 주입해 이
    의존성이 라우트와 같은 시그니처를 갖게 하기 위해서다(값은 쓰지 않는다).

    이 함수 자체는 "장비인가"만 본다 — "**그** 임무에 배정된 장비인가"는
    ``CoverageReportStore.record`` 의 ``DEVICE_NOT_ASSIGNED`` 게이트가 맡는다
    (``mission.assigned_device_id`` 대조, edge-sync 의 ``DEVICE_MISMATCH`` 와
    동형). 그 대조는 임무가 배정을 신고했을 때만 걸린다 — 배정 개념 자체가
    선택적이라(1:1 대일 배치 전제, 다대다 Fleet 관리는 아직 이 제품에 없다),
    신고 안 한 임무는 예전처럼 인증된 어느 장비든 닫을 수 있다. 지금은 언제나
    **제출 주체를 원장에 남겨** 최소한 "누가 그렇게 말했는가"에는 답할 수 있게 한다.
    """
    if principal.kind is not PrincipalKind.EDGE_DEVICE:
        raise HTTPException(status_code=403, detail="권한이 부족하다")
    return principal


def build_coverage_reports_router(
    store: CoverageReportStore,
    mission_execution_store: MissionExecutionStore | None = None,
) -> APIRouter:
    """``mission_execution_store`` 를 주면 접수된 보고가 임무 실행 상태를 옮긴다.

    **완료 판정의 권위는 이 접수(원장)이고 실행 상태는 그 투영이다**(INV-010) —
    그래서 투영 쓰기의 성패가 이 라우터의 응답을 바꾸지 않는다. 투영 원장이
    봉인돼도 커버리지 접수는 201 이어야 한다: 권위가 뒤집히면 안 된다.
    """
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
            report,
            now=datetime.now(UTC),
            reported_by=principal.principal_id,
            device_id=principal.device_id,
        )
        if (
            mission_execution_store is not None
            and result.verdict is CoverageReportVerdict.RECORDED
            and result.report is not None
        ):
            # 접수된(=INV-010 게이트를 통과한) 보고만 실행 상태를 옮긴다.
            # 거부된 주장이 상태를 옮기면 화면에서 사실처럼 읽힌다
            # (``CoverageReportStore._reject`` — RECORDED 만 완료 판정 권위를 가진다).
            # **반환값을 의도적으로 무시한다**: 투영 쓰기 실패가 접수 응답을 바꾸면
            # 완료 판정의 권위가 원장에서 투영으로 뒤집힌다.
            mission_execution_store.transition(
                mission_id,
                (
                    MissionExecutionStatus.COMPLETED
                    if result.report.summary.completion_state is CompletionState.COMPLETED
                    else MissionExecutionStatus.ENDED_INCOMPLETE
                ),
                detail=(
                    "coverageReport completionState="
                    f"{result.report.summary.completion_state.value}"
                ),
                actor="system:coverage-report",
                now=datetime.now(UTC),
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
        recorded = store.latest_recorded(mission_id)
        if recorded is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
        planned_ratio = store.mission_planned_general_ratio(mission_id)
        return CoverageReportView(
            mission_id=mission_id,
            report_count=len(store.history(mission_id)),
            latest=recorded.report.model_dump(by_alias=True, mode="json", exclude_none=True),
            reported_by=recorded.reported_by,
            recovery_recommended=recorded.report.needs_coverage_recovery(),
            ratio_attribution_note=RATIO_ATTRIBUTION_NOTE,
            planned_general_coverage_ratio=planned_ratio,
            planned_general_coverage_unavailable_reason=(
                None
                if planned_ratio is not None
                else PLANNED_GENERAL_COVERAGE_UNAVAILABLE_REASON
            ),
        )

    @router.get(
        "/{mission_id}/coverage-report/rejections", response_model=CoverageRejectionListView
    )
    def list_coverage_rejections(
        mission_id: str,
        _principal: Principal = Depends(require_permission(Permission.MISSIONS_READ)),  # noqa: B008
    ) -> CoverageRejectionListView:
        """서버가 거부한 완료 주장 목록 (risk coverage-report-rejection-not-auditable).

        거부 판정은 이미 durable 기록되고 있었지만 **어떤 GET 으로도 조회할 수
        없었다** — 판정이 제출 장비의 응답 본문으로만 가고 소멸했다. 그러면
        "서버가 근거 없는 완료를 막았다"는 사실이 운영자·감사자에게 도달하지 않고,
        장비가 반복적으로 허위 완료를 주장해도 사람은 알 수 없다. INV-010 의 강제는
        성립하지만 그 강제가 작동했다는 증거가 남지 않는 상태였다.

        거부된 보고의 **본문은 싣지 않는다** — 거부된 주장의 숫자를 조회 표면에
        그대로 실으면 그게 화면에서 사실처럼 읽힐 자리가 생긴다.
        """
        if not store.mission_is_visible(mission_id):
            raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL)
        rejections = store.rejections(mission_id)
        return CoverageRejectionListView(
            mission_id=mission_id,
            rejection_count=len(rejections),
            rejections=[
                CoverageRejectionView(
                    verdict=r.verdict.value,
                    detail=r.detail,
                    reported_by=r.reported_by,
                    rejected_at=r.rejected_at,
                )
                for r in rejections
            ],
        )

    return router


def mount_coverage_reports(
    app: FastAPI,
    store: CoverageReportStore,
    mission_execution_store: MissionExecutionStore | None = None,
) -> None:
    app.include_router(build_coverage_reports_router(store, mission_execution_store))
