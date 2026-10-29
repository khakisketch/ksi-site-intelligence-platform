"""Bounded Core worker HTTP material is assembled only into the sealed V2 wire."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, mount_auth
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_evidence_validations import (
    ExternalEvidenceValidationStore,
    mount_external_evidence_validations,
)
from ksi_core.external_relative_volume_launch_material import VolumeWorkerLaunchMaterialResolver
from ksi_core.external_relative_volumes import (
    ExternalRelativeVolumeQueuePolicy,
    ExternalRelativeVolumeStore,
)
from ksi_event_contracts.external_evidence import (
    EvidenceCoreVerdict,
    ExternalEvidenceRecordV1,
    ExternalEvidenceValidationRequestV1,
)
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1
from ksi_event_contracts.external_relative_volume import ExternalVolumeMetricsV1
from ksi_event_contracts.inspector_execution_manifest import InspectorExecutionManifestV1
from ksi_processing_controller.external_measurement_container_protocol import (
    build_completed_frame_v2,
    build_prepare_frame_v2,
)
from ksi_processing_controller.external_measurement_core_client import (
    ExternalMeasurementCoreClient,
    ExternalMeasurementCoreClientError,
)
from ksi_processing_controller.external_measurement_result import build_measurement_result
from ksi_processing_controller.external_validation_core_client import (
    ExternalCoreClientError,
    ExternalValidationCoreClient,
)
from test_external_measurement_evidence_binding import with_records
from test_external_measurement_protocol import limits, measurement_manifest_request
from test_external_relative_volumes import (
    _WORKER_TOKEN as _VOLUME_WORKER_TOKEN,
)
from test_external_relative_volumes import (
    _AuthorityPort,
    _launch_client,
    _launch_ready_authority,
    _principal,
    _StaticVolumeEvidence,
    _StaticVolumePolicyRegistry,
)
from test_external_validation_core_client import _CoreTestClientTransport


def _core_client(
    transport: httpx.BaseTransport | None = None, *, base_url: str = "https://core.invalid"
) -> ExternalValidationCoreClient:
    return ExternalValidationCoreClient(
        base_url=base_url,
        bearer_token="worker-private-token",
        transport=transport,
    )


def _volume_launch_with_records() -> tuple[Any, Any]:
    """Use the accepted V2 execution-manifest selection and ordered evidence material."""

    manifest, launch = measurement_manifest_request()
    evidence_launch = with_records()
    evidence_records = evidence_launch.volume_evidence_records
    assert launch.volume_request is not None
    request = launch.volume_request.model_copy(
        update={
            "evidence_record_digests": tuple(
                record.evidence_record_digest for record in evidence_records
            ),
            "request_digest": None,
        },
        deep=True,
    ).sealed()
    return (
        manifest,
        launch.model_copy(
            update={
                "volume_request": request,
                "volume_evidence_records": evidence_records,
                "canonical_input_digest": None,
            },
            deep=True,
        ).sealed(),
    )


def _volume_input(launch: Any) -> dict[str, Any]:
    assert launch.volume_request is not None
    assert launch.volume_execution_policy is not None
    return {
        "verdict": "INPUT_READY",
        "input": {
            "request": launch.volume_request.model_dump(by_alias=True, mode="json"),
            "executionPolicy": launch.volume_execution_policy.model_dump(
                by_alias=True, mode="json"
            ),
            "validationPolicy": launch.validation_policy.model_dump(by_alias=True, mode="json"),
            "volumeEvidenceRecords": [
                record.model_dump(by_alias=True, mode="json")
                for record in launch.volume_evidence_records
            ],
            "inputs": [
                {
                    "role": item.role,
                    "downloadUrl": f"https://objects.invalid/{item.artifact_id}?private=capability",
                    "requiredHeaders": {"x-bound-role": item.role},
                    "expiresAt": "2026-09-09T01:10:00Z",
                }
                for item in launch.inputs
            ],
        },
        "detail": None,
    }


def _lease_response(launch: Any, *, worker_id: str, acquisition_id: str) -> dict[str, Any]:
    assert launch.volume_request is not None
    return {
        "verdict": "LEASED",
        "request": {
            "requestRef": launch.request_id,
            "status": "LEASED",
            "currentWorkOrderId": launch.volume_request.current_work_order_id,
            "decisionDigest": launch.volume_request.decision_digest,
            "issuedAt": launch.volume_request.issued_at.isoformat().replace("+00:00", "Z"),
            "deadlineAt": "2026-09-09T02:00:00Z",
            "reportRef": None,
            "reportDigest": None,
        },
        "fence": {
            "workerInstanceId": worker_id,
            "leaseAcquisitionId": acquisition_id,
            "leaseGeneration": 7,
        },
        "leaseExpiresAt": "2026-09-09T01:05:00Z",
        "detail": None,
    }


def _completed_result(launch: Any, manifest: Any, *, uncertainty_m3: float | None = None) -> Any:
    assert launch.volume_request is not None
    assert launch.volume_execution_policy is not None
    metrics = ExternalVolumeMetricsV1(
        zone_cell_count=4,
        common_valid_cell_count=4,
        zone_area_m2=4.0,
        measured_area_m2=4.0,
        common_valid_fraction=1.0,
        cut_m3=1.0,
        fill_m3=5.0,
        net_m3=4.0,
        threshold_m=launch.volume_execution_policy.threshold_m,
        uncertainty_m3=(
            4.0 * (0.1**2 + 0.1**2) ** 0.5 if uncertainty_m3 is None else uncertainty_m3
        ),
        uncertainty_note="Independent validated checkpoint RMSE was used for both epochs.",
    )
    aggregate = {
        "metricType": "RELATIVE_VOLUME_AGGREGATE_V2",
        "zoneId": launch.volume_request.zone_snapshot.work_area_id,
        "metrics": metrics.model_dump(by_alias=True, mode="json"),
    }
    terminal = build_completed_frame_v2(
        prepare=build_prepare_frame_v2(request=launch, manifest=manifest),
        input_bindings=[item.model_dump(by_alias=True, mode="json") for item in launch.inputs],
        aggregate=aggregate,
    )
    return build_measurement_result(
        terminal=terminal, request=launch, manifest=manifest, limits=limits()
    )


def _checkpoint_core_material() -> tuple[
    Any,
    ExternalEvidenceValidationRequestV1,
    ExternalEvidenceMeasurementContextV1,
    Any,
    dict[str, Any],
]:
    """Build one complete checkpoint lane wire body from accepted V2 contracts."""

    manifest, volume = measurement_manifest_request()
    assert volume.volume_request is not None
    policy = volume.validation_policy.model_copy(
        update={
            "evidence_rule_ids": ("CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",),
            "policy_digest": None,
        },
        deep=True,
    ).sealed()
    assert policy.policy_digest is not None
    subject = volume.volume_request.current.subject
    target = volume.inputs[1]
    context = ExternalEvidenceMeasurementContextV1(
        context_id="checkpoint-context-1",
        subject=subject,
        evidence_manifest_digest="sha256:" + "a" * 64,
        evidence_observed_sha256="sha256:" + "b" * 64,
        evidence_observed_size_bytes=10,
        target_dsm_artifact_id=target.artifact_id,
        target_dsm_observed_sha256=target.observed_sha256,
        policy_digest=policy.policy_digest,
        measurement_execution_manifest_digest=manifest.canonical_body_digest(),
        rule_id="CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",
        csv_horizontal_crs="EPSG:5186",
        csv_vertical_reference_digest="sha256:" + "c" * 64,
        minimum_checkpoint_count=3,
        maximum_checkpoint_count=10,
        maximum_rmse_m=1.0,
        maximum_abs_mean_error_m=1.0,
        maximum_abs_error_m=1.0,
        independent_attestation=None,
        authorized_actor_ids=("authority",),
        active_from=datetime(2026, 9, 9, tzinfo=UTC),
        active_until=datetime(2026, 9, 10, tzinfo=UTC),
        synthetic_test_only=True,
    ).sealed()
    request = ExternalEvidenceValidationRequestV1(
        validation_id="checkpoint-validation-1",
        evidence_manifest_digest=context.evidence_manifest_digest,
        subject_digest=subject.canonical_digest(),
        target_dsm_observed_sha256=target.observed_sha256,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        policy_digest=policy.policy_digest,
        issued_at=datetime(2026, 9, 9, 1, tzinfo=UTC),
        idempotency_key="checkpoint-idempotency-1",
    )
    return (
        manifest,
        request,
        context,
        policy,
        {
            "verdict": "LEASED",
            "request": request.model_dump(by_alias=True, mode="json"),
            "context": context.model_dump(by_alias=True, mode="json"),
            "validationPolicy": policy.model_dump(by_alias=True, mode="json"),
            "bindings": [
                {
                    "role": "CHECKPOINT_CSV",
                    "artifactId": "checkpoint-evidence-1",
                    "observedSha256": context.evidence_observed_sha256,
                    "observedSizeBytes": context.evidence_observed_size_bytes,
                    "contentType": "text/csv",
                    "downloadUrl": "https://objects.invalid/checkpoints?private=capability",
                    "requiredHeaders": {"x-bound-role": "checkpoint"},
                },
                {
                    "role": "TARGET_DSM",
                    "artifactId": target.artifact_id,
                    "observedSha256": target.observed_sha256,
                    "observedSizeBytes": target.observed_size_bytes,
                    "contentType": "image/tiff",
                    "downloadUrl": "https://objects.invalid/dsm?private=capability",
                    "requiredHeaders": {"x-bound-role": "target"},
                },
            ],
        },
    )


def _completed_checkpoint_result(launch: Any, manifest: Any) -> Any:
    terminal = build_completed_frame_v2(
        prepare=build_prepare_frame_v2(request=launch, manifest=manifest),
        input_bindings=[item.model_dump(by_alias=True, mode="json") for item in launch.inputs],
        aggregate={
            "metricType": "CHECKPOINT_VALIDATION_AGGREGATE_V2",
            "measuredCheckpointCount": 3,
            "meanErrorM": 0.1,
            "maeM": 0.1,
            "rmseM": 0.1,
            "maxAbsErrorM": 0.1,
        },
    )
    return build_measurement_result(
        terminal=terminal, request=launch, manifest=manifest, limits=limits()
    )


class _VolumeCoreLoopback:
    """Owned stdlib loopback that exercises real HTTP status/body behavior."""

    def __init__(self, launch: Any, *, worker_id: str, acquisition_id: str) -> None:
        self.launch = launch
        self.worker_id = worker_id
        self.acquisition_id = acquisition_id
        self.drop_first_lease = True
        self.received_reports: list[dict[str, Any]] = []
        self.errors: list[BaseException] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                return

            def _reply(self, status: int, body: dict[str, Any]) -> None:
                encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                result = json.loads(raw)
                assert isinstance(result, dict)
                return result

            def do_GET(self) -> None:  # noqa: N802
                try:
                    if self.path == "/v1/internal/external-validation/relative-volumes?limit=50":
                        self._reply(
                            200,
                            {
                                "items": [
                                    {
                                        "requestRef": outer.launch.request_id,
                                        "issuedAt": "2026-09-09T01:00:00Z",
                                    }
                                ]
                            },
                        )
                    elif self.path == "/v1/internal/external-validation/inspections?limit=50":
                        self._reply(200, {"items": []})
                    elif self.path == (
                        "/v1/internal/external-validation/relative-volumes/"
                        f"{outer.launch.request_id}/input"
                    ):
                        assert self.headers["X-KSI-Lease-Generation"] == "7"
                        self._reply(200, _volume_input(outer.launch))
                    else:
                        raise AssertionError(self.path)
                except BaseException as exc:  # pragma: no cover - asserted by caller
                    outer.errors.append(exc)
                    self._reply(500, {})

            def do_POST(self) -> None:  # noqa: N802
                try:
                    lease_path = (
                        "/v1/internal/external-validation/relative-volumes/"
                        f"{outer.launch.request_id}/lease"
                    )
                    report_path = (
                        "/v1/internal/external-validation/relative-volumes/"
                        f"{outer.launch.request_id}/report"
                    )
                    if self.path == lease_path:
                        assert self._body() == {
                            "workerInstanceId": outer.worker_id,
                            "leaseAcquisitionId": outer.acquisition_id,
                            "leaseGeneration": 0,
                            "mode": "CLAIM",
                        }
                        if outer.drop_first_lease:
                            outer.drop_first_lease = False
                            self.close_connection = True
                            return
                        self._reply(
                            201,
                            _lease_response(
                                outer.launch,
                                worker_id=outer.worker_id,
                                acquisition_id=outer.acquisition_id,
                            ),
                        )
                    elif self.path == report_path:
                        assert self.headers["X-KSI-Lease-Generation"] == "7"
                        outer.received_reports.append(self._body())
                        assert outer.launch.volume_request is not None
                        self._reply(
                            201,
                            {
                                "verdict": "REPORTED",
                                "request": {
                                    "requestRef": outer.launch.request_id,
                                    "status": "SUCCEEDED",
                                    "currentWorkOrderId": (
                                        outer.launch.volume_request.current_work_order_id
                                    ),
                                    "decisionDigest": outer.launch.volume_request.decision_digest,
                                    "issuedAt": (
                                        outer.launch.volume_request.issued_at.isoformat().replace(
                                            "+00:00", "Z"
                                        )
                                    ),
                                    "deadlineAt": (
                                        outer.launch.volume_request.issued_at + timedelta(hours=1)
                                    )
                                    .isoformat()
                                    .replace("+00:00", "Z"),
                                    "reportRef": "external-relative-volume-report-loopback",
                                    "reportDigest": "sha256:" + "f" * 64,
                                },
                                "fence": None,
                                "leaseExpiresAt": None,
                                "detail": None,
                            },
                        )
                    else:
                        raise AssertionError(self.path)
                except BaseException as exc:  # pragma: no cover - asserted by caller
                    outer.errors.append(exc)
                    self._reply(500, {})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host = cast(str, self._server.server_address[0])
        port = self._server.server_address[1]
        return f"http://{host}:{port}"

    def __enter__(self) -> _VolumeCoreLoopback:
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._server.shutdown()
        self._thread.join(timeout=1)
        self._server.server_close()
        assert not self._thread.is_alive()


def test_private_core_request_keeps_default_200_only_but_allows_explicit_mutation_status() -> None:
    with _core_client(httpx.MockTransport(lambda _: httpx.Response(201, json={}))) as core:
        with pytest.raises(ExternalCoreClientError):
            core._request("POST", "/private", deadline=time.monotonic() + 1)  # noqa: SLF001
        assert (
            core._request(  # noqa: SLF001
                "POST", "/private", deadline=time.monotonic() + 1, accepted_statuses=(200, 201)
            )
            == {}
        )


def test_volume_core_body_response_loss_retry_v2_launch_and_exact_observed_report() -> None:
    manifest, expected_launch = _volume_launch_with_records()
    worker_id, acquisition_id = str(uuid4()), str(uuid4())
    with _VolumeCoreLoopback(
        expected_launch, worker_id=worker_id, acquisition_id=acquisition_id
    ) as loopback:
        shared = _core_client(base_url=loopback.base_url)
        client = ExternalMeasurementCoreClient(core_client=shared)
        try:
            pending = client.list_pending(
                "RELATIVE_VOLUME", deadline_monotonic=time.monotonic() + 1
            )
            assert pending[0].request_id == expected_launch.request_id
            with pytest.raises(ExternalMeasurementCoreClientError):
                client.claim(
                    "RELATIVE_VOLUME",
                    expected_launch.request_id,
                    worker_instance_id=worker_id,
                    acquisition_id=acquisition_id,
                    deadline_monotonic=time.monotonic() + 1,
                )
            lease_grant = client.claim(
                "RELATIVE_VOLUME",
                expected_launch.request_id,
                worker_instance_id=worker_id,
                acquisition_id=acquisition_id,
                deadline_monotonic=time.monotonic() + 1,
            )
            launch = client.current_input(
                "RELATIVE_VOLUME",
                expected_launch.request_id,
                lease_grant.fence,
                attempt_nonce=expected_launch.attempt_nonce,
                deadline_monotonic=time.monotonic() + 1,
            )
            assert (
                launch
                == expected_launch.model_copy(
                    update={"fence": lease_grant.fence, "canonical_input_digest": None}
                ).sealed()
            )
            assert launch is not None
            assert launch.volume_request is not None
            assert "capability" not in launch.model_dump_json()
            capability = client.capability_for(
                "RELATIVE_VOLUME", expected_launch.request_id, lease_grant.fence, launch.inputs[0]
            )
            assert "capability" not in repr(capability)

            result = _completed_result(launch, manifest)
            client.submit_result(
                launch,
                result,
                manifest=manifest,
                limits=limits(),
                computed_at=datetime(2026, 9, 9, 1, 1, tzinfo=UTC),
                deadline_monotonic=time.monotonic() + 1,
            )
            assert len(loopback.received_reports) == 1
            payload = loopback.received_reports[0]["payload"]
            assert payload["requestDigest"] == launch.volume_request.request_digest
            assert payload["algorithmBuildDigest"] == launch.execution_manifest_digest
            assert loopback.received_reports[0]["computedAt"] == "2026-09-09T01:01:00Z"
            with pytest.raises(ExternalMeasurementCoreClientError):
                client.capability_for(
                    "RELATIVE_VOLUME",
                    expected_launch.request_id,
                    lease_grant.fence,
                    launch.inputs[0],
                )
        finally:
            client.close()
            # The injected bearer transport remains caller-owned and usable by sibling lanes.
            assert shared.list_pending(deadline_monotonic=time.monotonic() + 1) == ()
            shared.close()
        assert not loopback.errors


def test_closed_or_released_adapter_never_restores_a_late_input_capability() -> None:
    manifest, launch = _volume_launch_with_records()
    del manifest
    worker_id, acquisition_id = str(uuid4()), str(uuid4())
    body = _volume_input(launch)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path.endswith("/input"):
            calls += 1
            return httpx.Response(200, json=body)
        raise AssertionError(request.url)

    shared = _core_client(httpx.MockTransport(handler))
    client = ExternalMeasurementCoreClient(core_client=shared)
    fence = client.fence_from_grant(worker_id, acquisition_id, 7)
    client.close()
    assert (
        client.current_input(
            "RELATIVE_VOLUME",
            launch.request_id,
            fence,
            attempt_nonce=launch.attempt_nonce,
            deadline_monotonic=time.monotonic() + 1,
        )
        is None
    )
    assert calls == 0
    with pytest.raises(ExternalMeasurementCoreClientError):
        client.list_pending("RELATIVE_VOLUME", deadline_monotonic=time.monotonic() + 1)
    assert shared._closed is False  # noqa: SLF001 - client must not close its injected sibling transport.
    shared.close()


def test_release_during_input_response_prevents_late_capability_resurrection() -> None:
    _manifest, launch = _volume_launch_with_records()
    fence = ExternalMeasurementCoreClient.fence_from_grant(str(uuid4()), str(uuid4()), 7)
    entered, release_response = Event(), Event()
    body = _volume_input(launch)

    def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url.path.endswith("/input")
        entered.set()
        assert release_response.wait(timeout=1)
        return httpx.Response(200, json=body)

    shared = _core_client(httpx.MockTransport(handler))
    client = ExternalMeasurementCoreClient(core_client=shared)
    result: list[Any] = []

    def fetch() -> None:
        result.append(
            client.current_input(
                "RELATIVE_VOLUME",
                launch.request_id,
                fence,
                attempt_nonce=launch.attempt_nonce,
                deadline_monotonic=time.monotonic() + 1,
            )
        )

    thread = Thread(target=fetch)
    thread.start()
    assert entered.wait(timeout=1)
    client.release("RELATIVE_VOLUME", launch.request_id, fence)
    release_response.set()
    thread.join(timeout=1)
    try:
        assert not thread.is_alive() and result == [None]
        with pytest.raises(ExternalMeasurementCoreClientError):
            client.capability_for("RELATIVE_VOLUME", launch.request_id, fence, launch.inputs[0])
    finally:
        client.close()
        shared.close()


@pytest.mark.parametrize("valid_terminal", (True, False))
def test_late_terminal_cleanup_cannot_erase_a_reacquired_volume_capability(
    valid_terminal: bool,
) -> None:
    """An old terminal response must not mutate a later same-key attempt."""

    manifest, expected = _volume_launch_with_records()
    assert expected.volume_request is not None
    entered, allow_response = Event(), Event()
    posts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/input"):
            return httpx.Response(200, json=_volume_input(expected))
        if request.method == "POST" and request.url.path.endswith("/report"):
            posts.append(request)
            entered.set()
            assert allow_response.wait(timeout=1)
            return httpx.Response(
                201,
                json={
                    "verdict": "REPORTED",
                    "request": (
                        {
                            "requestRef": expected.request_id,
                            "status": "SUCCEEDED",
                            "currentWorkOrderId": expected.volume_request.current_work_order_id,
                            "decisionDigest": expected.volume_request.decision_digest,
                            "issuedAt": expected.volume_request.issued_at.isoformat().replace(
                                "+00:00", "Z"
                            ),
                            "deadlineAt": "2026-09-09T02:00:00Z",
                            "reportRef": "external-relative-volume-report-race",
                            "reportDigest": "sha256:" + "f" * 64,
                        }
                        if valid_terminal
                        else None
                    ),
                    "fence": None,
                    "leaseExpiresAt": None,
                    "detail": None,
                },
            )
        raise AssertionError(request.url)

    shared = _core_client(httpx.MockTransport(handler))
    client = ExternalMeasurementCoreClient(core_client=shared)
    fence = ExternalMeasurementCoreClient.fence_from_grant(str(uuid4()), str(uuid4()), 7)
    failures: list[BaseException] = []
    try:
        initial = client.current_input(
            "RELATIVE_VOLUME",
            expected.request_id,
            fence,
            attempt_nonce=expected.attempt_nonce,
            deadline_monotonic=time.monotonic() + 1,
        )
        assert initial is not None

        def submit_old_attempt() -> None:
            try:
                client.submit_result(
                    initial,
                    _completed_result(initial, manifest),
                    manifest=manifest,
                    limits=limits(),
                    computed_at=datetime(2026, 9, 9, 1, 1, tzinfo=UTC),
                    deadline_monotonic=time.monotonic() + 1,
                )
            except BaseException as exc:  # The rejected response is an expected race outcome.
                failures.append(exc)

        thread = Thread(target=submit_old_attempt)
        thread.start()
        assert entered.wait(timeout=1)
        client.release("RELATIVE_VOLUME", initial.request_id, initial.fence)
        refreshed = client.current_input(
            "RELATIVE_VOLUME",
            expected.request_id,
            fence,
            attempt_nonce=expected.attempt_nonce,
            deadline_monotonic=time.monotonic() + 1,
        )
        assert refreshed is not None
        client.capability_for(
            "RELATIVE_VOLUME", refreshed.request_id, refreshed.fence, refreshed.inputs[0]
        )
        allow_response.set()
        thread.join(timeout=1)
        assert not thread.is_alive()
        if valid_terminal:
            assert failures == []
        else:
            assert len(failures) == 1
            assert isinstance(failures[0], ExternalMeasurementCoreClientError)
        client.capability_for(
            "RELATIVE_VOLUME", refreshed.request_id, refreshed.fence, refreshed.inputs[0]
        )
        assert len(posts) == 1
    finally:
        allow_response.set()
        client.close()
        shared.close()


def test_terminal_submission_requires_an_open_retained_volume_attempt() -> None:
    """Close and explicit release are local cancellation boundaries before Core POST."""

    manifest, expected = _volume_launch_with_records()
    posts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path.endswith("/input"):
            return httpx.Response(200, json=_volume_input(expected))
        if request.method == "POST" and request.url.path.endswith("/report"):
            posts.append(request)
            return httpx.Response(
                201,
                json={
                    "verdict": "REPORTED",
                    "request": None,
                    "fence": None,
                    "leaseExpiresAt": None,
                    "detail": None,
                },
            )
        raise AssertionError(request.url)

    for cancellation in ("close", "release"):
        shared = _core_client(httpx.MockTransport(handler))
        client = ExternalMeasurementCoreClient(core_client=shared)
        fence = ExternalMeasurementCoreClient.fence_from_grant(str(uuid4()), str(uuid4()), 7)
        try:
            launch = client.current_input(
                "RELATIVE_VOLUME",
                expected.request_id,
                fence,
                attempt_nonce=expected.attempt_nonce,
                deadline_monotonic=time.monotonic() + 1,
            )
            assert launch is not None
            result = _completed_result(launch, manifest)
            if cancellation == "close":
                client.close()
            else:
                client.release("RELATIVE_VOLUME", launch.request_id, launch.fence)
            with pytest.raises(ExternalMeasurementCoreClientError):
                client.submit_result(
                    launch,
                    result,
                    manifest=manifest,
                    limits=limits(),
                    computed_at=datetime(2026, 9, 9, 1, 1, tzinfo=UTC),
                    deadline_monotonic=time.monotonic() + 1,
                )
            assert shared._closed is False  # noqa: SLF001 - shared sibling transport survives.
        finally:
            client.close()
            shared.close()
    assert posts == []


def test_volume_terminal_response_requires_the_reported_request_identity() -> None:
    """A report verdict without the matching Core request/report identity is unsafe."""

    manifest, expected = _volume_launch_with_records()
    assert expected.volume_request is not None
    for terminal in (
        {
            "verdict": "REPORTED",
            "request": None,
            "fence": None,
            "leaseExpiresAt": None,
            "detail": None,
        },
        {
            "verdict": "REPORTED",
            "request": {
                "requestRef": "different-request",
                "status": "SUCCEEDED",
                "currentWorkOrderId": expected.volume_request.current_work_order_id,
                "decisionDigest": expected.volume_request.decision_digest,
                "issuedAt": expected.volume_request.issued_at.isoformat().replace("+00:00", "Z"),
                "deadlineAt": "2026-09-09T02:00:00Z",
                "reportRef": "external-relative-volume-report-unrelated",
                "reportDigest": "sha256:" + "f" * 64,
            },
            "fence": None,
            "leaseExpiresAt": None,
            "detail": None,
        },
        {
            "verdict": "REPORTED",
            "request": {
                "requestRef": expected.request_id,
                "status": "SUCCEEDED",
                "currentWorkOrderId": expected.volume_request.current_work_order_id,
                "decisionDigest": expected.volume_request.decision_digest,
                "issuedAt": (expected.volume_request.issued_at + timedelta(seconds=1))
                .isoformat()
                .replace("+00:00", "Z"),
                "deadlineAt": "2026-09-09T02:00:00Z",
                "reportRef": "external-relative-volume-report-issued-at",
                "reportDigest": "sha256:" + "f" * 64,
            },
            "fence": None,
            "leaseExpiresAt": None,
            "detail": None,
        },
        {
            "verdict": "REPORTED",
            "request": {
                "requestRef": expected.request_id,
                "status": "SUCCEEDED",
                "currentWorkOrderId": expected.volume_request.current_work_order_id,
                "decisionDigest": expected.volume_request.decision_digest,
                "issuedAt": expected.volume_request.issued_at.isoformat().replace("+00:00", "Z"),
                "deadlineAt": expected.volume_request.issued_at.isoformat().replace("+00:00", "Z"),
                "reportRef": "external-relative-volume-report-deadline-order",
                "reportDigest": "sha256:" + "f" * 64,
            },
            "fence": None,
            "leaseExpiresAt": None,
            "detail": None,
        },
    ):

        def handler(request: httpx.Request, response: dict[str, Any] = terminal) -> httpx.Response:
            if request.method == "GET" and request.url.path.endswith("/input"):
                return httpx.Response(200, json=_volume_input(expected))
            if request.method == "POST" and request.url.path.endswith("/report"):
                return httpx.Response(201, json=response)
            raise AssertionError(request.url)

        shared = _core_client(httpx.MockTransport(handler))
        client = ExternalMeasurementCoreClient(core_client=shared)
        fence = ExternalMeasurementCoreClient.fence_from_grant(str(uuid4()), str(uuid4()), 7)
        try:
            launch = client.current_input(
                "RELATIVE_VOLUME",
                expected.request_id,
                fence,
                attempt_nonce=expected.attempt_nonce,
                deadline_monotonic=time.monotonic() + 1,
            )
            assert launch is not None
            with pytest.raises(ExternalMeasurementCoreClientError):
                client.submit_result(
                    launch,
                    _completed_result(launch, manifest),
                    manifest=manifest,
                    limits=limits(),
                    computed_at=datetime(2026, 9, 9, 1, 1, tzinfo=UTC),
                    deadline_monotonic=time.monotonic() + 1,
                )
        finally:
            client.close()
            shared.close()


def test_current_input_rejects_boolean_capability_size_before_identity_comparison() -> None:
    """A JSON boolean must not be coerced into a trusted byte-count integer."""

    _manifest, initial = _volume_launch_with_records()
    assert initial.volume_request is not None
    baseline = initial.volume_request.baseline.model_copy(
        update={"observed_size_bytes": 1}, deep=True
    )
    request = initial.volume_request.model_copy(
        update={"baseline": baseline, "request_digest": None}, deep=True
    ).sealed()
    first_input = initial.inputs[0].model_copy(update={"observed_size_bytes": 1}, deep=True)
    launch = initial.model_copy(
        update={
            "inputs": (first_input, initial.inputs[1]),
            "volume_request": request,
            "canonical_input_digest": None,
        },
        deep=True,
    ).sealed()
    body = _volume_input(launch)
    body["input"]["inputs"][0]["observedSizeBytes"] = True
    fence = ExternalMeasurementCoreClient.fence_from_grant(str(uuid4()), str(uuid4()), 7)
    shared = _core_client(httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    client = ExternalMeasurementCoreClient(core_client=shared)
    try:
        assert (
            client.current_input(
                "RELATIVE_VOLUME",
                launch.request_id,
                fence,
                attempt_nonce=launch.attempt_nonce,
                deadline_monotonic=time.monotonic() + 1,
            )
            is None
        )
    finally:
        client.close()
        shared.close()


def test_measurement_adapter_rejects_extra_substituted_and_nonfinite_core_bodies() -> None:
    """Wire strictness remains fail-closed before a launch or capability is retained."""

    _manifest, launch = _volume_launch_with_records()
    fence = ExternalMeasurementCoreClient.fence_from_grant(str(uuid4()), str(uuid4()), 7)
    for mutate in (
        lambda body: body["input"].update({"unexpected": "no"}),
        lambda body: body["input"]["inputs"][0].update({"artifactId": "substitution"}),
    ):
        body = _volume_input(launch)
        mutate(body)
        shared = _core_client(
            httpx.MockTransport(lambda _request, payload=body: httpx.Response(200, json=payload))
        )
        client = ExternalMeasurementCoreClient(core_client=shared)
        try:
            assert (
                client.current_input(
                    "RELATIVE_VOLUME",
                    launch.request_id,
                    fence,
                    attempt_nonce=launch.attempt_nonce,
                    deadline_monotonic=time.monotonic() + 1,
                )
                is None
            )
        finally:
            client.close()
            shared.close()
    shared = _core_client(
        httpx.MockTransport(lambda _: httpx.Response(200, content=b'{"items":[],"extra":1e999}'))
    )
    client = ExternalMeasurementCoreClient(core_client=shared)
    try:
        with pytest.raises(ExternalMeasurementCoreClientError):
            client.list_pending("RELATIVE_VOLUME", deadline_monotonic=time.monotonic() + 1)
    finally:
        client.close()
        shared.close()


def test_checkpoint_core_body_claim_heartbeat_input_and_typed_failure_are_fenced() -> None:
    manifest, request, context, policy, worker_input = _checkpoint_core_material()
    worker_id, acquisition_id = str(uuid4()), str(uuid4())
    fence = {
        "workerInstanceId": worker_id,
        "leaseAcquisitionId": acquisition_id,
        "leaseGeneration": 3,
    }
    lease = {
        "verdict": "LEASED",
        "request": request.model_dump(by_alias=True, mode="json"),
        "fence": fence,
        "leaseExpiresAt": "2026-09-09T01:05:00Z",
    }
    seen: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        seen.append(http_request)
        path = http_request.url.path
        if http_request.method == "GET" and path.endswith("/evidence-validations"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"validationId": request.validation_id, "issuedAt": "2026-09-09T01:00:00Z"}
                    ]
                },
            )
        if path.endswith("/lease"):
            assert http_request.headers["X-KSI-Lease-Generation"] == "0"
            return httpx.Response(200, json=lease)
        if path.endswith("/heartbeat"):
            assert http_request.headers["X-KSI-Lease-Generation"] == "3"
            return httpx.Response(200, json=lease)
        if http_request.method == "GET" and path.endswith("/input"):
            return httpx.Response(200, json=worker_input)
        if path.endswith("/incomplete-failure"):
            assert json.loads(http_request.content) == {
                "reason": "INSUFFICIENT_COMMON_VALID_COVERAGE"
            }
            return httpx.Response(200, json={"verdict": "REJECTED", "record": None})
        raise AssertionError(path)

    shared = _core_client(httpx.MockTransport(handler))
    client = ExternalMeasurementCoreClient(core_client=shared)
    try:
        pending = client.list_pending(
            "CHECKPOINT_VALIDATION", deadline_monotonic=time.monotonic() + 1
        )
        assert pending == (pending[0],) and pending[0].request_id == request.validation_id
        grant = client.claim(
            "CHECKPOINT_VALIDATION",
            request.validation_id,
            worker_instance_id=worker_id,
            acquisition_id=acquisition_id,
            deadline_monotonic=time.monotonic() + 1,
        )
        launch = client.current_input(
            "CHECKPOINT_VALIDATION",
            request.validation_id,
            grant.fence,
            attempt_nonce=str(uuid4()),
            deadline_monotonic=time.monotonic() + 1,
        )
        assert launch is not None
        assert [item.role for item in launch.inputs] == ["TARGET_DSM", "CHECKPOINT_CSV"]
        assert launch.validation_policy == policy and launch.evidence_context == context
        renewed = client.heartbeat(
            "CHECKPOINT_VALIDATION",
            request.validation_id,
            grant.fence,
            deadline_monotonic=time.monotonic() + 1,
        )
        assert renewed is not None and renewed.fence == grant.fence
        client.record_incomplete_failure(
            "CHECKPOINT_VALIDATION",
            request.validation_id,
            grant.fence,
            "INSUFFICIENT_COMMON_VALID_COVERAGE",
            deadline_monotonic=time.monotonic() + 1,
        )
        with pytest.raises(ExternalMeasurementCoreClientError):
            client.capability_for(
                "CHECKPOINT_VALIDATION", request.validation_id, grant.fence, launch.inputs[0]
            )
        assert "private=capability" not in repr(client)
    finally:
        client.close()
        shared.close()
    assert len(seen) == 5


def test_checkpoint_terminal_submission_requires_an_open_retained_attempt() -> None:
    """Closing or releasing a checkpoint attempt cannot emit a measurement POST."""

    manifest, request, _context, _policy, worker_input = _checkpoint_core_material()
    posts: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        if http_request.method == "GET" and http_request.url.path.endswith("/input"):
            return httpx.Response(200, json=worker_input)
        if http_request.method == "POST" and http_request.url.path.endswith("/measurement"):
            posts.append(http_request)
            return httpx.Response(200, json={"verdict": "VALIDATED", "record": None})
        raise AssertionError(http_request.url)

    for cancellation in ("close", "release"):
        shared = _core_client(httpx.MockTransport(handler))
        client = ExternalMeasurementCoreClient(core_client=shared)
        fence = ExternalMeasurementCoreClient.fence_from_grant(str(uuid4()), str(uuid4()), 3)
        try:
            launch = client.current_input(
                "CHECKPOINT_VALIDATION",
                request.validation_id,
                fence,
                attempt_nonce=str(uuid4()),
                deadline_monotonic=time.monotonic() + 1,
            )
            assert launch is not None
            if cancellation == "close":
                client.close()
            else:
                client.release("CHECKPOINT_VALIDATION", launch.request_id, launch.fence)
            with pytest.raises(ExternalMeasurementCoreClientError):
                client.submit_result(
                    launch,
                    _completed_checkpoint_result(launch, manifest),
                    manifest=manifest,
                    limits=limits(),
                    computed_at=datetime(2026, 9, 9, 1, 1, tzinfo=UTC),
                    deadline_monotonic=time.monotonic() + 1,
                )
            assert shared._closed is False  # noqa: SLF001 - shared sibling transport survives.
        finally:
            client.close()
            shared.close()
    assert posts == []


def test_checkpoint_terminal_response_requires_matching_sealed_record() -> None:
    """A terminal verdict alone cannot acknowledge a different checkpoint measurement."""

    manifest, request, _context, _policy, worker_input = _checkpoint_core_material()
    for response_kind in ("missing", "wrong"):
        terminal_body: list[dict[str, Any]] = []

        def handler(
            http_request: httpx.Request, state: list[dict[str, Any]] = terminal_body
        ) -> httpx.Response:
            if http_request.method == "GET" and http_request.url.path.endswith("/input"):
                return httpx.Response(200, json=worker_input)
            if http_request.method == "POST" and http_request.url.path.endswith("/measurement"):
                assert state
                return httpx.Response(200, json=state[0])
            raise AssertionError(http_request.url)

        shared = _core_client(httpx.MockTransport(handler))
        client = ExternalMeasurementCoreClient(core_client=shared)
        fence = ExternalMeasurementCoreClient.fence_from_grant(str(uuid4()), str(uuid4()), 3)
        try:
            launch = client.current_input(
                "CHECKPOINT_VALIDATION",
                request.validation_id,
                fence,
                attempt_nonce=str(uuid4()),
                deadline_monotonic=time.monotonic() + 1,
            )
            assert launch is not None
            result = _completed_checkpoint_result(launch, manifest)
            payload = client._checkpoint_payload(  # noqa: SLF001 - exact outbound Core body.
                launch, result, datetime(2026, 9, 9, 1, 1, tzinfo=UTC)
            )
            if response_kind == "missing":
                terminal_body.append({"verdict": "VALIDATED", "record": None})
            else:
                assert launch.checkpoint_request is not None
                terminal_body.append(
                    {
                        "verdict": "VALIDATED",
                        "record": ExternalEvidenceRecordV1(
                            evidence_record_id="wrong-record",
                            validation_id=launch.checkpoint_request.validation_id,
                            subject_digest="sha256:" + "f" * 64,
                            evidence_manifest_digest=payload.evidence_manifest_digest,
                            target_dsm_observed_sha256=payload.target_dsm_observed_sha256,
                            policy_digest=payload.policy_digest,
                            measurement_payload=payload,
                            core_verdict=EvidenceCoreVerdict.VALIDATED,
                            core_recorded_at=datetime(2026, 9, 9, 1, 1, tzinfo=UTC),
                        )
                        .sealed()
                        .model_dump(by_alias=True, mode="json"),
                    }
                )
            with pytest.raises(ExternalMeasurementCoreClientError):
                client.submit_result(
                    launch,
                    result,
                    manifest=manifest,
                    limits=limits(),
                    computed_at=datetime(2026, 9, 9, 1, 1, tzinfo=UTC),
                    deadline_monotonic=time.monotonic() + 1,
                )
        finally:
            client.close()
            shared.close()


def _manifest_for_resource_envelope(resource_envelope_digest: str) -> InspectorExecutionManifestV1:
    """Build a V2 fixture whose signed body binds the actual Core policy envelope."""

    template, _ = measurement_manifest_request()
    body = template.body.model_copy(
        update={"resource_envelope_digest": resource_envelope_digest}, deep=True
    )
    return InspectorExecutionManifestV1(
        body=body,
        signature=template.signature.model_copy(
            update={"digest": body.canonical_body_digest()}, deep=True
        ),
    )


def _actual_volume_store(
    tmp_path: Path,
) -> tuple[ExternalRelativeVolumeStore, InspectorExecutionManifestV1]:
    """Use the accepted 4E store/router material with a V2-bound execution digest."""

    authority, policy, material = _launch_ready_authority()
    assert policy.resource_envelope_digest is not None
    manifest = _manifest_for_resource_envelope(policy.resource_envelope_digest)
    execution = authority.execution_policy.model_copy(
        update={"algorithm_build_digest": manifest.canonical_body_digest(), "policy_digest": None},
        deep=True,
    ).sealed()
    authority = replace(
        authority,
        execution_policy=execution,
        # The V2 terminal binds the two retained evidence RMSE values. Keep
        # this synthetic authority's Core report constraint aligned with them.
        baseline_rmse_m=0.1,
        current_rmse_m=0.1,
    )
    port = _AuthorityPort(authority)
    registry = _StaticVolumePolicyRegistry(policy, port.currentness_coordinator)
    registry.subjects = (authority.baseline.subject, authority.current.subject)
    evidence = _StaticVolumeEvidence(material, port.currentness_coordinator)
    resolver = VolumeWorkerLaunchMaterialResolver(
        policy_registry=cast(Any, registry),
        evidence_validations=cast(Any, evidence),
        currentness_coordinator=port.currentness_coordinator,
    )
    return (
        ExternalRelativeVolumeStore(
            DurableJournal(tmp_path / "actual-volume-router.jsonl"),
            authority_port=port,
            currentness_coordinator=port.currentness_coordinator,
            queue_policy=ExternalRelativeVolumeQueuePolicy(
                lease_ttl=timedelta(minutes=5),
                deadline_after_issue=timedelta(hours=1),
                max_attempts=3,
                max_active_requests_per_organization=8,
            ),
            launch_material_resolver=resolver,
            clock=lambda: datetime(2026, 9, 9, tzinfo=UTC),
        ),
        manifest,
    )


def test_actual_core_volume_router_claim_input_v2_and_report_parity(tmp_path: Path) -> None:
    """The adapter consumes actual 4E Core bodies, including response-loss retry."""

    store, manifest = _actual_volume_store(tmp_path)
    issued = store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="actual-core-volume",
        now=datetime(2026, 9, 9, tzinfo=UTC),
    )
    assert issued.record is not None
    request_id = issued.record.request.request_id
    worker_id, acquisition_id = str(uuid4()), str(uuid4())
    bridge = _CoreTestClientTransport(_launch_client(store))
    shared = ExternalValidationCoreClient(
        base_url="https://core.invalid",
        bearer_token=_VOLUME_WORKER_TOKEN,
        transport=bridge,
        monotonic=lambda: 0.0,
    )
    client = ExternalMeasurementCoreClient(core_client=shared)
    try:
        pending = client.list_pending("RELATIVE_VOLUME", deadline_monotonic=1.0)
        assert [item.request_id for item in pending] == [request_id]
        bridge.drop_next_suffix = "/lease"
        with pytest.raises(ExternalMeasurementCoreClientError):
            client.claim(
                "RELATIVE_VOLUME",
                request_id,
                worker_instance_id=worker_id,
                acquisition_id=acquisition_id,
                deadline_monotonic=1.0,
            )
        grant = client.claim(
            "RELATIVE_VOLUME",
            request_id,
            worker_instance_id=worker_id,
            acquisition_id=acquisition_id,
            deadline_monotonic=1.0,
        )
        assert grant.fence.lease_generation > 0
        launch = client.current_input(
            "RELATIVE_VOLUME",
            request_id,
            grant.fence,
            attempt_nonce="actual-core-volume-attempt",
            deadline_monotonic=1.0,
        )
        assert launch is not None and launch.volume_request is not None
        assert launch.volume_execution_policy is not None
        assert [record.subject_digest for record in launch.volume_evidence_records] == [
            launch.volume_request.baseline.subject.canonical_digest(),
            launch.volume_request.current.subject.canonical_digest(),
        ]
        assert [binding.role for binding in launch.inputs] == ["BASELINE_DSM", "CURRENT_DSM"]
        result = _completed_result(launch, manifest)
        expected_payload = client._volume_payload(launch, result)  # noqa: SLF001
        client.submit_result(
            launch,
            result,
            manifest=manifest,
            limits=limits(),
            computed_at=datetime(2026, 9, 9, tzinfo=UTC),
            deadline_monotonic=1.0,
        )
        stored = store.get(request_id, organization_id="org-a")
        assert stored is not None and stored.report is not None
        assert stored.report.measurement_payload_digest == expected_payload.canonical_digest()
    finally:
        client.close()
        shared.close()


def test_actual_core_evidence_router_claim_input_v2_and_measurement_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The checkpoint lane maps actual 4E evidence bodies into a complete V2 result."""

    import hashlib

    import test_external_evidence_validations as evidence_contract

    now = datetime.now(UTC)
    monkeypatch.setattr(evidence_contract, "NOW", now)
    item = evidence_contract._evidence()
    registry, policy = evidence_contract._policy_registry(tmp_path)
    assert policy.resource_envelope_digest is not None
    manifest = _manifest_for_resource_envelope(policy.resource_envelope_digest)
    context = (
        evidence_contract._context(item, policy)
        .model_copy(
            update={
                "measurement_execution_manifest_digest": manifest.canonical_body_digest(),
                "context_digest": None,
            },
            deep=True,
        )
        .sealed()
    )
    store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "actual-evidence-router.jsonl"),
        evidence=evidence_contract._Evidence(item, coordinator=registry.coordinator),
        policy_registry=registry,
        context_authority=evidence_contract._ContextAuthority(
            context, coordinator=registry.coordinator
        ),
        input_capabilities=evidence_contract._InputCapabilities(),
        clock=lambda: now,
    )
    issued = store.issue_after_seal(item.evidence_ref, now=now)
    assert issued.request is not None
    request_id = issued.request.validation_id
    token = "actual-evidence-worker-token"
    worker = Principal(
        principal_id="actual-evidence-worker",
        kind=PrincipalKind.PROCESSING_WORKER,
        role=None,
        device_id=None,
        organization_id="org-a",
    )
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(token.encode()).hexdigest(), principal=worker
                )
            ]
        ),
    )
    mount_external_evidence_validations(app, store)
    bridge = _CoreTestClientTransport(TestClient(app))
    shared = ExternalValidationCoreClient(
        base_url="https://core.invalid",
        bearer_token=token,
        transport=bridge,
        monotonic=lambda: 0.0,
    )
    client = ExternalMeasurementCoreClient(core_client=shared)
    worker_id, acquisition_id = str(uuid4()), str(uuid4())
    try:
        pending = client.list_pending("CHECKPOINT_VALIDATION", deadline_monotonic=1.0)
        assert [item.request_id for item in pending] == [request_id]
        bridge.drop_next_suffix = "/lease"
        with pytest.raises(ExternalMeasurementCoreClientError):
            client.claim(
                "CHECKPOINT_VALIDATION",
                request_id,
                worker_instance_id=worker_id,
                acquisition_id=acquisition_id,
                deadline_monotonic=1.0,
            )
        grant = client.claim(
            "CHECKPOINT_VALIDATION",
            request_id,
            worker_instance_id=worker_id,
            acquisition_id=acquisition_id,
            deadline_monotonic=1.0,
        )
        launch = client.current_input(
            "CHECKPOINT_VALIDATION",
            request_id,
            grant.fence,
            attempt_nonce="actual-core-evidence-attempt",
            deadline_monotonic=1.0,
        )
        assert launch is not None and launch.checkpoint_request is not None
        assert launch.evidence_context == context
        assert [binding.role for binding in launch.inputs] == ["TARGET_DSM", "CHECKPOINT_CSV"]
        terminal = build_completed_frame_v2(
            prepare=build_prepare_frame_v2(request=launch, manifest=manifest),
            input_bindings=[
                binding.model_dump(by_alias=True, mode="json") for binding in launch.inputs
            ],
            aggregate={
                "metricType": "CHECKPOINT_VALIDATION_AGGREGATE_V2",
                "measuredCheckpointCount": 3,
                "meanErrorM": 0.1,
                "maeM": 0.1,
                "rmseM": 0.1,
                "maxAbsErrorM": 0.1,
            },
        )
        result = build_measurement_result(
            terminal=terminal, request=launch, manifest=manifest, limits=limits()
        )
        client.submit_result(
            launch,
            result,
            manifest=manifest,
            limits=limits(),
            computed_at=now,
            deadline_monotonic=1.0,
        )
        records = store.terminal_records_for_evidence(item.evidence_ref)
        assert len(records) == 1
        assert records[0].measurement_payload is not None
        assert records[0].measurement_payload.validation_id == request_id
    finally:
        client.close()
        shared.close()


