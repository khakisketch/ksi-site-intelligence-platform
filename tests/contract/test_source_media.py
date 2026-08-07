"""원본 사진 번들 입구 계약 (B1 — 3D 파이프라인 입구).

초점 셋:

1. **digest 는 Core 가 계산하고, 업로드 순서와 무관하다** — 클라이언트가 준 값을
   싣지 않는다(요청이 자기 증명서를 쓰지 못한다).
2. **봉인 후에는 거부한다** — typed verdict, 재생도 같은 게이트를 다시 태운다
   (journal 을 손으로 고쳐 봉인 상태·digest 를 위조할 수 없다).
3. **경로 탈출 mediaId 는 거부된다** — 객체 키는 서버가 만든다.
4. **실측 대조의 판정은 Core 가 한다** — 워커는 잰 값만 보내고 "검증됨"을 보낼
   수 없다. 원장의 사실은 측정값이고 재생이 그걸로 **다시 대조**한다.
5. **부분 검증은 검증이 아니다** — 측정 집합이 등록 집합과 정확히 같아야 한다.
"""

from __future__ import annotations

import hashlib
import json
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
    SourceBundleVerifyVerdict,
    SourceMediaBatchVerdict,
    SourceMediaClaim,
    SourceMediaItemVerdict,
    SourceMediaMeasurement,
    SourceMediaRecord,
    SourceMediaRecoveryError,
    SourceMediaStore,
    build_source_media_object_key,
    compare_measurements,
    compute_source_bundle_digest,
)

_MISSION_ID = "mission-src-1"
_SITE_ID = "site-001"
_NOW = datetime(2026, 8, 5, 3, 0, tzinfo=UTC)

_ADMIN_TOKEN = "source-media-admin"  # noqa: S105 -- 테스트 고정값
_VIEWER_TOKEN = "source-media-viewer"  # noqa: S105
_WORKER_TOKEN = "source-media-worker"  # noqa: S105


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


# ── 실측 대조: 판정은 Core 가 한다 ──────────────────────────────────────────


def _measure(
    media_id: str, *, seed: str | None = None, width: int = 4000, height: int = 3000,
    size_bytes: int = 1_000_000,
) -> SourceMediaMeasurement:
    return SourceMediaMeasurement(
        media_id=media_id,
        sha256=_sha(seed or media_id),
        size_bytes=size_bytes,
        width=width,
        height=height,
    )


def _sealed(store: SourceMediaStore, *count_ids: str) -> None:
    ids = count_ids or ("img-1.jpg", "img-2.jpg")
    assert (
        store.register_batch(
            _MISSION_ID, [_claim(i) for i in ids], registered_by="op-1", now=_NOW
        ).verdict
        is SourceMediaBatchVerdict.PROCESSED
    )
    assert (
        store.seal(_MISSION_ID, sealed_by="op-1", now=_NOW).verdict
        is SourceBundleSealVerdict.SEALED
    )


def test_matching_measurements_verify_the_bundle(store: SourceMediaStore) -> None:
    _sealed(store)
    result = store.verify(
        _MISSION_ID,
        [_measure("img-1.jpg"), _measure("img-2.jpg")],
        verified_by="worker-1",
        now=_NOW,
    )
    assert result.verdict is SourceBundleVerifyVerdict.VERIFIED
    bundle = store.get(_MISSION_ID)
    assert bundle is not None
    assert bundle.is_verified
    assert bundle.verified_by == "worker-1"
    assert bundle.last_mismatch_at is None


@pytest.mark.parametrize(
    ("bad", "field"),
    [
        (_measure("img-2.jpg", seed="다른-파일"), "sha256"),
        (_measure("img-2.jpg", width=8000), "width"),
        (_measure("img-2.jpg", height=1), "height"),
        (_measure("img-2.jpg", size_bytes=42), "bytes"),
    ],
)
def test_any_field_mismatch_refuses_verification(
    store: SourceMediaStore, bad: SourceMediaMeasurement, field: str
) -> None:
    """[핵심] 네 필드 중 **하나라도** 어긋나면 검증이 아니다.

    해상도만 봐도 과금 근거(totalMegapixels)가 흔들리고, sha256 만 봐도
    파일 자체가 바뀐다 — 어느 하나를 느슨하게 둘 근거가 없다.
    """
    _sealed(store)
    result = store.verify(
        _MISSION_ID, [_measure("img-1.jpg"), bad], verified_by="worker-1", now=_NOW
    )
    assert result.verdict is SourceBundleVerifyVerdict.MISMATCH, field
    assert result.comparison is not None
    assert result.comparison.mismatched == ("img-2.jpg",)
    bundle = store.get(_MISSION_ID)
    assert bundle is not None
    # 불일치는 기록되지만 번들을 잠그지 않는다 — 오탐 복구 경로가 없으면 안 된다.
    assert not bundle.is_verified
    assert bundle.last_mismatch_at == _NOW


