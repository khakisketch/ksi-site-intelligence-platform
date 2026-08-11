"""체적 변화 종단 실행기 — 두 epoch 에서 리포트까지 (ADR-KSI-016 D3).

## 이 모듈이 잇는 것

``Core 에서 두 DSM 을 받는다 → 차분한다 → 구역 체적을 잰다 → Core 에 리포트를
올린다``. 각 조각은 이미 검증돼 있었지만 **이어 부르는 코드가 없었다** — 워커의
``run_job`` 이 재구성 쪽에서 같은 자리를 메운 것과 대칭이다.

## 자동으로 돌지 않는다

M1 은 이 함수를 데몬·스케줄러에 걸지 않는다. 운영자(또는 스크립트)가 "이 두
epoch 을 비교하라"고 지목해서 부른다. "변화가 크면 알아서 다시 촬영"까지 가는
폐루프는 다음 마일스톤이다(ADR-KSI-016 D8) — 지금 자동화하면 어느 두 시점을
비교할지, 어느 구역을 잴지를 코드가 추측하게 된다.

## 구역은 호출자가 준다

이 코드베이스는 **임무 AOI 와 현장 AOI 를 의도적으로 구분한다**(``sites.py``:
짝 발급은 ``site.aoi`` 를 보지 않고 매 요청의 ``request.aoi`` 를 쓴다). 체적을
재는 구역은 "실제로 촬영된 범위"여야 하므로 여기서 ``site.aoi`` 를 암묵
기본값으로 삼지 않는다 — 호출자가 명시적으로 넘긴다.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.comparison_policy import (
    DEFAULT_VOLUME_THRESHOLD_M as _POLICY_VOLUME_THRESHOLD_M,
)
from ksi_event_contracts.volume_change_report import VolumeChangeReport, ZoneVolumeDelta

from ksi_change_detection.download_errors import download_failure_detail
from ksi_change_detection.dsm_diff import DsmDiffError, align_and_diff, volume_delta_in_polygon

logger = logging.getLogger(__name__)

#: 재구성 노이즈 하한 기본값 — **정본은 계약 패키지**다(``ksi_event_contracts.
#: comparison_policy``). 재노출 이유는 ``run_change_detection.
#: DEFAULT_DISTANCE_THRESHOLD_M`` 과 같다(기존 import 유지 + 단일 정본).
DEFAULT_THRESHOLD_M = _POLICY_VOLUME_THRESHOLD_M

#: ODM 경로에서 오차한계를 못 내는 이유 — 리포트에 그대로 실린다(INV-024).
ODM_NO_CHECKPOINT_NOTE = (
    "기본 엔진(ODM)이 구조화된 GCP/검사점 RMSE 리포트를 내지 않아 절대 오차한계를 "
    "산출할 수 없다 — 같은 파이프라인·같은 좌표계의 두 시점을 비교한 상대값이다"
)


class VolumeChangeRunError(RuntimeError):
    """종단 실행 실패 — 부분 결과를 리포트로 올리지 않는다."""


@dataclass(frozen=True, slots=True)
class ArtifactSource:
    """비교 대상 산출물 하나 — 참조 + 그 바이트를 받을 URL.

    ``rmse_m`` 은 그 epoch 이 독립 검사점으로 검증됐을 때만 값이다. ODM 경로는
    항상 ``None`` 이고, 그러면 오차한계도 ``None`` 이 된다(INV-024).
    """

    ref: ArtifactRef
    download_url: str
    rmse_m: float | None = None


class VolumeChangeSink(Protocol):
    """계산된 리포트를 받는 곳 — Core 클라이언트를 이 형태로 주입한다."""

    def submit_volume_change(self, mission_id: str, report: VolumeChangeReport) -> None:
        ...


def compute_volume_change(
    *,
    volume_change_id: str,
    baseline: ArtifactSource,
    current: ArtifactSource,
    zones: dict[str, dict[str, Any]],
    zone_crs: str,
    vertical_datum: str,
    computed_at: datetime,
    http_client: httpx.Client,
    threshold_m: float = DEFAULT_THRESHOLD_M,
    uncertainty_note: str = ODM_NO_CHECKPOINT_NOTE,
    work_dir: Path | None = None,
) -> VolumeChangeReport:
    """두 DSM 을 받아 구역별 체적을 재고 리포트를 만든다(제출하지 않는다).

    ``zones`` 는 ``{zoneId: GeoJSON Polygon}`` 이고 ``zone_crs`` 는 그 폴리곤의
    좌표계다(보통 EPSG:4326). 계산·제출을 분리한 이유는 제출 실패가 계산을
    되돌리게 만들지 않기 위해서다 — 같은 리포트를 그대로 재제출하면 Core 가
    멱등 처리한다.

    ``computed_at`` 을 인자로 받는 것은 결정성 때문이다. 이 함수가 시각을
    스스로 만들면 같은 입력이 매번 다른 리포트가 되고, 재현 테스트가 성립하지
    않는다.
    """
    if not zones:
        raise VolumeChangeRunError("잴 구역이 하나도 주어지지 않았다")

    with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
        base_path = Path(tmp) / "baseline.tif"
        curr_path = Path(tmp) / "current.tif"
        _download(http_client, baseline.download_url, base_path)
        _download(http_client, current.download_url, curr_path)

        try:
            diff = align_and_diff(base_path, curr_path)
            deltas: list[ZoneVolumeDelta] = [
                volume_delta_in_polygon(
                    diff,
                    polygon,
                    zone_id=zone_id,
                    from_crs=zone_crs,
                    threshold_m=threshold_m,
                    uncertainty_note=uncertainty_note,
                    baseline_rmse_m=baseline.rmse_m,
                    current_rmse_m=current.rmse_m,
                )
                for zone_id, polygon in zones.items()
            ]
        except DsmDiffError as exc:
            raise VolumeChangeRunError(f"체적 계산 실패: {exc}") from exc
        crs = diff.crs

    return VolumeChangeReport(
        volume_change_id=volume_change_id,
        baseline=baseline.ref,
        current=current.ref,
        crs=crs,
        vertical_datum=vertical_datum,
        zones=deltas,
        computed_at=computed_at.astimezone(UTC),
    )


def compute_and_submit(
    *,
    sink: VolumeChangeSink,
    mission_id: str,
    volume_change_id: str,
    baseline: ArtifactSource,
    current: ArtifactSource,
    zones: dict[str, dict[str, Any]],
    zone_crs: str,
    vertical_datum: str,
    computed_at: datetime,
    http_client: httpx.Client,
    threshold_m: float = DEFAULT_THRESHOLD_M,
    uncertainty_note: str = ODM_NO_CHECKPOINT_NOTE,
    work_dir: Path | None = None,
) -> VolumeChangeReport:
    """계산 후 Core 에 제출한다. 제출 실패는 그대로 올라온다(삼키지 않는다)."""
    report = compute_volume_change(
        volume_change_id=volume_change_id,
        baseline=baseline,
        current=current,
        zones=zones,
        zone_crs=zone_crs,
        vertical_datum=vertical_datum,
        computed_at=computed_at,
        http_client=http_client,
        threshold_m=threshold_m,
        uncertainty_note=uncertainty_note,
        work_dir=work_dir,
    )
    sink.submit_volume_change(mission_id, report)
    logger.info(
        "체적 리포트 제출: mission=%s id=%s 구역 %d개 순변화 %.2f m³",
        mission_id,
        volume_change_id,
        len(report.zones),
        report.total_net_m3,
    )
    return report


def _download(client: httpx.Client, url: str, dest: Path) -> None:
    try:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with dest.open("wb") as handle:
                for chunk in response.iter_bytes(1024 * 1024):
                    handle.write(chunk)
    except httpx.HTTPStatusError as exc:
        # run_change_detection.py 의 _download 와 동일 근거(download_errors 모듈).
        raise VolumeChangeRunError(
            download_failure_detail(
                what="DSM", url=url, cause=f"HTTP {exc.response.status_code}"
            )
        ) from exc
    except httpx.HTTPError as exc:
        raise VolumeChangeRunError(
            download_failure_detail(
                what="DSM", url=url, cause=f"{type(exc).__name__}: {exc}"
            )
        ) from exc


__all__ = [
    "DEFAULT_THRESHOLD_M",
    "ODM_NO_CHECKPOINT_NOTE",
    "ArtifactSource",
    "VolumeChangeRunError",
    "VolumeChangeSink",
    "compute_and_submit",
    "compute_volume_change",
]
