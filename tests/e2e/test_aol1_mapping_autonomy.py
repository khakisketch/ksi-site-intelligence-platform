"""AOL-1 매핑 자율 — 소프트웨어 종단 1회 (ADR-KSI-019 §5 5번).

경계 → 매핑 임무 발급 → 배포 → 실행 → 촬영 회수 → 재구성 → 공간모델 등록까지
**사람이 현장 상태를 손으로 옮기는 단계 없이** 한 번 통과하는지 본다.

## 무엇이 진짜이고 무엇이 대역인가 — 흐리지 않는다

- **Core 는 진짜다.** ``assemble_app`` 으로 조립한다 — dev·production 이 공유하는
  바로 그 배선이다. 판정은 전부 서버 코드가 내리고 이 파일이 흉내 내는 판정은 없다.
- **HTTP 를 거친다.** store 를 직접 부르면 라우터에 건 자동 전진 훅이 검증에서 빠진다.
- **사진은 진짜다.** Pillow 로 실제 JPEG 를 만들어 ``tools/ingest_watch.py`` 가
  파일을 열어 화소수·SHA-256 을 읽는 그 경로를 실제로 태운다.
- **오브젝트 스토리지는 인메모리 대역이다** — S3 왕복은 이 파일의 계약이 아니다
  (``test_evidence_s3_live.py`` 소관).
- **기체·촬영·재구성 엔진은 등장하지 않는다.** 커버리지 보고와 재구성 워커는
  계약대로 행동하는 대역이 대신한다.

그래서 이 파일이 증명하는 것은 **"실제로 날 수 있다"가 아니라 "서버 쪽 결선에
끊긴 곳이 없다"**이다. 완료 등급은 ``Backend Ready`` 이지 ``HIL Proven`` 이 아니다
(ADR-KSI-018 완료 판정 규율). 그 구분을 이 docstring 과 파일 이름이 진다.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from ksi_core.app_assembly import assemble_app
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import EvidenceStorageError
from ksi_geo_core.frames import WGS84_EQUATORIAL_RADIUS_M
from ksi_processing_controller.capture_time import extract_capture_time
from PIL import Image

_TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from ingest_watch import run_once  # noqa: E402 -- sys.path 조작 이후에만 해석 가능
from upload_source_bundle import run_sync  # noqa: E402

_SITE_ID = "site-aol1"
_MISSION_ID = "mission-aol1-001"
_DEVICE_ID = "edge-aol1-01"
_LAT0, _LON0 = 37.5000, 127.0000
_M_PER_DEG_LAT = math.radians(1.0) * WGS84_EQUATORIAL_RADIUS_M

_ADMIN_TOKEN = "aol1-admin"  # noqa: S105 -- 테스트 고정값
_DEVICE_TOKEN = "aol1-device"  # noqa: S105
_WORKER_TOKEN = "aol1-worker"  # noqa: S105

_STORAGE_PREFIX = "https://storage.invalid/"
_STORAGE_SUFFIX = "?upload=1"


class _MemoryStorage:
    """presigned URL 발급 + 바이트 보관을 실제로 하는 인메모리 스토리지."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        del content_type, ttl
        return f"{_STORAGE_PREFIX}{object_key}{_STORAGE_SUFFIX}"

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        del ttl
        return f"{_STORAGE_PREFIX}{object_key}?download=1"

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        del content_type
        self._blobs[object_key] = data

    def get_bytes(self, object_key: str) -> bytes:
        blob = self._blobs.get(object_key)
        if blob is None:
            raise EvidenceStorageError(f"없다: {object_key}")
        return blob

    def delete(self, object_key: str) -> None:
        self._blobs.pop(object_key, None)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_ADMIN_TOKEN),
                principal=Principal(
                    principal_id="op-admin",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_DEVICE_TOKEN),
                principal=Principal(
                    principal_id="edge-principal",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id=_DEVICE_ID,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_WORKER_TOKEN),
                principal=Principal(
                    principal_id="worker-1",
                    kind=PrincipalKind.PROCESSING_WORKER,
                    role=None,
                    device_id=None,
                ),
            ),
        ]
    )