def test_partial_measurement_is_not_verification(store: SourceMediaStore) -> None:
    """[핵심] 일부만 읽고 '검증했다'가 되면 verifiedAt 이 뜻하는 바가 사라진다."""
    _sealed(store)
    result = store.verify(
        _MISSION_ID, [_measure("img-1.jpg")], verified_by="worker-1", now=_NOW
    )
    assert result.verdict is SourceBundleVerifyVerdict.COVERAGE_INCOMPLETE
    assert result.comparison is not None
    assert result.comparison.missing == ("img-2.jpg",)


def test_extra_and_duplicate_measurements_are_refused(store: SourceMediaStore) -> None:
    """등록되지 않은 파일·같은 파일 두 번은 둘 다 unexpected 다.

    중복을 막지 않으면 같은 파일을 여러 번 재서 대조를 흐릴 수 있다.
    """
    _sealed(store)
    duplicated = store.verify(
        _MISSION_ID,
        [_measure("img-1.jpg"), _measure("img-1.jpg"), _measure("img-2.jpg")],
        verified_by="worker-1",
        now=_NOW,
    )
    assert duplicated.verdict is SourceBundleVerifyVerdict.COVERAGE_INCOMPLETE
    assert duplicated.comparison is not None
    assert duplicated.comparison.unexpected == ("img-1.jpg",)

    unknown = store.verify(
        _MISSION_ID,
        [_measure("img-1.jpg"), _measure("img-2.jpg"), _measure("img-9.jpg")],
        verified_by="worker-1",
        now=_NOW,
    )
    assert unknown.verdict is SourceBundleVerifyVerdict.COVERAGE_INCOMPLETE
    assert unknown.comparison is not None
    assert unknown.comparison.unexpected == ("img-9.jpg",)


def test_unsealed_bundle_cannot_be_verified(store: SourceMediaStore) -> None:
    store.register_batch(_MISSION_ID, [_claim("img-1.jpg")], registered_by="op-1", now=_NOW)
    result = store.verify(
        _MISSION_ID, [_measure("img-1.jpg")], verified_by="worker-1", now=_NOW
    )
    assert result.verdict is SourceBundleVerifyVerdict.BUNDLE_NOT_SEALED


def test_reverification_is_idempotent(store: SourceMediaStore) -> None:
    _sealed(store)
    measurements = [_measure("img-1.jpg"), _measure("img-2.jpg")]
    store.verify(_MISSION_ID, measurements, verified_by="worker-1", now=_NOW)
    again = store.verify(_MISSION_ID, measurements, verified_by="worker-2", now=_NOW)
    assert again.verdict is SourceBundleVerifyVerdict.ALREADY_VERIFIED
    bundle = store.get(_MISSION_ID)
    assert bundle is not None
    assert bundle.verified_by == "worker-1", "첫 검증자가 유지된다"


def test_comparison_is_a_pure_shared_function() -> None:
    """live·재생이 함께 쓰는 판정 함수 자체의 계약."""
    media = [_record("a.jpg"), _record("b.jpg")]
    assert compare_measurements(media, [_measure("a.jpg"), _measure("b.jpg")]).is_match
    assert not compare_measurements(media, [_measure("a.jpg")]).is_match
    assert compare_measurements(media, [_measure("a.jpg")]).missing == ("b.jpg",)


# ── 재생이 검증 판정을 다시 매긴다 ──────────────────────────────────────────


def _verified_journal(tmp_path: Path, *, honest: bool = True) -> None:
    """봉인 + 검증까지 기록한 journal 을 만들고 핸들을 닫는다."""
    journal = DurableJournal(tmp_path / "source-media.jsonl")
    store = SourceMediaStore(journal, mission_store=_mission_store(tmp_path))
    _sealed(store)
    second = _measure("img-2.jpg") if honest else _measure("img-2.jpg", width=9999)
    store.verify(
        _MISSION_ID, [_measure("img-1.jpg"), second], verified_by="worker-1", now=_NOW
    )
    journal.close()


