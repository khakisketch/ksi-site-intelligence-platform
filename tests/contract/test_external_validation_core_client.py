"""External-only Core HTTP wire tests; no contained or live-storage claim."""

from __future__ import annotations

import base64
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
import httpx
import pytest
from botocore.config import Config
from fastapi.testclient import TestClient
from ksi_core.evidence import ObjectStorageObservation
from ksi_core.evidence_s3 import S3EvidenceStorage
from ksi_event_contracts.external_display_artifact import (
    SanitizedDisplayDeclarationV1,
    SanitizedDisplayReceiptV1,
)
from ksi_processing_controller.external_validation_core_client import (
    ExternalCoreClientError,
    ExternalValidationCoreClient,
)
from support.external_artifact_inspection_fixtures import report as inspection_report
from test_external_artifact_inspection_worker import (
    _accepted_report,
    _artifact,
    _fence,
    _policy,
    _request,
)
from test_external_artifact_inspections_api import _active_scoped_app


def _input() -> dict[str, Any]:
    policy = _policy()
    request = _request(policy).model_copy(update={"request_id": "inspection-1"})
    return {
        "verdict": "LEASED",
        "request": request.model_dump(by_alias=True, mode="json"),
        "policy": policy.model_dump(by_alias=True, mode="json"),
        "artifacts": [
            {
                **_artifact().model_dump(by_alias=True, mode="json"),
                "downloadUrl": "https://objects.test/a?signature=private",
                "requiredHeaders": {"x-amz-checksum-sha256": "bound"},
            }
        ],
        "phase": "INSPECTION",
        "nextAction": "INSPECT",
        "acceptedReport": None,
    }


def _client(handler: Any, **kwargs: Any) -> ExternalValidationCoreClient:
    return ExternalValidationCoreClient(
        base_url="https://core.test",
        bearer_token="core-private-token",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


class _CoreTestClientTransport(httpx.BaseTransport):
    """Test-only bridge proving the client binds to assembled Core routes."""

    def __init__(self, core: TestClient) -> None:
        self._core = core
        self.drop_next_suffix: str | None = None

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
        if self.drop_next_suffix is not None and path.endswith(self.drop_next_suffix):
            self.drop_next_suffix = None
            raise httpx.ReadError("test response loss", request=request)
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=response.content,
            request=request,
        )


def _assembled_client(core: TestClient) -> ExternalValidationCoreClient:
    return ExternalValidationCoreClient(
        base_url="https://core.invalid",
        bearer_token="worker-token",
        transport=_CoreTestClientTransport(core),
        monotonic=lambda: 0.0,
    )


def _display_input_and_declaration() -> tuple[dict[str, Any], SanitizedDisplayDeclarationV1]:
    policy = _policy()
    request = _request(policy).model_copy(update={"request_id": "inspection-1"})
    report = _accepted_report(request, policy)
    body = _input()
    body.update(
        request=request.model_dump(by_alias=True, mode="json"),
        policy=policy.model_dump(by_alias=True, mode="json"),
        phase="DISPLAY",
        nextAction="SANITIZE_DISPLAY",
        acceptedReport=report.model_dump(by_alias=True, mode="json"),
    )
    return (
        body,
        SanitizedDisplayDeclarationV1(
            display_id="display-1",
            request_id=request.request_id,
            source_subject_digest=report.subject_digest,
            source_report_digest=report.report_digest,
            policy_digest=report.inspection_policy_digest,
            inspector_build_digest=report.inspector_build_digest,
            declared_derivative_sha256="sha256:" + "9" * 64,
            declared_derivative_size_bytes=123,
            declared_derivative_content_type="image/tiff",
        ),
    )


def test_input_is_fenced_and_capabilities_are_stripped_from_launch_projection() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_input())

    with _client(handler) as client:
        current = client.current_input(
            "inspection-1", _fence(), deadline_monotonic=time.monotonic() + 2
        )
        assert current is not None
        assert "signature" not in current.model_dump_json()
        assert "requiredHeaders" not in current.model_dump_json()
        capability = client.capability_for("inspection-1", _fence(), _artifact())
        assert capability.required_headers == {"x-amz-checksum-sha256": "bound"}
        assert "signature" not in repr(capability)
    assert seen[0].headers["authorization"] == "Bearer core-private-token"
    assert seen[0].headers["X-KSI-Lease-Generation"] == "1"
    assert seen[0].url.path.endswith("/inspections/inspection-1/input")


