"""Lightweight loopback fixture for the spatial-data MCP adapter tests.

Only Task5 will add the real Core TIFF/worker path. This module provides a
plain loopback HTTP Core double, private generated configs/tokens under an
owned clean-ancestry scratch (never ``/tmp`` parents, which the adapter's
secure-file policy rejects as world-writable, and never the plan tree,
whose repository ancestors are group-writable and therefore rejected too),
and an explicit new-source path prepend for subprocesses. It touches no
real credentials, customer data, or network.
"""

from __future__ import annotations

import atexit as _atexit
import json
import os
import stat
import sys
import tempfile
from collections.abc import Callable
from collections.abc import Iterator as _Task5Iterator
from contextlib import contextmanager as _task5_contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_SRC = REPO_ROOT / "services" / "spatial-data-mcp" / "src"
# Owned generated-test namespace only: one unique 0700 directory per test
# process, created directly under the already-secure caller cache. Existing
# fixed namespaces (including earlier task runs) are never chmodded,
# scanned, or deleted; only this unique directory is test-owned and only it
# may be cleaned up.
_FIXTURE_NAMESPACE_PREFIX = "ksi-spatial-data-mcp-task4-"
_PRIVATE_ROOT: Path | None = None

# Required, strict, finite tests-only limits (not production quotas).
FIXTURE_LIMITS: dict[str, Any] = {
    "maxRequestBytes": 8192,
    "maxStructuredResponseBytes": 131072,
    "maxConcurrentCalls": 2,
    "maxIdentifierBytes": 255,
    "maxCursorBytes": 2048,
    "maxTokenBytes": 4096,
    "maxConfigBytes": 16384,
    "connectTimeoutSeconds": 2.0,
    "readTimeoutSeconds": 2.0,
    "poolTimeoutSeconds": 1.0,
    "callDeadlineSeconds": 5.0,
}


def ensure_source_path() -> None:
    """Prepend the explicit new-source path; never an editable install/shared sync."""
    explicit = os.fspath(PACKAGE_SRC)
    if explicit not in sys.path:
        sys.path.insert(0, explicit)


def _caller_cache() -> Path:
    """The already-secure caller cache; never created, moved, or re-permissioned."""
    cache = Path.home() / ".cache"
    metadata = os.lstat(cache)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o022
    ):
        raise RuntimeError("caller cache is not a secure owned directory")
    return cache


def private_root() -> Path:
    """One unique test-owned namespace per process (mkdtemp is 0700)."""
    global _PRIVATE_ROOT
    if _PRIVATE_ROOT is None:
        _PRIVATE_ROOT = Path(
            tempfile.mkdtemp(prefix=_FIXTURE_NAMESPACE_PREFIX, dir=_caller_cache())
        )
    return _PRIVATE_ROOT


def _cleanup_private_root() -> None:
    """Best-effort removal of exactly the unique directory this process made."""
    import shutil

    root = _PRIVATE_ROOT
    if root is not None and root.name.startswith(_FIXTURE_NAMESPACE_PREFIX):
        shutil.rmtree(root, ignore_errors=True)


_atexit.register(_cleanup_private_root)


def private_dir() -> Path:
    path = private_root() / "private"
    path.mkdir(parents=True, exist_ok=True)
    # Harden only the directory this fixture owns; the ambient umask must
    # not leave it group-writable.
    path.chmod(0o700)
    return path


def write_private_bytes(name: str, data: bytes) -> Path:
    directory = private_dir()
    path = directory / name
    path.write_bytes(data)
    path.chmod(0o600)
    return path


def write_token(name: str, token: str = "fixture-opaque-token") -> Path:
    return write_private_bytes(name, (token + "\n").encode("ascii"))


def write_adapter_config(
    name: str,
    *,
    origin: str,
    token_path: Path,
    overrides: dict[str, Any] | None = None,
) -> Path:
    payload: dict[str, Any] = {
        "coreOrigin": origin,
        "tokenFile": os.fspath(token_path),
        **FIXTURE_LIMITS,
    }
    if overrides:
        payload.update(overrides)
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return write_private_bytes(name, raw)


Responder = Callable[[str, str, dict[str, str], bytes], tuple[int, dict[str, str], bytes]]


class LoopbackCore:
    """One owned loopback HTTP listener recording actual requests."""

    def __init__(self, responder: Responder) -> None:
        self._responder = responder
        self.requests: list[dict[str, Any]] = []
        handler = self._build_handler()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                status, headers, response_body = outer._responder(
                    self.command, self.path, dict(self.headers), body
                )
                outer.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": body,
                    }
                )
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(response_body)

            do_GET = _handle
            do_POST = _handle
            do_HEAD = _handle

            def log_message(self, _format: str, *_args: object) -> None:
                return

        return Handler

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def start(self) -> LoopbackCore:
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def json_response(
    payload: Any, *, status: int = 200, ack: bool = True
) -> tuple[int, dict[str, str], bytes]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if ack:
        headers["X-KSI-Spatial-Data-AI-Egress"] = "ALLOWED"
    return status, headers, body


# ---------------------------------------------------------------------------
# Task5: genuine AI Core lane over real loopback HTTP.
#
# Additive-only Task5 section. Nothing above is modified. This lane composes
# the genuine generated-TIFF inspector, real Core journals/authority/grants,
# the actual AI egress/discovery routers, a separately started worker
# (subprocess launcher + run_once), the official SDK stdio adapter path, and
# a separate HTTP-only consumer — all over real loopback sockets except the
# worker's own pinned secure client, which requires an https origin and
# therefore reaches the SAME live app through an in-process mounted
# transport (never a mock body). The AI data plane (discovery, create, list,
# status, receipt, cancel, file) always uses real HTTP with query strings
# preserved. Only generated owned TIFFs are decoded; no customer data, no
# production credentials, no host installation.
# ---------------------------------------------------------------------------

