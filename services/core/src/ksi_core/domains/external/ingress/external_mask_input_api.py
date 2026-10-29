"""Optional, closed, bounded HTTP seam for independent mask-child ingress.

Human OPERATOR-only declarations plus raw bounded uploads; worker-only
narrow-inspection lease, protected-bytes fetch, and seal-from-report.  No
route mounts by default: the parent composition mounts these routers
explicitly and owns the auth allowlists.  MCP identities are denied here
(the new mask tools are not approved); the existing delta MCP surface is
untouched.

Trust boundaries, read carefully:

- The native mask inspector NEVER runs inside Core.  The worker fetches
  sealed bytes through the worker-only bytes endpoint, runs the contained
  primitive outside Core, and POSTs the sealed narrow report.  Core only
  seals: ``ExternalMaskInputStore.seal_observed`` rebuilds the manifest
  from the baseline anchor, the scoped protected-byte proof, and the
  separate profile activation.  Caller-written rows/digests and any caller
  ``userDeclaredInspection`` claim are never accepted.
- The inspection job fence below is server-issued and durable: a report is
  accepted only with a live lease binding the exact declared child, the
  exact worker, the exact inspection profile digest, and the exact byte
  identity.  A report caller hash alone is untrusted.  Humans cannot POST
  observations (403); the seal call carries the authenticated designated
  worker principal.
- Inspection budget is positive and capped: lease TTL comes from the sealed
  envelope and total issued leases per child never exceed the envelope's
  maximum retry attempts.
- Scope is checked before every mutation: path organization/site/area must
  match the stored scope; missing or foreign records answer uniform 404.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import tempfile
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ResourceEnvelopeV1,
)
from ksi_event_contracts.external_mask_input import (
    MaskChildDeclarationV1,
    MaskInspectionProfileV1,
)
from ksi_event_contracts.external_mask_input_report import MaskObservationReportV1
from ksi_event_contracts.external_masked_api import (
    MaskChildViewV1,
    MaskedBytesSliceViewV1,
    MaskInspectionFailureRequestV1,
    MaskInspectionFailureViewV1,
    MaskInspectionLeaseRequestV1,
    MaskInspectionLeaseViewV1,
    MaskInspectionPendingItemV1,
    MaskInspectionPendingListV1,
    MaskInspectionReportRequestV1,
    MaskInspectionStatusViewV1,
    MaskSealViewV1,
    MaskSourceContextViewV1,
    MaskUploadGrantRequestV1,
    MaskUploadGrantViewV1,
    MaskUploadSealViewV1,
    inspection_failure_status_for,
)
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from starlette.concurrency import run_in_threadpool

from ksi_core.domains.external.ingress.external_mask_input_bytes import (
    ExternalMaskInputByteStore,
)
from ksi_core.domains.external.ingress.external_mask_input_core_adapters import (
    MaskSourceNotAdmitted,
)
from ksi_core.domains.external.ingress.external_mask_input_store import (
    ExternalMaskInputStore,
)
from ksi_core.foundation.api_base import iso_utc
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import (
    Permission,
    Principal,
    PrincipalKind,
    require_permission,
)

_MAX_JSON = 65536
_MAX_SLICE = 1024 * 1024

_VERSION = 1
_EVENT_LEASED = "masked-inspection-lease-issued.v1"
_EVENT_ANNOUNCED = "masked-inspection-announced.v1"
_EVENT_FAILED = "masked-inspection-failed.v1"
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_LEASE_ID_PREFIX = "masked-inspection-lease-"
_LEASED_FIELDS = frozenset(
    {
        "kind",
        "version",
        "eventDigest",
        "leaseId",
        "organizationId",
        "siteId",
        "workAreaId",
        "maskChildId",
        "maskArtifactId",
        "subjectDigest",
        "baselineSubjectDigest",
        "baselineDsmArtifactId",
        "inspectionProfileDigest",
        "workerPrincipalId",
        "workerInstanceId",
        "leaseAcquisitionId",
        "issuedAt",
        "expiresAt",
    }
)
_ANNOUNCED_FIELDS = frozenset(
    {
        "kind",
        "version",
        "eventDigest",
        "organizationId",
        "siteId",
        "workAreaId",
        "maskChildId",
        "announcedAt",
        "declaration",
    }
)
_FAILED_FIELDS = frozenset(
    {
        "kind",
        "version",
        "eventDigest",
        "organizationId",
        "siteId",
        "workAreaId",
        "maskChildId",
        "maskArtifactId",
        "subjectDigest",
        "leaseId",
        "workerPrincipalId",
        "workerInstanceId",
        "inspectionProfileDigest",
        "reasonCode",
        "failedAt",
    }
)
_VALID_FAILURE_REASONS = frozenset(
    {
        "MASK_NODATA_REJECTED",
        "MASK_BYTES_MISMATCH",
        "MASK_RESOURCE_EXCEEDED",
        "MASK_INSPECTION_FAILED",
    }
)


@dataclass(frozen=True, slots=True)
class MaskAnnouncedChild:
    """One human-declared child awaiting worker inspection (Core-known)."""

    organization_id: str
    site_id: str
    work_area_id: str
    mask_child_id: str
    declaration: MaskChildDeclarationV1
    announced_at: datetime


class MaskInspectionJobRecoveryError(RuntimeError):
    """The inspection-job journal cannot be replayed safely."""


@dataclass(frozen=True, slots=True)
class MaskInspectionFailure:
    """One terminal worker-observed inspection failure (never revived)."""

    organization_id: str
    site_id: str
    work_area_id: str
    mask_child_id: str
    mask_artifact_id: str
    subject_digest: str
    lease_id: str
    worker_principal_id: str
    worker_instance_id: str
    inspection_profile_digest: str
    reason_code: str
    failed_at: datetime


@dataclass(frozen=True, slots=True)
class MaskInspectionLease:
    lease_id: str
    organization_id: str
    site_id: str
    work_area_id: str
    mask_child_id: str
    mask_artifact_id: str
    subject_digest: str
    baseline_subject_digest: str
    baseline_dsm_artifact_id: str
    inspection_profile_digest: str
    worker_principal_id: str
    worker_instance_id: str
    lease_acquisition_id: str
    issued_at: datetime
    expires_at: datetime

    def is_live(self, now: datetime) -> bool:
        return self.issued_at <= now < self.expires_at


def _digest(value: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _event_digest(raw: Mapping[str, object]) -> str:
    return _digest({key: value for key, value in raw.items() if key != "eventDigest"})


def _journal_text(value: object, description: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise MaskInspectionJobRecoveryError(f"inspection job {description} is malformed")
    return value


def _journal_id(value: object, description: str) -> str:
    """Opaque short id: never a URL, path, or capability."""
    text = _journal_text(value, description + " id")
    if len(text) > 128:
        raise MaskInspectionJobRecoveryError(f"inspection job {description} id is malformed")
    lowered = text.lower()
    if (
        "://" in text
        or text.startswith(("/", "\\"))
        or ".." in text
        or "\\" in text
        or "\n" in text
        or "\r" in text
        or lowered.startswith(("http:", "https:", "s3:", "file:", "cap:"))
    ):
        raise MaskInspectionJobRecoveryError(f"inspection job {description} id is not opaque")
    return text


def _journal_lease_id(value: object) -> str:
    lease_id = _journal_id(value, "lease")
    if not lease_id.startswith(_LEASE_ID_PREFIX):
        raise MaskInspectionJobRecoveryError("inspection job lease id escapes its namespace")
    return lease_id


def _journal_digest(value: object, description: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise MaskInspectionJobRecoveryError(f"inspection job {description} digest is invalid")
    return value


def _parse_utc(value: object, description: str) -> datetime:
    if not isinstance(value, str):
        raise MaskInspectionJobRecoveryError(f"inspection job {description} must be UTC text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MaskInspectionJobRecoveryError(
            f"inspection job {description} must be an RFC3339 UTC timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise MaskInspectionJobRecoveryError(f"inspection job {description} must be UTC")
    return parsed


class MaskInspectionJobLedger:
    """Durable server-issued inspection-job fence for one mask lane.

    Owned by this API module (new journal ``external-mask-inspection-jobs``).
    Lease issuance is the only mutation; report acceptance only reads a live
    lease.  Total issued leases per child are capped by the sealed envelope's
    maximum retry attempts (positive budget, never unbounded).
    """

    def __init__(
        self,
        journal: DurableJournal,
        *,
        resource_envelope: ResourceEnvelopeV1,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        if (
            resource_envelope.resource_envelope_digest is None
            or resource_envelope.resource_envelope_digest != resource_envelope.canonical_digest()
        ):
            raise ValueError("inspection fence requires a sealed resource envelope")
        self._journal = journal
        self._envelope = resource_envelope.model_copy(deep=True)
        self._coordinator = coordinator or ExternalAuthorityCurrentnessCoordinator()
        self._lock = threading.RLock()
        self._leases: dict[str, MaskInspectionLease] = {}
        self._failures: dict[tuple[str, str], MaskInspectionFailure] = {}
        self._issued_count: dict[tuple[str, str], int] = {}
        self._spent_acquisitions: set[tuple[str, str, str, str]] = set()
        self._announced: dict[tuple[str, str], MaskAnnouncedChild] = {}
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException as exc:
            journal.close()
            if isinstance(exc, MaskInspectionJobRecoveryError):
                raise
            raise MaskInspectionJobRecoveryError(str(exc)) from exc

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def _lease_duration(self) -> timedelta:
        return timedelta(seconds=self._envelope.lease_duration_seconds)

    @staticmethod
    def _announcement_mismatch(
        *,
        site_id: str,
        work_area_id: str,
        mask_child_id: str,
        mask_artifact_id: str,
        subject_digest: str,
        baseline_subject_digest: str,
        baseline_dsm_artifact_id: str,
        declaration: MaskChildDeclarationV1,
    ) -> str | None:
        """Exact lease↔announcement binding against the Core declaration."""
        if (
            (site_id, work_area_id, mask_child_id, mask_artifact_id)
            != (
                declaration.site_id,
                declaration.work_area_id,
                declaration.mask_child_id,
                declaration.mask_artifact_id,
            )
            or subject_digest != declaration.parent_subject.canonical_digest()
            or baseline_subject_digest != declaration.target_baseline_subject.canonical_digest()
            or baseline_dsm_artifact_id != declaration.target_baseline_dsm_artifact_id
        ):
            return "inspection lease does not bind its announced declaration"
        return None

    def issue_lease(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        mask_child_id: str,
        mask_artifact_id: str,
        subject_digest: str,
        baseline_subject_digest: str,
        baseline_dsm_artifact_id: str,
        inspection_profile_digest: str,
        worker_principal_id: str,
        worker_instance_id: str,
        lease_acquisition_id: str,
        now: datetime,
    ) -> MaskInspectionLease:
        self._require_utc(now)
        with self._coordinator.mutation(), self._lock:
            announced = self._announced.get((organization_id, mask_child_id))
            if announced is None:
                raise ValueError("mask inspection job is not announced")
            mismatch = self._announcement_mismatch(
                site_id=site_id,
                work_area_id=work_area_id,
                mask_child_id=mask_child_id,
                mask_artifact_id=mask_artifact_id,
                subject_digest=subject_digest,
                baseline_subject_digest=baseline_subject_digest,
                baseline_dsm_artifact_id=baseline_dsm_artifact_id,
                declaration=announced.declaration,
            )
            if mismatch is not None:
                raise ValueError(mismatch)
            if (organization_id, mask_child_id) in self._failures:
                raise ValueError("mask inspection job already reached a terminal outcome")
            live = self._live_locked(organization_id, mask_child_id, now)
            if live is not None:
                if (
                    live.worker_instance_id == worker_instance_id
                    and live.lease_acquisition_id == lease_acquisition_id
                    and live.inspection_profile_digest == inspection_profile_digest
                    and live.worker_principal_id == worker_principal_id
                ):
                    return live
                raise ValueError("mask inspection job is already leased to another fence")
            spent_key = (
                organization_id,
                mask_child_id,
                worker_instance_id,
                lease_acquisition_id,
            )
            if spent_key in self._spent_acquisitions:
                raise ValueError("mask inspection acquisition is already spent")
            key = (organization_id, mask_child_id)
            if self._issued_count.get(key, 0) >= self._envelope.max_retry_attempts:
                raise ValueError("mask inspection job budget is exhausted")
            lease = MaskInspectionLease(
                lease_id="masked-inspection-lease-" + uuid.uuid4().hex[:16],
                organization_id=organization_id,
                site_id=site_id,
                work_area_id=work_area_id,
                mask_child_id=mask_child_id,
                mask_artifact_id=mask_artifact_id,
                subject_digest=subject_digest,
                baseline_subject_digest=baseline_subject_digest,
                baseline_dsm_artifact_id=baseline_dsm_artifact_id,
                inspection_profile_digest=inspection_profile_digest,
                worker_principal_id=worker_principal_id,
                worker_instance_id=worker_instance_id,
                lease_acquisition_id=lease_acquisition_id,
                issued_at=now,
                expires_at=now + self._lease_duration(),
            )
            raw: dict[str, object] = {
                "kind": _EVENT_LEASED,
                "version": _VERSION,
                "organizationId": organization_id,
                "maskChildId": mask_child_id,
                "leaseId": lease.lease_id,
                "siteId": site_id,
                "workAreaId": work_area_id,
                "maskArtifactId": mask_artifact_id,
                "subjectDigest": subject_digest,
                "baselineSubjectDigest": baseline_subject_digest,
                "baselineDsmArtifactId": baseline_dsm_artifact_id,
                "inspectionProfileDigest": inspection_profile_digest,
                "workerPrincipalId": worker_principal_id,
                "workerInstanceId": worker_instance_id,
                "leaseAcquisitionId": lease_acquisition_id,
                "issuedAt": iso_utc(now),
                "expiresAt": iso_utc(lease.expires_at),
            }
            record = dict(raw)
            record["eventDigest"] = _event_digest(record)
            try:
                self._journal.append(record)
            except JournalSealedError:
                raise
            except BaseException as exc:
                raise MaskInspectionJobRecoveryError(str(exc)) from exc
            self._apply(record)
            self._spent_acquisitions.add(
                (
                    lease.organization_id,
                    lease.mask_child_id,
                    lease.worker_instance_id,
                    lease.lease_acquisition_id,
                )
            )
            return self._leases[lease.lease_id]

    def record_announced(
        self,
        *,
        organization_id: str,
        declaration: MaskChildDeclarationV1,
        now: datetime,
    ) -> MaskAnnouncedChild:
        """Announce one human declaration for worker discovery (idempotent).

        The declaration is Core-sealed and Core-stored; this journal only
        indexes its discovery.  No bytes, grids, or profiles travel here.
        """
        self._require_utc(now)
        sealed = MaskChildDeclarationV1.model_validate(declaration.model_dump(by_alias=True))
        if (
            sealed.declaration_digest is None
            or sealed.declaration_digest != sealed.canonical_digest()
            or sealed.organization_id != organization_id
        ):
            raise ValueError("announced declaration must be sealed for its organization")
        key = (organization_id, sealed.mask_child_id)
        with self._coordinator.mutation(), self._lock:
            existing = self._announced.get(key)
            if existing is not None:
                if existing.declaration != sealed:
                    raise ValueError("mask child id is already announced otherwise")
                return existing
            announced = MaskAnnouncedChild(
                organization_id=organization_id,
                site_id=sealed.site_id,
                work_area_id=sealed.work_area_id,
                mask_child_id=sealed.mask_child_id,
                declaration=sealed,
                announced_at=now,
            )
            raw: dict[str, object] = {
                "kind": _EVENT_ANNOUNCED,
                "version": _VERSION,
                "organizationId": organization_id,
                "siteId": sealed.site_id,
                "workAreaId": sealed.work_area_id,
                "maskChildId": sealed.mask_child_id,
                "announcedAt": iso_utc(now),
                "declaration": sealed.model_dump(by_alias=True, mode="json"),
            }
            record = dict(raw)
            record["eventDigest"] = _event_digest(record)
            try:
                self._journal.append(record)
            except JournalSealedError:
                raise
            except BaseException as exc:
                raise MaskInspectionJobRecoveryError(str(exc)) from exc
            self._apply(record)
            return announced

    def list_announced(self, *, organization_id: str) -> tuple[MaskAnnouncedChild, ...]:
        """Announced children for one organization, oldest first."""
        with self._coordinator.guarded_read(), self._lock:
            return tuple(
                sorted(
                    (
                        item
                        for (org, _child), item in self._announced.items()
                        if org == organization_id
                    ),
                    key=lambda item: (item.announced_at, item.mask_child_id),
                )
            )

    def check_lease(
        self,
        *,
        organization_id: str,
        mask_child_id: str,
        lease_id: str,
        worker_principal_id: str,
        worker_instance_id: str,
        inspection_profile_digest: str,
        now: datetime,
    ) -> MaskInspectionLease | None:
        self._require_utc(now)
        with self._coordinator.guarded_read(), self._lock:
            lease = self._leases.get(lease_id)
            if (
                lease is None
                or lease.organization_id != organization_id
                or lease.mask_child_id != mask_child_id
                or lease.worker_principal_id != worker_principal_id
                or lease.worker_instance_id != worker_instance_id
                or lease.inspection_profile_digest != inspection_profile_digest
                or not lease.is_live(now)
            ):
                return None
            return lease

    def resolve_live_lease(
        self,
        *,
        organization_id: str,
        mask_child_id: str,
        lease_id: str,
        worker_principal_id: str,
        worker_instance_id: str,
        now: datetime,
    ) -> MaskInspectionLease | None:
        """Resolve a live lease by its server-issued id (bytes/report paths).

        Binds organization, child, worker identity, and liveness only.  The
        inspection profile digest is never taken from the caller here: sealed
        bytes are not authority, and the seal path re-binds the exact live
        lease plus the profile activation through :meth:`check_lease`.
        """
        self._require_utc(now)
        with self._coordinator.guarded_read(), self._lock:
            lease = self._leases.get(lease_id)
            if (
                lease is None
                or lease.organization_id != organization_id
                or lease.mask_child_id != mask_child_id
                or lease.worker_principal_id != worker_principal_id
                or lease.worker_instance_id != worker_instance_id
                or not lease.is_live(now)
            ):
                return None
            return lease

    def get_failure(
        self, *, organization_id: str, mask_child_id: str
    ) -> MaskInspectionFailure | None:
        """Return the terminal failure recorded for one child, if any."""
        with self._coordinator.guarded_read(), self._lock:
            return self._failures.get((organization_id, mask_child_id))

    def record_failure(
        self,
        *,
        organization_id: str,
        mask_child_id: str,
        lease_id: str,
        worker_principal_id: str,
        worker_instance_id: str,
        inspection_profile_digest: str,
        reason_code: str,
        now: datetime,
    ) -> MaskInspectionFailure:
        """Journal one terminal worker-observed inspection failure.

        Requires the exact live lease plus the announced declaration; the
        reason is one closed wire code, never a native trace.  First terminal
        outcome wins: a sealed manifest and a recorded failure can never be
        followed by another fence transition (no revival).
        """
        self._require_utc(now)
        if reason_code not in _VALID_FAILURE_REASONS:
            raise ValueError("inspection failure reason is not a closed reason code")
        with self._coordinator.mutation(), self._lock:
            key = (organization_id, mask_child_id)
            existing = self._failures.get(key)
            announced = self._announced.get(key)
            if announced is None:
                raise ValueError("mask inspection job is not announced")
            lease = self._leases.get(lease_id)
            if (
                lease is None
                or lease.organization_id != organization_id
                or lease.mask_child_id != mask_child_id
                or lease.worker_principal_id != worker_principal_id
                or lease.worker_instance_id != worker_instance_id
                or lease.inspection_profile_digest != inspection_profile_digest
                or not lease.is_live(now)
            ):
                raise ValueError("mask inspection failure does not bind a live fence")
            mismatch = self._announcement_mismatch(
                site_id=lease.site_id,
                work_area_id=lease.work_area_id,
                mask_child_id=lease.mask_child_id,
                mask_artifact_id=lease.mask_artifact_id,
                subject_digest=lease.subject_digest,
                baseline_subject_digest=lease.baseline_subject_digest,
                baseline_dsm_artifact_id=lease.baseline_dsm_artifact_id,
                declaration=announced.declaration,
            )
            if mismatch is not None:
                raise ValueError(mismatch)
            failure = MaskInspectionFailure(
                organization_id=lease.organization_id,
                site_id=lease.site_id,
                work_area_id=lease.work_area_id,
                mask_child_id=lease.mask_child_id,
                mask_artifact_id=lease.mask_artifact_id,
                subject_digest=lease.subject_digest,
                lease_id=lease.lease_id,
                worker_principal_id=lease.worker_principal_id,
                worker_instance_id=lease.worker_instance_id,
                inspection_profile_digest=lease.inspection_profile_digest,
                reason_code=reason_code,
                failed_at=now,
            )
            if existing is not None:
                if existing != failure:
                    raise ValueError("mask inspection job already reached a terminal outcome")
                return existing
            raw: dict[str, object] = {
                "kind": _EVENT_FAILED,
                "version": _VERSION,
                "organizationId": failure.organization_id,
                "siteId": failure.site_id,
                "workAreaId": failure.work_area_id,
                "maskChildId": failure.mask_child_id,
                "maskArtifactId": failure.mask_artifact_id,
                "subjectDigest": failure.subject_digest,
                "leaseId": failure.lease_id,
                "workerPrincipalId": failure.worker_principal_id,
                "workerInstanceId": failure.worker_instance_id,
                "inspectionProfileDigest": failure.inspection_profile_digest,
                "reasonCode": failure.reason_code,
                "failedAt": iso_utc(now),
            }
            record = dict(raw)
            record["eventDigest"] = _event_digest(record)
            try:
                self._journal.append(record)
            except JournalSealedError:
                raise
            except BaseException as exc:
                raise MaskInspectionJobRecoveryError(str(exc)) from exc
            self._apply(record)
            stored = self._failures.get(key)
            assert stored == failure
            return stored

    def is_job_running(self, *, organization_id: str, mask_child_id: str, now: datetime) -> bool:
        """A live fence exists for one child (status derivation only)."""
        self._require_utc(now)
        with self._coordinator.guarded_read(), self._lock:
            return self._live_locked(organization_id, mask_child_id, now) is not None

    def _live_locked(
        self, organization_id: str, mask_child_id: str, now: datetime
    ) -> MaskInspectionLease | None:
        for lease in self._leases.values():
            if (
                lease.organization_id == organization_id
                and lease.mask_child_id == mask_child_id
                and lease.is_live(now)
            ):
                return lease
        return None

    @staticmethod
    def _overlaps(
        first_issued: datetime,
        first_expires: datetime,
        second_issued: datetime,
        second_expires: datetime,
    ) -> bool:
        return max(first_issued, second_issued) < min(first_expires, second_expires)

    def _apply(self, raw: Mapping[str, object]) -> None:
        kind = raw.get("kind")
        if (
            not isinstance(kind, str)
            or kind not in (_EVENT_LEASED, _EVENT_ANNOUNCED, _EVENT_FAILED)
            or type(raw.get("version")) is not int
            or raw.get("version") != _VERSION
        ):
            raise MaskInspectionJobRecoveryError("inspection job journal kind is unsupported")
        expected_fields = (
            _LEASED_FIELDS
            if kind == _EVENT_LEASED
            else _ANNOUNCED_FIELDS
            if kind == _EVENT_ANNOUNCED
            else _FAILED_FIELDS
        )
        if set(raw.keys()) != expected_fields:
            raise MaskInspectionJobRecoveryError("inspection job journal fields are not exact")
        digest = raw.get("eventDigest")
        if not isinstance(digest, str) or digest != _event_digest(raw):
            raise MaskInspectionJobRecoveryError("inspection job journal digest is invalid")
        if kind == _EVENT_ANNOUNCED:
            self._apply_announced(raw)
            return
        if kind == _EVENT_FAILED:
            self._apply_failure(raw)
            return
        self._apply_lease(raw)

    def _apply_announced(self, raw: Mapping[str, object]) -> None:
        declaration = MaskChildDeclarationV1.model_validate(raw["declaration"])
        if (
            declaration.declaration_digest is None
            or declaration.declaration_digest != declaration.canonical_digest()
        ):
            raise MaskInspectionJobRecoveryError("announced declaration is tampered")
        organization_id = _journal_text(raw["organizationId"], "organization")
        site_id = _journal_text(raw["siteId"], "site")
        work_area_id = _journal_text(raw["workAreaId"], "work area")
        mask_child_id = _journal_id(raw["maskChildId"], "mask child")
        if (
            declaration.organization_id != organization_id
            or declaration.site_id != site_id
            or declaration.work_area_id != work_area_id
            or declaration.mask_child_id != mask_child_id
        ):
            raise MaskInspectionJobRecoveryError("announced declaration escapes its scope")
        key = (organization_id, mask_child_id)
        announced = MaskAnnouncedChild(
            organization_id=organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            mask_child_id=mask_child_id,
            declaration=declaration,
            announced_at=_parse_utc(raw["announcedAt"], "announcement time"),
        )
        existing = self._announced.get(key)
        if existing is not None:
            if existing != announced:
                raise MaskInspectionJobRecoveryError("announced declaration conflicts")
            return
        self._announced[key] = announced

    def _apply_lease(self, raw: Mapping[str, object]) -> None:
        lease = MaskInspectionLease(
            lease_id=_journal_lease_id(raw["leaseId"]),
            organization_id=_journal_text(raw["organizationId"], "organization"),
            site_id=_journal_text(raw["siteId"], "site"),
            work_area_id=_journal_text(raw["workAreaId"], "work area"),
            mask_child_id=_journal_id(raw["maskChildId"], "mask child"),
            mask_artifact_id=_journal_id(raw["maskArtifactId"], "mask artifact"),
            subject_digest=_journal_digest(raw["subjectDigest"], "subject"),
            baseline_subject_digest=_journal_digest(
                raw["baselineSubjectDigest"], "baseline subject"
            ),
            baseline_dsm_artifact_id=_journal_id(
                raw["baselineDsmArtifactId"], "baseline DSM artifact"
            ),
            inspection_profile_digest=_journal_digest(
                raw["inspectionProfileDigest"], "inspection profile"
            ),
            worker_principal_id=_journal_id(raw["workerPrincipalId"], "worker principal"),
            worker_instance_id=_journal_id(raw["workerInstanceId"], "worker instance"),
            lease_acquisition_id=_journal_id(raw["leaseAcquisitionId"], "lease acquisition"),
            issued_at=_parse_utc(raw["issuedAt"], "lease issuance"),
            expires_at=_parse_utc(raw["expiresAt"], "lease expiry"),
        )
        if lease.expires_at - lease.issued_at != self._lease_duration():
            raise MaskInspectionJobRecoveryError(
                "inspection job lease duration differs from the sealed envelope"
            )
        announced = self._announced.get((lease.organization_id, lease.mask_child_id))
        if announced is None:
            raise MaskInspectionJobRecoveryError("inspection lease precedes its announcement")
        mismatch = self._announcement_mismatch(
            site_id=lease.site_id,
            work_area_id=lease.work_area_id,
            mask_child_id=lease.mask_child_id,
            mask_artifact_id=lease.mask_artifact_id,
            subject_digest=lease.subject_digest,
            baseline_subject_digest=lease.baseline_subject_digest,
            baseline_dsm_artifact_id=lease.baseline_dsm_artifact_id,
            declaration=announced.declaration,
        )
        if mismatch is not None:
            raise MaskInspectionJobRecoveryError(mismatch)
        existing = self._leases.get(lease.lease_id)
        if existing is not None:
            if existing != lease:
                raise MaskInspectionJobRecoveryError("inspection job journal conflicts")
            return
        spent_key = (
            lease.organization_id,
            lease.mask_child_id,
            lease.worker_instance_id,
            lease.lease_acquisition_id,
        )
        if spent_key in self._spent_acquisitions:
            raise MaskInspectionJobRecoveryError("inspection acquisition is already spent")
        key = (lease.organization_id, lease.mask_child_id)
        for other in self._leases.values():
            if (other.organization_id, other.mask_child_id) == key and self._overlaps(
                other.issued_at,
                other.expires_at,
                lease.issued_at,
                lease.expires_at,
            ):
                raise MaskInspectionJobRecoveryError("inspection job fences overlap")
        if self._issued_count.get(key, 0) >= self._envelope.max_retry_attempts:
            raise MaskInspectionJobRecoveryError("inspection job budget exceeded on replay")
        self._leases[lease.lease_id] = lease
        self._issued_count[key] = self._issued_count.get(key, 0) + 1
        self._spent_acquisitions.add(
            (
                lease.organization_id,
                lease.mask_child_id,
                lease.worker_instance_id,
                lease.lease_acquisition_id,
            )
        )

    def _apply_failure(self, raw: Mapping[str, object]) -> None:
        organization_id = _journal_text(raw["organizationId"], "organization")
        site_id = _journal_text(raw["siteId"], "site")
        work_area_id = _journal_text(raw["workAreaId"], "work area")
        mask_child_id = _journal_id(raw["maskChildId"], "mask child")
        lease_id = _journal_lease_id(raw["leaseId"])
        reason_code = _journal_id(raw["reasonCode"], "failure reason")
        if reason_code not in _VALID_FAILURE_REASONS:
            raise MaskInspectionJobRecoveryError("inspection failure reason is not closed")
        failure = MaskInspectionFailure(
            organization_id=organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            mask_child_id=mask_child_id,
            mask_artifact_id=_journal_id(raw["maskArtifactId"], "mask artifact"),
            subject_digest=_journal_digest(raw["subjectDigest"], "subject"),
            lease_id=lease_id,
            worker_principal_id=_journal_id(raw["workerPrincipalId"], "worker principal"),
            worker_instance_id=_journal_id(raw["workerInstanceId"], "worker instance"),
            inspection_profile_digest=_journal_digest(
                raw["inspectionProfileDigest"], "inspection profile"
            ),
            reason_code=reason_code,
            failed_at=_parse_utc(raw["failedAt"], "failure time"),
        )
        key = (organization_id, mask_child_id)
        existing = self._failures.get(key)
        if existing is not None:
            if existing != failure:
                raise MaskInspectionJobRecoveryError("inspection failure journal conflicts")
            return
        announced = self._announced.get(key)
        if announced is None:
            raise MaskInspectionJobRecoveryError("inspection failure precedes its announcement")
        lease = self._leases.get(failure.lease_id)
        if lease is None:
            raise MaskInspectionJobRecoveryError("inspection failure precedes its fence")
        if (
            (lease.organization_id, lease.mask_child_id) != key
            or lease.worker_principal_id != failure.worker_principal_id
            or lease.worker_instance_id != failure.worker_instance_id
            or lease.inspection_profile_digest != failure.inspection_profile_digest
            or lease.site_id != failure.site_id
            or lease.work_area_id != failure.work_area_id
            or lease.mask_artifact_id != failure.mask_artifact_id
            or lease.subject_digest != failure.subject_digest
            or not (lease.issued_at <= failure.failed_at <= lease.expires_at)
        ):
            raise MaskInspectionJobRecoveryError("inspection failure escapes its fence")
        mismatch = self._announcement_mismatch(
            site_id=lease.site_id,
            work_area_id=lease.work_area_id,
            mask_child_id=lease.mask_child_id,
            mask_artifact_id=lease.mask_artifact_id,
            subject_digest=lease.subject_digest,
            baseline_subject_digest=lease.baseline_subject_digest,
            baseline_dsm_artifact_id=lease.baseline_dsm_artifact_id,
            declaration=announced.declaration,
        )
        if mismatch is not None:
            raise MaskInspectionJobRecoveryError(mismatch)
        self._failures[key] = failure
        self._spent_acquisitions.add(
            (
                lease.organization_id,
                lease.mask_child_id,
                lease.worker_instance_id,
                lease.lease_acquisition_id,
            )
        )

    @staticmethod
    def _require_utc(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("inspection job time must be UTC")


def _json_body(model: type[BaseModel]) -> dict[str, object]:
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": model.model_json_schema(by_alias=True)},
            },
        }
    }


class _Control(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class _Reason(_Control):
    reason: str = Field(min_length=1, max_length=255)


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError("non-finite JSON value")


async def _bounded_json[Model: BaseModel](request: Request, model: type[Model]) -> Model:
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise HTTPException(status_code=415, detail="JSON_REQUIRED")
    payload = bytearray()
    try:
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                if len(payload) + len(chunk) > _MAX_JSON:
                    raise HTTPException(status_code=413, detail="MASK_REQUEST_TOO_LARGE")
                payload.extend(chunk)
        return model.model_validate(
            json.loads(
                payload,
                object_pairs_hook=_reject_duplicates,
                parse_constant=_reject_constant,
            )
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail="MASK_REQUEST_TIMED_OUT") from exc
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(status_code=422, detail="MASK_REQUEST_INVALID") from exc


def _lookup_grant(byte_store: ExternalMaskInputByteStore, grant_id: str) -> Any | None:
    """Read-only routing guard over the genuine grant index (no mutation).

    The byte store owns the grant journal; this lookup only verifies that a
    path-scoped upload targets the grant's own scope before mutating.  If the
    owning Lead later exposes a public getter, prefer it here.
    """
    grants = getattr(byte_store, "_grants", None)
    if not isinstance(grants, dict):
        return None
    return grants.get(grant_id)


def read_sealed_mask_slice(
    byte_store: ExternalMaskInputByteStore,
    *,
    organization_id: str,
    site_id: str,
    mask_child_id: str,
    mask_artifact_id: str,
    subject_digest: str,
    offset: int,
    length: int,
    cap_bytes: int,
) -> bytes:
    """Bounded internal slice of sealed mask bytes; paths never leave Core.

    Owner ``read_slice`` exclusively: full proof hash plus window on the SAME
    bound fd under guard.  No caller path, no browser path, and no absolute
    ``os.open`` remains in this seam.
    """
    if offset < 0 or length <= 0 or length > min(_MAX_SLICE, cap_bytes):
        raise ValueError("mask byte range is invalid")
    window = byte_store.read_slice(
        organization_id=organization_id,
        site_id=site_id,
        mask_child_id=mask_child_id,
        mask_artifact_id=mask_artifact_id,
        subject_digest=subject_digest,
        offset=offset,
        length=length,
    )
    if len(window) != length:
        raise ValueError("mask byte slice is short")
    return window


def operator_scope_allows(principal: Principal, site_id: str, work_area_id: str) -> bool:
    """Pure operator allowlist check: both site and area when granted.

    Legacy unscoped operators pass; MCP identities are not operator-scoped
    (denied earlier by permission gates).  Unit-tested directly; the routers
    below fold a False into uniform 404.
    """
    if principal.kind is not PrincipalKind.OPERATOR:
        return False
    if principal.allowed_site_ids is not None and site_id not in principal.allowed_site_ids:
        return False
    return not (
        principal.allowed_work_area_ids is not None
        and work_area_id not in principal.allowed_work_area_ids
    )


class MaskedLaneSourcePort(Protocol):
    """Structural port over the genuine lane source-context (graph-owned)."""

    def activation_current(self, *, now: datetime) -> bool: ...

    def resolve_source_context(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        source_calculation_identity_digest: str,
        now: datetime,
    ) -> Any | None: ...


def build_external_mask_input_router(
    *,
    ingress: ExternalMaskInputStore,
    byte_store: ExternalMaskInputByteStore,
    inspection_journal: DurableJournal,
    resource_envelope: ResourceEnvelopeV1,
    designated_worker: Principal,
    lane_source: MaskedLaneSourcePort,
    clock: Callable[[], datetime] | None = None,
) -> APIRouter:
    """Build the closed mask-ingress HTTP seam over the genuine Core stores."""
    if not isinstance(ingress, ExternalMaskInputStore):
        raise ValueError("mask ingress router requires the concrete Core ingress store")
    if not isinstance(byte_store, ExternalMaskInputByteStore):
        raise ValueError("mask ingress router requires the concrete Core byte store")
    if not isinstance(inspection_journal, DurableJournal):
        raise ValueError("mask ingress router requires an explicit inspection-job journal")
    if not (
        callable(getattr(lane_source, "activation_current", None))
        and callable(getattr(lane_source, "resolve_source_context", None))
    ):
        raise ValueError("mask ingress router requires the genuine lane source port")
    envelope = ResourceEnvelopeV1.model_validate(resource_envelope.model_dump())
    if envelope.resource_envelope_digest != envelope.canonical_digest():
        raise ValueError("mask ingress router requires a sealed resource envelope")
    if (
        designated_worker.kind is not PrincipalKind.ANALYSIS_WORKER
        or not designated_worker.organization_id
    ):
        raise ValueError("mask ingress router requires the designated organization worker")
    if ingress.coordinator is not byte_store.coordinator:
        raise ValueError("mask ingress stores must share one coordinator")
    now = clock or (lambda: datetime.now(UTC))
    fence = MaskInspectionJobLedger(
        inspection_journal,
        resource_envelope=envelope,
        coordinator=ingress.coordinator,
    )
    router = APIRouter(tags=["external-mask-input"])
    write = require_permission(Permission.SITES_WRITE)
    read = require_permission(Permission.SITES_READ)
    work = require_permission(Permission.ANALYSIS_WORK)

    def require_operator(principal: Principal) -> None:
        if principal.kind is not PrincipalKind.OPERATOR:
            raise HTTPException(status_code=403, detail="MASK_OPERATOR_REQUIRED")

    def require_operator_scope(principal: Principal, site_id: str, work_area_id: str) -> None:
        """Optional operator allowlists bind both site and area before mutation.

        A scoped operator outside its grants sees uniform 404 (never a
        foreign record); legacy unscoped operators pass.  MCP identities never
        reach here (they lack site permissions), and workers use their own
        designated pin below.
        """
        if not operator_scope_allows(principal, site_id, work_area_id):
            raise HTTPException(status_code=404, detail="MASK_CHILD_NOT_FOUND")

    def require_designated_worker(principal: Principal) -> None:
        if principal.kind is not PrincipalKind.ANALYSIS_WORKER:
            raise HTTPException(status_code=403, detail="MASK_WORKER_REQUIRED")
        if (
            principal.principal_id != designated_worker.principal_id
            or principal.organization_id != designated_worker.organization_id
        ):
            raise HTTPException(status_code=403, detail="MASK_WORKER_MISMATCH")

    def byte_cap() -> int:
        return min(envelope.max_input_bytes, envelope.max_streamed_bytes)

    @router.post(
        "/v3/sites/{site_id}/work-areas/{work_area_id}/mask-children",
        response_model=MaskChildViewV1,
    )
    async def declare_child(
        site_id: str,
        work_area_id: str,
        request: Request,
        principal: Principal = Depends(write),  # noqa: B008
    ) -> MaskChildViewV1:
        require_operator(principal)
        require_operator_scope(principal, site_id, work_area_id)
        body = await _bounded_json(request, MaskChildDeclarationV1)
        if body.organization_id != principal.organization_id:
            raise HTTPException(status_code=404, detail="MASK_CHILD_NOT_FOUND")
        if body.site_id != site_id or body.work_area_id != work_area_id:
            raise HTTPException(status_code=404, detail="MASK_CHILD_NOT_FOUND")
        # The browser sends declaration *intent* (digest null); Core owns the
        # seal.  Revalidating here rejects a tampered provided digest with
        # 422 while a null digest seals to the canonical Core digest.  No
        # client hash math is trusted; subjects/grids/currentness are all
        # rechecked by the ingress store below.
        try:
            sealed_intent = body.sealed()
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail="MASK_DECLARATION_INVALID") from exc
        try:
            declaration = await run_in_threadpool(
                ingress.declare, principal=principal, declaration=sealed_intent, now=now()
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="MASK_SCOPE_DENIED") from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail="MASK_DECLARATION_UNAVAILABLE") from exc
        try:
            await run_in_threadpool(
                fence.record_announced,
                organization_id=principal.organization_id,
                declaration=declaration,
                now=now(),
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail="MASK_ANNOUNCE_REJECTED") from exc
        return MaskChildViewV1(declaration=declaration, manifest=None)

    @router.get(
        "/v3/sites/{site_id}/work-areas/{work_area_id}/mask-children/{mask_child_id}",
        response_model=MaskChildViewV1,
    )
    def read_child(
        site_id: str,
        work_area_id: str,
        mask_child_id: str,
        principal: Principal = Depends(read),  # noqa: B008
    ) -> MaskChildViewV1:
        require_operator(principal)
        require_operator_scope(principal, site_id, work_area_id)
        try:
            record = ingress.get(
                organization_id=principal.organization_id,
                mask_child_id=mask_child_id,
                principal=principal,
                now=now(),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="MASK_SCOPE_DENIED") from exc
        if (
            record is None
            or record.declaration.site_id != site_id
            or record.declaration.work_area_id != work_area_id
        ):
            raise HTTPException(status_code=404, detail="MASK_CHILD_NOT_FOUND")
        return MaskChildViewV1(
            declaration=record.declaration,
            manifest=record.manifest,
        )

    @router.get(
        "/v3/sites/{site_id}/work-areas/{work_area_id}/mask-children/{mask_child_id}/inspection-status",
        response_model=MaskInspectionStatusViewV1,
    )
    def read_inspection_status(
        site_id: str,
        work_area_id: str,
        mask_child_id: str,
        principal: Principal = Depends(read),  # noqa: B008
    ) -> MaskInspectionStatusViewV1:
        """Human-readable inspection state; a terminal failure names its reason.

        Derived only: a sealed manifest wins, then a terminal worker failure,
        then a live fence, otherwise the bare announcement.  Read-only.
        """
        require_operator(principal)
        require_operator_scope(principal, site_id, work_area_id)
        checked_at = now()
        try:
            record = ingress.get(
                organization_id=principal.organization_id,
                mask_child_id=mask_child_id,
                principal=principal,
                now=checked_at,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="MASK_SCOPE_DENIED") from exc
        if (
            record is None
            or record.declaration.site_id != site_id
            or record.declaration.work_area_id != work_area_id
        ):
            raise HTTPException(status_code=404, detail="MASK_CHILD_NOT_FOUND")
        if record.manifest is not None:
            return MaskInspectionStatusViewV1(
                mask_child_id=mask_child_id,
                site_id=site_id,
                work_area_id=work_area_id,
                status="COMPLETED",
                reason_code=None,
                checked_at=checked_at,
                manifest_digest=record.manifest.manifest_digest,
            )
        failure = fence.get_failure(
            organization_id=principal.organization_id, mask_child_id=mask_child_id
        )
        if failure is not None:
            return MaskInspectionStatusViewV1(
                mask_child_id=mask_child_id,
                site_id=site_id,
                work_area_id=work_area_id,
                status=inspection_failure_status_for(failure.reason_code),
                reason_code=failure.reason_code,  # type: ignore[arg-type]
                checked_at=checked_at,
                manifest_digest=None,
            )
        if fence.is_job_running(
            organization_id=principal.organization_id,
            mask_child_id=mask_child_id,
            now=checked_at,
        ):
            status = "RUNNING"
        else:
            status = "PENDING"
        return MaskInspectionStatusViewV1(
            mask_child_id=mask_child_id,
            site_id=site_id,
            work_area_id=work_area_id,
            status=status,  # type: ignore[arg-type]
            reason_code=None,
            checked_at=checked_at,
            manifest_digest=None,
        )

    @router.get(
        "/v3/sites/{site_id}/work-areas/{work_area_id}/mask-source-context",
        response_model=MaskSourceContextViewV1,
    )
    def read_source_context(
        site_id: str,
        work_area_id: str,
        source_calculation_identity_digest: str = Query(
            min_length=71, max_length=71, pattern="^sha256:[0-9a-f]{64}$"
        ),
        principal: Principal = Depends(read),  # noqa: B008
    ) -> MaskSourceContextViewV1:
        """Resolve Core-owned declaration anchor for one sealed AP source.

        Read-only: returns sealed source copies plus the explicit lane caps.
        Creates no admission, requires no V2 numeric report, and invents no
        grid.  The Console builds only opaque ids plus hash/size from this;
        Core rechecks everything at declare/seal/bind time.
        """
        require_operator(principal)
        require_operator_scope(principal, site_id, work_area_id)
        try:
            view = lane_source.resolve_source_context(
                organization_id=principal.organization_id,
                site_id=site_id,
                work_area_id=work_area_id,
                source_calculation_identity_digest=source_calculation_identity_digest,
                now=now(),
            )
        except MaskSourceNotAdmitted as exc:
            raise HTTPException(status_code=409, detail=str(exc.reason)) from exc
        if view is None:
            raise HTTPException(status_code=404, detail="MASK_SOURCE_CONTEXT_NOT_FOUND")
        return view

    @router.get(
        "/v1/internal/mask-inspection-jobs/pending",
        response_model=MaskInspectionPendingListV1,
    )
    def pending_inspections(
        limit: int = Query(default=50, ge=1, le=50),
        principal: Principal = Depends(work),  # noqa: B008
    ) -> MaskInspectionPendingListV1:
        """Bounded worker-only discovery of announced, unsealed mask children.

        Lists only children with sealed bytes and no sealed manifest yet, for
        the designated worker's organization, while the lane activation is
        current.  No owner store is widened: announcements come from this
        API's own journal, manifests and byte proofs from public Core reads.
        """
        require_designated_worker(principal)
        if not lane_source.activation_current(now=now()):
            raise HTTPException(status_code=503, detail="MASKED_ACTIVATION_UNAVAILABLE")
        items: list[MaskInspectionPendingItemV1] = []
        for announced in fence.list_announced(organization_id=principal.organization_id):
            if len(items) >= limit:
                break
            # Narrow worker grants filter discovery the same way operator
            # allowlists do; the pin is worker-kind so the check is inline.
            if (
                principal.allowed_site_ids is not None
                and announced.site_id not in principal.allowed_site_ids
            ):
                continue
            if (
                principal.allowed_work_area_ids is not None
                and announced.work_area_id not in principal.allowed_work_area_ids
            ):
                continue
            declaration = announced.declaration
            manifest = ingress.resolve_manifest_by_child(
                organization_id=principal.organization_id,
                mask_child_id=announced.mask_child_id,
            )
            if manifest is not None:
                continue
            if (
                fence.get_failure(
                    organization_id=principal.organization_id,
                    mask_child_id=announced.mask_child_id,
                )
                is not None
            ):
                # Terminal worker failure: excluded from discovery, never
                # revived.  The Console surfaces it via inspection-status and
                # the user declares a fresh child with a fixed file.
                continue
            try:
                byte_store.fetch_proof(
                    organization_id=principal.organization_id,
                    site_id=announced.site_id,
                    subject_digest=declaration.parent_subject.canonical_digest(),
                    mask_child_id=announced.mask_child_id,
                    mask_artifact_id=declaration.mask_artifact_id,
                )
            except ValueError:
                continue
            items.append(
                MaskInspectionPendingItemV1(
                    mask_child_id=announced.mask_child_id,
                    site_id=announced.site_id,
                    work_area_id=announced.work_area_id,
                    declaration=declaration,
                )
            )
        return MaskInspectionPendingListV1(items=tuple(items))

    @router.post(
        "/v3/sites/{site_id}/work-areas/{work_area_id}/mask-children/{mask_child_id}/upload-grants",
        response_model=MaskUploadGrantViewV1,
        openapi_extra=_json_body(MaskUploadGrantRequestV1),
    )
    async def issue_grant(
        site_id: str,
        work_area_id: str,
        mask_child_id: str,
        request: Request,
        principal: Principal = Depends(write),  # noqa: B008
    ) -> MaskUploadGrantViewV1:
        require_operator(principal)
        require_operator_scope(principal, site_id, work_area_id)
        body = await _bounded_json(request, MaskUploadGrantRequestV1)
        try:
            record = ingress.get(
                organization_id=principal.organization_id,
                mask_child_id=mask_child_id,
                principal=principal,
                now=now(),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="MASK_SCOPE_DENIED") from exc
        if (
            record is None
            or record.declaration.site_id != site_id
            or record.declaration.work_area_id != work_area_id
        ):
            raise HTTPException(status_code=404, detail="MASK_CHILD_NOT_FOUND")
        declaration = record.declaration
        if (
            body.mask_artifact_id != declaration.mask_artifact_id
            or body.subject_digest != declaration.parent_subject.canonical_digest()
            or body.declared_sha256 != declaration.declared_sha256
            or body.declared_size_bytes != declaration.declared_size_bytes
        ):
            raise HTTPException(status_code=409, detail="MASK_GRANT_BINDING_MISMATCH")
        try:
            grant = await run_in_threadpool(
                byte_store.issue_grant,
                principal=principal,
                organization_id=declaration.organization_id,
                site_id=declaration.site_id,
                work_area_id=declaration.work_area_id,
                mask_child_id=declaration.mask_child_id,
                mask_artifact_id=declaration.mask_artifact_id,
                subject_digest=declaration.parent_subject.canonical_digest(),
                declared_sha256=declaration.declared_sha256,
                declared_size_bytes=declaration.declared_size_bytes,
                now=now(),
                ttl_seconds=body.ttl_seconds,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="MASK_SCOPE_DENIED") from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail="MASK_GRANT_UNAVAILABLE") from exc
        return MaskUploadGrantViewV1(
            grant_id=grant.grant_id,
            mask_child_id=grant.mask_child_id,
            mask_artifact_id=grant.mask_artifact_id,
            expires_at=grant.expires_at,
        )

    @router.post(
        "/v3/sites/{site_id}/work-areas/{work_area_id}/mask-children/{mask_child_id}/upload-grants/{grant_id}/bytes",
        response_model=MaskUploadSealViewV1,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
                },
            }
        },
    )
    async def upload_bytes(
        site_id: str,
        work_area_id: str,
        mask_child_id: str,
        grant_id: str,
        request: Request,
        principal: Principal = Depends(write),  # noqa: B008
    ) -> MaskUploadSealViewV1:
        require_operator(principal)
        require_operator_scope(principal, site_id, work_area_id)
        grant = _lookup_grant(byte_store, grant_id)
        if (
            grant is None
            or grant.organization_id != principal.organization_id
            or grant.site_id != site_id
            or grant.work_area_id != work_area_id
            or grant.mask_child_id != mask_child_id
        ):
            raise HTTPException(status_code=404, detail="MASK_UPLOAD_GRANT_NOT_FOUND")
        if request.headers.get("content-type") != "application/octet-stream":
            raise HTTPException(status_code=415, detail="MASK_RAW_BYTES_REQUIRED")
        # Raw bounded streaming avoids an unbounded multipart spool occurring
        # before the grant/scope check.  Core never decodes mask bytes here.
        with tempfile.TemporaryFile(mode="w+b") as stream:
            total = 0
            try:
                async with asyncio.timeout(30):
                    async for chunk in request.stream():
                        total += len(chunk)
                        if total > byte_cap():
                            raise HTTPException(status_code=413, detail="MASK_UPLOAD_TOO_LARGE")
                        await run_in_threadpool(stream.write, chunk)
            except TimeoutError as exc:
                raise HTTPException(status_code=408, detail="MASK_UPLOAD_TIMED_OUT") from exc
            stream.seek(0)
            payload = await run_in_threadpool(stream.read)
        try:
            observed = await run_in_threadpool(
                byte_store.complete_upload,
                grant_id=grant_id,
                data=payload,
                principal=principal,
                now=now(),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="MASK_SCOPE_DENIED") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="MASK_UPLOAD_REJECTED") from exc
        return MaskUploadSealViewV1(
            mask_child_id=mask_child_id,
            mask_artifact_id=grant.mask_artifact_id,
            observed_sha256=observed[0],
            observed_size_bytes=observed[1],
        )

    @router.post(
        "/v1/internal/mask-children/{mask_child_id}/inspection-lease",
        response_model=MaskInspectionLeaseViewV1,
        openapi_extra=_json_body(MaskInspectionLeaseRequestV1),
    )
    async def lease_inspection(
        mask_child_id: str,
        request: Request,
        principal: Principal = Depends(work),  # noqa: B008
    ) -> MaskInspectionLeaseViewV1:
        require_designated_worker(principal)
        body = await _bounded_json(request, MaskInspectionLeaseRequestV1)
        checked_at = now()
        try:
            byte_store.fetch_proof(
                organization_id=principal.organization_id,
                site_id=body.site_id,
                subject_digest=body.subject_digest,
                mask_child_id=mask_child_id,
                mask_artifact_id=body.mask_artifact_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="MASK_SEALED_BYTES_NOT_FOUND") from exc
        anchor = ingress.resolve_baseline_anchor(
            organization_id=principal.organization_id,
            site_id=body.site_id,
            work_area_id=body.work_area_id,
            baseline_subject=body.baseline_subject,
            dsm_artifact_id=body.baseline_dsm_artifact_id,
        )
        if (
            anchor is None
            or anchor.baseline_subject_digest != body.baseline_subject.canonical_digest()
            or anchor.dsm_artifact_id != body.baseline_dsm_artifact_id
        ):
            raise HTTPException(status_code=404, detail="MASK_BASELINE_ANCHOR_NOT_FOUND")
        try:
            lease = fence.issue_lease(
                organization_id=principal.organization_id,
                site_id=body.site_id,
                work_area_id=body.work_area_id,
                mask_child_id=mask_child_id,
                mask_artifact_id=body.mask_artifact_id,
                subject_digest=body.subject_digest,
                baseline_subject_digest=body.baseline_subject.canonical_digest(),
                baseline_dsm_artifact_id=body.baseline_dsm_artifact_id,
                inspection_profile_digest=body.inspection_profile_digest,
                worker_principal_id=principal.principal_id,
                worker_instance_id=body.worker_instance_id,
                lease_acquisition_id=body.lease_acquisition_id,
                now=checked_at,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="MASK_INSPECTION_FENCE_REJECTED") from exc
        return MaskInspectionLeaseViewV1(
            lease_id=lease.lease_id,
            mask_child_id=mask_child_id,
            worker_instance_id=lease.worker_instance_id,
            lease_acquisition_id=lease.lease_acquisition_id,
            issued_at=lease.issued_at,
            expires_at=lease.expires_at,
            expected_rows=anchor.rows,
            expected_columns=anchor.columns,
            expected_transform=anchor.transform,
            expected_transform_digest=anchor.transform_digest,
            expected_crs_identifier=anchor.crs_identifier,
            expected_crs_digest=anchor.crs_digest,
        )

    @router.get(
        "/v1/internal/mask-children/{mask_child_id}/bytes",
        response_model=MaskedBytesSliceViewV1,
    )
    def read_inspection_bytes(
        mask_child_id: str,
        mask_artifact_id: str = Query(min_length=1, max_length=128),
        offset: int = Query(ge=0),
        length: int = Query(gt=0, le=_MAX_SLICE),
        lease_id: str | None = Query(default=None, min_length=1, max_length=128),
        worker_instance_id: str | None = Query(default=None, min_length=1, max_length=255),
        principal: Principal = Depends(work),  # noqa: B008
    ) -> MaskedBytesSliceViewV1:
        require_designated_worker(principal)
        if not lease_id or not worker_instance_id:
            raise HTTPException(status_code=409, detail="MASK_INSPECTION_FENCE_REQUIRED")
        # The fence binds the lease id, worker, and child.  The profile
        # digest is never taken from the caller here: sealed bytes are not
        # authority, and the later seal re-binds the exact live lease plus
        # the profile activation.  A missing or stale lease fails closed
        # without revealing which field mismatched.
        live = fence.resolve_live_lease(
            organization_id=principal.organization_id,
            mask_child_id=mask_child_id,
            lease_id=lease_id,
            worker_principal_id=principal.principal_id,
            worker_instance_id=worker_instance_id,
            now=now(),
        )
        if live is None or live.mask_artifact_id != mask_artifact_id:
            raise HTTPException(status_code=404, detail="MASK_INSPECTION_JOB_NOT_FOUND")
        try:
            window = read_sealed_mask_slice(
                byte_store,
                organization_id=live.organization_id,
                site_id=live.site_id,
                mask_child_id=live.mask_child_id,
                mask_artifact_id=live.mask_artifact_id,
                subject_digest=live.subject_digest,
                offset=offset,
                length=length,
                cap_bytes=byte_cap(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="MASK_SEALED_BYTES_NOT_FOUND") from exc
        # Final fresh fence guard: no window leaves Core on an expired lease.
        # The bytes themselves stay genuine sealed state either way.
        if (
            fence.resolve_live_lease(
                organization_id=principal.organization_id,
                mask_child_id=mask_child_id,
                lease_id=lease_id,
                worker_principal_id=principal.principal_id,
                worker_instance_id=worker_instance_id,
                now=now(),
            )
            is None
        ):
            raise HTTPException(status_code=409, detail="MASK_INSPECTION_FENCE_REJECTED")
        import base64 as _base64

        return MaskedBytesSliceViewV1(
            artifact_id=live.mask_artifact_id,
            offset=offset,
            content_base64=_base64.b64encode(window).decode("ascii"),
        )

    @router.post(
        "/v1/internal/mask-children/{mask_child_id}:report",
        response_model=MaskSealViewV1,
        openapi_extra=_json_body(MaskInspectionReportRequestV1),
    )
    async def seal_report(
        mask_child_id: str,
        request: Request,
        principal: Principal = Depends(work),  # noqa: B008
    ) -> MaskSealViewV1:
        require_designated_worker(principal)
        # A terminal worker failure closes the child for good before any body
        # parsing: even a valid report can no longer seal it (no revival
        # through this seam, regardless of request shape).
        if (
            fence.get_failure(
                organization_id=principal.organization_id, mask_child_id=mask_child_id
            )
            is not None
        ):
            raise HTTPException(status_code=409, detail="MASK_SEAL_REJECTED")
        body = await _bounded_json(request, MaskInspectionReportRequestV1)
        checked_at = now()
        report = MaskObservationReportV1.model_validate(body.report.model_dump(by_alias=True))
        profile = MaskInspectionProfileV1.model_validate(
            body.inspection_profile.model_dump(by_alias=True)
        )
        if profile.canonical_digest() != report.inspection_profile_digest:
            raise HTTPException(status_code=409, detail="MASK_REPORT_FENCE_REJECTED")
        # Idempotent replay of an already-sealed success: the sealed manifest
        # binds the exact report digest, so returning the existing receipt
        # claims no new run and needs no live fence.  Anything else on a
        # sealed child fails closed below (the store rejects a divergent
        # report, and a fresh lease plus an old report never counts as a run).
        existing_manifest = ingress.resolve_manifest_by_child(
            organization_id=principal.organization_id,
            mask_child_id=mask_child_id,
        )
        if existing_manifest is not None:
            if (
                existing_manifest.observed_inspection_report_digest != report.canonical_digest()
                or existing_manifest.inspection_profile_digest != profile.canonical_digest()
                or report.mask_child_id != mask_child_id
                or report.mask_artifact_id != existing_manifest.mask_artifact_id
                or report.organization_id != existing_manifest.organization_id
                or report.site_id != existing_manifest.site_id
                or report.work_area_id != existing_manifest.work_area_id
                or report.subject_digest != existing_manifest.parent_subject_digest
                or report.observed_size_bytes > byte_cap()
            ):
                raise HTTPException(status_code=409, detail="MASK_REPORT_FENCE_REJECTED")
            return MaskSealViewV1(manifest=existing_manifest)
        live = fence.resolve_live_lease(
            organization_id=principal.organization_id,
            mask_child_id=mask_child_id,
            lease_id=body.lease_id,
            worker_principal_id=principal.principal_id,
            worker_instance_id=body.worker_instance_id,
            now=checked_at,
        )
        if (
            live is None
            or live.inspection_profile_digest != profile.canonical_digest()
            or report.mask_child_id != mask_child_id
            or report.mask_artifact_id != live.mask_artifact_id
            or report.organization_id != live.organization_id
            or report.site_id != live.site_id
            or report.work_area_id != live.work_area_id
            or report.subject_digest != live.subject_digest
            or report.observed_size_bytes > byte_cap()
            or not (live.issued_at <= report.reported_at <= checked_at)
        ):
            raise HTTPException(status_code=409, detail="MASK_REPORT_FENCE_REJECTED")
        # Final fresh fence guard with its own clock reading: the seal below
        # must never borrow an expired lease, even by milliseconds.
        final_at = now()
        if (
            fence.resolve_live_lease(
                organization_id=principal.organization_id,
                mask_child_id=mask_child_id,
                lease_id=body.lease_id,
                worker_principal_id=principal.principal_id,
                worker_instance_id=body.worker_instance_id,
                now=final_at,
            )
            is None
        ):
            raise HTTPException(status_code=409, detail="MASK_REPORT_FENCE_REJECTED")
        try:
            manifest = await run_in_threadpool(
                ingress.seal_observed,
                principal=principal,
                organization_id=principal.organization_id,
                mask_child_id=mask_child_id,
                report=report,
                inspection_profile=profile,
                now=final_at,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="MASK_SEAL_DENIED") from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail="MASK_SEAL_REJECTED") from exc
        return MaskSealViewV1(manifest=manifest)

    @router.post(
        "/v1/internal/mask-children/{mask_child_id}:inspection-failure",
        response_model=MaskInspectionFailureViewV1,
        openapi_extra=_json_body(MaskInspectionFailureRequestV1),
    )
    async def fail_inspection(
        mask_child_id: str,
        request: Request,
        principal: Principal = Depends(work),  # noqa: B008
    ) -> MaskInspectionFailureViewV1:
        """Record one terminal worker-observed inspection failure.

        The worker POSTs the same closed body it derives from caught
        primitive errors (NoData/non-binary/wrong-grid/resource/IO): the
        exact live lease plus one closed reason code, never a native trace
        or raw path.  Humans cannot POST failures (403); stale leases,
        foreign children, and mismatched profiles fail closed (409).
        """
        require_designated_worker(principal)
        body = await _bounded_json(request, MaskInspectionFailureRequestV1)
        checked_at = now()
        live = fence.resolve_live_lease(
            organization_id=principal.organization_id,
            mask_child_id=mask_child_id,
            lease_id=body.lease_id,
            worker_principal_id=principal.principal_id,
            worker_instance_id=body.worker_instance_id,
            now=checked_at,
        )
        if live is None or live.inspection_profile_digest != body.inspection_profile_digest:
            raise HTTPException(status_code=409, detail="MASK_REPORT_FENCE_REJECTED")
        # A sealed manifest already closed this child: a failure can neither
        # revive nor overwrite it.
        if (
            ingress.resolve_manifest_by_child(
                organization_id=principal.organization_id,
                mask_child_id=mask_child_id,
            )
            is not None
        ):
            raise HTTPException(status_code=409, detail="MASK_INSPECTION_FAILURE_REJECTED")
        final_at = now()
        if (
            fence.resolve_live_lease(
                organization_id=principal.organization_id,
                mask_child_id=mask_child_id,
                lease_id=body.lease_id,
                worker_principal_id=principal.principal_id,
                worker_instance_id=body.worker_instance_id,
                now=final_at,
            )
            is None
        ):
            raise HTTPException(status_code=409, detail="MASK_REPORT_FENCE_REJECTED")
        try:
            failure = await run_in_threadpool(
                fence.record_failure,
                organization_id=principal.organization_id,
                mask_child_id=mask_child_id,
                lease_id=body.lease_id,
                worker_principal_id=principal.principal_id,
                worker_instance_id=body.worker_instance_id,
                inspection_profile_digest=body.inspection_profile_digest,
                reason_code=body.reason_code,
                now=final_at,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail="MASK_INSPECTION_FAILURE_REJECTED") from exc
        return MaskInspectionFailureViewV1(
            mask_child_id=failure.mask_child_id,
            status=inspection_failure_status_for(failure.reason_code),
            reason_code=failure.reason_code,  # type: ignore[arg-type]
            failed_at=failure.failed_at,
        )

    return router


__all__ = [
    "MaskAnnouncedChild",
    "MaskInspectionFailure",
    "MaskInspectionJobLedger",
    "MaskInspectionJobRecoveryError",
    "MaskInspectionLease",
    "MaskedLaneSourcePort",
    "build_external_mask_input_router",
    "operator_scope_allows",
    "read_sealed_mask_slice",
]
