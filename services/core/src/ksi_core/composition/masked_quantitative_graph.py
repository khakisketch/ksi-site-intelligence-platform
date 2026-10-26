"""Explicit optional masked (P2) lane assembly over the exact common Core graph.

No environment discovery, no implicit activation, no V2 reuse, no default
signing/runtime authority.  A missing config mounts nothing; an invalid
explicit config fails closed.  This factory adds no competing assessment
store: it takes the actual common participants (assessments/sites/
reconstruction/inspections/work areas/coordinator) plus one explicit sealed
config and wires the genuine Core mask lane (ingress, protected bytes,
evidence, V3 calculations) around them.

The wiring additionally returns a narrow sealed-mask byte port
(:class:`MaskSealedBytePort`) for the late delta publication lane.  That
lane is parent-owned: its route binds its own new publication lease and
resolves the source identity plus the mask child itself; the port serves
bounded windows from sealed Core state with no raw paths to the browser.
The masked ``/input/bytes`` endpoint never lends a completed attempt as
delta read permission.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_mask_input import MaskInspectionProfileV1
from ksi_event_contracts.external_masked_execution import (
    MaskedExecutionRuntimeV3,
    masked_execution_runtime_digest,
)
from ksi_event_contracts.external_masked_volume import MaskedRelativeVolumeProfileV3

from ksi_core.domains.external.ingress.external_mask_input_bytes import (
    ExternalMaskInputByteStore,
)
from ksi_core.domains.external.ingress.external_mask_input_core_adapters import (
    CoreMaskProfileActivation,
    CoreMaskReconstructionAuthority,
    masked_inspection_runtime_digest,
)
from ksi_core.domains.external.ingress.external_mask_input_store import (
    ExternalMaskInputStore,
)
from ksi_core.domains.external.quantity.external_masked_calculation_core_adapters import (
    CoreMaskedAdmissionEvidence,
)
from ksi_core.domains.external.quantity.external_masked_calculation_store import (
    ExternalMaskedCalculationStore,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.identity.auth import Principal, PrincipalKind


@dataclass(frozen=True)
class MaskedQuantitativeLocalConfig:
    """Explicit sealed facts for one masked lane.  Nothing is defaulted.

    The masked profile, narrow inspection profile, execution runtime (exact
    five pins), and resource envelope must already be sealed; the worker must
    be the designated ``ANALYSIS_WORKER`` of the lane organization; the
    activation and verification-key files plus the owner-private byte root
    must be explicit absolute owner-controlled paths; the clock is the
    trusted owner-private byte clock shared with the byte store.
    """

    masked_profile: MaskedRelativeVolumeProfileV3
    inspection_profile: MaskInspectionProfileV1
    execution_runtime: MaskedExecutionRuntimeV3
    resource_envelope: ResourceEnvelopeV1
    worker_principal: Principal
    activation_path: Path
    verification_keys_path: Path
    bytes_root: Path
    clock: Callable[[], datetime]

    def __post_init__(self) -> None:
        masked = MaskedRelativeVolumeProfileV3.model_validate(self.masked_profile.model_dump())
        if masked.masked_profile_digest != masked.canonical_digest():
            raise ValueError("masked assembly requires a sealed masked profile")
        inspection = MaskInspectionProfileV1.model_validate(self.inspection_profile.model_dump())
        if inspection.inspection_profile_digest != inspection.canonical_digest():
            raise ValueError("masked assembly requires a sealed narrow inspection profile")
        runtime = MaskedExecutionRuntimeV3.model_validate(self.execution_runtime.model_dump())
        if runtime.runtime_digest != runtime.canonical_digest():
            raise ValueError("masked assembly requires a sealed five-pin execution runtime")
        envelope = ResourceEnvelopeV1.model_validate(self.resource_envelope.model_dump())
        if envelope.resource_envelope_digest != envelope.canonical_digest():
            raise ValueError("masked assembly requires a sealed resource envelope")
        if (
            not isinstance(self.worker_principal, Principal)
            or self.worker_principal.kind is not PrincipalKind.ANALYSIS_WORKER
            or not self.worker_principal.organization_id
        ):
            raise ValueError("masked assembly requires the designated organization worker")
        for label, path in (
            ("activation", self.activation_path),
            ("verification keys", self.verification_keys_path),
            ("byte root", self.bytes_root),
        ):
            if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
                raise ValueError(f"masked assembly {label} path must be an explicit absolute path")
        if not callable(self.clock):
            raise ValueError("masked assembly requires a trusted clock")
        if inspection.resource_envelope_digest != envelope.canonical_digest():
            raise ValueError("masked inspection profile must bind this resource envelope")
        # Closed lane binding: exact five-pin worker plus masked profile,
        # envelope, and narrow inspection profile digests.  Never a V2 runtime.
        masked_execution_runtime_digest(
            runtime,
            masked.canonical_digest(),
            envelope.canonical_digest(),
            inspection.canonical_digest(),
        )
        masked_inspection_runtime_digest(inspection)

    @property
    def masked_profile_digest(self) -> str:
        digest = self.masked_profile.masked_profile_digest
        assert digest is not None
        return digest

    @property
    def inspection_profile_digest(self) -> str:
        digest = self.inspection_profile.inspection_profile_digest
        assert digest is not None
        return digest

    @property
    def organization_id(self) -> str:
        return self.worker_principal.organization_id


class MaskSealedBytePort:
    """Narrow sealed-mask byte access for Core-internal consumers.

    Serves bounded windows from Core-sealed mask state only: the manifest
    resolves through the genuine ingress journal (exact child, never caller
    bytes), the byte identity re-proves through the genuine scoped proof
    (full re-hash under the trusted coordinator guard), and the window reads
    from the server-resolved object with ``O_NOFOLLOW`` plus private-file
    validation.  No path ever leaves Core; HTTP layers base64-encode the
    window.  The late delta publication lane uses
    :meth:`read_slice_by_binding` behind its own new publication lease.
    """

    def __init__(
        self,
        *,
        ingress: ExternalMaskInputStore,
        byte_store: ExternalMaskInputByteStore,
        resource_envelope: ResourceEnvelopeV1,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        if not isinstance(ingress, ExternalMaskInputStore):
            raise ValueError("mask byte port requires the real ingress store")
        if not isinstance(byte_store, ExternalMaskInputByteStore):
            raise ValueError("mask byte port requires the real byte store")
        if ingress.coordinator is not coordinator or byte_store.coordinator is not coordinator:
            raise ValueError("mask byte port must share the common coordinator")
        self._ingress = ingress
        self._bytes = byte_store
        self._envelope = resource_envelope
        self._coordinator = coordinator

    def fetch_manifest(self, *, organization_id: str, mask_child_id: str) -> Any | None:
        return self._ingress.resolve_manifest_by_child(
            organization_id=organization_id, mask_child_id=mask_child_id
        )

    def read_slice(
        self, *, organization_id: str, mask_child_id: str, offset: int, length: int
    ) -> bytes:
        manifest = self._ingress.resolve_manifest_by_child(
            organization_id=organization_id, mask_child_id=mask_child_id
        )
        if manifest is None:
            raise ValueError("mask child has no sealed manifest")
        return self._read_window(
            organization_id=manifest.organization_id,
            site_id=manifest.site_id,
            mask_child_id=manifest.mask_child_id,
            mask_artifact_id=manifest.mask_artifact_id,
            subject_digest=manifest.parent_subject_digest,
            offset=offset,
            length=length,
        )

    def read_slice_by_binding(
        self,
        *,
        organization_id: str,
        mask_artifact_id: str,
        observed_sha256: str,
        observed_size_bytes: int,
        offset: int,
        length: int,
    ) -> bytes:
        """Serve one window for a Core-bound mask capability (delta handoff).

        The caller sends only the opaque artifact binding; the unique sealed
        child resolves through Core-bound ingress state.  Ambiguity, missing
        manifests, or mismatched bytes fail closed.
        """
        child_id = self._ingress.find_child_by_artifact(
            organization_id=organization_id,
            mask_artifact_id=mask_artifact_id,
            observed_sha256=observed_sha256,
        )
        if child_id is None:
            raise ValueError("mask binding resolves to no unique sealed child")
        manifest = self._ingress.resolve_manifest_by_child(
            organization_id=organization_id, mask_child_id=child_id
        )
        if (
            manifest is None
            or manifest.mask_artifact_id != mask_artifact_id
            or manifest.observed_sha256 != observed_sha256
            or manifest.observed_size_bytes != observed_size_bytes
        ):
            raise ValueError("mask binding does not match the sealed manifest")
        return self._read_window(
            organization_id=manifest.organization_id,
            site_id=manifest.site_id,
            mask_child_id=manifest.mask_child_id,
            mask_artifact_id=manifest.mask_artifact_id,
            subject_digest=manifest.parent_subject_digest,
            offset=offset,
            length=length,
        )

    def _read_window(
        self,
        *,
        organization_id: str,
        site_id: str,
        mask_child_id: str,
        mask_artifact_id: str,
        subject_digest: str,
        offset: int,
        length: int,
    ) -> bytes:
        # Owner ``read_slice`` exclusively: proof hash plus window on the SAME
        # bound fd under guard.  No caller path, no browser path, and no
        # absolute ``os.open`` remains in this seam.
        window = self._bytes.read_slice(
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


class MaskSourceNotAdmitted(RuntimeError):
    """A known source cannot yield masked admission (blocked or lane-closed)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class MaskedLaneSourceContext:
    """Genuine declaration-aid resolution over the actual common AP graph.

    Resolves sealed source copies (subjects plus baseline DSM artifact) from
    the real AP assessment witness plus the real baseline anchor, gated by
    the real purpose-separated activation.  Creates no admission, requires
    no V2 numeric report, and returns no caller truth: the Console builds
    only opaque ids plus hash/size from the returned copies, and Core
    rechecks everything at declare/seal/bind time.
    """

    def __init__(
        self,
        *,
        assessments: Any,
        ingress: ExternalMaskInputStore,
        activation: CoreMaskProfileActivation,
        resource_envelope: ResourceEnvelopeV1,
        masked_profile_digest: str,
        inspection_profile: MaskInspectionProfileV1,
    ) -> None:
        if not callable(getattr(assessments, "prepare_execution_witness", None)) or not callable(
            getattr(assessments, "execution_witness_is_current", None)
        ):
            raise ValueError("source context requires the real AP assessment store")
        if not isinstance(ingress, ExternalMaskInputStore):
            raise ValueError("source context requires the real mask ingress store")
        if not isinstance(activation, CoreMaskProfileActivation):
            raise ValueError("source context requires the real mask profile activation")
        sealed_profile = MaskInspectionProfileV1.model_validate(
            inspection_profile.model_dump(by_alias=True)
        )
        if (
            sealed_profile.inspection_profile_digest is None
            or sealed_profile.inspection_profile_digest != sealed_profile.canonical_digest()
        ):
            raise ValueError("source context requires the sealed pinned inspection profile")
        self._assessments = assessments
        self._ingress = ingress
        self._activation = activation
        self._envelope = resource_envelope
        self._masked_profile_digest = masked_profile_digest
        self._inspection_profile = sealed_profile

    def activation_current(self, *, now: datetime) -> bool:
        """The exact lane activation is currently valid (never defaulted)."""
        return self._activation.is_profile_active(
            profile_digest=self._inspection_profile.canonical_digest(),
            resource_envelope_digest=self._envelope.canonical_digest(),
            contained_runtime_digest=masked_inspection_runtime_digest(self._inspection_profile),
            inspector_build_digest=self._inspection_profile.worker_build_digest,
            now=now,
        )

    def resolve_source_context(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        source_calculation_identity_digest: str,
        now: datetime,
    ) -> Any | None:
        """Return sealed declaration-aid copies, or None when unresolvable.

        Raises :class:`MaskSourceNotAdmitted` for a known-but-blocked source
        or a down lane activation (the router maps these to 409, never an
        invented admission).
        """
        from ksi_event_contracts.external_masked_api import MaskSourceContextViewV1
        from ksi_event_contracts.external_relative_volume_analysis import (
            AdmissionDispositionV2,
        )

        witness = self._assessments.prepare_execution_witness(
            calculation_identity_digest=source_calculation_identity_digest,
            organization_id=organization_id,
            now=now,
        )
        current = (
            self._assessments.execution_witness_is_current(witness=witness, now=now)
            if witness is not None
            else None
        )
        if current is None:
            return None
        admission = current.admission
        if admission.disposition not in (
            AdmissionDispositionV2.ADMIT_PROVISIONAL,
            AdmissionDispositionV2.ADMIT_EVALUATED,
        ):
            raise MaskSourceNotAdmitted("SOURCE_NOT_ADMITTED")
        identity = admission.calculation_identity
        if (
            identity is None
            or identity.calculation_identity_digest != source_calculation_identity_digest
            or (identity.organization_id, identity.site_id, identity.work_area_id)
            != (organization_id, site_id, work_area_id)
        ):
            return None
        anchor = self._ingress.resolve_baseline_anchor(
            organization_id=organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            baseline_subject=identity.baseline_subject,
            dsm_artifact_id=identity.baseline_dsm_artifact_id,
        )
        if anchor is None:
            return None
        if not self.activation_current(now=now):
            raise MaskSourceNotAdmitted("MASKED_ACTIVATION_UNAVAILABLE")
        return MaskSourceContextViewV1(
            source_calculation_identity_digest=source_calculation_identity_digest,
            baseline_subject=identity.baseline_subject.model_copy(deep=True),
            current_subject=identity.current_subject.model_copy(deep=True),
            baseline_dsm_artifact_id=identity.baseline_dsm_artifact_id,
            masked_profile_digest=self._masked_profile_digest,
            inspection_profile_digest=self._inspection_profile.canonical_digest(),
            max_mask_bytes=min(self._envelope.max_input_bytes, self._envelope.max_streamed_bytes),
            max_mask_pixels=self._envelope.max_pixels,
            source_disposition=(
                "ADMIT_PROVISIONAL"
                if admission.disposition is AdmissionDispositionV2.ADMIT_PROVISIONAL
                else "ADMIT_EVALUATED"
            ),
            assessed_at=admission.assessed_at,
        )


