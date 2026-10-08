"""TASK-2 Mission issuance OCC, atomic commit, retry and replay regressions."""

from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event, Lock
from typing import Any, Literal

import ksi_core.mission_issuance as issuance_module
import ksi_core.mission_plans as plans_module
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.acquisition import (
    AcquisitionCapability,
    AcquisitionConnectivityStore,
    AcquisitionCoordinationStore,
    AcquisitionDeploymentProfileV1,
    ConnectivitySnapshotV1,
)
from ksi_core.app import create_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.mission_atomicity import MissionIssuanceCommitter
from ksi_core.mission_records import (
    MissionRecord,
    MissionStore,
    MissionStoreRecoveryError,
)
from ksi_core.observation_work_orders import ObservationWorkOrderStore
from ksi_core.sites import SiteStore
from ksi_domain.enums import SiteStatus
from ksi_event_contracts.observation_work_order import (
    ObservationWorkOrder,
    ObservationWorkOrderStatus,
)
from ksi_mission_contracts.models import SiteFrame
from ksi_mission_planning import KmzBuildError, RouteGenerationError

_TOKEN = "mission-occ-field-operator"  # noqa: S105 -- test credential
_SITE_ID = "site-001"
_FRAME = {
    "crs": "EPSG:5186",
    "verticalDatum": "KNGeoid2018",
    "unit": "meter",
    "transformVersion": "1.0.0",
}


def _token_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_token_digest(_TOKEN),
                principal=Principal(
                    principal_id="field-operator-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.FIELD_OPERATOR,
                    device_id=None,
                ),
            )
        ]
    )


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_TOKEN}"}


def _contract_request(mission_id: str) -> dict[str, Any]:
    return {
        "missionId": mission_id,
        "siteId": _SITE_ID,
        "missionType": "BASELINE_MAPPING",
        "siteFrame": _FRAME,
        "flightEnvelope": {
            "allowedVolumes": ["volume-1"],
            "excludedVolumes": [],
            "minAltitudeM": 5.0,
            "maxAltitudeM": 120.0,
        },
        "objectives": ["baseline mapping"],
        "viewpointPolicyId": "vp-1",
        "riskPolicyPackId": "risk-1",
        "fallbackPolicyId": "fallback-1",
        "capturePolicyId": "capture-1",
    }


def _plan_request(mission_id: str, *, work_order_id: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "contract": _contract_request(mission_id),
        "aoi": {
            "vertices": [
                {"latDeg": 37.5, "lonDeg": 127.0},
                {"latDeg": 37.5, "lonDeg": 127.001},
                {"latDeg": 37.501, "lonDeg": 127.001},
                {"latDeg": 37.501, "lonDeg": 127.0},
            ]
        },
        "route": {"altitudeM": 40.0, "spacingM": 20.0, "captureIntervalM": 15.0},
        "drone": {
            "droneEnumValue": 99,
            "droneSubEnumValue": 0,
            "payloadEnumValue": 65534,
        },
        "wayline": {
            "autoFlightSpeedMs": 5.0,
            "takeoffSecurityHeightM": 20.0,
            "globalTransitionalSpeedMs": 10.0,
        },
    }
    if work_order_id is not None:
        payload["workOrderId"] = work_order_id
    return payload


def _profile() -> AcquisitionDeploymentProfileV1:
    return AcquisitionDeploymentProfileV1.model_validate(
        {
            "schemaVersion": "1.0",
            "siteId": _SITE_ID,
            "operatingMode": "RC_ATTENDED",
            "gatewayKind": "RC_PLUS_2",
            "gatewayTransports": ["WIFI", "CELLULAR"],
            "internetGate": "REQUIRED_FOR_MISSION_ISSUE",
            "manifoldDirectMode": "DISABLED",
            "routingPolicy": "RC_STANDARD",
            "mediaPolicy": "RESULTS_IMMEDIATE_RAW_POSTFLIGHT",
            "msdkBridgeMode": "CONDITIONAL_PREFLIGHT_POSTFLIGHT",
            "edgeDeviceId": "manifold-1",
            "gatewayDeviceId": "rc-plus-2-1",
        }
    )


