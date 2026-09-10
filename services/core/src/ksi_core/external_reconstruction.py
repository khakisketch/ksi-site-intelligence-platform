"""Durable ingress for customer-owned reconstruction exports (ADR-KSI-036).

This is deliberately a byte-declaration journal.  It does not create a
ProcessingJob, source-media authority, profile, accuracy claim, or flight output.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
from ksi_event_contracts.external_reconstruction import (
    ExternalReconstructionManifestEntryV1,
    ExternalReconstructionManifestV1,
    ExternalReconstructionSubmissionV1,
    external_reconstruction_manifest_wire_dict,
    external_reconstruction_submission_wire_dict,
)
from ksi_event_contracts.external_reobservation import ExternalPlanningOnlyWorkOrderBindingV1
from ksi_event_contracts.observation_work_order import (
    ObservationWorkOrder,
    ObservationWorkOrderExecutionMode,
)
from pydantic import Field

from ksi_core.acquisition import observation_epoch_id
from ksi_core.api_base import CamelModel, iso_utc
from ksi_core.auth import Permission, Principal, PrincipalKind, require_permission
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.evidence import (
    ALLOWED_CONTENT_TYPES,
    DEFAULT_UPLOAD_TTL,
    DigestBoundEvidenceStorage,
    EvidenceStorageError,
    ObjectStorageObservationPort,
)
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_result_projection_models import (
    ExternalResultProjectionState,
    ExternalResultProjectionView,
)
from ksi_core.observation_work_orders import ObservationWorkOrderStore

if TYPE_CHECKING:
    from ksi_core.external_result_workflow_api import ExternalResultReadProjector

_EVENT_VERSION = 1
_NOT_FOUND = "EXTERNAL_RECONSTRUCTION_NOT_FOUND"
_SUBMISSION_REF_VERSION = "external-reconstruction-submission-ref.v1"
_SUBMISSION_REF_PATTERN = r"ers-v1-[0-9a-f]{64}"


class ExternalReconstructionRecoveryError(RuntimeError):
    """The external-result journal cannot safely be used after failed replay."""


class ExternalReconstructionVerdict(StrEnum):
    REGISTERED = "REGISTERED"
    CONFLICT = "CONFLICT"
    NOT_FOUND = "NOT_FOUND"
    BAD_DECLARATION = "BAD_DECLARATION"
    SUPERSEDED = "SUPERSEDED"
    SEALED = "SEALED"
    OBSERVATION_MISSING = "OBSERVATION_MISSING"
    OBSERVATION_MISMATCH = "OBSERVATION_MISMATCH"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ExternalReconstructionRevision:
    """One immutable submission revision and its server-owned byte binding."""

    work_order_id: str
    work_order_version: int
    cycle_number: int
    observation_epoch_id: str
    submission: ExternalReconstructionSubmissionV1
    registered_at: datetime
    registered_by: str
    bindings: tuple[tuple[str, str], ...]
    manifest: ExternalReconstructionManifestV1 | None = None


@dataclass(frozen=True, slots=True)
class ExternalReconstructionResult:
    verdict: ExternalReconstructionVerdict
    revision: ExternalReconstructionRevision | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class UploadGrant:
    artifact_id: str
    object_key: str
    upload_url: str
    required_headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class UploadGrantResult:
    verdict: ExternalReconstructionVerdict
    grants: tuple[UploadGrant, ...] = ()
    revision: ExternalReconstructionRevision | None = None
    detail: str | None = None


def _event_digest(payload: dict[str, Any]) -> str:
    candidate = dict(payload)
    candidate.pop("eventDigest", None)
    return "sha256:" + hashlib.sha256(canonical_json_bytes(candidate)).hexdigest()


def _parse_time(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an RFC3339 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def build_external_reconstruction_object_key(
    *,
    organization_id: str,
    site_id: str,
    work_order_id: str,
    cycle_number: int,
    observation_epoch_id: str,
    submission_id: str,
    revision: int,
    artifact_id: str,
) -> str:
    """Derive a safe key from the complete scope without embedding client identifiers."""
    scope = {
        "version": "external-reconstruction-key.v1",
        "organizationId": organization_id,
        "siteId": site_id,
        "workOrderId": work_order_id,
        "cycleNumber": cycle_number,
        "observationEpochId": observation_epoch_id,
        "submissionId": submission_id,
        "revision": revision,
        "artifactId": artifact_id,
    }
    return "external-reconstruction/v1/" + hashlib.sha256(canonical_json_bytes(scope)).hexdigest()


def build_external_reconstruction_submission_ref(
    *,
    organization_id: str,
    work_order_id: str,
    submission_id: str,
) -> str:
    """Build the v1 opaque public address without changing durable raw identifiers."""
    scope = {
        "version": _SUBMISSION_REF_VERSION,
        "organizationId": organization_id,
        "workOrderId": work_order_id,
        "submissionId": submission_id,
    }
    return "ers-v1-" + hashlib.sha256(canonical_json_bytes(scope)).hexdigest()


def _derived_epoch_id(*, organization_id: str, work_order_id: str, cycle_number: int) -> str:
    raw = f"{organization_id}\0{work_order_id}\0{cycle_number}".encode()
    return "obs-epoch-" + hashlib.sha256(raw).hexdigest()[:24]


class ExternalReconstructionStore:
    """Journal-backed external declaration state machine with strict replay."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        self._journal = journal
        self._coordinator = coordinator or ExternalAuthorityCurrentnessCoordinator()
        self._streams: dict[tuple[str, str], list[ExternalReconstructionRevision]] = {}
        self._submission_ids_by_ref: dict[tuple[str, str], str] = {}
        self._seal_listeners: list[
            Callable[[ExternalReconstructionRevision, datetime], object]
        ] = []
        self._lock = threading.RLock()
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException as exc:
            journal.close()
            if isinstance(exc, ExternalReconstructionRecoveryError):
                raise
            raise ExternalReconstructionRecoveryError(
                f"external reconstruction replay failed: {exc}"
            ) from exc

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def bind_seal_listener(
        self, listener: Callable[[ExternalReconstructionRevision, datetime], object]
    ) -> None:
        """Bind additive post-commit work without granting it ingress authority.

        A listener runs only after the seal event has fsync'd and been projected,
        and always after releasing the ingress lock. Its failure therefore cannot
        rewrite, reject, or relabel the durable ingress seal.
        """
        with self._lock:
            self._seal_listeners.append(listener)

    def sealed_revisions_snapshot(self) -> tuple[ExternalReconstructionRevision, ...]:
        """Read-only immutable snapshot used by additive reconciliation stores."""
        with self._lock:
            return tuple(
                revision
                for stream in self._streams.values()
                for revision in stream
                if revision.manifest is not None
            )

    def resolve_sealed_subject(
        self, subject: SealedExternalSubjectV1
    ) -> ExternalReconstructionRevision | None:
        """Core-only exact sealed-subject resolution for derived validation work."""
        with self._lock:
            revisions = self._streams.get((subject.work_order_id, subject.submission_id), ())
            for revision in revisions:
                submission, manifest = revision.submission, revision.manifest
                if (
                    submission.organization_id == subject.organization_id
                    and submission.site_id == subject.site_id
                    and submission.revision == subject.revision
                    and submission.submission_digest == subject.submission_digest
                    and manifest is not None
                    and manifest.manifest_digest == subject.manifest_digest
                ):
                    return revision
        return None

    def _require_exact_fields(self, raw: dict[str, Any], expected: set[str]) -> None:
        if set(raw) != expected:
            raise ValueError("event fields are not exact")
        if raw.get("eventDigest") != _event_digest(raw):
            raise ValueError("event digest mismatch")
        if type(raw.get("version")) is not int or raw["version"] != _EVENT_VERSION:
            raise ValueError("unknown event version")

    def _registration_from_event(self, raw: dict[str, Any]) -> ExternalReconstructionRevision:
        self._require_exact_fields(
            raw,
            {
                "kind",
                "version",
                "eventDigest",
                "registeredAt",
                "registeredBy",
                "workOrderId",
                "workOrderVersion",
                "cycleNumber",
                "observationEpochId",
                "submission",
                "bindings",
            },
        )
        if raw["kind"] != "external-reconstruction-registered":
            raise ValueError("wrong registration event kind")
        submission = ExternalReconstructionSubmissionV1.model_validate(raw["submission"])
        if submission.submission_digest is None:
            raise ValueError("unsealed submission")
        if any(
            artifact.content_type not in ALLOWED_CONTENT_TYPES for artifact in submission.artifacts
        ):
            raise ValueError("unsupported artifact content type")
        work_order_id = raw["workOrderId"]
        work_order_version = raw["workOrderVersion"]
        cycle_number = raw["cycleNumber"]
        epoch = raw["observationEpochId"]
        actor = raw["registeredBy"]
        if not all(isinstance(item, str) and item for item in (work_order_id, epoch, actor)):
            raise ValueError("invalid registration scalar")
        if type(work_order_version) is not int or work_order_version < 1:
            raise ValueError("invalid workOrderVersion")
        if type(cycle_number) is not int or cycle_number < 1:
            raise ValueError("invalid cycleNumber")
        if (
            submission.observation_epoch_id != epoch
            or epoch
            != _derived_epoch_id(
                organization_id=submission.organization_id,
                work_order_id=work_order_id,
                cycle_number=cycle_number,
            )
            or submission.submitted_by != actor
        ):
            raise ValueError("submission scope mismatch")
        bindings_payload = raw["bindings"]
        if not isinstance(bindings_payload, list):
            raise ValueError("bindings must be an array")
        bindings: list[tuple[str, str]] = []
        declared = {artifact.artifact_id for artifact in submission.artifacts}
        for item in bindings_payload:
            if not isinstance(item, dict) or set(item) != {"artifactId", "objectKey"}:
                raise ValueError("invalid binding")
            artifact_id, key = item["artifactId"], item["objectKey"]
            if not isinstance(artifact_id, str) or not isinstance(key, str):
                raise ValueError("invalid binding values")
            expected_key = build_external_reconstruction_object_key(
                organization_id=submission.organization_id,
                site_id=submission.site_id,
                work_order_id=work_order_id,
                cycle_number=cycle_number,
                observation_epoch_id=epoch,
                submission_id=submission.submission_id,
                revision=submission.revision,
                artifact_id=artifact_id,
            )
            if key != expected_key:
                raise ValueError("binding key mismatch")
            bindings.append((artifact_id, key))
        if {item[0] for item in bindings} != declared or len(bindings) != len(declared):
            raise ValueError("bindings do not exactly match artifacts")
        return ExternalReconstructionRevision(
            work_order_id=work_order_id,
            work_order_version=work_order_version,
            cycle_number=cycle_number,
            observation_epoch_id=epoch,
            submission=submission,
            registered_at=_parse_time(raw["registeredAt"], field="registeredAt"),
            registered_by=actor,
            bindings=tuple(sorted(bindings)),
        )

    def _apply_registration(self, raw: dict[str, Any]) -> None:
        record = self._registration_from_event(raw)
        submission_ref = build_external_reconstruction_submission_ref(
            organization_id=record.submission.organization_id,
            work_order_id=record.work_order_id,
            submission_id=record.submission.submission_id,
        )
        ref_key = (record.work_order_id, submission_ref)
        existing_raw_id = self._submission_ids_by_ref.get(ref_key)
        if existing_raw_id is not None and existing_raw_id != record.submission.submission_id:
            raise ValueError("submissionRef collision")
        key = (record.work_order_id, record.submission.submission_id)
        stream = self._streams.setdefault(key, [])
        if stream:
            first = stream[0]
            if (
                record.submission.revision != len(stream) + 1
                or record.submission.organization_id != first.submission.organization_id
                or record.submission.site_id != first.submission.site_id
                or record.work_order_version != first.work_order_version
                or record.cycle_number != first.cycle_number
                or record.observation_epoch_id != first.observation_epoch_id
            ):
                raise ValueError("illegal revision stream")
        elif record.submission.revision != 1:
            raise ValueError("first revision must be one")
        stream.append(record)
        self._submission_ids_by_ref[ref_key] = record.submission.submission_id

    def _apply_seal(self, raw: dict[str, Any]) -> None:
        self._require_exact_fields(
            raw,
            {
                "kind",
                "version",
                "eventDigest",
                "observedAt",
                "observedBy",
                "workOrderId",
                "submissionId",
                "revision",
                "manifest",
            },
        )
        if raw["kind"] != "external-reconstruction-sealed":
            raise ValueError("wrong seal event kind")
        work_order_id, submission_id, revision = (
            raw["workOrderId"],
            raw["submissionId"],
            raw["revision"],
        )
        if (
            not isinstance(work_order_id, str)
            or not isinstance(submission_id, str)
            or type(revision) is not int
        ):
            raise ValueError("invalid seal scope")
        stream = self._streams.get((work_order_id, submission_id))
        if stream is None or revision < 1 or revision > len(stream):
            raise ValueError("seal before registration")
        current = stream[revision - 1]
        if current.manifest is not None:
            raise ValueError("duplicate seal")
        if stream[-1] is not current:
            raise ValueError("cannot seal superseded revision")
        manifest = ExternalReconstructionManifestV1.model_validate(raw["manifest"])
        if manifest.manifest_digest is None:
            raise ValueError("unsealed manifest")
        if (
            manifest.submission_id != submission_id
            or manifest.submission_revision != revision
            or manifest.submission_digest != current.submission.submission_digest
            or manifest.organization_id != current.submission.organization_id
            or manifest.site_id != current.submission.site_id
            or manifest.observation_epoch_id != current.observation_epoch_id
            or manifest.observed_at != _parse_time(raw["observedAt"], field="observedAt")
            or manifest.observed_by_service != raw["observedBy"]
        ):
            raise ValueError("manifest scope mismatch")
        entries = {entry.artifact_id: entry for entry in manifest.entries}
        declared = {item.artifact_id: item for item in current.submission.artifacts}
        if set(entries) != set(declared):
            raise ValueError("manifest artifact set mismatch")
        for artifact_id, object_key in current.bindings:
            artifact, entry = declared[artifact_id], entries[artifact_id]
            if (
                entry.object_key != object_key
                or entry.kind is not artifact.kind
                or entry.observed_sha256 != artifact.declared_sha256
                or entry.observed_size_bytes != artifact.declared_size_bytes
                or entry.observed_content_type != artifact.content_type
            ):
                raise ValueError("manifest observation mismatch")
        stream[revision - 1] = replace(current, manifest=manifest)

    def _apply(self, raw: dict[str, Any]) -> None:
        try:
            if not isinstance(raw, dict) or not isinstance(raw.get("kind"), str):
                raise ValueError("unknown event")
            if raw["kind"] == "external-reconstruction-registered":
                self._apply_registration(raw)
            elif raw["kind"] == "external-reconstruction-sealed":
                self._apply_seal(raw)
            else:
                raise ValueError("unknown event")
        except (KeyError, TypeError, ValueError) as exc:
            raise ExternalReconstructionRecoveryError(
                f"external reconstruction journal replay failed: {exc}"
            ) from exc

    def _record(
        self, work_order_id: str, submission_id: str, revision: int
    ) -> ExternalReconstructionRevision | None:
        stream = self._streams.get((work_order_id, submission_id))
        if stream is None or revision < 1 or revision > len(stream):
            return None
        return stream[revision - 1]

    def register(
        self,
        submission: ExternalReconstructionSubmissionV1,
        *,
        work_order: ObservationWorkOrder,
        registered_by: str,
        now: datetime,
    ) -> ExternalReconstructionResult:
        """Durably record a valid declaration before making it visible in memory."""
        if submission.submission_digest is None:
            return ExternalReconstructionResult(ExternalReconstructionVerdict.BAD_DECLARATION)
        if submission.submitted_by != registered_by:
            return ExternalReconstructionResult(ExternalReconstructionVerdict.BAD_DECLARATION)
        if any(
            artifact.content_type not in ALLOWED_CONTENT_TYPES for artifact in submission.artifacts
        ):
            return ExternalReconstructionResult(ExternalReconstructionVerdict.BAD_DECLARATION)
        if (
            submission.organization_id != work_order.organization_id
            or submission.site_id != work_order.site_id
        ):
            return ExternalReconstructionResult(ExternalReconstructionVerdict.BAD_DECLARATION)
        with self._coordinator.mutation(), self._lock:
            stream_key = (work_order.work_order_id, submission.submission_id)
            submission_ref = build_external_reconstruction_submission_ref(
                organization_id=submission.organization_id,
                work_order_id=work_order.work_order_id,
                submission_id=submission.submission_id,
            )
            existing_raw_id = self._submission_ids_by_ref.get(
                (work_order.work_order_id, submission_ref)
            )
            if existing_raw_id is not None and existing_raw_id != submission.submission_id:
                return ExternalReconstructionResult(
                    ExternalReconstructionVerdict.STORAGE_UNAVAILABLE
                )
            stream = self._streams.get(stream_key, [])
            first = stream[0] if stream else None
            if first is not None and not self._stream_matches_trusted_scope(
                first,
                work_order=work_order,
            ):
                return ExternalReconstructionResult(ExternalReconstructionVerdict.NOT_FOUND)
            existing = self._record(
                work_order.work_order_id, submission.submission_id, submission.revision
            )
            if existing is not None:
                if existing.submission.submission_digest == submission.submission_digest:
                    return ExternalReconstructionResult(
                        ExternalReconstructionVerdict.REGISTERED, existing
                    )
                return ExternalReconstructionResult(
                    ExternalReconstructionVerdict.CONFLICT, existing
                )
            if first is None:
                epoch = observation_epoch_id(work_order)
                work_order_version = work_order.version
                cycle_number = work_order.cycle_number
                if (
                    submission.organization_id != work_order.organization_id
                    or submission.site_id != work_order.site_id
                    or submission.observation_epoch_id != epoch
                ):
                    return ExternalReconstructionResult(
                        ExternalReconstructionVerdict.BAD_DECLARATION
                    )
                if submission.revision != 1:
                    return ExternalReconstructionResult(ExternalReconstructionVerdict.CONFLICT)
            else:
                epoch = first.observation_epoch_id
                work_order_version = first.work_order_version
                cycle_number = first.cycle_number
                if (
                    submission.revision != len(stream) + 1
                    or submission.organization_id != first.submission.organization_id
                    or submission.site_id != first.submission.site_id
                    or submission.observation_epoch_id != first.observation_epoch_id
                ):
                    return ExternalReconstructionResult(ExternalReconstructionVerdict.CONFLICT)
            bindings = tuple(
                sorted(
                    (
                        artifact.artifact_id,
                        build_external_reconstruction_object_key(
                            organization_id=submission.organization_id,
                            site_id=submission.site_id,
                            work_order_id=work_order.work_order_id,
                            cycle_number=cycle_number,
                            observation_epoch_id=epoch,
                            submission_id=submission.submission_id,
                            revision=submission.revision,
                            artifact_id=artifact.artifact_id,
                        ),
                    )
                    for artifact in submission.artifacts
                )
            )
            raw: dict[str, Any] = {
                "kind": "external-reconstruction-registered",
                "version": _EVENT_VERSION,
                "registeredAt": iso_utc(now),
                "registeredBy": registered_by,
                "workOrderId": work_order.work_order_id,
                "workOrderVersion": work_order_version,
                "cycleNumber": cycle_number,
                "observationEpochId": epoch,
                "submission": external_reconstruction_submission_wire_dict(submission),
                "bindings": [
                    {"artifactId": artifact_id, "objectKey": object_key}
                    for artifact_id, object_key in bindings
                ],
            }
            raw["eventDigest"] = _event_digest(raw)
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return ExternalReconstructionResult(
                    ExternalReconstructionVerdict.STORAGE_UNAVAILABLE
                )
            self._apply(raw)
        return ExternalReconstructionResult(
            ExternalReconstructionVerdict.REGISTERED,
            self._record(
                work_order.work_order_id, submission.submission_id, submission.revision
            ),
        )

    def is_registration_retry(
        self, submission: ExternalReconstructionSubmissionV1, *, work_order: ObservationWorkOrder
    ) -> bool:
        """Retained exact registration retries are reads and remain available after close."""

        record = self.get(
            work_order.work_order_id,
            submission.submission_id,
            submission.revision,
            organization_id=work_order.organization_id,
            site_id=work_order.site_id,
        )
        return (
            record is not None
            and record.submission.submission_digest == submission.submission_digest
        )

    @staticmethod
    def _stream_matches_trusted_scope(
        first: ExternalReconstructionRevision,
        *,
        work_order: ObservationWorkOrder,
    ) -> bool:
        return (
            first.submission.organization_id == work_order.organization_id
            and first.submission.site_id == work_order.site_id
        )

    @staticmethod
    def _in_scope(
        record: ExternalReconstructionRevision | None, *, organization_id: str, site_id: str
    ) -> bool:
        return record is not None and (
            record.submission.organization_id == organization_id
            and record.submission.site_id == site_id
        )

    def get(
        self,
        work_order_id: str,
        submission_id: str,
        revision: int,
        *,
        organization_id: str,
        site_id: str,
    ) -> ExternalReconstructionRevision | None:
        with self._lock:
            record = self._record(work_order_id, submission_id, revision)
            return (
                record
                if self._in_scope(record, organization_id=organization_id, site_id=site_id)
                else None
            )

    def resolve_submission_ref(
        self,
        work_order_id: str,
        submission_ref: str,
        *,
        organization_id: str,
        site_id: str,
    ) -> str | None:
        """Resolve an opaque public address without exposing an out-of-scope raw ID."""
        if re.fullmatch(_SUBMISSION_REF_PATTERN, submission_ref) is None:
            return None
        with self._lock:
            submission_id = self._submission_ids_by_ref.get((work_order_id, submission_ref))
            if submission_id is None:
                return None
            stream = self._streams.get((work_order_id, submission_id))
            if not stream or not self._in_scope(
                stream[0], organization_id=organization_id, site_id=site_id
            ):
                return None
            return submission_id

    def list(
        self, work_order_id: str, *, organization_id: str, site_id: str
    ) -> tuple[ExternalReconstructionRevision, ...]:
        with self._lock:
            return tuple(
                revision
                for (candidate_order, _submission_id), stream in self._streams.items()
                if candidate_order == work_order_id
                for revision in stream
                if self._in_scope(revision, organization_id=organization_id, site_id=site_id)
            )

    def upload_grants(
        self,
        work_order_id: str,
        submission_id: str,
        revision: int,
        *,
        organization_id: str,
        site_id: str,
        storage: DigestBoundEvidenceStorage,
    ) -> UploadGrantResult:
        with self._coordinator.mutation(), self._lock:
            current = self._record(work_order_id, submission_id, revision)
            if not self._in_scope(current, organization_id=organization_id, site_id=site_id):
                return UploadGrantResult(ExternalReconstructionVerdict.NOT_FOUND)
            assert current is not None
            stream = self._streams[(work_order_id, submission_id)]
            if current.manifest is not None or stream[-1] is not current:
                return UploadGrantResult(ExternalReconstructionVerdict.SUPERSEDED, revision=current)
            snapshot = current
        declared = {artifact.artifact_id: artifact for artifact in snapshot.submission.artifacts}
        try:
            grants = tuple(
                UploadGrant(
                    artifact_id=artifact_id,
                    object_key=object_key,
                    upload_url=(
                        capability := storage.presigned_put_bound_digest(
                            object_key,
                            content_type=declared[artifact_id].content_type,
                            content_digest="sha256:" + declared[artifact_id].declared_sha256,
                            ttl=DEFAULT_UPLOAD_TTL,
                        )
                    ).upload_url,
                    required_headers=capability.required_headers,
                )
                for artifact_id, object_key in snapshot.bindings
            )
        except EvidenceStorageError:
            return UploadGrantResult(
                ExternalReconstructionVerdict.STORAGE_UNAVAILABLE, revision=snapshot
            )
        with self._lock:
            current = self._record(work_order_id, submission_id, revision)
            if (
                current is not snapshot
                or current.manifest is not None
                or self._streams[(work_order_id, submission_id)][-1] is not current
            ):
                return UploadGrantResult(ExternalReconstructionVerdict.SUPERSEDED, revision=current)
            return UploadGrantResult(ExternalReconstructionVerdict.REGISTERED, grants, current)

    def seal(
        self,
        work_order_id: str,
        submission_id: str,
        revision: int,
        *,
        organization_id: str,
        site_id: str,
        storage: ObjectStorageObservationPort,
        now: datetime,
    ) -> ExternalReconstructionResult:
        with self._lock:
            current = self._record(work_order_id, submission_id, revision)
            if not self._in_scope(current, organization_id=organization_id, site_id=site_id):
                return ExternalReconstructionResult(ExternalReconstructionVerdict.NOT_FOUND)
            assert current is not None
            if current.manifest is not None:
                return ExternalReconstructionResult(ExternalReconstructionVerdict.SEALED, current)
            if self._streams[(work_order_id, submission_id)][-1] is not current:
                return ExternalReconstructionResult(
                    ExternalReconstructionVerdict.SUPERSEDED, current
                )
            snapshot = current
        declared = {artifact.artifact_id: artifact for artifact in snapshot.submission.artifacts}
        entries: list[ExternalReconstructionManifestEntryV1] = []
        try:
            for artifact_id, object_key in snapshot.bindings:
                observed = storage.observe_object(object_key)
                artifact = declared[artifact_id]
                if not observed.exists:
                    return ExternalReconstructionResult(
                        ExternalReconstructionVerdict.OBSERVATION_MISSING, snapshot
                    )
                if (
                    observed.object_key != object_key
                    or observed.sha256 != "sha256:" + artifact.declared_sha256
                    or observed.size_bytes != artifact.declared_size_bytes
                    or observed.content_type != artifact.content_type
                ):
                    return ExternalReconstructionResult(
                        ExternalReconstructionVerdict.OBSERVATION_MISMATCH, snapshot
                    )
                entries.append(
                    ExternalReconstructionManifestEntryV1(
                        artifact_id=artifact_id,
                        kind=artifact.kind,
                        object_key=object_key,
                        observed_sha256=artifact.declared_sha256,
                        observed_size_bytes=artifact.declared_size_bytes,
                        observed_content_type=artifact.content_type,
                    )
                )
        except EvidenceStorageError:
            return ExternalReconstructionResult(
                ExternalReconstructionVerdict.STORAGE_UNAVAILABLE, snapshot
            )
        with self._coordinator.mutation(), self._lock:
            current = self._record(work_order_id, submission_id, revision)
            if current is not snapshot:
                if current is not None and current.manifest is not None:
                    return ExternalReconstructionResult(
                        ExternalReconstructionVerdict.SEALED,
                        current,
                    )
                return ExternalReconstructionResult(
                    ExternalReconstructionVerdict.SUPERSEDED,
                    current,
                )
            if self._streams[(work_order_id, submission_id)][-1] is not current:
                return ExternalReconstructionResult(
                    ExternalReconstructionVerdict.SUPERSEDED, current
                )
            manifest = ExternalReconstructionManifestV1.from_submission(
                current.submission,
                manifest_id="external-manifest-"
                + hashlib.sha256(
                    f"{work_order_id}:{submission_id}:{revision}".encode()
                ).hexdigest()[:32],
                observed_at=now,
                observed_by_service="ksi-core",
                organization_id=current.submission.organization_id,
                site_id=current.submission.site_id,
                observation_epoch_id=current.observation_epoch_id,
                entries=tuple(entries),
            )
            raw: dict[str, Any] = {
                "kind": "external-reconstruction-sealed",
                "version": _EVENT_VERSION,
                "observedAt": iso_utc(now),
                "observedBy": "ksi-core",
                "workOrderId": work_order_id,
                "submissionId": submission_id,
                "revision": revision,
                "manifest": external_reconstruction_manifest_wire_dict(manifest),
            }
            raw["eventDigest"] = _event_digest(raw)
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return ExternalReconstructionResult(
                    ExternalReconstructionVerdict.STORAGE_UNAVAILABLE, snapshot
                )
            self._apply(raw)
            sealed = self._record(work_order_id, submission_id, revision)
            assert sealed is not None
            listeners = tuple(self._seal_listeners)
        for listener in listeners:
            try:
                listener(sealed, now)
            except Exception:
                # Reconciliation discovers a durable seal whose post-commit
                # consumer failed. The ingress receipt itself remains factual.
                continue
        return ExternalReconstructionResult(ExternalReconstructionVerdict.SEALED, sealed)


