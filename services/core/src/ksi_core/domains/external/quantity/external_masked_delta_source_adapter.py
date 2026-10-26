"""Separate V3 source resolver; never borrows a completed V2 numeric identity."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict, Unpack

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_masked_volume import MaskedCalculationIdentityV3
from ksi_event_contracts.external_masked_volume_result import MaskedVolumeCalculationReportV3

from ksi_core.domains.external.quantity.external_delta_publications import DeltaSourceWitness
from ksi_core.domains.external.quantity.external_delta_source_adapters import (
    CoreV2DeltaSourceAdapter,
)
from ksi_core.domains.external.quantity.external_masked_calculation_store import (
    ExternalMaskedCalculationStore,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator


@dataclass(frozen=True)
class MaskedDeltaSourceMaterialV3:
    masked_calculation_identity: MaskedCalculationIdentityV3
    report: MaskedVolumeCalculationReportV3


class CoreMaskedDeltaSourceAdapter:
    def __init__(
        self,
        *,
        calculations: ExternalMaskedCalculationStore,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        if (
            not isinstance(calculations, ExternalMaskedCalculationStore)
            or calculations.coordinator is not coordinator
        ):
            raise ValueError("V3 delta source requires the exact common masked calculation store")
        self.calculations, self.coordinator = calculations, coordinator

    def resolve_current_material(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        source_calculation_identity_digest: str,
        source_numeric_result_identity_digest: str,
        source_coverage_witness_digest: str,
        now: datetime,
    ) -> MaskedDeltaSourceMaterialV3 | None:
        with self.coordinator.guarded_read():
            resolved = self.calculations.resolve_completed_source(
                organization_id=organization_id,
                masked_calculation_identity_digest=source_calculation_identity_digest,
                numeric_result_identity_digest=source_numeric_result_identity_digest,
                coverage_witness_digest=source_coverage_witness_digest,
                now=now,
            )
            if resolved is None:
                return None
            record, witness = resolved
            identity, report = witness.source_identity, record.report
            if report is None or (
                identity.organization_id,
                identity.site_id,
                identity.work_area_id,
            ) != (organization_id, site_id, work_area_id):
                return None
            if identity.canonical_digest() != source_calculation_identity_digest:
                return None
            return MaskedDeltaSourceMaterialV3(
                identity.model_copy(deep=True), report.model_copy(deep=True)
            )

    def resolve_current_source(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        source_calculation_identity_digest: str,
        source_numeric_result_identity_digest: str,
        source_coverage_witness_digest: str,
        now: datetime,
    ) -> DeltaSourceWitness | None:
        material = self.resolve_current_material(
            organization_id=organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            source_calculation_identity_digest=source_calculation_identity_digest,
            source_numeric_result_identity_digest=source_numeric_result_identity_digest,
            source_coverage_witness_digest=source_coverage_witness_digest,
            now=now,
        )
        if material is None:
            return None
        identity = material.masked_calculation_identity.source_calculation_identity
        coverage = material.report.numeric_result.coverage
        a, b, c, d, e, f = identity.baseline_transform
        transform = (
            float(a),
            float(b),
            float(c + a * coverage.column_offset + b * coverage.row_offset),
            float(d),
            float(e),
            float(f + d * coverage.column_offset + e * coverage.row_offset),
        )
        return DeltaSourceWitness(
            organization_id=organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            source_contract_version="external-masked-volume-calculation-identity.v3",
            source_calculation_identity_digest=source_calculation_identity_digest,
            source_numeric_result_identity_digest=source_numeric_result_identity_digest,
            source_coverage_witness_digest=source_coverage_witness_digest,
            grid_rows=coverage.rows,
            grid_columns=coverage.columns,
            transform=transform,
            transform_digest="sha256:"
            + hashlib.sha256(
                canonical_json_bytes({"transform": list(transform)}),
            ).hexdigest(),
            grid_crs_identifier=identity.baseline_observed_crs_identifier,
            grid_crs_digest=identity.horizontal_crs_digest,
            bounds=coverage.bounds,
        )


class _SourceLookup(TypedDict):
    organization_id: str
    site_id: str
    work_area_id: str
    source_calculation_identity_digest: str
    source_numeric_result_identity_digest: str
    source_coverage_witness_digest: str
    now: datetime


class CoreVersionedDeltaSourceAdapter:
    """Route only genuine independently owned V2/V3 records; ambiguity denies.

    The source version comes from the matched Core record, never a caller
    parameter. V2 late-input issuance keeps its V2-only material resolver;
    V3 late inputs have their own three-input material/transport contract.
    """

    def __init__(
        self,
        *,
        v2: CoreV2DeltaSourceAdapter,
        v3: CoreMaskedDeltaSourceAdapter,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        if (
            not isinstance(v2, CoreV2DeltaSourceAdapter)
            or not isinstance(v3, CoreMaskedDeltaSourceAdapter)
            or v2.coordinator is not coordinator
            or v3.coordinator is not coordinator
        ):
            raise ValueError("versioned delta sources require the exact common V2/V3 adapters")
        self.v2, self.v3, self.coordinator = v2, v3, coordinator

    def resolve_current_source(self, **query: Unpack[_SourceLookup]) -> DeltaSourceWitness | None:
        with self.coordinator.guarded_read():
            matches = [
                source
                for adapter in (self.v2, self.v3)
                if (source := adapter.resolve_current_source(**query)) is not None
            ]
            return matches[0] if len(matches) == 1 else None
