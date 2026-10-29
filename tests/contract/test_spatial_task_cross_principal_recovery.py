"""One reserved Analysis remains one intent across a permitted handoff and restart."""

import socket
from pathlib import Path
from typing import Any

import pytest
from analysis_api_local_fixture import build_local_analysis_api_fixture
from fastapi.testclient import TestClient
from test_external_analysis_api import _active_analysis_activation


def test_machine_run_recovers_as_human_after_interrupted_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The fixture is an in-process Core app; never connect to a host service.
    real_connect = socket.socket.connect

    def no_ip_connect(sock: socket.socket, address: Any) -> Any:
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("this in-process regression must not use network sockets")
        return real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", no_ip_connect)
    fixture = build_local_analysis_api_fixture(
        tmp_path, ai_egress_allowed=True, analysis_activation=_active_analysis_activation(tmp_path)
    )
    base = f"/v1/sites/{fixture.site_id}/spatial-tasks"
    try:
        client = TestClient(fixture.app)
        created = client.post(
            base,
            headers={**fixture.mcp_client_headers(), "Idempotency-Key": "cross-actor-recovery"},
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
        task_id = created.json()["task"]["taskId"]
        path = f"{base}/{task_id}"
        store = fixture.app.state.spatial_tasks
        save = store._save

        def interrupt_link(record: Any) -> Any:
            if record.task.analysis_id:
                raise RuntimeError("simulated interruption after Analysis append")
            return save(record)

        monkeypatch.setattr(store, "_save", interrupt_link)
        with pytest.raises(RuntimeError, match="simulated interruption after Analysis append"):
            client.post(
                path + "/run", headers=fixture.mcp_client_headers(), json={"expectedRevision": 1}
            )
        intents = fixture.app.state.external_analysis_wiring.intents.list_for_organization(
            organization_id=fixture.organization_id
        )
        assert len(intents) == 1
        original_analysis_id = intents[0].analysis_id
        pending = client.get(path, headers=fixture.mcp_client_headers())
        assert pending.json()["state"] == "ANALYSIS_PENDING"
    finally:
        fixture.close()

    restarted = build_local_analysis_api_fixture(
        tmp_path, replay_of=fixture, analysis_activation=_active_analysis_activation(tmp_path)
    )
    try:
        client = TestClient(restarted.app)
        # A different machine principal outside the retained scope cannot resume it.
        denied = client.post(
            path + "/run", headers=restarted.mcp_other_area_headers(), json={"expectedRevision": 1}
        )
        assert denied.status_code == 404
        # An independently authorized human can resume the same reserved task.
        recovered = client.post(
            path + "/run", headers=restarted.operator_headers(), json={"expectedRevision": 1}
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["task"]["analysisId"] == original_analysis_id
        intents = restarted.app.state.external_analysis_wiring.intents.list_for_organization(
            organization_id=restarted.organization_id
        )
        assert len(intents) == 1
        assert intents[0].analysis_id == original_analysis_id
        replay = client.post(
            path + "/run", headers=restarted.mcp_client_headers(), json={"expectedRevision": 1}
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["task"]["analysisId"] == original_analysis_id
    finally:
        restarted.close()
