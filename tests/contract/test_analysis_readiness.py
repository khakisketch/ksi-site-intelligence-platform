"""Additive read-only Analysis readiness preflight for arbitrary selector pairs.

The ``POST /v2/sites/{site_id}/work-areas/{work_area_id}/analysis-readiness``
route reuses the sealed AP preparation/currentness predicates without
creating an intent, AP/NX record, journal entry, or execution authority.
Detailed ``READINESS_*`` blocker codes are confined to this view; the
durable ``ESSENTIAL_INPUT_UNAVAILABLE`` meaning is unchanged.
"""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

from analysis_api_local_fixture import build_local_analysis_api_fixture
from fastapi.testclient import TestClient
from ksi_event_contracts.external_analysis_api import (
    AnalysisObservationSelectorV1,
    AnalysisReadinessViewV1,
    AnalysisSuitabilityStateV1,
)


def _selectors(fixture: Any) -> dict[str, Any]:
    return {
        "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
        "current": fixture.current.model_dump(by_alias=True, mode="json"),
    }


def _journal_bytes(fixture: Any) -> dict[Path, bytes]:
    return {
        journal._path: journal._path.read_bytes()  # noqa: SLF001
        for journal in fixture.opened
        if journal._path.exists()  # noqa: SLF001
    }


def _readiness_path(fixture: Any) -> str:
    return f"/v2/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analysis-readiness"


def _without_checked_at(payload: dict[str, Any]) -> dict[str, Any]:
    """Readiness carries a fresh UTC instant; stability compares everything else."""
    return {key: value for key, value in payload.items() if key != "checkedAt"}


def test_readiness_api_mcp_parity_and_pure_read_only(tmp_path: Path) -> None:
    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        passed_checkpoint_epochs=("BASELINE", "CURRENT"),
        ai_egress_allowed=True,
    )
    try:
        client = TestClient(fixture.app)
        body = _selectors(fixture)
        path = _readiness_path(fixture)
        before_journals = _journal_bytes(fixture)
        wiring = fixture.app.state.external_analysis_wiring
        intents_before = len(
            wiring.intents.list_for_organization(organization_id="org-a")
        )

        operator = client.post(path, headers=fixture.operator_headers(), json=body)
        assert operator.status_code == 200, operator.text
        payload = operator.json()
        assert payload["contractVersion"] == "analysis-readiness.v1"
        assert payload["siteId"] == fixture.site_id
        assert payload["workAreaId"] == fixture.work_area_id
        assert payload["baseline"] == body["baseline"]
        assert payload["current"] == body["current"]
        assert payload["suitabilityState"] == "EVALUATED"
        assert payload["blockers"] == []
        assert payload["limitationCodes"] == []
        assert payload["calculationIdentityDigest"] is not None
        assert payload["checkedAt"].endswith("Z")
        assert payload["coverageCheck"] == "REQUIRES_WORKER_VALIDATION"
        assert "cutM3" not in json.dumps(payload)
        assert "netM3" not in json.dumps(payload)
        # The view validates as the canonical contract without extra keys.
        validated = AnalysisReadinessViewV1.model_validate(payload)
        assert validated.coverage_check == "REQUIRES_WORKER_VALIDATION"

        mcp = client.post(path, headers=fixture.mcp_client_headers(), json=body)
        assert mcp.status_code == 200, mcp.text
        assert mcp.headers.get("X-KSI-External-AI-Egress") == "ALLOWED"
        assert _without_checked_at(mcp.json()) == _without_checked_at(payload)
        # The operator carries no MCP acknowledgment header.
        assert "X-KSI-External-AI-Egress" not in operator.headers

        # A read-only viewer may preflight but cannot create execution authority.
        viewer = client.post(path, headers=fixture.viewer_headers(), json=body)
        assert viewer.status_code == 200, viewer.text
        assert viewer.json()["suitabilityState"] == payload["suitabilityState"]
        denied_create = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.viewer_headers(), "Idempotency-Key": "viewer-no-authority"},
            json=body,
        )
        assert denied_create.status_code == 403

        # MCP tool arguments and result models accept the exact HTTP contract.
        from ksi_analysis_mcp.core_client import (
            TOOL_RESULT_MODELS,
            ReadinessArguments,
            validate_tool_arguments,
        )

        parsed = validate_tool_arguments(
            "ksi_check_analysis_readiness",
            {"siteId": fixture.site_id, "workAreaId": fixture.work_area_id, **body},
        )
        assert isinstance(parsed, ReadinessArguments)
        assert parsed.site_id == fixture.site_id
        TOOL_RESULT_MODELS["ksi_check_analysis_readiness"].model_validate(payload)

        # Repeated and concurrent preflights agree and append nothing.
        with ThreadPoolExecutor(max_workers=8) as pool:
            repeats = list(
                pool.map(
                    lambda _: client.post(
                        path, headers=fixture.operator_headers(), json=body
                    ).json()["suitabilityState"],
                    range(16),
                )
            )
        assert set(repeats) == {"EVALUATED"}
        assert _journal_bytes(fixture) == before_journals
        assert (
            len(wiring.intents.list_for_organization(organization_id="org-a"))
            == intents_before
        )
    finally:
        fixture.close()


