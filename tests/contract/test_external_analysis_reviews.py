"""V2 review attaches only to the exact immutable calculation/evaluations.

These tests use generated raster fixtures, not customer export/accuracy evidence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from analysis_api_local_fixture import build_local_analysis_api_fixture
from fastapi.testclient import TestClient
from ksi_core.domains.external.quantity.external_analysis_reviews import (
    AnalysisReviewConflict,
    AnalysisReviewRecoveryError,
    AnalysisReviewSource,
    AnalysisReviewStore,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.identity.auth import Role
from ksi_core.identity.oidc_subject_registry import OidcSubjectRegistry
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_analysis_review import AnalysisReviewReceiptV2
from ksi_processing_controller.external_analysis_core_client import ExternalAnalysisCoreClient
from ksi_processing_controller.external_analysis_worker import (
    ProcessingWorkerRuntimeIdentityV1,
    run_once,
)
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)
from test_external_analysis_api import _active_analysis_activation
from test_external_analysis_real_inspection_lane_integration import _CoreAndObjectServers
from test_oidc_route_scope import _install_oidc


def _completed_fixture(path: Path) -> tuple[Any, Any, dict[str, str], str]:
    fixture = build_local_analysis_api_fixture(
        path, v2_dsm_only=True, analysis_activation=_active_analysis_activation(path)
    )
    token, _ = _install_oidc(fixture)
    headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(fixture.app)
    created = client.post(
        f"/v2/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
        headers={**headers, "Idempotency-Key": "review-analysis"},
        json={
            "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
            "current": fixture.current.model_dump(by_alias=True, mode="json"),
        },
    )
    assert created.status_code == 202, created.text
    with _CoreAndObjectServers(fixture) as servers:
        facts = fixture.app.state.external_analysis_wiring.assessments._runtime
        runtime = ProcessingWorkerRuntimeIdentityV1(
            worker_executable_digest=facts.worker_executable_digest,
            worker_build_digest=facts.worker_build_digest,
            runtime_image_version=facts.runtime_image_version,
            runtime_image_oci_digest=facts.runtime_image_oci_digest,
            dependency_lock_digest=facts.dependency_lock_digest,
        )
        transport = ExternalObjectTransportPolicyV1(
            endpoints=(
                TrustedObjectEndpointV1(origin=servers.object_origin, addresses=("127.0.0.1",)),
            ),
            max_header_bytes=16_384,
            max_object_bytes=4_000_000,
            max_chunk_bytes=4096,
        )
        with ExternalAnalysisCoreClient(
            base_url=servers.core_origin,
            worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
            worker_instance_id="review-test-worker",
        ) as worker:
            assert run_once(worker, runtime, transport)
    base = f"/v2/sites/{fixture.site_id}/analyses/{created.json()['analysisId']}"
    assert client.get(base, headers=headers).json()["executionState"] == "COMPLETED"
    return fixture, client, headers, base


def test_oidc_review_binds_exact_v2_target_and_retry_replays(tmp_path: Path) -> None:
    fixture, client, headers, base = _completed_fixture(tmp_path)
    replay = None
    try:
        target_response = client.get(base + "/review-target", headers=headers)
        assert target_response.status_code == 200, target_response.text
        target = target_response.json()
        assert target["resultRevision"] == 1
        assert [item["epoch"] for item in target["evaluations"]] == ["BASELINE", "CURRENT"]
        assert all(item["revision"] == 1 for item in target["evaluations"])
        request = {
            "target": target,
            "decision": "ACKNOWLEDGED",
            "comment": "Use only with stated limitations.",
        }
        response = client.post(
            base + "/reviews", headers={**headers, "Idempotency-Key": "review-once"}, json=request
        )
        assert response.status_code == 201, response.text
        receipt = response.json()
        assert receipt["target"] == target
        assert receipt["reviewerId"] == "pilot-mapped-operator"
        assert receipt["factualLimitations"] == [
            "HUMAN_REVIEW_IS_NOT_ACCURACY_VALIDATION",
            "HUMAN_REVIEW_IS_NOT_FIELD_OR_FLIGHT_AUTHORIZATION",
            "RELATIVE_VOLUME_IS_NOT_SETTLEMENT_OR_COMPLETION_PROOF",
        ]
        retry = client.post(
            base + "/reviews", headers={**headers, "Idempotency-Key": "review-once"}, json=request
        )
        assert retry.status_code == 201 and retry.json() == receipt
        changed = {**request, "comment": "different"}
        assert (
            client.post(
                base + "/reviews",
                headers={**headers, "Idempotency-Key": "review-once"},
                json=changed,
            ).status_code
            == 409
        )
        listed = client.get(base + "/reviews", headers=headers)
        assert listed.json()["items"] == [receipt]
        fixture.close()
        replay = build_local_analysis_api_fixture(tmp_path, replay_of=fixture)
        replay_token, _ = _install_oidc(replay)
        after = TestClient(replay.app).get(
            base + "/reviews", headers={"Authorization": f"Bearer {replay_token}"}
        )
        assert after.status_code == 200 and after.json()["items"] == [receipt]
    finally:
        (replay or fixture).close()


@pytest.mark.parametrize(
    "field", ["reportDigest", "calculationIdentityDigest", "admissionDigest", "resultId"]
)
def test_review_rejects_rebound_target(tmp_path: Path, field: str) -> None:
    fixture, client, headers, base = _completed_fixture(tmp_path)
    try:
        response = client.get(base + "/review-target", headers=headers)
        assert response.status_code == 200, response.text
        target = response.json()
        target[field] = "wrong-result" if field == "resultId" else "sha256:" + "f" * 64
        rejected = client.post(
            base + "/reviews",
            headers={**headers, "Idempotency-Key": "rebound"},
            json={"target": target, "decision": "ACKNOWLEDGED", "comment": "No rebind"},
        )
        assert rejected.status_code == 409
        assert client.get(base + "/reviews", headers=headers).json()["items"] == []
    finally:
        fixture.close()


def test_review_retains_history_but_cannot_acknowledge_later_failed_evidence(
    tmp_path: Path,
) -> None:
    fixture, client, headers, base = _completed_fixture(tmp_path)
    try:
        target = client.get(base + "/review-target", headers=headers).json()
        request = {
            "target": target,
            "decision": "ACKNOWLEDGED",
            "comment": "Exact historical result",
        }
        posted = client.post(
            base + "/reviews",
            headers={**headers, "Idempotency-Key": "before-failure"},
            json=request,
        )
        assert posted.status_code == 201, posted.text
        fixture.append_failed_current_checkpoint_evaluation()
        assert client.get(base, headers=headers).json()["result"] is None
        assert client.get(base + "/review-target", headers=headers).status_code == 409
        rejected = client.post(
            base + "/reviews", headers={**headers, "Idempotency-Key": "after-failure"}, json=request
        )
        assert rejected.status_code == 409, rejected.text
        assert client.get(base + "/reviews", headers=headers).json()["items"] == [posted.json()]
        replay = client.post(
            base + "/reviews",
            headers={**headers, "Idempotency-Key": "before-failure"},
            json=request,
        )
        assert replay.status_code == 201 and replay.json() == posted.json()
    finally:
        fixture.close()


def test_review_append_rechecks_real_mutation_after_prepared_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture, client, headers, base = _completed_fixture(tmp_path)
    try:
        source = fixture.app.state.external_analysis_wiring.reviews.source
        target = client.get(base + "/review-target", headers=headers).json()
        original = source.current

        def interleaved(*args: Any, **kwargs: Any) -> Any:
            prepared = original(*args, **kwargs)
            fixture.append_failed_current_checkpoint_evaluation()
            return prepared

        # Deterministic schedule only: use the real evidence mutation and currentness check.
        monkeypatch.setattr(source, "current", interleaved)
        posted = client.post(
            base + "/reviews",
            headers={**headers, "Idempotency-Key": "raced-review"},
            json={
                "target": target,
                "decision": "ACKNOWLEDGED",
                "comment": "Must recheck before append",
            },
        )
        assert posted.status_code == 409, posted.text
        assert client.get(base + "/reviews", headers=headers).json()["items"] == []
    finally:
        fixture.close()


@pytest.mark.parametrize("bad_field", ["report_digest", "admission_digest", "evaluations"])
def test_malformed_internal_review_source_is_typed_unavailable(
    tmp_path: Path, bad_field: str
) -> None:
    fixture, _, _, base = _completed_fixture(tmp_path)
    try:
        source = fixture.app.state.external_analysis_wiring.reviews.source
        analysis_id = base.split("/")[-1]
        admission = source.assessments.get_history(analysis_id, organization_id="org-a").admission
        intent = source.intents.get(analysis_id, organization_id="org-a")
        report = source.calculations.get_history(
            intent.calculation_request_id, organization_id="org-a"
        ).report
        if bad_field == "report_digest":
            report = report.model_copy(update={"report_digest": None})
        elif bad_field == "admission_digest":
            admission = admission.model_copy(update={"admission_digest": None})
        else:
            admission = admission.model_copy(update={"evaluation_revisions": ()})
        with pytest.raises(AnalysisReviewConflict, match="ANALYSIS_REVIEW_RESULT_UNAVAILABLE"):
            AnalysisReviewSource.target(admission, report)
    finally:
        fixture.close()


def test_review_body_cannot_claim_authority_and_never_recalculates(tmp_path: Path) -> None:
    fixture, client, headers, base = _completed_fixture(tmp_path)
    try:
        target = client.get(base + "/review-target", headers=headers).json()
        request = {"target": target, "decision": "ACKNOWLEDGED", "comment": "Human use review"}
        paths = [
            tmp_path / name
            for name in (
                "external-analysis-assessments.jsonl",
                "external-analysis-calculations.jsonl",
            )
        ]
        before = [path.read_bytes() for path in paths]
        for field in ("organizationId", "siteId", "workAreaId", "reviewerId"):
            assert (
                client.post(
                    base + "/reviews",
                    headers={**headers, "Idempotency-Key": field},
                    json={**request, field: "forged"},
                ).status_code
                == 422
            )
        assert client.post(base + "/reviews", headers=headers, json=request).status_code == 400
        assert (
            client.post(
                base + "/reviews", headers={**headers, "Idempotency-Key": " "}, json=request
            ).status_code
            == 400
        )
        assert client.get(base + "/reviews?limit=0", headers=headers).status_code == 422
        assert client.get(base + "/reviews?cursor=" + "x" * 81, headers=headers).status_code == 422
        assert (
            client.post(
                base + "/reviews",
                headers={**headers, "Idempotency-Key": "real-review"},
                json=request,
            ).status_code
            == 201
        )
        assert [path.read_bytes() for path in paths] == before
    finally:
        fixture.close()


def test_review_routes_recheck_current_site_area_role_and_revocation(tmp_path: Path) -> None:
    fixture, client, headers, base = _completed_fixture(tmp_path)
    try:
        target = client.get(base + "/review-target", headers=headers).json()
        request = {"target": target, "decision": "ACKNOWLEDGED", "comment": "No grant bypass"}
        verifier = fixture.app.state.oidc_verifier
        current = verifier._subject_registry
        entries = list(current._mappings.values())
        assert len(entries) == 1
        original = entries[0]
        for field, grant in (
            ("allowed_site_ids", frozenset({"other-site"})),
            ("allowed_work_area_ids", frozenset({"other-area"})),
        ):
            verifier._subject_registry = OidcSubjectRegistry(
                {(original.issuer, original.subject): replace(original, **{field: grant})}
            )
            assert client.get(base + "/review-target", headers=headers).status_code == 404
            assert client.get(base + "/reviews", headers=headers).status_code == 404
            assert (
                client.post(
                    base + "/reviews", headers={**headers, "Idempotency-Key": field}, json=request
                ).status_code
                == 404
            )
        verifier._subject_registry = OidcSubjectRegistry(
            {(original.issuer, original.subject): replace(original, role=Role.VIEWER)}
        )
        assert client.get(base + "/review-target", headers=headers).status_code == 200
        assert (
            client.post(
                base + "/reviews", headers={**headers, "Idempotency-Key": "viewer"}, json=request
            ).status_code
            == 403
        )
        verifier._subject_registry = OidcSubjectRegistry(
            {(original.issuer, original.subject): replace(original, status="REVOKED")}
        )
        assert client.get(base + "/review-target", headers=headers).status_code == 401
        assert client.get(base + "/reviews", headers=headers).status_code == 401
        assert (
            client.post(
                base + "/reviews", headers={**headers, "Idempotency-Key": "revoked"}, json=request
            ).status_code
            == 401
        )
    finally:
        fixture.close()


def test_policy_expiry_withholds_new_review_but_keeps_historical_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Advance the review clock, not policy contents or journal authority."""
    from ksi_core.domains.external.quantity import external_analysis_reviews as review_module

    fixture, client, headers, base = _completed_fixture(tmp_path)
    try:
        target = client.get(base + "/review-target", headers=headers).json()
        request = {"target": target, "decision": "ACKNOWLEDGED", "comment": "Historical use review"}
        receipt = client.post(
            base + "/reviews", headers={**headers, "Idempotency-Key": "before-expiry"}, json=request
        )
        assert receipt.status_code == 201, receipt.text
        future = datetime.now(UTC) + timedelta(hours=2)

        class ReviewClock(datetime):
            @classmethod
            def now(cls, tz: Any = None) -> Any:
                return future

        monkeypatch.setattr(review_module, "datetime", ReviewClock)
        assert client.get(base + "/review-target", headers=headers).status_code == 409
        assert (
            client.post(
                base + "/reviews",
                headers={**headers, "Idempotency-Key": "after-expiry"},
                json=request,
            ).status_code
            == 409
        )
        assert client.get(base + "/reviews", headers=headers).json()["items"] == [receipt.json()]
        retry = client.post(
            base + "/reviews", headers={**headers, "Idempotency-Key": "before-expiry"}, json=request
        )
        assert retry.status_code == 201 and retry.json() == receipt.json()
    finally:
        fixture.close()


