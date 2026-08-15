"""Site 등록·상태머신 영속·조회·전이 계약 (ADR-KSI-008 §1/§4).

수동 조립(``FastAPI()`` + ``mount_auth`` + ``mount_sites``, ``tmp_path``)으로
검증한다. green≠작동 초점: 픽스처로 최종상태를 손주입하지 않고 UNMAPPED →
BASELINE_MAPPING → … → PATROL_READY 전 구간을 **실제 HTTP 전이**로 통과시킨다.
"""

from __future__ import annotations

import hashlib
import json
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

_FIELD_OPERATOR_TOKEN = "fo-plaintext-token"
_VIEWER_TOKEN = "viewer-plaintext-token"
_ADMIN_TOKEN = "admin-plaintext-token"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_FIELD_OPERATOR_TOKEN),
                principal=Principal(
                    principal_id="fo-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
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


def _aoi_payload(lat0: float = 37.5, lon0: float = 127.0, delta: float = 0.001) -> dict[str, Any]:
    """작은 유효 사각 AOI(자기교차·중복 꼭짓점 없음, 10km 범위 내)."""
    return {
        "vertices": [
            {"latDeg": lat0, "lonDeg": lon0},
            {"latDeg": lat0, "lonDeg": lon0 + delta},
            {"latDeg": lat0 + delta, "lonDeg": lon0 + delta},
            {"latDeg": lat0 + delta, "lonDeg": lon0},
        ]
    }


def _build_app(journal: DurableJournal, *, registry: AuthRegistry | None = None) -> FastAPI:
    app = FastAPI()
    mount_auth(app, registry if registry is not None else _registry())
    mount_sites(app, SiteStore(journal))
    return app


def _register(
    client: TestClient, site_id: str = "site-001", *, token: str = _FIELD_OPERATOR_TOKEN
) -> Any:
    return client.post(
        "/v1/sites",
        json={"siteId": site_id, "name": "테스트 현장", "siteFrame": _site_frame_payload()},
        headers=_auth(token),
    )


def _put_aoi(
    client: TestClient,
    site_id: str,
    *,
    aoi: dict[str, Any] | None = None,
    site_frame: dict[str, str] | None = None,
    token: str = _FIELD_OPERATOR_TOKEN,
) -> Any:
    return client.put(
        f"/v1/sites/{site_id}/aoi",
        json={
            "aoi": aoi if aoi is not None else _aoi_payload(),
            "siteFrame": site_frame if site_frame is not None else _site_frame_payload(),
        },
        headers=_auth(token),
    )


def _transition(
    client: TestClient,
    site_id: str,
    target_status: str,
    *,
    evidence: str = "evidence-1",
    reason: str = "reason-1",
    token: str = _FIELD_OPERATOR_TOKEN,
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


# ── AOI(Area of Interest) 영속 (수용기준 1~4) ────────────────────────────


def test_register_with_aoi_returns_it_on_get(tmp_path: Path) -> None:
    """[AC1] AOI 와 함께 등록한 현장을 조회하면 AOI 가 그대로 돌아온다."""
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    aoi = _aoi_payload()

    response = client.post(
        "/v1/sites",
        json={
            "siteId": "site-aoi-1",
            "name": "AOI 현장",
            "siteFrame": _site_frame_payload(),
            "aoi": aoi,
        },
        headers=_auth(_FIELD_OPERATOR_TOKEN),
    )
    assert response.status_code == 201
    assert response.json()["site"]["aoi"] == aoi

    fetched = client.get("/v1/sites/site-aoi-1", headers=_auth(_VIEWER_TOKEN))
    assert fetched.status_code == 200
    assert fetched.json()["aoi"] == aoi


def test_register_without_aoi_still_works_and_aoi_is_null(tmp_path: Path) -> None:
    """[AC2 전조] AOI 없이 등록한 현장도 정상 조회되고 aoi 는 null(기존 위저드 흐름 회귀 없음)."""
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)

    response = _register(client, "site-no-aoi")
    assert response.status_code == 201
    assert response.json()["site"]["aoi"] is None

    fetched = client.get("/v1/sites/site-no-aoi", headers=_auth(_VIEWER_TOKEN))
    assert fetched.status_code == 200
    assert fetched.json()["aoi"] is None


def test_put_aoi_sets_aoi_on_unmapped_site(tmp_path: Path) -> None:
    """[AC1] 등록 후 별도 PUT 으로도 AOI 를 설정할 수 있다(UNMAPPED, 전용 경로)."""
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    assert _register(client, "site-put-aoi").status_code == 201

    response = _put_aoi(client, "site-put-aoi")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verdict"] == "AOI_SET"
    assert body["site"]["aoi"] == _aoi_payload()


def test_put_aoi_replaces_existing_aoi_while_unmapped(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    original = _aoi_payload(delta=0.001)
    replacement = _aoi_payload(delta=0.002)

    assert client.post(
        "/v1/sites",
        json={
            "siteId": "site-replace-aoi",
            "name": "교체 현장",
            "siteFrame": _site_frame_payload(),
            "aoi": original,
        },
        headers=_auth(_FIELD_OPERATOR_TOKEN),
    ).status_code == 201

    response = _put_aoi(client, "site-replace-aoi", aoi=replacement)

    assert response.status_code == 200
    assert response.json()["site"]["aoi"] == replacement


def test_put_aoi_unknown_site_returns_404(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)

    response = _put_aoi(client, "no-such-site")

    assert response.status_code == 404
    assert response.json()["verdict"] == "UNKNOWN_SITE"


def test_put_aoi_mismatched_site_frame_rejected(tmp_path: Path) -> None:
    """[AC3] 현장 siteFrame 과 어긋나는 AOI(다른 좌표계 주장)는 거부된다."""
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    assert _register(client, "site-frame-mismatch").status_code == 201

    other_frame = _site_frame_payload()
    other_frame["crs"] = "EPSG:4326"
    response = _put_aoi(client, "site-frame-mismatch", site_frame=other_frame)

    assert response.status_code == 422
    assert response.json()["verdict"] == "SITE_FRAME_MISMATCH"


def test_put_aoi_locked_after_site_leaves_unmapped(tmp_path: Path) -> None:
    """[AC4] UNMAPPED 를 벗어난 현장의 AOI 변경은 거부된다(막는 쪽이 기본)."""
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    assert _register(client, "site-locked").status_code == 201
    assert _transition(client, "site-locked", "BASELINE_MAPPING").status_code == 200

    response = _put_aoi(client, "site-locked")

    assert response.status_code == 409
    assert response.json()["verdict"] == "AOI_LOCKED"


def test_put_aoi_malformed_polygon_rejected(tmp_path: Path) -> None:
    """구조 위반(꼭짓점 부족)은 AreaOfInterest 파싱 단계에서 표준 422 로 거부된다."""
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    assert _register(client, "site-malformed-aoi").status_code == 201

    response = _put_aoi(
        client, "site-malformed-aoi", aoi={"vertices": [{"latDeg": 0.0, "lonDeg": 0.0}]}
    )

    assert response.status_code == 422


def test_put_aoi_requires_sites_write_permission(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    assert _register(client, "site-aoi-403").status_code == 201

    response = _put_aoi(client, "site-aoi-403", token=_VIEWER_TOKEN)

    assert response.status_code == 403


# ── AOI journal 재생(구버전 레코드·재검증) ────────────────────────────────


def test_replay_of_legacy_registered_record_without_aoi_key(tmp_path: Path) -> None:
    """[AC2] AOI 필드 도입 이전에 기록된 site-registered 레코드(aoi 키 자체가
    없음)도 재생이 깨지지 않고 aoi=None 으로 복원된다."""
    journal_path = tmp_path / "sites.jsonl"
    seed = DurableJournal(journal_path)
    legacy_raw = _registered_raw_without_aoi_key("site-legacy")
    seed.append(legacy_raw)
    seed.close()

    store = SiteStore(DurableJournal(journal_path))
    record = store.get("site-legacy")

    assert record is not None
    assert record.aoi is None


def _registered_raw_without_aoi_key(site_id: str) -> dict[str, Any]:
    return {
        "kind": "site-registered",
        "ts": datetime.now(UTC).isoformat(),
        "actor": "tester",
        "before": None,
        "after": "UNMAPPED",
        "evidence": None,
        "reason": None,
        "siteId": site_id,
        "name": "구버전 현장",
        "siteFrame": _site_frame_payload(),
        # 의도적으로 "aoi" 키 자체가 없다 — 이 필드 도입 이전 레코드를 흉내낸다.
    }


def test_replay_refuses_startup_on_aoi_set_for_non_unmapped_site(tmp_path: Path) -> None:
    """site-aoi-set 레코드가 UNMAPPED 아닌 상태 뒤에 기록됐다면(버그·직접 조작)
    재생이 조용히 채택하지 않는다 — API 경계(AOI_LOCKED)와 같은 강도의 재검증."""
    journal_path = tmp_path / "sites.jsonl"
    seed = DurableJournal(journal_path)
    seed.append(_registered_raw("site-aoi-after-transition"))
    seed.append(_transitioned_raw("site-aoi-after-transition", "UNMAPPED", "BASELINE_MAPPING"))
    seed.append(
        {
            "kind": "site-aoi-set",
            "ts": datetime.now(UTC).isoformat(),
            "actor": "tester",
            "siteId": "site-aoi-after-transition",
            "aoi": _aoi_payload(),
        }
    )
    seed.close()

    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(journal_path))


def test_replay_refuses_startup_on_malformed_aoi_payload(tmp_path: Path) -> None:
    journal_path = tmp_path / "sites.jsonl"
    seed = DurableJournal(journal_path)
    raw = _registered_raw("site-bad-aoi")
    raw["aoi"] = {"vertices": [{"latDeg": 0.0, "lonDeg": 0.0}]}  # 꼭짓점 부족
    seed.append(raw)
    seed.close()

    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(journal_path))


# ── 전 구간 실전이 (픽스처 손주입 아님) ─────────────────────────────────


def test_full_lifecycle_unmapped_to_patrol_ready(tmp_path: Path) -> None:
    """자율 시작 승인(→PROVISIONAL_AUTONOMY)·정식 순찰 승인(→PATROL_READY)만
    ADMIN 토큰이 필요하다(ADR-KSI-015 D2) — 그 외 일상 전이는 FIELD_OPERATOR 기본
    토큰(``_transition`` 기본값)으로 그대로 굴러간다."""
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
    admin_gated = {"PROVISIONAL_AUTONOMY", "PATROL_READY"}
    for target in sequence:
        token = _ADMIN_TOKEN if target in admin_gated else _FIELD_OPERATOR_TOKEN
        response = _transition(client, site_id, target, token=token)
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
    """SUSPENDED 진입·이탈은 둘 다 관리자 전용이다(ADR-KSI-015 D2) — 이 테스트의
    초점은 도메인 전이 자체(적법/불법 resume)이므로 게이트를 통과하는 ADMIN
    토큰으로 전 구간을 돈다(게이트 자체의 403 반증은
    ``test_field_operator_forbidden_*`` 가 별도로 맡는다)."""
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    site_id = "site-suspend"

    assert _register(client, site_id).status_code == 201
    assert _transition(client, site_id, "BASELINE_MAPPING").status_code == 200

    suspend = _transition(client, site_id, "SUSPENDED", token=_ADMIN_TOKEN)
    assert suspend.status_code == 200
    assert suspend.json()["site"]["status"] == "SUSPENDED"
    assert suspend.json()["site"]["resumeTarget"] == "BASELINE_MAPPING"

    wrong_resume = _transition(client, site_id, "MODEL_PROCESSING", token=_ADMIN_TOKEN)
    assert wrong_resume.status_code == 409
    assert wrong_resume.json()["verdict"] == "ILLEGAL_TRANSITION"

    correct_resume = _transition(client, site_id, "BASELINE_MAPPING", token=_ADMIN_TOKEN)
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
    assert _transition(client1, site_id, "SUSPENDED", token=_ADMIN_TOKEN).status_code == 200
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

    assert _register(client, site_id, token=_FIELD_OPERATOR_TOKEN).status_code == 201
    transition_response = _transition(
        client, site_id, "BASELINE_MAPPING", token=_FIELD_OPERATOR_TOKEN
    )
    assert transition_response.status_code == 200

    records = journal.replay()
    assert len(records) == 2

    registered = records[0]
    assert registered["kind"] == "site-registered"
    assert registered["actor"] == "fo-1"
    assert "ts" in registered
    datetime.fromisoformat(registered["ts"])  # tz-aware UTC 파싱 가능해야 한다
    assert registered["before"] is None
    assert registered["after"] == "UNMAPPED"

    transitioned = records[1]
    assert transitioned["kind"] == "site-transitioned"
    assert transitioned["actor"] == "fo-1"
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


# ── 자율운영 승인 게이트(ADR-KSI-015 D2) — (from, to) 간선 쌍 기준 ────────────
#
# SITES_WRITE 만으로는 안 되고 SITES_AUTONOMY_APPROVE(ADMIN 전용)가 추가로
# 필요한 간선(자율 시작 승인·정식 순찰 승인·SUSPENDED 진입/복귀)과, 그 옆의
# "일상 진행은 그대로 막히지 않는다"를 양성/음성 쌍으로 고정한다. 특히
# PATROL_ACTIVE→PATROL_READY(순찰 복귀)는 목적지가 PATROL_READY 로 같아도
# 게이트되지 않는다 — 목적지 상태만 보고 판정하면 이 케이스가 잘못 막히는
# 함정이 있다(ADR D2 "주의" 항목).


def _advance_field_operator(client: TestClient, site_id: str, *targets: str) -> None:
    """UNMAPPED 로 갓 등록된 site 를 게이트 없는 간선만으로 전진시킨다(FIELD_OPERATOR)."""
    for target in targets:
        response = _transition(client, site_id, target, token=_FIELD_OPERATOR_TOKEN)
        assert response.status_code == 200, f"{target}: {response.text}"


def test_field_operator_forbidden_model_validation_to_provisional_autonomy(
    tmp_path: Path,
) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    site_id = "site-gate-1"
    assert _register(client, site_id, token=_FIELD_OPERATOR_TOKEN).status_code == 201
    _advance_field_operator(
        client, site_id, "BASELINE_MAPPING", "MODEL_PROCESSING", "MODEL_VALIDATION"
    )

    response = _transition(client, site_id, "PROVISIONAL_AUTONOMY", token=_FIELD_OPERATOR_TOKEN)

    assert response.status_code == 403


def test_admin_allowed_model_validation_to_provisional_autonomy(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    site_id = "site-gate-2"
    assert _register(client, site_id, token=_FIELD_OPERATOR_TOKEN).status_code == 201
    _advance_field_operator(
        client, site_id, "BASELINE_MAPPING", "MODEL_PROCESSING", "MODEL_VALIDATION"
    )

    response = _transition(client, site_id, "PROVISIONAL_AUTONOMY", token=_ADMIN_TOKEN)

    assert response.status_code == 200


def test_field_operator_forbidden_provisional_autonomy_to_patrol_ready(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    site_id = "site-gate-3"
    assert _register(client, site_id, token=_FIELD_OPERATOR_TOKEN).status_code == 201
    _advance_field_operator(
        client, site_id, "BASELINE_MAPPING", "MODEL_PROCESSING", "MODEL_VALIDATION"
    )
    assert (
        _transition(client, site_id, "PROVISIONAL_AUTONOMY", token=_ADMIN_TOKEN).status_code
        == 200
    )

    response = _transition(client, site_id, "PATROL_READY", token=_FIELD_OPERATOR_TOKEN)

    assert response.status_code == 403


def test_admin_allowed_provisional_autonomy_to_patrol_ready(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    site_id = "site-gate-4"
    assert _register(client, site_id, token=_FIELD_OPERATOR_TOKEN).status_code == 201
    _advance_field_operator(
        client, site_id, "BASELINE_MAPPING", "MODEL_PROCESSING", "MODEL_VALIDATION"
    )
    assert (
        _transition(client, site_id, "PROVISIONAL_AUTONOMY", token=_ADMIN_TOKEN).status_code
        == 200
    )

    response = _transition(client, site_id, "PATROL_READY", token=_ADMIN_TOKEN)

    assert response.status_code == 200


def test_field_operator_forbidden_suspend(tmp_path: Path) -> None:
    """모든 상태 → SUSPENDED — 출발 상태와 무관하게 항상 관리자 전용이다."""
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    site_id = "site-gate-5"
    assert _register(client, site_id, token=_FIELD_OPERATOR_TOKEN).status_code == 201

    response = _transition(client, site_id, "SUSPENDED", token=_FIELD_OPERATOR_TOKEN)

    assert response.status_code == 403


def test_admin_allowed_suspend(tmp_path: Path) -> None:
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    site_id = "site-gate-6"
    assert _register(client, site_id, token=_FIELD_OPERATOR_TOKEN).status_code == 201

    response = _transition(client, site_id, "SUSPENDED", token=_ADMIN_TOKEN)

    assert response.status_code == 200


def test_field_operator_forbidden_suspended_resume(tmp_path: Path) -> None:
    """SUSPENDED → 직전 상태(동적 resume) — 출발 상태 기준으로 관리자 전용이다."""
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    site_id = "site-gate-7"
    assert _register(client, site_id, token=_FIELD_OPERATOR_TOKEN).status_code == 201
    assert _transition(client, site_id, "SUSPENDED", token=_ADMIN_TOKEN).status_code == 200

    response = _transition(client, site_id, "UNMAPPED", token=_FIELD_OPERATOR_TOKEN)

    assert response.status_code == 403


def test_field_operator_allowed_unmapped_to_baseline_mapping(tmp_path: Path) -> None:
    """일상 현장 진행은 관리자 대기 없이 굴러간다(ADR D2 근거) — 회귀 방지."""
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    site_id = "site-gate-8"
    assert _register(client, site_id, token=_FIELD_OPERATOR_TOKEN).status_code == 201

    response = _transition(client, site_id, "BASELINE_MAPPING", token=_FIELD_OPERATOR_TOKEN)

    assert response.status_code == 200


def test_field_operator_allowed_patrol_active_to_patrol_ready(tmp_path: Path) -> None:
    """[함정 회귀 방지, ADR D2 "주의"] PATROL_READY 로 들어오는 간선이 둘이다 —
    최초 정식 승인(PROVISIONAL_AUTONOMY→)은 관리자 전용이지만, 순찰 후 정상
    복귀(PATROL_ACTIVE→)는 목적지가 같아도 FIELD_OPERATOR 가 그대로 한다.
    목적지 상태 하나만 보는 게이트라면 이 케이스가 잘못 막힌다."""
    app = _build_app(DurableJournal(tmp_path / "sites.jsonl"))
    client = TestClient(app)
    site_id = "site-gate-9"
    assert _register(client, site_id, token=_FIELD_OPERATOR_TOKEN).status_code == 201
    _advance_field_operator(
        client, site_id, "BASELINE_MAPPING", "MODEL_PROCESSING", "MODEL_VALIDATION"
    )
    assert (
        _transition(client, site_id, "PROVISIONAL_AUTONOMY", token=_ADMIN_TOKEN).status_code
        == 200
    )
    assert _transition(client, site_id, "PATROL_READY", token=_ADMIN_TOKEN).status_code == 200
    assert (
        _transition(client, site_id, "PATROL_ACTIVE", token=_FIELD_OPERATOR_TOKEN).status_code
        == 200
    )

    response = _transition(client, site_id, "PATROL_READY", token=_FIELD_OPERATOR_TOKEN)

    assert response.status_code == 200


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
            headers=_auth(_FIELD_OPERATOR_TOKEN),
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


# ── 공간모델 노후 기준 선언 (ADR-KSI-019 G1) ──────────────────────────


def _put_model_age_policy(
    client: TestClient,
    site_id: str,
    max_age_days: int | None,
    *,
    token: str = _FIELD_OPERATOR_TOKEN,
) -> Any:
    return client.put(
        f"/v1/sites/{site_id}/model-age-policy",
        json={"maxAgeDays": max_age_days},
        headers=_auth(token),
    )


def test_model_age_policy_defaults_to_undeclared(tmp_path: Path) -> None:
    """[핵심] 이 필드 도입 이전 journal 로 재생된 현장은 미선언이다.

    ``data_residency`` 와 같은 이유 — 구버전 레코드에 없던 필드의 기본값을 임의의
    숫자로 두면 기존 현장 전체가 조용히 어떤 노후 정책을 갖게 된다. 서버가 노후
    기준을 지어내지 않는다는 것이 ADR-KSI-019 G1 의 요점이다.
    """
    client = TestClient(_build_app(DurableJournal(tmp_path / "sites.jsonl")))
    _register(client)

    body = client.get("/v1/sites/site-001", headers=_auth(_FIELD_OPERATOR_TOKEN)).json()

    assert body["modelMaxAgeDays"] is None


def test_model_age_policy_can_be_declared_and_replaced(tmp_path: Path) -> None:
    client = TestClient(_build_app(DurableJournal(tmp_path / "sites.jsonl")))
    _register(client)

    first = _put_model_age_policy(client, "site-001", 30)
    assert first.status_code == 200
    assert first.json()["verdict"] == "MODEL_AGE_POLICY_SET"
    assert first.json()["site"]["modelMaxAgeDays"] == 30

    second = _put_model_age_policy(client, "site-001", 7)
    assert second.status_code == 200
    assert second.json()["site"]["modelMaxAgeDays"] == 7


def test_model_age_policy_can_be_withdrawn(tmp_path: Path) -> None:
    """선언을 되돌리는 경로가 있어야 한다 — 되돌릴 수 없는 정책은 정책이 아니다."""
    client = TestClient(_build_app(DurableJournal(tmp_path / "sites.jsonl")))
    _register(client)
    _put_model_age_policy(client, "site-001", 30)

    withdrawn = _put_model_age_policy(client, "site-001", None)

    assert withdrawn.status_code == 200
    assert withdrawn.json()["site"]["modelMaxAgeDays"] is None


def test_model_age_policy_is_not_locked_by_site_status(tmp_path: Path) -> None:
    """AOI 와 달리 현장 상태로 잠그지 않는다.

    현장의 변화 속도는 매핑 시작 이후에 알게 되는 사실이고, 그때 기준을 못 고치면
    정책이 첫 추측에 갇힌다.
    """
    client = TestClient(_build_app(DurableJournal(tmp_path / "sites.jsonl")))
    _register(client)
    _transition(client, "site-001", "BASELINE_MAPPING")

    assert _put_model_age_policy(client, "site-001", 14).status_code == 200


@pytest.mark.parametrize("bad", [0, -1])
def test_non_positive_age_policy_is_refused(tmp_path: Path, bad: int) -> None:
    """0 일·음수는 '매 순간 낡음'이라 정책이 아니라 사고다."""
    client = TestClient(_build_app(DurableJournal(tmp_path / "sites.jsonl")))
    _register(client)

    response = _put_model_age_policy(client, "site-001", bad)

    assert response.status_code == 422
    assert response.json()["verdict"] == "INVALID_SITE"


def test_model_age_policy_unknown_site_returns_404(tmp_path: Path) -> None:
    client = TestClient(_build_app(DurableJournal(tmp_path / "sites.jsonl")))

    assert _put_model_age_policy(client, "nope", 30).status_code == 404


def test_model_age_policy_requires_sites_write_permission(tmp_path: Path) -> None:
    client = TestClient(_build_app(DurableJournal(tmp_path / "sites.jsonl")))
    _register(client)

    assert _put_model_age_policy(client, "site-001", 30, token=_VIEWER_TOKEN).status_code == 403


def test_model_age_policy_survives_replay(tmp_path: Path) -> None:
    """journal 재생 후에도 선언이 남는다."""
    journal_path = tmp_path / "sites.jsonl"
    journal1 = DurableJournal(journal_path)
    client = TestClient(_build_app(journal1))
    _register(client)
    _put_model_age_policy(client, "site-001", 14)
    journal1.close()

    reopened = SiteStore(DurableJournal(journal_path))

    record = reopened.get("site-001")
    assert record is not None
    assert record.model_max_age_days == 14


def test_model_age_policy_records_actor_in_the_journal(tmp_path: Path) -> None:
    """누가 기준을 정했는지가 남는다 — 자율운영 가능 여부를 가르는 값이다."""
    journal_path = tmp_path / "sites.jsonl"
    client = TestClient(_build_app(DurableJournal(journal_path)))
    _register(client)
    _put_model_age_policy(client, "site-001", 21)

    records = [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    policy_records = [r for r in records if r["kind"] == "site-model-age-policy-set"]

    assert len(policy_records) == 1
    assert policy_records[0]["actor"] == "fo-1"
    assert policy_records[0]["maxAgeDays"] == 21
    assert policy_records[0]["before"] is None


def test_replay_refuses_age_policy_for_unregistered_site(tmp_path: Path) -> None:
    """오염된 원장으로 기동하지 않는다(fail-closed) — AOI 재생과 같은 원칙."""
    journal_path = tmp_path / "sites.jsonl"
    journal_path.write_text(
        json.dumps(
            {
                "kind": "site-model-age-policy-set",
                "ts": datetime.now(UTC).isoformat(),
                "actor": "fo-1",
                "siteId": "ghost",
                "before": None,
                "maxAgeDays": 30,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SiteStoreRecoveryError):
        SiteStore(DurableJournal(journal_path))
