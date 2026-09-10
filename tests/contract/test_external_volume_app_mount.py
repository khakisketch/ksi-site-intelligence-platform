"""Assembled external-volume routes retain Core authentication and closed authority."""

from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from ksi_core.app import create_app
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_relative_volumes import ExternalRelativeVolumeInputCapabilityIssuer
from test_api_contract_sync import (
    _max_assembly,
    _max_assembly_arguments,
    _seed_max_assembly_site_and_work_order,
)


def test_assembled_volume_queue_requires_authentication(tmp_path: Path) -> None:
    app = _max_assembly(tmp_path)
    with TestClient(app) as client:
        response = client.get("/v1/internal/external-validation/relative-volumes")
    assert response.status_code == 401


def test_human_cannot_claim_assembled_volume_worker_surface(tmp_path: Path) -> None:
    app = _max_assembly(tmp_path)
    with TestClient(app) as client:
        response = client.get(
            "/v1/internal/external-validation/relative-volumes",
            headers={"Authorization": "Bearer contract-sync-test-token"},
        )
    assert response.status_code == 403


def test_assembled_volume_issue_stays_closed_without_mapping_authority(tmp_path: Path) -> None:
    arguments = _max_assembly_arguments(tmp_path)
    work_order_id = _seed_max_assembly_site_and_work_order(arguments)
    app = create_app(**arguments)
    with TestClient(app) as client:
        response = client.post(
            f"/v1/observation-work-orders/{work_order_id}/relative-volume-requests",
            json={"decisionRef": "unavailable"},
            headers={
                "Authorization": "Bearer contract-sync-test-token",
                "Idempotency-Key": "closed-authority-test",
            },
        )
    assert response.status_code == 422
    assert response.json()["verdict"] == "AUTHORITY_UNAVAILABLE"
    assert app.state.external_relative_volume_store.journal_records() == ()


def test_volume_capability_issuer_cannot_mount_without_store() -> None:
    with pytest.raises(ValueError, match="durable request store"):
        create_app(
            external_volume_input_capability_issuer=cast(
                ExternalRelativeVolumeInputCapabilityIssuer, lambda *_args, **_kwargs: None
            )
        )


def test_volume_cannot_mount_with_a_different_currentness_coordinator(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="coordinator"):
        _max_assembly(tmp_path, volume_coordinator=ExternalAuthorityCurrentnessCoordinator())


def test_result_workflow_cannot_mount_without_its_durable_volume_graph(tmp_path: Path) -> None:
    from external_product_loop_fixture import build_graph, seed_original

    graph = build_graph(tmp_path, seed_original(tmp_path))
    try:
        with pytest.raises(ValueError, match="result workflow"):
            create_app(external_result_workflow_service=graph.service)
    finally:
        graph.close()


def test_external_workflow_openapi_uses_defined_authentication_schemes() -> None:
    import yaml

    document = yaml.safe_load(Path("contracts/api/openapi-core.yaml").read_text())
    known = set(document["components"]["securitySchemes"])
    for path, operations in document["paths"].items():
        if "relative-volume" not in path and not path.startswith(
            (
                "/v1/external-result-reviews",
                "/v1/external-reobservation-proposals",
            )
        ):
            continue
        for operation in operations.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            assert operation["security"], path
            assert all(set(requirement) <= known for requirement in operation["security"]), path