@dataclass(frozen=True)
class MaskedQuantitativeWiring:
    """The complete optional masked lane, mounted only on explicit config."""

    config: MaskedQuantitativeLocalConfig
    authority: CoreMaskReconstructionAuthority
    profile_activation: CoreMaskProfileActivation
    ingress: ExternalMaskInputStore
    byte_store: ExternalMaskInputByteStore
    evidence: CoreMaskedAdmissionEvidence
    calculations: ExternalMaskedCalculationStore
    mask_bytes: MaskSealedBytePort
    source_context: MaskedLaneSourceContext
    mask_child_journal: DurableJournal
    mask_bytes_journal: DurableJournal
    masked_calc_journal: DurableJournal
    inspection_journal: DurableJournal
    assessments: Any
    sites: Any
    coordinator: ExternalAuthorityCurrentnessCoordinator
    dsm_byte_reader: Any | None = None

    def verify_participants(
        self,
        *,
        assessments: Any,
        sites: Any,
        reconstruction: Any,
        inspections: Any,
        work_areas: Any,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
        dsm_byte_reader: Any | None = None,
    ) -> None:
        """Reject a mount over substituted common stores sharing a coordinator.

        Type checks at construction are not enough: a different store of the
        same class on the same coordinator must fail here.  Every check below
        is exact object identity over the actually inspected authority fields
        (parent-directed), never a digest comparison.
        """
        if (
            self.assessments is not assessments
            or self.sites is not sites
            or self.coordinator is not coordinator
        ):
            raise ValueError("masked lane requires the exact mounted common Core graph")
        authority = self.authority
        if (
            authority._reconstruction is not reconstruction  # noqa: SLF001 -- exact participant identity
            or authority._inspections is not inspections  # noqa: SLF001
            or authority._work_areas is not work_areas  # noqa: SLF001
            or authority._coordinator is not coordinator  # noqa: SLF001
        ):
            raise ValueError("masked authority must wrap the exact mounted common stores")
        activation = self.profile_activation
        if (
            activation._designated_worker != self.config.worker_principal  # noqa: SLF001
            or activation._organization_id != self.config.organization_id  # noqa: SLF001
            or activation._coordinator is not coordinator  # noqa: SLF001
            or activation._pinned_profile.canonical_digest()  # noqa: SLF001
            != self.config.inspection_profile_digest
            or activation._pinned_masked_profile_digest  # noqa: SLF001
            != self.config.masked_profile_digest
        ):
            raise ValueError("masked activation must pin the exact configured lane")
        if (
            self.ingress._reconstruction is not authority  # noqa: SLF001 -- exact lane authority
            or self.ingress._activation is not activation  # noqa: SLF001
            or self.ingress._sealed_bytes is not self.byte_store  # noqa: SLF001
            or self.ingress._coordinator is not coordinator  # noqa: SLF001
        ):
            raise ValueError("masked ingress must be built over the exact lane authority")
        evidence = self.evidence
        if (
            evidence._assessments is not assessments  # noqa: SLF001 -- exact evidence participants
            or evidence._ingress is not self.ingress  # noqa: SLF001
            or evidence._byte_store is not self.byte_store  # noqa: SLF001
            or evidence._coordinator is not coordinator  # noqa: SLF001
        ):
            raise ValueError("masked evidence must bind the exact lane stores")
        if evidence.masked_profile_digest != self.config.masked_profile_digest:
            raise ValueError("masked evidence must pin the configured masked profile")
        if (
            self.evidence.designated_worker != self.config.worker_principal
            or self.calculations.designated_worker != self.config.worker_principal
        ):
            raise ValueError("masked lane must pin the designated organization worker")
        if (
            self.byte_store._coordinator is not coordinator  # noqa: SLF001
            or self.calculations._coordinator is not coordinator  # noqa: SLF001
            or self.calculations._evidence is not evidence  # noqa: SLF001
        ):
            raise ValueError("masked calculations must share the exact lane evidence")
        port = self.mask_bytes
        if (
            port._ingress is not self.ingress  # noqa: SLF001 -- same-module port state
            or port._bytes is not self.byte_store  # noqa: SLF001
        ):
            raise ValueError("masked byte port must serve the exact lane stores")
        if dsm_byte_reader is not None and self.dsm_byte_reader is not dsm_byte_reader:
            raise ValueError("masked lane must use the exact configured DSM byte reader")

    def close(self) -> None:
        try:
            closer = getattr(self.byte_store, "close", None)
            if callable(closer):
                closer()
        finally:
            for journal in (
                self.mask_child_journal,
                self.mask_bytes_journal,
                self.masked_calc_journal,
                self.inspection_journal,
            ):
                journal.close()


