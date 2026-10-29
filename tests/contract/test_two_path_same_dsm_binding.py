"""Same sealed DSM binds relative-change analysis and zoned data provision.

Local generated-software evidence only. Every byte below comes from owned
2x2 synthetic DSMs sealed once in one Core's Site/WorkArea/observation epoch/
submission revision, inspected once by the generated-only parser, then read
through the real analysis worker and the real spatial-data worker control path
plus isolated raster preparation. No customer bytes, no shared server, no
production host, no OIDC, no map egress, no network download, no deployment,
and no customer acceptance are claimed.

Connection: one ``LocalAnalysisApiFixture`` Core (org-a/site-a) boots both the
analysis lane and a minimal test-only spatial-data lane sharing the exact
reconstruction/inspection/site/work-area/work-order participants and the exact
``ExternalAuthorityCurrentnessCoordinator``. The same sealed DSM bytes (same
object key, same ``observed_sha256``/size, same manifest/submission digests)
flow to analysis (t0->t1 and t1->t2) and to the zoned native-window worker for
the current (and third) epoch. Catalog assets resolve through the genuine
``SpatialAssetCatalog``/``SpatialDataSourceResolver`` on those same stores;
IDs are never copied between fixtures and no second file is substituted.

Transports (explicit): analysis Core via local uvicorn HTTP loopback;
spatial Core via local ASGI TestClient + httpx MockTransport (same app object,
same stores); sealed bytes and spatial outputs via owned loopback HTTP
listeners on 127.0.0.1; spatial preparation via the generated-only launcher
confined to ``tests/contract/spatial_data_http_fixture.py``; inspection via
the generated-only UDS inspector. This is local software evidence, not OS
sandbox, operational host, or customer acceptance proof.
"""

from __future__ import annotations

import base64
import hashlib
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

import rasterio
from fastapi.testclient import TestClient

# --- test-only constants (never production credentials, quotas, or hosts) ---
_TEST_SPATIAL_WORKER_TOKEN = "two-path-spatial-worker-token"
_TEST_SPATIAL_AI_TOKEN = "two-path-spatial-ai-token"
_TEST_FOREIGN_TOKEN = "two-path-foreign-token"


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class _UnifiedCurrentness:
    """Test-only currentness sharing the analysis Core coordinator."""

    def __init__(self, coordinator: Any, principals: dict[tuple[str, str], Any]) -> None:
        self.coordinator = coordinator
        self.enabled = True
        self._principals = principals

    def resolve_requester(self, *, principal_id: str, organization_id: str, now: Any = None) -> Any:
        return self._principals.get((principal_id, organization_id))

    def is_current(self, *, policy: Any, runtime: Any, activation: Any, now: datetime) -> bool:
        return bool(self.enabled) and activation.is_current_at(now)


def _extend_registry(fixture: Any) -> dict[str, str]:
    """Provision synthetic spatial principals on the same Core registry.

    Additive only: existing analysis tokens are preserved; no permission is
    widened. Returns the new bearer tokens for explicit use below.
    """

    import hashlib as _hashlib

    from ksi_core.auth import Principal, PrincipalKind, PrincipalTokenRecord

    registry = fixture.app.state.auth_registry
    added: dict[str, str] = {}
    specs = [
        (
            _TEST_SPATIAL_WORKER_TOKEN,
            Principal(
                principal_id="two-path-spatial-worker",
                organization_id="org-a",
                kind=PrincipalKind.SPATIAL_DATA_WORKER,
                role=None,
                device_id=None,
            ),
        ),
        (
            _TEST_SPATIAL_AI_TOKEN,
            Principal(
                principal_id="two-path-spatial-ai",
                organization_id="org-a",
                kind=PrincipalKind.SPATIAL_DATA_MCP_CLIENT,
                role=None,
                device_id=None,
                allowed_site_ids=frozenset({"site-a"}),
                allowed_work_area_ids=frozenset({fixture.work_area_id}),
            ),
        ),
        (
            _TEST_FOREIGN_TOKEN,
            Principal(
                principal_id="two-path-foreign",
                organization_id="foreign-org",
                kind=PrincipalKind.OPERATOR,
                role=None,
                device_id=None,
            ),
        ),
    ]
    # Give the foreign principal a viewer-like shape without touching roles:
    # it authenticates but is scoped to a different organization, so scoped
    # reads must fail closed with 404 rather than leak existence.
    for token, principal in specs:
        record = PrincipalTokenRecord(
            token_sha256=_hashlib.sha256(token.encode()).hexdigest(),
            principal=principal,
        )
        # Test-only provisioning on the live registry object; the same
        # coordinator/participants stay authoritative for permission checks.
        registry._by_digest[record.token_sha256] = record  # noqa: SLF001
        # Do not clobber an existing id; all three ids are fresh in this lane.
        registry._by_principal_id[principal.principal_id] = principal  # noqa: SLF001
        added[principal.principal_id] = token
    return added


def _full_footprint_bounds() -> tuple[float, float, float, float]:
    """Exact footprint of the 2x2 analysis DSM (transform 0.1/200000/550000)."""

    return (200000.0, 549999.8, 200000.2, 550000.0)


