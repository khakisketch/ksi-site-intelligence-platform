"""Public facade keeps a known pre-admission block durable and non-numeric."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, NoReturn

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
    mount_auth,
)
from ksi_core.composition.external_graph import ExternalAnalysisWiring
from ksi_core.domains.external.quantity.external_analysis_api import (
    AnalysisSnapshotChanged,
    ExternalAnalysisFacade,
    _AnalysisAssessmentRecordPort,
    _AnalysisCalculationIdentityPort,
    _AnalysisCalculationRecordPort,
    _AnalysisCurrentViewPort,
    _AnalysisEvaluationPort,
    _AnalysisPublicRoutePort,
    build_external_analysis_router,
)
from ksi_core.domains.external.quantity.external_analysis_intents import AnalysisIntentStore
from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    AnalysisAssessmentRequestV2,
    ExternalRelativeVolumeAnalysisStore,
)
from ksi_core.domains.external.quantity.external_relative_volume_calculations import (
    CalculationCurrentDispositionV2,
    CalculationExecutionStatusV2,
    ExternalRelativeVolumeCalculationStore,
)
from ksi_core.durable_journal import DurableJournal
from ksi_event_contracts.external_analysis_api import (
    AnalysisBlockerV1,
    AnalysisEvidenceViewV1,
    AnalysisExecutionStateV1,
    AnalysisListV1,
    AnalysisObservationOptionsV1,
    AnalysisObservationOptionV1,
    AnalysisObservationSelectorV1,
    AnalysisSuitabilityStateV1,
    AnalysisViewV1,
    CreateAnalysisRequestV1,
)
from ksi_event_contracts.external_artifact_validation import (
    ObservedVerticalReferenceV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_relative_volume_analysis import (
    AdmissionDispositionV2,
    EvaluationOutcomeV1,
)
from ksi_event_contracts.external_relative_volume_calculation import (
    RelativeVolumeCoverageWitnessV2,
)


def _active_analysis_activation(tmp_path: Path) -> Any:
    from test_external_analysis_activation import _write_activation

    def activate(config: Any, worker: Any) -> Any:
        now = datetime.now(UTC)
        return _write_activation(
            tmp_path / "signed-analysis-activation",
            bindings={
                "organization_id": "org-a",
                "policy": config.policy,
                "runtime": config.runtime,
                "resource_envelope": config.resource_envelope,
                "worker_principal": worker,
            },
            activation_fields={
                "issuedAt": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                "validUntil": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            },
        )[2]

    return activate


def _principal() -> Principal:
    return Principal(
        principal_id="operator-a",
        organization_id="org-a",
        kind=PrincipalKind.OPERATOR,
        role=Role.ADMIN,
        device_id=None,
    )


@dataclass(frozen=True)
class _FakePolicyIdentity:
    policy_id: str
    version: int
    profile_id: str
    profile_digest: str
    algorithm_digest: str
    config_digest: str
    policy_digest: str | None


@dataclass(frozen=True)
class _FakeCalculationIdentity:
    calculation_id: str
    work_area_definition_digest: str
    baseline_subject: SealedExternalSubjectV1
    current_subject: SealedExternalSubjectV1
    baseline_dsm_artifact_id: str
    current_dsm_artifact_id: str
    baseline_dsm_observed_sha256: str
    current_dsm_observed_sha256: str
    baseline_dsm_observed_size_bytes: int
    current_dsm_observed_size_bytes: int
    baseline_observed_crs_identifier: str
    current_observed_crs_identifier: str
    baseline_observed_crs_digest: str
    current_observed_crs_digest: str
    baseline_vertical_reference: ObservedVerticalReferenceV1
    current_vertical_reference: ObservedVerticalReferenceV1
    baseline_vertical_unit: str
    current_vertical_unit: str
    baseline_transform: tuple[float, float, float, float, float, float]
    current_transform: tuple[float, float, float, float, float, float]
    baseline_transform_digest: str
    current_transform_digest: str
    baseline_inspection_report_digest: str
    current_inspection_report_digest: str
    baseline_input_digest: str
    current_input_digest: str
    policy: _FakePolicyIdentity
    worker_executable_digest: str
    worker_build_digest: str
    runtime_image_version: str
    runtime_image_oci_digest: str
    dependency_lock_digest: str


@dataclass(frozen=True)
class _FakeAdmission:
    admission_id: str
    admission_digest: str | None
    calculation_identity_digest: str | None
    calculation_identity: _AnalysisCalculationIdentityPort | None
    disposition: AdmissionDispositionV2
    reason_codes: tuple[str, ...]
    evaluation_revisions: tuple[_AnalysisEvaluationPort, ...]


@dataclass(frozen=True)
class _FakeEvaluation:
    evaluation_id: str
    epoch: Literal["BASELINE", "CURRENT"]
    revision: int
    evaluation_digest: str | None
    outcome: EvaluationOutcomeV1
    reason_codes: tuple[str, ...]
    assessed_at: datetime
    evidence_facts: tuple[()] = ()


@dataclass(frozen=True)
class _FakeAssessmentRecord:
    admission: _FakeAdmission


@dataclass(frozen=True)
class _FakeAuthorization:
    authorization_id: str


@dataclass(frozen=True)
class _FakeMetrics:
    cut_m3: float
    fill_m3: float
    net_m3: float
    threshold_m: float


@dataclass(frozen=True)
class _FakeNumericResult:
    metrics: _FakeMetrics
    coverage: RelativeVolumeCoverageWitnessV2


@dataclass(frozen=True)
class _FakeReport:
    report_id: str
    report_digest: str | None
    numeric_result_identity_digest: str | None
    computed_at: datetime
    numeric_result: _FakeNumericResult


@dataclass(frozen=True)
class _FakeFailure:
    reason_code: str
    failure_digest: str | None


@dataclass(frozen=True)
class _FakeCalculationRecord:
    request_id: str
    organization_id: str
    calculation_identity_digest: str
    status: CalculationExecutionStatusV2
    authorization: _FakeAuthorization
    report: _FakeReport | None
    failure: _FakeFailure | None


@dataclass(frozen=True)
class _FakeCurrentView:
    disposition: CalculationCurrentDispositionV2
    report: _FakeReport | None
    failure: _FakeFailure | None = None


class _UnusedAssessments:
    def get_history(
        self, request_id: str, *, organization_id: str
    ) -> _AnalysisAssessmentRecordPort | None:
        raise AssertionError("unexpected assessment history lookup")

    def get_history_for_principal(
        self, request_id: str, *, principal: Principal
    ) -> _AnalysisAssessmentRecordPort | None:
        raise AssertionError("unexpected principal-scoped assessment history lookup")

    def get_current(
        self, request_id: str, *, principal: Principal, now: datetime
    ) -> _AnalysisAssessmentRecordPort | None:
        raise AssertionError("unexpected assessment currentness lookup")

    def get_current_for_read(
        self, request_id: str, *, principal: Principal, now: datetime
    ) -> _AnalysisAssessmentRecordPort | None:
        raise AssertionError("unexpected assessment read-currentness lookup")

    def assess_and_record(
        self, *, principal: Principal, request: AnalysisAssessmentRequestV2, now: datetime
    ) -> _AnalysisAssessmentRecordPort:
        raise AssertionError("unexpected assessment write")


class _UnusedCalculations:
    def get_history(
        self, request_id: str, *, organization_id: str
    ) -> _AnalysisCalculationRecordPort | None:
        raise AssertionError("unexpected calculation history lookup")

    def issue(
        self,
        *,
        principal: Principal,
        request_id: str,
        calculation_identity_digest: str,
        idempotency_key: str,
        now: datetime,
    ) -> _AnalysisCalculationRecordPort:
        raise AssertionError("unexpected calculation issue")

    def get_current(
        self, *, request_id: str, principal: Principal, now: datetime
    ) -> _AnalysisCurrentViewPort | None:
        raise AssertionError("unexpected calculation currentness lookup")


class _Sites:
    def get_scoped(self, site_id: str, organization_id: str) -> object | None:
        return object() if (site_id, organization_id) == ("site-a", "org-a") else None


class _WorkAreas:
    def get(self, work_area_id: str) -> object | None:
        return SimpleNamespace(site_id="site-a") if work_area_id == "area-a" else None


class _RegisteredButUnsealedReconstruction:
    def resolve_submission_ref(self, *args: object, **kwargs: object) -> str:
        del args, kwargs
        return "internal-submission-a"

    def get(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        return SimpleNamespace(manifest=None)


class _SealedReconstruction:
    def resolve_submission_ref(self, *args: object, **kwargs: object) -> str:
        del args, kwargs
        return "internal-submission-a"

    def get(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        return SimpleNamespace(
            manifest=SimpleNamespace(manifest_digest="sha256:" + "b" * 64),
            submission=SimpleNamespace(submission_digest="sha256:" + "c" * 64),
        )


class _ObservationOptionsReconstruction:
    def list(self, work_order_id: str, *, organization_id: str, site_id: str) -> tuple[object, ...]:
        assert (organization_id, site_id) == ("org-a", "site-a")
        return (
            SimpleNamespace(
                work_order_id=work_order_id,
                observation_epoch_id="obs-epoch-" + work_order_id,
                submission=SimpleNamespace(
                    submission_id="submission-" + work_order_id,
                    revision=1,
                    input_declaration=SimpleNamespace(
                        capture_started_at=datetime(2026, 9, 20, tzinfo=UTC),
                        capture_ended_at=datetime(2026, 9, 21, tzinfo=UTC),
                    ),
                ),
            ),
        )


class _WorkOrders:
    def list_for_site(self, site_id: str, *, organization_id: str) -> tuple[object, ...]:
        assert (site_id, organization_id) == ("site-a", "org-a")
        return (SimpleNamespace(work_order_id="baseline-order"),)


class _AdmittedAssessments:
    def __init__(self) -> None:
        self.records: dict[str, _FakeAssessmentRecord] = {}
        self.assess_calls = 0

    def get_history(self, request_id: str, *, organization_id: str) -> _FakeAssessmentRecord | None:
        del organization_id
        return self.records.get(request_id)

    def get_history_for_principal(
        self, request_id: str, *, principal: Principal
    ) -> _FakeAssessmentRecord | None:
        del principal
        return self.records.get(request_id)

    def get_current(
        self, request_id: str, *, principal: Principal, now: datetime
    ) -> _FakeAssessmentRecord | None:
        del principal, now
        return self.records.get(request_id)

    def get_current_for_read(
        self, request_id: str, *, principal: Principal, now: datetime
    ) -> _FakeAssessmentRecord | None:
        del principal, now
        return self.records.get(request_id)

    def assess_and_record(
        self, *, principal: Principal, request: AnalysisAssessmentRequestV2, now: datetime
    ) -> _FakeAssessmentRecord:
        del principal, now
        self.assess_calls += 1
        request_id = request.request_id
        record = _FakeAssessmentRecord(
            admission=_FakeAdmission(
                admission_id="admission-" + request_id,
                admission_digest="sha256:" + "a" * 64,
                calculation_identity_digest="sha256:" + "d" * 64,
                calculation_identity=None,
                disposition=AdmissionDispositionV2.ADMIT_PROVISIONAL,
                reason_codes=(),
                evaluation_revisions=(),
            )
        )
        self.records[request_id] = record
        return record


class _CrashThenQueueCalculations:
    def __init__(
        self,
        *,
        record_organization_id: str = "org-a",
        record_identity_digest: str = "sha256:" + "d" * 64,
    ) -> None:
        self.issue_calls = 0
        self.current_request_ids: list[str] = []
        self.records: dict[str, _FakeCalculationRecord] = {}
        self._record_organization_id = record_organization_id
        self._record_identity_digest = record_identity_digest

    def issue(
        self,
        *,
        principal: Principal,
        request_id: str,
        calculation_identity_digest: str,
        idempotency_key: str,
        now: datetime,
    ) -> _FakeCalculationRecord:
        self.issue_calls += 1
        if self.issue_calls == 1:
            raise RuntimeError("simulated process interruption after AP append")
        record = _FakeCalculationRecord(
            request_id="calculation-shared-1",
            organization_id=self._record_organization_id,
            calculation_identity_digest=self._record_identity_digest,
            status=CalculationExecutionStatusV2.QUEUED,
            authorization=_FakeAuthorization(authorization_id="authorization-shared-1"),
            report=None,
            failure=None,
        )
        self.records[record.request_id] = record
        return record

    def get_history(
        self, request_id: str, *, organization_id: str
    ) -> _FakeCalculationRecord | None:
        del organization_id
        return self.records.get(request_id)

    def get_current(
        self, *, request_id: str, principal: Principal, now: datetime
    ) -> _FakeCurrentView | None:
        del principal, now
        self.current_request_ids.append(request_id)
        record = self.records.get(request_id)
        if record is None:
            return None
        return _FakeCurrentView(
            disposition=CalculationCurrentDispositionV2.PENDING,
            report=None,
        )


class _EvidenceReconstructions:
    def get(
        self,
        work_order_id: str,
        submission_id: str,
        revision: int,
        *,
        organization_id: str,
        site_id: str,
    ) -> object | None:
        assert (organization_id, site_id, revision) == ("org-a", "site-a", 1)
        value = "baseline" if work_order_id == "baseline-order" else "current"
        return SimpleNamespace(
            observation_epoch_id="obs-epoch-" + value,
            manifest=SimpleNamespace(
                manifest_digest="sha256:" + ("b" if value == "baseline" else "c") * 64
            ),
            submission=SimpleNamespace(
                submission_digest="sha256:" + ("d" if value == "baseline" else "e") * 64
            ),
        )


class _EvidenceAssessments(_UnusedAssessments):
    def __init__(self, analysis_id: str) -> None:
        baseline = SealedExternalSubjectV1(
            organization_id="org-a",
            site_id="site-a",
            work_order_id="baseline-order",
            submission_id="baseline-submission",
            revision=1,
            submission_digest="sha256:" + "d" * 64,
            manifest_digest="sha256:" + "b" * 64,
        )
        current = SealedExternalSubjectV1(
            organization_id="org-a",
            site_id="site-a",
            work_order_id="current-order",
            submission_id="current-submission",
            revision=1,
            submission_digest="sha256:" + "e" * 64,
            manifest_digest="sha256:" + "c" * 64,
        )
        identity = _FakeCalculationIdentity(
            calculation_id="calculation-evidence",
            work_area_definition_digest="sha256:" + "0" * 64,
            baseline_subject=baseline,
            current_subject=current,
            baseline_dsm_artifact_id="baseline-dsm",
            current_dsm_artifact_id="current-dsm",
            baseline_dsm_observed_sha256="sha256:" + "1" * 64,
            current_dsm_observed_sha256="sha256:" + "2" * 64,
            baseline_dsm_observed_size_bytes=101,
            current_dsm_observed_size_bytes=202,
            baseline_observed_crs_identifier="EPSG:5186",
            current_observed_crs_identifier="EPSG:5186",
            baseline_observed_crs_digest="sha256:" + "3" * 64,
            current_observed_crs_digest="sha256:" + "3" * 64,
            baseline_vertical_reference=ObservedVerticalReferenceV1(
                identifier="EPSG:5773", basis="EGM96 height"
            ),
            current_vertical_reference=ObservedVerticalReferenceV1(
                identifier="EPSG:5773", basis="EGM96 height"
            ),
            baseline_vertical_unit="metre",
            current_vertical_unit="metre",
            baseline_transform=(1.0, 0.0, 0.0, 0.0, -1.0, 10.0),
            current_transform=(1.0, 0.0, 0.0, 0.0, -1.0, 10.0),
            baseline_transform_digest="sha256:" + "4" * 64,
            current_transform_digest="sha256:" + "4" * 64,
            baseline_inspection_report_digest="sha256:" + "5" * 64,
            current_inspection_report_digest="sha256:" + "6" * 64,
            baseline_input_digest="sha256:" + "7" * 64,
            current_input_digest="sha256:" + "8" * 64,
            policy=_FakePolicyIdentity(
                policy_id="evidence-policy",
                version=1,
                profile_id="evidence-profile",
                profile_digest="sha256:" + "a" * 64,
                algorithm_digest="sha256:" + "b" * 64,
                config_digest="sha256:" + "c" * 64,
                policy_digest="sha256:" + "d" * 64,
            ),
            worker_executable_digest="sha256:" + "e" * 64,
            worker_build_digest="sha256:" + "f" * 64,
            runtime_image_version="local-test",
            runtime_image_oci_digest="sha256:" + "1" * 64,
            dependency_lock_digest="sha256:" + "2" * 64,
        )
        self.record = _FakeAssessmentRecord(
            admission=_FakeAdmission(
                admission_id="admission-" + analysis_id,
                admission_digest="sha256:" + "9" * 64,
                calculation_identity_digest="sha256:" + "a" * 64,
                calculation_identity=identity,
                disposition=AdmissionDispositionV2.ADMIT_PROVISIONAL,
                reason_codes=(),
                evaluation_revisions=(),
            )
        )

    def get_history_for_principal(
        self, request_id: str, *, principal: Principal
    ) -> _FakeAssessmentRecord:
        del request_id, principal
        return self.record

    def get_current_for_read(
        self, request_id: str, *, principal: Principal, now: datetime
    ) -> _FakeAssessmentRecord | None:
        del request_id, principal, now
        return self.record


class _NoCalculations:
    def get_history(
        self, request_id: str, *, organization_id: str
    ) -> _AnalysisCalculationRecordPort | None:
        return None

    def issue(
        self,
        *,
        principal: Principal,
        request_id: str,
        calculation_identity_digest: str,
        idempotency_key: str,
        now: datetime,
    ) -> _AnalysisCalculationRecordPort:
        raise AssertionError("unexpected calculation issue")

    def get_current(
        self, *, request_id: str, principal: Principal, now: datetime
    ) -> _AnalysisCurrentViewPort | None:
        return None


class _EffectiveTerminalCalculations(_UnusedCalculations):
    """NX-owned effective terminal verdict with no synthetic failure record."""

    def __init__(self, disposition: CalculationCurrentDispositionV2) -> None:
        self._disposition = disposition

    def get_history(
        self, request_id: str, *, organization_id: str
    ) -> _FakeCalculationRecord | None:
        if (request_id, organization_id) != ("calculation-terminal", "org-a"):
            return None
        return _FakeCalculationRecord(
            request_id=request_id,
            organization_id=organization_id,
            calculation_identity_digest="sha256:" + "a" * 64,
            status=CalculationExecutionStatusV2.RUNNING,
            authorization=_FakeAuthorization(authorization_id="authorization-terminal"),
            report=None,
            failure=None,
        )

    def get_current(
        self, *, request_id: str, principal: Principal, now: datetime
    ) -> _FakeCurrentView:
        del request_id, principal, now
        return _FakeCurrentView(disposition=self._disposition, report=None)


class _FailedAnalysisCalculations(_UnusedCalculations):
    def __init__(self, reason_code: str) -> None:
        self._failure = _FakeFailure(
            reason_code=reason_code,
            failure_digest="sha256:" + "c" * 64,
        )

    def get_history(
        self, request_id: str, *, organization_id: str
    ) -> _FakeCalculationRecord | None:
        if (request_id, organization_id) != ("calculation-terminal", "org-a"):
            return None
        return _FakeCalculationRecord(
            request_id=request_id,
            organization_id=organization_id,
            calculation_identity_digest="sha256:" + "a" * 64,
            status=CalculationExecutionStatusV2.FAILED,
            authorization=_FakeAuthorization(authorization_id="authorization-terminal"),
            report=None,
            failure=self._failure,
        )

    def get_current(
        self, *, request_id: str, principal: Principal, now: datetime
    ) -> _FakeCurrentView:
        del request_id, principal, now
        return _FakeCurrentView(
            disposition=CalculationCurrentDispositionV2.FAILED,
            report=None,
            failure=self._failure,
        )


class _RecordedCalculationOnly(_UnusedCalculations):
    """A durable NX record that must be projected before AP currentness."""

    def __init__(self, calculation_identity_digest: str) -> None:
        self._record = _FakeCalculationRecord(
            request_id="calculation-recorded",
            organization_id="org-a",
            calculation_identity_digest=calculation_identity_digest,
            status=CalculationExecutionStatusV2.COMPLETED,
            authorization=_FakeAuthorization(authorization_id="authorization-recorded"),
            report=None,
            failure=None,
        )

    def get_history(
        self, request_id: str, *, organization_id: str
    ) -> _FakeCalculationRecord | None:
        if (request_id, organization_id) == ("calculation-recorded", "org-a"):
            return self._record
        return None

    def get_current(
        self, *, request_id: str, principal: Principal, now: datetime
    ) -> _AnalysisCurrentViewPort:
        del request_id, principal, now
        raise AssertionError("stale or mismatched AP must suppress NX result projection")


def test_facade_projects_current_completion_when_history_read_precedes_worker_report(
    tmp_path: Path,
) -> None:
    """A worker completing between NX reads yields one coherent public projection."""
    journal_path = tmp_path / "analysis-intents.jsonl"
    intents = AnalysisIntentStore(DurableJournal(journal_path))
    created = intents.record_intent(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="area-a",
        request=_request(),
        idempotency_key="history-current-race-key",
        now=datetime(2026, 9, 22, tzinfo=UTC),
    )
    intents.link_calculation(
        analysis_id=created.analysis_id,
        organization_id="org-a",
        calculation_request_id="calculation-race",
    )
    coverage = RelativeVolumeCoverageWitnessV2(
        rows=1,
        columns=1,
        row_offset=0,
        column_offset=0,
        selected_mask_b64="gA==",
        common_valid_mask_b64="gA==",
        unavailable_mask_b64="AA==",
        threshold_excluded_mask_b64="AA==",
        selected_cell_count=1,
        common_valid_cell_count=1,
        unavailable_cell_count=0,
        threshold_excluded_cell_count=0,
        cell_area_m2=1.0,
        selected_area_m2=1.0,
        common_valid_area_m2=1.0,
        bounds=(0.0, 0.0, 1.0, 1.0),
    ).sealed()
    report = _FakeReport(
        report_id="report-race",
        report_digest="sha256:" + "b" * 64,
        numeric_result_identity_digest="sha256:" + "c" * 64,
        computed_at=datetime(2026, 9, 22, tzinfo=UTC),
        numeric_result=_FakeNumericResult(
            metrics=_FakeMetrics(cut_m3=3.0, fill_m3=1.0, net_m3=-2.0, threshold_m=0.0),
            coverage=coverage,
        ),
    )

    class CompletionBetweenReads(_UnusedCalculations):
        def get_history(
            self, request_id: str, *, organization_id: str
        ) -> _FakeCalculationRecord | None:
            if (request_id, organization_id) != ("calculation-race", "org-a"):
                return None
            return _FakeCalculationRecord(
                request_id=request_id,
                organization_id=organization_id,
                calculation_identity_digest="sha256:" + "a" * 64,
                status=CalculationExecutionStatusV2.QUEUED,
                authorization=_FakeAuthorization(authorization_id="authorization-race"),
                report=None,
                failure=None,
            )

        def get_current(
            self, *, request_id: str, principal: Principal, now: datetime
        ) -> _AnalysisCurrentViewPort:
            del request_id, principal, now
            return _FakeCurrentView(
                disposition=CalculationCurrentDispositionV2.AVAILABLE,
                report=report,
            )

    journal_before_get = journal_path.read_bytes()
    view = ExternalAnalysisFacade(
        intents=intents,
        assessments=_EvidenceAssessments(created.analysis_id),
        calculations=CompletionBetweenReads(),
        reconstructions=_EvidenceReconstructions(),
        sites=_Sites(),
        work_areas=_WorkAreas(),
    ).get(
        principal=_principal(),
        site_id="site-a",
        analysis_id=created.analysis_id,
        now=datetime(2026, 9, 22, tzinfo=UTC),
    )

    assert view is not None
    assert view.execution_state is AnalysisExecutionStateV1.COMPLETED
    assert view.authority.report_digest == report.report_digest
    assert view.result is not None
    assert view.result.result_id == report.report_id
    assert view.result.metrics.net_m3 == -2.0
    assert journal_path.read_bytes() == journal_before_get
    intents.close()


class _StaleEvidenceAssessments(_EvidenceAssessments):
    def get_current_for_read(
        self, request_id: str, *, principal: Principal, now: datetime
    ) -> _FakeAssessmentRecord | None:
        del request_id, principal, now
        return None


def _request() -> CreateAnalysisRequestV1:
    return CreateAnalysisRequestV1(
        baseline=AnalysisObservationSelectorV1(
            work_order_id="baseline-order", submission_ref="ers-v1-" + "a" * 64, revision=1
        ),
        current=AnalysisObservationSelectorV1(
            work_order_id="current-order", submission_ref="ers-v1-" + "b" * 64, revision=1
        ),
    )


def test_known_pre_admission_block_survives_retry_and_read_after_restart(tmp_path: Path) -> None:
    """GET returns the original typed block; it never invents AP recovery state or numbers."""
    journal_path = tmp_path / "analysis-intents.jsonl"
    intents = AnalysisIntentStore(DurableJournal(journal_path))
    facade = ExternalAnalysisFacade(
        intents=intents,
        assessments=_UnusedAssessments(),
        calculations=_UnusedCalculations(),
        reconstructions=_RegisteredButUnsealedReconstruction(),
        sites=_Sites(),
        work_areas=_WorkAreas(),
    )
    now = datetime(2026, 9, 22, tzinfo=UTC)

    created = facade.create_or_resume(
        principal=_principal(),
        site_id="site-a",
        work_area_id="area-a",
        request=_request(),
        idempotency_key="blocked-request",
        now=now,
    )
    assert created.execution_state is AnalysisExecutionStateV1.NOT_STARTED
    assert created.suitability_state is AnalysisSuitabilityStateV1.BLOCKED
    assert {item.code for item in created.blockers} == {"RECONSTRUCTION_NOT_SEALED"}
    assert created.result is None
    retry = facade.create_or_resume(
        principal=_principal(),
        site_id="site-a",
        work_area_id="area-a",
        request=_request(),
        idempotency_key="blocked-request",
        now=now,
    )
    assert retry.suitability_state is AnalysisSuitabilityStateV1.BLOCKED
    assert {item.code for item in retry.blockers} == {"RECONSTRUCTION_NOT_SEALED"}
    intents.close()

    recovered_intents = AnalysisIntentStore(DurableJournal(journal_path))
    recovered = ExternalAnalysisFacade(
        intents=recovered_intents,
        assessments=_UnusedAssessments(),
        calculations=_UnusedCalculations(),
        reconstructions=_RegisteredButUnsealedReconstruction(),
        sites=_Sites(),
        work_areas=_WorkAreas(),
    ).get(principal=_principal(), site_id="site-a", analysis_id=created.analysis_id, now=now)
    assert recovered is not None
    assert recovered.suitability_state is AnalysisSuitabilityStateV1.BLOCKED
    assert {item.code for item in recovered.blockers} == {"RECONSTRUCTION_NOT_SEALED"}
    assert recovered.result is None
    recovered_intents.close()


def test_same_key_post_resumes_ap_to_nx_gap_without_reassessing(tmp_path: Path) -> None:
    """A retry resumes a real missing NX handoff while retaining the original AP record."""
    intents = AnalysisIntentStore(DurableJournal(tmp_path / "analysis-intents.jsonl"))
    assessments = _AdmittedAssessments()
    calculations = _CrashThenQueueCalculations()
    facade = ExternalAnalysisFacade(
        intents=intents,
        assessments=assessments,
        calculations=calculations,
        reconstructions=_SealedReconstruction(),
        sites=_Sites(),
        work_areas=_WorkAreas(),
    )
    now = datetime(2026, 9, 22, tzinfo=UTC)

    with pytest.raises(RuntimeError, match="simulated process interruption"):
        facade.create_or_resume(
            principal=_principal(),
            site_id="site-a",
            work_area_id="area-a",
            request=_request(),
            idempotency_key="resume-after-ap",
            now=now,
        )

    resumed = facade.create_or_resume(
        principal=_principal(),
        site_id="site-a",
        work_area_id="area-a",
        request=_request(),
        idempotency_key="resume-after-ap",
        now=now,
    )
    assert assessments.assess_calls == 1
    assert calculations.issue_calls == 2
    assert resumed.execution_state is AnalysisExecutionStateV1.QUEUED
    assert resumed.suitability_state is AnalysisSuitabilityStateV1.PROVISIONAL_ACCURACY_UNVERIFIED
    assert calculations.current_request_ids == ["calculation-shared-1"]
    linked = intents.get(resumed.analysis_id, organization_id="org-a")
    assert linked is not None
    assert linked.calculation_request_id == "calculation-shared-1"
    intents.close()


def test_same_key_recovery_never_links_a_forged_nx_calculation(tmp_path: Path) -> None:
    """An unlinked retry validates the returned NX organization and AP identity first."""
    intents = AnalysisIntentStore(DurableJournal(tmp_path / "analysis-intents.jsonl"))
    assessments = _AdmittedAssessments()
    calculations = _CrashThenQueueCalculations(
        record_organization_id="org-b", record_identity_digest="sha256:" + "e" * 64
    )
    facade = ExternalAnalysisFacade(
        intents=intents,
        assessments=assessments,
        calculations=calculations,
        reconstructions=_SealedReconstruction(),
        sites=_Sites(),
        work_areas=_WorkAreas(),
    )
    now = datetime(2026, 9, 22, tzinfo=UTC)

    with pytest.raises(RuntimeError, match="simulated process interruption"):
        facade.create_or_resume(
            principal=_principal(),
            site_id="site-a",
            work_area_id="area-a",
            request=_request(),
            idempotency_key="forged-calculation-recovery",
            now=now,
        )
    with pytest.raises(RuntimeError, match="does not match analysis admission"):
        facade.create_or_resume(
            principal=_principal(),
            site_id="site-a",
            work_area_id="area-a",
            request=_request(),
            idempotency_key="forged-calculation-recovery",
            now=now,
        )

    (intent,) = intents.list_for_organization(organization_id="org-a")
    assert intent.calculation_request_id is None
    assert assessments.assess_calls == 1
    intents.close()


def test_observation_options_expose_only_scoped_opaque_selectors_and_capture_facts(
    tmp_path: Path,
) -> None:
    """Options are Site-read data; callers never provide an internal submission ID."""
    intents = AnalysisIntentStore(DurableJournal(tmp_path / "analysis-intents.jsonl"))
    facade = ExternalAnalysisFacade(
        intents=intents,
        assessments=_UnusedAssessments(),
        calculations=_UnusedCalculations(),
        reconstructions=_ObservationOptionsReconstruction(),
        sites=_Sites(),
        work_areas=_WorkAreas(),
        work_orders=_WorkOrders(),
    )
    options = facade.observation_options(principal=_principal(), site_id="site-a")
    assert len(options.items) == 1
    assert options.items[0].selector.submission_ref.startswith("ers-v1-")
    assert options.items[0].observation_epoch_id == "obs-epoch-baseline-order"
    intents.close()


def test_options_and_collection_are_bounded_and_newest_first(tmp_path: Path) -> None:
    """Large local histories remain usable through bounded deterministic projections."""
    now = datetime(2026, 9, 22, tzinfo=UTC)

    class ManyOrders:
        def list_for_site(self, site_id: str, *, organization_id: str) -> tuple[object, ...]:
            assert (site_id, organization_id) == ("site-a", "org-a")
            return tuple(
                SimpleNamespace(work_order_id=f"order-{index:03d}") for index in range(501)
            )

    class ManyRevisions:
        def list(
            self, work_order_id: str, *, organization_id: str, site_id: str
        ) -> tuple[object, ...]:
            index = int(work_order_id.removeprefix("order-"))
            return (
                SimpleNamespace(
                    work_order_id=work_order_id,
                    observation_epoch_id=f"epoch-{index:03d}",
                    submission=SimpleNamespace(
                        submission_id=f"submission-{index:03d}",
                        revision=1,
                        input_declaration=SimpleNamespace(
                            capture_started_at=now + timedelta(seconds=index),
                            capture_ended_at=now + timedelta(seconds=index + 1),
                        ),
                    ),
                ),
            )

    intents = AnalysisIntentStore(DurableJournal(tmp_path / "analysis-intents.jsonl"))
    facade = ExternalAnalysisFacade(
        intents=intents,
        assessments=_UnusedAssessments(),
        calculations=_UnusedCalculations(),
        reconstructions=ManyRevisions(),
        sites=_Sites(),
        work_areas=_WorkAreas(),
        work_orders=ManyOrders(),
    )
    options = facade.observation_options(principal=_principal(), site_id="site-a")
    assert len(options.items) == 500
    assert options.items[0].observation_epoch_id == "epoch-500"
    assert options.items[-1].observation_epoch_id == "epoch-001"

    request = _request()
    for index in range(501):
        intents.record_intent(
            organization_id="org-a",
            site_id="site-a",
            work_area_id="area-a",
            request=request,
            idempotency_key=f"bounded-list-{index}",
            now=now + timedelta(seconds=index),
            pre_admission_blockers=(AnalysisBlockerV1(code="RECONSTRUCTION_NOT_SEALED"),),
        )
    items = facade.list(principal=_principal(), site_id="site-a", now=now).items
    assert len(items) == 500
    assert items[0].created_at == now + timedelta(seconds=500)
    assert items[-1].created_at == now + timedelta(seconds=1)
    intents.close()


def test_v2_list_uses_bounded_keyset_pages_without_dropping_history(tmp_path: Path) -> None:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    intents = AnalysisIntentStore(DurableJournal(tmp_path / "analysis-intents.jsonl"))
    facade = ExternalAnalysisFacade(
        intents=intents,
        assessments=_UnusedAssessments(),
        calculations=_UnusedCalculations(),
        reconstructions=SimpleNamespace(),
        sites=_Sites(),
        work_areas=_WorkAreas(),
    )
    request = _request()
    for index in range(51):
        intents.record_intent(
            organization_id="org-a",
            site_id="site-a",
            work_area_id="area-a",
            request=request,
            idempotency_key=f"v2-keyset-{index}",
            now=now + timedelta(seconds=index),
            pre_admission_blockers=(AnalysisBlockerV1(code="RECONSTRUCTION_NOT_SEALED"),),
        )
    first = facade.list_v2(
        principal=_principal(), site_id="site-a", now=now, limit=50, cursor=None
    )
    assert len(first.items) == 50
    assert first.next_cursor is not None
    second = facade.list_v2(
        principal=_principal(),
        site_id="site-a",
        now=now,
        limit=50,
        cursor=first.next_cursor,
    )
    assert len(second.items) == 1
    assert second.next_cursor is None
    ids = [item.analysis_id for item in first.items + second.items]
    assert len(ids) == len(set(ids)) == 51
    with pytest.raises(ValueError, match="ANALYSIS_CURSOR_INVALID"):
        facade.list_v2(
            principal=_principal(), site_id="site-a", now=now, limit=50, cursor="broken"
        )
    intents.close()


@pytest.mark.parametrize(
    "payload",
    [
        {"createdAt": 42, "analysisId": "analysis-a"},
        {"createdAt": "2026-09-22T00:00:00Z", "analysisId": 17},
        {"createdAt": [], "analysisId": "analysis-a"},
    ],
)
def test_v2_list_rejects_decoded_cursor_with_wrong_field_types(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    intents = AnalysisIntentStore(DurableJournal(tmp_path / "analysis-intents.jsonl"))
    facade = ExternalAnalysisFacade(
        intents=intents,
        assessments=_UnusedAssessments(),
        calculations=_UnusedCalculations(),
        reconstructions=SimpleNamespace(),
        sites=_Sites(),
        work_areas=_WorkAreas(),
    )
    malformed = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    with pytest.raises(ValueError, match="ANALYSIS_CURSOR_INVALID"):
        facade.list_v2(
            principal=_principal(), site_id="site-a", now=now, limit=50, cursor=malformed
        )
    intents.close()


def test_v2_projection_retries_when_worker_completion_interleaves_view_and_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    route_fixture = _PublicApiFacade()
    stable_view = route_fixture.view
    stable_evidence = route_fixture.evidence(
        principal=_principal(), site_id="site-a", analysis_id=stable_view.analysis_id, now=now
    )
    facade = ExternalAnalysisFacade.__new__(ExternalAnalysisFacade)
    # Model worker completion between independent reads: the first evidence
    # snapshot carries a newer durable AP/NX authority digest than the view.
    assert stable_evidence is not None
    completed_evidence = stable_evidence.model_copy(
        update={
            "authority": stable_evidence.authority.model_copy(
                update={"failure_digest": "sha256:" + "0" * 64}
            )
        }
    )
    reads = {"view": 0, "evidence": 0}

    def get(*, principal: Principal, site_id: str, analysis_id: str, now: datetime) -> Any:
        del principal, site_id, analysis_id, now
        reads["view"] += 1
        return stable_view

    def evidence(*, principal: Principal, site_id: str, analysis_id: str, now: datetime) -> Any:
        del principal, site_id, analysis_id, now
        reads["evidence"] += 1
        return completed_evidence if reads["evidence"] == 1 else stable_evidence

    monkeypatch.setattr(facade, "get", get)
    monkeypatch.setattr(facade, "evidence", evidence)
    projected = facade.get_v2(
        principal=_principal(), site_id="site-a", analysis_id=stable_view.analysis_id, now=now
    )
    assert projected is not None
    assert reads == {"view": 4, "evidence": 2}
    assert projected.analysis_id == stable_view.analysis_id

    reads.update(view=0, evidence=0)
    page = facade.evidence_v2(
        principal=_principal(),
        site_id="site-a",
        analysis_id=stable_view.analysis_id,
        now=now,
        limit=32,
        cursor=None,
    )
    assert page is not None
    assert reads == {"view": 4, "evidence": 2}

    reads.update(view=0, evidence=0)
    monkeypatch.setattr(facade, "evidence", lambda **_kwargs: completed_evidence)
    with pytest.raises(AnalysisSnapshotChanged, match="ANALYSIS_SNAPSHOT_CHANGED"):
        facade.get_v2(
            principal=_principal(),
            site_id="site-a",
            analysis_id=stable_view.analysis_id,
            now=now,
        )
    assert reads == {"view": 6, "evidence": 0}


def test_v2_projection_retries_when_worker_state_changes_without_authority_digest_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    route_fixture = _PublicApiFacade()
    initial_view = route_fixture.view
    later_view = initial_view.model_copy(
        update={"blockers": (AnalysisBlockerV1(code="RECONSTRUCTION_NOT_SEALED"),)}
    )
    evidence = route_fixture.evidence(
        principal=_principal(), site_id="site-a", analysis_id=initial_view.analysis_id, now=now
    )
    facade = ExternalAnalysisFacade.__new__(ExternalAnalysisFacade)
    view_reads = iter((initial_view, later_view, later_view, later_view))
    monkeypatch.setattr(facade, "get", lambda **_kwargs: next(view_reads))
    monkeypatch.setattr(facade, "evidence", lambda **_kwargs: evidence)

    projected = facade.get_v2(
        principal=_principal(), site_id="site-a", analysis_id=initial_view.analysis_id, now=now
    )
    assert projected is not None
    assert projected.blockers == later_view.blockers


def test_v2_evidence_cursor_is_bound_to_projected_limitations_and_detail_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 9, 22, tzinfo=UTC)
    route_fixture = _PublicApiFacade()
    first_view = route_fixture.view.model_copy(
        update={
            "blockers": (
                AnalysisBlockerV1(code="SECOND"),
                AnalysisBlockerV1(code="THIRD"),
            )
        }
    )
    changed_view = first_view.model_copy(
        update={
            "blockers": (
                AnalysisBlockerV1(code="CHANGED"),
                AnalysisBlockerV1(code="THIRD"),
            )
        }
    )
    evidence = route_fixture.evidence(
        principal=_principal(), site_id="site-a", analysis_id=first_view.analysis_id, now=now
    )
    facade = ExternalAnalysisFacade.__new__(ExternalAnalysisFacade)
    current_view = [first_view]
    monkeypatch.setattr(facade, "get", lambda **_kwargs: current_view[0])
    monkeypatch.setattr(facade, "evidence", lambda **_kwargs: evidence)

    detail = facade.get_v2(
        principal=_principal(), site_id="site-a", analysis_id=first_view.analysis_id, now=now
    )
    first_page = facade.evidence_v2(
        principal=_principal(),
        site_id="site-a",
        analysis_id=first_view.analysis_id,
        now=now,
        limit=1,
        cursor=None,
    )
    assert detail is not None and first_page is not None
    assert detail.evidence_digest == first_page.evidence_digest
    assert first_page.next_cursor is not None

    current_view[0] = changed_view
    with pytest.raises(ValueError, match="ANALYSIS_EVIDENCE_CURSOR_STALE"):
        facade.evidence_v2(
            principal=_principal(),
            site_id="site-a",
            analysis_id=first_view.analysis_id,
            now=now,
            limit=1,
            cursor=first_page.next_cursor,
        )


def test_analysis_collection_does_not_disclose_unknown_or_foreign_site(tmp_path: Path) -> None:
    """The collection has the same generic 404 boundary as selector resolution."""
    token = "analysis-unknown-site-operator"
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(token.encode()).hexdigest(), principal=_principal()
            )
        ]
    )
    intents = AnalysisIntentStore(DurableJournal(tmp_path / "analysis-intents.jsonl"))
    facade = ExternalAnalysisFacade(
        intents=intents,
        assessments=_UnusedAssessments(),
        calculations=_UnusedCalculations(),
        reconstructions=SimpleNamespace(),
        sites=_Sites(),
        work_areas=_WorkAreas(),
    )
    app = FastAPI()
    mount_auth(app, registry)
    app.include_router(build_external_analysis_router(facade))
    response = TestClient(app).get(
        "/v1/sites/unknown-site/analyses", headers={"Authorization": "Bearer " + token}
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "ANALYSIS_RESOURCE_NOT_FOUND"}
    intents.close()


def test_evidence_endpoint_projects_full_identity_provenance_not_digests_only(
    tmp_path: Path,
) -> None:
    """Evidence returns actual AP identity facts and resolved observation epochs."""
    intents = AnalysisIntentStore(DurableJournal(tmp_path / "analysis-intents.jsonl"))
    created = intents.record_intent(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="area-a",
        request=_request(),
        idempotency_key="evidence-key",
        now=datetime(2026, 9, 22, tzinfo=UTC),
    )
    facade = ExternalAnalysisFacade(
        intents=intents,
        assessments=_EvidenceAssessments(created.analysis_id),
        calculations=_NoCalculations(),
        reconstructions=_EvidenceReconstructions(),
        sites=_Sites(),
        work_areas=_WorkAreas(),
    )
    evidence = facade.evidence(
        principal=_principal(),
        site_id="site-a",
        analysis_id=created.analysis_id,
        now=datetime(2026, 9, 22, tzinfo=UTC),
    )
    assert evidence is not None
    assert evidence.baseline is not None
    assert evidence.current is not None
    assert evidence.baseline.observation_epoch_id == "obs-epoch-baseline"
    assert evidence.current.artifact_id == "current-dsm"
    assert evidence.baseline.transform == (1.0, 0.0, 0.0, 0.0, -1.0, 10.0)
    assert evidence.baseline.inspection_report_digest == "sha256:" + "5" * 64
    assert evidence.calculation is not None
    assert evidence.calculation.work_area_definition_digest == "sha256:" + "0" * 64
    intents.close()


def test_completed_provisional_http_result_projects_only_unassessed_limitations(
    tmp_path: Path,
) -> None:
    """The result keeps recorded provisional limitations without relabeling evaluated evidence."""
    token = "analysis-provisional-result-token"
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(token.encode()).hexdigest(), principal=_principal()
            )
        ]
    )
    intents = AnalysisIntentStore(DurableJournal(tmp_path / "analysis-intents.jsonl"))
    created = intents.record_intent(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="area-a",
        request=_request(),
        idempotency_key="provisional-result-key",
        now=datetime(2026, 9, 22, tzinfo=UTC),
    )
    intents.link_calculation(
        analysis_id=created.analysis_id,
        organization_id="org-a",
        calculation_request_id="calculation-provisional",
    )
    coverage = RelativeVolumeCoverageWitnessV2(
        rows=1,
        columns=1,
        row_offset=0,
        column_offset=0,
        selected_mask_b64="gA==",
        common_valid_mask_b64="gA==",
        unavailable_mask_b64="AA==",
        threshold_excluded_mask_b64="AA==",
        selected_cell_count=1,
        common_valid_cell_count=1,
        unavailable_cell_count=0,
        threshold_excluded_cell_count=0,
        cell_area_m2=1.0,
        selected_area_m2=1.0,
        common_valid_area_m2=1.0,
        bounds=(0.0, 0.0, 1.0, 1.0),
    ).sealed()
    report = _FakeReport(
        report_id="report-provisional",
        report_digest="sha256:" + "a" * 64,
        numeric_result_identity_digest="sha256:" + "b" * 64,
        computed_at=datetime(2026, 9, 22, tzinfo=UTC),
        numeric_result=_FakeNumericResult(
            metrics=_FakeMetrics(cut_m3=0.0, fill_m3=0.0, net_m3=0.0, threshold_m=0.0),
            coverage=coverage,
        ),
    )

    unassessed = _FakeEvaluation(
        evaluation_id="evaluation-provisional",
        epoch="BASELINE",
        revision=1,
        outcome=EvaluationOutcomeV1.UNASSESSED,
        reason_codes=("CHECKPOINT_EVIDENCE_ABSENT",),
        assessed_at=datetime(2026, 9, 22, tzinfo=UTC),
        evaluation_digest="sha256:" + "e" * 64,
    )
    passed = _FakeEvaluation(
        evaluation_id="evaluation-passed",
        epoch="CURRENT",
        revision=1,
        outcome=EvaluationOutcomeV1.PASS,
        reason_codes=("CHECKPOINT_EVIDENCE_VALIDATED",),
        assessed_at=datetime(2026, 9, 22, tzinfo=UTC),
        evaluation_digest="sha256:" + "f" * 64,
    )

    class Assessments(_UnusedAssessments):
        def __init__(self) -> None:
            self.record = _FakeAssessmentRecord(
                admission=_FakeAdmission(
                    admission_id="admission-provisional",
                    admission_digest="sha256:" + "c" * 64,
                    calculation_identity_digest="sha256:" + "d" * 64,
                    calculation_identity=None,
                    disposition=AdmissionDispositionV2.ADMIT_PROVISIONAL,
                    reason_codes=(),
                    evaluation_revisions=(unassessed, passed),
                )
            )

        def get_history_for_principal(
            self, request_id: str, *, principal: Principal
        ) -> _FakeAssessmentRecord:
            del request_id, principal
            return self.record

        def get_current_for_read(
            self, request_id: str, *, principal: Principal, now: datetime
        ) -> _FakeAssessmentRecord:
            del request_id, principal, now
            return self.record

    class Calculations(_UnusedCalculations):
        def get_history(
            self, request_id: str, *, organization_id: str
        ) -> _FakeCalculationRecord | None:
            if (request_id, organization_id) != ("calculation-provisional", "org-a"):
                return None
            return _FakeCalculationRecord(
                request_id=request_id,
                organization_id=organization_id,
                calculation_identity_digest="sha256:" + "d" * 64,
                status=CalculationExecutionStatusV2.COMPLETED,
                authorization=_FakeAuthorization(authorization_id="authorization-provisional"),
                report=report,
                failure=None,
            )

        def get_current(
            self, *, request_id: str, principal: Principal, now: datetime
        ) -> _FakeCurrentView:
            del request_id, principal, now
            return _FakeCurrentView(
                disposition=CalculationCurrentDispositionV2.AVAILABLE,
                report=report,
            )

    facade = ExternalAnalysisFacade(
        intents=intents,
        assessments=Assessments(),
        calculations=Calculations(),
        reconstructions=SimpleNamespace(),
        sites=_Sites(),
        work_areas=_WorkAreas(),
    )
    app = FastAPI()
    mount_auth(app, registry)
    app.include_router(build_external_analysis_router(facade))
    response = TestClient(app).get(
        f"/v1/sites/site-a/analyses/{created.analysis_id}/result",
        headers={"Authorization": "Bearer " + token},
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["limitationCodes"] == ["CHECKPOINT_EVIDENCE_ABSENT"]
    intents.close()


@pytest.mark.parametrize(
    "disposition",
    (
        CalculationCurrentDispositionV2.EXECUTION_DEADLINE_EXPIRED,
        CalculationCurrentDispositionV2.EXECUTION_RETRY_EXHAUSTED,
    ),
)
def test_facade_projects_nx_effective_terminal_verdict_without_get_mutation(
    tmp_path: Path,
    disposition: CalculationCurrentDispositionV2,
) -> None:
    """Read-only NX expiry/retry verdicts make unfinished jobs publicly terminal."""
    journal_path = tmp_path / "analysis-intents.jsonl"
    intents = AnalysisIntentStore(DurableJournal(journal_path))
    created = intents.record_intent(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="area-a",
        request=_request(),
        idempotency_key="effective-terminal-key",
        now=datetime(2026, 9, 22, tzinfo=UTC),
    )
    intents.link_calculation(
        analysis_id=created.analysis_id,
        organization_id="org-a",
        calculation_request_id="calculation-terminal",
    )
    journal_before_get = journal_path.read_bytes()
    facade = ExternalAnalysisFacade(
        intents=intents,
        assessments=_EvidenceAssessments(created.analysis_id),
        calculations=_EffectiveTerminalCalculations(disposition),
        reconstructions=_EvidenceReconstructions(),
        sites=_Sites(),
        work_areas=_WorkAreas(),
    )
    view = facade.get(
        principal=_principal(),
        site_id="site-a",
        analysis_id=created.analysis_id,
        now=datetime(2026, 9, 22, tzinfo=UTC),
    )
    assert view is not None
    assert view.execution_state is AnalysisExecutionStateV1.FAILED
    assert view.suitability_state is AnalysisSuitabilityStateV1.PROVISIONAL_ACCURACY_UNVERIFIED
    assert {item.code for item in view.blockers} == {disposition.value}
    assert view.result is None
    assert journal_path.read_bytes() == journal_before_get
    intents.close()


@pytest.mark.parametrize(
    ("reason_code", "expected_suitability"),
    (
        ("EMPTY_COMMON_VALID_COVERAGE", AnalysisSuitabilityStateV1.BLOCKED),
        ("INSUFFICIENT_COMMON_VALID_COVERAGE", AnalysisSuitabilityStateV1.BLOCKED),
        (
            "ANALYSIS_EXECUTION_FAILED",
            AnalysisSuitabilityStateV1.PROVISIONAL_ACCURACY_UNVERIFIED,
        ),
    ),
)
def test_facade_projects_only_coverage_failures_as_terminal_blockers_without_get_mutation(
    tmp_path: Path,
    reason_code: str,
    expected_suitability: AnalysisSuitabilityStateV1,
) -> None:
    journal_path = tmp_path / "analysis-intents.jsonl"
    intents = AnalysisIntentStore(DurableJournal(journal_path))
    created = intents.record_intent(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="area-a",
        request=_request(),
        idempotency_key="coverage-failure-key",
        now=datetime(2026, 9, 22, tzinfo=UTC),
    )
    intents.link_calculation(
        analysis_id=created.analysis_id,
        organization_id="org-a",
        calculation_request_id="calculation-terminal",
    )
    journal_before_get = journal_path.read_bytes()
    view = ExternalAnalysisFacade(
        intents=intents,
        assessments=_EvidenceAssessments(created.analysis_id),
        calculations=_FailedAnalysisCalculations(reason_code),
        reconstructions=_EvidenceReconstructions(),
        sites=_Sites(),
        work_areas=_WorkAreas(),
    ).get(
        principal=_principal(),
        site_id="site-a",
        analysis_id=created.analysis_id,
        now=datetime(2026, 9, 22, tzinfo=UTC),
    )

    assert view is not None
    assert view.execution_state is AnalysisExecutionStateV1.FAILED
    assert view.suitability_state is expected_suitability
    assert {item.code for item in view.blockers} == {reason_code}
    assert view.authority.failure_digest == "sha256:" + "c" * 64
    assert view.result is None
    assert journal_path.read_bytes() == journal_before_get
    intents.close()


@pytest.mark.parametrize(
    ("assessment_type", "calculation_digest", "blocker"),
    (
        (_StaleEvidenceAssessments, "sha256:" + "a" * 64, "REASSESSMENT_REQUIRED"),
        (_EvidenceAssessments, "sha256:" + "f" * 64, "CALCULATION_IDENTITY_MISMATCH"),
    ),
)
def test_facade_preserves_recorded_execution_while_ap_stale_or_nx_link_mismatched(
    tmp_path: Path,
    assessment_type: type[_EvidenceAssessments],
    calculation_digest: str,
    blocker: str,
) -> None:
    """Staleness and corrupted replay links fail closed without hiding NX history."""
    journal_path = tmp_path / "analysis-intents.jsonl"
    intents = AnalysisIntentStore(DurableJournal(journal_path))
    created = intents.record_intent(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="area-a",
        request=_request(),
        idempotency_key="recorded-execution-key-" + blocker,
        now=datetime(2026, 9, 22, tzinfo=UTC),
    )
    intents.link_calculation(
        analysis_id=created.analysis_id,
        organization_id="org-a",
        calculation_request_id="calculation-recorded",
    )
    journal_before_get = journal_path.read_bytes()
    facade = ExternalAnalysisFacade(
        intents=intents,
        assessments=assessment_type(created.analysis_id),
        calculations=_RecordedCalculationOnly(calculation_digest),
        reconstructions=_EvidenceReconstructions(),
        sites=_Sites(),
        work_areas=_WorkAreas(),
    )
    view = facade.get(
        principal=_principal(),
        site_id="site-a",
        analysis_id=created.analysis_id,
        now=datetime(2026, 9, 22, tzinfo=UTC),
    )
    assert view is not None
    assert view.execution_state is AnalysisExecutionStateV1.COMPLETED
    assert view.suitability_state is AnalysisSuitabilityStateV1.REASSESSMENT_REQUIRED
    assert {item.code for item in view.blockers} == {blocker}
    assert view.result is None
    assert journal_path.read_bytes() == journal_before_get
    intents.close()


class _PublicApiFacade:
    """Route fixture that records only public call plumbing, never Core policy."""

    def __init__(self) -> None:
        selector = _request().baseline
        self.view = AnalysisViewV1(
            analysis_id="analysis-api-route-1",
            site_id="site-a",
            work_area_id="area-a",
            baseline=selector,
            current=_request().current,
            execution_state=AnalysisExecutionStateV1.NOT_STARTED,
            suitability_state=AnalysisSuitabilityStateV1.BLOCKED,
            blockers=(AnalysisBlockerV1(code="ASSESSMENT_RECOVERY_REQUIRED"),),
            evidence_refs=(),
            result=None,
            created_at=datetime(2026, 9, 22, tzinfo=UTC),
        )
        self.created: list[tuple[str, str, str]] = []

    def observation_options(
        self, *, principal: Principal, site_id: str
    ) -> AnalysisObservationOptionsV1:
        del principal
        assert site_id == "site-a"
        return AnalysisObservationOptionsV1(
            items=(
                AnalysisObservationOptionV1(
                    selector=_request().baseline,
                    observation_epoch_id="obs-epoch-api-1",
                    capture_started_at=datetime(2026, 9, 20, tzinfo=UTC),
                    capture_ended_at=datetime(2026, 9, 21, tzinfo=UTC),
                ),
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
        del principal, request, now
        self.created.append((site_id, work_area_id, idempotency_key))
        return self.view

    def list(self, *, principal: Principal, site_id: str, now: datetime) -> AnalysisListV1:
        del principal, now
        return (
            AnalysisListV1(items=(self.view,)) if site_id == "site-a" else AnalysisListV1(items=())
        )

    def get(
        self, *, principal: Principal, site_id: str, analysis_id: str, now: datetime
    ) -> AnalysisViewV1 | None:
        del principal, now
        return self.view if (site_id, analysis_id) == ("site-a", self.view.analysis_id) else None

    def evidence(
        self, *, principal: Principal, site_id: str, analysis_id: str, now: datetime
    ) -> AnalysisEvidenceViewV1 | None:
        del principal, now
        if (site_id, analysis_id) != ("site-a", self.view.analysis_id):
            return None
        return AnalysisEvidenceViewV1(
            analysis_id=self.view.analysis_id,
            authority=self.view.authority,
            result=None,
            evidence_refs=(),
        )

    def external_ai_egress_allowed(self, *, principal: Principal, site_id: str) -> bool:
        del principal, site_id
        return False

    def create_v2(self, **kwargs: Any) -> NoReturn:
        raise NotImplementedError("V1 plumbing fixture does not issue V2 authority")

    def list_v2(self, **kwargs: Any) -> NoReturn:
        raise NotImplementedError("V1 plumbing fixture does not list V2 records")

    def coverage_resource_v2(self, **kwargs: Any) -> NoReturn:
        raise NotImplementedError("V1 plumbing fixture does not serve V2 coverage")

    def get_v2(
        self, *, principal: Principal, site_id: str, analysis_id: str, now: datetime
    ) -> NoReturn:
        del principal, site_id, analysis_id, now
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
    ) -> NoReturn:
        del principal, site_id, analysis_id, now, limit, cursor
        raise AnalysisSnapshotChanged("ANALYSIS_SNAPSHOT_CHANGED")


def _real_core_store_ports_typecheck(
    intents: AnalysisIntentStore,
    assessments: ExternalRelativeVolumeAnalysisStore,
    calculations: ExternalRelativeVolumeCalculationStore,
) -> None:
    """Keep the narrow internal ports compatible with actual Core composition stores."""
    ExternalAnalysisFacade(
        intents=intents,
        assessments=assessments,
        calculations=calculations,
        reconstructions=object(),
        sites=object(),
        work_areas=object(),
    )


def _route_fixture_typecheck(facade: _PublicApiFacade) -> _AnalysisPublicRoutePort:
    return facade


def test_public_routes_use_frozen_paths_auth_and_idempotency_header() -> None:
    """All six UI routes share the selector-only DTO and reject a missing idempotency key."""
    token = "analysis-api-route-operator"
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(token.encode()).hexdigest(), principal=_principal()
            )
        ]
    )
    app = FastAPI()
    mount_auth(app, registry)
    facade = _PublicApiFacade()
    app.include_router(
        build_external_analysis_router(facade, clock=lambda: datetime(2026, 9, 22, tzinfo=UTC))
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + token}
    body = _request().model_dump(by_alias=True, mode="json")

    options = client.get("/v1/sites/site-a/analysis-observations", headers=headers)
    assert options.status_code == 200
    assert options.json()["items"][0]["selector"] == body["baseline"]
    missing_key = client.post(
        "/v1/sites/site-a/work-areas/area-a/analyses", headers=headers, json=body
    )
    assert missing_key.status_code == 400
    identical_selectors = client.post(
        "/v1/sites/site-a/work-areas/area-a/analyses",
        headers={**headers, "Idempotency-Key": "identical-selectors"},
        json={**body, "current": body["baseline"]},
    )
    assert identical_selectors.status_code == 422
    overlong_key = client.post(
        "/v1/sites/site-a/work-areas/area-a/analyses",
        headers={**headers, "Idempotency-Key": "k" * 256},
        json=body,
    )
    assert overlong_key.status_code == 422
    assert facade.created == []
    created = client.post(
        "/v1/sites/site-a/work-areas/area-a/analyses",
        headers={**headers, "Idempotency-Key": "route-key"},
        json=body,
    )
    unstable_detail = client.get(
        "/v2/sites/site-a/analyses/analysis-api-route-1", headers=headers
    )
    unstable_evidence = client.get(
        "/v2/sites/site-a/analyses/analysis-api-route-1/evidence", headers=headers
    )
    assert unstable_detail.status_code == unstable_evidence.status_code == 409
    assert unstable_detail.json()["detail"] == unstable_evidence.json()["detail"] == (
        "ANALYSIS_SNAPSHOT_CHANGED"
    )
    assert created.status_code == 202
    assert facade.created == [("site-a", "area-a", "route-key")]
    analysis_id = created.json()["analysisId"]
    assert client.get("/v1/sites/site-a/analyses", headers=headers).status_code == 200
    assert (
        client.get(f"/v1/sites/site-a/analyses/{analysis_id}", headers=headers).status_code == 200
    )
    assert (
        client.get(f"/v1/sites/site-a/analyses/{analysis_id}/result", headers=headers).status_code
        == 200
    )
    assert (
        client.get(f"/v1/sites/site-a/analyses/{analysis_id}/evidence", headers=headers).status_code
        == 200
    )


def test_common_app_mounts_analysis_only_from_explicit_local_wiring() -> None:
    """Production/default app remains closed; a supplied local graph is the only mount seam."""
    token = "analysis-wiring-operator"
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(token.encode()).hexdigest(), principal=_principal()
            )
        ]
    )
    default_app = create_app(auth_registry=registry)
    assert "/v1/sites/{site_id}/analyses" not in default_app.openapi()["paths"]
    wired_app = create_app(
        auth_registry=registry,
        external_analysis_wiring=ExternalAnalysisWiring(
            facade=_PublicApiFacade(),
            intents=object(),
            assessments=object(),
            calculations=object(),
            capability_issuer=object(),
        ),
    )
    response = TestClient(wired_app).get(
        "/v1/sites/site-a/analyses", headers={"Authorization": "Bearer " + token}
    )
    assert response.status_code == 200


def test_external_ai_identity_is_site_scoped_and_acknowledged_before_analysis_access(
    tmp_path: Path,
) -> None:
    """The dedicated MCP identity cannot read or append without the site's consent."""
    from analysis_api_local_fixture import build_local_analysis_api_fixture

    disabled_path = tmp_path / "disabled"
    allowed_path = tmp_path / "allowed"
    disabled_path.mkdir(mode=0o700)
    allowed_path.mkdir(mode=0o700)
    disabled = build_local_analysis_api_fixture(
        disabled_path,
        analysis_activation=_active_analysis_activation(disabled_path),
    )
    allowed = build_local_analysis_api_fixture(
        allowed_path,
        ai_egress_allowed=True,
        analysis_activation=_active_analysis_activation(allowed_path),
    )
    try:
        disabled_client = TestClient(disabled.app)
        body = {
            "baseline": disabled.baseline.model_dump(by_alias=True, mode="json"),
            "current": disabled.current.model_dump(by_alias=True, mode="json"),
        }
        denied_observations = disabled_client.get(
            f"/v1/sites/{disabled.site_id}/analysis-observations",
            headers=disabled.mcp_client_headers(),
        )
        assert denied_observations.status_code == 403
        assert denied_observations.json()["detail"] == "AI_EGRESS_NOT_ALLOWED"
        assert "X-KSI-External-AI-Egress" not in denied_observations.headers

        denied_v1 = disabled_client.post(
            f"/v1/sites/{disabled.site_id}/work-areas/{disabled.work_area_id}/analyses",
            headers={
                **disabled.mcp_client_headers(),
                "Idempotency-Key": "mcp-disabled-site",
            },
            json=body,
        )
        assert denied_v1.status_code == 403
        assert denied_v1.json()["detail"] == "권한이 부족하다"
        assert "X-KSI-External-AI-Egress" not in denied_v1.headers

        denied_v2 = disabled_client.post(
            f"/v2/sites/{disabled.site_id}/work-areas/{disabled.work_area_id}/analyses",
            headers={
                **disabled.mcp_client_headers(),
                "Idempotency-Key": "mcp-disabled-v2-site",
            },
            json=body,
        )
        assert denied_v2.status_code == 403
        assert denied_v2.json()["detail"] == "AI_EGRESS_NOT_ALLOWED"
        assert "X-KSI-External-AI-Egress" not in denied_v2.headers
        assert (
            disabled.app.state.external_analysis_wiring.intents.list_for_organization(
                organization_id="org-a"
            )
            == ()
        )

        allowed_client = TestClient(allowed.app)
        headers = allowed.mcp_client_headers()
        observations = allowed_client.get(
            f"/v1/sites/{allowed.site_id}/analysis-observations", headers=headers
        )
        assert observations.status_code == 200
        assert observations.headers["X-KSI-External-AI-Egress"] == "ALLOWED"
        forged_purpose = allowed_client.get(
            f"/v1/sites/{allowed.site_id}/analysis-observations",
            headers={**headers, "X-KSI-Access-Purpose": "EXTERNAL_AI"},
        )
        assert forged_purpose.status_code == 200
        assert forged_purpose.headers["X-KSI-External-AI-Egress"] == "ALLOWED"
        created = allowed_client.post(
            f"/v2/sites/{allowed.site_id}/work-areas/{allowed.work_area_id}/analyses",
            headers={**headers, "Idempotency-Key": "mcp-allowed-site"},
            json={
                "baseline": allowed.baseline.model_dump(by_alias=True, mode="json"),
                "current": allowed.current.model_dump(by_alias=True, mode="json"),
            },
        )
        assert created.status_code == 202
        assert created.headers["X-KSI-External-AI-Egress"] == "ALLOWED"
        analysis_id = created.json()["analysisId"]
        for route in (
            f"/v2/sites/{allowed.site_id}/analyses",
            f"/v2/sites/{allowed.site_id}/analyses/{analysis_id}",
            f"/v2/sites/{allowed.site_id}/analyses/{analysis_id}/evidence",
        ):
            response = allowed_client.get(route, headers=headers)
            assert response.status_code == 200, response.text
            assert response.headers["X-KSI-External-AI-Egress"] == "ALLOWED"

        foreign = allowed_client.get(
            "/v1/sites/foreign-site/analysis-observations", headers=headers
        )
        assert foreign.status_code == 404
        operator = allowed_client.get(
            f"/v1/sites/{allowed.site_id}/analysis-observations",
            headers={
                **allowed.operator_headers(),
                "X-KSI-Access-Purpose": "EXTERNAL_AI",
            },
        )
        assert operator.status_code == 200
        assert "X-KSI-External-AI-Egress" not in operator.headers
    finally:
        disabled.close()
        allowed.close()