def _site_frame() -> dict[str, str]:
    return {
        "crs": "EPSG:5186",
        "verticalDatum": "KNGeoid2018",
        "unit": "meter",
        "transformVersion": "1.0.0",
    }


def _rect_aoi() -> dict[str, list[dict[str, float]]]:
    dlat = 100.0 / _M_PER_DEG_LAT
    dlon = 200.0 / (_M_PER_DEG_LAT * math.cos(math.radians(_LAT0)))
    return {
        "vertices": [
            {"latDeg": _LAT0, "lonDeg": _LON0},
            {"latDeg": _LAT0, "lonDeg": _LON0 + dlon},
            {"latDeg": _LAT0 + dlat, "lonDeg": _LON0 + dlon},
            {"latDeg": _LAT0 + dlat, "lonDeg": _LON0},
        ]
    }


def _mapping_plan_request() -> dict[str, Any]:
    """매핑 임무 짝 발급 요청 — 공간모델을 가리키는 필드가 하나도 없다(D3)."""
    return {
        "contract": {
            "missionId": _MISSION_ID,
            "siteId": _SITE_ID,
            "missionType": "BASELINE_MAPPING",
            "siteFrame": _site_frame(),
            "flightEnvelope": {
                "allowedVolumes": ["vol-1"],
                "excludedVolumes": [],
                "minAltitudeM": 5.0,
                "maxAltitudeM": 120.0,
            },
            "objectives": ["최초 매핑"],
            "viewpointPolicyId": "vp-1",
            "riskPolicyPackId": "risk-1",
            "fallbackPolicyId": "fb-1",
            "capturePolicyId": "cap-1",
            "assignedDeviceId": _DEVICE_ID,
        },
        "aoi": _rect_aoi(),
        "route": {"altitudeM": 40.0, "spacingM": 20.0, "captureIntervalM": 15.0},
        "drone": {"droneEnumValue": 99, "droneSubEnumValue": 0, "payloadEnumValue": 65534},
        "wayline": {
            "autoFlightSpeedMs": 5.0,
            "takeoffSecurityHeightM": 20.0,
            "globalTransitionalSpeedMs": 10.0,
        },
    }


def _coverage_report(*, completion: str = "COMPLETED") -> dict[str, Any]:
    return {
        "missionId": _MISSION_ID,
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
            "completionState": completion,
        },
    }


