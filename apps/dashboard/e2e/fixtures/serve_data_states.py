#!/usr/bin/env python3
"""Serve a synthetic data-state Core for dashboard browser review.

Review-only fixture. It reuses the contract-test Analysis fixture, which builds
the real Core composition with two sealed DSM epochs backed by tiny synthetic
GeoTIFF bytes, then drives the real inspection lane and one real Analysis
worker turn, so the Console can show inspected observations, a two-epoch pair
and a completed Analysis result. Storage is in memory and credentials are the
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
    from test_external_analysis_real_inspection_lane_integration import (
        _CoreAndObjectServers,
        _drive_two_epochs_through_lane,
        _post_analysis,
    )

    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    with tempfile.TemporaryDirectory(prefix="ksi-data-states-") as tmp:
        tmp_path = Path(tmp).resolve()
        fixture = build_local_analysis_api_fixture(tmp_path, v2_dsm_only=True, real_inspection=True)
        forwarder: _Forwarder | None = None
        try:
            with _CoreAndObjectServers(fixture) as servers:
                _drive_two_epochs_through_lane(
                    fixture,
                    core_origin=servers.core_origin,
                    object_origin=servers.object_origin,
                    tmp_path=tmp_path,
                )
                created = _post_analysis(fixture, servers.core_origin, "data-state-review")
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
                try:
                    completed = run_once(
                        worker,
                        runtime,
                        ExternalObjectTransportPolicyV1(
                            endpoints=(
                                TrustedObjectEndpointV1(
                                    origin=servers.object_origin, addresses=("127.0.0.1",)
                                ),
                            ),
                            max_header_bytes=16_384,
                            max_object_bytes=envelope.max_input_bytes,
                            max_chunk_bytes=min(65_536, envelope.max_input_bytes),
                        ),
                    )
                finally:
                    worker.close()
                if not completed:
                    raise RuntimeError("analysis worker did not complete the review analysis")
                core_origin = servers.core_origin
                if args.publish_port is not None:
                    forwarder = _Forwarder(args.publish_port, int(core_origin.rsplit(":", 1)[1]))
                    Thread(target=forwarder.serve_forever, daemon=True).start()
                    core_origin = args.public_origin
                info = {
                    "coreOrigin": core_origin,
                    "siteId": fixture.site_id,
                    "workAreaId": fixture.work_area_id,
                    "analysisId": created["analysisId"],
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
