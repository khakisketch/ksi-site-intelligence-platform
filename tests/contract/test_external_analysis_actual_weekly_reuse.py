"""Three actual-inspected DSM epochs feed two independently recorded weekly pairs."""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import uuid4

import httpx
import pytest
from analysis_api_local_fixture import LocalAnalysisApiFixture, build_local_analysis_api_fixture
from fastapi.testclient import TestClient
from ksi_event_contracts.external_analysis_api import AnalysisObservationSelectorV1
from ksi_event_contracts.external_artifact_validation import ExternalArtifactInspectionReportV1
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
)

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            assert isinstance(key, str)
            result[key] = _json_value(item)
        return result
    raise AssertionError(f"unexpected non-JSON value: {type(value).__name__}")


def _json_object(value: object) -> JsonObject:
    normalized = _json_value(value)
    assert isinstance(normalized, dict)
    return normalized


def _nested(value: JsonObject, key: str) -> JsonObject:
    return _json_object(value[key])


def _request_body(
    baseline: AnalysisObservationSelectorV1, current: AnalysisObservationSelectorV1
) -> dict[str, object]:
    return {
        "baseline": baseline.model_dump(by_alias=True, mode="json"),
        "current": current.model_dump(by_alias=True, mode="json"),
    }


def _completed(
    client: httpx.Client, *, site_id: str, analysis_id: str, headers: dict[str, str]
) -> tuple[JsonObject, JsonObject, JsonObject]:
    detail_url = f"/v1/sites/{site_id}/analyses/{analysis_id}"
    for _ in range(100):
        detail = client.get(detail_url, headers=headers)
        assert detail.status_code == 200, detail.text
        if detail.json()["executionState"] == "COMPLETED":
            break
        time.sleep(0.02)
    result = client.get(detail_url + "/result", headers=headers)
    evidence = client.get(detail_url + "/evidence", headers=headers)
    assert detail.status_code == result.status_code == evidence.status_code == 200
    assert detail.json()["executionState"] == "COMPLETED"
    assert detail.json()["suitabilityState"] == "PROVISIONAL_ACCURACY_UNVERIFIED"
    assert detail.json()["result"] == result.json()["result"] == evidence.json()["result"]
    return _json_object(detail.json()), _json_object(result.json()), _json_object(evidence.json())


def _inspect_three_epochs(
    fixture: LocalAnalysisApiFixture,
    *,
    servers: _CoreAndObjectServers,
    tmp_path: Path,
) -> tuple[ExternalArtifactInspectionReportV1, ...]:
    inspection_store = fixture.app.state.external_artifact_inspection_store
    worker_id = str(uuid4())
    socket_path = Path("/tmp") / f"ksi-weekly-lane-{uuid4().hex}.sock"
    inspector_root = tmp_path / "weekly-real-inspector-root"
    inspector_root.mkdir(mode=0o700)
    subjects = (
        fixture._baseline_subject,
        fixture._current_subject,
        fixture._third_subject,
    )
    revisions = (
        fixture._baseline_revision,
        fixture._current_revision,
        fixture._third_revision,
    )
    with _RealDsmInspectorUds(
        path=socket_path,
        manifest=fixture._inspector_manifest,
        root=inspector_root,
    ) as inspector:
        reports: list[ExternalArtifactInspectionReportV1] = []
        core = ExternalValidationCoreClient(
            base_url=servers.core_origin,
            bearer_token=fixture.validation_worker_headers()["Authorization"].removeprefix(
                "Bearer "
            ),
        )
        lane = _inspection_lane(
            fixture,
            core=core,
            object_origin=servers.object_origin,
            socket_path=socket_path,
            private_root=tmp_path / "weekly-inspection-private",
            worker_instance_id=worker_id,
        )
        try:
            for index, (subject, revision) in enumerate(zip(subjects, revisions, strict=True)):
                if index == 2:
                    # Core caps active inspection leases per tenant at two; completed
                    # reports leave their lease fences current until the fixed TTL expires.
                    time.sleep(
                        fixture._inspection_policy.resource_envelope.lease_duration_seconds + 1
                    )
                now = max(datetime.now(UTC).replace(microsecond=0), fixture._fixture_now)
                issued = inspection_store.issue_after_seal(subject, now=now)
                assert issued.request is not None
                assert issued.verdict.value in {"ISSUED", "IDEMPOTENT"}
                deadline = time.monotonic() + 25
                request_id = lane.poll(deadline_monotonic=deadline)
                assert request_id == issued.request.request_id
                assert request_id is not None
                lease = lane.claim(request_id, str(uuid4()), deadline_monotonic=deadline)
                assert lease is not None
                try:
                    assert lane.execute(
                        lease, deadline_monotonic=deadline, stop=Event()
                    ) is TurnOutcome.COMPLETED
                finally:
                    lane.release(lease)
                report = inspection_store.public_snapshot(subject).report
                assert report is not None
                assert report.worker_instance_id == worker_id
                measured = report.measurement_payload.outcomes[0]
                assert measured.outcome.value == "MEASURED"
                assert measured.observed_sha256 == (
                    "sha256:" + revision.manifest.entries[0].observed_sha256
                )
                assert measured.measurements == inspector.measured[len(reports)].measurements
                reports.append(report)
        finally:
            lane.close()
            core.close()
        expected_digests = tuple(
            "sha256:" + revision.manifest.entries[0].observed_sha256
            for revision in revisions
        )
        assert tuple(inspector.actual_source_digests) == expected_digests
        assert tuple(inspector.source_digests) == expected_digests
        assert len(inspector.measured) == 3
        for measured in inspector.measured:
            assert measured.measurements is not None
            facts = measured.measurements
            assert facts.observed_crs_identifier == "EPSG:5186"
            assert facts.observed_vertical_reference is not None
            assert facts.observed_vertical_reference.identifier == "EPSG:5773"
            assert facts.observed_crs_wkt is not None
            assert facts.observed_crs_digest == (
                "sha256:" + hashlib.sha256(facts.observed_crs_wkt.encode()).hexdigest()
            )
            assert (facts.width, facts.height, facts.valid_pixel_count) == (2, 2, 4)
            assert facts.transform == (0.1, 0.0, 200000.0, 0.0, -0.1, 550000.0)
    return tuple(reports)