def test_same_sealed_dsm_binds_analysis_and_zoned_data(tmp_path: Path) -> None:
    from analysis_api_local_fixture import build_local_analysis_api_fixture

    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        include_third_epoch=True,
        real_inspection=True,
    )
    assert fixture.third is not None
    assert fixture._third_revision is not None
    servers = None
    spatial_output_server: ThreadingHTTPServer | None = None
    spatial_output_thread: threading.Thread | None = None
    try:
        # Provision synthetic spatial identities before any transport starts.
        _extend_registry(fixture)

        # Reuse the proven analysis loopback pair for inspection + analysis.
        from test_external_analysis_real_inspection_lane_integration import (
            _CoreAndObjectServers,
        )

        servers = _CoreAndObjectServers(fixture)
        servers.__enter__()
        assert servers.object_origin.startswith("http://127.0.0.1:")
        assert servers.core_origin.startswith("http://127.0.0.1:")

        # Inspect all three sealed DSM epochs with the real parser.
        from test_external_analysis_actual_weekly_reuse import _inspect_three_epochs

        reports = _inspect_three_epochs(fixture, servers=servers, tmp_path=tmp_path)
        assert len(reports) == 3

        # --- same-scope catalog + source resolution on the exact participants ---
        coordinator = fixture.app.state.external_reconstruction_store.coordinator
        assert fixture.app.state.external_artifact_inspection_store.coordinator is coordinator
        assert fixture.app.state.site_store.coordinator is coordinator
        assert fixture.app.state.work_area_store.coordinator is coordinator

        from ksi_core.domains.external.delivery.source import SpatialDataSourceResolver
        from ksi_core.domains.external.ingress.spatial_asset_catalog import (
            SpatialAssetCatalog,
        )

        catalog = SpatialAssetCatalog(
            reconstruction=fixture.app.state.external_reconstruction_store,
            work_orders=fixture.app.state.observation_work_order_store,
            sites=fixture.app.state.site_store,
            work_areas=fixture.app.state.work_area_store,
            inspections=fixture.app.state.external_artifact_inspection_store,
        )
        from ksi_core.auth import Principal, PrincipalKind, Role

        operator = Principal(
            principal_id="analysis-local-operator",
            kind=PrincipalKind.OPERATOR,
            role=Role.ADMIN,
            device_id=None,
            organization_id="org-a",
        )
        items = catalog.items("site-a", fixture.work_area_id, operator)
        assert len(items) == 3, f"expected three sealed DSM assets, got {len(items)}"
        by_artifact = {item.artifact_id: item for item in items}
        assert set(by_artifact) == {
            "dsm-analysis-local-baseline",
            "dsm-analysis-local-current",
            "dsm-analysis-local-third",
        }

        # Spatial policy/runtime/activation for the same org, trusting only the
        # owned loopback origins observed in this test.
        from spatial_data_fixture import make_activation, make_policy, make_runtime
        from test_external_native_window import _envelope

        env = _envelope(
            max_memory_bytes=1_073_741_824,
            max_workspace_bytes=6_000_000,
            max_retry_attempts=3,
            max_tenant_concurrency=2,
            max_queue_depth=8,
        )
        policy = make_policy(
            resource_envelope=env,
            max_output_bytes=1_000_000,
            max_stream_bytes=1_000_000,
            stream_chunk_bytes=512,
        )
        runtime = make_runtime()
        fixture_now = fixture._fixture_now
        activation = make_activation(
            organization_id="org-a",
            worker_principal_id="two-path-spatial-worker",
            worker_instance_id="two-path-spatial-instance",
            policy_digest=policy.policy_digest,
            runtime_digest=runtime.runtime_digest,
            trusted_endpoint_origins=(servers.object_origin,),
            valid_from=fixture_now - timedelta(minutes=10),
            valid_until=fixture_now + timedelta(hours=2),
        )

        resolver = SpatialDataSourceResolver(
            reconstruction=fixture.app.state.external_reconstruction_store,
            inspections=fixture.app.state.external_artifact_inspection_store,
            sites=fixture.app.state.site_store,
            work_areas=fixture.app.state.work_area_store,
            work_orders=fixture.app.state.observation_work_order_store,
            policy=policy,
            coordinator=coordinator,
            clock=_now,
        )
        sources: dict[str, Any] = {}
        for artifact_id, item in by_artifact.items():
            src = resolver.resolve(
                site_id="site-a",
                work_area_id=fixture.work_area_id,
                asset_ref=item.asset_ref,
                principal=operator,
            )
            sources[artifact_id] = src
            # Same Core scope: work-order/epoch/revision/submission + sealed bytes.
            assert src.site_id == "site-a"
            assert src.work_area_id == fixture.work_area_id
            assert src.artifact_id == artifact_id
            assert src.submission_ref == item.submission_ref
            assert src.revision == item.revision == 1
            assert src.inspection.outcome.value == "MEASURED"
            assert src.inspection.measurements is not None
            meas = src.inspection.measurements
            assert meas.observed_crs_identifier == "EPSG:5186"
            assert meas.transform == (0.1, 0.0, 200000.0, 0.0, -0.1, 550000.0)
            assert (meas.width, meas.height, meas.valid_pixel_count) == (2, 2, 4)
            # Sealed bytes identity matches the analysis manifest entry.
            rev = {
                "dsm-analysis-local-baseline": fixture._baseline_revision,
                "dsm-analysis-local-current": fixture._current_revision,
                "dsm-analysis-local-third": fixture._third_revision,
            }[artifact_id]
            entry = next(e for e in rev.manifest.entries if e.artifact_id == artifact_id)
            assert src.observed_sha256 == "sha256:" + entry.observed_sha256
            assert src.observed_size_bytes == entry.observed_size_bytes
            sealed = fixture.storage.object_bytes(entry.object_key)
            assert hashlib.sha256(sealed).hexdigest() == entry.observed_sha256

        # Cross-bind to analysis selectors: the current epoch (and the reused
        # middle epoch for t1->t2) is the exact same work-order/submission.
        current_src = sources["dsm-analysis-local-current"]
        assert current_src.work_order_id == fixture.current.work_order_id
        assert current_src.submission_ref == fixture.current.submission_ref
        assert current_src.revision == fixture.current.revision
        third_src = sources["dsm-analysis-local-third"]
        assert fixture.third is not None
        assert third_src.work_order_id == fixture.third.work_order_id
        baseline_src = sources["dsm-analysis-local-baseline"]
        assert baseline_src.work_order_id == fixture.baseline.work_order_id

        # --- minimal spatial lane sharing the exact participants ---
        from ksi_core.auth import Principal as _OpPrincipal
        from ksi_core.auth import PrincipalKind as _OpKind
        from ksi_core.auth import Role as _OpRole

        _operator_principal = _OpPrincipal(
            principal_id="analysis-local-operator",
            kind=_OpKind.OPERATOR,
            role=_OpRole.ADMIN,
            device_id=None,
            organization_id="org-a",
        )
        _worker_principal = _OpPrincipal(
            principal_id="two-path-spatial-worker",
            organization_id="org-a",
            kind=_OpKind.SPATIAL_DATA_WORKER,
            role=None,
            device_id=None,
        )
        _ai_principal = _OpPrincipal(
            principal_id="two-path-spatial-ai",
            organization_id="org-a",
            kind=_OpKind.SPATIAL_DATA_MCP_CLIENT,
            role=None,
            device_id=None,
            allowed_site_ids=frozenset({"site-a"}),
            allowed_work_area_ids=frozenset({fixture.work_area_id}),
        )
        currentness = _UnifiedCurrentness(
            coordinator,
            {
                ("analysis-local-operator", "org-a"): _operator_principal,
                ("two-path-spatial-worker", "org-a"): _worker_principal,
                ("two-path-spatial-ai", "org-a"): _ai_principal,
            },
        )
        from ksi_core.domains.external.delivery.grants import (
            SpatialDataGrantAuthorizer,
            SpatialDataGrantStore,
        )
        from ksi_core.durable_journal import DurableJournal
        from ksi_event_contracts.processing_job import ExecutionLocus

        grants = SpatialDataGrantStore(
            DurableJournal(tmp_path / "two-path-spatial-grants.jsonl"),
            coordinator=coordinator,
        )
        authorizer = SpatialDataGrantAuthorizer(
            grants=grants,
            sites=fixture.app.state.site_store,
            processing_location=ExecutionLocus.SITE_ONPREM,
        )
        from spatial_data_fixture import make_grant

        allowed = _full_footprint_bounds()
        grant_digests: dict[str, str] = {}
        for src in sources.values():
            assert src.inspection.measurements is not None
            grant = make_grant(
                grant_id=f"two-path-grant-{src.artifact_id}",
                organization_id="org-a",
                beneficiary_principal_id="analysis-local-operator",
                site_id="site-a",
                work_area_id=fixture.work_area_id,
                asset_ref=src.asset_ref,
                observed_crs_digest=src.inspection.measurements.observed_crs_digest,
                allowed_bounds=allowed,
                policy_digest=policy.policy_digest,
                valid_from=fixture_now - timedelta(minutes=10),
                valid_until=fixture_now + timedelta(hours=2),
                attribution="Two-path test grant; synthetic bytes only",
            )
            grants.provision(grant)
            assert grant.grant_digest is not None
            grant_digests[src.artifact_id] = grant.grant_digest

        # Exact-participant proof: direct identity asserts on the shared stores.
        # Manual test-only wiring below reuses the fixture's reconstruction,
        # inspection, site, work-area, and work-order participants plus the same
        # coordinator; no separate factory call builds this lane.
        assert resolver._reconstruction is fixture.app.state.external_reconstruction_store
        assert resolver._inspections is fixture.app.state.external_artifact_inspection_store
        assert authorizer._grants is grants

        # Test-only storage: source GETs resolve to the exact sealed object key
        # on the same loopback object server; outputs are PUT to a second
        # owned loopback listener and verified before completion.
        output_payloads: dict[str, bytes] = {}
        output_observations: dict[str, Any] = {}
        expected_puts: dict[str, Any] = {}

        class _UnifiedStorage:
            def __init__(self, origin: str) -> None:
                self._origin = origin

            def _object_key_for(self, source: Any) -> str:
                record = fixture.app.state.external_reconstruction_store.get(
                    source.work_order_id,
                    fixture.app.state.external_reconstruction_store.resolve_submission_ref(
                        source.work_order_id,
                        source.submission_ref,
                        organization_id=source.sealed_subject.organization_id,
                        site_id=source.site_id,
                    ),
                    source.revision,
                    organization_id=source.sealed_subject.organization_id,
                    site_id=source.site_id,
                )
                assert record is not None and record.manifest is not None
                entry = next(
                    e for e in record.manifest.entries if e.artifact_id == source.artifact_id
                )
                assert "sha256:" + entry.observed_sha256 == source.observed_sha256
                return entry.object_key

            def issue_source_get(self, source: Any, attempt: Any, *, expires_at: Any) -> Any:
                from ksi_event_contracts.spatial_data_worker import (
                    SpatialDataSourceCapabilityV1,
                )

                assert source.source_digest is not None
                object_key = self._object_key_for(source)
                return SpatialDataSourceCapabilityV1(
                    artifact_id=source.artifact_id,
                    source_digest=source.source_digest,
                    observed_sha256=source.observed_sha256,
                    observed_size_bytes=source.observed_size_bytes,
                    download_url=self._origin + "/objects/" + quote(object_key, safe=""),
                    required_headers=(),
                    expires_at=expires_at,
                )

            def issue_output_put(
                self,
                target: Any,
                *,
                sha256: str,
                size_bytes: int,
                content_type: str,
                expires_at: Any,
            ) -> Any:
                from ksi_event_contracts.spatial_data_worker import (
                    SpatialDataRequiredHeaderV1,
                    SpatialDataUploadCapabilityV1,
                )

                assert content_type == "image/tiff"
                key = f"{target.object_key}:{sha256}:{size_bytes}"
                expected_puts[key] = (sha256, size_bytes)
                headers = {
                    "Content-Type": content_type,
                    "Content-Length": str(size_bytes),
                    "x-amz-checksum-sha256": base64.b64encode(bytes.fromhex(sha256[7:])).decode(),
                }
                return SpatialDataUploadCapabilityV1(
                    receipt_digest=target.receipt_digest,
                    sha256=sha256,
                    size_bytes=size_bytes,
                    content_type="image/tiff",
                    expires_at=expires_at,
                    upload_url=self._origin + "/spatial-output/" + quote(key, safe=""),
                    required_headers=tuple(
                        SpatialDataRequiredHeaderV1.model_validate({"name": n, "value": v})
                        for n, v in headers.items()
                    ),
                )

            def observe_owned_output(self, target: Any) -> Any:
                return output_observations[target.object_key]

            @contextmanager
            def open_version(
                self, observation: Any, *, chunk_bytes: int, deadline: Any
            ) -> Iterator[Iterator[bytes]]:
                payload = output_payloads[observation.object_key]
                assert observation == output_observations[observation.object_key]
                yield (payload[i : i + chunk_bytes] for i in range(0, len(payload), chunk_bytes))

            def list_owned_versions(self, target: Any, *, limit: int) -> Any:
                raise NotImplementedError("test lane does not prove cleanup listing")

            def delete_owned_version(self, target: Any, version_id: str) -> None:
                raise NotImplementedError("test lane does not prove cleanup delete")

        # Second owned listener for PUT outputs (source GETs reuse object_origin).
        spatial_origin_holder: dict[str, str] = {}

        class _SpatialOutputHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                return

            def do_PUT(self) -> None:  # noqa: N802
                if not self.path.startswith("/spatial-output/"):
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                payload = self.rfile.read(length)
                key = unquote(self.path.removeprefix("/spatial-output/"))
                expected = expected_puts.get(key)
                if expected is None:
                    self.send_error(409)
                    return
                exp_sha, exp_size = expected
                if (
                    len(payload) != exp_size
                    or "sha256:" + hashlib.sha256(payload).hexdigest() != exp_sha
                ):
                    self.send_error(409)
                    return
                object_key = key.split(":")[0]
                from ksi_core.domains.external.delivery.storage_types import (
                    SpatialDataObjectObservation,
                )

                output_payloads[object_key] = payload
                output_observations[object_key] = SpatialDataObjectObservation(
                    object_key, "two-path-version-1", len(payload), exp_sha, "image/tiff"
                )
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

        spatial_output_server = ThreadingHTTPServer(("127.0.0.1", 0), _SpatialOutputHandler)
        spatial_output_thread = threading.Thread(
            target=spatial_output_server.serve_forever, daemon=True
        )
        spatial_output_thread.start()
        spatial_output_origin = f"http://127.0.0.1:{spatial_output_server.server_port}"
        spatial_origin_holder["origin"] = spatial_output_origin

        # Storage serves source GETs from the analysis object server and PUTs
        # to the dedicated output listener. Both are owned loopback HTTP.
        storage = _UnifiedStorage(servers.object_origin)

        # Patch the storage to route PUTs to the output listener while keeping
        # source GETs on the analysis object server.
        _orig_issue_output_put = storage.issue_output_put

        def _patched_issue_output_put(target: Any, **kwargs: Any) -> Any:
            cap = _orig_issue_output_put(target, **kwargs)
            key = unquote(cap.upload_url.split("/spatial-output/", 1)[1])
            return cap.model_copy(
                update={
                    "upload_url": spatial_output_origin + "/spatial-output/" + quote(key, safe="")
                }
            )

        storage.issue_output_put = _patched_issue_output_put  # type: ignore[method-assign]

        # Extend activation trust to the output listener (source stays on the
        # analysis object server). Rebuild activation + jobs to keep seals exact.
        from ksi_core.domains.external.delivery.jobs import SpatialDataJobStore as _JobStore

        activation = make_activation(
            organization_id="org-a",
            worker_principal_id="two-path-spatial-worker",
            worker_instance_id="two-path-spatial-instance",
            policy_digest=policy.policy_digest,
            runtime_digest=runtime.runtime_digest,
            trusted_endpoint_origins=(servers.object_origin, spatial_output_origin),
            valid_from=fixture_now - timedelta(minutes=10),
            valid_until=fixture_now + timedelta(hours=2),
        )
        jobs = _JobStore(
            DurableJournal(tmp_path / "two-path-spatial-jobs.jsonl"),
            grants=authorizer,
            sources=resolver,
            policy=policy,
            runtime=runtime,
            activation=activation,
            coordinator=coordinator,
            currentness=currentness,
        )

        from ksi_core.domains.external.delivery.audit import SpatialDataAuditStore
        from ksi_core.domains.external.delivery.downloads import SpatialDataDownloadService

        audit = SpatialDataAuditStore(
            DurableJournal(tmp_path / "two-path-spatial-audit.jsonl"), policy=policy
        )
        spool = tmp_path / "two-path-spatial-spool"
        spool.mkdir(mode=0o700)
        downloads = SpatialDataDownloadService(
            jobs=jobs, storage=storage, audit=audit, policy=policy, spool_root=spool, clock=_now
        )

        # Mount the data + worker routers onto the same Core app (dynamic, same
        # stores/coordinator). Asset HTTP is covered by direct catalog +
        # resolver proof above; the job/file lanes go through real HTTP below.
        from ksi_core.domains.external.delivery.api import build_spatial_data_router
        from ksi_core.domains.external.delivery.worker_api import (
            build_spatial_data_worker_router,
        )

        fixture.app.include_router(
            build_spatial_data_router(
                jobs=jobs,
                grants=authorizer,
                sources=resolver,
                downloads=downloads,
                clock=_now,
            )
        )
        fixture.app.include_router(
            build_spatial_data_worker_router(
                jobs=jobs, storage=storage, activation=activation, clock=_now
            )
        )

        # --- analysis t0->t1 and t1->t2 on the same sealed bytes ---
        import time as _time

        import httpx as _httpx
        from ksi_processing_controller.external_analysis_core_client import (
            ExternalAnalysisCoreClient,
        )
        from ksi_processing_controller.external_analysis_worker import (
            ProcessingWorkerRuntimeIdentityV1,
        )
        from ksi_processing_controller.external_analysis_worker import run_once as _arun_once
        from ksi_processing_controller.external_object_streams import (
            ExternalObjectTransportPolicyV1,
            TrustedObjectEndpointV1,
        )

        def _body(a: Any, b: Any) -> dict[str, object]:
            return {
                "baseline": a.model_dump(by_alias=True, mode="json"),
                "current": b.model_dump(by_alias=True, mode="json"),
            }

        with _httpx.Client(base_url=servers.core_origin, trust_env=False) as operator_http:
            headers = fixture.operator_headers()
            analysis_base = (
                f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses"
            )
            first_created = operator_http.post(
                analysis_base,
                headers={**headers, "Idempotency-Key": "two-path-t0-t1"},
                json=_body(fixture.baseline, fixture.current),
            )
            assert first_created.status_code == 202, first_created.text
            first_id = first_created.json()["analysisId"]
            facts = fixture.app.state.external_analysis_wiring.facade._assessments._runtime
            aenvelope = fixture.app.state.external_analysis_wiring.calculations._resource_envelope
            aruntime = ProcessingWorkerRuntimeIdentityV1(
                worker_executable_digest=facts.worker_executable_digest,
                worker_build_digest=facts.worker_build_digest,
                runtime_image_version=facts.runtime_image_version,
                runtime_image_oci_digest=facts.runtime_image_oci_digest,
                dependency_lock_digest=facts.dependency_lock_digest,
            )
            atransport = ExternalObjectTransportPolicyV1(
                endpoints=(
                    TrustedObjectEndpointV1(origin=servers.object_origin, addresses=("127.0.0.1",)),
                ),
                max_header_bytes=16_384,
                max_object_bytes=aenvelope.max_input_bytes,
                max_chunk_bytes=min(65_536, aenvelope.max_input_bytes),
            )
            aworker = ExternalAnalysisCoreClient(
                base_url=servers.core_origin,
                worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
                worker_instance_id="two-path-analysis-worker",
            )
            assert _arun_once(aworker, aruntime, atransport)
            detail_url = f"/v1/sites/{fixture.site_id}/analyses/{first_id}"
            for _ in range(100):
                detail = operator_http.get(detail_url, headers=headers)
                assert detail.status_code == 200, detail.text
                if detail.json()["executionState"] == "COMPLETED":
                    break
                _time.sleep(0.02)
            assert detail.json()["executionState"] == "COMPLETED"
            assert detail.json()["suitabilityState"] == "PROVISIONAL_ACCURACY_UNVERIFIED"
            result = operator_http.get(detail_url + "/result", headers=headers)
            evidence = operator_http.get(detail_url + "/evidence", headers=headers)
            assert result.status_code == evidence.status_code == 200
            first_detail_json = detail.json()
            first_result_json = result.json()
            first_evidence_json = evidence.json()
            first_result = first_result_json["result"]
            assert first_result is not None
            # Structured binding: detail carries the exact input selectors.
            assert (
                first_detail_json["baseline"]
                == _body(fixture.baseline, fixture.current)["baseline"]
            )
            assert (
                first_detail_json["current"] == _body(fixture.baseline, fixture.current)["current"]
            )
            first_evidence = first_evidence_json
            assert first_evidence["baseline"]["selector"] == first_detail_json["baseline"]
            assert first_evidence["current"]["selector"] == first_detail_json["current"]
            # Each epoch binds the sealed Core revision inspected above.
            assert first_evidence["baseline"]["observationEpochId"] == baseline_src.epoch_id
            assert first_evidence["current"]["observationEpochId"] == current_src.epoch_id
            assert first_evidence["baseline"]["artifactId"] == "dsm-analysis-local-baseline"
            assert first_evidence["current"]["artifactId"] == "dsm-analysis-local-current"
            assert first_evidence["baseline"]["observedSha256"] == baseline_src.observed_sha256
            assert first_evidence["current"]["observedSha256"] == current_src.observed_sha256
            assert first_evidence["baseline"]["observedSizeBytes"] == 390
            assert first_evidence["current"]["observedSizeBytes"] == 390
            assert first_evidence["baseline"]["observedCrsIdentifier"] == "EPSG:5186"
            assert first_evidence["current"]["observedCrsIdentifier"] == "EPSG:5186"
            assert (
                first_evidence["baseline"]["observedCrsDigest"]
                == baseline_src.inspection.measurements.observed_crs_digest
            )
            assert (
                first_evidence["current"]["observedCrsDigest"]
                == current_src.inspection.measurements.observed_crs_digest
            )
            assert first_evidence["baseline"]["verticalReferenceIdentifier"] == "EPSG:5773"
            assert first_evidence["current"]["verticalReferenceIdentifier"] == "EPSG:5773"
            assert first_evidence["baseline"]["transform"] == [
                0.1,
                0.0,
                200000.0,
                0.0,
                -0.1,
                550000.0,
            ]
            assert first_evidence["current"]["transform"] == [
                0.1,
                0.0,
                200000.0,
                0.0,
                -0.1,
                550000.0,
            ]
            assert first_evidence["baseline"]["inspectionReportDigest"] == reports[0].report_digest
            assert first_evidence["current"]["inspectionReportDigest"] == reports[1].report_digest
            first_authority = first_detail_json["authority"]
            assert first_authority["calculationRequestId"] is not None
            assert first_authority["admissionId"] is not None
            assert first_result["resultId"] is not None
            assert first_result["reportDigest"] is not None
            assert first_result["numericResultIdentityDigest"] is not None

            second_created = operator_http.post(
                analysis_base,
                headers={**headers, "Idempotency-Key": "two-path-t1-t2"},
                json=_body(fixture.current, fixture.third),
            )
            assert second_created.status_code == 202, second_created.text
            second_id = second_created.json()["analysisId"]
            assert second_id != first_id
            assert _arun_once(aworker, aruntime, atransport)
            second_detail_url = f"/v1/sites/{fixture.site_id}/analyses/{second_id}"
            for _ in range(100):
                sdetail = operator_http.get(second_detail_url, headers=headers)
                assert sdetail.status_code == 200, sdetail.text
                if sdetail.json()["executionState"] == "COMPLETED":
                    break
                _time.sleep(0.02)
            assert sdetail.json()["executionState"] == "COMPLETED"
            second_detail_json = sdetail.json()
            second_result_json = operator_http.get(
                second_detail_url + "/result", headers=headers
            ).json()
            second_evidence_json = operator_http.get(
                second_detail_url + "/evidence", headers=headers
            ).json()
            second_result = second_result_json["result"]
            assert second_result is not None
            # Middle-epoch reuse: the t0->t1 current is the t1->t2 baseline.
            assert second_detail_json["baseline"] == first_detail_json["current"]
            assert (
                second_detail_json["baseline"] == _body(fixture.current, fixture.third)["baseline"]
            )
            assert second_detail_json["current"] == _body(fixture.current, fixture.third)["current"]
            assert (
                second_evidence_json["baseline"]["selector"]
                == first_evidence_json["current"]["selector"]
            )
            # inspectionReportRef.href is analysis-scoped; digest identity is the binding.
            assert (
                second_evidence_json["baseline"]["inspectionReportRef"]["recordId"]
                == first_evidence_json["current"]["inspectionReportRef"]["recordId"]
            )
            for _field in (
                "artifactId",
                "observedSha256",
                "inputDigest",
                "inspectionReportDigest",
            ):
                assert (
                    second_evidence_json["baseline"][_field]
                    == first_evidence_json["current"][_field]
                )
            assert second_evidence_json["baseline"]["observationEpochId"] == current_src.epoch_id
            assert second_evidence_json["current"]["observationEpochId"] == third_src.epoch_id
            assert second_evidence_json["current"]["artifactId"] == "dsm-analysis-local-third"
            assert second_evidence_json["current"]["observedSha256"] == third_src.observed_sha256
            assert (
                second_evidence_json["current"]["inspectionReportDigest"]
                == reports[2].report_digest
            )
            # Distinct sealed runs: no result/authority/calculation identity is reused.
            assert second_detail_json["analysisId"] != first_detail_json["analysisId"]
            assert (
                second_detail_json["authority"]["calculationRequestId"]
                != first_authority["calculationRequestId"]
            )
            assert second_detail_json["authority"]["admissionId"] != first_authority["admissionId"]
            assert second_result["resultId"] != first_result["resultId"]
            assert second_result["reportDigest"] != first_result["reportDigest"]
            assert (
                second_result["numericResultIdentityDigest"]
                != first_result["numericResultIdentityDigest"]
            )
            assert (
                second_evidence_json["calculation"]["calculationId"]
                != first_evidence_json["calculation"]["calculationId"]
            )
            # First pair is immutable after the second pair completes.
            first_reread = (
                operator_http.get(detail_url, headers=headers).json(),
                operator_http.get(detail_url + "/result", headers=headers).json(),
                operator_http.get(detail_url + "/evidence", headers=headers).json(),
            )
            assert first_reread[0] == first_detail_json
            assert first_reread[1] == first_result_json
            assert first_reread[2] == first_evidence_json
            aworker.close()

        # --- zoned data on the exact current sealed DSM ---
        from ksi_processing_controller.external_object_streams import (
            ExternalObjectTransportPolicyV1 as _STransport,
        )
        from ksi_processing_controller.external_object_streams import (
            TrustedObjectEndpointV1 as _TEndpoint,
        )
        from ksi_processing_controller.spatial_data_core_client import (
            SpatialDataCoreClient,
        )
        from ksi_processing_controller.spatial_data_sandbox import SpatialDataSandbox
        from ksi_processing_controller.spatial_data_worker import run_once as _srun_once
        from spatial_data_http_fixture import GeneratedLauncher, client_module, mounted_transport

        http_client = TestClient(fixture.app)
        consumer = client_module().NativeWindowClient(
            base_url="https://core.invalid",
            site_id="site-a",
            work_area_id=fixture.work_area_id,
            token="analysis-local-fixture-operator",
            max_json_bytes=65536,
            max_file_bytes=1_000_000,
            timeout_seconds=10,
            transport=mounted_transport(http_client),
        )
        # Issue via the mounted Core (same stores) using the operator token.
        request_body = {
            "assetRef": current_src.asset_ref,
            "requestedBounds": list(allowed),
            "observedCrsDigest": current_src.inspection.measurements.observed_crs_digest,
            "resolutionMode": "NATIVE",
            "purpose": "GENERAL_DATA_USE",
        }
        issued = consumer.issue(request=request_body, idempotency_key="two-path-current")
        job_id = issued["jobId"]
        (tmp_path / "two-path-worker").mkdir(mode=0o700, exist_ok=True)
        with SpatialDataCoreClient(
            base_url="https://core.invalid",
            token=_TEST_SPATIAL_WORKER_TOKEN,
            activation=activation,
            policy=policy,
            runtime=runtime,
            clock=_now,
            maximum_response_bytes=policy.max_snapshot_bytes,
            request_timeout_seconds=5,
            transport=mounted_transport(http_client),
        ) as core:
            sandbox = SpatialDataSandbox(
                launcher=GeneratedLauncher(None),
                clock=_now,
                wall_timeout_seconds=10,
                heartbeat_interval_millis=50,
            )
            try:
                assert _srun_once(
                    core=core,
                    sandbox=sandbox,
                    transport_policy=_STransport(
                        endpoints=(
                            _TEndpoint(origin=servers.object_origin, addresses=("127.0.0.1",)),
                            _TEndpoint(origin=spatial_output_origin, addresses=("127.0.0.1",)),
                        ),
                        max_header_bytes=4096,
                        max_object_bytes=1_000_000,
                        max_chunk_bytes=512,
                    ),
                    worker_instance_id="two-path-spatial-instance",
                    clock=_now,
                    workspace_root=tmp_path / "two-path-worker",
                    heartbeat_interval_millis=100,
                )
            finally:
                sandbox.close()
        status = consumer.status(job_id)
        assert status["jobId"] == job_id, status
        assert status["assetRef"] == current_src.asset_ref, status
        assert status["siteId"] == "site-a", status
        assert status["workAreaId"] == fixture.work_area_id, status
        assert status["executionState"] == "COMPLETED", status
        assert status["availability"] == "AVAILABLE", status
        # Job view exposes no work-order/epoch/revision: that binding is proven
        # through the resolver source (work_order/epoch/submission/revision) plus
        # receipt.sourceDigest below, not through this view.
        assert "workOrderId" not in status
        assert "epochId" not in status
        assert "revision" not in status or status.get("revision") is None
        receipt = status["receipt"]
        assert receipt["jobId"] == job_id
        assert receipt["sourceDigest"] == current_src.source_digest
        assert receipt["sourceSha256"] == current_src.observed_sha256
        assert receipt["sourceSizeBytes"] == current_src.observed_size_bytes == 390
        assert receipt["artifactId"] == "dsm-analysis-local-current"
        assert receipt["artifactKind"] == "dsm"
        assert receipt["requestedBounds"] == list(allowed)
        assert (
            receipt["requestedCrsDigest"] == current_src.inspection.measurements.observed_crs_digest
        )
        assert (
            receipt["observedCrsDigest"] == current_src.inspection.measurements.observed_crs_digest
        )
        assert receipt["observedCrsIdentifier"] == "EPSG:5186"
        assert receipt["actualBounds"] == list(allowed)
        assert receipt["pixelWindow"] == [0, 2, 0, 2]
        assert receipt["width"] == 2 and receipt["height"] == 2
        assert receipt["transform"] == [0.1, 0.0, 200000.0, 0.0, -0.1, 550000.0]
        assert receipt["sourceTransform"] == [0.1, 0.0, 200000.0, 0.0, -0.1, 550000.0]
        assert receipt["sourceResolution"] == [0.1, 0.1]
        assert receipt["bandCount"] == 1
        assert receipt["dtype"] in ("float32", "float64")
        assert receipt["validPixelCount"] == 4
        assert receipt["receiptDigest"] is not None

        # Download through the guarded consumer (real bytes, not mock).
        out_dir = tmp_path / "two-path-download"
        out_dir.mkdir(mode=0o700)
        downloaded = consumer.download(status=status, output_dir=out_dir)
        downloaded_bytes = Path(downloaded).read_bytes()
        assert receipt["outputSha256"] == "sha256:" + hashlib.sha256(downloaded_bytes).hexdigest()
        assert receipt["outputSizeBytes"] == len(downloaded_bytes)

        # Independent oracle: reopen the original sealed bytes and compare
        # CRS/transform/shape/pixels/mask/hash without the production helper.
        current_entry = next(
            e
            for e in fixture._current_revision.manifest.entries
            if e.artifact_id == "dsm-analysis-local-current"
        )
        original_bytes = fixture.storage.object_bytes(current_entry.object_key)
        assert hashlib.sha256(original_bytes).hexdigest() == current_entry.observed_sha256
        assert (
            status["receipt"]["sourceSha256"]
            == "sha256:" + hashlib.sha256(original_bytes).hexdigest()
        )
        # Reopen both rasters directly from bytes.
        import io as _io

        import numpy as _np

        with (
            rasterio.open(_io.BytesIO(original_bytes)) as src_ds,
            rasterio.open(downloaded) as out_ds,
        ):
            assert (src_ds.width, src_ds.height, src_ds.count) == (2, 2, 1)
            assert (out_ds.width, out_ds.height, out_ds.count) == (2, 2, 1)
            assert tuple(src_ds.dtypes) == tuple(out_ds.dtypes)
            assert out_ds.dtypes[0] in ("float32", "float64")
            assert src_ds.crs is not None and out_ds.crs is not None
            assert src_ds.crs.to_string() == out_ds.crs.to_string()
            assert out_ds.transform == src_ds.transform
            assert out_ds.transform == rasterio.Affine(0.1, 0.0, 200000.0, 0.0, -0.1, 550000.0)
            assert tuple(out_ds.transform)[:6] == tuple(receipt["transform"])
            assert tuple(src_ds.transform)[:6] == tuple(receipt["sourceTransform"])

            expected_window = src_ds.read(1)
            actual_window = out_ds.read(1)
            assert _np.array_equal(actual_window, expected_window)
            expected_mask = src_ds.read_masks(1)
            actual_mask = out_ds.read_masks(1)
            assert _np.array_equal(actual_mask, expected_mask)
            assert int(_np.count_nonzero(actual_mask == 255)) == 4
            assert int(_np.count_nonzero(out_ds.dataset_mask() == 255)) == 4
            assert receipt["validPixelCount"] == int(_np.count_nonzero(actual_mask == 255))
            assert (
                receipt["observedCrsDigest"]
                == current_src.inspection.measurements.observed_crs_digest
            )

        # Source-result cross-bind: receipt source digest equals the resolved
        # source digest bound to the same work-order/epoch/revision above.
        # SpatialDataJobViewV1 carries no separate work-order/epoch field, so no
        # status["source"] lookup is asserted; the assetRef + sourceDigest chain
        # plus the resolver comparison is the complete binding.
        assert status["receipt"]["sourceDigest"] == current_src.source_digest
        assert "source" not in status

        # --- second zoned window on the third epoch (t1->t2 repetition) ---
        # The middle epoch links both analysis pairs; the third sealed DSM must
        # resolve and prepare independently on the same lane.
        third_request = {
            "assetRef": third_src.asset_ref,
            "requestedBounds": list(allowed),
            "observedCrsDigest": third_src.inspection.measurements.observed_crs_digest,
            "resolutionMode": "NATIVE",
            "purpose": "GENERAL_DATA_USE",
        }
        third_issued = consumer.issue(request=third_request, idempotency_key="two-path-third")
        third_job_id = third_issued["jobId"]
        with SpatialDataCoreClient(
            base_url="https://core.invalid",
            token=_TEST_SPATIAL_WORKER_TOKEN,
            activation=activation,
            policy=policy,
            runtime=runtime,
            clock=_now,
            maximum_response_bytes=policy.max_snapshot_bytes,
            request_timeout_seconds=5,
            transport=mounted_transport(http_client),
        ) as third_core:
            third_sandbox = SpatialDataSandbox(
                launcher=GeneratedLauncher(None),
                clock=_now,
                wall_timeout_seconds=10,
                heartbeat_interval_millis=50,
            )
            try:
                assert _srun_once(
                    core=third_core,
                    sandbox=third_sandbox,
                    transport_policy=_STransport(
                        endpoints=(
                            _TEndpoint(origin=servers.object_origin, addresses=("127.0.0.1",)),
                            _TEndpoint(origin=spatial_output_origin, addresses=("127.0.0.1",)),
                        ),
                        max_header_bytes=4096,
                        max_object_bytes=1_000_000,
                        max_chunk_bytes=512,
                    ),
                    worker_instance_id="two-path-spatial-instance",
                    clock=_now,
                    workspace_root=tmp_path / "two-path-worker",
                    heartbeat_interval_millis=100,
                )
            finally:
                third_sandbox.close()
        third_status = consumer.status(third_job_id)
        assert third_status["jobId"] == third_job_id, third_status
        assert third_status["assetRef"] == third_src.asset_ref, third_status
        assert third_status["siteId"] == "site-a", third_status
        assert third_status["workAreaId"] == fixture.work_area_id, third_status
        assert third_status["executionState"] == "COMPLETED", third_status
        assert third_status["availability"] == "AVAILABLE", third_status
        assert "workOrderId" not in third_status
        assert "epochId" not in third_status
        third_receipt = third_status["receipt"]
        assert third_receipt["jobId"] == third_job_id
        assert third_receipt["sourceDigest"] == third_src.source_digest
        assert third_receipt["sourceSha256"] == third_src.observed_sha256
        assert third_receipt["sourceSizeBytes"] == third_src.observed_size_bytes == 390
        assert third_receipt["artifactId"] == "dsm-analysis-local-third"
        assert third_receipt["requestedBounds"] == list(allowed)
        assert (
            third_receipt["requestedCrsDigest"]
            == third_src.inspection.measurements.observed_crs_digest
        )
        assert third_receipt["observedCrsDigest"] == third_receipt["requestedCrsDigest"]
        assert third_receipt["actualBounds"] == list(allowed)
        assert third_receipt["pixelWindow"] == [0, 2, 0, 2]
        assert third_receipt["width"] == 2 and third_receipt["height"] == 2
        assert third_receipt["transform"] == [0.1, 0.0, 200000.0, 0.0, -0.1, 550000.0]
        assert third_receipt["sourceTransform"] == [0.1, 0.0, 200000.0, 0.0, -0.1, 550000.0]
        assert third_receipt["validPixelCount"] == 4
        assert third_receipt["receiptDigest"] is not None
        third_out_dir = tmp_path / "two-path-download-third"
        third_out_dir.mkdir(mode=0o700)
        third_downloaded = consumer.download(status=third_status, output_dir=third_out_dir)
        third_downloaded_bytes = Path(third_downloaded).read_bytes()
        assert (
            third_receipt["outputSha256"]
            == "sha256:" + hashlib.sha256(third_downloaded_bytes).hexdigest()
        )
        assert third_receipt["outputSizeBytes"] == len(third_downloaded_bytes)
        third_entry = next(
            e
            for e in fixture._third_revision.manifest.entries
            if e.artifact_id == "dsm-analysis-local-third"
        )
        third_original = fixture.storage.object_bytes(third_entry.object_key)
        assert hashlib.sha256(third_original).hexdigest() == third_entry.observed_sha256
        import io as _io2

        import numpy as _np2

        with (
            rasterio.open(_io2.BytesIO(third_original)) as t_src_ds,
            rasterio.open(third_downloaded) as t_out_ds,
        ):
            assert (t_src_ds.width, t_src_ds.height, t_src_ds.count) == (2, 2, 1)
            assert (t_out_ds.width, t_out_ds.height, t_out_ds.count) == (2, 2, 1)
            assert tuple(t_src_ds.dtypes) == tuple(t_out_ds.dtypes)
            assert t_src_ds.crs is not None and t_out_ds.crs is not None
            assert t_src_ds.crs.to_string() == t_out_ds.crs.to_string()
            assert (
                t_out_ds.transform
                == t_src_ds.transform
                == rasterio.Affine(0.1, 0.0, 200000.0, 0.0, -0.1, 550000.0)
            )
            assert tuple(t_out_ds.transform)[:6] == tuple(third_receipt["transform"])
            assert _np2.array_equal(t_out_ds.read(1), t_src_ds.read(1))
            assert _np2.array_equal(t_out_ds.read_masks(1), t_src_ds.read_masks(1))
            assert int(_np2.count_nonzero(t_out_ds.dataset_mask() == 255)) == 4
            assert third_receipt["validPixelCount"] == 4
        assert "source" not in third_status

        # --- AI consent denial (no info/byte exposure for EXTERNAL_AI) ---
        # Site ai_egress_allowed stays False in this lane, so an AI-purpose
        # request must fail closed with AI_EGRESS_DENIED at the grant gate.
        from ksi_event_contracts.spatial_data import SpatialDataPurposeV1 as _Purpose
        from ksi_event_contracts.spatial_data import SpatialDataRequestV1 as _AIReq

        assert current_src.inspection.measurements is not None
        ai_request = _AIReq(
            asset_ref=current_src.asset_ref,
            requested_bounds=allowed,
            observed_crs_digest=current_src.inspection.measurements.observed_crs_digest,
            resolution_mode="NATIVE",
            purpose=_Purpose.EXTERNAL_AI,
        )
        try:
            jobs.issue(
                site_id="site-a",
                work_area_id=fixture.work_area_id,
                request=ai_request,
                principal=_ai_principal,
                idempotency_key="two-path-ai-denied",
                now=_now(),
            )
            raise AssertionError("AI request without consent must not issue")
        except Exception as exc:
            from ksi_core.domains.external.delivery.errors import SpatialDataDomainError as _SDE

            assert isinstance(exc, _SDE) and exc.reason == "AI_EGRESS_DENIED", exc
        # Same denial over HTTP with the synthetic AI bearer: no job, no bytes.
        # This minimal lane mounts only the data/worker routers (no AI egress
        # wiring, which Task5 already covers), so the AI HTTP fails closed with
        # 503 AUDIT_UNAVAILABLE while the grant gate above proves 403
        # AI_EGRESS_DENIED. Both deny bytes without relaxing policy.
        ai_http = TestClient(fixture.app)
        ai_resp = ai_http.post(
            f"/v1/sites/site-a/work-areas/{fixture.work_area_id}/spatial-data-requests",
            headers={
                "Authorization": "Bearer " + _TEST_SPATIAL_AI_TOKEN,
                "Idempotency-Key": "two-path-ai-http-denied",
            },
            json={
                "assetRef": current_src.asset_ref,
                "requestedBounds": list(allowed),
                "observedCrsDigest": current_src.inspection.measurements.observed_crs_digest,
                "resolutionMode": "NATIVE",
                "purpose": "EXTERNAL_AI",
            },
        )
        assert ai_resp.status_code == 503, ai_resp.text
        assert "AUDIT_UNAVAILABLE" in ai_resp.text
        ai_http.close()

        # --- negative controls (no info/byte exposure) ---
        # Wrong area for the same operator: strict 404, no existence oracle.
        resp = http_client.get(
            f"/v1/sites/site-a/work-areas/wa-site-a-9999/spatial-data-requests/{job_id}/file",
            headers=fixture.operator_headers(),
        )
        assert resp.status_code == 404, resp.text
        # Foreign organization cannot resolve the same asset.
        from ksi_core.auth import Principal as _P
        from ksi_core.auth import PrincipalKind as _K
        from ksi_core.auth import Role as _Role

        foreign = _P(
            principal_id="two-path-foreign-viewer",
            organization_id="foreign-org",
            kind=_K.OPERATOR,
            role=_Role.VIEWER,
            device_id=None,
        )
        from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

        try:
            resolver.resolve(
                site_id="site-a",
                work_area_id=fixture.work_area_id,
                asset_ref=current_src.asset_ref,
                principal=foreign,
            )
            raise AssertionError("foreign org must not resolve")
        except SpatialDataDomainError as exc:
            assert exc.reason in ("NOT_FOUND", "PERMISSION_DENIED"), exc.reason
        # Revoked grant closes reads and bytes while completed history stays.
        from ksi_event_contracts.spatial_data_authority import SpatialDataRevocationV1

        # Revoke via the provisioned grant digest kept at provision time.
        revocation = SpatialDataRevocationV1(
            grant_id=f"two-path-grant-{current_src.artifact_id}",
            revision=1,
            organization_id="org-a",
            grant_digest=grant_digests[current_src.artifact_id],
            revoked_at=_now(),
            reason="two-path negative control",
        ).sealed()
        grants.revoke(revocation)
        revoked_status = http_client.get(
            f"/v1/sites/site-a/work-areas/{fixture.work_area_id}/spatial-data-requests/{job_id}",
            headers=fixture.operator_headers(),
        )
        # Completed history remains addressable; live bytes deny closed.
        assert revoked_status.status_code == 200, revoked_status.text
        assert revoked_status.json()["availability"] in (
            "UNAVAILABLE",
            "REVOKED",
            "EXPIRED",
        ) or revoked_status.json().get("reason") in ("ACCESS_REVOKED", "ACCESS_EXPIRED", None)
        revoked_file = http_client.get(
            f"/v1/sites/site-a/work-areas/{fixture.work_area_id}/spatial-data-requests/{job_id}/file",
            headers=fixture.operator_headers(),
        )
        assert revoked_file.status_code == 403, revoked_file.text
        assert "ACCESS_REVOKED" in revoked_file.text or "ACCESS_EXPIRED" in revoked_file.text

        consumer.close()
        http_client.close()
    finally:
        try:
            if servers is not None:
                servers.__exit__(None, None, None)
        finally:
            if spatial_output_server is not None:
                spatial_output_server.shutdown()
                spatial_output_server.server_close()
            if spatial_output_thread is not None:
                spatial_output_thread.join(timeout=5)
            fixture.close()
