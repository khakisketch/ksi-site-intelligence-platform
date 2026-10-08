"""Historical managed-result readers pinned on the platform profile (P3 Task 2).

Finding (from actual code, recorded here and in the task report — the
tool-generated decision companion is not hand-edited):

* The platform profile (``assemble_platform_app``) mounts no managed
  execution/read surface: no ``/v1/processing-jobs*``,
  ``/v1/sites/{id}/processing-jobs``, ``/v1/processing-profiles``,
  source-media, comparison, design-conformance, region-extraction,
  report-export, checkpoint-validation or spatial-model routes. Verified by
  the RED probe (route inventory + direct GETs all 404).
* Restoring those reads is declined for the end-state reason: the managed
  job/artifact routes would require the transitional managed/mission domain
  chain (``MissionStore`` and related modules — among the Core import files
  Task 5 moves to archive), so wiring them now would create new active
  consumers of soon-archived modules. No concrete active consumer needs them
  (no platform route or store consumes ``ProcessingJobStore``). The managed
  store modules themselves import no ``ksi_mission*`` package at runtime
  today (proven by ``test_managed_store_chain_pulls_no_mission_package``) —
  the blocker is the archive end state, not a current import edge.
* What remains readable on the platform profile, pinned below:
  1. managed work-order rows via the observation-work-order GET/list
     (``ObservationWorkOrderStore`` imports no acquisition package);
  2. site detail with an honest ``SYSTEM_UNAVAILABLE`` spatial model
     (non-null object, never a fabricated ``ABSENT``);
  3. retained source-media/site/processing-job journals replay byte-identically
     through the REAL staying constructors at store level; the mission-linked
     replay proof (``MissionStore`` write + reopen) retired archive-internal
     with the managed set (P3 Task 5;
     ``archive/acquisition-2026/tests/contract/
     test_historical_managed_journals_archived.py``).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    Role,
)
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import DigestBoundUploadCapability, ObjectStorageObservation
from ksi_core.foundation.api_base import iso_utc
from ksi_event_contracts.site_frame import SiteFrame

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = (
    REPOSITORY_ROOT / "services/core/src",
    REPOSITORY_ROOT / "packages/event-contracts/src",
    REPOSITORY_ROOT / "packages/domain/src",
    REPOSITORY_ROOT / "packages/geo-core/src",
    REPOSITORY_ROOT / "packages/mission-contracts/src",
    REPOSITORY_ROOT / "packages/mission-planning/src",
)

# Task brief deny-hook: the platform read path must import none of these.
_DENIED_ACQUISITION_PREFIXES = (
    "ksi_mission_contracts",
    "ksi_mission_planning",
    "ksi_equipment_intelligence",
    "ksi_dji_gateway",
)

_NOW = datetime(2026, 10, 8, tzinfo=UTC)
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

_TOKEN_A = "historical-reader-a"  # noqa: S105 -- deterministic test credential
_TOKEN_B = "historical-reader-b"  # noqa: S105 -- deterministic test credential


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


def _auth_registry() -> AuthRegistry:
    def record(token: str, principal_id: str, organization_id: str) -> PrincipalTokenRecord:
        return PrincipalTokenRecord(
            token_sha256=_digest(token),
            principal=Principal(
                principal_id=principal_id,
                kind=PrincipalKind.OPERATOR,
                role=Role.ADMIN,
                device_id=None,
                organization_id=organization_id,
            ),
        )

    return AuthRegistry(
        [
            record(_TOKEN_A, "operator-a", "org-a"),
            record(_TOKEN_B, "operator-b", "org-b"),
        ]
    )


def _assemble(tmp_path: Path, opened: list[Any]) -> FastAPI:
    from ksi_core.composition.platform_assembly import assemble_platform_app

    def journal(name: str) -> DurableJournal:
        item = DurableJournal(tmp_path / name)
        opened.append(item)
        return item

    try:
        return assemble_platform_app(
            tmp_path,
            journal=journal,
            opened=opened,
            auth_registry=_auth_registry(),
            evidence_storage=_Storage(),
        )
    except BaseException:
        for item in opened:
            item.close()
        raise


def _seed_site_and_area(app: FastAPI) -> str:
    site_result = app.state.site_store.register(
        "site-a",
        "site-a",
        _FRAME,
        organization_id="org-a",
        actor="fixture",
        now=_NOW,
    )
    assert site_result.record is not None
    area_result = app.state.work_area_store.register(
        "site-a",
        name="historical zone",
        polygon=dict(_POLYGON),
        crs="EPSG:5186",
        supersedes=None,
        actor="fixture",
        now=_NOW,
    )
    assert area_result.work_area is not None
    return area_result.work_area.work_area_id


def _seed_managed_row(app: FastAPI, area_id: str) -> str:
    """A retained managed-mode row, written through the real work-order store."""
    order = app.state.observation_work_order_store.create_work_order(
        organization_id="org-a",
        site_id="site-a",
        name="Retained managed row",
        work_area_ids=[area_id],
        schedule_id=None,
        actor="fixture",
        now=_NOW,
    )
    return order.work_order_id


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _walk_routes(container: Any) -> list[Any]:
    found: list[Any] = []
    for route in getattr(container, "routes", None) or []:
        if getattr(route, "methods", None) and getattr(route, "path", None):
            found.append(route)
        inner = getattr(route, "original_router", None)
        if inner is not None:
            found.extend(_walk_routes(inner))
    return found


def test_platform_profile_mounts_no_managed_result_routes(tmp_path: Path) -> None:
    """The omission is deliberate — a future managed read must be explicit."""
    opened: list[Any] = []
    app = _assemble(tmp_path, opened)
    try:
        paths = {route.path for route in _walk_routes(app)}
        managed_markers = (
            "processing-job",
            "processing-profile",
            "source-media",
            "comparison",
            "design-conformance",
            "region-extraction",
            "report-export",
            "checkpoint",
            "spatial-model",
        )
        segments = [segment for path in sorted(paths) for segment in path.split("/")]
        assert [p for p in sorted(paths) if any(m in p for m in managed_markers)] == []
        assert "missions" not in segments
        with TestClient(app) as client:
            for probe in (
                "/v1/processing-jobs",
                "/v1/processing-profiles",
                "/v1/sites/site-a/processing-jobs",
            ):
                assert client.get(probe, headers=_headers(_TOKEN_A)).status_code == 404
    finally:
        for item in opened:
            item.close()


def test_site_detail_stays_honest_without_reconstruction_ledger(tmp_path: Path) -> None:
    """``mount_sites(app, sites, None)`` omits only the model summary computation.

    The site itself stays readable with exact bytes; the spatial model is a
    non-null honest ``SYSTEM_UNAVAILABLE``, never a fabricated ``ABSENT``.
    Tenant isolation holds on both endpoints.
    """
    opened: list[Any] = []
    app = _assemble(tmp_path, opened)
    try:
        _seed_site_and_area(app)
        with TestClient(app) as client:
            detail = client.get("/v1/sites/site-a", headers=_headers(_TOKEN_A))
            assert detail.status_code == 200, detail.text
            body = detail.json()
            assert body["siteId"] == "site-a"
            assert body["name"] == "site-a"
            assert body["spatialModel"] is not None
            assert body["spatialModel"]["state"] == "SYSTEM_UNAVAILABLE"
            assert body["spatialModel"]["siteId"] == "site-a"
            listed = client.get("/v1/sites", headers=_headers(_TOKEN_A))
            assert listed.status_code == 200, listed.text
            assert [s["siteId"] for s in listed.json()["sites"]] == ["site-a"]
            assert client.get("/v1/sites/site-a", headers=_headers(_TOKEN_B)).status_code == 404
            foreign_list = client.get("/v1/sites", headers=_headers(_TOKEN_B))
            assert foreign_list.status_code == 200, foreign_list.text
            assert foreign_list.json()["sites"] == []
    finally:
        for item in opened:
            item.close()


def test_managed_work_order_rows_stay_readable_with_tenant_isolation(
    tmp_path: Path,
) -> None:
    """Retained managed rows keep exact bytes on the platform list/read path.

    Scope: the readable HTTP body carries the row's identifier/lineage bytes
    (ids, version, timestamps, actor, lineage lists). Byte-grant bindings
    (artifact digests) have no HTTP surface for managed rows on this profile —
    they are pinned at journal level in
    ``test_retained_managed_journals_replay_byte_identical``.
    """
    opened: list[Any] = []
    app = _assemble(tmp_path, opened)
    try:
        area_id = _seed_site_and_area(app)
        managed_id = _seed_managed_row(app, area_id)
        with TestClient(app) as client:
            detail = client.get(
                f"/v1/observation-work-orders/{managed_id}", headers=_headers(_TOKEN_A)
            )
            assert detail.status_code == 200, detail.text
            body = detail.json()
            assert body["workOrderId"] == managed_id
            assert body["workOrderId"] == "obs-work-00000001"
            assert body["schemaVersion"] == "1.0"
            assert body["organizationId"] == "org-a"
            assert body["siteId"] == "site-a"
            assert body["purpose"] == "PROGRESS_QUANTITY"
            assert body["name"] == "Retained managed row"
            assert body["workAreaIds"] == [area_id]
            assert body["scheduleId"] is None
            assert body["temporalPolicy"] is None
            assert body["executionMode"] == "MANAGED_ACQUISITION"
            assert body["cycleNumber"] == 1
            assert body["status"] == "AWAITING_APPROVAL"
            assert body["missionIds"] == []
            assert body["processingJobIds"] == []
            assert body["reportRefs"] == []
            assert body["version"] == 1
            assert body["createdAt"] == iso_utc(_NOW)
            assert body["updatedAt"] == iso_utc(_NOW)
            assert body["createdBy"] == "fixture"
            assert body["approvedAt"] is None
            assert body["approvedBy"] is None
            listed = client.get(
                "/v1/sites/site-a/observation-work-orders", headers=_headers(_TOKEN_A)
            )
            assert listed.status_code == 200, listed.text
            assert managed_id in {item["workOrderId"] for item in listed.json()["workOrders"]}
            foreign = client.get(
                f"/v1/observation-work-orders/{managed_id}", headers=_headers(_TOKEN_B)
            )
            assert foreign.status_code == 404, foreign.text
    finally:
        for item in opened:
            item.close()


def test_managed_row_operations_stay_closed_on_platform_profile(
    tmp_path: Path,
) -> None:
    """Existing routes over retained managed records behave: no 500s, exact gates.

    The managed row stays readable (200, pinned above) but the operations
    surface rejects it with the established ``409 EXTERNAL_OPERATIONS_ONLY``.
    """
    opened: list[Any] = []
    app = _assemble(tmp_path, opened)
    try:
        area_id = _seed_site_and_area(app)
        managed_id = _seed_managed_row(app, area_id)
        with TestClient(app) as client:
            operations = client.get(
                f"/v1/observation-work-orders/{managed_id}/operations",
                headers=_headers(_TOKEN_A),
            )
            assert operations.status_code == 409, operations.text
            assert operations.json()["detail"] == "EXTERNAL_OPERATIONS_ONLY"
    finally:
        for item in opened:
            item.close()


def test_managed_store_chain_pulls_no_mission_package() -> None:
    """Current runtime fact: the managed store chain imports no ``ksi_mission*``.

    ``source_media``'s ``MissionStore`` import is ``TYPE_CHECKING``-only and
    ``processing_jobs`` builds on ``ksi_domain.signed_payload`` — so importing
    the chain (plus the platform site/work-order readers) must leave zero
    ``ksi_mission*`` modules behind. A subprocess keeps the parent's own
    ``SiteFrame`` import from polluting the observation.
    """
    script = dedent(
        """
        import sys

        import ksi_core.domains.artifacts.source_media  # noqa: F401
        import ksi_core.domains.processing.processing_jobs  # noqa: F401
        import ksi_core.domains.sites.observation_work_orders  # noqa: F401
        import ksi_core.domains.sites.sites  # noqa: F401
        import ksi_core.processing_jobs  # noqa: F401
        import ksi_core.source_media  # noqa: F401

        leaked = sorted(m for m in sys.modules if m.startswith("ksi_mission"))
        assert leaked == [], leaked
        """
    )
    completed = _run_python(script)
    assert completed.returncode == 0, completed.stdout + completed.stderr


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
        timeout=180,
    )


def _blocker_prelude(denied: tuple[str, ...]) -> str:
    return dedent(
        """
            import importlib.util
            import sys

            _DENIED_PREFIXES = %r

            # Sanity first: the control module is installed, so blocking it
            # below proves the hook fires (not that the package is missing).
            assert (
                importlib.util.find_spec("ksi_mission_contracts") is not None
            ), "ksi_mission_contracts must be installed for this probe"

            class _DenyPrefixes:
                # Python 3.12 no longer calls find_module — find_spec is the
                # supported blocker entry point. Raising here fails the import
                # loudly instead of silently skipping the module.
                def find_spec(self, name, path=None, target=None):
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
            # Positive control: the hook must actually fire.
            try:
                import ksi_mission_contracts  # noqa: F401
            except ImportError as exc:
                assert "platform isolation probe denies" in str(exc), exc
            else:
                raise AssertionError("deny-hook did not block ksi_mission_contracts")
            """
    ) % (denied,)


def test_platform_read_path_imports_no_acquisition_package(tmp_path: Path) -> None:
    """Fresh-process deny-hook: the retained reads import no acquisition package.

    The parent seeds a site, a work area and a managed work-order row through
    the real platform stores (fixture phase may import anything); the
    subprocess reboots the platform app over the same journals under a
    deny-hook and performs the retained reads over HTTP.
    """
    opened: list[Any] = []
    app = _assemble(tmp_path, opened)
    try:
        area_id = _seed_site_and_area(app)
        managed_id = _seed_managed_row(app, area_id)
    finally:
        for item in opened:
            item.close()

    script = _blocker_prelude(_DENIED_ACQUISITION_PREFIXES) + dedent(
        """
        import hashlib
        import sys
        import tempfile
        from pathlib import Path

        from fastapi.testclient import TestClient
        from ksi_core.auth import (
            AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role,
        )
        from ksi_core.composition.platform_assembly import assemble_platform_app
        from ksi_core.durable_journal import DurableJournal
        from ksi_core.evidence import ObjectStorageObservation

        denied = %r
        data_dir = Path(%r)
        managed_id = %r

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
                raise NotImplementedError

            def observe_object(self, object_key):
                return ObjectStorageObservation(object_key=object_key, exists=False)

        opened = []

        def journal(name):
            item = DurableJournal(data_dir / name)
            opened.append(item)
            return item

        registry = AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(%r).hexdigest(),
                    principal=Principal(
                        principal_id="probe-a",
                        kind=PrincipalKind.OPERATOR,
                        role=Role.ADMIN,
                        device_id=None,
                        organization_id="org-a",
                    ),
                ),
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(%r).hexdigest(),
                    principal=Principal(
                        principal_id="probe-b",
                        kind=PrincipalKind.OPERATOR,
                        role=Role.ADMIN,
                        device_id=None,
                        organization_id="org-b",
                    ),
                ),
            ]
        )
        app = assemble_platform_app(
            data_dir,
            journal=journal,
            opened=opened,
            auth_registry=registry,
            evidence_storage=_StubStorage(),
        )
        try:
            with TestClient(app) as client:
                headers_a = {"Authorization": "Bearer " + %r}
                headers_b = {"Authorization": "Bearer " + %r}
                detail = client.get("/v1/sites/site-a", headers=headers_a)
                assert detail.status_code == 200, detail.text
                assert detail.json()["spatialModel"]["state"] == "SYSTEM_UNAVAILABLE"
                listed = client.get("/v1/sites", headers=headers_a)
                assert [s["siteId"] for s in listed.json()["sites"]] == ["site-a"]
                order = client.get(
                    "/v1/observation-work-orders/" + managed_id, headers=headers_a
                )
                assert order.status_code == 200, order.text
                assert order.json()["executionMode"] == "MANAGED_ACQUISITION"
                orders = client.get(
                    "/v1/sites/site-a/observation-work-orders", headers=headers_a
                )
                assert managed_id in {
                    item["workOrderId"] for item in orders.json()["workOrders"]
                }, orders.text
                assert (
                    client.get(
                        "/v1/observation-work-orders/" + managed_id, headers=headers_b
                    ).status_code
                    == 404
                )
        finally:
            for item in opened:
                item.close()
        for name in denied:
            assert name not in sys.modules, name
            assert not any(
                module == name or module.startswith(name + ".") for module in sys.modules
            ), name
        """
    ) % (
        _DENIED_ACQUISITION_PREFIXES,
        str(tmp_path),
        managed_id,
        _TOKEN_A.encode(),
        _TOKEN_B.encode(),
        _TOKEN_A,
        _TOKEN_B,
    )
    completed = _run_python(script)
    assert completed.returncode == 0, completed.stdout + completed.stderr
