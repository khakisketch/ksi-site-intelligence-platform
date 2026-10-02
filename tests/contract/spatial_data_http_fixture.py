"""Owned generated TIFFs only; no customer/public TIFF decode or host containment proof.

Core authorities/journals and worker object transport are real. A generated-only
child launcher exercises actual framing/preparation but never enters production.
"""

import base64
import hashlib
import json
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, mount_auth
from ksi_core.domains.external.delivery.api import build_spatial_data_router
from ksi_core.domains.external.delivery.audit import SpatialDataAuditStore
from ksi_core.domains.external.delivery.downloads import SpatialDataDownloadService
from ksi_core.domains.external.delivery.grants import (
    SpatialDataGrantAuthorizer,
    SpatialDataGrantStore,
)
from ksi_core.domains.external.delivery.storage_types import SpatialDataObjectObservation
from ksi_core.domains.external.delivery.worker_api import build_spatial_data_worker_router
from ksi_core.durable_journal import DurableJournal
from ksi_event_contracts.external_reconstruction import ExternalArtifactDeclarationV1
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.processing_job import ExecutionLocus
from ksi_event_contracts.spatial_data import (
    SpatialDataAttemptV1,
    SpatialDataFrozenJobV1,
    SpatialDataSourceV1,
)
from ksi_event_contracts.spatial_data_worker import (
    SpatialDataSourceCapabilityV1,
    SpatialDataUploadCapabilityV1,
)
from ksi_processing_controller.external_geotiff_inspector import inspect_synthetic_sealed_geotiff
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)
from ksi_processing_controller.spatial_data_sandbox import SpatialDataSandbox
from ksi_processing_controller.spatial_data_worker import run_once
from spatial_data_fixture import make_activation, make_grant, make_policy, make_runtime
from spatial_data_job_fixture import NOW, LocalJobAuthority, job_store
from spatial_data_source_fixture import (
    restart_source_stores,
    source_identity,
    source_resolver,
    source_stores,
)
from support.external_artifact_inspection_fixtures import policy_template
from test_external_native_window import _envelope, _write_dsm, _write_ortho
from test_spatial_data_worker import core_client
from test_spatial_data_worker_api import LocalProvider