def _snapshot(
    observed_at: datetime,
    *,
    snapshot_id: str,
    expires_at: datetime | None = None,
) -> ConnectivitySnapshotV1:
    return ConnectivitySnapshotV1.model_validate(
        {
            "schemaVersion": "1.0",
            "snapshotId": snapshot_id,
            "siteId": _SITE_ID,
            "gatewayDeviceId": "rc-plus-2-1",
            "edgeDeviceId": "manifold-1",
            "observedAt": observed_at.isoformat(),
            "expiresAt": (expires_at or observed_at + timedelta(minutes=2)).isoformat(),
            "transport": "WIFI",
            "internetReachable": True,
            "gatewayState": "CONNECTED",
            "edgeState": "CONNECTED",
            "directEdgeState": "DISABLED",
            "queuedEventCount": 0,
            "queuedMediaCount": 0,
            "lastSuccessReceiptId": None,
            "missionContractSync": "NOT_STARTED",
            "rawMediaSync": "NOT_STARTED",
            "capabilities": [
                {
                    "capability": capability.value,
                    "hardwareModel": "M4D-RC-PLUS-2-M3",
                    "firmwareVersion": "test",
                    "status": "VERIFIED",
                    "checkedAt": observed_at.isoformat(),
                    "evidenceRef": f"hil/{capability.value.lower()}",
                }
                for capability in AcquisitionCapability
            ],
        }
    )


@dataclass(slots=True)
class _Harness:
    app: FastAPI
    site_store: SiteStore
    mission_store: MissionStore
    mission_journal: DurableJournal
    work_order_store: ObservationWorkOrderStore | None
    work_order: ObservationWorkOrder | None
    acquisition_store: AcquisitionConnectivityStore | None


def _harness(
    tmp_path: Path,
    *,
    with_work_order: bool = False,
    acquisition_gate: bool = False,
    snapshot_expires_at: datetime | None = None,
) -> _Harness:
    now = datetime.now(UTC)
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    registered = site_store.register(
        _SITE_ID,
        "Mission OCC Site",
        SiteFrame.model_validate(_FRAME),
        actor="test-harness",
        now=now,
    )
    assert registered.verdict.value == "REGISTERED"

    mission_journal = DurableJournal(tmp_path / "missions.jsonl")
    mission_store = MissionStore(mission_journal)
    work_order_store: ObservationWorkOrderStore | None = None
    work_order: ObservationWorkOrder | None = None
    coordination_store: AcquisitionCoordinationStore | None = None
    acquisition_store: AcquisitionConnectivityStore | None = None

    if with_work_order:
        work_order_store = ObservationWorkOrderStore(
            DurableJournal(tmp_path / "work-orders.jsonl"),
            site_exists=lambda site_id, organization_id: (
                site_store.get_scoped(site_id, organization_id) is not None
            ),
        )
        created = work_order_store.create_work_order(
            organization_id="legacy",
            site_id=_SITE_ID,
            name="Atomic issuance",
            work_area_ids=["area-1"],
            schedule_id=None,
            actor="test-harness",
            now=now,
        )
        work_order = work_order_store.approve(
            created.work_order_id,
            organization_id="legacy",
            expected_version=created.version,
            actor="test-harness",
            now=now,
        )
        coordination_store = AcquisitionCoordinationStore(
            DurableJournal(tmp_path / "acquisition-runs.jsonl")
        )

    if with_work_order or acquisition_gate:
        acquisition_store = AcquisitionConnectivityStore(
            DurableJournal(tmp_path / "acquisition-connectivity.jsonl"),
            site_exists=lambda site_id, organization_id: (
                site_store.get_scoped(site_id, organization_id) is not None
            ),
        )
    if acquisition_gate:
        assert acquisition_store is not None
        acquisition_store.upsert_profile(
            _profile(), organization_id="legacy", actor="test-harness", now=now
        )
        acquisition_store.observe(
            _snapshot(now, snapshot_id="snapshot-1", expires_at=snapshot_expires_at),
            organization_id="legacy",
            actor="test-harness",
            now=now,
        )

    app = create_app(
        auth_registry=_registry(),
        site_store=site_store,
        mission_store=mission_store,
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="mission-occ-key",
        observation_work_order_store=work_order_store,
        acquisition_connectivity_store=acquisition_store,
        acquisition_coordination_store=coordination_store,
        acquisition_issue_gate_enabled=acquisition_gate,
    )
    return _Harness(
        app=app,
        site_store=site_store,
        mission_store=mission_store,
        mission_journal=mission_journal,
        work_order_store=work_order_store,
        work_order=work_order,
        acquisition_store=acquisition_store,
    )


def _post(app: FastAPI, path: str, payload: dict[str, Any]) -> Any:
    with TestClient(app) as client:
        return client.post(path, json=payload, headers=_headers())


