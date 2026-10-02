"""Authenticated internal routes for the opt-in Analysis calculation worker.

This is not a public product surface and it is never mounted by production
composition.  It maps the frozen event-contract transport onto NX's existing
lease, input, report, and failure transitions without adding execution policy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from ksi_event_contracts.external_analysis_activation import AnalysisActivationV1
from ksi_event_contracts.external_analysis_worker import (
    ANALYSIS_ATTEMPT_DIGEST_HEADER,
    ANALYSIS_WORKER_INSTANCE_ID_HEADER,
    AnalysisWorkerFailureRequestV1,
    AnalysisWorkerInputCapabilityV1,
    AnalysisWorkerInputResponseV1,
    AnalysisWorkerInputV1,
    AnalysisWorkerLeaseRequestV1,
    AnalysisWorkerLeaseViewV1,
    AnalysisWorkerMutationViewV1,
    AnalysisWorkerPendingItemV1,
    AnalysisWorkerPendingListV1,
    AnalysisWorkerRenewRequestV1,
    AnalysisWorkerReportRequestV1,
)
from ksi_event_contracts.external_relative_volume_analysis import CalculationIdentityV2
from ksi_event_contracts.external_relative_volume_calculation import (
    AnalysisExecutionAttemptV2,
    RelativeVolumeCalculationFailureV2,
    RelativeVolumeCalculationReportV2,
)

from ksi_core.domains.external.quantity.external_relative_volume_calculations import (
    CalculationExecutionRecordV2,
    CalculationExecutionStatusV2,
)
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, require_permission

_INTERNAL_BASE = "/v1/internal/analysis-jobs"


class _WorkerIntentRecordPort(Protocol):
    @property
    def analysis_id(self) -> str: ...

    @property
    def calculation_request_id(self) -> str | None: ...


class _WorkerIntentPort(Protocol):
    def get(
        self, analysis_id: str, *, organization_id: str
    ) -> _WorkerIntentRecordPort | None: ...

    def list_for_organization(
        self, *, organization_id: str
    ) -> tuple[_WorkerIntentRecordPort, ...]: ...


class _WorkerResourceEnvelopePort(Protocol):
    @property
    def max_deadline_seconds(self) -> float: ...

    @property
    def max_retry_attempts(self) -> int: ...


class _WorkerAuthorizationPort(Protocol):
    @property
    def authorized_at(self) -> datetime: ...

    @property
    def resource_envelope(self) -> _WorkerResourceEnvelopePort: ...


class _WorkerAdmissionPort(Protocol):
    @property
    def calculation_identity_digest(self) -> str | None: ...

    @property
    def calculation_identity(self) -> CalculationIdentityV2 | None: ...


class _WorkerCalculationRecordPort(Protocol):
    @property
    def calculation_identity_digest(self) -> str: ...

    @property
    def admission(self) -> _WorkerAdmissionPort: ...

    @property
    def issued_at(self) -> datetime: ...

    @property
    def attempts(self) -> tuple[AnalysisExecutionAttemptV2, ...]: ...

    @property
    def authorization(self) -> _WorkerAuthorizationPort: ...

    @property
    def status(self) -> CalculationExecutionStatusV2: ...

    @property
    def active_attempt(self) -> AnalysisExecutionAttemptV2 | None: ...


class _WorkerCalculationPort(Protocol):
    def get_history(
        self, request_id: str, *, organization_id: str
    ) -> _WorkerCalculationRecordPort | None: ...

    def acquire_lease(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        worker_instance_id: str,
        lease_acquisition_id: str,
        now: datetime,
    ) -> AnalysisExecutionAttemptV2 | None: ...

    def input_for_worker(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        attempt: AnalysisExecutionAttemptV2,
        now: datetime,
    ) -> _WorkerCalculationRecordPort | None: ...

    def renew_lease(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        attempt: AnalysisExecutionAttemptV2,
        now: datetime,
    ) -> AnalysisExecutionAttemptV2 | None: ...

    def record_report(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        report: RelativeVolumeCalculationReportV2,
        now: datetime,
    ) -> _WorkerCalculationRecordPort | None: ...

    def record_failure(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        failure: RelativeVolumeCalculationFailureV2,
        now: datetime,
    ) -> _WorkerCalculationRecordPort | None: ...


@dataclass(frozen=True, slots=True)
class _LinkedWorkerIntent:
    analysis_id: str
    calculation_request_id: str


class AnalysisWorkerCapabilityIssuer:
    """Core-local capability issuer boundary; it is injected only by local graph wiring."""

    def __call__(
        self,
        record: CalculationExecutionRecordV2,
        *,
        attempt: AnalysisExecutionAttemptV2,
        principal: Principal,
        now: datetime,
    ) -> tuple[AnalysisWorkerInputCapabilityV1, AnalysisWorkerInputCapabilityV1] | None:
        raise NotImplementedError


def build_external_analysis_worker_router(
    *,
    intents: _WorkerIntentPort,
    assessments: Any,
    calculations: _WorkerCalculationPort,
    capability_issuer: Callable[
        ..., tuple[AnalysisWorkerInputCapabilityV1, AnalysisWorkerInputCapabilityV1] | None
    ],
    clock: Callable[[], datetime] | None = None,
    activation: AnalysisActivationV1 | None = None,
) -> APIRouter:
    """Build six worker-only endpoints over the exact durable calculation record."""
    now = clock or (lambda: datetime.now(UTC))
    router = APIRouter(tags=["external-analysis-worker"])
    worker = require_permission(Permission.ANALYSIS_WORK)

    def require_worker(principal: Principal, *, checked_at: datetime | None = None) -> datetime:
        if principal.kind is not PrincipalKind.ANALYSIS_WORKER:
            raise HTTPException(status_code=403, detail="WORKER_PERMISSION_REQUIRED")
        current_time = checked_at or now()
        if activation is not None:
            if not activation.is_current_at(current_time):
                raise HTTPException(status_code=503, detail="ANALYSIS_ACTIVATION_EXPIRED")
            if (
                principal.principal_id != activation.worker_principal_id
                or principal.organization_id != activation.organization_id
            ):
                raise HTTPException(status_code=403, detail="ANALYSIS_ACTIVATION_WORKER_MISMATCH")
        return current_time

    def intent_for(analysis_id: str, principal: Principal) -> _LinkedWorkerIntent:
        intent = intents.get(analysis_id, organization_id=principal.organization_id)
        if intent is None or intent.calculation_request_id is None:
            raise HTTPException(status_code=404, detail="ANALYSIS_JOB_NOT_FOUND")
        return _LinkedWorkerIntent(
            analysis_id=intent.analysis_id,
            calculation_request_id=intent.calculation_request_id,
        )

    def has_matching_admission(
        intent: _WorkerIntentRecordPort | _LinkedWorkerIntent,
        record: _WorkerCalculationRecordPort,
        principal: Principal,
    ) -> bool:
        assessment = assessments.get_history(
            intent.analysis_id, organization_id=principal.organization_id
        )
        admission = getattr(assessment, "admission", None)
        return (
            admission is not None
            and admission.calculation_identity_digest is not None
            and admission.calculation_identity_digest == record.calculation_identity_digest
        )

    def is_discovery_eligible(
        intent: _WorkerIntentRecordPort | _LinkedWorkerIntent,
        record: _WorkerCalculationRecordPort,
        principal: Principal,
        listed_at: datetime,
    ) -> bool:
        """Require the same current AP admission NX sealed before listing a job."""
        if not has_matching_admission(intent, record, principal):
            return False
        witness = assessments.prepare_execution_witness(
            calculation_identity_digest=record.calculation_identity_digest,
            organization_id=principal.organization_id,
            now=listed_at,
            expected_admission=record.admission,
        )
        current = assessments.execution_witness_is_current(witness=witness, now=listed_at)
        admission = getattr(current, "admission", None)
        return (
            admission is not None
            and admission == record.admission
            and admission.calculation_identity_digest is not None
            and admission.calculation_identity_digest == record.calculation_identity_digest
        )

    def record_for(
        intent: _LinkedWorkerIntent, principal: Principal
    ) -> _WorkerCalculationRecordPort:
        record = calculations.get_history(
            intent.calculation_request_id, organization_id=principal.organization_id
        )
        if record is None:
            raise HTTPException(status_code=404, detail="ANALYSIS_JOB_NOT_FOUND")
        if not has_matching_admission(intent, record, principal):
            raise HTTPException(status_code=409, detail="ANALYSIS_IDENTITY_MISMATCH")
        return record

    def lease_view(
        intent: _LinkedWorkerIntent, attempt: AnalysisExecutionAttemptV2
    ) -> AnalysisWorkerLeaseViewV1:
        return AnalysisWorkerLeaseViewV1(
            analysis_id=intent.analysis_id,
            calculation_request_id=intent.calculation_request_id,
            attempt=attempt,
        )

    def mutation_view(
        intent: _LinkedWorkerIntent, record: _WorkerCalculationRecordPort
    ) -> AnalysisWorkerMutationViewV1:
        return AnalysisWorkerMutationViewV1(
            analysis_id=intent.analysis_id,
            calculation_request_id=intent.calculation_request_id,
            execution_state=record.status.value,
            attempt=record.active_attempt,
        )

    @router.get(_INTERNAL_BASE, response_model=AnalysisWorkerPendingListV1)
    def list_jobs(
        limit: int = Query(default=50, ge=1, le=200),
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> AnalysisWorkerPendingListV1:
        listed_at = require_worker(principal)
        items: list[AnalysisWorkerPendingItemV1] = []
        seen_calculation_ids: set[str] = set()
        for intent in intents.list_for_organization(organization_id=principal.organization_id):
            calculation_request_id = intent.calculation_request_id
            if calculation_request_id is None:
                continue
            if calculation_request_id in seen_calculation_ids:
                continue
            record = calculations.get_history(
                calculation_request_id, organization_id=principal.organization_id
            )
            if (
                record is None
                or not _is_discoverable(record, listed_at)
                or not is_discovery_eligible(intent, record, principal, listed_at)
            ):
                continue
            seen_calculation_ids.add(calculation_request_id)
            items.append(
                AnalysisWorkerPendingItemV1(
                    analysis_id=intent.analysis_id,
                    calculation_request_id=calculation_request_id,
                    issued_at=record.issued_at,
                )
            )
            if len(items) >= limit:
                break
        return AnalysisWorkerPendingListV1(items=tuple(items))

    @router.post(_INTERNAL_BASE + "/{analysis_id}:lease", response_model=AnalysisWorkerLeaseViewV1)
    def lease_job(
        analysis_id: str,
        request: AnalysisWorkerLeaseRequestV1,
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> AnalysisWorkerLeaseViewV1:
        checked_at = require_worker(principal)
        intent = intent_for(analysis_id, principal)
        record_for(intent, principal)
        attempt = calculations.acquire_lease(
            request_id=intent.calculation_request_id,
            worker_principal=principal,
            worker_instance_id=request.worker_instance_id,
            lease_acquisition_id=request.lease_acquisition_id,
            now=checked_at,
        )
        if attempt is None:
            raise HTTPException(status_code=409, detail="ANALYSIS_LEASE_UNAVAILABLE")
        return lease_view(intent, attempt)

    @router.get(
        _INTERNAL_BASE + "/{analysis_id}/input", response_model=AnalysisWorkerInputResponseV1
    )
    def job_input(
        analysis_id: str,
        attempt_digest: str | None = Header(default=None, alias=ANALYSIS_ATTEMPT_DIGEST_HEADER),
        worker_instance_id: str | None = Header(
            default=None, alias=ANALYSIS_WORKER_INSTANCE_ID_HEADER
        ),
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> AnalysisWorkerInputResponseV1:
        checked_at = require_worker(principal)
        if not attempt_digest or not worker_instance_id:
            raise HTTPException(status_code=409, detail="ANALYSIS_INPUT_FENCE_REQUIRED")
        intent = intent_for(analysis_id, principal)
        record = record_for(intent, principal)
        attempt = record.active_attempt
        if (
            attempt is None
            or attempt.execution_attempt_digest != attempt_digest
            or attempt.worker_instance_id != worker_instance_id
        ):
            raise HTTPException(status_code=409, detail="ANALYSIS_INPUT_FENCE_REJECTED")
        leased = calculations.input_for_worker(
            request_id=intent.calculation_request_id,
            worker_principal=principal,
            attempt=attempt,
            now=checked_at,
        )
        if leased is None or leased.admission.calculation_identity is None:
            raise HTTPException(status_code=409, detail="ANALYSIS_INPUT_FENCE_REJECTED")
        inputs = capability_issuer(leased, attempt=attempt, principal=principal, now=checked_at)
        if inputs is None:
            raise HTTPException(status_code=409, detail="ANALYSIS_INPUT_UNAVAILABLE")
        # Presigning is external I/O.  It may run long enough for the lease,
        # worker identity, deadline, or AP witness to change, so recheck the
        # exact fence before returning a bearer URL.
        final_at = now()
        require_worker(principal, checked_at=final_at)
        final = calculations.input_for_worker(
            request_id=intent.calculation_request_id,
            worker_principal=principal,
            attempt=attempt,
            now=final_at,
        )
        if final is None or final.admission.calculation_identity is None:
            raise HTTPException(status_code=409, detail="ANALYSIS_INPUT_FENCE_REJECTED")
        return AnalysisWorkerInputResponseV1(
            input=AnalysisWorkerInputV1(
                analysis_id=intent.analysis_id,
                calculation_request_id=intent.calculation_request_id,
                attempt=attempt,
                calculation_identity=leased.admission.calculation_identity,
                inputs=inputs,
            )
        )

    @router.post(_INTERNAL_BASE + "/{analysis_id}:renew", response_model=AnalysisWorkerLeaseViewV1)
    def renew_job(
        analysis_id: str,
        request: AnalysisWorkerRenewRequestV1,
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> AnalysisWorkerLeaseViewV1:
        checked_at = require_worker(principal)
        intent = intent_for(analysis_id, principal)
        record_for(intent, principal)
        attempt = calculations.renew_lease(
            request_id=intent.calculation_request_id,
            worker_principal=principal,
            attempt=request.attempt,
            now=checked_at,
        )
        if attempt is None:
            raise HTTPException(status_code=409, detail="ANALYSIS_LEASE_RENEWAL_REJECTED")
        return lease_view(intent, attempt)

    @router.post(
        _INTERNAL_BASE + "/{analysis_id}:report", response_model=AnalysisWorkerMutationViewV1
    )
    def report_job(
        analysis_id: str,
        request: AnalysisWorkerReportRequestV1,
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> AnalysisWorkerMutationViewV1:
        checked_at = require_worker(principal)
        intent = intent_for(analysis_id, principal)
        record_for(intent, principal)
        record = calculations.record_report(
            request_id=intent.calculation_request_id,
            worker_principal=principal,
            report=request.report,
            now=checked_at,
        )
        if record is None:
            raise HTTPException(status_code=409, detail="ANALYSIS_REPORT_FENCE_REJECTED")
        return mutation_view(intent, record)

    @router.post(
        _INTERNAL_BASE + "/{analysis_id}:failure", response_model=AnalysisWorkerMutationViewV1
    )
    def fail_job(
        analysis_id: str,
        request: AnalysisWorkerFailureRequestV1,
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> AnalysisWorkerMutationViewV1:
        checked_at = require_worker(principal)
        intent = intent_for(analysis_id, principal)
        record_for(intent, principal)
        record = calculations.record_failure(
            request_id=intent.calculation_request_id,
            worker_principal=principal,
            failure=request.failure,
            now=checked_at,
        )
        if record is None:
            raise HTTPException(status_code=409, detail="ANALYSIS_FAILURE_FENCE_REJECTED")
        return mutation_view(intent, record)

    return router


def _is_discoverable(record: _WorkerCalculationRecordPort, now: datetime) -> bool:
    """Expose queued work and an expired RUNNING fence eligible for takeover.

    A worker restart must be able to rediscover a request whose prior lease
    expired.  Currentness is rechecked by NX during ``acquire_lease``; this
    listing merely avoids hiding a potentially reclaimable record forever.
    """
    envelope = record.authorization.resource_envelope
    deadline = record.authorization.authorized_at + timedelta(
        seconds=envelope.max_deadline_seconds
    )
    if now >= deadline:
        return False
    if record.status.value == "QUEUED":
        return len(record.attempts) < envelope.max_retry_attempts
    attempt = record.active_attempt
    return (
        record.status.value == "RUNNING"
        and attempt is not None
        and attempt.lease_expires_at <= now
        and len(record.attempts) < envelope.max_retry_attempts
    )


__all__ = ["AnalysisWorkerCapabilityIssuer", "build_external_analysis_worker_router"]
