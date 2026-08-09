"""결함 후보 수신·조회 계약 (Phase 4 "표면 점검·결함 후보", MODEL-P4-001).

초점은 하나다 — **서버가 "이 사진의 이 픽셀이 균열이다"라는 주장을 그대로 받아
적지 않는가.**

결함 후보의 값은 전부 유효 범위 안에 있을 수 있다(confidence 0~1, 좌표 양수,
imageSize 양의 정수). 그래서 스키마 검증만으로는 **축소본에서 뽑은 좌표를 원본
기준으로 신고하는 것**도, **등록된 적 없는 사진을 가리키는 것**도 전부 통과한다.
그 후보는 화면에 띄우면 엉뚱한 자리에 그려지거나 아예 그릴 대상이 없다 — 조회
시점에는 정상으로 보이는 종류의 오염이다.

green≠작동: 픽스처가 후보를 저장소에 직접 주입하지 않는다 — 임무를 실제로 발급하고
사진을 실제로 등록한 뒤, HTTP 로 후보를 올려 그 게이트를 통과시킨다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.defect_candidates import (
    DefectCandidateRecoveryError,
    DefectCandidateStore,
    DefectCandidateVerdict,
    mount_defect_candidates,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_records import MissionRecord, MissionStore
from ksi_core.source_media import SourceMediaClaim, SourceMediaStore
from ksi_event_contracts.defect_candidate import DefectCandidate

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _REPO_ROOT / "contracts" / "schemas" / "defect-candidate.v1.json"

_WORKER_TOKEN = "processing-worker-token"  # noqa: S105 — 테스트 고정값
_VIEWER_TOKEN = "viewer-token"  # noqa: S105
_OPERATOR_TOKEN = "operator-token"  # noqa: S105
_MISSION_ID = "mission-defect-1"
_SITE_ID = "site-001"
_MEDIA_ID = "photo-0001"
_MEDIA_W = 4000
_MEDIA_H = 3000
_NOW = datetime(2026, 8, 8, 3, 0, tzinfo=UTC)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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
                token_sha256=_digest(_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="vw-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_OPERATOR_TOKEN),
                principal=Principal(
                    principal_id="op-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                ),
            ),
        ]
    )


def _candidate_payload(
    *,
    candidate_id: str = "defect-photo-0001-0",
    source_media_id: str = _MEDIA_ID,
    width: int = _MEDIA_W,
    height: int = _MEDIA_H,
    polygon: list[list[float]] | None = None,
    confidence: float = 0.91,
) -> dict[str, Any]:
    default_polygon = [[100.0, 30.0], [107.0, 30.0], [107.0, 49.0]]
    return {
        "schemaVersion": "1.0",
        "defectCandidateId": candidate_id,
        "defectType": "CRACK",
        "sourceMediaId": source_media_id,
        "imageSize": {"widthPx": width, "heightPx": height},
        "geometry": {
            "format": "IMAGE_POLYGON_2D",
            "payload": polygon if polygon is not None else default_polygon,
        },
        "model": {
            "modelId": "ksi-crack-segmenter-mixercseg-deepcrack",
            "sourceDigests": {"weights": "a" * 64},
        },
        "confidence": confidence,
        "measurements": {"areaPx2": 364.0, "lengthPx": 52.0, "meanWidthPx": 7.0},
    }


def _mission_store(tmp_path: Path) -> MissionStore:
    store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    assert (
        store.record_issuance(
            MissionRecord(
                mission_id=_MISSION_ID,
                site_id=_SITE_ID,
                mission_type="ASSET_INSPECTION",
                artifact_kind="contract",
                contract={"schemaVersion": "1.2", "missionId": _MISSION_ID},
                kmz_sha256=None,
                route_pattern=None,
                waypoint_count=None,
                planned_coverage_ratio=None,
                issued_at=_NOW,
                issued_by="op-1",
                plan_request=None,
                plan_request_digest=None,
            )
        ).value
        == "RECORDED"
    )
    return store


def _source_media_store(
    tmp_path: Path, mission_store: MissionStore, *, width: int = _MEDIA_W, height: int = _MEDIA_H
) -> SourceMediaStore:
    store = SourceMediaStore(
        DurableJournal(tmp_path / "source-media.jsonl"), mission_store=mission_store
    )
    result = store.register_batch(
        _MISSION_ID,
        [
            SourceMediaClaim(
                media_id=_MEDIA_ID,
                sha256="b" * 64,
                size_bytes=1_234_567,
                width=width,
                height=height,
                content_type="image/jpeg",
            )
        ],
        registered_by="op-1",
        now=_NOW,
    )
    assert result.verdict.value == "PROCESSED", result
    return store


@pytest.fixture
def store(tmp_path: Path) -> DefectCandidateStore:
    missions = _mission_store(tmp_path)
    return DefectCandidateStore(
        DurableJournal(tmp_path / "defects.jsonl"),
        mission_store=missions,
        source_media_store=_source_media_store(tmp_path, missions),
    )


def _client(store: DefectCandidateStore, *, token: str = _WORKER_TOKEN) -> TestClient:
    app = FastAPI()
    mount_auth(app, _registry())
    mount_defect_candidates(app, store)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _post(client: TestClient, *candidates: dict[str, Any]) -> Any:
    return client.post(
        f"/v1/missions/{_MISSION_ID}/defect-candidates",
        json={"candidates": list(candidates)},
    )


# ── 계약 스키마 정합 ────────────────────────────────────────────────────────


def test_request_payload_satisfies_contract_schema() -> None:
    """테스트가 쓰는 후보 payload 자체가 계약 스키마를 만족한다 — 픽스처가
    스키마를 벗어난 값을 쓰면 이 파일의 다른 검증이 전부 의미를 잃는다."""
    validator = Draft202012Validator(json.loads(_SCHEMA.read_text(encoding="utf-8")))
    errors = sorted(validator.iter_errors(_candidate_payload()), key=lambda e: e.path)
    assert not errors, [e.message for e in errors]


# ── 서버가 후보의 참조 대상을 검증한다 ──────────────────────────────────────


def test_candidate_for_registered_photo_is_recorded(store: DefectCandidateStore) -> None:
    response = _post(_client(store), _candidate_payload())
    assert response.status_code == 201, response.json()
    assert response.json()["verdict"] == "RECORDED"
    assert response.json()["recordedCount"] == 1


def test_unregistered_source_media_is_rejected(store: DefectCandidateStore) -> None:
    """등록된 적 없는 사진을 가리키는 폴리곤은 그릴 대상이 없다."""
    response = _post(_client(store), _candidate_payload(source_media_id="photo-does-not-exist"))
    assert response.status_code == 422
    assert response.json()["verdict"] == DefectCandidateVerdict.UNKNOWN_SOURCE_MEDIA.value


def test_image_size_mismatch_is_rejected(store: DefectCandidateStore) -> None:
    """[핵심] 축소본(512x384)에서 뽑은 좌표를 4000x3000 사진에 신고하면, 값은 전부
    유효하고 스키마도 통과하지만 폴리곤은 사진 좌상단 구석을 가리킨다 — 서버가
    등록된 실제 화소수와 대조하지 않으면 이 오염은 화면에 그려질 때까지 안 보인다."""
    response = _post(_client(store), _candidate_payload(width=512, height=384))
    assert response.status_code == 422
    assert response.json()["verdict"] == DefectCandidateVerdict.IMAGE_SIZE_MISMATCH.value


@pytest.mark.parametrize(
    "polygon",
    [
        [[_MEDIA_W + 1.0, 10.0], [10.0, 10.0], [10.0, 20.0]],  # x 가 이미지 밖
        [[10.0, 10.0], [10.0, float(_MEDIA_H)], [20.0, 20.0]],  # y 가 마지막 픽셀 초과
        [[-1.0, 10.0], [10.0, 10.0], [10.0, 20.0]],  # 음수 좌표
    ],
)
def test_polygon_outside_image_is_rejected(
    store: DefectCandidateStore, polygon: list[list[float]]
) -> None:
    response = _post(_client(store), _candidate_payload(polygon=polygon))
    assert response.status_code == 422
    assert response.json()["verdict"] == DefectCandidateVerdict.GEOMETRY_OUT_OF_BOUNDS.value


def test_last_valid_pixel_is_inside(store: DefectCandidateStore) -> None:
    """경계 자체는 유효하다 — [0, width-1] 은 닫힌 구간이다(과잉 거부 방지)."""
    polygon = [[0.0, 0.0], [_MEDIA_W - 1.0, 0.0], [_MEDIA_W - 1.0, _MEDIA_H - 1.0]]
    response = _post(_client(store), _candidate_payload(polygon=polygon))
    assert response.status_code == 201, response.json()


def test_unknown_mission_is_rejected(tmp_path: Path) -> None:
    missions = _mission_store(tmp_path)
    store = DefectCandidateStore(
        DurableJournal(tmp_path / "defects.jsonl"),
        mission_store=missions,
        source_media_store=_source_media_store(tmp_path, missions),
    )
    response = _client(store).post(
        "/v1/missions/mission-never-issued/defect-candidates",
        json={"candidates": [_candidate_payload()]},
    )
    assert response.status_code == 404
    assert response.json()["verdict"] == DefectCandidateVerdict.UNKNOWN_MISSION.value


# ── 배치는 전부-또는-전무 ───────────────────────────────────────────────────


def test_batch_with_one_bad_candidate_records_nothing(store: DefectCandidateStore) -> None:
    """부분 기록은 조용한 누락이다 — 조회 시점엔 정상으로 보인다."""
    client = _client(store)
    response = _post(
        client,
        _candidate_payload(candidate_id="defect-ok"),
        _candidate_payload(candidate_id="defect-bad", source_media_id="nope"),
    )
    assert response.status_code == 422
    listed = client.get(
        f"/v1/missions/{_MISSION_ID}/defect-candidates",
        headers={"Authorization": f"Bearer {_VIEWER_TOKEN}"},
    ).json()
    assert listed["candidateCount"] == 0


def test_duplicate_id_in_same_batch_is_rejected(store: DefectCandidateStore) -> None:
    response = _post(
        _client(store),
        _candidate_payload(candidate_id="defect-dup"),
        _candidate_payload(candidate_id="defect-dup", confidence=0.5),
    )
    assert response.status_code == 409
    assert response.json()["verdict"] == DefectCandidateVerdict.DUPLICATE_CANDIDATE_ID.value


def test_resubmitting_identical_batch_is_idempotent(store: DefectCandidateStore) -> None:
    client = _client(store)
    assert _post(client, _candidate_payload()).status_code == 201
    again = _post(client, _candidate_payload())
    assert again.status_code == 201
    assert again.json()["recordedCount"] == 0
    listed = client.get(
        f"/v1/missions/{_MISSION_ID}/defect-candidates",
        headers={"Authorization": f"Bearer {_VIEWER_TOKEN}"},
    ).json()
    assert listed["candidateCount"] == 1


def test_same_id_different_content_is_conflict(store: DefectCandidateStore) -> None:
    """같은 id 로 **다른 내용**을 보내는 것은 재전송이 아니라 덮어쓰기 시도다."""
    client = _client(store)
    assert _post(client, _candidate_payload()).status_code == 201
    conflict = _post(client, _candidate_payload(confidence=0.42))
    assert conflict.status_code == 409
    assert conflict.json()["verdict"] == DefectCandidateVerdict.DUPLICATE_CANDIDATE_ID.value


def test_empty_batch_is_rejected(store: DefectCandidateStore) -> None:
    """'결함 0건'은 제출이 아니라 조회 결과가 비어 있는 것으로 표현된다."""
    response = _client(store).post(
        f"/v1/missions/{_MISSION_ID}/defect-candidates", json={"candidates": []}
    )
    # pydantic min_length=1 이 라우트 진입 전에 잡는다(422) — 저장소 게이트
    # (EMPTY_BATCH)는 그걸 우회하는 직접 호출에 대한 두 번째 방어선이다.
    assert response.status_code == 422


def test_store_level_empty_batch_verdict(store: DefectCandidateStore) -> None:
    result = store.record_batch(_MISSION_ID, [], now=_NOW)
    assert result.verdict is DefectCandidateVerdict.EMPTY_BATCH


# ── 권한: 사람은 결함을 손으로 주장할 수 없다 ───────────────────────────────


@pytest.mark.parametrize("token", [_VIEWER_TOKEN, _OPERATOR_TOKEN])
def test_operator_cannot_submit_candidates(store: DefectCandidateStore, token: str) -> None:
    """PROCESSING_WORK 는 어느 Role 에도 매핑되지 않는다 — 사람이 "여기 균열이
    있다"를 원장에 직접 주장할 수 없다(사람의 판단은 이벤트 트리아지로 표현된다)."""
    response = _post(_client(store, token=token), _candidate_payload())
    assert response.status_code == 403


