"""Durable, numeric-free V2 suitability assessments over sealed Core stores.

This internal foundation records eligibility for a future worker.  It neither
runs a calculation nor mounts a public surface.  Every admission is derived
from sealed reconstruction, inspection, WorkArea, evidence, and validation
records, then rechecked locally under the shared currentness coordinator.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import (
    ArtifactOutcome,
    ExternalArtifactInspectionReportV1,
    ObservedVerticalReferenceV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_evidence import EvidenceCoreVerdict
from ksi_event_contracts.external_relative_volume_analysis import (
    AdmissionDispositionV2,
    AdmissionV2,
    AnalysisPolicyV2,
    CalculationIdentityV2,
    EvaluationEvidenceFactV1,
    EvaluationOutcomeV1,
    EvaluationV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_geo_spatial.crs import assert_same_crs, assert_supported_project_crs
from pydantic import ConfigDict, StringConstraints
from pyproj import CRS
from pyproj.exceptions import CRSError

from ksi_core.domains.external.ingress.external_artifact_inspections import (
    ExternalArtifactInspectionStore,
)
from ksi_core.domains.external.ingress.external_evidence import EvidenceItem, ExternalEvidenceStore
from ksi_core.domains.external.ingress.external_evidence_validations import (
    AnalysisEvidenceFactSnapshot,
    AnalysisEvidenceValidationLifecycleSnapshot,
    ExternalEvidenceValidationStore,
)
from ksi_core.domains.external.ingress.external_reconstruction import (
    ExternalReconstructionRevision,
    ExternalReconstructionStore,
)
from ksi_core.domains.sites.work_areas import WorkArea, WorkAreaStatus, WorkAreaStore
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, principal_permissions

_VERSION = 1
_MAX_EVIDENCE_FACTS = 64
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_VERTICAL_EPSG_RE = re.compile(r"^EPSG:([1-9][0-9]*)$")
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Epoch = Literal["BASELINE", "CURRENT"]


def _digest(value: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _event_digest(raw: dict[str, object]) -> str:
    return _digest({key: value for key, value in raw.items() if key != "eventDigest"})


def _observed_vertical_unit(
    reference: ObservedVerticalReferenceV1,
) -> tuple[Literal["metre"], Literal["OBSERVED_VERTICAL_CRS_AXIS"]] | None:
    """Resolve the parser-observed vertical EPSG axis without accepting labels.

    External inspection emits this reference only after its own compound-CRS
    parser has found one vertical metre axis.  Core repeats the local EPSG
    resolution so a hand-constructed free-text reference cannot become a
    metre claim in a durable future-calculation identity.
    """
    match = _VERTICAL_EPSG_RE.fullmatch(reference.identifier)
    if match is None:
        return None
    try:
        vertical = CRS.from_epsg(int(match.group(1)))
    except CRSError:
        return None
    axis = vertical.axis_info
    if (
        not vertical.is_vertical
        or vertical.to_epsg() != int(match.group(1))
        or len(axis) != 1
        or axis[0].unit_name.lower() not in {"metre", "meter"}
        or reference.basis != vertical.name
    ):
        return None
    return "metre", "OBSERVED_VERTICAL_CRS_AXIS"


def _observed_projected_unit(horizontal_crs: str) -> Literal["metre"] | None:
    """Derive the horizontal unit from the exact inspection-observed CRS."""
    try:
        crs = CRS.from_user_input(horizontal_crs)
    except CRSError:
        return None
    if (
        not crs.is_projected
        or len(crs.axis_info) != 2
        or any(axis.unit_name.lower() not in {"metre", "meter"} for axis in crs.axis_info)
    ):
        return None
    return "metre"


def _measured_raster_bounds(
    transform: tuple[float, float, float, float, float, float],
    *,
    width: int,
    height: int,
) -> tuple[float, float, float, float] | None:
    """Return a measured affine's axis-aligned bounds, or None if inconclusive."""
    a, b, c, d, e, f = transform
    try:
        corners = tuple(
            (a * column + b * row + c, d * column + e * row + f)
            for column, row in ((0, 0), (width, 0), (0, height), (width, height))
        )
    except OverflowError:
        return None
    if not all(math.isfinite(coordinate) for corner in corners for coordinate in corner):
        return None
    xs = tuple(corner[0] for corner in corners)
    ys = tuple(corner[1] for corner in corners)
    return min(xs), min(ys), max(xs), max(ys)


def _have_positive_area_overlap(
    left: tuple[float, float, float, float], right: tuple[float, float, float, float]
) -> bool:
    """Compare conservative axis-aligned envelopes; rotated-grid false positives are safe."""
    return min(left[2], right[2]) > max(left[0], right[0]) and min(
        left[3], right[3]
    ) > max(left[1], right[1])


class AnalysisAssessmentRecoveryError(RuntimeError):
    """An assessment journal cannot be replayed without its exact bindings."""


class AnalysisEpochSelectionV2(_CamelModel):
    """An internal caller selects a sealed epoch subject, never evidence facts."""

    model_config = ConfigDict(frozen=True, revalidate_instances="always")
    subject: SealedExternalSubjectV1


class AnalysisAssessmentRequestV2(_CamelModel):
    """Internal request identity; the human idempotency key is never journaled."""

    model_config = ConfigDict(frozen=True, revalidate_instances="always")
    request_id: Text
    work_area_id: Text
    baseline: AnalysisEpochSelectionV2
    current: AnalysisEpochSelectionV2
    idempotency_key: Text

    def journal_body(self) -> dict[str, object]:
        return self.model_dump(by_alias=True, mode="json", exclude={"idempotency_key"})

    def request_digest(self) -> str:
        return _digest(self.journal_body())


@dataclass(frozen=True, slots=True)
class AnalysisRuntimeIdentityV2:
    """Trusted Core-selected worker/runtime provenance, never caller input."""

    worker_executable_digest: str
    worker_build_digest: str
    runtime_image_version: str
    runtime_image_oci_digest: str
    dependency_lock_digest: str

    def __post_init__(self) -> None:
        if not self.runtime_image_version.strip() or any(
            _DIGEST_RE.fullmatch(value) is None
            for value in (
                self.worker_executable_digest,
                self.worker_build_digest,
                self.runtime_image_oci_digest,
                self.dependency_lock_digest,
            )
        ):
            raise ValueError("analysis runtime identity requires exact non-empty provenance")


@dataclass(frozen=True, slots=True)
class AnalysisAssessmentRecord:
    request_id: str
    organization_id: str
    request_digest: str
    idempotency_digest: str
    admission: AdmissionV2


