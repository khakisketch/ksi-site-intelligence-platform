"""Requester-facing orchestration for independently attested two-surface profiles."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    DecisionVerdict,
    ExternalPairUseDecisionV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.surface_profile_job import (
    SurfaceProfileComparisonResultV1,
    SurfaceProfileComparisonSampleV1,
    SurfaceProfileComparisonV1,
)
from ksi_geo_spatial.surface_profile import (
    SurfaceProfileError,
    compare_profile_samples,
)

from ksi_core.domains.external.delivery.surface_profile_jobs import (
    SurfaceProfileComparisonInput,
    SurfaceProfileDomainError,
    SurfaceProfileJobStore,
)
from ksi_core.domains.external.quantity.external_use_decisions import (
    ExternalUseDecisionConflictError,
)
from ksi_core.identity.auth import Principal


def _digest(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _subject(value: SurfaceProfileComparisonInput) -> SealedExternalSubjectV1:
    return value.job.source.sealed_subject


def _observed_vertical_digest(
    baseline: SurfaceProfileComparisonInput,
    current: SurfaceProfileComparisonInput,
) -> str | None:
    before = baseline.receipt.vertical_reference
    after = current.receipt.vertical_reference
    if (
        before.provenance != "OBSERVED"
        or after.provenance != "OBSERVED"
        or before.observed is None
        or after.observed is None
        or before.observed != after.observed
    ):
        return None
    return before.observed.canonical_digest()


def _comparison_binding_digest(
    baseline: SurfaceProfileComparisonInput,
    current: SurfaceProfileComparisonInput,
) -> str:
    return _digest(
        {
            "domain": "ksi.surface-profile-comparison.binding.v1",
            "baseline": {
                "jobId": baseline.job.job_id,
                "jobDigest": baseline.job.job_digest,
                "receiptDigest": baseline.receipt.receipt_digest,
                "resultDigest": baseline.result.result_digest,
            },
            "current": {
                "jobId": current.job.job_id,
                "jobDigest": current.job.job_digest,
                "receiptDigest": current.receipt.receipt_digest,
                "resultDigest": current.result.result_digest,
            },
        }
    )


def _assert_comparable(
    baseline: SurfaceProfileComparisonInput,
    current: SurfaceProfileComparisonInput,
) -> tuple[str, str | None]:
    before, after = baseline.job, current.job
    before_result, after_result = baseline.result, current.result
    before_receipt, after_receipt = baseline.receipt, current.receipt
    if (
        before.job_id == after.job_id
        or (before.organization_id, before.site_id, before.work_area_id)
        != (after.organization_id, after.site_id, after.work_area_id)
        or before.requester_principal_id != after.requester_principal_id
        or before.feature.ref() != after.feature.ref()
        or before.profile_request.feature != after.profile_request.feature
        or before_result.feature != before.feature.ref()
        or after_result.feature != after.feature.ref()
        or before_result.line_digest != before.feature.line_digest
        or after_result.line_digest != after.feature.line_digest
        or before_result.line_length_m != after_result.line_length_m
        or before_result.sample_spacing_m != after_result.sample_spacing_m
        or not before_result.result_digest
        or not after_result.result_digest
    ):
        raise SurfaceProfileDomainError("INTEGRITY_MISMATCH", 409)

    before_subject, after_subject = _subject(baseline), _subject(current)
    if (
        before_subject == after_subject
        or before_subject.site_id != before.site_id
        or after_subject.site_id != after.site_id
        or before_subject.organization_id != before.organization_id
        or after_subject.organization_id != after.organization_id
    ):
        raise SurfaceProfileDomainError("INTEGRITY_MISMATCH", 409)

    before_vertical = before_receipt.vertical_reference
    before_measurements = before.source.inspection.measurements
    after_measurements = after.source.inspection.measurements
    if (
        before_measurements is None
        or after_measurements is None
        or before_receipt.artifact_id != before.source.artifact_id
        or after_receipt.artifact_id != after.source.artifact_id
        or before_receipt.source_sha256 != before.source.observed_sha256
        or after_receipt.source_sha256 != after.source.observed_sha256
        or before_receipt.observed_crs_digest != before_measurements.observed_crs_digest
        or after_receipt.observed_crs_digest != after_measurements.observed_crs_digest
        or before_receipt.observed_crs_identifier != before_measurements.observed_crs_identifier
        or after_receipt.observed_crs_identifier != after_measurements.observed_crs_identifier
        or before_receipt.vertical_reference != before.vertical_reference
        or after_receipt.vertical_reference != after.vertical_reference
    ):
        raise SurfaceProfileDomainError("INTEGRITY_MISMATCH", 409)

    if (
        len(before_result.samples) != len(after_result.samples)
        or not before_receipt.artifact_id
        or not after_receipt.artifact_id
    ):
        raise SurfaceProfileDomainError("INTEGRITY_MISMATCH", 409)

    vertical_digest = (
        before_vertical.observed.canonical_digest()
        if before_vertical.provenance == after_receipt.vertical_reference.provenance == "OBSERVED"
        and before_vertical.observed is not None
        else None
    )
    return before_receipt.observed_crs_digest, vertical_digest


def _comparison_result(
    baseline: SurfaceProfileComparisonInput,
    current: SurfaceProfileComparisonInput,
) -> SurfaceProfileComparisonResultV1:
    rows = compare_profile_samples(
        baseline.result.samples,
        current.result.samples,
    )
    samples = tuple(
        SurfaceProfileComparisonSampleV1(
            distance_m=row.distance_m,
            baseline_m=row.baseline_m,
            current_m=row.current_m,
            difference_m=row.difference_m,
            invalid_reason=row.invalid_reason.value if row.invalid_reason is not None else None,
        )
        for row in rows
    )
    differences = [sample.difference_m for sample in samples if sample.difference_m is not None]
    baseline_digest = baseline.result.result_digest
    current_digest = current.result.result_digest
    if baseline_digest is None or current_digest is None:
        raise SurfaceProfileDomainError("INTEGRITY_MISMATCH", 409)
    return SurfaceProfileComparisonResultV1(
        baseline_result_digest=baseline_digest,
        current_result_digest=current_digest,
        samples=samples,
        valid_count=len(differences),
        largest_rise_m=max((item for item in differences if item > 0), default=None),
        largest_drop_m=min((item for item in differences if item < 0), default=None),
    ).sealed()


class SurfaceProfileComparisonService:
    """Read exact retained results, resolve pair policy, then conditionally compare."""

    def __init__(self, *, jobs: SurfaceProfileJobStore, decisions: Any) -> None:
        if jobs is None or not callable(getattr(decisions, "request_pair", None)):
            raise ValueError("surface-profile comparison requires the Core pair decision owner")
        self._jobs = jobs
        self._decisions = decisions

    def _inputs(
        self,
        *,
        baseline_job_id: str,
        current_job_id: str,
        principal: Principal,
        scope: tuple[str, str],
        now: datetime,
    ) -> tuple[
        SurfaceProfileComparisonInput,
        SurfaceProfileComparisonInput,
    ]:
        baseline = self._jobs.comparison_input(
            job_id=baseline_job_id,
            principal=principal,
            now=now,
            expected_scope=scope,
        )
        current = self._jobs.comparison_input(
            job_id=current_job_id,
            principal=principal,
            now=now,
            expected_scope=scope,
        )
        _assert_comparable(baseline, current)
        return baseline, current

    @staticmethod
    def _view(
        baseline_job_id: str,
        current_job_id: str,
        decision: ExternalPairUseDecisionV1,
        result: SurfaceProfileComparisonResultV1 | None,
    ) -> SurfaceProfileComparisonV1:
        if (
            decision.decision_digest is None
            or decision.decision_digest != decision.canonical_digest()
        ):
            raise SurfaceProfileDomainError("INTEGRITY_MISMATCH", 409)
        return SurfaceProfileComparisonV1(
            baseline_job_id=baseline_job_id,
            current_job_id=current_job_id,
            decision_id=decision.decision_id,
            decision_digest=decision.decision_digest,
            verdict=("ELIGIBLE" if decision.verdict is DecisionVerdict.ELIGIBLE else "BLOCKED"),
            reasons=decision.reasons,
            remediations=decision.remediations,
            result=result,
        )

    def create(
        self,
        *,
        site_id: str,
        work_area_id: str,
        baseline_job_id: str,
        current_job_id: str,
        idempotency_key: str,
        principal: Principal,
        now: datetime,
    ) -> SurfaceProfileComparisonV1:
        baseline, current = self._inputs(
            baseline_job_id=baseline_job_id,
            current_job_id=current_job_id,
            principal=principal,
            scope=(site_id, work_area_id),
            now=now,
        )
        crs_digest, vertical_digest = _assert_comparable(baseline, current)
        binding_digest = _comparison_binding_digest(baseline, current)
        try:
            decision = self._decisions.request_pair(
                _subject(baseline),
                _subject(current),
                use="PROFILE_DIFFERENCE",
                zone_id=None,
                idempotency_key=idempotency_key,
                principal=principal,
                now=now,
                observed_crs_digest=crs_digest,
                observed_vertical_reference_digest=vertical_digest,
                baseline_artifact_id=baseline.receipt.artifact_id,
                baseline_source_sha256=baseline.receipt.source_sha256,
                current_artifact_id=current.receipt.artifact_id,
                current_source_sha256=current.receipt.source_sha256,
                profile_comparison_binding_digest=binding_digest,
                profile_work_area_id=baseline.job.work_area_id,
            )
        except ExternalUseDecisionConflictError as exc:
            raise SurfaceProfileDomainError("IDEMPOTENCY_CONFLICT", 409) from exc
        if (
            not isinstance(decision, ExternalPairUseDecisionV1)
            or decision.use != "PROFILE_DIFFERENCE"
            or decision.baseline_subject != _subject(baseline)
            or decision.current_subject != _subject(current)
            or decision.profile_comparison_binding_digest != binding_digest
        ):
            raise SurfaceProfileDomainError("INTEGRITY_MISMATCH", 409)
        if decision.verdict is DecisionVerdict.BLOCKED:
            return self._view(baseline_job_id, current_job_id, decision, None)
        return self._release(
            site_id=site_id,
            work_area_id=work_area_id,
            baseline_job_id=baseline_job_id,
            current_job_id=current_job_id,
            principal=principal,
            now=now,
            decision=decision,
            binding_digest=binding_digest,
            observed_crs_digest=crs_digest,
            observed_vertical_reference_digest=vertical_digest,
            baseline_artifact_id=baseline.receipt.artifact_id,
            baseline_source_sha256=baseline.receipt.source_sha256,
            current_artifact_id=current.receipt.artifact_id,
            current_source_sha256=current.receipt.source_sha256,
        )

    def get(
        self,
        *,
        site_id: str,
        work_area_id: str,
        baseline_job_id: str,
        current_job_id: str,
        decision_id: str,
        principal: Principal,
        now: datetime,
    ) -> SurfaceProfileComparisonV1:
        baseline, current = self._inputs(
            baseline_job_id=baseline_job_id,
            current_job_id=current_job_id,
            principal=principal,
            scope=(site_id, work_area_id),
            now=now,
        )
        decision = self._decisions.get_scoped(decision_id, principal=principal, site_id=site_id)
        binding_digest = _comparison_binding_digest(baseline, current)
        if (
            not isinstance(decision, ExternalPairUseDecisionV1)
            or decision.use != "PROFILE_DIFFERENCE"
            or decision.baseline_subject != _subject(baseline)
            or decision.current_subject != _subject(current)
            or decision.profile_comparison_binding_digest != binding_digest
        ):
            raise SurfaceProfileDomainError("NOT_FOUND", 404)
        if decision.verdict is DecisionVerdict.BLOCKED:
            return self._view(baseline_job_id, current_job_id, decision, None)
        crs_digest, vertical_digest = _assert_comparable(baseline, current)
        return self._release(
            site_id=site_id,
            work_area_id=work_area_id,
            baseline_job_id=baseline_job_id,
            current_job_id=current_job_id,
            principal=principal,
            now=now,
            decision=decision,
            binding_digest=binding_digest,
            observed_crs_digest=crs_digest,
            observed_vertical_reference_digest=vertical_digest,
            baseline_artifact_id=baseline.receipt.artifact_id,
            baseline_source_sha256=baseline.receipt.source_sha256,
            current_artifact_id=current.receipt.artifact_id,
            current_source_sha256=current.receipt.source_sha256,
        )

    def _release(
        self,
        *,
        site_id: str,
        work_area_id: str,
        baseline_job_id: str,
        current_job_id: str,
        principal: Principal,
        now: datetime,
        decision: ExternalPairUseDecisionV1,
        binding_digest: str,
        observed_crs_digest: str,
        observed_vertical_reference_digest: str | None,
        baseline_artifact_id: str,
        baseline_source_sha256: str,
        current_artifact_id: str,
        current_source_sha256: str,
    ) -> SurfaceProfileComparisonV1:
        response: list[SurfaceProfileComparisonV1] = []

        def release_if_current(candidate: ExternalPairUseDecisionV1) -> bool:
            if candidate != decision:
                return False
            with self._jobs.comparison_release(
                baseline_job_id=baseline_job_id,
                current_job_id=current_job_id,
                principal=principal,
                now=now,
                expected_scope=(site_id, work_area_id),
            ) as (baseline, current):
                crs_digest, vertical_digest = _assert_comparable(baseline, current)
                if _comparison_binding_digest(baseline, current) != binding_digest:
                    raise SurfaceProfileDomainError("INTEGRITY_MISMATCH", 409)
                if (
                    crs_digest != observed_crs_digest
                    or vertical_digest != observed_vertical_reference_digest
                    or baseline.receipt.observed_crs_identifier
                    != current.receipt.observed_crs_identifier
                    or baseline.receipt.observed_crs_digest != current.receipt.observed_crs_digest
                    or baseline.result.horizontal_crs != current.result.horizontal_crs
                    or baseline.receipt.artifact_id != baseline_artifact_id
                    or baseline.receipt.source_sha256 != baseline_source_sha256
                    or current.receipt.artifact_id != current_artifact_id
                    or current.receipt.source_sha256 != current_source_sha256
                    or candidate.profile_comparison_binding_digest != binding_digest
                ):
                    raise SurfaceProfileDomainError("INTEGRITY_MISMATCH", 409)
                observed_vertical = _observed_vertical_digest(baseline, current)
                if (
                    observed_vertical is None
                    or observed_vertical != observed_vertical_reference_digest
                ):
                    raise SurfaceProfileDomainError("INTEGRITY_MISMATCH", 409)
                try:
                    result = _comparison_result(baseline, current)
                except SurfaceProfileError as exc:
                    raise SurfaceProfileDomainError("INTEGRITY_MISMATCH", 409) from exc
                response.append(self._view(baseline_job_id, current_job_id, candidate, result))
                return True

        try:
            current_decision = self._decisions.resolve_eligible_pair_for_execution(
                decision.decision_id,
                principal=principal,
                site_id=site_id,
                observed_crs_digest=observed_crs_digest,
                observed_vertical_reference_digest=observed_vertical_reference_digest,
                baseline_artifact_id=baseline_artifact_id,
                baseline_source_sha256=baseline_source_sha256,
                current_artifact_id=current_artifact_id,
                current_source_sha256=current_source_sha256,
                profile_comparison_binding_digest=binding_digest,
                profile_work_area_id=work_area_id,
                before_return=release_if_current,
            )
        except SurfaceProfileDomainError:
            raise
        except (ConnectionError, OSError, RuntimeError) as exc:
            raise SurfaceProfileDomainError("CURRENTNESS_UNAVAILABLE", 503, retryable=True) from exc
        if current_decision is None:
            raise SurfaceProfileDomainError("PROFILE_COMPARISON_NO_LONGER_ELIGIBLE", 409)
        if current_decision != decision or len(response) != 1:
            raise SurfaceProfileDomainError("CURRENTNESS_UNAVAILABLE", 503, retryable=True)
        return response[0]


__all__ = ["SurfaceProfileComparisonService"]
