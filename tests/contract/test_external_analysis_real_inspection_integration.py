"""Real inspector entrypoint plumbing for the V2 Analysis HTTP acceptance."""

from __future__ import annotations

import hashlib
import os
import socket
import threading
import time
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from ksi_core.leasing import LeaseFence
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ExternalArtifactInspectionReportV1,
    ExternalInspectionMeasurementPayloadV1,
    SealedArtifactBindingV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_processing_controller.external_artifact_inspection_worker import (
    ExternalInspectorUdsClient,
    FileSystemSanitizedOutputSink,
)
from ksi_processing_controller.external_inspector_container_entrypoint import (
    run_container_entrypoint,
)
from ksi_processing_controller.external_inspector_container_protocol import (
    ContainerInnerFrameLimitsV1,
    build_execute_frame,
    build_prepare_frame,
    encode_inner_frame,
)
from ksi_processing_controller.external_inspector_protocol import (
    DeadlineBoundedBytesReader,
    DeadlineBoundedMemorySink,
    InspectorLaunchRequestV1,
    InspectorLaunchResultV1,
    InspectorOperation,
    LocalLeaseFenceV1,
    ProtocolLimitsV1,
    SealedByteBindingV1,
    read_bound_bytes,
    read_launch_request_header,
    write_launch_result,
)
from ksi_processing_controller.external_validation_worker_config import (
    FixedInspectionUdsConnector,
    LocalWorkerSocketIdentityV1,
)
from test_external_inspector_container_entrypoint import _decode_output


class _RealDsmInspectorUds:
    """Test-owned outer inspector protocol that executes the real parser entrypoint."""

    def __init__(self, *, path: Path, manifest: Any, root: Path) -> None:
        self._manifest, self._root = manifest, root
        self._path = path
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.bind(str(path))
        path.chmod(0o600)
        self._listener.listen(1)
        self._listener.settimeout(0.1)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve)
        self.errors: list[BaseException] = []
        self.measured: list[ArtifactInspectionOutcomeV1] = []
        self.source_digests: list[str] = []
        self.actual_source_digests: list[str] = []

    def __enter__(self) -> _RealDsmInspectorUds:
        self._thread.start()
        return self

    def __exit__(self, kind: object, *_args: object) -> None:
        self._stop.set()
        self._listener.close()
        self._thread.join(timeout=3)
        self._path.unlink(missing_ok=True)
        assert not self._thread.is_alive(), "owned inspector UDS server did not stop"
        if kind is None and self.errors:
            raise self.errors[0]

    def _serve(self) -> None:
        limits = ProtocolLimitsV1(
            max_header_bytes=128_000,
            max_chunk_bytes=4_096,
            max_input_bytes=4_000_000,
            max_output_bytes=4_000_000,
            max_wire_duration_millis=20_000,
        )
        try:
            while not self._stop.is_set():
                try:
                    connection, _address = self._listener.accept()
                except TimeoutError:
                    continue
                with connection:
                    request = read_launch_request_header(connection, limits)
                    source = DeadlineBoundedMemorySink()
                    read_bound_bytes(connection, request.sealed_byte_binding, limits, source)
                    payload = b"".join(source.chunks)
                    self.source_digests.append(request.sealed_byte_binding.observed_sha256)
                    actual_digest = "sha256:" + hashlib.sha256(payload).hexdigest()
                    self.actual_source_digests.append(actual_digest)
                    assert actual_digest == request.sealed_byte_binding.observed_sha256
                    write_launch_result(
                        connection,
                        InspectorLaunchResultV1.accepted(request.attempt_nonce),
                        limits,
                    )
                    artifact_path = self._root / (request.attempt_nonce + ".tif")
                    artifact_path.write_bytes(payload)
                    workspace = self._root / (request.attempt_nonce + "-workspace")
                    workspace.mkdir(mode=0o700)
                    inner_limits = ContainerInnerFrameLimitsV1(
                        maximum_frame_bytes=128_000, maximum_stderr_bytes=0
                    )
                    prepare = build_prepare_frame(
                        attempt_nonce=request.attempt_nonce,
                        outer_canonical_input_digest=request.canonical_input_digest,
                        operation=request.operation.value,
                        sealed_byte_binding=request.sealed_byte_binding.model_dump(
                            by_alias=True, mode="json"
                        ),
                        policy=request.policy,
                        manifest=self._manifest,
                        admitted_backend_profile_digest=self._manifest.body.backend_profile_digest,
                        admitted_security_profile_digest=self._manifest.body.security_profile_digest,
                        admitted_inner_protocol_digest=self._manifest.body.inspector_protocol_digest,
                    )
                    stdout = BytesIO()
                    run_container_entrypoint(
                        stdin=BytesIO(
                            encode_inner_frame(prepare, limits=inner_limits)
                            + encode_inner_frame(
                                build_execute_frame(prepare=prepare), limits=inner_limits
                            )
                        ),
                        stdout=stdout,
                        artifact_path=artifact_path,
                        workspace=workspace,
                        limits=inner_limits,
                    )
                    _mount, terminal, raw = _decode_output(stdout, inner_limits)
                    assert raw == b""
                    outcome = ArtifactInspectionOutcomeV1.model_validate(terminal["outcome"])
                    self.measured.append(outcome)
                    completed = InspectorLaunchResultV1.completed_inspection(
                        request.attempt_nonce,
                        request.canonical_input_digest,
                        self._manifest.parser_build_digest,
                        outcome,
                    )
                    write_launch_result(connection, completed, limits)
        except OSError as exc:
            if not self._stop.is_set() and self._listener.fileno() >= 0:
                self.errors.append(exc)
        except BaseException as exc:
            self.errors.append(exc)


