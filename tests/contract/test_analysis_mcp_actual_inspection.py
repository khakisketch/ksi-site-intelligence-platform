"""Actual-inspected DSMs produce the same Analysis record through MCP and Core HTTP."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from analysis_api_local_fixture import build_local_analysis_api_fixture
from ksi_event_contracts.external_analysis_api import AnalysisObservationSelectorV1
from ksi_processing_controller.external_analysis_core_client import ExternalAnalysisCoreClient
from ksi_processing_controller.external_analysis_worker import (
    ProcessingWorkerRuntimeIdentityV1,
    run_once,
)
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from test_external_analysis_real_inspection_lane_integration import _CoreAndObjectServers
from test_external_analysis_spatial_blockers_integration import (
    _inspect_both_epochs_with_actual_lane,
)


def _active_analysis_activation(tmp_path: Path) -> Any:
    from test_external_analysis_activation import _write_activation

    def activate(config: Any, worker: Any) -> Any:
        now = datetime.now(UTC)
        return _write_activation(
            tmp_path / "mcp-active-analysis-activation",
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


@pytest.mark.parametrize(
    ("spatial_case", "expected_execution", "expected_suitability", "expected_blocker"),
    (
        ("VALID", "COMPLETED", "PROVISIONAL_ACCURACY_UNVERIFIED", None),
        (
            "OVERLAPPING_CURRENT_NODATA_CELL",
            "FAILED",
            "BLOCKED",
            "INSUFFICIENT_COMMON_VALID_COVERAGE",
        ),
    ),
)
def test_mcp_uses_actual_inspection_and_returns_same_core_analysis(
    tmp_path: Path,
    spatial_case: str,
    expected_execution: str,
    expected_suitability: str,
    expected_blocker: str | None,
) -> None:
    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        real_inspection=True,
        ai_egress_allowed=True,
        current_dsm_spatial_case=spatial_case,
        analysis_activation=_active_analysis_activation(tmp_path),
    )
    worker: ExternalAnalysisCoreClient | None = None
    try:
        with _CoreAndObjectServers(fixture) as servers:
            reports = _inspect_both_epochs_with_actual_lane(
                fixture,
                core_origin=servers.core_origin,
                object_origin=servers.object_origin,
                tmp_path=tmp_path,
            )
            assert len(reports) == 2
            baseline_measurement = reports[0].measurement_payload.outcomes[0]
            current_measurement = reports[1].measurement_payload.outcomes[0]
            assert baseline_measurement.observed_sha256 == (
                "sha256:" + fixture._baseline_revision.manifest.entries[0].observed_sha256
            )
            assert current_measurement.observed_sha256 == (
                "sha256:" + fixture._current_revision.manifest.entries[0].observed_sha256
            )
            assert baseline_measurement.measurements is not None
            assert current_measurement.measurements is not None
            assert baseline_measurement.measurements.valid_pixel_count == 4
            if spatial_case == "OVERLAPPING_CURRENT_NODATA_CELL":
                assert current_measurement.measurements.valid_pixel_count == 3
                assert current_measurement.measurements.nodata_value == -9999.0

            create_arguments: dict[str, object] = {
                "siteId": fixture.site_id,
                "workAreaId": fixture.work_area_id,
                "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
                "current": fixture.current.model_dump(by_alias=True, mode="json"),
                "idempotencyKey": "actual-inspection-mcp-" + spatial_case.lower(),
            }
            token_file = tmp_path / ("mcp-token-" + spatial_case.lower())
            token_file.write_text(
                fixture.mcp_client_headers()["Authorization"].removeprefix("Bearer "),
                encoding="ascii",
            )
            token_file.chmod(0o600)

            runtime_facts = fixture.app.state.external_analysis_wiring.facade._assessments._runtime
            envelope = fixture.app.state.external_analysis_wiring.calculations._resource_envelope
            worker = ExternalAnalysisCoreClient(
                base_url=servers.core_origin,
                worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
                worker_instance_id="actual-inspection-mcp-worker-" + spatial_case.lower(),
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
                    TrustedObjectEndpointV1(origin=servers.object_origin, addresses=("127.0.0.1",)),
                ),
                max_header_bytes=16_384,
                max_object_bytes=envelope.max_input_bytes,
                max_chunk_bytes=min(65_536, envelope.max_input_bytes),
            )

            async def exercise_sdk() -> tuple[dict[str, Any], ...]:
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "ksi_analysis_mcp.server"],
                    env={
                        "KSI_ANALYSIS_MCP_CORE_ORIGIN": servers.core_origin,
                        "KSI_ANALYSIS_MCP_TOKEN_FILE": str(token_file),
                    },
                )
                async with (
                    stdio_client(parameters) as (read, write),
                    ClientSession(read, write) as session,
                ):
                    await session.initialize()

                    async def call(name: str, arguments: dict[str, object]) -> dict[str, Any]:
                        response = await session.call_tool(name, arguments)
                        assert response.is_error is False, response
                        assert isinstance(response.structured_content, dict)
                        return response.structured_content

                    created = await call("ksi_create_analysis", create_arguments)
                    analysis_id = created["analysisId"]
                    assert isinstance(analysis_id, str)
                    assert await asyncio.to_thread(run_once, worker, runtime, transport)
                    via_mcp_detail = await call(
                        "ksi_get_analysis",
                        {"siteId": fixture.site_id, "analysisId": analysis_id},
                    )
                    via_mcp_result = await call(
                        "ksi_get_analysis_result",
                        {"siteId": fixture.site_id, "analysisId": analysis_id},
                    )
                    via_mcp_evidence = await call(
                        "ksi_get_analysis_evidence",
                        {"siteId": fixture.site_id, "analysisId": analysis_id},
                    )
                    via_mcp_list = await call(
                        "ksi_list_analyses",
                        {"siteId": fixture.site_id, "limit": 50},
                    )
                    retried = await call("ksi_create_analysis", create_arguments)
                    return (
                        created,
                        via_mcp_detail,
                        via_mcp_result,
                        via_mcp_evidence,
                        via_mcp_list,
                        retried,
                    )

            (
                created,
                via_mcp_detail,
                via_mcp_result,
                via_mcp_evidence,
                via_mcp_list,
                retried,
            ) = asyncio.run(exercise_sdk())
            analysis_id = created["analysisId"]
            assert retried["analysisId"] == analysis_id
            assert retried["executionState"] == expected_execution
            assert retried["suitabilityState"] == expected_suitability
            assert len(
                fixture.app.state.external_analysis_wiring.intents.list_for_organization(
                    organization_id="org-a"
                )
            ) == 1

            with httpx.Client(base_url=servers.core_origin, trust_env=False) as direct:
                direct_detail = direct.get(
                    f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}",
                    headers=fixture.operator_headers(),
                )
                direct_evidence = direct.get(
                    f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
                    params={"limit": 32},
                    headers=fixture.operator_headers(),
                )
                direct_list = direct.get(
                    f"/v2/sites/{fixture.site_id}/analyses",
                    params={"limit": 50},
                    headers=fixture.operator_headers(),
                )
            assert (
                direct_detail.status_code == direct_evidence.status_code == 200
            )
            assert direct_list.status_code == 200
            assert via_mcp_detail == direct_detail.json()
            assert via_mcp_result == direct_detail.json()
            assert via_mcp_evidence == direct_evidence.json()
            assert via_mcp_list == direct_list.json()
            assert via_mcp_list["items"][0]["analysisId"] == created["analysisId"]
            assert via_mcp_detail["analysisId"] == via_mcp_result["analysisId"] == analysis_id
            assert via_mcp_detail["executionState"] == expected_execution
            assert via_mcp_detail["suitabilityState"] == expected_suitability
            authority_refs = {
                item["referenceName"]: item
                for item in via_mcp_evidence["items"]
                if item["kind"] == "AUTHORITY_REFERENCE"
            }
            assert {
                "assessmentRequestId",
                "admissionId",
                "admissionDigest",
                "calculationIdentityDigest",
                "calculationRequestId",
                "authorizationId",
            } <= authority_refs.keys()
            epochs = {
                item["epoch"]: item
                for item in via_mcp_evidence["items"]
                if item["kind"] == "EPOCH_IDENTITY"
            }
            assert epochs["BASELINE"]["observedSha256"] == (
                baseline_measurement.observed_sha256
            )
            assert (
                epochs["BASELINE"]["inspectionReportDigest"]
                == reports[0].report_digest
            )
            assert epochs["CURRENT"]["observedSha256"] == (
                current_measurement.observed_sha256
            )
            assert (
                epochs["CURRENT"]["inspectionReportDigest"]
                == reports[1].report_digest
            )
            assert epochs["BASELINE"]["inputDigest"].startswith("sha256:")
            assert epochs["CURRENT"]["inputDigest"].startswith("sha256:")

            if expected_blocker is None:
                assert via_mcp_result["result"] is not None
                numeric = next(
                    item
                    for item in via_mcp_evidence["items"]
                    if item["kind"] == "NUMERIC_RESULT"
                )
                assert numeric["resultId"] == via_mcp_result["result"]["resultId"]
                assert numeric["reportDigest"] == via_mcp_result["result"]["reportDigest"]
                assert via_mcp_result["result"]["metrics"]["uncertaintyM3"] is None
                assert authority_refs["reportDigest"]["sourceDigest"] == (
                    via_mcp_result["result"]["reportDigest"]
                )
                assert "failureDigest" not in authority_refs
            else:
                assert {item["code"] for item in via_mcp_detail["blockers"]} == {
                    expected_blocker
                }
                assert via_mcp_detail["result"] is via_mcp_result["result"] is None
                assert "failureDigest" in authority_refs
                assert "reportDigest" not in authority_refs
    finally:
        if worker is not None:
            worker.close()
        fixture.close()


def test_mcp_supports_two_independent_weekly_pairs_from_three_actual_inspections(
    tmp_path: Path,
) -> None:
    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        real_inspection=True,
        include_third_epoch=True,
        ai_egress_allowed=True,
        analysis_activation=_active_analysis_activation(tmp_path),
    )
    assert fixture.third is not None
    third_selector = fixture.third
    assert fixture._third_revision is not None
    assert fixture._third_subject is not None
    worker: ExternalAnalysisCoreClient | None = None
    try:
        with _CoreAndObjectServers(fixture) as servers:
            reports = _inspect_both_epochs_with_actual_lane(
                fixture,
                core_origin=servers.core_origin,
                object_origin=servers.object_origin,
                tmp_path=tmp_path,
                include_third_epoch=True,
            )
            assert len(reports) == 3

            revisions = (
                fixture._baseline_revision,
                fixture._current_revision,
                fixture._third_revision,
            )
            for report, revision in zip(reports, revisions, strict=True):
                measured = report.measurement_payload.outcomes[0]
                assert measured.outcome.value == "MEASURED"
                assert measured.observed_sha256 == (
                    "sha256:" + revision.manifest.entries[0].observed_sha256
                )
                assert measured.measurements is not None
                assert measured.measurements.valid_pixel_count == 4

            runtime_facts = fixture.app.state.external_analysis_wiring.facade._assessments._runtime
            envelope = fixture.app.state.external_analysis_wiring.calculations._resource_envelope
            worker = ExternalAnalysisCoreClient(
                base_url=servers.core_origin,
                worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
                worker_instance_id="actual-inspection-weekly-mcp-worker",
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
                        origin=servers.object_origin,
                        addresses=("127.0.0.1",),
                    ),
                ),
                max_header_bytes=16_384,
                max_object_bytes=envelope.max_input_bytes,
                max_chunk_bytes=min(65_536, envelope.max_input_bytes),
            )

            token_file = tmp_path / "weekly-mcp-token"
            token_file.write_text(
                fixture.mcp_client_headers()["Authorization"].removeprefix("Bearer "),
                encoding="ascii",
            )
            token_file.chmod(0o600)

            async def exercise_sdk() -> tuple[dict[str, Any], ...]:
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=["-m", "ksi_analysis_mcp.server"],
                    env={
                        "KSI_ANALYSIS_MCP_CORE_ORIGIN": servers.core_origin,
                        "KSI_ANALYSIS_MCP_TOKEN_FILE": str(token_file),
                    },
                )
                async with (
                    stdio_client(parameters) as (read, write),
                    ClientSession(read, write) as session,
                ):
                    await session.initialize()

                    async def call(
                        name: str,
                        arguments: dict[str, object],
                        *,
                        expected_error: str | None = None,
                    ) -> dict[str, Any]:
                        response = await session.call_tool(name, arguments)
                        assert response.is_error is (expected_error is not None), response
                        assert isinstance(response.structured_content, dict)
                        if expected_error is not None:
                            assert response.structured_content == {"code": expected_error}
                        return response.structured_content

                    def request(
                        baseline: AnalysisObservationSelectorV1,
                        current: AnalysisObservationSelectorV1,
                        key: str,
                    ) -> dict[str, object]:
                        return {
                            "siteId": fixture.site_id,
                            "workAreaId": fixture.work_area_id,
                            "baseline": baseline.model_dump(by_alias=True, mode="json"),
                            "current": current.model_dump(by_alias=True, mode="json"),
                            "idempotencyKey": key,
                        }

                    first_arguments = request(fixture.baseline, fixture.current, "weekly-mcp-t0-t1")
                    second_arguments = request(fixture.current, third_selector, "weekly-mcp-t1-t2")

                    async def read_record(
                        analysis_id: str,
                    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
                        arguments: dict[str, object] = {
                            "siteId": fixture.site_id,
                            "analysisId": analysis_id,
                        }
                        return (
                            await call("ksi_get_analysis", arguments),
                            await call("ksi_get_analysis_result", arguments),
                            await call("ksi_get_analysis_evidence", arguments),
                        )

                    first_created = await call("ksi_create_analysis", first_arguments)
                    first_id = first_created["analysisId"]
                    assert isinstance(first_id, str)
                    assert await asyncio.to_thread(run_once, worker, runtime, transport)
                    first_records = await read_record(first_id)
                    first_retry = await call("ksi_create_analysis", first_arguments)
                    assert first_retry["analysisId"] == first_id
                    assert first_retry["analysisId"] == first_created["analysisId"]
                    assert first_retry["evidenceDigest"] == first_records[0]["evidenceDigest"]
                    assert len(
                        fixture.app.state.external_analysis_wiring.intents.list_for_organization(
                            organization_id=fixture.organization_id
                        )
                    ) == 1

                    changed_payload = await call(
                        "ksi_create_analysis",
                        second_arguments | {"idempotencyKey": "weekly-mcp-t0-t1"},
                        expected_error="ANALYSIS_IDEMPOTENCY_CONFLICT",
                    )
                    assert changed_payload == {"code": "ANALYSIS_IDEMPOTENCY_CONFLICT"}
                    assert len(
                        fixture.app.state.external_analysis_wiring.intents.list_for_organization(
                            organization_id=fixture.organization_id
                        )
                    ) == 1

                    second_created = await call("ksi_create_analysis", second_arguments)
                    second_id = second_created["analysisId"]
                    assert isinstance(second_id, str)
                    assert second_id != first_id
                    assert await asyncio.to_thread(run_once, worker, runtime, transport)
                    second_records = await read_record(second_id)
                    assert not await asyncio.to_thread(run_once, worker, runtime, transport)
                    first_after_second = await read_record(first_id)
                    return (
                        first_created,
                        first_retry,
                        first_records[0],
                        first_records[1],
                        first_records[2],
                        second_created,
                        second_records[0],
                        second_records[1],
                        second_records[2],
                        first_after_second[0],
                        first_after_second[1],
                        first_after_second[2],
                    )

            (
                first_created,
                first_retry,
                first_detail,
                first_result,
                first_evidence,
                second_created,
                second_detail,
                second_result,
                second_evidence,
                first_detail_after_second,
                first_result_after_second,
                first_evidence_after_second,
            ) = asyncio.run(exercise_sdk())
            first_id = first_created["analysisId"]
            second_id = second_created["analysisId"]
            assert isinstance(first_id, str) and isinstance(second_id, str)
            assert first_retry["analysisId"] == first_id
            assert (
                first_detail_after_second,
                first_result_after_second,
                first_evidence_after_second,
            ) == (first_detail, first_result, first_evidence)

            direct_records: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
            with httpx.Client(base_url=servers.core_origin, trust_env=False) as direct:
                for analysis_id in (first_id, second_id):
                    path = f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}"
                    responses = (
                        direct.get(path, headers=fixture.operator_headers()),
                        direct.get(path, headers=fixture.operator_headers()),
                        direct.get(
                            path + "/evidence",
                            params={"limit": 32},
                            headers=fixture.operator_headers(),
                        ),
                    )
                    assert all(response.status_code == 200 for response in responses)
                    direct_records.append(tuple(response.json() for response in responses))

                direct_list = direct.get(
                    f"/v2/sites/{fixture.site_id}/analyses",
                    params={"limit": 50},
                    headers=fixture.operator_headers(),
                )
                assert direct_list.status_code == 200

            assert (first_detail, first_result, first_evidence) == direct_records[0]
            assert (second_detail, second_result, second_evidence) == direct_records[1]
            assert {item["analysisId"] for item in direct_list.json()["items"]} >= {
                first_id,
                second_id,
            }
            assert first_detail["analysisId"] == first_result["analysisId"] == first_id
            assert second_detail["analysisId"] == second_result["analysisId"] == second_id
            assert first_detail["executionState"] == second_detail["executionState"] == "COMPLETED"
            assert first_detail["suitabilityState"] == second_detail["suitabilityState"] == (
                "PROVISIONAL_ACCURACY_UNVERIFIED"
            )
            assert first_detail["workAreaId"] == second_detail["workAreaId"] == fixture.work_area_id

            first_items = first_evidence["items"]
            second_items = second_evidence["items"]
            first_calculation = next(
                item["calculation"]
                for item in first_items
                if item["kind"] == "CALCULATION_IDENTITY"
            )
            second_calculation = next(
                item["calculation"]
                for item in second_items
                if item["kind"] == "CALCULATION_IDENTITY"
            )
            assert first_calculation["workAreaDefinitionDigest"] == (
                second_calculation["workAreaDefinitionDigest"]
            )
            assert first_calculation["policy"] == second_calculation["policy"]
            assert first_calculation["runtime"] == second_calculation["runtime"]

            first_epochs = {
                item["epoch"]: item for item in first_items if item["kind"] == "EPOCH_IDENTITY"
            }
            second_epochs = {
                item["epoch"]: item for item in second_items if item["kind"] == "EPOCH_IDENTITY"
            }
            first_baseline = first_epochs["BASELINE"]
            first_current = first_epochs["CURRENT"]
            second_baseline = second_epochs["BASELINE"]
            second_current = second_epochs["CURRENT"]
            assert first_created["baseline"] == fixture.baseline.model_dump(
                by_alias=True, mode="json"
            )
            assert first_created["current"] == second_created["baseline"] == (
                fixture.current.model_dump(by_alias=True, mode="json")
            )
            assert second_created["current"] == third_selector.model_dump(
                by_alias=True, mode="json"
            )
            assert first_current["selector"] == second_baseline["selector"]
            assert first_current["observedSha256"] == second_baseline["observedSha256"]
            assert first_current["inputDigest"] == second_baseline["inputDigest"]
            assert first_current["inspectionReportDigest"] == second_baseline[
                "inspectionReportDigest"
            ] == reports[1].report_digest
            assert first_baseline["inspectionReportDigest"] == reports[0].report_digest
            assert second_current["inspectionReportDigest"] == reports[2].report_digest
            assert first_baseline["observedSha256"] == (
                "sha256:" + fixture._baseline_revision.manifest.entries[0].observed_sha256
            )
            assert first_current["observedSha256"] == (
                "sha256:" + fixture._current_revision.manifest.entries[0].observed_sha256
            )
            assert second_current["observedSha256"] == (
                "sha256:" + fixture._third_revision.manifest.entries[0].observed_sha256
            )
            assert first_baseline["inputDigest"] != first_current["inputDigest"]
            assert second_baseline["inputDigest"] != second_current["inputDigest"]
            assert second_current["inputDigest"] != first_current["inputDigest"]

            first_authority = {
                item["referenceName"]: item["recordId"]
                for item in first_evidence["items"]
                if item["kind"] == "AUTHORITY_REFERENCE"
            }
            second_authority = {
                item["referenceName"]: item["recordId"]
                for item in second_evidence["items"]
                if item["kind"] == "AUTHORITY_REFERENCE"
            }
            for authority_field in (
                "assessmentRequestId",
                "admissionId",
                "admissionDigest",
                "calculationIdentityDigest",
                "calculationRequestId",
                "authorizationId",
            ):
                assert first_authority[authority_field] != second_authority[authority_field]
            assert first_calculation["calculationId"] != second_calculation["calculationId"]
            first_payload = first_result["result"]
            second_payload = second_result["result"]
            assert first_payload is not None and second_payload is not None
            assert first_payload["resultId"] != second_payload["resultId"]
            assert first_payload["reportDigest"] != second_payload["reportDigest"]
            assert first_payload["numericResultIdentityDigest"] != second_payload[
                "numericResultIdentityDigest"
            ]
            assert first_payload["metrics"]["uncertaintyM3"] is None
            assert second_payload["metrics"]["uncertaintyM3"] is None
            assert first_payload["metrics"]["cutM3"] == pytest.approx(0.01)
            assert first_payload["metrics"]["fillM3"] == pytest.approx(0.01)
            assert second_payload["metrics"]["cutM3"] == pytest.approx(0.02)
            assert second_payload["metrics"]["fillM3"] == pytest.approx(0.02)
            assert len(
                fixture.app.state.external_analysis_wiring.intents.list_for_organization(
                    organization_id=fixture.organization_id
                )
            ) == 2
    finally:
        if worker is not None:
            worker.close()
        fixture.close()