def _install_post_sign_barrier(
    monkeypatch: pytest.MonkeyPatch,
    *,
    kind: Literal["contract", "pair"],
    signed: Event,
    release: Event,
) -> None:
    if kind == "contract":
        original_contract = issuance_module.issue_mission_contract

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            result = original_contract(*args, **kwargs)
            signed.set()
            assert release.wait(5)
            return result

        monkeypatch.setattr(issuance_module, "issue_mission_contract", wrapped)
    else:
        original_pair = plans_module.build_mission_plan

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            result = original_pair(*args, **kwargs)
            signed.set()
            assert release.wait(5)
            return result

        monkeypatch.setattr(plans_module, "build_mission_plan", wrapped)


def _suspend(store: SiteStore) -> None:
    result = store.transition(
        _SITE_ID,
        SiteStatus.SUSPENDED,
        evidence="concurrent suspend",
        reason="Mission OCC regression",
        actor="test-harness",
        now=datetime.now(UTC),
    )
    assert result.verdict.value == "TRANSITIONED"


@pytest.mark.parametrize("kind", ["contract", "pair"])
def test_site_suspended_after_signing_rejects_atomic_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: Literal["contract", "pair"]
) -> None:
    harness = _harness(tmp_path)
    signed, release = Event(), Event()
    _install_post_sign_barrier(monkeypatch, kind=kind, signed=signed, release=release)
    path = "/v1/missions/contracts" if kind == "contract" else "/v1/missions/plans"
    payload = (
        _contract_request(f"mission-suspended-{kind}")
        if kind == "contract"
        else _plan_request(f"mission-suspended-{kind}")
    )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_post, harness.app, path, payload)
        assert signed.wait(5)
        _suspend(harness.site_store)
        release.set()
        response = future.result(timeout=5)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "ISSUANCE_PRECONDITION_CHANGED — SITE_ISSUANCE_REVISION_CONFLICT"
    )
    mission_id = (
        payload["missionId"] if "missionId" in payload else payload["contract"]["missionId"]
    )
    assert harness.mission_store.get(mission_id) is None


@pytest.mark.parametrize("kind", ["contract", "pair"])
def test_site_aba_after_signing_is_rejected_by_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: Literal["contract", "pair"]
) -> None:
    harness = _harness(tmp_path)
    signed, release = Event(), Event()
    _install_post_sign_barrier(monkeypatch, kind=kind, signed=signed, release=release)
    mission_id = f"mission-aba-{kind}"
    path = "/v1/missions/contracts" if kind == "contract" else "/v1/missions/plans"
    payload = _contract_request(mission_id) if kind == "contract" else _plan_request(mission_id)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_post, harness.app, path, payload)
        assert signed.wait(5)
        _suspend(harness.site_store)
        resumed = harness.site_store.transition(
            _SITE_ID,
            SiteStatus.UNMAPPED,
            evidence="resume",
            reason="ABA regression",
            actor="test-harness",
            now=datetime.now(UTC),
        )
        assert resumed.verdict.value == "TRANSITIONED"
        assert resumed.record is not None and resumed.record.status is SiteStatus.UNMAPPED
        release.set()
        response = future.result(timeout=5)

    assert response.status_code == 409
    assert response.json()["detail"].endswith("SITE_ISSUANCE_REVISION_CONFLICT")
    assert harness.mission_store.get(mission_id) is None


def test_work_order_aba_same_authorizing_values_new_version_rejects_pair_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path, with_work_order=True)
    assert harness.work_order_store is not None and harness.work_order is not None
    signed, release = Event(), Event()
    _install_post_sign_barrier(monkeypatch, kind="pair", signed=signed, release=release)
    mission_id = "mission-work-order-race"
    payload = _plan_request(mission_id, work_order_id=harness.work_order.work_order_id)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_post, harness.app, "/v1/missions/plans", payload)
        assert signed.wait(5)
        changed = harness.work_order_store.link_mission(
            harness.work_order.work_order_id,
            organization_id="legacy",
            cycle_number=harness.work_order.cycle_number,
            mission_id="unrelated-mission",
            mission_site_id=_SITE_ID,
            actor="test-harness",
            now=datetime.now(UTC),
            require_approved=False,
        )
        assert changed.status.value == "APPROVED"
        assert changed.version == harness.work_order.version + 1
        release.set()
        response = future.result(timeout=5)

    assert response.status_code == 409
    assert response.json()["detail"].endswith("WORK_ORDER_REVISION_CONFLICT")
    assert harness.mission_store.get(mission_id) is None


