"""External result-contract cross-check against a real local Core lane.

The example ``examples/analysis/result_contract_crosscheck.py`` runs as a
subprocess (an outside codebase: stdlib + httpx, ``mcp`` only for the MCP
path) against a REAL local Core lane built from the repo fixture with real
inspected bytes. It reads one analysis through both the Core HTTP API and
the Analysis MCP stdio adapter and cross-checks the common result contract.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
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
from test_external_analysis_activation import _write_activation
from test_external_analysis_real_inspection_lane_integration import _CoreAndObjectServers
from test_external_analysis_spatial_blockers_integration import (
    _inspect_both_epochs_with_actual_lane,
)

EXAMPLE = (
    Path(__file__).resolve().parents[2] / "examples" / "analysis" / "result_contract_crosscheck.py"
)

SEVEN_ELEMENT_IDS = (
    "numeric",
    "region",
    "input-version",
    "calculation-settings",
    "valid-region",
    "quality",
    "limitations",
)

EXPECTED_CHECK_IDS = SEVEN_ELEMENT_IDS + (
    "continuation",
    "coverage-resource",
    "http-list",
    "mcp-parity",
)

STATUS_FAIL = "FAIL"
STATUS_SKIPPED = "SKIPPED"


def _active_analysis_activation(tmp_path: Path) -> Any:
    def activate(config: Any, worker: Any) -> Any:
        now = datetime.now(UTC)
        return _write_activation(
            tmp_path / "crosscheck-analysis-activation",
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


def _create_analysis(
    http: httpx.Client, fixture: Any, baseline: Any, current: Any, key: str
) -> str:
    response = http.post(
        f"/v2/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
        headers={**fixture.operator_headers(), "Idempotency-Key": key},
        json={
            "baseline": baseline.model_dump(by_alias=True, mode="json"),
            "current": current.model_dump(by_alias=True, mode="json"),
        },
    )
    assert response.status_code == 202, response.text
    analysis_id = response.json()["analysisId"]
    assert isinstance(analysis_id, str)
    return analysis_id


def _wait_completed(http: httpx.Client, fixture: Any, analysis_id: str) -> dict[str, Any]:
    for _ in range(200):
        detail = http.get(
            f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}",
            headers=fixture.operator_headers(),
        )
        assert detail.status_code == 200, detail.text
        body = detail.json()
        if body["executionState"] in ("COMPLETED", "FAILED"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"analysis {analysis_id} did not finish")


def _run_worker_to_idle(fixture: Any, servers: _CoreAndObjectServers) -> None:
    runtime_facts = fixture.app.state.external_analysis_wiring.facade._assessments._runtime
    envelope = fixture.app.state.external_analysis_wiring.calculations._resource_envelope
    worker = ExternalAnalysisCoreClient(
        base_url=servers.core_origin,
        worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
        worker_instance_id="crosscheck-worker",
    )
    try:
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
        assert run_once(worker, runtime, transport)
        assert run_once(worker, runtime, transport)
        assert not run_once(worker, runtime, transport)
    finally:
        worker.close()


def test_external_crosscheck_passes_for_two_completed_pairs(tmp_path: Path) -> None:
    """The example exits 0 with zero FAILs and a verified continuation."""
    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        include_third_epoch=True,
        real_inspection=True,
        ai_egress_allowed=True,
        analysis_activation=_active_analysis_activation(tmp_path),
    )
    assert fixture.third is not None
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
            with httpx.Client(base_url=servers.core_origin, trust_env=False) as http:
                first_id = _create_analysis(
                    http, fixture, fixture.baseline, fixture.current, "crosscheck-t0-t1"
                )
                second_id = _create_analysis(
                    http, fixture, fixture.current, fixture.third, "crosscheck-t1-t2"
                )
                assert first_id != second_id
            _run_worker_to_idle(fixture, servers)
            with httpx.Client(base_url=servers.core_origin, trust_env=False) as http:
                first_detail = _wait_completed(http, fixture, first_id)
                second_detail = _wait_completed(http, fixture, second_id)
            assert first_detail["executionState"] == "COMPLETED"
            assert second_detail["executionState"] == "COMPLETED"

            mcp_token = fixture.mcp_client_headers()["Authorization"].removeprefix("Bearer ")
            operator_token = fixture.operator_headers()["Authorization"].removeprefix("Bearer ")
            mcp_token_file = tmp_path / "crosscheck-mcp-token"
            mcp_token_file.write_text(mcp_token, encoding="ascii")
            mcp_token_file.chmod(0o600)
            out_path = tmp_path / "crosscheck-record.json"
            env = {key: value for key, value in os.environ.items() if key != "KSI_CUSTOMER_TOKEN"}
            env["KSI_CUSTOMER_TOKEN"] = operator_token
            completed = subprocess.run(
                [
                    sys.executable,
                    str(EXAMPLE),
                    "--core-origin",
                    servers.core_origin,
                    "--site-id",
                    fixture.site_id,
                    "--analysis-id",
                    first_id,
                    "--out",
                    str(out_path),
                    "--mcp-token-file",
                    str(mcp_token_file),
                    "--mcp-core-origin",
                    servers.core_origin,
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
            )
            assert completed.returncode == 0, completed.stderr
            record = json.loads(out_path.read_text(encoding="utf-8"))
            assert record["siteId"] == fixture.site_id
            assert record["analysisId"] == first_id
            assert record["mcpUsed"] is True
            assert [check["id"] for check in record["checks"]] == list(EXPECTED_CHECK_IDS)
            by_status = {check["id"]: check["status"] for check in record["checks"]}
            assert set(by_status) == set(EXPECTED_CHECK_IDS)
            assert all(status in ("PASS", "SKIPPED") for status in by_status.values()), record[
                "checks"
            ]
            for element_id in SEVEN_ELEMENT_IDS:
                assert by_status[element_id] == "PASS", record["checks"]
            assert by_status["continuation"] == "PASS"
            assert by_status["coverage-resource"] == "PASS"
            assert by_status["http-list"] == "PASS"
            assert by_status["mcp-parity"] == "PASS"
            continuations = {entry["analysisId"]: entry for entry in record["continuations"]}
            assert second_id in continuations, record["continuations"]
            assert continuations[second_id]["verified"] is True
            # The shared OBSERVATION must be identical on both sides. The
            # per-execution digests (inspection report, input digest) are
            # produced once per analysis and are recorded, not compared.
            assert {
                "observationEpochId",
                "artifactId",
                "observedSha256",
                "observedCrsIdentifier",
                "verticalReferenceIdentifier",
                "transformDigest",
            } <= set(continuations[second_id]["matchedFields"])
            assert "inputDigest" not in continuations[second_id]["matchedFields"]
            per_execution = continuations[second_id]["perExecutionFieldsEqual"]
            assert set(per_execution) == {
                "inputDigest",
                "inspectionReportDigest",
                "inspectionReportRecordId",
            }
            assert all(isinstance(value, bool) for value in per_execution.values())
            assert record["lists"]["agree"] is True
            assert {item["analysisId"] for item in record["lists"]["http"]} >= {
                first_id,
                second_id,
            }
            assert record["lists"]["mcp"] == record["lists"]["http"]
            coverage = record["coverage"]
            assert coverage["receivedBytes"] == coverage["totalLengthBytes"]
            assert str(coverage["digest"]).startswith("sha256:")
            blob = json.dumps(record)
            assert operator_token not in blob
            assert mcp_token not in blob
    finally:
        fixture.close()


def _synthetic_completed_inputs(tmp_path: Path) -> tuple[Any, Any, Any]:
    """One completed pair over synthetic inspection, fetched as plain JSON."""
    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        include_third_epoch=True,
        real_inspection=False,
        analysis_activation=_active_analysis_activation(tmp_path),
    )
    assert fixture.third is not None
    servers = _CoreAndObjectServers(fixture)
    servers.__enter__()
    try:
        with httpx.Client(base_url=servers.core_origin, trust_env=False) as http:
            first_id = _create_analysis(
                http, fixture, fixture.baseline, fixture.current, "mut-t0-t1"
            )
            second_id = _create_analysis(http, fixture, fixture.current, fixture.third, "mut-t1-t2")
        _run_worker_to_idle(fixture, servers)
        with httpx.Client(base_url=servers.core_origin, trust_env=False) as http:
            headers = fixture.operator_headers()
            detail = http.get(
                f"/v2/sites/{fixture.site_id}/analyses/{first_id}", headers=headers
            ).json()
            assert detail["executionState"] == "COMPLETED"
            evidence = http.get(
                f"/v2/sites/{fixture.site_id}/analyses/{first_id}/evidence",
                params={"limit": 32},
                headers=headers,
            ).json()
            assert evidence["nextCursor"] is None
            second_detail = http.get(
                f"/v2/sites/{fixture.site_id}/analyses/{second_id}", headers=headers
            ).json()
            second_evidence = http.get(
                f"/v2/sites/{fixture.site_id}/analyses/{second_id}/evidence",
                params={"limit": 32},
                headers=headers,
            ).json()
            listed = http.get(
                f"/v2/sites/{fixture.site_id}/analyses",
                params={"limit": 50},
                headers=headers,
            ).json()
            assert listed["nextCursor"] is None
        return (
            fixture,
            servers,
            {
                "first_id": first_id,
                "second_id": second_id,
                "detail": detail,
                "evidence_items": evidence["items"],
                "list_items": listed["items"],
                "second_detail": second_detail,
                "second_evidence_items": second_evidence["items"],
            },
        )
    except BaseException:
        servers.__exit__(None, None, None)
        fixture.close()
        raise


def test_crosscheck_detects_mutated_comparison_input(tmp_path: Path) -> None:
    """A tampered copy of the consumer's own input must report FAIL."""
    sys.path.insert(0, str(EXAMPLE.parent))
    try:
        import result_contract_crosscheck as crosscheck
    finally:
        sys.path.remove(str(EXAMPLE.parent))
    fixture, servers, fetched = _synthetic_completed_inputs(tmp_path)
    try:
        inputs = crosscheck.ComparisonInputs(
            site_id=fixture.site_id,
            analysis_id=fetched["first_id"],
            http_detail=fetched["detail"],
            http_evidence_items=fetched["evidence_items"],
            http_list_items=fetched["list_items"],
            named_continuations=[fetched["second_id"]],
            siblings={
                fetched["second_id"]: {
                    "detail": fetched["second_detail"],
                    "evidenceItems": fetched["second_evidence_items"],
                }
            },
            coverage=None,
        )
        base, _ = crosscheck.evaluate_contract(inputs)
        assert {check.id: check.status for check in base}["numeric"] == "PASS"

        mutated = copy.deepcopy(inputs)
        numeric_item = next(
            item for item in mutated.http_evidence_items if item["kind"] == "NUMERIC_RESULT"
        )
        numeric_item["resultId"] = "tampered-result-id"
        checks, _ = crosscheck.evaluate_contract(mutated)
        by_status = {check.id: check.status for check in checks}
        assert by_status["numeric"] == "FAIL"
        assert STATUS_FAIL in by_status.values()
    finally:
        servers.__exit__(None, None, None)
        fixture.close()