def test_readiness_scope_consent_and_unknown_selectors(tmp_path: Path) -> None:
    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        passed_checkpoint_epochs=("BASELINE", "CURRENT"),
        ai_egress_allowed=True,
    )
    try:
        client = TestClient(fixture.app)
        body = _selectors(fixture)
        path = _readiness_path(fixture)
        before = _journal_bytes(fixture)

        # Foreign scope is non-disclosing for both operator and MCP identities.
        assert (
            client.post(
                "/v2/sites/site-outside-grant/work-areas/"
                f"{fixture.work_area_id}/analysis-readiness",
                headers=fixture.operator_headers(),
                json=body,
            ).status_code
            == 404
        )
        assert (
            client.post(path, headers=fixture.mcp_other_area_headers(), json=body).status_code
            == 404
        )
        unknown = dict(body)
        unknown["current"] = {
            **body["current"],
            "submissionRef": "ers-v1-" + "f" * 64,
        }
        assert client.post(path, headers=fixture.operator_headers(), json=unknown).status_code == (
            404
        )
        identical = {"baseline": body["baseline"], "current": body["baseline"]}
        assert (
            client.post(path, headers=fixture.operator_headers(), json=identical).status_code
            == 422
        )

        # Revoked AI consent denies the MCP preflight but never the operator read.
        site_store = fixture.app.state.site_store
        from dataclasses import replace

        site = site_store.get_scoped(fixture.site_id, fixture.organization_id)
        assert site is not None and site.ai_egress_allowed
        site_store._sites[fixture.site_id] = replace(site, ai_egress_allowed=False)  # noqa: SLF001
        denied = client.post(path, headers=fixture.mcp_client_headers(), json=body)
        assert denied.status_code == 403
        assert denied.json()["detail"] == "AI_EGRESS_NOT_ALLOWED"
        assert "X-KSI-External-AI-Egress" not in denied.headers
        operator_after_revoke = client.post(
            path, headers=fixture.operator_headers(), json=body
        )
        assert operator_after_revoke.status_code == 200
        assert "X-KSI-External-AI-Egress" not in operator_after_revoke.headers
        assert _journal_bytes(fixture) == before
    finally:
        fixture.close()


def test_readiness_pending_inspection_is_actionable_and_durable_stays_coarse(
    tmp_path: Path,
) -> None:
    """Uninspected epochs explain per-epoch pending codes; create stays coarse."""
    fixture = build_local_analysis_api_fixture(
        tmp_path, v2_dsm_only=True, real_inspection=True, ai_egress_allowed=True
    )
    try:
        client = TestClient(fixture.app)
        body = _selectors(fixture)
        path = _readiness_path(fixture)
        before = _journal_bytes(fixture)

        readiness = client.post(path, headers=fixture.operator_headers(), json=body)
        assert readiness.status_code == 200, readiness.text
        payload = readiness.json()
        assert payload["suitabilityState"] == "BLOCKED"
        assert payload["calculationIdentityDigest"] is None
        assert payload["coverageCheck"] == "REQUIRES_WORKER_VALIDATION"
        assert {item["code"] for item in payload["blockers"]} == {
            "READINESS_INSPECTION_PENDING"
        }
        assert {item["epoch"] for item in payload["blockers"]} == {"BASELINE", "CURRENT"}
        assert "cutM3" not in json.dumps(payload)

        created = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": "pending-stays-coarse"},
            json=body,
        )
        assert created.status_code == 202, created.text
        assert created.json()["suitabilityState"] == "BLOCKED"
        assert {item["code"] for item in created.json()["blockers"]} == {
            "ESSENTIAL_INPUT_UNAVAILABLE"
        }
        assert _journal_bytes(fixture) != before  # the create above journaled once
        after_create = _journal_bytes(fixture)
        reread = client.post(path, headers=fixture.operator_headers(), json=body)
        assert _without_checked_at(reread.json()) == _without_checked_at(payload)
        assert _journal_bytes(fixture) == after_create
    finally:
        fixture.close()


def test_readiness_missing_vertical_blocks_without_numeric_and_keeps_history(
    tmp_path: Path,
) -> None:
    """Measured missing vertical reference blocks readiness with epoch precision."""
    from test_external_analysis_real_inspection_lane_integration import (
        _CoreAndObjectServers,
        _post_analysis,
    )
    from test_external_analysis_spatial_blockers_integration import (
        _inspect_both_epochs_with_actual_lane,
    )

    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        real_inspection=True,
        current_dsm_spatial_case="MISSING_VERTICAL_REFERENCE",
    )
    try:
        with _CoreAndObjectServers(fixture) as servers:
            _inspect_both_epochs_with_actual_lane(
                fixture,
                core_origin=servers.core_origin,
                object_origin=servers.object_origin,
                tmp_path=tmp_path,
            )
            import httpx

            body = _selectors(fixture)
            wiring = fixture.app.state.external_analysis_wiring
            intents_before = len(
                wiring.intents.list_for_organization(organization_id="org-a")
            )
            journals_before = _journal_bytes(fixture)
            with httpx.Client(base_url=servers.core_origin, trust_env=False) as operator:
                readiness = operator.post(
                    _readiness_path(fixture),
                    headers=fixture.operator_headers(),
                    json=body,
                )
                assert readiness.status_code == 200, readiness.text
                payload = readiness.json()
                assert payload["suitabilityState"] == "BLOCKED"
                assert payload["calculationIdentityDigest"] is None
                assert payload["coverageCheck"] == "REQUIRES_WORKER_VALIDATION"
                assert {item["epoch"] for item in payload["blockers"]} == {"CURRENT"}
                assert any(
                    item["code"]
                    in {
                        "READINESS_VERTICAL_REFERENCE_UNAVAILABLE",
                        "READINESS_VERTICAL_UNIT_UNAVAILABLE",
                    }
                    for item in payload["blockers"]
                )
                assert "cutM3" not in readiness.text and "netM3" not in readiness.text
                assert _journal_bytes(fixture) == journals_before
                assert (
                    len(wiring.intents.list_for_organization(organization_id="org-a"))
                    == intents_before
                )
                reread = operator.post(
                    _readiness_path(fixture),
                    headers=fixture.operator_headers(),
                    json=body,
                )
                assert _without_checked_at(reread.json()) == _without_checked_at(payload)
                intent = _post_analysis(
                    fixture, servers.core_origin, "missing-vertical-keeps-coarse"
                )
                assert intent["suitabilityState"] == "BLOCKED"
                assert {item["code"] for item in intent["blockers"]} == {
                    "ESSENTIAL_INPUT_UNAVAILABLE"
                }
    finally:
        fixture.close()