@pytest.mark.parametrize(
    "alter",
    [
        lambda body: body.update(verdict="POLICY_UNAVAILABLE"),
        lambda body: body["request"].update(requestId="other"),
        lambda body: body.update(unexpected="field"),
        lambda body: body["artifacts"][0].update(observedSizeBytes=True),
        lambda body: body["artifacts"][0].update(downloadUrl="file:///secret"),
        lambda body: body["artifacts"][0].update(requiredHeaders={"Authorization": "secret"}),
    ],
)
def test_malformed_or_unavailable_input_never_publishes_capability(alter: Any) -> None:
    body = _input()
    alter(body)
    with _client(lambda _: httpx.Response(200, json=body)) as client:
        assert (
            client.current_input("inspection-1", _fence(), deadline_monotonic=time.monotonic() + 2)
            is None
        )
        with pytest.raises(ExternalCoreClientError):
            client.capability_for("inspection-1", _fence(), _artifact())


def test_policy_loss_clears_prior_capability() -> None:
    available = True

    def handler(_: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(200, json=_input())
            if available
            else httpx.Response(409, json={"detail": "POLICY_UNAVAILABLE"})
        )

    with _client(handler) as client:
        assert client.current_input(
            "inspection-1", _fence(), deadline_monotonic=time.monotonic() + 2
        )
        available = False
        assert (
            client.current_input("inspection-1", _fence(), deadline_monotonic=time.monotonic() + 2)
            is None
        )
        with pytest.raises(ExternalCoreClientError):
            client.capability_for("inspection-1", _fence(), _artifact())


def test_redirect_and_error_body_never_leak_credentials_or_follow_location() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://attacker.test/?secret=private"})

    with _client(handler) as client:
        with pytest.raises(ExternalCoreClientError) as exc:
            client.list_pending(deadline_monotonic=time.monotonic() + 2)
        assert "private" not in str(exc.value)
    assert len(seen) == 1


@pytest.mark.parametrize(
    "body", [b'{"items":[],"items":[]}', b'{"items":[],"extra":1e999}', b"x" * 300]
)
def test_response_json_is_strict_and_bounded(body: bytes) -> None:
    with (
        _client(lambda _: httpx.Response(200, content=body), maximum_response_bytes=256) as client,
        pytest.raises(ExternalCoreClientError),
    ):
        client.list_pending(deadline_monotonic=time.monotonic() + 2)


def test_expired_deadline_sends_nothing() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("expired operation reached HTTP")

    with _client(handler) as client, pytest.raises(ExternalCoreClientError):
        client.list_pending(deadline_monotonic=time.monotonic() - 1)


def test_claim_uses_generation_zero_then_validates_returned_fence() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "verdict": "LEASED",
                "request": _input()["request"],
                "leaseExpiresAt": "2026-09-09T12:00:00Z",
                "phase": "INSPECTION",
                "fence": _fence().model_dump(by_alias=True, mode="json"),
            },
        )

    with _client(handler) as client:
        lease = client.claim(
            "inspection-1",
            worker_instance_id=_fence().worker_instance_id,
            acquisition_id=_fence().lease_acquisition_id,
            deadline_monotonic=time.monotonic() + 2,
        )
        assert lease.fence == _fence()
    assert seen[0].headers["X-KSI-Lease-Generation"] == "0"
    assert seen[0].content == b""


def test_invalid_server_claim_fence_is_not_accepted() -> None:
    body = {
        "verdict": "LEASED",
        "request": _input()["request"],
        "leaseExpiresAt": "2026-09-09T12:00:00Z",
        "phase": "INSPECTION",
        "fence": {**_fence().model_dump(by_alias=True), "leaseGeneration": 0},
    }
    with (
        _client(lambda _: httpx.Response(200, content=json.dumps(body))) as client,
        pytest.raises(ExternalCoreClientError),
    ):
        client.claim(
            "inspection-1",
            worker_instance_id=_fence().worker_instance_id,
            acquisition_id=_fence().lease_acquisition_id,
            deadline_monotonic=time.monotonic() + 2,
        )