@dataclass(frozen=True, slots=True)
class _EpochResolved:
    subject: SealedExternalSubjectV1
    revision: ExternalReconstructionRevision
    report: ExternalArtifactInspectionReportV1
    evidence_items: tuple[EvidenceItem, ...]
    evidence_facts: tuple[AnalysisEvidenceFactSnapshot, ...]
    facts_current: bool
    fact_currentness: tuple[bool, ...]
    validation_lifecycles: tuple[AnalysisEvidenceValidationLifecycleSnapshot, ...]
    lifecycles_current: bool
    matching_evidence_present: bool
    unresolved_evidence_present: bool
    dsm_artifact_id: str
    dsm_observed_sha256: str
    dsm_observed_size_bytes: int
    raster_extent_bounds: tuple[float, float, float, float] | None
    capture_started_at: datetime
    capture_ended_at: datetime
    transform_digest: str
    transform: tuple[float, float, float, float, float, float]
    horizontal_crs: str
    horizontal_crs_digest: str
    projected_unit: Literal["metre"]
    vertical_reference: ObservedVerticalReferenceV1
    vertical_reference_digest: str
    vertical_unit: Literal["metre"]
    vertical_unit_provenance: Literal["OBSERVED_VERTICAL_CRS_AXIS"]
    input_digest: str


@dataclass(frozen=True, slots=True)
class _PreparedAssessment:
    area: WorkArea
    baseline: _EpochResolved
    current: _EpochResolved
    admission: AdmissionV2


@dataclass(frozen=True, slots=True)
class ReadinessPreview:
    """Immutable guarded read-only preflight for one arbitrary selector pair.

    The admission is the exact sealed AP decision for the pair and ``details``
    carries the confined per-epoch ``READINESS_*`` explanation when that
    decision is the coarse ``ESSENTIAL_INPUT_UNAVAILABLE`` block.  Both are
    captured under one shared currentness guard, so a consumer can project
    them without a second store round-trip that could observe a newer
    snapshot.  This snapshot never allocates evaluation revisions, appends a
    journal event, or authorizes execution.
    """

    admission: AdmissionV2
    details: tuple[tuple[str, Epoch], ...] = ()


@dataclass(frozen=True, slots=True)
class _PreparedExecutionWitness:
    """Preflight-only assessment and its historical record selection.

    Policy selection happens while this witness is prepared, before entering
    the shared coordinator.  The final method below only compares the
    captured snapshots against local retained state under that coordinator.
    """

    record: AnalysisAssessmentRecord
    prepared: _PreparedAssessment
    expected_admission: AdmissionV2 | None