def test_readiness_currentness_replay_and_provisional_semantics(tmp_path: Path) -> None:
    """Changed evidence moves readiness; replay and provisional limits stay stable."""
    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        passed_checkpoint_epochs=("BASELINE", "CURRENT"),
        ai_egress_allowed=True,
    )
    try:
        client = TestClient(fixture.app)
        body = _selectors(fixture)
        path = _readiness_path(fixture)
        admitted = client.post(path, headers=fixture.operator_headers(), json=body)
        assert admitted.json()["suitabilityState"] == "EVALUATED"

        context = fixture._retained_contexts[0]  # noqa: SLF001
        context_digest = context.context_digest
        assert context_digest is not None
        fixture.revoke_evidence_context(context_digest)
        moved = client.post(path, headers=fixture.operator_headers(), json=body)
        assert moved.json()["suitabilityState"] == "BLOCKED"
        assert moved.json()["blockers"] == [
            {
                "code": "EVIDENCE_CONTEXT_UNAVAILABLE",
                "epoch": "BASELINE",
                "evidenceRef": None,
                "detail": None,
            }
        ]
        fixture.restore_evidence_context(context_digest)
        restored = client.post(path, headers=fixture.operator_headers(), json=body)
        assert _without_checked_at(restored.json()) == _without_checked_at(admitted.json())

        provisional_root = tmp_path / "provisional"
        provisional_root.mkdir(mode=0o700, exist_ok=True)
        provisional_fixture = build_local_analysis_api_fixture(
            provisional_root,
            v2_dsm_only=True,
            ai_egress_allowed=True,
        )
        provisional_body: dict[str, Any] | None = None
        provisional_payload: dict[str, Any] | None = None
        try:
            provisional_client = TestClient(provisional_fixture.app)
            provisional_body = _selectors(provisional_fixture)
            provisional = provisional_client.post(
                _readiness_path(provisional_fixture),
                headers=provisional_fixture.operator_headers(),
                json=provisional_body,
            )
            assert provisional.status_code == 200, provisional.text
            assert provisional.json()["suitabilityState"] == (
                "PROVISIONAL_ACCURACY_UNVERIFIED"
            )
            assert provisional.json()["blockers"] == []
            assert provisional.json()["calculationIdentityDigest"] is not None
            assert "CHECKPOINT_EVIDENCE_ABSENT" in provisional.json()["limitationCodes"]
            assert _without_checked_at(provisional.json())["suitabilityState"] == (
                "PROVISIONAL_ACCURACY_UNVERIFIED"
            )
            provisional_payload = provisional.json()
        finally:
            provisional_fixture.close()
        assert provisional_body is not None and provisional_payload is not None
        # Reopening the same journal directory replays the identical readiness
        # and repeated reads still append nothing.
        replay_fixture = build_local_analysis_api_fixture(
            provisional_root, replay_of=provisional_fixture
        )
        try:
            replay_client = TestClient(replay_fixture.app)
            replayed = replay_client.post(
                _readiness_path(replay_fixture),
                headers=replay_fixture.operator_headers(),
                json=_selectors(replay_fixture),
            )
            assert _without_checked_at(replayed.json()) == _without_checked_at(
                provisional_payload
            )
            journals_before = _journal_bytes(replay_fixture)
            reread = replay_client.post(
                _readiness_path(replay_fixture),
                headers=replay_fixture.operator_headers(),
                json=_selectors(replay_fixture),
            )
            assert _without_checked_at(reread.json()) == _without_checked_at(
                provisional_payload
            )
            assert _journal_bytes(replay_fixture) == journals_before
        finally:
            replay_fixture.close()
    finally:
        fixture.close()


