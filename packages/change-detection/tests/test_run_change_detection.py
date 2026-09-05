"""run_change_detection 종단 — 두 LAZ 파일에서 ChangeDetectionResult 까지.

``test_change_detection.py``(tests/contract)가 순수 numpy 배열로 C2C 계산
자체를 검증한다면, 이 파일은 **파일 I/O + 계약 구성 + 제출**을 검증한다 —
실제 laspy 로 만든 .laz 를 읽어 손계산 가능한 결과가 나오는지, 그리고
``run_volume_change.py`` 테스트와 동형으로 sink 제출·다운로드 실패 처리를 본다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import laspy
import numpy as np
import pytest
from ksi_change_detection.run_change_detection import (
    ChangeDetectionRunError,
    compute_and_submit_change_detection,
    compute_change_detection,
)
from ksi_event_contracts.change_detection_result import ArtifactRef, ChangeDetectionResult
from ksi_geo_spatial.crs import CrsMismatchError, UnsupportedCrsError
from pyproj import CRS

_COMPUTED_AT = datetime(2026, 8, 10, 5, 0, tzinfo=UTC)

# EPSG:5186 중부원점 — dsm_diff 쪽 테스트 픽스처(test_dsm_diff.py)와 동형.
_DEFAULT_CRS = "EPSG:5186"


def _write_laz(path: Path, points: np.ndarray, *, crs: str | None = _DEFAULT_CRS) -> Path:
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.offsets = [0.0, 0.0, 0.0]
    header.scales = [0.001, 0.001, 0.001]
    if crs is not None:
        header.add_crs(CRS.from_user_input(crs))
    las = laspy.LasData(header)
    las.x = points[:, 0]
    las.y = points[:, 1]
    las.z = points[:, 2]
    las.write(str(path))
    return path


def _grid(n: int, *, z: float = 0.0) -> np.ndarray:
    """x=0..n-1, y=0, z=z 인 점 n개 — 손계산 가능한 단순 배치(test_change_detection.py 와 동형)."""
    return np.array([[float(i), 0.0, z] for i in range(n)])


def _storage_transport(files: dict[str, Path]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        path = files.get(name)
        if path is None:
            return httpx.Response(404)
        return httpx.Response(200, content=path.read_bytes())

    return httpx.MockTransport(handler)


class _FakeSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ChangeDetectionResult]] = []

    def submit_change_detection(self, mission_id: str, result: ChangeDetectionResult) -> None:
        self.calls.append((mission_id, result))


def test_single_moved_point_produces_expected_result(tmp_path: Path) -> None:
    """baseline 은 x=0..9 격자, current 는 점 하나(5,0,0)->(5,10,0) 이동 —
    손계산: candidateCount=1, candidateRatio=0.1, maxDistanceM=10.0."""
    baseline = _grid(10)
    current = _grid(10)
    current[5] = [5.0, 10.0, 0.0]
    base_path = _write_laz(tmp_path / "baseline.laz", baseline)
    curr_path = _write_laz(tmp_path / "current.laz", current)

    transport = _storage_transport({"baseline.laz": base_path, "current.laz": curr_path})
    baseline_ref = ArtifactRef(job_id="job-a", artifact_id="point-cloud")
    current_ref = ArtifactRef(job_id="job-b", artifact_id="point-cloud")

    with httpx.Client(transport=transport, base_url="http://storage.test") as client:
        result = compute_change_detection(
            change_detection_id="mission-1-cmp1",
            baseline=baseline_ref,
            baseline_download_url="http://storage.test/x/baseline.laz",
            current=current_ref,
            current_download_url="http://storage.test/x/current.laz",
            computed_at=_COMPUTED_AT,
            http_client=client,
            distance_threshold_m=1.0,
        )

    assert result.point_count == 10
    assert result.candidate_count == 1
    assert result.candidate_ratio == pytest.approx(0.1)
    assert result.max_distance_m == pytest.approx(10.0, abs=1e-3)
    assert result.distance_threshold_m == pytest.approx(1.0)
    assert result.baseline == baseline_ref
    assert result.current == current_ref
    assert result.computed_at == _COMPUTED_AT


def test_identical_clouds_have_no_candidates(tmp_path: Path) -> None:
    cloud = _grid(8)
    base_path = _write_laz(tmp_path / "baseline.laz", cloud)
    curr_path = _write_laz(tmp_path / "current.laz", cloud.copy())
    transport = _storage_transport({"baseline.laz": base_path, "current.laz": curr_path})

    with httpx.Client(transport=transport, base_url="http://storage.test") as client:
        result = compute_change_detection(
            change_detection_id="mission-1-cmp2",
            baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
            baseline_download_url="http://storage.test/x/baseline.laz",
            current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
            current_download_url="http://storage.test/x/current.laz",
            computed_at=_COMPUTED_AT,
            http_client=client,
            distance_threshold_m=0.01,
        )

    assert result.candidate_count == 0
    assert result.candidate_ratio == pytest.approx(0.0)
    assert result.max_distance_m == pytest.approx(0.0, abs=1e-3)


def test_compute_and_submit_calls_sink(tmp_path: Path) -> None:
    cloud = _grid(6)
    base_path = _write_laz(tmp_path / "baseline.laz", cloud)
    curr_path = _write_laz(tmp_path / "current.laz", cloud.copy())
    transport = _storage_transport({"baseline.laz": base_path, "current.laz": curr_path})
    sink = _FakeSink()

    with httpx.Client(transport=transport, base_url="http://storage.test") as client:
        result = compute_and_submit_change_detection(
            sink=sink,
            mission_id="mission-1",
            change_detection_id="mission-1-cmp3",
            baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
            baseline_download_url="http://storage.test/x/baseline.laz",
            current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
            current_download_url="http://storage.test/x/current.laz",
            computed_at=_COMPUTED_AT,
            http_client=client,
        )

    assert sink.calls == [("mission-1", result)]


def test_missing_crs_is_refused(tmp_path: Path) -> None:
    """[핵심 음성] 좌표계가 없는 point cloud 는 비교하지 않는다 — dsm_diff.
    align_and_diff 의 'CRS 없는 래스터는 비교할 수 없다'와 동형."""
    cloud = _grid(6)
    base_path = _write_laz(tmp_path / "baseline.laz", cloud, crs=None)
    curr_path = _write_laz(tmp_path / "current.laz", cloud.copy(), crs=None)
    transport = _storage_transport({"baseline.laz": base_path, "current.laz": curr_path})

    with (
        httpx.Client(transport=transport, base_url="http://storage.test") as client,
        pytest.raises(ChangeDetectionRunError, match="좌표계가 없다"),
    ):
        compute_change_detection(
            change_detection_id="mission-1-cmp7",
            baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
            baseline_download_url="http://storage.test/x/baseline.laz",
            current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
            current_download_url="http://storage.test/x/current.laz",
            computed_at=_COMPUTED_AT,
            http_client=client,
        )


def test_mismatched_crs_is_refused(tmp_path: Path) -> None:
    """[핵심 음성] 두 epoch 의 좌표계가 서로 다르면 거부한다(INV-020)."""
    cloud = _grid(6)
    base_path = _write_laz(tmp_path / "baseline.laz", cloud, crs="EPSG:5186")
    curr_path = _write_laz(tmp_path / "current.laz", cloud.copy(), crs="EPSG:5187")
    transport = _storage_transport({"baseline.laz": base_path, "current.laz": curr_path})

    with (
        httpx.Client(transport=transport, base_url="http://storage.test") as client,
        pytest.raises(CrsMismatchError),
    ):
        compute_change_detection(
            change_detection_id="mission-1-cmp8",
            baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
            baseline_download_url="http://storage.test/x/baseline.laz",
            current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
            current_download_url="http://storage.test/x/current.laz",
            computed_at=_COMPUTED_AT,
            http_client=client,
        )


def test_unsupported_crs_is_refused_even_when_both_epochs_match(tmp_path: Path) -> None:
    """[핵심 음성][회귀 2026-08-11] 두 epoch 가 서로 '같은' 좌표계라도 그 좌표계가
    지원 화이트리스트 밖(다른 대륙의 UTM 존 등)이면 거부한다 — dsm_diff.py 의
    동형 회귀(test_dsm_diff.test_unsupported_crs_is_refused_even_when_both_epochs_match)
    와 같은 실 사고를 점군 경로에서 재현한다. ``point_cloud_diff`` 는 정합
    (registration)을 하지 않고 '이미 같은 좌표계'라는 전제로 최근접거리만 재므로,
    이 검증이 없으면 서로 다른 대륙의 두 점군을 빼고도 그럴듯한 변화 후보를
    만들어낸다."""
    cloud = _grid(6)
    base_path = _write_laz(tmp_path / "baseline.laz", cloud, crs="EPSG:32617")
    curr_path = _write_laz(tmp_path / "current.laz", cloud.copy(), crs="EPSG:32617")
    transport = _storage_transport({"baseline.laz": base_path, "current.laz": curr_path})

    with (
        httpx.Client(transport=transport, base_url="http://storage.test") as client,
        pytest.raises(UnsupportedCrsError),
    ):
        compute_change_detection(
            change_detection_id="mission-1-cmp9",
            baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
            baseline_download_url="http://storage.test/x/baseline.laz",
            current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
            current_download_url="http://storage.test/x/current.laz",
            computed_at=_COMPUTED_AT,
            http_client=client,
        )


def test_download_failure_raises_run_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    with (
        httpx.Client(transport=transport, base_url="http://storage.test") as client,
        pytest.raises(ChangeDetectionRunError),
    ):
        compute_change_detection(
            change_detection_id="mission-1-cmp4",
            baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
            baseline_download_url="http://storage.test/x/missing.laz",
            current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
            current_download_url="http://storage.test/x/missing.laz",
            computed_at=_COMPUTED_AT,
            http_client=client,
        )


def test_download_failure_message_does_not_leak_presigned_signature(tmp_path: Path) -> None:
    """[핵심][회귀] FAILED 사유가 그대로 화면에 노출된다(comparison_requests
    detail → /reports) — presigned URL 의 서명 쿼리스트링까지 그 문구에 실리면
    사용자 화면에 서명이 그대로 보인다(2026-08-10 실 인프라 재현으로 발견)."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(404)

    signed_url = (
        "http://storage.test/x/missing.laz"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=deadbeef1234"
    )
    transport = httpx.MockTransport(handler)
    with (
        httpx.Client(transport=transport, base_url="http://storage.test") as client,
        pytest.raises(ChangeDetectionRunError) as excinfo,
    ):
        compute_change_detection(
            change_detection_id="mission-1-cmp5",
            baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
            baseline_download_url=signed_url,
            current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
            current_download_url=signed_url,
            computed_at=_COMPUTED_AT,
            http_client=client,
        )
    assert "X-Amz-Signature" not in str(excinfo.value)
    assert "deadbeef1234" not in str(excinfo.value)
    assert "http://storage.test/x/missing.laz" in str(excinfo.value)


