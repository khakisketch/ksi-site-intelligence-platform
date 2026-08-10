"""점군 변화탐지 종단 실행기 — 두 epoch point cloud 에서 결과까지 (W2, run_volume_change.py 대칭).

## 이 모듈이 잇는 것

``Core 에서 두 point cloud 를 받는다 → C2C 최근접거리를 잰다 → Core 에 결과를
올린다``. 계산(``point_cloud_diff.detect_change_candidates``)과 계약
(``ChangeDetectionResult``)은 이미 있었지만 **이어 부르는 코드가 없었다** —
``run_volume_change.py`` 가 체적 쪽에서 이미 메운 자리와 정확히 대칭이다.

## 자동으로 돌지 않는다

이 함수 자체는 데몬이 아니다. 호출자(``ksi_processing_controller.
comparison_worker``)가 "이 두 point cloud 를 비교하라"는 요청을 받아 부른다.

## 점군 파일 형식 — LAZ(LASzip)

ODM 이 내놓는 원본 point cloud 는 ``.laz``다(``odm_assets.py`` 의
``POINT_CLOUD_ID`` 매핑). laspy(BSD-3)+lazrs(MIT/Apache-2.0)로 읽는다 — 둘 다
허용 라이선스이고 AGPL/GPL 프로세스경계(ADR-KSI-012 D2)와 무관하다(``point_cloud_
diff.py`` 모듈 docstring 이 이미 CloudCompare/Open3D 를 이 경계로 배제한 것과
같은 판단 기준. laspy/lazrs 는 애초에 그 배제 대상이 아니다).
"""

from __future__ import annotations

import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx
import laspy
import numpy as np
from ksi_event_contracts.change_detection_result import ArtifactRef, ChangeDetectionResult
from ksi_event_contracts.comparison_policy import (
    DEFAULT_DISTANCE_THRESHOLD_M as _POLICY_DISTANCE_THRESHOLD_M,
)
from numpy.typing import NDArray

from ksi_change_detection.point_cloud_diff import ChangeDetectionError, detect_change_candidates

logger = logging.getLogger(__name__)

#: C2C 후보 거리 문턱 기본값 — **정본은 계약 패키지**다(``ksi_event_contracts.
#: comparison_policy``). 여기서 재노출하는 이유는 기존 호출부·테스트의 import 를
#: 그대로 두기 위해서고, 값을 여기서 다시 정하지 않는다: 화면이 "이 값을 쓴다"고
#: 표시하려면 계산 쪽과 조회 쪽이 같은 자리를 읽어야 한다(그 모듈 docstring).
DEFAULT_DISTANCE_THRESHOLD_M = _POLICY_DISTANCE_THRESHOLD_M


class ChangeDetectionRunError(RuntimeError):
    """종단 실행 실패 — 부분 결과를 원장에 올리지 않는다."""


class ChangeDetectionSink(Protocol):
    """계산된 결과를 받는 곳 — Core 클라이언트를 이 형태로 주입한다."""

    def submit_change_detection(self, mission_id: str, result: ChangeDetectionResult) -> None: ...


def _download(client: httpx.Client, url: str, dest: Path) -> None:
    try:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with dest.open("wb") as handle:
                for chunk in response.iter_bytes(1024 * 1024):
                    handle.write(chunk)
    except httpx.HTTPStatusError as exc:
        # url 은 쿼리스트링(presigned 서명)을 잘라내고 남긴다 — httpx.HTTPStatusError
        # 자신의 str() 도 str(exc.request.url) 을 그대로 품어(요청 URL 원문) 서명이
        # 다시 새므로 str(exc) 를 통째로 쓰지 않고 상태코드만 뽑는다. 이 메시지는
        # FAILED detail 로 원장에 남고 화면에 그대로 보인다(실 인프라 재현 중 발견:
        # 서명이 실린 URL 을 사용자 화면에 그대로 노출하고 있었다).
        raise ChangeDetectionRunError(
            f"point cloud 를 받지 못했다({url.split('?', 1)[0]}): "
            f"HTTP {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        raise ChangeDetectionRunError(
            f"point cloud 를 받지 못했다({url.split('?', 1)[0]}): {type(exc).__name__}"
        ) from exc