def test_three_actual_inspections_support_two_independent_weekly_pairs_and_replay(
    tmp_path: Path,
) -> None:
    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        include_third_epoch=True,
        real_inspection=True,
    )
    assert fixture.third is not None
    assert fixture._third_revision is not None
    assert fixture._third_subject is not None
    servers: _CoreAndObjectServers | None = None
    worker: ExternalAnalysisCoreClient | None = None
    fixture_closed = False
    replay_fixture = None
    try:
        servers = _CoreAndObjectServers(fixture)
        servers.__enter__()
        reports = _inspect_three_epochs(fixture, servers=servers, tmp_path=tmp_path)
        assert len(reports) == 3
        with httpx.Client(base_url=servers.core_origin, trust_env=False) as operator:
            created_at = datetime.now(UTC)
            selectors = (fixture.baseline, fixture.current, fixture.third)
            assert all(item[3] <= created_at for item in fixture.synthetic_epoch_chronology)
            assert all(report.reported_at <= created_at for report in reports)
            assert all(
                earlier.reported_at < later.reported_at
                for earlier, later in zip(reports, reports[1:], strict=False)
            )
            assert all(
                revision.submission.input_declaration.capture_ended_at < report.reported_at
                for revision, report in zip(
                    (
                        fixture._baseline_revision,
                        fixture._current_revision,
                        fixture._third_revision,
                    ),
                    reports,
                    strict=True,
                )
            )
            assert selectors[2] is not None
            analysis_url = (
                f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses"
            )
            headers = fixture.operator_headers()
            first_body = _request_body(selectors[0], selectors[1])
            second_body = _request_body(selectors[1], selectors[2])
            first_created = operator.post(
                analysis_url,
                headers={**headers, "Idempotency-Key": "actual-weekly-t0-t1"},
                json=first_body,
            )
            assert first_created.status_code == 202, first_created.text
            first_id = first_created.json()["analysisId"]
            facts = fixture.app.state.external_analysis_wiring.facade._assessments._runtime
            envelope = fixture.app.state.external_analysis_wiring.calculations._resource_envelope
            runtime = ProcessingWorkerRuntimeIdentityV1(
                worker_executable_digest=facts.worker_executable_digest,
                worker_build_digest=facts.worker_build_digest,
                runtime_image_version=facts.runtime_image_version,
                runtime_image_oci_digest=facts.runtime_image_oci_digest,
                dependency_lock_digest=facts.dependency_lock_digest,
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
            worker = ExternalAnalysisCoreClient(
                base_url=servers.core_origin,
                worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
                worker_instance_id="actual-weekly-reuse-worker",
            )
            assert run_once(worker, runtime, transport)
            first = _completed(
                operator, site_id=fixture.site_id, analysis_id=first_id, headers=headers
            )
            first_retry = operator.post(
                analysis_url,
                headers={**headers, "Idempotency-Key": "actual-weekly-t0-t1"},
                json=first_body,
            )
            assert first_retry.status_code == 202, first_retry.text
            assert first_retry.json()["analysisId"] == first_id
            second_created = operator.post(
                analysis_url,
                headers={**headers, "Idempotency-Key": "actual-weekly-t1-t2"},
                json=second_body,
            )
            assert second_created.status_code == 202, second_created.text
            second_id = second_created.json()["analysisId"]
            assert second_id != first_id
            assert run_once(worker, runtime, transport)
            second = _completed(
                operator, site_id=fixture.site_id, analysis_id=second_id, headers=headers
            )
            second_retry = operator.post(
                analysis_url,
                headers={**headers, "Idempotency-Key": "actual-weekly-t1-t2"},
                json=second_body,
            )
            assert second_retry.status_code == 202, second_retry.text
            assert second_retry.json()["analysisId"] == second_id
            assert not run_once(worker, runtime, transport)

            first_detail, first_result_response, first_evidence_response = first
            second_detail, second_result_response, second_evidence_response = second
            first_result = _nested(first_result_response, "result")
            second_result = _nested(second_result_response, "result")
            first_evidence = first_evidence_response
            second_evidence = second_evidence_response
            first_calculation = _nested(first_evidence, "calculation")
            second_calculation = _nested(second_evidence, "calculation")
            first_policy = _nested(first_calculation, "policy")
            second_policy = _nested(second_calculation, "policy")
            first_current = _nested(first_evidence, "current")
            second_current = _nested(second_evidence, "current")
            second_baseline = _nested(second_evidence, "baseline")
            assert first_detail["workAreaId"] == second_detail["workAreaId"] == (
                fixture.work_area_id
            )
            assert first_calculation["workAreaDefinitionDigest"] == (
                second_calculation["workAreaDefinitionDigest"]
            )
            assert first_policy == second_policy
            assert (
                first_policy["profileId"]
                == second_policy["profileId"]
                == "KSI-GIS-RELATIVE-VOLUME-V2"
            )
            assert first_current["selector"] == second_baseline["selector"]
            for field in ("artifactId", "observedSha256", "inputDigest", "inspectionReportDigest"):
                assert first_current[field] == second_baseline[field]
            assert first_current["observedSha256"] == (
                "sha256:" + fixture._current_revision.manifest.entries[0].observed_sha256
            )
            assert first_current["inspectionReportDigest"] == (
                reports[1].report_digest
            )
            assert second_current["inspectionReportDigest"] == (
                reports[2].report_digest
            )
            for response, expected_reports in (
                (first_evidence, reports[:2]),
                (second_evidence, reports[1:]),
            ):
                assert [
                    _nested(response, key)["inspectionReportDigest"]
                    for key in ("baseline", "current")
                ] == [report.report_digest for report in expected_reports]
            first_authority = _nested(first_detail, "authority")
            second_authority = _nested(second_detail, "authority")
            assert (
                first_authority["admissionId"] != second_authority["admissionId"]
            )
            assert first_authority["admissionDigest"] != second_authority["admissionDigest"]
            assert first_authority["calculationIdentityDigest"] != second_authority[
                "calculationIdentityDigest"
            ]
            assert first_authority["calculationRequestId"] != second_authority[
                "calculationRequestId"
            ]
            assert first_calculation["calculationId"] != second_calculation["calculationId"]
            assert first_result["resultId"] != second_result["resultId"]
            assert first_result["reportDigest"] != second_result["reportDigest"]
            assert first_result["numericResultIdentityDigest"] != second_result[
                "numericResultIdentityDigest"
            ]
            first_metrics = _nested(first_result, "metrics")
            second_metrics = _nested(second_result, "metrics")
            assert first_metrics["fillM3"] == pytest.approx(0.01)
            assert first_metrics["cutM3"] == pytest.approx(0.01)
            assert second_metrics["fillM3"] == pytest.approx(0.02)
            assert second_metrics["cutM3"] == pytest.approx(0.02)
            first_still_readable = _completed(
                operator, site_id=fixture.site_id, analysis_id=first_id, headers=headers
            )
            assert first_still_readable == first
            second_still_readable = _completed(
                operator, site_id=fixture.site_id, analysis_id=second_id, headers=headers
            )
            assert second_still_readable == second

        worker.close()
        worker = None
        servers.__exit__(None, None, None)
        servers = None
        fixture.close()
        fixture_closed = True
        replay_fixture = build_local_analysis_api_fixture(tmp_path, replay_of=fixture)
        replay = TestClient(replay_fixture.app)
        for analysis_id, expected in ((first_id, first), (second_id, second)):
            detail_url = f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}"
            actual = (
                replay.get(detail_url, headers=replay_fixture.operator_headers()),
                replay.get(detail_url + "/result", headers=replay_fixture.operator_headers()),
                replay.get(detail_url + "/evidence", headers=replay_fixture.operator_headers()),
            )
            assert all(response.status_code == 200 for response in actual)
            assert tuple(_json_object(response.json()) for response in actual) == expected
    finally:
        if worker is not None:
            worker.close()
        if servers is not None:
            servers.__exit__(None, None, None)
        if replay_fixture is not None:
            replay_fixture.close()
        if not fixture_closed:
            fixture.close()
