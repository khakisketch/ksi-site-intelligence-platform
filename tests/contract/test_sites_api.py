"""Site 등록·상태머신 영속·조회·전이 계약 (ADR-KSI-008 §1/§4).

수동 조립(``FastAPI()`` + ``mount_auth`` + ``mount_sites``, ``tmp_path``)으로
검증한다. green≠작동 초점: 픽스처로 최종상태를 손주입하지 않고 UNMAPPED →
BASELINE_MAPPING → … → PATROL_READY 전 구간을 **실제 HTTP 전이**로 통과시킨다.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.sites import SiteStore, SiteStoreRecoveryError, mount_sites
from ksi_domain.enums import SiteStatus
from ksi_mission_contracts.models import SiteFrame

_SITE_MANAGER_TOKEN = "sm-plaintext-token"
_VIEWER_TOKEN = "viewer-plaintext-token"
_ADMIN_TOKEN = "admin-plaintext-token"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_SITE_MANAGER_TOKEN),
                principal=Principal(
                    principal_id="sm-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.SITE_MANAGER,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_VIEWER_TOKEN),
                principal=Principal(
                    principal_id="viewer-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest(_ADMIN_TOKEN),
                principal=Principal(
                    principal_id="admin-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            ),
        ]
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _site_frame_payload() -> dict[str, str]:
    return {
        "crs": "EPSG:5186",
        "verticalDatum": "KNGeoid2018",
        "unit": "meter",
        "transformVersion": "1.0.0",
    }


def _site_frame_model() -> SiteFrame:
    return SiteFrame.model_validate(_site_frame_payload())


def _build_app(journal: DurableJournal, *, registry: AuthRegistry | None = None) -> FastAPI:
    app = FastAPI()
    mount_auth(app, registry if registry is not None else _registry())
    mount_sites(app, SiteStore(journal))
    return app


def _register(
    client: TestClient, site_id: str = "site-001", *, token: str = _SITE_MANAGER_TOKEN
) -> Any:
    return client.post(
        "/v1/sites",
        json={"siteId": site_id, "name": "테스트 현장", "siteFrame": _site_frame_payload()},
        headers=_auth(token),
    )


def _transition(
    client: TestClient,
    site_id: str,
    target_status: str,
    *,
    evidence: str = "evidence-1",
    reason: str = "reason-1",
    token: str = _SITE_MANAGER_TOKEN,
    extra: dict[str, Any] | None = None,
) -> Any:
    body: dict[str, Any] = {"targetStatus": target_status, "evidence": evidence, "reason": reason}
    if extra:
        body.update(extra)
    return client.post(f"/v1/sites/{site_id}/transitions", json=body, headers=_auth(token))


# ── 등록 ──────────────────────────────────────────────────────────────


def test_register_returns_201_unmapped(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)

    response = _register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["verdict"] == "REGISTERED"
    assert body["site"]["siteId"] == "site-001"
    assert body["site"]["status"] == "UNMAPPED"
    assert body["site"]["resumeTarget"] is None


def test_duplicate_registration_rejected(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)

    first = _register(client)
    second = _register(client)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["verdict"] == "DUPLICATE_SITE_ID"


# ── 전 구간 실전이 (픽스처 손주입 아님) ─────────────────────────────────


def test_full_lifecycle_unmapped_to_patrol_ready(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    site_id = "site-lifecycle"

    assert _register(client, site_id).status_code == 201

    sequence = [
        "BASELINE_MAPPING",
        "MODEL_PROCESSING",
        "MODEL_VALIDATION",
        "PROVISIONAL_AUTONOMY",
        "PATROL_READY",
    ]
    for target in sequence:
        response = _transition(client, site_id, target)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["verdict"] == "TRANSITIONED"
        assert body["site"]["status"] == target

    final = client.get(f"/v1/sites/{site_id}", headers=_auth(_VIEWER_TOKEN))
    assert final.status_code == 200
    assert final.json()["status"] == "PATROL_READY"


def test_unmapped_to_patrol_ready_direct_rejected(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    site_id = "site-direct"

    assert _register(client, site_id).status_code == 201

    response = _transition(client, site_id, "PATROL_READY")

    assert response.status_code == 409
    assert response.json()["verdict"] == "ILLEGAL_TRANSITION"


# ── SUSPENDED resume 왕복 ────────────────────────────────────────────


def test_suspended_resume_roundtrip(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    site_id = "site-suspend"

    assert _register(client, site_id).status_code == 201
    assert _transition(client, site_id, "BASELINE_MAPPING").status_code == 200

    suspend = _transition(client, site_id, "SUSPENDED")
    assert suspend.status_code == 200
    assert suspend.json()["site"]["status"] == "SUSPENDED"
    assert suspend.json()["site"]["resumeTarget"] == "BASELINE_MAPPING"

    wrong_resume = _transition(client, site_id, "MODEL_PROCESSING")
    assert wrong_resume.status_code == 409
    assert wrong_resume.json()["verdict"] == "ILLEGAL_TRANSITION"

    correct_resume = _transition(client, site_id, "BASELINE_MAPPING")
    assert correct_resume.status_code == 200
    body = correct_resume.json()["site"]
    assert body["status"] == "BASELINE_MAPPING"
    assert body["resumeTarget"] is None


# ── 재기동 복구 ───────────────────────────────────────────────────────


def test_restart_recovery_preserves_status_and_resume_target(tmp_path: Path) -> None:
    journal_path = tmp_path / "sites.jsonl"
    site_id = "site-restart"

    journal1 = DurableJournal(journal_path)
    store1 = SiteStore(journal1)
    app1 = FastAPI()
    mount_auth(app1, _registry())
    mount_sites(app1, store1)
    client1 = TestClient(app1)

    assert _register(client1, site_id).status_code == 201
    assert _transition(client1, site_id, "BASELINE_MAPPING").status_code == 200
    assert _transition(client1, site_id, "SUSPENDED").status_code == 200
    journal1.close()

    journal2 = DurableJournal(journal_path)
    store2 = SiteStore(journal2)

    record = store2.get(site_id)
    assert record is not None
    assert record.status.value == "SUSPENDED"
    assert record.resume_target is not None
    assert record.resume_target.value == "BASELINE_MAPPING"


# ── 감사 필드 실재(journal replay 검증) ──────────────────────────────


def test_audit_fields_present_in_journal_records(tmp_path: Path) -> None:
    journal = DurableJournal(tmp_path / "sites.jsonl")
    app = _build_app(journal)
    client = TestClient(app)
    site_id = "site-audit"

    assert _register(client, site_id, token=_SITE_MANAGER_TOKEN).status_code == 201
    transition_response = _transition(
        client, site_id, "BASELINE_MAPPING", token=_SITE_MANAGER_TOKEN
    )
    assert transition_response.status_code == 200

    records = journal.replay()
    assert len(records) == 2

    registered = records[0]
    assert registered["kind"] == "site-registered"
    assert registered["actor"] == "sm-1"
    assert "ts" in registered
    datetime.fromisoformat(registered["ts"])  # tz-aware UTC 파싱 가능해야 한다
    assert registered["before"] is None
    assert registered["after"] == "UNMAPPED"

    transitioned = records[1]
    assert transitioned["kind"] == "site-transitioned"
    assert transitioned["actor"] == "sm-1"
    assert transitioned["before"] == "UNMAPPED"
    assert transitioned["after"] == "BASELINE_MAPPING"
    assert transitioned["evidence"] == "evidence-1"
    assert transitioned["reason"] == "reason-1"
    datetime.fromisoformat(transitioned["ts"])


def test_actor_cannot_be_forged_via_body(tmp_path: Path) -> None:
    journal = DurableJournal(tmp_path / "sites.jsonl")
    app = _build_app(journal)
    client = TestClient(app)
    site_id = "site-forge"

    assert _register(client, site_id).status_code == 201

    response = _transition(
        client, site_id, "BASELINE_MAPPING", extra={"actor": "someone-else"}
    )

    assert response.status_code == 422  # extra="forbid" 가 위조 필드를 거부한다

    records = journal.replay()
    # 위조 시도가 거부됐으니 원장에는 등록 레코드 1건만 있어야 한다.
    assert len(records) == 1


# ── 미지 site ─────────────────────────────────────────────────────────


def test_unknown_site_get_returns_404(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)

    response = client.get("/v1/sites/no-such-site", headers=_auth(_VIEWER_TOKEN))

    assert response.status_code == 404


def test_unknown_site_transition_returns_404(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)

    response = _transition(client, "no-such-site", "BASELINE_MAPPING")

    assert response.status_code == 404
    assert response.json()["verdict"] == "UNKNOWN_SITE"


# ── naive datetime 거부(직접 store 호출) ────────────────────────────


def test_register_rejects_naive_datetime(tmp_path: Path) -> None:
    store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))

    with pytest.raises(ValueError, match="tz-aware"):
        store.register(
            "site-naive", "Naive 현장", _site_frame_model(), actor="tester", now=datetime.now()  # noqa: DTZ005
        )


def test_transition_rejects_naive_datetime(tmp_path: Path) -> None:
    journal = DurableJournal(tmp_path / "sites.jsonl")
    store = SiteStore(journal)
    store.register(
        "site-naive-2", "Naive 현장 2", _site_frame_model(), actor="tester", now=datetime.now(UTC)
    )

    with pytest.raises(ValueError, match="tz-aware"):
        store.transition(
            "site-naive-2",
            SiteStatus.BASELINE_MAPPING,
            evidence="e",
            reason="r",
            actor="tester",
            now=datetime.now(),  # noqa: DTZ005
        )


# ── 401/403 ──────────────────────────────────────────────────────────


def test_401_without_token(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)

    response = client.get("/v1/sites")

    assert response.status_code == 401


def test_403_when_viewer_attempts_write(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)

    response = _register(client, token=_VIEWER_TOKEN)

    assert response.status_code == 403


def test_viewer_can_read(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    assert _register(client).status_code == 201

    response = client.get("/v1/sites", headers=_auth(_VIEWER_TOKEN))

    assert response.status_code == 200
    assert len(response.json()["sites"]) == 1


def test_admin_can_write(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)

    response = _register(client, token=_ADMIN_TOKEN)

    assert response.status_code == 201


def test_register_rejects_blank_site_frame_fields(tmp_path: Path) -> None:
    """[INV-020] crs·verticalDatum·transformVersion 공백은 422 INVALID_SITE.

    공유 SiteFrame 모델은 타입만 강제하므로 등록 경계가 비공백을 추가로 막는다 —
    좌표계 식별 불가능한 frame 으로 site 가 영속되는 경로 부재를 증명한다.
    """
    journal = DurableJournal(tmp_path / "sites.jsonl")
    client = TestClient(_build_app(journal))

    for field in ("crs", "verticalDatum", "transformVersion"):
        payload = _site_frame_payload()
        payload[field] = "   "
        response = client.post(
            "/v1/sites",
            json={"siteId": f"site-blank-{field}", "name": "테스트 현장", "siteFrame": payload},
            headers=_auth(_SITE_MANAGER_TOKEN),
        )
        assert response.status_code == 422, field
        assert response.json()["verdict"] == "INVALID_SITE", field

    # 거부된 등록은 journal 에 아무 레코드도 남기지 않는다.
    assert journal.replay() == []
    journal.close()


# ── SiteStore 재생 fail-closed (재검토 지적 #2) ───────────────────────────
# 픽스처로 최종상태를 손주입하지 않는다 — 오염 레코드를 journal 에 직접
# append 한 뒤 새 SiteStore 기동이 SiteStoreRecoveryError 로 실제 거부됨을
# 증명한다(재생이 API 경계와 같은 강도로 검증하는지의 반증).


def _registered_raw(
    site_id: str = "site-corrupt",
    *,
    name: str = "오염 테스트",
    ts: str | None = None,
    site_frame: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "site-registered",
        "ts": ts if ts is not None else datetime.now(UTC).isoformat(),
        "actor": "tester",
        "before": None,
        "after": "UNMAPPED",
        "evidence": None,
        "reason": None,
        "siteId": site_id,
        "name": name,
        "siteFrame": site_frame if site_frame is not None else _site_frame_payload(),
    }


def _transitioned_raw(
    site_id: str,
    before: str,
    after: str,
    *,
    ts: str | None = None,
    evidence: str = "evidence-1",
    reason: str = "reason-1",
) -> dict[str, Any]:
    return {
        "kind": "site-transitioned",
        "ts": ts if ts is not None else datetime.now(UTC).isoformat(),
        "actor": "tester",
        "before": before,
        "after": after,
        "evidence": evidence,
        "reason": reason,
        "siteId": site_id,
    }


def test_replay_refuses_startup_on_illegal_transition_sequence(tmp_path: Path) -> None:
    """UNMAPPED -> PATROL_READY 직행이 어떻게든 journal 에 기록됐다면(버그·직접
    조작) 재생이 그 상태를 조용히 채택하지 않는다."""
    journal_path = tmp_path / "sites.jsonl"
    seed = DurableJournal(journal_path)
    seed.append(_registered_raw("site-illegal"))
    seed.append(_transitioned_raw("site-illegal", "UNMAPPED", "PATROL_READY"))
    seed.close()

    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(journal_path))


def test_replay_refuses_startup_on_unknown_kind(tmp_path: Path) -> None:
    journal_path = tmp_path / "sites.jsonl"
    seed = DurableJournal(journal_path)
    seed.append({"kind": "site-bogus-kind", "siteId": "site-x"})
    seed.close()

    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(journal_path))


def test_replay_refuses_startup_on_missing_field(tmp_path: Path) -> None:
    """등록 레코드에서 필수 필드(``name``)가 결손되면 KeyError 가 fail-closed 로 승격된다."""
    journal_path = tmp_path / "sites.jsonl"
    seed = DurableJournal(journal_path)
    raw = _registered_raw("site-missing-field")
    del raw["name"]
    seed.append(raw)
    seed.close()

    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(journal_path))


def test_replay_refuses_startup_on_naive_timestamp(tmp_path: Path) -> None:
    journal_path = tmp_path / "sites.jsonl"
    seed = DurableJournal(journal_path)
    seed.append(_registered_raw("site-naive-ts", ts="2026-01-01T00:00:00"))  # naive
    seed.close()

    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(journal_path))


def test_replay_refuses_startup_on_duplicate_registration(tmp_path: Path) -> None:
    journal_path = tmp_path / "sites.jsonl"
    seed = DurableJournal(journal_path)
    seed.append(_registered_raw("site-dup"))
    seed.append(_registered_raw("site-dup"))
    seed.close()

    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(journal_path))


def test_replay_refuses_startup_on_transition_for_unknown_site(tmp_path: Path) -> None:
    journal_path = tmp_path / "sites.jsonl"
    seed = DurableJournal(journal_path)
    seed.append(_transitioned_raw("site-never-registered", "UNMAPPED", "BASELINE_MAPPING"))
    seed.close()

    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(journal_path))


def test_replay_refuses_startup_on_before_state_mismatch(tmp_path: Path) -> None:
    """journal 에 기록된 ``before`` 가 재생 중인 projection 의 실제 상태와 다르면 거부한다."""
    journal_path = tmp_path / "sites.jsonl"
    seed = DurableJournal(journal_path)
    seed.append(_registered_raw("site-mismatch"))
    # 실제로는 register 직후라 UNMAPPED 인데, before 를 BASELINE_MAPPING 으로 위조
    seed.append(_transitioned_raw("site-mismatch", "BASELINE_MAPPING", "MODEL_PROCESSING"))
    seed.close()

    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(journal_path))


# ── 재생 경로의 INV-020/evidence·reason 재검증 (재검토 지적 #3) ──────────


def test_replay_refuses_startup_on_blank_site_frame_field(tmp_path: Path) -> None:
    """등록 레코드의 siteFrame.crs 가 공백이면(API 경계를 우회해 기록됐다면
    가정) 재생도 이를 INV-020 위반으로 거부한다 — 재생이 API 와 다른 강도로
    검증하지 않는다."""
    journal_path = tmp_path / "sites.jsonl"
    frame = _site_frame_payload()
    frame["crs"] = "   "
    seed = DurableJournal(journal_path)
    seed.append(_registered_raw("site-blank-frame", site_frame=frame))
    seed.close()

    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(journal_path))


def test_replay_refuses_startup_on_blank_evidence(tmp_path: Path) -> None:
    journal_path = tmp_path / "sites.jsonl"
    seed = DurableJournal(journal_path)
    seed.append(_registered_raw("site-blank-evidence"))
    seed.append(
        _transitioned_raw(
            "site-blank-evidence", "UNMAPPED", "BASELINE_MAPPING", evidence="   "
        )
    )
    seed.close()

    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(journal_path))


def test_replay_refuses_startup_on_blank_reason(tmp_path: Path) -> None:
    journal_path = tmp_path / "sites.jsonl"
    seed = DurableJournal(journal_path)
    seed.append(_registered_raw("site-blank-reason"))
    seed.append(
        _transitioned_raw("site-blank-reason", "UNMAPPED", "BASELINE_MAPPING", reason="   ")
    )
    seed.close()

    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(journal_path))


# ── UTC 정규화 (재검토 지적 #4) ────────────────────────────────────────


def test_register_normalizes_non_utc_offset_to_utc(tmp_path: Path) -> None:
    """+09:00 등 UTC 가 아닌 tz-aware ``now`` 로 등록해도 저장된 시각은 UTC 로 정규화된다."""
    store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    kst = timezone(timedelta(hours=9))
    now_kst = datetime(2026, 1, 1, 9, 0, 0, tzinfo=kst)  # == 2026-01-01T00:00:00Z

    result = store.register(
        "site-tz", "TZ 현장", _site_frame_model(), actor="tester", now=now_kst
    )

    assert result.record is not None
    assert result.record.registered_at.utcoffset() == timedelta(0)
    assert result.record.updated_at.utcoffset() == timedelta(0)
    assert result.record.registered_at == datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def test_transition_normalizes_non_utc_offset_to_utc(tmp_path: Path) -> None:
    store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    kst = timezone(timedelta(hours=9))
    store.register(
        "site-tz-2", "TZ 현장 2", _site_frame_model(), actor="tester", now=datetime.now(UTC)
    )

    now_kst = datetime(2026, 1, 2, 9, 30, 0, tzinfo=kst)  # == 2026-01-02T00:30:00Z
    result = store.transition(
        "site-tz-2",
        SiteStatus.BASELINE_MAPPING,
        evidence="e",
        reason="r",
        actor="tester",
        now=now_kst,
    )

    assert result.record is not None
    assert result.record.updated_at.utcoffset() == timedelta(0)
    assert result.record.updated_at == datetime(2026, 1, 2, 0, 30, 0, tzinfo=UTC)


# ── lone surrogate 거부 (재검토 지적 #5) ───────────────────────────────


def test_register_rejects_lone_surrogate_in_name(tmp_path: Path) -> None:
    """name 에 lone surrogate 가 들어오면 journal 기록 자체는 통과하더라도
    이후 응답 렌더링(UTF-8 인코딩)이 500 으로 붕괴한다 — 등록 경계에서 미리
    typed 422(INVALID_SITE)로 거부한다."""
    journal = DurableJournal(tmp_path / "sites.jsonl")
    store = SiteStore(journal)

    result = store.register(
        "site-surrogate-name",
        "a\ud800b",
        _site_frame_model(),
        actor="tester",
        now=datetime.now(UTC),
    )

    assert result.verdict.value == "INVALID_SITE"
    assert journal.replay() == []
    journal.close()


def test_register_rejects_lone_surrogate_in_site_frame(tmp_path: Path) -> None:
    journal = DurableJournal(tmp_path / "sites.jsonl")
    store = SiteStore(journal)
    frame = SiteFrame.model_validate(
        {
            "crs": "EPSG:5186",
            "verticalDatum": "a\ud800b",
            "unit": "meter",
            "transformVersion": "1.0.0",
        }
    )

    result = store.register(
        "site-surrogate-frame", "정상 이름", frame, actor="tester", now=datetime.now(UTC)
    )

    assert result.verdict.value == "INVALID_SITE"
    assert journal.replay() == []
    journal.close()


def test_register_rejects_lone_surrogate_in_site_id(tmp_path: Path) -> None:
    journal = DurableJournal(tmp_path / "sites.jsonl")
    store = SiteStore(journal)

    result = store.register(
        "site-\ud800-id", "정상 이름", _site_frame_model(), actor="tester", now=datetime.now(UTC)
    )

    assert result.verdict.value == "INVALID_SITE"
    assert journal.replay() == []
    journal.close()


def test_slash_in_site_id_is_rejected_not_trapped(tmp_path: Path) -> None:
    """[P2] '/' 포함 siteId 는 durable 등록 자체를 거부한다(영구 404 트랩 차단).

    siteId 는 그대로 /v1/sites/{site_id} 의 경로 세그먼트가 된다 — 검증 없이
    등록되면 조회·전이 라우트에 영구히 도달할 수 없는 site 가 만들어진다.
    """
    journal = DurableJournal(tmp_path / "sites.jsonl")
    store = SiteStore(journal)

    result = store.register(
        "site/1", "정상 이름", _site_frame_model(), actor="tester", now=datetime.now(UTC)
    )

    assert result.verdict.value == "INVALID_SITE"
    assert journal.replay() == []
    journal.close()


def test_replay_failure_releases_journal_lock(tmp_path: Path) -> None:
    """[P2] SiteStore 기동이 재생 오염으로 실패하면 journal flock 이 해제된다."""
    path = tmp_path / "sites.jsonl"
    seed = DurableJournal(path)
    seed.append({"kind": "not-a-real-kind", "siteId": "x"})
    seed.close()

    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(path))

    # 잠금이 해제됐다면 재조립이 flock 경합 없이 같은 예외로 재실패한다.
    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(path))