def _single_volume_launch_fixture() -> tuple[Any, Any]:
    """Manifest-bound SINGLE_VOLUME launch with one sealed VALIDATED record."""

    from test_external_measurement_protocol import single_volume_manifest_request

    return single_volume_manifest_request()


def _single_volume_input_body(launch: Any) -> dict[str, Any]:
    assert launch.single_volume_request is not None
    assert launch.single_volume_execution_policy is not None
    assert len(launch.volume_evidence_records) == 1
    return {
        "verdict": "INPUT_READY",
        "input": {
            "request": launch.single_volume_request.model_dump(by_alias=True, mode="json"),
            "executionPolicy": launch.single_volume_execution_policy.model_dump(
                by_alias=True, mode="json"
            ),
            "validationPolicy": launch.validation_policy.model_dump(by_alias=True, mode="json"),
            "evidenceRecord": launch.volume_evidence_records[0].model_dump(
                by_alias=True, mode="json"
            ),
            "inputs": [
                {
                    "role": item.role,
                    "artifactId": item.artifact_id,
                    "observedSha256": item.observed_sha256,
                    "observedSizeBytes": item.observed_size_bytes,
                    "downloadUrl": f"https://objects.invalid/{item.artifact_id}?private=capability",
                    "requiredHeaders": {"x-bound-role": item.role},
                    "expiresAt": "2026-09-09T01:10:00Z",
                }
                for item in launch.inputs
            ],
        },
        "detail": None,
    }


