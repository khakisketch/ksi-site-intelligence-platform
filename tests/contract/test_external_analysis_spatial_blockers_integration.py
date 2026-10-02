"""Measured spatial prerequisites for DSM-only V2 Analysis."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

import httpx
import pytest
from analysis_api_local_fixture import build_local_analysis_api_fixture
from ksi_event_contracts.external_artifact_validation import NodataRepresentation
from ksi_processing_controller.external_analysis_core_client import ExternalAnalysisCoreClient
from ksi_processing_controller.external_analysis_worker import (
    ProcessingWorkerRuntimeIdentityV1,
    run_once,
)
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)
from ksi_processing_controller.external_validation_core_client import ExternalValidationCoreClient
from ksi_processing_controller.external_validation_runner import TurnOutcome
from test_external_analysis_real_inspection_integration import _RealDsmInspectorUds
from test_external_analysis_real_inspection_lane_integration import (
    _CoreAndObjectServers,
    _inspection_lane,
    _post_analysis,
)


def _inspect_both_epochs_with_actual_lane(
    fixture: Any,
    *,
    core_origin: str,
    object_origin: str,
    tmp_path: Path,
    include_third_epoch: bool = False,
) -> tuple[Any, ...]:
    inspection_store = fixture.app.state.external_artifact_inspection_store
    socket_path = Path("/tmp") / f"ksi-spatial-lane-{uuid4().hex}.sock"
    inspector_root = tmp_path / "actual-spatial-inspector-root"
    inspector_root.mkdir(mode=0o700)
    with _RealDsmInspectorUds(
        path=socket_path,
        manifest=fixture._inspector_manifest,
        root=inspector_root,
    ) as inspector:
        core = ExternalValidationCoreClient(
            base_url=core_origin,
            bearer_token=fixture.validation_worker_headers()["Authorization"].removeprefix(
                "Bearer "
            ),
        )
        lane = _inspection_lane(
            fixture,
            core=core,
            object_origin=object_origin,
            socket_path=socket_path,
            private_root=tmp_path / "actual-spatial-lane-private",
            worker_instance_id=str(uuid4()),
        )
        try:
            reports = []
            subjects = [fixture._baseline_subject, fixture._current_subject]
            if include_third_epoch:
                assert fixture._third_subject is not None
                subjects.append(fixture._third_subject)
            for index, subject in enumerate(subjects):
                if include_third_epoch and index == 2:
                    # Core permits two concurrent inspection leases. The first two
                    # completed reports retain their fences until the fixed TTL expires.
                    time.sleep(
                        fixture._inspection_policy.resource_envelope.lease_duration_seconds
                        + 1
                    )
                now = max(datetime.now(UTC).replace(microsecond=0), fixture._fixture_now)
                issued = inspection_store.issue_after_seal(subject, now=now)
                assert issued.request is not None
                assert issued.verdict.value in {"ISSUED", "IDEMPOTENT"}
                deadline = time.monotonic() + 25
                request_id = lane.poll(deadline_monotonic=deadline)
                assert request_id is not None
                assert request_id == issued.request.request_id
                lease = lane.claim(request_id, str(uuid4()), deadline_monotonic=deadline)
                assert lease is not None
                try:
                    assert lane.execute(
                        lease,
                        deadline_monotonic=deadline,
                        stop=Event(),
                    ) is TurnOutcome.COMPLETED
                finally:
                    lane.release(lease)
                report = inspection_store.public_snapshot(subject).report
                assert report is not None
                assert report.worker_instance_id == lane._worker_instance_id
                reports.append(report)
            assert len(inspector.actual_source_digests) == len(subjects)
            assert inspector.actual_source_digests == inspector.source_digests
            return tuple(reports)
        finally:
            lane.close()
            core.close()


def _terminal_analysis(fixture: Any, origin: str, analysis_id: str) -> tuple[dict[str, Any], ...]:
    with httpx.Client(base_url=origin, trust_env=False) as operator:
        detail_url = f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}"
        for _ in range(100):
            detail = operator.get(detail_url, headers=fixture.operator_headers())
            assert detail.status_code == 200, detail.text
            if detail.json()["executionState"] not in {"QUEUED", "RUNNING"}:
                break
            time.sleep(0.02)
        result = operator.get(detail_url + "/result", headers=fixture.operator_headers())
        evidence = operator.get(detail_url + "/evidence", headers=fixture.operator_headers())
    assert detail.status_code == result.status_code == evidence.status_code == 200
    return detail.json(), result.json(), evidence.json()


@pytest.mark.parametrize(
    ("spatial_case", "expected_current_crs", "expected_vertical", "expected_blocker"),
    [
        (
            "MISSING_VERTICAL_REFERENCE",
            "EPSG:5186",
            None,
            "ESSENTIAL_INPUT_UNAVAILABLE",
        ),
        (
            "HORIZONTAL_CRS_MISMATCH",
            "EPSG:32652",
            "EPSG:5773",
            "HORIZONTAL_CRS_UNAVAILABLE_OR_MISMATCH",
        ),
    ],
    ids=["missing-observed-vertical-reference", "measured-horizontal-crs-mismatch"],
)
def test_actual_parser_spatial_metadata_blocks_analysis_before_worker(
    tmp_path: Path,
    spatial_case: str,
    expected_current_crs: str,
    expected_vertical: str | None,
    expected_blocker: str,
) -> None:
    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        real_inspection=True,
        current_dsm_spatial_case=spatial_case,
    )
    try:
        with _CoreAndObjectServers(fixture) as servers:
            reports = _inspect_both_epochs_with_actual_lane(
                fixture,
                core_origin=servers.core_origin,
                object_origin=servers.object_origin,
                tmp_path=tmp_path,
            )
            baseline_measurements = reports[0].measurement_payload.outcomes[0].measurements
            current_measurements = reports[1].measurement_payload.outcomes[0].measurements
            assert baseline_measurements is not None and current_measurements is not None
            assert current_measurements.observed_crs_identifier == expected_current_crs
            assert (
                current_measurements.observed_vertical_reference.identifier
                if current_measurements.observed_vertical_reference is not None
                else None
            ) == expected_vertical
            assert reports[1].measurement_payload.outcomes[0].observed_sha256 == (
                "sha256:" + fixture._current_revision.manifest.entries[0].observed_sha256
            )
            intent = _post_analysis(fixture, servers.core_origin, "measured-spatial-blocker")
            assert intent["suitabilityState"] == "BLOCKED"
            assert intent["executionState"] == "NOT_STARTED"
            assert intent["result"] is None
            assert {item["code"] for item in intent["blockers"]} == {expected_blocker}
            with httpx.Client(base_url=servers.core_origin, trust_env=False) as operator:
                result = operator.get(
                    f"/v1/sites/{fixture.site_id}/analyses/{intent['analysisId']}/result",
                    headers=fixture.operator_headers(),
                )
                jobs = operator.get(
                    "/v1/internal/analysis-jobs", headers=fixture.worker_headers()
                )
            assert result.status_code == 200
            assert result.json()["result"] is None
            assert jobs.status_code == 200
            assert jobs.json()["items"] == []
    finally:
        fixture.close()


def test_measured_non_overlapping_dsm_grid_is_blocked_before_worker(tmp_path: Path) -> None:
    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        real_inspection=True,
        current_dsm_spatial_case="NON_OVERLAPPING_GRID",
    )
    worker_client: ExternalAnalysisCoreClient | None = None
    try:
        with _CoreAndObjectServers(fixture) as servers:
            reports = _inspect_both_epochs_with_actual_lane(
                fixture,
                core_origin=servers.core_origin,
                object_origin=servers.object_origin,
                tmp_path=tmp_path,
            )
            baseline = reports[0].measurement_payload.outcomes[0].measurements
            current = reports[1].measurement_payload.outcomes[0].measurements
            assert baseline is not None and current is not None
            assert (
                baseline.observed_crs_identifier
                == current.observed_crs_identifier
                == "EPSG:5186"
            )
            assert baseline.observed_vertical_reference == current.observed_vertical_reference
            assert baseline.transform != current.transform
            intent = _post_analysis(fixture, servers.core_origin, "non-overlap-target-blocker")
            retry = _post_analysis(fixture, servers.core_origin, "non-overlap-target-blocker")
            assert retry["analysisId"] == intent["analysisId"]
            if intent["executionState"] in {"QUEUED", "RUNNING"}:
                runtime_facts = (
                    fixture.app.state.external_analysis_wiring.facade._assessments._runtime
                )
                envelope = (
                    fixture.app.state.external_analysis_wiring.calculations._resource_envelope
                )
                runtime = ProcessingWorkerRuntimeIdentityV1(
                    worker_executable_digest=runtime_facts.worker_executable_digest,
                    worker_build_digest=runtime_facts.worker_build_digest,
                    runtime_image_version=runtime_facts.runtime_image_version,
                    runtime_image_oci_digest=runtime_facts.runtime_image_oci_digest,
                    dependency_lock_digest=runtime_facts.dependency_lock_digest,
                )
                transport = ExternalObjectTransportPolicyV1(
                    endpoints=(
                        TrustedObjectEndpointV1(
                            origin=servers.object_origin, addresses=("127.0.0.1",)
                        ),
                    ),
                    max_header_bytes=16_384,
                    max_object_bytes=envelope.max_input_bytes,
                    max_chunk_bytes=min(65_536, envelope.max_input_bytes),
                )
                worker_client = ExternalAnalysisCoreClient(
                    base_url=servers.core_origin,
                    worker_token=fixture.worker_headers()["Authorization"].removeprefix(
                        "Bearer "
                    ),
                    worker_instance_id="spatial-blocker-worker",
                )
                assert run_once(worker_client, runtime, transport)
            detail, result, evidence = _terminal_analysis(
                fixture, servers.core_origin, intent["analysisId"]
            )
            if detail["executionState"] == "FAILED":
                assert detail["suitabilityState"] == "PROVISIONAL_ACCURACY_UNVERIFIED"
                assert {item["code"] for item in detail["blockers"]} == {
                    "EMPTY_COMMON_VALID_COVERAGE"
                }
                assert detail["result"] is result["result"] is evidence["result"] is None
            assert _terminal_analysis(fixture, servers.core_origin, intent["analysisId"]) == (
                detail,
                result,
                evidence,
            )
            assert detail["suitabilityState"] == "BLOCKED", {
                "executionState": detail["executionState"],
                "suitabilityState": detail["suitabilityState"],
                "blockers": detail["blockers"],
            }
            assert detail["executionState"] == "NOT_STARTED"
            assert detail["result"] is result["result"] is evidence["result"] is None
    finally:
        if worker_client is not None:
            worker_client.close()
        fixture.close()


def test_rotated_overlapping_current_grid_remains_an_analysis_candidate(tmp_path: Path) -> None:
    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        real_inspection=True,
        current_dsm_spatial_case="ROTATED_OVERLAPPING_GRID",
    )
    try:
        with _CoreAndObjectServers(fixture) as servers:
            reports = _inspect_both_epochs_with_actual_lane(
                fixture,
                core_origin=servers.core_origin,
                object_origin=servers.object_origin,
                tmp_path=tmp_path,
            )
            current = reports[1].measurement_payload.outcomes[0].measurements
            assert current is not None
            assert current.transform[1] != 0.0 or current.transform[3] != 0.0
            intent = _post_analysis(fixture, servers.core_origin, "rotated-overlap-candidate")
            assert intent["suitabilityState"] == "PROVISIONAL_ACCURACY_UNVERIFIED"
            assert intent["executionState"] == "QUEUED"
            assert intent["result"] is None
    finally:
        fixture.close()


def test_overlapping_dsm_with_declared_current_nodata_fails_without_publishing_result(
    tmp_path: Path,
) -> None:
    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        real_inspection=True,
        current_dsm_spatial_case="OVERLAPPING_CURRENT_NODATA_CELL",
    )
    worker_client: ExternalAnalysisCoreClient | None = None
    replay_fixture: Any | None = None
    try:
        with _CoreAndObjectServers(fixture) as servers:
            reports = _inspect_both_epochs_with_actual_lane(
                fixture,
                core_origin=servers.core_origin,
                object_origin=servers.object_origin,
                tmp_path=tmp_path,
            )
            baseline = reports[0].measurement_payload.outcomes[0]
            current = reports[1].measurement_payload.outcomes[0]
            assert baseline.measurements is not None and current.measurements is not None
            assert baseline.observed_sha256 == (
                "sha256:" + fixture._baseline_revision.manifest.entries[0].observed_sha256
            )
            assert current.observed_sha256 == (
                "sha256:" + fixture._current_revision.manifest.entries[0].observed_sha256
            )
            assert baseline.measurements.valid_pixel_count == 4
            assert current.measurements.valid_pixel_count == 3
            assert current.measurements.nodata_representation is NodataRepresentation.FINITE
            assert current.measurements.nodata_value == -9999.0
            assert baseline.measurements.transform == current.measurements.transform
            intent = _post_analysis(fixture, servers.core_origin, "overlapping-current-nodata")
            retry = _post_analysis(fixture, servers.core_origin, "overlapping-current-nodata")
            assert retry["analysisId"] == intent["analysisId"]
            assert intent["suitabilityState"] == "PROVISIONAL_ACCURACY_UNVERIFIED"
            assert intent["executionState"] == "QUEUED"
            runtime_facts = fixture.app.state.external_analysis_wiring.facade._assessments._runtime
            envelope = fixture.app.state.external_analysis_wiring.calculations._resource_envelope
            runtime = ProcessingWorkerRuntimeIdentityV1(
                worker_executable_digest=runtime_facts.worker_executable_digest,
                worker_build_digest=runtime_facts.worker_build_digest,
                runtime_image_version=runtime_facts.runtime_image_version,
                runtime_image_oci_digest=runtime_facts.runtime_image_oci_digest,
                dependency_lock_digest=runtime_facts.dependency_lock_digest,
            )
            transport = ExternalObjectTransportPolicyV1(
                endpoints=(
                    TrustedObjectEndpointV1(origin=servers.object_origin, addresses=("127.0.0.1",)),
                ),
                max_header_bytes=16_384,
                max_object_bytes=envelope.max_input_bytes,
                max_chunk_bytes=min(65_536, envelope.max_input_bytes),
            )
            worker_client = ExternalAnalysisCoreClient(
                base_url=servers.core_origin,
                worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
                worker_instance_id="overlapping-nodata-worker",
            )
            assert run_once(worker_client, runtime, transport)
            detail, result, evidence = _terminal_analysis(
                fixture, servers.core_origin, intent["analysisId"]
            )
            assert detail["executionState"] == "FAILED"
            assert detail["suitabilityState"] == "BLOCKED"
            assert {item["code"] for item in detail["blockers"]} == {
                "INSUFFICIENT_COMMON_VALID_COVERAGE"
            }
            assert detail["result"] is result["result"] is evidence["result"] is None
            assert evidence["baseline"]["observedSha256"] == baseline.observed_sha256
            assert evidence["current"]["observedSha256"] == current.observed_sha256
            assert _terminal_analysis(fixture, servers.core_origin, intent["analysisId"]) == (
                detail,
                result,
                evidence,
            )
            with httpx.Client(base_url=servers.core_origin, trust_env=False) as worker:
                jobs = worker.get(
                    "/v1/internal/analysis-jobs", headers=fixture.worker_headers()
                )
            assert jobs.status_code == 200
            assert jobs.json()["items"] == []
        original = (detail, result, evidence)
        analysis_id = intent["analysisId"]
        failure_digest = detail["authority"]["failureDigest"]
        assert failure_digest is not None
        original_epoch_digests = {
            epoch: {
                "observedSha256": evidence[epoch]["observedSha256"],
                "inspectionReportDigest": evidence[epoch]["inspectionReportDigest"],
                "inputDigest": evidence[epoch]["inputDigest"],
            }
            for epoch in ("baseline", "current")
        }
        assert original_epoch_digests["baseline"]["observedSha256"] == baseline.observed_sha256
        assert original_epoch_digests["current"]["observedSha256"] == current.observed_sha256

        if worker_client is not None:
            worker_client.close()
            worker_client = None
        fixture.close()
        replay_fixture = build_local_analysis_api_fixture(tmp_path, replay_of=fixture)
        journal_bytes_before_reads = {
            journal._path: journal._path.read_bytes()  # noqa: SLF001
            for journal in replay_fixture.opened
            if journal._path.exists()  # noqa: SLF001
        }
        with _CoreAndObjectServers(replay_fixture) as replay_servers:
            replayed = _terminal_analysis(
                replay_fixture, replay_servers.core_origin, analysis_id
            )
            replayed_again = _terminal_analysis(
                replay_fixture, replay_servers.core_origin, analysis_id
            )
        assert replayed == replayed_again == original
        replay_detail, replay_result, replay_evidence = replayed
        assert replay_detail["analysisId"] == analysis_id
        assert replay_detail["executionState"] == "FAILED"
        assert replay_detail["suitabilityState"] == "BLOCKED"
        assert replay_detail["authority"]["failureDigest"] == failure_digest
        assert (
            replay_detail["result"]
            is replay_result["result"]
            is replay_evidence["result"]
            is None
        )
        assert {
            epoch: {
                "observedSha256": replay_evidence[epoch]["observedSha256"],
                "inspectionReportDigest": replay_evidence[epoch]["inspectionReportDigest"],
                "inputDigest": replay_evidence[epoch]["inputDigest"],
            }
            for epoch in ("baseline", "current")
        } == original_epoch_digests
        assert {
            journal._path: journal._path.read_bytes()  # noqa: SLF001
            for journal in replay_fixture.opened
            if journal._path.exists()  # noqa: SLF001
        } == journal_bytes_before_reads
    finally:
        if worker_client is not None:
            worker_client.close()
        if replay_fixture is not None:
            replay_fixture.close()
        else:
            fixture.close()
