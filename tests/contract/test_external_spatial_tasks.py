"""Actual mounted Core handoff; generated local observations, not host acceptance."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from analysis_api_local_fixture import build_local_analysis_api_fixture
from fastapi.testclient import TestClient


def test_external_create_human_selection_external_resume_and_conflicts(tmp_path: Path) -> None:
    fixture = build_local_analysis_api_fixture(tmp_path, ai_egress_allowed=True)
    try:
        client = TestClient(fixture.app)
        base = f"/v1/sites/{fixture.site_id}/spatial-tasks"
        headers = {**fixture.mcp_client_headers(), "Idempotency-Key": "same-user-task"}
        created = client.post(base, headers=headers, json={"purpose": "OBSERVED_CHANGE"})
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["state"] == "AREA_REQUIRED"
        assert created.headers["X-KSI-External-AI-Egress"] == "ALLOWED"
        assert created.headers["Cache-Control"] == "private, no-store"
        assert (
            client.post(base, headers=headers, json={"purpose": "OBSERVED_CHANGE"}).json() == body
        )
        path = base + "/" + body["task"]["taskId"]
        options = client.get(path + "/options", headers=fixture.mcp_client_headers())
        assert options.status_code == 200, options.text
        assert options.json()["areas"][0]["workAreaId"] == fixture.work_area_id
        assert len(options.json()["observations"]) >= 2
        selected = client.post(
            path + "/selection",
            headers=fixture.operator_headers(),
            json={
                "expectedRevision": 1,
                "purpose": "OBSERVED_CHANGE",
                "workAreaId": fixture.work_area_id,
                "inputs": {
                    "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
                    "current": fixture.current.model_dump(by_alias=True, mode="json"),
                },
            },
        )
        assert selected.status_code == 200, selected.text
        assert selected.json()["state"] == "CHECK_REQUIRED"
        resumed = client.get(path, headers=fixture.mcp_client_headers())
        assert resumed.json() == selected.json()
        assert "X-KSI-External-AI-Egress" not in selected.headers
        stale = client.post(
            path + "/selection",
            headers=fixture.operator_headers(),
            json={
                "expectedRevision": 1,
                "purpose": "DAILY_TARGET",
            },
        )
        assert stale.status_code == 409
        readiness = client.post(
            path + "/readiness", headers=fixture.mcp_client_headers(), json={"expectedRevision": 2}
        )
        assert readiness.status_code == 200, readiness.text
        assert readiness.json()["readiness"] is not None
        assert client.get(path, headers={}).status_code == 401
        assert client.get(path, headers=fixture.mcp_other_area_headers()).status_code == 404
        assert (
            client.post(
                path + "/selection", headers=fixture.viewer_headers(), json={"expectedRevision": 2}
            ).status_code
            == 403
        )
        # Missing activation is a real blocker, never synthesized by the handoff.
        run = client.post(
            path + "/run", headers=fixture.mcp_client_headers(), json={"expectedRevision": 2}
        )
        assert run.status_code == 503, run.text
        site = fixture.app.state.site_store.get_scoped(fixture.site_id, fixture.organization_id)
        fixture.app.state.site_store._sites[fixture.site_id] = replace(
            site, ai_egress_allowed=False
        )
        assert client.get(path, headers=fixture.mcp_client_headers()).status_code == 403
        assert client.get(path, headers=fixture.operator_headers()).status_code == 200
    finally:
        fixture.close()


def test_unsupported_purpose_never_becomes_an_analysis(tmp_path: Path) -> None:
    fixture = build_local_analysis_api_fixture(tmp_path, ai_egress_allowed=True)
    try:
        client = TestClient(fixture.app)
        base = f"/v1/sites/{fixture.site_id}/spatial-tasks"
        created = client.post(
            base,
            headers={**fixture.mcp_client_headers(), "Idempotency-Key": "daily-target"},
            json={"purpose": "DAILY_TARGET"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["state"] == "UNSUPPORTED_PURPOSE"
        path = base + "/" + created.json()["task"]["taskId"]
        denied = client.post(
            path + "/run", headers=fixture.mcp_client_headers(), json={"expectedRevision": 1}
        )
        assert denied.status_code == 409
        assert denied.json()["detail"] == "SPATIAL_TASK_PURPOSE_UNSUPPORTED"
        assert (
            fixture.app.state.external_analysis_wiring.intents.list_for_organization(
                organization_id=fixture.organization_id
            )
            == ()
        )
    finally:
        fixture.close()


def test_task_survives_full_core_reassembly_and_run_response_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_external_analysis_api import _active_analysis_activation

    fixture = build_local_analysis_api_fixture(
        tmp_path, ai_egress_allowed=True, analysis_activation=_active_analysis_activation(tmp_path)
    )
    base = f"/v1/sites/{fixture.site_id}/spatial-tasks"
    try:
        client = TestClient(fixture.app)
        created = client.post(
            base,
            headers={**fixture.mcp_client_headers(), "Idempotency-Key": "restart-task"},
            json={
                "purpose": "OBSERVED_CHANGE",
                "workAreaId": fixture.work_area_id,
                "inputs": {
                    "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
                    "current": fixture.current.model_dump(by_alias=True, mode="json"),
                },
            },
        )
        assert created.status_code == 201, created.text
        path = base + "/" + created.json()["task"]["taskId"]
        store = fixture.app.state.spatial_tasks
        real_save = store._save

        def fail_link(record: Any) -> Any:
            if record.task.analysis_id:
                raise RuntimeError("simulated process interruption after Analysis append")
            return real_save(record)

        monkeypatch.setattr(store, "_save", fail_link)
        with pytest.raises(RuntimeError, match="simulated process interruption"):
            client.post(
                path + "/run", headers=fixture.mcp_client_headers(), json={"expectedRevision": 1}
            )
        assert (
            client.get(path, headers=fixture.mcp_client_headers()).json()["state"]
            == "ANALYSIS_PENDING"
        )
        assert (
            client.post(
                path + "/selection",
                headers=fixture.operator_headers(),
                json={
                    "expectedRevision": 2,
                    "purpose": "DAILY_TARGET",
                },
            ).json()["detail"]
            == "SPATIAL_TASK_SELECTION_LOCKED"
        )
    finally:
        fixture.close()
    restarted = build_local_analysis_api_fixture(
        tmp_path, replay_of=fixture, analysis_activation=_active_analysis_activation(tmp_path)
    )
    try:
        client = TestClient(restarted.app)
        response = client.post(
            path + "/run", headers=restarted.mcp_client_headers(), json={"expectedRevision": 1}
        )
        assert response.status_code == 200, response.text
        assert response.json()["task"]["analysisId"]
        assert (
            len(
                restarted.app.state.external_analysis_wiring.intents.list_for_organization(
                    organization_id=restarted.organization_id
                )
            )
            == 1
        )
        repeated = client.post(
            path + "/run", headers=restarted.mcp_client_headers(), json={"expectedRevision": 1}
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["task"] == response.json()["task"]
    finally:
        restarted.close()


def test_concurrent_selection_and_stale_area_recovery(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    fixture = build_local_analysis_api_fixture(tmp_path, ai_egress_allowed=True)
    try:
        client = TestClient(fixture.app)
        base = f"/v1/sites/{fixture.site_id}/spatial-tasks"
        created = client.post(
            base,
            headers={**fixture.mcp_client_headers(), "Idempotency-Key": "concurrent-task"},
            json={},
        )
        assert created.status_code == 201, created.text
        path = base + "/" + created.json()["task"]["taskId"]

        def choose(purpose: str) -> Any:
            return client.post(
                path + "/selection",
                headers=fixture.operator_headers(),
                json={
                    "expectedRevision": 1,
                    "purpose": purpose,
                    "workAreaId": fixture.work_area_id,
                },
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(choose, ["OBSERVED_CHANGE", "DAILY_TARGET"]))
        assert sorted(item.status_code for item in responses) == [200, 409]
        archived = client.post(
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/archive",
            headers=fixture.operator_headers(),
        )
        assert archived.status_code == 200
        saved = client.get(path, headers=fixture.mcp_client_headers())
        assert saved.status_code == 200, saved.text
        assert saved.json()["state"] == "SELECTION_UNAVAILABLE"
        assert saved.json()["analysis"] is None
        recovered = client.post(
            path + "/selection",
            headers=fixture.operator_headers(),
            json={
                "expectedRevision": 2,
                "purpose": "OBSERVED_CHANGE",
                "workAreaId": None,
            },
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["state"] == "AREA_REQUIRED"
    finally:
        fixture.close()


def test_task_scope_is_fresh_and_link_is_not_authority(tmp_path: Path) -> None:
    import hashlib
    from datetime import UTC, datetime, timedelta

    from fastapi import HTTPException
    from ksi_core.auth import PrincipalTokenRecord

    fixture = build_local_analysis_api_fixture(tmp_path, ai_egress_allowed=True)
    try:
        client = TestClient(fixture.app)
        base = f"/v1/sites/{fixture.site_id}/spatial-tasks"
        headers = {**fixture.mcp_client_headers(), "Idempotency-Key": "scope-task"}
        created = client.post(base, headers=headers, json={"workAreaId": fixture.work_area_id})
        assert created.status_code == 201, created.text
        task_id = created.json()["task"]["taskId"]
        path = base + "/" + task_id
        registry = fixture.app.state.auth_registry
        original = registry.resolve(fixture._mcp_client_token)
        token_digest = hashlib.sha256(fixture._mcp_client_token.encode()).hexdigest()
        registry._by_digest[token_digest] = PrincipalTokenRecord(
            token_sha256=token_digest,
            principal=replace(original, principal_id="other-client-same-scope"),
        )
        assert client.get(path, headers=headers).status_code == 404
        registry._by_digest[token_digest] = PrincipalTokenRecord(
            token_sha256=token_digest,
            principal=replace(original, allowed_work_area_ids=frozenset({"wa-no-longer-granted"})),
        )
        assert client.get(path, headers=headers).status_code == 404
        registry._by_digest[token_digest] = PrincipalTokenRecord(
            token_sha256=token_digest, principal=original
        )
        with pytest.raises(HTTPException) as expired:
            fixture.app.state.spatial_tasks.read(
                original, fixture.site_id, task_id, datetime.now(UTC) + timedelta(days=8)
            )
        assert expired.value.status_code == 410
        assert (
            client.post(base, headers=headers, json={"purpose": "DAILY_TARGET"}).status_code == 409
        )
        for mutation in ["selection", "run", "readiness"]:
            assert (
                client.post(path + "/" + mutation, json={"expectedRevision": 1}).status_code == 401
            )
    finally:
        fixture.close()


def test_unknown_task_event_refuses_full_core_restart(tmp_path: Path) -> None:
    from ksi_core.domains.external.spatial_tasks import SpatialTaskRecoveryError

    fixture = build_local_analysis_api_fixture(tmp_path, ai_egress_allowed=True)
    try:
        fixture.app.state.spatial_tasks.journal.append({"kind": "forged-selection", "version": 2})
    finally:
        fixture.close()
    with pytest.raises(SpatialTaskRecoveryError):
        build_local_analysis_api_fixture(tmp_path, replay_of=fixture)


@pytest.mark.parametrize(
    "origin",
    [
        "http://example.test",
        "https://user:secret@example.test",
        "https://example.test/path",
        "https://example.test/?token=secret",
        "https://example.test/#fragment",
        "https://example.test\\@evil.test",
    ],
)
def test_task_console_origin_is_operator_config_not_model_redirect(
    tmp_path: Path, origin: str
) -> None:
    from ksi_analysis_mcp.config import AdapterConfig, AdapterConfigurationError

    token = tmp_path / "token"
    token.write_text("synthetic-token")
    token.chmod(0o600)
    with pytest.raises(AdapterConfigurationError):
        AdapterConfig.from_values(
            core_origin="http://127.0.0.1:8080", token_file=str(token), console_origin=origin
        )


def test_task_adapter_checks_machine_ack_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from ksi_analysis_mcp.config import AdapterConfig
    from ksi_analysis_mcp.core_client import CoreAdapterError, CoreAnalysisClient

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        # A human-token read may be valid HTTP but is not a machine-channel acknowledgment.
        return httpx.Response(200, json={"items": []})

    monkeypatch.setattr(
        AdapterConfig,
        "new_http_client",
        lambda self: httpx.AsyncClient(
            base_url=self.core_origin, transport=httpx.MockTransport(handler)
        ),
    )
    token = tmp_path / "token"
    token.write_text("synthetic-token")
    token.chmod(0o600)
    client = CoreAnalysisClient(
        AdapterConfig.from_values(
            core_origin="http://127.0.0.1:8080",
            token_file=str(token),
            console_origin="http://localhost:3000",
        )
    )
    with pytest.raises(CoreAdapterError, match="CORE_EGRESS_ACKNOWLEDGMENT_MISSING"):
        asyncio.run(
            client.invoke(
                "ksi_create_spatial_task",
                {
                    "siteId": "site-a",
                    "idempotencyKey": "caller-key",
                    "request": {"purpose": "CLARIFY"},
                },
            )
        )
    assert calls == ["GET"]


def test_published_task_schema_is_self_contained_and_matches_models() -> None:
    import importlib.util
    import json

    from jsonschema import Draft202012Validator
    from ksi_event_contracts.external_spatial_task import CreateSpatialTaskV1

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "task_schema_generator", root / "tools/generate_spatial_task_schema.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    published = json.loads((root / "contracts/schemas/external-spatial-task.v1.json").read_text())
    assert module.schema() == published
    Draft202012Validator.check_schema(published)
    validator = Draft202012Validator(
        {"$defs": published["$defs"], "$ref": "#/$defs/CreateSpatialTaskV1"}
    )
    validator.validate(CreateSpatialTaskV1().model_dump(mode="json", by_alias=True))
    assert list(validator.iter_errors({"purpose": "DAILY_TARGET", "organizationId": "caller"}))


def test_task_reserves_terminal_revision_before_analysis_create(tmp_path: Path) -> None:
    from test_external_analysis_api import _active_analysis_activation

    fixture = build_local_analysis_api_fixture(
        tmp_path, ai_egress_allowed=True, analysis_activation=_active_analysis_activation(tmp_path)
    )
    try:
        client = TestClient(fixture.app)
        base = f"/v1/sites/{fixture.site_id}/spatial-tasks"
        selection = {
            "purpose": "OBSERVED_CHANGE",
            "workAreaId": fixture.work_area_id,
            "inputs": {
                "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
                "current": fixture.current.model_dump(by_alias=True, mode="json"),
            },
        }
        created = client.post(
            base,
            headers={**fixture.mcp_client_headers(), "Idempotency-Key": "terminal-slot-limit"},
            json=selection,
        )
        assert created.status_code == 201
        path = base + "/" + created.json()["task"]["taskId"]
        for revision in range(1, 127):
            response = client.post(
                path + "/selection",
                headers=fixture.mcp_client_headers(),
                json={**selection, "expectedRevision": revision},
            )
            assert response.status_code == 200, response.text
        denied = client.post(
            path + "/run", headers=fixture.mcp_client_headers(), json={"expectedRevision": 127}
        )
        assert denied.status_code == 409, denied.text
        assert denied.json()["detail"] == "SPATIAL_TASK_REVISION_LIMIT"
        assert not client.get(path, headers=fixture.mcp_client_headers()).json()["task"][
            "executionRequested"
        ]
        assert (
            fixture.app.state.external_analysis_wiring.intents.list_for_organization(
                organization_id=fixture.organization_id
            )
            == ()
        )
    finally:
        fixture.close()


@pytest.mark.parametrize("spatial_case", ["VALID", "OVERLAPPING_CURRENT_NODATA_CELL"])
def test_stdio_task_map_handoff_runs_actual_inspected_rasters(
    tmp_path: Path, spatial_case: str
) -> None:
    import asyncio
    import sys

    from ksi_processing_controller.external_analysis_core_client import ExternalAnalysisCoreClient
    from ksi_processing_controller.external_analysis_worker import (
        ProcessingWorkerRuntimeIdentityV1,
        run_once,
    )
    from ksi_processing_controller.external_object_streams import (
        ExternalObjectTransportPolicyV1,
        TrustedObjectEndpointV1,
    )
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from test_analysis_mcp_stdio import _known_checkout_stdio_args
    from test_external_analysis_api import _active_analysis_activation
    from test_external_analysis_real_inspection_lane_integration import _CoreAndObjectServers
    from test_external_analysis_spatial_blockers_integration import (
        _inspect_both_epochs_with_actual_lane,
    )

    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        real_inspection=True,
        ai_egress_allowed=True,
        current_dsm_spatial_case=spatial_case,
        analysis_activation=_active_analysis_activation(tmp_path),
    )
    try:
        with _CoreAndObjectServers(fixture) as servers:
            reports = _inspect_both_epochs_with_actual_lane(
                fixture,
                core_origin=servers.core_origin,
                object_origin=servers.object_origin,
                tmp_path=tmp_path,
            )
            assert len(reports) == 2
            token_file = tmp_path / "task-mcp-token"
            token_file.write_text(
                fixture.mcp_client_headers()["Authorization"].removeprefix("Bearer ")
            )
            token_file.chmod(0o600)
            runtime = fixture.app.state.external_analysis_wiring.facade._assessments._runtime
            envelope = fixture.app.state.external_analysis_wiring.calculations._resource_envelope
            worker = ExternalAnalysisCoreClient(
                base_url=servers.core_origin,
                worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
                worker_instance_id="spatial-task-test-worker",
            )

            async def exercise() -> None:
                parameters = StdioServerParameters(
                    command=sys.executable,
                    args=_known_checkout_stdio_args(),
                    env={
                        "KSI_ANALYSIS_MCP_CORE_ORIGIN": servers.core_origin,
                        "KSI_ANALYSIS_MCP_TOKEN_FILE": str(token_file),
                        "KSI_ANALYSIS_MCP_CONSOLE_ORIGIN": "http://127.0.0.1:3099",
                    },
                )
                async with (
                    stdio_client(parameters) as (read, write),
                    ClientSession(read, write) as session,
                ):
                    await session.initialize()

                    async def call(name: str, args: dict[str, Any]) -> Any:
                        response = await session.call_tool(name, args)
                        assert not response.is_error, response
                        return response.structured_content

                    sites = await call("ksi_list_spatial_task_sites", {})
                    assert sites["items"][0]["siteId"] == fixture.site_id
                    created = await call(
                        "ksi_create_spatial_task",
                        {
                            "siteId": fixture.site_id,
                            "idempotencyKey": "natural-user-request",
                            "request": {"purpose": "OBSERVED_CHANGE"},
                        },
                    )
                    task_id = created["task"]["taskId"]
                    assert created["selectionUrl"].startswith("http://127.0.0.1:3099/sites/")
                    arguments = {"siteId": fixture.site_id, "taskId": task_id}
                    options = await call("ksi_get_spatial_task_options", arguments)
                    assert len(options["observations"]) == 2
                    # Human Console BFF uses this exact authenticated Core transition.
                    async with httpx.AsyncClient(
                        base_url=servers.core_origin, trust_env=False
                    ) as human:
                        selected = await human.post(
                            f"/v1/sites/{fixture.site_id}/spatial-tasks/{task_id}/selection",
                            headers=fixture.operator_headers(),
                            json={
                                "expectedRevision": 1,
                                "purpose": "OBSERVED_CHANGE",
                                "workAreaId": fixture.work_area_id,
                                "inputs": {
                                    "baseline": fixture.baseline.model_dump(
                                        mode="json", by_alias=True
                                    ),
                                    "current": fixture.current.model_dump(
                                        mode="json", by_alias=True
                                    ),
                                },
                            },
                        )
                        assert selected.status_code == 200, selected.text
                        resumed = await call("ksi_get_spatial_task", arguments)
                        assert resumed["task"] == selected.json()["task"]
                        journals = {p: p.read_bytes() for p in tmp_path.glob("*.jsonl")}
                        checked = await call(
                            "ksi_check_spatial_task",
                            {**arguments, "request": {"expectedRevision": 2}},
                        )
                        assert checked["readiness"]["coverageCheck"] == "REQUIRES_WORKER_VALIDATION"
                        assert journals == {p: p.read_bytes() for p in tmp_path.glob("*.jsonl")}
                        started = await call(
                            "ksi_run_spatial_task",
                            {**arguments, "request": {"expectedRevision": 2}},
                        )
                        assert started["task"]["analysisId"]
                        assert await asyncio.to_thread(
                            run_once,
                            worker,
                            ProcessingWorkerRuntimeIdentityV1(
                                worker_executable_digest=runtime.worker_executable_digest,
                                worker_build_digest=runtime.worker_build_digest,
                                runtime_image_version=runtime.runtime_image_version,
                                runtime_image_oci_digest=runtime.runtime_image_oci_digest,
                                dependency_lock_digest=runtime.dependency_lock_digest,
                            ),
                            ExternalObjectTransportPolicyV1(
                                endpoints=(
                                    TrustedObjectEndpointV1(
                                        origin=servers.object_origin, addresses=("127.0.0.1",)
                                    ),
                                ),
                                max_header_bytes=16384,
                                max_object_bytes=envelope.max_input_bytes,
                                max_chunk_bytes=min(65536, envelope.max_input_bytes),
                            ),
                        )
                        finished = await call("ksi_get_spatial_task", arguments)
                        direct = await human.get(
                            f"/v2/sites/{fixture.site_id}/analyses/{started['task']['analysisId']}",
                            headers=fixture.operator_headers(),
                        )
                        assert finished["analysis"] == direct.json()
                        assert finished["analysis"]["executionState"] == (
                            "COMPLETED" if spatial_case == "VALID" else "FAILED"
                        )
                        assert (finished["analysis"]["result"] is not None) == (
                            spatial_case == "VALID"
                        )

            try:
                asyncio.run(exercise())
            finally:
                worker.close()
    finally:
        fixture.close()