def _completed_single_volume_result(launch: Any, manifest: Any) -> Any:
    import numpy as np

    assert launch.single_volume_request is not None
    assert launch.single_volume_execution_policy is not None
    assert launch.volume_evidence_records[0].measurement_payload is not None
    rmse = launch.volume_evidence_records[0].measurement_payload.rmse_m
    aggregate = {
        "metricType": "SINGLE_VOLUME_AGGREGATE_V2",
        "zoneId": launch.single_volume_request.zone_snapshot.work_area_id,
        "metrics": {
            "zoneCellCount": 4,
            "commonValidCellCount": 4,
            "zoneAreaM2": 4.0,
            "measuredAreaM2": 4.0,
            "commonValidFraction": 1.0,
            "cutM3": 1.0,
            "fillM3": 5.0,
            "netM3": 4.0,
            "thresholdM": launch.single_volume_execution_policy.threshold_m,
            "uncertaintyM3": 4.0 * float(np.hypot(0.02, rmse)),
            "uncertaintyNote": (
                "Validated target-epoch checkpoint RMSE and boundary base "
                "roughness were used."
            ),
            "baseRoughnessM": 0.02,
            "boundaryCellCount": 4,
            "boundarySampleCount": 4,
            "boundaryValidFraction": 1.0,
        },
    }
    terminal = build_completed_frame_v2(
        prepare=build_prepare_frame_v2(request=launch, manifest=manifest),
        input_bindings=[item.model_dump(by_alias=True, mode="json") for item in launch.inputs],
        aggregate=aggregate,
    )
    return build_measurement_result(
        terminal=terminal, request=launch, manifest=manifest, limits=limits()
    )


