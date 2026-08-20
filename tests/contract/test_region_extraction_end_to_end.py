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

from datetime import UTC, datetime
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
from ksi_core.mission_records import MissionRecord, MissionRecordVerdict
from ksi_core.processing_jobs import ProcessingJobStatus, build_processing_artifact_object_key
from ksi_core.region_extraction_reports import RegionExtractionStore, mount_region_extraction
from ksi_core.region_extraction_requests import (
    RegionExtractionRequestStore,
    mount_region_extraction_requests,
)
from ksi_core.source_media import SourceMediaClaim
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_processing_controller.core_client import HttpCoreClient
from ksi_processing_controller.design_conformance_worker import run_design_conformance_request
from ksi_processing_controller.region_extraction_worker import run_region_extraction_request
from test_comparison_requests import (  # noqa: E402
    _ADMIN_TOKEN,
    _CURRENT_MISSION_ID,
    _SITE_ID,
    _WORKER_TOKEN,
    _artifact_spec,
    _job_spec,
    _registry,
    _verify_bundle,
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
from test_design_conformance_requests import _DSM_VERTICAL, Fixture  # noqa: E402

_PAIR_MISSION_ID = "mission-cmp-current-pair"
_PAIR_NOW = datetime(2026, 8, 15, 3, 0, tzinfo=UTC)

# 사진측량 촬영 조건 — DJI M4D 광각 계열에 가까운 값. 이 시험이 확인하는 것은
# 값의 정확도가 아니라 "이 값이 초안 응답에 그대로 실리는가"다.
_BASELINE_ALTITUDE_M = 80.0
_BASELINE_FRONT_OVERLAP = 0.8
_BASELINE_SIDE_OVERLAP = 0.7


def _register_pair_mission_with_capture(
    base: Fixture, *, mission_id: str = _PAIR_MISSION_ID, with_envelope: bool = True
) -> str:
    """짝 발급(artifactKind=pair) 임무 + 원본 산출물을 가진 SUCCEEDED 작업 하나.

    ``base.missions``·``base.jobs``·``base.source_media`` 는 이미 만들어진
    실제 저장소다 — 새 원장을 열지 않고 여기에 새 mission_id 를 하나 더 추가한다.
    사이트·설계면(``base.design_surface_id``)은 사이트 단위 자산이라 그대로
    재사용한다.

    ``with_envelope=False`` 는 도출 실패 경로(``CAPTURE_DERIVATION_FAILED``)를
    재현하기 위한 기형 계약이다 — ``flightEnvelope`` 자체를 빼서 도출이 실패할
    수밖에 없게 만든다.
    """
    plan_request = {
        "route": {
            "altitudeM": _BASELINE_ALTITUDE_M,
            "camera": {
                "sensorWidthMm": 17.3,
                "focalLengthMm": 12.29,
                "imageWidthPx": 5280,
                "imageHeightPx": 3956,
                "frontOverlap": _BASELINE_FRONT_OVERLAP,
                "sideOverlap": _BASELINE_SIDE_OVERLAP,
            },
        },
    }
    contract: dict[str, object] = {"schemaVersion": "1.2", "missionId": mission_id}
    if with_envelope:
        contract["flightEnvelope"] = {
            "allowedVolumes": [_SITE_ID],
            "excludedVolumes": [],
            "minAltitudeM": 20.0,
            "maxAltitudeM": 120.0,
            "altitudeReference": "relativeToStartPoint",
        }
    assert (
        base.missions.record_issuance(
            MissionRecord(
                mission_id=mission_id,
                site_id=_SITE_ID,
                mission_type="SPATIAL_REFRESH",
                artifact_kind="pair",
                contract=contract,
                kmz_sha256="sha256:" + "b" * 64,
                route_pattern="lawnmower",
                waypoint_count=13,
                planned_coverage_ratio=1.0,
                issued_at=_PAIR_NOW,
                issued_by="do-1",
                plan_request=plan_request,
                plan_request_digest=None,
            )
        )
        is MissionRecordVerdict.RECORDED
    )

    claims = [
        SourceMediaClaim(
            media_id=f"{mission_id}-img-{i:03d}.jpg",
            sha256="a" * 63 + str(i),
            size_bytes=1_000_000 + i,
            width=4000,
            height=3000,
            content_type="image/jpeg",
        )
        for i in range(3)
    ]
    assert (
        base.source_media.register_batch(
            mission_id, claims, registered_by="op-1", now=_PAIR_NOW
        ).verdict.value
        == "PROCESSED"
    )
    assert (
        base.source_media.seal(mission_id, sealed_by="op-1", now=_PAIR_NOW).verdict.value
        == "SEALED"
    )

    record = base.jobs.issue(mission_id, _job_spec(), issued_by="op-1", now=_PAIR_NOW).record
    assert record is not None
    assert base.jobs.acquire_lease(record.job_id, worker_id="w-1", now=_PAIR_NOW).verdict.value in {
        "LEASED",
        "LEASE_RENEWED",
    }
    assert (
        base.jobs.transition(
            record.job_id, ProcessingJobStatus.RUNNING, detail=None, actor="w-1", now=_PAIR_NOW
        ).verdict.value
        == "TRANSITIONED"
    )
    dsm_spec = _artifact_spec(
        "dsm", kind=ProcessingArtifactKind.DSM, vertical_reference=_DSM_VERTICAL
    )
    assert (
        base.jobs.register_artifact(
            record.job_id, dsm_spec, registered_by="w-1", now=_PAIR_NOW
        ).verdict.value
        == "ARTIFACT_REGISTERED"
    )
    # dsm 은 파생 kind(INV-051) — SUCCEEDED 게이트(assert_succeeded_is_backed)를
    # 정직하게 통과하려면 source-eligible artifact 가 최소 1건 필요하다. camera_poses
    # 필러는 이 테스트가 실제로 보는 dsm 존재 여부(구역 추출 대상)에 영향을 주지 않는다.
    camera_poses_spec = _artifact_spec(
        f"filler-camera-poses-{record.job_id}", kind=ProcessingArtifactKind.CAMERA_POSES
    )
    assert (
        base.jobs.register_artifact(
            record.job_id, camera_poses_spec, registered_by="w-1", now=_PAIR_NOW
        ).verdict.value
        == "ARTIFACT_REGISTERED"
    )
    _verify_bundle(base.source_media, mission_id)
    assert (
        base.jobs.transition(
            record.job_id,
            ProcessingJobStatus.SUCCEEDED,
            detail="산출물 등록됨",
            actor="w-1",
            now=_PAIR_NOW,
        ).verdict.value
        == "TRANSITIONED"
    )
    return record.job_id


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


def test_region_extraction_request_is_auto_chained_after_design_conformance_success(
    tmp_path: Path,
) -> None:
    """[핵심] region_extraction_store 를 넘기면 사람이 ③(수동 POST)을 안 눌러도 된다.

    region-extraction-ux-decision(2026-08-15, 대표자 확정): 설계 대비 잔량
    계산이 성공하면 변화 영역 추출은 자동으로 잇는다 — 재관측 Mission 발급만
    사람이 계속 고른다. 위 시험과 같은 픽스처를 쓰되 ③ 의 수동 POST 를
    빼고, 워커가 성공 전이를 보고하는 그 순간 요청이 이미 QUEUED 로 있는지를
    직접 본다.
    """
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

    app = FastAPI()
    mount_auth(app, _registry())
    # 유일한 차이 — region_extraction_store 를 넘겨 자동 연동을 켠다.
    mount_design_conformance_requests(
        app, base.requests, base.storage, region_extraction_store=region_extraction_requests
    )
    mount_design_conformance_reports(app, design_conformance_reports, base.storage)
    # 사람이 같은 조합을 다시 눌렀을 때의 멱등성(아래)을 HTTP 경로로 확인하려고
    # 수동 표면도 그대로 장착해 둔다 — 자동 연동이 이 표면을 없애지 않는다.
    mount_region_extraction_requests(
        app, region_extraction_requests, design_conformance_reports, base.storage
    )

    human = TestClient(app)
    human.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})

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
    # design_conformance_id_of 는 항등이다(모듈 docstring) — 첫 추출 요청의
    # id 는 결정적으로 유도된다(build_region_extraction_request_id).
    expected_rex_id = f"{dcf_request_id}-rex1"

    assert region_extraction_requests.get(expected_rex_id) is None, (
        "설계 대비 요청이 아직 안 끝났는데 변화 영역 추출이 벌써 있으면 안 된다"
    )

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
    finally:
        storage_http.close()

    # ③ 을 사람이 누르지 않았는데도 이미 QUEUED 로 있다.
    chained = region_extraction_requests.get(expected_rex_id)
    assert chained is not None
    assert chained.status is ProcessingJobStatus.QUEUED
    assert chained.requested_by == "system:design-conformance-auto-chain"

    # 같은 조합을 사람이 다시 눌러도(예: 대시보드에서 재확인) 중복을 만들지
    # 않는다 — create() 의 기존 멱등성을 그대로 물려받는다.
    duplicate = human.post(
        f"/v1/missions/{_CURRENT_MISSION_ID}/design-conformance/{dcf_request_id}"
        "/region-extraction-requests",
    )
    assert duplicate.status_code == 200, duplicate.json()
    assert duplicate.json()["verdict"] == "ALREADY_REQUESTED"
    assert duplicate.json()["request"]["requestId"] == chained.request_id