def inspect_fixture_epochs_with_real_parser(
    fixture: Any, *, root: Path
) -> tuple[str, ...]:
    """Issue, lease, inspect sealed DSM bytes, then retain Core's measured reports."""
    if not fixture.real_inspection or fixture._inspector_manifest is None:
        raise ValueError("fixture must be configured for manifest-bound real inspection")
    store = fixture.app.state.external_artifact_inspection_store
    report_digests: list[str] = []
    records = (
        (fixture._baseline_revision, fixture._baseline_subject),
        (fixture._current_revision, fixture._current_subject),
    )
    for index, (revision, subject) in enumerate(records):
        now = max(
            datetime.now(UTC).replace(microsecond=0),
            fixture._fixture_now + timedelta(seconds=1),
        )
        issued = store.issue_after_seal(subject, now=now)
        assert issued.request is not None and issued.verdict.value in {"ISSUED", "IDEMPOTENT"}
        worker_id, acquisition_id = str(uuid4()), str(uuid4())
        claimed = store.claim(
            issued.request.request_id,
            LeaseFence(worker_id, acquisition_id, 0),
            now,
            organization_id=subject.organization_id,
        )
        assert claimed.request is not None and claimed.fence is not None
        lease_fence = LocalLeaseFenceV1(
            worker_instance_id=claimed.fence.worker_instance_id,
            lease_acquisition_id=claimed.fence.lease_acquisition_id,
            lease_generation=claimed.fence.lease_generation,
        )
        manifest_entry = revision.manifest.entries[0]
        source_bytes = fixture.storage.object_bytes(manifest_entry.object_key)
        assert len(source_bytes) == manifest_entry.observed_size_bytes
        assert "sha256:" + hashlib.sha256(source_bytes).hexdigest() == (
            "sha256:" + manifest_entry.observed_sha256
        )
        socket_path = Path("/tmp") / f"ksi-inspect-{uuid4().hex}.sock"
        work_root = root / f"inspection-{index}-private"
        work_root.mkdir(mode=0o700)
        private_output = work_root / "private-output"
        private_output.mkdir(mode=0o700)
        with _RealDsmInspectorUds(
            path=socket_path, manifest=fixture._inspector_manifest, root=work_root
        ) as inspector:
            client = ExternalInspectorUdsClient(
                connect=FixedInspectionUdsConnector(
                    LocalWorkerSocketIdentityV1(
                        path=socket_path,
                        owner_uid=os.geteuid(),
                        owner_gid=os.getegid(),
                        mode=0o600,
                        peer_uid=os.geteuid(),
                    )
                ),
                protocol_limits=ProtocolLimitsV1(
                    max_header_bytes=128_000,
                    max_chunk_bytes=4_096,
                    max_input_bytes=4_000_000,
                    max_output_bytes=4_000_000,
                    max_wire_duration_millis=20_000,
                ),
                sanitized_output_sink=FileSystemSanitizedOutputSink(private_root=private_output),
                heartbeat_interval_millis=10,
            )
            terminal = client.execute(
                request=InspectorLaunchRequestV1.seal(
                    operation=InspectorOperation.INSPECT,
                    request=issued.request,
                    fence=lease_fence,
                    subject=subject,
                    sealed_byte_binding=SealedByteBindingV1(
                        artifact_id=manifest_entry.artifact_id,
                        observed_sha256="sha256:" + manifest_entry.observed_sha256,
                        observed_size_bytes=manifest_entry.observed_size_bytes,
                    ),
                    policy=fixture._inspection_policy,
                    attempt_nonce=f"real-dsm-inspection-{index}",
                ),
                source=DeadlineBoundedBytesReader(BytesIO(source_bytes)),
                artifact_kind=ProcessingArtifactKind.DSM,
                content_type=manifest_entry.observed_content_type,
                deadline_monotonic=time.monotonic() + 20,
                authority_is_current=lambda: True,
            )
            assert terminal.result == "COMPLETED" and isinstance(
                terminal.outcome, ArtifactInspectionOutcomeV1
            )
            assert inspector.measured == [terminal.outcome]
            assert inspector.source_digests == ["sha256:" + manifest_entry.observed_sha256]
            assert inspector.actual_source_digests == ["sha256:" + manifest_entry.observed_sha256]
            outcome = terminal.outcome
            assert outcome.observed_sha256 == "sha256:" + hashlib.sha256(source_bytes).hexdigest()
            if outcome.outcome.value == "MEASURED":
                assert outcome.measurements is not None
                measured = outcome.measurements
                assert measured.observed_crs_identifier == "EPSG:5186"
                assert measured.observed_vertical_reference is not None
                assert measured.observed_vertical_reference.identifier == "EPSG:5773"
                assert measured.observed_crs_wkt is not None
                assert measured.observed_crs_digest == (
                    "sha256:"
                    + hashlib.sha256(measured.observed_crs_wkt.encode("utf-8")).hexdigest()
                )
                assert (measured.width, measured.height, measured.valid_pixel_count) == (2, 2, 4)
                assert measured.transform == (0.1, 0.0, 200000.0, 0.0, -0.1, 550000.0)
            else:
                assert outcome.outcome.value == "REJECTED"
                assert outcome.reason == "MALFORMED_TIFF"
                assert outcome.measurements is None
            fence = claimed.fence
            payload = ExternalInspectionMeasurementPayloadV1(
                subject_digest=subject.canonical_digest(),
                sealed_manifest_digest=subject.manifest_digest,
                inspection_policy_digest=fixture._inspection_policy.policy_digest,
                inspector_build_digest=fixture._inspection_policy.parser_build_digest,
                artifact_bindings=(
                    SealedArtifactBindingV1(
                        artifact_id=manifest_entry.artifact_id,
                        observed_sha256="sha256:" + manifest_entry.observed_sha256,
                    ),
                ),
                outcomes=(outcome,),
            )
            report = ExternalArtifactInspectionReportV1(
                report_id=f"real-inspection-{index}-{uuid4()}",
                request_id=issued.request.request_id,
                subject=subject,
                subject_digest=subject.canonical_digest(),
                sealed_manifest_digest=subject.manifest_digest,
                inspection_policy_digest=fixture._inspection_policy.policy_digest,
                inspector_build_digest=fixture._inspection_policy.parser_build_digest,
                measurement_payload=payload,
                worker_instance_id=fence.worker_instance_id,
                lease_acquisition_id=fence.lease_acquisition_id,
                lease_generation=fence.lease_generation,
                reported_at=now,
            ).sealed()
            recorded = store.record_report(
                issued.request.request_id,
                fence,
                report,
                now,
                organization_id=subject.organization_id,
            )
            assert recorded.report is not None and recorded.verdict.value == "REPORTED"
            report_digests.append(recorded.report.report_digest)
    fixture.synthetic_inspection_report_digests = tuple(report_digests)
    return tuple(report_digests)


