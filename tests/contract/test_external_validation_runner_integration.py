"""Owned local wiring acceptance for the external validation runner.

All endpoints, UDS listeners, bytes, and synthetic executor outcomes are owned
by this test.  It establishes no host, container, credential, or HIL evidence.
"""

from __future__ import annotations

import hashlib
import os
import socket
import struct
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
import test_external_artifact_inspections_api as inspection_api
import test_external_evidence_validations as evidence_contract
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, mount_auth
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_evidence_validations import (
    ExternalEvidenceValidationInputBinding,
    ExternalEvidenceValidationStore,
    mount_external_evidence_validations,
)
from ksi_core.external_relative_volumes import (
    ExternalRelativeVolumeInputCapability,
    build_external_relative_volume_router,
)
from ksi_event_contracts.external_artifact_validation import ArtifactOutcome
from ksi_event_contracts.external_reconstruction import (
    ExternalReconstructionManifestEntryV1,
    ExternalReconstructionManifestV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_processing_controller.external_artifact_inspection_worker import (
    ExternalInspectorUdsClient,
    FileSystemSanitizedOutputSink,
    WorkerAuthorityLimitsV1,
)
from ksi_processing_controller.external_geotiff_profile import external_geotiff_profile_digest_v1
from ksi_processing_controller.external_inspector_protocol import (
    DeadlineBoundedMemorySink,
    InspectorLaunchResultV1,
    InspectorOperation,
    ProtocolLimitsV1,
    read_bound_bytes,
    read_launch_request_header,
    write_launch_result,
)
from ksi_processing_controller.external_measurement_client import (
    ExternalMeasurementUdsClient,
    FixedMeasurementUdsConnector,
    MeasurementSocketIdentityV2,
)
from ksi_processing_controller.external_measurement_core_client import ExternalMeasurementCoreClient
from ksi_processing_controller.external_measurement_transport import MeasurementRequestReceiverV2
from ksi_processing_controller.external_object_streams import (
    ExternalObjectCapabilityV1,
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)
from ksi_processing_controller.external_validation_core_client import (
    ExternalCoreClientError,
    ExternalDisplayUploadCapability,
    ExternalValidationCoreClient,
)
from ksi_processing_controller.external_validation_lanes import (
    InspectionLaneDependencies,
    InspectionValidationLane,
    MeasurementLaneDependencies,
    MeasurementValidationLane,
)
from ksi_processing_controller.external_validation_runner import (
    ExternalLane,
    ExternalLaneUnavailable,
    ExternalValidationRunner,
    RunnerPolicy,
    TurnOutcome,
)
from ksi_processing_controller.external_validation_worker_config import (
    FixedInspectionUdsConnector,
    LocalWorkerSocketIdentityV1,
    PinnedInspectionProfileV1,
)
from support.external_artifact_inspection_fixtures import (
    SyntheticStorage,
    policy_template,
    sealed_submission,
)
from support.external_artifact_inspection_fixtures import (
    report as inspection_report,
)
from support.external_artifact_inspection_fixtures import (
    subject as inspection_subject,
)
from test_external_artifact_inspection_worker import _fence
from test_external_measurement_core_client import (
    _completed_checkpoint_result,
    _completed_result,
)
from test_external_measurement_protocol import limits as measurement_limits
from test_external_relative_volumes import _WORKER_TOKEN as _VOLUME_WORKER_TOKEN
from test_external_validation_core_client import _CoreTestClientTransport

_RUNNER_CHECKPOINT_TOKEN = "runner-checkpoint-worker-token"


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class _InspectionAndDisplayObjectServer:
    """A finite local GET/PUT endpoint which exposes only test bytes to the lanes."""

    def __init__(
        self, *, source: bytes, storage: SyntheticStorage, maximum_connections: int = 3
    ) -> None:
        if type(maximum_connections) is not int or maximum_connections < 1:
            raise ValueError("owned object server needs a positive connection bound")
        self._source = source
        self._storage = storage
        self._maximum_connections = maximum_connections
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(3)
        self._listener.settimeout(0.1)
        self.port = int(self._listener.getsockname()[1])
        self.put_body = b""
        self.put_bodies: list[bytes] = []
        self.drop_next_put_response = False
        self.errors: list[BaseException] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve)

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def source_url(self) -> str:
        return self.origin + "/source"

    @property
    def upload_url(self) -> str:
        return self.origin + "/upload"

    def __enter__(self) -> _InspectionAndDisplayObjectServer:
        self._thread.start()
        return self

    def __exit__(self, kind: object, *_args: object) -> None:
        self._stop.set()
        self._listener.close()
        self._thread.join(timeout=2)
        assert not self._thread.is_alive(), "owned object server did not stop"
        if kind is None and self.errors:
            raise self.errors[0]

    def _serve(self) -> None:
        try:
            accepted = 0
            while accepted < self._maximum_connections and not self._stop.is_set():
                try:
                    connection, _address = self._listener.accept()
                except TimeoutError:
                    continue
                with connection:
                    accepted += 1
                    request = bytearray()
                    while b"\r\n\r\n" not in request:
                        chunk = connection.recv(4_096)
                        if not chunk:
                            raise AssertionError("owned object request ended before headers")
                        request.extend(chunk)
                    header, body = bytes(request).split(b"\r\n\r\n", 1)
                    method, path, _version = header.split(b"\r\n", 1)[0].split(b" ", 2)
                    if method == b"GET" and path == b"/source":
                        connection.sendall(
                            b"HTTP/1.1 200 OK\r\nContent-Length: "
                            + str(len(self._source)).encode("ascii")
                            + b"\r\n\r\n"
                            + self._source
                        )
                        continue
                    if method != b"PUT" or path != b"/upload":
                        raise AssertionError(header)
                    content_length = next(
                        int(line.split(b":", 1)[1].strip())
                        for line in header.split(b"\r\n")
                        if line.lower().startswith(b"content-length:")
                    )
                    while len(body) < content_length:
                        chunk = connection.recv(4_096)
                        if not chunk:
                            raise AssertionError("owned upload ended before declared bytes")
                        body += chunk
                    self.put_body = body
                    self.put_bodies.append(body)
                    assert self._storage.last_put_key is not None
                    self._storage.objects[self._storage.last_put_key] = (
                        inspection_api.ObjectStorageObservation(
                            object_key=self._storage.last_put_key,
                            exists=True,
                            size_bytes=len(body),
                            sha256=_digest(body),
                            content_type="image/tiff",
                        )
                    )
                    if self.drop_next_put_response:
                        self.drop_next_put_response = False
                        continue
                    connection.sendall(b"HTTP/1.1 201 Created\r\nContent-Length: 0\r\n\r\n")
        except OSError as exc:
            if not self._stop.is_set() and self._listener.fileno() >= 0:
                self.errors.append(exc)
        except BaseException as exc:  # surfaced by __exit__
            self.errors.append(exc)