def test_external_ai_identity_blocks_each_analysis_read_and_write_route_before_access(
    tmp_path: Path,
) -> None:
    """Every MCP route shares the site consent gate; denied POST leaves no intent."""
    from analysis_api_local_fixture import build_local_analysis_api_fixture

    fixture = build_local_analysis_api_fixture(
        tmp_path,
        analysis_activation=_active_analysis_activation(tmp_path),
    )
    try:
        client = TestClient(fixture.app)
        headers = fixture.mcp_client_headers()
        analysis_id = "analysis-does-not-exist"
        routes = (
            ("get", f"/v1/sites/{fixture.site_id}/analysis-observations"),
            ("get", f"/v2/sites/{fixture.site_id}/analyses"),
            ("get", f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}"),
            ("get", f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/evidence"),
        )
        for method, route in routes:
            response = getattr(client, method)(route, headers=headers)
            assert response.status_code == 403
            assert response.json()["detail"] == "AI_EGRESS_NOT_ALLOWED"
            assert "X-KSI-External-AI-Egress" not in response.headers
        coverage = client.get(
            f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/coverage",
            headers={**headers, "Range": "bytes=0-0"},
        )
        assert coverage.status_code == 403
        assert coverage.json()["detail"] == "AI_EGRESS_NOT_ALLOWED"
        assert "X-KSI-External-AI-Egress" not in coverage.headers
        created = client.post(
            f"/v2/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={"Idempotency-Key": "blocked-all-routes", **headers},
            json={
                "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
                "current": fixture.current.model_dump(by_alias=True, mode="json"),
            },
        )
        assert created.status_code == 403
        assert created.json()["detail"] == "AI_EGRESS_NOT_ALLOWED"
        assert "X-KSI-External-AI-Egress" not in created.headers
        assert (
            fixture.app.state.external_analysis_wiring.intents.list_for_organization(
                organization_id="org-a"
            )
            == ()
        )
    finally:
        fixture.close()


def test_external_ai_identity_preserves_operator_write_and_core_idempotency_conflict(
    tmp_path: Path,
) -> None:
    """The MCP identity cannot turn a viewer into a writer or soften a key conflict."""
    from analysis_api_local_fixture import build_local_analysis_api_fixture

    fixture = build_local_analysis_api_fixture(tmp_path, ai_egress_allowed=True)
    try:
        client = TestClient(fixture.app)
        request = {
            "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
            "current": fixture.current.model_dump(by_alias=True, mode="json"),
        }
        viewer_denied = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={
                **fixture.viewer_headers(),
                "Idempotency-Key": "viewer-cannot-write",
            },
            json=request,
        )
        assert viewer_denied.status_code == 403
        assert viewer_denied.json()["detail"] != "AI_EGRESS_NOT_ALLOWED"
        assert "X-KSI-External-AI-Egress" not in viewer_denied.headers

        headers = {
            **fixture.operator_headers(),
            "Idempotency-Key": "key-conflict-unchanged",
            "X-KSI-Access-Purpose": "EXTERNAL_AI",
        }
        first = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers=headers,
            json=request,
        )
        assert first.status_code == 202
        assert "X-KSI-External-AI-Egress" not in first.headers
        changed = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers=headers,
            json={"baseline": request["current"], "current": request["baseline"]},
        )
        assert changed.status_code == 409
        assert changed.json()["detail"] == "ANALYSIS_IDEMPOTENCY_CONFLICT"
    finally:
        fixture.close()