def test_report_submission_requires_exact_fence_and_echo_binding() -> None:
    from test_external_artifact_inspection_worker import _accepted_report

    policy = _policy()
    request = _request(policy).model_copy(update={"request_id": "inspection-1"})
    report = _accepted_report(request, policy)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "verdict": "REPORTED",
                "report": report.model_dump(by_alias=True, mode="json"),
                "phase": "DISPLAY",
            },
        )

    with _client(handler) as client:
        result = client.record_report(
            "inspection-1", _fence(), report, deadline_monotonic=time.monotonic() + 2
        )
        assert result == report
        with pytest.raises(ExternalCoreClientError):
            client.record_report("other", _fence(), report, deadline_monotonic=time.monotonic() + 2)
    assert len(seen) == 1
    assert json.loads(seen[0].content)["reportDigest"] == report.report_digest


def test_heartbeat_checks_returned_fence_and_clears_capability_on_loss() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/input"):
            return httpx.Response(200, json=_input())
        return httpx.Response(
            200,
            json={
                "verdict": "LEASED",
                "request": _input()["request"],
                "leaseExpiresAt": "2026-09-09T12:00:00Z",
                "phase": "INSPECTION",
                "fence": {**_fence().model_dump(by_alias=True), "leaseGeneration": 2},
            },
        )

    with _client(handler) as client:
        assert client.current_input(
            "inspection-1", _fence(), deadline_monotonic=time.monotonic() + 2
        )
        assert not client.heartbeat(
            "inspection-1", _fence(), deadline_monotonic=time.monotonic() + 2
        )
        with pytest.raises(ExternalCoreClientError):
            client.capability_for("inspection-1", _fence(), _artifact())


def test_release_forgets_completed_attempt_capabilities() -> None:
    with _client(lambda _: httpx.Response(200, json=_input())) as client:
        assert client.current_input(
            "inspection-1", _fence(), deadline_monotonic=time.monotonic() + 2
        )
        client.release("inspection-1", _fence())
        with pytest.raises(ExternalCoreClientError):
            client.capability_for("inspection-1", _fence(), _artifact())


def test_late_input_response_cannot_restore_capability_after_release() -> None:
    import threading

    entered, finish = threading.Event(), threading.Event()
    outcomes: list[object] = []

    def handler(_: httpx.Request) -> httpx.Response:
        entered.set()
        assert finish.wait(2)
        return httpx.Response(200, json=_input())

    with _client(handler) as client:
        thread = threading.Thread(
            target=lambda: outcomes.append(
                client.current_input(
                    "inspection-1", _fence(), deadline_monotonic=time.monotonic() + 2
                )
            )
        )
        thread.start()
        try:
            assert entered.wait(2)
            client.release("inspection-1", _fence())
        finally:
            finish.set()
            thread.join(2)
        assert not thread.is_alive()
        assert outcomes == [None]
        with pytest.raises(ExternalCoreClientError):
            client.capability_for("inspection-1", _fence(), _artifact())


def test_cached_input_is_scoped_to_exact_fence_and_full_artifact_binding() -> None:
    with _client(lambda _: httpx.Response(200, json=_input())) as client:
        assert client.current_input(
            "inspection-1", _fence(), deadline_monotonic=time.monotonic() + 2
        )
        with pytest.raises(ExternalCoreClientError):
            client.capability_for(
                "inspection-1", _fence().model_copy(update={"lease_generation": 2}), _artifact()
            )
        with pytest.raises(ExternalCoreClientError):
            client.capability_for("inspection-1", _fence(), _artifact(b"different"))


def test_incomplete_failure_uses_the_current_fence_then_releases_input_authority(
    tmp_path: Any,
) -> None:
    """A bounded runtime failure is Core-owned work state, never a fake report."""
    app, request_id, _policy, _storage, _submission_ref = _active_scoped_app(tmp_path)

    with TestClient(app) as core, _assembled_client(core) as client:
        lease = client.claim(
            request_id,
            worker_instance_id=_fence().worker_instance_id,
            acquisition_id=_fence().lease_acquisition_id,
            deadline_monotonic=1.0,
        )
        assert client.current_input(request_id, lease.fence, deadline_monotonic=1.0) is not None

        result = client.record_incomplete_failure(
            request_id,
            lease.fence,
            "TRANSIENT_SERVICE_UNAVAILABLE",
            deadline_monotonic=1.0,
        )

        assert result.verdict == "QUEUED"
        assert result.phase == "INSPECTION"
        with pytest.raises(ExternalCoreClientError):
            client.capability_for(request_id, lease.fence, _artifact())