class _InspectorUdsServer:
    """A two-attempt synthetic executor which reads every bound source byte."""

    def __init__(
        self,
        path: Path,
        *,
        source: bytes,
        derivative: bytes,
        sanitized_derivatives: tuple[bytes, ...] | None = None,
        wire_duration_millis: int = 5_000,
        reject_inspection: bool = False,
        maximum_connections: int = 2,
    ) -> None:
        if type(maximum_connections) is not int or maximum_connections < 1:
            raise ValueError("owned inspector UDS needs a positive connection bound")
        self._source = source
        self._derivative = derivative
        if sanitized_derivatives is not None and (
            not sanitized_derivatives
            or any(type(item) is not bytes for item in sanitized_derivatives)
        ):
            raise ValueError("owned inspector derivatives must be non-empty bytes")
        self._sanitized_derivatives = sanitized_derivatives or (derivative,)
        self._wire_duration_millis = wire_duration_millis
        self._reject_inspection = reject_inspection
        self._maximum_connections = maximum_connections
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.bind(str(path))
        path.chmod(0o600)
        self._listener.listen(maximum_connections)
        self._listener.settimeout(0.1)
        self.errors: list[BaseException] = []
        self.seen: list[bytes] = []
        self.inspection_outcomes: list[ArtifactOutcome] = []
        self.operations: list[InspectorOperation] = []
        self.sanitized_outputs: list[bytes] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve)

    def __enter__(self) -> _InspectorUdsServer:
        self._thread.start()
        return self

    def __exit__(self, kind: object, *_args: object) -> None:
        self._stop.set()
        self._listener.close()
        self._thread.join(timeout=2)
        assert not self._thread.is_alive(), "owned inspector UDS server did not stop"
        if kind is None and self.errors:
            raise self.errors[0]

    def _serve(self) -> None:
        limits = ProtocolLimitsV1(
            max_header_bytes=4_096,
            max_chunk_bytes=64,
            max_input_bytes=4_096,
            max_output_bytes=4_096,
            max_wire_duration_millis=self._wire_duration_millis,
        )
        try:
            accepted = 0
            while accepted < self._maximum_connections and not self._stop.is_set():
                try:
                    connection, _address = self._listener.accept()
                except TimeoutError:
                    continue
                with connection:
                    accepted += 1
                    request = read_launch_request_header(connection, limits)
                    self.operations.append(request.operation)
                    sink = DeadlineBoundedMemorySink()
                    read_bound_bytes(connection, request.sealed_byte_binding, limits, sink)
                    observed = b"".join(sink.chunks)
                    assert observed == self._source
                    self.seen.append(observed)
                    write_launch_result(
                        connection, InspectorLaunchResultV1.accepted(request.attempt_nonce), limits
                    )
                    if request.operation.value == "INSPECT":
                        outcome = (
                            inspection_report(
                                request_id=request.request.request_id,
                                policy=request.policy,
                                worker=request.fence.worker_instance_id,
                                acquisition=request.fence.lease_acquisition_id,
                                generation=request.fence.lease_generation,
                            )
                            .measurement_payload.outcomes[0]
                            .model_copy(
                                update={
                                    "observed_sha256": request.sealed_byte_binding.observed_sha256,
                                    **(
                                        {
                                            "outcome": ArtifactOutcome.REJECTED,
                                            "reason": "UNSUPPORTED_RASTER",
                                            "measurements": None,
                                        }
                                        if self._reject_inspection
                                        else {}
                                    ),
                                }
                            )
                        )
                        self.inspection_outcomes.append(outcome.outcome)
                        terminal = InspectorLaunchResultV1.completed_inspection(
                            request.attempt_nonce,
                            request.canonical_input_digest,
                            request.policy.parser_build_digest,
                            outcome,
                        )
                        write_launch_result(connection, terminal, limits)
                    else:
                        sanitize_index = len(self.sanitized_outputs)
                        derivative = self._sanitized_derivatives[
                            min(sanitize_index, len(self._sanitized_derivatives) - 1)
                        ]
                        self.sanitized_outputs.append(derivative)
                        terminal = InspectorLaunchResultV1.completed_sanitized(
                            request.attempt_nonce,
                            request.canonical_input_digest,
                            request.policy.parser_build_digest,
                            len(derivative),
                            _digest(derivative),
                        )
                        write_launch_result(connection, terminal, limits)
                        connection.sendall(derivative)
                        connection.shutdown(socket.SHUT_WR)
        except OSError as exc:
            if not self._stop.is_set() and self._listener.fileno() >= 0:
                self.errors.append(exc)
        except BaseException as exc:  # surfaced by __exit__
            self.errors.append(exc)


class _ObjectBoundInspectionCore:
    """Retains actual Core authority while replacing only opaque local object capabilities."""

    def __init__(
        self, core: ExternalValidationCoreClient, server: _InspectionAndDisplayObjectServer
    ) -> None:
        self._core = core
        self._server = server

    def __getattr__(self, name: str) -> Any:
        return getattr(self._core, name)

    def capability_for(
        self, request_id: str, fence: Any, artifact: Any
    ) -> ExternalObjectCapabilityV1:
        self._core.capability_for(request_id, fence, artifact)
        return ExternalObjectCapabilityV1(artifact, self._server.source_url, {})

    def grant_display_upload(
        self, request_id: str, fence: Any, declaration: Any, *, deadline_monotonic: float
    ) -> ExternalDisplayUploadCapability:
        granted = self._core.grant_display_upload(
            request_id, fence, declaration, deadline_monotonic=deadline_monotonic
        )
        return ExternalDisplayUploadCapability(
            granted.declaration, self._server.upload_url, granted.required_headers
        )


class _FailSealAfterUploadCore(_ObjectBoundInspectionCore):
    """Simulates a stopped worker only after actual Core grant and bounded PUT."""

    def __init__(
        self, core: ExternalValidationCoreClient, server: _InspectionAndDisplayObjectServer
    ) -> None:
        super().__init__(core, server)
        self.declaration: Any | None = None

    def grant_display_upload(
        self, request_id: str, fence: Any, declaration: Any, *, deadline_monotonic: float
    ) -> ExternalDisplayUploadCapability:
        grant = super().grant_display_upload(
            request_id, fence, declaration, deadline_monotonic=deadline_monotonic
        )
        self.declaration = grant.declaration
        return grant

    def seal_display_upload(
        self, request_id: str, fence: Any, grant: Any, *, deadline_monotonic: float
    ) -> None:
        del request_id, fence, grant, deadline_monotonic
        raise ExternalCoreClientError("DISPLAY_WORKER_STOPPED")


class _RecordingDisplayGrantCore(_ObjectBoundInspectionCore):
    """Records only Core's sealed declaration across a response-loss retry."""

    def __init__(
        self, core: ExternalValidationCoreClient, server: _InspectionAndDisplayObjectServer
    ) -> None:
        super().__init__(core, server)
        self.declarations: list[object] = []
        self.attempted_declarations: list[object] = []

    def grant_display_upload(
        self, request_id: str, fence: Any, declaration: Any, *, deadline_monotonic: float
    ) -> ExternalDisplayUploadCapability:
        self.attempted_declarations.append(declaration)
        grant = super().grant_display_upload(
            request_id, fence, declaration, deadline_monotonic=deadline_monotonic
        )
        self.declarations.append(grant.declaration)
        return grant