class ExternalRelativeVolumeAnalysisStore:
    """Append-only suitability history, isolated from numeric worker execution."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        reconstruction: ExternalReconstructionStore,
        inspections: ExternalArtifactInspectionStore,
        work_areas: WorkAreaStore,
        evidence: ExternalEvidenceStore,
        validations: ExternalEvidenceValidationStore,
        policy: AnalysisPolicyV2,
        runtime: AnalysisRuntimeIdentityV2,
        clock: Callable[[], datetime] | None = None,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        self._journal = journal
        self._reconstruction = reconstruction
        self._inspections = inspections
        self._work_areas = work_areas
        self._evidence = evidence
        self._validations = validations
        self._policy = policy
        self._runtime = runtime
        self._clock = clock or (lambda: datetime.now(UTC))
        self._coordinator = coordinator or reconstruction.coordinator
        if any(
            participant.coordinator is not self._coordinator
            for participant in (inspections, work_areas, evidence, validations)
        ):
            raise ValueError("analysis stores must share one currentness coordinator")
        if policy.policy_digest is None or policy.policy_digest != policy.canonical_digest():
            raise ValueError("analysis policy must be sealed")
        self._records: dict[str, AnalysisAssessmentRecord] = {}
        self._requests: dict[str, AnalysisAssessmentRequestV2] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._evaluation_by_content: dict[tuple[str, str, str], EvaluationV1] = {}
        self._evaluation_by_revision: dict[tuple[str, str, int], EvaluationV1] = {}
        self._lock = threading.RLock()
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException as exc:
            journal.close()
            if isinstance(exc, AnalysisAssessmentRecoveryError):
                raise
            raise AnalysisAssessmentRecoveryError(str(exc)) from exc

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        """The local-only coordinator shared by an execution ledger.

        This is deliberately a narrow Core seam.  A numeric execution store
        needs the same guarded witness as assessment currentness, but it does
        not receive any mutable assessment projection or authority provider.
        """
        return self._coordinator

    def assess_and_record(
        self, *, principal: Principal, request: AnalysisAssessmentRequestV2, now: datetime
    ) -> AnalysisAssessmentRecord:
        """Preflight real stores, then append a compound evaluation/admission event."""
        self._require_site_action(principal)
        self._require_resource_scope(principal, request)
        self._require_utc(now)
        request_digest = request.request_digest()
        idempotency_digest = (
            "sha256:" + hashlib.sha256(request.idempotency_key.encode("utf-8")).hexdigest()
        )
        with self._lock:
            self._check_idempotency(principal.organization_id, idempotency_digest, request_digest)

        # A mutation between preflight and final local recheck causes one fresh
        # preflight.  A second mismatch records no potentially stale admission.
        for _attempt in range(2):
            prepared = self._prepare(principal=principal, request=request, now=now)
            with self._coordinator.guarded_read(), self._lock:
                # The exact local recheck precedes both idempotent return and
                # append.  An old ADMIT is historical evidence, never an
                # authorization shortcut after a context/evidence mutation.
                self._check_idempotency(
                    principal.organization_id, idempotency_digest, request_digest
                )
                if isinstance(
                    prepared, _PreparedAssessment
                ) and not self._prepared_is_locally_current(prepared, now=now):
                    continue
                admission = self._finalize_admission(prepared)
                existing_id = self._idempotency.get((principal.organization_id, idempotency_digest))
                if existing_id is not None:
                    existing = self._records[existing_id]
                    if self._suitability_key(existing.admission) != self._suitability_key(
                        admission
                    ):
                        raise RuntimeError(
                            "idempotent assessment is historical; use a new idempotency key"
                        )
                    return self._public_record(existing)
                raw = self._event_for(
                    organization_id=principal.organization_id,
                    request=request,
                    request_digest=request_digest,
                    idempotency_digest=idempotency_digest,
                    admission=admission,
                )
                # Replay-equivalent validation occurs before durable append.
                # This prevents a rejected request id from poisoning the
                # journal and holds revision allocation under the same lock.
                try:
                    self._apply(raw, mutate=False)
                except AnalysisAssessmentRecoveryError as exc:
                    raise ValueError("analysis assessment event is invalid") from exc
                try:
                    self._journal.append(raw)
                except JournalSealedError as exc:
                    raise RuntimeError("analysis assessment journal is unavailable") from exc
                self._apply(raw)
                return self._public_record(self._records[request.request_id])
        raise RuntimeError("analysis inputs changed during currentness recheck; retry assessment")

    def _finalize_admission(self, prepared: _PreparedAssessment | AdmissionV2) -> AdmissionV2:
        """Allocate/reuse immutable evaluation revisions while store-locked."""
        admission = prepared.admission if isinstance(prepared, _PreparedAssessment) else prepared
        if admission.calculation_identity is None:
            return admission
        identity = admission.calculation_identity
        evaluations = tuple(
            self._with_revision(identity, evaluation)
            for evaluation in admission.evaluation_revisions
        )
        return admission.model_copy(
            update={"evaluation_revisions": evaluations, "admission_digest": None}
        ).sealed()

    def get_history(
        self, request_id: str, *, organization_id: str
    ) -> AnalysisAssessmentRecord | None:
        """Internal organization-filtered projection; callers still authenticate separately."""
        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.organization_id != organization_id:
                return None
            return self._public_record(record)

    def get_history_for_principal(
        self, request_id: str, *, principal: Principal
    ) -> AnalysisAssessmentRecord | None:
        """Principal-scoped historical record read without cross-tenant disclosure."""
        if not self._has_site_read(principal):
            raise PermissionError("analysis history requires SITES_READ")
        record = self.get_history(request_id, organization_id=principal.organization_id)
        if record is None or principal.kind is not PrincipalKind.ANALYSIS_MCP_CLIENT:
            return record
        with self._lock:
            request = self._requests.get(request_id)
        return (
            record
            if request is not None and self._resource_scope_allows(principal, request)
            else None
        )

    def get_current(
        self, request_id: str, *, principal: Principal, now: datetime
    ) -> AnalysisAssessmentRecord | None:
        """Return history only if a fresh, guarded assessment has the same suitability."""
        self._require_site_action(principal)
        self._require_utc(now)
        with self._lock:
            historical = self._records.get(request_id)
            request = self._requests.get(request_id)
        if (
            historical is None
            or historical.organization_id != principal.organization_id
            or request is None
            or not self._resource_scope_allows(principal, request)
        ):
            return None
        prepared = self._prepare(principal=principal, request=request, now=now)
        with self._coordinator.guarded_read(), self._lock:
            if isinstance(prepared, _PreparedAssessment) and not self._prepared_is_locally_current(
                prepared, now=now
            ):
                return None
            admission = self._finalize_admission(prepared)
        if self._suitability_key(admission) != self._suitability_key(historical.admission):
            return None
        return self._public_record(historical)

    def get_current_for_read(
        self, request_id: str, *, principal: Principal, now: datetime
    ) -> AnalysisAssessmentRecord | None:
        """Read an existing assessment's currentness without write authority.

        The public Analysis API must answer a SITES_READ detail request without
        manufacturing a SITES_WRITE principal.  This method deliberately
        reuses the guarded, side-effect-free preparation path; it does not
        append an assessment, select a policy, or authorize calculation.
        """
        if not self._has_site_read(principal):
            raise PermissionError("analysis currentness requires SITES_READ")
        self._require_utc(now)
        with self._lock:
            historical = self._records.get(request_id)
            request = self._requests.get(request_id)
        if (
            historical is None
            or historical.organization_id != principal.organization_id
            or request is None
            or not self._resource_scope_allows(principal, request)
        ):
            return None
        prepared = self._prepare_for_organization(
            organization_id=principal.organization_id, request=request, now=now
        )
        with self._coordinator.guarded_read(), self._lock:
            if isinstance(prepared, _PreparedAssessment) and not self._prepared_is_locally_current(
                prepared, now=now
            ):
                return None
            admission = self._finalize_admission(prepared)
        if self._suitability_key(admission) != self._suitability_key(historical.admission):
            return None
        return self._public_record(historical)

    def preview_readiness_snapshot(
        self, *, organization_id: str, request: AnalysisAssessmentRequestV2, now: datetime
    ) -> ReadinessPreview | None:
        """Decide and explain one arbitrary pair under one guarded snapshot.

        Preparation, the local currentness recheck, and the per-epoch
        ``READINESS_*`` classification all complete inside the shared
        ``guarded_read`` + store lock, so a negative decision can never be
        prepared from an older snapshot than its diagnostic details (or vice
        versa).  ``None`` is returned only when the guarded verification
        itself fails, which is unreachable unless a participant violates the
        shared coordinator contract; the caller projects that as
        reassessment-required without inventing a suitability verdict.

        Guard-holding audit: every call under the guard is a local in-memory
        predicate or pure CPU work — participant ``get``/``resolve``/``list``
        dict scans under their own locks, retained policy/context
        dict lookups, ``hashlib`` digests over small canonical JSON, and local
        PROJ EPSG resolution (system database, no KSI storage or remote I/O).
        No journal append, ``mutation()``, object-store, worker, lease, or
        network call runs under the guard; no evaluation revision is
        allocated.  Lock order is coordinator-then-participant, matching the
        documented mutation order, and every nested ``guarded_read`` reentry
        is ``RLock``-safe (``analysis_fact_currentness`` already reenters it
        under guard today).
        """
        self._require_utc(now)
        with self._coordinator.guarded_read(), self._lock:
            prepared = self._prepare_for_organization(
                organization_id=organization_id, request=request, now=now
            )
            if isinstance(
                prepared, _PreparedAssessment
            ) and not self._prepared_is_locally_current(prepared, now=now):
                # Defensive: preparation and verification share one guarded
                # snapshot, so this is unreachable unless a participant
                # violates the shared coordinator contract. Never project a
                # possibly stale verdict.
                return None
            admission = (
                prepared.admission if isinstance(prepared, _PreparedAssessment) else prepared
            )
            details: list[tuple[str, Epoch]] = []
            if admission.reason_codes == ("ESSENTIAL_INPUT_UNAVAILABLE",):
                pairs: tuple[
                    tuple[SealedExternalSubjectV1, Epoch],
                    tuple[SealedExternalSubjectV1, Epoch],
                ] = (
                    (request.baseline.subject, "BASELINE"),
                    (request.current.subject, "CURRENT"),
                )
                for subject, epoch in pairs:
                    code = self._diagnose_epoch_unavailable(subject, epoch=epoch)
                    if code is not None:
                        details.append((code, epoch))
                        if len(details) >= 8:
                            break
            return ReadinessPreview(admission=admission, details=tuple(details))

    def _diagnose_epoch_unavailable(
        self, subject: SealedExternalSubjectV1, *, epoch: Epoch
    ) -> str | None:
        """Return the first precise readiness code for one epoch, if unresolvable."""
        revision = self._reconstruction.resolve_sealed_subject(subject)
        if revision is None or revision.manifest is None:
            return "READINESS_DSM_UNAVAILABLE"
        dsm_entries = [
            entry for entry in revision.manifest.entries if entry.kind is ProcessingArtifactKind.DSM
        ]
        if len(dsm_entries) != 1:
            return "READINESS_DSM_UNAVAILABLE"
        dsm = dsm_entries[0]
        capture = revision.submission.input_declaration
        if (
            capture.capture_started_at is None
            or capture.capture_ended_at is None
            or capture.capture_started_at.tzinfo is None
            or capture.capture_ended_at.tzinfo is None
            or capture.capture_started_at.utcoffset() != UTC.utcoffset(capture.capture_started_at)
            or capture.capture_ended_at.utcoffset() != UTC.utcoffset(capture.capture_ended_at)
        ):
            return "READINESS_CAPTURE_INTERVAL_UNAVAILABLE"
        snapshot = self._inspections.public_snapshot(subject)
        report = snapshot.report
        if report is None or report.report_digest is None:
            return "READINESS_INSPECTION_PENDING"
        outcome = next(
            (
                item
                for item in report.measurement_payload.outcomes
                if item.artifact_id == dsm.artifact_id
            ),
            None,
        )
        if outcome is None:
            return "READINESS_INSPECTION_PENDING"
        # Terminal worker verdicts (REJECTED/NOT_APPLICABLE) carry a typed
        # reason and no measurements by contract, so classify them before any
        # measurements check. Only a MEASURED outcome with an absent payload
        # is pending.
        if outcome.outcome is not ArtifactOutcome.MEASURED:
            return "READINESS_INSPECTION_REJECTED"
        if outcome.observed_sha256 != "sha256:" + dsm.observed_sha256:
            return "READINESS_INSPECTION_BINDING_INVALID"
        measurements = outcome.measurements
        if measurements is None:
            return "READINESS_INSPECTION_PENDING"
        vertical_reference = measurements.observed_vertical_reference
        if vertical_reference is None:
            return "READINESS_VERTICAL_REFERENCE_UNAVAILABLE"
        if _observed_vertical_unit(vertical_reference) is None:
            return "READINESS_VERTICAL_UNIT_UNAVAILABLE"
        if _observed_projected_unit(measurements.observed_crs_identifier) is None:
            return "READINESS_PROJECTED_UNIT_UNAVAILABLE"
        a, b, _c, d, e, _f = measurements.transform
        if epoch == "BASELINE" and (b != 0.0 or d != 0.0 or a <= 0.0 or e >= 0.0):
            return "READINESS_BASELINE_GRID_INVALID"
        return None

    def latest_current_for_execution(
        self,
        *,
        calculation_identity_digest: str,
        organization_id: str,
        now: datetime,
    ) -> AnalysisAssessmentRecord | None:
        """Return the newest locally-current durable assessment for one identity.

        This is an internal Core-to-Core witness, deliberately separate from
        principal-scoped API methods.  It does not manufacture a ``Principal``
        or perform remote I/O under the shared currentness guard.  A changed
        underlying fact requires a new durable assessment; an older admission
        cannot become execution authority merely because it has the same
        calculation identity.
        """
        witness = self.prepare_execution_witness(
            calculation_identity_digest=calculation_identity_digest,
            organization_id=organization_id,
            now=now,
        )
        return self.execution_witness_is_current(witness=witness, now=now)

    def prepare_execution_witness(
        self,
        *,
        calculation_identity_digest: str,
        organization_id: str,
        now: datetime,
        expected_admission: AdmissionV2 | None = None,
    ) -> _PreparedExecutionWitness | None:
        """Run policy/inspection preflight for latest or an exact sealed admission.

        Record-bound NX transitions supply ``expected_admission``.  The
        historical record itself remains the authority, but a newer record
        for the same calculation identity may act as an alias only when its
        independently recomputed suitability is equivalent at final guard.
        """
        self._require_utc(now)
        if expected_admission is not None and (
            expected_admission.calculation_identity_digest != calculation_identity_digest
            or expected_admission.admission_digest is None
            or expected_admission.admission_digest != expected_admission.canonical_digest()
        ):
            return None
        with self._lock:
            candidates = tuple(
                record
                for record in self._records.values()
                if record.organization_id == organization_id
                and record.admission.calculation_identity_digest == calculation_identity_digest
            )
            if not candidates:
                return None
            selected = (
                next(
                    (record for record in candidates if record.admission == expected_admission),
                    None,
                )
                if expected_admission is not None
                else candidates[-1]
            )
            if selected is None:
                return None
            request = self._requests.get(selected.request_id)
            if request is None:
                return None
        prepared = self._prepare_for_organization(
            organization_id=organization_id,
            request=request,
            now=now,
        )
        if (
            not isinstance(prepared, _PreparedAssessment)
            or prepared.admission.calculation_identity_digest != calculation_identity_digest
        ):
            return None
        return _PreparedExecutionWitness(selected, prepared, expected_admission)

    def execution_witness_is_current(
        self, *, witness: _PreparedExecutionWitness | None, now: datetime
    ) -> AnalysisAssessmentRecord | None:
        """Finalize a preflight witness using local retained state only."""
        self._require_utc(now)
        if witness is None:
            return None
        with self._coordinator.guarded_read(), self._lock:
            latest = self._records.get(witness.record.request_id)
            if latest != witness.record:
                return None
            current_records = tuple(
                record
                for record in self._records.values()
                if record.organization_id == latest.organization_id
                and record.admission.calculation_identity_digest
                == latest.admission.calculation_identity_digest
            )
            if not current_records:
                return None
            newest = current_records[-1]
            if witness.expected_admission is None:
                if newest != latest:
                    return None
            elif self._suitability_key(newest.admission) != self._suitability_key(
                witness.expected_admission
            ):
                return None
            if not self._prepared_is_locally_current(witness.prepared, now=now):
                return None
            admission = self._finalize_admission(witness.prepared)
            if self._suitability_key(admission) != self._suitability_key(latest.admission):
                return None
            return self._public_record(latest)

    def _prepare(
        self, *, principal: Principal, request: AnalysisAssessmentRequestV2, now: datetime
    ) -> _PreparedAssessment | AdmissionV2:
        return self._prepare_for_organization(
            organization_id=principal.organization_id,
            request=request,
            now=now,
        )

    def _prepare_for_organization(
        self, *, organization_id: str, request: AnalysisAssessmentRequestV2, now: datetime
    ) -> _PreparedAssessment | AdmissionV2:
        try:
            return self._prepare_resolved(
                organization_id=organization_id,
                request=request,
                now=now,
            )
        except _PreflightBlocked as exc:
            return self._blocked(request.request_id, now, exc.reason)

    def _prepare_resolved(
        self, *, organization_id: str, request: AnalysisAssessmentRequestV2, now: datetime
    ) -> _PreparedAssessment:
        blocked = self._preflight_block_reason(organization_id, request)
        if blocked is not None:
            raise _PreflightBlocked(blocked)
        area = self._work_areas.get(request.work_area_id)
        assert area is not None
        baseline = self._resolve_epoch(request.baseline, now=now, epoch="BASELINE")
        current = self._resolve_epoch(request.current, now=now, epoch="CURRENT")
        if baseline is None or current is None:
            raise _PreflightBlocked("ESSENTIAL_INPUT_UNAVAILABLE")
        if baseline.subject == current.subject:
            raise _PreflightBlocked("EPOCH_SUBJECT_NOT_DISTINCT")
        if baseline.capture_ended_at > current.capture_started_at:
            raise _PreflightBlocked("CAPTURE_CHRONOLOGY_INVALID")
        try:
            crs = assert_same_crs(
                assert_supported_project_crs(area.crs),
                assert_supported_project_crs(baseline.horizontal_crs),
                assert_supported_project_crs(current.horizontal_crs),
            )
        except ValueError:
            raise _PreflightBlocked("HORIZONTAL_CRS_UNAVAILABLE_OR_MISMATCH") from None
        if baseline.vertical_reference_digest != current.vertical_reference_digest:
            raise _PreflightBlocked("VERTICAL_REFERENCE_MISMATCH")
        if (
            baseline.raster_extent_bounds is not None
            and current.raster_extent_bounds is not None
            and not _have_positive_area_overlap(
                baseline.raster_extent_bounds, current.raster_extent_bounds
            )
        ):
            raise _PreflightBlocked("EMPTY_COMMON_VALID_COVERAGE")
        identity = self._identity(organization_id, area, baseline, current, crs)
        baseline_evaluation = self._evaluation(identity, baseline, "BASELINE", now)
        current_evaluation = self._evaluation(identity, current, "CURRENT", now)
        evaluations = (baseline_evaluation, current_evaluation)
        if any(item.outcome is EvaluationOutcomeV1.FAIL for item in evaluations):
            disposition = AdmissionDispositionV2.REMEDIATION_REQUIRED
        elif any(item.outcome is EvaluationOutcomeV1.UNAVAILABLE for item in evaluations):
            disposition = AdmissionDispositionV2.BLOCKED
        elif any(item.outcome is EvaluationOutcomeV1.UNASSESSED for item in evaluations):
            disposition = AdmissionDispositionV2.ADMIT_PROVISIONAL
        else:
            disposition = AdmissionDispositionV2.ADMIT_EVALUATED
        admission = AdmissionV2(
            admission_id="admission-" + request.request_id,
            calculation_identity=identity,
            evaluation_revisions=evaluations,
            disposition=disposition,
            reason_codes=tuple(
                sorted({reason for item in evaluations for reason in item.reason_codes})
            ),
            assessed_at=now,
        ).sealed()
        return _PreparedAssessment(area, baseline, current, admission)

    def _preflight_block_reason(
        self, organization_id: str, request: AnalysisAssessmentRequestV2
    ) -> str | None:
        if (
            request.baseline.subject.organization_id != organization_id
            or request.current.subject.organization_id != organization_id
        ):
            return "SUBJECT_OUT_OF_SCOPE"
        if request.baseline.subject.site_id != request.current.subject.site_id:
            return "EPOCH_SITE_MISMATCH"
        area = self._work_areas.get(request.work_area_id)
        if (
            area is None
            or area.status is not WorkAreaStatus.ACTIVE
            or area.site_id != request.baseline.subject.site_id
        ):
            return "WORK_AREA_UNAVAILABLE"
        return None

    def _resolve_epoch(
        self, selection: AnalysisEpochSelectionV2, *, now: datetime, epoch: Epoch
    ) -> _EpochResolved | None:
        revision = self._reconstruction.resolve_sealed_subject(selection.subject)
        if revision is None or revision.manifest is None:
            return None
        dsm_entries = [
            entry for entry in revision.manifest.entries if entry.kind is ProcessingArtifactKind.DSM
        ]
        if len(dsm_entries) != 1:
            return None
        dsm = dsm_entries[0]
        capture = revision.submission.input_declaration
        if (
            capture.capture_started_at is None
            or capture.capture_ended_at is None
            or capture.capture_started_at.tzinfo is None
            or capture.capture_ended_at.tzinfo is None
            or capture.capture_started_at.utcoffset() != UTC.utcoffset(capture.capture_started_at)
            or capture.capture_ended_at.utcoffset() != UTC.utcoffset(capture.capture_ended_at)
        ):
            return None
        snapshot = self._inspections.public_snapshot(selection.subject)
        report = snapshot.report
        if report is None or report.report_digest is None:
            return None
        assert report.report_digest is not None
        outcome = next(
            (
                item
                for item in report.measurement_payload.outcomes
                if item.artifact_id == dsm.artifact_id
            ),
            None,
        )
        if (
            outcome is None
            or outcome.outcome is not ArtifactOutcome.MEASURED
            or outcome.measurements is None
            or outcome.observed_sha256 != "sha256:" + dsm.observed_sha256
            or outcome.measurements.observed_vertical_reference is None
        ):
            return None
        measurements = outcome.measurements
        vertical_reference = measurements.observed_vertical_reference
        assert vertical_reference is not None
        vertical_unit = _observed_vertical_unit(vertical_reference)
        projected_unit = _observed_projected_unit(measurements.observed_crs_identifier)
        if vertical_unit is None or projected_unit is None:
            return None
        # This profile fixes the baseline grid itself.  The current DSM is
        # resampled onto it and may retain its observed affine unchanged.
        a, b, _c, d, e, _f = measurements.transform
        if epoch == "BASELINE" and (b != 0.0 or d != 0.0 or a <= 0.0 or e >= 0.0):
            return None
        evidence_items = tuple(self._evidence.list(revision))
        matching_evidence_present = any(
            item.manifest is not None
            and item.manifest.subject == selection.subject
            and item.manifest.target_dsm_artifact_id == dsm.artifact_id
            and item.manifest.target_dsm_observed_sha256 == "sha256:" + dsm.observed_sha256
            for item in evidence_items
        )
        facts = self._validations.analysis_facts_for_subject_dsm(
            subject=selection.subject,
            target_dsm_artifact_id=dsm.artifact_id,
            target_dsm_observed_sha256="sha256:" + dsm.observed_sha256,
        )
        if len(facts) > _MAX_EVIDENCE_FACTS:
            raise _PreflightBlocked("TOO_MANY_TERMINAL_EVIDENCE_FACTS")
        fact_currentness = self._validations.analysis_fact_currentness(facts, now=now)
        facts_current = all(fact_currentness)
        lifecycles = self._validations.analysis_validation_lifecycles_for_subject_dsm(
            subject=selection.subject,
            target_dsm_artifact_id=dsm.artifact_id,
            target_dsm_observed_sha256="sha256:" + dsm.observed_sha256,
        )
        if len(lifecycles) > _MAX_EVIDENCE_FACTS:
            raise _PreflightBlocked("TOO_MANY_EVIDENCE_VALIDATIONS")
        lifecycles_current = self._validations.analysis_validation_lifecycles_are_locally_current(
            lifecycles, now=now
        )
        matching_evidence_refs = {
            item.evidence_ref
            for item in evidence_items
            if item.manifest is not None
            and item.manifest.subject == selection.subject
            and item.manifest.target_dsm_artifact_id == dsm.artifact_id
            and item.manifest.target_dsm_observed_sha256 == "sha256:" + dsm.observed_sha256
        }
        return _EpochResolved(
            subject=selection.subject,
            revision=revision,
            report=report,
            evidence_items=evidence_items,
            evidence_facts=facts,
            facts_current=facts_current,
            fact_currentness=fact_currentness,
            validation_lifecycles=lifecycles,
            lifecycles_current=lifecycles_current,
            matching_evidence_present=matching_evidence_present,
            unresolved_evidence_present=not matching_evidence_refs.issubset(
                {item.evidence_ref for item in lifecycles}
            ),
            dsm_artifact_id=dsm.artifact_id,
            dsm_observed_sha256="sha256:" + dsm.observed_sha256,
            dsm_observed_size_bytes=dsm.observed_size_bytes,
            raster_extent_bounds=_measured_raster_bounds(
                measurements.transform,
                width=measurements.width,
                height=measurements.height,
            ),
            capture_started_at=capture.capture_started_at,
            capture_ended_at=capture.capture_ended_at,
            transform_digest=_digest({"transform": list(measurements.transform)}),
            transform=measurements.transform,
            horizontal_crs=measurements.observed_crs_identifier,
            horizontal_crs_digest=measurements.observed_crs_digest,
            projected_unit=projected_unit,
            vertical_reference=vertical_reference,
            vertical_reference_digest=vertical_reference.canonical_digest(),
            vertical_unit=vertical_unit[0],
            vertical_unit_provenance=vertical_unit[1],
            input_digest=_digest(
                {
                    "subject": selection.subject.model_dump(by_alias=True, mode="json"),
                    "submission": revision.submission.model_dump(by_alias=True, mode="json"),
                    "manifest": revision.manifest.model_dump(by_alias=True, mode="json"),
                    "dsm": dsm.model_dump(by_alias=True, mode="json"),
                    "inspectionReport": report.model_dump(by_alias=True, mode="json"),
                }
            ),
        )

    def _identity(
        self,
        organization_id: str,
        area: WorkArea,
        baseline: _EpochResolved,
        current: _EpochResolved,
        crs: str,
    ) -> CalculationIdentityV2:
        assert baseline.report.report_digest is not None
        assert current.report.report_digest is not None
        identity_seed = {
            "organizationId": organization_id,
            "siteId": area.site_id,
            "workAreaId": area.work_area_id,
            "baselineInputDigest": baseline.input_digest,
            "currentInputDigest": current.input_digest,
            "policyDigest": self._policy.policy_digest,
            "runtime": asdict(self._runtime),
        }
        return CalculationIdentityV2(
            calculation_id="cal-v2-" + _digest(identity_seed)[7:39],
            organization_id=organization_id,
            site_id=area.site_id,
            work_area_id=area.work_area_id,
            work_area_polygon=area.polygon,
            work_area_crs=crs,
            work_area_definition_digest=_digest(
                {"workAreaId": area.work_area_id, "crs": crs, "polygon": area.polygon}
            ),
            baseline_subject=baseline.subject,
            current_subject=current.subject,
            baseline_capture_started_at=baseline.capture_started_at,
            baseline_capture_ended_at=baseline.capture_ended_at,
            current_capture_started_at=current.capture_started_at,
            current_capture_ended_at=current.capture_ended_at,
            baseline_dsm_artifact_id=baseline.dsm_artifact_id,
            current_dsm_artifact_id=current.dsm_artifact_id,
            baseline_input_digest=baseline.input_digest,
            current_input_digest=current.input_digest,
            baseline_dsm_observed_sha256=baseline.dsm_observed_sha256,
            current_dsm_observed_sha256=current.dsm_observed_sha256,
            baseline_dsm_observed_size_bytes=baseline.dsm_observed_size_bytes,
            current_dsm_observed_size_bytes=current.dsm_observed_size_bytes,
            baseline_observed_crs_identifier=baseline.horizontal_crs,
            current_observed_crs_identifier=current.horizontal_crs,
            baseline_observed_crs_digest=baseline.horizontal_crs_digest,
            current_observed_crs_digest=current.horizontal_crs_digest,
            baseline_projected_unit=baseline.projected_unit,
            current_projected_unit=current.projected_unit,
            baseline_vertical_reference=baseline.vertical_reference,
            current_vertical_reference=current.vertical_reference,
            baseline_vertical_reference_digest=baseline.vertical_reference_digest,
            current_vertical_reference_digest=current.vertical_reference_digest,
            baseline_vertical_unit=baseline.vertical_unit,
            current_vertical_unit=current.vertical_unit,
            baseline_vertical_unit_provenance=baseline.vertical_unit_provenance,
            current_vertical_unit_provenance=current.vertical_unit_provenance,
            baseline_inspection_report_digest=baseline.report.report_digest,
            current_inspection_report_digest=current.report.report_digest,
            baseline_inspection_policy_digest=baseline.report.inspection_policy_digest,
            current_inspection_policy_digest=current.report.inspection_policy_digest,
            baseline_inspector_build_digest=baseline.report.inspector_build_digest,
            current_inspector_build_digest=current.report.inspector_build_digest,
            baseline_transform_digest=baseline.transform_digest,
            current_transform_digest=current.transform_digest,
            baseline_transform=baseline.transform,
            current_transform=current.transform,
            horizontal_crs_digest=baseline.horizontal_crs_digest,
            vertical_reference_digest=baseline.vertical_reference_digest,
            policy=self._policy,
            worker_executable_digest=self._runtime.worker_executable_digest,
            worker_build_digest=self._runtime.worker_build_digest,
            runtime_image_version=self._runtime.runtime_image_version,
            runtime_image_oci_digest=self._runtime.runtime_image_oci_digest,
            dependency_lock_digest=self._runtime.dependency_lock_digest,
        ).sealed()

    def _evaluation(
        self,
        identity: CalculationIdentityV2,
        epoch: _EpochResolved,
        name: Epoch,
        now: datetime,
    ) -> EvaluationV1:
        assert identity.calculation_identity_digest is not None
        facts = tuple(
            EvaluationEvidenceFactV1(
                evidence_ref=fact.evidence_ref,
                context=fact.context,
                terminal_record=fact.terminal_record,
            )
            for fact in epoch.evidence_facts
        )
        outcome: EvaluationOutcomeV1
        reasons: tuple[str, ...]
        current_rejections = tuple(
            fact
            for fact, is_current in zip(epoch.evidence_facts, epoch.fact_currentness, strict=True)
            if is_current and fact.terminal_record.core_verdict is EvidenceCoreVerdict.REJECTED
        )
        if current_rejections:
            outcome = EvaluationOutcomeV1.FAIL
            reasons = tuple(
                sorted(
                    {
                        fact.terminal_record.core_reason or "CHECKPOINT_EVIDENCE_REJECTED"
                        for fact in current_rejections
                    }
                )
            )
        elif (
            not epoch.facts_current
            or not epoch.lifecycles_current
            or epoch.unresolved_evidence_present
            or (epoch.matching_evidence_present and not epoch.validation_lifecycles)
        ):
            outcome, reasons = EvaluationOutcomeV1.UNAVAILABLE, ("EVIDENCE_CONTEXT_UNAVAILABLE",)
        elif any(item.terminal_record is None for item in epoch.validation_lifecycles):
            outcome, reasons = EvaluationOutcomeV1.UNAVAILABLE, ("CHECKPOINT_EVIDENCE_PENDING",)
        elif not epoch.evidence_facts:
            outcome, reasons = EvaluationOutcomeV1.UNASSESSED, ("CHECKPOINT_EVIDENCE_ABSENT",)
        elif any(fact.context.independent_attestation is None for fact in epoch.evidence_facts):
            outcome, reasons = EvaluationOutcomeV1.UNASSESSED, ("CHECKPOINT_NOT_INDEPENDENT",)
        else:
            outcome, reasons = EvaluationOutcomeV1.PASS, ("CHECKPOINT_EVIDENCE_VALIDATED",)
        return EvaluationV1(
            evaluation_id="evaluation-" + epoch.subject.submission_id + "-" + name.lower(),
            calculation_identity_digest=identity.calculation_identity_digest,
            epoch=name,
            revision=1,
            subject=epoch.subject,
            evidence_facts=facts,
            outcome=outcome,
            reason_codes=reasons,
            assessed_at=now,
        ).sealed()

    def _with_revision(
        self, identity: CalculationIdentityV2, evaluation: EvaluationV1
    ) -> EvaluationV1:
        assert identity.calculation_identity_digest is not None
        content = self._evaluation_content_key(evaluation)
        key = (identity.calculation_identity_digest, evaluation.epoch, content)
        existing = self._evaluation_by_content.get(key)
        if existing is not None:
            return existing
        revision = 1 + max(
            (
                item.revision
                for (digest, epoch, _revision), item in self._evaluation_by_revision.items()
                if digest == identity.calculation_identity_digest and epoch == evaluation.epoch
            ),
            default=0,
        )
        return evaluation.model_copy(
            update={"revision": revision, "evaluation_digest": None}
        ).sealed()

    @staticmethod
    def _evaluation_content_key(evaluation: EvaluationV1) -> str:
        return _digest(
            {
                "epoch": evaluation.epoch,
                "subject": evaluation.subject.model_dump(by_alias=True, mode="json"),
                "evidenceFacts": [
                    item.model_dump(by_alias=True, mode="json")
                    for item in evaluation.evidence_facts
                ],
                "outcome": evaluation.outcome.value,
                "reasonCodes": list(evaluation.reason_codes),
            }
        )

    def _prepared_is_locally_current(self, prepared: _PreparedAssessment, *, now: datetime) -> bool:
        """Compare exact preflight snapshots using local-only store predicates."""
        area = self._work_areas.get(prepared.area.work_area_id)
        if area != prepared.area or area is None or area.status is not WorkAreaStatus.ACTIVE:
            return False
        for epoch in (prepared.baseline, prepared.current):
            if self._reconstruction.resolve_sealed_subject(epoch.subject) != epoch.revision:
                return False
            if (
                self._inspections.report_for_locally_current_use(
                    epoch.subject, epoch.report, now=now
                )
                != epoch.report
            ):
                return False
            if tuple(self._evidence.list(epoch.revision)) != epoch.evidence_items:
                return False
            matching_evidence_present = any(
                item.manifest is not None
                and item.manifest.subject == epoch.subject
                and item.manifest.target_dsm_artifact_id == epoch.dsm_artifact_id
                and item.manifest.target_dsm_observed_sha256 == epoch.dsm_observed_sha256
                for item in epoch.evidence_items
            )
            if matching_evidence_present != epoch.matching_evidence_present:
                return False
            facts = self._validations.analysis_facts_for_subject_dsm(
                subject=epoch.subject,
                target_dsm_artifact_id=epoch.dsm_artifact_id,
                target_dsm_observed_sha256=epoch.dsm_observed_sha256,
            )
            if facts != epoch.evidence_facts:
                return False
            fact_currentness = self._validations.analysis_fact_currentness(facts, now=now)
            if (
                fact_currentness != epoch.fact_currentness
                or all(fact_currentness) != epoch.facts_current
            ):
                return False
            lifecycles = self._validations.analysis_validation_lifecycles_for_subject_dsm(
                subject=epoch.subject,
                target_dsm_artifact_id=epoch.dsm_artifact_id,
                target_dsm_observed_sha256=epoch.dsm_observed_sha256,
            )
            if lifecycles != epoch.validation_lifecycles or (
                self._validations.analysis_validation_lifecycles_are_locally_current(
                    lifecycles, now=now
                )
                != epoch.lifecycles_current
            ):
                return False
            matching_evidence_refs = {
                item.evidence_ref
                for item in epoch.evidence_items
                if item.manifest is not None
                and item.manifest.subject == epoch.subject
                and item.manifest.target_dsm_artifact_id == epoch.dsm_artifact_id
                and item.manifest.target_dsm_observed_sha256 == epoch.dsm_observed_sha256
            }
            lifecycle_refs = {item.evidence_ref for item in lifecycles}
            if (
                not matching_evidence_refs.issubset(lifecycle_refs)
            ) != epoch.unresolved_evidence_present:
                return False
        return True

    def _event_for(
        self,
        *,
        organization_id: str,
        request: AnalysisAssessmentRequestV2,
        request_digest: str,
        idempotency_digest: str,
        admission: AdmissionV2,
    ) -> dict[str, object]:
        raw: dict[str, object] = {
            "kind": "external-relative-volume-analysis-assessed",
            "version": _VERSION,
            "organizationId": organization_id,
            "request": request.journal_body(),
            "requestDigest": request_digest,
            "idempotencyDigest": idempotency_digest,
            "admission": admission.model_dump(by_alias=True, mode="json"),
        }
        raw["eventDigest"] = _event_digest(raw)
        return raw

    @staticmethod
    def _suitability_key(admission: AdmissionV2) -> tuple[object, ...]:
        return (
            admission.calculation_identity_digest,
            admission.disposition,
            tuple(
                (
                    evaluation.epoch,
                    evaluation.revision,
                    evaluation.evaluation_digest,
                    evaluation.outcome,
                    evaluation.reason_codes,
                )
                for evaluation in admission.evaluation_revisions
            ),
        )

    @staticmethod
    def _public_record(record: AnalysisAssessmentRecord) -> AnalysisAssessmentRecord:
        """Keep frozen contracts from exposing mutable nested input snapshots."""
        return AnalysisAssessmentRecord(
            request_id=record.request_id,
            organization_id=record.organization_id,
            request_digest=record.request_digest,
            idempotency_digest=record.idempotency_digest,
            admission=record.admission.model_copy(deep=True),
        )

    def _check_idempotency(
        self, organization_id: str, idempotency_digest: str, request_digest: str
    ) -> None:
        existing_id = self._idempotency.get((organization_id, idempotency_digest))
        if existing_id is not None and self._records[existing_id].request_digest != request_digest:
            raise ValueError("idempotency key is already bound to another assessment")

    @staticmethod
    def _blocked(request_id: str, now: datetime, reason: str) -> AdmissionV2:
        return AdmissionV2(
            admission_id="admission-" + request_id,
            calculation_identity=None,
            evaluation_revisions=(),
            disposition=AdmissionDispositionV2.BLOCKED,
            reason_codes=(reason,),
            assessed_at=now,
        ).sealed()

    def _require_site_action(self, principal: Principal) -> None:
        granted = principal_permissions(principal)
        allowed = (
            Permission.ANALYSIS_API_CREATE in granted
            if principal.kind is PrincipalKind.ANALYSIS_MCP_CLIENT
            else Permission.SITES_WRITE in granted
        )
        if not allowed:
            raise PermissionError("analysis assessment requires SITES_WRITE")

    @staticmethod
    def _has_site_read(principal: Principal) -> bool:
        granted = principal_permissions(principal)
        return (
            Permission.ANALYSIS_API_READ in granted
            if principal.kind is PrincipalKind.ANALYSIS_MCP_CLIENT
            else Permission.SITES_READ in granted
        )

    @staticmethod
    def _resource_scope_allows(
        principal: Principal, request: AnalysisAssessmentRequestV2
    ) -> bool:
        if principal.kind is not PrincipalKind.ANALYSIS_MCP_CLIENT:
            return True
        sites = {request.baseline.subject.site_id, request.current.subject.site_id}
        organizations = {
            request.baseline.subject.organization_id,
            request.current.subject.organization_id,
        }
        return (
            organizations == {principal.organization_id}
            and principal.allowed_site_ids is not None
            and sites.issubset(principal.allowed_site_ids)
            and principal.allowed_work_area_ids is not None
            and request.work_area_id in principal.allowed_work_area_ids
        )

    @classmethod
    def _require_resource_scope(
        cls, principal: Principal, request: AnalysisAssessmentRequestV2
    ) -> None:
        if not cls._resource_scope_allows(principal, request):
            raise PermissionError("analysis assessment is outside client scope")

    @staticmethod
    def _require_utc(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("assessment time must be UTC")

    def _apply(self, raw: object, *, mutate: bool = True) -> None:
        try:
            if not isinstance(raw, dict) or raw.get("eventDigest") != _event_digest(raw):
                raise ValueError("event digest is invalid")
            expected = {
                "kind",
                "version",
                "eventDigest",
                "organizationId",
                "request",
                "requestDigest",
                "idempotencyDigest",
                "admission",
            }
            if (
                raw.get("kind") != "external-relative-volume-analysis-assessed"
                or set(raw) != expected
            ):
                raise ValueError("assessment event shape is invalid")
            if raw.get("version") != _VERSION or not isinstance(raw["organizationId"], str):
                raise ValueError("assessment event version or organization is invalid")
            if not isinstance(raw["request"], dict):
                raise ValueError("assessment request is invalid")
            request = AnalysisAssessmentRequestV2.model_validate(
                {**raw["request"], "idempotencyKey": "replayed"}
            )
            if raw["requestDigest"] != request.request_digest():
                raise ValueError("assessment request digest is invalid")
            if (
                not isinstance(raw["idempotencyDigest"], str)
                or _DIGEST_RE.fullmatch(raw["idempotencyDigest"]) is None
            ):
                raise ValueError("assessment idempotency digest is invalid")
            admission = AdmissionV2.model_validate(raw["admission"])
            if (
                admission.admission_digest is None
                or admission.admission_digest != admission.canonical_digest()
            ):
                raise ValueError("assessment admission is unsealed")
            if admission.admission_id != "admission-" + request.request_id:
                raise ValueError("assessment admission request crosslink is invalid")
            identity = admission.calculation_identity
            if identity is not None and (
                identity.organization_id != raw["organizationId"]
                or identity.work_area_id != request.work_area_id
                or identity.baseline_subject != request.baseline.subject
                or identity.current_subject != request.current.subject
            ):
                raise ValueError("assessment calculation identity crosslink is invalid")
            if (
                request.request_id in self._records
                or (raw["organizationId"], raw["idempotencyDigest"]) in self._idempotency
            ):
                raise ValueError("duplicate assessment event")
            pending_evaluations: list[
                tuple[tuple[str, str, str], tuple[str, str, int], EvaluationV1]
            ] = []
            for evaluation in admission.evaluation_revisions:
                content = self._evaluation_content_key(evaluation)
                content_key: tuple[str, str, str] = (
                    evaluation.calculation_identity_digest,
                    evaluation.epoch,
                    content,
                )
                revision_key: tuple[str, str, int] = (
                    evaluation.calculation_identity_digest,
                    evaluation.epoch,
                    evaluation.revision,
                )
                known_content = self._evaluation_by_content.get(content_key)
                known_revision = self._evaluation_by_revision.get(revision_key)
                if known_content is not None and known_content != evaluation:
                    raise ValueError("evaluation content revision is not immutable")
                if known_revision is not None and known_revision != evaluation:
                    raise ValueError("evaluation revision crosslink is not immutable")
                if known_content is None and known_revision is None:
                    expected_revision = 1 + max(
                        (
                            item.revision
                            for (digest, epoch, _), item in self._evaluation_by_revision.items()
                            if digest == evaluation.calculation_identity_digest
                            and epoch == evaluation.epoch
                        ),
                        default=0,
                    )
                    if evaluation.revision != expected_revision:
                        raise ValueError("evaluation revision sequence is invalid")
                elif known_content is None or known_revision is None:
                    raise ValueError("evaluation content and revision indexes disagree")
                pending_evaluations.append((content_key, revision_key, evaluation))
            record = AnalysisAssessmentRecord(
                request_id=request.request_id,
                organization_id=raw["organizationId"],
                request_digest=raw["requestDigest"],
                idempotency_digest=raw["idempotencyDigest"],
                admission=admission,
            )
            if not mutate:
                return
            self._records[record.request_id] = record
            self._requests[record.request_id] = request
            self._idempotency[(record.organization_id, record.idempotency_digest)] = (
                record.request_id
            )
            for content_key, revision_key, evaluation in pending_evaluations:
                self._evaluation_by_content[content_key] = evaluation
                self._evaluation_by_revision[revision_key] = evaluation
        except (KeyError, TypeError, ValueError) as exc:
            raise AnalysisAssessmentRecoveryError(str(exc)) from exc


class _PreflightBlocked(Exception):
    """Internal typed preflight outcome, converted to a durable blocked admission."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
