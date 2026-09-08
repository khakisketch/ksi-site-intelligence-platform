"""Focused durability and fail-closed tests for Core checkpoint validation."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

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
from ksi_core.checkpoint_validations import (
    CheckpointValidationRecoveryError,
    CheckpointValidationStore,
    CheckpointValidationVerdict,
    mount_checkpoint_validations,
)
from ksi_core.durable_journal import DurableJournal
from ksi_event_contracts.checkpoint_validation import (
    CheckpointFileDeclared,
    CheckpointValidationObserved,
    CheckpointValidationStatus,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.processing_job import ProcessingJobStatus
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)

_NOW = datetime(2026, 8, 29, tzinfo=UTC)
_SHA = "a" * 64
_DSM_DIGEST = "sha256:" + "b" * 64
_ADMIN_TOKEN = "checkpoint-admin-token"  # noqa: S105 -- deterministic test credential
_VIEWER_TOKEN = "checkpoint-viewer-token"  # noqa: S105
_WORKER_TOKEN = "checkpoint-worker-token"  # noqa: S105
_OTHER_ADMIN_TOKEN = "checkpoint-other-admin-token"  # noqa: S105
_OTHER_WORKER_TOKEN = "checkpoint-other-worker-token"  # noqa: S105


def _vertical(source: VerticalReferenceSource) -> VerticalReference:
    return VerticalReference(
        datum=VerticalDatum.ELLIPSOIDAL,
        basis="test provenance",
        source=source,
    )


def _declared(**changes: Any) -> CheckpointFileDeclared:
    values: dict[str, Any] = {
        "filename": "independent-checkpoints.csv",
        "sha256": _SHA,
        "size_bytes": 1024,
        "crs": "EPSG:5186",
        "vertical_reference": _vertical(VerticalReferenceSource.USER_DECLARED),
        "independent_from_processing_attested": True,
        "independence_basis": "separate total-station survey",
    }
    return CheckpointFileDeclared(**(values | changes))


class _Jobs:
    def __init__(self, *, digest: str = _DSM_DIGEST) -> None:
        self.digest = digest

    def artifact_of(self, job_id: str, artifact_id: str) -> tuple[object, object] | None:
        if (job_id, artifact_id) != ("job-1", "dsm-1"):
            return None
        return (
            SimpleNamespace(
                job_id="job-1",
                mission_id="mission-1",
                site_id="site-1",
                status=ProcessingJobStatus.SUCCEEDED,
            ),
            SimpleNamespace(
                artifact_id="dsm-1",
                kind=ProcessingArtifactKind.DSM,
                digest=self.digest,
                crs="EPSG:5186",
                vertical_reference=_vertical(VerticalReferenceSource.PIPELINE_DECLARED),
            ),
        )

    def resolve_artifact(self, job_id: str, artifact_id: str) -> object | None:
        pair = self.artifact_of(job_id, artifact_id)
        if pair is None:
            return None
        record, artifact = pair
        return SimpleNamespace(
            record=record,
            artifact=artifact,
            object_key="sites/site-1/processing-jobs/job-1/artifacts/dsm-1",
        )


class _Missions:
    _record = SimpleNamespace(mission_id="mission-1", site_id="site-1", organization_id="org-1")

    def get(self, mission_id: str) -> object | None:
        return self._record if mission_id == "mission-1" else None

    def get_scoped(self, mission_id: str, *, organization_id: str) -> object | None:
        return self._record if (mission_id, organization_id) == ("mission-1", "org-1") else None


def _store(path: Path, *, jobs: _Jobs | None = None) -> CheckpointValidationStore:
    return CheckpointValidationStore(
        DurableJournal(path),
        processing_jobs=cast(Any, jobs or _Jobs()),
        mission_store=cast(Any, _Missions()),
    )


def _observed(**changes: Any) -> CheckpointValidationObserved:
    values: dict[str, Any] = {
        "checkpoint_sha256": _SHA,
        "checkpoint_size_bytes": 1024,
        "dsm_digest": _DSM_DIGEST,
        "dsm_crs": "epsg:5186",
        "point_count": 3,
        "mean_error_m": 0.01,
        "mae_m": 0.02,
        "rmse_m": 0.03,
        "max_abs_error_m": 0.04,
        "measured_at": _NOW,
        "measured_by": "worker-1",
    }
    return CheckpointValidationObserved(**(values | changes))


def _token_record(
    token: str,
    *,
    principal_id: str,
    kind: PrincipalKind,
    organization_id: str,
    role: Role | None = None,
) -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        principal=Principal(
            principal_id=principal_id,
            kind=kind,
            role=role,
            device_id=None,
            organization_id=organization_id,
        ),
    )


class _Storage:
    def __init__(self) -> None:
        self.fail_put = False

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        if self.fail_put:
            from ksi_core.evidence import EvidenceStorageError

            raise EvidenceStorageError("fixture outage")
        assert content_type == "text/csv"
        return f"https://storage.test/put/{object_key}"

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        return f"https://storage.test/get/{object_key}"


def _api_client(
    tmp_path: Path,
    *,
    registration_enabled: bool = True,
    storage: _Storage | None = None,
) -> tuple[TestClient, CheckpointValidationStore, _Storage]:
    checkpoint_store = _store(tmp_path / "checkpoint-api.jsonl")
    evidence = storage or _Storage()
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                _token_record(
                    _ADMIN_TOKEN,
                    principal_id="admin-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    organization_id="org-1",
                ),
                _token_record(
                    _VIEWER_TOKEN,
                    principal_id="viewer-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.VIEWER,
                    organization_id="org-1",
                ),
                _token_record(
                    _WORKER_TOKEN,
                    principal_id="worker-1",
                    kind=PrincipalKind.PROCESSING_WORKER,
                    organization_id="org-1",
                ),
                _token_record(
                    _OTHER_ADMIN_TOKEN,
                    principal_id="admin-2",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    organization_id="org-2",
                ),
                _token_record(
                    _OTHER_WORKER_TOKEN,
                    principal_id="worker-2",
                    kind=PrincipalKind.PROCESSING_WORKER,
                    organization_id="org-2",
                ),
            ]
        ),
    )
    mount_checkpoint_validations(
        app,
        checkpoint_store,
        cast(Any, evidence),
        registration_enabled=registration_enabled,
    )
    return TestClient(app), checkpoint_store, evidence


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _register_payload(**changes: Any) -> dict[str, Any]:
    declared = _declared(**changes).model_dump(by_alias=True, mode="json")
    return {"declared": declared}


def _observation_payload(**changes: Any) -> dict[str, Any]:
    values = _observed(**changes).model_dump(by_alias=True, mode="json")
    values.pop("measuredAt")
    values.pop("measuredBy")
    return values


def test_register_seal_observe_persists_server_validated_rmse(tmp_path: Path) -> None:
    store = _store(tmp_path / "checkpoint.jsonl")
    registered = store.register("job-1", "dsm-1", _declared(), registered_by="operator", now=_NOW)
    assert registered.verdict is CheckpointValidationVerdict.REGISTERED
    assert registered.record is not None
    validation_id = registered.record.validation_id
    assert (
        store.seal(validation_id, now=_NOW + timedelta(minutes=1)).verdict
        is CheckpointValidationVerdict.SEALED
    )
    validated = store.observe(validation_id, _observed(), now=_NOW + timedelta(minutes=2))
    assert validated.verdict is CheckpointValidationVerdict.VALIDATED
    assert validated.record is not None
    assert validated.record.status is CheckpointValidationStatus.VALIDATED
    assert store.validated_rmse_for(validated.record.dsm) == 0.03


def test_digest_mismatch_is_terminal_rejection_and_retry_can_be_registered(tmp_path: Path) -> None:
    store = _store(tmp_path / "checkpoint.jsonl")
    first = store.register("job-1", "dsm-1", _declared(), registered_by="operator", now=_NOW)
    assert first.record is not None
    store.seal(first.record.validation_id, now=_NOW)
    rejected = store.observe(
        first.record.validation_id,
        _observed(checkpoint_sha256="c" * 64),
        now=_NOW,
    )
    assert rejected.verdict is CheckpointValidationVerdict.REJECTED
    assert rejected.record is not None
    assert rejected.record.status is CheckpointValidationStatus.REJECTED
    retry = store.register(
        "job-1", "dsm-1", _declared(filename="retry.csv"), registered_by="operator", now=_NOW
    )
    assert retry.verdict is CheckpointValidationVerdict.REGISTERED


def test_only_one_active_validation_can_target_a_dsm(tmp_path: Path) -> None:
    store = _store(tmp_path / "checkpoint.jsonl")
    first = store.register("job-1", "dsm-1", _declared(), registered_by="operator", now=_NOW)
    assert first.record is not None

    same = store.register("job-1", "dsm-1", _declared(), registered_by="operator", now=_NOW)
    assert same.verdict is CheckpointValidationVerdict.ALREADY_REGISTERED
    assert same.record == first.record

    store.seal(first.record.validation_id, now=_NOW)
    sealed_retry = store.register(
        "job-1", "dsm-1", _declared(), registered_by="operator", now=_NOW
    )
    assert sealed_retry.verdict is CheckpointValidationVerdict.ALREADY_SEALED
    assert sealed_retry.object_key is None

    different = store.register(
        "job-1",
        "dsm-1",
        _declared(filename="other.csv"),
        registered_by="operator",
        now=_NOW,
    )
    assert different.verdict is CheckpointValidationVerdict.ACTIVE_VALIDATION_EXISTS


def test_replay_recomputes_observation_verdict_and_rejects_tampering(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.jsonl"
    store = _store(path)
    registered = store.register("job-1", "dsm-1", _declared(), registered_by="operator", now=_NOW)
    assert registered.record is not None
    store.seal(registered.record.validation_id, now=_NOW)
    store.observe(registered.record.validation_id, _observed(), now=_NOW)
    store._journal.close()  # noqa: SLF001 -- prepares a controlled replay fixture
    path.write_text(
        path.read_text(encoding="utf-8").replace('"VALIDATED"', '"REJECTED"'), encoding="utf-8"
    )
    with pytest.raises(CheckpointValidationRecoveryError, match="판정 위조"):
        _store(path)


def test_replay_rebinds_snapshot_to_processing_artifact_ledger(tmp_path: Path) -> None:
    path = tmp_path / "checkpoint.jsonl"
    store = _store(path)
    registered = store.register("job-1", "dsm-1", _declared(), registered_by="operator", now=_NOW)
    assert registered.record is not None
    store._journal.close()  # noqa: SLF001 -- simulate next process startup

    with pytest.raises(CheckpointValidationRecoveryError, match="processing 원장"):
        _store(path, jobs=_Jobs(digest="sha256:" + "c" * 64))


def test_registration_fails_closed_on_crs_or_vertical_mismatch(tmp_path: Path) -> None:
    store = _store(tmp_path / "checkpoint.jsonl")
    assert (
        store.register(
            "job-1", "dsm-1", _declared(crs="EPSG:5187"), registered_by="operator", now=_NOW
        ).verdict
        is CheckpointValidationVerdict.CRS_MISMATCH
    )
    wrong_vertical = VerticalReference(
        datum=VerticalDatum.ORTHOMETRIC_KNGEOID2024,
        basis="survey datum",
        source=VerticalReferenceSource.USER_DECLARED,
    )
    assert (
        store.register(
            "job-1",
            "dsm-1",
            _declared(vertical_reference=wrong_vertical),
            registered_by="operator",
            now=_NOW,
        ).verdict
        is CheckpointValidationVerdict.VERTICAL_REFERENCE_MISMATCH
    )


def test_http_flow_exposes_only_worker_inputs_and_server_computed_result(tmp_path: Path) -> None:
    client, _, _ = _api_client(tmp_path)
    registered = client.post(
        "/v1/processing-jobs/job-1/artifacts/dsm-1/checkpoint-validations",
        headers=_auth(_ADMIN_TOKEN),
        json=_register_payload(),
    )
    assert registered.status_code == 201, registered.json()
    body = registered.json()
    validation_id = body["validationId"]
    assert body["validation"]["observed"] is None
    assert body["uploadUrl"].startswith("https://storage.test/put/")

    sealed = client.post(
        f"/v1/checkpoint-validations/{validation_id}/seal",
        headers=_auth(_ADMIN_TOKEN),
    )
    assert sealed.status_code == 201
    assert sealed.json()["validation"]["status"] == "SEALED"

    sealed_registration_retry = client.post(
        "/v1/processing-jobs/job-1/artifacts/dsm-1/checkpoint-validations",
        headers=_auth(_ADMIN_TOKEN),
        json=_register_payload(),
    )
    assert sealed_registration_retry.status_code == 200
    assert sealed_registration_retry.json()["verdict"] == "ALREADY_SEALED"
    assert sealed_registration_retry.json()["uploadUrl"] is None

    assert (
        client.get("/v1/checkpoint-validations", headers=_auth(_ADMIN_TOKEN)).status_code == 403
    )
    pending = client.get(
        "/v1/checkpoint-validations?status=SEALED", headers=_auth(_WORKER_TOKEN)
    )
    assert pending.status_code == 200, pending.json()
    candidate = pending.json()["validations"][0]
    assert candidate["validationId"] == validation_id
    assert candidate["checkpointCrs"] == "EPSG:5186"
    assert candidate["checkpointVerticalReference"]["source"] == "user_declared"
    assert "sha256" not in candidate
    assert "sizeBytes" not in candidate
    assert "rmseM" not in candidate

    observed = client.post(
        f"/v1/checkpoint-validations/{validation_id}/observations",
        headers=_auth(_WORKER_TOKEN),
        json=_observation_payload(),
    )
    assert observed.status_code == 201, observed.json()
    assert observed.json()["verdict"] == "VALIDATED"
    record = observed.json()["validation"]
    assert record["observed"]["rmseM"] == 0.03
    assert record["observed"]["measuredBy"] == "worker-1"

    listed = client.get(
        "/v1/processing-jobs/job-1/checkpoint-validations",
        headers=_auth(_VIEWER_TOKEN),
    )
    assert listed.status_code == 200
    assert [item["status"] for item in listed.json()["validations"]] == ["VALIDATED"]


def test_http_organization_isolation_hides_validation_and_worker_queue(tmp_path: Path) -> None:
    client, _, _ = _api_client(tmp_path)
    registered = client.post(
        "/v1/processing-jobs/job-1/artifacts/dsm-1/checkpoint-validations",
        headers=_auth(_ADMIN_TOKEN),
        json=_register_payload(),
    ).json()
    validation_id = registered["validationId"]
    client.post(
        f"/v1/checkpoint-validations/{validation_id}/seal", headers=_auth(_ADMIN_TOKEN)
    )

    hidden = client.get(
        f"/v1/checkpoint-validations/{validation_id}", headers=_auth(_OTHER_ADMIN_TOKEN)
    )
    assert hidden.status_code == 404
    hidden_list = client.get(
        "/v1/processing-jobs/job-1/checkpoint-validations",
        headers=_auth(_OTHER_ADMIN_TOKEN),
    )
    assert hidden_list.status_code == 200
    assert hidden_list.json() == {"validations": []}
    hidden_queue = client.get(
        "/v1/checkpoint-validations", headers=_auth(_OTHER_WORKER_TOKEN)
    )
    assert hidden_queue.status_code == 200
    assert hidden_queue.json() == {"validations": []}
    hidden_mutation = client.post(
        f"/v1/checkpoint-validations/{validation_id}/observations",
        headers=_auth(_OTHER_WORKER_TOKEN),
        json=_observation_payload(),
    )
    assert hidden_mutation.status_code == 404


def test_http_registration_flag_is_default_closed_but_routes_remain_mounted(
    tmp_path: Path,
) -> None:
    client, _, _ = _api_client(tmp_path, registration_enabled=False)
    response = client.post(
        "/v1/processing-jobs/job-1/artifacts/dsm-1/checkpoint-validations",
        headers=_auth(_ADMIN_TOKEN),
        json=_register_payload(),
    )
    assert response.status_code == 403
    assert response.json()["verdict"] == "REGISTRATION_DISABLED"
    assert (
        client.get(
            "/v1/processing-jobs/job-1/checkpoint-validations",
            headers=_auth(_VIEWER_TOKEN),
        ).status_code
        == 200
    )


def test_presign_outage_keeps_registered_record_retryable(tmp_path: Path) -> None:
    storage = _Storage()
    storage.fail_put = True
    client, _, _ = _api_client(tmp_path, storage=storage)
    path = "/v1/processing-jobs/job-1/artifacts/dsm-1/checkpoint-validations"
    failed = client.post(path, headers=_auth(_ADMIN_TOKEN), json=_register_payload())
    assert failed.status_code == 503
    assert failed.headers["Retry-After"] == "30"
    validation_id = failed.json()["validationId"]

    storage.fail_put = False
    retried = client.post(path, headers=_auth(_ADMIN_TOKEN), json=_register_payload())
    assert retried.status_code == 200, retried.json()
    assert retried.json()["verdict"] == "ALREADY_REGISTERED"
    assert retried.json()["validationId"] == validation_id
    assert retried.json()["uploadUrl"].startswith("https://storage.test/put/")


def test_invalid_worker_metrics_or_failure_reason_do_not_terminalize_record(
    tmp_path: Path,
) -> None:
    client, _, _ = _api_client(tmp_path)
    registered = client.post(
        "/v1/processing-jobs/job-1/artifacts/dsm-1/checkpoint-validations",
        headers=_auth(_ADMIN_TOKEN),
        json=_register_payload(),
    ).json()
    validation_id = registered["validationId"]
    client.post(
        f"/v1/checkpoint-validations/{validation_id}/seal", headers=_auth(_ADMIN_TOKEN)
    )

    contradictory_payload = _observation_payload()
    contradictory_payload["meanErrorM"] = 0.04
    contradictory_payload["rmseM"] = 0.03
    contradictory = client.post(
        f"/v1/checkpoint-validations/{validation_id}/observations",
        headers=_auth(_WORKER_TOKEN),
        json=contradictory_payload,
    )
    assert contradictory.status_code == 422
    assert contradictory.json()["verdict"] == "INVALID_MEASUREMENT"

    forbidden_reason = client.post(
        f"/v1/checkpoint-validations/{validation_id}/verification-failure",
        headers=_auth(_WORKER_TOKEN),
        json={"reason": "CHECKPOINT_DIGEST_MISMATCH"},
    )
    assert forbidden_reason.status_code == 422
    assert forbidden_reason.json()["verdict"] == "INVALID_MEASUREMENT"
    still_sealed = client.get(
        f"/v1/checkpoint-validations/{validation_id}", headers=_auth(_VIEWER_TOKEN)
    )
    assert still_sealed.json()["validation"]["status"] == "SEALED"

    missing = client.post(
        f"/v1/checkpoint-validations/{validation_id}/verification-failure",
        headers=_auth(_WORKER_TOKEN),
        json={"reason": "CHECKPOINT_OBJECT_MISSING", "detail": "sealed input object is missing"},
    )
    assert missing.status_code == 422, missing.json()
    assert missing.json()["validation"]["status"] == "REJECTED"