def test_review_rejects_wrong_evaluation_revision_and_uncompleted_result(tmp_path: Path) -> None:
    fixture, client, headers, base = _completed_fixture(tmp_path)
    try:
        response = client.get(base + "/review-target", headers=headers)
        assert response.status_code == 200, response.text
        target = response.json()
        target["evaluations"][0]["revision"] += 1
        assert (
            client.post(
                base + "/reviews",
                headers={**headers, "Idempotency-Key": "revision-rebind"},
                json={
                    "target": target,
                    "decision": "NEEDS_FOLLOW_UP",
                    "comment": "Cannot silently review a new evaluation",
                },
            ).status_code
            == 409
        )
        blocked = client.post(
            f"/v2/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**headers, "Idempotency-Key": "reversed-input"},
            json={
                "baseline": fixture.current.model_dump(by_alias=True, mode="json"),
                "current": fixture.baseline.model_dump(by_alias=True, mode="json"),
            },
        )
        assert blocked.status_code == 202, blocked.text
        blocked_base = f"/v2/sites/{fixture.site_id}/analyses/{blocked.json()['analysisId']}"
        assert client.get(blocked_base + "/review-target", headers=headers).status_code == 409
        assert (
            client.get(
                base.replace("/sites/site-a/", "/sites/another-site/") + "/reviews", headers=headers
            ).status_code
            == 404
        )
    finally:
        fixture.close()


