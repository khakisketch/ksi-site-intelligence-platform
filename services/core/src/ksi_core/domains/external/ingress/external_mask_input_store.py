"""Additive Core ingress for independent binary-mask child resources.

Owns the mask-child declaration journal and the Core-sealed observed-byte
manifest journal, plus the actual protected upload-grant/seal behavior
through :mod:`external_mask_input_bytes` (server object keys, no raw client
paths).  All authority is explicit and required: reconstruction-subject
currentness plus baseline-DSM anchor, separate profile/runtime activation,
and scoped protected-byte proofs.  Missing ports fail closed; no default
self-declared profile is accepted.

Binding authority, read carefully:

- The client declaration asserts intent only (which sealed reconstruction
  subject owns the upload, which baseline DSM artifact is targeted,
  declared SHA/size).  It asserts no grid, CRS, dtype, or inspection
  truth.  Fabricated subjects are rejected: both subjects must be current
  in the reconstruction authority and the baseline artifact must resolve
  to its anchor before declare, seal, read, or admission.
- Core constructs the observed manifest itself from the authenticated
  narrow mask observation report (``MaskObservationReportV1``) plus the
  scoped protected-byte proof.  Caller-written rows/digests and any caller
  ``userDeclaredInspection`` claim are never accepted.  The old DSM/ortho
  inspection report type is never accepted here.
- The narrow mask inspection profile (``MaskInspectionProfileV1``) is
  checked by digest and by separate activation: the report's profile
  digest must equal the sealed profile, and the profile/runtime must be
  currently active in the activation port.  The old float-DSM grammar and
  old inspector are never accepted.
- Reads are uniform: a missing record, an out-of-scope record, or a
  record whose subjects/anchor are no longer current returns ``None``
  without revealing which.  Only a missing ``SITES_READ`` permission
  raises.  Returned records are deep copies; the journal's historical
  state can never be mutated through a returned model.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_mask_input import (
    MaskChildDeclarationV1,
    MaskInspectionProfileV1,
    MaskObservedManifestV1,
)
from ksi_event_contracts.external_mask_input_report import MaskObservationReportV1

from ksi_core.foundation.api_base import iso_utc
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, principal_permissions

_VERSION = 1
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_EVENT_DECLARED = "external-mask-child-declared.v1"
_EVENT_OBSERVED = "external-mask-child-observed.v1"


class MaskInputRecoveryError(RuntimeError):
    """The mask-child journal cannot be replayed safely."""


@dataclass(frozen=True, slots=True)
class BaselineDsmAnchor:
    """Immutable baseline-DSM grid anchor resolved from sealed Core records.

    Rows/columns are the inspected DSM raster dimensions and observed
    SHA/size are the sealed manifest bytes: a mask whose dimensions do not
    match the anchor grid is rejected at seal, before any numeric work.
    Resolution is always scoped to the exact sealed baseline subject plus
    organization/site/work-area, never by bare global artifact id.
    """

    baseline_subject_digest: str
    dsm_artifact_id: str
    rows: int
    columns: int
    observed_sha256: str
    observed_size_bytes: int
    transform: tuple[float, float, float, float, float, float]
    transform_digest: str
    crs_identifier: str
    crs_digest: str


class MaskReconstructionAuthorityPort(Protocol):
    """Trusted reconstruction currentness plus baseline-DSM anchor (parent wiring)."""

    def is_subject_current(
        self,
        *,
        subject: SealedExternalSubjectV1,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        now: datetime,
    ) -> bool: ...

    def fetch_baseline_anchor(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        baseline_subject: SealedExternalSubjectV1,
        dsm_artifact_id: str,
    ) -> BaselineDsmAnchor | None: ...


class MaskProfileActivationPort(Protocol):
    """Separate profile/runtime activation policy; sealed digest alone is not authority."""

    def is_profile_active(
        self,
        *,
        profile_digest: str,
        resource_envelope_digest: str,
        contained_runtime_digest: str,
        inspector_build_digest: str,
        now: datetime,
    ) -> bool: ...


class MaskScopedByteProof(Protocol):
    """Scoped sealed-byte proof; resolves the server key internally, never a client path."""

    def fetch_proof(
        self,
        *,
        organization_id: str,
        site_id: str,
        subject_digest: str,
        mask_child_id: str,
        mask_artifact_id: str,
    ) -> tuple[str, int]: ...


def _digest(value: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _event_digest(raw: Mapping[str, object]) -> str:
    return _digest({key: value for key, value in raw.items() if key != "eventDigest"})


@dataclass(frozen=True, slots=True)
class MaskChildRecord:
    declaration: MaskChildDeclarationV1
    manifest: MaskObservedManifestV1 | None = None


class ExternalMaskInputStore:
    """Durable mask-child ingress: declaration journal plus Core-built observed binding."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        resource_envelope: ResourceEnvelopeV1,
        reconstruction_authority: MaskReconstructionAuthorityPort,
        profile_activation: MaskProfileActivationPort,
        sealed_bytes: MaskScopedByteProof,
        observer_principal: Principal | None = None,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        if (
            resource_envelope.resource_envelope_digest is None
            or resource_envelope.resource_envelope_digest != resource_envelope.canonical_digest()
        ):
            raise ValueError("mask ingress requires a sealed resource envelope")
        if reconstruction_authority is None or profile_activation is None or sealed_bytes is None:
            raise ValueError("mask ingress requires explicit trusted authority ports")
        if observer_principal is not None:
            if (
                observer_principal.kind is not PrincipalKind.ANALYSIS_WORKER
                or Permission.ANALYSIS_WORK not in principal_permissions(observer_principal)
                or not observer_principal.organization_id
            ):
                raise ValueError(
                    "mask ingress observer must be the pinned designated organization worker"
                )
            port_pinned = getattr(profile_activation, "designated_worker", None)
            if isinstance(port_pinned, Principal) and (
                port_pinned.principal_id != observer_principal.principal_id
                or port_pinned.organization_id != observer_principal.organization_id
            ):
                raise ValueError("mask ingress observer must match the activation worker")
        self._journal = journal
        self._envelope = resource_envelope.model_copy(deep=True)
        self._reconstruction = reconstruction_authority
        self._activation = profile_activation
        self._sealed_bytes = sealed_bytes
        self._observer_principal = observer_principal
        self._coordinator = coordinator or ExternalAuthorityCurrentnessCoordinator()
        self._lock = threading.RLock()
        self._records: dict[tuple[str, str], MaskChildRecord] = {}
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException as exc:
            journal.close()
            if isinstance(exc, MaskInputRecoveryError):
                raise
            raise MaskInputRecoveryError(str(exc)) from exc

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def declare(
        self,
        *,
        principal: Principal,
        declaration: MaskChildDeclarationV1,
        now: datetime,
    ) -> MaskChildDeclarationV1:
        self._require_site_write(principal)
        self._require_utc(now)
        sealed = MaskChildDeclarationV1.model_validate(declaration.model_dump(by_alias=True))
        if (
            sealed.declaration_digest is None
            or sealed.declaration_digest != sealed.canonical_digest()
        ):
            raise ValueError("mask declaration must be sealed")
        self._require_scope(principal, sealed.organization_id, sealed.site_id, sealed.work_area_id)
        if sealed.declared_size_bytes > min(
            self._envelope.max_input_bytes, self._envelope.max_streamed_bytes
        ):
            raise ValueError("mask declaration exceeds the finite byte cap")
        if not self._reconstruction.is_subject_current(
            subject=sealed.parent_subject,
            organization_id=sealed.organization_id,
            site_id=sealed.site_id,
            work_area_id=sealed.work_area_id,
            now=now,
        ):
            raise ValueError("mask parent subject is not currently sealed")
        if not self._reconstruction.is_subject_current(
            subject=sealed.target_baseline_subject,
            organization_id=sealed.organization_id,
            site_id=sealed.site_id,
            work_area_id=sealed.work_area_id,
            now=now,
        ):
            raise ValueError("mask baseline subject is not currently sealed")
        anchor = self._reconstruction.fetch_baseline_anchor(
            organization_id=sealed.organization_id,
            site_id=sealed.site_id,
            work_area_id=sealed.work_area_id,
            baseline_subject=sealed.target_baseline_subject,
            dsm_artifact_id=sealed.target_baseline_dsm_artifact_id,
        )
        if (
            anchor is None
            or anchor.baseline_subject_digest != sealed.target_baseline_subject.canonical_digest()
            or anchor.dsm_artifact_id != sealed.target_baseline_dsm_artifact_id
        ):
            raise ValueError("mask baseline artifact does not resolve to its anchor")
        key = (sealed.organization_id, sealed.mask_child_id)
        raw = {
            "kind": _EVENT_DECLARED,
            "version": _VERSION,
            "organizationId": sealed.organization_id,
            "maskChildId": sealed.mask_child_id,
            "declaredAt": iso_utc(now),
            "declaration": sealed.model_dump(by_alias=True, mode="json"),
        }
        with self._coordinator.mutation(), self._lock:
            existing = self._records.get(key)
            if existing is not None:
                if existing.declaration != sealed:
                    raise ValueError("mask child id is already bound to another declaration")
                return existing.declaration.model_copy(deep=True)
            self._append_locked(raw)
            return self._records[key].declaration.model_copy(deep=True)

    def seal_observed(
        self,
        *,
        principal: Principal,
        organization_id: str,
        mask_child_id: str,
        report: MaskObservationReportV1,
        inspection_profile: MaskInspectionProfileV1,
        now: datetime,
    ) -> MaskObservedManifestV1:
        """Core-build the observed manifest from the authenticated narrow report.

        Caller-written rows/digests are never accepted: the grid comes from
        the baseline anchor, the bytes from the scoped protected-byte proof,
        and the report must be the sealed narrow mask observation.

        Caller authority: the exact pinned designated worker (no
        ``SITES_WRITE`` grant involved), or the legacy internal human path
        which requires ``SITES_WRITE``.  Any other worker fails closed, even
        with ``ANALYSIS_WORK`` permission.  The human path is internal/test
        legacy only; no human report endpoint is mounted.
        """
        self._require_utc(now)
        sealed_report = MaskObservationReportV1.model_validate(report.model_dump(by_alias=True))
        sealed_profile = MaskInspectionProfileV1.model_validate(
            inspection_profile.model_dump(by_alias=True)
        )
        if (
            sealed_report.report_digest is None
            or sealed_report.report_digest != sealed_report.canonical_digest()
        ):
            raise ValueError("mask observation report must be sealed")
        if (
            sealed_profile.inspection_profile_digest is None
            or sealed_profile.inspection_profile_digest != sealed_profile.canonical_digest()
        ):
            raise ValueError("mask inspection profile must be sealed")
        key = (organization_id, mask_child_id)
        with self._lock:
            record = self._records.get(key)
            if record is None:
                raise ValueError("mask child declaration is missing")
            declaration = record.declaration
        self._require_seal_caller(
            principal,
            declaration.organization_id,
            declaration.site_id,
            declaration.work_area_id,
        )
        if (
            sealed_report.organization_id != declaration.organization_id
            or sealed_report.site_id != declaration.site_id
            or sealed_report.work_area_id != declaration.work_area_id
            or sealed_report.mask_child_id != declaration.mask_child_id
            or sealed_report.mask_artifact_id != declaration.mask_artifact_id
            or sealed_report.subject != declaration.parent_subject
            or sealed_report.subject_digest != declaration.parent_subject.canonical_digest()
            or sealed_report.inspection_profile_digest != sealed_profile.canonical_digest()
        ):
            raise ValueError("mask observation report does not bind its declaration")
        if sealed_profile.resource_envelope_digest != self._envelope.canonical_digest():
            raise ValueError("mask profile does not bind this resource envelope")
        if not self._activation.is_profile_active(
            profile_digest=sealed_profile.canonical_digest(),
            resource_envelope_digest=self._envelope.canonical_digest(),
            contained_runtime_digest=sealed_report.contained_runtime_digest,
            inspector_build_digest=sealed_report.inspector_build_digest,
            now=now,
        ):
            raise ValueError("mask inspection profile is not currently active")
        if not self._reconstruction.is_subject_current(
            subject=declaration.parent_subject,
            organization_id=declaration.organization_id,
            site_id=declaration.site_id,
            work_area_id=declaration.work_area_id,
            now=now,
        ):
            raise ValueError("mask parent subject is not currently sealed")
        if not self._reconstruction.is_subject_current(
            subject=declaration.target_baseline_subject,
            organization_id=declaration.organization_id,
            site_id=declaration.site_id,
            work_area_id=declaration.work_area_id,
            now=now,
        ):
            raise ValueError("mask baseline subject is not currently sealed")
        anchor = self._reconstruction.fetch_baseline_anchor(
            organization_id=declaration.organization_id,
            site_id=declaration.site_id,
            work_area_id=declaration.work_area_id,
            baseline_subject=declaration.target_baseline_subject,
            dsm_artifact_id=declaration.target_baseline_dsm_artifact_id,
        )
        if (
            anchor is None
            or anchor.baseline_subject_digest
            != declaration.target_baseline_subject.canonical_digest()
        ):
            raise ValueError("mask baseline anchor is not current")
        measurements = sealed_report.measurements
        if (
            tuple(measurements.transform) != tuple(anchor.transform)
            or measurements.transform_digest != anchor.transform_digest
            or measurements.observed_crs_identifier != anchor.crs_identifier
            or measurements.observed_crs_digest != anchor.crs_digest
            or measurements.width != anchor.columns
            or measurements.height != anchor.rows
        ):
            raise ValueError("mask observed grid does not match the baseline anchor")
        if measurements.width * measurements.height > self._envelope.max_pixels:
            raise ValueError("mask observed pixels exceed the finite pixel cap")
        if sealed_report.observed_size_bytes > min(
            self._envelope.max_input_bytes, self._envelope.max_streamed_bytes
        ):
            raise ValueError("mask observed bytes exceed the finite byte cap")
        sha256, size = self._sealed_bytes.fetch_proof(
            organization_id=declaration.organization_id,
            site_id=declaration.site_id,
            subject_digest=declaration.parent_subject.canonical_digest(),
            mask_child_id=declaration.mask_child_id,
            mask_artifact_id=declaration.mask_artifact_id,
        )
        if (
            sha256 != sealed_report.observed_sha256
            or size != sealed_report.observed_size_bytes
            or sha256 != declaration.declared_sha256
            or size != declaration.declared_size_bytes
        ):
            raise ValueError("mask stored bytes do not match the observed report")
        manifest = MaskObservedManifestV1(
            organization_id=declaration.organization_id,
            site_id=declaration.site_id,
            work_area_id=declaration.work_area_id,
            child_kind="MASK_CHILD",
            mask_child_id=declaration.mask_child_id,
            mask_artifact_id=declaration.mask_artifact_id,
            subject=declaration.parent_subject,
            parent_subject_digest=declaration.parent_subject.canonical_digest(),
            target_baseline_dsm_artifact_id=declaration.target_baseline_dsm_artifact_id,
            target_baseline_subject_digest=(declaration.target_baseline_subject.canonical_digest()),
            observed_sha256=sha256,
            observed_size_bytes=size,
            observed_inspection_report_digest=sealed_report.canonical_digest(),
            inspection_profile_digest=sealed_profile.canonical_digest(),
            rows=measurements.height,
            columns=measurements.width,
            transform=measurements.transform,
            transform_digest=measurements.transform_digest,
            observed_crs_identifier=measurements.observed_crs_identifier,
            observed_crs_digest=measurements.observed_crs_digest,
            dtype="UINT8",
            band_count=1,
            retain_value=0,
            exclude_value=1,
            nodata_representation="NONE",
            bounds=measurements.bounds,
        ).sealed()
        raw = {
            "kind": _EVENT_OBSERVED,
            "version": _VERSION,
            "organizationId": manifest.organization_id,
            "maskChildId": manifest.mask_child_id,
            "sealedAt": iso_utc(now),
            "manifest": manifest.model_dump(by_alias=True, mode="json"),
            "inspectionProfile": sealed_profile.model_dump(by_alias=True, mode="json"),
        }
        with self._coordinator.mutation(), self._lock:
            record = self._records.get(key)
            if record is None or record.declaration != declaration:
                raise ValueError("mask child declaration changed before observed seal")
            if record.manifest is not None:
                if record.manifest != manifest:
                    raise ValueError("mask child is already sealed to another manifest")
                return record.manifest.model_copy(deep=True)
            self._append_locked(raw)
            sealed = self._records[key]
            assert sealed.manifest is not None
            return sealed.manifest.model_copy(deep=True)

    def get(
        self,
        *,
        organization_id: str,
        mask_child_id: str,
        principal: Principal,
        now: datetime,
    ) -> MaskChildRecord | None:
        """Uniform read: missing, out-of-scope, or no-longer-current returns None."""
        if not self._has_site_read(principal):
            raise PermissionError("mask child read requires SITES_READ")
        self._require_utc(now)
        with self._lock:
            record = self._records.get((organization_id, mask_child_id))
            if record is None:
                return None
            declaration = record.declaration
            if not self._in_scope(
                principal,
                declaration.organization_id,
                declaration.site_id,
                declaration.work_area_id,
            ):
                return None
            if not self._reconstruction.is_subject_current(
                subject=declaration.parent_subject,
                organization_id=declaration.organization_id,
                site_id=declaration.site_id,
                work_area_id=declaration.work_area_id,
                now=now,
            ):
                return None
            if not self._reconstruction.is_subject_current(
                subject=declaration.target_baseline_subject,
                organization_id=declaration.organization_id,
                site_id=declaration.site_id,
                work_area_id=declaration.work_area_id,
                now=now,
            ):
                return None
            if record.manifest is not None:
                anchor = self._reconstruction.fetch_baseline_anchor(
                    organization_id=declaration.organization_id,
                    site_id=declaration.site_id,
                    work_area_id=declaration.work_area_id,
                    baseline_subject=declaration.target_baseline_subject,
                    dsm_artifact_id=declaration.target_baseline_dsm_artifact_id,
                )
                manifest = record.manifest
                if (
                    anchor is None
                    or tuple(manifest.transform) != tuple(anchor.transform)
                    or manifest.transform_digest != anchor.transform_digest
                    or manifest.observed_crs_identifier != anchor.crs_identifier
                    or manifest.observed_crs_digest != anchor.crs_digest
                    or manifest.columns != anchor.columns
                    or manifest.rows != anchor.rows
                ):
                    return None
            return MaskChildRecord(
                declaration=declaration.model_copy(deep=True),
                manifest=(
                    record.manifest.model_copy(deep=True) if record.manifest is not None else None
                ),
            )

    def resolve_baseline_anchor(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        baseline_subject: SealedExternalSubjectV1,
        dsm_artifact_id: str,
    ) -> BaselineDsmAnchor | None:
        """Expose the trusted baseline anchor for evidence assembly (no caller bytes)."""
        with self._lock:
            return self._reconstruction.fetch_baseline_anchor(
                organization_id=organization_id,
                site_id=site_id,
                work_area_id=work_area_id,
                baseline_subject=baseline_subject,
                dsm_artifact_id=dsm_artifact_id,
            )

    def resolve_manifest_by_child(
        self, *, organization_id: str, mask_child_id: str
    ) -> MaskObservedManifestV1 | None:
        """Core-internal manifest resolution for evidence assembly (no caller principal).

        Scoped by organization; returns a deep copy or None.  Caller scope is
        enforced separately by the evidence consumer and the issuing route.
        """
        with self._lock:
            record = self._records.get((organization_id, mask_child_id))
            if record is None or record.manifest is None:
                return None
            return record.manifest.model_copy(deep=True)

    def find_child_by_artifact(
        self, *, organization_id: str, mask_artifact_id: str, observed_sha256: str
    ) -> str | None:
        """Resolve the single child bound to an artifact+SHA; None when not unique."""
        with self._lock:
            candidates = [
                child_id
                for (org, child_id), record in self._records.items()
                if org == organization_id
                and record.manifest is not None
                and record.manifest.mask_artifact_id == mask_artifact_id
                and record.manifest.observed_sha256 == observed_sha256
            ]
            if len(candidates) != 1:
                return None
            return candidates[0]

    def _binds_declaration(
        self, declaration: MaskChildDeclarationV1, manifest: MaskObservedManifestV1
    ) -> None:
        if (
            (manifest.organization_id, manifest.site_id, manifest.work_area_id)
            != (
                declaration.organization_id,
                declaration.site_id,
                declaration.work_area_id,
            )
            or manifest.mask_child_id != declaration.mask_child_id
            or manifest.mask_artifact_id != declaration.mask_artifact_id
            or manifest.subject != declaration.parent_subject
            or manifest.parent_subject_digest != declaration.parent_subject.canonical_digest()
            or manifest.target_baseline_subject_digest
            != declaration.target_baseline_subject.canonical_digest()
            or manifest.target_baseline_dsm_artifact_id
            != declaration.target_baseline_dsm_artifact_id
            or manifest.observed_sha256 != declaration.declared_sha256
            or manifest.observed_size_bytes != declaration.declared_size_bytes
        ):
            raise ValueError("mask manifest does not bind its declaration")

    def _append_locked(self, raw: dict[str, object]) -> None:
        record = dict(raw)
        record["eventDigest"] = _event_digest(record)
        try:
            self._journal.append(record)
        except JournalSealedError:
            raise
        except BaseException as exc:
            raise MaskInputRecoveryError(str(exc)) from exc
        self._apply(record)

    def _apply(self, raw: Mapping[str, object]) -> None:
        kind = raw.get("kind")
        if kind != _EVENT_DECLARED and kind != _EVENT_OBSERVED:
            raise MaskInputRecoveryError(f"unknown mask-child journal kind: {kind!r}")
        if type(raw.get("version")) is not int or raw.get("version") != _VERSION:
            raise MaskInputRecoveryError("mask-child journal version is unsupported")
        expected_fields = (
            {
                "kind",
                "version",
                "eventDigest",
                "organizationId",
                "maskChildId",
                "declaredAt",
                "declaration",
            }
            if kind == _EVENT_DECLARED
            else {
                "kind",
                "version",
                "eventDigest",
                "organizationId",
                "maskChildId",
                "sealedAt",
                "manifest",
                "inspectionProfile",
            }
            if kind == _EVENT_OBSERVED
            else set()
        )
        if not expected_fields or set(raw.keys()) != expected_fields:
            raise MaskInputRecoveryError("mask-child journal fields are not exact")
        digest = raw.get("eventDigest")
        if not isinstance(digest, str) or digest != _event_digest(raw):
            raise MaskInputRecoveryError("mask-child journal digest is invalid")
        if kind == _EVENT_DECLARED:
            declaration = MaskChildDeclarationV1.model_validate(raw["declaration"])
            if (
                declaration.declaration_digest is None
                or declaration.declaration_digest != declaration.canonical_digest()
            ):
                raise MaskInputRecoveryError("mask declaration journal is tampered")
            key = (declaration.organization_id, declaration.mask_child_id)
            existing = self._records.get(key)
            if existing is not None:
                if existing.declaration != declaration:
                    raise MaskInputRecoveryError("mask declaration journal conflicts")
                return
            self._records[key] = MaskChildRecord(declaration=declaration)
        elif kind == _EVENT_OBSERVED:
            manifest = MaskObservedManifestV1.model_validate(raw["manifest"])
            profile = MaskInspectionProfileV1.model_validate(raw["inspectionProfile"])
            if (
                manifest.manifest_digest is None
                or manifest.manifest_digest != manifest.canonical_digest()
                or profile.inspection_profile_digest is None
                or profile.inspection_profile_digest != profile.canonical_digest()
            ):
                raise MaskInputRecoveryError("mask observed journal is tampered")
            if manifest.inspection_profile_digest != profile.canonical_digest():
                raise MaskInputRecoveryError("mask observed journal binds another profile")
            key = (manifest.organization_id, manifest.mask_child_id)
            existing = self._records.get(key)
            if existing is None:
                raise MaskInputRecoveryError("mask observed journal precedes its declaration")
            self._binds_declaration(existing.declaration, manifest)
            if existing.manifest is not None:
                if existing.manifest != manifest:
                    raise MaskInputRecoveryError("mask observed journal conflicts")
                return
            self._records[key] = MaskChildRecord(
                declaration=existing.declaration, manifest=manifest
            )
        else:
            raise MaskInputRecoveryError(f"unknown mask-child journal kind: {kind!r}")

    @staticmethod
    def _require_utc(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("mask ingress time must be UTC")

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
            raise PermissionError("mask ingress requires SITES_WRITE")

    @staticmethod
    def _has_site_read(principal: Principal) -> bool:
        granted = principal_permissions(principal)
        return (
            Permission.ANALYSIS_API_READ in granted
            if principal.kind is PrincipalKind.ANALYSIS_MCP_CLIENT
            else Permission.SITES_READ in granted
        )

    @classmethod
    def _in_scope(
        cls, principal: Principal, organization_id: str, site_id: str, work_area_id: str
    ) -> bool:
        if principal.kind is not PrincipalKind.ANALYSIS_MCP_CLIENT:
            if principal.organization_id != organization_id:
                return False
            if principal.allowed_site_ids is not None and site_id not in principal.allowed_site_ids:
                return False
            if (
                principal.allowed_work_area_ids is not None
                and work_area_id not in principal.allowed_work_area_ids
            ):
                return False
            return principal.organization_id == organization_id
        return (
            principal.organization_id == organization_id
            and principal.allowed_site_ids is not None
            and site_id in principal.allowed_site_ids
            and principal.allowed_work_area_ids is not None
            and work_area_id in principal.allowed_work_area_ids
        )

    @classmethod
    def _require_scope(
        cls, principal: Principal, organization_id: str, site_id: str, work_area_id: str
    ) -> None:
        if not cls._in_scope(principal, organization_id, site_id, work_area_id):
            if principal.kind is PrincipalKind.ANALYSIS_MCP_CLIENT:
                raise PermissionError("mask child is outside client scope")
            raise PermissionError("mask child is outside caller scope")

    def _pinned_observer(self) -> Principal | None:
        """The exact designated worker accepted for seals: explicit pin wins.

        Falls back to the profile activation's designated worker when the
        constructor pin is absent (parent wiring passes it through the
        already-wired activation).  Anything else means the worker seam is
        closed: only the legacy internal human path remains.
        """
        if self._observer_principal is not None:
            return self._observer_principal
        candidate = getattr(self._activation, "designated_worker", None)
        return candidate if isinstance(candidate, Principal) else None

    def _require_seal_caller(
        self, principal: Principal, organization_id: str, site_id: str, work_area_id: str
    ) -> None:
        """Gate the seal caller: exact pinned worker or legacy SITES_WRITE human.

        The worker path checks kind, exact principal id, organization, the
        ``ANALYSIS_WORK`` permission, and the caller's optional site/area
        allowlists — a different worker fails closed even with
        ``ANALYSIS_WORK``.  No ``SITES_WRITE`` grant is involved and none is
        created here.
        """
        pinned = self._pinned_observer()
        if (
            pinned is not None
            and principal.kind is PrincipalKind.ANALYSIS_WORKER
            and principal.principal_id == pinned.principal_id
            and principal.organization_id == pinned.organization_id
            and Permission.ANALYSIS_WORK in principal_permissions(principal)
        ):
            self._require_scope(principal, organization_id, site_id, work_area_id)
            return
        self._require_site_write(principal)
        self._require_scope(principal, organization_id, site_id, work_area_id)


__all__ = [
    "BaselineDsmAnchor",
    "ExternalMaskInputStore",
    "MaskChildRecord",
    "MaskInputRecoveryError",
    "MaskProfileActivationPort",
    "MaskReconstructionAuthorityPort",
    "MaskScopedByteProof",
]