@pytest.mark.parametrize(
    "reason", [b"TRANSIENT_SERVICE_UNAVAILABLE", True, 123, "not-a-bounded-code"]
)
def test_incomplete_failure_rejects_noncanonical_reason_before_http(reason: Any) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("invalid failure reason reached Core")

    with _client(handler) as client, pytest.raises(ExternalCoreClientError):
        client.record_incomplete_failure(
            "inspection-1", _fence(), reason, deadline_monotonic=time.monotonic() + 2
        )


def test_display_grant_and_seal_bind_the_accepted_report_on_assembled_core(tmp_path: Any) -> None:
    """A private upload capability becomes public metadata only after Core seals it."""
    app, request_id, policy, storage, _submission_ref = _active_scoped_app(tmp_path)

    with TestClient(app) as core, _assembled_client(core) as client:
        lease = client.claim(
            request_id,
            worker_instance_id=_fence().worker_instance_id,
            acquisition_id=_fence().lease_acquisition_id,
            deadline_monotonic=1.0,
        )
        accepted = inspection_report(request_id=request_id, policy=policy)
        retained = client.record_report(request_id, lease.fence, accepted, deadline_monotonic=1.0)
        current = client.current_input(request_id, lease.fence, deadline_monotonic=1.0)
        assert current is not None
        assert current.phase.value == "DISPLAY"
        assert current.accepted_report == retained
        declaration = SanitizedDisplayDeclarationV1(
            display_id="display-1",
            request_id=request_id,
            source_subject_digest=retained.subject_digest,
            source_report_digest=retained.report_digest,
            policy_digest=retained.inspection_policy_digest,
            inspector_build_digest=retained.inspector_build_digest,
            declared_derivative_sha256="sha256:" + "9" * 64,
            declared_derivative_size_bytes=123,
            declared_derivative_content_type="image/tiff",
        )

        grant = client.grant_display_upload(
            request_id, lease.fence, declaration, deadline_monotonic=1.0
        )

        assert grant.declaration.declaration_digest is not None
        # The retained worker guard polls the same exact DISPLAY before PUT/seal.
        assert client.current_input(request_id, lease.fence, deadline_monotonic=1.0) == current
        assert "storage.invalid" not in repr(grant)
        assert storage.last_put_key is not None
        storage.objects[storage.last_put_key] = ObjectStorageObservation(
            object_key=storage.last_put_key,
            exists=True,
            size_bytes=123,
            sha256="sha256:" + "9" * 64,
            content_type="image/tiff",
        )
        receipt = client.seal_display_upload(request_id, lease.fence, grant, deadline_monotonic=1.0)
        assert receipt.request_id == request_id
        assert receipt.declaration_digest == grant.declaration.declaration_digest
        assert receipt.receipt_digest is not None


def test_display_grant_rejects_a_capability_with_wrong_declared_byte_bindings() -> None:
    """A returned upload capability must bind the exact sealed derivative, not just a URL."""
    current, declaration = _display_input_and_declaration()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/input"):
            return httpx.Response(200, json=current)
        assert request.url.path.endswith("/display-artifacts/upload-grants")
        return httpx.Response(
            200,
            json={
                "verdict": "DECLARATION_RECORDED",
                "phase": "RUNNING",
                "declaration": declaration.sealed().model_dump(by_alias=True, mode="json"),
                "uploadUrl": "https://objects.test/upload?signature=private",
                "requiredHeaders": {
                    "Content-Type": "image/png",
                    "x-amz-checksum-sha256": declaration.declared_derivative_sha256,
                },
            },
        )

    with _client(handler) as client:
        assert (
            client.current_input("inspection-1", _fence(), deadline_monotonic=time.monotonic() + 2)
            is not None
        )
        with pytest.raises(ExternalCoreClientError):
            client.grant_display_upload(
                "inspection-1", _fence(), declaration, deadline_monotonic=time.monotonic() + 2
            )


