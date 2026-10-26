"""Common-assembly proof for the opt-in Analysis HTTP graph."""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, Protocol
from urllib.parse import unquote

import pytest
from analysis_api_local_fixture import (
    _digest,
    _LocalObjectStorage,
    _RetainedEvidenceContextAuthority,
    _RetainedPolicyAuthority,
    _workflow,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry
from ksi_core.composition.external_graph import ExternalAnalysisLocalGraphConfig
from ksi_core.composition.platform_assembly import assemble_platform_app as assemble_app
from ksi_core.domains.external.ingress.external_evidence_validations import (
    AnalysisEvidenceFactSnapshot,
)
from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
    AnalysisRuntimeIdentityV2,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_result_workflow_assembly import ExternalResultWorkflowAssemblyConfig
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1
from ksi_event_contracts.external_relative_volume_analysis import AnalysisPolicyV2


def _policy() -> AnalysisPolicyV2:
    return AnalysisPolicyV2(
        policy_id="analysis-http-local-policy",
        version=1,
        profile_id="KSI-GIS-RELATIVE-VOLUME-V2",
        profile_digest=_digest("analysis-http-profile"),
        algorithm_digest=_digest("analysis-http-algorithm"),
        config_digest=_digest("analysis-http-config"),
        baseline_grid_rule="BASELINE_NATIVE_NORTH_UP_AFFINE_V1",
        current_elevation_resampling="BILINEAR",
        current_mask_resampling="NEAREST",
        work_area_rasterization="CELL_CENTER",
        minimum_common_valid_fraction=1.0,
        threshold_m=0.0,
        cell_area_rule="ABSOLUTE_AFFINE_DETERMINANT",
        delta_rule="CURRENT_MINUS_BASELINE",
        uncertainty_method="NONE_UNCERTAINTY_M3_NULL_V1",
    ).sealed()


def _local_graph_config(envelope: ResourceEnvelopeV1) -> ExternalAnalysisLocalGraphConfig:
    return ExternalAnalysisLocalGraphConfig(
        policy=_policy(),
        runtime=AnalysisRuntimeIdentityV2(
            worker_executable_digest=_digest("analysis-http-worker"),
            worker_build_digest=_digest("analysis-http-build"),
            runtime_image_version="local-analysis-http-v1",
            runtime_image_oci_digest=_digest("analysis-http-oci"),
            dependency_lock_digest=_digest("analysis-http-lock"),
        ),
        resource_envelope=envelope,
    )


class _EvidenceFixtureView(Protocol):
    app: FastAPI
    _retained_contexts: tuple[ExternalEvidenceMeasurementContextV1, ...]


def _terminal_facts_for_subject(
    fixture: _EvidenceFixtureView, subject: SealedExternalSubjectV1
) -> tuple[AnalysisEvidenceFactSnapshot, ...]:
    contexts = [item for item in fixture._retained_contexts if item.subject == subject]
    assert contexts
    context = contexts[0]
    return fixture.app.state.external_evidence_validation_store.analysis_facts_for_subject_dsm(
        subject=subject,
        target_dsm_artifact_id=context.target_dsm_artifact_id,
        target_dsm_observed_sha256=context.target_dsm_observed_sha256,
    )


def _assemble_local_analysis_app(
    path: Path,
    *,
    workflow: ExternalResultWorkflowAssemblyConfig,
    storage: _LocalObjectStorage,
    config: ExternalAnalysisLocalGraphConfig,
    auth_registry: AuthRegistry | None = None,
    analysis_activation: Any = None,
    delta_publications: Any = None,
    masked_quantitative: Any = None,
) -> tuple[FastAPI, list[DurableJournal]]:
    opened: list[DurableJournal] = []

    def journal(name: str) -> DurableJournal:
        item = DurableJournal(path / name)
        opened.append(item)
        return item

    # P3 Task 5: legacy managed assembly retired to the archive boundary —
    # the analysis lane is platform, so this harness boots the platform
    # profile (same external wiring, no mission key / edge snapshot).
    app = assemble_app(
        path,
        journal=journal,
        opened=opened,
        auth_registry=auth_registry or AuthRegistry([]),
        evidence_storage=storage,
        external_result_workflow=workflow,
        external_analysis_local_graph=config,
        analysis_activation=analysis_activation,
        delta_publications=delta_publications,
        masked_quantitative=masked_quantitative,
    )
    return app, opened


def _close(opened: list[DurableJournal]) -> None:
    for journal in reversed(opened):
        journal.close()


def test_common_assembly_constructs_and_replays_exact_opt_in_analysis_graph(tmp_path: Path) -> None:
    """Local config builds against the exact external participants and survives reopening."""
    now = datetime(2026, 9, 22, tzinfo=UTC)
    storage = _LocalObjectStorage()
    workflow, _catalog, envelope, _catalog_authority = _workflow(
        tmp_path,
        now=now,
        policy_authority=_RetainedPolicyAuthority(),
        context_authority=_RetainedEvidenceContextAuthority(now),
    )
    config = _local_graph_config(envelope)
    app, opened = _assemble_local_analysis_app(
        tmp_path, workflow=workflow, storage=storage, config=config
    )
    try:
        wiring = app.state.external_analysis_wiring
        assert wiring.facade._reconstructions is app.state.external_reconstruction_store
        assert wiring.facade._work_areas is app.state.work_area_store
        assert (
            wiring.facade._assessments.coordinator
            is app.state.external_reconstruction_store.coordinator
        )
        paths = app.openapi()["paths"]
        assert "/v1/sites/{site_id}/analysis-observations" in paths
        assert "/v1/sites/{site_id}/work-areas/{work_area_id}/analyses" in paths
        assert "/v1/internal/analysis-jobs" in paths
    finally:
        _close(opened)

    restarted_workflow, _catalog, restarted_envelope, _catalog_authority = _workflow(
        tmp_path,
        now=now,
        policy_authority=_RetainedPolicyAuthority(),
        context_authority=_RetainedEvidenceContextAuthority(now),
    )
    reopened, reopened_journals = _assemble_local_analysis_app(
        tmp_path,
        workflow=restarted_workflow,
        storage=storage,
        config=_local_graph_config(restarted_envelope),
    )
    try:
        wiring = reopened.state.external_analysis_wiring
        assert wiring.intents.list_for_organization(organization_id="org-a") == ()
        assert wiring.facade._calculations._assessments is wiring.facade._assessments
    finally:
        _close(reopened_journals)


def test_reusable_local_fixture_serves_real_scoped_selectors_and_queues_over_http(
    tmp_path: Path,
) -> None:
    """The browser/worker fixture is a real common Core app with sealed GeoTIFF inputs."""
    from analysis_api_local_fixture import build_local_analysis_api_fixture

    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        client = TestClient(fixture.app)
        options = client.get(
            f"/v1/sites/{fixture.site_id}/analysis-observations",
            headers=fixture.operator_headers(),
        )
        assert options.status_code == 200, options.text
        option_selectors = {tuple(item["selector"].items()) for item in options.json()["items"]}
        body = {
            "baseline": fixture.baseline.model_dump(by_alias=True),
            "current": fixture.current.model_dump(by_alias=True),
        }
        assert tuple(body["baseline"].items()) in option_selectors
        assert tuple(body["current"].items()) in option_selectors
        created = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": "local-fixture-analysis"},
            json=body,
        )
        assert created.status_code == 202, created.text
        assert created.json()["executionState"] == "QUEUED"
        assert created.json()["result"] is None
        analysis_id = created.json()["analysisId"]
        alias_created = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": "local-fixture-alias"},
            json=body,
        )
        assert alias_created.status_code == 202, alias_created.text
        alias_id = alias_created.json()["analysisId"]
        assert alias_id != analysis_id
        assert (
            alias_created.json()["authority"]["calculationRequestId"]
            == created.json()["authority"]["calculationRequestId"]
        )

        evidence = client.get(
            f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
            headers=fixture.operator_headers(),
        )
        assert evidence.status_code == 200, evidence.text
        evidence_body = evidence.json()
        assert evidence_body["calculation"]["workAreaDefinitionDigest"].startswith("sha256:")
        assert evidence_body["calculation"]["policy"]["profileId"] == "KSI-GIS-RELATIVE-VOLUME-V2"
        assert evidence_body["calculation"]["runtime"]["workerExecutableDigest"].startswith(
            "sha256:"
        )
        assert {item["outcome"] for item in evidence_body["evaluations"]} == {"PASS"}
        assert {item["epoch"] for item in evidence_body["evaluations"]} == {
            "BASELINE",
            "CURRENT",
        }
        assert all(
            item["evaluationDigest"].startswith("sha256:") for item in evidence_body["evaluations"]
        )
        assert all(
            fact["contextDigest"].startswith("sha256:")
            and fact["evidenceRecordDigest"].startswith("sha256:")
            and fact["href"].endswith(f"/analyses/{analysis_id}/evidence")
            for item in evidence_body["evaluations"]
            for fact in item["evidenceFacts"]
        )
        assert all(
            epoch["inspectionReportRef"]["href"].endswith(f"/analyses/{analysis_id}/evidence")
            for epoch in (evidence_body["baseline"], evidence_body["current"])
        )

        pending = client.get("/v1/internal/analysis-jobs", headers=fixture.worker_headers())
        assert pending.status_code == 200, pending.text
        assert [item["analysisId"] for item in pending.json()["items"]] == [analysis_id]
        leased = client.post(
            f"/v1/internal/analysis-jobs/{alias_id}:lease",
            headers=fixture.worker_headers(),
            json={
                "workerInstanceId": "fixture-worker-1",
                "leaseAcquisitionId": "fixture-lease-1",
            },
        )
        assert leased.status_code == 200, leased.text
        attempt = leased.json()["attempt"]
        fixture.set_loopback_object_origin("http://127.0.0.1:8123")
        inputs = client.get(
            f"/v1/internal/analysis-jobs/{alias_id}/input",
            headers={
                **fixture.worker_headers(),
                "X-Analysis-Attempt-Digest": attempt["executionAttemptDigest"],
                "X-Analysis-Worker-Instance-Id": attempt["workerInstanceId"],
            },
        )
        assert inputs.status_code == 200, inputs.text
        capabilities = inputs.json()["input"]["inputs"]
        assert [item["role"] for item in capabilities] == ["BASELINE_DSM", "CURRENT_DSM"]
        assert all(
            item["downloadUrl"].startswith("http://127.0.0.1:8123/objects/")
            for item in capabilities
        )
        assert all(item["observedSizeBytes"] > 0 for item in capabilities)
        renewed = client.post(
            f"/v1/internal/analysis-jobs/{alias_id}:renew",
            headers=fixture.worker_headers(),
            json={"attempt": attempt},
        )
        assert renewed.status_code == 200, renewed.text
        assert (
            renewed.json()["calculationRequestId"]
            == created.json()["authority"]["calculationRequestId"]
        )
    finally:
        fixture.close()