def client_module() -> ModuleType:
    spec = spec_from_file_location(
        "native_window_client",
        Path(__file__).resolve().parents[2] / "examples/spatial-data/native_window_client.py",
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mounted_transport(client: TestClient) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        response = client.request(
            request.method, request.url.path, headers=dict(request.headers), content=request.read()
        )
        return httpx.Response(
            response.status_code,
            stream=httpx.ByteStream(response.content),
            headers=dict(response.headers),
        )

    return httpx.MockTransport(handle)


class GeneratedLauncher:
    def __init__(self, mutation: str | None) -> None:
        self.mutation = mutation

    def launch(self, *, workspace: Path, job: SpatialDataFrozenJobV1) -> subprocess.Popen[bytes]:
        script = """
import json, os, struct, sys
from datetime import datetime
from pathlib import Path
sys.path[:0] = json.loads(sys.argv[1])
from ksi_event_contracts.spatial_data import SpatialDataFrozenJobV1
from ksi_processing_controller.spatial_data_entrypoint import prepare_native_candidate
from ksi_processing_controller.spatial_data_sandbox import apply_spatial_data_rlimits
def emit(body):
    raw = json.dumps(body, separators=(',', ':')).encode()
    sys.stdout.buffer.write(struct.pack('>I', len(raw)) + raw); sys.stdout.buffer.flush()
emit({'version':'spatial-data-sandbox-ready.v1','pid':os.getpid(),'ready':True})
n = struct.unpack('>I', sys.stdin.buffer.read(4))[0]
request = json.loads(sys.stdin.buffer.read(n)); assert not sys.stdin.buffer.read(1)
job = SpatialDataFrozenJobV1.model_validate(request['job'])
apply_spatial_data_rlimits(job.policy.resource_envelope,
    max_output_bytes=job.policy.max_output_bytes)
root = Path(sys.argv[2])
receipt = prepare_native_candidate(job=job, source_path=root/'source.tif', output_parent=root,
    prepared_at=datetime.fromisoformat(request['preparedAt']), is_current=lambda: True)
if sys.argv[3] == 'receipt':
    receipt = receipt.model_copy(update={
        'source_digest':'sha256:'+'f'*64,'receipt_digest':None}).sealed()
if sys.argv[3] == 'candidate':
    (root/'candidate.tif').write_bytes(b'substituted')
emit({'version':'spatial-data-sandbox-result.v1','receipt':receipt.model_dump(mode='json',by_alias=True),'reason':None})
"""
        return subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-c",
                script,
                json.dumps(sys.path),
                str(workspace),
                self.mutation or "none",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            env={"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
        )

    def verify_containment(self, **_: Any) -> bool:
        # Explicit generated-only seam; this does NOT satisfy the production kernel proof.
        return True


class LocalVersionProvider(LocalProvider):
    def __init__(self, graph: SimpleNamespace, origin: str, source: bytes) -> None:
        super().__init__(graph)
        self.origin, self.source = origin, source
        self.payload: bytes | None = None
        self.uploads = 0

    def issue_source_get(
        self, source: SpatialDataSourceV1, attempt: SpatialDataAttemptV1, *, expires_at: datetime
    ) -> SpatialDataSourceCapabilityV1:
        assert source.source_digest is not None
        return SpatialDataSourceCapabilityV1(
            artifact_id=source.artifact_id,
            source_digest=source.source_digest,
            observed_sha256=source.observed_sha256,
            observed_size_bytes=source.observed_size_bytes,
            download_url=self.origin + "/source",
            required_headers=(),
            expires_at=expires_at,
        )

    def issue_output_put(self, *args: Any, **kwargs: Any) -> SpatialDataUploadCapabilityV1:
        cap = super().issue_output_put(*args, **kwargs)
        self.expected = self.observation
        self.observation = None  # Observation exists only AFTER real PUT bytes arrive.
        return cap.model_copy(update={"upload_url": self.origin + "/output"})

    @contextmanager
    def open_version(
        self, observation: SpatialDataObjectObservation, *, chunk_bytes: int, deadline: datetime
    ) -> Iterator[Iterator[bytes]]:
        assert observation == self.observation and self.payload is not None and deadline > NOW
        yield (self.payload[i : i + chunk_bytes] for i in range(0, len(self.payload), chunk_bytes))


class HttpLane:
    def __init__(
        self,
        root: Path,
        kind: str,
        origin: str,
        mutation: str | None,
        stream_chunk_bytes: int = 512,
    ) -> None:
        self.root, self.mutation = root, mutation
        self.source_path = root / "generated.tif"
        (_write_dsm if kind == "dsm" else _write_ortho)(self.source_path)
        self.source_bytes = self.source_path.read_bytes()
        env = _envelope(
            max_memory_bytes=1_073_741_824,
            max_workspace_bytes=6_000_000,
            max_retry_attempts=3,
            max_tenant_concurrency=2,
            max_queue_depth=8,
        )
        declaration = ExternalArtifactDeclarationV1(
            artifact_id=kind,
            kind=ProcessingArtifactKind(kind),
            file_name="generated.tif",
            format="GeoTIFF",
            content_type="application/octet-stream",
            declared_sha256=hashlib.sha256(self.source_bytes).hexdigest(),
            declared_size_bytes=len(self.source_bytes),
        )
        template = (
            policy_template()
            .model_copy(
                update={
                    "resource_envelope": env,
                    "resource_envelope_digest": env.canonical_digest(),
                    "policy_digest": None,
                }
            )
            .sealed()
        )
        inputs = [(self.source_path, declaration)]
        if kind == "dsm":
            ortho_path = root / "generated-ortho.tif"
            _write_ortho(ortho_path)
            inputs.append(
                (
                    ortho_path,
                    ExternalArtifactDeclarationV1(
                        artifact_id="ortho",
                        kind=ProcessingArtifactKind.ORTHO,
                        file_name="generated-ortho.tif",
                        format="GeoTIFF",
                        content_type="application/octet-stream",
                        declared_sha256=hashlib.sha256(ortho_path.read_bytes()).hexdigest(),
                        declared_size_bytes=ortho_path.stat().st_size,
                    ),
                )
            )

        def measurements(policy: Any) -> Any:
            outcomes = tuple(
                inspect_synthetic_sealed_geotiff(
                    path,
                    artifact_id=d.artifact_id,
                    observed_sha256="sha256:" + d.declared_sha256,
                    artifact_kind=d.kind,
                    envelope=policy.resource_envelope,
                )
                for path, d in inputs
            )
            self.inspection = outcomes[0]
            assert all(item.outcome.value == "MEASURED" for item in outcomes), outcomes
            return outcomes

        graph = source_stores(
            root,
            artifact_declarations=tuple(d for _, d in inputs),
            inspection_template=template,
            measurement_factory=measurements,
        )
        graph.data_policy = make_policy(
            stream_chunk_bytes=stream_chunk_bytes,
            resource_envelope=env,
            max_output_bytes=1_000_000,
            max_stream_bytes=1_000_000,
        )
        graph.runtime = make_runtime()
        graph.activation = make_activation(
            organization_id=graph.principal.organization_id,
            worker_principal_id="data-worker-1",
            worker_instance_id="instance-1",
            policy_digest=graph.data_policy.policy_digest,
            runtime_digest=graph.runtime.runtime_digest,
            trusted_endpoint_origins=(origin,),
            valid_from=NOW - timedelta(minutes=1),
            valid_until=NOW + timedelta(minutes=1),
        )
        graph.sources = source_resolver(graph)
        graph.source = graph.sources.resolve(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            asset_ref=source_identity(graph, artifact_id=kind),
            principal=graph.principal,
        )
        graph.grants = SpatialDataGrantStore(
            DurableJournal(root / "grants.jsonl"), coordinator=graph.coordinator
        )
        assert self.inspection.measurements is not None
        graph.grant = make_grant(
            organization_id=graph.principal.organization_id,
            beneficiary_principal_id=graph.principal.principal_id,
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            asset_ref=graph.source.asset_ref,
            observed_crs_digest=self.inspection.measurements.observed_crs_digest,
            allowed_bounds=(100, 180, 120, 200),
            policy_digest=graph.data_policy.policy_digest,
            valid_from=NOW - timedelta(minutes=1),
            valid_until=NOW + timedelta(minutes=1),
            attribution="Generated raster; local test only",
        )
        graph.grants.provision(graph.grant)
        graph.authorizer = SpatialDataGrantAuthorizer(
            grants=graph.grants, sites=graph.sites, processing_location=ExecutionLocus.SITE_ONPREM
        )
        graph.inspection_authority = graph.authority
        graph.authority = LocalJobAuthority(graph)
        graph.worker = Principal(
            principal_id="data-worker-1",
            organization_id=graph.principal.organization_id,
            kind=PrincipalKind.SPATIAL_DATA_WORKER,
            role=None,
            device_id=None,
        )
        graph.path = root
        self.graph = graph
        self.provider = LocalVersionProvider(graph, origin, self.source_bytes)
        self.workspace, self.spool = root / "worker", root / "spool"
        self.workspace.mkdir(mode=0o700)
        self.spool.mkdir(mode=0o700)
        self.transport_policy = ExternalObjectTransportPolicyV1(
            endpoints=(TrustedObjectEndpointV1(origin=origin, addresses=("127.0.0.1",)),),
            max_header_bytes=4096,
            max_object_bytes=1_000_000,
            max_chunk_bytes=512,
        )
        assert self.inspection.measurements is not None
        self.request = dict(
            assetRef=graph.source.asset_ref,
            requestedBounds=[102.1, 183.9, 108.1, 193.9],
            observedCrsDigest=self.inspection.measurements.observed_crs_digest,
            resolutionMode="NATIVE",
            purpose="GENERAL_DATA_USE",
        )
        self.base = f"/v1/sites/site-1/work-areas/{graph.area.work_area_id}/spatial-data-requests"
        self.auth = {"Authorization": "Bearer local"}
        self.mount()

    def mount(self) -> None:
        graph = self.graph
        graph.store = job_store(graph)
        self.audit = SpatialDataAuditStore(
            DurableJournal(self.root / "audit.jsonl"), policy=graph.data_policy
        )
        self.downloads = SpatialDataDownloadService(
            jobs=graph.store,
            storage=self.provider,
            audit=self.audit,
            policy=graph.data_policy,
            spool_root=self.spool,
            clock=lambda: NOW,
        )
        app = FastAPI()
        registry = AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(token.encode()).hexdigest(), principal=principal
                )
                for token, principal in (
                    ("local", graph.principal),
                    ("local-worker", graph.worker),
                    (
                        "foreign",
                        replace(graph.principal, principal_id="foreign", organization_id="foreign"),
                    ),
                )
            ]
        )
        mount_auth(app, registry)
        app.include_router(
            build_spatial_data_router(
                jobs=graph.store,
                grants=graph.authorizer,
                sources=graph.sources,
                downloads=self.downloads,
                clock=lambda: NOW,
            )
        )
        app.include_router(
            build_spatial_data_worker_router(
                jobs=graph.store,
                storage=self.provider,
                activation=graph.activation,
                clock=lambda: NOW,
            )
        )
        self.http = TestClient(app)
        self.consumer = client_module().NativeWindowClient(
            base_url="https://core.invalid",
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            token="local",
            max_json_bytes=65536,
            max_file_bytes=1_000_000,
            timeout_seconds=10,
            transport=mounted_transport(self.http),
        )

    def file_url(self, status: dict[str, Any]) -> str:
        return self.base + "/" + status["jobId"] + "/file"

    def request_and_run(self) -> dict[str, Any]:
        issued = self.consumer.issue(request=self.request, idempotency_key="integration-1")
        with core_client(self.graph, mounted_transport(self.http)) as core:
            sandbox = SpatialDataSandbox(
                launcher=GeneratedLauncher(self.mutation),
                clock=lambda: NOW,
                wall_timeout_seconds=5,
                heartbeat_interval_millis=50,
            )
            try:
                assert run_once(
                    core=core,
                    sandbox=sandbox,
                    transport_policy=self.transport_policy,
                    worker_instance_id="instance-1",
                    clock=lambda: NOW,
                    workspace_root=self.workspace,
                    heartbeat_interval_millis=100,
                )
            finally:
                sandbox.close()
        return self.consumer.status(issued["jobId"])

    def revoke(self) -> None:
        from ksi_event_contracts.spatial_data_authority import SpatialDataRevocationV1

        grant = self.graph.grant
        self.graph.grants.revoke(
            SpatialDataRevocationV1(
                grant_id=grant.grant_id,
                revision=grant.revision,
                organization_id=grant.organization_id,
                grant_digest=grant.grant_digest,
                revoked_at=NOW,
                reason="test rights withdrawn",
            ).sealed()
        )

    def restart(self) -> None:
        self.consumer.close()
        self.http.close()
        self.audit.close()
        graph = self.graph
        graph.store._journal.close()
        graph.grants._journal.close()
        graph.authority = graph.inspection_authority
        self.graph = graph = restart_source_stores(graph, self.root)
        graph.inspection_authority = graph.authority
        graph.authority = LocalJobAuthority(graph)
        graph.grants = SpatialDataGrantStore(
            DurableJournal(self.root / "grants.jsonl"), coordinator=graph.coordinator
        )
        graph.authorizer = SpatialDataGrantAuthorizer(
            grants=graph.grants, sites=graph.sites, processing_location=ExecutionLocus.SITE_ONPREM
        )
        graph.sources = source_resolver(graph)
        self.provider.graph = graph
        self.mount()