def test_transport_failure_keeps_the_cause_and_still_hides_the_signature(
    tmp_path: Path,
) -> None:
    """[핵심][회귀] 전송 실패(연결 거부·타임아웃)는 **원인 문자열이 곧 진단**이다.

    서명 유출을 막던 첫 수정이 예외 클래스 이름만 남기는 바람에
    ``[Errno 111] Connection refused`` 같은 진짜 원인이 통째로 사라졌었다 —
    방화벽 변경인지 DNS 실패인지 백엔드 지연인지 구분해야 하는 자리가 정확히
    실 인프라 장애 대응이다. 원인은 살리되 서명은 여전히 지운다.
    """
    del tmp_path

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[Errno 111] Connection refused", request=request)

    signed_url = (
        "http://storage.test/x/pc.laz"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=deadbeef1234"
    )
    transport = httpx.MockTransport(handler)
    with (
        httpx.Client(transport=transport, base_url="http://storage.test") as client,
        pytest.raises(ChangeDetectionRunError) as excinfo,
    ):
        compute_change_detection(
            change_detection_id="mission-1-cmp6",
            baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
            baseline_download_url=signed_url,
            current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
            current_download_url=signed_url,
            computed_at=_COMPUTED_AT,
            http_client=client,
        )
    message = str(excinfo.value)
    # 원인이 남아 있다 — 이게 이 테스트의 핵심이다.
    assert "Connection refused" in message
    # 그러면서도 서명은 없다.
    assert "X-Amz-Signature" not in message
    assert "deadbeef1234" not in message
