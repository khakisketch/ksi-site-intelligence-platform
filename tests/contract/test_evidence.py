"""Evidence 미디어 경계 계약 (ADR-KSI-010 §1/§3).

Core 는 바이트를 중계하지 않는다 — 원장에 등록하고 presigned URL 만 준다.
여기서 반증하는 것은 그 경계의 세 가지다:

1. 객체 키를 **서버가** 만든다 — 클라이언트 문자열이 키에 그대로 들어가면
   경로 탈출과 타 현장 덮어쓰기가 열린다(S2 재검토 P1 과 같은 클래스).
2. 스토리지가 없으면 경로가 **존재하지 않는다** — 조립되지 않은 기능이 2xx 로
   보이는 것보다 404 가 정직하다.
3. 폐기는 삭제가 아니라 tombstone — "증거가 없다"와 "정책대로 폐기했다"는
   사고 조사에서 다른 사실이다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.events import EventStore
from ksi_core.evidence import (
    ALLOWED_CONTENT_TYPES,
    EvidenceStorageError,
    EvidenceVerdict,
    build_object_key,
)
from ksi_domain.enums import EventStatus
from ksi_event_contracts.offline_sync import payload_digest

_ADMIN_TOKEN = "evidence-test-admin"  # noqa: S105 -- 테스트 고정값
_VIEWER_TOKEN = "evidence-test-viewer"  # noqa: S105 -- 테스트 고정값


class FakeStorage:
    """가짜 오브젝트 스토리지 — 포트 계약만 만족한다(네트워크·컨테이너 없이)."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self.put_calls: list[tuple[str, str, timedelta]] = []
        self.get_calls: list[tuple[str, timedelta]] = []
        self.deleted: list[str] = []
        self.fail_with: Exception | None = None

    def presigned_put(self, object_key: str, *, content_type: str, ttl: timedelta) -> str:
        if self.fail_with is not None:
            raise self.fail_with
        self.put_calls.append((object_key, content_type, ttl))
        return f"https://storage.invalid/{object_key}?upload=1"

    def presigned_get(self, object_key: str, *, ttl: timedelta) -> str:
        if self.fail_with is not None:
            raise self.fail_with
        self.get_calls.append((object_key, ttl))
        return f"https://storage.invalid/{object_key}?view=1"

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        """포트가 요구하는 서버측 직접 쓰기 — 이 스텁은 메모리에만 담는다."""
        del content_type
        self._blobs[object_key] = data

    def get_bytes(self, object_key: str) -> bytes:
        """부재도 오류다(포트 계약) — 조용히 빈 바이트를 돌려주지 않는다."""
        blob = self._blobs.get(object_key)
        if blob is None:
            raise EvidenceStorageError(f"없다: {object_key}")
        return blob

    def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)


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
                token_sha256=_digest(_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="op-viewer",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                ),
            ),
        ]
    )


def _bundle(event_id: str = "evt-1") -> dict[str, Any]:
    """유효한 EventBundle v1.2 — test_events_triage.py 의 빌더와 같은 형태."""
    return {
        "schemaVersion": "1.2",
        "eventId": event_id,
        "siteId": "site-1",
        "missionId": "mission-1",
        "eventType": "PERSON_PRESENT",
        "status": "CANDIDATE",
        "occurredAt": "2026-08-04T00:00:00Z",
        "entities": ["ent-trk-001"],
        "spatialContext": {"zone": "A"},
        "reasoning": {},
        "evidence": {},
        "lineage": {
            "edgeVersion": "evidence-test-edge-1.0",
            "modelVersions": {"detector": "stub"},
            "policyVersion": "evidence-test-policy-1",
            "calibrationProfileId": "evidence-test-cal-1",
            "classification": {
                "ent-trk-001": {
                    "entityClass": "Person",
                    "ontologyVersion": "ksi-ontology-v1",
                    "source": {
                        "taxonomy": "COCO-2017",
                        "sourceClassIds": [0],
                        "sourceClassNames": ["person"],
                    },
                    "entityFingerprint": "a" * 64,
                }
            },
        },
    }