def test_unauthenticated_cannot_read(store: DefectCandidateStore) -> None:
    app = FastAPI()
    mount_auth(app, _registry())
    mount_defect_candidates(app, store)
    response = TestClient(app).get(f"/v1/missions/{_MISSION_ID}/defect-candidates")
    assert response.status_code == 401


# ── 조회 ────────────────────────────────────────────────────────────────────


def test_list_is_empty_not_404_when_nothing_recorded(store: DefectCandidateStore) -> None:
    """'아직 안 돌았다'와 '돌렸는데 결함이 없다'를 이 엔드포인트는 구분하지 못하고,
    구분하는 척하면 안 된다 — 둘 다 빈 목록이다."""
    response = _client(store, token=_VIEWER_TOKEN).get(
        f"/v1/missions/{_MISSION_ID}/defect-candidates"
    )
    assert response.status_code == 200
    assert response.json()["candidateCount"] == 0
    assert response.json()["sourceMediaIds"] == []


def test_list_round_trips_contract_payload(store: DefectCandidateStore) -> None:
    """조회 응답의 후보가 계약 스키마를 만족하고 모델로 되파싱된다(왕복)."""
    _post(_client(store), _candidate_payload())
    listed = _client(store, token=_VIEWER_TOKEN).get(
        f"/v1/missions/{_MISSION_ID}/defect-candidates"
    ).json()
    assert listed["candidateCount"] == 1
    assert listed["sourceMediaIds"] == [_MEDIA_ID]
    wire = listed["candidates"][0]["candidate"]
    validator = Draft202012Validator(json.loads(_SCHEMA.read_text(encoding="utf-8")))
    assert not sorted(validator.iter_errors(wire), key=lambda e: e.path)
    assert DefectCandidate.model_validate(wire).defect_candidate_id == "defect-photo-0001-0"
    assert listed["candidates"][0]["reportedBy"] == "worker-1"