def test_display_grant_accepts_the_actual_s3_checksum_header() -> None:
    """The private client accepts S3's Base64 SHA-256 wire encoding, not a Core import."""
    current, declaration = _display_input_and_declaration()
    s3_client = boto3.client(
        "s3",
        endpoint_url="https://objects.test",
        aws_access_key_id="test-access-key",
        aws_secret_access_key="test-secret-key",
        region_name="us-east-1",
        config=Config(signature_version="s3v4"),
    )
    capability = S3EvidenceStorage(bucket="ksi-test", client=s3_client).presigned_put_bound_digest(
        "derived/display-1",
        content_type=declaration.declared_derivative_content_type,
        content_digest=declaration.declared_derivative_sha256,
        ttl=timedelta(minutes=5),
    )
    expected_checksum = base64.b64encode(
        bytes.fromhex(declaration.declared_derivative_sha256.removeprefix("sha256:"))
    ).decode("ascii")
    assert capability.required_headers["x-amz-checksum-sha256"] == expected_checksum

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/input"):
            return httpx.Response(200, json=current)
        assert request.url.path.endswith("/display-artifacts/upload-grants")
        return httpx.Response(
            200,
            json={
                "verdict": "DECLARATION_RECORDED",
                "phase": "RUNNING",
                "declaration": declaration.sealed().model_dump(by_alias=True, mode="json"),
                "uploadUrl": capability.upload_url,
                "requiredHeaders": capability.required_headers,
            },
        )

    with _client(handler) as client:
        assert (
            client.current_input("inspection-1", _fence(), deadline_monotonic=time.monotonic() + 2)
            is not None
        )
        grant = client.grant_display_upload(
            "inspection-1", _fence(), declaration, deadline_monotonic=time.monotonic() + 2
        )
    assert grant.required_headers["x-amz-checksum-sha256"] == expected_checksum


@pytest.mark.parametrize(
    "checksum",
    [
        base64.b64encode(bytes.fromhex("8" * 64)).decode("ascii"),
        "sha256:" + "8" * 64,
        "not-a-base64-checksum",
    ],
)
def test_display_grant_rejects_malformed_or_substituted_s3_checksum(checksum: str) -> None:
    current, declaration = _display_input_and_declaration()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/input"):
            return httpx.Response(200, json=current)
        return httpx.Response(
            200,
            json={
                "verdict": "DECLARATION_RECORDED",
                "phase": "RUNNING",
                "declaration": declaration.sealed().model_dump(by_alias=True, mode="json"),
                "uploadUrl": "https://objects.test/upload?signature=private",
                "requiredHeaders": {
                    "Content-Type": declaration.declared_derivative_content_type,
                    "x-amz-checksum-sha256": checksum,
                },
            },
        )

    with _client(handler) as client:
        assert (
            client.current_input("inspection-1", _fence(), deadline_monotonic=time.monotonic() + 2)
            is not None
        )
        with pytest.raises(ExternalCoreClientError):
            client.grant_display_upload(
                "inspection-1", _fence(), declaration, deadline_monotonic=time.monotonic() + 2
            )


def test_release_revokes_display_authority_before_a_late_seal() -> None:
    """A released attempt cannot use a retained private grant to obtain a receipt."""
    current, declaration = _display_input_and_declaration()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/input"):
            return httpx.Response(200, json=current)
        if request.url.path.endswith("/display-artifacts/upload-grants"):
            return httpx.Response(
                200,
                json={
                    "verdict": "DECLARATION_RECORDED",
                    "phase": "RUNNING",
                    "declaration": declaration.sealed().model_dump(by_alias=True, mode="json"),
                    "uploadUrl": "https://objects.test/upload?signature=private",
                    "requiredHeaders": {
                        "Content-Type": declaration.declared_derivative_content_type,
                        "x-amz-checksum-sha256": declaration.declared_derivative_sha256,
                    },
                },
            )
        pytest.fail("released display authority reached Core seal route")

    with _client(handler) as client:
        assert (
            client.current_input("inspection-1", _fence(), deadline_monotonic=time.monotonic() + 2)
            is not None
        )
        grant = client.grant_display_upload(
            "inspection-1", _fence(), declaration, deadline_monotonic=time.monotonic() + 2
        )
        client.release("inspection-1", _fence())
        with pytest.raises(ExternalCoreClientError):
            client.seal_display_upload(
                "inspection-1", _fence(), grant, deadline_monotonic=time.monotonic() + 2
            )