def build_masked_quantitative_wiring(
    *,
    journal: Callable[[str], DurableJournal],
    config: MaskedQuantitativeLocalConfig,
    assessments: Any,
    sites: Any,
    reconstruction: Any,
    inspections: Any,
    work_areas: Any,
    coordinator: ExternalAuthorityCurrentnessCoordinator,
    dsm_byte_reader: Any | None = None,
) -> MaskedQuantitativeWiring:
    """Assemble the optional masked lane around the actual common stores.

    No competing AP store is created: the passed ``assessments`` (the real
    ``ExternalRelativeVolumeAnalysisStore``) backs admission evidence, and
    the passed reconstruction/inspection/WorkArea stores back the mask
    ingress authority.  A missing config mounts nothing (the caller simply
    does not call this); an invalid explicit config fails closed, including
    a missing, expired, or purpose-mismatched
    (``MASKED_ANALYSIS_V3``-only, never V2) activation.
    """
    from ksi_core.domains.external.ingress.external_reconstruction import (
        ExternalReconstructionStore,
    )
    from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
        ExternalRelativeVolumeAnalysisStore,
    )
    from ksi_core.domains.sites.sites import SiteStore

    if not isinstance(config, MaskedQuantitativeLocalConfig):
        raise ValueError("masked assembly requires the explicit sealed lane config")
    for name, store, kind in (
        ("assessments", assessments, ExternalRelativeVolumeAnalysisStore),
        ("sites", sites, SiteStore),
        ("reconstruction", reconstruction, ExternalReconstructionStore),
    ):
        if not isinstance(store, kind):
            raise ValueError(f"masked assembly requires the real common {name} store")
    from ksi_core.domains.external.ingress.external_artifact_inspections import (
        ExternalArtifactInspectionStore,
    )
    from ksi_core.domains.sites.work_areas import WorkAreaStore

    if not isinstance(inspections, ExternalArtifactInspectionStore):
        raise ValueError("masked assembly requires the real common inspection store")
    if not isinstance(work_areas, WorkAreaStore):
        raise ValueError("masked assembly requires the real common WorkArea store")
    for name, participant in (
        ("assessments", assessments),
        ("sites", sites),
        ("reconstruction", reconstruction),
        ("inspections", inspections),
        ("work areas", work_areas),
    ):
        if participant.coordinator is not coordinator:
            raise ValueError(f"masked assembly {name} must share the common coordinator")

    envelope = config.resource_envelope
    authority = CoreMaskReconstructionAuthority(
        reconstruction=reconstruction,
        inspections=inspections,
        work_areas=work_areas,
        coordinator=coordinator,
    )
    activation = CoreMaskProfileActivation(
        activation_path=config.activation_path,
        verification_keys_path=config.verification_keys_path,
        organization_id=config.organization_id,
        pinned_profile=config.inspection_profile,
        pinned_masked_profile_digest=config.masked_profile_digest,
        pinned_execution_runtime=config.execution_runtime,
        pinned_envelope=envelope,
        designated_worker=config.worker_principal,
        coordinator=coordinator,
    )
    if not activation.is_profile_active(
        profile_digest=config.inspection_profile_digest,
        resource_envelope_digest=envelope.canonical_digest(),
        contained_runtime_digest=masked_inspection_runtime_digest(config.inspection_profile),
        inspector_build_digest=config.inspection_profile.worker_build_digest,
        now=config.clock(),
    ):
        raise ValueError(
            "masked assembly activation is missing, invalid, expired, or not purpose-bound"
        )
    # Owned journals open inside the guarded region: if the factory or any
    # later construction step fails, every successfully opened journal is
    # closed exactly once (``close`` is idempotent).  Journals owned by the
    # common assembly are never touched here.
    opened: list[DurableJournal] = []
    try:
        mask_bytes_journal = journal("external-mask-input-bytes.jsonl")
        opened.append(mask_bytes_journal)
        mask_child_journal = journal("external-mask-child.jsonl")
        opened.append(mask_child_journal)
        masked_calc_journal = journal("external-masked-calculations.jsonl")
        opened.append(masked_calc_journal)
        inspection_journal = journal("external-mask-inspection-jobs.jsonl")
        opened.append(inspection_journal)
        byte_store = ExternalMaskInputByteStore(
            mask_bytes_journal,
            config.bytes_root,
            resource_envelope=envelope,
            clock=config.clock,
            coordinator=coordinator,
        )
        ingress = ExternalMaskInputStore(
            mask_child_journal,
            resource_envelope=envelope,
            reconstruction_authority=authority,
            profile_activation=activation,
            sealed_bytes=byte_store,
            coordinator=coordinator,
        )
        evidence = CoreMaskedAdmissionEvidence(
            assessments=assessments,
            ingress=ingress,
            byte_store=byte_store,
            masked_profile=config.masked_profile,
            pinned_execution_runtime=config.execution_runtime,
            pinned_inspection_profile_digest=config.inspection_profile_digest,
            resource_envelope=envelope,
            activation_path=config.activation_path,
            verification_keys_path=config.verification_keys_path,
            organization_id=config.organization_id,
            designated_worker=config.worker_principal,
            coordinator=coordinator,
        )
        # The V3 calculation store pins the designated worker explicitly
        # (frozen principal, never the human issuer).  Every fenced worker
        # call must bear it; the human issue path only mints the grant.
        calculations = ExternalMaskedCalculationStore(
            masked_calc_journal,
            evidence=evidence,
            resource_envelope=envelope,
            designated_worker=config.worker_principal,
            coordinator=coordinator,
        )
        evidence.set_identity_resolver(calculations.get_bound_identity)
        port = MaskSealedBytePort(
            ingress=ingress,
            byte_store=byte_store,
            resource_envelope=envelope,
            coordinator=coordinator,
        )
        wiring = MaskedQuantitativeWiring(
            config=config,
            authority=authority,
            profile_activation=activation,
            ingress=ingress,
            byte_store=byte_store,
            evidence=evidence,
            calculations=calculations,
            mask_bytes=port,
            source_context=MaskedLaneSourceContext(
                assessments=assessments,
                ingress=ingress,
                activation=activation,
                resource_envelope=envelope,
                masked_profile_digest=config.masked_profile_digest,
                inspection_profile=config.inspection_profile,
            ),
            mask_child_journal=mask_child_journal,
            mask_bytes_journal=mask_bytes_journal,
            masked_calc_journal=masked_calc_journal,
            inspection_journal=inspection_journal,
            assessments=assessments,
            sites=sites,
            coordinator=coordinator,
            dsm_byte_reader=dsm_byte_reader,
        )
        wiring.verify_participants(
            assessments=assessments,
            sites=sites,
            reconstruction=reconstruction,
            inspections=inspections,
            work_areas=work_areas,
            coordinator=coordinator,
        )
        return wiring
    except BaseException:
        for open_journal in reversed(opened):
            with contextlib.suppress(BaseException):
                open_journal.close()
        raise


__all__ = [
    "MaskSealedBytePort",
    "MaskSourceNotAdmitted",
    "MaskedLaneSourceContext",
    "MaskedQuantitativeLocalConfig",
    "MaskedQuantitativeWiring",
    "build_masked_quantitative_wiring",
]
