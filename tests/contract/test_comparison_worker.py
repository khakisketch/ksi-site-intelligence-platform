"""비교 워커 오케스트레이션 계약 (``ksi_processing_controller.comparison_worker``).

``test_worker.py`` 가 재구성 쪽(``run_job``)의 순서를 가짜 Core·가짜 NodeODM 으로
고정한 것과 동형이다 — 이 파일은 ``run_comparison_request`` 의 순서를 가짜 Core
(비교 표면)로 고정한다: lease → 입력수신 → (QUEUED 면) RUNNING → 계산+제출
(point_cloud 쌍이 있으면 변화탐지, dsm 쌍+구역이 있으면 체적) → SUCCEEDED. 실패는
FAILED 로 수렴하고 원래 예외를 삼키지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import httpx
import laspy
import numpy as np
import pytest
import rasterio
from ksi_event_contracts.change_detection_result import ArtifactRef, ChangeDetectionResult
from ksi_event_contracts.volume_change_report import VolumeChangeReport
from ksi_geo_spatial.crs import reproject_point
from ksi_processing_controller.comparison_worker import (
    ComparisonWorkerRunError,
    run_comparison_request,
)
from ksi_processing_controller.core_client import (
    ComparisonInput,
    CoreClientError,
    PendingComparisonRequest,
)
from rasterio.transform import from_origin

# test_worker.py 와 같은 관용구(모듈 docstring 3항) — FakeCoreClient 를 그대로 확장한다.
from test_worker import FakeCoreClient

_ORIGIN_X = 200_000.0
_ORIGIN_Y = 550_000.0


def _grid(n: int, *, z: float = 0.0) -> np.ndarray:
    return np.array([[float(i), 0.0, z] for i in range(n)])


def _write_laz(path: Path, points: np.ndarray) -> Path:
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.offsets = [0.0, 0.0, 0.0]
    header.scales = [0.001, 0.001, 0.001]
    las = laspy.LasData(header)
    las.x, las.y, las.z = points[:, 0], points[:, 1], points[:, 2]
    las.write(str(path))
    return path


def _write_dsm(path: Path, value: float) -> Path:
    with rasterio.open(
        path, "w", driver="GTiff", height=10, width=10, count=1, dtype="float64",
        crs="EPSG:5186", transform=from_origin(_ORIGIN_X, _ORIGIN_Y, 1.0, 1.0),
    ) as dataset:
        dataset.write(np.full((10, 10), value, dtype=np.float64), 1)
    return path


def _wgs84_square(size_m: float) -> dict[str, object]:
    """래스터 좌상단 부근의 정사각 구역을 WGS84 로(test_volume_change_end_to_end.py 와 동형)."""
    corners_xy = [
        (_ORIGIN_X, _ORIGIN_Y),
        (_ORIGIN_X + size_m, _ORIGIN_Y),
        (_ORIGIN_X + size_m, _ORIGIN_Y - size_m),
        (_ORIGIN_X, _ORIGIN_Y - size_m),
        (_ORIGIN_X, _ORIGIN_Y),
    ]
    ring = [
        list(reproject_point(x, y, from_crs="EPSG:5186", to_crs="EPSG:4326"))
        for x, y in corners_xy
    ]
    return {"type": "Polygon", "coordinates": [ring]}


_ZONES = {"zone-a": _wgs84_square(5.0)}


def _storage_transport(files: dict[str, Path]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        path = files.get(name)
        if path is None:
            return httpx.Response(404)
        return httpx.Response(200, content=path.read_bytes())

    return httpx.MockTransport(handler)


@dataclass
class FakeComparisonCoreClient(FakeCoreClient):
    """``FakeCoreClient`` + 비교 요청 표면 — worker.py 시험의 확장 관용구를 따른다."""

    comparison_input: ComparisonInput | None = None
    comparison_status: str = "QUEUED"
    lease_conflict: bool = False
    fail_transition_to: str | None = None
    # 재시도 시뮬레이션 — 이 changeDetectionId/volumeChangeId 는 "이미 다른
    # (computed_at 만 다른) 내용으로 기록돼 있다"를 흉내낸다.
    duplicate_change_detection: bool = False
    duplicate_volume_change: bool = False
    change_detection_results: list[tuple[str, ChangeDetectionResult]] = field(
        default_factory=list
    )
    volume_change_reports: list[tuple[str, VolumeChangeReport]] = field(default_factory=list)

    def list_pending_comparisons(self, *, limit: int = 50) -> list[PendingComparisonRequest]:
        """이 파일의 시험 대상은 ``run_comparison_request(request_id, ...)`` 직접
        호출이라 대기 목록을 쓰지 않는다(``FakeCoreClient.list_pending`` 과 동일
        관용구 — 대기 목록 자체를 시험하는 것은 test_runner.py 의 몫)."""
        del limit
        return []

    def acquire_comparison_lease(self, request_id: str) -> None:
        self.calls.append(("cmp-lease", request_id))
        if self.lease_conflict:
            raise CoreClientError(
                what="comparison-lease", verdict="LEASE_HELD_BY_ANOTHER", detail="테스트 강제"
            )

    def get_comparison_input(self, request_id: str) -> ComparisonInput:
        self.calls.append(("cmp-input", request_id))
        assert self.comparison_input is not None
        return self.comparison_input

    def transition_comparison(
        self, request_id: str, target: str, *, detail: str | None = None
    ) -> None:
        self.calls.append(("cmp-transition", target, detail))
        if self.fail_transition_to == target:
            raise CoreClientError(
                what="comparison-transition", verdict="ILLEGAL_TRANSITION", detail="테스트 강제"
            )
        self.comparison_status = target

    def submit_change_detection(self, mission_id: str, result: ChangeDetectionResult) -> None:
        self.calls.append(("submit-cd", mission_id, result.change_detection_id))
        if self.duplicate_change_detection:
            raise CoreClientError(
                what=f"change-detection:{result.change_detection_id}",
                verdict="DUPLICATE_RESULT_ID",
                detail="테스트 강제(재시도 시뮬레이션 — computed_at 만 다르다)",
            )
        self.change_detection_results.append((mission_id, result))

    def submit_volume_change(self, mission_id: str, report: VolumeChangeReport) -> None:
        self.calls.append(("submit-vol", mission_id, report.volume_change_id))
        if self.duplicate_volume_change:
            raise CoreClientError(
                what=f"volume-change:{report.volume_change_id}",
                verdict="DUPLICATE_REPORT_ID",
                detail="테스트 강제(재시도 시뮬레이션 — computed_at 만 다르다)",
            )
        self.volume_change_reports.append((mission_id, report))


def test_full_success_path_submits_both_and_succeeds(tmp_path: Path) -> None:
    """point_cloud + dsm 둘 다 갖춘 요청 — 변화탐지·체적 둘 다 계산+제출되고
    SUCCEEDED 로 끝난다. QUEUED 였으므로 RUNNING 전이도 시도된다."""
    baseline_cloud = _grid(10)
    current_cloud = _grid(10)
    current_cloud[5] = [5.0, 10.0, 0.0]
    base_laz = _write_laz(tmp_path / "baseline.laz", baseline_cloud)
    curr_laz = _write_laz(tmp_path / "current.laz", current_cloud)
    base_tif = _write_dsm(tmp_path / "baseline.tif", 100.0)
    curr_tif = _write_dsm(tmp_path / "current.tif", 101.0)

    core = FakeComparisonCoreClient(
        comparison_input=ComparisonInput(
            request_id="mission-1-cmp1",
            mission_id="mission-1",
            status="QUEUED",
            point_cloud_baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
            point_cloud_baseline_url="http://fake-storage/baseline.laz",
            point_cloud_current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
            point_cloud_current_url="http://fake-storage/current.laz",
            dsm_baseline=ArtifactRef(job_id="job-a", artifact_id="dsm"),
            dsm_baseline_url="http://fake-storage/baseline.tif",
            dsm_current=ArtifactRef(job_id="job-b", artifact_id="dsm"),
            dsm_current_url="http://fake-storage/current.tif",
            zones=_ZONES,
            zone_crs="EPSG:4326",
        )
    )
    transport = _storage_transport(
        {
            "baseline.laz": base_laz, "current.laz": curr_laz,
            "baseline.tif": base_tif, "current.tif": curr_tif,
        }
    )

    with httpx.Client(transport=transport) as client:
        run_comparison_request(
            "mission-1-cmp1", core=core, work_dir=tmp_path, http_client=client,
            now_message=lambda _msg: None,
        )

    assert ("cmp-lease", "mission-1-cmp1") in core.calls
    assert ("cmp-transition", "RUNNING", None) in core.calls
    assert len(core.change_detection_results) == 1
    assert len(core.volume_change_reports) == 1
    assert core.change_detection_results[0][1].change_detection_id == "mission-1-cmp1"
    assert core.volume_change_reports[0][1].volume_change_id == "mission-1-cmp1"
    succeeded = [c for c in core.calls if c[0] == "cmp-transition" and c[1] == "SUCCEEDED"]
    assert len(succeeded) == 1


def test_duplicate_result_id_on_retry_is_treated_as_already_recorded(tmp_path: Path) -> None:
    """[핵심][회귀] 재시도(재시작·부분실패 후 재시도)로 이미 성공 제출한 결과를
    다시 계산+제출하면 Core 는 DUPLICATE_RESULT_ID/DUPLICATE_REPORT_ID 를 낸다
    (``computed_at`` 만 달라도 내용이 다르다고 본다). changeDetectionId/
    volumeChangeId 는 이 요청만 만들 수 있는 결정적 값이라 안전하게 넘어가야
    한다 — 그러지 않으면(2026-08-10 실 인프라 재현 전까지의 동작) 정상 재시도가
    매번 FAILED 로 끝난다."""
    cloud = _grid(8)
    base_laz = _write_laz(tmp_path / "baseline.laz", cloud)
    curr_laz = _write_laz(tmp_path / "current.laz", cloud.copy())
    base_tif = _write_dsm(tmp_path / "baseline.tif", 100.0)
    curr_tif = _write_dsm(tmp_path / "current.tif", 101.0)

    core = FakeComparisonCoreClient(
        comparison_input=ComparisonInput(
            request_id="mission-1-cmp-retry",
            mission_id="mission-1",
            status="RUNNING",  # 이미 한 번 RUNNING 으로 전이된 뒤의 재시도를 흉내낸다
            point_cloud_baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
            point_cloud_baseline_url="http://fake-storage/baseline.laz",
            point_cloud_current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
            point_cloud_current_url="http://fake-storage/current.laz",
            dsm_baseline=ArtifactRef(job_id="job-a", artifact_id="dsm"),
            dsm_baseline_url="http://fake-storage/baseline.tif",
            dsm_current=ArtifactRef(job_id="job-b", artifact_id="dsm"),
            dsm_current_url="http://fake-storage/current.tif",
            zones=_ZONES,
            zone_crs="EPSG:4326",
        ),
        duplicate_change_detection=True,
        duplicate_volume_change=True,
    )
    transport = _storage_transport(
        {
            "baseline.laz": base_laz, "current.laz": curr_laz,
            "baseline.tif": base_tif, "current.tif": curr_tif,
        }
    )

    with httpx.Client(transport=transport) as client:
        run_comparison_request(
            "mission-1-cmp-retry", core=core, work_dir=tmp_path, http_client=client,
            now_message=lambda _msg: None,
        )

    # 예외 없이 SUCCEEDED 로 끝난다 — DUPLICATE 는 실패가 아니라 "이미 됐다"다.
    succeeded = [c for c in core.calls if c[0] == "cmp-transition" and c[1] == "SUCCEEDED"]
    assert len(succeeded) == 1
    assert not any(c[0] == "cmp-transition" and c[1] == "FAILED" for c in core.calls)
    # 실제로 store 에 쌓인 결과는 0건이다(FakeComparisonCoreClient 가 DUPLICATE 를
    # 흉내내려고 append 를 건너뛰었다) — 그래도 워커는 안전하게 넘어갔다는 뜻.
    assert core.change_detection_results == []
    assert core.volume_change_reports == []


def test_dsm_diff_error_on_bad_zone_reports_failed_not_uncaught(tmp_path: Path) -> None:
    """[핵심][회귀] 구역이 DSM 래스터 밖이면 dsm_diff.DsmDiffError 가 난다 — 이
    예외가 run_volume_change.VolumeChangeRunError 로 감싸이지 않으면(2026-08-10
    실 인프라 재현으로 발견된 결함) 워커의 except 절을 통과해 그대로 새고, 비교
    요청은 FAILED 전이 시도조차 못 받은 채 RUNNING 에 무기한 걸린다."""
    cloud = _grid(6)
    base_laz = _write_laz(tmp_path / "baseline.laz", cloud)
    curr_laz = _write_laz(tmp_path / "current.laz", cloud.copy())
    base_tif = _write_dsm(tmp_path / "baseline.tif", 100.0)
    curr_tif = _write_dsm(tmp_path / "current.tif", 101.0)
    far_zone = {
        "zone-far": {
            "type": "Polygon",
            "coordinates": [
                [[10.0, 10.0], [10.001, 10.0], [10.001, 10.001], [10.0, 10.001], [10.0, 10.0]]
            ],
        }
    }

    core = FakeComparisonCoreClient(
        comparison_input=ComparisonInput(
            request_id="mission-1-cmp-badzone",
            mission_id="mission-1",
            status="QUEUED",
            point_cloud_baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
            point_cloud_baseline_url="http://fake-storage/baseline.laz",
            point_cloud_current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
            point_cloud_current_url="http://fake-storage/current.laz",
            dsm_baseline=ArtifactRef(job_id="job-a", artifact_id="dsm"),
            dsm_baseline_url="http://fake-storage/baseline.tif",
            dsm_current=ArtifactRef(job_id="job-b", artifact_id="dsm"),
            dsm_current_url="http://fake-storage/current.tif",
            zones=far_zone,
            zone_crs="EPSG:4326",
        ),
    )
    transport = _storage_transport(
        {
            "baseline.laz": base_laz, "current.laz": curr_laz,
            "baseline.tif": base_tif, "current.tif": curr_tif,
        }
    )

    with (
        httpx.Client(transport=transport) as client,
        pytest.raises(ComparisonWorkerRunError),
    ):
        run_comparison_request(
            "mission-1-cmp-badzone", core=core, work_dir=tmp_path, http_client=client,
            now_message=lambda _msg: None,
        )

    failed = [c for c in core.calls if c[0] == "cmp-transition" and c[1] == "FAILED"]
    assert len(failed) == 1
    # 변화탐지는 구역과 무관하므로 정상 성공·제출됐다 — 부분 성공이 있어도 전체는
    # FAILED 로 정직하게 보고된다(모듈 docstring "부분 성공을 별도 상태로 표현하지
    # 않는다").
    assert len(core.change_detection_results) == 1
    assert core.volume_change_reports == []


def test_resumed_request_skips_running_transition(tmp_path: Path) -> None:
    """status 가 이미 RUNNING(재개된 요청)이면 QUEUED→RUNNING 전이를 시도하지
    않는다 — 시도하면 ILLEGAL_TRANSITION 이다(RUNNING→RUNNING 은 허용 전이표에 없다)."""
    cloud = _grid(6)
    base_laz = _write_laz(tmp_path / "baseline.laz", cloud)
    curr_laz = _write_laz(tmp_path / "current.laz", cloud.copy())

    core = FakeComparisonCoreClient(
        comparison_input=ComparisonInput(
            request_id="mission-1-cmp2",
            mission_id="mission-1",
            status="RUNNING",
            point_cloud_baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
            point_cloud_baseline_url="http://fake-storage/baseline.laz",
            point_cloud_current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
            point_cloud_current_url="http://fake-storage/current.laz",
            dsm_baseline=None, dsm_baseline_url=None,
            dsm_current=None, dsm_current_url=None,
            zones=None, zone_crs=None,
        )
    )
    transport = _storage_transport({"baseline.laz": base_laz, "current.laz": curr_laz})

    with httpx.Client(transport=transport) as client:
        run_comparison_request(
            "mission-1-cmp2", core=core, work_dir=tmp_path, http_client=client,
            now_message=lambda _msg: None,
        )

    assert not any(c[0] == "cmp-transition" and c[1] == "RUNNING" for c in core.calls)
    assert len(core.change_detection_results) == 1
    assert core.volume_change_reports == []


def test_download_failure_reports_failed_and_reraises(tmp_path: Path) -> None:
    """다운로드 실패(예: 404) → FAILED 보고를 시도하고 원래 예외를 다시 던진다."""
    core = FakeComparisonCoreClient(
        comparison_input=ComparisonInput(
            request_id="mission-1-cmp3",
            mission_id="mission-1",
            status="QUEUED",
            point_cloud_baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
            point_cloud_baseline_url="http://fake-storage/missing.laz",
            point_cloud_current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
            point_cloud_current_url="http://fake-storage/missing.laz",
            dsm_baseline=None, dsm_baseline_url=None,
            dsm_current=None, dsm_current_url=None,
            zones=None, zone_crs=None,
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(404)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ComparisonWorkerRunError),
    ):
        run_comparison_request(
            "mission-1-cmp3", core=core, work_dir=tmp_path, http_client=client,
            now_message=lambda _msg: None,
        )

    failed = [c for c in core.calls if c[0] == "cmp-transition" and c[1] == "FAILED"]
    assert len(failed) == 1
    assert failed[0][2] is not None  # detail 이 채워져 있다


def test_failed_report_failure_does_not_swallow_original_exception(tmp_path: Path) -> None:
    """FAILED 보고 자체가 실패해도(예: lease 만료) 원래 원인이 그대로 올라온다
    (worker.py 모듈 docstring "실패는 전부 FAILED 로 수렴한다"와 동일 원칙)."""
    core = FakeComparisonCoreClient(
        comparison_input=ComparisonInput(
            request_id="mission-1-cmp4",
            mission_id="mission-1",
            status="QUEUED",
            point_cloud_baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
            point_cloud_baseline_url="http://fake-storage/missing.laz",
            point_cloud_current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
            point_cloud_current_url="http://fake-storage/missing.laz",
            dsm_baseline=None, dsm_baseline_url=None,
            dsm_current=None, dsm_current_url=None,
            zones=None, zone_crs=None,
        ),
        fail_transition_to="FAILED",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(404)

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ComparisonWorkerRunError, match="point cloud"),
    ):
        run_comparison_request(
            "mission-1-cmp4", core=core, work_dir=tmp_path, http_client=client,
            now_message=lambda _msg: None,
        )


def test_pending_comparison_request_is_a_lightweight_reference() -> None:
    """워커가 다음에 잡을 후보는 requestId 뿐이다 — PendingJob(jobId 뿐)과 동형(문서화 고정)."""
    pending = PendingComparisonRequest(request_id="mission-1-cmp5")
    assert pending.request_id == "mission-1-cmp5"
    # PendingJob 과 필드 "개수"가 같다는 것을 구조적으로 남긴다(이름은 job_id/
    # request_id 로 다르다 — 각자의 도메인을 반영한다, 회귀 시 이 assert 가 깨진다).
    assert len(PendingComparisonRequest.__dataclass_fields__) == 1