def test_work_order_status_change_rejects_pair_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path, with_work_order=True)
    assert harness.work_order_store is not None and harness.work_order is not None
    signed, release = Event(), Event()
    _install_post_sign_barrier(monkeypatch, kind="pair", signed=signed, release=release)
    mission_id = "mission-work-order-status-race"
    payload = _plan_request(mission_id, work_order_id=harness.work_order.work_order_id)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_post, harness.app, "/v1/missions/plans", payload)
        assert signed.wait(5)
        changed = harness.work_order_store.record_status(
            harness.work_order.work_order_id,
            organization_id="legacy",
            status=ObservationWorkOrderStatus.DISPATCHED,
            status_reason=None,
            mission_ids=None,
            processing_job_ids=None,
            report_refs=None,
            actor="test-harness",
            now=datetime.now(UTC),
        )
        assert changed.status is ObservationWorkOrderStatus.DISPATCHED
        release.set()
        response = future.result(timeout=5)

    assert response.status_code == 409
    assert response.json()["detail"].endswith("WORK_ORDER_REVISION_CONFLICT")
    assert harness.mission_store.get(mission_id) is None


def test_new_acquisition_snapshot_rejects_signed_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path, acquisition_gate=True)
    assert harness.acquisition_store is not None
    signed, release = Event(), Event()
    _install_post_sign_barrier(monkeypatch, kind="contract", signed=signed, release=release)
    mission_id = "mission-acquisition-race"

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            _post,
            harness.app,
            "/v1/missions/contracts",
            _contract_request(mission_id),
        )
        assert signed.wait(5)
        now = datetime.now(UTC)
        harness.acquisition_store.observe(
            _snapshot(now, snapshot_id="snapshot-2"),
            organization_id="legacy",
            actor="test-harness",
            now=now,
        )
        release.set()
        response = future.result(timeout=5)

    assert response.status_code == 409
    assert response.json()["detail"].endswith("ACQUISITION_WITNESS_STALE")
    assert harness.mission_store.get(mission_id) is None