TASK5_AI_TOKEN = "ai-test-token"
TASK5_OPERATOR_TOKEN = "operator-test-token"
TASK5_WORKER_TOKEN = "worker-test-token"
TASK5_FOREIGN_TOKEN = "foreign-test-token"

TASK5_REQUEST_BOUNDS = (102.1, 183.9, 108.1, 193.9)
TASK5_FULL_EXTENT_BOUNDS = (100, 180, 120, 200)

_ACK_HEADER = "X-KSI-Spatial-Data-AI-Egress"


def task5_write_rgba(path: Path) -> Any:
    """Genuine owned 4-band RGBA TIFF on the shared 10x10 test grid."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    values = np.zeros((4, 10, 10), dtype=np.uint8)
    rows, cols = np.indices((10, 10))
    values[0] = 200
    values[1] = (rows * 20).astype(np.uint8)
    values[2] = (cols * 20).astype(np.uint8)
    values[3] = 255
    values[3, 3, 3] = 0
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=4,
        dtype="uint8",
        crs="EPSG:3857",
        transform=from_origin(100.0, 200.0, 2.0, 2.0),
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="DEFLATE",
        predictor=2,
        interleave="pixel",
        photometric="RGB",
        ALPHA="YES",
    ) as dataset:
        dataset.write(values)
        dataset.colorinterp = (
            rasterio.enums.ColorInterp.red,
            rasterio.enums.ColorInterp.green,
            rasterio.enums.ColorInterp.blue,
            rasterio.enums.ColorInterp.alpha,
        )
    return values


def task5_write_epoch2_variant(path: Path, kind: str) -> Any:
    """Genuinely different owned pixels on the same grid for a new observation."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    transform = from_origin(100.0, 200.0, 2.0, 2.0)
    if kind == "dsm":
        values = np.arange(100, dtype=np.float32).reshape(10, 10) + 1000.0
        values[1, 1] = -9999.0
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=10,
            height=10,
            count=1,
            dtype="float32",
            crs="EPSG:3857",
            transform=transform,
            nodata=-9999.0,
            tiled=True,
            blockxsize=16,
            blockysize=16,
            compress="DEFLATE",
        ) as dataset:
            dataset.write(values, 1)
        return values
    values = np.zeros((4 if kind == "rgba" else 3, 10, 10), dtype=np.uint8)
    rows, cols = np.indices((10, 10))
    values[0] = 90
    values[1] = ((rows * 20 + 50) % 256).astype(np.uint8)
    values[2] = ((cols * 20 + 50) % 256).astype(np.uint8)
    if kind == "rgba":
        values[3] = 200
    if kind == "ortho":
        import rasterio as _rasterio

        env = _rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True)
    else:
        import contextlib as _contextlib

        env = _contextlib.nullcontext()
    with (
        env,
        rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=10,
            height=10,
            count=4 if kind == "rgba" else 3,
            dtype="uint8",
            crs="EPSG:3857",
            transform=transform,
            tiled=True,
            blockxsize=16,
            blockysize=16,
            compress="DEFLATE",
            photometric="RGB" if kind == "ortho" else None,
        ) as dataset,
    ):
        dataset.write(values)
        if kind == "ortho":
            mask = np.full((10, 10), 255, dtype=np.uint8)
            mask[5, 5] = 0
            dataset.write_mask(mask)
    return values


def task5_free_port() -> int:
    import socket as _socket

    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


class Task5CoreHttp:
    """One owned uvicorn listener serving the live Core app on loopback."""

    def __init__(self, app: Any, port: int) -> None:
        self._app = app
        self._port = port
        self._server: Any = None
        self._thread: Any = None

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def start(self) -> Task5CoreHttp:
        import threading as _threading
        import time as _time

        import uvicorn

        config = uvicorn.Config(
            self._app, host="127.0.0.1", port=self._port, log_level="error", access_log=False
        )
        self._server = uvicorn.Server(config)
        self._thread = _threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = _time.monotonic() + 15
        while not self._server.started:
            if _time.monotonic() > deadline:
                raise RuntimeError("task5 core loopback did not start")
            _time.sleep(0.02)
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=15)
        self._server, self._thread = None, None


class Task5AiAuthority:
    """Test-only currentness resolving the operator and the AI principal."""

    def __init__(self, graph: Any, ai: Any) -> None:
        self.coordinator = graph.coordinator
        self._principals = {
            (graph.principal.principal_id, graph.principal.organization_id): graph.principal,
            (ai.principal_id, ai.organization_id): ai,
        }
        self.enabled = True

    def resolve_requester(self, *, principal_id: str, organization_id: str, now: Any = None) -> Any:
        return self._principals.get((principal_id, organization_id))

    def is_current(self, *, policy: Any, runtime: Any, activation: Any, now: Any) -> bool:
        return self.enabled and activation.is_current_at(now)


def task5_worker_transport(client: Any) -> Any:
    """In-process transport to the SAME live app for the pinned https-only worker client."""
    import httpx

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        raw_query = bytes(request.url.query)
        if raw_query:
            path = path + "?" + raw_query.decode("ascii")
        response = client.request(
            request.method, path, headers=dict(request.headers), content=request.read()
        )
        return httpx.Response(
            response.status_code,
            content=response.content,
            headers=dict(response.headers),
        )

    return httpx.MockTransport(handle)