def test_v2_routes_project_history_and_require_activation_for_new_create(tmp_path: Path) -> None:
    """V2 reads survive without execution authority, while create needs current activation."""
    from analysis_api_local_fixture import build_local_analysis_api_fixture

    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        client = TestClient(fixture.app)
        request = {
            "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
            "current": fixture.current.model_dump(by_alias=True, mode="json"),
        }
        created = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": "v2-history"},
            json=request,
        )
        assert created.status_code == 202, created.text
        analysis_id = created.json()["analysisId"]

        detail = client.get(
            f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}",
            headers=fixture.operator_headers(),
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["analysisId"] == analysis_id
        assert detail.json()["executionState"] == "QUEUED"
        assert "selectedMaskB64" not in detail.text

        listing = client.get(
            f"/v2/sites/{fixture.site_id}/analyses", headers=fixture.operator_headers()
        )
        assert listing.status_code == 200, listing.text
        assert [item["analysisId"] for item in listing.json()["items"]] == [analysis_id]

        evidence = client.get(
            f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
            headers=fixture.operator_headers(),
        )
        assert evidence.status_code == 200, evidence.text
        assert {item["kind"] for item in evidence.json()["items"]} >= {
            "EPOCH_IDENTITY",
            "CALCULATION_IDENTITY",
            "EVALUATION",
            "CHECKPOINT_FACT",
        }
        assert all("href" not in item or item["href"] is None for item in evidence.json()["items"])
        alias = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": "v2-history-alias"},
            json=request,
        )
        assert alias.status_code == 202
        first_page = client.get(
            f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/evidence?limit=1",
            headers=fixture.operator_headers(),
        )
        assert first_page.status_code == 200
        assert first_page.json()["nextCursor"] is not None
        cross_analysis_cursor = client.get(
            f"/v2/sites/{fixture.site_id}/analyses/{alias.json()['analysisId']}/evidence",
            params={"limit": 1, "cursor": first_page.json()["nextCursor"]},
            headers=fixture.operator_headers(),
        )
        assert cross_analysis_cursor.status_code == 409
        malformed_cursor = client.get(
            f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
            params={"limit": 1, "cursor": "not-a-valid-cursor"},
            headers=fixture.operator_headers(),
        )
        assert malformed_cursor.status_code == 400
        wrong_type_evidence_cursor = (
            base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "analysisId": analysis_id,
                        "evidenceRevision": "1",
                        "evidenceDigest": "sha256:" + "0" * 64,
                        "offset": 1,
                    }
                ).encode()
            )
            .decode()
            .rstrip("=")
        )
        malformed_evidence = client.get(
            f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
            params={"limit": 1, "cursor": wrong_type_evidence_cursor},
            headers=fixture.operator_headers(),
        )
        assert malformed_evidence.status_code == 400
        assert malformed_evidence.json()["detail"] == "ANALYSIS_EVIDENCE_CURSOR_INVALID"

        new_create = client.post(
            f"/v2/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": "v2-no-activation"},
            json=request,
        )
        assert new_create.status_code == 503
        assert new_create.json()["detail"] == "ANALYSIS_ACTIVATION_UNAVAILABLE"
    finally:
        fixture.close()


def test_v2_current_rejected_checkpoint_requires_remediation_and_survives_retry_replay(
    tmp_path: Path,
) -> None:
    """A terminal failed current-DSM evaluation suppresses numeric work and stays durable."""
    from analysis_api_local_fixture import build_local_analysis_api_fixture

    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        failed_checkpoint_current=True,
    )
    try:
        client = TestClient(fixture.app)
        url = f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses"
        request = {
            "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
            "current": fixture.current.model_dump(by_alias=True, mode="json"),
        }
        headers = {
            **fixture.operator_headers(),
            "Idempotency-Key": "failed-current-checkpoint-analysis",
        }
        created = client.post(url, headers=headers, json=request)
        assert created.status_code == 202, created.text
        analysis_id = created.json()["analysisId"]
        assert created.json()["executionState"] == "NOT_STARTED"
        assert created.json()["suitabilityState"] == "REMEDIATION_REQUIRED"
        assert created.json()["result"] is None
        assert {item["code"] for item in created.json()["blockers"]} == {
            "CHECKPOINT_EVIDENCE_ABSENT",
            "CHECKPOINT_COUNT_OUT_OF_RANGE",
        }

        retry = client.post(url, headers=headers, json=request)
        assert retry.status_code == 202
        assert retry.json()["analysisId"] == analysis_id
        assert retry.json() == created.json()
        detail = client.get(
            f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}",
            headers=fixture.operator_headers(),
        )
        result = client.get(
            f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/result",
            headers=fixture.operator_headers(),
        )
        evidence = client.get(
            f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
            headers=fixture.operator_headers(),
        )
        assert detail.status_code == result.status_code == evidence.status_code == 200
        assert detail.json()["executionState"] == result.json()["executionState"] == "NOT_STARTED"
        assert (
            detail.json()["suitabilityState"]
            == result.json()["suitabilityState"]
            == ("REMEDIATION_REQUIRED")
        )
        assert detail.json()["result"] is result.json()["result"] is None
        assert evidence.json()["result"] is None
        current_evaluation = next(
            item for item in evidence.json()["evaluations"] if item["epoch"] == "CURRENT"
        )
        baseline_evaluation = next(
            item for item in evidence.json()["evaluations"] if item["epoch"] == "BASELINE"
        )
        assert current_evaluation["outcome"] == "FAIL"
        assert current_evaluation["reasonCodes"] == ["CHECKPOINT_COUNT_OUT_OF_RANGE"]
        assert baseline_evaluation["outcome"] == "UNASSESSED"
        assert baseline_evaluation["reasonCodes"] == ["CHECKPOINT_EVIDENCE_ABSENT"]

        pending = client.get("/v1/internal/analysis-jobs", headers=fixture.worker_headers())
        assert pending.status_code == 200
        assert pending.json()["items"] == []
        claim = client.post(
            f"/v1/internal/analysis-jobs/{analysis_id}:lease",
            headers=fixture.worker_headers(),
            json={
                "workerInstanceId": "rejected-checkpoint-worker",
                "leaseAcquisitionId": "rejected-checkpoint-lease",
            },
        )
        assert claim.status_code == 404
    finally:
        fixture.close()

    replay = build_local_analysis_api_fixture(tmp_path, replay_of=fixture)
    try:
        replay_client = TestClient(replay.app)
        replay_headers = {
            **replay.operator_headers(),
            "Idempotency-Key": "failed-current-checkpoint-analysis",
        }
        replayed = replay_client.post(url, headers=replay_headers, json=request)
        assert replayed.status_code == 202, replayed.text
        assert replayed.json()["analysisId"] == analysis_id
        assert replayed.json()["executionState"] == "NOT_STARTED"
        assert replayed.json()["suitabilityState"] == "REMEDIATION_REQUIRED"
        assert replayed.json()["result"] is None
        replayed_detail = replay_client.get(
            f"/v1/sites/{replay.site_id}/analyses/{analysis_id}",
            headers=replay.operator_headers(),
        )
        replayed_result = replay_client.get(
            f"/v1/sites/{replay.site_id}/analyses/{analysis_id}/result",
            headers=replay.operator_headers(),
        )
        replayed_evidence = replay_client.get(
            f"/v1/sites/{replay.site_id}/analyses/{analysis_id}/evidence",
            headers=replay.operator_headers(),
        )
        assert replayed_detail.status_code == replayed_result.status_code == 200
        assert replayed_evidence.status_code == 200
        assert replayed_detail.json()["result"] is replayed_result.json()["result"] is None
        assert replayed_evidence.json()["result"] is None
        assert replayed_detail.json()["blockers"] == created.json()["blockers"]
        replayed_current_evaluation = next(
            item for item in replayed_evidence.json()["evaluations"] if item["epoch"] == "CURRENT"
        )
        assert (
            replayed_current_evaluation["evaluationDigest"]
            == current_evaluation["evaluationDigest"]
        )
        replayed_pending = replay_client.get(
            "/v1/internal/analysis-jobs", headers=replay.worker_headers()
        )
        assert replayed_pending.status_code == 200
        assert replayed_pending.json()["items"] == []
        replayed_claim = replay_client.post(
            f"/v1/internal/analysis-jobs/{analysis_id}:lease",
            headers=replay.worker_headers(),
            json={
                "workerInstanceId": "replayed-rejected-checkpoint-worker",
                "leaseAcquisitionId": "replayed-rejected-checkpoint-lease",
            },
        )
        assert replayed_claim.status_code == 404
    finally:
        replay.close()


