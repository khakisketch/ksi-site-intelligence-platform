"""HTTP boundary tests for Core-owned external artifact inspection work."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import httpx
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
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import ObjectStorageObservation
from ksi_core.external_artifact_inspections import (
    ExternalArtifactInspectionStore,
    mount_external_artifact_inspections,
)
from ksi_core.external_display_artifacts import ExternalDisplayArtifactStore
from ksi_core.external_reconstruction import (
    ExternalReconstructionRevision,
    build_external_reconstruction_submission_ref,
)
from ksi_core.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicyAuthorityPort,
    PolicyAuthorityRecord,
    authorized_policy_body_digest,
)
from ksi_core.sites import SiteStore
from ksi_event_contracts.external_artifact_validation import ExternalValidationPolicyV1
from support.external_artifact_inspection_fixtures import (
    ACQUISITION,
    WORKER_A,
    SyntheticStorage,
    policy_template,
    report,
    sealed_manifest,
    sealed_submission,
    subject,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_HOSTILE_JSON_BODIES = (
    '{"x": NaN}',
    '{"x": Infinity}',
    '{"x": -Infinity}',
    '{"x": 1e400}',
    '{"x": "a\\ud800b"}',
    '{"x": {"y": ["a\\udfffb"]}}',
)


class _Task7AClientTransport(httpx.BaseTransport):
    """Bridge the current repository client to assembled Core without network IO."""

    def __init__(self, core: TestClient) -> None:
        self._core = core

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.query:
            path += "?" + request.url.query.decode("ascii")
        response = self._core.request(
            request.method,
            path,
            content=request.read(),
            headers=dict(request.headers),
        )
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=response.content,
            request=request,
        )


def _registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=_digest("operator-token"),
                principal=Principal(
                    principal_id="operator-1",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                    organization_id="organization-1",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest("worker-token"),
                principal=Principal(
                    principal_id="worker-1",
                    kind=PrincipalKind.PROCESSING_WORKER,
                    role=None,
                    device_id=None,
                    organization_id="organization-1",
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=_digest("foreign-worker-token"),
                principal=Principal(
                    principal_id="worker-foreign",
                    kind=PrincipalKind.PROCESSING_WORKER,
                    role=None,
                    device_id=None,
                    organization_id="organization-foreign",
                ),
            ),
        ]
    )


class _EmptyInspectionStore:
    def list_pending(self, limit: int, *, organization_id: str | None = None) -> tuple[()]:
        assert limit == 50
        assert organization_id == "organization-1"
        return ()


class _ScopedIngress:
    """Synthetic sealed ingress only; it exposes no object key through HTTP."""

    def __init__(self) -> None:
        submission = sealed_submission()
        self.record = ExternalReconstructionRevision(
            work_order_id="work-order-1",
            work_order_version=1,
            cycle_number=1,
            observation_epoch_id=submission.observation_epoch_id,
            submission=submission,
            registered_at=datetime(2026, 9, 7, tzinfo=UTC),
            registered_by="operator-1",
            bindings=(("ortho", "external-reconstruction/v1/synthetic-ortho"),),
            manifest=sealed_manifest(),
        )
        self.ref = build_external_reconstruction_submission_ref(
            organization_id=submission.organization_id,
            work_order_id=self.record.work_order_id,
            submission_id=submission.submission_id,
        )

    def sealed_revisions_snapshot(self) -> tuple[ExternalReconstructionRevision, ...]:
        return (self.record,)

    def resolve_submission_ref(
        self,
        work_order_id: str,
        submission_ref: str,
        *,
        organization_id: str,
        site_id: str,
    ) -> str | None:
        if (
            work_order_id == self.record.work_order_id
            and submission_ref == self.ref
            and organization_id == "organization-1"
            and site_id == "site-1"
        ):
            return self.record.submission.submission_id
        return None

    def get(
        self,
        work_order_id: str,
        submission_id: str,
        revision: int,
        *,
        organization_id: str,
        site_id: str,
    ) -> ExternalReconstructionRevision | None:
        if (
            work_order_id == self.record.work_order_id
            and submission_id == self.record.submission.submission_id
            and revision == self.record.submission.revision
            and organization_id == "organization-1"
            and site_id == "site-1"
        ):
            return self.record
        return None


class _ScopedWorkOrders:
    def get(self, work_order_id: str, *, organization_id: str) -> SimpleNamespace | None:
        if work_order_id == "work-order-1" and organization_id == "organization-1":
            return SimpleNamespace(site_id="site-1")
        return None


def _scoped_app(tmp_path: Path) -> tuple[FastAPI, _ScopedIngress]:
    ingress = _ScopedIngress()
    inspection_store = ExternalArtifactInspectionStore(
        DurableJournal(tmp_path / "inspections.jsonl"),
        policy_registry=ExternalValidationPolicyRegistry(
            DurableJournal(tmp_path / "policies.jsonl"),
            clock=lambda: datetime(2026, 9, 7, tzinfo=UTC),
        ),
        external_reconstruction=ingress,
        clock=lambda: datetime(2026, 9, 7, tzinfo=UTC),
    )
    app = FastAPI()
    app.state.auth_registry = _registry()
    mount_external_artifact_inspections(
        app,
        inspection_store,
        reconstruction=ingress,
        work_orders=_ScopedWorkOrders(),
    )
    return app, ingress


class _Authority(PolicyAuthorityPort):
    def __init__(self, record: PolicyAuthorityRecord) -> None:
        assert record.digest is not None
        self.record = record

    def resolve(self, authority_record_digest: str, now: datetime) -> PolicyAuthorityRecord | None:
        del now
        return self.record if authority_record_digest == self.record.digest else None


def _active_scoped_app(
    tmp_path: Path,
) -> tuple[FastAPI, str, object, SyntheticStorage, str]:
    ingress = _ScopedIngress()
    now = datetime.now(UTC)
    template = policy_template()
    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=(subject(),),
        permitted_uses=("INSPECTION", "DISPLAY"),
        authorized_actor_ids=("authority",),
        active_from=now - timedelta(minutes=1),
        active_until=now + timedelta(days=1),
        synthetic_test_only=True,
    ).sealed()
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policies.jsonl"),
        authority_port=_Authority(authority),
        clock=lambda: now,
    )
    registry.admit(policy, actor="authority", now=now)
    storage = SyntheticStorage()
    display = ExternalDisplayArtifactStore(
        DurableJournal(tmp_path / "display.jsonl"),
        policy_registry=registry,
        storage=storage,
        clock=lambda: now,
    )
    inspections = ExternalArtifactInspectionStore(
        DurableJournal(tmp_path / "inspections.jsonl"),
        policy_registry=registry,
        external_reconstruction=ingress,
        storage=storage,
        display_store=display,
        clock=lambda: now,
    )
    issued = inspections.issue_after_seal(subject(), now=now)
    assert issued.request is not None
    app = create_app(
        auth_registry=_registry(),
        evidence_storage=storage,
        site_store=SiteStore(DurableJournal(tmp_path / "sites.jsonl")),
        external_reconstruction_store=ingress,  # type: ignore[arg-type]
        observation_work_order_store=_ScopedWorkOrders(),  # type: ignore[arg-type]
        external_display_artifact_store=display,
        external_artifact_inspection_store=inspections,
    )
    app.state.external_validation_policy_registry = registry
    return app, issued.request.request_id, policy, storage, ingress.ref


def test_internal_inspection_list_allows_only_processing_workers() -> None:
    """Removing the worker permission gate must make this test fail."""
    app = FastAPI()
    app.state.auth_registry = _registry()
    mount_external_artifact_inspections(
        app,
        _EmptyInspectionStore(),  # type: ignore[arg-type]
        reconstruction=object(),
        work_orders=object(),
    )
    client = TestClient(app)

    assert client.get("/v1/internal/external-validation/inspections").status_code == 401
    assert (
        client.get(
            "/v1/internal/external-validation/inspections",
            headers={"Authorization": "Bearer operator-token"},
        ).status_code
        == 403
    )
    response = client.get(
        "/v1/internal/external-validation/inspections",
        headers={"Authorization": "Bearer worker-token"},
    )
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_sealed_revision_reports_pending_policy_without_worker_capabilities(tmp_path: Path) -> None:
    """Dropping the scoped read gate or exposing bound object keys must fail here."""
    app, ingress = _scoped_app(tmp_path)
    response = TestClient(app).get(
        "/v1/observation-work-orders/work-order-1/external-reconstruction-submissions/"
        f"{ingress.ref}/revisions/1/inspection",
        headers={"Authorization": "Bearer operator-token"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "registrationState": "SEALED",
        "sealState": "SEALED",
        "inspection": {
            "state": "INSPECTION_PENDING_POLICY",
            "request": None,
            "phase": None,
            "outcome": None,
            "report": None,
        },
        "display": {
            "state": "PENDING_INSPECTION",
            "sanitizedDisplayRef": None,
            "receiptDigest": None,
        },
    }


def test_worker_lease_and_input_are_fenced_and_never_expose_object_keys(tmp_path: Path) -> None:
    """Removing an exact worker fence or exposing a private key must fail this test."""
    app, request_id, _policy, _storage, _submission_ref = _active_scoped_app(tmp_path)
    client = TestClient(app)
    acquire_headers = {
        "Authorization": "Bearer worker-token",
        "X-KSI-Worker-Instance-Id": WORKER_A,
        "X-KSI-Lease-Acquisition-Id": ACQUISITION,
        "X-KSI-Lease-Generation": "0",
    }
    lease = client.post(
        f"/v1/internal/external-validation/inspections/{request_id}/lease",
        headers=acquire_headers,
    )
    assert lease.status_code == 200, lease.text
    assert lease.json()["verdict"] == "LEASED"
    assert lease.json()["fence"] == {
        "workerInstanceId": WORKER_A,
        "leaseAcquisitionId": ACQUISITION,
        "leaseGeneration": 1,
    }
    fence_headers = {
        "Authorization": "Bearer worker-token",
        "X-KSI-Worker-Instance-Id": WORKER_A,
        "X-KSI-Lease-Acquisition-Id": ACQUISITION,
        "X-KSI-Lease-Generation": "1",
    }
    current = client.get(
        f"/v1/internal/external-validation/inspections/{request_id}/input",
        headers=fence_headers,
    )
    assert current.status_code == 200
    body = current.json()
    assert body["verdict"] == "LEASED"
    assert body["phase"] == "INSPECTION"
    assert body["nextAction"] == "INSPECT"
    assert body["acceptedReport"] is None
    assert body["artifacts"][0]["downloadUrl"].startswith("https://storage.invalid/get/")
    assert body["artifacts"][0]["requiredHeaders"] == {}
    assert "objectKey" not in str(body)
    assert (
        client.get(
            f"/v1/internal/external-validation/inspections/{request_id}/input",
            headers={**fence_headers, "Authorization": "Bearer operator-token"},
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/v1/internal/external-validation/inspections/{request_id}/input",
            headers={**fence_headers, "Authorization": "Bearer foreign-worker-token"},
        ).status_code
        == 404
    )


def test_task_7a_client_accepts_a_pre_report_heartbeat_from_assembled_core(
    tmp_path: Path,
) -> None:
    """A claimed inspection must renew as INSPECTION before any report is retained."""
    app, request_id, _policy, _storage, _submission_ref = _active_scoped_app(tmp_path)
    from ksi_processing_controller.external_validation_core_client import (
        ExternalValidationCoreClient,
    )

    with TestClient(app) as core:
        authority = ExternalValidationCoreClient(
            base_url="https://core.invalid",
            bearer_token="worker-token",
            transport=_Task7AClientTransport(core),
            monotonic=lambda: 0.0,
        )
        try:
            pending = authority.list_pending(deadline_monotonic=1.0)
            assert [item.request_id for item in pending] == [request_id]
            lease = authority.claim(
                request_id,
                worker_instance_id=WORKER_A,
                acquisition_id=ACQUISITION,
                deadline_monotonic=1.0,
            )
            assert (
                authority.current_input(request_id, lease.fence, deadline_monotonic=1.0) is not None
            )
            assert authority.heartbeat(request_id, lease.fence, deadline_monotonic=1.0)
        finally:
            authority.close()


@pytest.mark.parametrize("raw", _HOSTILE_JSON_BODIES)
@pytest.mark.parametrize(
    "suffix",
    (
        "/report",
        "/incomplete-failure",
        "/display-artifacts/upload-grants",
    ),
)
def test_worker_body_routes_render_hostile_json_as_422(
    tmp_path: Path, suffix: str, raw: str
) -> None:
    """Worker body parsing rejects non-finite and surrogate payloads before mutation."""
    app, request_id, _policy, _storage, _submission_ref = _active_scoped_app(tmp_path)
    client = TestClient(app)
    claim_headers = {
        "Authorization": "Bearer worker-token",
        "X-KSI-Worker-Instance-Id": WORKER_A,
        "X-KSI-Lease-Acquisition-Id": ACQUISITION,
        "X-KSI-Lease-Generation": "0",
    }
    assert (
        client.post(
            f"/v1/internal/external-validation/inspections/{request_id}/lease",
            headers=claim_headers,
        ).status_code
        == 200
    )
    response = client.post(
        f"/v1/internal/external-validation/inspections/{request_id}{suffix}",
        content=raw.encode("utf-8", "surrogatepass"),
        headers={
            **claim_headers,
            "X-KSI-Lease-Generation": "1",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 422, response.text
    assert response.headers["content-type"].startswith("application/json")


def test_public_download_uses_only_a_current_exact_sealed_display_receipt(tmp_path: Path) -> None:
    """Making a display receipt permanent or exposing its object key must fail this test."""
    app, request_id, policy, storage, submission_ref = _active_scoped_app(tmp_path)
    policy = cast(ExternalValidationPolicyV1, policy)
    client = TestClient(app)
    headers = {
        "Authorization": "Bearer worker-token",
        "X-KSI-Worker-Instance-Id": WORKER_A,
        "X-KSI-Lease-Acquisition-Id": ACQUISITION,
        "X-KSI-Lease-Generation": "0",
    }
    assert (
        client.post(
            f"/v1/internal/external-validation/inspections/{request_id}/lease", headers=headers
        ).status_code
        == 200
    )
    fence_headers = {**headers, "X-KSI-Lease-Generation": "1"}
    accepted = report(request_id=request_id, policy=policy)
    assert (
        client.post(
            f"/v1/internal/external-validation/inspections/{request_id}/report",
            headers=fence_headers,
            json=accepted.model_dump(by_alias=True, mode="json"),
        ).status_code
        == 200
    )
    declaration = {
        "displayId": "display-1",
        "requestId": request_id,
        "sourceSubjectDigest": accepted.subject_digest,
        "sourceReportDigest": accepted.report_digest,
        "policyDigest": accepted.inspection_policy_digest,
        "inspectorBuildDigest": accepted.inspector_build_digest,
        "declaredDerivativeSha256": "sha256:" + "9" * 64,
        "declaredDerivativeSizeBytes": 123,
        "declaredDerivativeContentType": "image/tiff",
    }
    granted = client.post(
        f"/v1/internal/external-validation/inspections/{request_id}/display-artifacts/upload-grants",
        headers=fence_headers,
        json=declaration,
    )
    assert granted.status_code == 200, granted.text
    assert storage.last_put_key is not None
    storage.objects[storage.last_put_key] = ObjectStorageObservation(
        object_key=storage.last_put_key,
        exists=True,
        size_bytes=123,
        sha256="sha256:" + "9" * 64,
        content_type="image/tiff",
    )
    wrong_display_id = client.post(
        f"/v1/internal/external-validation/inspections/{request_id}/display-artifacts/not-display-1/seal",
        headers=fence_headers,
    )
    assert wrong_display_id.status_code == 404
    assert app.state.external_display_artifact_store.phase_for(request_id).value != "SEALED"
    sealed = client.post(
        f"/v1/internal/external-validation/inspections/{request_id}/display-artifacts/display-1/seal",
        headers=fence_headers,
    )
    assert sealed.status_code == 200, sealed.text
    receipt = sealed.json()["receipt"]
    stale_retry = client.post(
        f"/v1/internal/external-validation/inspections/{request_id}/display-artifacts/display-1/seal",
        headers={**fence_headers, "X-KSI-Lease-Generation": "999"},
    )
    assert stale_retry.status_code == 409
    assert "receiptDigest" not in stale_retry.text
    download = client.get(
        "/v1/observation-work-orders/work-order-1/external-reconstruction-submissions/"
        f"{submission_ref}/"
        f"revisions/1/display-artifacts/{receipt['sanitizedDisplayRef']}/download",
        headers={"Authorization": "Bearer operator-token"},
    )

    assert download.status_code == 200
    assert download.json() == {
        "sanitizedDisplayRef": receipt["sanitizedDisplayRef"],
        "receiptDigest": receipt["receiptDigest"],
        "observedDerivativeSha256": "sha256:" + "9" * 64,
        "observedDerivativeSizeBytes": 123,
        "observedDerivativeContentType": "image/tiff",
        "downloadUrl": f"https://storage.invalid/get/{storage.last_put_key}",
        "expiresAt": download.json()["expiresAt"],
        "requiredHeaders": {},
    }
    assert "objectKey" not in str(download.json())


def test_policy_revocation_during_display_presigning_returns_no_capability(tmp_path: Path) -> None:
    """Removing the post-presign current-policy recheck must make this test fail."""
    app, request_id, policy, storage, submission_ref = _active_scoped_app(tmp_path)
    policy = cast(ExternalValidationPolicyV1, policy)
    client = TestClient(app)
    headers = {
        "Authorization": "Bearer worker-token",
        "X-KSI-Worker-Instance-Id": WORKER_A,
        "X-KSI-Lease-Acquisition-Id": ACQUISITION,
        "X-KSI-Lease-Generation": "0",
    }
    assert (
        client.post(
            f"/v1/internal/external-validation/inspections/{request_id}/lease", headers=headers
        ).status_code
        == 200
    )
    fence_headers = {**headers, "X-KSI-Lease-Generation": "1"}
    accepted = report(request_id=request_id, policy=policy)
    assert (
        client.post(
            f"/v1/internal/external-validation/inspections/{request_id}/report",
            headers=fence_headers,
            json=accepted.model_dump(by_alias=True, mode="json"),
        ).status_code
        == 200
    )
    declaration = {
        "displayId": "display-1",
        "requestId": request_id,
        "sourceSubjectDigest": accepted.subject_digest,
        "sourceReportDigest": accepted.report_digest,
        "policyDigest": accepted.inspection_policy_digest,
        "inspectorBuildDigest": accepted.inspector_build_digest,
        "declaredDerivativeSha256": "sha256:" + "9" * 64,
        "declaredDerivativeSizeBytes": 123,
        "declaredDerivativeContentType": "image/tiff",
    }
    assert (
        client.post(
            f"/v1/internal/external-validation/inspections/{request_id}/display-artifacts/upload-grants",
            headers=fence_headers,
            json=declaration,
        ).status_code
        == 200
    )
    assert storage.last_put_key is not None
    storage.objects[storage.last_put_key] = ObjectStorageObservation(
        object_key=storage.last_put_key,
        exists=True,
        size_bytes=123,
        sha256="sha256:" + "9" * 64,
        content_type="image/tiff",
    )
    sealed = client.post(
        f"/v1/internal/external-validation/inspections/{request_id}/display-artifacts/display-1/seal",
        headers=fence_headers,
    )
    assert sealed.status_code == 200
    receipt = sealed.json()["receipt"]
    original_presign = storage.presigned_get

    def revoke_then_presign(object_key: str, *, ttl: timedelta) -> str:
        app.state.external_validation_policy_registry.revoke(
            policy.policy_id, policy.version, actor="authority", now=datetime.now(UTC)
        )
        return original_presign(object_key, ttl=ttl)

    storage.presigned_get = revoke_then_presign  # type: ignore[method-assign]
    response = client.get(
        "/v1/observation-work-orders/work-order-1/external-reconstruction-submissions/"
        f"{submission_ref}/revisions/1/display-artifacts/{receipt['sanitizedDisplayRef']}/download",
        headers={"Authorization": "Bearer operator-token"},
    )
    assert response.status_code == 404