def test_withheld_result_is_skipped_and_per_execution_digests_do_not_break_the_link(
    tmp_path: Path,
) -> None:
    """A withheld number is a state, and per-execution digests differ by design.

    Two properties the live rig showed, now locked into the contract:

    * an analysis whose numeric result Core withheld (reassessment required,
      blocked, not started) is SKIPPED for the result-scoped elements — never
      a FAIL, never a silent PASS;
    * the inspection-report and input digests are produced once per analysis,
      so two analyses that share an observation epoch legitimately differ
      there. The shared observation itself must still verify.
    """
    sys.path.insert(0, str(EXAMPLE.parent))
    try:
        import result_contract_crosscheck as crosscheck
    finally:
        sys.path.remove(str(EXAMPLE.parent))
    fixture, servers, fetched = _synthetic_completed_inputs(tmp_path)
    try:
        withheld = copy.deepcopy(fetched["detail"])
        withheld["result"] = None
        withheld["suitabilityState"] = "REASSESSMENT_REQUIRED"
        withheld["blockers"] = [
            {"code": "REASSESSMENT_REQUIRED", "epoch": None, "evidenceRef": None, "detail": None}
        ]
        withheld_evidence = [
            item
            for item in copy.deepcopy(fetched["evidence_items"])
            if item["kind"] not in ("NUMERIC_RESULT", "LIMITATION")
            or item.get("source") != "RESULT"
        ]
        # The blocker the detail now carries must also be in the evidence.
        withheld_evidence.append(
            {
                "kind": "LIMITATION",
                "recordId": "limitation-reassessment-required",
                "digest": "sha256:" + "a" * 64,
                "limitationCodes": [],
                "source": "BLOCKER",
                "code": "REASSESSMENT_REQUIRED",
                "epoch": None,
                "evidenceRef": None,
                "detail": None,
            }
        )
        inputs = crosscheck.ComparisonInputs(
            site_id=fixture.site_id,
            analysis_id=fetched["first_id"],
            http_detail=withheld,
            http_evidence_items=withheld_evidence,
            http_list_items=fetched["list_items"],
            named_continuations=[fetched["second_id"]],
            siblings={
                fetched["second_id"]: {
                    "detail": fetched["second_detail"],
                    "evidenceItems": fetched["second_evidence_items"],
                }
            },
            coverage=None,
        )
        checks, _ = crosscheck.evaluate_contract(inputs)
        by_status = {check.id: check.status for check in checks}
        for element_id in ("numeric", "region", "valid-region", "coverage-resource"):
            assert by_status[element_id] == STATUS_SKIPPED, checks
        assert by_status["limitations"] == "PASS", checks
        assert by_status["continuation"] == "PASS", checks
        # The list still carries a result identity the detail no longer has:
        # the reconciliation check must see that.
        assert by_status["http-list"] == STATUS_FAIL, checks

        # Per-execution digests differ between two analyses of one epoch.
        mutated_sibling_evidence = copy.deepcopy(fetched["second_evidence_items"])
        for item in mutated_sibling_evidence:
            if item["kind"] == "EPOCH_IDENTITY" and item["epoch"] == "BASELINE":
                item["inputDigest"] = "sha256:" + "f" * 64
                item["inspectionReportDigest"] = "sha256:" + "e" * 64
        differing = crosscheck.ComparisonInputs(
            site_id=fixture.site_id,
            analysis_id=fetched["first_id"],
            http_detail=fetched["detail"],
            http_evidence_items=fetched["evidence_items"],
            http_list_items=fetched["list_items"],
            named_continuations=[fetched["second_id"]],
            siblings={
                fetched["second_id"]: {
                    "detail": fetched["second_detail"],
                    "evidenceItems": mutated_sibling_evidence,
                }
            },
            coverage=None,
        )
        checks, entries = crosscheck.evaluate_contract(differing)
        assert {check.id: check.status for check in checks}["continuation"] == "PASS", checks
        entry = next(e for e in entries if e["analysisId"] == fetched["second_id"])
        assert entry["verified"] is True
        assert entry["perExecutionFieldsEqual"]["inputDigest"] is False
        assert entry["perExecutionFieldsEqual"]["inspectionReportDigest"] is False
    finally:
        servers.__exit__(None, None, None)
        fixture.close()