def test_acquisition_profile_aba_and_new_snapshot_rejects_original_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A->B->A profile values cannot revive the witness captured with snapshot A."""

    harness = _harness(tmp_path, acquisition_gate=True)
    assert harness.acquisition_store is not None
    signed, release = Event(), Event()
    _install_post_sign_barrier(monkeypatch, kind="contract", signed=signed, release=release)
    mission_id = "mission-acquisition-aba"

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            _post,
            harness.app,
            "/v1/missions/contracts",
            _contract_request(mission_id),
        )
        assert signed.wait(5)
        now = datetime.now(UTC)
        original_profile = _profile()
        intermediate_profile = AcquisitionDeploymentProfileV1.model_validate(
            {
                **original_profile.model_dump(mode="json", by_alias=True),
                "gatewayTransports": ["WIFI"],
            }
        )
        harness.acquisition_store.upsert_profile(
            intermediate_profile,
            organization_id="legacy",
            actor="test-harness",
            now=now,
        )
        harness.acquisition_store.upsert_profile(
            original_profile,
            organization_id="legacy",
            actor="test-harness",
            now=now + timedelta(milliseconds=1),
        )
        restored_at = now + timedelta(milliseconds=2)
        harness.acquisition_store.observe(
            _snapshot(restored_at, snapshot_id="snapshot-after-aba"),
            organization_id="legacy",
            actor="test-harness",
            now=restored_at,
        )
        release.set()
        response = future.result(timeout=5)

    assert response.status_code == 409
    assert response.json()["detail"].endswith("ACQUISITION_WITNESS_STALE")
    assert harness.mission_store.get(mission_id) is None


def test_snapshot_expiry_after_signing_rejects_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expires_at = datetime.now(UTC) + timedelta(milliseconds=700)
    harness = _harness(
        tmp_path,
        acquisition_gate=True,
        snapshot_expires_at=expires_at,
    )
    signed, release = Event(), Event()
    _install_post_sign_barrier(monkeypatch, kind="contract", signed=signed, release=release)
    mission_id = "mission-snapshot-expiry"

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            _post,
            harness.app,
            "/v1/missions/contracts",
            _contract_request(mission_id),
        )
        assert signed.wait(5)
        while datetime.now(UTC) < expires_at + timedelta(milliseconds=20):
            time.sleep(0.01)
        release.set()
        response = future.result(timeout=5)

    assert response.status_code == 409
    assert response.json()["detail"].endswith("ACQUISITION_WITNESS_STALE")
    assert harness.mission_store.get(mission_id) is None


def test_two_concurrent_identical_contract_issuances_append_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path)
    rendezvous = Barrier(2)
    original = issuance_module.issue_mission_contract

    def synchronized_sign(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        rendezvous.wait(timeout=5)
        return result

    monkeypatch.setattr(issuance_module, "issue_mission_contract", synchronized_sign)
    payload = _contract_request("mission-concurrent")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_post, harness.app, "/v1/missions/contracts", payload)
            for _ in range(2)
        ]
        responses = [future.result(timeout=5) for future in futures]

    assert sorted(response.status_code for response in responses) == [200, 201]
    assert responses[0].json() == responses[1].json()
    assert len(harness.mission_store.list_scoped(organization_id="legacy")) == 1
    assert len(harness.mission_journal.replay()) == 1


@pytest.mark.parametrize("kind", ["contract", "pair"])
def test_durable_winner_reconciles_matching_retry_after_prerequisite_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: Literal["contract", "pair"]
) -> None:
    """A stale loser must read the durable winner, not overwrite it with a typed 409."""

    harness = _harness(tmp_path)
    original_commit = MissionIssuanceCommitter.commit
    mission_id = f"mission-winner-{kind}"
    signed = Barrier(2)
    winner_durable, release_winner, allow_loser = Event(), Event(), Event()
    call_lock = Lock()
    calls = 0

    if kind == "contract":
        original_sign = issuance_module.issue_mission_contract

        def synchronized_sign(*args: Any, **kwargs: Any) -> Any:
            result = original_sign(*args, **kwargs)
            signed.wait(timeout=5)
            return result

        monkeypatch.setattr(issuance_module, "issue_mission_contract", synchronized_sign)
    else:
        original_build = plans_module.build_mission_plan
        build_lock = Lock()
        build_calls = 0

        def synchronized_build(*args: Any, **kwargs: Any) -> Any:
            nonlocal build_calls
            result = original_build(*args, **kwargs)
            with build_lock:
                build_calls += 1
                original_issuance_attempt = build_calls <= 2
            if original_issuance_attempt:
                signed.wait(timeout=5)
            return result

        monkeypatch.setattr(plans_module, "build_mission_plan", synchronized_build)

    def winner_then_stale(
        self: MissionIssuanceCommitter, record: MissionRecord, witness: Any
    ) -> Any:
        nonlocal calls
        with call_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            verdict = original_commit(self, record, witness)
            winner_durable.set()
            assert release_winner.wait(5)
            return verdict
        assert allow_loser.wait(5)
        return original_commit(self, record, witness)

    monkeypatch.setattr(MissionIssuanceCommitter, "commit", winner_then_stale)
    path = "/v1/missions/contracts" if kind == "contract" else "/v1/missions/plans"
    payload = _contract_request(mission_id) if kind == "contract" else _plan_request(mission_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_post, harness.app, path, payload),
            pool.submit(_post, harness.app, path, payload),
        ]
        assert winner_durable.wait(5)
        _suspend(harness.site_store)
        release_winner.set()
        allow_loser.set()
        responses = [future.result(timeout=15) for future in futures]

    assert sorted(response.status_code for response in responses) == [200, 201]
    assert harness.mission_store.get(mission_id) is not None
    assert len(harness.mission_journal.replay()) == 1


def test_mission_issuance_openapi_declares_exact_retry_and_typed_conflicts() -> None:
    document = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "contracts/api/openapi-core.yaml").read_text()
    )
    for path in ("/v1/missions/contracts", "/v1/missions/plans"):
        responses = document["paths"][path]["post"]["responses"]
        schema = responses["200"]["content"]["application/json"]["schema"]
        assert schema
        description = responses["409"]["description"]
        for subreason in (
            "MISSION_ID_CONFLICT",
            "ISSUANCE_PRECONDITION_CHANGED",
            "SITE_ISSUANCE_REVISION_CONFLICT",
            "WORK_ORDER_REVISION_CONFLICT",
            "ACQUISITION_WITNESS_STALE",
        ):
            assert subreason in description


def test_site_transition_waits_until_mission_append_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path)
    entered, release = Event(), Event()
    original = MissionStore.record_issuance

    def blocked_append(self: MissionStore, record: MissionRecord) -> Any:
        if record.issuance_schema_version == "1.0":
            entered.set()
            assert release.wait(5)
        return original(self, record)

    monkeypatch.setattr(MissionStore, "record_issuance", blocked_append)
    with ThreadPoolExecutor(max_workers=2) as pool:
        issue = pool.submit(
            _post,
            harness.app,
            "/v1/missions/contracts",
            _contract_request("mission-linearized"),
        )
        assert entered.wait(5)
        transition = pool.submit(_suspend, harness.site_store)
        time.sleep(0.1)
        assert not transition.done(), "Site mutation must wait while Mission append owns Site guard"
        release.set()
        response = issue.result(timeout=5)
        transition.result(timeout=5)

    assert response.status_code == 201
    assert harness.mission_store.get("mission-linearized") is not None
    assert harness.site_store.get(_SITE_ID).status is SiteStatus.SUSPENDED  # type: ignore[union-attr]


def test_terminal_mission_append_holds_all_prerequisite_guards_without_deadlock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Actual mutation paths wait behind Site->WorkOrder->Acquisition->Mission commit."""

    harness = _harness(tmp_path, with_work_order=True, acquisition_gate=True)
    assert harness.work_order_store is not None
    assert harness.work_order is not None
    assert harness.acquisition_store is not None
    work_order_store = harness.work_order_store
    work_order = harness.work_order
    acquisition_store = harness.acquisition_store
    entered, release = Event(), Event()
    original = MissionStore.record_issuance

    def blocked_append(self: MissionStore, record: MissionRecord) -> Any:
        if record.issuance_schema_version == "1.0":
            entered.set()
            assert release.wait(5)
        return original(self, record)

    monkeypatch.setattr(MissionStore, "record_issuance", blocked_append)
    payload = _plan_request(
        "mission-all-guards", work_order_id=work_order.work_order_id
    )

    def mutate_work_order() -> None:
        work_order_store.link_mission(
            work_order.work_order_id,
            organization_id="legacy",
            cycle_number=work_order.cycle_number,
            mission_id="concurrent-work-order-mutation",
            mission_site_id=_SITE_ID,
            actor="test-harness",
            now=datetime.now(UTC),
            require_approved=False,
        )

    def mutate_acquisition() -> None:
        observed_at = datetime.now(UTC)
        acquisition_store.observe(
            _snapshot(observed_at, snapshot_id="snapshot-concurrent-mutation"),
            organization_id="legacy",
            actor="test-harness",
            now=observed_at,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        issue = pool.submit(_post, harness.app, "/v1/missions/plans", payload)
        assert entered.wait(5)
        mutations = [
            pool.submit(_suspend, harness.site_store),
            pool.submit(mutate_work_order),
            pool.submit(mutate_acquisition),
        ]
        time.sleep(0.1)
        assert all(not future.done() for future in mutations)
        release.set()
        response = issue.result(timeout=5)
        for future in mutations:
            future.result(timeout=5)

    assert response.status_code == 201
    assert harness.mission_store.get("mission-all-guards") is not None


def test_route_kmz_and_signing_failures_leave_no_mission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    route_harness = _harness(tmp_path / "route")

    def route_failure(*_args: Any, **_kwargs: Any) -> Any:
        raise RouteGenerationError("route generation failed")

    monkeypatch.setattr(plans_module, "lawnmower_route", route_failure)
    route_response = _post(
        route_harness.app,
        "/v1/missions/plans",
        _plan_request("mission-route-failure"),
    )
    assert route_response.status_code == 422
    assert route_harness.mission_store.get("mission-route-failure") is None

    monkeypatch.undo()
    kmz_harness = _harness(tmp_path / "kmz")

    def kmz_failure(*_args: Any, **_kwargs: Any) -> Any:
        raise KmzBuildError("KMZ generation failed")

    monkeypatch.setattr(plans_module, "build_kmz", kmz_failure)
    kmz_response = _post(
        kmz_harness.app,
        "/v1/missions/plans",
        _plan_request("mission-kmz-failure"),
    )
    assert kmz_response.status_code == 422
    assert kmz_harness.mission_store.get("mission-kmz-failure") is None

    monkeypatch.undo()
    signing_harness = _harness(tmp_path / "signing")

    def signing_failure(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("signing failed")

    monkeypatch.setattr(issuance_module, "issue_mission_contract", signing_failure)
    with TestClient(signing_harness.app, raise_server_exceptions=False) as client:
        signing_response = client.post(
            "/v1/missions/contracts",
            json=_contract_request("mission-signing-failure"),
            headers=_headers(),
        )
    assert signing_response.status_code == 500
    assert signing_harness.mission_store.get("mission-signing-failure") is None


def test_new_writer_witness_replays_and_response_loss_retry_is_exactly_once(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    payload = _contract_request("mission-response-loss")
    first = _post(harness.app, "/v1/missions/contracts", payload)
    assert first.status_code == 201
    record = harness.mission_store.get("mission-response-loss")
    assert record is not None
    assert record.issuance_schema_version == "1.0"
    assert record.authorization_witness is not None
    assert record.issuance_request_digest == record.authorization_witness.request_digest

    harness.mission_journal.close()
    replay_journal = DurableJournal(tmp_path / "missions.jsonl")
    replay_store = MissionStore(replay_journal)
    replay_app = create_app(
        auth_registry=_registry(),
        site_store=harness.site_store,
        mission_store=replay_store,
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="mission-occ-restart-key",
    )
    retry = _post(replay_app, "/v1/missions/contracts", payload)
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert len(replay_store.list_scoped(organization_id="legacy")) == 1
    assert replay_store.get("mission-response-loss") == record


def test_legacy_record_is_readable_but_not_assumed_idempotent(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    payload = _contract_request("mission-legacy")
    legacy = MissionRecord(
        mission_id="mission-legacy",
        site_id=_SITE_ID,
        mission_type="BASELINE_MAPPING",
        artifact_kind="contract",
        contract={"schemaVersion": "1.2", "missionId": "mission-legacy"},
        kmz_sha256=None,
        route_pattern=None,
        waypoint_count=None,
        planned_coverage_ratio=None,
        issued_at=datetime.now(UTC),
        issued_by="legacy-writer",
    )
    assert harness.mission_store.record_issuance(legacy).value == "RECORDED"
    retry = _post(harness.app, "/v1/missions/contracts", payload)
    assert retry.status_code == 409
    assert retry.json()["detail"] == "MISSION_ID_CONFLICT"
    assert harness.mission_store.get("mission-legacy") == legacy


def test_corrupted_new_witness_is_rejected_on_replay(tmp_path: Path) -> None:
    harness = _harness(tmp_path / "source")
    response = _post(
        harness.app,
        "/v1/missions/contracts",
        _contract_request("mission-corrupt-witness"),
    )
    assert response.status_code == 201
    raw = harness.mission_journal.replay()[0]
    raw["authorizationWitness"]["siteIssuanceRevision"] = 0

    corrupted_path = tmp_path / "corrupted.jsonl"
    seed = DurableJournal(corrupted_path)
    seed.append(raw)
    seed.close()
    with pytest.raises(MissionStoreRecoveryError):
        MissionStore(DurableJournal(corrupted_path))


def test_pair_is_one_durable_record_binding_contract_and_kmz(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    response = _post(
        harness.app,
        "/v1/missions/plans",
        _plan_request("mission-atomic-pair"),
    )
    assert response.status_code == 201
    records = harness.mission_journal.replay()
    assert len(records) == 1
    raw = records[0]
    assert raw["artifactKind"] == "pair"
    assert raw["contract"] == response.json()["contract"]
    assert raw["kmzSha256"] == response.json()["kmzSha256"]
    assert raw["authorizationWitness"]["requestDigest"] == raw["planRequestDigest"]


def test_crash_before_append_replays_as_unissued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path)

    def crash_before_append(
        _self: MissionIssuanceCommitter,
        _record: MissionRecord,
        _witness: Any,
    ) -> Any:
        raise RuntimeError("simulated process crash before append")

    monkeypatch.setattr(MissionIssuanceCommitter, "commit", crash_before_append)
    with TestClient(harness.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/missions/contracts",
            json=_contract_request("mission-pre-append-crash"),
            headers=_headers(),
        )
    assert response.status_code == 500
    assert harness.mission_store.get("mission-pre-append-crash") is None
    harness.mission_journal.close()
    replay_journal = DurableJournal(tmp_path / "missions.jsonl")
    replay_store = MissionStore(replay_journal)
    assert replay_store.get("mission-pre-append-crash") is None
    assert replay_journal.replay() == []


def test_crash_after_append_before_response_replays_once_and_retry_is_200(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path)
    payload = _contract_request("mission-post-append-crash")
    original = MissionIssuanceCommitter.commit

    def crash_after_append(
        self: MissionIssuanceCommitter,
        record: MissionRecord,
        witness: Any,
    ) -> Any:
        verdict = original(self, record, witness)
        if verdict.value == "RECORDED":
            raise RuntimeError("simulated process crash after durable append")
        return verdict

    monkeypatch.setattr(MissionIssuanceCommitter, "commit", crash_after_append)
    with TestClient(harness.app, raise_server_exceptions=False) as client:
        lost = client.post(
            "/v1/missions/contracts",
            json=payload,
            headers=_headers(),
        )
    assert lost.status_code == 500
    assert len(harness.mission_journal.replay()) == 1
    harness.mission_journal.close()

    monkeypatch.undo()
    replay_journal = DurableJournal(tmp_path / "missions.jsonl")
    replay_store = MissionStore(replay_journal)
    replay_app = create_app(
        auth_registry=_registry(),
        site_store=harness.site_store,
        mission_store=replay_store,
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="mission-occ-post-append-restart-key",
    )
    retry = _post(replay_app, "/v1/missions/contracts", payload)
    assert retry.status_code == 200
    assert len(replay_store.list_scoped(organization_id="legacy")) == 1
    assert len(replay_journal.replay()) == 1


def test_multiple_prerequisite_changes_reject_before_any_mission_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path, with_work_order=True, acquisition_gate=True)
    assert harness.work_order_store is not None
    assert harness.work_order is not None
    assert harness.acquisition_store is not None
    signed, release = Event(), Event()
    _install_post_sign_barrier(monkeypatch, kind="pair", signed=signed, release=release)
    mission_id = "mission-combined-race"
    payload = _plan_request(mission_id, work_order_id=harness.work_order.work_order_id)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_post, harness.app, "/v1/missions/plans", payload)
        assert signed.wait(5)
        harness.work_order_store.link_mission(
            harness.work_order.work_order_id,
            organization_id="legacy",
            cycle_number=harness.work_order.cycle_number,
            mission_id="unrelated-combined",
            mission_site_id=_SITE_ID,
            actor="test-harness",
            now=datetime.now(UTC),
            require_approved=False,
        )
        now = datetime.now(UTC)
        harness.acquisition_store.observe(
            _snapshot(now, snapshot_id="snapshot-combined"),
            organization_id="legacy",
            actor="test-harness",
            now=now,
        )
        _suspend(harness.site_store)
        release.set()
        response = future.result(timeout=5)

    assert response.status_code == 409
    # Canonical lock order validates Site first; no lower-priority stale witness can append.
    assert response.json()["detail"].endswith("SITE_ISSUANCE_REVISION_CONFLICT")
    assert harness.mission_store.get(mission_id) is None
    assert harness.mission_journal.replay() == []


def test_site_revision_replays_and_keeps_aba_witness_stale(tmp_path: Path) -> None:
    journal_path = tmp_path / "sites.jsonl"
    journal = DurableJournal(journal_path)
    store = SiteStore(journal)
    store.register(
        _SITE_ID,
        "Revision replay",
        SiteFrame.model_validate(_FRAME),
        actor="test-harness",
        now=datetime.now(UTC),
    )
    before = store.issuance_snapshot(_SITE_ID, organization_id="legacy")
    assert before is not None and before.issuance_revision == 1
    _suspend(store)
    resumed = store.transition(
        _SITE_ID,
        SiteStatus.UNMAPPED,
        evidence="resume",
        reason="revision replay",
        actor="test-harness",
        now=datetime.now(UTC),
    )
    assert resumed.verdict.value == "TRANSITIONED"
    after = store.issuance_snapshot(_SITE_ID, organization_id="legacy")
    assert after is not None and after.issuance_revision == 3
    journal.close()

    replay_journal = DurableJournal(journal_path)
    replayed = SiteStore(replay_journal)
    replayed_state = replayed.issuance_snapshot(_SITE_ID, organization_id="legacy")
    assert replayed_state is not None
    assert replayed_state.record.status is SiteStatus.UNMAPPED
    assert replayed_state.issuance_revision == 3
    assert replayed_state.issuance_revision != before.issuance_revision


def test_later_site_suspension_does_not_revoke_past_durable_mission(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    response = _post(
        harness.app,
        "/v1/missions/contracts",
        _contract_request("mission-before-suspension"),
    )
    assert response.status_code == 201
    issued = harness.mission_store.get("mission-before-suspension")
    assert issued is not None
    _suspend(harness.site_store)
    assert harness.mission_store.get("mission-before-suspension") == issued

    harness.mission_journal.close()
    replay = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    assert replay.get("mission-before-suspension") == issued


def test_runtime_snapshot_latency_measurement_remains_pre_activation_not_occ_test_gate() -> None:
    contract = Path("docs/design/MISSION_ISSUANCE_ATOMICITY_CONTRACT.md").read_text()
    assert "PRE-ACTIVATION RUNTIME GATE" in contract
    assert "route generation duration" in contract
    assert "signing duration" in contract
    assert "production" in contract and "BLOCKED" in contract
