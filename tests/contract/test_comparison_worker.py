"""비교 워커 오케스트레이션 계약 (``ksi_processing_controller.comparison_worker``).

``test_worker.py`` 가 재구성 쪽(``run_job``)의 순서를 가짜 Core·가짜 NodeODM 으로
고정한 것과 동형이다 — 이 파일은 ``run_comparison_request`` 의 순서를 가짜 Core
(비교 표면)로 고정한다: lease → 입력수신 → (QUEUED 면) RUNNING → 계산+제출
(point_cloud 쌍이 있으면 변화탐지, dsm 쌍+구역이 있으면 체적) → SUCCEEDED. 실패는
FAILED 로 수렴하고 원래 예외를 삼키지 않는다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import laspy
import numpy as np
import pytest
import rasterio
from ksi_event_contracts.change_detection_result import ArtifactRef, ChangeDetectionResult
from ksi_event_contracts.comparison_policy import current_comparison_policy
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)
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
from pyproj import CRS
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
    header.add_crs(CRS.from_user_input("EPSG:5186"))
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
            policy=current_comparison_policy(),
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


def test_neither_input_ready_reports_failed_not_empty_success(tmp_path: Path) -> None:
    """[핵심][회귀] 생성 시점엔 계산 대상이 있었지만(``NOTHING_TO_COMPARE`` 게이트를
    통과) 워커가 입력을 받은 시점엔 point_cloud/dsm 이 전부 비어 있는 경우 —
    두 계산 모두 건너뛰어 요약이 빈 채로 남는다. 이걸 그냥 SUCCEEDED 로 보내면
    화면엔 "완료"가 뜨는데 결과는 없다(INV-040). FAILED 로 보고하고 원래
    예외를 다시 던져야 한다(worker.py 와 동일 "실패는 전부 FAILED 로 수렴한다" 원칙)."""
    core = FakeComparisonCoreClient(
        comparison_input=ComparisonInput(
            request_id="mission-1-cmp-empty",
            mission_id="mission-1",
            status="QUEUED",
            policy=current_comparison_policy(),
            point_cloud_baseline=None, point_cloud_baseline_url=None,
            point_cloud_current=None, point_cloud_current_url=None,
            dsm_baseline=None, dsm_baseline_url=None,
            dsm_current=None, dsm_current_url=None,
            zones=None, zone_crs=None,
        )
    )

    with (
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404))) as client,
        pytest.raises(ComparisonWorkerRunError),
    ):
        run_comparison_request(
            "mission-1-cmp-empty", core=core, work_dir=tmp_path, http_client=client,
            now_message=lambda _msg: None,
        )

    assert not core.change_detection_results
    assert not core.volume_change_reports
    succeeded = [c for c in core.calls if c[0] == "cmp-transition" and c[1] == "SUCCEEDED"]
    assert not succeeded
    failed = [c for c in core.calls if c[0] == "cmp-transition" and c[1] == "FAILED"]
    assert len(failed) == 1
    assert failed[0][2] is not None  # detail 이 채워져 있다


def test_lease_is_renewed_while_the_computation_runs(tmp_path: Path) -> None:
    """[핵심][회귀] 계산이 lease TTL(15분)보다 오래 걸려도 lease 를 놓치지 않는다.

    갱신이 없으면 만료된 RUNNING 요청을 다른 워커가 집어가 같은 계산을 중복으로
    돌리고, 이쪽의 최종 SUCCEEDED 전이는 LEASE_HELD_BY_ANOTHER 로 거부돼
    **성공한 계산이 FAILED 로 보고된다**. 여기서는 다운로드를 인위적으로 늦춰
    (transport 에서 sleep) 갱신 tick 이 실제로 도는지 본다 — 취득 1회 + 갱신
    n회가 되어야 한다."""
    cloud = _grid(8)
    base_laz = _write_laz(tmp_path / "baseline.laz", cloud)
    curr_laz = _write_laz(tmp_path / "current.laz", cloud.copy())

    core = FakeComparisonCoreClient(
        comparison_input=ComparisonInput(
            request_id="mission-1-cmp-slow",
            mission_id="mission-1",
            status="QUEUED",
            policy=current_comparison_policy(),
            point_cloud_baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
            point_cloud_baseline_url="http://fake-storage/baseline.laz",
            point_cloud_current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
            point_cloud_current_url="http://fake-storage/current.laz",
            dsm_baseline=None, dsm_baseline_url=None,
            dsm_current=None, dsm_current_url=None,
            zones=None, zone_crs=None,
        )
    )

    files = {"baseline.laz": base_laz, "current.laz": curr_laz}

    def slow_handler(request: httpx.Request) -> httpx.Response:
        # 갱신 주기(아래 0.05s)보다 확실히 길게 — tick 이 여러 번 돌 시간을 준다.
        time.sleep(0.3)
        name = request.url.path.rsplit("/", 1)[-1]
        path = files.get(name)
        if path is None:
            return httpx.Response(404)
        return httpx.Response(200, content=path.read_bytes())

    with httpx.Client(transport=httpx.MockTransport(slow_handler)) as client:
        run_comparison_request(
            "mission-1-cmp-slow", core=core, work_dir=tmp_path, http_client=client,
            now_message=lambda _msg: None,
            heartbeat_interval_seconds=0.05,
        )

    leases = [c for c in core.calls if c[0] == "cmp-lease"]
    # 최초 취득 1회 + 계산 중 갱신 최소 1회.
    assert len(leases) >= 2, f"lease 갱신이 돌지 않았다: {leases}"
    succeeded = [c for c in core.calls if c[0] == "cmp-transition" and c[1] == "SUCCEEDED"]
    assert len(succeeded) == 1


def test_heartbeat_failure_does_not_kill_the_computation(tmp_path: Path) -> None:
    """[회귀] 갱신 왕복이 실패해도(일시적 Core 장애) 계산은 끝까지 간다.

    갱신 실패로 계산을 중단하면 이미 제출한 부분 결과와 요청 상태가 어긋난다 —
    lease 를 진짜 뺏긴 경우라면 마지막 전이가 거부되며 그때 FAILED 로 수렴하는
    것이 이 모듈의 설계다(comparison_worker.LeaseHeartbeat docstring)."""
    cloud = _grid(8)
    base_laz = _write_laz(tmp_path / "baseline.laz", cloud)
    curr_laz = _write_laz(tmp_path / "current.laz", cloud.copy())

    class HeartbeatFailsCoreClient(FakeComparisonCoreClient):
        def acquire_comparison_lease(self, request_id: str) -> None:
            self.calls.append(("cmp-lease", request_id))
            # 최초 취득은 통과시키고, 이후 갱신만 실패시킨다.
            if len([c for c in self.calls if c[0] == "cmp-lease"]) > 1:
                raise CoreClientError(
                    what="comparison-lease", verdict="STORE_UNAVAILABLE", detail="테스트 강제"
                )

    core = HeartbeatFailsCoreClient(
        comparison_input=ComparisonInput(
            request_id="mission-1-cmp-beatfail",
            mission_id="mission-1",
            status="QUEUED",
            policy=current_comparison_policy(),
            point_cloud_baseline=ArtifactRef(job_id="job-a", artifact_id="point-cloud"),
            point_cloud_baseline_url="http://fake-storage/baseline.laz",
            point_cloud_current=ArtifactRef(job_id="job-b", artifact_id="point-cloud"),
            point_cloud_current_url="http://fake-storage/current.laz",
            dsm_baseline=None, dsm_baseline_url=None,
            dsm_current=None, dsm_current_url=None,
            zones=None, zone_crs=None,
        )
    )

    files = {"baseline.laz": base_laz, "current.laz": curr_laz}

    def slow_handler(request: httpx.Request) -> httpx.Response:
        time.sleep(0.2)
        name = request.url.path.rsplit("/", 1)[-1]
        path = files.get(name)
        if path is None:
            return httpx.Response(404)
        return httpx.Response(200, content=path.read_bytes())

    with httpx.Client(transport=httpx.MockTransport(slow_handler)) as client:
        run_comparison_request(
            "mission-1-cmp-beatfail", core=core, work_dir=tmp_path, http_client=client,
            now_message=lambda _msg: None,
            heartbeat_interval_seconds=0.05,
        )

    # 갱신이 실패했어도 계산은 완주해 결과가 제출되고 SUCCEEDED 로 끝났다.
    assert len(core.change_detection_results) == 1
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
            policy=current_comparison_policy(),
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
            policy=current_comparison_policy(),
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
            policy=current_comparison_policy(),
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
            policy=current_comparison_policy(),
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


def test_work_directory_oserror_after_running_reports_failed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RUNNING 뒤 mkdir 실패도 FAILED 한 번 + 원래 OSError cause로 수렴한다."""
    request_id = "mission-1-cmp-disk-error"
    core = FakeComparisonCoreClient(
        comparison_input=ComparisonInput(
            request_id=request_id,
            mission_id="mission-1",
            status="QUEUED",
            policy=current_comparison_policy(),
            point_cloud_baseline=None,
            point_cloud_baseline_url=None,
            point_cloud_current=None,
            point_cloud_current_url=None,
            dsm_baseline=None,
            dsm_baseline_url=None,
            dsm_current=None,
            dsm_current_url=None,
            zones=None,
            zone_crs=None,
        )
    )
    disk_error = OSError("disk unavailable: " + "x" * 600)

    def fail_mkdir(_path: Path, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise disk_error

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)
    with (
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))) as client,
        pytest.raises(ComparisonWorkerRunError) as exc_info,
    ):
        run_comparison_request(
            request_id,
            core=core,
            work_dir=tmp_path / "work",
            http_client=client,
            now_message=lambda _msg: None,
        )

    assert exc_info.value.__cause__ is disk_error
    transitions = [call for call in core.calls if call[0] == "cmp-transition"]
    assert [call[1] for call in transitions] == ["RUNNING", "FAILED"]
    assert transitions[-1][2] is not None
    assert len(transitions[-1][2]) == 500