def test_rehashed_review_cannot_replay_a_forged_source(tmp_path: Path) -> None:
    fixture, client, headers, base = _completed_fixture(tmp_path)
    source = fixture.app.state.external_analysis_wiring.reviews.source
    try:
        target = client.get(base + "/review-target", headers=headers).json()
        reviewed = client.post(
            base + "/reviews",
            headers={**headers, "Idempotency-Key": "forged-replay"},
            json={"target": target, "decision": "ACKNOWLEDGED", "comment": "Test replay binding"},
        )
        assert reviewed.status_code == 201, reviewed.text
    finally:
        fixture.close()
    path = tmp_path / "external-analysis-reviews.jsonl"
    event = json.loads(path.read_text())
    event["receipt"]["target"]["reportDigest"] = "sha256:" + "e" * 64
    event["receipt"]["receiptDigest"] = None
    receipt = AnalysisReviewReceiptV2.model_validate(event["receipt"]).sealed()
    event["receipt"] = receipt.model_dump(by_alias=True, mode="json")
    request = {key: event["receipt"][key] for key in ("target", "decision", "comment")}
    event["requestDigest"] = "sha256:" + hashlib.sha256(canonical_json_bytes(request)).hexdigest()
    event.pop("eventDigest")
    event["eventDigest"] = "sha256:" + hashlib.sha256(canonical_json_bytes(event)).hexdigest()
    path.write_text(json.dumps(event) + "\n")
    with pytest.raises(AnalysisReviewRecoveryError, match="source binding"):
        AnalysisReviewStore(DurableJournal(path), source=source)


