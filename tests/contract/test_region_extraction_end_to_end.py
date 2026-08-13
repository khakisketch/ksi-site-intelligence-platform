"""종단: 사람이 요청하고 **진짜 워커**가 설계 대비 잔량 → 변화 영역 추출까지 완주한다 (M4-E).

``test_design_conformance_reports.py`` 의
``test_end_to_end_human_request_worker_run_and_map_download`` 을 그대로
이어간다 — 그 시험이 만든 실제 diffRaster 위에서, 이번엔 ① 사람이 변화 영역
추출을 요청하고 ② 프로덕션과 같은 ``HttpCoreClient`` 를 쓴 워커가 ③ 그
diffRaster 를 실제로 내려받아 ④ 결정적으로 영역을 뽑고 ⑤ 제출·기록하고
⑥ 재관찰 초안 핸드오프까지 지나는 전 경로를 한 번에 지난다.

두 시점 손계산이 이미 검증돼 있다(``test_design_conformance_compute.py``):
설계면(flat 110)과 현재(서→동 1m/셀 램프)의 차이는 col=10 에서 정확히 0 이라
threshold(0.05m) 미만으로 빠지고, 그 결과 래스터가 **정확히 두 개**의 연결영역
(왼쪽 fill 블록·오른쪽 cut 블록)으로 갈라진다 — 그 총량은 각각
``_EXPECTED_FILL_M3``/``_EXPECTED_CUT_M3`` 와 같다(같은 래스터, 같은 셀들).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_change_detection.diff_raster import sha256_of_file
from ksi_core.auth import mount_auth
from ksi_core.design_conformance_reports import (
    DesignConformanceStore,
    mount_design_conformance_reports,
)
from ksi_core.design_conformance_requests import mount_design_conformance_requests
from ksi_core.design_surfaces import build_design_surface_object_key
from ksi_core.durable_journal import DurableJournal
from ksi_core.processing_jobs import ProcessingJobStatus, build_processing_artifact_object_key
from ksi_core.region_extraction_reports import RegionExtractionStore, mount_region_extraction
from ksi_core.region_extraction_requests import (
    RegionExtractionRequestStore,
    mount_region_extraction_requests,
)
from ksi_processing_controller.core_client import HttpCoreClient
from ksi_processing_controller.design_conformance_worker import run_design_conformance_request
from ksi_processing_controller.region_extraction_worker import run_region_extraction_request
from test_comparison_requests import (  # noqa: E402
    _ADMIN_TOKEN,
    _CURRENT_MISSION_ID,
    _SITE_ID,
    _WORKER_TOKEN,
    _registry,
)
from test_design_conformance_compute import (  # noqa: E402
    _CRS,
    _EXPECTED_CUT_M3,
    _EXPECTED_FILL_M3,
    _flat,
    _full_extent_zone,
    _ramp,
    _write_raster,
)
from test_design_conformance_reports import _storage_transport  # noqa: E402
from test_design_conformance_requests import Fixture  # noqa: E402


def test_design_conformance_then_region_extraction_end_to_end(tmp_path: Path) -> None:
    current_path = _write_raster(tmp_path / "current.tif", _ramp())
    design_path = _write_raster(tmp_path / "design.tif", _flat())
    design_sha = sha256_of_file(design_path).removeprefix("sha256:")

    base = Fixture(tmp_path, design_sha256=design_sha)
    base.storage.put_bytes(
        build_design_surface_object_key(
            site_id=base.sites.get(_SITE_ID).site_id,  # type: ignore[union-attr]
            design_surface_id=base.design_surface_id,
        ),
        design_path.read_bytes(),
        content_type="application/octet-stream",
    )
    base.storage.put_bytes(
        build_processing_artifact_object_key(
            site_id=_SITE_ID, job_id=base.current_job_id, artifact_id="dsm"
        ),
        current_path.read_bytes(),
        content_type="application/octet-stream",
    )
    design_conformance_reports = DesignConformanceStore(
        DurableJournal(tmp_path / "design-conformance.jsonl"),
        mission_store=base.missions,
        processing_job_store=base.jobs,
        request_store=base.requests,
        storage=base.storage,
    )
    region_extraction_requests = RegionExtractionRequestStore(
        DurableJournal(tmp_path / "region-extraction-requests.jsonl"),
        mission_store=base.missions,
        design_conformance_report_store=design_conformance_reports,
    )
    region_extraction_reports = RegionExtractionStore(
        DurableJournal(tmp_path / "region-extraction.jsonl"),
        mission_store=base.missions,
        request_store=region_extraction_requests,
        design_conformance_report_store=design_conformance_reports,
    )

    app = FastAPI()
    mount_auth(app, _registry())
    mount_design_conformance_requests(app, base.requests, base.storage)
    mount_design_conformance_reports(app, design_conformance_reports, base.storage)
    mount_region_extraction_requests(
        app, region_extraction_requests, design_conformance_reports, base.storage
    )
    mount_region_extraction(app, region_extraction_reports)

    human = TestClient(app)
    human.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})

    # ① 설계 대비 잔량 요청 + ② 워커 완주(이미 검증된 경로, test_design_
    # conformance_reports.py 의 종단 시험과 동일).
    created = human.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance-requests",
        json={
            "designSurfaceId": base.design_surface_id,
            "currentJobId": base.current_job_id,
            "zones": {"zone-all": _full_extent_zone()},
            "zoneCrs": _CRS,
        },
    )
    assert created.status_code == 201, created.json()
    dcf_request_id = created.json()["request"]["requestId"]

    worker_http = TestClient(app)
    core_client = HttpCoreClient("http://core.test", token=_WORKER_TOKEN, client=worker_http)
    storage_http = httpx.Client(transport=_storage_transport(base.storage))
    try:
        run_design_conformance_request(
            dcf_request_id,
            core=core_client,
            work_dir=tmp_path / "work-dcf",
            http_client=storage_http,
            now_message=lambda _msg: None,
        )

        # ③ 사람이 변화 영역 추출을 요청한다(같은 designConformanceId).
        design_conformance_id = dcf_request_id  # design_conformance_id_of 는 항등이다
        rex_created = human.post(
            f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance/{design_conformance_id}"
            "/region-extraction-requests",
        )
        assert rex_created.status_code == 201, rex_created.json()
        rex_request_id = rex_created.json()["request"]["requestId"]

        # ④ 진짜 워커가 실제로 diffRaster 를 내려받아 계산·제출·SUCCEEDED 까지.
        run_region_extraction_request(
            rex_request_id,
            core=core_client,
            work_dir=tmp_path / "work-rex",
            http_client=storage_http,
            now_message=lambda _msg: None,
        )
    finally:
        storage_http.close()

    final_request = region_extraction_requests.get(rex_request_id)
    assert final_request is not None
    assert final_request.status is ProcessingJobStatus.SUCCEEDED

    listed = human.get(f"/v1/missions/{_CURRENT_MISSION_ID}/region-extraction")
    assert listed.status_code == 200, listed.json()
    report_body = listed.json()["reports"][0]["report"]
    regions = report_body["regions"]

    # 손계산과 같은 두 영역(왼쪽 fill 블록·오른쪽 cut 블록) — col=10 이 문턱
    # 미만이라 정확히 둘로 갈라진다(모듈 docstring).
    assert len(regions) == 2
    fill_region = next(r for r in regions if r["volume"]["fillM3"] > 0)
    cut_region = next(r for r in regions if r["volume"]["cutM3"] > 0)
    assert fill_region["volume"]["fillM3"] == pytest.approx(_EXPECTED_FILL_M3)
    assert cut_region["volume"]["cutM3"] == pytest.approx(_EXPECTED_CUT_M3)
    # 둘 다 볼록(직사각형 블록)이라 hull 초안이 있다.
    assert fill_region["hullOvercaptureRatio"] == pytest.approx(1.0, abs=1e-6)
    assert cut_region["hullOvercaptureRatio"] == pytest.approx(1.0, abs=1e-6)

    # ⑤ 재관찰 초안 — 실제 AreaOfInterest 가 나온다.
    change_region_set_id = report_body["changeRegionSetId"]
    draft = human.get(
        f"/v1/missions/{_CURRENT_MISSION_ID}/region-extraction/{change_region_set_id}"
        f"/regions/{fill_region['regionId']}/spatial-refresh-draft"
    )
    assert draft.status_code == 200, draft.json()
    assert draft.json()["verdict"] == "DRAFT_READY"
    assert len(draft.json()["aoi"]["vertices"]) >= 3
