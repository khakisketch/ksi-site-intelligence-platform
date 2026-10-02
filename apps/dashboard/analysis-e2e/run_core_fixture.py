#!/usr/bin/env python3
"""Run an isolated loopback Core/OIDC/worker stack for the Analysis browser test."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import signal
import socket
import stat
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests" / "contract"))

from analysis_api_local_fixture import build_local_analysis_api_fixture  # noqa: E402
from ksi_core.identity.auth import HumanAuthMode  # noqa: E402
from ksi_core.identity.oidc_subject_registry import OidcSubjectRegistry  # noqa: E402
from ksi_core.oidc import OidcJwtVerifier, OidcVerifierConfig  # noqa: E402
from ksi_processing_controller.external_analysis_core_client import (  # noqa: E402
    ExternalAnalysisCoreClient,
)
from ksi_processing_controller.external_analysis_worker import (  # noqa: E402
    ProcessingWorkerRuntimeIdentityV1,
    run_once,
)
from ksi_processing_controller.external_object_streams import (  # noqa: E402
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)
from test_external_analysis_real_inspection_integration import (  # noqa: E402
    inspect_fixture_epochs_with_real_parser,
)
from test_external_analysis_spatial_blockers_integration import (  # noqa: E402
    _inspect_both_epochs_with_actual_lane,
)
from test_external_analysis_activation import _write_activation  # noqa: E402


def _load_local_issuer() -> ModuleType:
    issuer_path = ROOT / "tools" / "run_local_oidc_issuer.py"
    spec = importlib.util.spec_from_file_location("ksi_analysis_test_local_oidc", issuer_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the test-only local OIDC issuer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _bound_loopback_socket(port: int) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(128)
    return listener


def _start_uvicorn(app: Any, port: int, label: str) -> tuple[uvicorn.Server, threading.Thread]:
    listener = _bound_loopback_socket(port)
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="warning", access_log=False, lifespan="on")
    )
    thread = threading.Thread(
        target=lambda: server.run(sockets=[listener]),
        name=label,
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if server.started:
            return server, thread
        if not thread.is_alive():
            raise RuntimeError(f"{label} server stopped during startup")
        time.sleep(0.025)
    server.should_exit = True
    thread.join(timeout=3)
    raise TimeoutError(f"{label} server did not become ready")


def _wait_http(url: str, label: str) -> None:
    deadline = time.monotonic() + 20
    last_error: BaseException | None = None
    with httpx.Client(trust_env=False, timeout=1.0) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(url)
                if response.is_success:
                    return
                last_error = RuntimeError(f"{label} returned HTTP {response.status_code}")
            except httpx.HTTPError as exc:
                last_error = exc
            time.sleep(0.05)
    raise TimeoutError(f"{label} did not become ready: {last_error}")


def _write_inspection_manifest(
    data_dir: Path, fixture: Any, report_digests: tuple[str, ...], scenario: str
) -> None:
    expected_count = 3 if scenario == "weekly-reuse" else 2
    if (
        len(report_digests) != expected_count
        or report_digests != fixture.synthetic_inspection_report_digests
    ):
        raise RuntimeError(
            "all DSM epochs must pass real parser inspection before the browser flow"
        )
    if (scenario == "weekly-reuse") != (fixture.third is not None):
        raise RuntimeError("weekly manifest must include exactly three sealed DSM epochs")
    inspection_manifest = {
        "siteId": fixture.site_id,
        "workAreaId": fixture.work_area_id,
        "scenario": scenario,
        "baselineSelector": fixture.baseline.model_dump(by_alias=True, mode="json"),
        "currentSelector": fixture.current.model_dump(by_alias=True, mode="json"),
        "inspectionReportDigests": list(report_digests),
    }
    if scenario == "weekly-reuse":
        inspection_manifest["thirdSelector"] = fixture.third.model_dump(
            by_alias=True, mode="json"
        )
    manifest_path = data_dir / "inspected-fixture.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        raise FileExistsError(f"inspection manifest already exists: {manifest_path}")

    pending_path = data_dir / f".inspected-fixture-{os.urandom(16).hex()}.pending"
    descriptor = os.open(pending_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as manifest_stream:
            json.dump(inspection_manifest, manifest_stream)
            manifest_stream.flush()
            os.fsync(manifest_stream.fileno())
        os.replace(pending_path, manifest_path)
    finally:
        pending_path.unlink(missing_ok=True)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--client-secret-file", type=Path, required=True)
    parser.add_argument("--dashboard-origin", required=True)
    parser.add_argument("--core-port", type=int, default=8033)
    parser.add_argument("--issuer-port", type=int, default=9031)
    parser.add_argument(
        "--scenario",
        choices=(
            "normal",
            "missing-vertical-reference",
            "overlapping-current-nodata-cell",
            "viewer-readonly",
            "weekly-reuse",
        ),
        default="normal",
    )
    args = parser.parse_args()
    if args.dashboard_origin != "http://localhost:3231":
        parser.error(
            "analysis browser fixture only permits its assigned localhost Dashboard origin"
        )
    if (args.core_port, args.issuer_port) != (8033, 9031):
        parser.error("analysis browser fixture only permits its assigned isolated service ports")
    return args


def _validate_runtime_root(
    data_dir: Path, run_id: str, client_secret_file: Path
) -> tuple[int, int]:
    expected_parent = Path(tempfile.gettempdir()).resolve()
    if (
        data_dir.parent != expected_parent
        or not data_dir.name.startswith("ksi-analysis-e2e-")
        or len(run_id) != 64
        or any(character not in "0123456789abcdef" for character in run_id)
        or client_secret_file != data_dir / "secrets" / "oidc-client.secret"
    ):
        raise ValueError(
            "Analysis E2E runtime must be a unique direct child of the system temp root"
        )
    root_metadata = data_dir.lstat()
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or stat.S_ISLNK(root_metadata.st_mode)
        or root_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(root_metadata.st_mode) != 0o700
        or data_dir.resolve(strict=True) != data_dir
    ):
        raise PermissionError("Analysis E2E runtime directory is not private and owner-controlled")

    marker = data_dir / "run-identity"
    marker_metadata = marker.lstat()
    if (
        not stat.S_ISREG(marker_metadata.st_mode)
        or stat.S_ISLNK(marker_metadata.st_mode)
        or marker_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(marker_metadata.st_mode) != 0o600
        or marker.read_text(encoding="utf-8") != run_id
    ):
        raise PermissionError("Analysis E2E run identity marker is missing or unsafe")

    secrets_directory = data_dir / "secrets"
    secrets_metadata = secrets_directory.lstat()
    if (
        not stat.S_ISDIR(secrets_metadata.st_mode)
        or stat.S_ISLNK(secrets_metadata.st_mode)
        or secrets_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(secrets_metadata.st_mode) != 0o700
    ):
        raise PermissionError("Analysis E2E secrets directory is missing or unsafe")
    expected_secret_files = (
        secrets_directory / "oidc-client.secret",
        secrets_directory / "dashboard-session.secret",
    )
    if client_secret_file != expected_secret_files[0]:
        raise PermissionError("Analysis E2E client secret path is not the owned private file")
    for secret_file in expected_secret_files:
        secret_metadata = secret_file.lstat()
        if (
            not stat.S_ISREG(secret_metadata.st_mode)
            or stat.S_ISLNK(secret_metadata.st_mode)
            or secret_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(secret_metadata.st_mode) != 0o600
            or secret_metadata.st_size < 32
        ):
            raise PermissionError("Analysis E2E secret file is missing or unsafe")
    return root_metadata.st_dev, root_metadata.st_ino


def _remove_owned_runtime_root(
    data_dir: Path,
    run_id: str,
    original_identity: tuple[int, int],
) -> None:
    try:
        metadata = data_dir.lstat()
        marker = data_dir / "run-identity"
        marker_metadata = marker.lstat()
        if (
            (metadata.st_dev, metadata.st_ino) != original_identity
            or not stat.S_ISDIR(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or not stat.S_ISREG(marker_metadata.st_mode)
            or stat.S_ISLNK(marker_metadata.st_mode)
            or marker_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(marker_metadata.st_mode) != 0o600
            or marker.read_text(encoding="utf-8") != run_id
        ):
            print(
                "Analysis E2E cleanup skipped: runtime identity changed",
                file=sys.stderr,
                flush=True,
            )
            return
        shutil.rmtree(data_dir)
    except FileNotFoundError:
        return


def _process_pending_controls(data_dir: Path, run_id: str, fixture: Any, core_origin: str) -> None:
    for request_path in sorted(data_dir.glob("control-*.request.json")):
        filename_id = request_path.name.removeprefix("control-").removesuffix(".request.json")
        if len(filename_id) != 48 or any(
            character not in "0123456789abcdef" for character in filename_id
        ):
            raise ValueError("Analysis E2E control request has an invalid identity")
        request_metadata = request_path.lstat()
        if (
            not stat.S_ISREG(request_metadata.st_mode)
            or stat.S_ISLNK(request_metadata.st_mode)
            or request_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(request_metadata.st_mode) != 0o600
        ):
            raise PermissionError(
                "Analysis E2E control request is not private and owner-controlled"
            )
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if (
            not isinstance(request, dict)
            or set(request) != {"version", "runId", "controlId", "action"}
            or request["version"] != 1
            or request["runId"] != run_id
            or request["controlId"] != filename_id
        ):
            raise ValueError("Analysis E2E control request does not match this run")

        # Consume before acting so a retry/re-scan can never append twice.
        request_path.unlink()
        action = request["action"]
        if action == "APPEND_FAILED_CURRENT_CHECKPOINT_EVALUATION":
            rejected = fixture.append_failed_current_checkpoint_evaluation()
            if (
                getattr(rejected.core_verdict, "value", None) != "REJECTED"
                or rejected.core_reason != "CHECKPOINT_COUNT_OUT_OF_RANGE"
            ):
                raise RuntimeError("late checkpoint fixture did not produce the expected rejection")
            acknowledgement = {
                "controlId": filename_id,
                "status": "APPLIED",
                "verdict": rejected.core_verdict.value,
                "reason": rejected.core_reason,
            }
        elif action == "CHECK_NO_WORKER_JOB":
            with httpx.Client(trust_env=False, timeout=5.0) as client:
                response = client.get(
                    f"{core_origin}/v1/internal/analysis-jobs",
                    headers=fixture.worker_headers(),
                )
            if response.status_code != 200:
                raise RuntimeError(
                    f"worker queue inspection returned HTTP {response.status_code}"
                )
            pending = response.json().get("items")
            if not isinstance(pending, list):
                raise RuntimeError("worker queue inspection returned an invalid item list")
            acknowledgement = {
                "controlId": filename_id,
                "status": "CHECKED",
                "pendingJobCount": len(pending),
            }
        else:
            raise ValueError("Analysis E2E control request has an unsupported action")

        acknowledgement_path = data_dir / f"control-{filename_id}.ack.json"
        with acknowledgement_path.open("x", encoding="utf-8") as acknowledgement_stream:
            json.dump(acknowledgement, acknowledgement_stream)
        acknowledgement_path.chmod(0o600)


def main() -> int:
    args = _arguments()
    runtime_identity = _validate_runtime_root(args.data_dir, args.run_id, args.client_secret_file)
    issuer_state_dir = args.data_dir / "identity"
    core_data_dir = args.data_dir / "core"

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda _signum, _frame: stop.set())
    signal.signal(signal.SIGTERM, lambda _signum, _frame: stop.set())

    fixture = None
    object_server: ThreadingHTTPServer | None = None
    object_thread: threading.Thread | None = None
    issuer_server: uvicorn.Server | None = None
    issuer_thread: threading.Thread | None = None
    core_server: uvicorn.Server | None = None
    core_thread: threading.Thread | None = None
    worker_client: ExternalAnalysisCoreClient | None = None
    try:
        issuer_state_dir.mkdir(mode=0o700)
        core_data_dir.mkdir(mode=0o700)
        def active_analysis_activation(config: Any, worker: Any) -> Any:
            return _write_activation(
                args.data_dir / "analysis-activation-test-only",
                bindings={
                    "organization_id": "org-local-pilot",
                    "policy": config.policy,
                    "runtime": config.runtime,
                    "resource_envelope": config.resource_envelope,
                    "worker_principal": worker,
                },
                activation_fields={
                    "issuedAt": (datetime.now(UTC) - timedelta(minutes=1))
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "validUntil": (datetime.now(UTC) + timedelta(hours=1))
                    .isoformat()
                    .replace("+00:00", "Z"),
                },
            )[2]

        fixture = build_local_analysis_api_fixture(
            core_data_dir,
            organization_id="org-local-pilot",
            v2_dsm_only=True,
            include_third_epoch=args.scenario == "weekly-reuse",
            real_inspection=True,
            current_dsm_spatial_case=(
                {
                    "normal": "VALID",
                    "missing-vertical-reference": "MISSING_VERTICAL_REFERENCE",
                    "overlapping-current-nodata-cell": "OVERLAPPING_CURRENT_NODATA_CELL",
                    "viewer-readonly": "VALID",
                    "weekly-reuse": "VALID",
                }[args.scenario]
            ),
            analysis_activation=active_analysis_activation,
        )
        assert fixture is not None
        fixture_for_http = fixture
        inspection_root = args.data_dir / "real-inspection-private"
        inspection_root.mkdir(mode=0o700)
        if args.scenario in {"normal", "viewer-readonly"}:
            measured = inspect_fixture_epochs_with_real_parser(fixture, root=inspection_root)
            _write_inspection_manifest(args.data_dir, fixture, measured, args.scenario)

        class LoopbackObjectHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if not self.path.startswith("/objects/"):
                    self.send_error(404)
                    return
                object_key = unquote(urlsplit(self.path).path.removeprefix("/objects/"))
                try:
                    payload = fixture_for_http.storage.object_bytes(object_key)
                except KeyError:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/tiff")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        object_server = ThreadingHTTPServer(("127.0.0.1", 0), LoopbackObjectHandler)
        object_thread = threading.Thread(
            target=object_server.serve_forever,
            name="analysis-e2e-object-bytes",
            daemon=True,
        )
        object_thread.start()
        object_origin = f"http://127.0.0.1:{object_server.server_port}"
        fixture.set_loopback_object_origin(object_origin)

        issuer_module = _load_local_issuer()
        issuer_origin = f"http://localhost:{args.issuer_port}"
        issuer_config = issuer_module.LocalOidcConfig(
            issuer=issuer_origin,
            dashboard_origin=args.dashboard_origin,
            client_id="ksi-operations-console",
            client_secret_file=args.client_secret_file,
            key_file=issuer_state_dir / "local-oidc-rsa.private.pem",
            core_audience="ksi-core",
        )
        issuer_app = issuer_module.build_local_oidc_app(issuer_config)
        issuer_server, issuer_thread = _start_uvicorn(
            issuer_app, args.issuer_port, "analysis-e2e-issuer"
        )
        _wait_http(f"http://127.0.0.1:{args.issuer_port}/healthz", "local issuer")

        fixture.app.state.human_auth_mode = HumanAuthMode.OIDC
        fixture.app.state.oidc_verifier = OidcJwtVerifier(
            OidcVerifierConfig(
                issuer=issuer_origin,
                audience="ksi-core",
                jwks_url=f"http://127.0.0.1:{args.issuer_port}/jwks.json",
            ),
            subject_registry=OidcSubjectRegistry.from_document(
                {
                    "version": "oidc-subject-registry.v1",
                    "subjects": [
                        {
                            "issuer": issuer_origin,
                            "subject": subject,
                            "principalId": subject,
                            "organizationId": organization_id,
                            "role": role,
                            "status": "ACTIVE",
                            "allowedSiteIds": site_ids,
                            "allowedWorkAreaIds": work_area_ids,
                        }
                        for subject, role, organization_id, site_ids, work_area_ids in (
                            (
                                "local-admin",
                                "ADMIN",
                                fixture.organization_id,
                                [fixture.site_id],
                                [fixture.work_area_id],
                            ),
                            (
                                "local-field-operator",
                                "FIELD_OPERATOR",
                                fixture.organization_id,
                                [fixture.site_id],
                                [fixture.work_area_id],
                            ),
                            (
                                "local-viewer",
                                "VIEWER",
                                fixture.organization_id,
                                [fixture.site_id],
                                [fixture.work_area_id],
                            ),
                            ("local-empty-org-admin", "ADMIN", "org-local-empty", [], []),
                        )
                    ],
                },
                expected_issuer=issuer_origin,
            ),
        )
        core_server, core_thread = _start_uvicorn(fixture.app, args.core_port, "analysis-e2e-core")
        core_origin = f"http://127.0.0.1:{args.core_port}"
        _wait_http(f"{core_origin}/ready", "local Core")

        if args.scenario == "weekly-reuse":
            reports = _inspect_both_epochs_with_actual_lane(
                fixture,
                core_origin=core_origin,
                object_origin=object_origin,
                tmp_path=args.data_dir,
                include_third_epoch=True,
            )
            if fixture.third is None or fixture._third_revision is None or len(reports) != 3:
                raise RuntimeError("weekly inspection lane did not inspect all three DSM epochs")
            revisions = (
                fixture._baseline_revision,
                fixture._current_revision,
                fixture._third_revision,
            )
            for report, revision in zip(reports, revisions, strict=True):
                measured = report.measurement_payload.outcomes[0]
                if (
                    measured.outcome.value != "MEASURED"
                    or measured.observed_sha256
                    != "sha256:" + revision.manifest.entries[0].observed_sha256
                ):
                    raise RuntimeError("weekly actual inspection did not bind the sealed DSM bytes")
            report_digests = tuple(report.report_digest for report in reports)
            fixture.synthetic_inspection_report_digests = report_digests
            _write_inspection_manifest(args.data_dir, fixture, report_digests, args.scenario)

        if args.scenario == "missing-vertical-reference":
            reports = _inspect_both_epochs_with_actual_lane(
                fixture,
                core_origin=core_origin,
                object_origin=object_origin,
                tmp_path=args.data_dir,
            )
            current_measurements = reports[1].measurement_payload.outcomes[0].measurements
            if (
                current_measurements is None
                or current_measurements.observed_vertical_reference is not None
                or current_measurements.observed_crs_identifier != "EPSG:5186"
            ):
                raise RuntimeError(
                    "real parser did not preserve the missing vertical reference case"
                )
            measured = tuple(report.report_digest for report in reports)
            fixture.synthetic_inspection_report_digests = measured
            _write_inspection_manifest(args.data_dir, fixture, measured, args.scenario)
        elif args.scenario == "overlapping-current-nodata-cell":
            reports = _inspect_both_epochs_with_actual_lane(
                fixture,
                core_origin=core_origin,
                object_origin=object_origin,
                tmp_path=args.data_dir,
            )
            baseline_measurements = reports[0].measurement_payload.outcomes[0].measurements
            current_measurements = reports[1].measurement_payload.outcomes[0].measurements
            if baseline_measurements is None or current_measurements is None:
                raise RuntimeError("actual parser did not report both DSM measurement payloads")
            baseline_vertical = baseline_measurements.observed_vertical_reference
            current_vertical = current_measurements.observed_vertical_reference
            if (
                baseline_measurements.valid_pixel_count != 4
                or current_measurements.valid_pixel_count != 3
                or current_measurements.nodata_representation.value != "FINITE"
                or current_measurements.nodata_value != -9999.0
                or baseline_measurements.observed_crs_identifier != "EPSG:5186"
                or baseline_measurements.observed_crs_identifier
                != current_measurements.observed_crs_identifier
                or baseline_vertical is None
                or current_vertical is None
                or baseline_vertical.identifier != "EPSG:5773"
                or baseline_vertical.identifier != current_vertical.identifier
                or baseline_measurements.transform != current_measurements.transform
            ):
                raise RuntimeError(
                    "actual parser did not preserve the overlapping 3-of-4 NoData spatial case"
                )
            measured = tuple(report.report_digest for report in reports)
            fixture.synthetic_inspection_report_digests = measured
            _write_inspection_manifest(args.data_dir, fixture, measured, args.scenario)

        runtime_facts = fixture.app.state.external_analysis_wiring.facade._assessments._runtime
        envelope = fixture.app.state.external_analysis_wiring.calculations._resource_envelope
        worker_runtime = ProcessingWorkerRuntimeIdentityV1(
            worker_executable_digest=runtime_facts.worker_executable_digest,
            worker_build_digest=runtime_facts.worker_build_digest,
            runtime_image_version=runtime_facts.runtime_image_version,
            runtime_image_oci_digest=runtime_facts.runtime_image_oci_digest,
            dependency_lock_digest=runtime_facts.dependency_lock_digest,
        )
        object_transport = ExternalObjectTransportPolicyV1(
            endpoints=(
                TrustedObjectEndpointV1(origin=object_origin, addresses=("127.0.0.1",)),
            ),
            max_header_bytes=16_384,
            max_object_bytes=envelope.max_input_bytes,
            max_chunk_bytes=min(65_536, envelope.max_input_bytes),
        )
        worker_client = ExternalAnalysisCoreClient(
            base_url=core_origin,
            worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
            worker_instance_id="analysis-e2e-gis-worker",
        )
        print("Analysis E2E Core/issuer/object fixture and real inspections are ready", flush=True)

        while not stop.is_set():
            _process_pending_controls(args.data_dir, args.run_id, fixture, core_origin)
            if not run_once(worker_client, worker_runtime, object_transport):
                stop.wait(0.2)
        return 0
    finally:
        stop.set()
        if worker_client is not None:
            worker_client.close()
        for server in (core_server, issuer_server):
            if server is not None:
                server.should_exit = True
        for thread in (core_thread, issuer_thread):
            if thread is not None:
                thread.join(timeout=10)
        if object_server is not None:
            object_server.shutdown()
            object_server.server_close()
        if object_thread is not None:
            object_thread.join(timeout=5)
        try:
            if fixture is not None:
                fixture.close()
        finally:
            _remove_owned_runtime_root(args.data_dir, args.run_id, runtime_identity)


if __name__ == "__main__":
    raise SystemExit(main())
