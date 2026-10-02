"""Authenticated Core inspection-lane to Analysis/GIS result integration."""

from __future__ import annotations

import hashlib
import os
import socket
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import Any
from urllib.parse import unquote
from uuid import uuid4

import httpx
import pytest
import uvicorn
from analysis_api_local_fixture import build_local_analysis_api_fixture
from ksi_processing_controller.external_analysis_core_client import ExternalAnalysisCoreClient
from ksi_processing_controller.external_analysis_worker import (
    ProcessingWorkerRuntimeIdentityV1,
    run_once,
)
from ksi_processing_controller.external_artifact_inspection_worker import (
    ExternalInspectorUdsClient,
    FileSystemSanitizedOutputSink,
    WorkerAuthorityLimitsV1,
)
from ksi_processing_controller.external_geotiff_profile import external_geotiff_profile_digest_v1
from ksi_processing_controller.external_inspector_protocol import ProtocolLimitsV1
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)
from ksi_processing_controller.external_validation_core_client import ExternalValidationCoreClient
from ksi_processing_controller.external_validation_lanes import (
    InspectionLaneDependencies,
    InspectionValidationLane,
)
from ksi_processing_controller.external_validation_runner import TurnOutcome
from ksi_processing_controller.external_validation_worker_config import (
    FixedInspectionUdsConnector,
    LocalWorkerSocketIdentityV1,
    PinnedInspectionProfileV1,
)
from test_external_analysis_real_inspection_integration import _RealDsmInspectorUds


class _CoreAndObjectServers:
    """Test-owned loopback endpoints used by authenticated worker clients."""

    def __init__(self, fixture: Any) -> None:
        self.fixture = fixture
        self.object_server: ThreadingHTTPServer | None = None
        self.object_thread: Thread | None = None
        self.core_server: uvicorn.Server | None = None
        self.core_thread: Thread | None = None
        self.core_socket: socket.socket | None = None
        self.core_origin = ""
        self.object_origin = ""

    def __enter__(self) -> _CoreAndObjectServers:
        fixture = self.fixture

        class ObjectHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if not self.path.startswith("/objects/"):
                    self.send_error(404)
                    return
                object_key = unquote(self.path.removeprefix("/objects/"))
                try:
                    payload = fixture.storage.object_bytes(object_key)
                except KeyError:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self.object_server = ThreadingHTTPServer(("127.0.0.1", 0), ObjectHandler)
        self.object_thread = Thread(target=self.object_server.serve_forever, daemon=True)
        self.object_thread.start()
        self.object_origin = f"http://127.0.0.1:{self.object_server.server_port}"
        fixture.set_loopback_object_origin(self.object_origin)

        listen_socket = socket.socket()
        self.core_socket = listen_socket
        listen_socket.bind(("127.0.0.1", 0))
        listen_socket.listen(128)
        self.core_origin = f"http://127.0.0.1:{listen_socket.getsockname()[1]}"
        server = uvicorn.Server(
            uvicorn.Config(fixture.app, log_level="warning", access_log=False)
        )
        self.core_server = server
        self.core_thread = Thread(
            target=lambda: server.run(sockets=[listen_socket]), daemon=True
        )
        self.core_thread.start()
        for _ in range(150):
            if server.started:
                break
            assert self.core_thread.is_alive(), "local Core server stopped during startup"
            time.sleep(0.02)
        assert server.started
        return self

    def __exit__(self, *_args: object) -> None:
        if self.core_server is not None:
            self.core_server.should_exit = True
        if self.core_thread is not None:
            self.core_thread.join(timeout=5)
            assert not self.core_thread.is_alive(), "local Core server did not stop"
        if self.core_socket is not None:
            self.core_socket.close()
        if self.object_server is not None:
            self.object_server.shutdown()
            self.object_server.server_close()
        if self.object_thread is not None:
            self.object_thread.join(timeout=5)
            assert not self.object_thread.is_alive(), "local object server did not stop"