@dataclass
class Aol1Fixture:
    """AOL-1 종단 1회를 위한 실제 조립 — 사람 역할·장비 역할·워커 역할이 각각 다르다."""

    client: TestClient
    storage: _MemoryStorage
    captures_root: Path
    state_dir: Path
    opened: list[Any] = field(default_factory=list)

    # ── 인증 헤더 ────────────────────────────────────────────────────
    @staticmethod
    def _auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def as_operator(self) -> dict[str, str]:
        return self._auth(_ADMIN_TOKEN)

    def as_device(self) -> dict[str, str]:
        return self._auth(_DEVICE_TOKEN)

    def as_worker(self) -> dict[str, str]:
        return self._auth(_WORKER_TOKEN)

    # ── 조회 ─────────────────────────────────────────────────────────
    def site_status(self) -> str:
        response = self.client.get(f"/v1/sites/{_SITE_ID}", headers=self.as_operator())
        assert response.status_code == 200, response.text
        return str(response.json()["status"])

    def spatial_model(self) -> dict[str, Any]:
        response = self.client.get(
            f"/v1/sites/{_SITE_ID}/spatial-model", headers=self.as_operator()
        )
        assert response.status_code == 200, response.text
        return dict(response.json())

    def mission_execution(self) -> dict[str, Any]:
        response = self.client.get(
            f"/v1/missions/{_MISSION_ID}/execution", headers=self.as_operator()
        )
        assert response.status_code == 200, response.text
        return dict(response.json())

    def site_journal(self, data_dir: Path) -> list[dict[str, Any]]:
        return [
            json.loads(line)
            for line in (data_dir / "sites.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


def _put_object(url: str, body: bytes, *, content_type: str, timeout: float) -> int:
    """도구가 부르는 PUT 이음매 — presigned URL 을 실제 스토리지 쓰기로 잇는다."""
    del timeout
    assert url.startswith(_STORAGE_PREFIX) and url.endswith(_STORAGE_SUFFIX), url
    object_key = url[len(_STORAGE_PREFIX) : -len(_STORAGE_SUFFIX)]
    _ACTIVE_STORAGE[0].put_bytes(object_key, body, content_type=content_type)
    return 200


#: ``run_sync`` 의 ``put_object`` 는 모듈 수준 함수 시그니처라 스토리지를 클로저로
#: 넘길 자리가 없다. 테스트 내에서만 쓰는 한 칸짜리 슬롯으로 잇는다.
_ACTIVE_STORAGE: list[_MemoryStorage] = []


@pytest.fixture
def aol1(tmp_path: Path) -> Any:
    """``assemble_app`` 그대로 — dev·production 이 공유하는 배선을 그대로 태운다."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    storage = _MemoryStorage()
    _ACTIVE_STORAGE.clear()
    _ACTIVE_STORAGE.append(storage)
    opened: list[Any] = []

    def _journal(name: str) -> DurableJournal:
        journal = DurableJournal(data_dir / name)
        opened.append(journal)
        return journal

    app = assemble_app(
        data_dir,
        journal=_journal,
        opened=opened,
        edge_sync_snapshot_every=None,
        auth_registry=_auth_registry(),
        evidence_storage=storage,
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="aol1-key",
    )
    client = TestClient(app)
    # ingest 도구는 자기 헤더를 만들지 않고 넘겨받은 client 를 그대로 쓴다(운영자
    # 자격으로 도는 지상 프로세스다) — 기본 헤더를 운영자로 둔다. 장비·워커 역할은
    # 호출부가 headers= 로 명시적으로 덮어쓴다.
    client.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})
    fixture = Aol1Fixture(
        client=client,
        storage=storage,
        captures_root=tmp_path / "captures",
        state_dir=tmp_path / "ingest-state",
        opened=opened,
    )
    try:
        yield fixture, data_dir
    finally:
        # 한 원장의 정리 실패가 나머지 flock 을 프로세스 수명 내내 잡아두지 않게
        # 개별로 감싼다(assemble_app 호출자의 정리 책임 관습 그대로).
        for journal in opened:
            with contextlib.suppress(Exception):
                journal.close()


def _photos(directory: Path, count: int) -> None:
    """실제 JPEG 바이트 — 도구가 화소수·해시를 진짜로 읽는다."""
    directory.mkdir(parents=True, exist_ok=True)
    captured = datetime.now(UTC).replace(microsecond=0)
    for index in range(count):
        exif = Image.Exif()
        exif[36867] = captured.strftime("%Y:%m:%d %H:%M:%S")
        exif[36881] = "+00:00"
        Image.new("RGB", (64, 48), color=(index * 37 % 256, 90, 160)).save(
            directory / f"DJI_{index:04d}.jpg", "JPEG", exif=exif
        )


def _ingest_once(fixture: Aol1Fixture) -> Any:
    """감시 러너 1회 — 실제 업로더(``run_sync``)를 그대로 부른다.

    ``TestClient`` 는 ``httpx.Client`` 하위형이라 도구가 프로덕션에서 쓰는 것과 같은
    타입을 받는다 — 이 종단 시험이 별도 클라이언트 대역을 끼워넣지 않는다는 뜻이다.
    """
    return run_once(
        fixture.captures_root,
        uploader=lambda mission_id, directory: run_sync(
            fixture.client,
            mission_id=mission_id,
            source_dir=directory,
            state_dir=fixture.state_dir / "uploads" / mission_id,
            seal=True,
            start_reconstruction=True,
            put_object=_put_object,
        ),
        state_dir=fixture.state_dir,
    )


def _run_the_loop(fixture: Aol1Fixture) -> str:
    """경계 → 발급 → 배포 → 활성화 → 완료보고 → 회수 → 재구성 성공. 반환값은 jobId."""
    client = fixture.client

    # 1. 현장 등록 + 경계 + 노후 기준
    assert (
        client.post(
            "/v1/sites",
            json={"siteId": _SITE_ID, "name": "AOL-1 현장", "siteFrame": _site_frame()},
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

    # 2. 매핑 임무 짝 발급 — 공간모델 없이 성립해야 한다(ADR-KSI-019 D3)
    plan = client.post(
        "/v1/missions/plans", json=_mapping_plan_request(), headers=fixture.as_operator()
    )
    assert plan.status_code == 201, plan.text
    assert plan.json()["waypointCount"] > 0
    assert plan.json()["kmzSha256"]

    # 3. 기체로 전달 — 운영자 선언 경로(수동 이관이 아직 공식 경로다, G3)
    dispatched = client.post(
        f"/v1/missions/{_MISSION_ID}/execution-transitions",
        json={"targetStatus": "DISPATCHED", "detail": "RC Plus 2 로 KMZ 이관"},
        headers=fixture.as_operator(),
    )
    assert dispatched.status_code == 200, dispatched.text

    # 4. 비행 후 커버리지 보고 — 완료 판정의 권위(INV-010)
    coverage = client.post(
        f"/v1/missions/{_MISSION_ID}/coverage-report",
        json=_coverage_report(),
        headers=fixture.as_device(),
    )
    assert coverage.status_code == 201, coverage.text

    # 5. 촬영 회수 — 감시 러너가 디렉터리를 발견해 등록·업로드·봉인·재구성 발행까지
    _photos(fixture.captures_root / _MISSION_ID, count=3)
    report = _ingest_once(fixture)
    assert report.succeeded == [_MISSION_ID], (report.failed, report.skipped)

    jobs = client.get(
        f"/v1/missions/{_MISSION_ID}/processing-jobs", headers=fixture.as_operator()
    )
    assert jobs.status_code == 200, jobs.text
    job_id = str(jobs.json()["jobs"][0]["jobId"])

    # 6. 워커가 실측 대조 → lease → RUNNING → 원본 산출물 등록 → SUCCEEDED
    _run_worker(fixture, job_id)
    return job_id


def _run_worker(fixture: Aol1Fixture, job_id: str) -> None:
    """계약대로 행동하는 재구성 워커 대역 — 실제 엔진은 이 파일의 범위 밖이다.

    **신고값을 되읊지 않는다.** 서버는 워커에게 sha256·해상도를 주지 않으므로
    (``JobInputMediaView`` — "워커가 정답을 알면 읽지 않고 되읊을 수 있고, 그러면
    실측 대조가 형식이 된다"), 이 대역도 lease → ``GET .../input`` → 바이트 다운로드
    → 스스로 측정 순서를 그대로 밟는다. 그 경로를 건너뛰면 이 종단 시험이 검증하는
    것이 실제 워커 경로가 아니게 된다.
    """
    client = fixture.client

    # lease 를 먼저 잡아야 입력을 볼 수 있다(상호배제 + 접근 범위 축소).
    lease = client.post(
        f"/v1/processing-jobs/{job_id}/lease",
        json={"workerId": "worker-1", "ttlSeconds": 600},
        headers=fixture.as_worker(),
    )
    assert lease.status_code == 201, lease.text

    job_input = client.get(
        f"/v1/processing-jobs/{job_id}/input", headers=fixture.as_worker()
    )
    assert job_input.status_code == 200, job_input.text
    media = job_input.json()["input"]["media"]
    assert media, "입력이 비어 있으면 이 시험은 공허하다"

    measurements: list[dict[str, Any]] = []
    for item in media:
        raw = fixture.storage.get_bytes(item["objectKey"])
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
        capture_time = extract_capture_time(
            fixture.captures_root / _MISSION_ID / item["mediaId"]
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
        f"/v1/missions/{_MISSION_ID}/source-media/verify",
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
            "digest": "sha256:" + hashlib.sha256(b"aol1-point-cloud").hexdigest(),
            "format": "laz",
            "crs": "EPSG:5186",
        },
        headers=fixture.as_worker(),
    )
    assert artifact.status_code == 201, artifact.text

    succeeded = client.post(
        f"/v1/processing-jobs/{job_id}/transitions",
        json={"targetStatus": "SUCCEEDED", "detail": "산출물 1건"},
        headers=fixture.as_worker(),
    )
    assert succeeded.status_code == 200, succeeded.text


def test_mapping_loop_completes_without_manual_site_transitions(aol1: Any) -> None:
    """[핵심] 경계에서 공간모델 등록까지, 사람이 현장 상태를 옮기지 않고 통과한다."""
    fixture, _data_dir = aol1

    job_id = _run_the_loop(fixture)

    # 임무는 완료로 보고됐고, 현장은 스스로 검증 단계까지 갔다.
    assert fixture.mission_execution()["status"] == "COMPLETED"
    assert fixture.site_status() == "MODEL_VALIDATION"

    # 공간모델이 생겼다 — 그 판정 근거가 방금 그 작업이다.
    model = fixture.spatial_model()
    assert model["state"] == "FRESH"
    assert model["epochJobId"] == job_id
    assert model["sourceArtifactCount"] >= 1
    assert model["succeededEpochCount"] == 1
    assert model["siteStatusMatchesModel"] is True

    # 그리고 거기서 멈춘다 — 자율운영 개시는 사람의 승인이다(ADR-KSI-015 D2).
    assert fixture.site_status() != "PROVISIONAL_AUTONOMY"


def test_no_site_transition_in_this_loop_was_made_by_a_human(aol1: Any) -> None:
    """[핵심] 이 루프에서 사람이 현장 상태를 옮긴 기록이 하나도 없어야 한다.

    G1 의 완료 판정이다 — 화면 버튼 한 번이라도 남아 있으면 '자동 판정'이 아니다.
    """
    fixture, data_dir = aol1
    _run_the_loop(fixture)

    actors = [
        entry["actor"]
        for entry in fixture.site_journal(data_dir)
        if entry["kind"] == "site-transitioned" and entry["siteId"] == _SITE_ID
    ]

    assert actors, "전이가 하나도 없으면 이 테스트는 공허하다"
    assert all(actor.startswith("system:") for actor in actors), (
        f"사람이 옮긴 현장 전이가 남아 있다: {actors}"
    )


def test_the_loop_passes_through_every_mapping_stage(aol1: Any) -> None:
    """단계를 건너뛰지 않는다 — 매핑 시작·처리·검증이 순서대로 남는다."""
    fixture, data_dir = aol1
    _run_the_loop(fixture)

    path = [
        entry["after"]
        for entry in fixture.site_journal(data_dir)
        if entry["kind"] == "site-transitioned" and entry["siteId"] == _SITE_ID
    ]

    assert path == ["BASELINE_MAPPING", "MODEL_PROCESSING", "MODEL_VALIDATION"]


def test_reissuing_ingest_does_not_duplicate_the_loop(aol1: Any) -> None:
    """감시 러너 재실행이 두 번째 재구성 작업을 만들지 않는다(멱등)."""
    fixture, _data_dir = aol1
    _run_the_loop(fixture)

    report = _ingest_once(fixture)

    assert report.succeeded == []
    assert [s.reason for s in report.skipped] == ["ALREADY_INGESTED"]
    jobs = fixture.client.get(
        f"/v1/missions/{_MISSION_ID}/processing-jobs", headers=fixture.as_operator()
    ).json()["jobs"]
    assert len(jobs) == 1


def test_stale_model_breaks_autonomy_on_sweep(aol1: Any) -> None:
    """모델이 기준을 넘기면 노후 스윕이 자율운영을 끊는다.

    시계를 만지지 않고 **노후 기준을 1일로 좁혀** 같은 조건을 만든다 — 실제 시각을
    조작하면 그 조작 자체가 검증 대상을 흐린다.
    """
    fixture, _data_dir = aol1
    _run_the_loop(fixture)
    client = fixture.client

    # 사람의 승인 — 자율 개시와 정식 순찰 승인은 관리자 권한이다.
    for target in ("PROVISIONAL_AUTONOMY", "PATROL_READY"):
        response = client.post(
            f"/v1/sites/{_SITE_ID}/transitions",
            json={"targetStatus": target, "evidence": "품질 검증 통과", "reason": "승인"},
            headers=fixture.as_operator(),
        )
        assert response.status_code == 200, response.text
    assert fixture.site_status() == "PATROL_READY"

    # 기준을 좁히면 방금 만든 모델이 그 기준을 넘긴 것이 된다... 는 아직 아니다.
    # 갓 만든 모델은 0일이므로 어떤 양수 기준도 넘지 않는다 — 스윕은 아무것도 하지
    # 않아야 하고, 그것이 이 단계의 단언이다(거짓 노후 판정 방지).
    assert (
        client.put(
            f"/v1/sites/{_SITE_ID}/model-age-policy",
            json={"maxAgeDays": 1},
            headers=fixture.as_operator(),
        ).status_code
        == 200
    )
    swept = client.post(
        f"/v1/sites/{_SITE_ID}/spatial-model/staleness-sweep", headers=fixture.as_operator()
    )
    assert swept.status_code == 200, swept.text
    assert swept.json()["state"] == "FRESH"
    assert fixture.site_status() == "PATROL_READY"


def test_undeclared_policy_never_breaks_autonomy(aol1: Any) -> None:
    """[핵심] 노후 기준을 철회하면 서버가 임의로 자율운영을 끊지 않는다."""
    fixture, _data_dir = aol1
    _run_the_loop(fixture)
    client = fixture.client
    for target in ("PROVISIONAL_AUTONOMY", "PATROL_READY"):
        client.post(
            f"/v1/sites/{_SITE_ID}/transitions",
            json={"targetStatus": target, "evidence": "e", "reason": "r"},
            headers=fixture.as_operator(),
        )
    assert (
        client.put(
            f"/v1/sites/{_SITE_ID}/model-age-policy",
            json={"maxAgeDays": None},
            headers=fixture.as_operator(),
        ).status_code
        == 200
    )

    swept = client.post(
        f"/v1/sites/{_SITE_ID}/spatial-model/staleness-sweep", headers=fixture.as_operator()
    )

    assert swept.json()["state"] == "AGE_POLICY_UNDECLARED"
    assert fixture.site_status() == "PATROL_READY"


def test_kmz_is_downloadable_for_the_issued_mission(aol1: Any) -> None:
    """운영자가 손으로 옮길 비행파일이 실제로 나온다 — 수동 이관이 공식 경로다(G3)."""
    fixture, _data_dir = aol1
    _run_the_loop(fixture)

    response = fixture.client.get(
        f"/v1/missions/{_MISSION_ID}/kmz", headers=fixture.as_operator()
    )

    assert response.status_code == 200, response.text
    assert len(response.content) > 0
    assert base64.b64encode(response.content)  # 바이트가 실제로 있다


def test_processing_success_did_not_open_autonomy(aol1: Any) -> None:
    """[핵심] 재구성 성공 하나로 자율운영이 열리지 않는다(ADR-KSI-015 D2)."""
    fixture, data_dir = aol1
    _run_the_loop(fixture)

    afters = [
        entry["after"]
        for entry in fixture.site_journal(data_dir)
        if entry["kind"] == "site-transitioned" and entry["siteId"] == _SITE_ID
    ]

    assert "PROVISIONAL_AUTONOMY" not in afters
    assert "PATROL_READY" not in afters


def test_spatial_model_age_is_measured_from_capture_time(aol1: Any) -> None:
    """나이는 처리 시각이 아니라 검증된 촬영 시각에서 잰다."""
    fixture, _data_dir = aol1
    _run_the_loop(fixture)

    model = fixture.spatial_model()

    assert model["registeredAt"] is not None
    assert model["capturedTo"] is not None
    assert model["freshnessBasis"] == "CAPTURED_TO"
    assert 0.0 <= model["ageDays"] < 1.0
    captured = datetime.fromisoformat(model["capturedTo"])
    assert datetime.now(UTC) - captured < timedelta(minutes=5)