def _record_rejected_current_inspection(fixture: Any, *, reason: str = "DSM_UNREADABLE") -> None:
    """Store one terminal REJECTED inspection outcome for the current DSM epoch.

    Mirrors the fixture's synthetic inspection flow (issue/claim/record) but
    carries the contract-required rejected shape: a typed reason and no
    measurements. The baseline epoch stays inspection-pending on purpose.
    """
    from ksi_core.leasing import LeaseFence
    from ksi_event_contracts.external_artifact_validation import (
        ArtifactInspectionOutcomeV1,
        ArtifactOutcome,
        ExternalArtifactInspectionReportV1,
        ExternalInspectionMeasurementPayloadV1,
        SealedArtifactBindingV1,
    )

    inspections = fixture.app.state.external_artifact_inspection_store
    revision = fixture._current_revision  # noqa: SLF001
    subject = fixture._current_subject  # noqa: SLF001
    policy = fixture._inspection_policy  # noqa: SLF001
    assert policy.policy_digest is not None and policy.parser_build_digest is not None
    now = datetime.now(UTC)
    issued = inspections.issue_after_seal(subject, now=now)
    assert issued.request is not None
    fence = LeaseFence(str(uuid4()), str(uuid4()), 0)
    leased = inspections.claim(
        issued.request.request_id, fence, now, organization_id="org-a"
    )
    assert leased.fence is not None and leased.request is not None
    dsm = next(
        entry
        for entry in revision.manifest.entries
        if entry.kind.value == "dsm"
        or str(entry.kind).endswith("DSM")
    )
    observed = "sha256:" + dsm.observed_sha256
    payload = ExternalInspectionMeasurementPayloadV1(
        subject_digest=subject.canonical_digest(),
        sealed_manifest_digest=subject.manifest_digest,
        inspection_policy_digest=policy.policy_digest,
        inspector_build_digest=policy.parser_build_digest,
        artifact_bindings=(
            SealedArtifactBindingV1(artifact_id=dsm.artifact_id, observed_sha256=observed),
        ),
        outcomes=(
            ArtifactInspectionOutcomeV1(
                artifact_id=dsm.artifact_id,
                observed_sha256=observed,
                outcome=ArtifactOutcome.REJECTED,
                reason=reason,
            ),
        ),
    )
    report = ExternalArtifactInspectionReportV1(
        report_id="inspection-report-current-rejected",
        request_id=leased.request.request_id,
        subject=subject,
        subject_digest=subject.canonical_digest(),
        sealed_manifest_digest=subject.manifest_digest,
        inspection_policy_digest=policy.policy_digest,
        inspector_build_digest=policy.parser_build_digest,
        measurement_payload=payload,
        worker_instance_id=leased.fence.worker_instance_id,
        lease_acquisition_id=leased.fence.lease_acquisition_id,
        lease_generation=leased.fence.lease_generation,
        reported_at=now,
    ).sealed()
    recorded = inspections.record_report(
        leased.request.request_id, leased.fence, report, now, organization_id="org-a"
    )
    assert recorded.report is not None and recorded.verdict.value == "REPORTED"


def test_readiness_known_rejection_is_not_pending(tmp_path: Path) -> None:
    """A terminal REJECTED outcome classifies as rejected, never pending.

    The contracts require REJECTED/NOT_APPLICABLE outcomes to carry a typed
    reason and no measurements; the readiness diagnostic must not relabel
    that known terminal state as pending. Durable create stays coarse and
    readiness reads append nothing.
    """
    fixture = build_local_analysis_api_fixture(
        tmp_path, v2_dsm_only=True, real_inspection=True, ai_egress_allowed=True
    )
    try:
        _record_rejected_current_inspection(fixture)
        client = TestClient(fixture.app)
        body = _selectors(fixture)
        path = _readiness_path(fixture)
        before = _journal_bytes(fixture)

        readiness = client.post(path, headers=fixture.operator_headers(), json=body)
        assert readiness.status_code == 200, readiness.text
        payload = readiness.json()
        assert payload["suitabilityState"] == "BLOCKED"
        assert payload["calculationIdentityDigest"] is None
        assert {item["code"] for item in payload["blockers"]} == {
            "READINESS_INSPECTION_PENDING",
            "READINESS_INSPECTION_REJECTED",
        }
        by_epoch = {(item["code"], item["epoch"]) for item in payload["blockers"]}
        assert ("READINESS_INSPECTION_REJECTED", "CURRENT") in by_epoch
        assert ("READINESS_INSPECTION_PENDING", "BASELINE") in by_epoch
        assert ("READINESS_INSPECTION_PENDING", "CURRENT") not in by_epoch
        assert ("READINESS_INSPECTION_REJECTED", "BASELINE") not in by_epoch
        assert "cutM3" not in readiness.text and "netM3" not in readiness.text
        assert _journal_bytes(fixture) == before

        created = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": "rejected-stays-coarse"},
            json=body,
        )
        assert created.status_code == 202, created.text
        assert created.json()["suitabilityState"] == "BLOCKED"
        assert {item["code"] for item in created.json()["blockers"]} == {
            "ESSENTIAL_INPUT_UNAVAILABLE"
        }
    finally:
        fixture.close()


def _register_v3_dsm(
    client: TestClient,
    fixture: Any,
    *,
    order_id: str,
    submission_id: str,
    basis: str,
    content: bytes,
) -> str:
    """Register and seal one V3 DSM-only revision with DATE_ONLY/UNKNOWN capture."""
    from ksi_core.domains.observations.epoch_identity import observation_epoch_id
    from ksi_event_contracts.external_reconstruction import (
        ExternalReconstructionSubmissionV3,
    )

    order = fixture.app.state.observation_work_order_store.get(
        order_id, organization_id="org-a"
    )
    assert order is not None
    artifact_id = "dsm-" + submission_id
    wire: dict[str, Any] = {
        "contractVersion": "external-reconstruction-submission.v3",
        "submissionId": submission_id,
        "revision": 1,
        "organizationId": "org-a",
        "siteId": "site-a",
        "observationEpochId": observation_epoch_id(order),
        "submittedAt": "2026-09-30T00:00:00Z",
        "submittedBy": "analysis-local-operator",
        "executionResponsibility": "customer_operator",
        "executionLocus": "customer_workstation",
        "producerDeclaration": {
            "producerKnowledge": "UNKNOWN",
            "softwareName": None,
            "softwareVersion": None,
            "buildIdentifier": None,
            "producerRunIdentifier": None,
            "configurationDigest": None,
            "completedAt": None,
            "sourceNote": "readiness probe",
        },
        "inputDeclaration": {
            "rawMediaStoredByKsi": False,
            "originalRetentionLocus": "unknown",
            "originalRetentionDetail": "readiness probe",
            "localInputManifestDigest": None,
            "imageCount": None,
            "captureStartedAt": None,
            "captureEndedAt": None,
            "captureDate": "2021-08-17" if basis == "DATE_ONLY" else None,
            "captureBasis": basis,
            "upstreamSource": None,
            "derivativeExport": None,
        },
        "artifacts": [
            {
                "artifactId": artifact_id,
                "kind": "dsm",
                "fileName": artifact_id + ".tif",
                "format": "GeoTIFF",
                "contentType": "application/octet-stream",
                "declaredSha256": hashlib.sha256(content).hexdigest(),
                "declaredSizeBytes": len(content),
                "declaredCrs": "EPSG:5186",
                "declaredVerticalReference": None,
                "declaredGsdM": None,
            }
        ],
    }
    wire["submissionDigest"] = ExternalReconstructionSubmissionV3.digest_for_wire(wire)
    registered = client.post(
        f"/v1/observation-work-orders/{order_id}/external-reconstruction-submissions-v3",
        headers={**fixture.operator_headers(), "Idempotency-Key": "v3-" + submission_id},
        json=wire,
    )
    assert registered.status_code == 201, registered.text
    ref = registered.json()["submissionRef"]
    grants = client.post(
        f"/v1/observation-work-orders/{order_id}/external-reconstruction-submissions/"
        f"{ref}/revisions/1/upload-grants",
        headers=fixture.operator_headers(),
    )
    assert grants.status_code == 200, grants.text
    fixture.storage.put_bytes(
        grants.json()["grants"][0]["objectKey"],
        content,
        content_type="application/octet-stream",
    )
    sealed = client.post(
        f"/v1/observation-work-orders/{order_id}/external-reconstruction-submissions/"
        f"{ref}/revisions/1/seal",
        headers=fixture.operator_headers(),
    )
    assert sealed.status_code == 200, sealed.text
    return ref