def test_single_volume_launch_maps_capabilities_and_seals_the_launch() -> None:
    """Capabilities are addressed as (TARGET_DSM, CHECKPOINT_CSV) in launch order."""

    _manifest, expected = _single_volume_launch_fixture()
    body = _single_volume_input_body(expected)
    fence = ExternalMeasurementCoreClient.fence_from_grant(str(uuid4()), str(uuid4()), 7)
    shared = _core_client(httpx.MockTransport(lambda _: httpx.Response(200, json=body)))
    client = ExternalMeasurementCoreClient(core_client=shared)
    try:
        launch = client.current_input(
            "SINGLE_VOLUME",
            expected.request_id,
            fence,
            attempt_nonce=expected.attempt_nonce,
            deadline_monotonic=time.monotonic() + 1,
        )
        assert launch is not None
        assert launch == expected.model_copy(
            update={"fence": fence, "canonical_input_digest": None}
        ).sealed()
        assert launch.operation == "SINGLE_VOLUME"
        assert [item.role for item in launch.inputs] == ["TARGET_DSM", "CHECKPOINT_CSV"]
        assert launch.single_volume_request is not None
        assert launch.request_id == launch.single_volume_request.request_id
        assert len(launch.volume_evidence_records) == 1
        record = launch.volume_evidence_records[0]
        assert record.evidence_record_digest == record.canonical_digest()
        assert "capability" not in launch.model_dump_json()
        for item in launch.inputs:
            capability = client.capability_for(
                "SINGLE_VOLUME", expected.request_id, fence, item
            )
            assert "capability" not in repr(capability)
    finally:
        client.close()
        shared.close()