def test_list_filters_by_source_media(store: DefectCandidateStore) -> None:
    client = _client(store)
    _post(client, _candidate_payload(candidate_id="d-0"), _candidate_payload(candidate_id="d-1"))
    viewer = _client(store, token=_VIEWER_TOKEN)
    hit = viewer.get(
        f"/v1/missions/{_MISSION_ID}/defect-candidates", params={"sourceMediaId": _MEDIA_ID}
    ).json()
    assert hit["candidateCount"] == 2
    miss = viewer.get(
        f"/v1/missions/{_MISSION_ID}/defect-candidates", params={"sourceMediaId": "other"}
    ).json()
    assert miss["candidateCount"] == 0


# ── 재생(replay)도 같은 게이트를 탄다 ───────────────────────────────────────


def test_replay_restores_recorded_candidates(tmp_path: Path) -> None:
    missions = _mission_store(tmp_path)
    media = _source_media_store(tmp_path, missions)
    journal_path = tmp_path / "defects.jsonl"
    journal = DurableJournal(journal_path)
    first = DefectCandidateStore(
        journal, mission_store=missions, source_media_store=media
    )
    assert (
        first.record_batch(
            _MISSION_ID, [DefectCandidate.model_validate(_candidate_payload())], now=_NOW
        ).verdict
        is DefectCandidateVerdict.RECORDED
    )
    journal.close()  # flock 해제 — 단일 writer 불변식은 재기동 시뮬레이션에도 적용된다

    reborn = DurableJournal(journal_path)
    try:
        reopened = DefectCandidateStore(
            reborn, mission_store=missions, source_media_store=media
        )
        restored = reopened.list_for_mission(_MISSION_ID)
    finally:
        reborn.close()
    assert len(restored) == 1
    assert restored[0].candidate.defect_candidate_id == "defect-photo-0001-0"
    assert restored[0].reported_by is None