def test_v2_baseline_rejected_checkpoint_requires_remediation_and_survives_retry_replay(
    tmp_path: Path,
) -> None:
    """A failed evaluation of the baseline DSM also blocks numeric work durably."""
    from analysis_api_local_fixture import build_local_analysis_api_fixture

    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        failed_checkpoint_baseline=True,
    )
    try:
        client = TestClient(fixture.app)
        url = f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses"
        request = {
            "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
            "current": fixture.current.model_dump(by_alias=True, mode="json"),
        }
        headers = {
            **fixture.operator_headers(),
            "Idempotency-Key": "failed-baseline-checkpoint-analysis",
        }
        created = client.post(url, headers=headers, json=request)
        assert created.status_code == 202, created.text
        analysis_id = created.json()["analysisId"]
        assert created.json()["executionState"] == "NOT_STARTED"
        assert created.json()["suitabilityState"] == "REMEDIATION_REQUIRED"
        assert created.json()["result"] is None
        assert "CHECKPOINT_COUNT_OUT_OF_RANGE" in {
            item["code"] for item in created.json()["blockers"]
        }
        retry = client.post(url, headers=headers, json=request)
        assert retry.status_code == 202
        assert retry.json() == created.json()
        evidence = client.get(
            f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
            headers=fixture.operator_headers(),
        )
        assert evidence.status_code == 200
        baseline = next(
            item for item in evidence.json()["evaluations"] if item["epoch"] == "BASELINE"
        )
        current = next(
            item for item in evidence.json()["evaluations"] if item["epoch"] == "CURRENT"
        )
        assert baseline["outcome"] == "FAIL"
        assert baseline["reasonCodes"] == ["CHECKPOINT_COUNT_OUT_OF_RANGE"]
        assert current["outcome"] == "UNASSESSED"
        assert baseline["evaluationDigest"].startswith("sha256:")
        assert len(baseline["evidenceFacts"]) == 1
        baseline_terminal_records = _terminal_facts_for_subject(fixture, fixture._baseline_subject)
        assert len(baseline_terminal_records) == 1
        baseline_assessed_at = datetime.fromisoformat(baseline["assessedAt"].replace("Z", "+00:00"))
        assert baseline_terminal_records[0].terminal_record.core_recorded_at <= baseline_assessed_at
        result = client.get(
            f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/result",
            headers=fixture.operator_headers(),
        )
        assert result.status_code == 200
        assert result.json()["result"] is None

        pending = client.get("/v1/internal/analysis-jobs", headers=fixture.worker_headers())
        assert pending.status_code == 200
        assert pending.json()["items"] == []
        claim = client.post(
            f"/v1/internal/analysis-jobs/{analysis_id}:lease",
            headers=fixture.worker_headers(),
            json={
                "workerInstanceId": "rejected-baseline-checkpoint-worker",
                "leaseAcquisitionId": "rejected-baseline-checkpoint-lease",
            },
        )
        assert claim.status_code == 404
    finally:
        fixture.close()

    replay = build_local_analysis_api_fixture(tmp_path, replay_of=fixture)
    try:
        replay_client = TestClient(replay.app)
        replayed = replay_client.post(
            url,
            headers={
                **replay.operator_headers(),
                "Idempotency-Key": "failed-baseline-checkpoint-analysis",
            },
            json=request,
        )
        assert replayed.status_code == 202, replayed.text
        assert replayed.json()["analysisId"] == analysis_id
        assert replayed.json()["executionState"] == "NOT_STARTED"
        assert replayed.json()["suitabilityState"] == "REMEDIATION_REQUIRED"
        assert replayed.json()["result"] is None
        assert "CHECKPOINT_COUNT_OUT_OF_RANGE" in {
            item["code"] for item in replayed.json()["blockers"]
        }
        evidence = replay_client.get(
            f"/v1/sites/{replay.site_id}/analyses/{analysis_id}/evidence",
            headers=replay.operator_headers(),
        )
        assert evidence.status_code == 200
        failed = [item for item in evidence.json()["evaluations"] if item["outcome"] == "FAIL"]
        assert len(failed) == 1
        assert failed[0]["epoch"] == "BASELINE"
        assert failed[0]["evaluationDigest"] == baseline["evaluationDigest"]
        assert failed[0]["evidenceFacts"] == baseline["evidenceFacts"]
        result = replay_client.get(
            f"/v1/sites/{replay.site_id}/analyses/{analysis_id}/result",
            headers=replay.operator_headers(),
        )
        assert result.status_code == 200
        assert result.json()["result"] is None
        pending = replay_client.get("/v1/internal/analysis-jobs", headers=replay.worker_headers())
        assert pending.status_code == 200
        assert pending.json()["items"] == []
    finally:
        replay.close()