def _inspection_lane(
    fixture: Any,
    *,
    core: ExternalValidationCoreClient,
    object_origin: str,
    socket_path: Path,
    private_root: Path,
    worker_instance_id: str,
) -> InspectionValidationLane:
    limits = ProtocolLimitsV1(
        max_header_bytes=128_000,
        max_chunk_bytes=4_096,
        max_input_bytes=4_000_000,
        max_output_bytes=4_000_000,
        max_wire_duration_millis=20_000,
    )
    private_root.mkdir(mode=0o700)
    sink = FileSystemSanitizedOutputSink(private_root=private_root)
    envelope = fixture._inspection_policy.resource_envelope
    assert envelope is not None
    return InspectionValidationLane(
        core=core,
        worker_instance_id=worker_instance_id,
        dependencies=InspectionLaneDependencies(
            launcher=ExternalInspectorUdsClient(
                connect=FixedInspectionUdsConnector(
                    LocalWorkerSocketIdentityV1(
                        path=socket_path,
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
                parser_build_digest=fixture._inspection_policy.parser_build_digest,
                grammar_digest=external_geotiff_profile_digest_v1(),
            ),
            candidate_sink=sink,
            object_policy=ExternalObjectTransportPolicyV1(
                endpoints=(
                    TrustedObjectEndpointV1(origin=object_origin, addresses=("127.0.0.1",)),
                ),
                max_header_bytes=16_384,
                max_object_bytes=envelope.max_input_bytes,
                max_chunk_bytes=min(65_536, envelope.max_input_bytes),
            ),
            worker_limits=WorkerAuthorityLimitsV1(
                heartbeat_interval_millis=10,
                max_authority_wait_millis=20_000,
            ),
        ),
    )


def _drive_two_epochs_through_lane(
    fixture: Any,
    *,
    core_origin: str,
    object_origin: str,
    tmp_path: Path,
) -> tuple[Any, ...]:
    inspection_store = fixture.app.state.external_artifact_inspection_store
    worker_id = str(uuid4())
    socket_path = Path("/tmp") / f"ksi-lane-{uuid4().hex}.sock"
    inspector_root = tmp_path / "real-inspector-lane-root"
    inspector_root.mkdir(mode=0o700)
    with _RealDsmInspectorUds(
        path=socket_path,
        manifest=fixture._inspector_manifest,
        root=inspector_root,
    ) as inspector:
        core = ExternalValidationCoreClient(
            base_url=core_origin,
            bearer_token=fixture.validation_worker_headers()["Authorization"].removeprefix(
                "Bearer "
            ),
        )
        lane = _inspection_lane(
            fixture,
            core=core,
            object_origin=object_origin,
            socket_path=socket_path,
            private_root=tmp_path / "inspection-lane-private",
            worker_instance_id=worker_id,
        )
        try:
            for index, subject in enumerate((fixture._baseline_subject, fixture._current_subject)):
                now = max(datetime.now(UTC).replace(microsecond=0), fixture._fixture_now)
                issued = inspection_store.issue_after_seal(subject, now=now)
                assert issued.request is not None
                assert issued.verdict.value in {"ISSUED", "IDEMPOTENT"}
                deadline = time.monotonic() + 25
                request_id = lane.poll(deadline_monotonic=deadline)
                assert request_id is not None
                assert request_id == issued.request.request_id
                lease = lane.claim(
                    request_id,
                    str(uuid4()),
                    deadline_monotonic=deadline,
                )
                assert lease is not None
                try:
                    turn_outcome = lane.execute(
                        lease,
                        deadline_monotonic=deadline,
                        stop=Event(),
                    )
                    assert turn_outcome is TurnOutcome.COMPLETED
                finally:
                    lane.release(lease)
                snapshot = inspection_store.public_snapshot(subject)
                assert snapshot.report is not None
                report = snapshot.report
                assert report.worker_instance_id == worker_id
                assert report.lease_acquisition_id == lease.fence.lease_acquisition_id
                assert report.lease_generation == lease.fence.lease_generation
                report_outcome = report.measurement_payload.outcomes[0]
                assert report_outcome.outcome.value == "MEASURED" or fixture.malformed_current_dsm
                revision = (fixture._baseline_revision, fixture._current_revision)[index]
                entry = revision.manifest.entries[0]
                assert report_outcome.observed_sha256 == "sha256:" + entry.observed_sha256
                if report_outcome.outcome.value == "MEASURED":
                    assert report_outcome.measurements == inspector.measured[index].measurements
        finally:
            lane.close()
            core.close()
        assert len(inspector.actual_source_digests) == 2
        expected_digests = tuple(
            "sha256:" + revision.manifest.entries[0].observed_sha256
            for revision in (fixture._baseline_revision, fixture._current_revision)
        )
        assert tuple(inspector.actual_source_digests) == expected_digests
        assert tuple(inspector.source_digests) == expected_digests
        for measurement_outcome in inspector.measured:
            if measurement_outcome.outcome.value == "MEASURED":
                assert measurement_outcome.measurements is not None
                measured = measurement_outcome.measurements
                assert measured.observed_crs_identifier == "EPSG:5186"
                assert measured.observed_vertical_reference is not None
                assert measured.observed_vertical_reference.identifier == "EPSG:5773"
                assert measured.observed_crs_wkt is not None
                assert measured.observed_crs_digest == (
                    "sha256:" + hashlib.sha256(measured.observed_crs_wkt.encode()).hexdigest()
                )
                assert (measured.width, measured.height, measured.valid_pixel_count) == (2, 2, 4)
                assert measured.transform == (0.1, 0.0, 200000.0, 0.0, -0.1, 550000.0)
        if fixture.malformed_current_dsm:
            assert [item.outcome.value for item in inspector.measured] == ["MEASURED", "REJECTED"]
            assert inspector.measured[1].reason == "MALFORMED_TIFF"
        else:
            assert [item.outcome.value for item in inspector.measured] == ["MEASURED", "MEASURED"]
    return tuple(
        inspection_store.public_snapshot(subject).report
        for subject in (fixture._baseline_subject, fixture._current_subject)
    )


def _post_analysis(fixture: Any, origin: str, idempotency_key: str) -> dict[str, Any]:
    body = {
        "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
        "current": fixture.current.model_dump(by_alias=True, mode="json"),
    }
    with httpx.Client(base_url=origin, trust_env=False) as operator:
        created = operator.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={
                **fixture.operator_headers(),
                "Idempotency-Key": idempotency_key,
            },
            json=body,
        )
        assert created.status_code == 202, created.text
        return created.json()


def test_actual_inspection_lane_authenticates_and_feeds_analysis_worker(
    tmp_path: Path,
) -> None:
    fixture = build_local_analysis_api_fixture(tmp_path, v2_dsm_only=True, real_inspection=True)
    try:
        with _CoreAndObjectServers(fixture) as servers:
            reports = _drive_two_epochs_through_lane(
                fixture,
                core_origin=servers.core_origin,
                object_origin=servers.object_origin,
                tmp_path=tmp_path,
            )
            assert len(reports) == 2
            intent = _post_analysis(fixture, servers.core_origin, "lane-backed-analysis")
            assert intent["suitabilityState"] == "PROVISIONAL_ACCURACY_UNVERIFIED"
            assert intent["executionState"] == "QUEUED"

            facts = fixture.app.state.external_analysis_wiring.facade._assessments._runtime
            envelope = fixture.app.state.external_analysis_wiring.calculations._resource_envelope
            runtime = ProcessingWorkerRuntimeIdentityV1(
                worker_executable_digest=facts.worker_executable_digest,
                worker_build_digest=facts.worker_build_digest,
                runtime_image_version=facts.runtime_image_version,
                runtime_image_oci_digest=facts.runtime_image_oci_digest,
                dependency_lock_digest=facts.dependency_lock_digest,
            )
            analysis_client = ExternalAnalysisCoreClient(
                base_url=servers.core_origin,
                worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
                worker_instance_id="lane-linked-analysis-worker",
            )
            object_policy = ExternalObjectTransportPolicyV1(
                endpoints=(
                    TrustedObjectEndpointV1(origin=servers.object_origin, addresses=("127.0.0.1",)),
                ),
                max_header_bytes=16_384,
                max_object_bytes=envelope.max_input_bytes,
                max_chunk_bytes=min(65_536, envelope.max_input_bytes),
            )
            assert run_once(analysis_client, runtime, object_policy)
            with httpx.Client(base_url=servers.core_origin, trust_env=False) as operator:
                detail_url = f"/v1/sites/{fixture.site_id}/analyses/{intent['analysisId']}"
                detail = operator.get(detail_url, headers=fixture.operator_headers())
                result = operator.get(detail_url + "/result", headers=fixture.operator_headers())
                evidence = operator.get(
                    detail_url + "/evidence", headers=fixture.operator_headers()
                )
            assert detail.status_code == result.status_code == evidence.status_code == 200
            assert detail.json()["executionState"] == "COMPLETED"
            assert detail.json()["result"] == result.json()["result"] == evidence.json()["result"]
            metrics = result.json()["result"]["metrics"]
            assert metrics["cutM3"] == pytest.approx(0.01)
            assert metrics["fillM3"] == pytest.approx(0.01)
            assert metrics["netM3"] == pytest.approx(0.0)
            assert metrics["uncertaintyM3"] is None
            assert evidence.json()["baseline"]["inspectionReportDigest"] == reports[0].report_digest
            assert evidence.json()["current"]["inspectionReportDigest"] == reports[1].report_digest
            for index, (epoch_key, revision) in enumerate(
                (
                    ("baseline", fixture._baseline_revision),
                    ("current", fixture._current_revision),
                )
            ):
                epoch = evidence.json()[epoch_key]
                entry = revision.manifest.entries[0]
                assert epoch["observedSha256"] == "sha256:" + entry.observed_sha256
                assert epoch["observedCrsIdentifier"] == "EPSG:5186"
                assert epoch["verticalReferenceIdentifier"] == "EPSG:5773"
                assert epoch["observedCrsDigest"] == (
                    reports[index].measurement_payload.outcomes[0].measurements.observed_crs_digest
                )
                assert epoch["transform"] == [0.1, 0.0, 200000.0, 0.0, -0.1, 550000.0]
            analysis_client.close()
    finally:
        fixture.close()


def test_actual_inspection_lane_rejects_malformed_current_and_blocks_analysis(
    tmp_path: Path,
) -> None:
    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        real_inspection=True,
        malformed_current_dsm=True,
    )
    try:
        with _CoreAndObjectServers(fixture) as servers:
            reports = _drive_two_epochs_through_lane(
                fixture,
                core_origin=servers.core_origin,
                object_origin=servers.object_origin,
                tmp_path=tmp_path,
            )
            assert reports[1].measurement_payload.outcomes[0].outcome.value == "REJECTED"
            assert reports[1].measurement_payload.outcomes[0].reason == "MALFORMED_TIFF"
            intent = _post_analysis(fixture, servers.core_origin, "lane-malformed-analysis")
            assert intent["suitabilityState"] == "BLOCKED"
            assert intent["executionState"] == "NOT_STARTED"
            assert intent["result"] is None
            assert any(item["code"] == "ESSENTIAL_INPUT_UNAVAILABLE" for item in intent["blockers"])
    finally:
        fixture.close()
