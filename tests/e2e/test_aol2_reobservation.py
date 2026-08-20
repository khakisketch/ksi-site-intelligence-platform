"""AOL-2 재관측 심화도 — 소프트웨어 종단 1회 (ADR-KSI-019 §5 6번, G5).

``test_aol1_mapping_autonomy.py`` 가 증명한 1세대 루프 위에서, 이번엔 설계 대비
잔량 → 변화 영역 추출 → **밀도가 변화량에 맞춰 자동 도출된** 재관측 초안 →
그 초안에서 실제로 발급된 2번째 매핑 임무 → 배포·회수·재구성까지 지나
공간모델이 2세대(``succeededEpochCount == 2``)로 갱신되는지 본다.

## 무엇이 진짜이고 무엇이 대역인가 — ``test_aol1_mapping_autonomy.py`` 와 동일 원칙

- **Core 는 진짜다**(``assemble_app``). **HTTP 를 거친다**(자동 전진 훅이 라우터에
  걸려 있다). **사진·설계면·현재 지형 래스터는 실제 바이트다** — 워커가 실제로
  열어 재고, 신고값을 되읊지 않는다(``verify_design_surface``·
  ``run_design_conformance_request``·``run_region_extraction_request`` 모두
  프로덕션 워커 함수 그대로). **오브젝트 스토리지는 인메모리 대역**이고
  **기체·재구성 엔진은 등장하지 않는다**(계약대로 행동하는 대역).

그래서 이 파일도 ``Backend Ready`` 를 증명하지 ``HIL Proven`` 을 증명하지
않는다(ADR-KSI-018).

## 이 파일이 함께 확인하는 것 — 계획 문서(2026-08-15-aol-2-reobservation-depth.md)
   Task 5 의 세 가지 단언

1. 재관측이 현장 상태를 ``BASELINE_MAPPING`` 으로 되돌리지 않는다.
2. 도출된 촬영 계획은 **제안**이지 **관문**이 아니다 — 운영자가 다른 값으로
   발급할 수 있다. 그리고 INV-015 중복도 하한은 그 제안과 무관하게 서버가
   여전히 강제한다(제안이 하한을 깎아 준 것이 아니다).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import rasterio
from fastapi.testclient import TestClient
from ksi_change_detection.diff_raster import sha256_of_file
from ksi_core.design_surfaces import build_design_surface_object_key
from ksi_core.processing_jobs import build_processing_artifact_object_key
from ksi_processing_controller.capture_time import extract_capture_time
from ksi_processing_controller.core_client import HttpCoreClient
from ksi_processing_controller.design_conformance_worker import run_design_conformance_request
from ksi_processing_controller.design_surface_verifier import verify_design_surface
from ksi_processing_controller.region_extraction_worker import run_region_extraction_request
from PIL import Image
from rasterio.transform import from_origin
from test_aol1_mapping_autonomy import (  # noqa: E402 -- 같은 디렉터리 sibling import 관행
    Aol1Fixture,
    _coverage_report,
    _ingest_once,
    _mapping_plan_request,
    _photos,
    _rect_aoi,
    _site_frame,
    aol1,
)

__test_uses_aol1_fixture = aol1  # pytest 픽스처 재수출 — 임포트만으론 미사용 경고가 뜬다

_SITE_ID = "site-aol1"
_MISSION_ID = "mission-aol1-001"
_MISSION_ID_2 = "mission-aol2-002"
_DEVICE_ID = "edge-aol1-01"
_WORKER_TOKEN = "aol1-worker"  # noqa: S105 -- test_aol1_mapping_autonomy._WORKER_TOKEN 과 동일 고정값

# 설계 대비 잔량이 쓰는 래스터 좌표계 — 실제 지리좌표(AOI)와는 독립된, 값
# 계산용 투영 CRS 공간이다(test_design_conformance_compute.py 와 동형, 이
# 파일 안에서 자체 정의한다 — tests/contract 와 tests/e2e 는 서로 다른 pytest
# import root 라 파일 간 임포트가 보장되지 않는다).
_RASTER_ORIGIN_X = 200_000.0
_RASTER_ORIGIN_Y = 550_000.0
_RASTER_SIZE = 20
_RASTER_CRS = "EPSG:5186"
_RASTER_NODATA = -9999.0

_BASELINE_ALTITUDE_M = 60.0
_BASELINE_FRONT_OVERLAP = 0.8
_BASELINE_SIDE_OVERLAP = 0.7
_CAMERA = {
    "sensorWidthMm": 17.3,
    "focalLengthMm": 12.29,
    "imageWidthPx": 5280,
    "imageHeightPx": 3956,
}

_DESIGN_VERTICAL = {
    "datum": "ellipsoidal",
    "basis": "설계사 제공 도면 표제부에 타원체고 명시",
    "source": "user_declared",
}
_DSM_VERTICAL = {
    "datum": "ellipsoidal_native",
    "basis": "ODM 이 RTK 타원체고를 변환 없이 그대로 출력",
    "source": "pipeline_declared",
}


def _write_raster(path: Path, values: np.ndarray) -> Path:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=_RASTER_SIZE,
        width=_RASTER_SIZE,
        count=1,
        dtype="float64",
        crs=_RASTER_CRS,
        nodata=_RASTER_NODATA,
        transform=from_origin(_RASTER_ORIGIN_X, _RASTER_ORIGIN_Y, 1.0, 1.0),
    ) as dataset:
        dataset.write(values.astype(np.float64), 1)
    return path


def _ramp() -> np.ndarray:
    """서→동으로 1m/셀 오르는 현재 지형 — 설계면(평탄 110)과 갈라져 변화를 만든다."""
    cols = np.arange(_RASTER_SIZE, dtype=np.float64)
    return np.tile(100.0 + cols, (_RASTER_SIZE, 1))


def _flat(level: float = 110.0) -> np.ndarray:
    return np.full((_RASTER_SIZE, _RASTER_SIZE), level, dtype=np.float64)


def _full_extent_zone() -> dict[str, Any]:
    """래스터 전체를 덮는 구역(래스터와 같은 좌표계)."""
    ring = [
        [_RASTER_ORIGIN_X, _RASTER_ORIGIN_Y],
        [_RASTER_ORIGIN_X + _RASTER_SIZE, _RASTER_ORIGIN_Y],
        [_RASTER_ORIGIN_X + _RASTER_SIZE, _RASTER_ORIGIN_Y - _RASTER_SIZE],
        [_RASTER_ORIGIN_X, _RASTER_ORIGIN_Y - _RASTER_SIZE],
        [_RASTER_ORIGIN_X, _RASTER_ORIGIN_Y],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def _storage_transport(storage: Any) -> httpx.MockTransport:
    """``_MemoryStorage`` 의 presigned URL 규약(경로=objectKey, 쿼리는 장식)을 흉내 낸다."""

    def handler(request: httpx.Request) -> httpx.Response:
        object_key = request.url.path.removeprefix("/")
        if request.method == "PUT":
            storage.put_bytes(object_key, request.content, content_type="application/octet-stream")
            return httpx.Response(200)
        try:
            return httpx.Response(200, content=storage.get_bytes(object_key))
        except Exception:  # noqa: BLE001 -- 없는 키는 404 로(스토리지와 같은 모양)
            return httpx.Response(404)

    return httpx.MockTransport(handler)


def _run_worker(fixture: Aol1Fixture, job_id: str, mission_id: str, *, with_dsm: bool) -> None:
    """``test_aol1_mapping_autonomy._run_worker`` 와 같은 실측 대조 경로.

    ``mission_id`` 를 인자로 받는 것이 유일한 차이다 — 그 워커 대역은 모듈 상수
    하나(첫 임무)에 고정돼 있어 두 번째(재관측) 임무에는 못 쓴다. ``with_dsm`` 은
    설계 대비 잔량 계산에 쓸 DSM 산출물을 이 재구성이 함께 내는지 — 1세대만
    ``True`` 다(2세대는 재관측 결과이지 새 설계 대비 기준이 아니다).
    """
    client = fixture.client

    lease = client.post(
        f"/v1/processing-jobs/{job_id}/lease",
        json={"workerId": "worker-1", "ttlSeconds": 600},
        headers=fixture.as_worker(),
    )
    assert lease.status_code == 201, lease.text

    job_input = client.get(f"/v1/processing-jobs/{job_id}/input", headers=fixture.as_worker())
    assert job_input.status_code == 200, job_input.text
    media = job_input.json()["input"]["media"]
    assert media, "입력이 비어 있으면 이 시험은 공허하다"

    measurements: list[dict[str, Any]] = []
    for item in media:
        raw = fixture.storage.get_bytes(item["objectKey"])
        with Image.open(BytesIO(raw)) as image:
            width, height = image.size
        capture_time = extract_capture_time(
            fixture.captures_root / mission_id / item["mediaId"]
        )
        measurements.append(
            {
                "mediaId": item["mediaId"],
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
                "width": width,
                "height": height,
                "captureTime": {
                    "capturedAt": (
                        capture_time.captured_at.isoformat()
                        if capture_time.captured_at is not None
                        else None
                    ),
                    "source": capture_time.source.value,
                    "status": capture_time.status.value,
                },
            }
        )

    verified = client.post(
        f"/v1/missions/{mission_id}/source-media/verify",
        json={"measurements": measurements},
        headers=fixture.as_worker(),
    )
    assert verified.status_code == 201, verified.text
    assert verified.json()["verdict"] == "VERIFIED", verified.text

    running = client.post(
        f"/v1/processing-jobs/{job_id}/transitions",
        json={"targetStatus": "RUNNING"},
        headers=fixture.as_worker(),
    )
    assert running.status_code == 200, running.text

    artifact = client.post(
        f"/v1/processing-jobs/{job_id}/artifacts",
        json={
            "artifactId": "pointcloud",
            "kind": "point_cloud",
            "authority": "source",
            "digest": "sha256:" + hashlib.sha256(f"aol2-point-cloud-{job_id}".encode()).hexdigest(),
            "format": "laz",
            "crs": _RASTER_CRS,
        },
        headers=fixture.as_worker(),
    )
    assert artifact.status_code == 201, artifact.text

    if with_dsm:
        dsm = client.post(
            f"/v1/processing-jobs/{job_id}/artifacts",
            json={
                "artifactId": "dsm",
                "kind": "dsm",
                "authority": "source",
                "digest": "sha256:" + hashlib.sha256(f"aol2-dsm-{job_id}".encode()).hexdigest(),
                "format": "geotiff",
                "crs": _RASTER_CRS,
                "gsd": 0.05,
                "verticalReference": _DSM_VERTICAL,
            },
            headers=fixture.as_worker(),
        )
        assert dsm.status_code == 201, dsm.text

    succeeded = client.post(
        f"/v1/processing-jobs/{job_id}/transitions",
        json={"targetStatus": "SUCCEEDED", "detail": "산출물 등록됨"},
        headers=fixture.as_worker(),
    )
    assert succeeded.status_code == 200, succeeded.text


def _run_first_epoch(fixture: Aol1Fixture) -> str:
    """1세대 매핑 루프 — ``_run_the_loop`` 와 같되 카메라 계약(route.camera) 을
    실어 재관측 초안이 직전 촬영 조건을 읽을 수 있게 하고, DSM 도 함께 낸다.
    """
    client = fixture.client

    assert (
        client.post(
            "/v1/sites",
            json={"siteId": _SITE_ID, "name": "AOL-2 현장", "siteFrame": _site_frame()},
            headers=fixture.as_operator(),
        ).status_code
        == 201
    )
    assert (
        client.put(
            f"/v1/sites/{_SITE_ID}/aoi",
            json={"aoi": _rect_aoi(), "siteFrame": _site_frame()},
            headers=fixture.as_operator(),
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/v1/sites/{_SITE_ID}/model-age-policy",
            json={"maxAgeDays": 30},
            headers=fixture.as_operator(),
        ).status_code
        == 200
    )

    plan_request = _mapping_plan_request()
    # spacingM/captureIntervalM 직접 지정 대신 camera 를 실어 서버가 간격을
    # 계산하게 한다 — 재관측 초안의 직전 촬영조건 도출은 route.camera 가 있어야
    # 성립한다(region_extraction_reports._baseline_capture_of).
    plan_request["route"] = {
        "altitudeM": _BASELINE_ALTITUDE_M,
        "camera": {
            **_CAMERA,
            "frontOverlap": _BASELINE_FRONT_OVERLAP,
            "sideOverlap": _BASELINE_SIDE_OVERLAP,
        },
    }
    plan = client.post("/v1/missions/plans", json=plan_request, headers=fixture.as_operator())
    assert plan.status_code == 201, plan.text
    assert plan.json()["waypointCount"] > 0
    assert plan.json()["kmzSha256"]

    dispatched = client.post(
        f"/v1/missions/{_MISSION_ID}/execution-transitions",
        json={"targetStatus": "DISPATCHED", "detail": "RC Plus 2 로 KMZ 이관"},
        headers=fixture.as_operator(),
    )
    assert dispatched.status_code == 200, dispatched.text

    coverage = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_coverage_report(),
        headers=fixture.as_device(),
    )
    assert coverage.status_code == 201, coverage.text

    _photos(fixture.captures_root / _MISSION_ID, count=3)
    report = _ingest_once(fixture)
    assert report.succeeded == [_MISSION_ID], (report.failed, report.skipped)

    jobs = client.get(
        f"/v1/missions/{_MISSION_ID}/processing-jobs", headers=fixture.as_operator()
    )
    assert jobs.status_code == 200, jobs.text
    job_id = str(jobs.json()["jobs"][0]["jobId"])

    _run_worker(fixture, job_id, _MISSION_ID, with_dsm=True)
    return job_id


def _approve_autonomy(fixture: Aol1Fixture) -> None:
    """사람의 승인 — SPATIAL_REFRESH 는 자율 개시 이후 현장에서만 발급된다
    (``mission_gating._REFRESH_EXISTING_MODEL``, ``MODEL_VALIDATION`` 은 포함되지
    않는다)."""
    client = fixture.client
    for target in ("PROVISIONAL_AUTONOMY", "PATROL_READY"):
        response = client.post(
            f"/v1/sites/{_SITE_ID}/transitions",
            json={"targetStatus": target, "evidence": "품질 검증 통과", "reason": "승인"},
            headers=fixture.as_operator(),
        )
        assert response.status_code == 200, response.text
    assert fixture.site_status() == "PATROL_READY"


def _register_verified_design_surface(
    fixture: Aol1Fixture,
    *,
    design_path: Path,
    core_client: HttpCoreClient,
    storage_http: httpx.Client,
) -> str:
    """설계면 등록 → 봉인 → 실제 워커(``verify_design_surface``)로 검증까지."""
    client = fixture.client
    design_sha = sha256_of_file(design_path).removeprefix("sha256:")

    registered = client.post(
        f"/v1/sites/{_SITE_ID}/design-surfaces",
        json={
            "name": "AOL-2 설계고",
            "revision": "Rev.A",
            "declared": {
                "crs": _RASTER_CRS,
                "sha256": design_sha,
                "verticalReference": _DESIGN_VERTICAL,
            },
        },
        headers=fixture.as_operator(),
    )
    assert registered.status_code == 201, registered.text
    design_surface_id = str(registered.json()["designSurfaceId"])

    fixture.storage.put_bytes(
        build_design_surface_object_key(site_id=_SITE_ID, design_surface_id=design_surface_id),
        design_path.read_bytes(),
        content_type="application/octet-stream",
    )

    sealed = client.post(
        f"/v1/sites/{_SITE_ID}/design-surfaces/{design_surface_id}/seal",
        headers=fixture.as_operator(),
    )
    assert sealed.status_code == 201, sealed.text

    pending = client.get(
        "/v1/design-surfaces", params={"status": "SEALED"}, headers=fixture.as_worker()
    )
    assert pending.status_code == 200, pending.text
    matches = [
        surface
        for surface in pending.json()["surfaces"]
        if surface["designSurfaceId"] == design_surface_id
    ]
    assert matches, "방금 봉인한 설계면이 워커 대기 목록에 없다"

    verdict = verify_design_surface(
        design_surface_id,
        download_url=matches[0]["downloadUrl"],
        core=core_client,
        http_client=storage_http,
        work_dir=fixture.state_dir / "work-verify",
    )
    assert verdict == "VERIFIED", verdict
    return design_surface_id


def _run_design_conformance_and_region_extraction(
    fixture: Aol1Fixture,
    *,
    design_surface_id: str,
    job_id: str,
    core_client: HttpCoreClient,
    storage_http: httpx.Client,
) -> tuple[str, dict[str, Any]]:
    """설계 대비 잔량 → (자동 연동) 변화 영역 추출까지 실제 워커로 완주한다.

    반환값은 ``(changeRegionSetId, fillRegion)`` — 다음 단계(재관측 초안)가 쓴다.
    """
    client = fixture.client

    created = client.post(
        f"/v1/missions/{_MISSION_ID}/design-conformance-requests",
        json={
            "designSurfaceId": design_surface_id,
            "currentJobId": job_id,
            "zones": {"zone-all": _full_extent_zone()},
            "zoneCrs": _RASTER_CRS,
        },
        headers=fixture.as_operator(),
    )
    assert created.status_code == 201, created.text
    dcf_request_id = created.json()["request"]["requestId"]

    run_design_conformance_request(
        dcf_request_id,
        core=core_client,
        work_dir=fixture.state_dir / "work-dcf",
        http_client=storage_http,
        now_message=lambda _msg: None,
    )

    # region-extraction-ux-decision(2026-08-15): 설계 대비 잔량 성공이 변화 영역
    # 추출을 자동으로 잇는다 — id 는 결정적이다(design_conformance_id_of 항등 +
    # build_region_extraction_request_id 관례, test_region_extraction_end_to_end.py).
    rex_request_id = f"{dcf_request_id}-rex1"
    run_region_extraction_request(
        rex_request_id,
        core=core_client,
        work_dir=fixture.state_dir / "work-rex",
        http_client=storage_http,
        now_message=lambda _msg: None,
    )

    listed = client.get(
        f"/v1/missions/{_MISSION_ID}/region-extraction", headers=fixture.as_operator()
    )
    assert listed.status_code == 200, listed.text
    report_body = listed.json()["reports"][0]["report"]
    fill_region = next(r for r in report_body["regions"] if r["volume"]["fillM3"] > 0)
    return report_body["changeRegionSetId"], fill_region


def test_reobservation_pair_completes_a_second_epoch_without_regressing_site_status(
    aol1: Any,
) -> None:
    """[핵심] 1세대 매핑 → 설계 대비 잔량 → 변화 영역 → 도출된 재관측 초안으로
    발급된 2세대 매핑까지, 사람이 현장 상태를 손으로 옮기지 않고 통과한다.

    ADR-KSI-019 G5 의 완료 기준 3가지를 함께 확인한다: (1) 재관측이 현장을
    ``BASELINE_MAPPING`` 으로 되돌리지 않는다, (2) 도출값은 촬영 조건에 그대로
    실려 발급된다(제안이 버려지지 않는다), (3) ``ProcessingJobRecord`` 원장 위의
    순수 판정(``evaluate_spatial_model``)이 2세대를 스스로 센다 — 별도 원장 없이.
    """
    fixture, _data_dir = aol1
    client = fixture.client
    tmp_path = fixture.captures_root.parent

    job_id = _run_first_epoch(fixture)
    _approve_autonomy(fixture)

    current_path = _write_raster(tmp_path / "current.tif", _ramp())
    design_path = _write_raster(tmp_path / "design.tif", _flat())
    fixture.storage.put_bytes(
        build_processing_artifact_object_key(site_id=_SITE_ID, job_id=job_id, artifact_id="dsm"),
        current_path.read_bytes(),
        content_type="application/octet-stream",
    )

    worker_http = TestClient(fixture.client.app)
    core_client = HttpCoreClient("http://core.test", token=_WORKER_TOKEN, client=worker_http)
    storage_http = httpx.Client(transport=_storage_transport(fixture.storage))
    try:
        design_surface_id = _register_verified_design_surface(
            fixture, design_path=design_path, core_client=core_client, storage_http=storage_http
        )
        change_region_set_id, fill_region = _run_design_conformance_and_region_extraction(
            fixture,
            design_surface_id=design_surface_id,
            job_id=job_id,
            core_client=core_client,
            storage_http=storage_http,
        )
    finally:
        storage_http.close()

    # ⑤ 재관찰 초안 — AOI 뿐 아니라 밀도가 도출돼 실린다(G5, 계획 2 Task 2).
    draft = client.get(
        f"/v1/missions/{_MISSION_ID}/region-extraction/{change_region_set_id}"
        f"/regions/{fill_region['regionId']}/spatial-refresh-draft",
        headers=fixture.as_operator(),
    )
    assert draft.status_code == 200, draft.text
    body = draft.json()
    assert body["verdict"] == "DRAFT_READY"
    assert body["captureUnavailableReason"] is None, body
    assert body["captureGrade"] in {"STANDARD", "DETAILED", "INTENSIVE"}
    assert body["captureAltitudeM"] is not None
    assert body["captureFrontOverlap"] is not None
    assert body["captureSideOverlap"] is not None
    assert body["captureRationale"], "근거 없는 자동 초안은 검토할 수 없다"

    # 도출값이 INV-015 하한을 스스로 지킨다(도출이 하한을 깎아준 것이 아니라
    # 원래 하한 이상인 직전 조건에서 시작했기 때문 — reobservation.py 클램프는
    # '올리기'만 한다). 별도 확인 시험(아래)에서 하한 자체가 서버에서 여전히
    # 강제되는지를 본다.
    assert body["captureFrontOverlap"] >= 0.6
    assert body["captureSideOverlap"] >= 0.5

    # ⑥ 그 초안에서 2세대 매핑 임무를 실제로 발급한다 — derivedFrom 이 계보를 싣는다.
    second_plan_request = {
        "contract": {
            "missionId": _MISSION_ID_2,
            "siteId": _SITE_ID,
            "missionType": "SPATIAL_REFRESH",
            "siteFrame": _site_frame(),
            "flightEnvelope": {
                "allowedVolumes": ["vol-1"],
                "excludedVolumes": [],
                "minAltitudeM": 5.0,
                "maxAltitudeM": 120.0,
            },
            "objectives": ["변화영역 재관측"],
            "viewpointPolicyId": "vp-1",
            "riskPolicyPackId": "risk-1",
            "fallbackPolicyId": "fb-1",
            "capturePolicyId": "cap-1",
            "assignedDeviceId": _DEVICE_ID,
        },
        "aoi": body["aoi"],
        "route": {
            "altitudeM": body["captureAltitudeM"],
            "camera": {
                **_CAMERA,
                "frontOverlap": body["captureFrontOverlap"],
                "sideOverlap": body["captureSideOverlap"],
            },
        },
        "drone": {"droneEnumValue": 99, "droneSubEnumValue": 0, "payloadEnumValue": 65534},
        "wayline": {
            "autoFlightSpeedMs": 5.0,
            "takeoffSecurityHeightM": 20.0,
            "globalTransitionalSpeedMs": 10.0,
        },
        "derivedFrom": {
            "sourceMissionId": _MISSION_ID,
            "changeRegionSetId": change_region_set_id,
            "regionId": fill_region["regionId"],
            "captureGrade": body["captureGrade"],
        },
    }
    plan2 = client.post(
        "/v1/missions/plans", json=second_plan_request, headers=fixture.as_operator()
    )
    assert plan2.status_code == 201, plan2.text
    assert plan2.json()["waypointCount"] > 0
    assert plan2.json()["kmzSha256"]

    dispatched2 = client.post(
        f"/v1/missions/{_MISSION_ID_2}/execution-transitions",
        json={"targetStatus": "DISPATCHED", "detail": "RC Plus 2 로 KMZ 이관"},
        headers=fixture.as_operator(),
    )
    assert dispatched2.status_code == 200, dispatched2.text

    coverage2 = client.post(
        f"/v1/missions/{_MISSION_ID_2}/coverage-report",
        json={
            "missionId": _MISSION_ID_2,
            "siteId": _SITE_ID,
            "timestamp": datetime.now(UTC).isoformat(),
            "cells": [
                {"cellId": "c-1", "state": "OBSERVED_HIGH_CONFIDENCE"},
                {"cellId": "c-2", "state": "RECONSTRUCTION_READY"},
            ],
            "summary": {
                "mandatoryHazardRatio": 1.0,
                "mandatoryAssetRatio": 1.0,
                "accessibleGeneralRatio": 1.0,
                "completionState": "COMPLETED",
            },
        },
        headers=fixture.as_device(),
    )
    assert coverage2.status_code == 201, coverage2.text

    _photos(fixture.captures_root / _MISSION_ID_2, count=3)
    report2 = _ingest_once(fixture)
    assert _MISSION_ID_2 in report2.succeeded, (report2.failed, report2.skipped)

    jobs2 = client.get(
        f"/v1/missions/{_MISSION_ID_2}/processing-jobs", headers=fixture.as_operator()
    )
    assert jobs2.status_code == 200, jobs2.text
    job_id_2 = str(jobs2.json()["jobs"][0]["jobId"])

    _run_worker(fixture, job_id_2, _MISSION_ID_2, with_dsm=False)

    # (1) 공간모델이 2세대다 — ProcessingJobRecord 원장 위의 순수 판정뿐, 별도
    # 원장이 없다(ADR-KSI-016 D3).
    model = fixture.spatial_model()
    assert model["state"] == "FRESH"
    assert model["succeededEpochCount"] == 2
    assert model["epochJobId"] == job_id_2

    # (1) 재관측이 현장을 되돌리지 않는다 — SPATIAL_REFRESH 는 매핑 계열이
    # 아니라 자동 전진 규칙표(_JOB_STATUS_SITE_ADVANCE)의 출발 상태가 아니고,
    # 갱신 계열 자동 전진 규칙 자체가 없다(스윕과 달리 사람이 다시 승인할
    # 필요도 없다는 뜻).
    assert fixture.site_status() == "PATROL_READY"

    # (2) derivedFrom 이 계보를 그대로 싣는다 — 제안이 버려지지 않았다.
    mission2 = client.get(f"/v1/missions/{_MISSION_ID_2}", headers=fixture.as_operator())
    assert mission2.status_code == 200, mission2.text
    derived = mission2.json()["derivedFrom"]
    assert derived is not None
    assert derived["sourceMissionId"] == _MISSION_ID
    assert derived["changeRegionSetId"] == change_region_set_id
    assert derived["regionId"] == fill_region["regionId"]

    filtered = client.get(
        "/v1/missions",
        params={"derivedFromRegion": fill_region["regionId"]},
        headers=fixture.as_operator(),
    )
    assert filtered.status_code == 200, filtered.text
    assert [m["missionId"] for m in filtered.json()] == [_MISSION_ID_2]


def test_capture_plan_is_a_proposal_the_floor_still_gates(aol1: Any) -> None:
    """[핵심] 도출값을 무시하고 하한 아래로 발급을 시도해도 서버가 여전히 막는다.

    G5 의 두 번째 단언 — "제안이지 관문이 아니다"는 **양방향**이다: 운영자가
    도출값을 따르지 않아도 되지만(자유), 그렇다고 INV-015 하한 자체가 느슨해지는
    것도 아니다(그 자유가 안전을 깎지 않는다). 재관측 초안까지는 앞 시험과
    동일 경로라 새 site/mission id 로 짧게 반복한다.
    """
    fixture, _data_dir = aol1
    client = fixture.client

    _run_first_epoch(fixture)
    _approve_autonomy(fixture)

    below_floor_request = {
        "contract": {
            "missionId": _MISSION_ID_2,
            "siteId": _SITE_ID,
            "missionType": "SPATIAL_REFRESH",
            "siteFrame": _site_frame(),
            "flightEnvelope": {
                "allowedVolumes": ["vol-1"],
                "excludedVolumes": [],
                "minAltitudeM": 5.0,
                "maxAltitudeM": 120.0,
            },
            "objectives": ["변화영역 재관측"],
            "viewpointPolicyId": "vp-1",
            "riskPolicyPackId": "risk-1",
            "fallbackPolicyId": "fb-1",
            "capturePolicyId": "cap-1",
            "assignedDeviceId": _DEVICE_ID,
        },
        "aoi": _rect_aoi(),
        "route": {
            "altitudeM": _BASELINE_ALTITUDE_M,
            "camera": {**_CAMERA, "frontOverlap": 0.3, "sideOverlap": 0.2},
        },
        "drone": {"droneEnumValue": 99, "droneSubEnumValue": 0, "payloadEnumValue": 65534},
        "wayline": {
            "autoFlightSpeedMs": 5.0,
            "takeoffSecurityHeightM": 20.0,
            "globalTransitionalSpeedMs": 10.0,
        },
    }

    rejected = client.post(
        "/v1/missions/plans", json=below_floor_request, headers=fixture.as_operator()
    )

    assert rejected.status_code == 422, rejected.text