@pytest.mark.parametrize(
    ("source", "reject_inspection", "drop_first_put_response"),
    (
        (b"ortho-bytes!", False, False),
        (b"ortho-bytes!", False, True),
        (b"not-a-geotiff", True, False),
    ),
)
def test_runner_drives_actual_core_octet_source_through_real_uds_inspection_and_display(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: bytes,
    reject_inspection: bool,
    drop_first_put_response: bool,
) -> None:
    """Core admits the exact profile; the owned parser boundary may reject bytes."""

    derivative = b"sanitized-tiff"

    def bound_policy() -> Any:
        return (
            policy_template()
            .model_copy(
                update={
                    "grammar_digest": external_geotiff_profile_digest_v1(),
                    "policy_digest": None,
                },
                deep=True,
            )
            .sealed()
        )

    def bound_submission() -> Any:
        original = sealed_submission()
        return original.model_copy(
            update={
                "artifacts": (
                    original.artifacts[0].model_copy(
                        update={
                            "declared_sha256": _digest(source).removeprefix("sha256:"),
                            "declared_size_bytes": len(source),
                        }
                    ),
                ),
                "submission_digest": None,
            },
            deep=True,
        ).sealed()

    def bound_manifest() -> ExternalReconstructionManifestV1:
        submission = bound_submission()
        return ExternalReconstructionManifestV1.from_submission(
            submission,
            manifest_id="manifest-actual-uds",
            observed_at=datetime(2026, 9, 9, tzinfo=UTC),
            observed_by_service="owned-runner-integration",
            organization_id=submission.organization_id,
            site_id=submission.site_id,
            observation_epoch_id=submission.observation_epoch_id,
            entries=(
                ExternalReconstructionManifestEntryV1(
                    artifact_id="ortho",
                    kind=ProcessingArtifactKind.ORTHO,
                    object_key="external-reconstruction/v1/synthetic-ortho",
                    observed_sha256=_digest(source).removeprefix("sha256:"),
                    observed_size_bytes=len(source),
                    observed_content_type="application/octet-stream",
                ),
            ),
        )

    def bound_subject() -> Any:
        return inspection_subject().model_copy(
            update={
                "submission_digest": bound_submission().submission_digest,
                "manifest_digest": bound_manifest().manifest_digest,
            }
        )

    monkeypatch.setattr(inspection_api, "policy_template", bound_policy)
    monkeypatch.setattr(inspection_api, "sealed_submission", bound_submission)
    monkeypatch.setattr(inspection_api, "sealed_manifest", bound_manifest)
    monkeypatch.setattr(inspection_api, "subject", bound_subject)
    app, _request_id, policy, storage, _submission_ref = inspection_api._active_scoped_app(tmp_path)
    uds_path = tmp_path / "inspector.sock"
    with _InspectionAndDisplayObjectServer(  # noqa: SIM117 - fixture teardown order is explicit
        source=source,
        storage=storage,
        maximum_connections=4 if drop_first_put_response else 3,
    ) as objects:
        objects.drop_next_put_response = drop_first_put_response
        with (
            _InspectorUdsServer(
                uds_path,
                source=source,
                derivative=derivative,
                reject_inspection=reject_inspection,
                wire_duration_millis=20_000,
            ) as uds,
            TestClient(app) as core_app,
            ExternalValidationCoreClient(
                base_url="https://core.invalid",
                bearer_token="worker-token",
                transport=_CoreTestClientTransport(core_app),
            ) as core,
        ):
            fixed_core = _ObjectBoundInspectionCore(core, objects)
            limits = ProtocolLimitsV1(
                max_header_bytes=4_096,
                max_chunk_bytes=64,
                max_input_bytes=4_096,
                max_output_bytes=4_096,
                max_wire_duration_millis=20_000,
            )
            sink_root = tmp_path / "private-output"
            sink_root.mkdir(mode=0o700)
            sink = FileSystemSanitizedOutputSink(private_root=sink_root)
            inspection = InspectionValidationLane(
                core=cast(Any, fixed_core),
                worker_instance_id=_fence().worker_instance_id,
                dependencies=InspectionLaneDependencies(
                    launcher=ExternalInspectorUdsClient(
                        connect=FixedInspectionUdsConnector(
                            LocalWorkerSocketIdentityV1(
                                path=uds_path,
                                owner_uid=os.geteuid(),
                                owner_gid=os.getegid(),
                                mode=0o600,
                                peer_uid=os.geteuid(),
                            )
                        ),
                        protocol_limits=limits,
                        sanitized_output_sink=sink,
                        heartbeat_interval_millis=10,
                    ),
                    operation_profile=PinnedInspectionProfileV1(
                        parser_build_digest=cast(Any, policy).parser_build_digest,
                        grammar_digest=external_geotiff_profile_digest_v1(),
                    ),
                    candidate_sink=sink,
                    object_policy=ExternalObjectTransportPolicyV1(
                        endpoints=(
                            TrustedObjectEndpointV1(
                                origin=objects.origin, addresses=("127.0.0.1",)
                            ),
                        ),
                        max_header_bytes=4_096,
                        max_object_bytes=4_096,
                        max_chunk_bytes=64,
                    ),
                    worker_limits=WorkerAuthorityLimitsV1(
                        heartbeat_interval_millis=10, max_authority_wait_millis=20_000
                    ),
                ),
            )
            # The production lane retains this one deadline for both
            # phases; this fixture grants enough of that original
            # budget for two real Core/UDS turns.
            deadline = time.monotonic() + 20
            request_id = inspection.poll(deadline_monotonic=deadline)
            assert request_id is not None
            lease = inspection.claim(
                request_id,
                _fence().lease_acquisition_id,
                deadline_monotonic=deadline,
            )
            assert lease is not None
            # A completed public INSPECTION turn must refresh the same
            # live Core lease and publish DISPLAY itself. Calling the
            # private phase methods here would hide a release/reclaim
            # regression.
            outcome = inspection.execute(lease, deadline_monotonic=deadline, stop=threading.Event())
            assert outcome is TurnOutcome.COMPLETED, (
                outcome,
                uds.operations,
                objects.put_bodies,
                objects.errors,
            )
            inspection.release(lease)

    assert uds.seen == ([source] if reject_inspection else [source, source])
    assert uds.inspection_outcomes == [
        ArtifactOutcome.REJECTED if reject_inspection else ArtifactOutcome.MEASURED
    ]
    assert objects.put_body == (b"" if reject_inspection else derivative)
    assert objects.put_bodies == (
        [] if reject_inspection else [derivative] * (2 if drop_first_put_response else 1)
    )
    assert list(sink_root.iterdir()) == []