def test_readiness_v3_date_only_and_unknown_pair_yields_capture_blockers(
    tmp_path: Path,
) -> None:
    """Actually registered V3 DATE_ONLY/UNKNOWN pairs preflight precisely.

    Both revisions are sealed V3 DSM-only records with no exact capture
    interval, so the candidate-options read excludes them while pure
    readiness names the per-epoch capture blocker without numbers or records.
    """
    fixture = build_local_analysis_api_fixture(
        tmp_path, v2_dsm_only=True, real_inspection=True, ai_egress_allowed=True
    )
    try:
        client = TestClient(fixture.app)
        date_only_ref = _register_v3_dsm(
            client,
            fixture,
            order_id=fixture.baseline.work_order_id,
            submission_id="v3-dateonly-dsm",
            basis="DATE_ONLY",
            content=b"v3-dateonly-dsm-bytes",
        )
        unknown_ref = _register_v3_dsm(
            client,
            fixture,
            order_id=fixture.current.work_order_id,
            submission_id="v3-unknown-dsm",
            basis="UNKNOWN",
            content=b"v3-unknown-dsm-bytes",
        )
        body = {
            "baseline": {
                "workOrderId": fixture.baseline.work_order_id,
                "submissionRef": date_only_ref,
                "revision": 1,
            },
            "current": {
                "workOrderId": fixture.current.work_order_id,
                "submissionRef": unknown_ref,
                "revision": 1,
            },
        }
        options = client.get(
            f"/v1/sites/{fixture.site_id}/analysis-observations",
            headers=fixture.operator_headers(),
        )
        assert options.status_code == 200
        option_refs = {item["selector"]["submissionRef"] for item in options.json()["items"]}
        assert date_only_ref not in option_refs
        assert unknown_ref not in option_refs

        before = _journal_bytes(fixture)
        readiness = client.post(
            _readiness_path(fixture), headers=fixture.operator_headers(), json=body
        )
        assert readiness.status_code == 200, readiness.text
        payload = readiness.json()
        assert payload["suitabilityState"] == "BLOCKED"
        assert payload["calculationIdentityDigest"] is None
        assert payload["coverageCheck"] == "REQUIRES_WORKER_VALIDATION"
        assert {item["code"] for item in payload["blockers"]} == {
            "READINESS_CAPTURE_INTERVAL_UNAVAILABLE"
        }
        assert {item["epoch"] for item in payload["blockers"]} == {"BASELINE", "CURRENT"}
        assert "cutM3" not in readiness.text and "netM3" not in readiness.text
        AnalysisReadinessViewV1.model_validate(payload)
        assert _journal_bytes(fixture) == before

        created = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": "v3-capture-coarse"},
            json=body,
        )
        assert created.status_code == 202, created.text
        assert {item["code"] for item in created.json()["blockers"]} == {
            "ESSENTIAL_INPUT_UNAVAILABLE"
        }
    finally:
        fixture.close()


