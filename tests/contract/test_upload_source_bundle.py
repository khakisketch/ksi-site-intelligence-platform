"""자동 수집 종단 계약 (tools/upload_source_bundle.py) — **사람 손 업로드 0회**.

이 스위트가 고정하는 것은 하나다: *디렉터리에 사진이 놓이면, 브라우저도 사람의
클릭도 없이 서버 등록 → 바이트 업로드 → 번들 봉인 → 재구성 발행까지 간다.*
(ADR-KSI-018 P1 완료기준 "사람이 웹 화면에서 사진을 직접 선택해서 업로드하는
작업 0회".)

## 무엇이 진짜이고 무엇이 대역인가 — 흐리지 않는다

- **Core 는 진짜다.** ``create_app`` 으로 조립한 실제 FastAPI 앱을 TestClient 로
  두드린다. 등록·봉인·발행 판정은 전부 서버 코드가 내린다(이 테스트가 흉내 내는
  판정은 하나도 없다).
- **사진은 진짜다.** Pillow 로 실제 JPEG 바이트를 만든다 — 도구가 파일을 열어
  화소수를 읽고 SHA-256 을 계산하는 그 경로가 실제로 돈다.
- **오브젝트 스토리지는 인메모리 대역이다**(``_RecordingStorage``). presigned URL
  발급과 바이트 보관을 실제로 하되 프로세스 안에서 한다. 실제 S3/MinIO 왕복은
  이 스위트의 계약이 아니라 스토리지 계층의 계약이고, 그건
  ``test_evidence_s3_live.py`` 계열이 따로 고정한다.
- **드론·촬영은 전혀 등장하지 않는다.** 디렉터리를 채우는 주체(조종기 회수·
  SD카드 오프로드, ADR-KSI-013 D1/D2)는 실기 종속이라 여기서 흉내 내지 않는다 —
  이 도구의 계약은 "누군가 채워 놓으면 그 뒤"부터다.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import EvidenceStorageError
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_core.processing_jobs import ProcessingJobStore
from ksi_core.sites import SiteStore
from ksi_core.source_media import SourceMediaStore
from ksi_mission_contracts.models import SiteFrame
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from upload_source_bundle import (  # noqa: E402 -- 위 sys.path 조작 뒤에만 해석 가능
    RECONSTRUCTION_SPEC,
    SyncOutcome,
    load_confirmed,
    run_sync,
)

_MISSION_ID = "mission-auto-ingest-1"
_SITE_ID = "site-auto-ingest-001"
_NOW = datetime(2026, 8, 14, 6, 0, tzinfo=UTC)
_ADMIN_TOKEN = "auto-ingest-admin"  # noqa: S105 -- 테스트 고정값

_SITE_FRAME = SiteFrame(
    crs="EPSG:5186", vertical_datum="KNG2018", transform_version="v1", unit="meter"
)

_STORAGE_PREFIX = "https://storage.invalid/"
_STORAGE_SUFFIX = "?upload=1"


class _RecordingStorage:
    """presigned URL 발급 + 바이트 보관을 실제로 하는 인메모리 스토리지.

    ``test_source_media.FakeStorage`` 와 같은 포트 계약이되, 업로드된 바이트를
    보관해 이 스위트가 "올린 바이트가 파일과 같은가"를 실제로 대조할 수 있게 한다.
    """

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self.put_calls: list[tuple[str, str]] = []

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        del ttl
        self.put_calls.append((object_key, content_type))
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
        raise NotImplementedError


class _StorageUploads:
    """도구가 부르는 PUT 이음매 — presigned URL 을 실제 스토리지 쓰기로 잇는다.

    호출 횟수를 세는 이유는 **재실행이 바이트를 다시 올리지 않는다**는 것이 이
    스위트의 핵심 단언 중 하나이기 때문이다(확인 캐시의 존재 이유).
    """

    def __init__(self, storage: _RecordingStorage) -> None:
        self._storage = storage
        self.calls: list[tuple[str, int]] = []
        #: Core 인증 헤더가 스토리지로 새는지 감시한다(신뢰 경계 분리).
        self.seen_headers: list[dict[str, str]] = []

    def __call__(self, url: str, body: bytes, *, content_type: str, timeout: float) -> int:
        del timeout
        assert url.startswith(_STORAGE_PREFIX) and url.endswith(_STORAGE_SUFFIX), url
        object_key = url[len(_STORAGE_PREFIX) : -len(_STORAGE_SUFFIX)]
        self._storage.put_bytes(object_key, body, content_type=content_type)
        self.calls.append((object_key, len(body)))
        return 200


def _auth_registry() -> AuthRegistry:
    import hashlib

    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_ADMIN_TOKEN.encode("utf-8")).hexdigest(),
                principal=Principal(
                    principal_id="op-admin",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            )
        ]
    )


def _photos(directory: Path, count: int) -> list[Path]:
    """실제 JPEG 바이트를 만든다 — 도구가 화소수·해시를 진짜로 읽는다."""
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index in range(count):
        path = directory / f"DJI_{index:04d}.jpg"
        # 장마다 다른 색 — 바이트가 서로 달라 sha256 도 달라진다(같은 파일이
        # 여러 mediaId 로 중복 등록되는 것을 이 테스트가 못 잡는 상황을 막는다).
        Image.new("RGB", (64, 48), color=(index * 20 % 256, 100, 150)).save(path, "JPEG")
        paths.append(path)
    return paths


def _client(tmp_path: Path, storage: _RecordingStorage) -> TestClient:
    """실제 Core 조립 — 임무·현장·원본미디어·처리작업 저장소를 전부 붙인다."""
    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    assert (
        mission_store.record_issuance(
            MissionRecord(
                mission_id=_MISSION_ID,
                site_id=_SITE_ID,
                mission_type="BASELINE_MAPPING",
                artifact_kind="contract",
                contract={"schemaVersion": "1.2", "missionId": _MISSION_ID},
                kmz_sha256=None,
                route_pattern=None,
                waypoint_count=None,
                planned_coverage_ratio=None,
                issued_at=_NOW,
                issued_by="do-1",
            )
        ).value
        == "RECORDED"
    )
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    assert (
        site_store.register(
            _SITE_ID, "자동 수집 현장", _SITE_FRAME, data_residency=None, actor="op-1", now=_NOW
        ).verdict.value
        == "REGISTERED"
    )
    source_media_store = SourceMediaStore(
        DurableJournal(tmp_path / "source-media.jsonl"), mission_store=mission_store
    )
    app = create_app(
        auth_registry=_auth_registry(),
        mission_store=mission_store,
        site_store=site_store,
        evidence_storage=storage,
        source_media_store=source_media_store,
        processing_job_store=ProcessingJobStore(
            DurableJournal(tmp_path / "processing-jobs.jsonl"),
            source_media_store=source_media_store,
            site_store=site_store,
        ),
        mission_signing_key=None,
    )
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})
    return client


# ── 종단 증명 ────────────────────────────────────────────────────────────────


def test_directory_of_photos_reaches_reconstruction_with_no_human_step(tmp_path: Path) -> None:
    """[핵심] 디렉터리 → 등록 → 업로드 → 봉인 → 재구성 발행이 한 호출로 끝난다.

    이 테스트에 사람의 클릭·브라우저·파일 선택 대화상자가 등장하지 않는다는 것이
    증명 그 자체다 — ADR-KSI-018 P1 완료기준.
    """
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    photos = _photos(tmp_path / "photos", 5)
    state_dir = tmp_path / "state"

    outcome = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=state_dir,
        seal=True,
        start_reconstruction=True,
        put_object=_StorageUploads(storage),
    )

    assert outcome.failures == []
    assert outcome.discovered == 5
    assert outcome.uploaded == 5
    assert outcome.sealed is True
    assert outcome.source_bundle_digest is not None
    assert outcome.source_bundle_digest.startswith("sha256:")
    # 재구성이 실제로 발행됐다 — 사람이 "재구성 작업 발행" 버튼을 누르지 않았다.
    assert outcome.processing_job_id is not None

    # 서버가 본 번들도 같은 사실을 말한다(도구의 자기보고가 아니라 서버 조회).
    bundle = client.get(f"/v1/missions/{_MISSION_ID}/source-media").json()
    assert bundle["status"] == "SEALED"
    assert bundle["mediaCount"] == 5
    assert bundle["sourceBundleDigest"] == outcome.source_bundle_digest

    # 재구성 작업도 서버 원장에 실재한다 — 도구가 응답을 잘못 읽은 게 아니라
    # 실제로 발행됐고, 그 입력이 방금 봉인한 번들을 가리킨다.
    jobs = client.get(f"/v1/missions/{_MISSION_ID}/processing-jobs").json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["jobId"] == outcome.processing_job_id
    assert jobs[0]["status"] == "QUEUED"
    assert jobs[0]["contract"]["input"]["imageCount"] == 5
    assert jobs[0]["contract"]["input"]["sourceBundleDigest"] == outcome.source_bundle_digest

    # 올라간 바이트가 원본 파일과 **같다** — 등록만 되고 내용이 안 간 상태를 배제한다.
    for photo in photos:
        object_key = f"sites/{_SITE_ID}/missions/{_MISSION_ID}/source/{photo.name}"
        assert storage.get_bytes(object_key) == photo.read_bytes()


def test_nested_source_directory_is_discovered_like_sd_card_layout(tmp_path: Path) -> None:
    """SD카드 회수 레이아웃(``DCIM/100MEDIA/`` 하위)도 찾는다.

    ``_collect_files`` 가 ``source_dir.iterdir()``(비재귀)였을 때는 이 레이아웃에서
    발견 0장으로 떨어져 영구 재시도 실패가 됐다 —
    ``tests/contract/test_ingest_watch.py::test_finds_images_in_nested_directories``
    가 고정하는 것과 같은 레이아웃을, 같은 재귀 규칙(``rglob``)으로 여기서도 찾는다.
    """
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    nested_dir = tmp_path / "photos" / "DCIM" / "100MEDIA"
    nested_dir.mkdir(parents=True)
    Image.new("RGB", (64, 48), color=(10, 100, 150)).save(nested_dir / "DJI_0001.JPG", "JPEG")

    outcome = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        seal=True,
        put_object=_StorageUploads(storage),
    )

    assert outcome.discovered == 1
    assert outcome.uploaded == 1
    assert outcome.failures == []
    assert outcome.sealed is True


def test_rerun_uploads_no_bytes_again(tmp_path: Path) -> None:
    """[핵심] 같은 디렉터리로 다시 돌리면 바이트를 다시 올리지 않는다.

    확인 캐시의 존재 이유다. 정합성은 서버 멱등성이 이미 보장하므로(같은 신고값
    재전송 = 멱등 재발급), 이 단언이 지키는 것은 **일의 양**이다 — 수백 장 규모에서
    재시도가 전량 재업로드가 되면 운용이 성립하지 않는다.
    """
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    _photos(tmp_path / "photos", 3)
    state_dir = tmp_path / "state"

    uploads = _StorageUploads(storage)
    first = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=state_dir,
        put_object=uploads,
    )
    assert first.uploaded == 3
    assert len(uploads.calls) == 3

    second_uploads = _StorageUploads(storage)
    second = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=state_dir,
        put_object=second_uploads,
    )
    assert second.failures == []
    assert second.uploaded == 0
    assert second.skipped_already_uploaded == 3
    assert second_uploads.calls == []


def test_lost_cache_reuploads_and_still_succeeds(tmp_path: Path) -> None:
    """캐시를 잃으면 전량 재업로드가 되지만 **결과는 같다**(서버 멱등성).

    캐시가 정합성 장치가 아니라 속도 장치라는 것을 고정한다 — 캐시 파일이
    사라지거나 깨졌을 때 도구가 멈추거나 틀린 상태로 가지 않는다.
    """
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    _photos(tmp_path / "photos", 3)
    state_dir = tmp_path / "state"

    run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=state_dir,
        put_object=_StorageUploads(storage),
    )
    (state_dir / "uploaded.json").write_text("{ 깨진 json", encoding="utf-8")

    uploads = _StorageUploads(storage)
    outcome = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=state_dir,
        seal=True,
        put_object=uploads,
    )

    assert outcome.failures == []
    assert outcome.uploaded == 3  # 다시 올렸다
    assert len(uploads.calls) == 3
    assert outcome.sealed is True  # 그래도 봉인까지 정상 도달


def test_upload_failure_blocks_seal_and_reconstruction(tmp_path: Path) -> None:
    """[fail-closed] 한 장이라도 못 올리면 봉인하지 않고, 봉인 없이는 재구성도 없다.

    빠진 사진이 있는 채로 번들이 잠기면 그 위의 모든 계산이 조용히 틀린 입력을
    쓴다 — 이 순서가 그것을 막는 유일한 장치다.
    """
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    _photos(tmp_path / "photos", 3)

    def failing_put(url: str, body: bytes, *, content_type: str, timeout: float) -> int:
        del url, body, content_type, timeout
        return 500

    outcome = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        seal=True,
        start_reconstruction=True,
        put_object=failing_put,
    )

    assert outcome.uploaded == 0
    assert len(outcome.failures) == 3
    assert outcome.sealed is False
    assert outcome.processing_job_id is None
    # 서버 번들도 봉인되지 않았다 — 도구가 자기 상태만 그렇게 적은 게 아니다.
    assert client.get(f"/v1/missions/{_MISSION_ID}/source-media").json()["status"] == "OPEN"


def test_changed_file_under_same_name_is_refused_not_silently_accepted(tmp_path: Path) -> None:
    """같은 파일명으로 내용이 바뀌면 서버가 거부하고, 도구는 그것을 실패로 올린다.

    조용히 넘어가면 번들 digest 가 가리키는 내용과 실제 바이트가 갈린다.
    """
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    photos = _photos(tmp_path / "photos", 1)
    state_dir = tmp_path / "state"

    run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=state_dir,
        put_object=_StorageUploads(storage),
    )

    # 같은 이름, 다른 내용으로 교체한다(회수 절차가 파일을 덮어썼다고 가정).
    Image.new("RGB", (80, 60), color=(9, 9, 9)).save(photos[0], "JPEG")

    outcome = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=state_dir,
        seal=True,
        put_object=_StorageUploads(storage),
    )

    assert outcome.failures, "내용이 바뀐 같은 이름 파일이 조용히 통과했다"
    assert any("CLAIM_CONFLICT" in failure for failure in outcome.failures)
    assert outcome.sealed is False


def test_rerun_after_full_success_is_success_not_failure(tmp_path: Path) -> None:
    """[핵심] 이미 다 끝난 뒤 같은 명령을 또 돌려도 **성공**이다.

    주기 실행(cron·supervisor)이 첫 성공 이후 영원히 실패로 뜨면, 운용자는 진짜
    실패와 구분할 수 없어 결국 알림을 꺼버린다 — 그 순간 자동화는 감시받지 않는
    상태가 된다. 실제 Core 상대 실행에서 실측으로 드러난 결함이다.
    """
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    _photos(tmp_path / "photos", 3)
    state_dir = tmp_path / "state"

    first = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=state_dir,
        seal=True,
        start_reconstruction=True,
        put_object=_StorageUploads(storage),
    )
    assert first.failures == []
    assert first.sealed is True

    uploads = _StorageUploads(storage)
    second = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=state_dir,
        seal=True,
        start_reconstruction=True,
        put_object=uploads,
    )

    assert second.failures == [], "이미 도달한 상태의 재실행이 실패로 보고됐다"
    assert second.already_complete is True
    assert uploads.calls == []
    assert second.sealed is True
    # 재구성도 중복 발행되지 않는다(같은 사양 재요청 = 기존 작업 반환).
    assert second.processing_job_id == first.processing_job_id
    assert len(client.get(f"/v1/missions/{_MISSION_ID}/processing-jobs").json()["jobs"]) == 1


def test_rerun_with_different_photo_count_stays_a_failure(tmp_path: Path) -> None:
    """봉인된 번들과 **장수가 다르면** 수렴이 아니라 실패다.

    "이미 봉인됨"을 무조건 성공으로 접으면, 다른 사진 묶음을 올리려는 시도가
    조용히 성공으로 보고된다 — 그 임무의 재구성은 엉뚱한 입력으로 이미 돌았는데
    운용자는 자기 사진이 반영됐다고 믿게 된다.
    """
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    _photos(tmp_path / "photos", 3)
    state_dir = tmp_path / "state"

    run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=state_dir,
        seal=True,
        put_object=_StorageUploads(storage),
    )

    # 사진 2장을 더 놓고 다시 돌린다 — 봉인된 번들(3장)과 장수가 다르다.
    _photos(tmp_path / "photos", 5)
    outcome = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=state_dir,
        seal=True,
        put_object=_StorageUploads(storage),
    )

    assert outcome.already_complete is False
    assert outcome.failures, "장수가 다른데도 수렴으로 접혔다"


def test_rerun_with_the_same_count_but_different_photos_stays_a_failure(tmp_path: Path) -> None:
    """[핵심] 장수가 같아도 **내용이 다르면** 수렴이 아니라 실패다.

    장수만 대조하면 이 경우가 조용히 "이미 완료"로 성공 보고된다 — 그 임무의 재구성은
    먼저 봉인된 다른 묶음으로 이미 돌았는데, 운용자는 방금 넣은 사진이 반영됐다고
    믿는다. 수렴 판정 기준이 mediaCount 가 아니라 sourceBundleDigest 여야 하는 이유다.
    """
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    photo_dir = tmp_path / "photos"
    _photos(photo_dir, 3)
    state_dir = tmp_path / "state"

    first = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=photo_dir,
        state_dir=state_dir,
        seal=True,
        put_object=_StorageUploads(storage),
    )
    assert first.sealed is True

    # 같은 3장이 아니라 **다른 3장**으로 갈아끼운다(장수는 그대로 3).
    for path in sorted(photo_dir.iterdir()):
        path.unlink()
    for index in range(3):
        Image.new("RGB", (64, 48), color=(7, index * 30 % 256, 200)).save(
            photo_dir / f"OTHER_{index:04d}.jpg", "JPEG"
        )

    outcome = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=photo_dir,
        state_dir=state_dir,
        seal=True,
        put_object=_StorageUploads(storage),
    )

    assert outcome.already_complete is False
    assert outcome.failures, "장수가 같은 다른 묶음인데도 수렴으로 접혔다"


def test_core_unreachable_is_a_reported_failure_not_a_crash(tmp_path: Path) -> None:
    """서버에 닿지 못해도 traceback 이 아니라 판정으로 낸다.

    현장 네트워크 두절은 예외 상황이 아니라 흔한 상태다(ADR-KSI-005 "오프라인이
    정상 동작"). 그때 도구가 스택트레이스로 죽으면 운용자는 무엇을 다시 하면
    되는지 알 수 없고, 재시도 절차도 자동화할 수 없다.
    """
    storage = _RecordingStorage()
    _photos(tmp_path / "photos", 2)

    # 아무도 듣지 않는 포트 — 실제 연결 거부를 일으킨다(예외를 흉내 내지 않는다).
    with httpx.Client(base_url="http://127.0.0.1:9", timeout=1.0) as offline_client:
        outcome = run_sync(
            offline_client,
            mission_id=_MISSION_ID,
            source_dir=tmp_path / "photos",
            seal=True,
            start_reconstruction=True,
            put_object=_StorageUploads(storage),
        )

    assert outcome.failures, "연결 실패가 조용히 성공으로 처리됐다"
    assert outcome.uploaded == 0
    assert outcome.sealed is False
    assert outcome.processing_job_id is None


def test_empty_directory_is_a_typed_failure_not_a_silent_success(tmp_path: Path) -> None:
    """사진이 0장이면 실패다 — "아무것도 안 했는데 성공"이 가장 위험한 답이다."""
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    (tmp_path / "photos").mkdir()

    outcome = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        seal=True,
        start_reconstruction=True,
        put_object=_StorageUploads(storage),
    )

    assert outcome.discovered == 0
    assert outcome.failures
    assert outcome.sealed is False
    assert outcome.processing_job_id is None


def test_confirmed_cache_is_written_atomically_and_readable(tmp_path: Path) -> None:
    """확인 캐시가 실제로 남고 다시 읽힌다 — 재실행 경로의 전제."""
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    _photos(tmp_path / "photos", 2)
    state_dir = tmp_path / "state"

    run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=state_dir,
        put_object=_StorageUploads(storage),
    )

    confirmed = load_confirmed(state_dir)
    assert set(confirmed) == {"DJI_0000.jpg", "DJI_0001.jpg"}
    assert all(len(sha) == 64 for sha in confirmed.values())
    # 임시 파일이 남지 않는다(원자적 교체).
    assert [p.name for p in state_dir.iterdir()] == ["uploaded.json"]


def test_reconstruction_spec_matches_the_dashboard(tmp_path: Path) -> None:
    """자동 경로와 사람 경로가 **같은 사양**으로 재구성한다.

    두 경로가 다른 엔진·다른 파라미터로 돌면 나중에 그 산출물을 같은 기준으로
    비교할 수 없다. 대시보드 쪽 상수(SourceUploadPanel.tsx RECONSTRUCTION_SPEC)와
    글자 단위로 맞춘다 — 한쪽만 바뀌면 이 테스트가 깨진다.
    """
    del tmp_path
    dashboard_source = (
        Path(__file__).resolve().parents[2]
        / "apps/dashboard/src/components/missions/SourceUploadPanel.tsx"
    ).read_text(encoding="utf-8")

    assert RECONSTRUCTION_SPEC == {"processingProfileId": "ksi-odm-civil-v1"}
    assert 'KSI_STANDARD_PROCESSING_PROFILE_ID = "ksi-odm-civil-v1"' in dashboard_source
    assert "processingProfileId: KSI_STANDARD_PROCESSING_PROFILE_ID" in dashboard_source


@pytest.mark.parametrize("seal", [False, True])
def test_reconstruction_is_never_issued_without_seal(tmp_path: Path, seal: bool) -> None:
    """봉인 없이는 재구성이 발행되지 않는다 — 장수·digest 가 확정되기 전 계산 금지."""
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    _photos(tmp_path / "photos", 2)

    outcome = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        seal=seal,
        start_reconstruction=True,
        put_object=_StorageUploads(storage),
    )

    assert outcome.sealed is seal
    assert (outcome.processing_job_id is not None) is seal


# ── 지상 기준점(GCP) — 조사가 비교 가능해지려면 붙어야 하는 파일 ──────────────
#
# 이 네 개가 없으면 `attach_ground_control` 은 아무도 부르지 않는 코드다. 특히
# **거부됐을 때 봉인되지 않는다**는 성질은 이 도구에만 있는 순서 규칙이라
# (Core 는 봉인 요청을 받으면 봉인한다) 여기서 고정하지 않으면 지켜질 근거가 없다.


def _gcp_file(directory: Path, crs: str = "EPSG:5186") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "gcp_list.txt"
    path.write_text(
        f"{crs}\n205123.456 521987.654 34.210 2648 2147 photo-0.jpg\n", encoding="utf-8"
    )
    return path


def test_ground_control_is_attached_before_sealing(tmp_path: Path) -> None:
    """붙고 나서 봉인된다 — 봉인 뒤에는 Core 가 받지 않으므로 순서가 곧 기능이다."""
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    _photos(tmp_path / "photos", 3)

    outcome = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=tmp_path / "state",
        seal=True,
        ground_control=_gcp_file(tmp_path / "gcp"),
        ground_control_crs="EPSG:5186",
        put_object=_StorageUploads(storage),
    )

    assert outcome.failures == []
    assert outcome.sealed is True
    # 도구의 자기보고가 아니라 서버가 본 사실로 확인한다.
    bundle = client.get(f"/v1/missions/{_MISSION_ID}/source-media").json()
    assert bundle["status"] == "SEALED"
    assert bundle["groundControlCrs"] == "EPSG:5186"


def test_refused_ground_control_leaves_the_bundle_unsealed(tmp_path: Path) -> None:
    """[핵심] 비교할 수 없는 조사를 잠그지 않는다.

    허용 목록 밖 좌표계(여기서는 실제로 부딪힌 UTM 17N)는 Core 가 거부한다. 그때
    봉인까지 진행하면 "재구성은 되는데 두 시점 비교는 영영 불가능한" 조사가
    확정된다 — 사진을 다시 찍는 것 말고는 되돌릴 방법이 없다.
    """
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    _photos(tmp_path / "photos", 3)

    outcome = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=tmp_path / "state",
        seal=True,
        start_reconstruction=True,
        ground_control=_gcp_file(tmp_path / "gcp", crs="EPSG:32617"),
        ground_control_crs="EPSG:32617",
        put_object=_StorageUploads(storage),
    )

    assert outcome.failures, "허용 목록 밖 좌표계인데 실패가 기록되지 않았다"
    assert any("UNSUPPORTED_CRS" in message for message in outcome.failures)
    assert outcome.sealed is False
    assert outcome.processing_job_id is None
    bundle = client.get(f"/v1/missions/{_MISSION_ID}/source-media").json()
    assert bundle["status"] == "OPEN"
    assert bundle["groundControlCrs"] is None


def test_ground_control_without_crs_is_refused_before_touching_the_server(
    tmp_path: Path,
) -> None:
    """좌표계 없는 기준점은 신고가 성립하지 않는다 — 봉인도 하지 않는다."""
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    _photos(tmp_path / "photos", 2)

    outcome = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=tmp_path / "state",
        seal=True,
        ground_control=_gcp_file(tmp_path / "gcp"),
        ground_control_crs=None,
        put_object=_StorageUploads(storage),
    )

    assert any("좌표계" in message for message in outcome.failures)
    assert outcome.sealed is False


def test_no_ground_control_keeps_the_previous_behaviour(tmp_path: Path) -> None:
    """기준점을 안 주면 기존 경로 그대로다 — 이 기능이 기존 조사를 막지 않는다."""
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    _photos(tmp_path / "photos", 3)

    outcome = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=tmp_path / "state",
        seal=True,
        start_reconstruction=True,
        put_object=_StorageUploads(storage),
    )

    assert outcome.failures == []
    assert outcome.sealed is True
    assert outcome.processing_job_id is not None
    assert client.get(f"/v1/missions/{_MISSION_ID}/source-media").json()["groundControlCrs"] is None


def test_rerunning_the_same_command_with_ground_control_is_not_a_failure(
    tmp_path: Path,
) -> None:
    """[핵심] 이 도구의 계약은 "재시도는 같은 명령을 다시 부르면 된다"이다.

    서버는 봉인된 번들의 기준점 등록을 BUNDLE_SEALED 로 거부하므로, 등록을 무조건
    부르면 **성공적으로 끝난 조사를 재실행할 때마다 실패로 끝난다**. FIELD-1 절차
    문서가 제시하는 명령이 정확히 이 형태라, 현장에서 가장 먼저 부딪히는 결함이
    됐을 것이다(독립 검토 2026-08-18 적발 → 이 테스트로 고정).
    """
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    _photos(tmp_path / "photos", 3)
    gcp = _gcp_file(tmp_path / "gcp")

    def _run() -> SyncOutcome:
        return run_sync(
            client,
            mission_id=_MISSION_ID,
            source_dir=tmp_path / "photos",
            state_dir=tmp_path / "state",
            seal=True,
            start_reconstruction=True,
            ground_control=gcp,
            ground_control_crs="EPSG:5186",
            put_object=_StorageUploads(storage),
        )

    first = _run()
    assert first.failures == []
    second = _run()
    assert second.failures == [], f"같은 명령의 재실행이 실패로 끝났다: {second.failures}"
    assert second.sealed is True


def test_sealed_bundle_with_a_different_ground_control_file_is_reported(
    tmp_path: Path,
) -> None:
    """재실행 관용이 **다른 기준점을 조용히 삼키는** 것으로 번지면 안 된다.

    이미 봉인된 조사에 다른 성과를 올리려는 것은 재시도가 아니라 착오다 — 그
    조사의 성과는 지금 올리려는 기준점으로 만들어진 것이 아니다.
    """
    storage = _RecordingStorage()
    client = _client(tmp_path, storage)
    _photos(tmp_path / "photos", 3)

    first = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=tmp_path / "state",
        seal=True,
        ground_control=_gcp_file(tmp_path / "gcp-a"),
        ground_control_crs="EPSG:5186",
        put_object=_StorageUploads(storage),
    )
    assert first.failures == []

    other = tmp_path / "gcp-b" / "gcp_list.txt"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text(
        "EPSG:5186\n999999.000 888888.000 12.000 100 100 photo-1.jpg\n", encoding="utf-8"
    )
    second = run_sync(
        client,
        mission_id=_MISSION_ID,
        source_dir=tmp_path / "photos",
        state_dir=tmp_path / "state",
        seal=True,
        ground_control=other,
        ground_control_crs="EPSG:5186",
        put_object=_StorageUploads(storage),
    )
    assert any("이미 봉인" in message for message in second.failures), second.failures
