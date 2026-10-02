"""Real DSM Analysis worker lease abandonment and recovery integration."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from analysis_api_local_fixture import build_local_analysis_api_fixture
from ksi_processing_controller.external_analysis_core_client import ExternalAnalysisCoreClient
from ksi_processing_controller.external_analysis_worker import (
    ProcessingWorkerRuntimeIdentityV1,
    run_once,
)
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)
from test_external_analysis_real_inspection_lane_integration import (
    _CoreAndObjectServers,
    _drive_two_epochs_through_lane,
    _post_analysis,
)


def test_abandoned_analysis_worker_lease_recovers_on_actual_inspected_dsms(
    tmp_path: Path,
) -> None:
    """A worker that abandons a lease before input cannot publish; another recovers after expiry."""
    fixture = build_local_analysis_api_fixture(tmp_path, v2_dsm_only=True, real_inspection=True)
    worker_b: ExternalAnalysisCoreClient | None = None
    try:
        with _CoreAndObjectServers(fixture) as servers:
            reports = _drive_two_epochs_through_lane(
                fixture,
                core_origin=servers.core_origin,
                object_origin=servers.object_origin,
                tmp_path=tmp_path,
            )
            assert len(reports) == 2

            idempotency_key = "abandoned-lease-recovery-analysis"
            created = _post_analysis(fixture, servers.core_origin, idempotency_key)
            analysis_id = created["analysisId"]
            calculation_request_id = created["authority"]["calculationRequestId"]
            assert created["executionState"] == "QUEUED"
            assert created["result"] is None

            wiring = fixture.app.state.external_analysis_wiring
            history = wiring.calculations.get_history(
                calculation_request_id, organization_id="org-a"
            )
            assert history is not None and history.status.value == "QUEUED"
            assert history.attempts == ()
            lease_seconds = history.authorization.resource_envelope.lease_duration_seconds

            worker_a = ExternalAnalysisCoreClient(
                base_url=servers.core_origin,
                worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
                worker_instance_id="abandoned-analysis-worker-a",
            )
            try:
                pending_a = worker_a.list_pending()
                assert [item.analysis_id for item in pending_a] == [analysis_id]
                abandoned_lease = worker_a.lease(analysis_id, "abandoned-acquisition-a")
            finally:
                # No input, report, or failure call is made by this worker.
                worker_a.close()

            attempt_a = abandoned_lease.attempt
            assert attempt_a.lease_generation == 1
            assert attempt_a.worker_instance_id == "abandoned-analysis-worker-a"
            assert attempt_a.lease_acquisition_id == "abandoned-acquisition-a"
            history = wiring.calculations.get_history(
                calculation_request_id, organization_id="org-a"
            )
            assert history is not None
            assert history.status.value == "RUNNING"
            assert history.attempts == (attempt_a,)
            assert history.report is None
            assert history.failure is None

            facts = wiring.facade._assessments._runtime
            envelope = wiring.calculations._resource_envelope
            runtime = ProcessingWorkerRuntimeIdentityV1(
                worker_executable_digest=facts.worker_executable_digest,
                worker_build_digest=facts.worker_build_digest,
                runtime_image_version=facts.runtime_image_version,
                runtime_image_oci_digest=facts.runtime_image_oci_digest,
                dependency_lock_digest=facts.dependency_lock_digest,
            )
            object_policy = ExternalObjectTransportPolicyV1(
                endpoints=(
                    TrustedObjectEndpointV1(origin=servers.object_origin, addresses=("127.0.0.1",)),
                ),
                max_header_bytes=16_384,
                max_object_bytes=envelope.max_input_bytes,
                max_chunk_bytes=min(65_536, envelope.max_input_bytes),
            )
            worker_b = ExternalAnalysisCoreClient(
                base_url=servers.core_origin,
                worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
                worker_instance_id="recovering-analysis-worker-b",
            )

            with httpx.Client(base_url=servers.core_origin, trust_env=False) as operator:
                detail_before_expiry = operator.get(
                    f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}",
                    headers=fixture.operator_headers(),
                )
                result_before_expiry = operator.get(
                    f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/result",
                    headers=fixture.operator_headers(),
                )
            assert detail_before_expiry.status_code == result_before_expiry.status_code == 200
            assert detail_before_expiry.json()["executionState"] == "RUNNING"
            assert detail_before_expiry.json()["result"] is None
            assert result_before_expiry.json()["result"] is None
            assert run_once(worker_b, runtime, object_policy) is False
            assert worker_b.list_pending() == ()
            history = wiring.calculations.get_history(
                calculation_request_id, organization_id="org-a"
            )
            assert history is not None and history.attempts == (attempt_a,)
            assert history.report is None

            remaining = (attempt_a.lease_expires_at - datetime.now(UTC)).total_seconds()
            wait_seconds = max(0.0, remaining) + 0.05
            assert wait_seconds <= lease_seconds + 0.5
            time.sleep(wait_seconds)

            assert run_once(worker_b, runtime, object_policy) is True
            recovered = wiring.calculations.get_history(
                calculation_request_id, organization_id="org-a"
            )
            assert recovered is not None and recovered.status.value == "COMPLETED"
            assert recovered.report is not None and recovered.failure is None
            assert len(recovered.attempts) == 2
            attempt_b = recovered.attempts[1]
            assert attempt_b.lease_generation == 2
            assert attempt_b.worker_instance_id == "recovering-analysis-worker-b"
            assert attempt_b.lease_acquisition_id != attempt_a.lease_acquisition_id
            assert recovered.report.attempt == attempt_b

            with httpx.Client(base_url=servers.core_origin, trust_env=False) as operator:
                detail = operator.get(
                    f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}",
                    headers=fixture.operator_headers(),
                )
                result = operator.get(
                    f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/result",
                    headers=fixture.operator_headers(),
                )
                evidence = operator.get(
                    f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
                    headers=fixture.operator_headers(),
                )
            assert detail.status_code == result.status_code == evidence.status_code == 200
            detail_view = detail.json()
            result_view = result.json()
            evidence_view = evidence.json()
            assert detail_view["executionState"] == "COMPLETED"
            assert detail_view["result"] == result_view["result"] == evidence_view["result"]
            assert detail_view["analysisId"] == result_view["analysisId"] == analysis_id
            assert detail_view["authority"]["calculationRequestId"] == calculation_request_id
            metrics = result_view["result"]["metrics"]
            assert metrics["cutM3"] == pytest.approx(0.01)
            assert metrics["fillM3"] == pytest.approx(0.01)
            assert metrics["netM3"] == pytest.approx(0.0)
            assert metrics["uncertaintyM3"] is None
            assert recovered.report.report_digest == result_view["result"]["reportDigest"]
            assert evidence_view["baseline"]["inspectionReportDigest"] == reports[0].report_digest
            assert evidence_view["current"]["inspectionReportDigest"] == reports[1].report_digest
            identity = recovered.admission.calculation_identity
            assert identity is not None
            assert identity.calculation_identity_digest is not None
            assert identity.calculation_identity_digest == recovered.calculation_identity_digest
            for epoch_key, revision, expected_input_digest in (
                ("baseline", fixture._baseline_revision, identity.baseline_input_digest),
                ("current", fixture._current_revision, identity.current_input_digest),
            ):
                epoch = evidence_view[epoch_key]
                entry = revision.manifest.entries[0]
                assert epoch["observedSha256"] == "sha256:" + entry.observed_sha256
                assert epoch["inputDigest"] == expected_input_digest

            retried = _post_analysis(fixture, servers.core_origin, idempotency_key)
            assert retried["analysisId"] == analysis_id
            assert retried["authority"]["calculationRequestId"] == calculation_request_id
            assert retried["result"] == result_view["result"]
            assert worker_b.list_pending() == ()
            assert run_once(worker_b, runtime, object_policy) is False
            assert len(wiring.intents.list_for_organization(organization_id="org-a")) == 1
            final_history = wiring.calculations.get_history(
                calculation_request_id, organization_id="org-a"
            )
            assert final_history == recovered
    finally:
        if worker_b is not None:
            worker_b.close()
        fixture.close()