def test_display_seal_rejects_a_receipt_that_is_not_bound_to_the_declaration() -> None:
    """A Core response cannot turn mismatched display metadata into a receipt."""
    current, declaration = _display_input_and_declaration()
    sealed = declaration.sealed()
    assert sealed.declaration_digest is not None
    wrong_receipt = SanitizedDisplayReceiptV1(
        display_id="other-display",
        request_id=sealed.request_id,
        declaration_digest=sealed.declaration_digest,
        source_subject_digest=sealed.source_subject_digest,
        source_report_digest=sealed.source_report_digest,
        policy_digest=sealed.policy_digest,
        inspector_build_digest=sealed.inspector_build_digest,
        observed_derivative_sha256=sealed.declared_derivative_sha256,
        observed_derivative_size_bytes=sealed.declared_derivative_size_bytes,
        observed_derivative_content_type=sealed.declared_derivative_content_type,
        sanitized_display_ref="sda-v1-display-1",
        sealed_at=datetime(2026, 9, 9, tzinfo=UTC),
    ).sealed()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/input"):
            return httpx.Response(200, json=current)
        if request.url.path.endswith("/display-artifacts/upload-grants"):
            return httpx.Response(
                200,
                json={
                    "verdict": "DECLARATION_RECORDED",
                    "phase": "RUNNING",
                    "declaration": sealed.model_dump(by_alias=True, mode="json"),
                    "uploadUrl": "https://objects.test/upload?signature=private",
                    "requiredHeaders": {
                        "Content-Type": sealed.declared_derivative_content_type,
                        "x-amz-checksum-sha256": sealed.declared_derivative_sha256,
                    },
                },
            )
        assert request.url.path.endswith("/display-artifacts/display-1/seal")
        return httpx.Response(
            200,
            json={
                "verdict": "SEALED",
                "phase": "SEALED",
                "receipt": wrong_receipt.model_dump(by_alias=True, mode="json"),
            },
        )

    with _client(handler) as client:
        assert (
            client.current_input("inspection-1", _fence(), deadline_monotonic=time.monotonic() + 2)
            is not None
        )
        grant = client.grant_display_upload(
            "inspection-1", _fence(), declaration, deadline_monotonic=time.monotonic() + 2
        )
        with pytest.raises(ExternalCoreClientError):
            client.seal_display_upload(
                "inspection-1", _fence(), grant, deadline_monotonic=time.monotonic() + 2
            )


def test_display_grant_and_seal_retry_exact_intent_after_lost_core_responses(tmp_path: Any) -> None:
    """Lost grant or seal responses may retry the exact retained declaration, never a new one."""
    app, request_id, policy, storage, _submission_ref = _active_scoped_app(tmp_path)

    with TestClient(app) as core:
        transport = _CoreTestClientTransport(core)
        with ExternalValidationCoreClient(
            base_url="https://core.invalid",
            bearer_token="worker-token",
            transport=transport,
            monotonic=lambda: 0.0,
        ) as client:
            lease = client.claim(
                request_id,
                worker_instance_id=_fence().worker_instance_id,
                acquisition_id=_fence().lease_acquisition_id,
                deadline_monotonic=1.0,
            )
            accepted = inspection_report(request_id=request_id, policy=policy)
            client.record_report(request_id, lease.fence, accepted, deadline_monotonic=1.0)
            assert client.current_input(request_id, lease.fence, deadline_monotonic=1.0) is not None
            declaration = SanitizedDisplayDeclarationV1(
                display_id="display-1",
                request_id=request_id,
                source_subject_digest=accepted.subject_digest,
                source_report_digest=accepted.report_digest,
                policy_digest=accepted.inspection_policy_digest,
                inspector_build_digest=accepted.inspector_build_digest,
                declared_derivative_sha256="sha256:" + "9" * 64,
                declared_derivative_size_bytes=123,
                declared_derivative_content_type="image/tiff",
            )
            transport.drop_next_suffix = "/display-artifacts/upload-grants"
            with pytest.raises(ExternalCoreClientError):
                client.grant_display_upload(
                    request_id, lease.fence, declaration, deadline_monotonic=1.0
                )
            grant = client.grant_display_upload(
                request_id, lease.fence, declaration, deadline_monotonic=1.0
            )
            assert storage.last_put_key is not None
            storage.objects[storage.last_put_key] = ObjectStorageObservation(
                object_key=storage.last_put_key,
                exists=True,
                size_bytes=123,
                sha256="sha256:" + "9" * 64,
                content_type="image/tiff",
            )
            transport.drop_next_suffix = "/seal"
            with pytest.raises(ExternalCoreClientError):
                client.seal_display_upload(request_id, lease.fence, grant, deadline_monotonic=1.0)
            receipt = client.seal_display_upload(
                request_id, lease.fence, grant, deadline_monotonic=1.0
            )
            assert receipt.declaration_digest == grant.declaration.declaration_digest