def _critical_evidence_refs() -> dict[str, Any]:
    return {
        "clips": ["clip-01"],
        "riskFieldArtifact": "risk-1",
        "trajectoryArtifact": "trajectory-1",
        "viewpointHistoryArtifact": "viewpoint-1",
    }


def _project_critical_finding(store: EventStore) -> None:
    for status in ("EVIDENCE_COLLECTION", "FINDING"):
        payload = _bundle()
        payload.update(
            {
                "status": status,
                "severity": "CRITICAL",
                "evidence": _critical_evidence_refs(),
            }
        )
        verdict = store.project_bundle(
            payload,
            edge_device_id="dev-1",
            received_at=datetime.now(UTC),
        )
        assert verdict.value == "EVENT_UPDATED"


def _risk_field_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemaVersion": "1.0",
        "riskFieldId": "risk-1",
        "type": "DYNAMIC",
        "sourceEntityIds": ["ent-trk-001"],
        "validity": {
            "from": "2026-08-03T23:59:59Z",
            "to": "2026-08-04T00:00:01Z",
        },
        "geometry": {
            "format": "PARAMETRIC_VOLUME",
            "payload": {"shape": "capsule", "radiusM": 2.5},
        },
        "riskModel": {
            "policyId": "critical-person-proximity-v1",
            "severity": 0.98,
            "predictionHorizonSeconds": 5.0,
        },
        "uncertainty": {"positionSigmaM": 0.2},
    }
    payload.update(overrides)
    return payload