def test_review_paging_and_mcp_human_boundary(tmp_path: Path) -> None:
    fixture, client, headers, base = _completed_fixture(tmp_path)
    try:
        target = client.get(base + "/review-target", headers=headers).json()
        for index in range(3):
            response = client.post(
                base + "/reviews",
                headers={**headers, "Idempotency-Key": f"review-{index}"},
                json={"target": target, "decision": "ACKNOWLEDGED", "comment": f"Review {index}"},
            )
            assert response.status_code == 201, response.text
        first = client.get(base + "/reviews?limit=2", headers=headers).json()
        assert len(first["items"]) == 2 and first["nextCursor"] is not None
        second = client.get(
            base + "/reviews", params={"limit": 2, "cursor": first["nextCursor"]}, headers=headers
        ).json()
        assert len(second["items"]) == 1 and second["nextCursor"] is None
        assert client.get(base + "/reviews?limit=51", headers=headers).status_code == 422
        assert client.get(base + "/reviews?cursor=unrelated", headers=headers).status_code == 409
        assert (
            client.post(
                base + "/reviews",
                headers={**fixture.mcp_client_headers(), "Idempotency-Key": "mcp-cannot-review"},
                json={"target": target, "decision": "ACKNOWLEDGED", "comment": "Not human"},
            ).status_code
            == 403
        )
    finally:
        fixture.close()