def test_readiness_mcp_tool_calls_core_route_with_typed_parity_and_denied_egress(
    tmp_path: Path,
) -> None:
    """The MCP adapter reaches the Core readiness route; consent gates it."""
    import asyncio

    from ksi_analysis_mcp.config import AdapterConfig
    from ksi_analysis_mcp.core_client import CoreAdapterError, CoreAnalysisClient

    canned = AnalysisReadinessViewV1(
        site_id="site-a",
        work_area_id="area-a",
        baseline=AnalysisObservationSelectorV1(
            work_order_id="wo-b",
            submission_ref="ers-v1-" + "a" * 64,
            revision=1,
        ),
        current=AnalysisObservationSelectorV1(
            work_order_id="wo-c",
            submission_ref="ers-v1-" + "b" * 64,
            revision=1,
        ),
        suitability_state=AnalysisSuitabilityStateV1.EVALUATED,
        blockers=(),
        checked_at=datetime(2026, 10, 25, tzinfo=UTC),
        calculation_identity_digest="sha256:" + "c" * 64,
    ).model_dump(by_alias=True, mode="json")
    state: dict[str, Any] = {"mode": "ok", "seen": {}}

    class _CoreHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            state["seen"] = {
                "path": self.path,
                "body": json.loads(raw),
                "authorization": self.headers.get("Authorization"),
                "idempotency": self.headers.get("Idempotency-Key"),
            }
            if self.path != "/v2/sites/site-a/work-areas/area-a/analysis-readiness":
                body = json.dumps({"detail": "ANALYSIS_RESOURCE_NOT_FOUND"}).encode()
                self.send_response(404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if state["mode"] == "denied":
                body = json.dumps({"detail": "AI_EGRESS_NOT_ALLOWED"}).encode()
                self.send_response(403)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            body = json.dumps(canned).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            if state["mode"] != "no-ack":
                self.send_header("X-KSI-External-AI-Egress", "ALLOWED")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _CoreHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        token_file = tmp_path / "mcp-readiness-token"
        token_file.write_text("readiness-probe-token", encoding="ascii")
        token_file.chmod(0o600)
        client = CoreAnalysisClient(
            AdapterConfig.from_values(
                core_origin=f"http://127.0.0.1:{server.server_port}",
                token_file=str(token_file),
            )
        )
        arguments: dict[str, Any] = {
            "siteId": "site-a",
            "workAreaId": "area-a",
            "baseline": canned["baseline"],
            "current": canned["current"],
        }
        assert asyncio.run(client.invoke("ksi_check_analysis_readiness", arguments)) == canned
        assert state["seen"]["path"] == (
            "/v2/sites/site-a/work-areas/area-a/analysis-readiness"
        )
        assert state["seen"]["authorization"] == "Bearer readiness-probe-token"
        assert state["seen"]["idempotency"] is None
        assert state["seen"]["body"] == {
            "baseline": canned["baseline"],
            "current": canned["current"],
        }

        state["mode"] = "denied"
        try:
            asyncio.run(client.invoke("ksi_check_analysis_readiness", arguments))
        except CoreAdapterError as exc:
            assert exc.code == "AI_EGRESS_NOT_ALLOWED"
        else:
            raise AssertionError("denied egress must surface a typed adapter error")

        state["mode"] = "no-ack"
        try:
            asyncio.run(client.invoke("ksi_check_analysis_readiness", arguments))
        except CoreAdapterError as exc:
            assert exc.code == "CORE_EGRESS_ACKNOWLEDGMENT_MISSING"
        else:
            raise AssertionError("missing ack must surface a typed adapter error")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_oidc_restricted_operator_reaches_readiness_and_asset_description(
    tmp_path: Path,
) -> None:
    """Mapped OIDC operators preflight own scope; foreign scope stays hidden."""
    from ksi_core.identity.auth import _OIDC_SCOPED_OPERATOR_ROUTE_ALLOWLIST
    from test_oidc_route_scope import _install_oidc

    assert (
        "POST",
        "/v2/sites/{site_id}/work-areas/{work_area_id}/analysis-readiness",
    ) in _OIDC_SCOPED_OPERATOR_ROUTE_ALLOWLIST
    assert (
        "GET",
        "/v2/sites/{site_id}/work-areas/{work_area_id}/spatial-assets/{asset_ref}",
    ) in _OIDC_SCOPED_OPERATOR_ROUTE_ALLOWLIST

    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        passed_checkpoint_epochs=("BASELINE", "CURRENT"),
    )
    try:
        client = TestClient(fixture.app)
        body = _selectors(fixture)
        denied_create = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.viewer_headers(), "Idempotency-Key": "oidc-viewer-noexec"},
            json=body,
        )
        assert denied_create.status_code == 403

        token, _key = _install_oidc(fixture)
        headers = {"Authorization": f"Bearer {token}"}
        readiness = client.post(
            _readiness_path(fixture), headers=headers, json=body
        )
        assert readiness.status_code == 200, readiness.text
        assert readiness.json()["suitabilityState"] == "EVALUATED"
        foreign = client.post(
            f"/v2/sites/site-outside-grant/work-areas/{fixture.work_area_id}"
            "/analysis-readiness",
            headers=headers,
            json=body,
        )
        assert foreign.status_code == 404
        asset = client.get(
            f"/v2/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}"
            "/spatial-assets/no-such-asset",
            headers=headers,
        )
        assert asset.status_code == 404
        assert asset.json() == {"detail": "SITE_SPATIAL_ASSET_NOT_FOUND"}
    finally:
        fixture.close()