def test_malformed_sealed_dsm_is_rejected_and_analysis_stays_blocked(tmp_path: Path) -> None:
    from analysis_api_local_fixture import build_local_analysis_api_fixture
    from fastapi.testclient import TestClient

    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        real_inspection=True,
        malformed_current_dsm=True,
    )
    root = tmp_path / "malformed-inspector-private"
    root.mkdir(mode=0o700)
    try:
        inspect_fixture_epochs_with_real_parser(fixture, root=root)
        current_snapshot = fixture.app.state.external_artifact_inspection_store.public_snapshot(
            fixture._current_subject
        )
        assert current_snapshot.report is not None
        current_outcomes = current_snapshot.report.measurement_payload.outcomes
        assert len(current_outcomes) == 1
        assert current_outcomes[0].outcome.value == "REJECTED"
        assert current_outcomes[0].reason == "MALFORMED_TIFF"
        assert current_outcomes[0].measurements is None

        with TestClient(fixture.app) as client:
            response = client.post(
                f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
                headers={**fixture.operator_headers(), "Idempotency-Key": "malformed-dsm-analysis"},
                json={
                    "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
                    "current": fixture.current.model_dump(by_alias=True, mode="json"),
                },
            )
        assert response.status_code == 202, response.text
        assert response.json()["suitabilityState"] == "BLOCKED"
        assert response.json()["executionState"] == "NOT_STARTED"
        assert response.json().get("result") is None
    finally:
        fixture.close()