class ExternalReconstructionContextView(CamelModel):
    """Registration identity only; grants no acquisition or analysis authority."""

    work_order_id: str = Field(min_length=1, max_length=255)
    site_id: str = Field(min_length=1, max_length=255)
    expected_epoch_id: str = Field(pattern=r"^obs-epoch-[0-9a-f]{24}$")
    cycle_number: int = Field(ge=1)
    work_order_version: int = Field(ge=1)
    execution_mode: ObservationWorkOrderExecutionMode | None = None
    external_planning_binding: ExternalPlanningOnlyWorkOrderBindingV1 | None = None
    external_result: ExternalResultProjectionView


class ExternalReconstructionRevisionView(CamelModel):
    submission_ref: str
    submission: dict[str, Any]
    state: str
    manifest: dict[str, Any] | None = None


class ExternalReconstructionListView(CamelModel):
    submissions: list[ExternalReconstructionRevisionView]


class ExternalReconstructionGrantView(CamelModel):
    artifact_id: str
    object_key: str
    upload_url: str
    required_headers: dict[str, str]


class ExternalReconstructionGrantResponse(CamelModel):
    grants: list[ExternalReconstructionGrantView]


def _view(record: ExternalReconstructionRevision) -> ExternalReconstructionRevisionView:
    return ExternalReconstructionRevisionView(
        submission_ref=build_external_reconstruction_submission_ref(
            organization_id=record.submission.organization_id,
            work_order_id=record.work_order_id,
            submission_id=record.submission.submission_id,
        ),
        submission=external_reconstruction_submission_wire_dict(record.submission),
        state="SEALED" if record.manifest is not None else "REGISTERED",
        manifest=(
            external_reconstruction_manifest_wire_dict(record.manifest) if record.manifest else None
        ),
    )


