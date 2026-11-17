"""실제 Core 소유자를 연결한 단면 loopback HTTP 왕복.

등록·봉인·검사 원장·grant·HEIGHT·저장 선·AuthRegistry는 실제 소유자를 쓴다.
검사 준비에는 기존 TIFF parser entrypoint를 프로세스 안에서 실행하고 실제 검사 원장에
보고서를 수락시킨다. Linux 전용 UDS/컨테이너 격리와 C3 워커 실행은 검증하지 않는다.
자료 바이트와 currentness는 기존 로컬 시험 backend이며, 정확도·고객 수락 증거가 아니다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from analysis_api_local_fixture import _ORIGIN_X, _ORIGIN_Y
from fastapi.testclient import TestClient
from ksi_core.composition.surface_profile_graph import SurfaceProfileGraphConfig
from ksi_core.domains.external.delivery.surface_profile_api import SurfaceProfileHttpLimits
from ksi_core.domains.external.ingress.external_reconstruction import (
    build_external_reconstruction_submission_ref,
)
from ksi_event_contracts.surface_profile_job import (
    SURFACE_PROFILE_ATTEMPT_DIGEST_HEADER,
    SURFACE_PROFILE_WORKER_INSTANCE_ID_HEADER,
    SurfaceProfileActivationV1,
    SurfaceProfileFrozenJobV1,
)
from test_external_analysis_real_inspection_lane_integration import _CoreAndObjectServers
from test_platform_core_http_integration import (
    _admit_real_inspection_policy,
    _create_external_order,
    _lane_view,
    _PlatformFlowContext,
    _seal_two_dsm_revisions,
    _seed_site_and_area,
    _store_order,
)

_READER_TOKEN = "platform-flow-surface-reader"  # noqa: S105 -- 결정적인 시험용 자격
_WORKER_TOKEN = "platform-flow-surface-worker"  # noqa: S105 -- 결정적인 시험용 자격
_FOREIGN_TOKEN = "platform-flow-foreign"  # noqa: S105 -- 결정적인 시험용 자격
_WORKER_INSTANCE = "platform-flow-surface-instance-1"


def _reader_headers(key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": "Bearer " + _READER_TOKEN}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _worker_headers(*, digest: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": "Bearer " + _WORKER_TOKEN,
        SURFACE_PROFILE_WORKER_INSTANCE_ID_HEADER: _WORKER_INSTANCE,
    }
    if digest is not None:
        headers[SURFACE_PROFILE_ATTEMPT_DIGEST_HEADER] = digest
    return headers


def _surface_config(
    now_box: list[datetime],
    *,
    activation_seconds: float = 3600.0,
    origin: str = "https://store.invalid",
) -> SurfaceProfileGraphConfig:
    from spatial_data_fixture import make_envelope
    from surface_profile_job_fixture import profile_policy, profile_runtime

    policy = profile_policy(
        resource_envelope=make_envelope(
            max_input_bytes=1_000_000,
            max_output_bytes=2_000_000,
            max_workspace_bytes=4_000_000,
            max_pixels=100_000,
            max_geometry_vertices=64,
            max_tenant_concurrency=3,
            max_queue_depth=8,
            max_deadline_seconds=120.0,
        )
    )
    runtime = profile_runtime()
    activation = SurfaceProfileActivationV1(
        activation_id="platform-surface-activation-1",
        organization_id="org-a",
        worker_principal_id="platform-flow-surface-worker",
        worker_instance_id=_WORKER_INSTANCE,
        policy_digest=policy.policy_digest or "",
        runtime_digest=runtime.runtime_digest or "",
        trusted_endpoint_origins=(origin,),
        valid_from=now_box[0] - timedelta(minutes=1),
        valid_until=now_box[0] + timedelta(seconds=activation_seconds),
    ).sealed()
    return SurfaceProfileGraphConfig(
        policy=policy,
        runtime=runtime,
        activation=activation,
        http_limits=SurfaceProfileHttpLimits(
            request_max_bytes=4096,
            complete_max_bytes=500_000,
            timeout_seconds=1.0,
        ),
        clock=lambda: now_box[0],
    )


def _line_inside_current_dsm() -> list[list[float]]:
    x0, y0 = float(_ORIGIN_X), float(_ORIGIN_Y)
    return [[x0 + 0.02, y0 - 0.02], [x0 + 0.18, y0 - 0.18]]


def _create_feature(client: Any, area_id: str, *, key: str) -> dict[str, Any]:
    response = client.post(
        f"/v1/sites/site-a/work-areas/{area_id}/measurement-features",
        headers=_reader_headers(key),
        json={
            "workAreaId": area_id,
            "name": "단면 시험 선",
            "line": {"crs": "EPSG:5186", "vertices": _line_inside_current_dsm()},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["revision"]


def _feature_ref(revision: dict[str, Any]) -> dict[str, Any]:
    return {
        "featureId": revision["featureId"],
        "revision": revision["revision"],
        "lineDigest": revision["lineDigest"],
    }


def _height_decision_id(client: Any, order: Any, subject: Any, *, key: str) -> str:
    submission_ref = build_external_reconstruction_submission_ref(
        organization_id="org-a",
        work_order_id=order.work_order_id,
        submission_id=subject.submission_id,
    )
    response = client.post(
        f"/v1/observation-work-orders/{order.work_order_id}/"
        f"external-reconstruction-submissions/{submission_ref}/revisions/1/"
        "use-decisions/single",
        headers=_reader_headers(key),
        json={"use": "HEIGHT"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["decision"]["verdict"] == "ELIGIBLE", response.text
    return response.json()["decision"]["decisionId"]


def _provision_surface_grant(ctx: _PlatformFlowContext, area_id: str, current_revision: Any) -> str:
    from ksi_core.auth import Principal, PrincipalKind, Role
    from ksi_core.domains.external.ingress.spatial_asset_catalog import SpatialAssetCatalog
    from spatial_data_fixture import make_grant

    lane = ctx.app.state.spatial_data
    assert lane is not None
    reader = Principal(
        principal_id="platform-data-reader",
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
        organization_id="org-a",
    )
    entry = current_revision.manifest.entries[0]
    items = SpatialAssetCatalog(
        reconstruction=ctx.app.state.external_reconstruction_store,
        work_orders=ctx.app.state.observation_work_order_store,
        sites=ctx.app.state.site_store,
        work_areas=ctx.app.state.work_area_store,
        inspections=ctx.app.state.external_artifact_inspection_store,
    ).items(ctx.site_id, area_id, reader)
    current_items = [item for item in items if item.artifact_id == entry.artifact_id]
    assert current_items, "sealed current DSM must be discoverable as a profile source"
    candidate = current_items[0]
    source = lane.sources.resolve(
        site_id=ctx.site_id,
        work_area_id=area_id,
        asset_ref=candidate.asset_ref,
        principal=reader,
    )
    measurements = source.inspection.measurements
    assert measurements is not None
    lane.grants.provision(
        make_grant(
            grant_id="platform-surface-grant-1",
            organization_id="org-a",
            beneficiary_principal_id="platform-data-reader",
            asset_ref=candidate.asset_ref,
            site_id=ctx.site_id,
            work_area_id=area_id,
            allowed_bounds=(
                float(_ORIGIN_X) - 1.0,
                float(_ORIGIN_Y) - 1.0,
                float(_ORIGIN_X) + 1.0,
                float(_ORIGIN_Y) + 1.0,
            ),
            observed_crs_digest=measurements.observed_crs_digest,
            policy_digest=lane.config.policy.policy_digest,
            valid_from=ctx.now - timedelta(minutes=1),
            valid_until=ctx.now + timedelta(hours=1),
        )
    )
    return candidate.asset_ref


def _sealed_object_key(ctx: _PlatformFlowContext, current_revision: Any) -> str:
    entry = current_revision.manifest.entries[0]
    wanted = "sha256:" + entry.observed_sha256
    for key in list(ctx.storage._bytes.keys()):  # noqa: SLF001 -- 시험 저장소 확인
        if ctx.storage.observe_object(key).sha256 == wanted:
            return key
    raise AssertionError("sealed current DSM bytes must be in the loopback storage")


def _genuine_completion(
    frozen: SurfaceProfileFrozenJobV1, raw_dsm: bytes, tmp_path: Path, now: datetime
) -> tuple[dict[str, Any], dict[str, Any]]:
    from surface_profile_job_fixture import genuine_answer

    raster_path = tmp_path / f"surface-{frozen.job_id}.tif"
    raster_path.write_bytes(raw_dsm)
    result, receipt = genuine_answer(frozen, raster_path, now)
    return (
        result.model_dump(by_alias=True, mode="json"),
        receipt.model_dump(by_alias=True, mode="json"),
    )


def _retain_real_parser_report(flow: Any) -> None:
    """실제 parser와 검사 소유자를 쓰되 외부 프로세스 실행 경계는 분리한다."""
    import hashlib
    from io import BytesIO
    from uuid import uuid4

    from ksi_core.leasing import LeaseFence
    from ksi_event_contracts.external_artifact_validation import (
        ArtifactInspectionOutcomeV1,
        ExternalArtifactInspectionReportV1,
        ExternalInspectionMeasurementPayloadV1,
        SealedArtifactBindingV1,
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
        InspectorLaunchRequestV1,
        InspectorOperation,
        LocalLeaseFenceV1,
        SealedByteBindingV1,
    )
    from test_external_inspector_container_entrypoint import _decode_output

    ctx, subject, revision = flow.ctx, flow.current_subject, flow.current_revision
    store = ctx.app.state.external_artifact_inspection_store
    policy, manifest = flow.view._inspection_policy, flow.view._inspector_manifest
    now = ctx.now
    issued = store.issue_after_seal(subject, now=now)
    assert issued.request is not None
    worker_id, acquisition = str(uuid4()), str(uuid4())
    claimed = store.claim(
        issued.request.request_id,
        LeaseFence(worker_id, acquisition, 0),
        now,
        organization_id=subject.organization_id,
    )
    assert claimed.fence is not None
    fence = claimed.fence
    entry = revision.manifest.entries[0]
    raw = ctx.storage.object_bytes(entry.object_key)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    assert digest == "sha256:" + entry.observed_sha256 and len(raw) == entry.observed_size_bytes
    binding = SealedByteBindingV1(
        artifact_id=entry.artifact_id, observed_sha256=digest, observed_size_bytes=len(raw)
    )
    launch = InspectorLaunchRequestV1.seal(
        operation=InspectorOperation.INSPECT,
        request=issued.request,
        fence=LocalLeaseFenceV1(
            worker_instance_id=fence.worker_instance_id,
            lease_acquisition_id=fence.lease_acquisition_id,
            lease_generation=fence.lease_generation,
        ),
        subject=subject,
        sealed_byte_binding=binding,
        policy=policy,
        attempt_nonce="surface-fixture-actual-parser",
    )
    root = flow.tmp_path / "surface-fixture-inspection"
    root.mkdir(mode=0o700)
    artifact, workspace = root / "sealed-dsm.tif", root / "workspace"
    artifact.write_bytes(raw)
    workspace.mkdir(mode=0o700)
    limits = ContainerInnerFrameLimitsV1(maximum_frame_bytes=128_000, maximum_stderr_bytes=0)
    prepare = build_prepare_frame(
        attempt_nonce=launch.attempt_nonce,
        outer_canonical_input_digest=launch.canonical_input_digest,
        operation=launch.operation.value,
        sealed_byte_binding=binding.model_dump(by_alias=True, mode="json"),
        policy=policy,
        manifest=manifest,
        admitted_backend_profile_digest=manifest.body.backend_profile_digest,
        admitted_security_profile_digest=manifest.body.security_profile_digest,
        admitted_inner_protocol_digest=manifest.body.inspector_protocol_digest,
    )
    output = BytesIO()
    run_container_entrypoint(
        stdin=BytesIO(
            encode_inner_frame(prepare, limits=limits)
            + encode_inner_frame(build_execute_frame(prepare=prepare), limits=limits)
        ),
        stdout=output,
        artifact_path=artifact,
        workspace=workspace,
        limits=limits,
    )
    _, terminal, raw_output = _decode_output(output, limits)
    assert raw_output == b""
    outcome = ArtifactInspectionOutcomeV1.model_validate(terminal["outcome"])
    assert outcome.outcome.value == "MEASURED" and outcome.observed_sha256 == digest
    payload = ExternalInspectionMeasurementPayloadV1(
        subject_digest=subject.canonical_digest(),
        sealed_manifest_digest=subject.manifest_digest,
        inspection_policy_digest=policy.policy_digest,
        inspector_build_digest=policy.parser_build_digest,
        artifact_bindings=(
            SealedArtifactBindingV1(artifact_id=entry.artifact_id, observed_sha256=digest),
        ),
        outcomes=(outcome,),
    )
    report = ExternalArtifactInspectionReportV1(
        report_id="surface-real-parser-" + str(uuid4()),
        request_id=issued.request.request_id,
        subject=subject,
        subject_digest=subject.canonical_digest(),
        sealed_manifest_digest=subject.manifest_digest,
        inspection_policy_digest=policy.policy_digest,
        inspector_build_digest=policy.parser_build_digest,
        measurement_payload=payload,
        worker_instance_id=fence.worker_instance_id,
        lease_acquisition_id=fence.lease_acquisition_id,
        lease_generation=fence.lease_generation,
        reported_at=now,
    ).sealed()
    accepted = store.record_report(
        issued.request.request_id, fence, report, now, organization_id=subject.organization_id
    )
    assert accepted.verdict.value == "REPORTED"
    assert store.public_snapshot(subject).report == report


class _ReadyFlow:
    def __init__(self, tmp_path: Path, *, activation_seconds: float = 3600.0) -> None:
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.now_box: list[datetime] = [datetime.now(UTC).replace(microsecond=0)]
        # 봉인된 DSM 바이트를 /source로 내려주는 실제 loopback 객체 서버. 바이트는 봉인 뒤 채운다.
        self.source_bytes: dict[str, bytes] = {"payload": b""}
        source_bytes = self.source_bytes

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/source" or not source_bytes["payload"]:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/tiff")
                self.send_header("Content-Length", str(len(source_bytes["payload"])))
                self.end_headers()
                self.wfile.write(source_bytes["payload"])

            def log_message(self, *_: object) -> None:
                return

        self.object_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.object_thread = threading.Thread(target=self.object_server.serve_forever, daemon=True)
        self.object_thread.start()
        self.object_origin = f"http://127.0.0.1:{self.object_server.server_port}"
        try:
            self.ctx = _PlatformFlowContext(
                tmp_path,
                with_spatial_data=True,
                surface_profile=_surface_config(
                    self.now_box,
                    activation_seconds=activation_seconds,
                    origin=self.object_origin,
                ),
                spatial_object_origin=self.object_origin,
            )
        except BaseException:
            self.object_server.shutdown()
            self.object_server.server_close()
            raise
        assert self.ctx.app.state.surface_profile is not None
        self.tmp_path = tmp_path
        self.area_id = ""
        self.servers: _CoreAndObjectServers | None = None
        self.http: httpx.Client | None = None
        self.view: Any = None
        self.current_order: Any = None
        self.current_subject: Any = None

    @property
    def requester_base(self) -> str:
        return f"/v1/sites/site-a/work-areas/{self.area_id}/surface-profile-jobs"

    @property
    def worker_base(self) -> str:
        return "/v1/internal/surface-profile-jobs"

    def seal(self) -> None:
        with TestClient(self.ctx.app) as setup:
            self.area_id = _seed_site_and_area(self.ctx)
            baseline_order = _store_order(
                self.ctx,
                _create_external_order(setup, self.area_id, key="surface-baseline")["workOrderId"],
            )
            self.current_order = _store_order(
                self.ctx,
                _create_external_order(setup, self.area_id, key="surface-current")["workOrderId"],
            )
            revisions = _seal_two_dsm_revisions(self.ctx, setup, baseline_order, self.current_order)
            _, _, self.current_revision, self.current_subject = revisions
            policy, manifest = _admit_real_inspection_policy(
                self.ctx, (revisions[1], self.current_subject), allow_height=True
            )
            self.feature = _create_feature(setup, self.area_id, key="surface-feature-1")
            self.view = _lane_view(
                self.ctx,
                revisions[0],
                revisions[1],
                self.current_revision,
                self.current_subject,
                policy,
                manifest,
            )

    def serve_and_measure(self) -> None:
        self.servers = _CoreAndObjectServers(self.view)
        self.servers.__enter__()
        _retain_real_parser_report(self)
        self.source_bytes["payload"] = self.ctx.storage.object_bytes(
            _sealed_object_key(self.ctx, self.current_revision)
        )
        self.http = httpx.Client(base_url=self.servers.core_origin, trust_env=False)
        self.asset_ref = _provision_surface_grant(self.ctx, self.area_id, self.current_revision)

    def issue_body(self, asset_ref: str, decision_id: str) -> dict[str, Any]:
        return {
            "assetRef": asset_ref,
            "feature": _feature_ref(self.feature),
            "heightDecisionId": decision_id,
            "sampleSpacingM": 0.05,
        }

    def close(self) -> None:
        try:
            if self.http is not None:
                self.http.close()
            if self.servers is not None:
                self.servers.__exit__(None, None, None)
        finally:
            self.ctx.close()
            self.object_server.shutdown()
            self.object_server.server_close()
            self.object_thread.join(timeout=2)


def test_issue_list_lease_renew_complete_result_over_loopback_http(tmp_path: Path) -> None:
    flow = _ReadyFlow(tmp_path)
    try:
        flow.seal()
        flow.serve_and_measure()
        assert flow.http is not None
        http = flow.http
        decision_id = _height_decision_id(
            http, flow.current_order, flow.current_subject, key="surface-height-1"
        )
        body = flow.issue_body(flow.asset_ref, decision_id)

        created = http.post(
            flow.requester_base, headers=_reader_headers("surface-issue-1"), json=body
        )
        assert created.status_code == 200, created.text
        job_id = created.json()["jobId"]
        assert created.json()["executionState"] == "QUEUED"
        assert "samples" not in created.text

        retried = http.post(
            flow.requester_base, headers=_reader_headers("surface-issue-1"), json=body
        )
        assert retried.status_code == 200, retried.text
        assert retried.json()["jobId"] == job_id

        conflict = http.post(
            flow.requester_base,
            headers=_reader_headers("surface-issue-1"),
            json=dict(body, sampleSpacingM=0.1),
        )
        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["reason"] == "IDEMPOTENCY_CONFLICT"

        listed = http.get(flow.requester_base, headers=_reader_headers())
        assert listed.status_code == 200, listed.text
        assert [item["jobId"] for item in listed.json()["items"]] == [job_id]

        fetched = http.get(f"{flow.requester_base}/{job_id}", headers=_reader_headers())
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["jobId"] == job_id

        pending = http.get(flow.worker_base, headers=_worker_headers())
        assert pending.status_code == 200, pending.text
        assert [item["jobId"] for item in pending.json()["items"]] == [job_id]

        lease = http.post(
            f"{flow.worker_base}/{job_id}/lease",
            headers=_worker_headers(),
            json={"workerInstanceId": _WORKER_INSTANCE, "acquisitionId": "surface-acq-1"},
        )
        assert lease.status_code == 200, lease.text
        attempt = lease.json()["attempt"]
        digest = attempt["attemptDigest"]

        first_input = http.get(
            f"{flow.worker_base}/{job_id}/input", headers=_worker_headers(digest=digest)
        )
        assert first_input.status_code == 200, first_input.text
        frozen = SurfaceProfileFrozenJobV1.model_validate(first_input.json()["input"]["job"])
        assert frozen.job_id == job_id

        flow.now_box[0] = flow.now_box[0] + timedelta(seconds=1)
        renewed = http.post(
            f"{flow.worker_base}/{job_id}/renew",
            headers=_worker_headers(digest=digest),
            json={"attempt": attempt},
        )
        assert renewed.status_code == 200, renewed.text
        attempt2 = renewed.json()["attempt"]
        assert attempt2["attemptDigest"] != digest

        stale = http.get(
            f"{flow.worker_base}/{job_id}/input", headers=_worker_headers(digest=digest)
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["reason"] == "FENCE_CONFLICT"

        fresh = http.get(
            f"{flow.worker_base}/{job_id}/input",
            headers=_worker_headers(digest=attempt2["attemptDigest"]),
        )
        assert fresh.status_code == 200, fresh.text
        live = SurfaceProfileFrozenJobV1.model_validate(fresh.json()["input"]["job"])
        assert live.job_digest == frozen.job_digest

        raw_dsm = flow.ctx.storage.object_bytes(_sealed_object_key(flow.ctx, flow.current_revision))
        result_json, receipt_json = _genuine_completion(live, raw_dsm, tmp_path, flow.now_box[0])
        completed = http.post(
            f"{flow.worker_base}/{job_id}/complete",
            headers=_worker_headers(digest=attempt2["attemptDigest"]),
            json={"attempt": attempt2, "result": result_json, "receipt": receipt_json},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["executionState"] == "COMPLETED"

        again = http.post(
            f"{flow.worker_base}/{job_id}/complete",
            headers=_worker_headers(digest=attempt2["attemptDigest"]),
            json={"attempt": attempt2, "result": result_json, "receipt": receipt_json},
        )
        assert again.status_code == 200, again.text
        assert again.json()["executionState"] == "COMPLETED"

        result = http.get(f"{flow.requester_base}/{job_id}/result", headers=_reader_headers())
        assert result.status_code == 200, result.text
        payload = result.json()
        assert payload["job"]["executionState"] == "COMPLETED"
        assert payload["result"]["resultDigest"] == receipt_json["resultDigest"]
        assert payload["result"]["lineDigest"] == flow.feature["lineDigest"]
    finally:
        flow.close()


def test_cancel_failure_retry_and_cross_job_tamper_over_loopback_http(tmp_path: Path) -> None:
    flow = _ReadyFlow(tmp_path)
    try:
        flow.seal()
        flow.serve_and_measure()
        assert flow.http is not None
        http = flow.http
        decision_id = _height_decision_id(
            http, flow.current_order, flow.current_subject, key="surface-height-2"
        )

        job_a = http.post(
            flow.requester_base,
            headers=_reader_headers("surface-a"),
            json=flow.issue_body(flow.asset_ref, decision_id),
        )
        assert job_a.status_code == 200, job_a.text
        job_a_id = job_a.json()["jobId"]
        job_b = http.post(
            flow.requester_base,
            headers=_reader_headers("surface-b"),
            json=flow.issue_body(flow.asset_ref, decision_id),
        )
        assert job_b.status_code == 200, job_b.text
        job_b_id = job_b.json()["jobId"]
        assert job_b_id != job_a_id

        lease_a = http.post(
            f"{flow.worker_base}/{job_a_id}/lease",
            headers=_worker_headers(),
            json={"workerInstanceId": _WORKER_INSTANCE, "acquisitionId": "surface-acq-a"},
        )
        assert lease_a.status_code == 200, lease_a.text
        attempt_a = lease_a.json()["attempt"]
        lease_b = http.post(
            f"{flow.worker_base}/{job_b_id}/lease",
            headers=_worker_headers(),
            json={"workerInstanceId": _WORKER_INSTANCE, "acquisitionId": "surface-acq-b"},
        )
        assert lease_b.status_code == 200, lease_b.text
        attempt_b = lease_b.json()["attempt"]

        frozen_a = SurfaceProfileFrozenJobV1.model_validate(
            http.get(
                f"{flow.worker_base}/{job_a_id}/input",
                headers=_worker_headers(digest=attempt_a["attemptDigest"]),
            ).json()["input"]["job"]
        )
        raw_dsm = flow.ctx.storage.object_bytes(_sealed_object_key(flow.ctx, flow.current_revision))
        result_a, receipt_a = _genuine_completion(frozen_a, raw_dsm, tmp_path, flow.now_box[0])

        tampered = http.post(
            f"{flow.worker_base}/{job_b_id}/complete",
            headers=_worker_headers(digest=attempt_b["attemptDigest"]),
            json={"attempt": attempt_b, "result": result_a, "receipt": receipt_a},
        )
        assert tampered.status_code == 422, tampered.text
        assert tampered.json()["reason"] == "INVALID_REQUEST"

        canceled = http.post(f"{flow.requester_base}/{job_a_id}/cancel", headers=_reader_headers())
        assert canceled.status_code == 200, canceled.text
        assert canceled.json()["executionState"] == "CANCELED"
        not_ready = http.get(f"{flow.requester_base}/{job_a_id}/result", headers=_reader_headers())
        assert not_ready.status_code == 409, not_ready.text
        assert not_ready.json()["reason"] == "NOT_READY"

        failed = http.post(
            f"{flow.worker_base}/{job_b_id}/failure",
            headers=_worker_headers(digest=attempt_b["attemptDigest"]),
            json={"attempt": attempt_b, "reason": "STORAGE_UNAVAILABLE", "retryable": True},
        )
        assert failed.status_code == 200, failed.text
        assert failed.json()["executionState"] == "QUEUED"

        flow.now_box[0] = flow.now_box[0] + timedelta(seconds=2)
        pending = http.get(flow.worker_base, headers=_worker_headers())
        assert pending.status_code == 200, pending.text
        assert [item["jobId"] for item in pending.json()["items"]] == [job_b_id]

        lease_b2 = http.post(
            f"{flow.worker_base}/{job_b_id}/lease",
            headers=_worker_headers(),
            json={"workerInstanceId": _WORKER_INSTANCE, "acquisitionId": "surface-acq-b2"},
        )
        assert lease_b2.status_code == 200, lease_b2.text
        attempt_b2 = lease_b2.json()["attempt"]
        frozen_b = SurfaceProfileFrozenJobV1.model_validate(
            http.get(
                f"{flow.worker_base}/{job_b_id}/input",
                headers=_worker_headers(digest=attempt_b2["attemptDigest"]),
            ).json()["input"]["job"]
        )
        result_b, receipt_b = _genuine_completion(frozen_b, raw_dsm, tmp_path, flow.now_box[0])
        completed = http.post(
            f"{flow.worker_base}/{job_b_id}/complete",
            headers=_worker_headers(digest=attempt_b2["attemptDigest"]),
            json={"attempt": attempt_b2, "result": result_b, "receipt": receipt_b},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["executionState"] == "COMPLETED"
        result = http.get(f"{flow.requester_base}/{job_b_id}/result", headers=_reader_headers())
        assert result.status_code == 200, result.text
        assert result.json()["job"]["executionState"] == "COMPLETED"
    finally:
        flow.close()


def test_scope_org_and_line_revision_guards_over_loopback_http(tmp_path: Path) -> None:
    flow = _ReadyFlow(tmp_path)
    try:
        flow.seal()
        flow.serve_and_measure()
        assert flow.http is not None
        http = flow.http
        foreign = {"Authorization": "Bearer " + _FOREIGN_TOKEN}
        decision_id = _height_decision_id(
            http, flow.current_order, flow.current_subject, key="surface-height-3"
        )
        body = flow.issue_body(flow.asset_ref, decision_id)

        created = http.post(
            flow.requester_base, headers=_reader_headers("surface-guard"), json=body
        )
        assert created.status_code == 200, created.text
        job_id = created.json()["jobId"]

        assert (
            http.post(
                flow.requester_base, headers={**foreign, "Idempotency-Key": "x"}, json=body
            ).status_code
            == 404
        )
        assert http.get(flow.requester_base, headers=foreign).status_code == 404
        assert http.get(f"{flow.requester_base}/{job_id}", headers=foreign).status_code == 404
        assert (
            http.get(f"{flow.requester_base}/{job_id}/result", headers=foreign).status_code == 404
        )

        assert (
            http.get(
                f"/v1/sites/site-a/work-areas/wa-elsewhere-0000/surface-profile-jobs/{job_id}",
                headers=_reader_headers(),
            ).status_code
            == 404
        )

        # 편집은 새 revision을 만들며 과거 exact revision을 무효화하지 않는다.
        x0, y0 = float(_ORIGIN_X), float(_ORIGIN_Y)
        revised = http.post(
            f"/v1/sites/site-a/work-areas/{flow.area_id}/measurement-features/"
            f"{flow.feature['featureId']}/revisions",
            headers=_reader_headers("surface-revise-1"),
            json={
                "expectedRevision": 1,
                "name": "단면 시험 선 2",
                "line": {
                    "crs": "EPSG:5186",
                    "vertices": [[x0 + 0.03, y0 - 0.03], [x0 + 0.17, y0 - 0.17]],
                },
            },
        )
        assert revised.status_code == 201, revised.text
        assert revised.json()["revision"]["revision"] == 2
        stale_issue = http.post(
            flow.requester_base, headers=_reader_headers("surface-guard"), json=body
        )
        assert stale_issue.status_code == 200, stale_issue.text
        assert stale_issue.json()["jobId"] == job_id
        assert stale_issue.json()["feature"] == body["feature"]
        new_body = dict(body, feature=_feature_ref(revised.json()["revision"]))
        moved = http.post(
            flow.requester_base, headers=_reader_headers("surface-new-ref"), json=new_body
        )
        assert moved.status_code == 200, moved.text
        assert moved.json()["executionState"] == "QUEUED"

        lease = http.post(
            f"{flow.worker_base}/{job_id}/lease",
            headers=_worker_headers(),
            json={"workerInstanceId": _WORKER_INSTANCE, "acquisitionId": "surface-acq-g"},
        )
        assert lease.status_code == 200, lease.text
        digest = lease.json()["attempt"]["attemptDigest"]
        wrong_instance = {
            "Authorization": "Bearer " + _WORKER_TOKEN,
            SURFACE_PROFILE_WORKER_INSTANCE_ID_HEADER: "another-instance",
            SURFACE_PROFILE_ATTEMPT_DIGEST_HEADER: digest,
        }
        assert (
            http.get(f"{flow.worker_base}/{job_id}/input", headers=wrong_instance).status_code
            == 403
        )
        assert (
            http.get(
                f"{flow.worker_base}/{job_id}/input", headers=_worker_headers(digest="digest wrong")
            ).status_code
            == 409
        )
        original = http.get(
            f"{flow.worker_base}/{job_id}/input", headers=_worker_headers(digest=digest)
        )
        assert original.status_code == 200, original.text
        frozen = SurfaceProfileFrozenJobV1.model_validate(original.json()["input"]["job"])
        assert frozen.feature.revision == 1
        raw = flow.ctx.storage.object_bytes(_sealed_object_key(flow.ctx, flow.current_revision))
        result_json, receipt_json = _genuine_completion(frozen, raw, tmp_path, flow.now_box[0])
        completed = http.post(
            f"{flow.worker_base}/{job_id}/complete",
            headers=_worker_headers(digest=digest),
            json={
                "attempt": lease.json()["attempt"],
                "result": result_json,
                "receipt": receipt_json,
            },
        )
        assert completed.status_code == 200, completed.text
        retained = http.get(f"{flow.requester_base}/{job_id}/result", headers=_reader_headers())
        assert retained.status_code == 200, retained.text
        assert retained.json()["result"]["feature"]["revision"] == 1
    finally:
        flow.close()


def test_surface_opt_in_routes_and_journal_inventory(tmp_path: Path) -> None:
    from test_platform_core_http_integration import _walk_routes

    now_box: list[datetime] = [datetime.now(UTC).replace(microsecond=0)]
    ctx = _PlatformFlowContext(
        tmp_path, with_spatial_data=True, surface_profile=_surface_config(now_box)
    )
    try:
        assert ctx.app.state.surface_profile is not None
        assert ctx.app.state.surface_profile.jobs is not None
        assert ctx.app.state.surface_profile.authority is not None
        inventory = {(route.path, next(iter(route.methods))) for route in _walk_routes(ctx.app)}
        requester = "/v1/sites/{site_id}/work-areas/{work_area_id}/surface-profile-jobs"
        assert (requester, "POST") in inventory
        assert (requester, "GET") in inventory
        assert ("/v1/internal/surface-profile-jobs", "GET") in inventory
        native = "/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-requests"
        assert (native, "POST") in inventory
        basenames = sorted(Path(name).name for name in ctx.trace)
        assert any("surface" in name and "profile" in name for name in basenames), basenames
    finally:
        ctx.close()


def test_surface_routes_absent_without_opt_in(tmp_path: Path) -> None:
    from test_platform_core_http_integration import _walk_routes

    ctx = _PlatformFlowContext(tmp_path, with_spatial_data=True)
    try:
        inventory = {(route.path, next(iter(route.methods))) for route in _walk_routes(ctx.app)}
        assert not any("surface-profile" in path for path, _ in inventory)
        with TestClient(ctx.app) as client:
            assert (
                client.get(
                    "/v1/sites/site-a/work-areas/wa-x/surface-profile-jobs",
                    headers=_reader_headers(),
                ).status_code
                == 404
            )
            assert (
                client.get(
                    "/v1/internal/surface-profile-jobs", headers=_worker_headers()
                ).status_code
                == 404
            )
    finally:
        ctx.close()


@pytest.mark.parametrize("revocation", ["grant", "height_policy"])
@pytest.mark.parametrize("release", ["input", "result"])
def test_real_owners_withdraw_input_and_numeric_result(
    tmp_path: Path,
    revocation: str,
    release: str,
) -> None:
    """실제 grant·HEIGHT 정책 철회가 이후 HTTP 입력·수치 반환을 차단한다."""
    from ksi_event_contracts.spatial_data_authority import SpatialDataRevocationV1

    flow = _ReadyFlow(tmp_path)
    try:
        flow.seal()
        flow.serve_and_measure()
        assert flow.http is not None
        http = flow.http
        decision_id = _height_decision_id(
            http, flow.current_order, flow.current_subject, key="revocation-height"
        )
        issued = http.post(
            flow.requester_base,
            headers=_reader_headers("revoke-job"),
            json=flow.issue_body(flow.asset_ref, decision_id),
        )
        assert issued.status_code == 200, issued.text
        job_id = issued.json()["jobId"]
        url = f"{flow.worker_base}/{job_id}"
        lease = http.post(
            url + "/lease",
            headers=_worker_headers(),
            json={
                "workerInstanceId": _WORKER_INSTANCE,
                "acquisitionId": "revocation-attempt",
            },
        )
        assert lease.status_code == 200, lease.text
        attempt = lease.json()["attempt"]
        headers = _worker_headers(digest=attempt["attemptDigest"])
        source = http.get(url + "/input", headers=headers)
        assert source.status_code == 200, source.text
        frozen = SurfaceProfileFrozenJobV1.model_validate(source.json()["input"]["job"])
        if release == "result":
            raw = flow.ctx.storage.object_bytes(_sealed_object_key(flow.ctx, flow.current_revision))
            result, receipt = _genuine_completion(frozen, raw, tmp_path, flow.now_box[0])
            completed = http.post(
                url + "/complete",
                headers=headers,
                json={"attempt": attempt, "result": result, "receipt": receipt},
            )
            assert completed.status_code == 200, completed.text
        flow.now_box[0] += timedelta(seconds=1)
        if revocation == "grant":
            assert frozen.grant.grant_digest is not None
            flow.ctx.app.state.spatial_data.grants.revoke(
                SpatialDataRevocationV1(
                    grant_id=frozen.grant.grant_id,
                    revision=frozen.grant.revision,
                    organization_id="org-a",
                    grant_digest=frozen.grant.grant_digest,
                    revoked_at=flow.now_box[0],
                    reason="시험에서 명시적으로 철회",
                ).sealed()
            )
        else:
            policy = flow.view._inspection_policy
            revoked = flow.ctx.app.state.external_validation_policy_registry.revoke(
                policy.policy_id, policy.version, actor="policy-admin", now=flow.now_box[0]
            )
            assert revoked.status.value == "REVOKED"
        denied = http.get(
            url + "/input" if release == "input" else f"{flow.requester_base}/{job_id}/result",
            headers=headers if release == "input" else _reader_headers(),
        )
        expected_status, expected_reason = (
            (403, "ACCESS_REVOKED") if revocation == "grant" else (503, "CURRENTNESS_UNAVAILABLE")
        )
        assert denied.status_code == expected_status, denied.text
        assert denied.json()["reason"] == expected_reason
        assert "samples" not in denied.text and "result" not in denied.json()
    finally:
        flow.close()


def test_real_activation_expiry_blocks_pending_and_still_live_input(tmp_path: Path) -> None:
    flow = _ReadyFlow(tmp_path, activation_seconds=1.0)
    try:
        flow.seal()
        flow.serve_and_measure()
        assert flow.http is not None
        http = flow.http
        decision_id = _height_decision_id(
            http, flow.current_order, flow.current_subject, key="activation-height"
        )
        issued = http.post(
            flow.requester_base,
            headers=_reader_headers("activation-job"),
            json=flow.issue_body(flow.asset_ref, decision_id),
        )
        assert issued.status_code == 200, issued.text
        url = f"{flow.worker_base}/{issued.json()['jobId']}"
        lease = http.post(
            url + "/lease",
            headers=_worker_headers(),
            json={
                "workerInstanceId": _WORKER_INSTANCE,
                "acquisitionId": "activation-attempt",
            },
        )
        assert lease.status_code == 200, lease.text
        attempt = lease.json()["attempt"]
        flow.now_box[0] += timedelta(seconds=2)
        assert flow.now_box[0] < datetime.fromisoformat(
            attempt["leaseUntil"].replace("Z", "+00:00")
        )
        assert http.get(flow.worker_base, headers=_worker_headers()).status_code == 403
        denied = http.get(url + "/input", headers=_worker_headers(digest=attempt["attemptDigest"]))
        assert denied.status_code == 403 and denied.json()["reason"] == "PERMISSION_DENIED"
    finally:
        flow.close()


def _run_surface_worker(flow: _ReadyFlow, core_origin: str) -> bool:
    """https 전용 일꾼 클라이언트가 실제 loopback Core로 전달한다. 성공 본문은 만들지 않는다."""
    from ksi_processing_controller.external_object_streams import (
        ExternalObjectTransportPolicyV1,
        TrustedObjectEndpointV1,
    )
    from ksi_processing_controller.surface_profile_core_client import SurfaceProfileCoreClient
    from ksi_processing_controller.surface_profile_runner import run_once

    wiring = flow.ctx.app.state.surface_profile
    workspace = flow.tmp_path / "surface-worker"
    workspace.mkdir(mode=0o700, exist_ok=True)
    with httpx.Client(base_url=core_origin, trust_env=False) as direct:

        def forward(request: httpx.Request) -> httpx.Response:
            assert request.url.host == "core.invalid"
            response = direct.request(
                request.method,
                request.url.raw_path.decode(),
                headers=dict(request.headers),
                content=request.read(),
            )
            return httpx.Response(
                response.status_code, headers=response.headers, content=response.content
            )

        with SurfaceProfileCoreClient(
            base_url="https://core.invalid",
            token=_WORKER_TOKEN,
            activation=wiring.config.activation,
            policy=wiring.config.policy,
            runtime=wiring.config.runtime,
            clock=lambda: flow.now_box[0],
            maximum_response_bytes=1_000_000,
            maximum_request_bytes=500_000,
            request_timeout_seconds=5.0,
            transport=httpx.MockTransport(forward),
        ) as core:
            return run_once(
                core=core,
                transport_policy=ExternalObjectTransportPolicyV1(
                    endpoints=(
                        TrustedObjectEndpointV1(
                            origin=flow.object_origin, addresses=("127.0.0.1",)
                        ),
                    ),
                    max_header_bytes=4096,
                    max_object_bytes=1_000_000,
                    max_chunk_bytes=65_536,
                ),
                clock=lambda: flow.now_box[0],
                workspace_root=workspace,
                heartbeat_millis=50,
            )


def test_actual_worker_reads_sealed_dsm_bytes_through_real_core_and_owners(tmp_path: Path) -> None:
    """실제 소유자·실제 Core HTTP·실제 봉인 DSM 바이트로 일꾼이 결과를 만들고 Core가 검산한다."""
    import rasterio

    flow = _ReadyFlow(tmp_path)
    try:
        flow.seal()
        flow.serve_and_measure()
        assert flow.http is not None and flow.servers is not None
        http = flow.http
        decision_id = _height_decision_id(
            http, flow.current_order, flow.current_subject, key="worker-height"
        )
        issued = http.post(
            flow.requester_base,
            headers=_reader_headers("worker-job"),
            json=flow.issue_body(flow.asset_ref, decision_id),
        )
        assert issued.status_code == 200, issued.text
        job_id = issued.json()["jobId"]
        assert _run_surface_worker(flow, flow.servers.core_origin) is True
        status = http.get(f"{flow.requester_base}/{job_id}", headers=_reader_headers())
        assert status.json()["executionState"] == "COMPLETED", status.text
        assert status.json()["receipt"]["accuracyAssessed"] is False
        released = http.get(f"{flow.requester_base}/{job_id}/result", headers=_reader_headers())
        assert released.status_code == 200, released.text
        samples = released.json()["result"]["samples"]

        # 독립 기준: 봉인된 바이트를 rasterio로 직접 읽어 화소 중심 사이를 이중선형으로 보간한다.
        raw = flow.source_bytes["payload"]
        with rasterio.MemoryFile(raw) as memory, memory.open() as dataset:
            grid = dataset.read(1)
            left, top = dataset.transform.c, dataset.transform.f
            cell = dataset.transform.a
        valid = 0
        for sample in samples:
            col = (sample["x"] - left) / cell - 0.5
            row = (top - sample["y"]) / cell - 0.5
            if sample["elevationM"] is None:
                continue
            c0, r0 = int(col // 1), int(row // 1)
            fc, fr = col - c0, row - r0
            expected = (
                grid[r0, c0] * (1 - fc) * (1 - fr)
                + grid[r0, c0 + 1] * fc * (1 - fr)
                + grid[r0 + 1, c0] * (1 - fc) * fr
                + grid[r0 + 1, c0 + 1] * fc * fr
            )
            assert sample["elevationM"] == pytest.approx(float(expected), abs=1e-4)
            valid += 1
        assert valid >= 2
    finally:
        flow.close()


def _horizontal_only_geotiff(values: Any, *, transform: Any = None) -> bytes:
    """수직 좌표계 없이 수평 EPSG:5186 만 담은 DSM. 일반 벤더 내보내기와 같은 모양이다."""
    from analysis_api_local_fixture import _ORIGIN_X as origin_x
    from analysis_api_local_fixture import _ORIGIN_Y as origin_y
    from rasterio.crs import CRS
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin

    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            height=values.shape[0],
            width=values.shape[1],
            count=1,
            dtype="float64",
            crs=CRS.from_user_input("EPSG:5186"),
            transform=transform or from_origin(origin_x, origin_y, 1.0, 1.0),
        ) as dataset:
            dataset.write(values, 1)
        return memory.read()


def test_a_declared_vertical_reference_opens_height_and_the_real_worker_reads_on_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """파일에 수직 기준이 없는 DSM: 선언 전에는 막히고, 선언하면 열리고, 철회하면 숫자가 닫힌다."""
    import test_platform_core_http_integration as platform_flow

    monkeypatch.setattr(platform_flow, "_geotiff_bytes", _horizontal_only_geotiff)
    flow = _ReadyFlow(tmp_path)
    try:
        flow.seal()
        flow.serve_and_measure()
        assert flow.http is not None and flow.servers is not None
        http = flow.http
        submission_ref = build_external_reconstruction_submission_ref(
            organization_id="org-a",
            work_order_id=flow.current_order.work_order_id,
            submission_id=flow.current_subject.submission_id,
        )
        decisions = (
            f"/v1/observation-work-orders/{flow.current_order.work_order_id}/"
            f"external-reconstruction-submissions/{submission_ref}/revisions/1/"
            "use-decisions/single"
        )
        blocked = http.post(
            decisions, headers=_reader_headers("height-before"), json={"use": "HEIGHT"}
        )
        assert blocked.json()["decision"]["verdict"] == "BLOCKED", blocked.text
        assert blocked.json()["decision"]["reasons"] == ["VERTICAL_REFERENCE_UNKNOWN"]

        ledger = (
            f"/v1/sites/site-a/work-areas/{flow.area_id}/spatial-assets/{flow.asset_ref}"
            "/vertical-reference"
        )
        state = http.get(ledger, headers=_reader_headers()).json()
        assert state["observed"] is False and state["current"] is None
        declared = http.post(
            ledger + "/declarations",
            headers=_reader_headers("declare-1"),
            json={
                "datum": "orthometric_kngeoid2018",
                "unit": "metre",
                "basis": "Terra에서 정표고(KNGeoid18)로 내보냄",
                "expectedSequence": 0,
            },
        )
        assert declared.status_code == 201, declared.text

        decision_id = _height_decision_id(
            http, flow.current_order, flow.current_subject, key="height-after"
        )
        issued = http.post(
            flow.requester_base,
            headers=_reader_headers("declared-job"),
            json=flow.issue_body(flow.asset_ref, decision_id),
        )
        assert issued.status_code == 200, issued.text
        job_id = issued.json()["jobId"]
        assert _run_surface_worker(flow, flow.servers.core_origin) is True
        status = http.get(f"{flow.requester_base}/{job_id}", headers=_reader_headers())
        assert status.json()["executionState"] == "COMPLETED", status.text
        vertical = status.json()["receipt"]["verticalReference"]
        assert vertical["provenance"] == "DECLARED" and vertical["observed"] is None
        assert (
            vertical["declared"]["declarationId"] == declared.json()["declaration"]["declarationId"]
        )
        assert vertical["declared"]["unit"] == "metre"
        released = http.get(f"{flow.requester_base}/{job_id}/result", headers=_reader_headers())
        assert released.status_code == 200, released.text
        assert any(s["elevationM"] is not None for s in released.json()["result"]["samples"])

        # 철회하면 이 선언이 허락한 숫자는 더 내보내지 않고, 새 읽기도 열리지 않는다.
        withdrawn = http.post(
            ledger + "/withdrawals",
            headers=_reader_headers("withdraw-1"),
            json={"expectedSequence": 1},
        )
        assert withdrawn.status_code == 201, withdrawn.text
        closed = http.get(f"{flow.requester_base}/{job_id}/result", headers=_reader_headers())
        assert closed.status_code == 409 and "samples" not in closed.text
        again = http.post(
            flow.requester_base,
            headers=_reader_headers("declared-job-2"),
            json=flow.issue_body(flow.asset_ref, decision_id),
        )
        # 선언도 파일의 관측값도 없으니 이 엔진은 표고를 m 로 말할 근거가 없다.
        assert again.status_code == 422 and again.json()["reason"] == "UNSUPPORTED_CRS", again.text
    finally:
        flow.close()
