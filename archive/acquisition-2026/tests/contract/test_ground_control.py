"""지상 기준점(GCP) 파일 입구 계약 — 두 시점 비교를 가능하게 만드는 전제.

## 왜 이 표면이 생겼나

2026-08-18 실제 파이프라인 종단 실행에서 드러난 사실이다: 사진 87장을 두 벌로
나눠 재구성을 두 번 완주시켰는데, **두 결과 모두 EPSG:32617(UTM 17N)** 로 나와
비교 단계에서 거부됐다. 재구성 엔진은 사진의 EXIF GPS 만으로는 그 지역의 UTM
좌표계를 고르고, 이 시스템은 현행 한국 평면직각좌표계에서만 두 시점을 비교한다
(``ksi_geo_spatial.crs`` 화이트리스트, INV-020). 즉 **기준점 없이 찍은 조사는
한국에서 찍어도 비교 단계에 도달하지 못한다** — 엔진이 UTM 52N 을 낼 뿐이다.

기준점 파일이 좌표계를 선언하면 엔진이 그 좌표계로 성과를 낸다. 그래서 이
파일을 조사에 붙일 자리가 필요하다.

## 이 파일이 고정하는 것

1. **허용 목록 밖 좌표계는 등록 시점에 거부된다** — 재구성을 다 돌린 뒤 비교에서
   거부되면 몇 분을 버리고 사유도 멀리서 나타난다.
2. **봉인 후에는 못 붙인다** — 봉인은 "이 입력으로 재구성한다"의 확정이다.
3. **다른 내용으로 덮어쓸 수 없다** — 어느 기준점으로 만든 성과인지가 원장에서
   흔들리면 안 된다.
4. **digest 가 기준점까지 덮는다** — 기준점이 다르면 다른 입력이다. 동시에
   **기준점이 없는 기존 번들의 digest 는 변하지 않는다**(하위호환).
5. **재생도 같은 게이트를 다시 태운다** — journal 을 손으로 고쳐 UTM 기준점을
   붙인 번들을 되살릴 수 없다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_core.source_media import (
    GroundControlRecord,
    GroundControlResult,
    GroundControlVerdict,
    SourceMediaClaim,
    SourceMediaRecord,
    SourceMediaRecoveryError,
    SourceMediaStore,
    build_ground_control_object_key,
    compute_source_bundle_digest,
)

_MISSION_ID = "mission-gcp-1"
_SITE_ID = "site-gcp"
_NOW = datetime(2026, 8, 18, 6, 0, tzinfo=UTC)
_GCP_SHA = hashlib.sha256(b"gcp").hexdigest()


def _mission_store(tmp_path: Path, *, path: str = "missions.jsonl") -> MissionStore:
    store = MissionStore(DurableJournal(tmp_path / path))
    assert (
        store.record_issuance(
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
    return store


@pytest.fixture
def store(tmp_path: Path) -> SourceMediaStore:
    return SourceMediaStore(
        DurableJournal(tmp_path / "source-media.jsonl"), mission_store=_mission_store(tmp_path)
    )


def _register(
    store: SourceMediaStore, *, crs: str = "EPSG:5186", sha: str = _GCP_SHA
) -> GroundControlResult:
    return store.register_ground_control(
        _MISSION_ID,
        sha256=sha,
        size_bytes=512,
        crs=crs,
        registered_by="op-1",
        now=_NOW,
    )


def _photo(store: SourceMediaStore) -> None:
    """봉인에는 사진이 최소 1장 필요하다 — 기준점만으로는 번들이 성립하지 않는다."""
    result = store.register_batch(
        _MISSION_ID,
        [
            SourceMediaClaim(
                media_id="a.jpg",
                sha256=hashlib.sha256(b"a").hexdigest(),
                size_bytes=1_000_000,
                width=4000,
                height=3000,
                content_type="image/jpeg",
            )
        ],
        registered_by="op-1",
        now=_NOW,
    )
    assert result.verdict.value == "PROCESSED"


# ── 좌표계 게이트 ───────────────────────────────────────────────────────────


def test_korean_projected_crs_is_accepted(store: SourceMediaStore) -> None:
    result = _register(store, crs="EPSG:5186")
    assert result.verdict is GroundControlVerdict.REGISTERED
    assert result.record is not None
    assert result.record.crs == "EPSG:5186"
    assert result.record.object_key.endswith("/gcp_list.txt")


@pytest.mark.parametrize(
    "crs",
    [
        "EPSG:32617",  # 실제로 부딪힌 값 — 미국 UTM 17N
        "EPSG:32652",  # 한국 UTM 52N — **한국이어도** 국가 좌표계가 아니다
        "EPSG:5174",  # 구 측지계(Bessel) — 화이트리스트가 원래 막던 대상
        "EPSG:4326",  # 지리좌표계 — 투영좌표계가 아니다
    ],
)
def test_non_korean_grid_is_refused_at_registration(store: SourceMediaStore, crs: str) -> None:
    """비교 단계까지 가서 거부되는 대신 **여기서** 막는다.

    EPSG:32652 를 함께 막는 것이 이 테스트의 요점이다 — "한국에서 찍었으니
    괜찮다"가 아니라 "국가 평면직각좌표계 성과냐"가 기준이다.
    """
    result = _register(store, crs=crs)
    assert result.verdict is GroundControlVerdict.UNSUPPORTED_CRS
    assert result.detail is not None
    bundle = store.get(_MISSION_ID)
    assert bundle is None or bundle.ground_control is None


def test_unparseable_crs_is_refused(store: SourceMediaStore) -> None:
    result = _register(store, crs="좌표계아님")
    assert result.verdict is GroundControlVerdict.UNSUPPORTED_CRS


# ── 봉인·중복 ───────────────────────────────────────────────────────────────


def test_ground_control_cannot_be_attached_after_seal(store: SourceMediaStore) -> None:
    _photo(store)
    assert store.seal(_MISSION_ID, sealed_by="op-1", now=_NOW).verdict.value == "SEALED"
    assert _register(store).verdict is GroundControlVerdict.BUNDLE_SEALED


def test_same_file_resent_is_idempotent(store: SourceMediaStore) -> None:
    first = _register(store)
    second = _register(store)
    assert second.verdict is GroundControlVerdict.REGISTERED
    assert first.record is not None and second.record is not None
    assert second.record.registered_at == first.record.registered_at


def test_different_file_is_refused_not_overwritten(store: SourceMediaStore) -> None:
    _register(store)
    other = _register(store, sha=hashlib.sha256(b"other").hexdigest())
    assert other.verdict is GroundControlVerdict.CLAIM_CONFLICT
    bundle = store.get(_MISSION_ID)
    assert bundle is not None and bundle.ground_control is not None
    assert bundle.ground_control.sha256 == _GCP_SHA


def test_unknown_mission_is_refused(store: SourceMediaStore) -> None:
    result = store.register_ground_control(
        "mission-does-not-exist",
        sha256=_GCP_SHA,
        size_bytes=512,
        crs="EPSG:5186",
        registered_by="op-1",
        now=_NOW,
    )
    assert result.verdict is GroundControlVerdict.UNKNOWN_MISSION


# ── digest ─────────────────────────────────────────────────────────────────


def _record(media_id: str) -> SourceMediaRecord:
    return SourceMediaRecord(
        media_id=media_id,
        sha256=hashlib.sha256(media_id.encode()).hexdigest(),
        size_bytes=1_000_000,
        width=4000,
        height=3000,
        content_type="image/jpeg",
        object_key=f"sites/{_SITE_ID}/missions/{_MISSION_ID}/source/{media_id}",
        registered_at=_NOW,
        registered_by="op-1",
    )


def _gcp_record(crs: str = "EPSG:5186", sha: str = _GCP_SHA) -> GroundControlRecord:
    return GroundControlRecord(
        sha256=sha,
        size_bytes=512,
        crs=crs,
        object_key=build_ground_control_object_key(site_id=_SITE_ID, mission_id=_MISSION_ID),
        registered_at=_NOW,
        registered_by="op-1",
    )


def test_digest_is_unchanged_for_bundles_without_ground_control() -> None:
    """하위호환의 핵심 — 이미 봉인된 원장이 재생에서 거부되면 안 된다.

    ``_replay_seal`` 이 digest 를 재계산해 기록과 대조하므로, 기준점이 없는
    번들의 digest 가 조금이라도 달라지면 **기존 배포의 모든 봉인 레코드가**
    재생에서 무너진다.
    """
    media = [_record("a.jpg"), _record("b.jpg")]
    assert compute_source_bundle_digest(_MISSION_ID, media) == compute_source_bundle_digest(
        _MISSION_ID, media, None
    )


def test_digest_changes_when_ground_control_is_attached() -> None:
    media = [_record("a.jpg")]
    without = compute_source_bundle_digest(_MISSION_ID, media)
    with_gcp = compute_source_bundle_digest(_MISSION_ID, media, _gcp_record())
    assert without != with_gcp


def test_digest_distinguishes_different_ground_control() -> None:
    """같은 사진 + 다른 기준점 = 다른 입력. digest 가 그걸 구분해야 한다."""
    media = [_record("a.jpg")]
    first = compute_source_bundle_digest(_MISSION_ID, media, _gcp_record())
    other_file = compute_source_bundle_digest(
        _MISSION_ID, media, _gcp_record(sha=hashlib.sha256(b"other").hexdigest())
    )
    other_crs = compute_source_bundle_digest(_MISSION_ID, media, _gcp_record(crs="EPSG:5187"))
    assert len({first, other_file, other_crs}) == 3


# ── 재생 ───────────────────────────────────────────────────────────────────


def _rewrite_journal(path: Path, mutate: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    mutated = [mutate(raw) for raw in lines]
    path.write_text(
        "".join(json.dumps(raw, ensure_ascii=False) + "\n" for raw in mutated), encoding="utf-8"
    )


def test_replay_restores_ground_control(tmp_path: Path) -> None:
    path = tmp_path / "source-media.jsonl"
    journal = DurableJournal(path)
    store = SourceMediaStore(journal, mission_store=_mission_store(tmp_path))
    _register(store)
    journal.close()  # 프로세스 종료 재현(flock 해제)

    reborn_journal = DurableJournal(path)
    reborn = SourceMediaStore(
        reborn_journal, mission_store=_mission_store(tmp_path, path="missions2.jsonl")
    )
    bundle = reborn.get(_MISSION_ID)
    assert bundle is not None and bundle.ground_control is not None
    assert bundle.ground_control.crs == "EPSG:5186"
    reborn_journal.close()


def test_replay_refuses_forged_out_of_whitelist_crs(tmp_path: Path) -> None:
    """journal 을 손으로 고쳐 UTM 기준점을 되살릴 수 없다.

    이 게이트가 없으면 등록 시점 검증은 우회 가능한 장식이 된다 — 원장 파일에
    한 글자만 고치면 그 조사가 다른 좌표계로 재구성되고, 비교 결과는 그럴듯한
    숫자로 나온다.
    """
    path = tmp_path / "source-media.jsonl"
    journal = DurableJournal(path)
    store = SourceMediaStore(journal, mission_store=_mission_store(tmp_path))
    _register(store)
    journal.close()

    def _forge(raw: dict[str, Any]) -> dict[str, Any]:
        if raw.get("kind") == "source-media-ground-control-registered":
            raw["crs"] = "EPSG:32617"
        return raw

    _rewrite_journal(path, _forge)
    with pytest.raises(SourceMediaRecoveryError, match="허용 목록 밖"):
        SourceMediaStore(
            DurableJournal(path), mission_store=_mission_store(tmp_path, path="missions2.jsonl")
        )
