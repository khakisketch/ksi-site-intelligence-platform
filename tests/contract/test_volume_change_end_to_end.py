"""체적 변화 종단 — 두 DSM 산출물에서 Core 조회까지 (ADR-KSI-016 D3).

각 조각(측지·차분·계약·원장)은 개별로 검증됐다. 이 파일이 보는 것은 **이어
부르면 실제로 답이 나오는가**다: 스토리지에 있는 두 DSM 을 받아 → 차분해 →
AOI 를 그 좌표계로 옮겨 → 체적을 재고 → Core 에 올려 → 조회로 같은 숫자가
돌아오는지.

가짜인 것은 스토리지 바이트를 서빙하는 트랜스포트뿐이다. DSM 은 rasterio 로
실제 GeoTIFF 를 만들고, 차분·마스킹·재투영은 진짜 라이브러리가 하며, Core 는
실제 라우터·실제 journal 이다.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import pytest
import rasterio
from _volume_fixtures import (
    _MISSION_ID,
    _WORKER_TOKEN,
    _artifact_spec,
    _digest,
    _job_store,
    _job_with_artifacts,
    _mission_store,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_change_detection.run_volume_change import (
    ArtifactSource,
    VolumeChangeRunError,
    compute_and_submit,
)
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.volume_reports import VolumeChangeStore, mount_volume_reports
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.volume_change_report import VolumeChangeReport
from ksi_geo_spatial.crs import reproject_point
from rasterio.transform import from_origin

_ORIGIN_X = 200_000.0
_ORIGIN_Y = 550_000.0
_COMPUTED_AT = datetime(2026, 8, 8, 5, 0, tzinfo=UTC)


def _write_dsm(path: Path, value: float) -> Path:
    """20×20m, 셀 1m, EPSG:5186 평면좌표의 평평한 DSM."""
    with rasterio.open(
        path, "w", driver="GTiff", height=20, width=20, count=1, dtype="float64",
        crs="EPSG:5186", transform=from_origin(_ORIGIN_X, _ORIGIN_Y, 1.0, 1.0),
    ) as dataset:
        dataset.write(np.full((20, 20), value, dtype=np.float64), 1)
    return path


def _storage_transport(files: dict[str, Path]) -> httpx.MockTransport:
    """presigned GET 을 흉내내는 트랜스포트 — 경로 마지막 조각으로 파일을 찾는다."""

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        path = files.get(name)
        if path is None:
            return httpx.Response(404)
        return httpx.Response(200, content=path.read_bytes())

    return httpx.MockTransport(handler)


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_WORKER_TOKEN),
                principal=Principal(
                    principal_id="worker-1",
                    kind=PrincipalKind.PROCESSING_WORKER,
                    role=None,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"admin").hexdigest(),
                principal=Principal(
                    principal_id="op-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            ),
        ]
    )


class _CoreSink:
    """Core 의 실제 라우터에 HTTP 로 제출하는 sink."""

    def __init__(self, client: TestClient) -> None:
        self._client = client
        self.last_status: int | None = None

    def submit_volume_change(self, mission_id: str, report: VolumeChangeReport) -> None:
        response = self._client.post(
            f"/v1/missions/{mission_id}/volume-changes",
            json=report.model_dump(by_alias=True, mode="json", exclude_none=False),
        )
        self.last_status = response.status_code
        if response.status_code != 201:
            raise AssertionError(f"제출 실패 {response.status_code}: {response.text}")


@pytest.fixture
def wired(tmp_path: Path) -> tuple[_CoreSink, TestClient, str, httpx.Client]:
    """(sink, Core 클라이언트, jobId, 스토리지 바이트를 주는 http 클라이언트)."""
    missions = _mission_store(tmp_path)
    jobs = _job_store(tmp_path, DurableJournal(tmp_path / "processing-jobs.jsonl"))
    job_id = _job_with_artifacts(
        jobs,
        _artifact_spec("dsm-baseline"),
        _artifact_spec("dsm-current"),
        _artifact_spec("pc-1", kind=ProcessingArtifactKind.POINT_CLOUD),
    )
    store = VolumeChangeStore(
        DurableJournal(tmp_path / "volume-changes.jsonl"),
        mission_store=missions,
        processing_job_store=jobs,
    )
    app = FastAPI()
    mount_auth(app, _registry())
    mount_volume_reports(app, store)
    core = TestClient(app)
    core.headers.update({"Authorization": f"Bearer {_WORKER_TOKEN}"})

    files = {
        "dsm-baseline": _write_dsm(tmp_path / "base.tif", 100.0),
        "dsm-current": _write_dsm(tmp_path / "curr.tif", 101.0),
    }
    storage = httpx.Client(transport=_storage_transport(files))
    return _CoreSink(core), core, job_id, storage


def _wgs84_square(size_m: float) -> dict[str, object]:
    """래스터 좌상단 부근의 정사각 AOI 를 WGS84 로 — 정상 입력 경로다."""
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


def _sources(job_id: str) -> tuple[ArtifactSource, ArtifactSource]:
    return (
        ArtifactSource(
            ref=ArtifactRef(job_id=job_id, artifact_id="dsm-baseline"),
            download_url="https://storage.invalid/dsm-baseline",
        ),
        ArtifactSource(
            ref=ArtifactRef(job_id=job_id, artifact_id="dsm-current"),
            download_url="https://storage.invalid/dsm-current",
        ),
    )


def test_two_dsm_epochs_become_a_readable_volume_report(
    wired: tuple[_CoreSink, TestClient, str, httpx.Client],
) -> None:
    """[종단] 두 DSM → 차분 → 구역 체적 → Core 제출 → 조회로 같은 숫자.

    10m×10m 구역이 1m 올라갔으므로 성토 100m³ 다. 이 숫자가 스토리지 바이트에서
    출발해 API 응답까지 변형 없이 도착하는지가 이 테스트의 전부다.
    """
    sink, core, job_id, storage = wired
    baseline, current = _sources(job_id)

    report = compute_and_submit(
        sink=sink,
        mission_id=_MISSION_ID,
        volume_change_id="vc-e2e-1",
        baseline=baseline,
        current=current,
        zones={"zone-0": _wgs84_square(10.0)},
        zone_crs="EPSG:4326",
        vertical_datum="ellipsoidal_native",
        computed_at=_COMPUTED_AT,
        http_client=storage,
    )

    assert sink.last_status == 201
    assert report.zones[0].fill_m3 == pytest.approx(100.0, rel=0.05)
    assert report.crs == "EPSG:5186"

    core.headers.update({"Authorization": "Bearer admin"})
    view = core.get(f"/v1/missions/{_MISSION_ID}/volume-changes")
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["reportCount"] == 1
    assert body["latestTotalNetM3"] == pytest.approx(report.total_net_m3)
    zone = body["reports"][0]["report"]["zones"][0]
    assert zone["fillM3"] == pytest.approx(report.zones[0].fill_m3)


def test_uncertainty_is_null_and_says_why_on_the_odm_path(
    wired: tuple[_CoreSink, TestClient, str, httpx.Client],
) -> None:
    """[핵심 정직성] 오차한계 없음이 화면까지 이유와 함께 전달된다 (INV-024)."""
    sink, _core, job_id, storage = wired
    baseline, current = _sources(job_id)

    report = compute_and_submit(
        sink=sink,
        mission_id=_MISSION_ID,
        volume_change_id="vc-e2e-2",
        baseline=baseline,
        current=current,
        zones={"zone-0": _wgs84_square(10.0)},
        zone_crs="EPSG:4326",
        vertical_datum="ellipsoidal_native",
        computed_at=_COMPUTED_AT,
        http_client=storage,
    )

    zone = report.zones[0]
    assert zone.uncertainty_m3 is None
    assert "GCP" in zone.uncertainty_note or "검사점" in zone.uncertainty_note


def test_multiple_zones_are_measured_independently(
    wired: tuple[_CoreSink, TestClient, str, httpx.Client],
) -> None:
    """구역을 여러 개 주면 각각 잰다 — 총합이 아니라 구역별 답이 필요하다."""
    sink, _core, job_id, storage = wired
    baseline, current = _sources(job_id)

    report = compute_and_submit(
        sink=sink,
        mission_id=_MISSION_ID,
        volume_change_id="vc-e2e-3",
        baseline=baseline,
        current=current,
        zones={"zone-a": _wgs84_square(10.0), "zone-b": _wgs84_square(5.0)},
        zone_crs="EPSG:4326",
        vertical_datum="ellipsoidal_native",
        computed_at=_COMPUTED_AT,
        http_client=storage,
    )

    by_id = {zone.zone_id: zone for zone in report.zones}
    assert by_id["zone-a"].fill_m3 > by_id["zone-b"].fill_m3
    assert by_id["zone-b"].fill_m3 == pytest.approx(25.0, rel=0.1)


def test_a_missing_dsm_fails_without_submitting(
    wired: tuple[_CoreSink, TestClient, str, httpx.Client],
) -> None:
    """[음성] 받지 못한 DSM 으로 부분 결과를 올리지 않는다."""
    sink, core, job_id, storage = wired
    baseline, current = _sources(job_id)
    broken = ArtifactSource(ref=current.ref, download_url="https://storage.invalid/nope")

    with pytest.raises(VolumeChangeRunError):
        compute_and_submit(
            sink=sink,
            mission_id=_MISSION_ID,
            volume_change_id="vc-e2e-4",
            baseline=baseline,
            current=broken,
            zones={"zone-0": _wgs84_square(10.0)},
            zone_crs="EPSG:4326",
            vertical_datum="ellipsoidal_native",
            computed_at=_COMPUTED_AT,
            http_client=storage,
        )

    core.headers.update({"Authorization": "Bearer admin"})
    assert core.get(f"/v1/missions/{_MISSION_ID}/volume-changes").status_code == 404


def _wgs84_square_far_outside_raster(size_m: float) -> dict[str, object]:
    """래스터에서 10km 떨어진 정사각 구역 — DsmDiffError("유효한 셀이 없다")를 낸다."""
    far_x, far_y = _ORIGIN_X + 10_000.0, _ORIGIN_Y + 10_000.0
    corners_xy = [
        (far_x, far_y), (far_x + size_m, far_y),
        (far_x + size_m, far_y - size_m), (far_x, far_y - size_m), (far_x, far_y),
    ]
    ring = [
        list(reproject_point(x, y, from_crs="EPSG:5186", to_crs="EPSG:4326"))
        for x, y in corners_xy
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def test_a_zone_outside_the_raster_fails_without_submitting(
    wired: tuple[_CoreSink, TestClient, str, httpx.Client],
) -> None:
    """[음성][회귀] dsm_diff.DsmDiffError(구역이 래스터 밖)가 VolumeChangeRunError
    로 감싸이지 않고 그대로 새면, 이 함수를 자동으로 부르는 호출자(비교 워커,
    W2)는 실패를 FAILED 로 보고하지 못하고 요청이 RUNNING 에 무기한 걸린다
    (2026-08-10 실 인프라 재현으로 확인된 결함, run_change_detection.py 가 이미
    ChangeDetectionError 를 감싸는 것과 대칭으로 고쳤다)."""
    sink, core, job_id, storage = wired
    baseline, current = _sources(job_id)

    with pytest.raises(VolumeChangeRunError):
        compute_and_submit(
            sink=sink,
            mission_id=_MISSION_ID,
            volume_change_id="vc-e2e-outside-raster",
            baseline=baseline,
            current=current,
            zones={"zone-far": _wgs84_square_far_outside_raster(10.0)},
            zone_crs="EPSG:4326",
            vertical_datum="ellipsoidal_native",
            computed_at=_COMPUTED_AT,
            http_client=storage,
        )

    core.headers.update({"Authorization": "Bearer admin"})
    assert core.get(f"/v1/missions/{_MISSION_ID}/volume-changes").status_code == 404


def test_identical_inputs_produce_an_identical_report(
    wired: tuple[_CoreSink, TestClient, str, httpx.Client],
) -> None:
    """같은 입력·같은 시각이면 같은 리포트다 — 재현 가능해야 원장이 의미를 갖는다."""
    sink, _core, job_id, storage = wired
    baseline, current = _sources(job_id)
    zones = {"zone-0": _wgs84_square(10.0)}

    def run() -> VolumeChangeReport:
        return compute_and_submit(
            sink=sink,
            mission_id=_MISSION_ID,
            volume_change_id="vc-e2e-5",
            baseline=baseline,
            current=current,
            zones=zones,
            zone_crs="EPSG:4326",
            vertical_datum="ellipsoidal_native",
            computed_at=_COMPUTED_AT,
            http_client=storage,
        )

    first = run()
    second = run()

    assert first == second
    # 같은 내용의 재제출은 Core 가 멱등 처리한다(409 가 아니다).
    assert sink.last_status == 201