def test_production_display_reclaim_uses_generation_two_lease_and_immutable_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new DISPLAY lease resumes one report after grant/PUT-before-seal interruption."""

    source, derivative = b"reclaim-ortho-source", b"reclaim-display-derivative"
    changed_derivative = b"reclaim-changed-derivative"

    def bound_policy() -> Any:
        original = policy_template()
        assert original.resource_envelope is not None
        envelope = original.resource_envelope.model_copy(
            update={"max_deadline_seconds": 60.0, "resource_envelope_digest": None},
            deep=True,
        ).sealed()
        return original.model_copy(
            update={
                "grammar_digest": external_geotiff_profile_digest_v1(),
                "resource_envelope": envelope,
                "resource_envelope_digest": envelope.resource_envelope_digest,
                "policy_digest": None,
            },
            deep=True,
        ).sealed()

    def bound_submission() -> Any:
        original = sealed_submission()
        return original.model_copy(
            update={
                "artifacts": (
                    original.artifacts[0].model_copy(
                        update={
                            "declared_sha256": _digest(source).removeprefix("sha256:"),
                            "declared_size_bytes": len(source),
                        }
                    ),
                ),
                "submission_digest": None,
            },
            deep=True,
        ).sealed()

    def bound_manifest() -> ExternalReconstructionManifestV1:
        submission = bound_submission()
        return ExternalReconstructionManifestV1.from_submission(
            submission,
            manifest_id="manifest-generation-two-reclaim",
            observed_at=datetime(2026, 9, 9, tzinfo=UTC),
            observed_by_service="owned-runner-reclaim",
            organization_id=submission.organization_id,
            site_id=submission.site_id,
            observation_epoch_id=submission.observation_epoch_id,
            entries=(
                ExternalReconstructionManifestEntryV1(
                    artifact_id="ortho",
                    kind=ProcessingArtifactKind.ORTHO,
                    object_key="external-reconstruction/v1/reclaim-ortho",
                    observed_sha256=_digest(source).removeprefix("sha256:"),
                    observed_size_bytes=len(source),
                    observed_content_type="application/octet-stream",
                ),
            ),
        )

    def bound_subject() -> Any:
        return inspection_subject().model_copy(
            update={
                "submission_digest": bound_submission().submission_digest,
                "manifest_digest": bound_manifest().manifest_digest,
            }
        )

    monkeypatch.setattr(inspection_api, "policy_template", bound_policy)
    monkeypatch.setattr(inspection_api, "sealed_submission", bound_submission)
    monkeypatch.setattr(inspection_api, "sealed_manifest", bound_manifest)
    monkeypatch.setattr(inspection_api, "subject", bound_subject)
    app, _request_id, policy, storage, _submission_ref = inspection_api._active_scoped_app(tmp_path)
    uds_path = tmp_path / "reclaim-inspector.sock"

    def lane_for(core: object, sink: FileSystemSanitizedOutputSink) -> InspectionValidationLane:
        limits = ProtocolLimitsV1(
            max_header_bytes=4_096,
            max_chunk_bytes=64,
            max_input_bytes=4_096,
            max_output_bytes=4_096,
            max_wire_duration_millis=20_000,
        )
        return InspectionValidationLane(
            core=cast(Any, core),
            worker_instance_id=_fence().worker_instance_id,
            dependencies=InspectionLaneDependencies(
                launcher=ExternalInspectorUdsClient(
                    connect=FixedInspectionUdsConnector(
                        LocalWorkerSocketIdentityV1(
                            path=uds_path,
                            owner_uid=os.geteuid(),
                            owner_gid=os.getegid(),
                            mode=0o600,
                            peer_uid=os.geteuid(),
                        )
                    ),
                    protocol_limits=limits,
                    sanitized_output_sink=sink,
                    heartbeat_interval_millis=10,
                ),
                operation_profile=PinnedInspectionProfileV1(
                    parser_build_digest=cast(Any, policy).parser_build_digest,
                    grammar_digest=external_geotiff_profile_digest_v1(),
                ),
                candidate_sink=sink,
                object_policy=ExternalObjectTransportPolicyV1(
                    endpoints=(
                        TrustedObjectEndpointV1(origin=objects.origin, addresses=("127.0.0.1",)),
                    ),
                    max_header_bytes=4_096,
                    max_object_bytes=4_096,
                    max_chunk_bytes=64,
                ),
                worker_limits=WorkerAuthorityLimitsV1(
                    heartbeat_interval_millis=10, max_authority_wait_millis=20_000
                ),
            ),
        )

    with _InspectionAndDisplayObjectServer(  # noqa: SIM117 - fixture teardown order is explicit
        # Four bounded source reads plus two owned upload attempts.
        source=source,
        storage=storage,
        maximum_connections=6,
    ) as objects:
        with _InspectorUdsServer(
            uds_path,
            source=source,
            derivative=derivative,
            sanitized_derivatives=(derivative, changed_derivative, derivative),
            wire_duration_millis=20_000,
            maximum_connections=4,
        ) as uds:
            with TestClient(app) as core_app:
                first_transport = _CoreTestClientTransport(core_app)
                with ExternalValidationCoreClient(
                    base_url="https://core.invalid",
                    bearer_token="worker-token",
                    transport=first_transport,
                ) as first_client:
                    first_sink_root = tmp_path / "first-private-output"
                    first_sink_root.mkdir(mode=0o700)
                    first_sink = FileSystemSanitizedOutputSink(private_root=first_sink_root)
                    stopped_core = _FailSealAfterUploadCore(first_client, objects)
                    first_lane = lane_for(stopped_core, first_sink)
                    first_deadline = time.monotonic() + 20
                    request_id = first_lane.poll(deadline_monotonic=first_deadline)
                    assert request_id is not None
                    first_lease = first_lane.claim(
                        request_id,
                        _fence().lease_acquisition_id,
                        deadline_monotonic=first_deadline,
                    )
                    assert first_lease is not None
                    with pytest.raises(
                        ExternalLaneUnavailable, match="inspection display unavailable"
                    ):
                        first_lane.execute(
                            first_lease,
                            deadline_monotonic=first_deadline,
                            stop=threading.Event(),
                        )
                    assert stopped_core.declaration is not None
                    assert objects.put_bodies == [derivative]
                    assert list(first_sink_root.iterdir()) == []

                    # The report stays immutable after the stopped worker. A
                    # real wall-clock expiry makes the next claim generation 2.
                    before_reclaim = first_client.current_input(
                        request_id,
                        first_lease.fence,
                        deadline_monotonic=time.monotonic() + 2,
                    )
                    assert before_reclaim is not None and before_reclaim.accepted_report is not None
                    accepted_report = before_reclaim.accepted_report
                    app.state.external_artifact_inspection_store._clock = lambda: datetime.now(UTC)
                    time.sleep(4.2)

                    second_transport = _CoreTestClientTransport(core_app)
                    with ExternalValidationCoreClient(
                        base_url="https://core.invalid",
                        bearer_token="worker-token",
                        transport=second_transport,
                    ) as second_client:
                        second_sink_root = tmp_path / "second-private-output"
                        second_sink_root.mkdir(mode=0o700)
                        second_sink = FileSystemSanitizedOutputSink(private_root=second_sink_root)
                        second_core = _RecordingDisplayGrantCore(second_client, objects)
                        second_lane = lane_for(second_core, second_sink)
                        second_deadline = time.monotonic() + 20
                        assert second_lane.poll(deadline_monotonic=second_deadline) == request_id
                        second_lease = second_lane.claim(
                            request_id,
                            str(uuid4()),
                            deadline_monotonic=second_deadline,
                        )
                        assert second_lease is not None
                        assert second_lease.fence.lease_generation == 2
                        reclaimed = second_lane._current(second_lease, second_deadline)
                        assert reclaimed.accepted_report == accepted_report
                        assert reclaimed.accepted_report.lease_generation == 1

                        # A retained generation-1 client has an input cache,
                        # but Core rejects its stale mutation before storage IO.
                        with pytest.raises(ExternalCoreClientError, match="CORE_HTTP_409"):
                            first_client.grant_display_upload(
                                request_id,
                                first_lease.fence,
                                stopped_core.declaration,
                                deadline_monotonic=second_deadline,
                            )

                        # A valid-but-different terminal output yields a
                        # different declaration.  The actual Core storage
                        # rejects it before a new private PUT, then the same
                        # generation-2 lease remains available for the exact
                        # interrupted derivative.
                        with pytest.raises(
                            ExternalLaneUnavailable, match="inspection display unavailable"
                        ):
                            second_lane.execute(
                                second_lease,
                                deadline_monotonic=second_deadline,
                                stop=threading.Event(),
                            )
                        assert objects.put_bodies == [derivative]
                        assert list(second_sink_root.iterdir()) == []

                        # Core receives a grant but its first response is lost.
                        # The real publisher recovers the same declaration and
                        # candidate under generation 2 without a new INSPECT.
                        second_transport.drop_next_suffix = "/display-artifacts/upload-grants"
                        assert (
                            second_lane.execute(
                                second_lease,
                                deadline_monotonic=second_deadline,
                                stop=threading.Event(),
                            )
                            is TurnOutcome.COMPLETED
                        )
                        second_lane.release(second_lease)
                        assert list(second_sink_root.iterdir()) == []
                        # A generation-2 current fence is valid for the
                        # mutation, but the interrupted generation-1 report,
                        # source, and derivative declare the same display
                        # identity.  The accepted Core client may adjudicate
                        # the response loss without issuing a second wrapper
                        # grant, so equality matters rather than call count.
                        assert second_core.declarations
                        assert all(
                            declaration == stopped_core.declaration
                            for declaration in second_core.declarations
                        )
                        assert second_core.attempted_declarations[0] != stopped_core.declaration
                        assert all(
                            declaration == stopped_core.declaration
                            for declaration in second_core.attempted_declarations[1:]
                        )

    assert uds.operations == [
        InspectorOperation.INSPECT,
        InspectorOperation.SANITIZE,
        InspectorOperation.SANITIZE,
        InspectorOperation.SANITIZE,
    ]
    assert uds.inspection_outcomes == [ArtifactOutcome.MEASURED]
    assert uds.sanitized_outputs == [derivative, changed_derivative, derivative]
    assert objects.put_bodies == [derivative, derivative]


class _FiniteObjectGetServer:
    """Owned bounded raw-HTTP source fixture; each path may be read once."""

    def __init__(self, bodies: dict[str, bytes]) -> None:
        self._bodies = dict(bodies)
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(len(bodies))
        self._listener.settimeout(0.1)
        self._stop = threading.Event()
        self.errors: list[BaseException] = []
        self._thread = threading.Thread(target=self._serve)

    @property
    def origin(self) -> str:
        host, port = self._listener.getsockname()
        return f"http://{host}:{port}"

    def url_for(self, path: str) -> str:
        return self.origin + path

    def __enter__(self) -> _FiniteObjectGetServer:
        self._thread.start()
        return self

    def __exit__(self, kind: object, *_args: object) -> None:
        self._stop.set()
        self._listener.close()
        self._thread.join(timeout=2)
        assert not self._thread.is_alive(), "owned measurement object server did not stop"
        if kind is None and self.errors:
            raise self.errors[0]

    def _serve(self) -> None:
        try:
            while self._bodies and not self._stop.is_set():
                try:
                    connection, _address = self._listener.accept()
                except TimeoutError:
                    continue
                with connection:
                    request = bytearray()
                    while b"\r\n\r\n" not in request:
                        chunk = connection.recv(4_096)
                        if not chunk:
                            raise AssertionError("owned object request ended before headers")
                        request.extend(chunk)
                    header = bytes(request).split(b"\r\n\r\n", 1)[0]
                    method, path, _version = header.split(b"\r\n", 1)[0].split(b" ", 2)
                    if method != b"GET":
                        raise AssertionError(header)
                    body = self._bodies.pop(path.decode("ascii"), None)
                    if body is None:
                        raise AssertionError(header)
                    connection.sendall(
                        b"HTTP/1.1 200 OK\r\nContent-Length: "
                        + str(len(body)).encode("ascii")
                        + b"\r\n\r\n"
                        + body
                    )
        except OSError as exc:
            if not self._stop.is_set() and self._listener.fileno() >= 0:
                self.errors.append(exc)
        except BaseException as exc:  # surfaced by __exit__
            self.errors.append(exc)


class _MeasurementUdsServer:
    """One real V2 UDS exchange that reads both sources and returns a sealed result."""

    def __init__(
        self, *, path: Path, manifest: object, operation: str, bodies: tuple[bytes, bytes]
    ) -> None:
        self._manifest = manifest
        self._operation = operation
        self._bodies = bodies
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.bind(str(path))
        path.chmod(0o600)
        self._listener.listen(1)
        self._listener.settimeout(0.1)
        self._stop = threading.Event()
        self.errors: list[BaseException] = []
        self.requests: list[object] = []
        self._thread = threading.Thread(target=self._serve)

    def __enter__(self) -> _MeasurementUdsServer:
        self._thread.start()
        return self

    def __exit__(self, kind: object, *_args: object) -> None:
        self._stop.set()
        self._listener.close()
        self._thread.join(timeout=2)
        assert not self._thread.is_alive(), "owned measurement UDS server did not stop"
        if kind is None and self.errors:
            raise self.errors[0]

    def _serve(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    connection, _address = self._listener.accept()
                except TimeoutError:
                    continue
                with connection:
                    receiver = MeasurementRequestReceiverV2(
                        connection,
                        measurement_limits(),
                        wait_is_current=lambda: True,
                        heartbeat_interval_millis=10,
                    )
                    request = receiver.read_header()
                    assert request.operation == self._operation
                    primary, secondary = DeadlineBoundedMemorySink(), DeadlineBoundedMemorySink()
                    receiver.read_primary(primary)
                    receiver.read_secondary(secondary)
                    assert receiver.complete
                    assert (b"".join(primary.chunks), b"".join(secondary.chunks)) == self._bodies
                    self.requests.append(request)
                    result = (
                        _completed_checkpoint_result(request, self._manifest)
                        if self._operation == "CHECKPOINT_VALIDATION"
                        else _completed_result(request, self._manifest)
                    )
                    payload = result.canonical_bytes(
                        request=request, manifest=self._manifest, limits=measurement_limits()
                    )
                    connection.sendall(struct.pack(">I", len(payload)) + payload)
                    connection.shutdown(socket.SHUT_WR)
                    return
        except OSError as exc:
            if not self._stop.is_set() and self._listener.fileno() >= 0:
                self.errors.append(exc)
        except BaseException as exc:  # surfaced by __exit__
            self.errors.append(exc)


def _actual_measurement_core_apps(
    tmp_path: Path,
    *,
    checkpoint_bodies: tuple[bytes, bytes],
    volume_bodies: tuple[bytes, bytes],
    objects: _FiniteObjectGetServer,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    FastAPI,
    ExternalEvidenceValidationStore,
    str,
    object,
    FastAPI,
    Any,
    str,
    object,
]:
    """Issue and serve both V2 measurement launches through assembled Core routers."""

    from ksi_core.external_relative_volume_launch_material import VolumeWorkerLaunchMaterialResolver
    from ksi_core.external_relative_volumes import (
        ExternalRelativeVolumeQueuePolicy,
        ExternalRelativeVolumeStore,
    )
    from test_external_measurement_core_client import _manifest_for_resource_envelope
    from test_external_relative_volumes import (
        _AuthorityPort,
        _launch_ready_authority,
        _principal,
        _StaticVolumeEvidence,
        _StaticVolumePolicyRegistry,
        _volume_evidence_material,
    )

    now = datetime.now(UTC)
    monkeypatch.setattr(evidence_contract, "NOW", now)

    item = evidence_contract._evidence()
    declaration = item.declaration.model_copy(
        update={
            "declared_content_digest": _digest(checkpoint_bodies[1]),
            "declaration_digest": None,
        },
        deep=True,
    ).sealed()
    assert item.manifest is not None
    evidence_manifest = item.manifest.model_copy(
        update={
            "declaration_digest": declaration.declaration_digest,
            "target_dsm_observed_sha256": _digest(checkpoint_bodies[0]),
            "observed_object_digest": _digest(checkpoint_bodies[1]),
            "observed_size_bytes": len(checkpoint_bodies[1]),
            "evidence_manifest_digest": None,
        },
        deep=True,
    ).sealed()
    item = replace(item, declaration=declaration, manifest=evidence_manifest)
    registry, policy = evidence_contract._policy_registry(tmp_path / "checkpoint-policy")
    checkpoint_manifest = _manifest_for_resource_envelope(policy.resource_envelope_digest or "")
    checkpoint_manifest_digest = checkpoint_manifest.canonical_body_digest()
    context = (
        evidence_contract._context(item, policy)
        .model_copy(
            update={
                "measurement_execution_manifest_digest": checkpoint_manifest_digest,
                "context_digest": None,
            },
            deep=True,
        )
        .sealed()
    )

    class LoopbackCheckpointCapabilities:
        def issue_input(
            self, *, item: Any, request: Any, context: Any
        ) -> tuple[ExternalEvidenceValidationInputBinding, ExternalEvidenceValidationInputBinding]:
            del request
            assert item.manifest is not None
            return (
                ExternalEvidenceValidationInputBinding(
                    role="CHECKPOINT_CSV",
                    artifact_id=item.manifest.evidence_manifest_id,
                    observed_sha256=context.evidence_observed_sha256,
                    observed_size_bytes=context.evidence_observed_size_bytes,
                    content_type="text/csv",
                    download_url=objects.url_for("/checkpoint-csv"),
                    required_headers={},
                ),
                ExternalEvidenceValidationInputBinding(
                    role="TARGET_DSM",
                    artifact_id=context.target_dsm_artifact_id,
                    observed_sha256=context.target_dsm_observed_sha256,
                    observed_size_bytes=len(checkpoint_bodies[0]),
                    content_type="image/tiff",
                    download_url=objects.url_for("/checkpoint-target"),
                    required_headers={},
                ),
            )

    checkpoint_store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "checkpoint-core.jsonl"),
        evidence=evidence_contract._Evidence(item),
        policy_registry=registry,
        context_authority=evidence_contract._ContextAuthority(context),
        input_capabilities=LoopbackCheckpointCapabilities(),
        clock=lambda: now,
    )
    checkpoint_issued = checkpoint_store.issue_after_seal(item.evidence_ref, now=now)
    assert checkpoint_issued.request is not None
    checkpoint_worker = Principal(
        principal_id="runner-checkpoint-worker",
        kind=PrincipalKind.PROCESSING_WORKER,
        role=None,
        device_id=None,
        organization_id="org-a",
    )
    checkpoint_app = FastAPI()
    mount_auth(
        checkpoint_app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(_RUNNER_CHECKPOINT_TOKEN.encode()).hexdigest(),
                    principal=checkpoint_worker,
                )
            ]
        ),
    )
    mount_external_evidence_validations(checkpoint_app, checkpoint_store)

    authority, volume_policy, _unused_material = _launch_ready_authority()
    baseline = authority.baseline.model_copy(
        update={
            "observed_sha256": _digest(volume_bodies[0]),
            "observed_size_bytes": len(volume_bodies[0]),
        }
    )
    current = authority.current.model_copy(
        update={
            "observed_sha256": _digest(volume_bodies[1]),
            "observed_size_bytes": len(volume_bodies[1]),
        }
    )
    authority = replace(authority, baseline=baseline, current=current)
    volume_material = _volume_evidence_material(authority, volume_policy)
    assert volume_policy.resource_envelope_digest is not None
    volume_manifest = _manifest_for_resource_envelope(volume_policy.resource_envelope_digest)
    execution_policy = authority.execution_policy.model_copy(
        update={
            "algorithm_build_digest": volume_manifest.canonical_body_digest(),
            "policy_digest": None,
        },
        deep=True,
    ).sealed()
    authority = replace(
        authority,
        evidence_record_digests=tuple(volume_material),
        execution_policy=execution_policy,
        baseline_rmse_m=0.1,
        current_rmse_m=0.1,
    )
    volume_port = _AuthorityPort(authority)
    volume_registry = _StaticVolumePolicyRegistry(
        volume_policy, volume_port.currentness_coordinator
    )
    volume_registry.subjects = (authority.baseline.subject, authority.current.subject)
    volume_evidence = _StaticVolumeEvidence(volume_material, volume_port.currentness_coordinator)
    volume_store = ExternalRelativeVolumeStore(
        DurableJournal(tmp_path / "volume-core.jsonl"),
        authority_port=volume_port,
        currentness_coordinator=volume_port.currentness_coordinator,
        queue_policy=ExternalRelativeVolumeQueuePolicy(
            lease_ttl=timedelta(minutes=5),
            deadline_after_issue=timedelta(hours=1),
            max_attempts=3,
            max_active_requests_per_organization=8,
        ),
        launch_material_resolver=VolumeWorkerLaunchMaterialResolver(
            policy_registry=cast(Any, volume_registry),
            evidence_validations=cast(Any, volume_evidence),
            currentness_coordinator=volume_port.currentness_coordinator,
        ),
        clock=lambda: datetime(2026, 9, 9, tzinfo=UTC),
    )
    volume_issued = volume_store.issue(
        principal=_principal(),
        current_work_order_id="work-current",
        decision_ref="decision-a",
        idempotency_key="runner-three-lane-volume",
        now=datetime(2026, 9, 9, tzinfo=UTC),
    )
    assert volume_issued.record is not None
    volume_request_id = volume_issued.record.request.request_id
    volume_worker = Principal(
        principal_id="worker-principal",
        kind=PrincipalKind.PROCESSING_WORKER,
        role=None,
        device_id=None,
        organization_id="org-a",
    )

    def issue_volume_capabilities(
        *_args: object, **_kwargs: object
    ) -> tuple[ExternalRelativeVolumeInputCapability, ExternalRelativeVolumeInputCapability]:
        expires_at = now + timedelta(minutes=5)
        return (
            ExternalRelativeVolumeInputCapability(
                role="BASELINE_DSM",
                download_url=objects.url_for("/volume-base"),
                required_headers={},
                expires_at=expires_at,
            ),
            ExternalRelativeVolumeInputCapability(
                role="CURRENT_DSM",
                download_url=objects.url_for("/volume-current"),
                required_headers={},
                expires_at=expires_at,
            ),
        )

    volume_app = FastAPI()
    mount_auth(
        volume_app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(_VOLUME_WORKER_TOKEN.encode()).hexdigest(),
                    principal=volume_worker,
                )
            ]
        ),
    )
    volume_app.include_router(
        build_external_relative_volume_router(
            volume_store,
            input_capability_issuer=issue_volume_capabilities,
            clock=lambda: datetime(2026, 9, 9, tzinfo=UTC),
        )
    )
    return (
        checkpoint_app,
        checkpoint_store,
        checkpoint_issued.request.validation_id,
        checkpoint_manifest,
        volume_app,
        volume_store,
        volume_request_id,
        volume_manifest,
    )


def test_single_runner_composes_actual_core_clients_and_real_uds_for_three_lanes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One scheduler drives actual Core issuance/claims/reports and owned local IO seams."""

    source, derivative = b"runner-octet-source", b"runner-display-derivative"

    def bound_policy() -> Any:
        return (
            policy_template()
            .model_copy(
                update={
                    "grammar_digest": external_geotiff_profile_digest_v1(),
                    "policy_digest": None,
                },
                deep=True,
            )
            .sealed()
        )

    def bound_submission() -> Any:
        original = sealed_submission()
        return original.model_copy(
            update={
                "artifacts": (
                    original.artifacts[0].model_copy(
                        update={
                            "declared_sha256": _digest(source).removeprefix("sha256:"),
                            "declared_size_bytes": len(source),
                        }
                    ),
                ),
                "submission_digest": None,
            },
            deep=True,
        ).sealed()

    def bound_manifest() -> ExternalReconstructionManifestV1:
        submission = bound_submission()
        return ExternalReconstructionManifestV1.from_submission(
            submission,
            manifest_id="runner-three-lane-manifest",
            observed_at=datetime(2026, 9, 9, tzinfo=UTC),
            observed_by_service="owned-runner-three-lane",
            organization_id=submission.organization_id,
            site_id=submission.site_id,
            observation_epoch_id=submission.observation_epoch_id,
            entries=(
                ExternalReconstructionManifestEntryV1(
                    artifact_id="ortho",
                    kind=ProcessingArtifactKind.ORTHO,
                    object_key="external-reconstruction/v1/runner-ortho",
                    observed_sha256=_digest(source).removeprefix("sha256:"),
                    observed_size_bytes=len(source),
                    observed_content_type="application/octet-stream",
                ),
            ),
        )

    def bound_subject() -> Any:
        return inspection_subject().model_copy(
            update={
                "submission_digest": bound_submission().submission_digest,
                "manifest_digest": bound_manifest().manifest_digest,
            }
        )

    monkeypatch.setattr(inspection_api, "policy_template", bound_policy)
    monkeypatch.setattr(inspection_api, "sealed_submission", bound_submission)
    monkeypatch.setattr(inspection_api, "sealed_manifest", bound_manifest)
    monkeypatch.setattr(inspection_api, "subject", bound_subject)
    app, _request_id, policy, storage, _submission_ref = inspection_api._active_scoped_app(tmp_path)
    checkpoint_bodies = (b"checkpoint-target", b"x,y\n1,2\n")
    volume_bodies = (b"volume-baseline", b"volume-current")
    inspection_socket = tmp_path / "inspection.sock"
    checkpoint_socket, volume_socket = tmp_path / "checkpoint.sock", tmp_path / "volume.sock"
    with _InspectionAndDisplayObjectServer(  # noqa: SIM117 - fixtures have bounded nested teardown
        source=source, storage=storage
    ) as inspection_objects:
        with _InspectorUdsServer(
            inspection_socket,
            source=source,
            derivative=derivative,
            wire_duration_millis=20_000,
        ) as inspection_uds:
            with _FiniteObjectGetServer(
                {
                    "/checkpoint-target": checkpoint_bodies[0],
                    "/checkpoint-csv": checkpoint_bodies[1],
                    "/volume-base": volume_bodies[0],
                    "/volume-current": volume_bodies[1],
                }
            ) as measurement_objects:
                (
                    checkpoint_app,
                    checkpoint_store,
                    _checkpoint_request_id,
                    checkpoint_manifest,
                    volume_app,
                    volume_store,
                    volume_request_id,
                    volume_manifest,
                ) = _actual_measurement_core_apps(
                    tmp_path,
                    checkpoint_bodies=checkpoint_bodies,
                    volume_bodies=volume_bodies,
                    objects=measurement_objects,
                    monkeypatch=monkeypatch,
                )
                with _MeasurementUdsServer(  # noqa: SIM117 - two independent owned UDS fixtures
                    path=checkpoint_socket,
                    manifest=checkpoint_manifest,
                    operation="CHECKPOINT_VALIDATION",
                    bodies=checkpoint_bodies,
                ) as checkpoint_uds:
                    with _MeasurementUdsServer(
                        path=volume_socket,
                        manifest=volume_manifest,
                        operation="RELATIVE_VOLUME",
                        bodies=volume_bodies,
                    ) as volume_uds:
                        with TestClient(app) as core_app:
                            with TestClient(checkpoint_app) as checkpoint_core_app:
                                with TestClient(volume_app) as volume_core_app:
                                    with ExternalValidationCoreClient(
                                        base_url="https://core.invalid",
                                        bearer_token="worker-token",
                                        transport=_CoreTestClientTransport(core_app),
                                    ) as inspection_core:
                                        with ExternalValidationCoreClient(
                                            base_url="https://checkpoint.invalid",
                                            bearer_token=_RUNNER_CHECKPOINT_TOKEN,
                                            transport=_CoreTestClientTransport(checkpoint_core_app),
                                        ) as checkpoint_shared:
                                            with ExternalValidationCoreClient(
                                                base_url="https://volume.invalid",
                                                bearer_token=_VOLUME_WORKER_TOKEN,
                                                transport=_CoreTestClientTransport(volume_core_app),
                                            ) as volume_shared:
                                                checkpoint_core = ExternalMeasurementCoreClient(
                                                    core_client=checkpoint_shared
                                                )
                                                volume_core = ExternalMeasurementCoreClient(
                                                    core_client=volume_shared
                                                )
                                                try:
                                                    limits = ProtocolLimitsV1(
                                                        max_header_bytes=4_096,
                                                        max_chunk_bytes=64,
                                                        max_input_bytes=4_096,
                                                        max_output_bytes=4_096,
                                                        max_wire_duration_millis=20_000,
                                                    )
                                                    sink_root = tmp_path / "private-output"
                                                    sink_root.mkdir(mode=0o700)
                                                    sink = FileSystemSanitizedOutputSink(
                                                        private_root=sink_root
                                                    )
                                                    inspection_lane = InspectionValidationLane(
                                                        core=_ObjectBoundInspectionCore(
                                                            inspection_core, inspection_objects
                                                        ),
                                                        worker_instance_id=_fence().worker_instance_id,
                                                        dependencies=InspectionLaneDependencies(
                                                            launcher=ExternalInspectorUdsClient(
                                                                connect=FixedInspectionUdsConnector(
                                                                    LocalWorkerSocketIdentityV1(
                                                                        path=inspection_socket,
                                                                        owner_uid=os.geteuid(),
                                                                        owner_gid=os.getegid(),
                                                                        mode=0o600,
                                                                        peer_uid=os.geteuid(),
                                                                    )
                                                                ),
                                                                protocol_limits=limits,
                                                                sanitized_output_sink=sink,
                                                                heartbeat_interval_millis=10,
                                                            ),
                                                            operation_profile=PinnedInspectionProfileV1(
                                                                parser_build_digest=cast(
                                                                    Any, policy
                                                                ).parser_build_digest,
                                                                grammar_digest=external_geotiff_profile_digest_v1(),
                                                            ),
                                                            candidate_sink=sink,
                                                            object_policy=ExternalObjectTransportPolicyV1(
                                                                endpoints=(
                                                                    TrustedObjectEndpointV1(
                                                                        origin=inspection_objects.origin,
                                                                        addresses=("127.0.0.1",),
                                                                    ),
                                                                ),
                                                                max_header_bytes=4_096,
                                                                max_object_bytes=4_096,
                                                                max_chunk_bytes=64,
                                                            ),
                                                            worker_limits=WorkerAuthorityLimitsV1(
                                                                heartbeat_interval_millis=10,
                                                                max_authority_wait_millis=20_000,
                                                            ),
                                                        ),
                                                    )
                                                    measurement_endpoints = (
                                                        TrustedObjectEndpointV1(
                                                            origin=measurement_objects.origin,
                                                            addresses=("127.0.0.1",),
                                                        ),
                                                    )
                                                    measurement_policy = (
                                                        ExternalObjectTransportPolicyV1(
                                                            endpoints=measurement_endpoints,
                                                            max_header_bytes=4_096,
                                                            max_object_bytes=4_096,
                                                            max_chunk_bytes=64,
                                                        )
                                                    )
                                                    checkpoint_lane = MeasurementValidationLane(
                                                        lane=ExternalLane.CHECKPOINT,
                                                        operation="CHECKPOINT_VALIDATION",
                                                        core=checkpoint_core,
                                                        worker_instance_id=_fence().worker_instance_id,
                                                        dependencies=MeasurementLaneDependencies(
                                                            manifest=cast(Any, checkpoint_manifest),
                                                            uds_client=ExternalMeasurementUdsClient(
                                                                connector=FixedMeasurementUdsConnector(
                                                                    MeasurementSocketIdentityV2(
                                                                        path=checkpoint_socket,
                                                                        owner_uid=os.geteuid(),
                                                                        owner_gid=os.getegid(),
                                                                        mode=0o600,
                                                                        launcher_uid=os.geteuid(),
                                                                    )
                                                                ),
                                                                protocol_limits=measurement_limits(),
                                                                heartbeat_interval_millis=10,
                                                            ),
                                                            protocol_limits=measurement_limits(),
                                                            heartbeat_interval_millis=10,
                                                            object_policy=measurement_policy,
                                                        ),
                                                        attempt_nonce_factory=lambda: str(uuid4()),
                                                        clock=lambda: datetime.now(UTC),
                                                    )
                                                    volume_lane = MeasurementValidationLane(
                                                        lane=ExternalLane.RELATIVE_VOLUME,
                                                        operation="RELATIVE_VOLUME",
                                                        core=volume_core,
                                                        worker_instance_id=_fence().worker_instance_id,
                                                        dependencies=MeasurementLaneDependencies(
                                                            manifest=cast(Any, volume_manifest),
                                                            uds_client=ExternalMeasurementUdsClient(
                                                                connector=FixedMeasurementUdsConnector(
                                                                    MeasurementSocketIdentityV2(
                                                                        path=volume_socket,
                                                                        owner_uid=os.geteuid(),
                                                                        owner_gid=os.getegid(),
                                                                        mode=0o600,
                                                                        launcher_uid=os.geteuid(),
                                                                    )
                                                                ),
                                                                protocol_limits=measurement_limits(),
                                                                heartbeat_interval_millis=10,
                                                            ),
                                                            protocol_limits=measurement_limits(),
                                                            heartbeat_interval_millis=10,
                                                            object_policy=measurement_policy,
                                                        ),
                                                        attempt_nonce_factory=lambda: str(uuid4()),
                                                        clock=lambda: datetime(
                                                            2026, 9, 9, tzinfo=UTC
                                                        ),
                                                    )
                                                    runner = ExternalValidationRunner(
                                                        lanes=(
                                                            inspection_lane,
                                                            checkpoint_lane,
                                                            volume_lane,
                                                        ),
                                                        policy=RunnerPolicy(
                                                            turn_budget_seconds=20,
                                                            claim_retry_seconds=1,
                                                            idle_backoff_seconds=0.01,
                                                        ),
                                                    )
                                                    try:
                                                        assert [
                                                            runner.run_once() for _ in range(3)
                                                        ] == [
                                                            TurnOutcome.COMPLETED,
                                                            TurnOutcome.COMPLETED,
                                                            TurnOutcome.COMPLETED,
                                                        ]
                                                    finally:
                                                        runner.close()
                                                finally:
                                                    checkpoint_core.close()
                                                    volume_core.close()

    assert inspection_uds.seen == [source, source]
    assert checkpoint_uds.requests and volume_uds.requests
    records = checkpoint_store.terminal_records_for_evidence("eev-v1-a")
    assert len(records) == 1
    volume_record = volume_store.get(volume_request_id, organization_id="org-a")
    assert volume_record is not None and volume_record.report is not None
    assert list(sink_root.iterdir()) == []