def _read_points(path: Path) -> NDArray[np.float64]:
    """LAZ/LAS 파일에서 (N, 3) 좌표 배열을 읽는다.

    ``laspy`` 의 ``.x``/``.y``/``.z`` 는 헤더의 scale·offset 이 이미 적용된
    실좌표(미터 단위, 원시 정수 ``X``/``Y``/``Z`` 가 아니다)다.
    """
    try:
        with laspy.open(path) as reader:
            data = reader.read()
    except laspy.LaspyException as exc:
        raise ChangeDetectionRunError(f"point cloud 를 읽지 못했다({path}): {exc}") from exc
    return np.column_stack((data.x, data.y, data.z)).astype(np.float64)


def compute_change_detection(
    *,
    change_detection_id: str,
    baseline: ArtifactRef,
    baseline_download_url: str,
    current: ArtifactRef,
    current_download_url: str,
    computed_at: datetime,
    http_client: httpx.Client,
    distance_threshold_m: float = DEFAULT_DISTANCE_THRESHOLD_M,
    work_dir: Path | None = None,
) -> ChangeDetectionResult:
    """두 point cloud 를 받아 C2C 거리를 재고 결과를 만든다(제출하지 않는다).

    계산·제출을 분리한 이유는 ``run_volume_change.compute_volume_change`` 와
    같다 — 제출 실패가 계산을 되돌리게 만들지 않기 위해서다. ``computed_at`` 을
    인자로 받는 것도 같은 이유(결정성 — 재현 테스트가 성립하려면 이 함수가
    시각을 스스로 만들면 안 된다).
    """
    with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
        base_path = Path(tmp) / "baseline.laz"
        curr_path = Path(tmp) / "current.laz"
        _download(http_client, baseline_download_url, base_path)
        _download(http_client, current_download_url, curr_path)

        baseline_points = _read_points(base_path)
        current_points = _read_points(curr_path)

    try:
        candidates = detect_change_candidates(
            baseline=baseline_points,
            current=current_points,
            distance_threshold_m=distance_threshold_m,
        )
    except ChangeDetectionError as exc:
        raise ChangeDetectionRunError(f"C2C 계산 실패: {exc}") from exc

    max_distance_m = float(np.max(candidates.distances_m))

    return ChangeDetectionResult(
        change_detection_id=change_detection_id,
        baseline=baseline,
        current=current,
        distance_threshold_m=distance_threshold_m,
        point_count=len(current_points),
        candidate_count=candidates.candidate_count,
        candidate_ratio=candidates.candidate_ratio,
        max_distance_m=max_distance_m,
        computed_at=computed_at.astimezone(UTC),
    )


def compute_and_submit_change_detection(
    *,
    sink: ChangeDetectionSink,
    mission_id: str,
    change_detection_id: str,
    baseline: ArtifactRef,
    baseline_download_url: str,
    current: ArtifactRef,
    current_download_url: str,
    computed_at: datetime,
    http_client: httpx.Client,
    distance_threshold_m: float = DEFAULT_DISTANCE_THRESHOLD_M,
    work_dir: Path | None = None,
) -> ChangeDetectionResult:
    """계산 후 Core 에 제출한다. 제출 실패는 그대로 올라온다(삼키지 않는다)."""
    result = compute_change_detection(
        change_detection_id=change_detection_id,
        baseline=baseline,
        baseline_download_url=baseline_download_url,
        current=current,
        current_download_url=current_download_url,
        computed_at=computed_at,
        http_client=http_client,
        distance_threshold_m=distance_threshold_m,
        work_dir=work_dir,
    )
    sink.submit_change_detection(mission_id, result)
    logger.info(
        "변화탐지 결과 제출: mission=%s id=%s 후보 %d/%d(%.4f)",
        mission_id,
        change_detection_id,
        result.candidate_count,
        result.point_count,
        result.candidate_ratio,
    )
    return result


__all__ = [
    "DEFAULT_DISTANCE_THRESHOLD_M",
    "ChangeDetectionRunError",
    "ChangeDetectionSink",
    "compute_and_submit_change_detection",
    "compute_change_detection",
]