def _reborn(tmp_path: Path) -> tuple[SourceMediaStore, DurableJournal]:
    """재기동 시뮬레이션. journal 핸들을 함께 돌려준다(단일 writer 잠금 해제용)."""
    journal = DurableJournal(tmp_path / "source-media.jsonl")
    return (
        SourceMediaStore(
            journal, mission_store=_mission_store(tmp_path, path="replay-missions.jsonl")
        ),
        journal,
    )


def _rewrite(tmp_path: Path, mutate: Any) -> None:
    path = tmp_path / "source-media.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    mutate(records)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8"
    )


def test_replay_restores_verification(tmp_path: Path) -> None:
    """대조군 — 손대지 않은 원장은 그대로 복원된다(아래 거부들이 공허하지 않다)."""
    _verified_journal(tmp_path)
    reborn, journal = _reborn(tmp_path)
    try:
        bundle = reborn.get(_MISSION_ID)
        assert bundle is not None
        assert bundle.is_verified
        assert bundle.verified_by == "worker-1"
    finally:
        journal.close()


def test_replay_refuses_verdict_forged_to_verified(tmp_path: Path) -> None:
    """[핵심] 불일치 레코드의 verdict 만 VERIFIED 로 고쳐도 기동이 거부된다.

    원장의 사실은 판정이 아니라 **측정값**이고, 재생이 그걸로 다시 대조한다.
    """
    _verified_journal(tmp_path, honest=False)

    def forge(records: list[dict[str, Any]]) -> None:
        for record in records:
            if record["kind"] == "source-media-verified":
                record["verdict"] = "VERIFIED"

    _rewrite(tmp_path, forge)
    with pytest.raises(SourceMediaRecoveryError, match="재대조와 불일치"):
        _reborn(tmp_path)


def test_replay_refuses_measurements_edited_to_match(tmp_path: Path) -> None:
    """측정값을 신고값에 맞게 고치면 판정이 뒤집혀 기록된 MISMATCH 와 어긋난다."""
    _verified_journal(tmp_path, honest=False)

    def forge(records: list[dict[str, Any]]) -> None:
        for record in records:
            if record["kind"] == "source-media-verified":
                for item in record["measurements"]:
                    item["width"] = 4000

    _rewrite(tmp_path, forge)
    with pytest.raises(SourceMediaRecoveryError, match="재대조와 불일치"):
        _reborn(tmp_path)


def test_replay_refuses_verification_before_seal(tmp_path: Path) -> None:
    _verified_journal(tmp_path)

    def reorder(records: list[dict[str, Any]]) -> None:
        verified = next(r for r in records if r["kind"] == "source-media-verified")
        records.remove(verified)
        records.insert(0, verified)

    _rewrite(tmp_path, reorder)
    with pytest.raises(SourceMediaRecoveryError, match="봉인되지 않은"):
        _reborn(tmp_path)


# ── HTTP 표면 ──────────────────────────────────────────────────────────────


