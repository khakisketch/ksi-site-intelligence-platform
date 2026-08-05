"""원본 사진 번들 입구 계약 (B1 — 3D 파이프라인 입구).

초점 셋:

1. **digest 는 Core 가 계산하고, 업로드 순서와 무관하다** — 클라이언트가 준 값을
   싣지 않는다(요청이 자기 증명서를 쓰지 못한다).
2. **봉인 후에는 거부한다** — typed verdict, 재생도 같은 게이트를 다시 태운다
   (journal 을 손으로 고쳐 봉인 상태·digest 를 위조할 수 없다).
3. **경로 탈출 mediaId 는 거부된다** — 객체 키는 서버가 만든다.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_core.source_media import (
    SourceBundleSealVerdict,
    SourceMediaBatchVerdict,
    SourceMediaClaim,
    SourceMediaItemVerdict,
    SourceMediaRecord,
    SourceMediaRecoveryError,
    SourceMediaStore,
    build_source_media_object_key,
    compute_source_bundle_digest,
)

_MISSION_ID = "mission-src-1"
_SITE_ID = "site-001"
_NOW = datetime(2026, 8, 5, 3, 0, tzinfo=UTC)

_ADMIN_TOKEN = "source-media-admin"  # noqa: S105 -- 테스트 고정값
_VIEWER_TOKEN = "source-media-viewer"  # noqa: S105


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _claim(
    media_id: str, *, seed: str | None = None, content_type: str = "image/jpeg"
) -> SourceMediaClaim:
    return SourceMediaClaim(
        media_id=media_id,
        sha256=_sha(seed or media_id),
        size_bytes=1_000_000,
        width=4000,
        height=3000,
        content_type=content_type,
    )


def _record(media_id: str, *, seed: str | None = None) -> SourceMediaRecord:
    claim = _claim(media_id, seed=seed)
    return SourceMediaRecord(
        media_id=claim.media_id,
        sha256=claim.sha256,
        size_bytes=claim.size_bytes,
        width=claim.width,
        height=claim.height,
        content_type=claim.content_type,
        object_key=f"sites/{_SITE_ID}/missions/{_MISSION_ID}/source/{media_id}",
        registered_at=_NOW,
        registered_by="op-1",
    )


def _mission_store(
    tmp_path: Path, *, site_id: str = _SITE_ID, path: str = "missions.jsonl"
) -> MissionStore:
    store = MissionStore(DurableJournal(tmp_path / path))
    assert (
        store.record_issuance(
            MissionRecord(
                mission_id=_MISSION_ID,
                site_id=site_id,
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
    return store


@pytest.fixture
def store(tmp_path: Path) -> SourceMediaStore:
    return SourceMediaStore(
        DurableJournal(tmp_path / "source-media.jsonl"), mission_store=_mission_store(tmp_path)
    )


# ── 객체 키 생성 (순수 함수) ────────────────────────────────────────────────


def test_object_key_is_built_from_validated_parts() -> None:
    key = build_source_media_object_key(site_id="site-1", mission_id="mission-1", media_id="a.jpg")
    assert key == "sites/site-1/missions/mission-1/source/a.jpg"


@pytest.mark.parametrize("bad_id", ["../evil.jpg", "a/b.jpg", ".hidden", "", "/etc/passwd"])
def test_path_escaping_media_id_is_refused_by_object_key_builder(bad_id: str) -> None:
    with pytest.raises(ValueError, match="mediaId"):
        build_source_media_object_key(site_id="site-1", mission_id="mission-1", media_id=bad_id)


# ── digest — 업로드 순서와 무관하다(핵심) ───────────────────────────────────


def test_digest_matches_the_processing_job_pattern() -> None:
    records = [_record(f"img-{i:03d}.jpg") for i in range(5)]
    digest = compute_source_bundle_digest(_MISSION_ID, records)
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64


def test_digest_is_invariant_to_registration_order() -> None:
    """[핵심] 같은 파일 집합을 다른 순서로 매니페스트에 넣어도 같은 digest 다."""
    records = [_record(f"img-{i:03d}.jpg") for i in range(7)]
    forward = compute_source_bundle_digest(_MISSION_ID, records)
    backward = compute_source_bundle_digest(_MISSION_ID, list(reversed(records)))
    shuffled_order = [records[i] for i in (3, 0, 6, 1, 5, 2, 4)]
    shuffled = compute_source_bundle_digest(_MISSION_ID, shuffled_order)
    assert forward == backward == shuffled


def test_digest_changes_if_any_file_content_differs() -> None:
    records_a = [_record("img-1.jpg", seed="content-a")]
    records_b = [_record("img-1.jpg", seed="content-b")]
    assert compute_source_bundle_digest(_MISSION_ID, records_a) != compute_source_bundle_digest(
        _MISSION_ID, records_b
    )


def test_batch_register_then_seal_produces_valid_digest(store: SourceMediaStore) -> None:
    """[수용기준 1] 200장 이상을 등록·봉인하면 sourceBundleDigest 가 패턴을 만족한다."""
    claims = [_claim(f"img-{i:04d}.jpg") for i in range(220)]
    result = store.register_batch(_MISSION_ID, claims, registered_by="op-1", now=_NOW)
    assert result.verdict is SourceMediaBatchVerdict.PROCESSED
    assert all(item.verdict is SourceMediaItemVerdict.REGISTERED for item in result.items)

    seal = store.seal(_MISSION_ID, sealed_by="op-1", now=_NOW)
    assert seal.verdict is SourceBundleSealVerdict.SEALED
    assert seal.bundle is not None
    assert seal.bundle.media_count if hasattr(seal.bundle, "media_count") else len(
        seal.bundle.media
    ) == 220
    assert seal.bundle.source_bundle_digest is not None
    assert seal.bundle.source_bundle_digest.startswith("sha256:")


def test_client_supplied_digest_is_ignored_by_construction(store: SourceMediaStore) -> None:
    """claim 에는 digest 를 실을 자리가 아예 없다 — Core 가 매니페스트에서 계산한다."""
    claims = [_claim("img-1.jpg")]
    store.register_batch(_MISSION_ID, claims, registered_by="op-1", now=_NOW)
    seal = store.seal(_MISSION_ID, sealed_by="op-1", now=_NOW)
    assert seal.bundle is not None
    expected = compute_source_bundle_digest(_MISSION_ID, seal.bundle.media)
    assert seal.bundle.source_bundle_digest == expected


# ── 등록 판정 ───────────────────────────────────────────────────────────────


def test_unknown_mission_is_rejected(store: SourceMediaStore) -> None:
    result = store.register_batch(
        "mission-never-issued", [_claim("img-1.jpg")], registered_by="op-1", now=_NOW
    )
    assert result.verdict is SourceMediaBatchVerdict.UNKNOWN_MISSION


@pytest.mark.parametrize("bad_id", ["../evil.jpg", "a/b.jpg", ".hidden"])
def test_path_escaping_media_id_is_refused_at_registration(
    store: SourceMediaStore, bad_id: str
) -> None:
    """[수용기준 4] 경로 탈출 문자열이 든 mediaId 가 거부된다."""
    result = store.register_batch(_MISSION_ID, [_claim(bad_id)], registered_by="op-1", now=_NOW)
    assert result.verdict is SourceMediaBatchVerdict.PROCESSED
    assert result.items[0].verdict is SourceMediaItemVerdict.INVALID_MEDIA_ID


def test_unsupported_content_type_is_rejected(store: SourceMediaStore) -> None:
    result = store.register_batch(
        _MISSION_ID, [_claim("img-1.jpg", content_type="text/html")], registered_by="op-1", now=_NOW
    )
    assert result.items[0].verdict is SourceMediaItemVerdict.UNSUPPORTED_CONTENT_TYPE


def test_same_claim_resubmitted_is_idempotent_reissue(store: SourceMediaStore) -> None:
    claim = _claim("img-1.jpg")
    first = store.register_batch(_MISSION_ID, [claim], registered_by="op-1", now=_NOW)
    second = store.register_batch(_MISSION_ID, [claim], registered_by="op-1", now=_NOW)
    assert first.items[0].verdict is SourceMediaItemVerdict.REGISTERED
    assert second.items[0].verdict is SourceMediaItemVerdict.REGISTERED
    assert first.items[0].object_key == second.items[0].object_key
    bundle = store.get(_MISSION_ID)
    assert bundle is not None
    assert len(bundle.media) == 1, "같은 claim 재전송이 중복 등록을 만들었다"


def test_different_claim_same_media_id_is_conflict(store: SourceMediaStore) -> None:
    store.register_batch(
        _MISSION_ID, [_claim("img-1.jpg", seed="a")], registered_by="op-1", now=_NOW
    )
    result = store.register_batch(
        _MISSION_ID, [_claim("img-1.jpg", seed="b")], registered_by="op-1", now=_NOW
    )
    assert result.items[0].verdict is SourceMediaItemVerdict.CLAIM_CONFLICT


def test_one_bad_item_does_not_block_the_rest_of_the_batch(store: SourceMediaStore) -> None:
    claims = [_claim("good-1.jpg"), _claim("../evil.jpg"), _claim("good-2.jpg")]
    result = store.register_batch(_MISSION_ID, claims, registered_by="op-1", now=_NOW)
    verdicts = [item.verdict for item in result.items]
    assert verdicts == [
        SourceMediaItemVerdict.REGISTERED,
        SourceMediaItemVerdict.INVALID_MEDIA_ID,
        SourceMediaItemVerdict.REGISTERED,
    ]


# ── 봉인 ────────────────────────────────────────────────────────────────────


def test_empty_bundle_cannot_be_sealed(store: SourceMediaStore) -> None:
    result = store.seal(_MISSION_ID, sealed_by="op-1", now=_NOW)
    assert result.verdict is SourceBundleSealVerdict.EMPTY_BUNDLE


def test_seal_unknown_mission_is_rejected(store: SourceMediaStore) -> None:
    result = store.seal("mission-never-issued", sealed_by="op-1", now=_NOW)
    assert result.verdict is SourceBundleSealVerdict.UNKNOWN_MISSION


def test_sealing_twice_is_idempotent(store: SourceMediaStore) -> None:
    store.register_batch(_MISSION_ID, [_claim("img-1.jpg")], registered_by="op-1", now=_NOW)
    first = store.seal(_MISSION_ID, sealed_by="op-1", now=_NOW)
    second = store.seal(_MISSION_ID, sealed_by="op-1", now=_NOW)
    assert first.verdict is SourceBundleSealVerdict.SEALED
    assert second.verdict is SourceBundleSealVerdict.ALREADY_SEALED
    assert first.bundle is not None and second.bundle is not None
    assert first.bundle.source_bundle_digest == second.bundle.source_bundle_digest


def test_registration_after_seal_is_refused(store: SourceMediaStore) -> None:
    """[수용기준 3] 봉인 후 추가 업로드가 거부된다."""
    store.register_batch(_MISSION_ID, [_claim("img-1.jpg")], registered_by="op-1", now=_NOW)
    store.seal(_MISSION_ID, sealed_by="op-1", now=_NOW)
    result = store.register_batch(
        _MISSION_ID, [_claim("img-2.jpg")], registered_by="op-1", now=_NOW
    )
    assert result.verdict is SourceMediaBatchVerdict.BUNDLE_SEALED
    bundle = store.get(_MISSION_ID)
    assert bundle is not None
    assert len(bundle.media) == 1, "봉인 후 등록이 실제로 추가됐다"


# ── 영속·재생 ───────────────────────────────────────────────────────────────


def test_replay_restores_bundle_state(tmp_path: Path) -> None:
    mission_store = _mission_store(tmp_path)
    journal = DurableJournal(tmp_path / "source-media.jsonl")
    store = SourceMediaStore(journal, mission_store=mission_store)
    store.register_batch(
        _MISSION_ID, [_claim("img-1.jpg"), _claim("img-2.jpg")], registered_by="op-1", now=_NOW
    )
    sealed = store.seal(_MISSION_ID, sealed_by="op-1", now=_NOW)
    journal.close()

    reborn_journal = DurableJournal(tmp_path / "source-media.jsonl")
    reborn = SourceMediaStore(
        reborn_journal, mission_store=MissionStore(DurableJournal(tmp_path / "missions2.jsonl"))
    )
    try:
        bundle = reborn.get(_MISSION_ID)
        assert bundle is not None
        assert len(bundle.media) == 2
        assert bundle.is_sealed
        assert sealed.bundle is not None
        assert bundle.source_bundle_digest == sealed.bundle.source_bundle_digest
    finally:
        reborn_journal.close()


def test_replay_rejects_seal_with_tampered_digest(tmp_path: Path) -> None:
    """[핵심] journal 조작으로 매니페스트와 어긋난 digest 를 봉인 상태로 위조할 수 없다."""
    seed = DurableJournal(tmp_path / "source-media.jsonl")
    seed.append(
        {
            "kind": "source-media-registered",
            "ts": _NOW.isoformat(),
            "missionId": _MISSION_ID,
            "siteId": _SITE_ID,
            "mediaId": "img-1.jpg",
            "objectKey": f"sites/{_SITE_ID}/missions/{_MISSION_ID}/source/img-1.jpg",
            "sha256": _sha("img-1.jpg"),
            "bytes": 1_000_000,
            "width": 4000,
            "height": 3000,
            "contentType": "image/jpeg",
            "registeredBy": "op-1",
        }
    )
    seed.append(
        {
            "kind": "source-media-sealed",
            "ts": _NOW.isoformat(),
            "missionId": _MISSION_ID,
            "sourceBundleDigest": "sha256:" + "0" * 64,  # 조작된 digest — 매니페스트와 무관
            "mediaCount": 1,
            "sealedBy": "op-1",
        }
    )
    seed.close()

    with pytest.raises(SourceMediaRecoveryError, match="digest"):
        SourceMediaStore(
            DurableJournal(tmp_path / "source-media.jsonl"), mission_store=_mission_store(tmp_path)
        )


def test_replay_rejects_registration_after_sealed_record(tmp_path: Path) -> None:
    records = [_record("img-1.jpg")]
    digest = compute_source_bundle_digest(_MISSION_ID, records)
    seed = DurableJournal(tmp_path / "source-media.jsonl")
    seed.append(
        {
            "kind": "source-media-registered",
            "ts": _NOW.isoformat(),
            "missionId": _MISSION_ID,
            "siteId": _SITE_ID,
            "mediaId": "img-1.jpg",
            "objectKey": records[0].object_key,
            "sha256": records[0].sha256,
            "bytes": records[0].size_bytes,
            "width": records[0].width,
            "height": records[0].height,
            "contentType": records[0].content_type,
            "registeredBy": "op-1",
        }
    )
    seed.append(
        {
            "kind": "source-media-sealed",
            "ts": _NOW.isoformat(),
            "missionId": _MISSION_ID,
            "sourceBundleDigest": digest,
            "mediaCount": 1,
            "sealedBy": "op-1",
        }
    )
    seed.append(
        {
            "kind": "source-media-registered",
            "ts": _NOW.isoformat(),
            "missionId": _MISSION_ID,
            "siteId": _SITE_ID,
            "mediaId": "img-2.jpg",
            "objectKey": f"sites/{_SITE_ID}/missions/{_MISSION_ID}/source/img-2.jpg",
            "sha256": _sha("img-2.jpg"),
            "bytes": 1,
            "width": 1,
            "height": 1,
            "contentType": "image/jpeg",
            "registeredBy": "op-1",
        }
    )
    seed.close()

    with pytest.raises(SourceMediaRecoveryError, match="봉인"):
        SourceMediaStore(
            DurableJournal(tmp_path / "source-media.jsonl"), mission_store=_mission_store(tmp_path)
        )


def test_status_maps_cover_every_verdict() -> None:
    """새 verdict 를 추가하고 상태코드를 빠뜨리는 경로를 막는다(다른 라우터 관습)."""
    from ksi_core.source_media import _BATCH_STATUS, _SEAL_STATUS

    assert set(_BATCH_STATUS) == set(SourceMediaBatchVerdict)
    assert set(_SEAL_STATUS) == set(SourceBundleSealVerdict)


# ── HTTP 표면 ──────────────────────────────────────────────────────────────


class FakeStorage:
    """가짜 오브젝트 스토리지 — 포트 계약만 만족한다(네트워크·컨테이너 없이)."""

    def __init__(self) -> None:
        self.put_calls: list[tuple[str, str]] = []
        self.fail_with: Exception | None = None

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        del ttl
        if self.fail_with is not None:
            raise self.fail_with
        self.put_calls.append((object_key, content_type))
        return f"https://storage.invalid/{object_key}?upload=1"

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        raise NotImplementedError

    def delete(self, object_key: str) -> None:
        raise NotImplementedError


def _digest_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest_token(_ADMIN_TOKEN),
                principal=Principal(
                    principal_id="op-admin",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest_token(_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="op-viewer",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                ),
            ),
        ]
    )


def _client(tmp_path: Path, *, storage: FakeStorage | None) -> TestClient:
    mission_store = _mission_store(tmp_path, path="http-missions.jsonl")
    source_media_store = SourceMediaStore(
        DurableJournal(tmp_path / "http-source-media.jsonl"), mission_store=mission_store
    )
    app = create_app(
        auth_registry=_auth_registry(),
        mission_store=mission_store,
        evidence_storage=storage,
        source_media_store=source_media_store,
        mission_signing_key=None,
    )
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})
    return client


def _file_payload(media_id: str, *, seed: str | None = None) -> dict[str, Any]:
    return {
        "mediaId": media_id,
        "sha256": _sha(seed or media_id),
        "bytes": 1_000_000,
        "width": 4000,
        "height": 3000,
        "contentType": "image/jpeg",
    }


def test_register_then_seal_over_http(tmp_path: Path) -> None:
    storage = FakeStorage()
    client = _client(tmp_path, storage=storage)

    register = client.post(
        f"/v1/missions/{_MISSION_ID}/source-media",
        json={"files": [_file_payload("img-1.jpg"), _file_payload("img-2.jpg")]},
    )
    assert register.status_code == 201, register.text
    body = register.json()
    assert body["verdict"] == "PROCESSED"
    assert len(body["results"]) == 2
    for item in body["results"]:
        assert item["verdict"] == "REGISTERED"
        assert item["uploadUrl"].startswith("https://storage.invalid/")
        expected_key = f"sites/{_SITE_ID}/missions/{_MISSION_ID}/source/{item['mediaId']}"
        assert item["objectKey"] == expected_key
    assert len(storage.put_calls) == 2

    status_before_seal = client.get(f"/v1/missions/{_MISSION_ID}/source-media")
    assert status_before_seal.status_code == 200
    assert status_before_seal.json()["status"] == "OPEN"
    assert status_before_seal.json()["sourceBundleDigest"] is None
    assert status_before_seal.json()["verifiedAt"] is None

    seal = client.post(f"/v1/missions/{_MISSION_ID}/source-media/seal")
    assert seal.status_code == 201, seal.text
    seal_body = seal.json()
    assert seal_body["verdict"] == "SEALED"
    assert seal_body["bundle"]["status"] == "SEALED"
    assert seal_body["bundle"]["mediaCount"] == 2
    assert seal_body["bundle"]["sourceBundleDigest"].startswith("sha256:")
    assert seal_body["bundle"]["verifiedAt"] is None

    status_after_seal = client.get(f"/v1/missions/{_MISSION_ID}/source-media")
    assert status_after_seal.json()["status"] == "SEALED"

    reupload = client.post(
        f"/v1/missions/{_MISSION_ID}/source-media", json={"files": [_file_payload("img-3.jpg")]}
    )
    assert reupload.status_code == 409
    assert reupload.json()["verdict"] == "BUNDLE_SEALED"


def test_viewer_cannot_register_or_seal(tmp_path: Path) -> None:
    client = _client(tmp_path, storage=FakeStorage())
    headers = {"Authorization": f"Bearer {_VIEWER_TOKEN}"}
    register = client.post(
        f"/v1/missions/{_MISSION_ID}/source-media",
        json={"files": [_file_payload("img-1.jpg")]},
        headers=headers,
    )
    assert register.status_code == 403
    seal = client.post(f"/v1/missions/{_MISSION_ID}/source-media/seal", headers=headers)
    assert seal.status_code == 403


def test_viewer_can_read_status(tmp_path: Path) -> None:
    client = _client(tmp_path, storage=FakeStorage())
    client.post(
        f"/v1/missions/{_MISSION_ID}/source-media", json={"files": [_file_payload("img-1.jpg")]}
    )
    response = client.get(
        f"/v1/missions/{_MISSION_ID}/source-media",
        headers={"Authorization": f"Bearer {_VIEWER_TOKEN}"},
    )
    assert response.status_code == 200


def test_status_for_unknown_bundle_is_404(tmp_path: Path) -> None:
    client = _client(tmp_path, storage=FakeStorage())
    response = client.get(f"/v1/missions/{_MISSION_ID}/source-media")
    assert response.status_code == 404


def test_storage_failure_degrades_item_but_keeps_registration(tmp_path: Path) -> None:
    storage = FakeStorage()
    from ksi_core.evidence import EvidenceStorageError

    storage.fail_with = EvidenceStorageError("연결 실패")
    client = _client(tmp_path, storage=storage)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/source-media", json={"files": [_file_payload("img-1.jpg")]}
    )
    assert response.status_code == 201, response.text
    item = response.json()["results"][0]
    assert item["verdict"] == "STORAGE_UNAVAILABLE"
    assert item["objectKey"] is not None
    assert item["uploadUrl"] is None


def test_routes_absent_without_storage(tmp_path: Path) -> None:
    """조립되지 않은 기능은 존재하지 않는 편이 정직하다."""
    client = _client(tmp_path, storage=None)
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/source-media", json={"files": [_file_payload("img-1.jpg")]}
    )
    assert response.status_code == 404


def test_source_media_store_without_mission_store_refuses_assembly() -> None:
    with pytest.raises(ValueError, match="mission_store"):
        create_app(
            auth_registry=_auth_registry(),
            evidence_storage=FakeStorage(),
            source_media_store=SourceMediaStore(
                DurableJournal(Path("/tmp/unused-source-media.jsonl")),  # noqa: S108 -- 조립만 시험, 실제 사용 안 함
                mission_store=MissionStore(DurableJournal(Path("/tmp/unused-missions.jsonl"))),  # noqa: S108
            ),
            mission_signing_key=None,
        )


@pytest.mark.parametrize("bad_id", ["../evil.jpg", "a/b.jpg", ".hidden"])
def test_path_escaping_media_id_is_refused_over_http(tmp_path: Path, bad_id: str) -> None:
    """[수용기준 4] HTTP 경로에서도 경로 탈출 mediaId 가 거부된다(항목 판정으로)."""
    client = _client(tmp_path, storage=FakeStorage())
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/source-media", json={"files": [_file_payload(bad_id)]}
    )
    assert response.status_code == 201
    assert response.json()["results"][0]["verdict"] == "INVALID_MEDIA_ID"


def test_batch_over_max_size_is_rejected_by_schema(tmp_path: Path) -> None:
    client = _client(tmp_path, storage=FakeStorage())
    files = [_file_payload(f"img-{i}.jpg") for i in range(201)]
    response = client.post(f"/v1/missions/{_MISSION_ID}/source-media", json={"files": files})
    assert response.status_code == 422
