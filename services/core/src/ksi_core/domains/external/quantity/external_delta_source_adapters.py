"""Real Core source/egress adapters for opt-in delta publication.

These do not supply execution or publication authority. In particular a V2
activation cannot authorize the new output worker. Shared composition must
provide a separately verified output policy/runtime and observation authority.
No caller hash, requested grid, or role-created synthetic numeric result is
turned into source evidence by this module.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_relative_volume_analysis import (
    CalculationIdentityV2,
)
from ksi_event_contracts.external_relative_volume_calculation import (
    RelativeVolumeCalculationReportV2,
    RelativeVolumeNumericResultV2,
)

from ksi_core.domains.external.quantity.external_analysis_intents import AnalysisIntentStore
from ksi_core.domains.external.quantity.external_delta_publications import DeltaSourceWitness
from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    ExternalRelativeVolumeAnalysisStore,
)
from ksi_core.domains.external.quantity.external_relative_volume_calculations import (
    CalculationExecutionStatusV2,
    ExternalRelativeVolumeCalculationStore,
)
from ksi_core.domains.sites.sites import SiteStore
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.identity.auth import Principal, PrincipalKind


@dataclass(frozen=True, slots=True)
class DeltaSourceMaterialV1:
    """Exact sealed V2 identity plus its sealed completed report.

    Produced ONLY by :meth:`CoreV2DeltaSourceAdapter.resolve_current_material`
    from genuine Core AP/NX state under the shared coordinator. The worker
    input factory copies these sealed records verbatim into the late-export
    input; it never re-derives grids or invents numeric facts from digests.
    """

    organization_id: str
    site_id: str
    work_area_id: str
    calculation_identity: CalculationIdentityV2
    report: RelativeVolumeCalculationReportV2

    @property
    def numeric_result(self) -> RelativeVolumeNumericResultV2:
        return self.report.numeric_result


class CoreV2DeltaSourceAdapter:
    """Resolve immutable V2 reports against their actual current AP/NX stores.

    Caller identity and AI-egress authorization remain the publication store's
    responsibility. This internal resolver accepts only an exact triple already
    retained in an organization/site/area-bound Core intent and completed report.
    It never requires a V2 report for the independent V3 calculation lane.
    """

    def __init__(
        self,
        *,
        intents: AnalysisIntentStore,
        assessments: ExternalRelativeVolumeAnalysisStore,
        calculations: ExternalRelativeVolumeCalculationStore,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        if (
            not isinstance(intents, AnalysisIntentStore)
            or not isinstance(assessments, ExternalRelativeVolumeAnalysisStore)
            or not isinstance(calculations, ExternalRelativeVolumeCalculationStore)
            or assessments.coordinator is not coordinator
            or calculations._coordinator is not coordinator
            or calculations._assessments is not assessments
        ):
            raise ValueError("delta source requires the exact common AP/NX participants")
        self.coordinator = coordinator
        self._intents = intents
        self._assessments = assessments
        self._calculations = calculations

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
        with self.coordinator.guarded_read():
            for intent in self._intents.list(organization_id=organization_id, site_id=site_id):
                if intent.work_area_id != work_area_id or intent.calculation_request_id is None:
                    continue
                record = self._calculations.get_history(
                    intent.calculation_request_id,
                    organization_id=organization_id,
                )
                if (
                    record is None
                    or record.status is not CalculationExecutionStatusV2.COMPLETED
                    or record.report is None
                    or record.calculation_identity_digest != source_calculation_identity_digest
                ):
                    continue
                report = record.report
                numeric = report.numeric_result
                coverage = numeric.coverage
                identity = record.admission.calculation_identity
                if (
                    identity is None
                    or identity.organization_id != organization_id
                    or identity.site_id != site_id
                    or identity.work_area_id != work_area_id
                    or identity.canonical_digest() != source_calculation_identity_digest
                    or report.numeric_result_identity_digest
                    != source_numeric_result_identity_digest
                    or numeric.numeric_result_identity_digest
                    != source_numeric_result_identity_digest
                    or coverage.coverage_witness_digest != source_coverage_witness_digest
                ):
                    continue
                witness = self._assessments.prepare_execution_witness(
                    calculation_identity_digest=source_calculation_identity_digest,
                    organization_id=organization_id,
                    now=now,
                )
                consulted = self._assessments.execution_witness_is_current(witness=witness, now=now)
                if consulted is None or not self._calculations._admission_can_execute(
                    consulted.admission
                ):
                    return None
                a, b, c, d, e, f = identity.baseline_transform
                transform = (
                    float(a),
                    float(b),
                    float(c + a * coverage.column_offset + b * coverage.row_offset),
                    float(d),
                    float(e),
                    float(f + d * coverage.column_offset + e * coverage.row_offset),
                )
                transform_digest = (
                    "sha256:"
                    + hashlib.sha256(
                        canonical_json_bytes({"transform": list(transform)})
                    ).hexdigest()
                )
                return DeltaSourceWitness(
                    organization_id=organization_id,
                    site_id=site_id,
                    work_area_id=work_area_id,
                    source_contract_version="external-relative-volume-calculation-report.v2",
                    source_calculation_identity_digest=source_calculation_identity_digest,
                    source_numeric_result_identity_digest=source_numeric_result_identity_digest,
                    source_coverage_witness_digest=source_coverage_witness_digest,
                    grid_rows=coverage.rows,
                    grid_columns=coverage.columns,
                    transform=transform,
                    transform_digest=transform_digest,
                    grid_crs_identifier=identity.baseline_observed_crs_identifier,
                    grid_crs_digest=identity.horizontal_crs_digest,
                    bounds=coverage.bounds,
                )
        return None

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
    ) -> DeltaSourceMaterialV1 | None:
        """Return the exact sealed identity plus its sealed numeric report.

        Narrow additive seam for the late-export output job: the same actual
        intents → NX COMPLETED report → fresh AP witness chain as
        :meth:`resolve_current_source`, but projecting the full
        ``(CalculationIdentityV2, RelativeVolumeCalculationReportV2)`` the
        worker needs to re-measure, instead of only the witness grid. All
        checks run under the shared currentness coordinator; bare caller
        hashes, synthetic numeric results, or a caller-supplied Principal
        never become material. A revoked/expired source, a non-COMPLETED
        record, a digest mismatch, or a non-admitted AP witness returns
        ``None``. The old NX numeric state is never mutated here.
        """
        with self.coordinator.guarded_read():
            for intent in self._intents.list(organization_id=organization_id, site_id=site_id):
                if intent.work_area_id != work_area_id or intent.calculation_request_id is None:
                    continue
                record = self._calculations.get_history(
                    intent.calculation_request_id,
                    organization_id=organization_id,
                )
                if (
                    record is None
                    or record.status is not CalculationExecutionStatusV2.COMPLETED
                    or record.report is None
                    or record.calculation_identity_digest != source_calculation_identity_digest
                ):
                    continue
                report = record.report
                numeric = report.numeric_result
                identity = record.admission.calculation_identity
                if (
                    identity is None
                    or identity.organization_id != organization_id
                    or identity.site_id != site_id
                    or identity.work_area_id != work_area_id
                    or identity.canonical_digest() != source_calculation_identity_digest
                    or report.numeric_result_identity_digest
                    != source_numeric_result_identity_digest
                    or numeric.numeric_result_identity_digest
                    != source_numeric_result_identity_digest
                    or numeric.canonical_digest() != source_numeric_result_identity_digest
                    or numeric.coverage.coverage_witness_digest != source_coverage_witness_digest
                    or numeric.coverage.canonical_digest() != source_coverage_witness_digest
                ):
                    continue
                witness = self._assessments.prepare_execution_witness(
                    calculation_identity_digest=source_calculation_identity_digest,
                    organization_id=organization_id,
                    now=now,
                )
                consulted = self._assessments.execution_witness_is_current(witness=witness, now=now)
                if consulted is None or not self._calculations._admission_can_execute(
                    consulted.admission
                ):
                    return None
                return DeltaSourceMaterialV1(
                    organization_id=organization_id,
                    site_id=site_id,
                    work_area_id=work_area_id,
                    calculation_identity=identity,
                    report=report,
                )
        return None


class CoreDeltaEgressAdapter:
    """Consult the genuine scoped Site consent and retain caller scope limits.

    Machine AI consumers require explicit Site consent; ordinary human reads
    do not acquire an artificial AI-consent prerequisite. An HTTP operator
    purpose header does not impersonate the dedicated machine identity, following
    the incumbent Analysis API's authenticated-identity consent boundary.
    """

    def __init__(self, *, sites: SiteStore) -> None:
        if not isinstance(sites, SiteStore):
            raise ValueError("delta egress requires the actual Core Site store")
        self._sites = sites

    def is_egress_allowed(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        principal: Principal,
        now: datetime,
    ) -> bool:
        if (
            principal.organization_id != organization_id
            or principal.allowed_site_ids is not None
            and site_id not in principal.allowed_site_ids
            or principal.allowed_work_area_ids is not None
            and work_area_id not in principal.allowed_work_area_ids
        ):
            return False
        site = self._sites.get_scoped(site_id, organization_id)
        if site is None:
            return False
        return bool(
            principal.kind
            not in {
                PrincipalKind.ANALYSIS_MCP_CLIENT,
                PrincipalKind.SPATIAL_DATA_MCP_CLIENT,
            }
            or site.ai_egress_allowed
        )
