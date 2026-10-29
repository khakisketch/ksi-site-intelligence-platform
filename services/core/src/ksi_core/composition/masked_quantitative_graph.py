"""Explicit optional masked (P2) lane assembly over the exact common Core graph.

No environment discovery, no implicit activation, no V2 reuse, no default
signing/runtime authority.  A missing config mounts nothing; an invalid
explicit config fails closed.  This factory adds no competing assessment
store: it takes the actual common participants (assessments/sites/
reconstruction/inspections/work areas/coordinator) plus one explicit sealed
config and wires the genuine Core mask lane (ingress, protected bytes,
evidence, V3 calculations) around them.

The concrete wiring types live in the quantity domain
(``masked_quantitative_wiring``) so domain seams can require them directly;
they are re-exported here so existing composition imports keep resolving to
the identical classes.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from ksi_core.domains.external.ingress.external_mask_input_bytes import (
    ExternalMaskInputByteStore,
)
from ksi_core.domains.external.ingress.external_mask_input_core_adapters import (
    CoreMaskProfileActivation,
    CoreMaskReconstructionAuthority,
    MaskSourceNotAdmitted,
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
from ksi_core.domains.external.quantity.masked_quantitative_wiring import (
    MaskedLaneSourceContext,
    MaskedQuantitativeLocalConfig,
    MaskedQuantitativeWiring,
    MaskSealedBytePort,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal

__all__ = [
    "MaskSealedBytePort",
    "MaskSourceNotAdmitted",
    "MaskedLaneSourceContext",
    "MaskedQuantitativeLocalConfig",
    "MaskedQuantitativeWiring",
    "build_masked_quantitative_wiring",
]


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