def test_v2_failed_checkpoint_wins_over_pass_for_same_exact_dsm(tmp_path: Path) -> None:
    """A PASS cannot override a Core REJECTED evaluation of identical DSM bytes."""
    from analysis_api_local_fixture import build_local_analysis_api_fixture

    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        passed_and_failed_checkpoint_current=True,
    )
    try:
        client = TestClient(fixture.app)
        created = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={
                **fixture.operator_headers(),
                "Idempotency-Key": "conflicting-current-checkpoint-analysis",
            },
            json={
                "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
                "current": fixture.current.model_dump(by_alias=True, mode="json"),
            },
        )
        assert created.status_code == 202, created.text
        analysis_id = created.json()["analysisId"]
        assert created.json()["executionState"] == "NOT_STARTED"
        assert created.json()["suitabilityState"] == "REMEDIATION_REQUIRED"
        assert created.json()["result"] is None
        assert "CHECKPOINT_COUNT_OUT_OF_RANGE" in {
            item["code"] for item in created.json()["blockers"]
        }
        evidence = client.get(
            f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
            headers=fixture.operator_headers(),
        )
        assert evidence.status_code == 200
        current_facts = [
            item for item in evidence.json()["evaluations"] if item["epoch"] == "CURRENT"
        ]
        assert len(current_facts) == 1
        assert current_facts[0]["outcome"] == "FAIL"
        assert current_facts[0]["reasonCodes"] == ["CHECKPOINT_COUNT_OUT_OF_RANGE"]
        retained = current_facts[0]["evidenceFacts"]
        assert len(retained) == 2
        assert {fact["coreVerdict"] for fact in retained} == {"VALIDATED", "REJECTED"}
        assert len({fact["evidenceRecordDigest"] for fact in retained}) == 2
        terminal_facts = _terminal_facts_for_subject(fixture, fixture._current_subject)
        assert len(terminal_facts) == 2
        assert {item.terminal_record.evidence_record_digest for item in terminal_facts} == {
            fact["evidenceRecordDigest"] for fact in retained
        }
        assessed_at = datetime.fromisoformat(current_facts[0]["assessedAt"].replace("Z", "+00:00"))
        assert all(item.terminal_record.core_recorded_at <= assessed_at for item in terminal_facts)
        retry = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={
                **fixture.operator_headers(),
                "Idempotency-Key": "conflicting-current-checkpoint-analysis",
            },
            json={
                "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
                "current": fixture.current.model_dump(by_alias=True, mode="json"),
            },
        )
        assert retry.status_code == 202
        assert retry.json() == created.json()
        pending = client.get("/v1/internal/analysis-jobs", headers=fixture.worker_headers())
        assert pending.status_code == 200
        assert pending.json()["items"] == []
    finally:
        fixture.close()

    replay = build_local_analysis_api_fixture(tmp_path, replay_of=fixture)
    try:
        replay_client = TestClient(replay.app)
        replayed = replay_client.post(
            f"/v1/sites/{replay.site_id}/work-areas/{replay.work_area_id}/analyses",
            headers={
                **replay.operator_headers(),
                "Idempotency-Key": "conflicting-current-checkpoint-analysis",
            },
            json={
                "baseline": replay.baseline.model_dump(by_alias=True, mode="json"),
                "current": replay.current.model_dump(by_alias=True, mode="json"),
            },
        )
        assert replayed.status_code == 202, replayed.text
        assert replayed.json()["analysisId"] == analysis_id
        assert replayed.json()["executionState"] == "NOT_STARTED"
        assert replayed.json()["suitabilityState"] == "REMEDIATION_REQUIRED"
        assert replayed.json()["result"] is None
        replayed_evidence = replay_client.get(
            f"/v1/sites/{replay.site_id}/analyses/{analysis_id}/evidence",
            headers=replay.operator_headers(),
        )
        assert replayed_evidence.status_code == 200
        replayed_current = next(
            item for item in replayed_evidence.json()["evaluations"] if item["epoch"] == "CURRENT"
        )
        assert replayed_current["evaluationDigest"] == current_facts[0]["evaluationDigest"]
        assert replayed_current["evidenceFacts"] == retained
        pending = replay_client.get("/v1/internal/analysis-jobs", headers=replay.worker_headers())
        assert pending.status_code == 200
        assert pending.json()["items"] == []
    finally:
        replay.close()


def test_failed_checkpoint_fixture_rejects_v1_combination(tmp_path: Path) -> None:
    from analysis_api_local_fixture import build_local_analysis_api_fixture

    with pytest.raises(ValueError, match="V2 DSM-only fixture"):
        build_local_analysis_api_fixture(
            tmp_path,
            v2_dsm_only=False,
            failed_checkpoint_current=True,
        )


def test_unfinished_alias_fails_closed_after_newer_inequivalent_ap_admission(
    tmp_path: Path,
) -> None:
    """A later failed AP alias cannot reauthorize the shared unfinished NX job."""
    from analysis_api_local_fixture import build_local_analysis_api_fixture

    fixture = build_local_analysis_api_fixture(tmp_path)
    try:
        client = TestClient(fixture.app)
        url = f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses"
        body = {
            "baseline": fixture.baseline.model_dump(by_alias=True),
            "current": fixture.current.model_dump(by_alias=True),
        }
        created = client.post(
            url,
            headers={**fixture.operator_headers(), "Idempotency-Key": "stale-alias-a"},
            json=body,
        )
        alias = client.post(
            url,
            headers={**fixture.operator_headers(), "Idempotency-Key": "stale-alias-b"},
            json=body,
        )
        assert created.status_code == alias.status_code == 202
        analysis_id = created.json()["analysisId"]
        alias_id = alias.json()["analysisId"]
        assert alias_id != analysis_id
        assert (
            alias.json()["authority"]["calculationRequestId"]
            == created.json()["authority"]["calculationRequestId"]
        )

        leased = client.post(
            f"/v1/internal/analysis-jobs/{alias_id}:lease",
            headers=fixture.worker_headers(),
            json={
                "workerInstanceId": "stale-alias-worker",
                "leaseAcquisitionId": "stale-alias-lease",
            },
        )
        assert leased.status_code == 200, leased.text
        attempt = leased.json()["attempt"]
        wiring = fixture.app.state.external_analysis_wiring
        first_assessment = wiring.assessments.get_history(analysis_id, organization_id="org-a")
        assert first_assessment is not None
        identity_digest = first_assessment.admission.calculation_identity_digest
        assert identity_digest is not None
        assert (
            wiring.assessments.prepare_execution_witness(
                calculation_identity_digest=identity_digest,
                organization_id="org-b",
                now=datetime.now(UTC),
                expected_admission=first_assessment.admission,
            )
            is None
        )
        forged_admission = first_assessment.admission.model_copy(
            update={"admission_id": "admission-forged", "admission_digest": None}
        ).sealed()
        assert (
            wiring.assessments.prepare_execution_witness(
                calculation_identity_digest=identity_digest,
                organization_id="org-a",
                now=datetime.now(UTC),
                expected_admission=forged_admission,
            )
            is None
        )
        context_digest = (
            first_assessment.admission.evaluation_revisions[0]
            .evidence_facts[0]
            .context.context_digest
        )
        assert context_digest is not None

        fixture.revoke_evidence_context(context_digest)
        changed = client.post(
            url,
            headers={**fixture.operator_headers(), "Idempotency-Key": "stale-alias-c"},
            json=body,
        )
        assert changed.status_code == 202, changed.text
        changed_id = changed.json()["analysisId"]
        changed_assessment = wiring.assessments.get_history(changed_id, organization_id="org-a")
        assert changed_assessment is not None
        assert (
            changed_assessment.admission.calculation_identity_digest
            == first_assessment.admission.calculation_identity_digest
        )
        assert changed_assessment.admission != first_assessment.admission

        stale_renew = client.post(
            f"/v1/internal/analysis-jobs/{alias_id}:renew",
            headers=fixture.worker_headers(),
            json={"attempt": attempt},
        )
        assert stale_renew.status_code == 409
        pending = client.get("/v1/internal/analysis-jobs", headers=fixture.worker_headers())
        assert pending.status_code == 200
        assert pending.json()["items"] == []

        # Reverting the mutable authority alone cannot make the older A/B
        # admission current again: C's retained inequivalent AP record stays
        # the newest identity witness until a fresh assessment is recorded.
        fixture.restore_evidence_context(context_digest)
        assert (
            client.post(
                f"/v1/internal/analysis-jobs/{alias_id}:renew",
                headers=fixture.worker_headers(),
                json={"attempt": attempt},
            ).status_code
            == 409
        )
        restored_pending = client.get(
            "/v1/internal/analysis-jobs", headers=fixture.worker_headers()
        )
        assert restored_pending.status_code == 200
        assert restored_pending.json()["items"] == []
        detail = client.get(
            f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}",
            headers=fixture.operator_headers(),
        )
        assert detail.status_code == 200
        assert detail.json()["executionState"] == "RUNNING"
        assert detail.json()["suitabilityState"] == "REASSESSMENT_REQUIRED"
        assert detail.json()["result"] is None

        restored = client.post(
            url,
            headers={**fixture.operator_headers(), "Idempotency-Key": "stale-alias-d"},
            json=body,
        )
        assert restored.status_code == 202, restored.text
        assert (
            restored.json()["authority"]["calculationRequestId"]
            == created.json()["authority"]["calculationRequestId"]
        )
        assert (
            client.post(
                f"/v1/internal/analysis-jobs/{alias_id}:renew",
                headers=fixture.worker_headers(),
                json={"attempt": attempt},
            ).status_code
            == 200
        )
    finally:
        fixture.close()


