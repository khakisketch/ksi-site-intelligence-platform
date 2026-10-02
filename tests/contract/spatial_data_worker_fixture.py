"""Synthetic byte orchestration only; no raster/provider/host acceptance claim."""

import base64
import hashlib
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ksi_event_contracts.spatial_data import SpatialDataReceiptV1
from ksi_event_contracts.spatial_data_worker import (
    SpatialDataOutputUploadViewV1,
    SpatialDataRequiredHeaderV1,
    SpatialDataSourceCapabilityV1,
    SpatialDataUploadCapabilityV1,
    SpatialDataUploadDeclarationV1,
    SpatialDataWorkerInputV1,
)
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)
from spatial_data_fixture import (
    NOW,
    make_activation,
    make_attempt,
    make_job,
    make_receipt,
    make_source,
)


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class ByteCore:
    def __init__(self, origin: str, data: bytes) -> None:
        source = make_source(
            observed_sha256=digest(data),
            observed_size_bytes=len(data),
            inspection=make_source().inspection.model_copy(
                update={"observed_sha256": digest(data)}
            ),
        )
        self.job = make_job(source=source)
        self.activation = make_activation(trusted_endpoint_origins=(origin,))
        self.attempt = make_attempt(frozen_job_digest=self.job.job_digest)
        self.origin = origin
        self.current = True
        self.completed_reports: list[SpatialDataReceiptV1] = []
        self.failures: list[str] = []
        self.renewals = 0
        self.declaration: SpatialDataUploadDeclarationV1 | None = None

    def pending(self, *, limit: int) -> Any:
        return (self.job,)

    def lease(self, *, job_id: str, acquisition_id: str) -> Any:
        assert job_id == self.job.job_id and acquisition_id
        return self.attempt

    def renew(self, *, attempt: Any) -> Any:
        from ksi_processing_controller.spatial_data_core_client import SpatialDataCoreClientError

        if not self.current:
            raise SpatialDataCoreClientError("CORE_REQUEST_DENIED")
        assert attempt.fence_digest() == self.attempt.fence_digest()
        self.renewals += 1
        self.attempt = attempt.model_copy(
            update={"lease_until": NOW + timedelta(seconds=10), "attempt_digest": None}
        ).sealed()
        return self.attempt

    def input(self, *, attempt: Any) -> Any:
        assert self.job.source.source_digest is not None
        assert attempt == self.attempt
        return SpatialDataWorkerInputV1(
            job=self.job,
            attempt=attempt,
            activation=self.activation,
            runtime=self.job.runtime,
            source_capability=SpatialDataSourceCapabilityV1(
                artifact_id=self.job.source.artifact_id,
                source_digest=self.job.source.source_digest,
                observed_sha256=self.job.source.observed_sha256,
                observed_size_bytes=self.job.source.observed_size_bytes,
                download_url=self.origin + "/source",
                required_headers=(),
                expires_at=attempt.lease_until,
            ),
        )

    def output_upload(self, *, declaration: Any) -> Any:
        assert self.current and declaration.attempt == self.attempt
        self.declaration = declaration
        headers = {
            "Content-Type": "image/tiff",
            "Content-Length": str(declaration.size_bytes),
            "x-amz-checksum-sha256": base64.b64encode(
                bytes.fromhex(declaration.sha256[7:])
            ).decode(),
        }
        return SpatialDataOutputUploadViewV1(
            upload_digest=declaration.upload_digest,
            capability=SpatialDataUploadCapabilityV1(
                receipt_digest=declaration.receipt.receipt_digest,
                sha256=declaration.sha256,
                size_bytes=declaration.size_bytes,
                content_type="image/tiff",
                upload_url=self.origin + "/output",
                required_headers=tuple(
                    SpatialDataRequiredHeaderV1.model_validate({"name": k, "value": v})
                    for k, v in headers.items()
                ),
                expires_at=declaration.attempt.lease_until,
            ),
        )

    def complete(self, *, attempt: Any, upload_digest: str) -> None:
        assert self.declaration is not None
        assert (
            self.current
            and attempt == self.attempt
            and upload_digest == self.declaration.upload_digest
        )
        self.completed_reports.append(self.declaration.receipt)

    def failure(self, *, attempt: Any, reason: str) -> None:
        assert attempt == self.attempt
        self.failures.append(reason)


class ByteSandbox:
    """Test-only fake; source and candidate byte binding, not raster arithmetic."""

    def __init__(self, core: Any, *, change: str | None = None) -> None:
        self.core = core
        self.change = change
        self.calls = 0

    def prepare(
        self, *, job: Any, source_path: Path, output_parent: Path, is_current: Callable[[], bool]
    ) -> Any:
        assert source_path.read_bytes() == b"sealed-source" * 100
        assert is_current()
        self.calls += 1
        candidate = b"private-output" * 100
        (output_parent / "candidate.tif").write_bytes(candidate)
        (output_parent / "candidate.tif").chmod(0o600)
        receipt = make_receipt(
            job_digest=job.job_digest,
            source_digest=job.source.source_digest,
            source_sha256=job.source.observed_sha256,
            source_size_bytes=job.source.observed_size_bytes,
            output_sha256=digest(candidate),
            output_size_bytes=len(candidate),
            prepared_at=NOW,
            attribution=job.grant.attribution,
        )
        if self.change == "lease-loss":
            self.core.current = False
        elif self.change == "tamper":
            (output_parent / "candidate.tif").write_bytes(b"tampered-output")
        elif self.change == "crash":
            raise RuntimeError("private-child-details")
        elif self.change == "receipt-source":
            receipt = receipt.model_copy(
                update={"source_digest": "sha256:" + "f" * 64, "receipt_digest": None}
            ).sealed()
        elif self.change == "native-failure":
            from ksi_geo_spatial.external_native_window_geometry import NativeWindowError

            raise NativeWindowError("EMPTY_VALID_WINDOW", "private-source-details")
        return receipt


@contextmanager
def byte_lane(
    *, phase: str | None = None, sandbox_change: str | None = None, bad_source: bool = False
) -> Iterator[Any]:
    source = b"sealed-source" * 100
    uploads, headers = [], []
    core: ByteCore | None = None

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *_: Any) -> None:
            pass

        def do_GET(self) -> None:
            assert core is not None
            headers.append(dict(self.headers))
            if phase == "download":
                core.current = False
            self.send_response(200)
            self.send_header("Content-Length", str(len(source)))
            self.end_headers()
            with suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(b"x" * len(source) if bad_source else source)

        def do_PUT(self) -> None:
            assert core is not None
            headers.append(dict(self.headers))
            payload = self.rfile.read(int(self.headers["Content-Length"]))
            uploads.append(payload)
            if phase == "upload":
                core.current = False
            self.send_response(200)
            self.send_header("Content-Length", "1" if phase == "bad-upload-response" else "0")
            self.end_headers()
            if phase == "bad-upload-response":
                self.wfile.write(b"x")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{server.server_port}"
        core = ByteCore(origin, source)
        policy = ExternalObjectTransportPolicyV1(
            endpoints=(TrustedObjectEndpointV1(origin=origin, addresses=("127.0.0.1",)),),
            max_header_bytes=4096,
            max_object_bytes=4096,
            max_chunk_bytes=512,
        )
        yield core, ByteSandbox(core, change=sandbox_change), policy, uploads, headers
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