def test_readiness_snapshot_is_coherent_under_concurrent_evidence_mutation(
    tmp_path: Path,
) -> None:
    """Decision and diagnostics stay paired while evidence facts change.

    Concurrent preflights during revoke/restore cycles must each validate as
    the canonical contract and append nothing; the restored state must equal
    the original. The typed snapshot path (not a second store round-trip)
    is what guarantees the pairing.
    """
    from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
        AnalysisAssessmentRequestV2,
        AnalysisEpochSelectionV2,
        ReadinessPreview,
    )
    from ksi_event_contracts.external_relative_volume_analysis import AdmissionV2

    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        passed_checkpoint_epochs=("BASELINE", "CURRENT"),
        ai_egress_allowed=True,
    )
    try:
        client = TestClient(fixture.app)
        body = _selectors(fixture)
        path = _readiness_path(fixture)
        wiring = fixture.app.state.external_analysis_wiring

        snapshot = wiring.assessments.preview_readiness_snapshot(
            organization_id="org-a",
            request=AnalysisAssessmentRequestV2(
                request_id="snapshot-type-probe",
                work_area_id=fixture.work_area_id,
                baseline=AnalysisEpochSelectionV2(subject=fixture._baseline_subject),  # noqa: SLF001
                current=AnalysisEpochSelectionV2(subject=fixture._current_subject),  # noqa: SLF001
                idempotency_key="snapshot-type-probe",
            ),
            now=datetime.now(UTC),
        )
        assert isinstance(snapshot, ReadinessPreview)
        assert isinstance(snapshot.admission, AdmissionV2)
        assert snapshot.details == ()
        assert snapshot.admission.calculation_identity_digest is not None

        # A moved snapshot projects the defensive reassessment state explicitly.
        original_guard = wiring.assessments._prepared_is_locally_current  # noqa: SLF001
        wiring.assessments._prepared_is_locally_current = lambda *a, **k: False  # noqa: SLF001
        try:
            stale = client.post(path, headers=fixture.operator_headers(), json=body)
        finally:
            wiring.assessments._prepared_is_locally_current = original_guard  # noqa: SLF001
        assert stale.status_code == 200
        assert stale.json()["suitabilityState"] == "REASSESSMENT_REQUIRED"
        assert stale.json()["blockers"] == [
            {"code": "REASSESSMENT_REQUIRED", "epoch": None, "evidenceRef": None, "detail": None}
        ]

        admitted = client.post(path, headers=fixture.operator_headers(), json=body)
        assert admitted.json()["suitabilityState"] == "EVALUATED"
        before = _journal_bytes(fixture)
        context = fixture._retained_contexts[0]  # noqa: SLF001
        context_digest = context.context_digest
        assert context_digest is not None
        stop = threading.Event()
        failures: list[BaseException] = []

        def hammer() -> None:
            while not stop.is_set():
                try:
                    response = client.post(
                        path, headers=fixture.operator_headers(), json=body
                    )
                    assert response.status_code == 200
                    AnalysisReadinessViewV1.model_validate(response.json())
                except BaseException as exc:  # noqa: BLE001
                    failures.append(exc)
                    stop.set()

        with ThreadPoolExecutor(max_workers=4) as pool:
            workers = [pool.submit(hammer) for _ in range(4)]
            for _ in range(10):
                fixture.revoke_evidence_context(context_digest)
                fixture.restore_evidence_context(context_digest)
            stop.set()
            for worker in workers:
                worker.result(timeout=120)
        assert not failures
        restored = client.post(path, headers=fixture.operator_headers(), json=body)
        assert _without_checked_at(restored.json()) == _without_checked_at(admitted.json())
        assert _journal_bytes(fixture) == before
    finally:
        fixture.close()


def _record_measured_inspection(
    fixture: Any, *, revision: Any, subject: Any, report_id: str
) -> None:
    """Store a terminal MEASURED inspection outcome with synthetic-style facts.

    Mirrors the fixture's synthetic inspection shape (axis-aligned grid,
    EPSG:5186/EGM96) against the real sealed DSM bytes, so the epoch
    resolves exactly like a measured lane report.
    """
    import hashlib as _hashlib

    from ksi_core.leasing import LeaseFence
    from ksi_event_contracts.external_artifact_validation import (
        ArtifactInspectionOutcomeV1,
        ArtifactOutcome,
        ExternalArtifactInspectionReportV1,
        ExternalInspectionMeasurementPayloadV1,
        NodataRepresentation,
        ObservedVerticalReferenceV1,
        RasterMeasurementsV1,
        SealedArtifactBindingV1,
    )

    inspections = fixture.app.state.external_artifact_inspection_store
    policy = fixture._inspection_policy  # noqa: SLF001
    assert policy.policy_digest is not None and policy.parser_build_digest is not None
    now = datetime.now(UTC)
    issued = inspections.issue_after_seal(subject, now=now)
    assert issued.request is not None
    fence = LeaseFence(str(uuid4()), str(uuid4()), 0)
    leased = inspections.claim(
        issued.request.request_id, fence, now, organization_id="org-a"
    )
    assert leased.fence is not None and leased.request is not None
    dsm = next(
        entry
        for entry in revision.manifest.entries
        if entry.kind.value == "dsm" or str(entry.kind).endswith("DSM")
    )
    observed = "sha256:" + dsm.observed_sha256
    payload = ExternalInspectionMeasurementPayloadV1(
        subject_digest=subject.canonical_digest(),
        sealed_manifest_digest=subject.manifest_digest,
        inspection_policy_digest=policy.policy_digest,
        inspector_build_digest=policy.parser_build_digest,
        artifact_bindings=(
            SealedArtifactBindingV1(artifact_id=dsm.artifact_id, observed_sha256=observed),
        ),
        outcomes=(
            ArtifactInspectionOutcomeV1(
                artifact_id=dsm.artifact_id,
                observed_sha256=observed,
                outcome=ArtifactOutcome.MEASURED,
                measurements=RasterMeasurementsV1(
                    observed_crs_identifier="EPSG:5186",
                    observed_crs_wkt="PROJCRS[EPSG:5186]",
                    observed_crs_digest="sha256:"
                    + _hashlib.sha256(b"observed-crs-5186").hexdigest(),
                    observed_vertical_reference=ObservedVerticalReferenceV1(
                        identifier="EPSG:5773", basis="EGM96 height"
                    ),
                    transform=(1.0, 0.0, 0.0, 0.0, -1.0, 10.0),
                    footprint_wkt="POLYGON((0 0,10 0,10 10,0 10,0 0))",
                    footprint_digest="sha256:" + _hashlib.sha256(b"footprint-dsm").hexdigest(),
                    width=2,
                    height=2,
                    band_count=1,
                    dtype="float32",
                    layout="striped",
                    nodata_representation=NodataRepresentation.NONE,
                    valid_pixel_count=4,
                ),
            ),
        ),
    )
    report = ExternalArtifactInspectionReportV1(
        report_id=report_id,
        request_id=leased.request.request_id,
        subject=subject,
        subject_digest=subject.canonical_digest(),
        sealed_manifest_digest=subject.manifest_digest,
        inspection_policy_digest=policy.policy_digest,
        inspector_build_digest=policy.parser_build_digest,
        measurement_payload=payload,
        worker_instance_id=leased.fence.worker_instance_id,
        lease_acquisition_id=leased.fence.lease_acquisition_id,
        lease_generation=leased.fence.lease_generation,
        reported_at=now,
    ).sealed()
    recorded = inspections.record_report(
        leased.request.request_id, leased.fence, report, now, organization_id="org-a"
    )
    assert recorded.report is not None and recorded.verdict.value == "REPORTED"