def test_spatial_refresh_draft_carries_a_derived_capture_plan(tmp_path: Path) -> None:
    """[핵심] 재관측 초안이 AOI 에서 멈추지 않고 촬영 계획까지 준다(ADR-KSI-019 G5).

    이 임무는 짝 발급(``artifactKind=pair``)이라 직전 촬영 조건(고도·카메라)을
    안다 — 그래서 도출이 성립하고, 그 결과가 초안 응답에 실린다. 도출 고도가
    비행 봉투(20~120m) 안인지도 함께 본다(INV-014 의 상한을 이 도출이 존중하는지).
    """
    current_path = _write_raster(tmp_path / "current.tif", _ramp())
    design_path = _write_raster(tmp_path / "design.tif", _flat())
    design_sha = sha256_of_file(design_path).removeprefix("sha256:")

    base = Fixture(tmp_path, design_sha256=design_sha)
    pair_job_id = _register_pair_mission_with_capture(base)

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
            site_id=_SITE_ID, job_id=pair_job_id, artifact_id="dsm"
        ),
        current_path.read_bytes(),
        content_type="application/octet-stream",
    )
    design_conformance_reports = DesignConformanceStore(
        DurableJournal(tmp_path / "design-conformance-pair.jsonl"),
        mission_store=base.missions,
        processing_job_store=base.jobs,
        request_store=base.requests,
        storage=base.storage,
    )
    region_extraction_requests = RegionExtractionRequestStore(
        DurableJournal(tmp_path / "region-extraction-requests-pair.jsonl"),
        mission_store=base.missions,
        design_conformance_report_store=design_conformance_reports,
    )
    region_extraction_reports = RegionExtractionStore(
        DurableJournal(tmp_path / "region-extraction-pair.jsonl"),
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

    created = human.post(
        f"/v1/missions/{_PAIR_MISSION_ID}/design-conformance-requests",
        json={
            "designSurfaceId": base.design_surface_id,
            "currentJobId": pair_job_id,
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
            work_dir=tmp_path / "work-dcf-pair",
            http_client=storage_http,
            now_message=lambda _msg: None,
        )

        rex_created = human.post(
            f"/v1/missions/{_PAIR_MISSION_ID}/design-conformance/{dcf_request_id}"
            "/region-extraction-requests",
        )
        assert rex_created.status_code == 201, rex_created.json()
        rex_request_id = rex_created.json()["request"]["requestId"]

        run_region_extraction_request(
            rex_request_id,
            core=core_client,
            work_dir=tmp_path / "work-rex-pair",
            http_client=storage_http,
            now_message=lambda _msg: None,
        )
    finally:
        storage_http.close()

    listed = human.get(f"/v1/missions/{_PAIR_MISSION_ID}/region-extraction")
    assert listed.status_code == 200, listed.json()
    report_body = listed.json()["reports"][0]["report"]
    regions = report_body["regions"]
    fill_region = next(r for r in regions if r["volume"]["fillM3"] > 0)
    assert fill_region["volume"]["fillM3"] == pytest.approx(_EXPECTED_FILL_M3)

    change_region_set_id = report_body["changeRegionSetId"]
    draft = human.get(
        f"/v1/missions/{_PAIR_MISSION_ID}/region-extraction/{change_region_set_id}"
        f"/regions/{fill_region['regionId']}/spatial-refresh-draft"
    )
    assert draft.status_code == 200, draft.json()
    body = draft.json()
    assert body["verdict"] == "DRAFT_READY"
    assert body["aoi"] is not None
    assert body["captureUnavailableReason"] is None
    assert body["captureGrade"] in {"STANDARD", "DETAILED", "INTENSIVE"}
    assert body["captureAltitudeM"] is not None
    assert 20.0 <= body["captureAltitudeM"] <= 120.0  # 비행 봉투 안(INV-014)
    assert body["captureIntervalM"] is not None
    assert body["captureIntervalM"] > 0.0  # 카메라 산식에서 도출된 진행방향 간격
    assert body["baselineGsdM"] is not None
    assert body["captureRationale"], "근거 없는 자동 초안은 검토할 수 없다"


def test_capture_plan_derivation_does_not_block_the_aoi_draft_on_failure(
    tmp_path: Path,
) -> None:
    """[핵심] 도출이 실패해도 AOI 초안까지 죽지 않는다.

    비행 봉투(``flightEnvelope``)가 계약에 없는 기형 계약을 만들어 도출을 실패시킨다
    — 그래도 AOI 는 나오고, 사유가 ``CAPTURE_DERIVATION_FAILED`` 로 명시된다.
    """
    current_path = _write_raster(tmp_path / "current2.tif", _ramp())
    design_path = _write_raster(tmp_path / "design2.tif", _flat())
    design_sha = sha256_of_file(design_path).removeprefix("sha256:")

    base = Fixture(tmp_path, design_sha256=design_sha)
    # 봉투(flightEnvelope)가 없는 별도 "pair" 임무 — 도출이 실패할 수밖에 없다.
    broken_mission_id = f"{_PAIR_MISSION_ID}-no-envelope"
    pair_job_id = _register_pair_mission_with_capture(
        base, mission_id=broken_mission_id, with_envelope=False
    )

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
            site_id=_SITE_ID, job_id=pair_job_id, artifact_id="dsm"
        ),
        current_path.read_bytes(),
        content_type="application/octet-stream",
    )
    design_conformance_reports = DesignConformanceStore(
        DurableJournal(tmp_path / "design-conformance-broken.jsonl"),
        mission_store=base.missions,
        processing_job_store=base.jobs,
        request_store=base.requests,
        storage=base.storage,
    )
    region_extraction_requests = RegionExtractionRequestStore(
        DurableJournal(tmp_path / "region-extraction-requests-broken.jsonl"),
        mission_store=base.missions,
        design_conformance_report_store=design_conformance_reports,
    )
    region_extraction_reports = RegionExtractionStore(
        DurableJournal(tmp_path / "region-extraction-broken.jsonl"),
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

    created = human.post(
        f"/v1/missions/{broken_mission_id}/design-conformance-requests",
        json={
            "designSurfaceId": base.design_surface_id,
            "currentJobId": pair_job_id,
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
            work_dir=tmp_path / "work-dcf-broken",
            http_client=storage_http,
            now_message=lambda _msg: None,
        )
        rex_created = human.post(
            f"/v1/missions/{broken_mission_id}/design-conformance/{dcf_request_id}"
            "/region-extraction-requests",
        )
        assert rex_created.status_code == 201, rex_created.json()
        rex_request_id = rex_created.json()["request"]["requestId"]
        run_region_extraction_request(
            rex_request_id,
            core=core_client,
            work_dir=tmp_path / "work-rex-broken",
            http_client=storage_http,
            now_message=lambda _msg: None,
        )
    finally:
        storage_http.close()

    listed = human.get(f"/v1/missions/{broken_mission_id}/region-extraction")
    report_body = listed.json()["reports"][0]["report"]
    fill_region = next(r for r in report_body["regions"] if r["volume"]["fillM3"] > 0)
    change_region_set_id = report_body["changeRegionSetId"]

    draft = human.get(
        f"/v1/missions/{broken_mission_id}/region-extraction/{change_region_set_id}"
        f"/regions/{fill_region['regionId']}/spatial-refresh-draft"
    )

    assert draft.status_code == 200, draft.json()
    body = draft.json()
    assert body["verdict"] == "DRAFT_READY"
    assert body["aoi"] is not None
    assert body["captureGrade"] is None
    assert body["captureUnavailableReason"] == "CAPTURE_DERIVATION_FAILED"