def test_failed_report_failure_does_not_swallow_original_exception(tmp_path: Path) -> None:
    """FAILED 보고 자체가 실패해도(예: lease 만료) 원래 원인이 그대로 올라온다
    (worker.py 모듈 docstring "실패는 전부 FAILED 로 수렴한다"와 동일 원칙)."""
    core = FakeComparisonCoreClient(
        comparison_input=ComparisonInput(
            request_id="mission-1-cmp4",
            mission_id="mission-1",
            status="QUEUED",
            policy=current_comparison_policy(),
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


# ── 리포트의 verticalDatum 은 어디서 오는가 (M4-A 쟁점 1 ④) ──────────────────
#
# 예전엔 워커의 하드코딩 상수 하나였다 — 리포트가 "이건 타원체고다"라고 말하면서
# 그걸 어떻게 아는지는 아무도 몰랐다. 이제 정본은 **산출물이 스스로 선언한 값**
# (``ProcessingArtifact.verticalReference``)이고, 상수는 그 값이 없는 옛 산출물의
# 대체값으로만 남는다.


def _vertical_dsm_core(
    request_id: str,
    *,
    baseline_reference: VerticalReference | None,
    current_reference: VerticalReference | None,
    baseline_checkpoint_rmse_m: float | None = None,
    current_checkpoint_rmse_m: float | None = None,
) -> FakeComparisonCoreClient:
    """체적 계산만 하는(점군 없는) 비교 요청 — 수직기준·검사점 잔차만 바꿔가며 쓴다."""
    return FakeComparisonCoreClient(
        comparison_input=ComparisonInput(
            request_id=request_id,
            mission_id="mission-1",
            status="QUEUED",
            policy=current_comparison_policy(),
            point_cloud_baseline=None, point_cloud_baseline_url=None,
            point_cloud_current=None, point_cloud_current_url=None,
            dsm_baseline=ArtifactRef(job_id="job-a", artifact_id="dsm"),
            dsm_baseline_url="http://fake-storage/baseline.tif",
            dsm_current=ArtifactRef(job_id="job-b", artifact_id="dsm"),
            dsm_current_url="http://fake-storage/current.tif",
            zones=_ZONES,
            zone_crs="EPSG:4326",
            dsm_baseline_vertical_reference=baseline_reference,
            dsm_current_vertical_reference=current_reference,
            dsm_baseline_checkpoint_rmse_m=baseline_checkpoint_rmse_m,
            dsm_current_checkpoint_rmse_m=current_checkpoint_rmse_m,
        )
    )


def _declared(datum: VerticalDatum) -> VerticalReference:
    return VerticalReference(
        datum=datum,
        basis="테스트 — 산출물 등록 시 파이프라인이 선언한 값",
        source=VerticalReferenceSource.PIPELINE_DECLARED,
    )


def _run_vertical_case(
    core: FakeComparisonCoreClient, request_id: str, tmp_path: Path
) -> None:
    transport = _storage_transport(
        {
            "baseline.tif": _write_dsm(tmp_path / "baseline.tif", 100.0),
            "current.tif": _write_dsm(tmp_path / "current.tif", 101.0),
        }
    )
    with httpx.Client(transport=transport) as client:
        run_comparison_request(
            request_id, core=core, work_dir=tmp_path, http_client=client,
            now_message=lambda _msg: None,
        )


def test_report_carries_the_datum_the_artifacts_declared(tmp_path: Path) -> None:
    """[핵심] 두 산출물이 같은 수직기준을 선언했으면 **그 값**이 리포트에 실린다.

    상수(``ellipsoidal_native``)가 아니라 ``ellipsoidal`` 을 쓴다 — 상수가 아직
    남아 있어도 이 단언이 통과하는 일이 없게 하려는 것이다.
    """
    core = _vertical_dsm_core(
        "mission-1-cmp-vr",
        baseline_reference=_declared(VerticalDatum.ELLIPSOIDAL),
        current_reference=_declared(VerticalDatum.ELLIPSOIDAL),
    )

    _run_vertical_case(core, "mission-1-cmp-vr", tmp_path)

    assert len(core.volume_change_reports) == 1
    _, report = core.volume_change_reports[0]
    assert report.vertical_datum == "ellipsoidal"


def test_missing_declaration_falls_back_to_the_legacy_constant(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """[회귀] 한쪽이라도 수직기준을 안 밝힌 산출물이면 **예전과 정확히 같은 값**을
    쓰고 경고를 남긴다 — 수직기준 개념 이전에 등록된 M1/M2 산출물의 비교를
    소급해서 못 하게 만들지 않는다(이 milestone 의 무효화 금지 요건)."""
    core = _vertical_dsm_core(
        "mission-1-cmp-legacy",
        baseline_reference=_declared(VerticalDatum.ELLIPSOIDAL),
        current_reference=None,
    )

    with caplog.at_level(logging.WARNING, logger="ksi_processing_controller.comparison_worker"):
        _run_vertical_case(core, "mission-1-cmp-legacy", tmp_path)

    assert len(core.volume_change_reports) == 1
    _, report = core.volume_change_reports[0]
    assert report.vertical_datum == "ellipsoidal_native"
    # 조용히 대체하지 않는다 — 재처리 대상을 나중에 찾을 수 있어야 한다.
    assert any("수직기준 미기록" in record.message for record in caplog.records)
    succeeded = [c for c in core.calls if c[0] == "cmp-transition" and c[1] == "SUCCEEDED"]
    assert len(succeeded) == 1


def test_uncertainty_is_computed_when_both_epochs_are_checkpoint_verified(
    tmp_path: Path,
) -> None:
    """[핵심·INV-024] 양쪽 epoch 이 독립 검사점으로 검증됐으면 오차한계가 **실제로 나온다**.

    이 경로는 계산 코드가 존재하는데도 입력이 한 번도 도달한 적이 없었다 —
    워커가 ``rmse_m`` 을 늘 ``None`` 으로 넘겨 ``uncertaintyM3`` 가 항상 비어
    있었다(2026-08-18 배선). 이 단언이 그 비공허성을 지킨다.
    """
    core = _vertical_dsm_core(
        "mission-1-cmp-unc",
        baseline_reference=_declared(VerticalDatum.ELLIPSOIDAL),
        current_reference=_declared(VerticalDatum.ELLIPSOIDAL),
        baseline_checkpoint_rmse_m=0.03,
        current_checkpoint_rmse_m=0.04,
    )

    _run_vertical_case(core, "mission-1-cmp-unc", tmp_path)

    assert len(core.volume_change_reports) == 1
    _, report = core.volume_change_reports[0]
    assert report.zones, "구역이 비면 이 단언이 공허해진다"
    for zone in report.zones:
        assert zone.uncertainty_m3 is not None, "검증된 두 epoch 인데 오차한계가 비었다"
        assert zone.uncertainty_m3 > 0


@pytest.mark.parametrize(
    ("baseline_rmse", "current_rmse"),
    [(0.03, None), (None, 0.04), (None, None)],
    ids=["기준만 검증", "최신만 검증", "둘 다 미검증"],
)
def test_uncertainty_stays_null_unless_both_epochs_are_verified(
    baseline_rmse: float | None, current_rmse: float | None, tmp_path: Path
) -> None:
    """[회귀·INV-024] 한쪽만 알면 차분의 오차를 말할 수 없다 — 0 으로 채우지 않는다.

    모르는 쪽을 0 으로 두면 "검증된 한쪽만큼만 틀릴 수 있다"는 거짓 주장이 된다.
    """
    core = _vertical_dsm_core(
        "mission-1-cmp-unc-partial",
        baseline_reference=_declared(VerticalDatum.ELLIPSOIDAL),
        current_reference=_declared(VerticalDatum.ELLIPSOIDAL),
        baseline_checkpoint_rmse_m=baseline_rmse,
        current_checkpoint_rmse_m=current_rmse,
    )

    _run_vertical_case(core, "mission-1-cmp-unc-partial", tmp_path)

    assert len(core.volume_change_reports) == 1
    _, report = core.volume_change_reports[0]
    assert report.zones
    for zone in report.zones:
        assert zone.uncertainty_m3 is None


def test_incompatible_datum_families_fail_instead_of_producing_numbers(tmp_path: Path) -> None:
    """[핵심] 타원체고와 정표고를 그냥 빼지 않는다 — 한국에서 20~30m 가 조용히
    섞인다. 이론상 같은 파이프라인끼리는 발생하지 않지만, 발생했다면 전제가
    깨진 것이므로 숫자를 내지 않고 FAILED 로 수렴한다."""
    core = _vertical_dsm_core(
        "mission-1-cmp-incompat",
        baseline_reference=_declared(VerticalDatum.ELLIPSOIDAL_NATIVE),
        current_reference=_declared(VerticalDatum.ORTHOMETRIC_KNGEOID2018),
    )

    with pytest.raises(ComparisonWorkerRunError):
        _run_vertical_case(core, "mission-1-cmp-incompat", tmp_path)

    assert core.volume_change_reports == []
    failed = [c for c in core.calls if c[0] == "cmp-transition" and c[1] == "FAILED"]
    assert len(failed) == 1


def test_same_family_but_different_datums_still_refuses_to_pick_one(tmp_path: Path) -> None:
    """계열이 같아도 datum 이 다르면 리포트의 verticalDatum 한 자리에 어느 쪽을
    적어도 절반은 거짓이 된다 — 한쪽을 고르는 대신 실패한다(fail-closed)."""
    core = _vertical_dsm_core(
        "mission-1-cmp-mixed",
        baseline_reference=_declared(VerticalDatum.ELLIPSOIDAL),
        current_reference=_declared(VerticalDatum.ELLIPSOIDAL_NATIVE),
    )

    with pytest.raises(ComparisonWorkerRunError):
        _run_vertical_case(core, "mission-1-cmp-mixed", tmp_path)

    assert core.volume_change_reports == []
    failed = [c for c in core.calls if c[0] == "cmp-transition" and c[1] == "FAILED"]
    assert len(failed) == 1


def test_pending_comparison_request_is_a_lightweight_reference() -> None:
    """워커가 다음에 잡을 후보는 requestId 뿐이다 — PendingJob(jobId 뿐)과 동형(문서화 고정)."""
    pending = PendingComparisonRequest(request_id="mission-1-cmp5")
    assert pending.request_id == "mission-1-cmp5"
    # PendingJob 과 필드 "개수"가 같다는 것을 구조적으로 남긴다(이름은 job_id/
    # request_id 로 다르다 — 각자의 도메인을 반영한다, 회귀 시 이 assert 가 깨진다).
    assert len(PendingComparisonRequest.__dataclass_fields__) == 1
