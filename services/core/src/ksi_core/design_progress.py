"""계획 대비 진척 — 두 개의 설계 대비 잔량 리포트를 이어 뺀 파생값 (M4-C).

## 저장하지 않는다

이 모듈은 원장을 만들지 않는다. 이미 기록된 ``DesignConformanceReport`` 두 건 —
사람이 '원지형 기준'으로 지정한 것과 가장 최근 것 — 을 같은 구역끼리 뺀 결과를
조회 시점에 만든다. 저장하면 원본 리포트가 하나 더 들어올 때마다 갱신해야 하는
두 번째 진실이 생긴다.

.. code-block:: text

    계획 = 기준 시점의 잔량      (원지형에서 설계까지 얼마였나)
    잔여 = 최신 시점의 잔량      (지금 설계까지 얼마 남았나)
    완료 = 계획 − 잔여

## 이어붙이기를 거부하는 조건 — 조용히 틀리는 것을 막는다

두 리포트가 **같은 자로 잰 것이 아니면 뺄셈이 성립하지 않는다.** 그런데 그
결과는 어느 화면에서도 이상해 보이지 않는다(그냥 숫자가 하나 나온다). 그래서
아래 넷 중 하나라도 다르면 표를 만들지 않고 사람이 읽는 사유를 낸다:

- **설계면 해시** — 설계가 바뀌면 계획 물량 자체가 바뀐다. 같은 ``designSurfaceId``
  라도 다른 판이면 다른 계획이다.
- **집계 문턱(volumeThresholdM)** — 0.05m 로 센 값과 0.10m 로 센 값을 빼면 그 차이가
  진척으로 둔갑한다.
- **수직기준(datum)** — 한국에서 타원체고와 정표고는 20~30m 차이다.
- **좌표계(crs)** — 면적이 달라지면 체적이 달라진다.

## 구역 맞춤은 ``zoneId`` 로 하지만, 그것만으로는 "같은 곳을 쟀다"를 보장하지 않는다

작업구역(M4-C)을 쓰면 ``zoneId`` 가 곧 ``workAreaId`` 라 두 시점이 자연히 이어진다.
즉석 폴리곤으로 낸 리포트는 ``zoneId`` 가 매번 같은 고정 문자열이라 **좌표가 달라도
이어져 버릴 수 있다.** 등록된 작업구역이라도 안심할 수 없다 — ``ZoneVolumeDelta``
의 ``cut``/``fill``/``area`` 는 구역의 명목 면적이 아니라 **그 비행에서 실제로
잰 셀들만의 값**이라(``dsm_diff.volume_delta_in_polygon``), 두 시점의 DSM 커버리지가
다르면(구름·그늘·비행경로 차이) 그 차이가 조용히 "완료"로 계상된다.

그래서 이 모듈은 zoneId 로 짝지은 뒤 **두 리포트가 이미 갖고 있는**
``ZoneVolumeDelta.area_m2`` 를 대조한다 — 값싼 반증 수단이 요청에 이미 실려 있는데
쓰지 않을 이유가 없다(2026-08-13 프로젝트 두뇌 재감사 확인). 면적이
:data:`AREA_MISMATCH_RATIO_THRESHOLD` 이상 벌어지면 그 구역은 "같은 곳을 쟀다"고
보지 않고 표에서 빼며, 이유를 ``areaMismatchZoneIds`` 로 따로 알린다 — zoneId가
같다는 사실만으로 안심시키지 않는다.

한쪽에만 있는 구역은 표에서 빼고 ``unmatchedZoneIds`` 로 따로 알린다 — 조용히
빠지면 총합이 달라진 이유를 아무도 모른다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query, Response
from ksi_event_contracts.design_conformance_report import DesignConformanceReport
from ksi_event_contracts.design_progress import (
    PLANNED_EPSILON_M3,
    DesignProgress,
    ZoneProgress,
)
from ksi_event_contracts.volume_change_report import ZoneVolumeDelta
from pydantic import Field, ValidationError

from ksi_core.api_base import CamelModel, iso_utc
from ksi_core.auth import Permission, Principal, require_permission

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.design_conformance_reports import DesignConformanceStore
    from ksi_core.work_areas import WorkAreaStore

#: 진척을 낼 수 없는 이유. 화면이 사유마다 다른 안내를 띄우므로 문자열이 아니라 코드다.
_BASIS_NO_PLAN = (
    "이 방향의 계획 물량이 없다 — 기준 시점에 이미 설계 높이거나 그보다 낮았다. "
    "진척률은 0%가 아니라 '해당 없음'이다"
)
_BASIS_NORMAL = "계획·잔여 모두 같은 문턱·같은 수직기준으로 잰 값이다"
_BASIS_OVERSHOOT = (
    "완료가 계획을 넘었다 — 설계보다 더 깎았거나 더 쌓았다는 뜻이다(과굴착·과성토). "
    "계산 오류가 아니라 현장 상태다"
)
_BASIS_REGRESSED = (
    "완료가 음수다 — 잔여가 기준보다 늘었다(되메우기·재시공·붕괴·유실). "
    "계산 오류가 아니라 현장 상태다"
)

#: 두 시점의 측정 면적(``ZoneVolumeDelta.area_m2``)이 이 비율 넘게 다르면 "같은
#: 곳을 쟀다"고 보지 않는다. **관측 편의값이다** — 항공 재구성마다 구역 경계
#: 부근 몇 % 편차는 정상이고, 이 값은 그 정상 편차와 "다른 범위를 쟀다"(즉석
#: 폴리곤 재사용·DSM 커버리지 손실)를 가르는 출발점이지 캘리브레이션된 수치가
#: 아니다(``DEFAULT_DISTANCE_THRESHOLD_M`` 와 같은 지위 — comparison_policy.py 참고).
AREA_MISMATCH_RATIO_THRESHOLD = 0.10


def _area_mismatch(baseline_area_m2: float, latest_area_m2: float) -> bool:
    larger = max(baseline_area_m2, latest_area_m2)
    if larger <= 0.0:
        return False
    return abs(latest_area_m2 - baseline_area_m2) / larger > AREA_MISMATCH_RATIO_THRESHOLD


@dataclass(frozen=True, slots=True)
class ProgressDerivation:
    """파생 결과 — 성공이면 ``progress``, 아니면 ``detail`` 이 사람이 읽는 사유."""

    progress: DesignProgress | None
    unmatched_zone_ids: tuple[str, ...] = ()
    #: zoneId 는 양쪽에 다 있었지만 측정 면적이 10% 넘게 달라 "같은 곳을 쟀다"고
    #: 볼 수 없어 표에서 뺀 구역. unmatched 와 다른 사유이므로 따로 센다.
    area_mismatch_zone_ids: tuple[str, ...] = ()
    detail: str | None = None


def derive_progress(
    baseline: DesignConformanceReport,
    latest: DesignConformanceReport,
    *,
    site_id: str,
    zone_names: dict[str, str] | None = None,
) -> ProgressDerivation:
    """두 리포트 → 구역별 진척. 이어붙일 수 없으면 ``progress=None`` + 사유.

    순수 함수다 — 저장소도 시각도 보지 않는다. 그래서 이 판정 전부를 저장소 없이
    테스트할 수 있고, 조회 경로가 바뀌어도 규칙이 따라 흔들리지 않는다.
    """
    if baseline.design_conformance_id == latest.design_conformance_id:
        return ProgressDerivation(
            None,
            detail=(
                "기준과 최신이 같은 리포트다 — 자기 자신 대비 진척은 항상 0이라 화면에 "
                "'아무것도 안 했다'로 나온다. 최신 시점의 비교를 한 번 더 돌린 뒤에 본다"
            ),
        )
    if baseline.design_surface_ref.sha256 != latest.design_surface_ref.sha256:
        return ProgressDerivation(
            None,
            detail=(
                "두 리포트가 서로 다른 설계면 판으로 계산됐다 — 설계가 바뀌면 계획 물량 "
                "자체가 바뀌므로 빼면 그 차이가 진척으로 둔갑한다. 같은 판으로 기준 시점을 "
                "다시 계산해야 한다"
            ),
        )
    if baseline.policy.volume_threshold_m != latest.policy.volume_threshold_m:
        return ProgressDerivation(
            None,
            detail=(
                f"집계 문턱이 다르다(기준 {baseline.policy.volume_threshold_m}m, 최신 "
                f"{latest.policy.volume_threshold_m}m) — 다른 자로 잰 두 값의 차이는 "
                "진척이 아니다"
            ),
        )
    if baseline.vertical_reference.datum != latest.vertical_reference.datum:
        return ProgressDerivation(
            None,
            detail=(
                f"수직기준이 다르다(기준 {baseline.vertical_reference.datum.value}, 최신 "
                f"{latest.vertical_reference.datum.value}) — 한국에서 타원체고와 정표고는 "
                "20~30m 차이다"
            ),
        )
    if baseline.crs != latest.crs:
        return ProgressDerivation(
            None,
            detail=(
                f"좌표계가 다르다(기준 {baseline.crs}, 최신 {latest.crs}) — 면적이 "
                "달라지면 체적이 달라진다"
            ),
        )

    baseline_zones = {zone.zone_id: zone for zone in baseline.zones}
    latest_zones = {zone.zone_id: zone for zone in latest.zones}
    matched = [zone_id for zone_id in latest_zones if zone_id in baseline_zones]
    unmatched = tuple(
        sorted(set(baseline_zones) ^ set(latest_zones))  # 한쪽에만 있는 구역 전부
    )
    if not matched:
        return ProgressDerivation(
            None,
            unmatched_zone_ids=unmatched,
            detail=(
                "두 리포트에 공통 구역이 없다 — 기준 시점과 최신 시점을 **같은 작업구역**"
                "으로 계산해야 이어진다(즉석으로 그린 폴리곤은 매번 다른 구역이 된다)"
            ),
        )

    # zoneId 가 같아도 "같은 곳을 쟀다"는 보장이 안 된다(모듈 docstring) — 두
    # 리포트가 이미 갖고 있는 area_m2 를 대조해 갈라낸다.
    comparable = [
        zone_id
        for zone_id in matched
        if not _area_mismatch(baseline_zones[zone_id].area_m2, latest_zones[zone_id].area_m2)
    ]
    area_mismatch = tuple(
        sorted(zone_id for zone_id in matched if zone_id not in comparable)
    )
    if not comparable:
        return ProgressDerivation(
            None,
            unmatched_zone_ids=unmatched,
            area_mismatch_zone_ids=area_mismatch,
            detail=(
                "공통 구역은 있지만 전부 측정 면적이 기준 시점과 크게 달라 같은 곳을 "
                "쟀다고 볼 수 없다 — zoneId가 같아도 이번 비행에서 그 구역 일부가 안 "
                "찍혔거나(구름·그늘·비행경로 차이), 즉석으로 그린 구역이 매번 다른 "
                "범위였을 수 있다. 작업구역을 등록해 범위를 고정하거나, 같은 범위로 "
                "다시 재야 진척이 나온다"
            ),
        )

    names = zone_names or {}
    zones = []
    unrepresentable: list[str] = []
    for zone_id in comparable:
        try:
            zones.append(
                _zone_progress(baseline_zones[zone_id], latest_zones[zone_id], names.get(zone_id))
            )
        except ValidationError:
            # done/planned 가 float 범위를 넘어 inf 가 되면 ZoneProgress 의 유한성
            # 게이트(allow_inf_nan=False)가 거부한다. 여기서 안 잡으면 조회 라우트가
            # 500 을 내고, 리포트가 원장에 남아 있는 한 **그 현장의 진척 조회가
            # 영원히 500** 이다(2026-08-18 재조사 F6 실측: 기준 cut 1e-6 급 + 최신
            # cut 1e308 조합). 이 함수의 계약은 "못 내면 이유를 낸다"이므로 그
            # 구역을 typed 사유로 접는다 — 숫자를 지어내 표를 채우지 않는다.
            unrepresentable.append(zone_id)
    if unrepresentable:
        return ProgressDerivation(
            None,
            unmatched_zone_ids=unmatched,
            area_mismatch_zone_ids=area_mismatch,
            detail=(
                "일부 구역의 진척 비율이 수로 표현되지 않는다"
                f"(구역: {', '.join(sorted(unrepresentable))}) — 두 시점의 절·성토 "
                "물량 차이가 계산 범위를 넘었다. 리포트 물량 값이 실측 범위를 "
                "벗어났는지(워커 오염 입력) 확인이 필요하다"
            ),
        )
    progress = DesignProgress(
        site_id=site_id,
        design_surface_id=latest.design_surface_ref.design_surface_id,
        design_surface_sha256=latest.design_surface_ref.sha256,
        baseline_design_conformance_id=baseline.design_conformance_id,
        baseline_computed_at=iso_utc(baseline.computed_at),
        latest_design_conformance_id=latest.design_conformance_id,
        latest_computed_at=iso_utc(latest.computed_at),
        threshold_m=latest.policy.volume_threshold_m,
        zones=zones,
    )
    return ProgressDerivation(
        progress, unmatched_zone_ids=unmatched, area_mismatch_zone_ids=area_mismatch
    )


def _zone_progress(
    baseline: ZoneVolumeDelta, latest: ZoneVolumeDelta, zone_name: str | None
) -> ZoneProgress:
    done_cut = baseline.cut_m3 - latest.cut_m3
    done_fill = baseline.fill_m3 - latest.fill_m3
    return ZoneProgress(
        zone_id=latest.zone_id,
        zone_name=zone_name,
        planned_cut_m3=baseline.cut_m3,
        planned_fill_m3=baseline.fill_m3,
        remaining_cut_m3=latest.cut_m3,
        remaining_fill_m3=latest.fill_m3,
        done_cut_m3=done_cut,
        done_fill_m3=done_fill,
        cut_progress_ratio=_ratio(done_cut, baseline.cut_m3),
        fill_progress_ratio=_ratio(done_fill, baseline.fill_m3),
        basis=_basis(done_cut, baseline.cut_m3, done_fill, baseline.fill_m3),
    )


def _ratio(done: float, planned: float) -> float | None:
    if planned <= PLANNED_EPSILON_M3:
        return None
    return done / planned


def _basis(done_cut: float, planned_cut: float, done_fill: float, planned_fill: float) -> str:
    """이 행을 어떻게 읽어야 하는가 — 숫자만으로는 오해되는 상태에 이름을 준다."""
    notes: list[str] = []
    if planned_cut <= PLANNED_EPSILON_M3 and planned_fill <= PLANNED_EPSILON_M3:
        return _BASIS_NO_PLAN
    if done_cut < 0.0 or done_fill < 0.0:
        notes.append(_BASIS_REGRESSED)
    if (planned_cut > PLANNED_EPSILON_M3 and done_cut > planned_cut) or (
        planned_fill > PLANNED_EPSILON_M3 and done_fill > planned_fill
    ):
        notes.append(_BASIS_OVERSHOOT)
    if planned_cut <= PLANNED_EPSILON_M3 or planned_fill <= PLANNED_EPSILON_M3:
        notes.append(_BASIS_NO_PLAN)
    if not notes:
        return _BASIS_NORMAL
    return " / ".join(notes)


# ── API ────────────────────────────────────────────────────────────────
class ProgressBaselineRequest(CamelModel):
    design_surface_id: str = Field(min_length=1)


class ProgressBaselineResponse(CamelModel):
    verdict: str
    detail: str | None = None


class DesignProgressResponse(CamelModel):
    """진척 표 또는 왜 못 내는지. **둘 중 하나는 항상 채워진다.**

    빈 응답을 200 으로 내지 않는 이유 — 화면이 "아직 데이터가 없다"와 "이어붙일 수
    없다"를 갈라 말해야 하는데, 빈 표는 그 둘을 같아 보이게 만든다.
    """

    progress: DesignProgress | None = None
    #: 한쪽 시점에만 있던 구역. 표에서 빠진 이유를 화면이 밝힌다.
    unmatched_zone_ids: list[str] = Field(default_factory=list)
    #: 양쪽에 다 있었지만(zoneId 일치) 측정 면적이 크게 달라 "같은 곳을 쟀다"고
    #: 볼 수 없어 표에서 뺀 구역 — unmatched 와는 다른 사유라 따로 알린다.
    area_mismatch_zone_ids: list[str] = Field(default_factory=list)
    detail: str | None = None
    #: 최신 리포트가 속한 임무 — **UI 편의값일 뿐 도메인 모델의 일부가 아니다**
    #: (그래서 ``DesignProgress`` 가 아니라 여기 있다). 화면이 히트맵(임무 스코프
    #: 표면)으로 건너뛸 때만 쓴다. progress 가 없으면 항상 None.
    latest_mission_id: str | None = None


def build_design_progress_router(
    store: DesignConformanceStore, work_area_store: WorkAreaStore | None = None
) -> APIRouter:
    router = APIRouter(tags=["design-progress"])

    @router.post(
        "/v1/missions/{mission_id}/design-conformance/{design_conformance_id}/progress-baseline",
        response_model=ProgressBaselineResponse,
        status_code=201,
    )
    def set_progress_baseline(
        mission_id: str,
        design_conformance_id: str,
        request: ProgressBaselineRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.MISSIONS_ISSUE)),  # noqa: B008
    ) -> ProgressBaselineResponse:
        """이 리포트를 '원지형 기준'으로 지정한다 — 계획 물량이 여기서 나온다.

        권한이 ``MISSIONS_ISSUE`` 인 것은 설계 대비 요청 생성과 같은 자리다 —
        구역·현장의 영속 자산을 바꾸는 것(``SITES_WRITE``)이 아니라, "이 임무의
        어느 결과를 기준으로 볼지" 결정하는 임무 단위 판단이기 때문이다.

        자동으로 고르지 않는 이유가 이 엔드포인트의 존재 이유다. 가장 오래된 리포트를
        기준으로 삼으면, 첫 비행이 이미 시공 중이었을 때 계획 물량이 조용히 깎인다.
        """
        recorded = store.get(mission_id, design_conformance_id)
        if recorded is None:
            response.status_code = 404
            return ProgressBaselineResponse(
                verdict="UNKNOWN_REPORT",
                detail=(
                    f"임무 {mission_id!r} 에 designConformanceId="
                    f"{design_conformance_id!r} 인 리포트가 없다"
                ),
            )
        site_id = store.site_of(design_conformance_id)
        if site_id is None:
            response.status_code = 409
            return ProgressBaselineResponse(
                verdict="UNKNOWN_SITE",
                detail="그 리포트의 요청 기록을 찾을 수 없다 — 현장을 특정할 수 없다",
            )
        ok, detail = store.set_progress_baseline(
            site_id=site_id,
            design_surface_id=request.design_surface_id,
            design_conformance_id=design_conformance_id,
            actor=principal.principal_id,
            now=datetime.now(UTC),
        )
        if not ok:
            response.status_code = 409
            return ProgressBaselineResponse(verdict="REJECTED", detail=detail)
        return ProgressBaselineResponse(verdict="BASELINE_SET")

    @router.get(
        "/v1/sites/{site_id}/design-progress", response_model=DesignProgressResponse
    )
    def get_design_progress(
        site_id: str,
        design_surface_id: str = Query(min_length=1),
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> DesignProgressResponse:
        """구역별 계획·완료·잔여·진척률. 못 내면 그 이유를 낸다(빈 표를 내지 않는다)."""
        del principal
        baseline_id = store.progress_baseline_id(site_id, design_surface_id)
        if baseline_id is None:
            return DesignProgressResponse(
                detail=(
                    "원지형 기준으로 지정된 리포트가 없다 — 계획 물량은 '시공 전 지형 대비 "
                    "설계까지의 잔량'이고, 어느 시점을 그 기준으로 볼지는 사람이 정한다"
                )
            )
        history = [
            recorded
            for recorded in store.site_history(site_id)
            if recorded.report.design_surface_ref.design_surface_id == design_surface_id
        ]
        baseline = next(
            (r.report for r in history if r.report.design_conformance_id == baseline_id),
            None,
        )
        if baseline is None:
            return DesignProgressResponse(
                detail="지정된 기준 리포트를 찾을 수 없다 — 기준을 다시 지정해야 한다"
            )
        # "최신"은 **기록 순서**가 아니라 **계산 시각**(computed_at)으로 고른다 —
        # 기록 순서(리포트가 원장에 append된 순서)와 계산 시각은 보통 같이 가지만,
        # 사람이 지난 epoch를 다시 계산해 나중에 제출하면(예: 1주차 재검산을 3주차
        # 제출 이후에 함) 둘이 갈린다. 기록 순서로 고르면 그 재검산이 조용히
        # "최신"으로 뽑혀 실제로는 기준보다 이른 시점을 최신이라 부르게 된다
        # (독립 검토 2026-08-13 지적 — 반증은 아니었으나 완료기준 목록에 없던 공백).
        candidates = [
            r.report for r in history if r.report.design_conformance_id != baseline_id
        ]
        if not candidates:
            return DesignProgressResponse(
                detail=(
                    "기준 시점 말고 다른 비교가 아직 없다 — 최신 지형으로 설계 대비 잔량을 "
                    "한 번 더 계산하면 진척이 나온다"
                )
            )
        latest = max(candidates, key=lambda report: report.computed_at)
        if latest.computed_at <= baseline.computed_at:
            return DesignProgressResponse(
                detail=(
                    f"가장 최근에 계산된 리포트({latest.computed_at.isoformat()})가 기준 "
                    f"시점({baseline.computed_at.isoformat()})보다 앞서거나 같다 — 진척은 "
                    "기준 이후 시점에 대해서만 말이 된다. 기준 이후 지형으로 다시 계산하거나 "
                    "기준 지정을 다시 확인한다"
                )
            )
        names = (
            work_area_store.names_of([zone.zone_id for zone in latest.zones])
            if work_area_store is not None
            else {}
        )
        derived = derive_progress(baseline, latest, site_id=site_id, zone_names=names)
        return DesignProgressResponse(
            progress=derived.progress,
            unmatched_zone_ids=list(derived.unmatched_zone_ids),
            area_mismatch_zone_ids=list(derived.area_mismatch_zone_ids),
            detail=derived.detail,
            latest_mission_id=(
                store.mission_of(latest.design_conformance_id)
                if derived.progress is not None
                else None
            ),
        )

    return router


def mount_design_progress(
    app: FastAPI,
    store: DesignConformanceStore,
    work_area_store: WorkAreaStore | None = None,
) -> None:
    app.include_router(build_design_progress_router(store, work_area_store))


__all__ = [
    "AREA_MISMATCH_RATIO_THRESHOLD",
    "DesignProgressResponse",
    "ProgressBaselineRequest",
    "ProgressBaselineResponse",
    "ProgressDerivation",
    "build_design_progress_router",
    "derive_progress",
    "mount_design_progress",
]