def _register_critical_artifacts(store: EventStore, storage: FakeStorage) -> bytes:
    for artifact_id, content_type in (
        ("clip-01", "video/mp4"),
        ("risk-1", "application/json"),
        ("trajectory-1", "application/octet-stream"),
        ("viewpoint-1", "application/octet-stream"),
    ):
        result = _register(store, artifact_id, content_type=content_type)
        assert result.verdict is EvidenceVerdict.REGISTERED
    raw = json.dumps(
        _risk_field_payload(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    risk_artifact = store.get_evidence("dev-1::evt-1", "risk-1")
    assert risk_artifact is not None
    storage.put_bytes(risk_artifact.object_key, raw, content_type="application/json")
    return raw


@pytest.fixture
def store(tmp_path: Path) -> EventStore:
    store = EventStore(DurableJournal(tmp_path / "events.jsonl"))
    store.project_bundle(_bundle(), edge_device_id="dev-1", received_at=datetime.now(UTC))
    return store


@pytest.fixture
def storage() -> FakeStorage:
    return FakeStorage()


def _client(store: EventStore, storage: FakeStorage | None, tmp_path: Path) -> TestClient:
    app = create_app(
        auth_registry=_auth_registry(),
        event_store=store,
        evidence_storage=storage,
        mission_signing_key=None,
    )
    del tmp_path
    return TestClient(app)


def _auth(token: str = _ADMIN_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── 객체 키 생성 (순수 함수) ────────────────────────────────────────────────


def test_object_key_is_built_from_validated_parts() -> None:
    key = build_object_key(site_id="site-1", event_key="dev-1::evt-1", artifact_id="clip-01.mp4")
    assert key == "sites/site-1/events/dev-1/evt-1/clip-01.mp4"


@pytest.mark.parametrize(
    "artifact_id",
    [
        "../../etc/passwd",
        "a/b",
        ".hidden",
        "-leading-dash",
        "",
        "clip 01",
        "clip\n01",
    ],
)
def test_path_escaping_artifact_id_is_refused(artifact_id: str) -> None:
    """클라이언트 문자열이 객체 키에 그대로 들어가면 경로 탈출이 열린다."""
    with pytest.raises(ValueError, match="artifactId"):
        build_object_key(site_id="site-1", event_key="dev-1::evt-1", artifact_id=artifact_id)


@pytest.mark.parametrize(
    "event_key",
    ["dev-1", "dev-1::", "::evt-1", "../x::evt-1", "dev-1::../x"],
)
def test_malformed_event_key_is_refused(event_key: str) -> None:
    with pytest.raises(ValueError, match="eventKey"):
        build_object_key(site_id="site-1", event_key=event_key, artifact_id="clip-01")


def test_path_escaping_site_id_is_refused() -> None:
    with pytest.raises(ValueError, match="siteId"):
        build_object_key(site_id="../other", event_key="dev-1::evt-1", artifact_id="clip-01")


# ── 저장소 등록·폐기 ────────────────────────────────────────────────────────


def _register(store: EventStore, artifact_id: str = "clip-01", **kwargs: Any) -> Any:
    return store.register_evidence(
        event_key="dev-1::evt-1",
        artifact_id=artifact_id,
        content_type=kwargs.pop("content_type", "video/mp4"),
        registered_by=kwargs.pop("registered_by", "op-admin"),
        now=kwargs.pop("now", datetime.now(UTC)),
    )


def test_register_then_replay_preserves_artifact(store: EventStore, tmp_path: Path) -> None:
    result = _register(store)
    assert result.verdict is EvidenceVerdict.REGISTERED
    assert result.artifact is not None
    assert result.artifact.object_key == "sites/site-1/events/dev-1/evt-1/clip-01"

    # 재기동해도 증거가 살아남는다 — 원장이 정본이다.
    journal_path = tmp_path / "events.jsonl"
    store._journal.close()  # noqa: SLF001 -- flock 해제(재기동 시뮬레이션)
    reopened = EventStore(DurableJournal(journal_path))
    artifact = reopened.get_evidence("dev-1::evt-1", "clip-01")
    assert artifact is not None
    assert artifact.registered_by == "op-admin"
    assert not artifact.is_tombstoned


def test_optional_evidence_digest_is_validated_and_replayed(
    store: EventStore, tmp_path: Path
) -> None:
    digest = "sha256:" + "a" * 64
    result = store.register_evidence(
        event_key="dev-1::evt-1",
        artifact_id="edge-risk-01.json",
        content_type="application/octet-stream",
        registered_by="edge-dev-1",
        now=datetime.now(UTC),
        content_digest=digest,
    )
    assert result.verdict is EvidenceVerdict.REGISTERED
    assert result.artifact is not None and result.artifact.content_digest == digest
    assert (
        store.register_evidence(
            event_key="dev-1::evt-1",
            artifact_id="bad-digest",
            content_type="application/octet-stream",
            registered_by="edge-dev-1",
            now=datetime.now(UTC),
            content_digest="not-a-digest",
        ).verdict
        is EvidenceVerdict.INVALID_CONTENT_DIGEST
    )

    journal_path = tmp_path / "events.jsonl"
    store._journal.close()  # noqa: SLF001 -- flock 해제(재기동 시뮬레이션)
    reopened = EventStore(DurableJournal(journal_path))
    artifact = reopened.get_evidence("dev-1::evt-1", "edge-risk-01.json")
    assert artifact is not None and artifact.content_digest == digest


def test_duplicate_artifact_id_is_refused(store: EventStore) -> None:
    """같은 id 재등록을 허용하면 앞선 증거의 객체 키를 조용히 덮어쓴다."""
    assert _register(store).verdict is EvidenceVerdict.REGISTERED
    assert _register(store).verdict is EvidenceVerdict.DUPLICATE_ARTIFACT


def test_duplicate_is_refused_even_after_tombstone(store: EventStore) -> None:
    _register(store)
    store.tombstone_evidence(
        event_key="dev-1::evt-1",
        artifact_id="clip-01",
        reason="보관 기간 만료",
        now=datetime.now(UTC),
    )
    assert _register(store).verdict is EvidenceVerdict.DUPLICATE_ARTIFACT


def test_unknown_event_is_refused(store: EventStore) -> None:
    result = store.register_evidence(
        event_key="dev-9::evt-9",
        artifact_id="clip-01",
        content_type="video/mp4",
        registered_by="op-admin",
        now=datetime.now(UTC),
    )
    assert result.verdict is EvidenceVerdict.UNKNOWN_EVENT


@pytest.mark.parametrize("content_type", ["text/html", "image/svg+xml", "application/javascript"])
def test_script_bearing_content_types_are_refused(store: EventStore, content_type: str) -> None:
    """열람 URL 에서 브라우저가 스크립트로 해석할 수 있는 타입은 증거가 아니다."""
    assert content_type not in ALLOWED_CONTENT_TYPES
    assert _register(store, content_type=content_type).verdict is (
        EvidenceVerdict.UNSUPPORTED_CONTENT_TYPE
    )


def test_tombstone_marks_without_deleting_record(store: EventStore) -> None:
    _register(store)
    result = store.tombstone_evidence(
        event_key="dev-1::evt-1",
        artifact_id="clip-01",
        reason="candidateDays 30일 경과",
        now=datetime.now(UTC),
    )
    assert result.artifact is not None
    assert result.artifact.is_tombstoned
    assert result.artifact.tombstone_reason == "candidateDays 30일 경과"
    # 레코드는 남는다 — 폐기 사실 자체가 감사 대상이다.
    artifact = store.get_evidence("dev-1::evt-1", "clip-01")
    assert artifact is not None and artifact.is_tombstoned


def test_tombstone_is_not_repeatable(store: EventStore) -> None:
    _register(store)

    def tombstone() -> EvidenceVerdict:
        return store.tombstone_evidence(
            event_key="dev-1::evt-1",
            artifact_id="clip-01",
            reason="만료",
            now=datetime.now(UTC),
        ).verdict

    assert tombstone() is EvidenceVerdict.REGISTERED
    assert tombstone() is EvidenceVerdict.ALREADY_TOMBSTONED


def test_tombstone_requires_reason(store: EventStore) -> None:
    """이유 없는 폐기는 기록의 값어치를 없앤다."""
    _register(store)
    result = store.tombstone_evidence(
        event_key="dev-1::evt-1", artifact_id="clip-01", reason="   ", now=datetime.now(UTC)
    )
    assert result.verdict is not EvidenceVerdict.REGISTERED


def test_naive_timestamp_is_refused(store: EventStore) -> None:
    with pytest.raises(ValueError, match="now"):
        _register(store, now=datetime(2026, 8, 4, 0, 0, 0))  # noqa: DTZ001 -- 의도적 naive


# ── CRITICAL RiskField 실증거 게이트 (INV-021) ───────────────────────────


def test_critical_confirmation_verifies_risk_field_bytes_and_snapshots_digest(
    store: EventStore, storage: FakeStorage, tmp_path: Path
) -> None:
    _project_critical_finding(store)
    raw = _register_critical_artifacts(store, storage)
    before = store.get("dev-1::evt-1")
    assert before is not None

    response = _client(store, storage, tmp_path).post(
        "/v1/events/dev-1::evt-1/transitions",
        json={
            "targetStatus": "CONFIRMED_EVENT",
            "reason": "RiskField 원문과 현장 증거 확인",
            "expectedBundleDigest": payload_digest(before.bundle),
        },
        headers=_auth(),
    )

    assert response.status_code == 200
    assert response.json()["verdict"] == "TRANSITIONED"
    transitioned = store.get("dev-1::evt-1")
    assert transitioned is not None and transitioned.status is EventStatus.CONFIRMED_EVENT
    snapshot = transitioned.transitions[-1]["evidenceSnapshot"]["riskFieldVerification"]
    assert snapshot["contentSha256"] == hashlib.sha256(raw).hexdigest()
    assert snapshot["contentLengthBytes"] == len(raw)
    assert snapshot["eventBundleDigest"] == payload_digest(before.bundle)
    assert snapshot["sourceEntityIds"] == ["ent-trk-001"]
    assert snapshot["geometryFormat"] == "PARAMETRIC_VOLUME"


def test_critical_confirmation_accepts_risk_field_v1_1_during_transition(
    store: EventStore, storage: FakeStorage, tmp_path: Path
) -> None:
    """Core 전이 reader는 기존 v1.0뿐 아니라 새 Edge v1.1 원문도 검증한다."""
    _project_critical_finding(store)
    _register_critical_artifacts(store, storage)
    payload = _risk_field_payload(
        schemaVersion="1.1",
        type="PREDICTED",
        geometry={
            "format": "EXTRUDED_POLYGON",
            "payload": {
                "vertices": [[100.0, 200.0], [101.0, 200.0], [101.0, 201.0]],
                "zMinM": 20.0,
                "zMaxM": 25.0,
            },
        },
        lineage={
            "riskPolicyPackDigest": "sha256:" + "a" * 64,
            "calibrationProfileId": "evidence-test-cal-1",
            "sourceTimestamp": "2026-08-04T00:00:00Z",
            "sensorTimestamp": "2026-08-04T00:00:00Z",
        },
    )
    risk_artifact = store.get_evidence("dev-1::evt-1", "risk-1")
    assert risk_artifact is not None
    raw = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    storage.put_bytes(risk_artifact.object_key, raw, content_type="application/json")
    before = store.get("dev-1::evt-1")
    assert before is not None

    response = _client(store, storage, tmp_path).post(
        "/v1/events/dev-1::evt-1/transitions",
        json={
            "targetStatus": "CONFIRMED_EVENT",
            "reason": "v1.1 RiskField 계보와 기하 확인",
            "expectedBundleDigest": payload_digest(before.bundle),
        },
        headers=_auth(),
    )

    assert response.status_code == 200
    assert response.json()["verdict"] == "TRANSITIONED"
    transitioned = store.get("dev-1::evt-1")
    assert transitioned is not None and transitioned.status is EventStatus.CONFIRMED_EVENT
    snapshot = transitioned.transitions[-1]["evidenceSnapshot"]["riskFieldVerification"]
    assert snapshot["schemaVersion"] == "1.1"
    assert snapshot["geometryFormat"] == "EXTRUDED_POLYGON"
    assert snapshot["contentSha256"] == hashlib.sha256(raw).hexdigest()


def test_critical_confirmation_requires_registered_artifacts(
    store: EventStore, storage: FakeStorage, tmp_path: Path
) -> None:
    _project_critical_finding(store)

    response = _client(store, storage, tmp_path).post(
        "/v1/events/dev-1::evt-1/transitions",
        json={"targetStatus": "CONFIRMED_EVENT", "reason": "문자열만 있음"},
        headers=_auth(),
    )

    assert response.status_code == 422
    assert response.json()["verdict"] == "EVIDENCE_INCOMPLETE"
    assert "등록되지 않았다" in response.json()["detail"]


def test_critical_confirmation_reports_storage_outage_separately(
    store: EventStore, storage: FakeStorage, tmp_path: Path
) -> None:
    _project_critical_finding(store)
    _register_critical_artifacts(store, storage)
    risk_artifact = store.get_evidence("dev-1::evt-1", "risk-1")
    assert risk_artifact is not None
    storage._blobs.pop(risk_artifact.object_key)

    response = _client(store, storage, tmp_path).post(
        "/v1/events/dev-1::evt-1/transitions",
        json={"targetStatus": "CONFIRMED_EVENT", "reason": "스토리지 장애"},
        headers=_auth(),
    )

    assert response.status_code == 503
    assert response.json()["verdict"] == "STORE_UNAVAILABLE"
    assert response.headers["retry-after"] == "30"
    assert store.get("dev-1::evt-1").status is EventStatus.FINDING  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("mutate", "detail"),
    [
        (lambda payload: payload.update({"riskFieldId": "other-risk"}), "riskFieldId"),
        (
            lambda payload: payload.update(
                {"geometry": {"format": "PARAMETRIC_VOLUME", "payload": {}}}
            ),
            "geometry.payload",
        ),
        (
            lambda payload: payload.update(
                {
                    "validity": {
                        "from": "2026-08-04T00:00:01Z",
                        "to": "2026-08-04T00:00:02Z",
                    }
                }
            ),
            "occurredAt",
        ),
        (lambda payload: payload.update({"sourceEntityIds": ["other-entity"]}), "entities"),
    ],
)
def test_critical_confirmation_rejects_semantically_invalid_risk_field(
    store: EventStore,
    storage: FakeStorage,
    tmp_path: Path,
    mutate: Any,
    detail: str,
) -> None:
    _project_critical_finding(store)
    _register_critical_artifacts(store, storage)
    payload = _risk_field_payload()
    mutate(payload)
    risk_artifact = store.get_evidence("dev-1::evt-1", "risk-1")
    assert risk_artifact is not None
    storage.put_bytes(
        risk_artifact.object_key,
        json.dumps(payload).encode("utf-8"),
        content_type="application/json",
    )

    response = _client(store, storage, tmp_path).post(
        "/v1/events/dev-1::evt-1/transitions",
        json={"targetStatus": "CONFIRMED_EVENT", "reason": "의미 검증"},
        headers=_auth(),
    )

    assert response.status_code == 422
    assert response.json()["verdict"] == "EVIDENCE_INCOMPLETE"
    assert detail in response.json()["detail"]


def test_critical_confirmation_rejects_tombstoned_reference(
    store: EventStore, storage: FakeStorage, tmp_path: Path
) -> None:
    _project_critical_finding(store)
    _register_critical_artifacts(store, storage)
    store.tombstone_evidence(
        event_key="dev-1::evt-1",
        artifact_id="trajectory-1",
        reason="보관 기한 만료",
        now=datetime.now(UTC),
    )

    response = _client(store, storage, tmp_path).post(
        "/v1/events/dev-1::evt-1/transitions",
        json={"targetStatus": "CONFIRMED_EVENT", "reason": "폐기 참조"},
        headers=_auth(),
    )

    assert response.status_code == 422
    assert "폐기됐다" in response.json()["detail"]


def test_critical_confirmation_detects_artifact_change_during_storage_read(
    store: EventStore,
    storage: FakeStorage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """스토리지 I/O 중 증거 상태가 바뀌면 검증한 것과 굳힌 것이 달라지지 않는다."""
    _project_critical_finding(store)
    _register_critical_artifacts(store, storage)
    original_get = storage.get_bytes

    def get_then_tombstone(object_key: str) -> bytes:
        raw = original_get(object_key)
        result = store.tombstone_evidence(
            event_key="dev-1::evt-1",
            artifact_id="trajectory-1",
            reason="검증 경합 주입",
            now=datetime.now(UTC),
        )
        assert result.verdict is EvidenceVerdict.REGISTERED
        return raw

    monkeypatch.setattr(storage, "get_bytes", get_then_tombstone)
    response = _client(store, storage, tmp_path).post(
        "/v1/events/dev-1::evt-1/transitions",
        json={"targetStatus": "CONFIRMED_EVENT", "reason": "경합 반증"},
        headers=_auth(),
    )

    assert response.status_code == 409
    assert response.json()["verdict"] == "STALE_EVENT_VIEW"
    assert store.get("dev-1::evt-1").status is EventStatus.FINDING  # type: ignore[union-attr]


# ── HTTP 표면 ──────────────────────────────────────────────────────────────


def test_upload_url_is_issued_after_permission_check(
    store: EventStore, storage: FakeStorage, tmp_path: Path
) -> None:
    client = _client(store, storage, tmp_path)
    response = client.post(
        "/v1/events/dev-1::evt-1/evidence",
        json={"artifactId": "clip-01", "contentType": "video/mp4"},
        headers=_auth(),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["objectKey"] == "sites/site-1/events/dev-1/evt-1/clip-01"
    assert body["uploadUrl"].startswith("https://storage.invalid/")
    assert storage.put_calls[0][0] == body["objectKey"]


def test_upload_requires_triage_permission(
    store: EventStore, storage: FakeStorage, tmp_path: Path
) -> None:
    client = _client(store, storage, tmp_path)
    response = client.post(
        "/v1/events/dev-1::evt-1/evidence",
        json={"artifactId": "clip-01", "contentType": "video/mp4"},
        headers=_auth(_VIEWER_TOKEN),
    )
    assert response.status_code == 403
    assert not storage.put_calls, "권한 검사 전에 URL 이 발급됐다"


def test_view_url_requires_read_permission_and_hides_storage(
    store: EventStore, storage: FakeStorage, tmp_path: Path
) -> None:
    _register(store)
    client = _client(store, storage, tmp_path)
    response = client.get("/v1/events/dev-1::evt-1/evidence/clip-01", headers=_auth(_VIEWER_TOKEN))
    assert response.status_code == 200
    assert response.json()["viewUrl"].endswith("?view=1")


def test_tombstoned_evidence_reads_as_gone_not_missing(
    store: EventStore, storage: FakeStorage, tmp_path: Path
) -> None:
    """410 Gone — '없음'이 아니라 '폐기됨'이다."""
    _register(store)
    store.tombstone_evidence(
        event_key="dev-1::evt-1", artifact_id="clip-01", reason="만료", now=datetime.now(UTC)
    )
    client = _client(store, storage, tmp_path)
    response = client.get("/v1/events/dev-1::evt-1/evidence/clip-01", headers=_auth())
    assert response.status_code == 410
    assert not storage.get_calls, "폐기된 객체에 URL 을 발급했다"


def test_storage_outage_is_not_reported_as_missing_evidence(
    store: EventStore, storage: FakeStorage, tmp_path: Path
) -> None:
    _register(store)
    storage.fail_with = EvidenceStorageError("연결 실패")
    client = _client(store, storage, tmp_path)
    response = client.get("/v1/events/dev-1::evt-1/evidence/clip-01", headers=_auth())
    assert response.status_code == 503


def test_unknown_artifact_is_404(store: EventStore, storage: FakeStorage, tmp_path: Path) -> None:
    client = _client(store, storage, tmp_path)
    response = client.get("/v1/events/dev-1::evt-1/evidence/nope", headers=_auth())
    assert response.status_code == 404


def test_routes_absent_without_storage(store: EventStore, tmp_path: Path) -> None:
    """조립되지 않은 기능은 존재하지 않는 편이 정직하다 — 2xx 로 보이면 안 된다."""
    client = _client(store, None, tmp_path)
    response = client.post(
        "/v1/events/dev-1::evt-1/evidence",
        json={"artifactId": "clip-01", "contentType": "video/mp4"},
        headers=_auth(),
    )
    assert response.status_code == 404


def test_evidence_storage_without_any_consumer_store_refuses_assembly() -> None:
    """소비자 저장소가 **하나도** 없으면 오브젝트 스토리지를 매단 채 기동하지 않는다.

    원래 이 가드는 ``event_store`` 만 요구했으나 3D 파이프라인 입구
    (``source_media_store``)가 같은 스토리지 포트의 두 번째 소비자가 되었고,
    2026-08-08 부터 임무 발급이 KMZ 바이트 보관으로 **세 번째** 소비자가 됐다
    (risk kmz-regeneration-determinism-timebomb) — 이 테스트가 확인하는 것은
    "셋 다 없을 때 거부"이지 특정 하나가 없을 때의 거부가 아니다.
    """
    with pytest.raises(ValueError, match="소비자 저장소"):
        create_app(
            auth_registry=_auth_registry(),
            evidence_storage=FakeStorage(),
            mission_signing_key=None,
        )