def task5_sdk_parameters(config: Path) -> Any:
    """Official SDK stdio parameters for the adapter server (source-only, no install)."""
    import os as _os
    import sys as _sys

    from mcp.client.stdio import StdioServerParameters

    env = {
        key: value
        for key, value in _os.environ.items()
        if key not in {"HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"}
    }
    env["PYTHONPATH"] = os.fspath(PACKAGE_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return StdioServerParameters(
        command=_sys.executable,
        args=["-m", "ksi_spatial_data_mcp.server", f"--config={config}"],
        env=env,
    )


def task5_sdk_config(origin: str, *, name: str) -> Path:
    """Private adapter config + token file for the generated AI principal."""
    token = write_token(f"task5-{name}-token", TASK5_AI_TOKEN)
    return write_adapter_config(f"task5-{name}-adapter.json", origin=origin, token_path=token)


class Task5AiCoreLane:
    """Genuine AI lane: generated TIFF, real Core authority, real loopback HTTP."""

    def __init__(
        self,
        root: Path,
        *,
        kind: str,
        mutation: str | None,
        stream_chunk_bytes: int,
        object_origin: str,
        core_port: int,
    ) -> None:
        from dataclasses import replace as _replace
        from datetime import timedelta as _timedelta

        from ksi_core.auth import (
            Principal as _Principal,
        )
        from ksi_core.auth import (
            PrincipalKind as _PrincipalKind,
        )
        from ksi_core.domains.external.delivery.grants import (
            SpatialDataGrantAuthorizer as _Authorizer,
        )
        from ksi_core.domains.external.delivery.grants import (
            SpatialDataGrantStore as _GrantStore,
        )
        from ksi_core.durable_journal import DurableJournal as _Journal
        from ksi_event_contracts.external_reconstruction import (
            ExternalArtifactDeclarationV1 as _Declaration,
        )
        from ksi_event_contracts.processing_artifact import (
            ProcessingArtifactKind as _ArtifactKind,
        )
        from ksi_processing_controller.external_geotiff_inspector import (
            inspect_synthetic_sealed_geotiff as _inspect,
        )
        from spatial_data_fixture import make_activation as _activation
        from spatial_data_fixture import make_grant as _grant
        from spatial_data_fixture import make_policy as _policy
        from spatial_data_fixture import make_runtime as _runtime
        from spatial_data_http_fixture import LocalVersionProvider as _Provider
        from spatial_data_source_fixture import source_resolver as _resolver
        from spatial_data_source_fixture import source_stores as _stores
        from test_external_native_window import _envelope as _envelope
        from test_external_native_window import _write_dsm, _write_ortho

        assert kind in ("dsm", "rgb", "rgba")
        self.root, self.kind, self.mutation = root, kind, mutation
        self.object_origin = object_origin
        self.core_port = core_port
        artifact_kind = "dsm" if kind == "dsm" else "ortho"
        artifact_id = artifact_kind
        primary_writer: Callable[..., Any]
        if kind == "dsm":
            primary_path, primary_writer = root / "generated.tif", _write_dsm
        elif kind == "rgb":
            primary_path, primary_writer = root / "generated.tif", _write_ortho
        else:
            primary_path, primary_writer = root / "generated.tif", task5_write_rgba
        primary_writer(primary_path)
        inputs: list[tuple[Any, Any, Any]] = [(primary_path, artifact_id, artifact_kind)]
        if kind == "dsm":
            # Sealed submissions require exactly one ortho companion.
            companion_path = root / "companion-ortho.tif"
            _write_ortho(companion_path)
            inputs.append((companion_path, "ortho", "ortho"))
        import hashlib as _hashlib

        declarations = tuple(
            _Declaration(
                artifact_id=item_artifact_id,
                kind=_ArtifactKind(item_kind),
                file_name=path.name,
                format="GeoTIFF",
                content_type="application/octet-stream",
                declared_sha256=_hashlib.sha256(path.read_bytes()).hexdigest(),
                declared_size_bytes=path.stat().st_size,
            )
            for path, item_artifact_id, item_kind in inputs
        )
        self._artifact_kind = _ArtifactKind(artifact_kind)
        self._declaration = declarations[0]
        self.source_path = primary_path
        self.source_bytes = primary_path.read_bytes()

        env = _envelope(
            max_memory_bytes=1_073_741_824,
            max_workspace_bytes=6_000_000,
            max_retry_attempts=3,
            max_tenant_concurrency=2,
            max_queue_depth=8,
        )

        def measurements(policy: Any) -> Any:
            by_id = {item.artifact_id: item for item in declarations}
            outcomes = tuple(
                _inspect(
                    path,
                    artifact_id=item_artifact_id,
                    observed_sha256="sha256:" + by_id[item_artifact_id].declared_sha256,
                    artifact_kind=_ArtifactKind(item_kind),
                    envelope=policy.resource_envelope,
                )
                for path, item_artifact_id, item_kind in inputs
            )
            self.inspection = next(item for item in outcomes if item.artifact_id == artifact_id)
            assert all(item.outcome.value == "MEASURED" for item in outcomes), outcomes
            return outcomes

        from support.external_artifact_inspection_fixtures import policy_template

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
        graph = _stores(
            root,
            artifact_declarations=declarations,
            inspection_template=template,
            measurement_factory=measurements,
        )
        graph.data_policy = _policy(
            stream_chunk_bytes=stream_chunk_bytes,
            resource_envelope=env,
            max_output_bytes=1_000_000,
            max_stream_bytes=1_000_000,
        )
        graph.runtime = _runtime()
        graph.activation = _activation(
            organization_id=graph.principal.organization_id,
            worker_principal_id="data-worker-1",
            worker_instance_id="instance-1",
            policy_digest=graph.data_policy.policy_digest,
            runtime_digest=graph.runtime.runtime_digest,
            trusted_endpoint_origins=(object_origin,),
            valid_from=self._now() - _timedelta(minutes=1),
            valid_until=self._now() + _timedelta(minutes=1),
        )
        graph.path = root
        # Generated-test consent switch on the real site record.
        record = graph.sites._sites["site-1"]  # noqa: SLF001
        graph.sites._sites["site-1"] = _replace(record, ai_egress_allowed=True)  # noqa: SLF001
        graph.sources = _resolver(graph)
        assert self.inspection.measurements is not None
        from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog

        items = SpatialAssetCatalog(
            reconstruction=graph.reconstruction,
            work_orders=graph.work_orders,
            sites=graph.sites,
            work_areas=graph.work_areas,
            inspections=graph.inspections,
        ).items("site-1", graph.area.work_area_id, graph.principal)
        asset_ref = next(item.asset_ref for item in items if item.artifact_id == artifact_id)
        graph.source = graph.sources.resolve(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            asset_ref=asset_ref,
            principal=graph.principal,
        )
        self.ai = _Principal(
            "ai-client-1",
            _PrincipalKind.SPATIAL_DATA_MCP_CLIENT,
            None,
            None,
            "organization-1",
            allowed_site_ids=frozenset({"site-1"}),
            allowed_work_area_ids=frozenset({graph.area.work_area_id}),
        )
        graph.grants = _GrantStore(_Journal(root / "grants.jsonl"), coordinator=graph.coordinator)
        self._grant_factory = _grant
        graph.grant = _grant(
            grant_id="local-ai-grant",
            organization_id=self.ai.organization_id,
            beneficiary_principal_id=self.ai.principal_id,
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            asset_ref=graph.source.asset_ref,
            observed_crs_digest=self.inspection.measurements.observed_crs_digest,
            allowed_bounds=TASK5_FULL_EXTENT_BOUNDS,
            operations=("PREPARE", "READ"),
            purposes=("EXTERNAL_AI",),
            processing_location="site_onprem",
            policy_digest=graph.data_policy.policy_digest,
            valid_from=self._now() - _timedelta(minutes=1),
            valid_until=self._now() + _timedelta(minutes=1),
            attribution="Generated raster; local test only",
        )
        graph.grants.provision(graph.grant)
        graph.authorizer = _Authorizer(
            grants=graph.grants,
            sites=graph.sites,
            processing_location=self._locus(),
        )
        graph.inspection_authority = graph.authority
        graph.authority = Task5AiAuthority(graph, self.ai)
        graph.worker = _Principal(
            principal_id="data-worker-1",
            organization_id=graph.principal.organization_id,
            kind=_PrincipalKind.SPATIAL_DATA_WORKER,
            role=None,
            device_id=None,
        )
        self.graph = graph
        self.provider = _Provider(graph, object_origin, self.source_bytes)
        self.epoch_bytes: dict[str, bytes] = {graph.source.asset_ref: self.source_bytes}
        assert self.inspection.measurements is not None
        self.assets: dict[str, dict[str, Any]] = {
            "primary": {
                "asset_ref": graph.source.asset_ref,
                "observed_crs_digest": self.inspection.measurements.observed_crs_digest,
                "artifact_id": artifact_id,
                "measurements": self.inspection.measurements,
            }
        }
        self.workspace, self.spool = root / "worker", root / "spool"
        self.workspace.mkdir(mode=0o700)
        self.spool.mkdir(mode=0o700)
        from ksi_processing_controller.external_object_streams import (
            ExternalObjectTransportPolicyV1 as _TransportPolicy,
        )
        from ksi_processing_controller.external_object_streams import (
            TrustedObjectEndpointV1 as _Endpoint,
        )

        self.transport_policy = _TransportPolicy(
            endpoints=(_Endpoint(origin=object_origin, addresses=("127.0.0.1",)),),
            max_header_bytes=4096,
            max_object_bytes=1_000_000,
            max_chunk_bytes=512,
        )
        self.base = f"/v1/sites/site-1/work-areas/{graph.area.work_area_id}/spatial-data-requests"
        self.asset_base = (
            f"/v1/sites/site-1/work-areas/{graph.area.work_area_id}/spatial-data-assets"
        )
        self.area_id = graph.area.work_area_id
        self.mounted: Any = None
        self.core_http: Task5CoreHttp | None = None
        self.mount()

    @staticmethod
    def _now() -> Any:
        from spatial_data_job_fixture import NOW as _NOW

        return _NOW

    @staticmethod
    def _locus() -> Any:
        from ksi_event_contracts.processing_job import ExecutionLocus as _Locus

        return _Locus.SITE_ONPREM

    # -- mounting ---------------------------------------------------------
    def mount(self) -> None:
        import hashlib as _hashlib

        from fastapi import FastAPI as _FastAPI
        from ksi_core.auth import AuthRegistry as _Registry
        from ksi_core.auth import PrincipalTokenRecord as _Record
        from ksi_core.auth import mount_auth as _mount
        from ksi_core.domains.external.delivery.ai_egress import (
            SpatialDataAiEgress as _Egress,
        )
        from ksi_core.domains.external.delivery.api import (
            build_spatial_data_router as _data_router,
        )
        from ksi_core.domains.external.delivery.asset_api import (
            build_spatial_data_asset_router as _asset_router,
        )
        from ksi_core.domains.external.delivery.asset_discovery import (
            SpatialDataAssetDiscovery as _Discovery,
        )
        from ksi_core.domains.external.delivery.audit import (
            SpatialDataAuditStore as _Audit,
        )
        from ksi_core.domains.external.delivery.downloads import (
            SpatialDataDownloadService as _Downloads,
        )
        from ksi_core.domains.external.delivery.metadata_audit import (
            SpatialDataMetadataAuditStore as _MetadataAudit,
        )
        from ksi_core.domains.external.delivery.worker_api import (
            build_spatial_data_worker_router as _worker_router,
        )
        from ksi_core.durable_journal import DurableJournal as _Journal
        from spatial_data_job_fixture import job_store as _job_store

        graph = self.graph
        graph.store = _job_store(graph)
        self.audit = _Audit(_Journal(self.root / "audit.jsonl"), policy=graph.data_policy)
        self.metadata_audit = _MetadataAudit(
            _Journal(self.root / "metadata-audit.jsonl"), policy=graph.data_policy
        )
        self.discovery = _Discovery(
            sources=graph.sources,
            grants=graph.authorizer,
            jobs=graph.store,
            clock=lambda: self._now(),
        )
        self.egress = _Egress(
            graph.store,
            graph.sources,
            graph.authorizer,
            self.metadata_audit,
            clock=lambda: self._now(),
            discovery=self.discovery,
        )
        self.downloads = _Downloads(
            jobs=graph.store,
            storage=self.provider,
            audit=self.audit,
            policy=graph.data_policy,
            spool_root=self.spool,
            clock=lambda: self._now(),
        )
        app = _FastAPI()
        _mount(
            app,
            _Registry(
                [
                    _Record(
                        token_sha256=_hashlib.sha256(token.encode()).hexdigest(),
                        principal=principal,
                    )
                    for token, principal in (
                        (TASK5_AI_TOKEN, self.ai),
                        (TASK5_OPERATOR_TOKEN, graph.principal),
                        (TASK5_WORKER_TOKEN, graph.worker),
                        (
                            TASK5_FOREIGN_TOKEN,
                            self._foreign(graph),
                        ),
                    )
                ]
            ),
        )
        app.include_router(
            _data_router(
                jobs=graph.store,
                grants=graph.authorizer,
                sources=graph.sources,
                downloads=self.downloads,
                egress=self.egress,
                clock=lambda: self._now(),
            )
        )
        app.include_router(
            _asset_router(
                discovery=self.discovery,
                egress=self.egress,
                clock=lambda: self._now(),
            )
        )
        app.include_router(
            _worker_router(
                jobs=graph.store,
                storage=self.provider,
                activation=graph.activation,
                clock=lambda: self._now(),
            )
        )
        from fastapi.testclient import TestClient as _TestClient
        from spatial_data_http_fixture import client_module as _client_module

        self.mounted = _TestClient(app)
        self.app = app
        self.consumer = _client_module().NativeWindowClient(
            base_url=f"http://127.0.0.1:{self.core_port}",
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            token=TASK5_AI_TOKEN,
            max_json_bytes=65536,
            max_file_bytes=1_000_000,
            timeout_seconds=10,
            transport=None,
        )
        if self.core_http is None:
            self.core_http = Task5CoreHttp(app, self.core_port).start()
        else:
            self.core_http._app = app  # noqa: SLF001
            if self.core_http._server is None:  # noqa: SLF001
                self.core_http.start()

    @staticmethod
    def _foreign(graph: Any) -> Any:
        from dataclasses import replace as _replace

        return _replace(graph.principal, principal_id="foreign", organization_id="foreign")

    @property
    def origin(self) -> str:
        assert self.core_http is not None
        return self.core_http.origin

    # -- requests ----------------------------------------------------------
    def request_body(self, asset: str = "primary") -> dict[str, Any]:
        entry = self.assets[asset]
        return {
            "assetRef": entry["asset_ref"],
            "requestedBounds": list(TASK5_REQUEST_BOUNDS),
            "observedCrsDigest": entry["observed_crs_digest"],
            "resolutionMode": "NATIVE",
            "purpose": "EXTERNAL_AI",
        }

    def file_url(self, status: dict[str, Any]) -> str:
        return self.base + "/" + status["jobId"] + "/file"

    def run_worker(self, job_id: str) -> dict[str, Any]:
        from ksi_processing_controller.spatial_data_core_client import (
            SpatialDataCoreClient as _CoreClient,
        )
        from ksi_processing_controller.spatial_data_sandbox import (
            SpatialDataSandbox as _Sandbox,
        )
        from ksi_processing_controller.spatial_data_worker import run_once as _run_once
        from spatial_data_http_fixture import GeneratedLauncher as _Launcher

        graph = self.graph
        core = _CoreClient(
            base_url="https://core.invalid",
            token=TASK5_WORKER_TOKEN,
            activation=graph.activation,
            policy=graph.data_policy,
            runtime=graph.runtime,
            clock=lambda: self._now(),
            maximum_response_bytes=graph.data_policy.max_snapshot_bytes,
            request_timeout_seconds=5,
            transport=task5_worker_transport(self.mounted),
        )
        with core as handle:
            sandbox = _Sandbox(
                launcher=_Launcher(self.mutation),
                clock=lambda: self._now(),
                wall_timeout_seconds=10,
                heartbeat_interval_millis=50,
            )
            try:
                assert _run_once(
                    core=handle,
                    sandbox=sandbox,
                    transport_policy=self.transport_policy,
                    worker_instance_id="instance-1",
                    clock=lambda: self._now(),
                    workspace_root=self.workspace,
                    heartbeat_interval_millis=100,
                )
            finally:
                sandbox.close()
        return self.consumer.status(job_id)

    def request_and_run(self, *, key: str, asset: str = "primary") -> dict[str, Any]:
        entry = self.assets[asset]
        self.provider.source = self.epoch_bytes[entry["asset_ref"]]
        issued = self.consumer.issue(request=self.request_body(asset), idempotency_key=key)
        return self.run_worker(issued["jobId"])

    # -- rights mutation ----------------------------------------------------
    def revoke_grant(self) -> None:
        from ksi_event_contracts.spatial_data_authority import (
            SpatialDataRevocationV1 as _Revocation,
        )

        grant = self.graph.grant
        self.graph.grants.revoke(
            _Revocation(
                grant_id=grant.grant_id,
                revision=grant.revision,
                organization_id=grant.organization_id,
                grant_digest=grant.grant_digest,
                revoked_at=self._now(),
                reason="test rights withdrawn",
            ).sealed()
        )

    def replace_grant(self, **overrides: Any) -> Any:
        from datetime import timedelta as _timedelta

        payload: dict[str, Any] = {
            "grant_id": "local-ai-grant-replacement",
            "organization_id": self.ai.organization_id,
            "beneficiary_principal_id": self.ai.principal_id,
            "site_id": "site-1",
            "work_area_id": self.area_id,
            "asset_ref": self.graph.source.asset_ref,
            "observed_crs_digest": self.assets["primary"]["observed_crs_digest"],
            "allowed_bounds": TASK5_FULL_EXTENT_BOUNDS,
            "operations": ("PREPARE", "READ"),
            "purposes": ("EXTERNAL_AI",),
            "processing_location": "site_onprem",
            "policy_digest": self.graph.data_policy.policy_digest,
            "valid_from": self._now() - _timedelta(minutes=1),
            "valid_until": self._now() + _timedelta(minutes=1),
            "attribution": "Generated raster; local test only",
        }
        payload.update(overrides)
        grant = self._grant_factory(**payload)
        self.graph.grants.provision(grant)
        return grant

    def set_consent(self, allowed: bool) -> None:
        from dataclasses import replace as _replace

        record = self.graph.sites._sites["site-1"]  # noqa: SLF001
        self.graph.sites._sites["site-1"] = _replace(  # noqa: SLF001
            record, ai_egress_allowed=allowed
        )

    # -- restart --------------------------------------------------------------
    def restart(self) -> None:
        from ksi_core.domains.external.delivery.grants import (
            SpatialDataGrantAuthorizer as _Authorizer,
        )
        from ksi_core.domains.external.delivery.grants import (
            SpatialDataGrantStore as _GrantStore,
        )
        from ksi_core.durable_journal import DurableJournal as _Journal
        from spatial_data_source_fixture import restart_source_stores as _restart
        from spatial_data_source_fixture import source_resolver as _resolver

        assert self.core_http is not None
        self.core_http.stop()
        self.consumer.close()
        self.mounted.close()
        self.audit.close()
        self.metadata_audit.close()
        graph = self.graph
        graph.store._journal.close()  # noqa: SLF001
        graph.grants._journal.close()  # noqa: SLF001
        graph.authority = graph.inspection_authority
        self.graph = graph = _restart(graph, self.root)
        graph.inspection_authority = graph.authority
        graph.authority = Task5AiAuthority(graph, self.ai)
        graph.grants = _GrantStore(
            _Journal(self.root / "grants.jsonl"), coordinator=graph.coordinator
        )
        graph.authorizer = _Authorizer(
            grants=graph.grants,
            sites=graph.sites,
            processing_location=self._locus(),
        )
        graph.sources = _resolver(graph)
        self.provider.graph = graph
        self.mount()

    def close(self) -> None:
        for handle in (
            getattr(self, "consumer", None),
            getattr(self, "mounted", None),
            getattr(self, "audit", None),
            getattr(self, "metadata_audit", None),
        ):
            if handle is not None:
                with _suppress():
                    handle.close()
        graph = getattr(self, "graph", None)
        if graph is not None:
            for store in (getattr(graph, "store", None), getattr(graph, "grants", None)):
                journal = getattr(store, "_journal", None)  # noqa: SLF001
                if journal is not None:
                    with _suppress():
                        journal.close()
        if self.core_http is not None:
            self.core_http.stop()

    # -- second observation ----------------------------------------------------
    def advance_observation(self) -> dict[str, Any]:
        """Register, seal, genuinely inspect and grant a new-epoch observation."""
        import hashlib as _hashlib

        from ksi_core.domains.external.ingress.external_reconstruction import (
            ExternalReconstructionVerdict as _Verdict,
        )
        from ksi_core.domains.external.ingress.spatial_asset_catalog import (
            SpatialAssetCatalog as _Catalog,
        )
        from ksi_core.domains.observations.epoch_identity import observation_epoch_id as _epoch_id
        from ksi_core.evidence import ObjectStorageObservation as _Observation
        from ksi_core.leasing import LeaseFence as _Fence
        from ksi_event_contracts.external_artifact_validation import (
            SealedArtifactBindingV1 as _Binding,
        )
        from ksi_event_contracts.external_artifact_validation import (
            SealedExternalSubjectV1 as _Subject,
        )
        from ksi_event_contracts.external_reconstruction import (
            ExternalArtifactDeclarationV1 as _Declaration,
        )
        from ksi_event_contracts.processing_artifact import (
            ProcessingArtifactKind as _ArtifactKind,
        )
        from ksi_processing_controller.external_geotiff_inspector import (
            inspect_synthetic_sealed_geotiff as _inspect,
        )
        from support.external_artifact_inspection_fixtures import (
            ACQUISITION_B as _ACQ_B,
        )
        from support.external_artifact_inspection_fixtures import (
            WORKER_A as _WORKER,
        )
        from support.external_artifact_inspection_fixtures import (
            SyntheticStorage as _Storage,
        )
        from support.external_artifact_inspection_fixtures import (
            sealed_submission as _submission,
        )
        from test_external_native_window import _envelope as _envelope

        graph = self.graph
        kind = self.kind
        primary_kind = "dsm" if kind == "dsm" else "ortho"
        artifact_id = f"{primary_kind}-epoch2"
        tiff_path = self.root / "generated-epoch2.tif"
        task5_write_epoch2_variant(tiff_path, kind)
        epoch_inputs: list[tuple[Any, Any, Any]] = [(tiff_path, artifact_id, primary_kind)]
        if kind == "dsm":
            # Sealed submissions require exactly one ortho companion.
            from test_external_native_window import _write_ortho as _write_companion

            companion_epoch2 = self.root / "companion-epoch2.tif"
            _write_companion(companion_epoch2)
            epoch_inputs.append((companion_epoch2, "ortho-epoch2", "ortho"))
        declarations = tuple(
            _Declaration(
                artifact_id=item_artifact_id,
                kind=_ArtifactKind(item_kind),
                file_name=path.name,
                format="GeoTIFF",
                content_type="application/octet-stream",
                declared_sha256=_hashlib.sha256(path.read_bytes()).hexdigest(),
                declared_size_bytes=path.stat().st_size,
            )
            for path, item_artifact_id, item_kind in epoch_inputs
        )
        by_id = {item.artifact_id: item for item in declarations}
        source_bytes = tiff_path.read_bytes()
        order = graph.work_orders.create_work_order(
            organization_id=graph.principal.organization_id,
            site_id="site-1",
            name="export-epoch2",
            work_area_ids=[self.area_id],
            schedule_id=None,
            actor="operator-1",
            now=self._now(),
        )
        submission = (
            _submission()
            .model_copy(
                update={
                    "submission_id": "submission-epoch2",
                    "observation_epoch_id": _epoch_id(order),
                    "artifacts": declarations,
                    "submission_digest": None,
                }
            )
            .sealed()
        )
        registered = graph.reconstruction.register(
            submission, work_order=order, registered_by="operator-1", now=self._now()
        )
        assert registered.revision is not None, registered
        storage = _Storage()
        assert {item for item, _ in registered.revision.bindings} == set(by_id)
        for bound_artifact_id, key in registered.revision.bindings:
            bound = by_id[bound_artifact_id]
            storage.objects[key] = _Observation(
                object_key=key,
                exists=True,
                sha256="sha256:" + bound.declared_sha256,
                size_bytes=bound.declared_size_bytes,
                content_type=bound.content_type,
            )
        sealed = graph.reconstruction.seal(
            order.work_order_id,
            submission.submission_id,
            1,
            organization_id=graph.principal.organization_id,
            site_id="site-1",
            storage=storage,
            now=self._now(),
        )
        assert sealed.verdict == _Verdict.SEALED, sealed
        assert sealed.revision is not None and sealed.revision.manifest is not None
        manifest_digest = sealed.revision.manifest.manifest_digest
        assert submission.submission_digest is not None and manifest_digest is not None
        subject = _Subject(
            organization_id=graph.principal.organization_id,
            site_id="site-1",
            work_order_id=order.work_order_id,
            submission_id=submission.submission_id,
            revision=1,
            submission_digest=submission.submission_digest,
            manifest_digest=manifest_digest,
        )
        issued = None
        if True:
            from datetime import timedelta as _td

            from ksi_core.domains.external.ingress.external_validation_policy import (
                PolicyAuthorityRecord as _AuthorityRecord,
            )
            from ksi_core.domains.external.ingress.external_validation_policy import (
                authorized_policy_body_digest as _body_digest,
            )

            entries = list(
                graph.inspection_policies._entries_by_identity.values()  # noqa: SLF001
            )
            policy1 = next(entry.policy for entry in entries if entry.policy.version == 1)
            stub2 = policy1.model_copy(update={"version": 2})
            record2 = _AuthorityRecord(
                policy_id=stub2.policy_id,
                policy_version=2,
                authorized_policy_body_digest=_body_digest(stub2),
                permitted_subjects=(subject,),
                permitted_uses=("INSPECTION", "DISPLAY"),
                authorized_actor_ids=("authority",),
                active_from=self._now() - _td(minutes=1),
                active_until=self._now() + _td(minutes=1),
                synthetic_test_only=True,
            ).sealed()
            graph.inspection_authority._records[record2.digest] = record2  # noqa: SLF001
            policy2 = stub2.model_copy(
                update={"authority_record_digest": record2.digest, "policy_digest": None}
            ).sealed()
            receipt2 = graph.inspection_policies.admit(policy2, actor="authority", now=self._now())
            assert receipt2.status.value in ("ADMITTED", "IDEMPOTENT"), receipt2
            issued = graph.inspections.issue_after_seal(subject, now=self._now())
        assert issued is not None and issued.request is not None
        fence = _Fence(_WORKER, _ACQ_B, 0)
        claimed = graph.inspections.claim(issued.request.request_id, fence, now=self._now())
        assert claimed.fence is not None
        stored = claimed.fence
        env = _envelope(
            max_memory_bytes=1_073_741_824,
            max_workspace_bytes=6_000_000,
            max_retry_attempts=3,
            max_tenant_concurrency=2,
            max_queue_depth=8,
        )
        outcomes = tuple(
            _inspect(
                path,
                artifact_id=item_artifact_id,
                observed_sha256="sha256:" + by_id[item_artifact_id].declared_sha256,
                artifact_kind=_ArtifactKind(item_kind),
                envelope=env,
            )
            for path, item_artifact_id, item_kind in epoch_inputs
        )
        assert all(item.outcome.value == "MEASURED" for item in outcomes), outcomes
        primary_outcome = next(item for item in outcomes if item.artifact_id == artifact_id)
        assert primary_outcome.measurements is not None
        base = self.graph.accepted_report
        payload = base.measurement_payload.model_copy(
            update={
                "subject_digest": subject.canonical_digest(),
                "sealed_manifest_digest": subject.manifest_digest,
                "inspection_policy_digest": policy2.policy_digest,
                "outcomes": outcomes,
                "artifact_bindings": tuple(
                    _Binding(
                        artifact_id=item.artifact_id,
                        observed_sha256=item.observed_sha256,
                    )
                    for item in outcomes
                ),
            }
        )
        candidate = base.model_copy(
            update={
                "report_id": "inspection-report-task5-epoch2",
                "request_id": issued.request.request_id,
                "subject": subject,
                "subject_digest": subject.canonical_digest(),
                "sealed_manifest_digest": subject.manifest_digest,
                "inspection_policy_digest": policy2.policy_digest,
                "measurement_payload": payload,
                "measurement_payload_digest": None,
                "worker_instance_id": stored.worker_instance_id,
                "lease_acquisition_id": stored.lease_acquisition_id,
                "lease_generation": stored.lease_generation,
                "report_digest": None,
            }
        ).sealed()
        result = graph.inspections.record_report(
            issued.request.request_id, stored, candidate, now=self._now()
        )
        assert result.verdict == "REPORTED", result
        items = _Catalog(
            reconstruction=graph.reconstruction,
            work_orders=graph.work_orders,
            sites=graph.sites,
            work_areas=graph.work_areas,
            inspections=graph.inspections,
        ).items("site-1", self.area_id, graph.principal)
        asset_ref = next(item.asset_ref for item in items if item.artifact_id == artifact_id)
        grant = self.replace_grant(
            grant_id="local-ai-grant-epoch2",
            asset_ref=asset_ref,
            observed_crs_digest=primary_outcome.measurements.observed_crs_digest,
        )
        self.epoch_bytes[asset_ref] = source_bytes
        self.assets["epoch2"] = {
            "asset_ref": asset_ref,
            "observed_crs_digest": primary_outcome.measurements.observed_crs_digest,
            "measurements": primary_outcome.measurements,
            "artifact_id": artifact_id,
            "source_path": tiff_path,
            "epoch_id": _epoch_id(order),
        }
        self.assets["primary"]["epoch_id"] = self._first_epoch_id()
        return {"asset_ref": asset_ref, "grant": grant}

    def _first_epoch_id(self) -> str:
        from ksi_core.domains.observations.epoch_identity import observation_epoch_id as _epoch_id

        return _epoch_id(self.graph.order)


class _Task5Suppress:
    def __enter__(self) -> _Task5Suppress:
        return self

    def __exit__(self, *args: Any) -> bool:
        return True


_suppress = _Task5Suppress


@_task5_contextmanager
def task5_ai_lane(
    root: Path,
    *,
    kind: str = "dsm",
    mutation: str | None = None,
    stream_chunk_bytes: int = 512,
) -> _Task5Iterator[Task5AiCoreLane]:
    """Own exactly one AI lane: object server, genuine Core lane, loopback Core HTTP."""
    import base64 as _base64
    import hashlib as _hashlib
    import threading as _threading
    from http.server import BaseHTTPRequestHandler as _Handler
    from http.server import ThreadingHTTPServer as _Server

    from ksi_core.domains.external.delivery.storage_types import (
        SpatialDataObjectObservation as _ObjectObservation,
    )

    holder: dict[str, Any] = {}

    class Handler(_Handler):
        def log_message(self, *_: Any) -> None:
            pass

        def do_GET(self) -> None:
            lane = holder["lane"]
            payload = lane.provider.source
            if lane.mutation == "source":
                payload = b"x" * len(payload)
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_PUT(self) -> None:
            lane = holder["lane"]
            payload = self.rfile.read(int(self.headers["Content-Length"]))
            expected = lane.provider.expected
            assert expected is not None
            assert "Authorization" not in self.headers
            assert (
                len(payload) == expected.size_bytes
                and "sha256:" + _hashlib.sha256(payload).hexdigest() == expected.sha256
            )
            assert (
                self.headers["x-amz-checksum-sha256"]
                == _base64.b64encode(bytes.fromhex(expected.sha256[7:])).decode()
            )
            lane.provider.payload = payload
            lane.provider.observation = _ObjectObservation(
                expected.object_key, "local-version-1", len(payload), expected.sha256, "image/tiff"
            )
            lane.provider.uploads += 1
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = _Server(("127.0.0.1", 0), Handler)
    thread = _threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    lane: Task5AiCoreLane | None = None
    try:
        lane = Task5AiCoreLane(
            root,
            kind=kind,
            mutation=mutation,
            stream_chunk_bytes=stream_chunk_bytes,
            object_origin=f"http://127.0.0.1:{server.server_port}",
            core_port=task5_free_port(),
        )
        holder["lane"] = lane
        yield lane
    finally:
        if lane is not None:
            lane.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


_ACK_HEADER_BYTES = b"x-ksi-spatial-data-ai-egress"


class _StripAck:
    """Test-owned transport wrapper: strips the genuine Core ack, keeps the body.

    Only the ``http.response.start`` ack header is removed from the SAME live
    Core app; status and body bytes pass through untouched. This proves the
    official SDK refuses unacknowledged success instead of trusting a
    forged-looking body. Never a mocked success body.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        app = self._app

        async def stripping(message: Any) -> None:
            assert isinstance(message, dict)
            if message.get("type") == "http.response.start":
                message = dict(message)
                message["headers"] = [
                    (key, value)
                    for key, value in message["headers"]
                    if bytes(key).lower() != _ACK_HEADER_BYTES
                ]
            await send(message)

        await app(scope, receive, stripping)


@_task5_contextmanager
def serve_without_ack(lane: Task5AiCoreLane) -> _Task5Iterator[Task5AiCoreLane]:
    """Serve the SAME live Core app with the genuine ack stripped (test-only).

    Restarts the owned loopback listener around the ack-stripping wrapper on
    a fresh loopback port, then restores a direct listener afterwards. The
    SDK config must be recreated after entering (new origin); the
    pre-existing HTTP consumer keeps its original base URL and is not used
    while stripping. The lane is closed by its own ``task5_ai_lane`` owner.
    """
    assert lane.core_http is not None
    lane.core_http.stop()
    lane.core_http = Task5CoreHttp(_StripAck(lane.app), task5_free_port()).start()
    try:
        yield lane
    finally:
        assert lane.core_http is not None
        lane.core_http.stop()
        lane.core_http = Task5CoreHttp(lane.app, task5_free_port()).start()
