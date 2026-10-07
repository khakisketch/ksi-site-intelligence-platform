"""Explicit external-only platform Core assembly (Task 2).

The platform profile boots only Site/WorkArea/roster/WorkOrder stores plus the
existing external graphs. It never imports acquisition, Mission/planning,
capability/device, Copilot runtime, or the legacy managed assembly — even when
the HTTP surface behaves correctly, a polluted interpreter would hide that
coupling, so boot isolation is proven in a fresh subprocess with a deny-hook.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from textwrap import dedent
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.domains.sites.observation_work_orders import build_observation_work_order_router
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import DigestBoundUploadCapability, ObjectStorageObservation
from ksi_mission_contracts.models import SiteFrame

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = (
    REPOSITORY_ROOT / "services/core/src",
    REPOSITORY_ROOT / "packages/event-contracts/src",
    REPOSITORY_ROOT / "packages/domain/src",
    REPOSITORY_ROOT / "packages/geo-core/src",
    REPOSITORY_ROOT / "packages/mission-contracts/src",
    REPOSITORY_ROOT / "packages/mission-planning/src",
)

_DENIED_PREFIXES = (
    "ksi_core.acquisition",
    "ksi_mission_contracts",
    "ksi_mission_planning",
    "ksi_core.capability",
    "ksi_core.device_attestation",
    "ksi_core.copilot",
    "ksi_core.copilot_conversations",
    "ksi_core.copilot_openai",
    "ksi_core.composition.assembly",
)

_NOW = datetime(2026, 10, 7, tzinfo=UTC)
_FRAME = SiteFrame(
    crs="EPSG:5186",
    vertical_datum="KNGeoid2018",
    unit="meter",
    transform_version="1.0.0",
)
_POLYGON = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [0.0, 0.0]]],
}

_TOKEN_A = "platform-operator-a"  # noqa: S105 -- deterministic test credential
_TOKEN_B = "platform-operator-b"  # noqa: S105 -- deterministic test credential
_SCOPED_TOKEN = "platform-scoped-a"  # noqa: S105 -- deterministic test credential


class _Storage:
    """In-memory evidence storage satisfying the digest-bound observation ports."""

    def __init__(self) -> None:
        self.objects: dict[str, ObjectStorageObservation] = {}

    def presigned_put(self, object_key: str, *, content_type: str, ttl: Any) -> str:
        del content_type, ttl
        return f"https://storage.invalid/put/{object_key}"

    def presigned_get(self, object_key: str, *, ttl: Any) -> str:
        del ttl
        return f"https://storage.invalid/get/{object_key}"

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        self.objects[object_key] = ObjectStorageObservation(
            object_key=object_key,
            exists=True,
            size_bytes=len(data),
            sha256="sha256:" + hashlib.sha256(data).hexdigest(),
            content_type=content_type,
        )

    def get_bytes(self, object_key: str) -> bytes:
        raise NotImplementedError

    def delete(self, object_key: str) -> None:
        self.objects.pop(object_key, None)

    def presigned_put_bound_digest(
        self, object_key: str, *, content_type: str, content_digest: str, ttl: Any
    ) -> DigestBoundUploadCapability:
        del ttl
        return DigestBoundUploadCapability(
            upload_url=f"https://storage.invalid/put/{object_key}",
            required_headers={
                "Content-Type": content_type,
                "x-amz-checksum-sha256": content_digest,
            },
        )

    def observe_object(self, object_key: str) -> ObjectStorageObservation:
        return self.objects.get(
            object_key, ObjectStorageObservation(object_key=object_key, exists=False)
        )


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _record(
    token: str,
    principal_id: str,
    organization_id: str,
    role: Role = Role.FIELD_OPERATOR,
    *,
    allowed_site_ids: frozenset[str] | None = None,
    allowed_work_area_ids: frozenset[str] | None = None,
) -> PrincipalTokenRecord:
    return PrincipalTokenRecord(
        token_sha256=_digest(token),
        principal=Principal(
            principal_id=principal_id,
            kind=PrincipalKind.OPERATOR,
            role=role,
            device_id=None,
            organization_id=organization_id,
            allowed_site_ids=allowed_site_ids,
            allowed_work_area_ids=allowed_work_area_ids,
        ),
    )


def _auth_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            _record(_TOKEN_A, "operator-a", "org-a", Role.ADMIN),
            _record(_TOKEN_B, "operator-b", "org-b", Role.ADMIN),
            _record(
                _SCOPED_TOKEN,
                "scoped-a",
                "org-a",
                Role.FIELD_OPERATOR,
                allowed_site_ids=frozenset({"site-b"}),
            ),
        ]
    )


def _assemble(
    tmp_path: Path,
    trace: list[str],
    opened: list[Any],
    *,
    auth_registry: AuthRegistry | None = None,
    storage: Any = None,
    **kwargs: Any,
) -> FastAPI:
    from ksi_core.composition.platform_assembly import assemble_platform_app

    if auth_registry is None:
        auth_registry = _auth_registry()
    if storage is None:
        storage = _Storage()

    def journal(name: str) -> DurableJournal:
        trace.append(name)
        item = DurableJournal(tmp_path / name)
        opened.append(item)
        return item

    try:
        return assemble_platform_app(
            tmp_path,
            journal=journal,
            opened=opened,
            auth_registry=auth_registry,
            evidence_storage=storage,
            **kwargs,
        )
    except BaseException:
        for item in opened:
            item.close()
        raise


def _seed_site_and_area(
    app: Any, *, site_id: str = "site-a", organization_id: str = "org-a"
) -> str:
    site_result = app.state.site_store.register(
        site_id,
        site_id,
        _FRAME,
        organization_id=organization_id,
        actor="fixture",
        now=_NOW,
    )
    assert site_result.record is not None
    area_result = app.state.work_area_store.register(
        site_id,
        name="platform zone",
        polygon=dict(_POLYGON),
        crs="EPSG:5186",
        supersedes=None,
        actor="fixture",
        now=_NOW,
    )
    assert area_result.work_area is not None
    return area_result.work_area.work_area_id


def _headers(token: str = _TOKEN_A, *, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _walk_routes(container: Any) -> list[Any]:
    """Unfold ``_IncludedRouter`` wrappers (FastAPI 0.140) to the real routes.

    Same established pattern as ``test_api_contract_sync._walk_routes``:
    ``app.routes`` alone hides conditionally included routers.
    """
    found: list[Any] = []
    for route in getattr(container, "routes", None) or []:
        if getattr(route, "methods", None) and getattr(route, "path", None):
            found.append(route)
        inner = getattr(route, "original_router", None)
        if inner is not None:
            found.extend(_walk_routes(inner))
    return found


def _run_python(script: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(root) for root in SOURCE_ROOTS] + ([existing] if existing else [])
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=120,
    )


def _blocker_prelude(denied: tuple[str, ...]) -> str:
    return dedent(
        """
            import sys

            _DENIED_PREFIXES = %r

            class _DenyPrefixes:
                def find_module(self, name, path=None):
                    if name in _DENIED_PREFIXES or any(
                        name.startswith(prefix + ".") for prefix in _DENIED_PREFIXES
                    ):
                        raise ImportError(f"platform isolation probe denies {name}")
                    return None

            sys.meta_path.insert(0, _DenyPrefixes())
            for _module in list(sys.modules):
                assert _module not in _DENIED_PREFIXES and not any(
                    _module.startswith(prefix + ".") for prefix in _DENIED_PREFIXES
                ), _module
            """
    ) % (denied,)


def test_platform_boot_imports_no_managed_flight_or_legacy_assembly() -> None:
    script = _blocker_prelude(_DENIED_PREFIXES) + dedent(
        """
        import hashlib
        import sys
        import tempfile
        from pathlib import Path

        from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
        from ksi_core.composition.platform_assembly import assemble_platform_app
        from ksi_core.durable_journal import DurableJournal
        from ksi_core.evidence import DigestBoundUploadCapability, ObjectStorageObservation

        denied = %r

        def _walk_routes(container):
            found = []
            for route in getattr(container, "routes", None) or []:
                if getattr(route, "methods", None) and getattr(route, "path", None):
                    found.append(route)
                inner = getattr(route, "original_router", None)
                if inner is not None:
                    found.extend(_walk_routes(inner))
            return found

        class _StubStorage:
            def presigned_put(self, object_key, *, content_type, ttl):
                return "https://storage.invalid/put/" + object_key

            def presigned_get(self, object_key, *, ttl):
                return "https://storage.invalid/get/" + object_key

            def put_bytes(self, object_key, data, *, content_type):
                raise NotImplementedError

            def get_bytes(self, object_key):
                raise NotImplementedError

            def delete(self, object_key):
                pass

            def presigned_put_bound_digest(
                self, object_key, *, content_type, content_digest, ttl
            ):
                return DigestBoundUploadCapability(
                    upload_url="https://storage.invalid/put/" + object_key,
                    required_headers={"Content-Type": content_type},
                )

            def observe_object(self, object_key):
                return ObjectStorageObservation(object_key=object_key, exists=False)

        with tempfile.TemporaryDirectory() as data_dir:
            root = Path(data_dir)
            opened = []

            def journal(name):
                item = DurableJournal(root / name)
                opened.append(item)
                return item

            registry = AuthRegistry(
                [
                    PrincipalTokenRecord(
                        token_sha256=hashlib.sha256(b"probe-token").hexdigest(),
                        principal=Principal(
                            principal_id="probe",
                            kind=PrincipalKind.OPERATOR,
                            role=Role.ADMIN,
                            device_id=None,
                            organization_id="org-probe",
                        ),
                    )
                ]
            )
            app = assemble_platform_app(
                root,
                journal=journal,
                opened=opened,
                auth_registry=registry,
                evidence_storage=_StubStorage(),
            )
            try:
                paths = sorted({route.path for route in _walk_routes(app)})
                assert "/v1/sites/{site_id}/observation-work-orders" in paths
                assert "/capabilities" not in paths
            finally:
                for item in opened:
                    item.close()
            for name in denied:
                assert name not in sys.modules, name
                assert not any(
                    module == name or module.startswith(name + ".") for module in sys.modules
                ), name
        """
    ) % (_DENIED_PREFIXES,)
    completed = _run_python(script)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_platform_graph_opens_only_external_journals(tmp_path: Path) -> None:
    from ksi_core.composition.platform_graph import build_platform_graph

    trace: list[str] = []
    opened: list[Any] = []

    def journal(name: str) -> DurableJournal:
        trace.append(name)
        item = DurableJournal(tmp_path / name)
        opened.append(item)
        return item

    storage = _Storage()
    try:
        graph = build_platform_graph(
            data_dir=tmp_path,
            journal=journal,
            opened=opened,
            evidence_storage=storage,
        )
    finally:
        for item in opened:
            item.close()
    assert trace == [
        "sites.jsonl",
        "work-areas.jsonl",
        "external-reconstruction.jsonl",
        "external-evidence.jsonl",
        "external-validation-policy.jsonl",
        "external-evidence-validations.jsonl",
        "external-sanitized-display-artifacts.jsonl",
        "external-artifact-inspections.jsonl",
        "external-use-decisions.jsonl",
        "organization-work-roster.jsonl",
        "observation-work-orders.jsonl",
        "work-inbox.jsonl",
    ]
    for name in trace:
        lowered = name.lower()
        assert "mission" not in lowered, name
        assert "edge" not in lowered, name
        assert "flight" not in lowered, name
        assert "acquisition" not in lowered, name
        assert "processing" not in lowered, name
        assert "source-media" not in lowered, name
        assert "capability" not in lowered, name
        assert "device" not in lowered, name
        assert "copilot" not in lowered, name
    assert graph.storage is storage
    assert graph.coordinator is graph.work_orders.operations_coordinator
    assert graph.roster.coordinator is graph.coordinator
    assert graph.sites is not None and graph.work_areas is not None
    assert graph.external.reconstruction_store is not None
    assert graph.external.artifact_inspection_store is not None
    assert graph.external.use_evaluator is not None
    # No workflow configured: result services stay absent rather than mocked.
    assert graph.workflow.result_workflow_service is None
    assert graph.workflow.result_read_projector is None
    assert graph.analysis is None
    assert graph.data is None
    assert graph.external.proposal_authority is None
    assert graph.inbox.uses_exact_dependencies(
        work_orders=graph.work_orders,
        roster=graph.roster,
        report_resolver=None,
    )


def test_platform_requires_auth_registry_and_storage(tmp_path: Path) -> None:
    from ksi_core.composition.platform_app import create_platform_app
    from ksi_core.composition.platform_assembly import assemble_platform_app
    from ksi_core.composition.platform_graph import build_platform_graph

    trace: list[str] = []
    opened: list[Any] = []

    def journal(name: str) -> DurableJournal:
        trace.append(name)
        item = DurableJournal(tmp_path / name)
        opened.append(item)
        return item

    try:
        with pytest.raises(ValueError, match="auth_registry"):
            assemble_platform_app(
                tmp_path,
                journal=journal,
                opened=opened,
                auth_registry=None,  # type: ignore[arg-type]
                evidence_storage=_Storage(),
            )
        with pytest.raises(ValueError, match="evidence_storage"):
            build_platform_graph(
                data_dir=tmp_path,
                journal=journal,
                opened=opened,
                evidence_storage=None,  # type: ignore[arg-type]
            )
        graph = build_platform_graph(
            data_dir=tmp_path,
            journal=journal,
            opened=opened,
            evidence_storage=_Storage(),
        )
        with pytest.raises(ValueError, match="auth_registry"):
            create_platform_app(graph=graph, auth_registry=None)
    finally:
        for item in opened:
            item.close()


def test_restricted_router_omits_only_managed_mutation_routes(tmp_path: Path) -> None:
    from ksi_core.observation_work_orders import ObservationWorkOrderStore
    from starlette.routing import Route

    store_journal = DurableJournal(tmp_path / "observation-work-orders.jsonl")
    store = ObservationWorkOrderStore(
        store_journal,
        site_exists=lambda site_id, organization_id: True,
    )
    try:
        legacy = build_observation_work_order_router(store)
        legacy_paths = {
            (route.path, next(iter(route.methods)))
            for route in legacy.routes
            if isinstance(route, Route) and route.methods is not None
        }
        restricted = build_observation_work_order_router(store, external_only=True)
        restricted_paths = {
            (route.path, next(iter(route.methods)))
            for route in restricted.routes
            if isinstance(route, Route) and route.methods is not None
        }
    finally:
        store_journal.close()

    omitted = legacy_paths - restricted_paths
    assert omitted == {
        ("/v1/sites/{site_id}/observation-schedules", "POST"),
        ("/v1/observation-work-orders/{work_order_id}/approve", "POST"),
        ("/v1/observation-work-orders/{work_order_id}/reobservation-drafts", "POST"),
        ("/v1/reobservation-drafts/{draft_id}/approve", "POST"),
    }
    retained = {
        ("/v1/sites/{site_id}/observation-schedules", "GET"),
        ("/v1/sites/{site_id}/observation-work-orders", "POST"),
        ("/v1/sites/{site_id}/observation-work-orders", "GET"),
        ("/v1/observation-work-orders", "GET"),
        ("/v1/observation-work-orders/{work_order_id}", "GET"),
        ("/v1/observation-work-orders/{work_order_id}/operations", "GET"),
        ("/v1/observation-work-order-operations", "GET"),
        ("/v1/observation-work-orders/{work_order_id}/operations/assignment", "POST"),
        ("/v1/observation-work-orders/{work_order_id}/operations/due-date", "PUT"),
        ("/v1/observation-work-orders/{work_order_id}/operations/close", "POST"),
        ("/v1/observation-work-orders/{work_order_id}/operations/reopen", "POST"),
        ("/v1/observation-work-orders/{work_order_id}/reobservation-drafts", "GET"),
    }
    assert retained <= restricted_paths


def test_platform_route_inventory_has_no_managed_or_flight_surface(tmp_path: Path) -> None:
    trace: list[str] = []
    opened: list[Any] = []
    app = _assemble(tmp_path, trace, opened)
    try:
        inventory = {(route.path, next(iter(route.methods))) for route in _walk_routes(app)}
        paths = {path for path, _ in inventory}
        assert ("/health", "GET") in inventory
        assert ("/ready", "GET") in inventory
        assert ("/metrics", "GET") in inventory
        assert ("/v1/auth/whoami", "GET") in inventory
        assert ("/v1/sites/{site_id}/observation-work-orders", "POST") in inventory
        assert ("/v1/sites/{site_id}/observation-schedules", "POST") not in inventory
        assert ("/v1/observation-work-orders/{work_order_id}/approve", "POST") not in inventory
        assert (
            "/v1/observation-work-orders/{work_order_id}/reobservation-drafts",
            "POST",
        ) not in inventory
        assert ("/v1/reobservation-drafts/{draft_id}/approve", "POST") not in inventory
        assert "/capabilities" not in paths
        assert not any(path.startswith("/v1/missions") for path in paths)
        assert not any("edge" in path for path in paths)
        assert not any("flight" in path for path in paths)
        assert not any("acquisition" in path for path in paths)
        assert not any("copilot" in path for path in paths)
        assert not any("processing-job" in path for path in paths)
        assert not any("source-media" in path for path in paths)
        assert not any("comparison" in path for path in paths)
        assert app.state.capability_authority_store is None
        assert app.state.external_authority_currentness is app.state.site_store.coordinator
    finally:
        for item in opened:
            item.close()


def _create_external_order(
    client: TestClient, area_id: str, *, key: str, site_id: str = "site-a", token: str = _TOKEN_A
) -> dict[str, Any]:
    response = client.post(
        f"/v1/sites/{site_id}/observation-work-orders",
        headers=_headers(token, key=key),
        json={
            "name": "외부 관측 운영",
            "workAreaIds": [area_id],
            "scheduleId": None,
            "executionMode": "EXTERNAL_RECONSTRUCTION",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_external_create_keeps_idempotency_and_rejects_managed_mode(tmp_path: Path) -> None:
    trace: list[str] = []
    opened: list[Any] = []
    app = _assemble(tmp_path, trace, opened)
    try:
        area_id = _seed_site_and_area(app)
        with TestClient(app) as client:
            created = _create_external_order(client, area_id, key="external-first")
            order_id = created["workOrderId"]
            assert created["executionMode"] == "EXTERNAL_RECONSTRUCTION"
            repeated = _create_external_order(client, area_id, key="external-first")
            assert repeated["workOrderId"] == order_id
            conflict = client.post(
                "/v1/sites/site-a/observation-work-orders",
                headers=_headers(_TOKEN_A, key="external-first"),
                json={
                    "name": "다른 관측 운영",
                    "workAreaIds": [area_id],
                    "scheduleId": None,
                    "executionMode": "EXTERNAL_RECONSTRUCTION",
                },
            )
            assert conflict.status_code == 409, conflict.text
            omitted_mode = client.post(
                "/v1/sites/site-a/observation-work-orders",
                headers=_headers(_TOKEN_A, key="managed-omitted"),
                json={"name": "기본 관측 운영", "workAreaIds": [area_id], "scheduleId": None},
            )
            assert omitted_mode.status_code == 422, omitted_mode.text
            assert omitted_mode.json()["detail"] == "EXTERNAL_RECONSTRUCTION_REQUIRED"
            explicit_managed = client.post(
                "/v1/sites/site-a/observation-work-orders",
                headers=_headers(_TOKEN_A, key="managed-explicit"),
                json={
                    "name": "관리 관측 운영",
                    "workAreaIds": [area_id],
                    "scheduleId": None,
                    "executionMode": "MANAGED_ACQUISITION",
                },
            )
            assert explicit_managed.status_code == 422, explicit_managed.text
            assert explicit_managed.json()["detail"] == "EXTERNAL_RECONSTRUCTION_REQUIRED"
            # Ordinary resource-scope checks run before the profile rejection:
            # a principal scoped away from site-a sees 404 even with a managed
            # mode, while an unrestricted foreign principal passes scope checks
            # and then meets the profile gate (422, before store tenancy).
            scope_rejected = client.post(
                "/v1/sites/site-a/observation-work-orders",
                headers=_headers(_SCOPED_TOKEN, key="scoped-managed"),
                json={"name": "범위 밖 관측", "workAreaIds": [area_id], "scheduleId": None},
            )
            assert scope_rejected.status_code == 404, scope_rejected.text
            foreign_managed = client.post(
                "/v1/sites/site-a/observation-work-orders",
                headers=_headers(_TOKEN_B, key="foreign-managed"),
                json={"name": "타 조직 관측", "workAreaIds": [area_id], "scheduleId": None},
            )
            assert foreign_managed.status_code == 422, foreign_managed.text
            assert foreign_managed.json()["detail"] == "EXTERNAL_RECONSTRUCTION_REQUIRED"
            fetched = client.get(
                f"/v1/observation-work-orders/{order_id}", headers=_headers(_TOKEN_A)
            )
            assert fetched.status_code == 200, fetched.text
            foreign_read = client.get(
                f"/v1/observation-work-orders/{order_id}", headers=_headers(_TOKEN_B)
            )
            assert foreign_read.status_code == 404, foreign_read.text
    finally:
        for item in opened:
            item.close()


def test_managed_rows_stay_readable_but_reject_operations(tmp_path: Path) -> None:
    trace: list[str] = []
    opened: list[Any] = []
    app = _assemble(tmp_path, trace, opened)
    try:
        area_id = _seed_site_and_area(app)
        store = app.state.observation_work_order_store
        managed = store.create_work_order(
            organization_id="org-a",
            site_id="site-a",
            name="Retained managed row",
            work_area_ids=[area_id],
            schedule_id=None,
            actor="fixture",
            now=_NOW,
        )
        managed_id = managed.work_order_id
        with TestClient(app) as client:
            detail = client.get(
                f"/v1/observation-work-orders/{managed_id}", headers=_headers(_TOKEN_A)
            )
            assert detail.status_code == 200, detail.text
            listed = client.get(
                "/v1/sites/site-a/observation-work-orders", headers=_headers(_TOKEN_A)
            )
            assert listed.status_code == 200, listed.text
            assert managed_id in {item["workOrderId"] for item in listed.json()["workOrders"]}
            operations = client.get(
                f"/v1/observation-work-orders/{managed_id}/operations",
                headers=_headers(_TOKEN_A),
            )
            assert operations.status_code == 409, operations.text
            assert operations.json()["detail"] == "EXTERNAL_OPERATIONS_ONLY"
            assignment = client.post(
                f"/v1/observation-work-orders/{managed_id}/operations/assignment",
                headers=_headers(_TOKEN_A, key="managed-assign"),
                json={"expectedOperationsRevision": 1, "action": "ASSIGN_TO_ME"},
            )
            assert assignment.status_code == 409, assignment.text
            assert assignment.json()["detail"] == "EXTERNAL_OPERATIONS_ONLY"
    finally:
        for item in opened:
            item.close()


def test_external_operations_stay_available_for_bound_orders(tmp_path: Path) -> None:
    trace: list[str] = []
    opened: list[Any] = []
    app = _assemble(tmp_path, trace, opened)
    try:
        area_id = _seed_site_and_area(app)
        with TestClient(app) as client:
            created = _create_external_order(client, area_id, key="bound-operations")
            order_id = created["workOrderId"]
            current = client.get(
                f"/v1/observation-work-orders/{order_id}/operations",
                headers=_headers(_TOKEN_A),
            )
            assert current.status_code == 200, current.text
            revision = current.json()["operationsRevision"]
            assigned = client.post(
                f"/v1/observation-work-orders/{order_id}/operations/assignment",
                headers=_headers(_TOKEN_A, key="bound-assign"),
                json={"expectedOperationsRevision": revision, "action": "ASSIGN_TO_ME"},
            )
            assert assigned.status_code == 200, assigned.text
            assert assigned.json()["assigneePrincipalId"] == "operator-a"
    finally:
        for item in opened:
            item.close()


def _v1_submission(*, epoch_id: str, work_order_id: str) -> dict[str, Any]:
    del work_order_id
    from ksi_event_contracts.external_reconstruction import (
        ExternalReconstructionSubmissionV1,
    )

    wire = {
        "submissionId": "external-001",
        "revision": 1,
        "organizationId": "org-a",
        "siteId": "site-a",
        "observationEpochId": epoch_id,
        "submittedAt": "2026-10-07T00:00:00Z",
        "submittedBy": "operator-a",
        "executionResponsibility": "customer_operator",
        "executionLocus": "customer_workstation",
        "producerDeclaration": {
            "softwareName": "Customer Mapper",
            "softwareVersion": "1.0",
            "buildIdentifier": None,
            "producerRunIdentifier": None,
            "configurationDigest": None,
            "completedAt": None,
        },
        "inputDeclaration": {
            "rawMediaStoredByKsi": False,
            "originalRetentionLocus": "customer_workstation",
            "localInputManifestDigest": None,
            "imageCount": None,
            "captureStartedAt": "2026-10-07T00:00:00Z",
            "captureEndedAt": "2026-10-07T00:10:00Z",
        },
        "artifacts": [
            {
                "artifactId": "ortho",
                "kind": "ortho",
                "fileName": "ortho.tif",
                "format": "GeoTIFF",
                "contentType": "application/octet-stream",
                "declaredSha256": hashlib.sha256(b"ortho bytes").hexdigest(),
                "declaredSizeBytes": len(b"ortho bytes"),
                "declaredCrs": None,
                "declaredVerticalReference": None,
                "declaredGsdM": None,
            }
        ],
    }
    wire["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(wire)
    return wire


def test_empty_policy_keeps_inspection_pending_and_quantitative_use_closed(
    tmp_path: Path,
) -> None:
    from ksi_core.domains.observations.epoch_identity import observation_epoch_id

    trace: list[str] = []
    opened: list[Any] = []
    storage = _Storage()
    app = _assemble(tmp_path, trace, opened, storage=storage)
    try:
        area_id = _seed_site_and_area(app)
        with TestClient(app) as client:
            created = _create_external_order(client, area_id, key="pending-inspection")
            order_id = created["workOrderId"]
            order = app.state.observation_work_order_store.get(order_id, organization_id="org-a")
            assert order is not None
            epoch_id = observation_epoch_id(order)
            base = f"/v1/observation-work-orders/{order_id}/external-reconstruction-submissions"
            registered = client.post(
                base,
                headers=_headers(_TOKEN_A),
                json=_v1_submission(epoch_id=epoch_id, work_order_id=order_id),
            )
            assert registered.status_code == 201, registered.text
            submission_ref = registered.json()["submissionRef"]
            revision_path = f"{base}/{submission_ref}/revisions/1"
            grants = client.post(f"{revision_path}/upload-grants", headers=_headers(_TOKEN_A))
            assert grants.status_code == 200, grants.text
            grant = grants.json()["grants"][0]
            storage.objects[grant["objectKey"]] = ObjectStorageObservation(
                object_key=grant["objectKey"],
                exists=True,
                size_bytes=len(b"ortho bytes"),
                sha256="sha256:" + hashlib.sha256(b"ortho bytes").hexdigest(),
                content_type="application/octet-stream",
            )
            sealed = client.post(f"{revision_path}/seal", headers=_headers(_TOKEN_A))
            assert sealed.status_code == 200, sealed.text
            inspection = client.get(f"{revision_path}/inspection", headers=_headers(_TOKEN_A))
            assert inspection.status_code == 200, inspection.text
            body = inspection.json()
            assert body["registrationState"] == "SEALED"
            assert body["inspection"]["state"] == "INSPECTION_PENDING_POLICY"
            decision = client.post(
                f"{revision_path}/use-decisions/single",
                headers=_headers(_TOKEN_A, key="quantitative-single"),
                json={"use": "HEIGHT"},
            )
            assert decision.status_code == 201, decision.text
            assert decision.json()["decision"]["verdict"] == "BLOCKED"
    finally:
        for item in opened:
            item.close()


def _workflow_config(trace: list[str]) -> Any:
    from ksi_core.external_relative_volume_authorities import (
        DefaultClosedExternalRelativeVolumeAuthorityPort,
    )
    from ksi_core.external_relative_volume_use_history import (
        ClosedExternalRelativeVolumeUseHistory,
    )
    from ksi_core.external_relative_volumes import ExternalRelativeVolumeQueuePolicy
    from ksi_core.external_result_workflow_assembly import (
        ExternalRelativeVolumeRuntimeAuthorities,
        ExternalResultWorkflowAssemblyConfig,
    )

    def mapping(**context: object) -> object:
        trace.append("mapping")
        coordinator = context["coordinator"]
        return DefaultClosedExternalRelativeVolumeAuthorityPort(
            currentness_coordinator=coordinator,  # type: ignore[arg-type]
        )

    def runtime(**context: object) -> object:
        trace.append("runtime")
        coordinator = context["coordinator"]
        return ExternalRelativeVolumeRuntimeAuthorities(
            execution=DefaultClosedExternalRelativeVolumeAuthorityPort(
                currentness_coordinator=coordinator,  # type: ignore[arg-type]
            ),
            historical_use=ClosedExternalRelativeVolumeUseHistory(),
        )

    def issuer(*args: object, **kwargs: object) -> object:
        raise AssertionError("boot probe never issues byte capabilities")

    return ExternalResultWorkflowAssemblyConfig(
        build_mapping=mapping,  # type: ignore[arg-type]
        build_runtime=runtime,  # type: ignore[arg-type]
        queue_policy=ExternalRelativeVolumeQueuePolicy(
            lease_ttl=timedelta(seconds=5),
            deadline_after_issue=timedelta(seconds=30),
            max_attempts=1,
            max_active_requests_per_organization=2,
        ),
        input_capability_issuer=issuer,  # type: ignore[arg-type]
    )


def test_workflow_configured_boot_shares_coordinator_and_traces_review_journals(
    tmp_path: Path,
) -> None:
    trace: list[str] = []
    opened: list[Any] = []
    config = _workflow_config(trace)
    app = _assemble(tmp_path, trace, opened, external_result_workflow=config)
    try:
        journals = [name for name in trace if name.endswith(".jsonl")]
        assert journals == [
            "sites.jsonl",
            "work-areas.jsonl",
            "external-reconstruction.jsonl",
            "external-evidence.jsonl",
            "external-validation-policy.jsonl",
            "external-evidence-validations.jsonl",
            "external-sanitized-display-artifacts.jsonl",
            "external-artifact-inspections.jsonl",
            "external-use-decisions.jsonl",
            "external-relative-volumes.jsonl",
            "external-result-reviews.jsonl",
            "external-reobservation-proposals.jsonl",
            "organization-work-roster.jsonl",
            "observation-work-orders.jsonl",
            "work-inbox.jsonl",
        ]
        assert trace.index("mapping") < trace.index("runtime")
        for name in journals:
            lowered = name.lower()
            assert "mission" not in lowered, name
            assert "edge" not in lowered, name
            assert "flight" not in lowered, name
            assert "acquisition" not in lowered, name
            assert "processing" not in lowered, name
            assert "capability" not in lowered, name
            assert "copilot" not in lowered, name
        coordinator = app.state.external_authority_currentness
        assert app.state.site_store.coordinator is coordinator
        assert app.state.work_area_store.coordinator is coordinator
        assert app.state.observation_work_order_store.operations_coordinator is coordinator
        assert app.state.organization_work_roster_store.coordinator is coordinator
        assert app.state.external_relative_volume_store.coordinator is coordinator
        service = app.state.external_result_workflow_service
        assert service is not None
        assert service.work_orders is app.state.observation_work_order_store
        assert service.sites is app.state.site_store
        assert service.work_areas is app.state.work_area_store
        assert app.state.observation_work_order_store.uses_external_reobservation_authority(
            service.authority_port
        )
        assert app.state.external_result_read_projector is not None
        paths = {route.path for route in _walk_routes(app)}
        assert "/v1/sites/{site_id}/external-relative-volume-reports" in paths
    finally:
        for item in opened:
            item.close()


def _close_all(opened: list[Any]) -> None:
    for item in opened:
        item.close()
    opened.clear()


def test_incomplete_analysis_or_data_participants_raise_before_routes(tmp_path: Path) -> None:
    from ksi_core.composition.platform_graph import build_platform_graph

    trace: list[str] = []
    opened: list[Any] = []

    def journal(name: str) -> DurableJournal:
        trace.append(name)
        item = DurableJournal(tmp_path / name)
        opened.append(item)
        return item

    try:
        with pytest.raises(ValueError, match="spatial data"):
            build_platform_graph(
                data_dir=tmp_path,
                journal=journal,
                opened=opened,
                evidence_storage=_Storage(),
                spatial_data=cast(Any, object()),
            )
    finally:
        _close_all(opened)
    trace.clear()
    assert opened == []
    try:
        with pytest.raises(ValueError, match="[Aa]nalysis"):
            build_platform_graph(
                data_dir=tmp_path,
                journal=journal,
                opened=opened,
                evidence_storage=_Storage(),
                analysis_activation=cast(Any, object()),
            )
    finally:
        _close_all(opened)
    # Both failures happen in the graph phase: no protected route was mounted
    # because no app was ever built, and every journal opened before the raise
    # was handed back through ``opened`` for the caller to close.