@contextmanager
def http_lane(
    root: Path, *, kind: str = "dsm", mutation: str | None = None, stream_chunk_bytes: int = 512
) -> Iterator[HttpLane]:
    lane: HttpLane | None = None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: Any) -> None:
            pass

        def do_GET(self) -> None:
            assert lane is not None
            payload = lane.source_bytes
            if mutation == "source":
                payload = b"x" * len(payload)
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_PUT(self) -> None:
            assert lane is not None
            payload = self.rfile.read(int(self.headers["Content-Length"]))
            expected = lane.provider.expected
            assert expected is not None
            assert "Authorization" not in self.headers
            assert (
                len(payload) == expected.size_bytes
                and "sha256:" + hashlib.sha256(payload).hexdigest() == expected.sha256
            )
            assert (
                self.headers["x-amz-checksum-sha256"]
                == base64.b64encode(bytes.fromhex(expected.sha256[7:])).decode()
            )
            lane.provider.payload = payload
            lane.provider.observation = SpatialDataObjectObservation(
                expected.object_key, "local-version-1", len(payload), expected.sha256, "image/tiff"
            )
            lane.provider.uploads += 1
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        lane = HttpLane(
            root,
            kind,
            f"http://127.0.0.1:{server.server_port}",
            mutation,
            stream_chunk_bytes=stream_chunk_bytes,
        )
        lane.graph.authorizer = SpatialDataGrantAuthorizer(
            grants=lane.graph.grants,
            sites=lane.graph.sites,
            processing_location=ExecutionLocus.SITE_ONPREM,
        )
        yield lane
    finally:
        if lane is not None:
            lane.consumer.close()
            lane.http.close()
            lane.audit.close()
            lane.graph.store._journal.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