def test_same_key_relinks_persisted_nx_after_link_crash_and_core_journal_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A POST retry repairs only its missing durable AP→NX link after a crash."""
    from analysis_api_local_fixture import build_local_analysis_api_fixture

    fixture = build_local_analysis_api_fixture(tmp_path)
    reopened_fixture = None
    try:
        body = {
            "baseline": fixture.baseline.model_dump(by_alias=True),
            "current": fixture.current.model_dump(by_alias=True),
        }
        url = f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses"
        idempotency_key = "link-crash-recovery"
        wiring = fixture.app.state.external_analysis_wiring

        def crash_after_nx_issue(**_kwargs: object) -> object:
            raise RuntimeError("simulated crash after NX issue before intent link")

        monkeypatch.setattr(wiring.intents, "link_calculation", crash_after_nx_issue)
        crashing_client = TestClient(fixture.app, raise_server_exceptions=False)
        crashed = crashing_client.post(
            url,
            headers={**fixture.operator_headers(), "Idempotency-Key": idempotency_key},
            json=body,
        )
        assert crashed.status_code == 500

        (intent,) = wiring.intents.list_for_organization(organization_id="org-a")
        assert intent.calculation_request_id is None
        calculation = wiring.calculations.get_history(intent.analysis_id, organization_id="org-a")
        assert calculation is not None
        assert calculation.calculation_identity_digest == (
            wiring.assessments.get_history(
                intent.analysis_id, organization_id="org-a"
            ).admission.calculation_identity_digest
        )

        # Polling retains the durable projection but never appends the missing
        # link.  Only the matching POST retry is the recovery action.
        intent_journal = tmp_path / "external-analysis-intents.jsonl"
        before_get = intent_journal.read_bytes()
        detail = crashing_client.get(
            f"/v1/sites/{fixture.site_id}/analyses/{intent.analysis_id}",
            headers=fixture.operator_headers(),
        )
        assert detail.status_code == 200
        assert intent_journal.read_bytes() == before_get

        # Reconstruct the actual Core journals before retrying the same public
        # request.  The NX issued event and AP assessment are retained.
        fixture.close()
        reopened_fixture = build_local_analysis_api_fixture(tmp_path, replay_of=fixture)
        reopened_client = TestClient(reopened_fixture.app)
        recovered = reopened_client.post(
            url,
            headers={
                **reopened_fixture.operator_headers(),
                "Idempotency-Key": idempotency_key,
            },
            json=body,
        )
        assert recovered.status_code == 202, recovered.text
        assert recovered.json()["analysisId"] == intent.analysis_id
        assert recovered.json()["authority"]["calculationRequestId"] == calculation.request_id

        recovered_wiring = reopened_fixture.app.state.external_analysis_wiring
        linked = recovered_wiring.intents.get(intent.analysis_id, organization_id="org-a")
        assert linked is not None
        assert linked.calculation_request_id == calculation.request_id
        assert (
            sum(
                1
                for raw in recovered_wiring.assessments._journal.replay()  # noqa: SLF001
                if raw["kind"] == "external-relative-volume-analysis-assessed"
            )
            == 1
        )
        assert (
            sum(
                1
                for raw in recovered_wiring.calculations._journal.replay()  # noqa: SLF001
                if raw["kind"] == "external-relative-volume-calculation-issued"
            )
            == 1
        )

        pending = reopened_client.get(
            "/v1/internal/analysis-jobs", headers=reopened_fixture.worker_headers()
        )
        assert pending.status_code == 200, pending.text
        assert [item["analysisId"] for item in pending.json()["items"]] == [intent.analysis_id]
        leased = reopened_client.post(
            f"/v1/internal/analysis-jobs/{intent.analysis_id}:lease",
            headers=reopened_fixture.worker_headers(),
            json={
                "workerInstanceId": "link-recovery-worker",
                "leaseAcquisitionId": "link-recovery-lease",
            },
        )
        assert leased.status_code == 200, leased.text
        assert leased.json()["calculationRequestId"] == calculation.request_id
    finally:
        if reopened_fixture is not None:
            reopened_fixture.close()
        else:
            fixture.close()


@pytest.mark.parametrize(
    ("v2_dsm_only", "late_failure", "real_inspection", "passed_checkpoint_epochs"),
    [
        (False, False, False, ()),
        (True, False, False, ()),
        (True, True, False, ()),
        (True, False, True, ()),
        (True, False, False, ("BASELINE", "CURRENT")),
        (True, False, False, ("BASELINE",)),
    ],
    ids=[
        "v1-ortho-dsm",
        "v2-dsm-only-provisional",
        "v2-dsm-only-late-failure",
        "v2-dsm-only-real-inspection",
        "v2-dsm-only-evaluated",
        "v2-dsm-only-one-epoch-passed",
    ],
)
def test_combined_frozen_worker_completes_real_core_http_loop_over_loopback_objects(
    tmp_path: Path,
    v2_dsm_only: bool,
    late_failure: bool,
    real_inspection: bool,
    passed_checkpoint_epochs: tuple[str, ...],
) -> None:
    """Real Core/worker HTTP and GeoTIFF path for V1 and DSM-only V2 observations."""
    import httpx
    import uvicorn
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

    activation_factory = None
    if real_inspection:
        from test_external_analysis_activation import _write_activation

        def _active_activation(config: Any, worker: Any) -> Any:
            _activation_dir = tmp_path / "active-analysis-activation"
            return _write_activation(
                _activation_dir,
                bindings={
                    "organization_id": "org-a",
                    "policy": config.policy,
                    "runtime": config.runtime,
                    "resource_envelope": config.resource_envelope,
                    "worker_principal": worker,
                },
                activation_fields={
                    "issuedAt": (datetime.now(UTC) - timedelta(minutes=1))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "validUntil": (datetime.now(UTC) + timedelta(hours=1))
                    .isoformat()
                    .replace("+00:00", "Z"),
                },
            )[2]

        activation_factory = _active_activation

    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=v2_dsm_only,
        real_inspection=real_inspection,
        passed_checkpoint_epochs=passed_checkpoint_epochs,
        analysis_activation=activation_factory,
    )
    object_server: ThreadingHTTPServer | None = None
    object_thread: Thread | None = None
    core_server: uvicorn.Server | None = None
    core_thread: Thread | None = None
    core_socket: socket.socket | None = None
    worker_client: ExternalAnalysisCoreClient | None = None
    restarted_client: ExternalAnalysisCoreClient | None = None
    reopened_fixture = None
    fixture_closed = False
    try:

        class LoopbackObjectHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if not self.path.startswith("/objects/"):
                    self.send_error(404)
                    return
                try:
                    payload = fixture.storage.object_bytes(
                        unquote(self.path.removeprefix("/objects/"))
                    )
                except KeyError:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/tiff")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        object_server = ThreadingHTTPServer(("127.0.0.1", 0), LoopbackObjectHandler)
        object_thread = Thread(target=object_server.serve_forever, daemon=True)
        object_thread.start()
        object_origin = f"http://127.0.0.1:{object_server.server_port}"
        fixture.set_loopback_object_origin(object_origin)

        listen_socket = socket.socket()
        core_socket = listen_socket
        listen_socket.bind(("127.0.0.1", 0))
        listen_socket.listen(128)
        core_origin = f"http://127.0.0.1:{listen_socket.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(fixture.app, log_level="warning", access_log=False))
        core_server = server
        core_thread = Thread(target=lambda: server.run(sockets=[listen_socket]), daemon=True)
        core_thread.start()
        for _ in range(100):
            if core_server.started:
                break
            assert core_thread.is_alive(), "local Core server stopped during startup"
            time.sleep(0.02)
        assert core_server.started

        if real_inspection:
            from test_external_analysis_real_inspection_integration import (
                inspect_fixture_epochs_with_real_parser,
            )

            inspection_root = tmp_path / "real-inspector-private"
            inspection_root.mkdir(mode=0o700)
            measured_reports = inspect_fixture_epochs_with_real_parser(
                fixture, root=inspection_root
            )
            assert len(measured_reports) == 2
            assert measured_reports == fixture.synthetic_inspection_report_digests

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
            endpoints=(TrustedObjectEndpointV1(origin=object_origin, addresses=("127.0.0.1",)),),
            max_header_bytes=16_384,
            max_object_bytes=envelope.max_input_bytes,
            max_chunk_bytes=min(65_536, envelope.max_input_bytes),
        )
        body = {
            "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
            "current": fixture.current.model_dump(by_alias=True, mode="json"),
        }
        with httpx.Client(base_url=core_origin, trust_env=False) as operator:
            options = operator.get(
                f"/v1/sites/{fixture.site_id}/analysis-observations",
                headers=fixture.operator_headers(),
            )
            assert options.status_code == 200, options.text
            offered = {tuple(item["selector"].items()) for item in options.json()["items"]}
            assert tuple(body["baseline"].items()) in offered
            assert tuple(body["current"].items()) in offered
            if v2_dsm_only:
                for selector in (fixture.baseline, fixture.current):
                    submission_path = (
                        f"/v1/observation-work-orders/{selector.work_order_id}/"
                        f"external-reconstruction-submissions/{selector.submission_ref}"
                        f"/revisions/{selector.revision}"
                    )
                    sealed = operator.get(submission_path, headers=fixture.operator_headers())
                    assert sealed.status_code == 200, sealed.text
                    assert sealed.json()["submission"]["contractVersion"] == (
                        "external-reconstruction-submission.v2"
                    )
                    assert [
                        artifact["kind"] for artifact in sealed.json()["submission"]["artifacts"]
                    ] == ["dsm"]
                    assert [entry["kind"] for entry in sealed.json()["manifest"]["entries"]] == [
                        "dsm"
                    ]
            created = operator.post(
                f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
                headers={**fixture.operator_headers(), "Idempotency-Key": "combined-real-loop"},
                json=body,
            )
            assert created.status_code == 202, created.text
            analysis_id = created.json()["analysisId"]
            alias_created = operator.post(
                f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
                headers={**fixture.operator_headers(), "Idempotency-Key": "combined-real-alias"},
                json=body,
            )
            assert alias_created.status_code == 202, alias_created.text
            alias_id = alias_created.json()["analysisId"]
            assert alias_id != analysis_id
            assert (
                alias_created.json()["authority"]["calculationRequestId"]
                == created.json()["authority"]["calculationRequestId"]
            )
            worker_client = ExternalAnalysisCoreClient(
                base_url=core_origin,
                worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
                worker_instance_id="combined-local-worker",
            )
            assert run_once(worker_client, runtime, transport)
            detail_url = f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}"
            for _ in range(20):
                detail = operator.get(detail_url, headers=fixture.operator_headers())
                if detail.status_code == 200 and detail.json()["executionState"] == "COMPLETED":
                    break
                time.sleep(0.01)
            result = operator.get(
                f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/result",
                headers=fixture.operator_headers(),
            )
            evidence = operator.get(
                f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
                headers=fixture.operator_headers(),
            )
            assert detail.status_code == result.status_code == evidence.status_code == 200
            detail_body = detail.json()
            result_body = result.json()
            evidence_body = evidence.json()
            expected_suitability = (
                "EVALUATED"
                if not v2_dsm_only or set(passed_checkpoint_epochs) == {"BASELINE", "CURRENT"}
                else "PROVISIONAL_ACCURACY_UNVERIFIED"
            )
            assert detail_body["suitabilityState"] == expected_suitability
            assert detail_body["executionState"] == result_body["executionState"] == "COMPLETED"
            assert detail_body["result"] == result_body["result"] == evidence_body["result"]
            assert (
                evidence_body["baseline"]["inspectionReportDigest"]
                == (fixture.synthetic_inspection_report_digests[0])
            )
            assert (
                evidence_body["current"]["inspectionReportDigest"]
                == (fixture.synthetic_inspection_report_digests[1])
            )
            if real_inspection:
                for epoch_key, revision in (
                    ("baseline", fixture._baseline_revision),
                    ("current", fixture._current_revision),
                ):
                    evidence_epoch = evidence_body[epoch_key]
                    sealed_entry = revision.manifest.entries[0]
                    assert evidence_epoch["observedSha256"] == (
                        "sha256:" + sealed_entry.observed_sha256
                    )
                    assert evidence_epoch["observedSizeBytes"] == sealed_entry.observed_size_bytes
                    assert evidence_epoch["observedCrsIdentifier"] == "EPSG:5186"
                    assert evidence_epoch["verticalReferenceIdentifier"] == "EPSG:5773"
                    assert evidence_epoch["transform"] == [
                        0.1,
                        0.0,
                        200000.0,
                        0.0,
                        -0.1,
                        550000.0,
                    ]
            assert detail_body["result"]["resultRevision"] == 1
            metrics = detail_body["result"]["metrics"]
            # Hand check: each 0.1 m × 0.1 m cell contributes 0.01 m³ for
            # the 1 m rise/fall in one cell, so cut and fill are both 0.01 m³.
            assert metrics["cutM3"] == pytest.approx(0.01)
            assert metrics["fillM3"] == pytest.approx(0.01)
            assert metrics["netM3"] == pytest.approx(0.0)
            assert metrics["thresholdM"] == 0.0
            assert metrics["uncertaintyM3"] is None
            assert evidence_body["baseline"]["observedSizeBytes"] > 0
            assert evidence_body["current"]["observedSizeBytes"] > 0
            v2_detail = operator.get(
                f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}",
                headers=fixture.operator_headers(),
            )
            assert v2_detail.status_code == 200, v2_detail.text
            assert v2_detail.json()["analysisId"] == detail_body["analysisId"]
            assert v2_detail.json()["result"]["resultId"] == detail_body["result"]["resultId"]
            assert v2_detail.json()["result"]["metrics"] == detail_body["result"]["metrics"]
            assert "selectedMaskB64" not in v2_detail.text
            malformed_list_cursor = (
                base64.urlsafe_b64encode(
                    json.dumps({"createdAt": 42, "analysisId": analysis_id}).encode()
                )
                .decode()
                .rstrip("=")
            )
            malformed_list = operator.get(
                f"/v2/sites/{fixture.site_id}/analyses",
                params={"cursor": malformed_list_cursor},
                headers=fixture.operator_headers(),
            )
            assert malformed_list.status_code == 400
            assert malformed_list.json()["detail"] == "ANALYSIS_CURSOR_INVALID"
            evidence_cursor = None
            evidence_items = []
            evidence_digest = None
            evidence_page_count = 0
            while True:
                evidence_page = operator.get(
                    f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
                    params={"limit": 1, **({"cursor": evidence_cursor} if evidence_cursor else {})},
                    headers=fixture.operator_headers(),
                )
                assert evidence_page.status_code == 200, evidence_page.text
                evidence_body_v2 = evidence_page.json()
                assert len(evidence_body_v2["items"]) <= 1
                evidence_digest = evidence_digest or evidence_body_v2["evidenceDigest"]
                assert evidence_body_v2["evidenceDigest"] == evidence_digest
                evidence_items.extend(evidence_body_v2["items"])
                evidence_page_count += 1
                evidence_cursor = evidence_body_v2["nextCursor"]
                if evidence_cursor is None:
                    break
                assert evidence_page_count <= 100
            assert evidence_page_count >= 2
            assert {item["kind"] for item in evidence_items} >= {
                "EPOCH_IDENTITY",
                "CALCULATION_IDENTITY",
                "EVALUATION",
            }
            range_url = f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/coverage"
            first_range = operator.get(
                range_url, headers={**fixture.operator_headers(), "Range": "bytes=0-0"}
            )
            assert first_range.status_code == 206, first_range.text
            total_bytes = int(first_range.headers["X-KSI-Coverage-Total-Length"])
            site_store = fixture.app.state.site_store
            site_record = site_store.get_scoped(fixture.site_id, fixture.organization_id)
            assert site_record is not None
            site_store._sites[fixture.site_id] = replace(site_record, ai_egress_allowed=True)
            mcp_range = operator.get(
                range_url,
                headers={
                    **fixture.mcp_client_headers(),
                    "Range": "bytes=0-0",
                },
            )
            assert mcp_range.status_code == 206, mcp_range.text
            assert mcp_range.headers["X-KSI-External-AI-Egress"] == "ALLOWED"
            full_range = operator.get(
                range_url,
                headers={
                    **fixture.operator_headers(),
                    "Range": f"bytes=0-{total_bytes - 1}",
                },
            )
            expected_coverage = canonical_json_bytes(detail_body["result"]["coverage"])
            assert full_range.status_code == 206, full_range.text
            assert full_range.content == expected_coverage
            assert full_range.headers["Content-Range"] == f"bytes 0-{total_bytes - 1}/{total_bytes}"
            assert full_range.headers["Content-Length"] == str(total_bytes)
            assert full_range.headers["X-KSI-Coverage-Digest"] == (
                "sha256:" + hashlib.sha256(expected_coverage).hexdigest()
            )
            if real_inspection:
                completed_retry = operator.post(
                    f"/v2/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
                    headers={
                        **fixture.operator_headers(),
                        "Idempotency-Key": "combined-real-loop",
                    },
                    json=body,
                )
                assert completed_retry.status_code == 202, completed_retry.text
                assert completed_retry.json()["analysisId"] == analysis_id
                assert (
                    completed_retry.json()["result"]["resultId"]
                    == detail_body["result"]["resultId"]
                )
                assert (
                    completed_retry.json()["result"]["metrics"] == detail_body["result"]["metrics"]
                )
            for invalid_range in (None, "bytes=0-1,3-4", "bytes=0-65536", "bytes=999999-1000000"):
                headers = dict(fixture.operator_headers())
                if invalid_range is not None:
                    headers["Range"] = invalid_range
                rejected = operator.get(range_url, headers=headers)
                assert rejected.status_code == 416
            if v2_dsm_only:
                by_epoch = {item["epoch"]: item for item in evidence_body["evaluations"]}
                expected_outcomes = {
                    epoch: ("PASS" if epoch in passed_checkpoint_epochs else "UNASSESSED")
                    for epoch in ("BASELINE", "CURRENT")
                }
                assert {epoch: item["outcome"] for epoch, item in by_epoch.items()} == (
                    expected_outcomes
                )
                if set(passed_checkpoint_epochs) == {"BASELINE", "CURRENT"}:
                    assert all(
                        len(by_epoch[epoch]["evidenceFacts"]) == 1
                        and by_epoch[epoch]["evidenceFacts"][0]["coreVerdict"] == "VALIDATED"
                        for epoch in ("BASELINE", "CURRENT")
                    )
                    evaluation_digests = {item["evaluationDigest"] for item in by_epoch.values()}
                    checkpoint_refs = {
                        item["recordId"]
                        for item in evidence_body["evidenceRefs"]
                        if item["kind"] == "CHECKPOINT_EVIDENCE"
                    }
                    passed_record_refs = {
                        fact["evidenceRef"]
                        for item in by_epoch.values()
                        for fact in item["evidenceFacts"]
                    }
                    assert len(evaluation_digests) == 2
                    assert checkpoint_refs == passed_record_refs
                    assert detail_body["result"]["limitationCodes"] == []
                elif passed_checkpoint_epochs:
                    assert detail_body["suitabilityState"] == ("PROVISIONAL_ACCURACY_UNVERIFIED")
                    unassessed_epochs = set(("BASELINE", "CURRENT")) - set(passed_checkpoint_epochs)
                    assert len(unassessed_epochs) == 1
                    unassessed_epoch = unassessed_epochs.pop()
                    assert by_epoch[unassessed_epoch]["reasonCodes"] == [
                        "CHECKPOINT_EVIDENCE_ABSENT"
                    ]
                    assert "CHECKPOINT_EVIDENCE_ABSENT" in detail_body["result"]["limitationCodes"]
            completed_alias = operator.post(
                f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
                headers={
                    **fixture.operator_headers(),
                    "Idempotency-Key": "combined-real-completed-alias",
                },
                json=body,
            )
            assert completed_alias.status_code == 202, completed_alias.text
            completed_alias_id = completed_alias.json()["analysisId"]
            assert completed_alias_id not in {analysis_id, alias_id}
            assert (
                completed_alias.json()["authority"]["calculationRequestId"]
                == created.json()["authority"]["calculationRequestId"]
            )
            if set(passed_checkpoint_epochs) == {"BASELINE", "CURRENT"}:
                retried = operator.post(
                    f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
                    headers={
                        **fixture.operator_headers(),
                        "Idempotency-Key": "combined-real-loop",
                    },
                    json=body,
                )
                assert retried.status_code == 202, retried.text
                assert retried.json()["analysisId"] == analysis_id
                assert retried.json()["executionState"] == "COMPLETED"
                assert retried.json()["suitabilityState"] == "EVALUATED"
                assert retried.json()["result"] == result_body["result"]
                retried_evidence = operator.get(
                    f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
                    headers=fixture.operator_headers(),
                )
                assert retried_evidence.status_code == 200
                assert retried_evidence.json()["evaluations"] == evidence_body["evaluations"]
                assert retried_evidence.json()["evidenceRefs"] == evidence_body["evidenceRefs"]
            # A compatible AP record recorded after completion must project the
            # immutable result; it cannot schedule a new worker execution.
            assert not run_once(worker_client, runtime, transport)
            alias_detail = operator.get(
                f"/v1/sites/{fixture.site_id}/analyses/{alias_id}",
                headers=fixture.operator_headers(),
            )
            alias_result = operator.get(
                f"/v1/sites/{fixture.site_id}/analyses/{alias_id}/result",
                headers=fixture.operator_headers(),
            )
            alias_evidence = operator.get(
                f"/v1/sites/{fixture.site_id}/analyses/{alias_id}/evidence",
                headers=fixture.operator_headers(),
            )
            assert (
                alias_detail.status_code
                == alias_result.status_code
                == alias_evidence.status_code
                == 200
            )
            assert alias_detail.json()["result"] == result_body["result"]
            assert alias_result.json()["result"] == result_body["result"]
            assert alias_evidence.json()["result"] == evidence_body["result"]
            completed_alias_result = operator.get(
                f"/v1/sites/{fixture.site_id}/analyses/{completed_alias_id}/result",
                headers=fixture.operator_headers(),
            )
            assert completed_alias_result.status_code == 200
            assert completed_alias_result.json()["result"] == result_body["result"]

            if late_failure:
                wiring = fixture.app.state.external_analysis_wiring
                original_assessment = wiring.assessments.get_history(
                    analysis_id, organization_id="org-a"
                )
                original_calculation = wiring.calculations.get_history(
                    analysis_id, organization_id="org-a"
                )
                assert original_assessment is not None
                assert original_calculation is not None
                assert original_calculation.report is not None
                original_report_digest = original_calculation.report.report_digest

                revision_page = operator.get(
                    f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
                    params={"limit": 1},
                    headers=fixture.operator_headers(),
                )
                assert revision_page.status_code == 200, revision_page.text
                revision_cursor = revision_page.json()["nextCursor"]
                assert revision_cursor is not None

                rejected = fixture.append_failed_current_checkpoint_evaluation()
                assert rejected.core_verdict.value == "REJECTED"
                assert rejected.core_reason == "CHECKPOINT_COUNT_OUT_OF_RANGE"

                stale_revision_page = operator.get(
                    f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
                    params={"limit": 1, "cursor": revision_cursor},
                    headers=fixture.operator_headers(),
                )
                assert stale_revision_page.status_code == 409, stale_revision_page.text
                assert stale_revision_page.json()["detail"] == "ANALYSIS_EVIDENCE_CURSOR_STALE"

                current_detail = operator.get(detail_url, headers=fixture.operator_headers())
                current_result = operator.get(
                    f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/result",
                    headers=fixture.operator_headers(),
                )
                current_evidence = operator.get(
                    f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
                    headers=fixture.operator_headers(),
                )
                assert (
                    current_detail.status_code
                    == current_result.status_code
                    == current_evidence.status_code
                    == 200
                )
                assert current_detail.json()["executionState"] == "COMPLETED"
                assert current_result.json()["executionState"] == "COMPLETED"
                assert current_detail.json()["suitabilityState"] == "REASSESSMENT_REQUIRED"
                assert current_result.json()["suitabilityState"] == "REASSESSMENT_REQUIRED"
                assert current_detail.json()["result"] is None
                assert current_result.json()["result"] is None
                assert current_evidence.json()["result"] is None
                # Existing AP evidence remains its original immutable snapshot;
                # the current suitability projection suppresses its number.
                assert current_evidence.json()["evaluations"] == evidence_body["evaluations"]

                later_request = operator.post(
                    f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
                    headers={
                        **fixture.operator_headers(),
                        "Idempotency-Key": "late-failed-current-evaluation",
                    },
                    json=body,
                )
                assert later_request.status_code == 202, later_request.text
                assert later_request.json()["analysisId"] != analysis_id
                assert later_request.json()["executionState"] == "NOT_STARTED"
                assert later_request.json()["suitabilityState"] == "REMEDIATION_REQUIRED"
                assert later_request.json()["result"] is None
                assert "CHECKPOINT_COUNT_OUT_OF_RANGE" in {
                    item["code"] for item in later_request.json()["blockers"]
                }
                later_evidence = operator.get(
                    f"/v1/sites/{fixture.site_id}/analyses/"
                    f"{later_request.json()['analysisId']}/evidence",
                    headers=fixture.operator_headers(),
                )
                assert later_evidence.status_code == 200, later_evidence.text
                assert any(
                    item["epoch"] == "CURRENT"
                    and item["outcome"] == "FAIL"
                    and item["reasonCodes"] == ["CHECKPOINT_COUNT_OUT_OF_RANGE"]
                    for item in later_evidence.json()["evaluations"]
                )
                pending_after_late_evaluation = operator.get(
                    "/v1/internal/analysis-jobs", headers=fixture.worker_headers()
                )
                assert pending_after_late_evaluation.status_code == 200
                assert pending_after_late_evaluation.json()["items"] == []
                assert not run_once(worker_client, runtime, transport)

                assert (
                    wiring.assessments.get_history(analysis_id, organization_id="org-a")
                    == original_assessment
                )
                historical_calculation = wiring.calculations.get_history(
                    analysis_id, organization_id="org-a"
                )
                assert historical_calculation == original_calculation
                assert historical_calculation.report.report_digest == original_report_digest

        restarted_client = ExternalAnalysisCoreClient(
            base_url=core_origin,
            worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
            worker_instance_id="combined-restarted-worker",
        )
        assert not run_once(restarted_client, runtime, transport)
        restarted_client.close()
        restarted_client = None
        worker_client.close()
        worker_client = None
        core_server.should_exit = True
        core_thread.join(timeout=10)
        assert not core_thread.is_alive()
        core_server = None
        core_thread = None
        core_socket.close()
        core_socket = None
        fixture.close()
        fixture_closed = True

        # This is a Core journal replay, distinct from the worker-client
        # restart above.  Supporting local facts are reconstructed by the
        # same fixture, then AP/NX/intent journals project the prior result.
        replay_activation = None
        if real_inspection and not late_failure:
            from ksi_core.identity.auth import Principal, PrincipalKind
            from test_external_analysis_activation import _write_activation

            wiring = fixture.app.state.external_analysis_wiring
            worker_principal = Principal(
                principal_id="analysis-local-worker",
                kind=PrincipalKind.ANALYSIS_WORKER,
                role=None,
                device_id=None,
                organization_id=fixture.organization_id,
            )
            activation_dir = tmp_path / "expired-analysis-activation"
            activation_path, _keys_path, replay_activation = _write_activation(
                activation_dir,
                bindings={
                    "organization_id": fixture.organization_id,
                    "policy": wiring.assessments._policy,
                    "runtime": wiring.assessments._runtime,
                    "resource_envelope": wiring.calculations._resource_envelope,
                    "worker_principal": worker_principal,
                },
                activation_fields={
                    "issuedAt": (datetime.now(UTC) - timedelta(hours=2))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "validUntil": (datetime.now(UTC) - timedelta(hours=1))
                    .isoformat()
                    .replace("+00:00", "Z"),
                },
            )
            assert activation_path.is_file()
        reopened_fixture = build_local_analysis_api_fixture(
            tmp_path, replay_of=fixture, analysis_activation=replay_activation
        )
        replayed_client = TestClient(reopened_fixture.app)
        replayed_detail = replayed_client.get(
            f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}",
            headers=reopened_fixture.operator_headers(),
        )
        replayed_result = replayed_client.get(
            f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/result",
            headers=reopened_fixture.operator_headers(),
        )
        replayed_evidence = replayed_client.get(
            f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
            headers=reopened_fixture.operator_headers(),
        )
        replayed_list = replayed_client.get(
            f"/v1/sites/{fixture.site_id}/analyses",
            headers=reopened_fixture.operator_headers(),
        )
        replayed_alias_detail = replayed_client.get(
            f"/v1/sites/{fixture.site_id}/analyses/{alias_id}",
            headers=reopened_fixture.operator_headers(),
        )
        replayed_alias_evidence = replayed_client.get(
            f"/v1/sites/{fixture.site_id}/analyses/{alias_id}/evidence",
            headers=reopened_fixture.operator_headers(),
        )
        replayed_completed_alias = replayed_client.get(
            f"/v1/sites/{fixture.site_id}/analyses/{completed_alias_id}/result",
            headers=reopened_fixture.operator_headers(),
        )
        assert (
            replayed_detail.status_code
            == replayed_result.status_code
            == replayed_evidence.status_code
            == replayed_list.status_code
            == 200
        )
        assert analysis_id in {item["analysisId"] for item in replayed_list.json()["items"]}
        assert replayed_alias_detail.status_code == replayed_alias_evidence.status_code == 200
        assert replayed_completed_alias.status_code == 200
        if late_failure:
            assert replayed_detail.json()["executionState"] == "COMPLETED"
            assert replayed_detail.json()["suitabilityState"] == "REASSESSMENT_REQUIRED"
            assert replayed_detail.json()["result"] is None
            assert replayed_result.json()["result"] is None
            assert replayed_evidence.json()["result"] is None
            assert replayed_evidence.json()["evaluations"] == evidence_body["evaluations"]
        else:
            assert replayed_detail.json()["result"] == detail_body["result"]
            assert replayed_result.json()["result"] == result_body["result"]
            assert replayed_evidence.json()["result"] == evidence_body["result"]
            assert replayed_evidence.json()["evaluations"] == evidence_body["evaluations"]
            assert replayed_evidence.json()["evidenceRefs"] == evidence_body["evidenceRefs"]
            if replay_activation is not None:
                assert replayed_detail.json()["analysisId"] == analysis_id
                assert replayed_result.json()["result"] == result_body["result"]
                replayed_v2_detail = replayed_client.get(
                    f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}",
                    headers=reopened_fixture.operator_headers(),
                )
                assert replayed_v2_detail.status_code == 200
                assert replayed_v2_detail.json()["analysisId"] == analysis_id
                assert (
                    replayed_v2_detail.json()["result"]["resultId"]
                    == result_body["result"]["resultId"]
                )
                expired_v2_create = replayed_client.post(
                    f"/v2/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
                    headers={
                        **reopened_fixture.operator_headers(),
                        "Idempotency-Key": "expired-v2-activation-create-blocked",
                    },
                    json=body,
                )
                assert expired_v2_create.status_code == 503
                assert expired_v2_create.json()["detail"] == "ANALYSIS_ACTIVATION_EXPIRED"
                expired_create = replayed_client.post(
                    f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
                    headers={
                        **reopened_fixture.operator_headers(),
                        "Idempotency-Key": "expired-activation-create-blocked",
                    },
                    json=body,
                )
                assert expired_create.status_code == 503
                assert expired_create.json()["detail"] == "ANALYSIS_ACTIVATION_EXPIRED"
                expired_jobs = replayed_client.get(
                    "/v1/internal/analysis-jobs", headers=reopened_fixture.worker_headers()
                )
                assert expired_jobs.status_code == 503
                assert expired_jobs.json()["detail"] == "ANALYSIS_ACTIVATION_EXPIRED"
        if late_failure:
            assert replayed_alias_detail.json()["executionState"] == "COMPLETED"
            assert replayed_alias_detail.json()["suitabilityState"] == "REASSESSMENT_REQUIRED"
            assert replayed_alias_detail.json()["result"] is None
            assert replayed_alias_evidence.json()["result"] is None
            assert replayed_completed_alias.json()["result"] is None
        else:
            assert replayed_alias_detail.json()["result"] == detail_body["result"]
            assert replayed_alias_evidence.json()["result"] == evidence_body["result"]
            assert replayed_completed_alias.json()["result"] == detail_body["result"]
        if late_failure:
            replayed_current = replayed_client.get(
                f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/result",
                headers=reopened_fixture.operator_headers(),
            )
            assert replayed_current.status_code == 200
            assert replayed_current.json()["executionState"] == "COMPLETED"
            assert replayed_current.json()["suitabilityState"] == "REASSESSMENT_REQUIRED"
            assert replayed_current.json()["result"] is None
            replayed_latest = replayed_client.post(
                f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
                headers={
                    **reopened_fixture.operator_headers(),
                    "Idempotency-Key": "late-failed-current-evaluation",
                },
                json=body,
            )
            assert replayed_latest.status_code == 202, replayed_latest.text
            assert replayed_latest.json()["executionState"] == "NOT_STARTED"
            assert replayed_latest.json()["suitabilityState"] == "REMEDIATION_REQUIRED"
            assert replayed_latest.json()["result"] is None
            assert "CHECKPOINT_COUNT_OUT_OF_RANGE" in {
                item["code"] for item in replayed_latest.json()["blockers"]
            }
            replayed_latest_evidence = replayed_client.get(
                f"/v1/sites/{fixture.site_id}/analyses/"
                f"{replayed_latest.json()['analysisId']}/evidence",
                headers=reopened_fixture.operator_headers(),
            )
            assert replayed_latest_evidence.status_code == 200
            assert any(
                item["epoch"] == "CURRENT"
                and item["outcome"] == "FAIL"
                and item["reasonCodes"] == ["CHECKPOINT_COUNT_OUT_OF_RANGE"]
                for item in replayed_latest_evidence.json()["evaluations"]
            )
            replayed_jobs = replayed_client.get(
                "/v1/internal/analysis-jobs", headers=reopened_fixture.worker_headers()
            )
            assert replayed_jobs.status_code == 200
            assert replayed_jobs.json()["items"] == []
            replayed_wiring = reopened_fixture.app.state.external_analysis_wiring
            assert (
                replayed_wiring.assessments.get_history(analysis_id, organization_id="org-a")
                == original_assessment
            )
            replayed_calculation = replayed_wiring.calculations.get_history(
                analysis_id, organization_id="org-a"
            )
            assert replayed_calculation == original_calculation
            assert replayed_calculation.report.report_digest == original_report_digest
        reopened_fixture.close()
        reopened_fixture = None
    finally:
        if reopened_fixture is not None:
            reopened_fixture.close()
        if restarted_client is not None:
            restarted_client.close()
        if worker_client is not None:
            worker_client.close()
        if core_server is not None:
            core_server.should_exit = True
        if core_thread is not None:
            core_thread.join(timeout=10)
            assert not core_thread.is_alive()
        if core_socket is not None:
            core_socket.close()
        if object_server is not None:
            object_server.shutdown()
            object_server.server_close()
        if object_thread is not None:
            object_thread.join(timeout=10)
            assert not object_thread.is_alive()
        if not fixture_closed:
            fixture.close()