def test_crosscheck_closed_failure_cases(tmp_path: Path) -> None:
    """Missing token and bad identifiers fail closed without echoing secrets."""
    scrubbed = {key: value for key, value in os.environ.items() if key != "KSI_CUSTOMER_TOKEN"}
    missing = subprocess.run(
        [
            sys.executable,
            str(EXAMPLE),
            "--core-origin",
            "http://127.0.0.1:1",
            "--site-id",
            "site-a",
            "--analysis-id",
            "analysis-a",
            "--out",
            str(tmp_path / "missing.json"),
        ],
        env=scrubbed,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert missing.returncode == 2
    assert "TOKEN_UNAVAILABLE" in missing.stderr

    canary = "canary-secret-token-abcdef123456"
    evil_env = dict(scrubbed)
    evil_env["KSI_CUSTOMER_TOKEN"] = canary
    evil = subprocess.run(
        [
            sys.executable,
            str(EXAMPLE),
            "--core-origin",
            "http://127.0.0.1:1",
            "--site-id",
            "../evil",
            "--analysis-id",
            "analysis-a",
            "--out",
            str(tmp_path / "evil.json"),
        ],
        env=evil_env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert evil.returncode == 2
    assert "INVALID_IDENTIFIER" in evil.stderr
    assert canary not in evil.stderr
    assert canary not in evil.stdout


def test_crosscheck_module_imports_without_ksi_or_mcp(tmp_path: Path) -> None:
    """The example stays an outside codebase: no KSI import, lazy mcp import."""
    assert tmp_path.is_dir()
    probe_lines = [
        "import importlib.abc",
        "import sys",
        "",
        "class Blocker(importlib.abc.MetaPathFinder):",
        "    def find_spec(self, name, path=None, target=None):",
        "        blocked = name == 'mcp' or name.startswith(('ksi_', 'mcp.'))",
        "        if blocked:",
        "            raise ImportError('blocked:' + name)",
        "        return None",
        "",
        "sys.meta_path.insert(0, Blocker())",
        f"sys.path.insert(0, {str(EXAMPLE.parent)!r})",
        "import result_contract_crosscheck as m",
        "assert list(m.CHECK_IDS)[:7] == list(m.SEVEN_ELEMENT_IDS)",
        "print('import-ok')",
    ]
    probe = "\n".join(probe_lines) + "\n"
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert "import-ok" in completed.stdout


def test_crosscheck_skips_mcp_without_token_file(tmp_path: Path) -> None:
    """Without --mcp-token-file the MCP check is SKIPPED, never PASS."""
    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        real_inspection=False,
        analysis_activation=_active_analysis_activation(tmp_path),
    )
    try:
        with _CoreAndObjectServers(fixture) as servers:
            with httpx.Client(base_url=servers.core_origin, trust_env=False) as http:
                analysis_id = _create_analysis(
                    http, fixture, fixture.baseline, fixture.current, "skip-mcp-1"
                )
            _run_worker_once(fixture, servers)
            with httpx.Client(base_url=servers.core_origin, trust_env=False) as http:
                detail = _wait_completed(http, fixture, analysis_id)
            assert detail["executionState"] == "COMPLETED"
            operator_token = fixture.operator_headers()["Authorization"].removeprefix("Bearer ")
            out_path = tmp_path / "skip-record.json"
            env = {key: value for key, value in os.environ.items() if key != "KSI_CUSTOMER_TOKEN"}
            env["KSI_CUSTOMER_TOKEN"] = operator_token
            completed = subprocess.run(
                [
                    sys.executable,
                    str(EXAMPLE),
                    "--core-origin",
                    servers.core_origin,
                    "--site-id",
                    fixture.site_id,
                    "--analysis-id",
                    analysis_id,
                    "--out",
                    str(out_path),
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=300,
            )
            assert completed.returncode == 0, completed.stderr
            record = json.loads(out_path.read_text(encoding="utf-8"))
            by_status = {check["id"]: check["status"] for check in record["checks"]}
            assert by_status["mcp-parity"] == "SKIPPED"
            assert record["mcpUsed"] is False
            assert record["lists"]["mcp"] is None
            assert record["lists"]["agree"] is None
    finally:
        fixture.close()


def _run_worker_once(fixture: Any, servers: _CoreAndObjectServers) -> None:
    runtime_facts = fixture.app.state.external_analysis_wiring.facade._assessments._runtime
    envelope = fixture.app.state.external_analysis_wiring.calculations._resource_envelope
    worker = ExternalAnalysisCoreClient(
        base_url=servers.core_origin,
        worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
        worker_instance_id="crosscheck-skip-worker",
    )
    try:
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
        assert run_once(worker, runtime, transport)
    finally:
        worker.close()
