"""Unmounted Core ledger for fixed-profile external volume execution."""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_relative_volume_analysis import (
    AdmissionDispositionV2,
    AdmissionV2,
    CalculationIdentityV2,
)
from ksi_event_contracts.external_relative_volume_calculation import (
    AnalysisExecutionAttemptV2,
    AnalysisExecutionAuthorizationV2,
    RelativeVolumeCalculationFailureV2,
    RelativeVolumeCalculationReportV2,
)

from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    ExternalRelativeVolumeAnalysisStore,
)
from ksi_core.foundation.api_base import iso_utc
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, principal_permissions

_VERSION = 1
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _digest(value: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _event_digest(raw: dict[str, object]) -> str:
    return _digest({key: value for key, value in raw.items() if key != "eventDigest"})


class CalculationExecutionRecoveryError(RuntimeError):
    """An execution journal cannot be replayed safely."""


class CalculationExecutionStatusV2(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CalculationCurrentDispositionV2(StrEnum):
    AVAILABLE = "AVAILABLE"
    REASSESSMENT_REQUIRED = "REASSESSMENT_REQUIRED"
    PENDING = "PENDING"
    FAILED = "FAILED"
    EXECUTION_DEADLINE_EXPIRED = "EXECUTION_DEADLINE_EXPIRED"
    EXECUTION_RETRY_EXHAUSTED = "EXECUTION_RETRY_EXHAUSTED"


@dataclass(frozen=True, slots=True)
class CalculationExecutionRecordV2:
    request_id: str
    organization_id: str
    calculation_identity_digest: str
    request_digest: str
    idempotency_digest: str
    issued_at: datetime
    admission: AdmissionV2
    authorization: AnalysisExecutionAuthorizationV2
    status: CalculationExecutionStatusV2
    attempts: tuple[AnalysisExecutionAttemptV2, ...] = ()
    report: RelativeVolumeCalculationReportV2 | None = None
    failure: RelativeVolumeCalculationFailureV2 | None = None
    consulted_admission: AdmissionV2 | None = None

    @property
    def active_attempt(self) -> AnalysisExecutionAttemptV2 | None:
        return self.attempts[-1] if self.attempts else None


@dataclass(frozen=True, slots=True)
class CalculationCurrentViewV2:
    disposition: CalculationCurrentDispositionV2
    record: CalculationExecutionRecordV2
    consulted_admission: AdmissionV2 | None
    report: RelativeVolumeCalculationReportV2 | None


class ExternalRelativeVolumeCalculationStore:
    """Issue and lease only from a fresh local assessment witness."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        assessments: ExternalRelativeVolumeAnalysisStore,
        resource_envelope: ResourceEnvelopeV1,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        if (
            resource_envelope.resource_envelope_digest is None
            or resource_envelope.resource_envelope_digest != resource_envelope.canonical_digest()
        ):
            raise ValueError("calculation execution requires a sealed resource envelope")
        self._journal = journal
        self._assessments = assessments
        self._resource_envelope = resource_envelope.model_copy(deep=True)
        self._coordinator = coordinator or assessments.coordinator
        if self._coordinator is not assessments.coordinator:
            raise ValueError("calculation and assessment stores must share a coordinator")
        self._lock = threading.RLock()
        self._records: dict[str, CalculationExecutionRecordV2] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._by_calculation: dict[tuple[str, str], str] = {}
        self._lease_acquisitions: dict[str, set[str]] = {}
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException as exc:
            journal.close()
            if isinstance(exc, CalculationExecutionRecoveryError):
                raise
            raise CalculationExecutionRecoveryError(str(exc)) from exc

    def issue(
        self,
        *,
        principal: Principal,
        request_id: str,
        calculation_identity_digest: str,
        idempotency_key: str,
        now: datetime,
    ) -> CalculationExecutionRecordV2:
        self._require_site_write(principal)
        self._require_utc(now)
        self._require_digest(calculation_identity_digest, "calculation identity")
        if not request_id.strip() or not idempotency_key.strip():
            raise ValueError("request and idempotency identifiers are required")
        witness = self._assessments.prepare_execution_witness(
            calculation_identity_digest=calculation_identity_digest,
            organization_id=principal.organization_id,
            now=now,
        )
        request_digest = _digest(
            {
                "requestId": request_id,
                "calculationIdentityDigest": calculation_identity_digest,
            }
        )
        idempotency_digest = "sha256:" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        with self._lock:
            existing_id = self._idempotency.get((principal.organization_id, idempotency_digest))
            if existing_id is not None:
                existing = self._records[existing_id]
                if existing.request_digest != request_digest:
                    raise ValueError("idempotency key is already bound to another calculation")
                self._require_record_scope(principal, existing)
                return self._without_numeric_result(self._public_record(existing))
            existing_by_identity = self._by_calculation.get(
                (principal.organization_id, calculation_identity_digest)
            )
            if existing_by_identity is not None:
                self._require_record_scope(principal, self._records[existing_by_identity])
                return self._without_numeric_result(
                    self._public_record(self._records[existing_by_identity])
                )
        assessment = self._assessments.execution_witness_is_current(witness=witness, now=now)
        if assessment is None or not self._admission_can_execute(assessment.admission):
            raise RuntimeError("calculation requires a current admitted assessment")
        self._require_identity_scope(principal, assessment.admission.calculation_identity)
        admission_digest = assessment.admission.admission_digest
        envelope_digest = self._resource_envelope.resource_envelope_digest
        assert admission_digest is not None
        assert envelope_digest is not None
        authorization = AnalysisExecutionAuthorizationV2(
            authorization_id="calculation-authorization-" + request_id,
            organization_id=principal.organization_id,
            calculation_identity_digest=calculation_identity_digest,
            admission_digest=admission_digest,
            resource_envelope=self._resource_envelope,
            resource_envelope_digest=envelope_digest,
            authorized_at=now,
        ).sealed()
        raw = {
            "kind": "external-relative-volume-calculation-issued",
            "version": _VERSION,
            "organizationId": principal.organization_id,
            "requestId": request_id,
            "calculationIdentityDigest": calculation_identity_digest,
            "requestDigest": request_digest,
            "idempotencyDigest": idempotency_digest,
            "issuedAt": iso_utc(now),
            "admission": assessment.admission.model_dump(by_alias=True, mode="json"),
            "authorization": authorization.model_dump(by_alias=True, mode="json"),
        }
        with self._coordinator.guarded_read(), self._lock:
            existing_id = self._idempotency.get((principal.organization_id, idempotency_digest))
            if existing_id is not None:
                existing = self._records[existing_id]
                if existing.request_digest != request_digest:
                    raise ValueError("idempotency key is already bound to another calculation")
                self._require_record_scope(principal, existing)
                return self._without_numeric_result(self._public_record(existing))
            existing_by_identity = self._by_calculation.get(
                (principal.organization_id, calculation_identity_digest)
            )
            if existing_by_identity is not None:
                self._require_record_scope(principal, self._records[existing_by_identity])
                return self._without_numeric_result(
                    self._public_record(self._records[existing_by_identity])
                )
            assessment = self._assessments.execution_witness_is_current(witness=witness, now=now)
            if assessment is None or assessment.admission != AdmissionV2.model_validate(
                raw["admission"]
            ):
                raise RuntimeError("assessment changed before calculation issue")
            self._require_identity_scope(principal, assessment.admission.calculation_identity)
            queued = sum(
                1
                for candidate in self._records.values()
                if candidate.organization_id == principal.organization_id
                and candidate.status is CalculationExecutionStatusV2.QUEUED
            )
            if queued >= self._resource_envelope.max_queue_depth:
                raise RuntimeError("calculation queue capacity is exhausted")
            self._append_locked(raw)
            return self._without_numeric_result(self._public_record(self._records[request_id]))

    def acquire_lease(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        worker_instance_id: str,
        lease_acquisition_id: str,
        now: datetime,
    ) -> AnalysisExecutionAttemptV2 | None:
        self._require_worker(worker_principal)
        self._require_utc(now)
        if not worker_instance_id.strip() or not lease_acquisition_id.strip():
            raise ValueError("worker and lease acquisition identifiers are required")
        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != worker_principal.organization_id:
                return None
            if record.status in {
                CalculationExecutionStatusV2.COMPLETED,
                CalculationExecutionStatusV2.FAILED,
            }:
                return None
            active = record.active_attempt
            if active is not None and active.lease_expires_at > now:
                if (
                    active.worker_instance_id == worker_instance_id
                    and active.lease_acquisition_id == lease_acquisition_id
                ):
                    return active.model_copy(deep=True)
                return None
            if lease_acquisition_id in self._lease_acquisitions.get(request_id, set()):
                return None
            if len(record.attempts) >= record.authorization.resource_envelope.max_retry_attempts:
                return None
            if now >= self._deadline(record):
                return None
        witness = self._assessments.prepare_execution_witness(
            calculation_identity_digest=record.calculation_identity_digest,
            organization_id=record.organization_id,
            now=now,
            expected_admission=record.admission,
        )
        with self._coordinator.guarded_read(), self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != worker_principal.organization_id:
                return None
            assessment = self._assessments.execution_witness_is_current(witness=witness, now=now)
            if assessment is None or assessment.admission != record.admission:
                return None
            active = record.active_attempt
            if active is not None and active.lease_expires_at > now:
                return None
            if lease_acquisition_id in self._lease_acquisitions.get(request_id, set()):
                return None
            if len(record.attempts) >= record.authorization.resource_envelope.max_retry_attempts:
                return None
            if now >= self._deadline(record):
                return None
            running = sum(
                1
                for candidate in self._records.values()
                if candidate.organization_id == record.organization_id
                and candidate.status is CalculationExecutionStatusV2.RUNNING
                and candidate.active_attempt is not None
                and candidate.active_attempt.lease_expires_at > now
            )
            if running >= record.authorization.resource_envelope.max_tenant_concurrency:
                return None
            generation = len(record.attempts) + 1
            authorization_digest = record.authorization.execution_authorization_digest
            assert authorization_digest is not None
            attempt = AnalysisExecutionAttemptV2(
                attempt_id=f"calculation-attempt-{request_id}-{generation}",
                authorization=record.authorization,
                authorization_digest=authorization_digest,
                worker_instance_id=worker_instance_id,
                lease_acquisition_id=lease_acquisition_id,
                lease_generation=generation,
                issued_at=now,
                lease_expires_at=min(
                    now
                    + timedelta(
                        seconds=record.authorization.resource_envelope.lease_duration_seconds
                    ),
                    self._deadline(record),
                ),
            ).sealed()
            raw = {
                "kind": "external-relative-volume-calculation-leased",
                "version": _VERSION,
                "requestId": request_id,
                "attempt": attempt.model_dump(by_alias=True, mode="json"),
            }
            self._append_locked(raw)
            return attempt.model_copy(deep=True)

    def renew_lease(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        attempt: AnalysisExecutionAttemptV2,
        now: datetime,
    ) -> AnalysisExecutionAttemptV2 | None:
        """Extend only the exact active fence while a fresh assessment remains admitted."""
        self._require_worker(worker_principal)
        self._require_utc(now)
        with self._lock:
            record = self._records.get(request_id)
            if (
                record is None
                or record.organization_id != worker_principal.organization_id
                or record.active_attempt != attempt
                or attempt.lease_expires_at <= now
                or now >= self._deadline(record)
            ):
                return None
            calculation_identity_digest = record.calculation_identity_digest
            organization_id = record.organization_id
            expected_admission = record.admission
        witness = self._assessments.prepare_execution_witness(
            calculation_identity_digest=calculation_identity_digest,
            organization_id=organization_id,
            now=now,
            expected_admission=expected_admission,
        )
        with self._coordinator.guarded_read(), self._lock:
            record = self._records.get(request_id)
            assessment = self._assessments.execution_witness_is_current(witness=witness, now=now)
            if (
                record is None
                or record.organization_id != worker_principal.organization_id
                or record.status is not CalculationExecutionStatusV2.RUNNING
                or record.active_attempt != attempt
                or attempt.lease_expires_at <= now
                or now >= self._deadline(record)
                or assessment is None
                or assessment.admission != record.admission
            ):
                return None
            renewed = attempt.model_copy(
                update={
                    "lease_expires_at": min(
                        now
                        + timedelta(
                            seconds=record.authorization.resource_envelope.lease_duration_seconds
                        ),
                        self._deadline(record),
                    ),
                    "execution_attempt_digest": None,
                }
            ).sealed()
            raw = {
                "kind": "external-relative-volume-calculation-renewed",
                "version": _VERSION,
                "requestId": request_id,
                "renewedAt": iso_utc(now),
                "attempt": renewed.model_dump(by_alias=True, mode="json"),
            }
            self._append_locked(raw)
            return renewed.model_copy(deep=True)

    def input_for_worker(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        attempt: AnalysisExecutionAttemptV2,
        now: datetime,
    ) -> CalculationExecutionRecordV2 | None:
        """Return a sealed input only to the principal holding an active exact fence."""
        self._require_worker(worker_principal)
        self._require_utc(now)
        with self._lock:
            record = self._records.get(request_id)
            if (
                record is None
                or record.organization_id != worker_principal.organization_id
                or record.active_attempt != attempt
                or attempt.lease_expires_at <= now
                or now >= self._deadline(record)
            ):
                return None
            calculation_identity_digest = record.calculation_identity_digest
            organization_id = record.organization_id
            expected_admission = record.admission
        witness = self._assessments.prepare_execution_witness(
            calculation_identity_digest=calculation_identity_digest,
            organization_id=organization_id,
            now=now,
            expected_admission=expected_admission,
        )
        with self._coordinator.guarded_read(), self._lock:
            record = self._records.get(request_id)
            assessment = self._assessments.execution_witness_is_current(witness=witness, now=now)
            if (
                record is None
                or record.organization_id != worker_principal.organization_id
                or record.status is not CalculationExecutionStatusV2.RUNNING
                or record.active_attempt != attempt
                or attempt.lease_expires_at <= now
                or now >= self._deadline(record)
                or assessment is None
                or assessment.admission != record.admission
            ):
                return None
            return self._public_record(record)

    def record_report(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        report: RelativeVolumeCalculationReportV2,
        now: datetime,
    ) -> CalculationExecutionRecordV2 | None:
        """Persist a fenced report even if late assessment currentness is absent.

        The historical record retains both its original admission and the
        current admission consulted at report time. A later current projection
        decides whether it can expose numeric output.
        """
        self._require_worker(worker_principal)
        self._require_utc(now)
        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != worker_principal.organization_id:
                return None
            if record.report is not None:
                return self._public_record(record) if record.report == report else None
            if not self._report_matches_active(record, report, now):
                return None
            calculation_identity_digest = record.calculation_identity_digest
            organization_id = record.organization_id
            expected_admission = record.admission
        witness = self._assessments.prepare_execution_witness(
            calculation_identity_digest=calculation_identity_digest,
            organization_id=organization_id,
            now=now,
            expected_admission=expected_admission,
        )
        with self._coordinator.guarded_read(), self._lock:
            record = self._records.get(request_id)
            if (
                record is None
                or record.organization_id != worker_principal.organization_id
                or not self._report_matches_active(record, report, now)
            ):
                return None
            consulted = self._assessments.execution_witness_is_current(witness=witness, now=now)
            raw = {
                "kind": "external-relative-volume-calculation-reported",
                "version": _VERSION,
                "requestId": request_id,
                "report": report.model_dump(by_alias=True, mode="json"),
                "consultedAdmission": (
                    consulted.admission.model_dump(by_alias=True, mode="json")
                    if consulted is not None
                    else None
                ),
            }
            self._append_locked(raw)
            return self._public_record(self._records[request_id])

    def record_failure(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        failure: RelativeVolumeCalculationFailureV2,
        now: datetime,
    ) -> CalculationExecutionRecordV2 | None:
        """Store one fenced failure; it does not create a numeric current result."""
        self._require_worker(worker_principal)
        self._require_utc(now)
        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != worker_principal.organization_id:
                return None
            if record.failure is not None:
                return self._public_record(record) if record.failure == failure else None
            if not self._failure_matches_active(record, failure, now):
                return None
            calculation_identity_digest = record.calculation_identity_digest
            organization_id = record.organization_id
            expected_admission = record.admission
        witness = self._assessments.prepare_execution_witness(
            calculation_identity_digest=calculation_identity_digest,
            organization_id=organization_id,
            now=now,
            expected_admission=expected_admission,
        )
        with self._coordinator.guarded_read(), self._lock:
            record = self._records.get(request_id)
            if (
                record is None
                or record.organization_id != worker_principal.organization_id
                or not self._failure_matches_active(record, failure, now)
            ):
                return None
            consulted = self._assessments.execution_witness_is_current(witness=witness, now=now)
            raw = {
                "kind": "external-relative-volume-calculation-failed",
                "version": _VERSION,
                "requestId": request_id,
                "failure": failure.model_dump(by_alias=True, mode="json"),
                "consultedAdmission": (
                    consulted.admission.model_dump(by_alias=True, mode="json")
                    if consulted is not None
                    else None
                ),
            }
            self._append_locked(raw)
            return self._public_record(self._records[request_id])

    def get_history(
        self, request_id: str, *, organization_id: str
    ) -> CalculationExecutionRecordV2 | None:
        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != organization_id:
                return None
            return self._public_record(record)

    def get_history_for_principal(
        self, request_id: str, *, principal: Principal
    ) -> CalculationExecutionRecordV2 | None:
        if not self._has_site_read(principal):
            raise PermissionError("calculation history requires SITES_READ")
        record = self.get_history(request_id, organization_id=principal.organization_id)
        if record is not None:
            self._require_record_scope(principal, record)
        return record

    def get_current(
        self, *, request_id: str, principal: Principal, now: datetime
    ) -> CalculationCurrentViewV2 | None:
        """Expose numeric output only through a fresh durable assessment revision."""
        if not self._has_site_read(principal):
            raise PermissionError("calculation result requires SITES_READ")
        self._require_utc(now)
        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != principal.organization_id:
                return None
            self._require_record_scope(principal, record)
            calculation_identity_digest = record.calculation_identity_digest
            organization_id = record.organization_id
            expected_admission = (
                record.admission
                if record.status
                in {
                    CalculationExecutionStatusV2.QUEUED,
                    CalculationExecutionStatusV2.RUNNING,
                }
                else None
            )
        witness = self._assessments.prepare_execution_witness(
            calculation_identity_digest=calculation_identity_digest,
            organization_id=organization_id,
            now=now,
            expected_admission=expected_admission,
        )
        with self._coordinator.guarded_read(), self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != principal.organization_id:
                return None
            consulted = self._assessments.execution_witness_is_current(witness=witness, now=now)
            public = self._public_record(record)
            if consulted is None or not self._admission_can_execute(consulted.admission):
                return CalculationCurrentViewV2(
                    CalculationCurrentDispositionV2.REASSESSMENT_REQUIRED,
                    self._without_numeric_result(public),
                    None,
                    None,
                )
            admission = consulted.admission.model_copy(deep=True)
            if record.status is CalculationExecutionStatusV2.COMPLETED:
                return CalculationCurrentViewV2(
                    CalculationCurrentDispositionV2.AVAILABLE,
                    public,
                    admission,
                    record.report.model_copy(deep=True) if record.report is not None else None,
                )
            if record.status is CalculationExecutionStatusV2.FAILED:
                return CalculationCurrentViewV2(
                    CalculationCurrentDispositionV2.FAILED,
                    public,
                    admission,
                    None,
                )
            # A current projection must never leave a durable but no-longer
            # runnable record pending forever.  These effective terminal
            # dispositions are read-only: the immutable journal remains the
            # historical account of attempts and GET never appends a failure.
            if now >= self._deadline(record):
                return CalculationCurrentViewV2(
                    CalculationCurrentDispositionV2.EXECUTION_DEADLINE_EXPIRED,
                    self._without_numeric_result(public),
                    admission,
                    None,
                )
            active_attempt = record.active_attempt
            active_fence_is_live = (
                record.status is CalculationExecutionStatusV2.RUNNING
                and active_attempt is not None
                and active_attempt.lease_expires_at > now
            )
            if (
                len(record.attempts) >= record.authorization.resource_envelope.max_retry_attempts
                and not active_fence_is_live
            ):
                return CalculationCurrentViewV2(
                    CalculationCurrentDispositionV2.EXECUTION_RETRY_EXHAUSTED,
                    self._without_numeric_result(public),
                    admission,
                    None,
                )
            return CalculationCurrentViewV2(
                CalculationCurrentDispositionV2.PENDING,
                public,
                admission,
                None,
            )

    @staticmethod
    def _report_matches_active(
        record: CalculationExecutionRecordV2,
        report: RelativeVolumeCalculationReportV2,
        now: datetime,
    ) -> bool:
        attempt = record.active_attempt
        return (
            record.status is CalculationExecutionStatusV2.RUNNING
            and attempt is not None
            and attempt.lease_expires_at > now
            and report.attempt == attempt
            and report.attempt_digest == attempt.execution_attempt_digest
            and report.numeric_result.calculation_identity_digest
            == record.calculation_identity_digest
            and report.computed_at >= attempt.issued_at
            and report.reported_at <= now
            and report.reported_at <= attempt.lease_expires_at
            and report.computed_at <= report.reported_at
            and ExternalRelativeVolumeCalculationStore._report_binds_immutable_identity(
                record, report
            )
        )

    @staticmethod
    def _failure_matches_active(
        record: CalculationExecutionRecordV2,
        failure: RelativeVolumeCalculationFailureV2,
        now: datetime,
    ) -> bool:
        attempt = record.active_attempt
        return (
            record.status is CalculationExecutionStatusV2.RUNNING
            and attempt is not None
            and attempt.lease_expires_at > now
            and now < ExternalRelativeVolumeCalculationStore._deadline(record)
            and failure.attempt == attempt
            and failure.attempt_digest == attempt.execution_attempt_digest
            and failure.failed_at >= attempt.issued_at
            and failure.failed_at <= now
            and ExternalRelativeVolumeCalculationStore._failure_is_sealed(failure)
        )

    @staticmethod
    def _report_is_sealed(report: RelativeVolumeCalculationReportV2) -> bool:
        return (
            report.report_digest is not None and report.report_digest == report.canonical_digest()
        )

    @staticmethod
    def _failure_is_sealed(failure: RelativeVolumeCalculationFailureV2) -> bool:
        return (
            failure.failure_digest is not None
            and failure.failure_digest == failure.canonical_digest()
        )

    @staticmethod
    def _report_binds_immutable_identity(
        record: CalculationExecutionRecordV2,
        report: RelativeVolumeCalculationReportV2,
    ) -> bool:
        """Check result facts derivable from the admission, without reopening inputs.

        The worker owns raster parsing and masks; Core owns the immutable
        admission and its resource envelope.  These local cross-links must
        hold both before an append and when replaying the same journal event.
        """
        identity = record.admission.calculation_identity
        if (
            not ExternalRelativeVolumeCalculationStore._report_is_sealed(report)
            or identity is None
            or identity.calculation_identity_digest != record.calculation_identity_digest
            or identity.calculation_identity_digest != identity.canonical_digest()
            or report.numeric_result.profile_digest != identity.policy.profile_digest
        ):
            return False

        coverage = report.numeric_result.coverage
        envelope = record.authorization.resource_envelope
        if coverage.rows * coverage.columns > envelope.max_pixels:
            return False
        if len(report.model_dump_json(by_alias=True).encode("utf-8")) > envelope.max_output_bytes:
            return False

        a, b, c, d, e, f = identity.baseline_transform
        # The first profile admits only the native north-up baseline grid.
        if b != 0.0 or d != 0.0 or a <= 0.0 or e >= 0.0:
            return False
        expected_area = abs(a * e - b * d)
        # Reproduce the worker's ``Affine.translation`` composition followed
        # by Rasterio ``array_bounds`` exactly.  Do not regroup these
        # operations: a valid fractional grid can otherwise differ by one
        # IEEE-754 representable value.  Negative offsets are valid when the
        # unselected part of a floored zone window lies outside the raster.
        local_c = a * coverage.column_offset + b * coverage.row_offset + c
        local_f = d * coverage.column_offset + e * coverage.row_offset + f
        expected_bounds = (
            local_c,
            local_f + e * coverage.rows,
            local_c + a * coverage.columns,
            local_f,
        )
        return coverage.cell_area_m2 == expected_area and coverage.bounds == expected_bounds

    @staticmethod
    def _deadline(record: CalculationExecutionRecordV2) -> datetime:
        return record.authorization.authorized_at + timedelta(
            seconds=record.authorization.resource_envelope.max_deadline_seconds
        )

    @staticmethod
    def _consulted_admission_matches(
        record: CalculationExecutionRecordV2, consulted: AdmissionV2 | None
    ) -> bool:
        if consulted is None:
            return True
        identity = consulted.calculation_identity
        return (
            consulted.admission_digest is not None
            and consulted.admission_digest == consulted.canonical_digest()
            and identity is not None
            and identity.organization_id == record.organization_id
            and identity.canonical_digest() == record.calculation_identity_digest
        )

    @staticmethod
    def _admission_can_execute(admission: AdmissionV2) -> bool:
        return admission.disposition in {
            AdmissionDispositionV2.ADMIT_PROVISIONAL,
            AdmissionDispositionV2.ADMIT_EVALUATED,
        }

    @staticmethod
    def _require_utc(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("calculation time must be UTC")

    @staticmethod
    def _require_digest(value: str, description: str) -> None:
        if _DIGEST_RE.fullmatch(value) is None:
            raise ValueError(f"{description} digest is invalid")

    @staticmethod
    def _require_site_write(principal: Principal) -> None:
        granted = principal_permissions(principal)
        allowed = (
            Permission.ANALYSIS_API_CREATE in granted
            if principal.kind is PrincipalKind.ANALYSIS_MCP_CLIENT
            else Permission.SITES_WRITE in granted
        )
        if not allowed:
            raise PermissionError("calculation issue requires SITES_WRITE")

    @staticmethod
    def _has_site_read(principal: Principal) -> bool:
        granted = principal_permissions(principal)
        return (
            Permission.ANALYSIS_API_READ in granted
            if principal.kind is PrincipalKind.ANALYSIS_MCP_CLIENT
            else Permission.SITES_READ in granted
        )

    @classmethod
    def _require_identity_scope(
        cls, principal: Principal, identity: CalculationIdentityV2 | None
    ) -> None:
        if principal.kind is not PrincipalKind.ANALYSIS_MCP_CLIENT:
            return
        if (
            identity is None
            or principal.allowed_site_ids is None
            or identity.site_id not in principal.allowed_site_ids
            or principal.allowed_work_area_ids is None
            or identity.work_area_id not in principal.allowed_work_area_ids
        ):
            raise PermissionError("calculation is outside client scope")

    @classmethod
    def _require_record_scope(
        cls, principal: Principal, record: CalculationExecutionRecordV2
    ) -> None:
        cls._require_identity_scope(principal, record.admission.calculation_identity)

    @staticmethod
    def _require_worker(principal: Principal) -> None:
        if (
            principal.kind is not PrincipalKind.ANALYSIS_WORKER
            or Permission.ANALYSIS_WORK not in principal_permissions(principal)
        ):
            raise PermissionError("calculation execution requires analysis worker scope")

    def _append_locked(self, raw: dict[str, object]) -> None:
        raw["eventDigest"] = _event_digest(raw)
        try:
            self._apply(raw, mutate=False)
        except CalculationExecutionRecoveryError as exc:
            raise ValueError("calculation event is invalid") from exc
        try:
            self._journal.append(raw)
        except JournalSealedError as exc:
            raise RuntimeError("calculation journal is unavailable") from exc
        self._apply(raw)

    def _apply(self, raw: object, *, mutate: bool = True) -> None:
        try:
            if not isinstance(raw, dict) or raw.get("eventDigest") != _event_digest(raw):
                raise ValueError("calculation event digest is invalid")
            if raw.get("version") != _VERSION:
                raise ValueError("calculation event version is invalid")
            if raw.get("kind") == "external-relative-volume-calculation-issued":
                self._apply_issued(raw, mutate=mutate)
            elif raw.get("kind") == "external-relative-volume-calculation-leased":
                self._apply_leased(raw, mutate=mutate)
            elif raw.get("kind") == "external-relative-volume-calculation-renewed":
                self._apply_renewed(raw, mutate=mutate)
            elif raw.get("kind") == "external-relative-volume-calculation-reported":
                self._apply_reported(raw, mutate=mutate)
            elif raw.get("kind") == "external-relative-volume-calculation-failed":
                self._apply_failed(raw, mutate=mutate)
            else:
                raise ValueError("calculation event kind is invalid")
        except (KeyError, TypeError, ValueError) as exc:
            raise CalculationExecutionRecoveryError(str(exc)) from exc

    def _apply_issued(self, raw: dict[str, object], *, mutate: bool) -> None:
        expected = {
            "kind",
            "version",
            "eventDigest",
            "organizationId",
            "requestId",
            "calculationIdentityDigest",
            "requestDigest",
            "idempotencyDigest",
            "issuedAt",
            "admission",
            "authorization",
        }
        if set(raw) != expected or not all(
            isinstance(raw.get(field), str)
            for field in (
                "organizationId",
                "requestId",
                "calculationIdentityDigest",
                "requestDigest",
                "idempotencyDigest",
                "issuedAt",
            )
        ):
            raise ValueError("issued event shape is invalid")
        organization_id = raw["organizationId"]
        request_id = raw["requestId"]
        calculation_identity_digest = raw["calculationIdentityDigest"]
        request_digest = raw["requestDigest"]
        idempotency_digest = raw["idempotencyDigest"]
        issued_at_raw = raw["issuedAt"]
        assert isinstance(organization_id, str)
        assert isinstance(request_id, str)
        assert isinstance(calculation_identity_digest, str)
        assert isinstance(request_digest, str)
        assert isinstance(idempotency_digest, str)
        assert isinstance(issued_at_raw, str)
        self._require_digest(calculation_identity_digest, "calculation identity")
        self._require_digest(request_digest, "request")
        self._require_digest(idempotency_digest, "idempotency")
        issued_at = datetime.fromisoformat(issued_at_raw)
        self._require_utc(issued_at)
        admission = AdmissionV2.model_validate(raw["admission"])
        authorization = AnalysisExecutionAuthorizationV2.model_validate(raw["authorization"])
        if (
            admission.admission_digest is None
            or admission.admission_digest != admission.canonical_digest()
            or admission.calculation_identity is None
            or admission.calculation_identity.canonical_digest() != calculation_identity_digest
            or admission.calculation_identity.organization_id != organization_id
            or not self._admission_can_execute(admission)
            or authorization.execution_authorization_digest is None
            or authorization.execution_authorization_digest != authorization.canonical_digest()
            or authorization.organization_id != organization_id
            or authorization.calculation_identity_digest != calculation_identity_digest
            or authorization.admission_digest != admission.admission_digest
            or authorization.authorization_id != "calculation-authorization-" + request_id
            or authorization.authorized_at != issued_at
            or request_digest
            != _digest(
                {
                    "requestId": request_id,
                    "calculationIdentityDigest": calculation_identity_digest,
                }
            )
        ):
            raise ValueError("issued calculation crosslink is invalid")
        key = (organization_id, calculation_identity_digest)
        idem = (organization_id, idempotency_digest)
        if request_id in self._records or idem in self._idempotency or key in self._by_calculation:
            raise ValueError("duplicate issued calculation")
        if not mutate:
            return
        record = CalculationExecutionRecordV2(
            request_id=request_id,
            organization_id=organization_id,
            calculation_identity_digest=calculation_identity_digest,
            request_digest=request_digest,
            idempotency_digest=idempotency_digest,
            issued_at=issued_at,
            admission=admission,
            authorization=authorization,
            status=CalculationExecutionStatusV2.QUEUED,
        )
        self._records[record.request_id] = record
        self._idempotency[idem] = record.request_id
        self._by_calculation[key] = record.request_id

    def _apply_leased(self, raw: dict[str, object], *, mutate: bool) -> None:
        expected = {"kind", "version", "eventDigest", "requestId", "attempt"}
        if set(raw) != expected or not isinstance(raw.get("requestId"), str):
            raise ValueError("leased event shape is invalid")
        request_id = raw["requestId"]
        assert isinstance(request_id, str)
        attempt = AnalysisExecutionAttemptV2.model_validate(raw["attempt"])
        record = self._records.get(request_id)
        active = record.active_attempt if record is not None else None
        deadline = self._deadline(record) if record is not None else None
        expected_expiry = (
            min(
                attempt.issued_at
                + timedelta(seconds=record.authorization.resource_envelope.lease_duration_seconds),
                deadline,
            )
            if record is not None and deadline is not None
            else None
        )
        if (
            record is None
            or record.status
            not in {
                CalculationExecutionStatusV2.QUEUED,
                CalculationExecutionStatusV2.RUNNING,
            }
            or (record.status is CalculationExecutionStatusV2.QUEUED and active is not None)
            or (
                record.status is CalculationExecutionStatusV2.RUNNING
                and (active is None or active.lease_expires_at > attempt.issued_at)
            )
            or attempt.authorization != record.authorization
            or attempt.lease_generation != len(record.attempts) + 1
            or attempt.attempt_id
            != f"calculation-attempt-{record.request_id}-{attempt.lease_generation}"
            or attempt.lease_acquisition_id
            in self._lease_acquisitions.get(record.request_id, set())
            or len(record.attempts) >= record.authorization.resource_envelope.max_retry_attempts
            or attempt.issued_at < record.authorization.authorized_at
            or deadline is None
            or attempt.issued_at >= deadline
            or attempt.lease_expires_at != expected_expiry
        ):
            raise ValueError("leased calculation crosslink is invalid")
        if not mutate:
            return
        self._records[record.request_id] = replace(
            record,
            status=CalculationExecutionStatusV2.RUNNING,
            attempts=(*record.attempts, attempt),
        )
        self._lease_acquisitions.setdefault(record.request_id, set()).add(
            attempt.lease_acquisition_id
        )

    def _apply_reported(self, raw: dict[str, object], *, mutate: bool) -> None:
        expected = {"kind", "version", "eventDigest", "requestId", "report", "consultedAdmission"}
        if set(raw) != expected or not isinstance(raw.get("requestId"), str):
            raise ValueError("reported event shape is invalid")
        request_id = raw["requestId"]
        assert isinstance(request_id, str)
        report = RelativeVolumeCalculationReportV2.model_validate(raw["report"])
        consulted_raw = raw["consultedAdmission"]
        consulted = AdmissionV2.model_validate(consulted_raw) if consulted_raw is not None else None
        if consulted is not None and (
            consulted.admission_digest is None
            or consulted.admission_digest != consulted.canonical_digest()
        ):
            raise ValueError("consulted admission is not sealed")
        record = self._records.get(request_id)
        if (
            record is None
            or record.status is not CalculationExecutionStatusV2.RUNNING
            or record.report is not None
            or record.failure is not None
            or record.active_attempt != report.attempt
            or report.numeric_result.calculation_identity_digest
            != record.calculation_identity_digest
            or report.computed_at < report.attempt.issued_at
            or report.reported_at > report.attempt.lease_expires_at
            or not self._report_binds_immutable_identity(record, report)
            or not self._consulted_admission_matches(record, consulted)
        ):
            raise ValueError("reported calculation crosslink is invalid")
        if not mutate:
            return
        self._records[record.request_id] = replace(
            record,
            status=CalculationExecutionStatusV2.COMPLETED,
            report=report,
            consulted_admission=consulted,
        )

    def _apply_renewed(self, raw: dict[str, object], *, mutate: bool) -> None:
        expected = {"kind", "version", "eventDigest", "requestId", "renewedAt", "attempt"}
        if (
            set(raw) != expected
            or not isinstance(raw.get("requestId"), str)
            or not isinstance(raw.get("renewedAt"), str)
        ):
            raise ValueError("renewed event shape is invalid")
        request_id = raw["requestId"]
        renewed_at_raw = raw["renewedAt"]
        assert isinstance(request_id, str)
        assert isinstance(renewed_at_raw, str)
        renewed_at = datetime.fromisoformat(renewed_at_raw)
        self._require_utc(renewed_at)
        attempt = AnalysisExecutionAttemptV2.model_validate(raw["attempt"])
        record = self._records.get(request_id)
        active = record.active_attempt if record is not None else None
        deadline = self._deadline(record) if record is not None else None
        expected_expiry = (
            min(
                renewed_at
                + timedelta(seconds=record.authorization.resource_envelope.lease_duration_seconds),
                deadline,
            )
            if record is not None and deadline is not None
            else None
        )
        if (
            record is None
            or record.status is not CalculationExecutionStatusV2.RUNNING
            or active is None
            or attempt.attempt_id != active.attempt_id
            or attempt.worker_instance_id != active.worker_instance_id
            or attempt.lease_acquisition_id != active.lease_acquisition_id
            or attempt.lease_generation != active.lease_generation
            or attempt.authorization != record.authorization
            or attempt.issued_at != active.issued_at
            or renewed_at < active.issued_at
            or renewed_at >= active.lease_expires_at
            or deadline is None
            or renewed_at >= deadline
            or attempt.lease_expires_at <= active.lease_expires_at
            or attempt.lease_expires_at != expected_expiry
        ):
            raise ValueError("renewed calculation crosslink is invalid")
        if not mutate:
            return
        self._records[record.request_id] = replace(
            record, attempts=(*record.attempts[:-1], attempt)
        )

    def _apply_failed(self, raw: dict[str, object], *, mutate: bool) -> None:
        expected = {"kind", "version", "eventDigest", "requestId", "failure", "consultedAdmission"}
        if set(raw) != expected or not isinstance(raw.get("requestId"), str):
            raise ValueError("failed event shape is invalid")
        request_id = raw["requestId"]
        assert isinstance(request_id, str)
        failure = RelativeVolumeCalculationFailureV2.model_validate(raw["failure"])
        consulted_raw = raw["consultedAdmission"]
        consulted = AdmissionV2.model_validate(consulted_raw) if consulted_raw is not None else None
        if consulted is not None and (
            consulted.admission_digest is None
            or consulted.admission_digest != consulted.canonical_digest()
        ):
            raise ValueError("consulted admission is not sealed")
        record = self._records.get(request_id)
        if (
            record is None
            or record.status is not CalculationExecutionStatusV2.RUNNING
            or record.report is not None
            or record.failure is not None
            or record.active_attempt != failure.attempt
            or failure.failed_at < failure.attempt.issued_at
            or failure.failed_at > failure.attempt.lease_expires_at
            or not self._failure_is_sealed(failure)
            or not self._consulted_admission_matches(record, consulted)
        ):
            raise ValueError("failed calculation crosslink is invalid")
        if not mutate:
            return
        self._records[record.request_id] = replace(
            record,
            status=CalculationExecutionStatusV2.FAILED,
            failure=failure,
            consulted_admission=consulted,
        )

    @staticmethod
    def _public_record(record: CalculationExecutionRecordV2) -> CalculationExecutionRecordV2:
        return CalculationExecutionRecordV2(
            request_id=record.request_id,
            organization_id=record.organization_id,
            calculation_identity_digest=record.calculation_identity_digest,
            request_digest=record.request_digest,
            idempotency_digest=record.idempotency_digest,
            issued_at=record.issued_at,
            admission=record.admission.model_copy(deep=True),
            authorization=record.authorization.model_copy(deep=True),
            status=record.status,
            attempts=tuple(item.model_copy(deep=True) for item in record.attempts),
            report=record.report.model_copy(deep=True) if record.report is not None else None,
            failure=record.failure.model_copy(deep=True) if record.failure is not None else None,
            consulted_admission=(
                record.consulted_admission.model_copy(deep=True)
                if record.consulted_admission is not None
                else None
            ),
        )

    @staticmethod
    def _without_numeric_result(
        record: CalculationExecutionRecordV2,
    ) -> CalculationExecutionRecordV2:
        """Status projection is not a historical report read.

        A caller whose evidence needs reassessment may learn the durable job
        state, but cannot recover old numeric values through the nested record
        object.  Explicit principal-scoped history remains the auditable path.
        """
        return replace(record, report=None)


__all__ = [
    "CalculationCurrentDispositionV2",
    "CalculationCurrentViewV2",
    "CalculationExecutionRecordV2",
    "CalculationExecutionRecoveryError",
    "CalculationExecutionStatusV2",
    "ExternalRelativeVolumeCalculationStore",
]