def test_single_volume_payload_builds_the_report_body() -> None:
    """The Core report body binds the sealed request, policy and observed metrics."""

    from ksi_processing_controller.external_measurement_result import SingleVolumeAggregateV2

    manifest, launch = _single_volume_launch_fixture()
    assert launch.single_volume_request is not None
    assert launch.single_volume_execution_policy is not None
    result = _completed_single_volume_result(launch, manifest)
    assert isinstance(result.aggregate, SingleVolumeAggregateV2)
    payload = ExternalMeasurementCoreClient._single_volume_payload(  # noqa: SLF001
        launch, result
    )
    assert payload.request_digest == launch.single_volume_request.request_digest
    assert payload.decision_digest == launch.single_volume_request.decision_digest
    assert payload.target_dsm_digest == launch.single_volume_request.target.observed_sha256
    assert (
        payload.zone_snapshot_digest
        == launch.single_volume_request.zone_snapshot.canonical_digest()
    )
    assert payload.execution_policy_digest == launch.single_volume_execution_policy.policy_digest
    assert payload.algorithm_build_digest == launch.execution_manifest_digest
    assert payload.config_digest == launch.single_volume_execution_policy.config_digest
    assert payload.metrics == result.aggregate.metrics


def test_single_volume_queue_branches_target_the_single_volume_base() -> None:
    """Pending, claim and input calls use the single-volume internal base path."""

    _manifest, expected = _single_volume_launch_fixture()
    assert expected.single_volume_request is not None
    seen: list[str] = []
    worker_id, acquisition_id = str(uuid4()), str(uuid4())

    def handler(http_request: httpx.Request) -> httpx.Response:
        seen.append(f"{http_request.method} {http_request.url.path}")
        path = http_request.url.path
        if http_request.method == "GET" and path == (
            "/v1/internal/external-validation/single-volumes"
        ):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "requestRef": expected.request_id,
                            "issuedAt": "2026-09-09T01:00:00Z",
                        }
                    ]
                },
            )
        if path.endswith("/lease"):
            assert path.startswith("/v1/internal/external-validation/single-volumes/")
            return httpx.Response(
                200,
                json={
                    "verdict": "LEASED",
                    "request": {
                        "requestRef": expected.request_id,
                        "status": "LEASED",
                        "currentWorkOrderId": (
                            expected.single_volume_request.current_work_order_id
                        ),
                        "decisionDigest": expected.single_volume_request.decision_digest,
                        "issuedAt": expected.single_volume_request.issued_at.isoformat().replace(
                            "+00:00", "Z"
                        ),
                        "deadlineAt": "2026-09-09T02:00:00Z",
                        "reportRef": None,
                        "reportDigest": None,
                    },
                    "fence": {
                        "workerInstanceId": worker_id,
                        "leaseAcquisitionId": acquisition_id,
                        "leaseGeneration": 7,
                    },
                    "leaseExpiresAt": "2026-09-09T01:05:00Z",
                    "detail": None,
                },
            )
        if http_request.method == "GET" and path.endswith("/input"):
            assert path.startswith("/v1/internal/external-validation/single-volumes/")
            return httpx.Response(200, json=_single_volume_input_body(expected))
        raise AssertionError(path)

    shared = _core_client(httpx.MockTransport(handler))
    client = ExternalMeasurementCoreClient(core_client=shared)
    try:
        pending = client.list_pending("SINGLE_VOLUME", deadline_monotonic=time.monotonic() + 1)
        assert [item.request_id for item in pending] == [expected.request_id]
        assert all(item.operation == "SINGLE_VOLUME" for item in pending)
        grant = client.claim(
            "SINGLE_VOLUME",
            expected.request_id,
            worker_instance_id=worker_id,
            acquisition_id=acquisition_id,
            deadline_monotonic=time.monotonic() + 1,
        )
        assert grant.operation == "SINGLE_VOLUME"
        launch = client.current_input(
            "SINGLE_VOLUME",
            expected.request_id,
            grant.fence,
            attempt_nonce=expected.attempt_nonce,
            deadline_monotonic=time.monotonic() + 1,
        )
        assert launch is not None and launch.operation == "SINGLE_VOLUME"
        assert [item.role for item in launch.inputs] == ["TARGET_DSM", "CHECKPOINT_CSV"]
    finally:
        client.close()
        shared.close()
    assert seen[0] == "GET /v1/internal/external-validation/single-volumes"
    assert seen[1].startswith("POST /v1/internal/external-validation/single-volumes/")
    assert seen[2].startswith("GET /v1/internal/external-validation/single-volumes/")
    assert not any("relative-volumes" in path for path in seen)