def test_readiness_negative_is_recomputed_under_guard_not_stale(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A negative prepared at the old gap cannot survive as a verdict.

    The exact negative prerequisite (inspection pending on both epochs) is
    flipped to measured *between preparation and the guard* — the precise
    interleaving the old out-of-guard prepare-then-verify order mishandled
    (stale coarse BLOCKED with empty fresh details). The snapshot must
    return the fresh admission with coherent details, and the read path
    itself must append nothing.
    """
    from contextlib import contextmanager

    from ksi_core.domains.external.quantity.external_relative_volume_analysis import (
        AnalysisAssessmentRequestV2,
        AnalysisEpochSelectionV2,
    )
    from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
    from ksi_event_contracts.external_relative_volume_analysis import AdmissionV2

    fixture = build_local_analysis_api_fixture(
        tmp_path, v2_dsm_only=True, real_inspection=True, ai_egress_allowed=True
    )
    try:
        store = fixture.app.state.external_analysis_wiring.assessments
        request = AnalysisAssessmentRequestV2(
            request_id="negative-gap-probe",
            work_area_id=fixture.work_area_id,
            baseline=AnalysisEpochSelectionV2(subject=fixture._baseline_subject),  # noqa: SLF001
            current=AnalysisEpochSelectionV2(subject=fixture._current_subject),  # noqa: SLF001
            idempotency_key="negative-gap-probe",
        )
        # The old out-of-guard verdict for this pair: coarse and blocked.
        # (Pure preparation; the no-writes property is asserted on the
        # snapshot calls below, whose journals are snapshotted separately.)
        stale = store._prepare_for_organization(  # noqa: SLF001
            organization_id="org-a", request=request, now=datetime.now(UTC)
        )
        assert isinstance(stale, AdmissionV2)
        assert stale.reason_codes == ("ESSENTIAL_INPUT_UNAVAILABLE",)

        # Inject the prerequisite flip at the exact old seam: on first guard
        # entry (i.e. after the old prepare, before its guard), complete both
        # inspections. The old order projected the stale coarse verdict here.
        real_guarded = ExternalAuthorityCurrentnessCoordinator.guarded_read
        injected = {"done": False}

        @contextmanager
        def _gap_guarded(self: Any) -> Any:
            if not injected["done"]:
                injected["done"] = True
                _record_measured_inspection(
                    fixture,
                    revision=fixture._baseline_revision,  # noqa: SLF001
                    subject=fixture._baseline_subject,  # noqa: SLF001
                    report_id="inspection-report-baseline-measured",
                )
                _record_measured_inspection(
                    fixture,
                    revision=fixture._current_revision,  # noqa: SLF001
                    subject=fixture._current_subject,  # noqa: SLF001
                    report_id="inspection-report-current-measured",
                )
            with real_guarded(self):
                yield

        monkeypatch.setattr(
            ExternalAuthorityCurrentnessCoordinator, "guarded_read", _gap_guarded
        )
        fresh = store.preview_readiness_snapshot(
            organization_id="org-a", request=request, now=datetime.now(UTC)
        )
        monkeypatch.undo()
        assert injected["done"]
        assert fresh is not None
        assert fresh.admission.reason_codes != ("ESSENTIAL_INPUT_UNAVAILABLE",)
        assert fresh.details == ()
        assert fresh.admission.calculation_identity_digest is not None

        # The read path itself appended nothing: only the injected setup wrote.
        journals_after_gap = _journal_bytes(fixture)
        repeat = store.preview_readiness_snapshot(
            organization_id="org-a", request=request, now=datetime.now(UTC)
        )
        assert repeat is not None
        # assessed_at moves per call by design; the suitability-relevant
        # projection (disposition, reasons, identity, details) is stable.
        assert (
            repeat.admission.disposition,
            repeat.admission.reason_codes,
            repeat.admission.calculation_identity_digest,
            repeat.details,
        ) == (
            fresh.admission.disposition,
            fresh.admission.reason_codes,
            fresh.admission.calculation_identity_digest,
            fresh.details,
        )
        assert _journal_bytes(fixture) == journals_after_gap

        client = TestClient(fixture.app)
        body = _selectors(fixture)
        view = client.post(
            _readiness_path(fixture), headers=fixture.operator_headers(), json=body
        )
        assert view.status_code == 200, view.text
        assert view.json()["suitabilityState"] == "PROVISIONAL_ACCURACY_UNVERIFIED"
        assert "CHECKPOINT_EVIDENCE_ABSENT" in view.json()["limitationCodes"]
    finally:
        fixture.close()
