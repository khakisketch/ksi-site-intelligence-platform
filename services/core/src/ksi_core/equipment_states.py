"""장비 운동상태 수신 + CPA/TTC 위험 평가 — Phase 3 를 운영자에게 닿게 하는 표면.

## 이 모듈이 채우는 자리

``packages/equipment-intelligence`` 는 KinematicState 계약·CPA/TTC 골든벡터 계산기·
RiskField 조립·재관찰 권고 신호까지 정확하게 만들어놨지만 **프로덕션 호출부가
0건**이었다(``needs_active_reobservation`` 호출 8건이 전부 테스트). 계산할 수는 있는데
그 결과가 도달할 표면이 없었다 — 이 모듈이 그 표면이다.

Phase 3 acceptance "Active Reobservation 실동작"의 **Core 측 절반**이 여기서 닫힌다.
나머지 절반(Manifold 가 이 신호를 소비해 실제로 재관찰 비행을 하는 것)은 여전히
하드웨어 종속이다 — Control boundary(CLAUDE.md)상 Viewpoint 선택·비행 행동은 Edge
소관이고, 이 모듈은 권고 불리언과 계산값만 낸다.

## 왜 "쌍을 서버가 고르지 않는가"

위험 평가는 장비 하나와 대상 하나의 **쌍**에 대해 성립한다. 그런데 "어느 쌍이
평가 대상인가"는 이 저장소 어디에도 정해져 있지 않은 정책 문제다 — 반경 기반인지,
같은 작업구역 기반인지, 장비 종류별로 다른지. 서버가 임의로 전조합을 돌리면
N² 개의 근거 없는 위험장이 생기고, 그중 무엇이 의미 있는지는 여전히 아무도 모른다.

그래서 이 API 는 **호출자가 쌍과 정책 파라미터를 지목**하면 서버가 *지어낼 수 없는
값*(CPA 거리·TTC·재관찰 권고)을 계산해 돌려준다. 지어낼 수 없는 것만 서버가 하고,
정해진 적 없는 것은 정해진 척하지 않는다.

## 저장은 site 단위, 조회는 entity 별 최신

같은 개체의 상태가 계속 올라온다(추적). 전부 append 하되 조회는 개체별 최신을
낸다 — 이력이 필요한 소비자는 ``history`` 를 쓴다. 상태는 덮어쓰지 않는다:
"언제 어디 있었다고 봤는가"가 사고 조사의 입력이다(``coverage_reports.py`` 와 동일).

## 두 상태의 관측 시각차는 계산 전에 걸린다

``cpa_ttc`` 가 ``max_observation_gap_s`` 를 필수로 받는다(그쪽 모듈 docstring) —
10분 전 굴착기 상태와 방금 작업자 상태로 "TTC 2.1초"를 내지 않는다. 이 API 는 그
값을 요청에서 받아 그대로 넘기고, 초과하면 계산을 거부한다(422).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from ksi_equipment_intelligence.cpa_ttc import (
    KinematicComparisonError,
    closest_point_of_approach,
    observation_gap_s,
    time_to_collision,
)
from ksi_equipment_intelligence.kinematic_state import KinematicState
from ksi_equipment_intelligence.reobservation_signal import (
    needs_active_reobservation,
    position_uncertainty_m,
)
from pydantic import Field

from ksi_core.api_base import (
    JOURNAL_APPEND_FAILED_DETAIL,
    JOURNAL_SEALED_DETAIL,
    CamelModel,
    iso_utc,
)
from ksi_core.auth import Permission, Principal, PrincipalKind, require_permission
from ksi_core.durable_journal import DurableJournal, JournalSealedError

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.sites import SiteStore

logger = logging.getLogger(__name__)


class EquipmentStateVerdict(StrEnum):
    RECORDED = "RECORDED"
    UNKNOWN_SITE = "UNKNOWN_SITE"
    SITE_FRAME_MISMATCH = "SITE_FRAME_MISMATCH"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_STATUS: dict[EquipmentStateVerdict, int] = {
    EquipmentStateVerdict.RECORDED: 201,
    EquipmentStateVerdict.UNKNOWN_SITE: 404,
    EquipmentStateVerdict.SITE_FRAME_MISMATCH: 422,
    EquipmentStateVerdict.STORE_UNAVAILABLE: 503,
}


class EquipmentStateRecoveryError(RuntimeError):
    """equipment-state journal 재생 실패 — 오염된 원장으로 기동하지 않는다."""


@dataclass(frozen=True, slots=True)
class EquipmentStateResult:
    verdict: EquipmentStateVerdict
    detail: str | None = None
    recorded_count: int = 0


@dataclass(frozen=True, slots=True)
class RecordedKinematicState:
    state: KinematicState
    reported_by: str | None
    recorded_at: datetime


class EquipmentStateStore:
    """``DurableJournal`` 위의 장비 운동상태 원장 — append-only, 덮어쓰지 않는다."""

    def __init__(self, journal: DurableJournal, *, site_store: SiteStore) -> None:
        self._journal = journal
        self._site_store = site_store
        self._lock = threading.Lock()
        # site_id → entity_id → 그 개체의 상태들(수신 순서 보존)
        self._by_site: dict[str, dict[str, list[RecordedKinematicState]]] = {}
        try:
            self._replay(journal)
        except EquipmentStateRecoveryError:
            journal.close()
            raise
        except BaseException as exc:
            journal.close()
            raise EquipmentStateRecoveryError(
                f"equipment-state journal 재생 실패 — 오염된 레코드: {exc}"
            ) from exc

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw.get("kind")
            if kind == "equipment-states-rejected":
                continue
            if kind not in (None, "equipment-states-recorded"):
                raise EquipmentStateRecoveryError(f"알 수 없는 journal 레코드 kind: {kind!r}")
            site_id = raw["siteId"]
            recorded_at = datetime.fromisoformat(raw["ts"])
            reported_by = raw.get("reportedBy")
            for wire in raw["states"]:
                state = KinematicState.model_validate(wire)
                verdict, detail = self._judge(site_id, state)
                if verdict is not EquipmentStateVerdict.RECORDED:
                    raise EquipmentStateRecoveryError(
                        f"재생: 기록될 수 없는 상태({verdict.value}: {detail}) — "
                        f"siteId={site_id} entityId={state.entity_id}"
                    )
                self._project(site_id, state, reported_by, recorded_at)

    def _project(
        self,
        site_id: str,
        state: KinematicState,
        reported_by: str | None,
        recorded_at: datetime,
    ) -> None:
        self._by_site.setdefault(site_id, {}).setdefault(state.entity_id, []).append(
            RecordedKinematicState(
                state=state, reported_by=reported_by, recorded_at=recorded_at
            )
        )

    def _judge(
        self, site_id: str, state: KinematicState
    ) -> tuple[EquipmentStateVerdict, str | None]:
        """현장이 실재하고 좌표계가 그 현장의 것인가 — live 와 재생이 공유한다.

        ``site_frame`` 대조가 핵심이다. 위치·속도는 좌표계 없이는 숫자일 뿐이고,
        다른 현장의 좌표계로 신고된 상태를 그대로 받으면 CPA/TTC 가 서로 다른
        기준계의 점 사이 거리를 재게 된다 — ``cpa_ttc`` 의 site_frame 일치 검사는
        **두 상태끼리**만 보므로, 둘 다 같은 잘못된 좌표계면 통과한다.
        """
        site = self._site_store.get(site_id)
        if site is None:
            return (
                EquipmentStateVerdict.UNKNOWN_SITE,
                f"등록된 적 없는 현장이다 (siteId={site_id!r})",
            )
        site_crs = site.site_frame.get("crs")
        if site_crs is not None and state.site_frame != site_crs:
            return (
                EquipmentStateVerdict.SITE_FRAME_MISMATCH,
                f"siteFrame={state.site_frame!r} 이 현장 등록 좌표계({site_crs!r})와 다르다"
                " — 위치·속도는 좌표계 없이는 숫자일 뿐이다",
            )
        return EquipmentStateVerdict.RECORDED, None

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def record_batch(
        self,
        site_id: str,
        states: list[KinematicState],
        *,
        now: datetime,
        reported_by: str | None = None,
    ) -> EquipmentStateResult:
        """상태 배치를 판정·durable 기록한다 — 전부 또는 전무."""
        with self._lock:
            if self._journal.sealed_reason is not None:
                return EquipmentStateResult(
                    EquipmentStateVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            for state in states:
                verdict, detail = self._judge(site_id, state)
                if verdict is not EquipmentStateVerdict.RECORDED:
                    return self._reject(site_id, states, now, reported_by, verdict, detail)

            record = {
                "kind": "equipment-states-recorded",
                "ts": iso_utc(now),
                "siteId": site_id,
                "reportedBy": reported_by,
                "states": [
                    s.model_dump(by_alias=True, mode="json", exclude_none=False) for s in states
                ],
            }
            try:
                self._journal.append(record)
            except JournalSealedError:
                return EquipmentStateResult(
                    EquipmentStateVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_APPEND_FAILED_DETAIL,
                )
            for state in states:
                self._project(site_id, state, reported_by, now)
            return EquipmentStateResult(
                EquipmentStateVerdict.RECORDED, recorded_count=len(states)
            )

    def _reject(
        self,
        site_id: str,
        states: list[KinematicState],
        now: datetime,
        reported_by: str | None,
        verdict: EquipmentStateVerdict,
        detail: str | None,
    ) -> EquipmentStateResult:
        record = {
            "kind": "equipment-states-rejected",
            "ts": iso_utc(now),
            "siteId": site_id,
            "verdict": verdict.value,
            "detail": detail,
            "reportedBy": reported_by,
            "entityIds": [s.entity_id for s in states],
        }
        try:
            self._journal.append(record)
        except JournalSealedError:
            return EquipmentStateResult(
                EquipmentStateVerdict.STORE_UNAVAILABLE,
                detail=JOURNAL_APPEND_FAILED_DETAIL,
            )
        return EquipmentStateResult(verdict, detail=detail)

    def latest(self, site_id: str, entity_id: str) -> RecordedKinematicState | None:
        with self._lock:
            recorded = self._by_site.get(site_id, {}).get(entity_id)
            return recorded[-1] if recorded else None

    def latest_per_entity(self, site_id: str) -> list[RecordedKinematicState]:
        """개체별 최신 상태(entity_id 오름차순 — 응답 순서를 결정적으로 고정)."""
        with self._lock:
            by_entity = self._by_site.get(site_id, {})
            return [by_entity[e][-1] for e in sorted(by_entity) if by_entity[e]]

    def history(self, site_id: str, entity_id: str) -> list[RecordedKinematicState]:
        with self._lock:
            return list(self._by_site.get(site_id, {}).get(entity_id, ()))


# ── HTTP 배선 ────────────────────────────────────────────────────────────


class EquipmentStateBatchRequest(CamelModel):
    states: list[KinematicState] = Field(min_length=1)


class EquipmentStateBatchResponse(CamelModel):
    verdict: str
    detail: str | None
    recorded_count: int


class EquipmentStateItem(CamelModel):
    state: dict[str, Any]
    reported_by: str | None
    recorded_at: datetime
    # 이 개체 위치 불확실성의 스칼라 요약(공분산 trace 의 제곱근, RMS 반경 근사) —
    # 화면이 "이 추정을 얼마나 믿을 수 있나"를 표시할 수 있게 서버가 함께 낸다.
    position_uncertainty_m: float


class EquipmentStateListView(CamelModel):
    site_id: str
    entity_count: int
    entities: list[EquipmentStateItem]


class RiskAssessmentView(CamelModel):
    """지목된 두 개체 쌍의 CPA/TTC + 재관찰 권고.

    ``timeToCollisionS`` 가 ``None`` 인 것은 "위험 없음"이 아니라 **"이 지평선
    안에서는 확인되지 않음"**이다(``cpa_ttc.time_to_collision`` 계약). 화면이 이
    둘을 같게 표시하면 안 된다.
    """

    site_id: str
    equipment_entity_id: str
    subject_entity_id: str
    observation_gap_s: float
    closest_approach_m: float
    closest_approach_time_s: float
    time_to_collision_s: float | None
    horizon_s: float
    combined_radius_m: float
    position_uncertainty_threshold_m: float
    reobservation_recommended: bool


def _require_reporting_device(
    site_id: str,
    principal: Principal = Depends(require_permission(Permission.EDGE_SYNC_INGEST)),  # noqa: B008
) -> Principal:
    """운동상태는 **장비만** 올린다 — 사람이 손으로 위치·속도를 주장할 수 없다.

    ``site_id`` 를 받는 이유는 FastAPI 가 경로 파라미터를 주입해 이 의존성이
    라우트와 같은 시그니처를 갖게 하기 위해서다(값은 쓰지 않는다 —
    ``coverage_reports._require_reporting_device`` 와 같은 관습).
    """
    del site_id
    if principal.kind is not PrincipalKind.EDGE_DEVICE:
        raise HTTPException(status_code=403, detail="권한이 부족하다")
    return principal


def build_equipment_states_router(store: EquipmentStateStore) -> APIRouter:
    router = APIRouter(prefix="/v1/sites", tags=["equipment-states"])

    @router.post("/{site_id}/equipment-states", status_code=201)
    def submit_equipment_states(
        site_id: str,
        body: EquipmentStateBatchRequest,
        response: Response,
        principal: Principal = Depends(_require_reporting_device),  # noqa: B008
    ) -> EquipmentStateBatchResponse:
        """장비·작업자 운동상태 배치 접수(Phase 3, PRD RISK-002)."""
        result = store.record_batch(
            site_id, body.states, now=datetime.now(UTC), reported_by=principal.principal_id
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is EquipmentStateVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return EquipmentStateBatchResponse(
            verdict=result.verdict.value,
            detail=result.detail,
            recorded_count=result.recorded_count,
        )

    @router.get("/{site_id}/equipment-states", response_model=EquipmentStateListView)
    def list_equipment_states(
        site_id: str,
        _principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> EquipmentStateListView:
        """개체별 **최신** 상태. 이력이 아니라 현재 화면용 스냅샷이다."""
        recorded = store.latest_per_entity(site_id)
        return EquipmentStateListView(
            site_id=site_id,
            entity_count=len(recorded),
            entities=[
                EquipmentStateItem(
                    state=r.state.model_dump(by_alias=True, mode="json", exclude_none=False),
                    reported_by=r.reported_by,
                    recorded_at=r.recorded_at,
                    position_uncertainty_m=position_uncertainty_m(r.state),
                )
                for r in recorded
            ],
        )

    @router.get("/{site_id}/risk-assessment", response_model=RiskAssessmentView)
    def assess_risk(  # noqa: PLR0913 -- 정책 파라미터는 전부 호출자가 명시한다(모듈 docstring)
        site_id: str,
        equipment_entity_id: str = Query(alias="equipmentEntityId"),  # noqa: B008
        subject_entity_id: str = Query(alias="subjectEntityId"),  # noqa: B008
        # ``allow_inf_nan=False`` 가 넷 다 붙는 이유: ``ge``/``gt`` 만으로는 ``inf`` 가
        # 통과한다(``inf >= 0`` 은 참). 그 값이 하류 CPA/TTC 계산으로 흘러가면
        # ``needs_active_reobservation`` 이 typed except 밖에서 ValueError 를 던져
        # 500 이 된다(2026-08-18 실측).
        horizon_s: float = Query(alias="horizonS", gt=0.0, allow_inf_nan=False),  # noqa: B008
        combined_radius_m: float = Query(  # noqa: B008
            alias="combinedRadiusM", ge=0.0, allow_inf_nan=False
        ),
        max_observation_gap_s: float = Query(  # noqa: B008
            alias="maxObservationGapS", ge=0.0, allow_inf_nan=False
        ),
        position_uncertainty_threshold_m: float = Query(  # noqa: B008
            alias="positionUncertaintyThresholdM", ge=0.0, allow_inf_nan=False
        ),
        _principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> RiskAssessmentView:
        """지목된 두 개체의 최신 상태로 CPA/TTC 와 재관찰 권고를 계산한다.

        **쌍과 정책 파라미터는 전부 호출자가 지목한다** — 어느 쌍이 평가 대상인지,
        지평선·합산반경·허용 시간창·불확실성 문턱을 얼마로 볼지는 이 저장소 어디에도
        정해져 있지 않은 정책 문제라 서버가 지어내지 않는다(모듈 docstring). 서버가
        하는 것은 지어낼 수 없는 계산뿐이다.

        ``reobservationRecommended`` 는 **권고**다 — 어떤 Viewpoint 로 재관측할지는
        Edge/Manifold 의 Next Best View 소관이고(PRD §14.2) 이 응답은 비행 좌표를
        만들지 않는다.
        """
        equipment = store.latest(site_id, equipment_entity_id)
        subject = store.latest(site_id, subject_entity_id)
        missing = [
            entity_id
            for entity_id, record in (
                (equipment_entity_id, equipment),
                (subject_entity_id, subject),
            )
            if record is None
        ]
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"이 현장에 상태가 보고된 적 없는 개체: {missing}",
            )
        assert equipment is not None and subject is not None  # noqa: S101 -- 위 missing 검사의 사후조건
        try:
            cpa = closest_point_of_approach(
                equipment.state,
                subject.state,
                horizon_s=horizon_s,
                max_observation_gap_s=max_observation_gap_s,
            )
            ttc = time_to_collision(
                equipment.state,
                subject.state,
                combined_radius_m=combined_radius_m,
                horizon_s=horizon_s,
                max_observation_gap_s=max_observation_gap_s,
            )
        except KinematicComparisonError as exc:
            # 시간창 초과·좌표계 불일치는 "위험 없음"이 아니라 **계산 불가**다.
            # 200 으로 빈 값을 돌려주면 화면이 안전하다고 읽는다.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return RiskAssessmentView(
            site_id=site_id,
            equipment_entity_id=equipment_entity_id,
            subject_entity_id=subject_entity_id,
            observation_gap_s=observation_gap_s(equipment.state, subject.state),
            closest_approach_m=cpa.distance_m,
            closest_approach_time_s=cpa.time_s,
            time_to_collision_s=ttc,
            horizon_s=horizon_s,
            combined_radius_m=combined_radius_m,
            position_uncertainty_threshold_m=position_uncertainty_threshold_m,
            reobservation_recommended=needs_active_reobservation(
                equipment_state=equipment.state,
                subject_state=subject.state,
                position_uncertainty_threshold_m=position_uncertainty_threshold_m,
            ),
        )

    return router


def mount_equipment_states(app: FastAPI, store: EquipmentStateStore) -> None:
    app.include_router(build_equipment_states_router(store))


__all__ = [
    "EquipmentStateListView",
    "EquipmentStateRecoveryError",
    "EquipmentStateResult",
    "EquipmentStateStore",
    "EquipmentStateVerdict",
    "RiskAssessmentView",
    "build_equipment_states_router",
    "mount_equipment_states",
]