def test_replay_refuses_candidate_that_live_would_reject(tmp_path: Path) -> None:
    """[핵심] journal 을 손으로 고쳐 사진에 걸리지 않는 후보를 되살릴 수 없다 —
    재생이 live 보다 느슨하면 원장 조작이 검증 우회 경로가 된다."""
    missions = _mission_store(tmp_path)
    media = _source_media_store(tmp_path, missions)
    journal_path = tmp_path / "defects.jsonl"
    journal_path.write_text(
        json.dumps(
            {
                "kind": "defect-candidates-recorded",
                "ts": _NOW.isoformat(),
                "missionId": _MISSION_ID,
                "reportedBy": "worker-1",
                "candidates": [_candidate_payload(width=512, height=384)],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(DefectCandidateRecoveryError, match="IMAGE_SIZE_MISMATCH"):
        DefectCandidateStore(
            DurableJournal(journal_path), mission_store=missions, source_media_store=media
        )


def test_rejection_is_journaled_and_skipped_on_replay(tmp_path: Path) -> None:
    """거부도 감사기록에 남지만 수용 상태로는 되살아나지 않는다."""
    missions = _mission_store(tmp_path)
    media = _source_media_store(tmp_path, missions)
    journal_path = tmp_path / "defects.jsonl"
    journal = DurableJournal(journal_path)
    store = DefectCandidateStore(journal, mission_store=missions, source_media_store=media)
    bad = DefectCandidate.model_validate(_candidate_payload(source_media_id="nope"))
    assert (
        store.record_batch(_MISSION_ID, [bad], now=_NOW).verdict
        is DefectCandidateVerdict.UNKNOWN_SOURCE_MEDIA
    )
    kinds = [
        json.loads(line)["kind"]
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert kinds == ["defect-candidates-rejected"]
    journal.close()

    reborn = DurableJournal(journal_path)
    try:
        reopened = DefectCandidateStore(
            reborn, mission_store=missions, source_media_store=media
        )
        assert reopened.list_for_mission(_MISSION_ID) == []
    finally:
        reborn.close()