class FakeStorage:
    """가짜 오브젝트 스토리지 — 포트 계약만 만족한다(네트워크·컨테이너 없이)."""

    def __init__(self) -> None:
        self.put_calls: list[tuple[str, str]] = []
        self.get_calls: list[str] = []
        self.fail_with: Exception | None = None

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        del ttl
        if self.fail_with is not None:
            raise self.fail_with
        self.put_calls.append((object_key, content_type))
        return f"https://storage.invalid/{object_key}?upload=1"

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        del ttl
        if self.fail_with is not None:
            raise self.fail_with
        self.get_calls.append(object_key)
        return f"https://storage.invalid/{object_key}?download=1"

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
            PrincipalTokenRecord(
                token_sha256=_digest_token(_WORKER_TOKEN),
                principal=Principal(
                    principal_id="worker-odm-1",
                    kind=PrincipalKind.PROCESSING_WORKER,
                    role=None,
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


def test_source_media_store_without_mission_store_refuses_assembly(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mission_store"):
        create_app(
            auth_registry=_auth_registry(),
            evidence_storage=FakeStorage(),
            source_media_store=SourceMediaStore(
                DurableJournal(tmp_path / "unused-source-media.jsonl"),
                mission_store=MissionStore(DurableJournal(tmp_path / "unused-missions.jsonl")),
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


# ── HTTP: 올린 사람은 자기 신고값을 검증할 수 없다 ──────────────────────────


def _measurement_payload(media_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "mediaId": media_id,
        "sha256": _sha(media_id),
        "bytes": 1_000_000,
        "width": 4000,
        "height": 3000,
    }
    payload.update(overrides)
    return payload


def _sealed_over_http(client: TestClient, *media_ids: str) -> None:
    ids = media_ids or ("img-1.jpg", "img-2.jpg")
    assert (
        client.post(
            f"/v1/missions/{_MISSION_ID}/source-media",
            json={"files": [_file_payload(i) for i in ids]},
        ).status_code
        == 201
    )
    assert client.post(f"/v1/missions/{_MISSION_ID}/source-media/seal").status_code == 201


@pytest.mark.parametrize("token", [_ADMIN_TOKEN, _VIEWER_TOKEN])
def test_http_humans_cannot_verify_their_own_claims(tmp_path: Path, token: str) -> None:
    """[핵심 음성] 사진을 올린 주체가 자기 신고값을 스스로 검증할 수 없다.

    ADMIN 은 이 제품에서 가장 넓은 사람 권한이고 업로드 권한(MISSIONS_ISSUE)도
    갖는다. 그 ADMIN 이 막힌다는 것이 "재는 쪽과 올리는 쪽을 갈랐다"의 실측이다.
    """
    client = _client(tmp_path, storage=FakeStorage())
    _sealed_over_http(client)
    client.headers.update({"Authorization": f"Bearer {token}"})
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/source-media/verify",
        json={"measurements": [_measurement_payload("img-1.jpg")]},
    )
    assert response.status_code == 403


def test_http_worker_verifies_and_bundle_reports_it(tmp_path: Path) -> None:
    client = _client(tmp_path, storage=FakeStorage())
    _sealed_over_http(client)

    client.headers.update({"Authorization": f"Bearer {_WORKER_TOKEN}"})
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/source-media/verify",
        json={
            "measurements": [
                _measurement_payload("img-1.jpg"),
                _measurement_payload("img-2.jpg"),
            ]
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["verdict"] == "VERIFIED"

    client.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})
    bundle = client.get(f"/v1/missions/{_MISSION_ID}/source-media").json()
    assert bundle["verifiedAt"] is not None
    assert bundle["lastMismatchAt"] is None


def test_http_mismatch_is_422_and_shows_which_files(tmp_path: Path) -> None:
    """불일치는 422 이고 **어떤 파일이** 어긋났는지 돌려준다 — 워커가 다시 볼 수 있게."""
    client = _client(tmp_path, storage=FakeStorage())
    _sealed_over_http(client)

    client.headers.update({"Authorization": f"Bearer {_WORKER_TOKEN}"})
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/source-media/verify",
        json={
            "measurements": [
                _measurement_payload("img-1.jpg"),
                _measurement_payload("img-2.jpg", width=9999),
            ]
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["verdict"] == "MISMATCH"
    assert body["mismatched"] == ["img-2.jpg"]

    client.headers.update({"Authorization": f"Bearer {_ADMIN_TOKEN}"})
    bundle = client.get(f"/v1/missions/{_MISSION_ID}/source-media").json()
    # "아직 아무도 안 읽었다"와 "재봤는데 어긋났다"를 화면이 구분할 수 있어야 한다.
    assert bundle["verifiedAt"] is None
    assert bundle["lastMismatchAt"] is not None


def test_http_verify_request_has_no_verdict_field(tmp_path: Path) -> None:
    """[핵심] 요청에 판정을 실을 자리가 없다 — 워커는 '검증됨'을 보낼 수 없다."""
    client = _client(tmp_path, storage=FakeStorage())
    _sealed_over_http(client)
    client.headers.update({"Authorization": f"Bearer {_WORKER_TOKEN}"})
    response = client.post(
        f"/v1/missions/{_MISSION_ID}/source-media/verify",
        json={
            "measurements": [_measurement_payload("img-1.jpg")],
            "verdict": "VERIFIED",
        },
    )
    assert response.status_code == 422, response.text


def test_replay_refuses_any_record_after_verification(tmp_path: Path) -> None:
    """[핵심] 검증된 번들 뒤의 어떤 검증 레코드도 live 가 만들 수 없다.

    VERIFIED 중복만 막고 MISMATCH 를 통과시키면 "검증됐는데 마지막 대조는 실패"
    라는, live 가 도달할 수 없는 상태를 재생이 만들어낸다.
    """
    _verified_journal(tmp_path)

    def append_mismatch(records: list[dict[str, Any]]) -> None:
        verified = next(r for r in records if r["kind"] == "source-media-verified")
        forged = json.loads(json.dumps(verified))
        forged["verdict"] = "MISMATCH"
        forged["measurements"][1]["width"] = 9999
        forged["mismatched"] = ["img-2.jpg"]
        records.append(forged)

    _rewrite(tmp_path, append_mismatch)
    with pytest.raises(SourceMediaRecoveryError, match="이미 검증된 번들"):
        _reborn(tmp_path)


def test_replay_refuses_duplicate_successful_verification(tmp_path: Path) -> None:
    """대조군 — 같은 게이트가 VERIFIED 중복도 막는다."""
    _verified_journal(tmp_path)

    def duplicate(records: list[dict[str, Any]]) -> None:
        verified = next(r for r in records if r["kind"] == "source-media-verified")
        records.append(json.loads(json.dumps(verified)))

    _rewrite(tmp_path, duplicate)
    with pytest.raises(SourceMediaRecoveryError, match="이미 검증된 번들"):
        _reborn(tmp_path)


# ── 사진 열람 URL (결함 후보 폴리곤 오버레이의 전제) ────────────────────────


def test_view_url_carries_the_registered_pixel_size(tmp_path: Path) -> None:
    """[핵심] 화소수를 서버가 함께 낸다.

    결함 후보의 폴리곤은 원본 픽셀 좌표라, 화면이 축소해 그릴 때 배율을 계산하려면
    원본 크기가 필요하다. 클라이언트가 이미지 로드 후 읽어 쓰면 로드 전에 레이아웃을
    못 잡고, 무엇보다 등록된 화소수와 실제 이미지가 다를 때 그 불일치가 조용히 묻힌다.
    """
    storage = FakeStorage()
    client = _client(tmp_path, storage=storage)
    assert (
        client.post(
            f"/v1/missions/{_MISSION_ID}/source-media",
            json={"files": [_file_payload("img-1.jpg")]},
        ).status_code
        == 201
    )
    response = client.get(f"/v1/missions/{_MISSION_ID}/source-media/img-1.jpg/view")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["width"] == 4000
    assert body["height"] == 3000
    assert body["sha256"] == _sha("img-1.jpg")
    assert body["viewUrl"].endswith("?download=1")
    assert storage.get_calls == [
        f"sites/{_SITE_ID}/missions/{_MISSION_ID}/source/img-1.jpg"
    ]


def test_view_of_unregistered_media_is_404(tmp_path: Path) -> None:
    client = _client(tmp_path, storage=FakeStorage())
    client.post(
        f"/v1/missions/{_MISSION_ID}/source-media",
        json={"files": [_file_payload("img-1.jpg")]},
    )
    assert (
        client.get(f"/v1/missions/{_MISSION_ID}/source-media/never-uploaded.jpg/view").status_code
        == 404
    )


def test_view_of_unknown_mission_is_404(tmp_path: Path) -> None:
    client = _client(tmp_path, storage=FakeStorage())
    assert (
        client.get("/v1/missions/mission-never-issued/source-media/img-1.jpg/view").status_code
        == 404
    )


def test_storage_failure_is_503_not_missing_photo(tmp_path: Path) -> None:
    """스토리지 장애를 "사진 없음"(404)으로 뭉개지 않는다 — 둘은 완전히 다른 사실이다."""
    storage = FakeStorage()
    client = _client(tmp_path, storage=storage)
    client.post(
        f"/v1/missions/{_MISSION_ID}/source-media",
        json={"files": [_file_payload("img-1.jpg")]},
    )
    from ksi_core.evidence import EvidenceStorageError

    storage.fail_with = EvidenceStorageError("boom")
    response = client.get(f"/v1/missions/{_MISSION_ID}/source-media/img-1.jpg/view")
    assert response.status_code == 503
    assert response.json()["detail"] == "SOURCE_MEDIA_STORAGE_UNAVAILABLE"


def test_viewer_role_can_view(tmp_path: Path) -> None:
    """열람은 MISSIONS_READ 다 — 업로드 권한(MISSIONS_ISSUE)과 다르다."""
    client = _client(tmp_path, storage=FakeStorage())
    client.post(
        f"/v1/missions/{_MISSION_ID}/source-media",
        json={"files": [_file_payload("img-1.jpg")]},
    )
    response = client.get(
        f"/v1/missions/{_MISSION_ID}/source-media/img-1.jpg/view",
        headers={"Authorization": f"Bearer {_VIEWER_TOKEN}"},
    )
    assert response.status_code == 200
