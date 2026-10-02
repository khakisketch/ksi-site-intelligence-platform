"""The analysis worker HTTP seam is a strict event-contract boundary."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
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
from ksi_core.domains.external.quantity.external_analysis_intents import AnalysisIntentStore
from ksi_core.domains.external.quantity.external_analysis_s3_capabilities import (
    ExternalAnalysisS3InputCapabilityIssuer,
)
from ksi_core.domains.external.quantity.external_analysis_worker_api import (
    build_external_analysis_worker_router,
)
from ksi_core.domains.external.quantity.external_relative_volume_calculations import (
    CalculationExecutionStatusV2,
    ExternalRelativeVolumeCalculationStore,
)
from ksi_event_contracts.external_analysis_worker import (
    ANALYSIS_ATTEMPT_DIGEST_HEADER,
    ANALYSIS_WORKER_INSTANCE_ID_HEADER,
    AnalysisWorkerInputCapabilityV1,
    AnalysisWorkerLeaseRequestV1,
    AnalysisWorkerPendingItemV1,
)
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_relative_volume_analysis import CalculationIdentityV2
from ksi_event_contracts.external_relative_volume_calculation import (
    AnalysisExecutionAttemptV2,
    AnalysisExecutionAuthorizationV2,
    RelativeVolumeCalculationFailureV2,
    RelativeVolumeCalculationReportV2,
)
from pydantic import ValidationError
from test_external_analysis_measurement import _identity, _write_dsm


@dataclass(frozen=True)
class _IntentRecord:
    analysis_id: str
    calculation_request_id: str | None
    created_at: datetime


@dataclass(frozen=True)
class _ResourceEnvelopeRecord:
    max_deadline_seconds: float
    max_retry_attempts: int


@dataclass(frozen=True)
class _AuthorizationRecord:
    authorized_at: datetime
    resource_envelope: _ResourceEnvelopeRecord


@dataclass(frozen=True)
class _AdmissionRecord:
    calculation_identity_digest: str | None
    calculation_identity: CalculationIdentityV2 | None = None


@dataclass(frozen=True)
class _CalculationRecord:
    status: CalculationExecutionStatusV2
    calculation_identity_digest: str
    admission: _AdmissionRecord
    issued_at: datetime
    attempts: tuple[AnalysisExecutionAttemptV2, ...]
    authorization: _AuthorizationRecord

    @property
    def active_attempt(self) -> AnalysisExecutionAttemptV2 | None:
        return self.attempts[-1] if self.attempts else None


class _UnusedIntentMethods:
    def get(self, analysis_id: str, *, organization_id: str) -> _IntentRecord | None:
        raise AssertionError("unexpected intent lookup")

    def list_for_organization(self, *, organization_id: str) -> tuple[_IntentRecord, ...]:
        raise AssertionError("unexpected intent listing")


class _UnusedCalculationMethods:
    def get_history(
        self, request_id: str, *, organization_id: str
    ) -> _CalculationRecord | None:
        raise AssertionError("unexpected calculation history lookup")

    def acquire_lease(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        worker_instance_id: str,
        lease_acquisition_id: str,
        now: datetime,
    ) -> AnalysisExecutionAttemptV2 | None:
        raise AssertionError("unexpected lease acquisition")

    def input_for_worker(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        attempt: AnalysisExecutionAttemptV2,
        now: datetime,
    ) -> _CalculationRecord | None:
        raise AssertionError("unexpected worker input read")

    def renew_lease(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        attempt: AnalysisExecutionAttemptV2,
        now: datetime,
    ) -> AnalysisExecutionAttemptV2 | None:
        raise AssertionError("unexpected lease renewal")

    def record_report(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        report: RelativeVolumeCalculationReportV2,
        now: datetime,
    ) -> _CalculationRecord | None:
        raise AssertionError("unexpected report recording")

    def record_failure(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        failure: RelativeVolumeCalculationFailureV2,
        now: datetime,
    ) -> _CalculationRecord | None:
        raise AssertionError("unexpected failure recording")


def _calculation_record(
    *,
    status: CalculationExecutionStatusV2,
    calculation_identity_digest: str,
    issued_at: datetime,
    authorization_at: datetime,
    max_retry_attempts: int = 2,
    attempts: tuple[AnalysisExecutionAttemptV2, ...] = (),
    calculation_identity: CalculationIdentityV2 | None = None,
) -> _CalculationRecord:
    return _CalculationRecord(
        status=status,
        calculation_identity_digest=calculation_identity_digest,
        admission=_AdmissionRecord(calculation_identity_digest, calculation_identity),
        issued_at=issued_at,
        attempts=attempts,
        authorization=_AuthorizationRecord(
            authorized_at=authorization_at,
            resource_envelope=_ResourceEnvelopeRecord(
                max_deadline_seconds=600.0,
                max_retry_attempts=max_retry_attempts,
            ),
        ),
    )


def _expired_attempt(
    at: datetime, *, worker_instance_id: str = "worker-expired"
) -> AnalysisExecutionAttemptV2:
    envelope = ResourceEnvelopeV1(
        max_input_bytes=1,
        max_streamed_bytes=1,
        max_tiff_directories=1,
        max_tiff_entries=1,
        max_pixels=1,
        max_bands=1,
        max_blocks=1,
        max_decompressed_bytes=1,
        max_sample_bytes=1,
        max_geometry_vertices=1,
        max_cpu_seconds=1.0,
        max_memory_bytes=1,
        max_workspace_bytes=1,
        max_output_bytes=1,
        max_tenant_concurrency=1,
        max_queue_depth=1,
        max_deadline_seconds=600.0,
        lease_duration_seconds=30.0,
        max_retry_attempts=2,
    ).sealed()
    assert envelope.resource_envelope_digest is not None
    authorization = AnalysisExecutionAuthorizationV2(
        authorization_id="authorization-test",
        organization_id="org-a",
        calculation_identity_digest="sha256:" + "a" * 64,
        admission_digest="sha256:" + "b" * 64,
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authorized_at=at - timedelta(minutes=2),
    ).sealed()
    assert authorization.execution_authorization_digest is not None
    return AnalysisExecutionAttemptV2(
        attempt_id="attempt-test",
        authorization=authorization,
        authorization_digest=authorization.execution_authorization_digest,
        worker_instance_id=worker_instance_id,
        lease_acquisition_id="lease-expired",
        lease_generation=1,
        issued_at=at - timedelta(minutes=1),
        lease_expires_at=at - timedelta(seconds=1),
    ).sealed()


def _concrete_core_stores_satisfy_worker_ports(
    intents: AnalysisIntentStore,
    calculations: ExternalRelativeVolumeCalculationStore,
) -> None:
    """Static mypy probe: real Core stores must implement both internal router ports."""
    build_external_analysis_worker_router(
        intents=intents,
        assessments=object(),
        calculations=calculations,
        capability_issuer=_unexpected_capability_issuer,
    )


def _worker_principal() -> Principal:
    return Principal(
        principal_id="analysis-worker-a",
        kind=PrincipalKind.ANALYSIS_WORKER,
        role=None,
        device_id=None,
        organization_id="org-a",
    )


def _processing_worker_principal() -> Principal:
    return Principal(
        principal_id="processing-worker-a",
        kind=PrincipalKind.PROCESSING_WORKER,
        role=None,
        device_id=None,
        organization_id="org-a",
    )


def _operator_principal() -> Principal:
    return Principal(
        principal_id="operator-a",
        kind=PrincipalKind.OPERATOR,
        role=Role.ADMIN,
        device_id=None,
        organization_id="org-a",
    )


def _unexpected_capability_issuer(
    *args: object, **kwargs: object
) -> tuple[AnalysisWorkerInputCapabilityV1, AnalysisWorkerInputCapabilityV1] | None:
    del args, kwargs
    raise AssertionError("worker list and lease routes must not issue input capabilities")


class _WorkerIntents(_UnusedIntentMethods):
    def list_for_organization(self, *, organization_id: str) -> tuple[_IntentRecord, ...]:
        assert organization_id == "org-a"
        return (
            _IntentRecord(
                analysis_id="analysis-v1-1",
                calculation_request_id="calculation-v1-1",
                created_at=datetime(2026, 9, 22, tzinfo=UTC),
            ),
        )


class _WorkerCalculations(_UnusedCalculationMethods):
    def get_history(
        self, request_id: str, *, organization_id: str
    ) -> _CalculationRecord | None:
        if (request_id, organization_id) != ("calculation-v1-1", "org-a"):
            return None
        return _calculation_record(
            status=CalculationExecutionStatusV2.QUEUED,
            calculation_identity_digest="sha256:" + "a" * 64,
            issued_at=datetime(2026, 9, 22, tzinfo=UTC),
            authorization_at=datetime(2026, 9, 22, tzinfo=UTC),
        )


class _WorkerAssessments:
    def get_history(self, request_id: str, *, organization_id: str) -> object | None:
        assert (request_id, organization_id) == ("analysis-v1-1", "org-a")
        return SimpleNamespace(
            admission=SimpleNamespace(calculation_identity_digest="sha256:" + "a" * 64)
        )

    def prepare_execution_witness(self, *, expected_admission: object, **_kwargs: object) -> object:
        return expected_admission

    def execution_witness_is_current(self, *, witness: object, **_kwargs: object) -> object:
        return SimpleNamespace(admission=witness)


def test_worker_lease_and_pending_wire_are_closed_and_runtime_neutral() -> None:
    """A worker can name an exact lease but cannot inject profile/runtime evidence."""
    lease = AnalysisWorkerLeaseRequestV1(
        worker_instance_id="local-analysis-worker-1",
        lease_acquisition_id="lease-acquisition-1",
    )
    pending = AnalysisWorkerPendingItemV1(
        analysis_id="analysis-v1-1",
        calculation_request_id="calculation-v1-1",
        issued_at=datetime(2026, 9, 22, tzinfo=UTC),
    )

    assert lease.model_dump(by_alias=True) == {
        "workerInstanceId": "local-analysis-worker-1",
        "leaseAcquisitionId": "lease-acquisition-1",
    }
    assert pending.calculation_request_id == "calculation-v1-1"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AnalysisWorkerLeaseRequestV1.model_validate(
            {**lease.model_dump(by_alias=True), "runtimeImageOciDigest": "sha256:" + "a" * 64}
        )


def test_worker_capability_is_short_lived_and_binds_only_one_sealed_dsm() -> None:
    """The internal input has two ordered byte URLs but no public artifact authority."""
    capability = AnalysisWorkerInputCapabilityV1(
        role="BASELINE_DSM",
        artifact_id="baseline-dsm",
        observed_sha256="sha256:" + "a" * 64,
        observed_size_bytes=123,
        download_url="http://127.0.0.1:8123/object/baseline.tif",
        required_headers={"x-test": "bound"},
        expires_at=datetime(2026, 9, 22, tzinfo=UTC),
    )

    assert capability.role == "BASELINE_DSM"
    assert capability.download_url.startswith("http://127.0.0.1:")
    assert capability.expires_at.tzinfo is not None


def test_input_fence_headers_bind_the_active_attempt_and_worker_instance() -> None:
    """GET input cannot turn a shared worker token into a current-lease oracle."""
    assert ANALYSIS_ATTEMPT_DIGEST_HEADER == "X-Analysis-Attempt-Digest"
    assert ANALYSIS_WORKER_INSTANCE_ID_HEADER == "X-Analysis-Worker-Instance-Id"


def test_internal_list_requires_worker_authentication_and_exposes_no_capability() -> None:
    """The worker queue is unavailable to an operator and list rows are identifier-only."""
    worker_token = "analysis-worker-token"
    operator_token = "analysis-operator-token"
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(worker_token.encode()).hexdigest(),
                    principal=_worker_principal(),
                ),
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(operator_token.encode()).hexdigest(),
                    principal=_operator_principal(),
                ),
            ]
        ),
    )
    app.include_router(
        build_external_analysis_worker_router(
            intents=_WorkerIntents(),
            assessments=_WorkerAssessments(),
            calculations=_WorkerCalculations(),
            capability_issuer=_unexpected_capability_issuer,
            clock=lambda: datetime(2026, 9, 22, tzinfo=UTC),
        )
    )
    client = TestClient(app)
    assert (
        client.get(
            "/v1/internal/analysis-jobs", headers={"Authorization": "Bearer " + operator_token}
        ).status_code
        == 403
    )
    response = client.get(
        "/v1/internal/analysis-jobs", headers={"Authorization": "Bearer " + worker_token}
    )
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "analysisId": "analysis-v1-1",
                "calculationRequestId": "calculation-v1-1",
                "issuedAt": "2026-09-22T00:00:00Z",
            }
        ]
    }


def test_generic_processing_worker_cannot_access_any_analysis_worker_route() -> None:
    token = "generic-processing-worker-token"
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(token.encode()).hexdigest(),
                    principal=_processing_worker_principal(),
                )
            ]
        ),
    )
    app.include_router(
        build_external_analysis_worker_router(
            intents=_WorkerIntents(),
            assessments=_WorkerAssessments(),
            calculations=_WorkerCalculations(),
            capability_issuer=_unexpected_capability_issuer,
            clock=lambda: datetime(2026, 9, 22, tzinfo=UTC),
        )
    )
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"Authorization": "Bearer " + token}
    responses = (
        client.get("/v1/internal/analysis-jobs", headers=headers),
        client.post(
            "/v1/internal/analysis-jobs/analysis-v1-1:lease",
            headers=headers,
            json={"workerInstanceId": "worker-a", "leaseAcquisitionId": "lease-a"},
        ),
        client.get("/v1/internal/analysis-jobs/analysis-v1-1/input", headers=headers),
        client.post("/v1/internal/analysis-jobs/analysis-v1-1:renew", headers=headers, json={}),
        client.post("/v1/internal/analysis-jobs/analysis-v1-1:report", headers=headers, json={}),
        client.post("/v1/internal/analysis-jobs/analysis-v1-1:failure", headers=headers, json={}),
    )

    assert [response.status_code for response in responses] == [403] * 6


def test_generic_processing_worker_cannot_lease_analysis_calculations() -> None:
    with pytest.raises(PermissionError, match="analysis worker scope"):
        ExternalRelativeVolumeCalculationStore._require_worker(_processing_worker_principal())


def test_generic_processing_worker_cannot_trigger_analysis_input_resolution() -> None:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    resolved_subjects: list[object] = []

    class Reconstruction:
        def resolve_sealed_subject(self, subject: object) -> None:
            resolved_subjects.append(subject)
            return None

    class Storage:
        pass

    record = SimpleNamespace(
        admission=SimpleNamespace(
            calculation_identity=SimpleNamespace(
                baseline_subject="baseline-subject",
                current_subject="current-subject",
                baseline_dsm_artifact_id="baseline-dsm",
                baseline_dsm_observed_sha256="sha256:" + "a" * 64,
                baseline_dsm_observed_size_bytes=10,
                current_dsm_artifact_id="current-dsm",
                current_dsm_observed_sha256="sha256:" + "b" * 64,
                current_dsm_observed_size_bytes=20,
            )
        ),
        active_attempt=SimpleNamespace(lease_expires_at=now + timedelta(seconds=30)),
        status=CalculationExecutionStatusV2.RUNNING,
        authorization=SimpleNamespace(
            authorized_at=now,
            resource_envelope=SimpleNamespace(max_deadline_seconds=600.0),
        ),
        organization_id="org-a",
    )
    issuer = ExternalAnalysisS3InputCapabilityIssuer(
        reconstruction=cast(Any, Reconstruction()), storage=cast(Any, Storage())
    )

    issuer(
        record,  # type: ignore[arg-type]
        attempt=record.active_attempt,
        principal=_processing_worker_principal(),
        now=now,
    )

    assert resolved_subjects == []


def test_worker_list_rediscovers_expired_running_fence_and_deduplicates_calculation() -> None:
    """A restarted worker can take over expired work without duplicate queue rows."""
    worker_token = "analysis-worker-reclaim-token"
    listed_at = datetime(2026, 9, 22, 1, tzinfo=UTC)

    class Intents(_UnusedIntentMethods):
        def list_for_organization(self, *, organization_id: str) -> tuple[_IntentRecord, ...]:
            assert organization_id == "org-a"
            return (
                _IntentRecord(
                    analysis_id="analysis-forged-prefix",
                    calculation_request_id="calculation-shared",
                    created_at=listed_at,
                ),
                _IntentRecord(
                    analysis_id="analysis-expired-queued",
                    calculation_request_id="calculation-expired-queued",
                    created_at=listed_at,
                ),
                _IntentRecord(
                    analysis_id="analysis-shared-a",
                    calculation_request_id="calculation-shared",
                    created_at=listed_at,
                ),
                _IntentRecord(
                    analysis_id="analysis-shared-b",
                    calculation_request_id="calculation-shared",
                    created_at=listed_at,
                ),
                _IntentRecord(
                    analysis_id="analysis-expired",
                    calculation_request_id="calculation-expired",
                    created_at=listed_at,
                ),
                _IntentRecord(
                    analysis_id="analysis-exhausted",
                    calculation_request_id="calculation-exhausted",
                    created_at=listed_at,
                ),
            )

    class Calculations(_UnusedCalculationMethods):
        def get_history(
            self, request_id: str, *, organization_id: str
        ) -> _CalculationRecord | None:
            assert organization_id == "org-a"
            if request_id == "calculation-expired-queued":
                return _calculation_record(
                    status=CalculationExecutionStatusV2.QUEUED,
                    calculation_identity_digest="sha256:" + "a" * 64,
                    issued_at=listed_at - timedelta(minutes=11),
                    authorization_at=listed_at - timedelta(minutes=11),
                )
            if request_id == "calculation-shared":
                return _calculation_record(
                    status=CalculationExecutionStatusV2.QUEUED,
                    calculation_identity_digest="sha256:" + "a" * 64,
                    issued_at=listed_at,
                    authorization_at=listed_at,
                )
            if request_id == "calculation-expired":
                attempt = _expired_attempt(listed_at)
                return _calculation_record(
                    status=CalculationExecutionStatusV2.RUNNING,
                    calculation_identity_digest="sha256:" + "a" * 64,
                    issued_at=listed_at - timedelta(minutes=1),
                    authorization_at=listed_at - timedelta(minutes=2),
                    attempts=(attempt,),
                )
            if request_id == "calculation-exhausted":
                attempt = _expired_attempt(listed_at)
                return _calculation_record(
                    status=CalculationExecutionStatusV2.RUNNING,
                    calculation_identity_digest="sha256:" + "a" * 64,
                    issued_at=listed_at - timedelta(minutes=1),
                    authorization_at=listed_at - timedelta(minutes=2),
                    max_retry_attempts=1,
                    attempts=(attempt,),
                )
            return None

    class Assessments:
        def get_history(self, request_id: str, *, organization_id: str) -> object | None:
            assert organization_id == "org-a"
            digest = "sha256:" + ("b" if request_id == "analysis-forged-prefix" else "a") * 64
            return SimpleNamespace(
                admission=SimpleNamespace(calculation_identity_digest=digest)
            )

        def prepare_execution_witness(
            self, *, expected_admission: object, **_kwargs: object
        ) -> object:
            return expected_admission

        def execution_witness_is_current(self, *, witness: object, **_kwargs: object) -> object:
            return SimpleNamespace(admission=witness)

    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(worker_token.encode()).hexdigest(),
                    principal=_worker_principal(),
                )
            ]
        ),
    )
    app.include_router(
        build_external_analysis_worker_router(
            intents=Intents(),
            assessments=Assessments(),
            calculations=Calculations(),
            capability_issuer=_unexpected_capability_issuer,
            clock=lambda: listed_at,
        )
    )
    response = TestClient(app).get(
        "/v1/internal/analysis-jobs", headers={"Authorization": "Bearer " + worker_token}
    )
    assert response.status_code == 200
    assert [
        (item["analysisId"], item["calculationRequestId"]) for item in response.json()["items"]
    ] == [
        ("analysis-shared-a", "calculation-shared"),
        ("analysis-expired", "calculation-expired"),
    ]
    bounded = TestClient(app).get(
        "/v1/internal/analysis-jobs?limit=1", headers={"Authorization": "Bearer " + worker_token}
    )
    assert bounded.status_code == 200
    assert [item["analysisId"] for item in bounded.json()["items"]] == ["analysis-shared-a"]


def test_worker_list_skips_ap_stale_job_before_bounded_page_limit() -> None:
    """A stale AP admission cannot starve a later runnable NX calculation."""
    worker_token = "analysis-worker-stale-discovery-token"
    listed_at = datetime(2026, 9, 22, 1, tzinfo=UTC)
    admission = SimpleNamespace(
        admission_id="admission-current",
        calculation_identity_digest="sha256:" + "a" * 64,
    )

    class Intents(_UnusedIntentMethods):
        def list_for_organization(self, *, organization_id: str) -> tuple[_IntentRecord, ...]:
            assert organization_id == "org-a"
            return (
                _IntentRecord(
                    analysis_id="analysis-stale",
                    calculation_request_id="calculation-stale",
                    created_at=listed_at,
                ),
                _IntentRecord(
                    analysis_id="analysis-runnable",
                    calculation_request_id="calculation-runnable",
                    created_at=listed_at,
                ),
            )

    class Calculations(_UnusedCalculationMethods):
        def get_history(
            self, request_id: str, *, organization_id: str
        ) -> _CalculationRecord | None:
            assert organization_id == "org-a"
            if request_id not in {"calculation-stale", "calculation-runnable"}:
                return None
            return _calculation_record(
                status=CalculationExecutionStatusV2.QUEUED,
                calculation_identity_digest="sha256:" + "a" * 64,
                issued_at=listed_at,
                authorization_at=listed_at,
            )

    class Assessments:
        def __init__(self) -> None:
            self.currentness_calls: list[str] = []

        def get_history(self, request_id: str, *, organization_id: str) -> object | None:
            assert organization_id == "org-a"
            return SimpleNamespace(admission=admission)

        def prepare_execution_witness(
            self,
            *,
            calculation_identity_digest: str,
            organization_id: str,
            now: datetime,
            expected_admission: object,
        ) -> object:
            assert calculation_identity_digest == "sha256:" + "a" * 64
            assert organization_id == "org-a"
            assert now == listed_at
            return expected_admission

        def execution_witness_is_current(self, *, witness: object, now: datetime) -> object | None:
            assert now == listed_at
            self.currentness_calls.append("current")
            if len(self.currentness_calls) == 1:
                return None
            return SimpleNamespace(admission=witness)

    assessments = Assessments()
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(worker_token.encode()).hexdigest(),
                    principal=_worker_principal(),
                )
            ]
        ),
    )
    app.include_router(
        build_external_analysis_worker_router(
            intents=Intents(),
            assessments=assessments,
            calculations=Calculations(),
            capability_issuer=_unexpected_capability_issuer,
            clock=lambda: listed_at,
        )
    )

    response = TestClient(app).get(
        "/v1/internal/analysis-jobs?limit=1",
        headers={"Authorization": "Bearer " + worker_token},
    )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "analysisId": "analysis-runnable",
            "calculationRequestId": "calculation-runnable",
            "issuedAt": "2026-09-22T01:00:00Z",
        }
    ]
    assert assessments.currentness_calls == ["current", "current"]


def test_input_rechecks_exact_fence_after_capability_issuer_returns(tmp_path: Path) -> None:
    """A lease transition during capability I/O never leaks the newly signed URLs."""
    worker_token = "analysis-worker-input-recheck-token"
    now = datetime(2026, 9, 22, 1, tzinfo=UTC)
    baseline = _write_dsm(tmp_path / "baseline.tif", np.ones((2, 2)))
    current = _write_dsm(tmp_path / "current.tif", np.ones((2, 2)))
    calculation_identity = _identity(baseline, current)
    calculation_digest = calculation_identity.canonical_digest()
    attempt = _expired_attempt(now, worker_instance_id="local-analysis-worker-1")

    class Intents(_UnusedIntentMethods):
        def get(
            self, analysis_id: str, *, organization_id: str
        ) -> _IntentRecord | None:
            if (analysis_id, organization_id) != ("analysis-input", "org-a"):
                return None
            return _IntentRecord(
                analysis_id=analysis_id,
                calculation_request_id="calculation-input",
                created_at=now,
            )

    class Calculations(_UnusedCalculationMethods):
        def __init__(self) -> None:
            self.input_calls = 0
            self.record = _calculation_record(
                status=CalculationExecutionStatusV2.RUNNING,
                calculation_identity_digest=calculation_digest,
                issued_at=now,
                authorization_at=now - timedelta(minutes=1),
                attempts=(attempt,),
            )
            self.leased = _calculation_record(
                status=CalculationExecutionStatusV2.RUNNING,
                calculation_identity_digest=calculation_digest,
                issued_at=now,
                authorization_at=now - timedelta(minutes=1),
                attempts=(attempt,),
                calculation_identity=calculation_identity,
            )

        def get_history(
            self, request_id: str, *, organization_id: str
        ) -> _CalculationRecord | None:
            assert (request_id, organization_id) == ("calculation-input", "org-a")
            return self.record

        def input_for_worker(
            self,
            *,
            request_id: str,
            worker_principal: Principal,
            attempt: AnalysisExecutionAttemptV2,
            now: datetime,
        ) -> _CalculationRecord | None:
            self.input_calls += 1
            return self.leased if self.input_calls == 1 else None

    calculations = Calculations()

    class Assessments:
            def get_history(self, request_id: str, *, organization_id: str) -> object | None:
                assert (request_id, organization_id) == ("analysis-input", "org-a")
                return SimpleNamespace(
                    admission=SimpleNamespace(calculation_identity_digest=calculation_digest)
                )

    def issue_capabilities(
        _record: object, **_kwargs: object
    ) -> tuple[AnalysisWorkerInputCapabilityV1, AnalysisWorkerInputCapabilityV1]:
        capability = AnalysisWorkerInputCapabilityV1(
            role="BASELINE_DSM",
            artifact_id="baseline-dsm",
            observed_sha256="sha256:" + "b" * 64,
            observed_size_bytes=4,
            download_url="http://127.0.0.1:8123/baseline.tif",
            required_headers={},
            expires_at=now + timedelta(seconds=30),
        )
        return capability, capability.model_copy(update={"role": "CURRENT_DSM"})

    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(worker_token.encode()).hexdigest(),
                    principal=_worker_principal(),
                )
            ]
        ),
    )
    app.include_router(
        build_external_analysis_worker_router(
            intents=Intents(),
            assessments=Assessments(),
            calculations=calculations,
            capability_issuer=issue_capabilities,
            clock=lambda: now,
        )
    )
    assert attempt.execution_attempt_digest is not None
    response = TestClient(app).get(
        "/v1/internal/analysis-jobs/analysis-input/input",
        headers={
            "Authorization": "Bearer " + worker_token,
            ANALYSIS_ATTEMPT_DIGEST_HEADER: attempt.execution_attempt_digest,
            ANALYSIS_WORKER_INSTANCE_ID_HEADER: attempt.worker_instance_id,
        },
    )
    assert response.status_code == 409
    assert "127.0.0.1" not in response.text
    assert calculations.input_calls == 2


def test_worker_rejects_rebound_intent_before_lease_mutation() -> None:
    """A same-org intent link cannot authorize a different AP calculation identity."""
    worker_token = "analysis-worker-identity-mismatch-token"

    class Intents(_UnusedIntentMethods):
        def get(
            self, analysis_id: str, *, organization_id: str
        ) -> _IntentRecord | None:
            if (analysis_id, organization_id) != ("analysis-rebound", "org-a"):
                return None
            return _IntentRecord(
                analysis_id=analysis_id,
                calculation_request_id="calculation-rebound",
                created_at=datetime(2026, 9, 22, tzinfo=UTC),
            )

    class Calculations(_UnusedCalculationMethods):
        def __init__(self) -> None:
            self.acquire_calls = 0

        def get_history(
            self, request_id: str, *, organization_id: str
        ) -> _CalculationRecord | None:
            if (request_id, organization_id) != ("calculation-rebound", "org-a"):
                return None
            return _calculation_record(
                status=CalculationExecutionStatusV2.QUEUED,
                calculation_identity_digest="sha256:" + "b" * 64,
                issued_at=datetime(2026, 9, 22, tzinfo=UTC),
                authorization_at=datetime(2026, 9, 22, tzinfo=UTC),
            )

        def acquire_lease(
            self,
            *,
            request_id: str,
            worker_principal: Principal,
            worker_instance_id: str,
            lease_acquisition_id: str,
            now: datetime,
        ) -> AnalysisExecutionAttemptV2 | None:
            self.acquire_calls += 1
            raise AssertionError("mismatched AP/NX link must be rejected before mutation")

    class Assessments:
        def get_history(self, request_id: str, *, organization_id: str) -> object | None:
            if (request_id, organization_id) != ("analysis-rebound", "org-a"):
                return None
            return SimpleNamespace(
                admission=SimpleNamespace(calculation_identity_digest="sha256:" + "a" * 64)
            )

    calculations = Calculations()
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(worker_token.encode()).hexdigest(),
                    principal=_worker_principal(),
                )
            ]
        ),
    )
    app.include_router(
        build_external_analysis_worker_router(
            intents=Intents(),
            assessments=Assessments(),
            calculations=calculations,
            capability_issuer=_unexpected_capability_issuer,
            clock=lambda: datetime(2026, 9, 22, tzinfo=UTC),
        )
    )
    response = TestClient(app).post(
        "/v1/internal/analysis-jobs/analysis-rebound:lease",
        headers={"Authorization": "Bearer " + worker_token},
        json={"workerInstanceId": "worker-a", "leaseAcquisitionId": "rebound-lease"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "ANALYSIS_IDENTITY_MISMATCH"
    assert calculations.acquire_calls == 0
