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
from ksi_geo_spatial.crs import assert_same_crs, assert_supported_project_crs
from numpy.typing import NDArray

from ksi_change_detection.download_errors import download_failure_detail
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
        # 상태코드가 곧 원인이라 str(exc)(요청 URL 원문을 품는다)를 쓸 이유가 없다.
        raise ChangeDetectionRunError(
            download_failure_detail(
                what="point cloud", url=url, cause=f"HTTP {exc.response.status_code}"
            )
        ) from exc
    except httpx.HTTPError as exc:
        # 전송 실패는 **원인 문자열이 곧 진단**이다(연결 거부·타임아웃·프로토콜
        # 오류) — 클래스 이름만 남기면 그 진단이 사라진다. 서명 유출은 타입
        # 열거가 아니라 출력 검사로 막는다(download_errors 모듈 docstring).
        raise ChangeDetectionRunError(
            download_failure_detail(
                what="point cloud", url=url, cause=f"{type(exc).__name__}: {exc}"
            )
        ) from exc


def _read_points(path: Path) -> tuple[NDArray[np.float64], str | None]:
    """LAZ/LAS 파일에서 (N, 3) 좌표 배열과 헤더에 박힌 좌표계를 읽는다.

    ``laspy`` 의 ``.x``/``.y``/``.z`` 는 헤더의 scale·offset 이 이미 적용된
    실좌표(미터 단위, 원시 정수 ``X``/``Y``/``Z`` 가 아니다)다. 좌표계는
    VLR 에 박혀 있으면 읽히고, 없으면 ``None`` 이다(fail-closed 판단은 호출부 몫).
    """
    try:
        with laspy.open(path) as reader:
            crs = reader.header.parse_crs()
            data = reader.read()
    except laspy.LaspyException as exc:
        raise ChangeDetectionRunError(f"point cloud 를 읽지 못했다({path}): {exc}") from exc
    points = np.column_stack((data.x, data.y, data.z)).astype(np.float64)
    return points, (str(crs) if crs is not None else None)


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

        baseline_points, baseline_crs = _read_points(base_path)
        current_points, current_crs = _read_points(curr_path)

    # INV-020 강제 지점 — dsm_diff.align_and_diff 와 동형. point_cloud_diff 는
    # 정합(registration)을 하지 않고 "이미 같은 좌표계"라는 전제로 최근접거리를
    # 재므로, 그 전제를 여기서 검증하지 않으면 서로 다른(심지어 지원 밖) 좌표계의
    # 두 점군을 빼고도 "그럴듯한 변화 후보"를 만들어낸다(2026-08-11 실 종단
    # 실행에서 EPSG:32617 로 라벨된 두 산출물이 검증 없이 통과해 후보비율
    # 99.9995%·평균 90m 하강이라는 물리적으로 말이 안 되는 결과를 냈다).
    if baseline_crs is None or current_crs is None:
        raise ChangeDetectionRunError(
            "point cloud 에 좌표계가 없다 — CRS 없는 point cloud 는 다른 시점과 비교할 수 없다"
        )
    # CrsMismatchError/UnsupportedCrsError 는 감싸지 않고 그대로 전파한다 —
    # run_volume_change.compute_volume_change 가 align_and_diff 의 같은 두 예외를
    # 감싸지 않는 것과 동형(그쪽은 DsmDiffError 만 잡는다).
    crs = assert_same_crs(baseline_crs, current_crs)
    assert_supported_project_crs(crs)

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