def _require_work_order(
    store: ObservationWorkOrderStore, work_order_id: str, principal: Principal
) -> ObservationWorkOrder:
    order = store.get(work_order_id, organization_id=principal.organization_id)
    if order is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return order


def _write_principal(principal: Principal) -> Principal:
    if principal.kind is not PrincipalKind.OPERATOR:
        raise HTTPException(status_code=403, detail="HUMAN_AUTHORITY_REQUIRED")
    return principal


def _result_error(result: ExternalReconstructionResult) -> None:
    status = {
        ExternalReconstructionVerdict.NOT_FOUND: 404,
        ExternalReconstructionVerdict.CONFLICT: 409,
        ExternalReconstructionVerdict.BAD_DECLARATION: 422,
        ExternalReconstructionVerdict.SUPERSEDED: 409,
        ExternalReconstructionVerdict.OBSERVATION_MISSING: 422,
        ExternalReconstructionVerdict.OBSERVATION_MISMATCH: 422,
        ExternalReconstructionVerdict.STORAGE_UNAVAILABLE: 503,
    }.get(result.verdict)
    if status is not None:
        raise HTTPException(status_code=status, detail=result.verdict.value)


def mount_external_reconstruction(
    app: FastAPI,
    store: ExternalReconstructionStore,
    *,
    work_orders: ObservationWorkOrderStore,
    storage: Any,
    external_results: ExternalResultReadProjector | None = None,
) -> None:
    """Mount the scoped external declaration surface after its dependencies are validated."""
    router = APIRouter(prefix="/v1/observation-work-orders", tags=["external-reconstruction"])
    read = require_permission(Permission.SITES_READ)
    write = require_permission(Permission.SITES_WRITE)
    base = "/{work_order_id}/external-reconstruction-submissions"

    @router.get(
        "/{work_order_id}/external-reconstruction-context",
        response_model=ExternalReconstructionContextView,
    )
    def registration_context(
        work_order_id: str,
        principal: Principal = Depends(read),  # noqa: B008
    ) -> ExternalReconstructionContextView:
        # The same immutable WorkOrder snapshot supplies all fields. Never recover
        # or create an AcquisitionRun merely to obtain the external upload epoch.
        order = _require_work_order(work_orders, work_order_id, principal)
        return ExternalReconstructionContextView(
            work_order_id=order.work_order_id,
            site_id=order.site_id,
            expected_epoch_id=observation_epoch_id(order),
            cycle_number=order.cycle_number,
            work_order_version=order.version,
            execution_mode=order.execution_mode,
            external_planning_binding=work_orders.get_external_reobservation_binding(
                order.work_order_id, organization_id=principal.organization_id
            ),
            external_result=(
                external_results.for_work_order(
                    order.work_order_id, organization_id=principal.organization_id
                )
                if external_results is not None
                else ExternalResultProjectionView(
                    state=ExternalResultProjectionState.NOT_CONFIGURED
                )
            ),
        )

    @router.post(base, response_model=ExternalReconstructionRevisionView, status_code=201)
    def register(
        work_order_id: str,
        submission: ExternalReconstructionSubmissionV1,
        principal: Principal = Depends(write),  # noqa: B008
    ) -> ExternalReconstructionRevisionView:
        order = _require_work_order(work_orders, work_order_id, principal)
        _write_principal(principal)
        capture_started_at = submission.input_declaration.capture_started_at
        capture_ended_at = submission.input_declaration.capture_ended_at
        if (
            order.execution_mode is ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION
            and work_orders.get_external_reobservation_binding(
                order.work_order_id, organization_id=principal.organization_id
            )
            is None
            and (
                capture_started_at is None
                or capture_ended_at is None
            )
        ):
            raise HTTPException(
                status_code=422,
                detail="CAPTURE_INTERVAL_REQUIRED_FOR_EXTERNAL_INGRESS",
            )
        if (
            order.execution_mode is ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION
            and work_orders.get_external_reobservation_binding(
                order.work_order_id, organization_id=principal.organization_id
            )
            is None
            and capture_started_at is not None
            and capture_ended_at is not None
            and capture_started_at >= capture_ended_at
        ):
            raise HTTPException(
                status_code=422,
                detail="CAPTURE_INTERVAL_MUST_BE_POSITIVE_FOR_EXTERNAL_INGRESS",
            )
        try:
            with work_orders.guard_new_external_intent(
                order.work_order_id,
                organization_id=principal.organization_id,
                is_durable_retry=lambda: store.is_registration_retry(
                    submission, work_order=order
                ),
            ):
                result = store.register(
                    submission,
                    work_order=order,
                    registered_by=principal.principal_id,
                    now=datetime.now(UTC),
                )
        except RuntimeError as exc:
            if str(exc) == "EXTERNAL_WORKFLOW_CLOSED":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise
        _result_error(result)
        assert result.revision is not None
        return _view(result.revision)

    @router.get(base, response_model=ExternalReconstructionListView)
    def list_submissions(
        work_order_id: str,
        principal: Principal = Depends(read),  # noqa: B008
    ) -> ExternalReconstructionListView:
        order = _require_work_order(work_orders, work_order_id, principal)
        return ExternalReconstructionListView(
            submissions=[
                _view(item)
                for item in store.list(
                    work_order_id, organization_id=principal.organization_id, site_id=order.site_id
                )
            ]
        )

    @router.get(
        base + "/{submission_ref}/revisions/{revision}",
        response_model=ExternalReconstructionRevisionView,
    )
    def get_revision(
        work_order_id: str,
        submission_ref: str,
        revision: int,
        principal: Principal = Depends(read),  # noqa: B008
    ) -> ExternalReconstructionRevisionView:
        order = _require_work_order(work_orders, work_order_id, principal)
        submission_id = store.resolve_submission_ref(
            work_order_id,
            submission_ref,
            organization_id=principal.organization_id,
            site_id=order.site_id,
        )
        if submission_id is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        record = store.get(
            work_order_id,
            submission_id,
            revision,
            organization_id=principal.organization_id,
            site_id=order.site_id,
        )
        if record is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        return _view(record)

    @router.post(
        base + "/{submission_ref}/revisions/{revision}/upload-grants",
        response_model=ExternalReconstructionGrantResponse,
    )
    def upload_grants(
        work_order_id: str,
        submission_ref: str,
        revision: int,
        principal: Principal = Depends(write),  # noqa: B008
    ) -> ExternalReconstructionGrantResponse:
        order = _require_work_order(work_orders, work_order_id, principal)
        _write_principal(principal)
        submission_id = store.resolve_submission_ref(
            work_order_id,
            submission_ref,
            organization_id=principal.organization_id,
            site_id=order.site_id,
        )
        if submission_id is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        result = store.upload_grants(
            work_order_id,
            submission_id,
            revision,
            organization_id=principal.organization_id,
            site_id=order.site_id,
            storage=storage,
        )
        if result.verdict is not ExternalReconstructionVerdict.REGISTERED:
            _result_error(
                ExternalReconstructionResult(result.verdict, result.revision, result.detail)
            )
        return ExternalReconstructionGrantResponse(
            grants=[
                ExternalReconstructionGrantView(
                    artifact_id=grant.artifact_id,
                    object_key=grant.object_key,
                    upload_url=grant.upload_url,
                    required_headers=grant.required_headers,
                )
                for grant in result.grants
            ]
        )

    @router.post(
        base + "/{submission_ref}/revisions/{revision}/seal",
        response_model=ExternalReconstructionRevisionView,
    )
    def seal(
        work_order_id: str,
        submission_ref: str,
        revision: int,
        principal: Principal = Depends(write),  # noqa: B008
    ) -> ExternalReconstructionRevisionView:
        order = _require_work_order(work_orders, work_order_id, principal)
        _write_principal(principal)
        submission_id = store.resolve_submission_ref(
            work_order_id,
            submission_ref,
            organization_id=principal.organization_id,
            site_id=order.site_id,
        )
        if submission_id is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        result = store.seal(
            work_order_id,
            submission_id,
            revision,
            organization_id=principal.organization_id,
            site_id=order.site_id,
            storage=storage,
            now=datetime.now(UTC),
        )
        _result_error(result)
        assert result.revision is not None
        return _view(result.revision)

    app.state.external_reconstruction_store = store
    app.include_router(router)


__all__ = [
    "ExternalReconstructionRecoveryError",
    "ExternalReconstructionResult",
    "ExternalReconstructionRevision",
    "ExternalReconstructionStore",
    "ExternalReconstructionVerdict",
    "build_external_reconstruction_object_key",
    "build_external_reconstruction_submission_ref",
    "mount_external_reconstruction",
]
