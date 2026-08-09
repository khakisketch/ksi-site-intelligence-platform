"""장비 운동상태 수신 + CPA/TTC 위험 평가 계약 (Phase 3, PRD RISK-002/004/005).

초점은 셋이다.

**① 좌표계 없이 숫자를 받지 않는가.** 위치·속도는 site_frame 없이는 숫자일 뿐이다.
``cpa_ttc`` 의 site_frame 검사는 **두 상태끼리**만 보므로, 둘 다 같은 잘못된
좌표계로 신고되면 그대로 통과한다 — 그 구멍은 수신 시점에만 막을 수 있다.

**② 시간축을 넘어 값을 지어내지 않는가.** 10분 전 굴착기 상태와 방금 작업자
상태로 "TTC 2.1초"가 나오면 안 된다(risk cpa-ttc-observed-at-mismatch-unchecked).
그리고 그 거부가 200+빈값이 아니라 **422** 여야 한다 — 200 이면 화면이 안전하다고 읽는다.

**③ 재관찰 권고가 운영자에게 도달하는가.** needs_active_reobservation 은 프로덕션
호출부가 0건이었다(호출 8건이 전부 테스트).

green≠작동: 현장을 실제로 등록하고 HTTP 로 상태를 올린 뒤 조회 API 로 계산을 시킨다.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
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
from ksi_core.equipment_states import (
    EquipmentStateRecoveryError,
    EquipmentStateStore,
    EquipmentStateVerdict,
    mount_equipment_states,
)
from ksi_core.sites import SiteFrame, SiteStore

_DEVICE_TOKEN = "edge-device-token"  # noqa: S105 — 테스트 고정값
_VIEWER_TOKEN = "viewer-token"  # noqa: S105
_SITE_ID = "site-001"
_SITE_CRS = "EPSG:5186"
_SITE_FRAME = SiteFrame(
    crs=_SITE_CRS, vertical_datum="KNG2018", transform_version="v1", unit="meter"
)
_NOW = datetime(2026, 8, 8, 3, 0, tzinfo=UTC)
_COV3 = [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]
# 불확실성이 큰 관측 — trace=27 → sqrt≈5.196m. 재관찰 권고 문턱 테스트용.
_COV3_UNCERTAIN = [9.0, 0, 0, 0, 9.0, 0, 0, 0, 9.0]


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest(_DEVICE_TOKEN),
                principal=Principal(
                    principal_id="edge-1",
                    kind=PrincipalKind.EDGE_DEVICE,
                    role=None,
                    device_id="edge-001",
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
        ]
    )


def _state_payload(
    *,
    entity_id: str,
    position: list[float],
    velocity: list[float],
    observed_at: datetime = _NOW,
    site_frame: str = _SITE_CRS,
    covariance: list[float] | None = None,
    source_class: str = "Excavator",
) -> dict[str, Any]:
    cov = covariance if covariance is not None else _COV3
    return {
        "entityId": entity_id,
        "observedAt": observed_at.isoformat(),
        "siteFrame": site_frame,
        "position": position,
        "positionCovariance": cov,
        "velocity": velocity,
        "velocityCovariance": _COV3,
        "sourceClass": source_class,
    }


def _site_store(tmp_path: Path) -> SiteStore:
    store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    assert (
        store.register(
            _SITE_ID, "테스트 현장", _SITE_FRAME, data_residency=None, actor="op-1", now=_NOW
        ).verdict.value
        == "REGISTERED"
    )
    return store


@pytest.fixture
def store(tmp_path: Path) -> EquipmentStateStore:
    return EquipmentStateStore(
        DurableJournal(tmp_path / "equipment-states.jsonl"), site_store=_site_store(tmp_path)
    )


def _client(store: EquipmentStateStore, *, token: str = _DEVICE_TOKEN) -> TestClient:
    app = FastAPI()
    mount_auth(app, _registry())
    mount_equipment_states(app, store)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


def _post(client: TestClient, *states: dict[str, Any]) -> Any:
    return client.post(
        f"/v1/sites/{_SITE_ID}/equipment-states", json={"states": list(states)}
    )


def _seed_pair(
    store: EquipmentStateStore,
    *,
    subject_observed_at: datetime = _NOW,
    equipment_covariance: list[float] | None = None,
) -> None:
    """굴착기@(0,0,0) v=(1,0,0) / 작업자@(10,0,0) v=(-1,0,0) — 정면 접근."""
    response = _post(
        _client(store),
        _state_payload(
            entity_id="excavator-1",
            position=[0.0, 0.0, 0.0],
            velocity=[1.0, 0.0, 0.0],
            covariance=equipment_covariance,
        ),
        _state_payload(
            entity_id="worker-1",
            position=[10.0, 0.0, 0.0],
            velocity=[-1.0, 0.0, 0.0],
            observed_at=subject_observed_at,
            source_class="Worker",
        ),
    )
    assert response.status_code == 201, response.json()


def _assess(store: EquipmentStateStore, **overrides: Any) -> Any:
    params: dict[str, Any] = {
        "equipmentEntityId": "excavator-1",
        "subjectEntityId": "worker-1",
        "horizonS": 30.0,
        "combinedRadiusM": 2.0,
        "maxObservationGapS": 1.0,
        "positionUncertaintyThresholdM": 3.0,
    }
    params.update(overrides)
    return _client(store, token=_VIEWER_TOKEN).get(
        f"/v1/sites/{_SITE_ID}/risk-assessment", params=params
    )


# ── ① 좌표계 없이 숫자를 받지 않는다 ────────────────────────────────────────


def test_state_in_registered_site_frame_is_recorded(store: EquipmentStateStore) -> None:
    response = _post(
        _client(store),
        _state_payload(entity_id="excavator-1", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0]),
    )
    assert response.status_code == 201, response.json()
    assert response.json()["recordedCount"] == 1


def test_foreign_site_frame_is_rejected(store: EquipmentStateStore) -> None:
    """[핵심] cpa_ttc 의 site_frame 검사는 두 상태끼리만 본다 — 둘 다 같은 잘못된
    좌표계면 통과한다. 그 구멍은 수신 시점에만 막을 수 있다."""
    response = _post(
        _client(store),
        _state_payload(
            entity_id="excavator-1",
            position=[0.0, 0.0, 0.0],
            velocity=[0.0, 0.0, 0.0],
            site_frame="EPSG:4326",
        ),
    )
    assert response.status_code == 422
    assert response.json()["verdict"] == EquipmentStateVerdict.SITE_FRAME_MISMATCH.value


def test_batch_with_one_foreign_frame_records_nothing(store: EquipmentStateStore) -> None:
    client = _client(store)
    response = _post(
        client,
        _state_payload(entity_id="ok-1", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0]),
        _state_payload(
            entity_id="bad-1",
            position=[0.0, 0.0, 0.0],
            velocity=[0.0, 0.0, 0.0],
            site_frame="EPSG:4326",
        ),
    )
    assert response.status_code == 422
    listed = _client(store, token=_VIEWER_TOKEN).get(
        f"/v1/sites/{_SITE_ID}/equipment-states"
    ).json()
    assert listed["entityCount"] == 0


def test_unknown_site_is_rejected(store: EquipmentStateStore) -> None:
    response = _client(store).post(
        "/v1/sites/site-never-registered/equipment-states",
        json={
            "states": [
                _state_payload(
                    entity_id="e-1", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0]
                )
            ]
        },
    )
    assert response.status_code == 404
    assert response.json()["verdict"] == EquipmentStateVerdict.UNKNOWN_SITE.value


def test_operator_cannot_submit_states(store: EquipmentStateStore) -> None:
    """사람이 손으로 장비 위치·속도를 주장할 수 없다."""
    response = _post(
        _client(store, token=_VIEWER_TOKEN),
        _state_payload(entity_id="e-1", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0]),
    )
    assert response.status_code == 403


# ── 조회: 개체별 최신 ───────────────────────────────────────────────────────


def test_list_returns_latest_state_per_entity(store: EquipmentStateStore) -> None:
    client = _client(store)
    _post(
        client,
        _state_payload(entity_id="e-1", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0]),
    )
    _post(
        client,
        _state_payload(
            entity_id="e-1",
            position=[5.0, 0.0, 0.0],
            velocity=[1.0, 0.0, 0.0],
            observed_at=_NOW + timedelta(seconds=5),
        ),
    )
    listed = _client(store, token=_VIEWER_TOKEN).get(
        f"/v1/sites/{_SITE_ID}/equipment-states"
    ).json()
    assert listed["entityCount"] == 1
    assert listed["entities"][0]["state"]["position"] == [5.0, 0.0, 0.0]
    assert store.history(_SITE_ID, "e-1") != []
    assert len(store.history(_SITE_ID, "e-1")) == 2  # 덮어쓰지 않는다


def test_list_exposes_position_uncertainty(store: EquipmentStateStore) -> None:
    """화면이 "이 추정을 얼마나 믿을 수 있나"를 표시할 수 있어야 한다."""
    _post(
        _client(store),
        _state_payload(
            entity_id="e-1",
            position=[0.0, 0.0, 0.0],
            velocity=[0.0, 0.0, 0.0],
            covariance=_COV3_UNCERTAIN,
        ),
    )
    listed = _client(store, token=_VIEWER_TOKEN).get(
        f"/v1/sites/{_SITE_ID}/equipment-states"
    ).json()
    assert listed["entities"][0]["positionUncertaintyM"] == pytest.approx(27.0**0.5)


# ── ② 시간축을 넘어 값을 지어내지 않는다 ────────────────────────────────────


def test_risk_assessment_computes_cpa_and_ttc(store: EquipmentStateStore) -> None:
    """정면 접근 골든벡터: 상대위치 -10, 상대속도 +2 → CPA t=5s, 거리 0.
    합산반경 2m 진입은 |p+vt|=2 → t=4s."""
    _seed_pair(store)
    body = _assess(store).json()
    assert body["closestApproachTimeS"] == pytest.approx(5.0)
    assert body["closestApproachM"] == pytest.approx(0.0, abs=1e-9)
    assert body["timeToCollisionS"] == pytest.approx(4.0)
    assert body["observationGapS"] == 0.0


def test_stale_partner_state_is_422_not_a_silent_number(store: EquipmentStateStore) -> None:
    """[핵심 — risk cpa-ttc-observed-at-mismatch-unchecked] 10분 벌어진 두 상태로
    TTC 를 내지 않는다. 그리고 200+빈값이 아니라 422 다 — 200 이면 화면이
    '위험 없음'으로 읽는다."""
    _seed_pair(store, subject_observed_at=_NOW - timedelta(minutes=10))
    response = _assess(store)
    assert response.status_code == 422
    assert "observed_at" in response.json()["detail"]


def test_generous_gap_window_allows_the_same_pair(store: EquipmentStateStore) -> None:
    """허용창을 넓히면 같은 쌍이 계산된다 — 게이트가 무조건 막는 게 아니다."""
    _seed_pair(store, subject_observed_at=_NOW - timedelta(minutes=10))
    response = _assess(store, maxObservationGapS=700.0)
    assert response.status_code == 200
    assert response.json()["observationGapS"] == pytest.approx(600.0)


def test_ttc_outside_horizon_is_null_not_zero(store: EquipmentStateStore) -> None:
    """null 은 '위험 없음'이 아니라 '이 지평선 안에서는 확인되지 않음'이다."""
    _seed_pair(store)
    body = _assess(store, horizonS=1.0).json()
    assert body["timeToCollisionS"] is None
    assert body["horizonS"] == 1.0


def test_unknown_entity_is_404(store: EquipmentStateStore) -> None:
    _seed_pair(store)
    response = _assess(store, subjectEntityId="worker-does-not-exist")
    assert response.status_code == 404


# ── ③ 재관찰 권고가 도달한다 ────────────────────────────────────────────────


def test_reobservation_recommended_when_uncertainty_exceeds_threshold(
    store: EquipmentStateStore,
) -> None:
    """[핵심] needs_active_reobservation 이 API 필드로 나온다 — 프로덕션 호출부 0건
    이던 신호가 여기서 처음으로 운영자에게 닿는다.

    굴착기 공분산 trace=27 → 불확실성 ≈5.196m. 문턱 3m 초과 → 권고 True.
    """
    _seed_pair(store, equipment_covariance=_COV3_UNCERTAIN)
    assert _assess(store, positionUncertaintyThresholdM=3.0).json()[
        "reobservationRecommended"
    ] is True
    assert _assess(store, positionUncertaintyThresholdM=6.0).json()[
        "reobservationRecommended"
    ] is False


def test_reobservation_not_recommended_for_confident_states(
    store: EquipmentStateStore,
) -> None:
    """공분산 trace=3 → 불확실성 ≈1.73m. 문턱 3m 미만 → 권고 False."""
    _seed_pair(store)
    body = _assess(store, positionUncertaintyThresholdM=3.0).json()
    assert body["reobservationRecommended"] is False
    assert body["positionUncertaintyThresholdM"] == 3.0


def test_assessment_echoes_the_policy_inputs_it_used(store: EquipmentStateStore) -> None:
    """무슨 파라미터로 계산했는지가 응답에 남는다 — 숫자만 주면 다음 사람이 그
    값을 재검증할 수 없다(gridBasis 관습과 같은 사유)."""
    _seed_pair(store)
    body = _assess(store, horizonS=12.5, combinedRadiusM=3.5).json()
    assert body["horizonS"] == 12.5
    assert body["combinedRadiusM"] == 3.5
    assert body["equipmentEntityId"] == "excavator-1"
    assert body["subjectEntityId"] == "worker-1"


def test_assessment_requires_all_policy_parameters(store: EquipmentStateStore) -> None:
    """정책 파라미터에 서버 기본값을 두지 않는다 — 빠뜨리면 422 다."""
    _seed_pair(store)
    response = _client(store, token=_VIEWER_TOKEN).get(
        f"/v1/sites/{_SITE_ID}/risk-assessment",
        params={"equipmentEntityId": "excavator-1", "subjectEntityId": "worker-1"},
    )
    assert response.status_code == 422


# ── 재생도 같은 게이트를 탄다 ───────────────────────────────────────────────


def test_replay_restores_states(tmp_path: Path) -> None:
    sites = _site_store(tmp_path)
    journal_path = tmp_path / "equipment-states.jsonl"
    journal = DurableJournal(journal_path)
    first = EquipmentStateStore(journal, site_store=sites)
    _post(
        _client(first),
        _state_payload(entity_id="e-1", position=[1.0, 2.0, 3.0], velocity=[0.0, 0.0, 0.0]),
    )
    journal.close()

    reborn = DurableJournal(journal_path)
    try:
        reopened = EquipmentStateStore(reborn, site_store=sites)
        latest = reopened.latest(_SITE_ID, "e-1")
    finally:
        reborn.close()
    assert latest is not None
    assert latest.state.position == [1.0, 2.0, 3.0]


def test_replay_refuses_state_that_live_would_reject(tmp_path: Path) -> None:
    """journal 을 손으로 고쳐 다른 좌표계 상태를 되살릴 수 없다."""
    import json

    sites = _site_store(tmp_path)
    journal_path = tmp_path / "equipment-states.jsonl"
    journal_path.write_text(
        json.dumps(
            {
                "kind": "equipment-states-recorded",
                "ts": _NOW.isoformat(),
                "siteId": _SITE_ID,
                "reportedBy": "edge-1",
                "states": [
                    _state_payload(
                        entity_id="e-1",
                        position=[0.0, 0.0, 0.0],
                        velocity=[0.0, 0.0, 0.0],
                        site_frame="EPSG:4326",
                    )
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    journal = DurableJournal(journal_path)
    with pytest.raises(EquipmentStateRecoveryError, match="SITE_FRAME_MISMATCH"):
        EquipmentStateStore(journal, site_store=sites)
