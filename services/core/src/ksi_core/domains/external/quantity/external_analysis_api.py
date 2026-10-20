"""Selector-only public facade over the AP suitability and NX execution records."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_analysis_activation import AnalysisActivationV1
from ksi_event_contracts.external_analysis_api import (
    AnalysisAuthorityReferencesV1,
    AnalysisBlockerV1,
    AnalysisCalculationIdentityEvidenceV1,
    AnalysisEpochEvidenceV1,
    AnalysisEvaluationEvidenceFactV1,
    AnalysisEvaluationEvidenceV1,
    AnalysisEvidenceReferenceV1,
    AnalysisEvidenceViewV1,
    AnalysisExecutionStateV1,
    AnalysisListV1,
    AnalysisMetricsV1,
    AnalysisObservationOptionsV1,
    AnalysisObservationOptionV1,
    AnalysisObservationSelectorV1,
    AnalysisPolicyEvidenceV1,
    AnalysisResultV1,
    AnalysisRuntimeEvidenceV1,
    AnalysisSuitabilityStateV1,
    AnalysisViewV1,
    CreateAnalysisRequestV1,
)
from ksi_event_contracts.external_analysis_api_v2 import (
    AnalysisAuthorityEvidenceItemV2,
    AnalysisCalculationEvidenceItemV2,
    AnalysisCheckpointEvidenceItemV2,
    AnalysisCoverageSummaryV2,
    AnalysisEpochEvidenceItemV2,
    AnalysisEvaluationEvidenceItemV2,
    AnalysisEvidenceItemV2,
    AnalysisEvidencePageV2,
    AnalysisLimitationEvidenceItemV2,
    AnalysisListItemV2,
    AnalysisListPageV2,
    AnalysisNumericResultEvidenceItemV2,
    AnalysisReferenceEvidenceItemV2,
    AnalysisResultSummaryV2,
    AnalysisViewV2,
)
from ksi_event_contracts.external_artifact_validation import (
    ObservedVerticalReferenceV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_evidence import EvidenceCoreVerdict
from ksi_event_contracts.external_relative_volume_analysis import (
    AdmissionDispositionV2,
    EvaluationOutcomeV1,
)
from ksi_event_contracts.external_relative_volume_calculation import (
    RelativeVolumeCoverageWitnessV2,
)

from ksi_core.domains.external.ingress.external_reconstruction import (
    build_external_reconstruction_submission_ref,
)
from ksi_core.domains.external.quantity.external_analysis_intents import (
    AnalysisIntentStore,
    PublicAnalysisIntent,
)
from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    AnalysisAssessmentRequestV2,
    AnalysisEpochSelectionV2,
)
from ksi_core.domains.external.quantity.external_relative_volume_calculations import (
    CalculationCurrentDispositionV2,
    CalculationExecutionStatusV2,
)
from ksi_core.identity.auth import (
    Permission,
    Principal,
    PrincipalKind,
    principal_permissions,
    require_permission_any,
)


class AnalysisScopeNotFound(LookupError):
    """Use one non-disclosing error for missing or foreign path/selector resources."""


class AnalysisSnapshotChanged(RuntimeError):
    """Bounded V2 reads could not capture one coherent AP/NX projection."""


class _AnalysisAdmissionPort(Protocol):
    @property
    def admission_id(self) -> str: ...

    @property
    def admission_digest(self) -> str | None: ...

    @property
    def calculation_identity_digest(self) -> str | None: ...

    @property
    def disposition(self) -> AdmissionDispositionV2: ...

    @property
    def reason_codes(self) -> tuple[str, ...]: ...

    @property
    def calculation_identity(self) -> _AnalysisCalculationIdentityPort | None: ...

    @property
    def evaluation_revisions(self) -> tuple[_AnalysisEvaluationPort, ...]: ...


class _AnalysisEvaluationContextPort(Protocol):
    @property
    def context_id(self) -> str: ...

    @property
    def context_digest(self) -> str | None: ...

    @property
    def evidence_manifest_digest(self) -> str: ...


class _AnalysisEvaluationRecordPort(Protocol):
    @property
    def evidence_record_id(self) -> str: ...

    @property
    def evidence_record_digest(self) -> str | None: ...

    @property
    def core_verdict(self) -> EvidenceCoreVerdict: ...


class _AnalysisEvaluationFactPort(Protocol):
    @property
    def evidence_ref(self) -> str: ...

    @property
    def context(self) -> _AnalysisEvaluationContextPort: ...

    @property
    def terminal_record(self) -> _AnalysisEvaluationRecordPort: ...


class _AnalysisEvaluationPort(Protocol):
    @property
    def evaluation_id(self) -> str: ...

    @property
    def epoch(self) -> Literal["BASELINE", "CURRENT"]: ...

    @property
    def revision(self) -> int: ...

    @property
    def evaluation_digest(self) -> str | None: ...

    @property
    def outcome(self) -> EvaluationOutcomeV1: ...

    @property
    def reason_codes(self) -> tuple[str, ...]: ...

    @property
    def assessed_at(self) -> datetime: ...

    @property
    def evidence_facts(self) -> tuple[_AnalysisEvaluationFactPort, ...]: ...


class _AnalysisPolicyIdentityPort(Protocol):
    @property
    def policy_id(self) -> str: ...

    @property
    def version(self) -> int: ...

    @property
    def profile_id(self) -> str: ...

    @property
    def profile_digest(self) -> str: ...

    @property
    def algorithm_digest(self) -> str: ...

    @property
    def config_digest(self) -> str: ...

    @property
    def policy_digest(self) -> str | None: ...


class _AnalysisCalculationIdentityPort(Protocol):
    @property
    def calculation_id(self) -> str: ...

    @property
    def work_area_definition_digest(self) -> str: ...

    @property
    def baseline_subject(self) -> SealedExternalSubjectV1: ...

    @property
    def current_subject(self) -> SealedExternalSubjectV1: ...

    @property
    def baseline_dsm_artifact_id(self) -> str: ...

    @property
    def current_dsm_artifact_id(self) -> str: ...

    @property
    def baseline_dsm_observed_sha256(self) -> str: ...

    @property
    def current_dsm_observed_sha256(self) -> str: ...

    @property
    def baseline_dsm_observed_size_bytes(self) -> int: ...

    @property
    def current_dsm_observed_size_bytes(self) -> int: ...

    @property
    def baseline_observed_crs_identifier(self) -> str: ...

    @property
    def current_observed_crs_identifier(self) -> str: ...

    @property
    def baseline_observed_crs_digest(self) -> str: ...

    @property
    def current_observed_crs_digest(self) -> str: ...

    @property
    def baseline_vertical_reference(self) -> ObservedVerticalReferenceV1: ...

    @property
    def current_vertical_reference(self) -> ObservedVerticalReferenceV1: ...

    @property
    def baseline_vertical_unit(self) -> str: ...

    @property
    def current_vertical_unit(self) -> str: ...

    @property
    def baseline_transform(self) -> tuple[float, float, float, float, float, float]: ...

    @property
    def current_transform(self) -> tuple[float, float, float, float, float, float]: ...

    @property
    def baseline_transform_digest(self) -> str: ...

    @property
    def current_transform_digest(self) -> str: ...

    @property
    def baseline_inspection_report_digest(self) -> str: ...

    @property
    def current_inspection_report_digest(self) -> str: ...

    @property
    def baseline_input_digest(self) -> str: ...

    @property
    def current_input_digest(self) -> str: ...

    @property
    def policy(self) -> _AnalysisPolicyIdentityPort: ...

    @property
    def worker_executable_digest(self) -> str: ...

    @property
    def worker_build_digest(self) -> str: ...

    @property
    def runtime_image_version(self) -> str: ...

    @property
    def runtime_image_oci_digest(self) -> str: ...

    @property
    def dependency_lock_digest(self) -> str: ...


class _AnalysisAssessmentRecordPort(Protocol):
    @property
    def admission(self) -> _AnalysisAdmissionPort: ...


class _AnalysisAssessmentPort(Protocol):
    def get_history(
        self, request_id: str, *, organization_id: str
    ) -> _AnalysisAssessmentRecordPort | None: ...

    def get_history_for_principal(
        self, request_id: str, *, principal: Principal
    ) -> _AnalysisAssessmentRecordPort | None: ...

    def get_current(
        self, request_id: str, *, principal: Principal, now: datetime
    ) -> _AnalysisAssessmentRecordPort | None: ...

    def get_current_for_read(
        self, request_id: str, *, principal: Principal, now: datetime
    ) -> _AnalysisAssessmentRecordPort | None: ...

    def assess_and_record(
        self, *, principal: Principal, request: AnalysisAssessmentRequestV2, now: datetime
    ) -> _AnalysisAssessmentRecordPort: ...


class _AnalysisAuthorizationPort(Protocol):
    @property
    def authorization_id(self) -> str: ...


class _AnalysisMetricsPort(Protocol):
    @property
    def cut_m3(self) -> float: ...

    @property
    def fill_m3(self) -> float: ...

    @property
    def net_m3(self) -> float: ...

    @property
    def threshold_m(self) -> float: ...


class _AnalysisNumericResultPort(Protocol):
    @property
    def metrics(self) -> _AnalysisMetricsPort: ...

    @property
    def coverage(self) -> RelativeVolumeCoverageWitnessV2: ...


class _AnalysisReportPort(Protocol):
    @property
    def report_id(self) -> str: ...

    @property
    def report_digest(self) -> str | None: ...

    @property
    def numeric_result_identity_digest(self) -> str | None: ...

    @property
    def computed_at(self) -> datetime: ...

    @property
    def numeric_result(self) -> _AnalysisNumericResultPort: ...


class _AnalysisFailurePort(Protocol):
    @property
    def reason_code(self) -> str: ...

    @property
    def failure_digest(self) -> str | None: ...


class _AnalysisCalculationRecordPort(Protocol):
    @property
    def request_id(self) -> str: ...

    @property
    def organization_id(self) -> str: ...

    @property
    def calculation_identity_digest(self) -> str: ...

    @property
    def status(self) -> CalculationExecutionStatusV2: ...

    @property
    def authorization(self) -> _AnalysisAuthorizationPort: ...

    @property
    def report(self) -> _AnalysisReportPort | None: ...

    @property
    def failure(self) -> _AnalysisFailurePort | None: ...


class _AnalysisCurrentViewPort(Protocol):
    @property
    def disposition(self) -> CalculationCurrentDispositionV2: ...

    @property
    def report(self) -> _AnalysisReportPort | None: ...


class _AnalysisCalculationPort(Protocol):
    def get_history(
        self, request_id: str, *, organization_id: str
    ) -> _AnalysisCalculationRecordPort | None: ...

    def issue(
        self,
        *,
        principal: Principal,
        request_id: str,
        calculation_identity_digest: str,
        idempotency_key: str,
        now: datetime,
    ) -> _AnalysisCalculationRecordPort: ...

    def get_current(
        self, *, request_id: str, principal: Principal, now: datetime
    ) -> _AnalysisCurrentViewPort | None: ...


class _AnalysisPublicRoutePort(Protocol):
    def external_ai_egress_allowed(self, *, principal: Principal, site_id: str) -> bool: ...

    def observation_options(
        self, *, principal: Principal, site_id: str
    ) -> AnalysisObservationOptionsV1: ...

    def create_or_resume(
        self,
        *,
        principal: Principal,
        site_id: str,
        work_area_id: str,
        request: CreateAnalysisRequestV1,
        idempotency_key: str,
        now: datetime,
    ) -> AnalysisViewV1: ...

    def list(self, *, principal: Principal, site_id: str, now: datetime) -> AnalysisListV1: ...

    def get(
        self, *, principal: Principal, site_id: str, analysis_id: str, now: datetime
    ) -> AnalysisViewV1 | None: ...

    def evidence(
        self, *, principal: Principal, site_id: str, analysis_id: str, now: datetime
    ) -> AnalysisEvidenceViewV1 | None: ...

    def create_v2(
        self,
        *,
        principal: Principal,
        site_id: str,
        work_area_id: str,
        request: CreateAnalysisRequestV1,
        idempotency_key: str,
        now: datetime,
    ) -> AnalysisViewV2: ...

    def list_v2(
        self,
        *,
        principal: Principal,
        site_id: str,
        now: datetime,
        limit: int,
        cursor: str | None,
    ) -> AnalysisListPageV2: ...

    def get_v2(
        self, *, principal: Principal, site_id: str, analysis_id: str, now: datetime
    ) -> AnalysisViewV2 | None: ...

    def evidence_v2(
        self,
        *,
        principal: Principal,
        site_id: str,
        analysis_id: str,
        now: datetime,
        limit: int,
        cursor: str | None,
    ) -> AnalysisEvidencePageV2 | None: ...

    def coverage_resource_v2(
        self, *, principal: Principal, site_id: str, analysis_id: str, now: datetime
    ) -> tuple[bytes, str] | None: ...


@dataclass(frozen=True, slots=True)
class _ResolvedSelector:
    selector: AnalysisObservationSelectorV1
    subject: SealedExternalSubjectV1 | None
    blocker: AnalysisBlockerV1 | None


def _digest_payload(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _encode_cursor(value: dict[str, Any]) -> str:
    payload = canonical_json_bytes(value)
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        value = json.loads(raw)
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("ANALYSIS_CURSOR_INVALID") from exc
    if not isinstance(value, dict):
        raise ValueError("ANALYSIS_CURSOR_INVALID")
    return value


def _evidence_revision(evidence: AnalysisEvidenceViewV1) -> int:
    return max((evaluation.revision for evaluation in evidence.evaluations), default=1)


def _same_analysis_snapshot(view: AnalysisViewV1, evidence: AnalysisEvidenceViewV1) -> bool:
    return (
        evidence.analysis_id == view.analysis_id
        and evidence.authority == view.authority
        and evidence.result == view.result
        and evidence.evidence_refs == view.evidence_refs
        and (evidence.baseline is None or evidence.baseline.selector == view.baseline)
        and (evidence.current is None or evidence.current.selector == view.current)
    )


class ExternalAnalysisFacade:
    """Compose AP/NX under public intent identity without creating policy or numbers."""

    def __init__(
        self,
        *,
        intents: AnalysisIntentStore,
        assessments: _AnalysisAssessmentPort,
        calculations: _AnalysisCalculationPort,
        reconstructions: Any,
        sites: Any,
        work_areas: Any,
        work_orders: Any | None = None,
    ) -> None:
        self._intents = intents
        self._assessments = assessments
        self._calculations = calculations
        self._reconstructions = reconstructions
        self._sites = sites
        self._work_areas = work_areas
        self._work_orders = work_orders

    def observation_options(
        self, *, principal: Principal, site_id: str
    ) -> AnalysisObservationOptionsV1:
        """List only Site-scoped selector facts with an actual opaque ref."""
        self._require(principal, Permission.SITES_READ)
        self._require_site_grant(principal, site_id)
        if self._sites.get_scoped(site_id, principal.organization_id) is None:
            raise AnalysisScopeNotFound("ANALYSIS_RESOURCE_NOT_FOUND")
        if self._work_orders is None:
            raise RuntimeError("analysis observation options require the work-order store")
        options: list[AnalysisObservationOptionV1] = []
        for order in self._work_orders.list_for_site(
            site_id, organization_id=principal.organization_id
        ):
            if (
                principal.allowed_work_area_ids is not None
                and not self._has_work_area_grants(principal, order.work_area_ids)
            ):
                continue
            for revision in self._reconstructions.list(
                order.work_order_id,
                organization_id=principal.organization_id,
                site_id=site_id,
            ):
                capture = revision.submission.input_declaration
                start = capture.capture_started_at
                end = capture.capture_ended_at
                # Historic registrations may omit/invert a capture window;
                # they are not valid selectable epoch facts for this API.
                if (
                    start is None
                    or end is None
                    or start.tzinfo is None
                    or end.tzinfo is None
                    or start.utcoffset() != UTC.utcoffset(start)
                    or end.utcoffset() != UTC.utcoffset(end)
                    or start >= end
                ):
                    continue
                options.append(
                    AnalysisObservationOptionV1(
                        selector=AnalysisObservationSelectorV1(
                            work_order_id=revision.work_order_id,
                            submission_ref=build_external_reconstruction_submission_ref(
                                organization_id=principal.organization_id,
                                work_order_id=revision.work_order_id,
                                submission_id=revision.submission.submission_id,
                            ),
                            revision=revision.submission.revision,
                        ),
                        observation_epoch_id=revision.observation_epoch_id,
                        capture_started_at=start,
                        capture_ended_at=end,
                    )
                )
        return AnalysisObservationOptionsV1(
            items=tuple(
                sorted(
                    options,
                    key=lambda item: (
                        item.capture_ended_at,
                        item.selector.work_order_id,
                        item.selector.submission_ref,
                        item.selector.revision,
                    ),
                    reverse=True,
                )[:500]
            )
        )

    def create_or_resume(
        self,
        *,
        principal: Principal,
        site_id: str,
        work_area_id: str,
        request: CreateAnalysisRequestV1,
        idempotency_key: str,
        now: datetime,
    ) -> AnalysisViewV1:
        self._require(principal, Permission.SITES_WRITE)
        self._require_path(principal, site_id, work_area_id)
        if not self._selectors_are_in_scope(
            principal, site_id, (request.baseline, request.current)
        ):
            raise AnalysisScopeNotFound("ANALYSIS_RESOURCE_NOT_FOUND")
        existing = self._intents.get_by_idempotency(
            organization_id=principal.organization_id, idempotency_key=idempotency_key
        )
        if existing is not None:
            if (
                existing.site_id != site_id
                or existing.work_area_id != work_area_id
                or existing.baseline != request.baseline
                or existing.current != request.current
            ):
                raise ValueError("idempotency key is already bound to another analysis request")
            # POST, unlike GET, is the explicit recovery action.  It may
            # continue a durable intent that crashed between its append, AP,
            # and NX without creating a replacement assessment.
            return self._resume(existing, principal=principal, now=now)

        baseline = self._resolve_selector(principal, site_id, request.baseline, "BASELINE")
        current = self._resolve_selector(principal, site_id, request.current, "CURRENT")
        blockers = tuple(item for item in (baseline.blocker, current.blocker) if item)
        intent = self._intents.record_intent(
            organization_id=principal.organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            request=request,
            idempotency_key=idempotency_key,
            now=now,
            pre_admission_blockers=blockers,
        )
        if baseline.subject is None or current.subject is None:
            return self._blocked_view(intent, blockers)

        return self._resume(
            intent,
            principal=principal,
            now=now,
            resolved=(baseline, current),
        )

    def _resume(
        self,
        intent: PublicAnalysisIntent,
        *,
        principal: Principal,
        now: datetime,
        resolved: tuple[_ResolvedSelector, _ResolvedSelector] | None = None,
    ) -> AnalysisViewV1:
        """Advance only missing durable AP/NX records for an authorized retry."""
        if intent.pre_admission_blockers:
            return self._blocked_view(intent, intent.pre_admission_blockers)
        assessment = self._assessments.get_history(
            intent.analysis_id, organization_id=principal.organization_id
        )
        if assessment is None:
            baseline, selected_current = resolved or (
                self._resolve_selector(principal, intent.site_id, intent.baseline, "BASELINE"),
                self._resolve_selector(principal, intent.site_id, intent.current, "CURRENT"),
            )
            blockers = tuple(item for item in (baseline.blocker, selected_current.blocker) if item)
            if baseline.subject is None or selected_current.subject is None:
                return self._blocked_view(intent, blockers)
            assessment = self._assessments.assess_and_record(
                principal=principal,
                request=AnalysisAssessmentRequestV2(
                    request_id=intent.analysis_id,
                    work_area_id=intent.work_area_id,
                    baseline=AnalysisEpochSelectionV2(subject=baseline.subject),
                    current=AnalysisEpochSelectionV2(subject=selected_current.subject),
                    # Never persist the caller's opaque key in AP; the public
                    # intent owns it and binds its exact selectors.
                    idempotency_key="analysis-intent/" + intent.analysis_id,
                ),
                now=now,
            )

        identity = assessment.admission.calculation_identity_digest
        if identity is not None and assessment.admission.disposition in {
            AdmissionDispositionV2.ADMIT_PROVISIONAL,
            AdmissionDispositionV2.ADMIT_EVALUATED,
        }:
            # AP history is immutable.  Confirm its suitability remains
            # current before letting a retry issue NX; a changed fact becomes
            # a read-only reassessment state, never an implicit re-assessment.
            current = self._assessments.get_current(
                intent.analysis_id, principal=principal, now=now
            )
            if current is not None:
                calculation_request_id = intent.calculation_request_id or intent.analysis_id
                calculation = self._calculations.get_history(
                    calculation_request_id, organization_id=principal.organization_id
                )
                if calculation is None:
                    calculation = self._calculations.issue(
                        principal=principal,
                        request_id=intent.analysis_id,
                        calculation_identity_digest=identity,
                        idempotency_key="analysis-execution/" + intent.analysis_id,
                        now=now,
                    )
                # The NX append may have completed immediately before an
                # interruption prevented the intent-link append.  A matching
                # retry must bind that durable record, including NX's valid
                # identity-deduplicated canonical request ID.  Never adopt a
                # record merely because its request ID is reachable: both its
                # organization and sealed AP calculation identity must match.
                if (
                    calculation.organization_id != principal.organization_id
                    or calculation.calculation_identity_digest != identity
                ):
                    raise RuntimeError("recovered calculation does not match analysis admission")
                if intent.calculation_request_id is None:
                    intent = self._intents.link_calculation(
                        analysis_id=intent.analysis_id,
                        organization_id=principal.organization_id,
                        calculation_request_id=calculation.request_id,
                    )
        return self._view(intent, principal=principal, now=now)

    def get(
        self, *, principal: Principal, site_id: str, analysis_id: str, now: datetime
    ) -> AnalysisViewV1 | None:
        self._require(principal, Permission.SITES_READ)
        intent = self._intents.get(analysis_id, organization_id=principal.organization_id)
        if (
            intent is None
            or intent.site_id != site_id
            or not self._intent_is_in_scope(principal, intent)
        ):
            return None
        return self._view(intent, principal=principal, now=now)

    def external_ai_egress_allowed(self, *, principal: Principal, site_id: str) -> bool:
        """Return a scoped site's explicit external-AI egress decision.

        This is deliberately a read-only facade seam.  It does not infer AI
        consent from generic egress policy and it does not append a durable
        record.  Callers must already have authenticated a route-specific
        analysis permission before asking this question.
        """
        self._require_site_grant(principal, site_id)
        site = self._sites.get_scoped(site_id, principal.organization_id)
        if site is None:
            raise AnalysisScopeNotFound(site_id)
        return bool(getattr(site, "ai_egress_allowed", False))

    def list(self, *, principal: Principal, site_id: str, now: datetime) -> AnalysisListV1:
        self._require(principal, Permission.SITES_READ)
        self._require_site_grant(principal, site_id)
        if self._sites.get_scoped(site_id, principal.organization_id) is None:
            raise AnalysisScopeNotFound("ANALYSIS_RESOURCE_NOT_FOUND")
        intents = sorted(
            (
                intent
                for intent in self._intents.list(
                    organization_id=principal.organization_id, site_id=site_id
                )
                if self._intent_is_in_scope(principal, intent)
            ),
            key=lambda intent: (intent.created_at, intent.analysis_id),
            reverse=True,
        )[:500]
        return AnalysisListV1(
            items=tuple(self._view(intent, principal=principal, now=now) for intent in intents)
        )

    def evidence(
        self, *, principal: Principal, site_id: str, analysis_id: str, now: datetime
    ) -> AnalysisEvidenceViewV1 | None:
        view = self.get(principal=principal, site_id=site_id, analysis_id=analysis_id, now=now)
        if view is None:
            return None
        intent = self._intents.get(analysis_id, organization_id=principal.organization_id)
        assert intent is not None
        assessment = self._assessments.get_history_for_principal(
            intent.analysis_id, principal=principal
        )
        identity = assessment.admission.calculation_identity if assessment is not None else None
        # A pre-admission block has no sealed AP identity; expose that absence
        # rather than inventing epoch provenance from an unsealed revision.
        baseline = (
            self._epoch_evidence(
                selector=intent.baseline,
                subject=identity.baseline_subject,
                identity=identity,
                prefix="baseline",
                organization_id=principal.organization_id,
                site_id=site_id,
                analysis_id=intent.analysis_id,
            )
            if identity is not None
            else None
        )
        current = (
            self._epoch_evidence(
                selector=intent.current,
                subject=identity.current_subject,
                identity=identity,
                prefix="current",
                organization_id=principal.organization_id,
                site_id=site_id,
                analysis_id=intent.analysis_id,
            )
            if identity is not None
            else None
        )
        return AnalysisEvidenceViewV1(
            analysis_id=view.analysis_id,
            authority=view.authority,
            baseline=baseline,
            current=current,
            calculation=self._calculation_evidence(identity) if identity is not None else None,
            evaluations=self._evaluation_evidence(
                assessment.admission, site_id=site_id, analysis_id=intent.analysis_id
            )
            if assessment is not None
            else (),
            result=view.result,
            evidence_refs=view.evidence_refs,
        )

    def create_v2(
        self,
        *,
        principal: Principal,
        site_id: str,
        work_area_id: str,
        request: CreateAnalysisRequestV1,
        idempotency_key: str,
        now: datetime,
    ) -> AnalysisViewV2:
        created = self.create_or_resume(
            principal=principal,
            site_id=site_id,
            work_area_id=work_area_id,
            request=request,
            idempotency_key=idempotency_key,
            now=now,
        )
        view = self.get_v2(
            principal=principal, site_id=site_id, analysis_id=created.analysis_id, now=now
        )
        if view is None:
            raise AnalysisScopeNotFound("ANALYSIS_RESOURCE_NOT_FOUND")
        return view

    @staticmethod
    def _selector_link_key(selector: AnalysisObservationSelectorV1) -> tuple[str, str, int]:
        return (selector.work_order_id, selector.submission_ref, selector.revision)

    def _newer_sibling_index(
        self, intents: Sequence[PublicAnalysisIntent]
    ) -> dict[str, tuple[str, ...]]:
        """Derive shared-epoch continuers read-side from already-scoped intents.

        A newer sibling B of A shares site+workArea and satisfies
        B.baseline == A.current by exact selector equality. The map is built
        in one O(N) pass over the intent list the caller already holds; no
        journal append, no capture-time inference, no suitability judgment.
        Groups sort by (createdAt, analysisId) so output order is stable.
        Only intents the caller already scoped appear, so no cross-grant leak.
        """
        groups: dict[tuple[str, str, tuple[str, str, int]], list[tuple[datetime, str]]] = {}
        for intent in intents:
            key = (
                intent.site_id,
                intent.work_area_id,
                self._selector_link_key(intent.baseline),
            )
            groups.setdefault(key, []).append((intent.created_at, intent.analysis_id))
        for members in groups.values():
            members.sort()
        index: dict[str, tuple[str, ...]] = {}
        for intent in intents:
            key = (
                intent.site_id,
                intent.work_area_id,
                self._selector_link_key(intent.current),
            )
            candidates = groups.get(key, [])
            index[intent.analysis_id] = tuple(
                analysis_id
                for _, analysis_id in candidates
                if analysis_id != intent.analysis_id
            )[:50]
        return index

    def list_v2(
        self,
        *,
        principal: Principal,
        site_id: str,
        now: datetime,
        limit: int,
        cursor: str | None,
    ) -> AnalysisListPageV2:
        self._require(principal, Permission.SITES_READ)
        self._require_site_grant(principal, site_id)
        if not 1 <= limit <= 50:
            raise ValueError("ANALYSIS_PAGE_LIMIT_INVALID")
        if self._sites.get_scoped(site_id, principal.organization_id) is None:
            raise AnalysisScopeNotFound("ANALYSIS_RESOURCE_NOT_FOUND")
        intents = sorted(
            (
                intent
                for intent in self._intents.list(
                    organization_id=principal.organization_id, site_id=site_id
                )
                if self._intent_is_in_scope(principal, intent)
            ),
            key=lambda intent: (intent.created_at, intent.analysis_id),
            reverse=True,
        )
        sibling_index = self._newer_sibling_index(intents)
        if cursor is not None:
            payload = _decode_cursor(cursor)
            if set(payload) != {"createdAt", "analysisId"}:
                raise ValueError("ANALYSIS_CURSOR_INVALID")
            raw_created_at = payload["createdAt"]
            analysis_id = payload["analysisId"]
            if not isinstance(raw_created_at, str) or not isinstance(analysis_id, str):
                raise ValueError("ANALYSIS_CURSOR_INVALID")
            try:
                created_at = datetime.fromisoformat(raw_created_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("ANALYSIS_CURSOR_INVALID") from exc
            if (
                not analysis_id
                or created_at.tzinfo is None
                or created_at.utcoffset() != UTC.utcoffset(created_at)
            ):
                raise ValueError("ANALYSIS_CURSOR_INVALID")
            anchor = (created_at, analysis_id)
            matches = [
                index
                for index, intent in enumerate(intents)
                if (intent.created_at, intent.analysis_id) == anchor
            ]
            if len(matches) != 1:
                raise ValueError("ANALYSIS_CURSOR_STALE")
            intents = intents[matches[0] + 1 :]
        selected = intents[:limit]
        items = []
        for intent in selected:
            view = self._view(intent, principal=principal, now=now)
            items.append(
                AnalysisListItemV2(
                    analysis_id=view.analysis_id,
                    site_id=view.site_id,
                    work_area_id=view.work_area_id,
                    execution_state=view.execution_state,
                    suitability_state=view.suitability_state,
                    created_at=view.created_at,
                    result_id=view.result.result_id if view.result is not None else None,
                    metrics=view.result.metrics if view.result is not None else None,
                    limitation_count=len(view.blockers)
                    + (len(view.result.limitation_codes) if view.result is not None else 0),
                    analysis_href=f"/v2/sites/{site_id}/analyses/{view.analysis_id}",
                    newer_sibling_analysis_ids=sibling_index.get(view.analysis_id, ()),
                )
            )
        next_cursor = None
        if len(intents) > limit and selected:
            last = selected[-1]
            next_cursor = _encode_cursor(
                {
                    "createdAt": last.created_at.isoformat().replace("+00:00", "Z"),
                    "analysisId": last.analysis_id,
                }
            )
        return AnalysisListPageV2(site_id=site_id, items=tuple(items), next_cursor=next_cursor)

    def get_v2(
        self, *, principal: Principal, site_id: str, analysis_id: str, now: datetime
    ) -> AnalysisViewV2 | None:
        snapshot = self._read_v2_snapshot(
            principal=principal, site_id=site_id, analysis_id=analysis_id, now=now
        )
        if snapshot is None:
            return None
        view, evidence = snapshot
        return self._project_v2(view, evidence)

    def _read_v2_snapshot(
        self, *, principal: Principal, site_id: str, analysis_id: str, now: datetime
    ) -> tuple[AnalysisViewV1, AnalysisEvidenceViewV1] | None:
        for _ in range(3):
            before = self.get(
                principal=principal, site_id=site_id, analysis_id=analysis_id, now=now
            )
            if before is None:
                return None
            evidence = self.evidence(
                principal=principal, site_id=site_id, analysis_id=analysis_id, now=now
            )
            if evidence is None:
                return None
            after = self.get(
                principal=principal, site_id=site_id, analysis_id=analysis_id, now=now
            )
            if after is None:
                return None
            if before == after and _same_analysis_snapshot(before, evidence):
                return after, evidence
        raise AnalysisSnapshotChanged("ANALYSIS_SNAPSHOT_CHANGED")

    def evidence_v2(
        self,
        *,
        principal: Principal,
        site_id: str,
        analysis_id: str,
        now: datetime,
        limit: int,
        cursor: str | None,
    ) -> AnalysisEvidencePageV2 | None:
        if not 1 <= limit <= 32:
            raise ValueError("ANALYSIS_EVIDENCE_PAGE_LIMIT_INVALID")
        snapshot = self._read_v2_snapshot(
            principal=principal, site_id=site_id, analysis_id=analysis_id, now=now
        )
        if snapshot is None:
            return None
        view, evidence = snapshot
        items = self._evidence_items_v2(view, evidence)
        result, _coverage_href = self._result_summary_v2(view)
        digest = self._evidence_digest_v2(view, evidence, result, items)
        revision = _evidence_revision(evidence)
        offset = 0
        if cursor is not None:
            payload = _decode_cursor(cursor)
            if set(payload) != {
                "analysisId",
                "evidenceRevision",
                "evidenceDigest",
                "offset",
            }:
                raise ValueError("ANALYSIS_EVIDENCE_CURSOR_INVALID")
            raw_analysis_id = payload["analysisId"]
            raw_revision = payload["evidenceRevision"]
            raw_digest = payload["evidenceDigest"]
            raw_offset = payload["offset"]
            if (
                not isinstance(raw_analysis_id, str)
                or not raw_analysis_id
                or not isinstance(raw_revision, int)
                or isinstance(raw_revision, bool)
                or raw_revision < 1
                or not isinstance(raw_digest, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", raw_digest) is None
                or not isinstance(raw_offset, int)
                or isinstance(raw_offset, bool)
                or raw_offset < 0
            ):
                raise ValueError("ANALYSIS_EVIDENCE_CURSOR_INVALID")
            expected = {
                "analysisId": analysis_id,
                "evidenceRevision": revision,
                "evidenceDigest": digest,
            }
            if any(payload.get(key) != value for key, value in expected.items()):
                raise ValueError("ANALYSIS_EVIDENCE_CURSOR_STALE")
            offset = raw_offset
        if offset > len(items):
            raise ValueError("ANALYSIS_EVIDENCE_CURSOR_INVALID")
        selected = items[offset : offset + limit]
        next_cursor = None
        if offset + len(selected) < len(items):
            next_cursor = _encode_cursor(
                {
                    "analysisId": analysis_id,
                    "evidenceRevision": revision,
                    "evidenceDigest": digest,
                    "offset": offset + len(selected),
                }
            )
        return AnalysisEvidencePageV2(
            analysis_id=analysis_id,
            evidence_revision=revision,
            evidence_digest=digest,
            items=tuple(selected),
            next_cursor=next_cursor,
        )

    def coverage_resource_v2(
        self, *, principal: Principal, site_id: str, analysis_id: str, now: datetime
    ) -> tuple[bytes, str] | None:
        view = self.get(principal=principal, site_id=site_id, analysis_id=analysis_id, now=now)
        if view is None or view.result is None:
            return None
        payload = canonical_json_bytes(view.result.coverage.model_dump(by_alias=True, mode="json"))
        return payload, "sha256:" + hashlib.sha256(payload).hexdigest()

    def _project_v2(
        self, view: AnalysisViewV1, evidence: AnalysisEvidenceViewV1
    ) -> AnalysisViewV2:
        result, coverage_href = self._result_summary_v2(view)
        items = self._evidence_items_v2(view, evidence)
        evidence_digest = self._evidence_digest_v2(view, evidence, result, items)
        return AnalysisViewV2(
            analysis_id=view.analysis_id,
            site_id=view.site_id,
            work_area_id=view.work_area_id,
            baseline=view.baseline,
            current=view.current,
            execution_state=view.execution_state,
            suitability_state=view.suitability_state,
            blockers=view.blockers,
            result=result,
            evidence_revision=_evidence_revision(evidence),
            evidence_digest=evidence_digest,
            evidence_href=f"/v2/sites/{view.site_id}/analyses/{view.analysis_id}/evidence",
            coverage_href=coverage_href,
            created_at=view.created_at,
        )

    def _result_summary_v2(
        self, view: AnalysisViewV1
    ) -> tuple[AnalysisResultSummaryV2 | None, str | None]:
        result = None
        coverage_href = None
        if view.result is not None:
            coverage = view.result.coverage
            witness_digest = coverage.coverage_witness_digest or _digest_payload(
                coverage.model_dump(by_alias=True, mode="json")
            )
            result = AnalysisResultSummaryV2(
                result_id=view.result.result_id,
                report_digest=view.result.report_digest,
                numeric_result_identity_digest=view.result.numeric_result_identity_digest,
                computed_at=view.result.computed_at,
                metrics=view.result.metrics,
                coverage=AnalysisCoverageSummaryV2(
                    coverage_witness_digest=witness_digest,
                    rows=coverage.rows,
                    columns=coverage.columns,
                    selected_cell_count=coverage.selected_cell_count,
                    common_valid_cell_count=coverage.common_valid_cell_count,
                    unavailable_cell_count=coverage.unavailable_cell_count,
                    threshold_excluded_cell_count=coverage.threshold_excluded_cell_count,
                    cell_area_m2=coverage.cell_area_m2,
                    selected_area_m2=coverage.selected_area_m2,
                    common_valid_area_m2=coverage.common_valid_area_m2,
                    bounds=coverage.bounds,
                ),
                limitation_codes=view.result.limitation_codes,
            )
            coverage_href = f"/v2/sites/{view.site_id}/analyses/{view.analysis_id}/coverage"
        return result, coverage_href

    def _evidence_digest_v2(
        self,
        view: AnalysisViewV1,
        evidence: AnalysisEvidenceViewV1,
        result: AnalysisResultSummaryV2 | None,
        items: tuple[AnalysisEvidenceItemV2, ...],
    ) -> str:
        detail_identity = {
            "analysisId": view.analysis_id,
            "siteId": view.site_id,
            "workAreaId": view.work_area_id,
            "baseline": view.baseline.model_dump(by_alias=True, mode="json"),
            "current": view.current.model_dump(by_alias=True, mode="json"),
            "executionState": view.execution_state.value,
            "suitabilityState": view.suitability_state.value,
            "blockers": [
                item.model_dump(by_alias=True, mode="json") for item in view.blockers
            ],
            "result": result.model_dump(by_alias=True, mode="json") if result is not None else None,
            "createdAt": view.created_at.isoformat().replace("+00:00", "Z"),
        }
        return _digest_payload(
            {
                "sourceEvidence": evidence.model_dump(by_alias=True, mode="json"),
                "detail": detail_identity,
                "items": [item.model_dump(by_alias=True, mode="json") for item in items],
            }
        )

    def _evidence_items_v2(
        self, view: AnalysisViewV1, evidence: AnalysisEvidenceViewV1
    ) -> tuple[AnalysisEvidenceItemV2, ...]:
        items: list[AnalysisEvidenceItemV2] = []
        for epoch, value in (("BASELINE", evidence.baseline), ("CURRENT", evidence.current)):
            if value is None:
                continue
            items.append(
                AnalysisEpochEvidenceItemV2(
                    kind="EPOCH_IDENTITY",
                    record_id=value.observation_epoch_id,
                    digest=value.input_digest,
                    epoch=cast(Literal["BASELINE", "CURRENT"], epoch),
                    selector=value.selector,
                    observation_epoch_id=value.observation_epoch_id,
                    artifact_id=value.artifact_id,
                    observed_sha256=value.observed_sha256,
                    observed_size_bytes=value.observed_size_bytes,
                    observed_crs_identifier=value.observed_crs_identifier,
                    observed_crs_digest=value.observed_crs_digest,
                    vertical_reference_identifier=value.vertical_reference_identifier,
                    vertical_reference_basis=value.vertical_reference_basis,
                    vertical_unit=value.vertical_unit,
                    transform=value.transform,
                    transform_digest=value.transform_digest,
                    inspection_report_digest=value.inspection_report_digest,
                    inspection_report_record_id=value.inspection_report_ref.record_id,
                    input_digest=value.input_digest,
                )
            )
        if evidence.calculation is not None:
            calculation = evidence.calculation
            items.append(
                AnalysisCalculationEvidenceItemV2(
                    kind="CALCULATION_IDENTITY",
                    record_id=calculation.calculation_id,
                    digest=_digest_payload(calculation.model_dump(by_alias=True, mode="json")),
                    calculation=calculation,
                )
            )
        for evaluation in evidence.evaluations:
            items.append(
                AnalysisEvaluationEvidenceItemV2(
                    kind="EVALUATION",
                    record_id=evaluation.evaluation_id,
                    digest=evaluation.evaluation_digest,
                    evaluation_id=evaluation.evaluation_id,
                    epoch=evaluation.epoch,
                    revision=evaluation.revision,
                    evaluation_digest=evaluation.evaluation_digest,
                    outcome=evaluation.outcome,
                    reason_codes=evaluation.reason_codes,
                    assessed_at=evaluation.assessed_at,
                )
            )
            for fact in evaluation.evidence_facts:
                items.append(
                    AnalysisCheckpointEvidenceItemV2(
                        kind="CHECKPOINT_FACT",
                        record_id=fact.evidence_record_id,
                        digest=fact.evidence_record_digest,
                        evaluation_id=evaluation.evaluation_id,
                        epoch=evaluation.epoch,
                        evaluation_revision=evaluation.revision,
                        evidence_ref=fact.evidence_ref,
                        context_id=fact.context_id,
                        context_digest=fact.context_digest,
                        evidence_manifest_digest=fact.evidence_manifest_digest,
                        evidence_record_id=fact.evidence_record_id,
                        evidence_record_digest=fact.evidence_record_digest,
                        core_verdict=fact.core_verdict,
                    )
                )
        authority = evidence.authority.model_dump(by_alias=True, mode="json", exclude_none=True)
        for name, value in authority.items():
            source_digest = (
                value if isinstance(value, str) and value.startswith("sha256:") else None
            )
            items.append(
                AnalysisAuthorityEvidenceItemV2(
                    kind="AUTHORITY_REFERENCE",
                    record_id=str(value),
                    digest=source_digest or _digest_payload({"name": name, "value": value}),
                    reference_name=cast(
                        Literal[
                            "assessmentRequestId",
                            "admissionId",
                            "admissionDigest",
                            "calculationIdentityDigest",
                            "calculationRequestId",
                            "authorizationId",
                            "reportDigest",
                            "failureDigest",
                        ],
                        name,
                    ),
                    source_digest=source_digest,
                )
            )
        for reference in evidence.evidence_refs:
            items.append(
                AnalysisReferenceEvidenceItemV2(
                    kind="SOURCE_REFERENCE",
                    record_id=reference.record_id,
                    digest=_digest_payload(reference.model_dump(by_alias=True, mode="json")),
                    reference_kind=reference.kind,
                )
            )
        if evidence.result is not None:
            result = evidence.result
            items.append(
                AnalysisNumericResultEvidenceItemV2(
                    kind="NUMERIC_RESULT",
                    record_id=result.result_id,
                    digest=result.report_digest,
                    result_id=result.result_id,
                    report_digest=result.report_digest,
                    numeric_result_identity_digest=result.numeric_result_identity_digest,
                    computed_at=result.computed_at,
                )
            )
        for index, blocker in enumerate(view.blockers):
            items.append(
                AnalysisLimitationEvidenceItemV2(
                    kind="LIMITATION",
                    record_id=f"blocker-{index}-{blocker.code}",
                    digest=_digest_payload(blocker.model_dump(by_alias=True, mode="json")),
                    source="BLOCKER",
                    code=blocker.code,
                    epoch=blocker.epoch,
                    evidence_ref=blocker.evidence_ref,
                    detail=blocker.detail,
                )
            )
        if view.result is not None:
            for index, code in enumerate(view.result.limitation_codes):
                items.append(
                    AnalysisLimitationEvidenceItemV2(
                        kind="LIMITATION",
                        record_id=f"result-limitation-{index}-{code}",
                        digest=_digest_payload({"source": "RESULT", "code": code}),
                        source="RESULT",
                        code=code,
                    )
                )
        return tuple(items)

    def _epoch_evidence(
        self,
        *,
        selector: AnalysisObservationSelectorV1,
        subject: SealedExternalSubjectV1,
        identity: Any,
        prefix: str,
        organization_id: str,
        site_id: str,
        analysis_id: str,
    ) -> AnalysisEpochEvidenceV1 | None:
        """Return exact AP identity facts only while their sealed ingress agrees."""
        if subject.work_order_id != selector.work_order_id or subject.revision != selector.revision:
            return None
        revision = self._reconstructions.get(
            subject.work_order_id,
            subject.submission_id,
            subject.revision,
            organization_id=organization_id,
            site_id=site_id,
        )
        if (
            revision is None
            or revision.manifest is None
            or revision.manifest.manifest_digest != subject.manifest_digest
            or revision.submission.submission_digest != subject.submission_digest
        ):
            return None
        vertical_reference = getattr(identity, prefix + "_vertical_reference")
        return AnalysisEpochEvidenceV1(
            selector=selector,
            observation_epoch_id=revision.observation_epoch_id,
            artifact_id=getattr(identity, prefix + "_dsm_artifact_id"),
            observed_sha256=getattr(identity, prefix + "_dsm_observed_sha256"),
            observed_size_bytes=getattr(identity, prefix + "_dsm_observed_size_bytes"),
            observed_crs_identifier=getattr(identity, prefix + "_observed_crs_identifier"),
            observed_crs_digest=getattr(identity, prefix + "_observed_crs_digest"),
            vertical_reference_identifier=vertical_reference.identifier,
            vertical_reference_basis=vertical_reference.basis,
            vertical_unit=getattr(identity, prefix + "_vertical_unit"),
            transform=getattr(identity, prefix + "_transform"),
            transform_digest=getattr(identity, prefix + "_transform_digest"),
            inspection_report_digest=getattr(identity, prefix + "_inspection_report_digest"),
            inspection_report_ref=AnalysisEvidenceReferenceV1(
                kind="INSPECTION_REPORT",
                record_id=getattr(identity, prefix + "_inspection_report_digest"),
                href=self._evidence_href(site_id, analysis_id),
            ),
            input_digest=getattr(identity, prefix + "_input_digest"),
        )

    @staticmethod
    def _evidence_href(site_id: str, analysis_id: str) -> str:
        return f"/v1/sites/{site_id}/analyses/{analysis_id}/evidence"

    @staticmethod
    def _calculation_evidence(identity: Any) -> AnalysisCalculationIdentityEvidenceV1:
        policy = identity.policy
        return AnalysisCalculationIdentityEvidenceV1(
            calculation_id=identity.calculation_id,
            work_area_definition_digest=identity.work_area_definition_digest,
            baseline_input_digest=identity.baseline_input_digest,
            current_input_digest=identity.current_input_digest,
            policy=AnalysisPolicyEvidenceV1(
                policy_id=policy.policy_id,
                version=policy.version,
                profile_id=policy.profile_id,
                profile_digest=policy.profile_digest,
                algorithm_digest=policy.algorithm_digest,
                config_digest=policy.config_digest,
                policy_digest=policy.policy_digest,
            ),
            runtime=AnalysisRuntimeEvidenceV1(
                worker_executable_digest=identity.worker_executable_digest,
                worker_build_digest=identity.worker_build_digest,
                runtime_image_version=identity.runtime_image_version,
                runtime_image_oci_digest=identity.runtime_image_oci_digest,
                dependency_lock_digest=identity.dependency_lock_digest,
            ),
        )

    @classmethod
    def _evaluation_evidence(
        cls, admission: Any, *, site_id: str, analysis_id: str
    ) -> tuple[AnalysisEvaluationEvidenceV1, ...]:
        href = cls._evidence_href(site_id, analysis_id)
        return tuple(
            AnalysisEvaluationEvidenceV1(
                evaluation_id=evaluation.evaluation_id,
                epoch=evaluation.epoch,
                revision=evaluation.revision,
                evaluation_digest=evaluation.evaluation_digest,
                outcome=evaluation.outcome,
                reason_codes=tuple(evaluation.reason_codes),
                assessed_at=evaluation.assessed_at,
                evidence_facts=tuple(
                    AnalysisEvaluationEvidenceFactV1(
                        evidence_ref=fact.evidence_ref,
                        context_id=fact.context.context_id,
                        context_digest=fact.context.context_digest,
                        evidence_manifest_digest=fact.context.evidence_manifest_digest,
                        evidence_record_id=fact.terminal_record.evidence_record_id,
                        evidence_record_digest=fact.terminal_record.evidence_record_digest,
                        core_verdict=fact.terminal_record.core_verdict,
                        href=href,
                    )
                    for fact in evaluation.evidence_facts
                ),
            )
            for evaluation in getattr(admission, "evaluation_revisions", ())
        )

    @classmethod
    def _admission_evidence_refs(
        cls, admission: Any | None, *, site_id: str, analysis_id: str
    ) -> tuple[AnalysisEvidenceReferenceV1, ...]:
        identity = getattr(admission, "calculation_identity", None)
        if identity is None:
            return ()
        href = cls._evidence_href(site_id, analysis_id)
        inspection_refs = tuple(
            AnalysisEvidenceReferenceV1(
                kind="INSPECTION_REPORT",
                record_id=getattr(identity, prefix + "_inspection_report_digest"),
                href=href,
            )
            for prefix in ("baseline", "current")
        )
        checkpoint_refs = tuple(
            AnalysisEvidenceReferenceV1(
                kind="CHECKPOINT_EVIDENCE",
                record_id=fact.evidence_ref,
                href=href,
            )
            for evaluation in getattr(admission, "evaluation_revisions", ())
            for fact in evaluation.evidence_facts
        )
        return inspection_refs + checkpoint_refs

    def _view(
        self, intent: PublicAnalysisIntent, *, principal: Principal, now: datetime
    ) -> AnalysisViewV1:
        if intent.pre_admission_blockers:
            return self._blocked_view(intent, intent.pre_admission_blockers)
        assessment = self._assessments.get_history_for_principal(
            intent.analysis_id, principal=principal
        )
        if assessment is None:
            return self._blocked_view(
                intent,
                (AnalysisBlockerV1(code="ASSESSMENT_RECOVERY_REQUIRED"),),
            )
        admission = assessment.admission
        authority = AnalysisAuthorityReferencesV1(
            assessment_request_id=intent.analysis_id,
            admission_id=admission.admission_id,
            admission_digest=admission.admission_digest,
            calculation_identity_digest=admission.calculation_identity_digest,
        )
        if admission.disposition is AdmissionDispositionV2.BLOCKED:
            return self._view_with(
                intent,
                AnalysisExecutionStateV1.NOT_STARTED,
                AnalysisSuitabilityStateV1.BLOCKED,
                tuple(AnalysisBlockerV1(code=code) for code in admission.reason_codes),
                authority,
                None,
                admission=admission,
            )
        if admission.disposition is AdmissionDispositionV2.REMEDIATION_REQUIRED:
            return self._view_with(
                intent,
                AnalysisExecutionStateV1.NOT_STARTED,
                AnalysisSuitabilityStateV1.REMEDIATION_REQUIRED,
                tuple(AnalysisBlockerV1(code=code) for code in admission.reason_codes),
                authority,
                None,
                admission=admission,
            )
        calculation = self._calculations.get_history(
            intent.calculation_request_id or intent.analysis_id,
            organization_id=principal.organization_id,
        )
        suitability = (
            AnalysisSuitabilityStateV1.PROVISIONAL_ACCURACY_UNVERIFIED
            if admission.disposition is AdmissionDispositionV2.ADMIT_PROVISIONAL
            else AnalysisSuitabilityStateV1.EVALUATED
        )
        if calculation is None:
            return self._view_with(
                intent,
                AnalysisExecutionStateV1.NOT_STARTED,
                suitability,
                (),
                authority,
                None,
                admission=admission,
            )
        execution = AnalysisExecutionStateV1(calculation.status.value)
        authority = authority.model_copy(
            update={
                "calculation_request_id": calculation.request_id,
                "authorization_id": calculation.authorization.authorization_id,
                "report_digest": calculation.report.report_digest if calculation.report else None,
                "failure_digest": calculation.failure.failure_digest
                if calculation.failure
                else None,
            }
        )
        if calculation.calculation_identity_digest != admission.calculation_identity_digest:
            return self._view_with(
                intent,
                execution,
                AnalysisSuitabilityStateV1.REASSESSMENT_REQUIRED,
                (AnalysisBlockerV1(code="CALCULATION_IDENTITY_MISMATCH"),),
                authority,
                None,
                admission=admission,
            )
        # AP's original public currentness reader requires SITES_WRITE.  This
        # narrow read seam computes the same local witness after SITES_READ
        # without manufacturing a privileged Principal or appending a record.
        # Consult it after the durable NX record so a stale AP never erases
        # the historical execution state from the orthogonal public axis.
        if (
            self._assessments.get_current_for_read(intent.analysis_id, principal=principal, now=now)
            is None
        ):
            return self._view_with(
                intent,
                execution,
                AnalysisSuitabilityStateV1.REASSESSMENT_REQUIRED,
                (AnalysisBlockerV1(code="REASSESSMENT_REQUIRED"),),
                authority,
                None,
                admission=admission,
            )
        current = self._calculations.get_current(
            request_id=calculation.request_id, principal=principal, now=now
        )
        if (
            current is None
            or current.disposition is CalculationCurrentDispositionV2.REASSESSMENT_REQUIRED
        ):
            return self._view_with(
                intent,
                execution,
                AnalysisSuitabilityStateV1.REASSESSMENT_REQUIRED,
                (AnalysisBlockerV1(code="REASSESSMENT_REQUIRED"),),
                authority,
                None,
                admission=admission,
            )
        if current.disposition in {
            CalculationCurrentDispositionV2.EXECUTION_DEADLINE_EXPIRED,
            CalculationCurrentDispositionV2.EXECUTION_RETRY_EXHAUSTED,
        }:
            # NX, rather than this facade, decides that the durable unfinished
            # execution can no longer acquire a lease.  Project that read-only
            # authority verdict into the fixed public terminal state; do not
            # append a synthetic failure during a GET.
            return self._view_with(
                intent,
                AnalysisExecutionStateV1.FAILED,
                suitability,
                (AnalysisBlockerV1(code=current.disposition.value),),
                authority,
                None,
                admission=admission,
            )
        if current.disposition is CalculationCurrentDispositionV2.FAILED:
            failure_code = (
                calculation.failure.reason_code
                if calculation.failure
                else "ANALYSIS_EXECUTION_FAILED"
            )
            failure_suitability = (
                AnalysisSuitabilityStateV1.BLOCKED
                if failure_code
                in {"EMPTY_COMMON_VALID_COVERAGE", "INSUFFICIENT_COMMON_VALID_COVERAGE"}
                else suitability
            )
            return self._view_with(
                intent,
                execution,
                failure_suitability,
                (AnalysisBlockerV1(code=failure_code),),
                authority,
                None,
                admission=admission,
            )
        if (
            current.disposition is CalculationCurrentDispositionV2.AVAILABLE
            and current.report is not None
        ):
            # The worker may finish between the immutable-history read above
            # and NX's currentness read.  AVAILABLE and its report are the
            # authoritative current pair for numeric projection; do not mix
            # that report with the earlier QUEUED/RUNNING history snapshot.
            execution = AnalysisExecutionStateV1.COMPLETED
            authority = authority.model_copy(
                update={
                    "report_digest": current.report.report_digest
                }
            )
        result = (
            self._result(
                current.report,
                limitation_codes=self._limitation_codes(admission),
            )
            if current.report is not None
            else None
        )
        return self._view_with(
            intent, execution, suitability, (), authority, result, admission=admission
        )

    @staticmethod
    def _limitation_codes(admission: Any) -> tuple[str, ...]:
        """Expose only the sealed, unresolved reasons for a provisional result."""
        if admission.disposition is not AdmissionDispositionV2.ADMIT_PROVISIONAL:
            return ()
        return tuple(
            sorted(
                {
                    reason_code
                    for evaluation in getattr(admission, "evaluation_revisions", ())
                    if getattr(evaluation.outcome, "value", evaluation.outcome) == "UNASSESSED"
                    for reason_code in evaluation.reason_codes
                }
            )
        )

    @staticmethod
    def _result(report: Any, *, limitation_codes: tuple[str, ...]) -> AnalysisResultV1:
        numeric = report.numeric_result
        coverage = numeric.coverage
        return AnalysisResultV1(
            result_id=report.report_id,
            result_revision=1,
            report_digest=report.report_digest,
            numeric_result_identity_digest=report.numeric_result_identity_digest,
            computed_at=report.computed_at,
            metrics=AnalysisMetricsV1(
                cut_m3=numeric.metrics.cut_m3,
                fill_m3=numeric.metrics.fill_m3,
                net_m3=numeric.metrics.net_m3,
                threshold_m=numeric.metrics.threshold_m,
                uncertainty_m3=None,
            ),
            coverage=coverage,
            limitation_codes=limitation_codes,
        )

    def _blocked_view(
        self, intent: PublicAnalysisIntent, blockers: tuple[AnalysisBlockerV1, ...]
    ) -> AnalysisViewV1:
        return self._view_with(
            intent,
            AnalysisExecutionStateV1.NOT_STARTED,
            AnalysisSuitabilityStateV1.BLOCKED,
            blockers,
            AnalysisAuthorityReferencesV1(assessment_request_id=intent.analysis_id),
            None,
        )

    @staticmethod
    def _view_with(
        intent: PublicAnalysisIntent,
        execution: AnalysisExecutionStateV1,
        suitability: AnalysisSuitabilityStateV1,
        blockers: tuple[AnalysisBlockerV1, ...],
        authority: AnalysisAuthorityReferencesV1,
        result: AnalysisResultV1 | None,
        *,
        admission: Any | None = None,
    ) -> AnalysisViewV1:
        href = ExternalAnalysisFacade._evidence_href(intent.site_id, intent.analysis_id)
        reconstruction_refs = tuple(
            AnalysisEvidenceReferenceV1(
                kind="EXTERNAL_RECONSTRUCTION_REVISION",
                record_id=selector.submission_ref,
                href=(
                    "/v1/observation-work-orders/"
                    f"{selector.work_order_id}/external-reconstruction-submissions/"
                    f"{selector.submission_ref}/revisions/{selector.revision}"
                ),
            )
            for selector in (intent.baseline, intent.current)
        )
        return AnalysisViewV1(
            analysis_id=intent.analysis_id,
            site_id=intent.site_id,
            work_area_id=intent.work_area_id,
            baseline=intent.baseline,
            current=intent.current,
            execution_state=execution,
            suitability_state=suitability,
            blockers=blockers,
            # Existing AP facts are returned as references only; the full
            # sealed projections remain on the scoped evidence endpoint.
            evidence_refs=(
                AnalysisEvidenceReferenceV1(
                    kind="ANALYSIS_EVIDENCE", record_id=intent.analysis_id, href=href
                ),
            )
            + reconstruction_refs
            + ExternalAnalysisFacade._admission_evidence_refs(
                admission, site_id=intent.site_id, analysis_id=intent.analysis_id
            ),
            authority=authority,
            result=result,
            created_at=intent.created_at,
        )

    def _require_path(self, principal: Principal, site_id: str, work_area_id: str) -> None:
        self._require_site_grant(principal, site_id)
        if not self._has_work_area_grant(principal, work_area_id):
            raise AnalysisScopeNotFound("ANALYSIS_RESOURCE_NOT_FOUND")
        site = self._sites.get_scoped(site_id, principal.organization_id)
        area = self._work_areas.get(work_area_id)
        if site is None or area is None or area.site_id != site_id:
            raise AnalysisScopeNotFound("ANALYSIS_RESOURCE_NOT_FOUND")

    @staticmethod
    def _has_site_grant(principal: Principal, site_id: str) -> bool:
        return principal.allowed_site_ids is None or site_id in principal.allowed_site_ids

    @staticmethod
    def _has_work_area_grant(principal: Principal, work_area_id: str) -> bool:
        return (
            principal.allowed_work_area_ids is None
            or work_area_id in principal.allowed_work_area_ids
        )

    @staticmethod
    def _has_work_area_grants(principal: Principal, work_area_ids: Sequence[str]) -> bool:
        return principal.allowed_work_area_ids is None or (
            bool(work_area_ids) and set(work_area_ids).issubset(principal.allowed_work_area_ids)
        )

    def _selectors_are_in_scope(
        self,
        principal: Principal,
        site_id: str,
        selectors: Sequence[AnalysisObservationSelectorV1],
    ) -> bool:
        # F-01 KTD5: area scope 가 null(조직 전체)이어도 WorkOrder 의 Org·Site
        # binding 확인은 계속한다 — null 은 area membership 검사만 생략하지
        # "모든 검사 생략"이 아니다. graph/원장 부재를 unrestricted 로 읽지 않는다.
        if principal.allowed_work_area_ids is None and not principal.registry_scoped:
            return True
        if self._work_orders is None:
            return False
        for selector in selectors:
            order = self._work_orders.get(
                selector.work_order_id, organization_id=principal.organization_id
            )
            if (
                order is None
                or order.site_id != site_id
                or not self._has_work_area_grants(principal, order.work_area_ids)
            ):
                return False
        return True

    def _intent_is_in_scope(self, principal: Principal, intent: PublicAnalysisIntent) -> bool:
        return (
            self._has_site_grant(principal, intent.site_id)
            and self._has_work_area_grant(principal, intent.work_area_id)
            and self._selectors_are_in_scope(
                principal, intent.site_id, (intent.baseline, intent.current)
            )
        )

    @classmethod
    def _require_site_grant(cls, principal: Principal, site_id: str) -> None:
        if not cls._has_site_grant(principal, site_id):
            raise AnalysisScopeNotFound("ANALYSIS_RESOURCE_NOT_FOUND")

    def _resolve_selector(
        self,
        principal: Principal,
        site_id: str,
        selector: AnalysisObservationSelectorV1,
        epoch: Literal["BASELINE", "CURRENT"],
    ) -> _ResolvedSelector:
        if not self._selectors_are_in_scope(principal, site_id, (selector,)):
            raise AnalysisScopeNotFound("ANALYSIS_RESOURCE_NOT_FOUND")
        submission_id = self._reconstructions.resolve_submission_ref(
            selector.work_order_id,
            selector.submission_ref,
            organization_id=principal.organization_id,
            site_id=site_id,
        )
        if submission_id is None:
            raise AnalysisScopeNotFound("ANALYSIS_RESOURCE_NOT_FOUND")
        revision = self._reconstructions.get(
            selector.work_order_id,
            submission_id,
            selector.revision,
            organization_id=principal.organization_id,
            site_id=site_id,
        )
        if revision is None:
            raise AnalysisScopeNotFound("ANALYSIS_RESOURCE_NOT_FOUND")
        if revision.manifest is None or revision.manifest.manifest_digest is None:
            return _ResolvedSelector(
                selector, None, AnalysisBlockerV1(code="RECONSTRUCTION_NOT_SEALED", epoch=epoch)
            )
        submission = revision.submission
        if submission.submission_digest is None:
            return _ResolvedSelector(
                selector, None, AnalysisBlockerV1(code="SUBMISSION_NOT_SEALED", epoch=epoch)
            )
        return _ResolvedSelector(
            selector,
            SealedExternalSubjectV1(
                organization_id=principal.organization_id,
                site_id=site_id,
                work_order_id=selector.work_order_id,
                submission_id=submission_id,
                revision=selector.revision,
                submission_digest=submission.submission_digest,
                manifest_digest=revision.manifest.manifest_digest,
            ),
            None,
        )

    @staticmethod
    def _require(principal: Principal, permission: Permission) -> None:
        granted = principal_permissions(principal)
        analysis_client_permission = {
            Permission.SITES_READ: Permission.ANALYSIS_API_READ,
            Permission.SITES_WRITE: Permission.ANALYSIS_API_CREATE,
        }.get(permission)
        if permission not in granted and analysis_client_permission not in granted:
            raise PermissionError(f"analysis requires {permission.value}")


def build_external_analysis_router(
    facade: _AnalysisPublicRoutePort,
    *,
    clock: Callable[[], datetime] | None = None,
    activation: AnalysisActivationV1 | None = None,
) -> APIRouter:
    """Build the six frozen public Analysis API routes.

    This router intentionally carries no worker control endpoints and does
    not mount itself.  Only an explicitly injected local/common composition
    may include it; the production composition remains closed.
    """
    now = clock or (lambda: datetime.now(UTC))
    router = APIRouter(tags=["external-analysis"])
    read = require_permission_any(Permission.SITES_READ, Permission.ANALYSIS_API_READ)
    write = require_permission_any(Permission.SITES_WRITE, Permission.ANALYSIS_API_CREATE)

    def require_current_activation() -> datetime:
        checked_at = now()
        if activation is not None and not activation.is_current_at(checked_at):
            raise HTTPException(status_code=503, detail="ANALYSIS_ACTIVATION_EXPIRED")
        return checked_at

    def not_found() -> HTTPException:
        return HTTPException(status_code=404, detail="ANALYSIS_RESOURCE_NOT_FOUND")

    def bounded_json(
        value: Any, *, status_code: int = 200, response: Response | None = None
    ) -> JSONResponse:
        payload = value.model_dump(by_alias=True, mode="json")
        headers = dict(response.headers) if response is not None else None
        encoded_response = JSONResponse(content=payload, status_code=status_code, headers=headers)
        if len(encoded_response.body) > 512 * 1024:
            raise HTTPException(status_code=422, detail="ANALYSIS_RESPONSE_TOO_LARGE")
        return encoded_response

    def cursor_error(exc: ValueError) -> HTTPException:
        detail = str(exc)
        if detail.endswith("_STALE"):
            return HTTPException(status_code=409, detail=detail)
        if detail.endswith("_LIMIT_INVALID"):
            return HTTPException(status_code=422, detail=detail)
        return HTTPException(status_code=400, detail=detail)

    # Keep the historical optional purpose header in the wire surface for
    # compatibility only. Authorization and consent depend on the authenticated
    # Analysis MCP identity, never on this caller-controlled value.
    def guard_external_ai_egress(
        *, principal: Principal, site_id: str, response: Response
    ) -> None:
        """Require current consent for the dedicated external AI identity."""
        if principal.kind is not PrincipalKind.ANALYSIS_MCP_CLIENT:
            return
        try:
            allowed = facade.external_ai_egress_allowed(principal=principal, site_id=site_id)
        except AnalysisScopeNotFound as exc:
            raise not_found() from exc
        if not allowed:
            raise HTTPException(status_code=403, detail="AI_EGRESS_NOT_ALLOWED")
        # The adapter uses this response as an identity/consent acknowledgment. It is
        # emitted only for the dedicated authenticated MCP client, never on a human
        # operator request that happens to carry a caller-controlled purpose header.
        response.headers["X-KSI-External-AI-Egress"] = "ALLOWED"

    @router.get(
        "/v1/sites/{site_id}/analysis-observations",
        response_model=AnalysisObservationOptionsV1,
    )
    def observation_options(
        site_id: str,
        response: Response,
        access_purpose: Literal["EXTERNAL_AI"] | None = Header(
            default=None, alias="X-KSI-Access-Purpose"
        ),
        principal: Principal = Depends(read),  # noqa: B008
    ) -> AnalysisObservationOptionsV1:
        guard_external_ai_egress(
            principal=principal,
            site_id=site_id,
            response=response,
        )
        try:
            return facade.observation_options(principal=principal, site_id=site_id)
        except AnalysisScopeNotFound as exc:
            raise not_found() from exc

    @router.post(
        "/v1/sites/{site_id}/work-areas/{work_area_id}/analyses",
        response_model=AnalysisViewV1,
        status_code=202,
    )
    def create_analysis(
        site_id: str,
        work_area_id: str,
        request: CreateAnalysisRequestV1,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
        access_purpose: Literal["EXTERNAL_AI"] | None = Header(
            default=None, alias="X-KSI-Access-Purpose"
        ),
        principal: Principal = Depends(write),  # noqa: B008
    ) -> AnalysisViewV1:
        checked_at = require_current_activation()
        if idempotency_key is None or not idempotency_key.strip():
            raise HTTPException(status_code=400, detail="IDEMPOTENCY_KEY_REQUIRED")
        guard_external_ai_egress(
            principal=principal,
            site_id=site_id,
            response=response,
        )
        try:
            return facade.create_or_resume(
                principal=principal,
                site_id=site_id,
                work_area_id=work_area_id,
                request=request,
                idempotency_key=idempotency_key,
                now=checked_at,
            )
        except AnalysisScopeNotFound as exc:
            raise not_found() from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="ANALYSIS_IDEMPOTENCY_CONFLICT") from exc

    @router.get("/v1/sites/{site_id}/analyses", response_model=AnalysisListV1)
    def list_analyses(
        site_id: str,
        response: Response,
        access_purpose: Literal["EXTERNAL_AI"] | None = Header(
            default=None, alias="X-KSI-Access-Purpose"
        ),
        principal: Principal = Depends(read),  # noqa: B008
    ) -> AnalysisListV1:
        guard_external_ai_egress(
            principal=principal,
            site_id=site_id,
            response=response,
        )
        try:
            return facade.list(principal=principal, site_id=site_id, now=now())
        except AnalysisScopeNotFound as exc:
            raise not_found() from exc

    @router.get("/v1/sites/{site_id}/analyses/{analysis_id}", response_model=AnalysisViewV1)
    def get_analysis(
        site_id: str,
        analysis_id: str,
        response: Response,
        access_purpose: Literal["EXTERNAL_AI"] | None = Header(
            default=None, alias="X-KSI-Access-Purpose"
        ),
        principal: Principal = Depends(read),  # noqa: B008
    ) -> AnalysisViewV1:
        guard_external_ai_egress(
            principal=principal,
            site_id=site_id,
            response=response,
        )
        view = facade.get(principal=principal, site_id=site_id, analysis_id=analysis_id, now=now())
        if view is None:
            raise not_found()
        return view

    @router.get("/v1/sites/{site_id}/analyses/{analysis_id}/result", response_model=AnalysisViewV1)
    def get_result(
        site_id: str,
        analysis_id: str,
        response: Response,
        access_purpose: Literal["EXTERNAL_AI"] | None = Header(
            default=None, alias="X-KSI-Access-Purpose"
        ),
        principal: Principal = Depends(read),  # noqa: B008
    ) -> AnalysisViewV1:
        guard_external_ai_egress(
            principal=principal,
            site_id=site_id,
            response=response,
        )
        view = facade.get(principal=principal, site_id=site_id, analysis_id=analysis_id, now=now())
        if view is None:
            raise not_found()
        return view

    @router.get(
        "/v1/sites/{site_id}/analyses/{analysis_id}/evidence",
        response_model=AnalysisEvidenceViewV1,
    )
    def get_evidence(
        site_id: str,
        analysis_id: str,
        response: Response,
        access_purpose: Literal["EXTERNAL_AI"] | None = Header(
            default=None, alias="X-KSI-Access-Purpose"
        ),
        principal: Principal = Depends(read),  # noqa: B008
    ) -> AnalysisEvidenceViewV1:
        guard_external_ai_egress(
            principal=principal,
            site_id=site_id,
            response=response,
        )
        evidence = facade.evidence(
            principal=principal, site_id=site_id, analysis_id=analysis_id, now=now()
        )
        if evidence is None:
            raise not_found()
        return evidence

    @router.post(
        "/v2/sites/{site_id}/work-areas/{work_area_id}/analyses",
        response_model=AnalysisViewV2,
        status_code=202,
    )
    def create_analysis_v2(
        site_id: str,
        work_area_id: str,
        request: CreateAnalysisRequestV1,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
        access_purpose: Literal["EXTERNAL_AI"] | None = Header(
            default=None, alias="X-KSI-Access-Purpose"
        ),
        principal: Principal = Depends(write),  # noqa: B008
    ) -> Response:
        checked_at = now()
        if activation is None:
            raise HTTPException(status_code=503, detail="ANALYSIS_ACTIVATION_UNAVAILABLE")
        if not activation.is_current_at(checked_at):
            raise HTTPException(status_code=503, detail="ANALYSIS_ACTIVATION_EXPIRED")
        if idempotency_key is None or not idempotency_key.strip():
            raise HTTPException(status_code=400, detail="IDEMPOTENCY_KEY_REQUIRED")
        guard_external_ai_egress(principal=principal, site_id=site_id, response=response)
        try:
            projected = facade.create_v2(
                principal=principal,
                site_id=site_id,
                work_area_id=work_area_id,
                request=request,
                idempotency_key=idempotency_key,
                now=checked_at,
            )
        except AnalysisScopeNotFound as exc:
            raise not_found() from exc
        except AnalysisSnapshotChanged as exc:
            raise HTTPException(status_code=409, detail="ANALYSIS_SNAPSHOT_CHANGED") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="ANALYSIS_IDEMPOTENCY_CONFLICT") from exc
        return bounded_json(projected, status_code=202, response=response)

    @router.get(
        "/v2/sites/{site_id}/analyses",
        response_model=AnalysisListPageV2,
    )
    def list_analyses_v2(
        site_id: str,
        response: Response,
        limit: int = Query(default=50, ge=1, le=50),
        cursor: str | None = Query(default=None, min_length=1, max_length=512),
        access_purpose: Literal["EXTERNAL_AI"] | None = Header(
            default=None, alias="X-KSI-Access-Purpose"
        ),
        principal: Principal = Depends(read),  # noqa: B008
    ) -> Response:
        guard_external_ai_egress(principal=principal, site_id=site_id, response=response)
        try:
            page = facade.list_v2(
                principal=principal, site_id=site_id, now=now(), limit=limit, cursor=cursor
            )
        except AnalysisScopeNotFound as exc:
            raise not_found() from exc
        except ValueError as exc:
            raise cursor_error(exc) from exc
        return bounded_json(page, response=response)

    @router.get("/v2/sites/{site_id}/analyses/{analysis_id}", response_model=AnalysisViewV2)
    def get_analysis_v2(
        site_id: str,
        analysis_id: str,
        response: Response,
        access_purpose: Literal["EXTERNAL_AI"] | None = Header(
            default=None, alias="X-KSI-Access-Purpose"
        ),
        principal: Principal = Depends(read),  # noqa: B008
    ) -> Response:
        guard_external_ai_egress(principal=principal, site_id=site_id, response=response)
        try:
            view = facade.get_v2(
                principal=principal, site_id=site_id, analysis_id=analysis_id, now=now()
            )
        except AnalysisSnapshotChanged as exc:
            raise HTTPException(status_code=409, detail="ANALYSIS_SNAPSHOT_CHANGED") from exc
        if view is None:
            raise not_found()
        return bounded_json(view, response=response)

    @router.get(
        "/v2/sites/{site_id}/analyses/{analysis_id}/evidence",
        response_model=AnalysisEvidencePageV2,
    )
    def get_evidence_v2(
        site_id: str,
        analysis_id: str,
        response: Response,
        limit: int = Query(default=32, ge=1, le=32),
        cursor: str | None = Query(default=None, min_length=1, max_length=512),
        access_purpose: Literal["EXTERNAL_AI"] | None = Header(
            default=None, alias="X-KSI-Access-Purpose"
        ),
        principal: Principal = Depends(read),  # noqa: B008
    ) -> Response:
        guard_external_ai_egress(principal=principal, site_id=site_id, response=response)
        try:
            page = facade.evidence_v2(
                principal=principal,
                site_id=site_id,
                analysis_id=analysis_id,
                now=now(),
                limit=limit,
                cursor=cursor,
            )
        except AnalysisSnapshotChanged as exc:
            raise HTTPException(status_code=409, detail="ANALYSIS_SNAPSHOT_CHANGED") from exc
        except ValueError as exc:
            raise cursor_error(exc) from exc
        if page is None:
            raise not_found()
        return bounded_json(page, response=response)

    @router.get("/v2/sites/{site_id}/analyses/{analysis_id}/coverage")
    def get_coverage_v2(
        site_id: str,
        analysis_id: str,
        response: Response,
        range_header: str | None = Header(default=None, alias="Range"),
        access_purpose: Literal["EXTERNAL_AI"] | None = Header(
            default=None, alias="X-KSI-Access-Purpose"
        ),
        principal: Principal = Depends(read),  # noqa: B008
    ) -> Response:
        guard_external_ai_egress(principal=principal, site_id=site_id, response=response)
        resource = facade.coverage_resource_v2(
            principal=principal, site_id=site_id, analysis_id=analysis_id, now=now()
        )
        if resource is None:
            raise not_found()
        payload, digest = resource
        total = len(payload)
        match = re.fullmatch(r"bytes=(\d{1,19})-(\d{1,19})", range_header or "")
        if match is None:
            raise HTTPException(
                status_code=416,
                detail="ANALYSIS_COVERAGE_RANGE_REQUIRED",
                headers={"Content-Range": f"bytes */{total}"},
            )
        start, end = (int(match.group(1)), int(match.group(2)))
        length = end - start + 1
        if start > end or end >= total or length > 65_536:
            raise HTTPException(
                status_code=416,
                detail="ANALYSIS_COVERAGE_RANGE_INVALID",
                headers={"Content-Range": f"bytes */{total}"},
            )
        range_response = Response(
            content=payload[start : end + 1],
            status_code=206,
            media_type="application/vnd.ksi.analysis-coverage+json",
        )
        if response.headers.get("X-KSI-External-AI-Egress") is not None:
            range_response.headers["X-KSI-External-AI-Egress"] = "ALLOWED"
        range_response.headers["Accept-Ranges"] = "bytes"
        range_response.headers["Content-Range"] = f"bytes {start}-{end}/{total}"
        range_response.headers["Content-Length"] = str(length)
        range_response.headers["X-KSI-Coverage-Digest"] = digest
        range_response.headers["X-KSI-Coverage-Total-Length"] = str(total)
        return range_response

    return router


__all__ = ["AnalysisScopeNotFound", "ExternalAnalysisFacade", "build_external_analysis_router"]
