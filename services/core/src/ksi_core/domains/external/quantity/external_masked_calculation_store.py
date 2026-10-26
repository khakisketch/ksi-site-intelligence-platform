"""Additive Core ledger for masked (P2) execution: admission, lease, fenced report.

Owns one immutable journal for the V3 masked path only.  The frozen V2
calculation journal, V2 math, and V2 worker transport are untouched.  Source
truth is evidence only: admission binds the exact sealed source V2 identity
(plus mask/area/policy/runtime/envelope/activation/scope/egress) without
requiring a completed V2 numeric result.

Fence and publication rules:

- Authorization carries the signed activation digest; a missing activation
  fails closed with no default.
- Admission currentness (source/mask/area/policy/runtime) plus
  organization/site/area scope and AI-egress are checked before admission and
  again at every fenced transition (lease, renew, input, report, failure).
- The V3 numeric report carries no fence fields; this journal binds it to the
  exact live attempt by digest, identity, grid, and time window.
- Cancellation, deadline, retry caps, stale fences, and replay follow the V2
  discipline in a separate namespace: lease acquisitions never cross into V2,
  two-input V2 attempts are never accepted here, and the numeric output
  identity is V3 only.
- Publication state is out of scope: a publication failure never rewrites
  the numeric journal.  ``get_current`` exposes numeric output through a
  fresh admission witness; publication currency is decided elsewhere.

Parent integration: the store takes explicit evidence/currentness ports.
Tests use strict synthetic fakes (exact digest checks, never always-true).
The parent wires the real Core adapters (reconstruction/inspection/evidence
stores, WorkArea/policy/runtime registries, activation loader, scope/egress
evaluator, byte storage) and owns composition, routes, and activation files.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_mask_input import MaskObservedManifestV1
from ksi_event_contracts.external_masked_api import MaskedCalculationPendingItemV1
from ksi_event_contracts.external_masked_execution import (
    MaskedAdmissionDispositionV3,
    MaskedAdmissionV3,
    MaskedExecutionAttemptV3,
    MaskedExecutionAuthorizationV3,
    MaskedWorkerInputV3,
)
from ksi_event_contracts.external_masked_volume import MaskedCalculationIdentityV3
from ksi_event_contracts.external_masked_volume_result import (
    MaskedVolumeCalculationFailureV3,
    MaskedVolumeCalculationReportV3,
)

from ksi_core.foundation.api_base import iso_utc
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, principal_permissions

_VERSION = 1
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

# Bounded discovery budget: each pending poll examines at most ``limit``
# eligible-seeking candidates plus this small constant rejection allowance,
# then stops.  A rotating cursor (not pagination state) moves the scan start
# so a permanently stale head can never starve deeper eligible items.
_PENDING_SCAN_REJECTIONS = 25


def _digest(value: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _event_digest(raw: dict[str, object]) -> str:
    return _digest({key: value for key, value in raw.items() if key != "eventDigest"})


class MaskedCalculationRecoveryError(RuntimeError):
    """A masked-execution journal cannot be replayed safely."""


class MaskedExecutionStatusV3(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class MaskedCurrentDispositionV3(StrEnum):
    AVAILABLE = "AVAILABLE"
    REASSESSMENT_REQUIRED = "REASSESSMENT_REQUIRED"
    PENDING = "PENDING"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    EXECUTION_DEADLINE_EXPIRED = "EXECUTION_DEADLINE_EXPIRED"
    EXECUTION_RETRY_EXHAUSTED = "EXECUTION_RETRY_EXHAUSTED"


@dataclass(frozen=True, slots=True)
class MaskedAdmissionWitnessV3:
    """Fresh evidence bundle Core assembles before admission and at fenced completion."""

    admission: MaskedAdmissionV3
    source_identity: MaskedCalculationIdentityV3
    mask_manifest: MaskObservedManifestV1


class MaskedSourceEvidencePort(Protocol):
    """Resolves the exact sealed masked identity Core admitted (parent wires V2+mask sources)."""

    def fetch_masked_identity(
        self, *, masked_calculation_identity_digest: str
    ) -> MaskedCalculationIdentityV3 | None: ...


class MaskedManifestEvidencePort(Protocol):
    """Resolves the Core-sealed observed mask manifest for one mask child."""

    def fetch_manifest(
        self, *, organization_id: str, mask_child_id: str
    ) -> MaskObservedManifestV1 | None: ...


class MaskedAdmissionEvidencePort(Protocol):
    """Builds a fresh admission witness; returns None when any input is not current/admitted.

    A strict fake checks source/mask/area/policy/runtime digests, scope, and
    AI-egress exactly; an always-true callback is never acceptable.
    """

    def prepare_witness(
        self,
        *,
        masked_calculation_identity_digest: str,
        organization_id: str,
        now: datetime,
        expected_admission: MaskedAdmissionV3 | None = None,
    ) -> MaskedAdmissionWitnessV3 | None: ...

    def witness_is_current(
        self, *, witness: MaskedAdmissionWitnessV3, now: datetime
    ) -> MaskedAdmissionWitnessV3 | None: ...


@dataclass(frozen=True, slots=True)
class MaskedExecutionRecordV3:
    request_id: str
    organization_id: str
    masked_calculation_identity_digest: str
    request_digest: str
    idempotency_digest: str
    issued_at: datetime
    admission: MaskedAdmissionV3
    authorization: MaskedExecutionAuthorizationV3
    status: MaskedExecutionStatusV3
    attempts: tuple[MaskedExecutionAttemptV3, ...] = ()
    report: MaskedVolumeCalculationReportV3 | None = None
    failure: MaskedVolumeCalculationFailureV3 | None = None
    consulted_admission: MaskedAdmissionV3 | None = None

    @property
    def active_attempt(self) -> MaskedExecutionAttemptV3 | None:
        return self.attempts[-1] if self.attempts else None


@dataclass(frozen=True, slots=True)
class MaskedCurrentViewV3:
    disposition: MaskedCurrentDispositionV3
    record: MaskedExecutionRecordV3
    consulted_admission: MaskedAdmissionV3 | None
    report: MaskedVolumeCalculationReportV3 | None


class ExternalMaskedCalculationStore:
    """Issue and lease masked calculations only from a fresh V3 admission witness."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        evidence: MaskedAdmissionEvidencePort,
        resource_envelope: ResourceEnvelopeV1,
        designated_worker: Principal,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        if (
            resource_envelope.resource_envelope_digest is None
            or resource_envelope.resource_envelope_digest != resource_envelope.canonical_digest()
        ):
            raise ValueError("masked execution requires a sealed resource envelope")
        if (
            not isinstance(designated_worker, Principal)
            or designated_worker.kind is not PrincipalKind.ANALYSIS_WORKER
            or Permission.ANALYSIS_WORK not in principal_permissions(designated_worker)
            or not designated_worker.principal_id
            or not designated_worker.organization_id
        ):
            raise ValueError("masked execution requires the designated organization worker")
        self._journal = journal
        self._evidence = evidence
        self._envelope = resource_envelope.model_copy(deep=True)
        # The single configured execution worker.  Frozen identity: safe to
        # share.  Issue binds this id into every authorization; every fenced
        # worker call must bear it.  The human issuer is never substituted.
        self._designated_worker = designated_worker
        self._coordinator = coordinator or ExternalAuthorityCurrentnessCoordinator()
        self._lock = threading.RLock()
        self._records: dict[str, MaskedExecutionRecordV3] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._by_identity: dict[tuple[str, str], str] = {}
        self._identities: dict[tuple[str, str], MaskedCalculationIdentityV3] = {}
        self._lease_acquisitions: dict[str, set[str]] = {}
        # Pending discovery index: request ids with no terminal event yet, in
        # issue (journal) order.  Maintained by _apply (issue adds, terminal
        # pops); listing walks this index only, never replays the journal.
        self._pending: dict[str, None] = {}
        self._scan_cursor = 0
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException as exc:
            journal.close()
            if isinstance(exc, MaskedCalculationRecoveryError):
                raise
            raise MaskedCalculationRecoveryError(str(exc)) from exc

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    @property
    def designated_worker(self) -> Principal:
        """The configured designated execution worker (frozen identity)."""
        return self._designated_worker

    def issue(
        self,
        *,
        principal: Principal,
        request_id: str,
        masked_calculation_identity_digest: str,
        idempotency_key: str,
        now: datetime,
    ) -> MaskedExecutionRecordV3:
        self._require_site_write(principal)
        self._require_utc(now)
        self._require_digest(masked_calculation_identity_digest, "masked calculation identity")
        if not request_id.strip() or not idempotency_key.strip():
            raise ValueError("request and idempotency identifiers are required")
        bound = self._identities.get(
            (principal.organization_id, masked_calculation_identity_digest)
        )
        if bound is None:
            raise RuntimeError("masked calculation requires a Core-bound identity; bind first")
        witness = self._evidence.prepare_witness(
            masked_calculation_identity_digest=masked_calculation_identity_digest,
            organization_id=principal.organization_id,
            now=now,
        )
        request_digest = _digest(
            {
                "requestId": request_id,
                "maskedCalculationIdentityDigest": masked_calculation_identity_digest,
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
                return self._without_numeric(existing)
            existing_by_identity = self._by_identity.get(
                (principal.organization_id, masked_calculation_identity_digest)
            )
            if existing_by_identity is not None:
                self._require_record_scope(principal, self._records[existing_by_identity])
                return self._without_numeric(self._records[existing_by_identity])
        assessment = (
            self._evidence.witness_is_current(witness=witness, now=now) if witness else None
        )
        if assessment is None or not self._admission_can_execute(assessment.admission):
            raise RuntimeError("masked calculation requires a current admitted assessment")
        self._require_witness_scope(principal, assessment)
        admission_digest = assessment.admission.admission_digest
        envelope_digest = self._envelope.resource_envelope_digest
        assert admission_digest is not None and envelope_digest is not None
        activation_digest = assessment.admission.activation_digest
        if not activation_digest or _DIGEST_RE.fullmatch(activation_digest) is None:
            raise ValueError("masked issue requires a signed activation (no default)")
        masked_profile_digest = assessment.source_identity.profile.masked_profile_digest
        assert masked_profile_digest is not None
        authorization = MaskedExecutionAuthorizationV3(
            authorization_id="masked-calculation-authorization-" + request_id,
            organization_id=principal.organization_id,
            masked_calculation_identity_digest=masked_calculation_identity_digest,
            masked_profile_digest=masked_profile_digest,
            mask_binding_digest=assessment.source_identity.mask_binding_digest,
            source_calculation_identity_digest=(
                assessment.source_identity.source_calculation_identity_digest
            ),
            admission_digest=admission_digest,
            activation_digest=activation_digest,
            worker_principal_id=self._designated_worker.principal_id,
            resource_envelope=self._envelope,
            resource_envelope_digest=envelope_digest,
            authorized_at=now,
        ).sealed()
        raw = {
            "kind": "external-masked-calculation-issued.v3",
            "version": _VERSION,
            "organizationId": principal.organization_id,
            "requestId": request_id,
            "maskedCalculationIdentityDigest": masked_calculation_identity_digest,
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
                return self._without_numeric(existing)
            existing_by_identity = self._by_identity.get(
                (principal.organization_id, masked_calculation_identity_digest)
            )
            if existing_by_identity is not None:
                self._require_record_scope(principal, self._records[existing_by_identity])
                return self._without_numeric(self._records[existing_by_identity])
            assessment_now = (
                self._evidence.witness_is_current(witness=witness, now=now) if witness else None
            )
            if (
                assessment_now is None
                or assessment_now.admission != MaskedAdmissionV3.model_validate(raw["admission"])
            ):
                raise RuntimeError("masked assessment changed before issue")
            self._require_witness_scope(principal, assessment_now)
            queued = sum(
                1
                for candidate in self._records.values()
                if candidate.organization_id == principal.organization_id
                and candidate.status is MaskedExecutionStatusV3.QUEUED
            )
            if queued >= self._envelope.max_queue_depth:
                raise RuntimeError("masked calculation queue capacity is exhausted")
            self._append_locked(raw)
            return self._without_numeric(self._records[request_id])

    def bind_constructed_identity(
        self,
        *,
        principal: Principal,
        identity: MaskedCalculationIdentityV3,
        now: datetime,
    ) -> MaskedCalculationIdentityV3:
        """Durably bind a Core-constructed masked identity (no caller digest fetch).

        The caller (real evidence adapter or parent route) must have validated
        the identity against a current AP assessment and a current Core mask
        manifest; this method re-checks sealed shape plus organization/site/area
        consistency, then journals the binding idempotently by digest.
        """
        self._require_site_write(principal)
        self._require_utc(now)
        sealed = MaskedCalculationIdentityV3.model_validate(identity.model_dump(by_alias=True))
        if (
            sealed.masked_calculation_identity_digest is None
            or sealed.masked_calculation_identity_digest != sealed.canonical_digest()
        ):
            raise ValueError("masked identity must be sealed")
        source = sealed.source_calculation_identity
        if (
            source.calculation_identity_digest is None
            or source.calculation_identity_digest != source.canonical_digest()
            or sealed.source_calculation_identity_digest != source.calculation_identity_digest
        ):
            raise ValueError("masked source identity must be sealed")
        mask = sealed.mask_binding
        if (
            mask.mask_binding_digest is None
            or mask.mask_binding_digest != mask.canonical_digest()
            or sealed.mask_binding_digest != mask.mask_binding_digest
        ):
            raise ValueError("masked mask binding must be sealed")
        if (sealed.organization_id, sealed.site_id, sealed.work_area_id) != (
            source.organization_id,
            source.site_id,
            source.work_area_id,
        ) or (sealed.organization_id, sealed.site_id, sealed.work_area_id) != (
            mask.organization_id,
            mask.site_id,
            mask.work_area_id,
        ):
            raise ValueError("masked identity scope must match its source and mask")
        self._require_record_scope_for_identity(principal, sealed)
        key = (sealed.organization_id, sealed.masked_calculation_identity_digest)
        raw = {
            "kind": "external-masked-identity-bound.v3",
            "version": _VERSION,
            "organizationId": sealed.organization_id,
            "maskedCalculationIdentityDigest": sealed.masked_calculation_identity_digest,
            "boundAt": iso_utc(now),
            "identity": sealed.model_dump(by_alias=True, mode="json"),
        }
        with self._coordinator.mutation(), self._lock:
            existing = self._identities.get(key)
            if existing is not None:
                if existing != sealed:
                    raise ValueError("masked identity digest is bound to another identity")
                return existing.model_copy(deep=True)
            self._append_locked(raw)
            return self._identities[key].model_copy(deep=True)

    def get_bound_identity(
        self, masked_calculation_identity_digest: str, organization_id: str
    ) -> MaskedCalculationIdentityV3 | None:
        """Read a Core-bound masked identity; None when unknown or out of scope."""
        with self._lock:
            identity = self._identities.get((organization_id, masked_calculation_identity_digest))
            return None if identity is None else identity.model_copy(deep=True)

    def acquire_lease(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        worker_instance_id: str,
        lease_acquisition_id: str,
        now: datetime,
    ) -> MaskedExecutionAttemptV3 | None:
        self._require_designated_caller(worker_principal)
        self._require_utc(now)
        if not worker_instance_id.strip() or not lease_acquisition_id.strip():
            raise ValueError("worker and lease acquisition identifiers are required")
        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != worker_principal.organization_id:
                return None
            if record.status in {
                MaskedExecutionStatusV3.COMPLETED,
                MaskedExecutionStatusV3.FAILED,
                MaskedExecutionStatusV3.CANCELED,
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
        witness = self._evidence.prepare_witness(
            masked_calculation_identity_digest=record.masked_calculation_identity_digest,
            organization_id=record.organization_id,
            now=now,
            expected_admission=record.admission,
        )
        with self._coordinator.guarded_read(), self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != worker_principal.organization_id:
                return None
            assessment = (
                self._evidence.witness_is_current(witness=witness, now=now) if witness else None
            )
            if assessment is None or assessment.admission != record.admission:
                return None
            self._require_attempt_worker_binding(record, worker_principal)
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
                and candidate.status is MaskedExecutionStatusV3.RUNNING
                and candidate.active_attempt is not None
                and candidate.active_attempt.lease_expires_at > now
            )
            if running >= record.authorization.resource_envelope.max_tenant_concurrency:
                return None
            generation = len(record.attempts) + 1
            authorization_digest = record.authorization.execution_authorization_digest
            assert authorization_digest is not None
            attempt = MaskedExecutionAttemptV3(
                attempt_id=f"masked-calculation-attempt-{request_id}-{generation}",
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
                "kind": "external-masked-calculation-leased.v3",
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
        attempt: MaskedExecutionAttemptV3,
        now: datetime,
    ) -> MaskedExecutionAttemptV3 | None:
        self._require_designated_caller(worker_principal)
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
            masked_digest = record.masked_calculation_identity_digest
            organization_id = record.organization_id
            expected_admission = record.admission
        witness = self._evidence.prepare_witness(
            masked_calculation_identity_digest=masked_digest,
            organization_id=organization_id,
            now=now,
            expected_admission=expected_admission,
        )
        with self._coordinator.guarded_read(), self._lock:
            record = self._records.get(request_id)
            assessment = (
                self._evidence.witness_is_current(witness=witness, now=now) if witness else None
            )
            if (
                record is None
                or record.organization_id != worker_principal.organization_id
                or record.status is not MaskedExecutionStatusV3.RUNNING
                or record.active_attempt != attempt
                or attempt.lease_expires_at <= now
                or now >= self._deadline(record)
                or assessment is None
                or assessment.admission != record.admission
            ):
                return None
            self._require_attempt_worker_binding(record, worker_principal)
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
                "kind": "external-masked-calculation-renewed.v3",
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
        attempt: MaskedExecutionAttemptV3,
        now: datetime,
    ) -> MaskedWorkerInputV3 | None:
        self._require_designated_caller(worker_principal)
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
            masked_digest = record.masked_calculation_identity_digest
            organization_id = record.organization_id
            expected_admission = record.admission
        witness = self._evidence.prepare_witness(
            masked_calculation_identity_digest=masked_digest,
            organization_id=organization_id,
            now=now,
            expected_admission=expected_admission,
        )
        with self._coordinator.guarded_read(), self._lock:
            record = self._records.get(request_id)
            assessment = (
                self._evidence.witness_is_current(witness=witness, now=now) if witness else None
            )
            if (
                record is None
                or record.organization_id != worker_principal.organization_id
                or record.status is not MaskedExecutionStatusV3.RUNNING
                or record.active_attempt != attempt
                or attempt.lease_expires_at <= now
                or now >= self._deadline(record)
                or assessment is None
                or assessment.admission != record.admission
            ):
                return None
            self._require_attempt_worker_binding(record, worker_principal)
            identity = assessment.source_identity
            binding = identity.mask_binding
            source = identity.source_calculation_identity
            capability_expiry = min(attempt.lease_expires_at, now + timedelta(seconds=600))
            worker_input = MaskedWorkerInputV3(
                masked_request_id=request_id,
                attempt=attempt,
                masked_calculation_identity=identity,
                inputs=(
                    {
                        "role": "BASELINE_DSM",
                        "artifactId": source.baseline_dsm_artifact_id,
                        "observedSha256": source.baseline_dsm_observed_sha256,
                        "observedSizeBytes": source.baseline_dsm_observed_size_bytes,
                        "expiresAt": capability_expiry,
                    },
                    {
                        "role": "CURRENT_DSM",
                        "artifactId": source.current_dsm_artifact_id,
                        "observedSha256": source.current_dsm_observed_sha256,
                        "observedSizeBytes": source.current_dsm_observed_size_bytes,
                        "expiresAt": capability_expiry,
                    },
                    {
                        "role": "EXCLUSION_MASK",
                        "artifactId": binding.mask_artifact_id,
                        "observedSha256": binding.observed_sha256,
                        "observedSizeBytes": binding.observed_size_bytes,
                        "expiresAt": capability_expiry,
                    },
                ),  # type: ignore[arg-type]
            )
            return worker_input.model_copy(deep=True)

    def record_report(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        report: MaskedVolumeCalculationReportV3,
        attempt: MaskedExecutionAttemptV3,
        now: datetime,
    ) -> MaskedExecutionRecordV3 | None:
        """Persist a fenced V3 report; a later publication failure never rewrites it."""
        self._require_designated_caller(worker_principal)
        self._require_utc(now)
        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != worker_principal.organization_id:
                return None
            if record.report is not None:
                return self._public_record(record) if record.report == report else None
            if not self._report_matches_active(record, report, attempt, now):
                return None
            self._require_attempt_worker_binding(record, worker_principal, attempt)
            if worker_principal.organization_id != record.organization_id:
                return None
            masked_digest = record.masked_calculation_identity_digest
            organization_id = record.organization_id
            expected_admission = record.admission
        witness = self._evidence.prepare_witness(
            masked_calculation_identity_digest=masked_digest,
            organization_id=organization_id,
            now=now,
            expected_admission=expected_admission,
        )
        with self._coordinator.guarded_read(), self._lock:
            record = self._records.get(request_id)
            if (
                record is None
                or record.organization_id != worker_principal.organization_id
                or not self._report_matches_active(record, report, attempt, now)
            ):
                return None
            self._require_attempt_worker_binding(record, worker_principal, attempt)
            consulted = (
                self._evidence.witness_is_current(witness=witness, now=now) if witness else None
            )
            if consulted is None:
                return None
            if not self._witness_still_binds_record(record, consulted):
                return None
            raw = {
                "kind": "external-masked-calculation-reported.v3",
                "version": _VERSION,
                "requestId": request_id,
                "report": report.model_dump(by_alias=True, mode="json"),
                "attempt": attempt.model_dump(by_alias=True, mode="json"),
                "consultedAdmission": consulted.admission.model_dump(by_alias=True, mode="json"),
            }
            self._append_locked(raw)
            return self._public_record(self._records[request_id])

    def record_failure(
        self,
        *,
        request_id: str,
        worker_principal: Principal,
        failure: MaskedVolumeCalculationFailureV3,
        attempt: MaskedExecutionAttemptV3,
        now: datetime,
    ) -> MaskedExecutionRecordV3 | None:
        self._require_designated_caller(worker_principal)
        self._require_utc(now)
        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != worker_principal.organization_id:
                return None
            if record.failure is not None:
                return self._public_record(record) if record.failure == failure else None
            if not self._failure_matches_active(record, failure, attempt, now):
                return None
            masked_digest = record.masked_calculation_identity_digest
            organization_id = record.organization_id
            expected_admission = record.admission
        witness = self._evidence.prepare_witness(
            masked_calculation_identity_digest=masked_digest,
            organization_id=organization_id,
            now=now,
            expected_admission=expected_admission,
        )
        with self._coordinator.guarded_read(), self._lock:
            record = self._records.get(request_id)
            if (
                record is None
                or record.organization_id != worker_principal.organization_id
                or not self._failure_matches_active(record, failure, attempt, now)
            ):
                return None
            self._require_attempt_worker_binding(record, worker_principal, attempt)
            consulted = (
                self._evidence.witness_is_current(witness=witness, now=now) if witness else None
            )
            if consulted is None:
                return None
            if not self._witness_still_binds_record(record, consulted):
                return None
            raw = {
                "kind": "external-masked-calculation-failed.v3",
                "version": _VERSION,
                "requestId": request_id,
                "failure": failure.model_dump(by_alias=True, mode="json"),
                "attempt": attempt.model_dump(by_alias=True, mode="json"),
                "consultedAdmission": consulted.admission.model_dump(by_alias=True, mode="json"),
            }
            self._append_locked(raw)
            return self._public_record(self._records[request_id])

    def cancel(
        self,
        *,
        request_id: str,
        principal: Principal,
        now: datetime,
    ) -> MaskedExecutionRecordV3 | None:
        """Operator cancellation: terminal, explicit, replayed. No numeric result."""
        self._require_site_write(principal)
        self._require_utc(now)
        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != principal.organization_id:
                return None
            self._require_record_scope(principal, record)
            if record.status in {
                MaskedExecutionStatusV3.COMPLETED,
                MaskedExecutionStatusV3.FAILED,
                MaskedExecutionStatusV3.CANCELED,
            }:
                return self._public_record(record)
        witness = self._evidence.prepare_witness(
            masked_calculation_identity_digest=record.masked_calculation_identity_digest,
            organization_id=record.organization_id,
            now=now,
        )
        with self._coordinator.guarded_read(), self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != principal.organization_id:
                return None
            self._require_record_scope(principal, record)
            if record.status in {
                MaskedExecutionStatusV3.COMPLETED,
                MaskedExecutionStatusV3.FAILED,
                MaskedExecutionStatusV3.CANCELED,
            }:
                return self._public_record(record)
            assessment = (
                self._evidence.witness_is_current(witness=witness, now=now) if witness else None
            )
            raw = {
                "kind": "external-masked-calculation-canceled.v3",
                "version": _VERSION,
                "requestId": request_id,
                "canceledAt": iso_utc(now),
                "consultedAdmission": (
                    assessment.admission.model_dump(by_alias=True, mode="json")
                    if assessment is not None
                    else None
                ),
            }
            self._append_locked(raw)
            return self._public_record(self._records[request_id])

    def get_history(
        self, request_id: str, *, organization_id: str
    ) -> MaskedExecutionRecordV3 | None:
        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != organization_id:
                return None
            return self._public_record(record)

    def get_history_for_principal(
        self, request_id: str, *, principal: Principal
    ) -> MaskedExecutionRecordV3 | None:
        if not self._has_site_read(principal):
            raise PermissionError("masked calculation history requires SITES_READ")
        record = self.get_history(request_id, organization_id=principal.organization_id)
        if record is not None:
            self._require_record_scope(principal, record)
        return record

    def get_current(
        self, *, request_id: str, principal: Principal, now: datetime
    ) -> MaskedCurrentViewV3 | None:
        if not self._has_site_read(principal):
            raise PermissionError("masked calculation result requires SITES_READ")
        self._require_utc(now)
        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != principal.organization_id:
                return None
            self._require_record_scope(principal, record)
            masked_digest = record.masked_calculation_identity_digest
            organization_id = record.organization_id
            expected_admission = (
                record.admission
                if record.status
                in {
                    MaskedExecutionStatusV3.QUEUED,
                    MaskedExecutionStatusV3.RUNNING,
                }
                else None
            )
        witness = self._evidence.prepare_witness(
            masked_calculation_identity_digest=masked_digest,
            organization_id=organization_id,
            now=now,
            expected_admission=expected_admission,
        )
        with self._coordinator.guarded_read(), self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != principal.organization_id:
                return None
            consulted = (
                self._evidence.witness_is_current(witness=witness, now=now) if witness else None
            )
            public = self._public_record(record)
            if consulted is None or not self._admission_can_execute(consulted.admission):
                return MaskedCurrentViewV3(
                    MaskedCurrentDispositionV3.REASSESSMENT_REQUIRED,
                    self._without_numeric(public),
                    None,
                    None,
                )
            admission = consulted.admission.model_copy(deep=True)
            if record.status is MaskedExecutionStatusV3.COMPLETED:
                return MaskedCurrentViewV3(
                    MaskedCurrentDispositionV3.AVAILABLE,
                    public,
                    admission,
                    record.report.model_copy(deep=True) if record.report is not None else None,
                )
            if record.status is MaskedExecutionStatusV3.FAILED:
                return MaskedCurrentViewV3(
                    MaskedCurrentDispositionV3.FAILED, public, admission, None
                )
            if record.status is MaskedExecutionStatusV3.CANCELED:
                return MaskedCurrentViewV3(
                    MaskedCurrentDispositionV3.CANCELED, public, admission, None
                )
            if now >= self._deadline(record):
                return MaskedCurrentViewV3(
                    MaskedCurrentDispositionV3.EXECUTION_DEADLINE_EXPIRED,
                    self._without_numeric(public),
                    admission,
                    None,
                )
            active = record.active_attempt
            fence_live = (
                record.status is MaskedExecutionStatusV3.RUNNING
                and active is not None
                and active.lease_expires_at > now
            )
            if (
                len(record.attempts) >= record.authorization.resource_envelope.max_retry_attempts
                and not fence_live
            ):
                return MaskedCurrentViewV3(
                    MaskedCurrentDispositionV3.EXECUTION_RETRY_EXHAUSTED,
                    self._without_numeric(public),
                    admission,
                    None,
                )
            return MaskedCurrentViewV3(MaskedCurrentDispositionV3.PENDING, public, admission, None)

    def list_queued_calculations(
        self, *, organization_id: str, limit: int, now: datetime
    ) -> tuple[MaskedCalculationPendingItemV1, ...]:
        """Bounded worker discovery over the maintained pending index.

        Lists up to ``limit`` calculations the caller org owns that a worker
        may take: ``QUEUED``, plus ``RUNNING`` only with an expired lease and
        attempts left under the sealed envelope's retry cap.  Live-leased,
        terminal, and deadline-past records are never listed.  Every item is
        backed by a fresh masked witness at ``now`` (admission, identity, and
        mask binding must still match the record exactly); stale or foreign
        records are omitted, never listed.

        Walks the in-memory pending index only (no journal replay, no journal
        append); examinations stop after the first ``limit`` eligible items
        plus a small constant rejection budget, starting from a rotating cursor
        so stale heads cannot starve deeper eligible items.
        """
        if (
            not isinstance(organization_id, str)
            or not organization_id.strip()
            or len(organization_id) > 128
        ):
            raise ValueError("masked queued listing requires an organization")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("masked queued listing limit must be an integer 1..50")
        self._require_utc(now)
        with self._lock:
            prune: list[str] = []
            ordered: list[tuple[str, MaskedExecutionRecordV3]] = []
            for request_id in self._pending:
                record = self._records.get(request_id)
                if record is None:
                    prune.append(request_id)
                    continue
                if record.organization_id != organization_id:
                    continue
                if record.status in {
                    MaskedExecutionStatusV3.COMPLETED,
                    MaskedExecutionStatusV3.FAILED,
                    MaskedExecutionStatusV3.CANCELED,
                } or now >= self._deadline(record):
                    # Terminal or permanently deadline-past: drop from the
                    # index (records stay readable via get_history).
                    prune.append(request_id)
                    continue
                ordered.append((request_id, record))
            for request_id in prune:
                self._pending.pop(request_id, None)
            if not ordered:
                return ()
            start = self._scan_cursor % len(ordered)
            rotated = ordered[start:] + ordered[:start]
        collected: list[tuple[str, MaskedExecutionRecordV3]] = []
        examined = 0
        allowance = limit + _PENDING_SCAN_REJECTIONS
        for request_id, snapshot in rotated:
            if len(collected) >= limit or examined >= allowance:
                break
            examined += 1
            if not self._pending_eligible(snapshot, now):
                continue
            try:
                witness = self._evidence.prepare_witness(
                    masked_calculation_identity_digest=(
                        snapshot.masked_calculation_identity_digest
                    ),
                    organization_id=snapshot.organization_id,
                    now=now,
                    expected_admission=snapshot.admission,
                )
                assessment = (
                    self._evidence.witness_is_current(witness=witness, now=now)
                    if witness is not None
                    else None
                )
            except Exception:
                # One unreadable candidate must not fail the whole poll;
                # omit it exactly like a stale witness.
                continue
            if (
                assessment is None
                or assessment.admission != snapshot.admission
                or not self._admission_can_execute(assessment.admission)
                or not self._witness_still_binds_record(snapshot, assessment)
            ):
                continue
            with self._lock:
                current = self._records.get(request_id)
                if (
                    current is None
                    or current.admission != snapshot.admission
                    or not self._pending_eligible(current, now)
                ):
                    continue
                collected.append((request_id, current))
        with self._lock:
            self._scan_cursor += examined
        collected.sort(key=lambda item: (item[1].issued_at, item[0]))
        return tuple(
            MaskedCalculationPendingItemV1(
                request_id=request_id,
                masked_calculation_identity_digest=record.masked_calculation_identity_digest,
                execution_state=record.status.value,  # type: ignore[arg-type]
                issued_at=record.issued_at,
            )
            for request_id, record in collected[:limit]
        )

    @staticmethod
    def _pending_eligible(record: MaskedExecutionRecordV3, now: datetime) -> bool:
        """Local takeability gate: status, live fence, retry cap, deadline."""
        if record.status is MaskedExecutionStatusV3.QUEUED:
            pass
        elif record.status is MaskedExecutionStatusV3.RUNNING:
            active = record.active_attempt
            if active is None or active.lease_expires_at > now:
                return False
            if len(record.attempts) >= record.authorization.resource_envelope.max_retry_attempts:
                return False
        else:
            return False
        return now < ExternalMaskedCalculationStore._deadline(record)

    def resolve_completed_source(
        self,
        *,
        organization_id: str,
        masked_calculation_identity_digest: str,
        numeric_result_identity_digest: str,
        coverage_witness_digest: str,
        now: datetime,
    ) -> tuple[MaskedExecutionRecordV3, MaskedAdmissionWitnessV3] | None:
        """Read-only V3 publication source: exact completed report + fresh witness.

        Resolves the durable completed record for one masked identity and
        re-resolves fresh current evidence under the common coordinator.  The
        completed report must match the requested numeric/coverage identities
        exactly, and the fresh witness must still bind the same masked
        identity with executable disposition plus current
        mask-manifest/source/grid scope.  No journal mutation occurs here;
        publication currency/revocation/scope/egress remain the publication
        store's separate checks, and no completed V2 numeric result is
        required (source evidence only).
        """
        self._require_utc(now)
        self._require_digest(masked_calculation_identity_digest, "masked calculation identity")
        self._require_digest(numeric_result_identity_digest, "numeric result identity")
        self._require_digest(coverage_witness_digest, "coverage witness")
        if not organization_id.strip():
            return None
        with self._lock:
            request_id = self._by_identity.get(
                (organization_id, masked_calculation_identity_digest)
            )
            if request_id is None:
                return None
            record = self._records.get(request_id)
            if record is None or record.organization_id != organization_id:
                return None
            if record.status is not MaskedExecutionStatusV3.COMPLETED:
                return None
            report = record.report
            if report is None:
                return None
            numeric = report.numeric_result
            if (
                report.masked_calculation_identity_digest != masked_calculation_identity_digest
                or numeric.masked_calculation_identity_digest != masked_calculation_identity_digest
                or numeric.numeric_result_identity_digest != numeric_result_identity_digest
                or numeric.coverage.coverage_witness_digest != coverage_witness_digest
            ):
                return None
            masked_digest = record.masked_calculation_identity_digest
        witness = self._evidence.prepare_witness(
            masked_calculation_identity_digest=masked_digest,
            organization_id=organization_id,
            now=now,
        )
        with self._coordinator.guarded_read(), self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != organization_id:
                return None
            if record.status is not MaskedExecutionStatusV3.COMPLETED or record.report is None:
                return None
            report = record.report
            numeric = report.numeric_result
            if (
                report.masked_calculation_identity_digest != masked_calculation_identity_digest
                or numeric.masked_calculation_identity_digest != masked_calculation_identity_digest
                or numeric.numeric_result_identity_digest != numeric_result_identity_digest
                or numeric.coverage.coverage_witness_digest != coverage_witness_digest
            ):
                return None
            fresh = self._evidence.witness_is_current(witness=witness, now=now) if witness else None
            if fresh is None or not self._admission_can_execute(fresh.admission):
                return None
            admission = fresh.admission
            identity = fresh.source_identity
            manifest = fresh.mask_manifest
            if (
                admission.masked_calculation_identity_digest != masked_calculation_identity_digest
                or identity.masked_calculation_identity_digest != masked_calculation_identity_digest
                or admission.organization_id != organization_id
                or identity.organization_id != organization_id
                or manifest.organization_id != organization_id
                or (identity.organization_id, identity.site_id, identity.work_area_id)
                != (admission.organization_id, admission.site_id, admission.work_area_id)
                or (manifest.organization_id, manifest.site_id, manifest.work_area_id)
                != (admission.organization_id, admission.site_id, admission.work_area_id)
                or numeric.masked_profile_digest != admission.masked_profile_digest
                or numeric.mask_binding_digest != admission.mask_binding_digest
                or numeric.mask_binding_digest != identity.mask_binding_digest
            ):
                return None
            return self._public_record(record), MaskedAdmissionWitnessV3(
                admission=admission.model_copy(deep=True),
                source_identity=identity.model_copy(deep=True),
                mask_manifest=manifest.model_copy(deep=True),
            )

    @staticmethod
    def _report_matches_active(
        record: MaskedExecutionRecordV3,
        report: MaskedVolumeCalculationReportV3,
        attempt: MaskedExecutionAttemptV3,
        now: datetime,
    ) -> bool:
        active = record.active_attempt
        if (
            record.status is not MaskedExecutionStatusV3.RUNNING
            or active is None
            or active != attempt
            or attempt.lease_expires_at <= now
            or now >= ExternalMaskedCalculationStore._deadline(record)
        ):
            return False
        if active.worker_instance_id != attempt.worker_instance_id:
            return False
        if (
            active.lease_acquisition_id != attempt.lease_acquisition_id
            or active.lease_generation != attempt.lease_generation
            or active.attempt_id != attempt.attempt_id
            or active.authorization_digest != attempt.authorization_digest
        ):
            return False
        if not ExternalMaskedCalculationStore._report_is_sealed(report):
            return False
        if report.masked_calculation_identity_digest != record.masked_calculation_identity_digest:
            return False
        if (
            report.numeric_result.masked_calculation_identity_digest
            != record.masked_calculation_identity_digest
        ):
            return False
        if report.numeric_result_identity_digest != report.numeric_result.canonical_digest():
            return False
        if not (active.issued_at <= report.computed_at <= report.reported_at <= now):
            return False
        if report.reported_at > active.lease_expires_at:
            return False
        return ExternalMaskedCalculationStore._report_binds_immutable_identity(record, report)

    @staticmethod
    def _failure_matches_active(
        record: MaskedExecutionRecordV3,
        failure: MaskedVolumeCalculationFailureV3,
        attempt: MaskedExecutionAttemptV3,
        now: datetime,
    ) -> bool:
        active = record.active_attempt
        if (
            record.status is not MaskedExecutionStatusV3.RUNNING
            or active is None
            or active != attempt
            or attempt.lease_expires_at <= now
            or now >= ExternalMaskedCalculationStore._deadline(record)
        ):
            return False
        if not ExternalMaskedCalculationStore._failure_is_sealed(failure):
            return False
        if failure.masked_calculation_identity_digest != record.masked_calculation_identity_digest:
            return False
        return attempt.issued_at <= failure.failed_at <= now

    @staticmethod
    def _report_is_sealed(report: MaskedVolumeCalculationReportV3) -> bool:
        return (
            report.report_digest is not None and report.report_digest == report.canonical_digest()
        ) and (
            report.numeric_result.numeric_result_identity_digest is not None
            and report.numeric_result.numeric_result_identity_digest
            == report.numeric_result.canonical_digest()
        )

    @staticmethod
    def _failure_is_sealed(failure: MaskedVolumeCalculationFailureV3) -> bool:
        return (
            failure.failure_digest is not None
            and failure.failure_digest == failure.canonical_digest()
        )

    @staticmethod
    def _report_binds_immutable_identity(
        record: MaskedExecutionRecordV3,
        report: MaskedVolumeCalculationReportV3,
    ) -> bool:
        identity = record.admission
        numeric = report.numeric_result
        if numeric.masked_calculation_identity_digest != record.masked_calculation_identity_digest:
            return False
        if (
            numeric.masked_profile_digest != identity.masked_profile_digest
            or numeric.mask_binding_digest != identity.mask_binding_digest
            or numeric.mask_binding_digest != record.authorization.mask_binding_digest
            or numeric.masked_profile_digest != record.authorization.masked_profile_digest
        ):
            return False
        if numeric.contract_version != "external-masked-volume-numeric-result.v3":
            return False
        coverage = numeric.coverage
        if (
            coverage.effective_selected_cell_count <= 0
            or coverage.common_valid_cell_count != coverage.effective_selected_cell_count
            or coverage.unavailable_cell_count != 0
            or coverage.mask_excluded_cell_count != numeric.impact.excluded_cell_count
        ):
            return False
        envelope = record.authorization.resource_envelope
        if coverage.rows * coverage.columns > envelope.max_pixels:
            return False
        size = len(report.model_dump_json(by_alias=True).encode("utf-8"))
        return size <= envelope.max_output_bytes

    @staticmethod
    def _witness_still_binds_record(
        record: MaskedExecutionRecordV3, witness: MaskedAdmissionWitnessV3
    ) -> bool:
        if witness.admission != record.admission:
            return False
        identity = witness.source_identity
        manifest = witness.mask_manifest
        if identity.masked_calculation_identity_digest != record.masked_calculation_identity_digest:
            return False
        if (identity.organization_id, identity.site_id, identity.work_area_id) != (
            record.admission.organization_id,
            record.admission.site_id,
            record.admission.work_area_id,
        ):
            return False
        if (manifest.organization_id, manifest.site_id, manifest.work_area_id) != (
            record.admission.organization_id,
            record.admission.site_id,
            record.admission.work_area_id,
        ):
            return False
        binding_digest = identity.mask_binding_digest
        return (
            manifest.observed_sha256 == identity.mask_binding.observed_sha256
            and manifest.observed_size_bytes == identity.mask_binding.observed_size_bytes
            and witness.admission.mask_binding_digest == binding_digest
        )

    @staticmethod
    def _deadline(record: MaskedExecutionRecordV3) -> datetime:
        return record.authorization.authorized_at + timedelta(
            seconds=record.authorization.resource_envelope.max_deadline_seconds
        )

    @staticmethod
    def _admission_can_execute(admission: MaskedAdmissionV3) -> bool:
        return admission.disposition in {
            MaskedAdmissionDispositionV3.ADMIT_PROVISIONAL,
            MaskedAdmissionDispositionV3.ADMIT_EVALUATED,
        }

    def _append_locked(self, raw: dict[str, object]) -> None:
        record = dict(raw)
        record["eventDigest"] = _event_digest(record)
        try:
            self._journal.append(record)
        except JournalSealedError:
            raise
        except BaseException as exc:
            raise MaskedCalculationRecoveryError(str(exc)) from exc
        self._apply(record)

    def _apply(self, raw: Mapping[str, object]) -> None:
        kind = raw.get("kind")
        if raw.get("version") != _VERSION:
            raise MaskedCalculationRecoveryError("masked journal version is unsupported")
        record: MaskedExecutionRecordV3 | None = None
        if kind == "external-masked-identity-bound.v3":
            identity = MaskedCalculationIdentityV3.model_validate(raw["identity"])
            if (
                identity.masked_calculation_identity_digest is None
                or identity.masked_calculation_identity_digest != identity.canonical_digest()
                or identity.masked_calculation_identity_digest
                != str(raw["maskedCalculationIdentityDigest"])
            ):
                raise MaskedCalculationRecoveryError("masked identity journal is tampered")
            key = (identity.organization_id, identity.masked_calculation_identity_digest)
            bound = self._identities.get(key)
            if bound is not None:
                if bound != identity:
                    raise MaskedCalculationRecoveryError("masked identity journal conflicts")
                return
            self._identities[key] = identity
            return
        if kind == "external-masked-calculation-issued.v3":
            admission = MaskedAdmissionV3.model_validate(raw["admission"])
            authorization = MaskedExecutionAuthorizationV3.model_validate(raw["authorization"])
            self._require_sealed_admission(admission)
            self._require_sealed_authorization(authorization)
            request_id = str(raw["requestId"])
            if request_id in self._records:
                existing = self._records[request_id]
                if (
                    existing.admission != admission
                    or existing.authorization != authorization
                    or existing.request_digest != str(raw["requestDigest"])
                ):
                    raise MaskedCalculationRecoveryError("masked issue journal conflicts")
                return
            record = MaskedExecutionRecordV3(
                request_id=request_id,
                organization_id=str(raw["organizationId"]),
                masked_calculation_identity_digest=str(raw["maskedCalculationIdentityDigest"]),
                request_digest=str(raw["requestDigest"]),
                idempotency_digest=str(raw["idempotencyDigest"]),
                issued_at=datetime.fromisoformat(str(raw["issuedAt"]).replace("Z", "+00:00")),
                admission=admission,
                authorization=authorization,
                status=MaskedExecutionStatusV3.QUEUED,
            )
            self._records[request_id] = record
            self._idempotency[(record.organization_id, record.idempotency_digest)] = request_id
            self._by_identity[
                (record.organization_id, record.masked_calculation_identity_digest)
            ] = request_id
            self._pending[request_id] = None
        elif kind == "external-masked-calculation-leased.v3":
            attempt = MaskedExecutionAttemptV3.model_validate(raw["attempt"])
            self._require_sealed_attempt(attempt)
            request_id = str(raw["requestId"])
            record = self._records.get(request_id)
            if record is None:
                raise MaskedCalculationRecoveryError("masked lease precedes its issue")
            if record.status in {
                MaskedExecutionStatusV3.COMPLETED,
                MaskedExecutionStatusV3.FAILED,
                MaskedExecutionStatusV3.CANCELED,
            }:
                raise MaskedCalculationRecoveryError("masked lease follows a terminal record")
            if record.active_attempt is not None and record.active_attempt == attempt:
                return
            if attempt.lease_generation != len(record.attempts) + 1:
                raise MaskedCalculationRecoveryError("masked lease generation is out of order")
            if attempt.attempt_id != (
                f"masked-calculation-attempt-{request_id}-{attempt.lease_generation}"
            ):
                raise MaskedCalculationRecoveryError("masked lease attempt id breaks the counter")
            authorization_digest = record.authorization.execution_authorization_digest
            if (
                authorization_digest is None
                or attempt.authorization_digest != authorization_digest
                or attempt.authorization != record.authorization
            ):
                raise MaskedCalculationRecoveryError("masked lease binds another authorization")
            if (
                record.active_attempt is not None
                and record.active_attempt.lease_expires_at > attempt.issued_at
            ):
                raise MaskedCalculationRecoveryError("masked lease overlaps a live fence")
            self._records[request_id] = MaskedExecutionRecordV3(
                request_id=record.request_id,
                organization_id=record.organization_id,
                masked_calculation_identity_digest=record.masked_calculation_identity_digest,
                request_digest=record.request_digest,
                idempotency_digest=record.idempotency_digest,
                issued_at=record.issued_at,
                admission=record.admission,
                authorization=record.authorization,
                status=MaskedExecutionStatusV3.RUNNING,
                attempts=(*record.attempts, attempt),
                report=record.report,
                failure=record.failure,
                consulted_admission=record.consulted_admission,
            )
            acquisitions = self._lease_acquisitions.setdefault(request_id, set())
            acquisitions.add(attempt.lease_acquisition_id)
            self._pending.setdefault(request_id, None)
        elif kind == "external-masked-calculation-renewed.v3":
            attempt = MaskedExecutionAttemptV3.model_validate(raw["attempt"])
            self._require_sealed_attempt(attempt)
            request_id = str(raw["requestId"])
            record = self._records.get(request_id)
            if record is None or not record.attempts:
                raise MaskedCalculationRecoveryError("masked renew precedes its lease")
            if record.status != MaskedExecutionStatusV3.RUNNING:
                raise MaskedCalculationRecoveryError("masked renew follows a terminal record")
            if record.active_attempt == attempt:
                return
            previous = record.attempts[-1]
            if (
                attempt.attempt_id != previous.attempt_id
                or attempt.authorization_digest != previous.authorization_digest
                or attempt.worker_instance_id != previous.worker_instance_id
                or attempt.lease_acquisition_id != previous.lease_acquisition_id
            ):
                raise MaskedCalculationRecoveryError("masked renew binds another fence")
            self._records[request_id] = MaskedExecutionRecordV3(
                request_id=record.request_id,
                organization_id=record.organization_id,
                masked_calculation_identity_digest=record.masked_calculation_identity_digest,
                request_digest=record.request_digest,
                idempotency_digest=record.idempotency_digest,
                issued_at=record.issued_at,
                admission=record.admission,
                authorization=record.authorization,
                status=MaskedExecutionStatusV3.RUNNING,
                attempts=(*record.attempts[:-1], attempt),
                report=record.report,
                failure=record.failure,
                consulted_admission=record.consulted_admission,
            )
            self._pending.setdefault(request_id, None)
        elif kind == "external-masked-calculation-reported.v3":
            report = MaskedVolumeCalculationReportV3.model_validate(raw["report"])
            if not self._report_is_sealed(report):
                raise MaskedCalculationRecoveryError("masked report journal is tampered")
            attempt_raw = raw.get("attempt")
            if attempt_raw is None:
                raise MaskedCalculationRecoveryError("masked report journal misses its fence")
            attempt = MaskedExecutionAttemptV3.model_validate(attempt_raw)
            self._require_sealed_attempt(attempt)
            request_id = str(raw["requestId"])
            record = self._records.get(request_id)
            if record is None:
                raise MaskedCalculationRecoveryError("masked report precedes its issue")
            if record.status in {
                MaskedExecutionStatusV3.COMPLETED,
                MaskedExecutionStatusV3.FAILED,
                MaskedExecutionStatusV3.CANCELED,
            }:
                if record.report is not None and record.report == report:
                    return
                raise MaskedCalculationRecoveryError("masked report follows a terminal record")
            if record.report is not None:
                if record.report != report:
                    raise MaskedCalculationRecoveryError("masked report journal conflicts")
                return
            if record.active_attempt != attempt:
                raise MaskedCalculationRecoveryError("masked report binds another fence")
            if not self._report_binds_immutable_identity(record, report):
                raise MaskedCalculationRecoveryError("masked report breaks numeric identity")
            consulted_raw = raw.get("consultedAdmission")
            consulted = (
                MaskedAdmissionV3.model_validate(consulted_raw)
                if consulted_raw is not None
                else None
            )
            self._records[request_id] = MaskedExecutionRecordV3(
                request_id=record.request_id,
                organization_id=record.organization_id,
                masked_calculation_identity_digest=record.masked_calculation_identity_digest,
                request_digest=record.request_digest,
                idempotency_digest=record.idempotency_digest,
                issued_at=record.issued_at,
                admission=record.admission,
                authorization=record.authorization,
                status=MaskedExecutionStatusV3.COMPLETED,
                attempts=record.attempts,
                report=report,
                failure=None,
                consulted_admission=consulted,
            )
            self._pending.pop(request_id, None)
        elif kind == "external-masked-calculation-failed.v3":
            failure = MaskedVolumeCalculationFailureV3.model_validate(raw["failure"])
            attempt = MaskedExecutionAttemptV3.model_validate(raw["attempt"])
            if not self._failure_is_sealed(failure):
                raise MaskedCalculationRecoveryError("masked failure journal is tampered")
            self._require_sealed_attempt(attempt)
            request_id = str(raw["requestId"])
            record = self._records.get(request_id)
            if record is None:
                raise MaskedCalculationRecoveryError("masked failure precedes its issue")
            if record.status in {
                MaskedExecutionStatusV3.COMPLETED,
                MaskedExecutionStatusV3.FAILED,
                MaskedExecutionStatusV3.CANCELED,
            }:
                if record.failure is not None and record.failure == failure:
                    return
                raise MaskedCalculationRecoveryError("masked failure follows a terminal record")
            if record.failure is not None:
                if record.failure != failure:
                    raise MaskedCalculationRecoveryError("masked failure journal conflicts")
                return
            if record.active_attempt != attempt:
                raise MaskedCalculationRecoveryError("masked failure binds another fence")
            consulted_raw = raw.get("consultedAdmission")
            consulted = (
                MaskedAdmissionV3.model_validate(consulted_raw)
                if consulted_raw is not None
                else None
            )
            self._records[request_id] = MaskedExecutionRecordV3(
                request_id=record.request_id,
                organization_id=record.organization_id,
                masked_calculation_identity_digest=(record.masked_calculation_identity_digest),
                request_digest=record.request_digest,
                idempotency_digest=record.idempotency_digest,
                issued_at=record.issued_at,
                admission=record.admission,
                authorization=record.authorization,
                status=MaskedExecutionStatusV3.FAILED,
                attempts=record.attempts,
                report=None,
                failure=failure,
                consulted_admission=consulted,
            )
            self._pending.pop(request_id, None)
        elif kind == "external-masked-calculation-canceled.v3":
            request_id = str(raw["requestId"])
            record = self._records.get(request_id)
            if record is None:
                raise MaskedCalculationRecoveryError("masked cancel precedes its issue")
            if record.status in {
                MaskedExecutionStatusV3.COMPLETED,
                MaskedExecutionStatusV3.FAILED,
                MaskedExecutionStatusV3.CANCELED,
            }:
                if record.status is MaskedExecutionStatusV3.CANCELED:
                    return
                raise MaskedCalculationRecoveryError("masked cancel follows a terminal record")
            consulted_raw = raw.get("consultedAdmission")
            consulted = (
                MaskedAdmissionV3.model_validate(consulted_raw)
                if consulted_raw is not None
                else None
            )
            self._records[request_id] = MaskedExecutionRecordV3(
                request_id=record.request_id,
                organization_id=record.organization_id,
                masked_calculation_identity_digest=record.masked_calculation_identity_digest,
                request_digest=record.request_digest,
                idempotency_digest=record.idempotency_digest,
                issued_at=record.issued_at,
                admission=record.admission,
                authorization=record.authorization,
                status=MaskedExecutionStatusV3.CANCELED,
                attempts=record.attempts,
                report=None,
                failure=None,
                consulted_admission=consulted,
            )
            self._pending.pop(request_id, None)
        else:
            raise MaskedCalculationRecoveryError(f"unknown masked journal kind: {kind!r}")

    @staticmethod
    def _require_sealed_admission(admission: MaskedAdmissionV3) -> None:
        if (
            admission.admission_digest is None
            or admission.admission_digest != admission.canonical_digest()
        ):
            raise MaskedCalculationRecoveryError("masked admission journal is tampered")

    @staticmethod
    def _require_sealed_authorization(authorization: MaskedExecutionAuthorizationV3) -> None:
        if (
            authorization.execution_authorization_digest is None
            or authorization.execution_authorization_digest != authorization.canonical_digest()
        ):
            raise MaskedCalculationRecoveryError("masked authorization journal is tampered")

    @staticmethod
    def _require_sealed_attempt(attempt: MaskedExecutionAttemptV3) -> None:
        if (
            attempt.execution_attempt_digest is None
            or attempt.execution_attempt_digest != attempt.canonical_digest()
        ):
            raise MaskedCalculationRecoveryError("masked attempt journal is tampered")

    @staticmethod
    def _without_numeric(record: MaskedExecutionRecordV3) -> MaskedExecutionRecordV3:
        return MaskedExecutionRecordV3(
            request_id=record.request_id,
            organization_id=record.organization_id,
            masked_calculation_identity_digest=record.masked_calculation_identity_digest,
            request_digest=record.request_digest,
            idempotency_digest=record.idempotency_digest,
            issued_at=record.issued_at,
            admission=record.admission,
            authorization=record.authorization,
            status=record.status,
            attempts=record.attempts,
            report=None,
            failure=record.failure,
            consulted_admission=record.consulted_admission,
        )

    def _public_record(self, record: MaskedExecutionRecordV3) -> MaskedExecutionRecordV3:
        return MaskedExecutionRecordV3(
            request_id=record.request_id,
            organization_id=record.organization_id,
            masked_calculation_identity_digest=record.masked_calculation_identity_digest,
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

    def _require_designated_caller(self, worker: Principal) -> None:
        """Every fenced worker call must bear the configured designated worker.

        Kind, grant, exact id, and org are all pinned: a second worker in the
        same org, a V2 worker identity, or an elevated human fails here with
        no journal mutation.  Workers are never granted SITES_WRITE.
        """
        granted = principal_permissions(worker)
        if (
            worker.kind is not PrincipalKind.ANALYSIS_WORKER
            or Permission.ANALYSIS_WORK not in granted
        ):
            raise PermissionError("masked execution requires the dedicated organization worker")
        if (
            worker.principal_id != self._designated_worker.principal_id
            or worker.organization_id != self._designated_worker.organization_id
        ):
            raise PermissionError("masked worker is not the designated execution worker")

    @staticmethod
    def _require_attempt_worker_binding(
        record: MaskedExecutionRecordV3,
        worker: Principal,
        attempt: MaskedExecutionAttemptV3 | None = None,
    ) -> None:
        if worker.organization_id != record.organization_id:
            raise PermissionError("masked worker is outside calculation scope")
        if worker.principal_id != record.authorization.worker_principal_id:
            # A record sealed under another worker (stale config, replay from
            # a rotated deployment) is not executable; the sealed record is
            # never rewritten.
            raise PermissionError("masked worker does not hold the authorized fence")
        if attempt is not None:
            active = record.active_attempt
            if active is None or active != attempt:
                raise PermissionError("masked attempt is not the active fence")
            if (
                attempt.worker_instance_id != active.worker_instance_id
                or attempt.lease_acquisition_id != active.lease_acquisition_id
                or attempt.lease_generation != active.lease_generation
                or attempt.attempt_id != active.attempt_id
            ):
                raise PermissionError("masked worker binding does not match the fence")

    @staticmethod
    def _require_utc(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("masked execution time must be UTC")

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
            raise PermissionError("masked issue requires SITES_WRITE")

    @staticmethod
    def _has_site_read(principal: Principal) -> bool:
        granted = principal_permissions(principal)
        return (
            Permission.ANALYSIS_API_READ in granted
            if principal.kind is PrincipalKind.ANALYSIS_MCP_CLIENT
            else Permission.SITES_READ in granted
        )

    @classmethod
    def _require_record_scope_for_identity(
        cls, principal: Principal, identity: MaskedCalculationIdentityV3
    ) -> None:
        if principal.kind is not PrincipalKind.ANALYSIS_MCP_CLIENT:
            if principal.organization_id != identity.organization_id:
                raise PermissionError("masked identity is outside caller scope")
            return
        if (
            principal.organization_id != identity.organization_id
            or principal.allowed_site_ids is None
            or identity.site_id not in principal.allowed_site_ids
            or principal.allowed_work_area_ids is None
            or identity.work_area_id not in principal.allowed_work_area_ids
        ):
            raise PermissionError("masked identity is outside client scope")

    @classmethod
    def _require_record_scope(cls, principal: Principal, record: MaskedExecutionRecordV3) -> None:
        if principal.kind is not PrincipalKind.ANALYSIS_MCP_CLIENT:
            if principal.organization_id != record.organization_id:
                raise PermissionError("masked calculation is outside caller scope")
            return
        if principal.organization_id != record.organization_id:
            raise PermissionError("masked calculation is outside client scope")

    @classmethod
    def _require_witness_scope(
        cls, principal: Principal, witness: MaskedAdmissionWitnessV3
    ) -> None:
        admission = witness.admission
        identity = witness.source_identity
        if (
            admission.organization_id != principal.organization_id
            or admission.organization_id != identity.organization_id
            or admission.site_id != identity.site_id
            or admission.work_area_id != identity.work_area_id
        ):
            raise PermissionError("masked admission is outside caller scope")
        if principal.kind is PrincipalKind.ANALYSIS_MCP_CLIENT:
            if (
                principal.allowed_site_ids is not None
                and admission.site_id not in principal.allowed_site_ids
            ):
                raise PermissionError("masked admission is outside client scope")
            if (
                principal.allowed_work_area_ids is not None
                and admission.work_area_id not in principal.allowed_work_area_ids
            ):
                raise PermissionError("masked admission is outside client scope")


__all__ = [
    "ExternalMaskedCalculationStore",
    "MaskedAdmissionEvidencePort",
    "MaskedAdmissionWitnessV3",
    "MaskedCalculationRecoveryError",
    "MaskedCurrentDispositionV3",
    "MaskedCurrentViewV3",
    "MaskedExecutionRecordV3",
    "MaskedExecutionStatusV3",
    "MaskedManifestEvidencePort",
    "MaskedSourceEvidencePort",
]
