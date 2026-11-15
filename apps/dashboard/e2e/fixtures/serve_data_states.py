#!/usr/bin/env python3
"""Serve a synthetic data-state Core for dashboard browser review.

Review-only fixture. It reuses the contract-test Analysis fixture, which builds
the real Core composition with three sealed DSM epochs backed by tiny synthetic
GeoTIFF bytes, drives the real inspection lane over all of them and runs two
real Analysis worker turns (t0 to t1, then t1 to t2), so the Console can show
inspected observations and a repeated two-epoch review. Storage is in memory and credentials are the
fixture's opaque test tokens. Nothing here is field, accuracy, settlement or
customer evidence.

Linux only: the inspection worker socket identity check uses ``SO_PEERCRED`` and
the Analysis worker reads sealed inputs through ``/proc/self/fd``. On macOS run
it in a Linux container; ``scripts/run-data-state-stack.mjs`` does that.

The Core origin and operator token are written to ``--info-file`` (mode 0600)
once the data is ready, then the process serves until it is terminated.
``--publish-port`` additionally forwards 0.0.0.0:<port> to the loopback Core so a
container can expose it; the info file then reports ``--public-origin``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import signal
import socket
import sys
import tempfile
from pathlib import Path
from socketserver import StreamRequestHandler, ThreadingTCPServer
from threading import Event, Thread

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPOSITORY_ROOT / "tests" / "contract"))
sys.path.insert(0, str(REPOSITORY_ROOT / "tests"))


class _Forwarder(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, port: int, target_port: int) -> None:
        self.target_port = target_port

        class Handler(StreamRequestHandler):
            def handle(self) -> None:
                upstream = socket.create_connection(("127.0.0.1", target_port))

                def pump(source: socket.socket, sink: socket.socket) -> None:
                    try:
                        with contextlib.suppress(OSError):
                            while chunk := source.recv(65536):
                                sink.sendall(chunk)
                    finally:
                        for end in (source, sink):
                            with contextlib.suppress(OSError):
                                end.shutdown(socket.SHUT_RDWR)

                Thread(target=pump, args=(self.request, upstream), daemon=True).start()
                pump(upstream, self.request)

        super().__init__(("0.0.0.0", port), Handler)


def _drive_epochs(fixture, *, core_origin, object_origin, tmp_path, subjects):  # type: ignore[no-untyped-def]
    """Run the real inspection lane over every sealed subject (the contract helper does two)."""
    import os
    import time
    from datetime import UTC, datetime
    from threading import Event as LaneStop
    from uuid import uuid4

    from ksi_processing_controller.external_validation_core_client import (
        ExternalValidationCoreClient,
    )
    from ksi_processing_controller.external_validation_runner import TurnOutcome
    from test_external_analysis_real_inspection_integration import _RealDsmInspectorUds
    from test_external_analysis_real_inspection_lane_integration import _inspection_lane

    inspection_store = fixture.app.state.external_artifact_inspection_store
    worker_id = str(uuid4())
    socket_path = Path("/tmp") / f"ksi-lane-{uuid4().hex}.sock"
    inspector_root = tmp_path / "real-inspector-lane-root"
    inspector_root.mkdir(mode=0o700)
    with _RealDsmInspectorUds(
        path=socket_path, manifest=fixture._inspector_manifest, root=inspector_root
    ):
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
            envelope = fixture._inspection_policy.resource_envelope
            spacing = envelope.lease_duration_seconds + 1
            for index, subject in enumerate(subjects):
                if index:
                    # Core fences back-to-back inspections of one area; the fixture
                    # itself waits one lease period between epochs for the same reason.
                    time.sleep(spacing)
                now = max(datetime.now(UTC).replace(microsecond=0), fixture._fixture_now)
                issued = inspection_store.issue_after_seal(subject, now=now)
                deadline = time.monotonic() + 25
                request_id = lane.poll(deadline_monotonic=deadline)
                if request_id is None or request_id != issued.request.request_id:
                    raise RuntimeError("inspection lane did not return the issued request")
                try:
                    lease = lane.claim(request_id, str(uuid4()), deadline_monotonic=deadline)
                except Exception as error:
                    raise RuntimeError(
                        f"claim failed at epoch {index}: {error.__cause__!r}"
                    ) from error
                if lease is None:
                    raise RuntimeError(f"inspection lane could not claim request {index}")
                try:
                    outcome = lane.execute(lease, deadline_monotonic=deadline, stop=LaneStop())
                    if outcome is not TurnOutcome.COMPLETED:
                        raise RuntimeError(f"inspection did not complete: {outcome}")
                finally:
                    lane.release(lease)
        finally:
            lane.close()
            core.close()
    del os


def _post_pair(fixture, origin, baseline, current, key):  # type: ignore[no-untyped-def]
    import httpx

    body = {
        "baseline": baseline.model_dump(by_alias=True, mode="json"),
        "current": current.model_dump(by_alias=True, mode="json"),
    }
    with httpx.Client(base_url=origin, trust_env=False) as operator:
        created = operator.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses",
            headers={**fixture.operator_headers(), "Idempotency-Key": key},
            json=body,
        )
        if created.status_code != 202:
            raise RuntimeError(f"analysis request refused: {created.status_code} {created.text}")
        return created.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--info-file", type=Path, required=True)
    parser.add_argument("--publish-port", type=int)
    parser.add_argument("--public-origin")
    args = parser.parse_args()
    if sys.platform != "linux":
        raise SystemExit("serve_data_states.py needs Linux; run it in a Linux container.")
    if (args.publish_port is None) != (args.public_origin is None):
        raise SystemExit("--publish-port and --public-origin go together.")

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
    from test_external_analysis_real_inspection_lane_integration import _CoreAndObjectServers

    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    with tempfile.TemporaryDirectory(prefix="ksi-data-states-") as tmp:
        tmp_path = Path(tmp).resolve()
        fixture = build_local_analysis_api_fixture(
            tmp_path, v2_dsm_only=True, include_third_epoch=True, real_inspection=True
        )
        forwarder: _Forwarder | None = None
        try:
            with _CoreAndObjectServers(fixture) as servers:
                _drive_epochs(
                    fixture,
                    core_origin=servers.core_origin,
                    object_origin=servers.object_origin,
                    tmp_path=tmp_path,
                    subjects=(
                        fixture._baseline_subject,
                        fixture._current_subject,
                        fixture._third_subject,
                    ),
                )
                # t0 to t1, then t1 to t2: a real repeated review of one work area.
                pairs = (
                    ("data-state-review-t0-t1", fixture.baseline, fixture.current),
                    ("data-state-review-t1-t2", fixture.current, fixture.third),
                )
                wiring = fixture.app.state.external_analysis_wiring
                facts = wiring.facade._assessments._runtime
                envelope = wiring.calculations._resource_envelope
                runtime = ProcessingWorkerRuntimeIdentityV1(
                    worker_executable_digest=facts.worker_executable_digest,
                    worker_build_digest=facts.worker_build_digest,
                    runtime_image_version=facts.runtime_image_version,
                    runtime_image_oci_digest=facts.runtime_image_oci_digest,
                    dependency_lock_digest=facts.dependency_lock_digest,
                )
                worker = ExternalAnalysisCoreClient(
                    base_url=servers.core_origin,
                    worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
                    worker_instance_id="data-state-review-worker",
                )
                object_policy = ExternalObjectTransportPolicyV1(
                    endpoints=(
                        TrustedObjectEndpointV1(
                            origin=servers.object_origin, addresses=("127.0.0.1",)
                        ),
                    ),
                    max_header_bytes=16_384,
                    max_object_bytes=envelope.max_input_bytes,
                    max_chunk_bytes=min(65_536, envelope.max_input_bytes),
                )
                created_ids = []
                try:
                    for key, baseline, current in pairs:
                        created = _post_pair(fixture, servers.core_origin, baseline, current, key)
                        created_ids.append(created["analysisId"])
                        if not run_once(worker, runtime, object_policy):
                            raise RuntimeError(f"analysis worker did not complete {key}")
                finally:
                    worker.close()
                core_origin = servers.core_origin
                if args.publish_port is not None:
                    forwarder = _Forwarder(args.publish_port, int(core_origin.rsplit(":", 1)[1]))
                    Thread(target=forwarder.serve_forever, daemon=True).start()
                    core_origin = args.public_origin
                info = {
                    "coreOrigin": core_origin,
                    "siteId": fixture.site_id,
                    "workAreaId": fixture.work_area_id,
                    "analysisId": created_ids[-1],
                    "analysisIds": created_ids,
                    "operatorToken": fixture.operator_headers()["Authorization"].removeprefix(
                        "Bearer "
                    ),
                    "viewerToken": fixture.viewer_headers()["Authorization"].removeprefix(
                        "Bearer "
                    ),
                }
                args.info_file.write_text(json.dumps(info), encoding="utf-8")
                args.info_file.chmod(0o600)
                stop.wait()
        finally:
            if forwarder is not None:
                forwarder.shutdown()
            fixture.close()


if __name__ == "__main__":
    main()
