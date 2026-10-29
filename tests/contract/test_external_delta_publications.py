"""Contract tests for the Core delta-publication lane (synthetic fixtures only).

These tests use fabricated digests/bytes and in-test fake authority ports;
they prove software behavior of the lane, never signed production authority.
"""

from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from ksi_core.domains.external.quantity.external_delta_publication_api import (
    build_external_delta_publication_router,
)
from ksi_core.domains.external.quantity.external_delta_publications import (
    DeltaOutputObservation,
    DeltaPublicationDispositionV1,
    DeltaPublicationPolicy,
    DeltaPublicationStatusV1,
    DeltaPublicationView,
    DeltaSourceWitness,
    ExternalDeltaPublicationStore,
    FilesystemDeltaByteStore,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.identity.auth import Principal, PrincipalKind, Role
from ksi_domain.canonical_json import canonical_json_bytes

NOW = datetime(2026, 10, 26, tzinfo=UTC)
GRID_ROWS = 4
GRID_COLUMNS = 4
TRANSFORM = (1.0, 0.0, 100.0, 0.0, -1.0, 200.0)
BOUNDS = (100.0, 196.0, 104.0, 200.0)
V2_CONTRACT = "external-relative-volume-calculation-report.v2"
V3_CONTRACT = "external-masked-volume-calculation-identity.v3"


def _digest(marker: str) -> str:
    return "sha256:" + hashlib.sha256(marker.encode()).hexdigest()


def _transform_digest() -> str:
    return (
        "sha256:" + hashlib.sha256(canonical_json_bytes({"transform": list(TRANSFORM)})).hexdigest()
    )


CALC_DIGEST = _digest("calculation")
NUMERIC_DIGEST = _digest("numeric")
COVERAGE_DIGEST = _digest("coverage")
CRS_DIGEST = _digest("horizontal-crs")


class _Clock:
    """Injected trusted time; tests advance it instead of passing stale stamps."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _operator(org: str = "org-a") -> Principal:
    return Principal("operator-a", PrincipalKind.OPERATOR, Role.ADMIN, None, org)


def _scoped_operator(sites: frozenset[str] | None, areas: frozenset[str] | None) -> Principal:
    return Principal(
        "operator-scoped",
        PrincipalKind.OPERATOR,
        Role.ADMIN,
        None,
        "org-a",
        allowed_site_ids=sites,
        allowed_work_area_ids=areas,
    )


def _viewer() -> Principal:
    return Principal("viewer-a", PrincipalKind.OPERATOR, Role.VIEWER, None, "org-a")


def _worker(
    org: str = "org-a",
    principal_id: str = "analysis-worker-1",
    sites: frozenset[str] | None = None,
    areas: frozenset[str] | None = None,
) -> Principal:
    return Principal(
        principal_id,
        PrincipalKind.ANALYSIS_WORKER,
        None,
        None,
        org,
        allowed_site_ids=sites,
        allowed_work_area_ids=areas,
    )


def _processing_worker() -> Principal:
    return Principal("processing-worker-1", PrincipalKind.PROCESSING_WORKER, None, None, "org-a")


def _mcp_client(site: str = "site-a", area: str = "work-area-a") -> Principal:
    return Principal(
        "mcp-1",
        PrincipalKind.ANALYSIS_MCP_CLIENT,
        None,
        None,
        "org-a",
        allowed_site_ids=frozenset({site}),
        allowed_work_area_ids=frozenset({area}),
    )


class _FakeSource:
    def __init__(
        self,
        version: str = V3_CONTRACT,
        live: bool = True,
        max_calls: int | None = None,
    ) -> None:
        self.version = version
        self.live = live
        self.max_calls = max_calls
        self.calls = 0
        self.known = {
            ("org-a", "site-a", "work-area-a", CALC_DIGEST, NUMERIC_DIGEST, COVERAGE_DIGEST)
        }

    def resolve_current_source(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        if not self.live:
            return None
        if self.max_calls is not None and self.calls > self.max_calls:
            return None
        key = (
            kwargs["organization_id"],
            kwargs["site_id"],
            kwargs["work_area_id"],
            kwargs["source_calculation_identity_digest"],
            kwargs["source_numeric_result_identity_digest"],
            kwargs["source_coverage_witness_digest"],
        )
        if key not in self.known:
            return None
        return DeltaSourceWitness(
            organization_id=kwargs["organization_id"],
            site_id=kwargs["site_id"],
            work_area_id=kwargs["work_area_id"],
            source_contract_version=self.version,
            source_calculation_identity_digest=kwargs["source_calculation_identity_digest"],
            source_numeric_result_identity_digest=kwargs["source_numeric_result_identity_digest"],
            source_coverage_witness_digest=kwargs["source_coverage_witness_digest"],
            grid_rows=GRID_ROWS,
            grid_columns=GRID_COLUMNS,
            transform=TRANSFORM,
            transform_digest=_transform_digest(),
            grid_crs_identifier="EPSG:5186",
            grid_crs_digest=CRS_DIGEST,
            bounds=BOUNDS,
        )


class _FakeAuthority:
    def __init__(self) -> None:
        self.policy_current = True
        self.runtime_current = True
        self.runtime_calls: list[dict] = []

    def is_policy_current(self, *, policy_digest: str, now: datetime) -> bool:
        return self.policy_current

    def is_runtime_current(  # type: ignore[no-untyped-def]
        self, *, now, worker_principal_id=None, publication_id=None, lease_generation=None
    ) -> bool:
        self.runtime_calls.append(
            {
                "worker_principal_id": worker_principal_id,
                "publication_id": publication_id,
                "lease_generation": lease_generation,
            }
        )
        return self.runtime_current


class _FakeEgress:
    def __init__(self, allowed: bool = True, max_calls: int | None = None) -> None:
        self.allowed = allowed
        self.max_calls = max_calls
        self.calls = 0

    def is_egress_allowed(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.max_calls is not None and self.calls > self.max_calls:
            return False
        return self.allowed


class _FakeObservations:
    """Stand-in for the separately authenticated worker result acceptance.

    Tests bind explicit sealed observations; the default empty registry
    resolves to ``None``, proving unobserved bytes never publish.  A
    ``script`` list, when set, overrides the registry call-by-call so tests
    can rotate or withdraw the acceptance mid-operation.
    """

    def __init__(self) -> None:
        self._bound: dict[tuple[str, str, str, int], DeltaOutputObservation] = {}
        self.script: list = []
        self.calls: list[dict] = []

    def bind(self, observation: DeltaOutputObservation) -> None:
        self._bound[
            (
                observation.publication_id,
                observation.worker_principal_id,
                observation.worker_instance_id,
                observation.lease_generation,
            )
        ] = observation

    def resolve_output_observation(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        if self.script:
            return self.script.pop(0)
        return self._bound.get(
            (
                kwargs["publication_id"],
                kwargs["worker_principal_id"],
                kwargs["worker_instance_id"],
                kwargs["lease_generation"],
            )
        )


def _policy(**overrides):  # type: ignore[no-untyped-def]
    fields = {
        "policy_id": "delta-publication-test-v1",
        "version": 1,
        "max_output_bytes": 1_000_000,
        "max_grid_cells": 1_000_000,
        "max_lifetime_seconds": 86_400,
        "max_active_publications": 8,
        "upload_lease_duration_seconds": 600,
        "max_upload_attempts": 8,
    }
    fields.update(overrides)
    return DeltaPublicationPolicy(**fields)


def _harness(tmp_path: Path, **policy_overrides):  # type: ignore[no-untyped-def]
    journal_path = tmp_path / "delta-publications.jsonl"
    byte_root = tmp_path / "delta-bytes"
    clock = _Clock()
    source = _FakeSource()
    authority = _FakeAuthority()
    egress = _FakeEgress()
    observations = _FakeObservations()
    policy = _policy(**policy_overrides)
    store = ExternalDeltaPublicationStore(
        DurableJournal(journal_path),
        source_witness=source,
        authority=authority,
        egress=egress,
        byte_store=FilesystemDeltaByteStore(byte_root),
        observations=observations,
        policy=policy,
        clock=clock,
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    return store, journal_path, byte_root, source, authority, egress, policy, observations, clock


def _observation(  # type: ignore[no-untyped-def]
    payload: bytes,
    *,
    pub="pub-01",
    worker_id="analysis-worker-1",
    instance="inst-1",
    generation=1,
    version=V3_CONTRACT,
    sha=None,
    size=None,
):
    return DeltaOutputObservation(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        source_contract_version=version,
        source_calculation_identity_digest=CALC_DIGEST,
        source_numeric_result_identity_digest=NUMERIC_DIGEST,
        source_coverage_witness_digest=COVERAGE_DIGEST,
        publication_id=pub,
        worker_principal_id=worker_id,
        worker_instance_id=instance,
        lease_generation=generation,
        output_sha256=sha or "sha256:" + hashlib.sha256(payload).hexdigest(),
        output_size_bytes=size or len(payload),
        grid_rows=GRID_ROWS,
        grid_columns=GRID_COLUMNS,
        transform=TRANSFORM,
        transform_digest=_transform_digest(),
        grid_crs_identifier="EPSG:5186",
        grid_crs_digest=CRS_DIGEST,
        bounds=BOUNDS,
        dtype="FLOAT64",
        delta_sign="CURRENT_MINUS_BASELINE",
        nodata_value="NAN",
    ).sealed()


def _intent_kwargs(**overrides):  # type: ignore[no-untyped-def]
    fields = {
        "publication_id": "pub-01",
        "site_id": "site-a",
        "work_area_id": "work-area-a",
        "source_calculation_identity_digest": CALC_DIGEST,
        "source_numeric_result_identity_digest": NUMERIC_DIGEST,
        "source_coverage_witness_digest": COVERAGE_DIGEST,
        "grid_rows": GRID_ROWS,
        "grid_columns": GRID_COLUMNS,
        "transform": TRANSFORM,
        "transform_digest": _transform_digest(),
        "grid_crs_identifier": "EPSG:5186",
        "grid_crs_digest": CRS_DIGEST,
        "bounds": BOUNDS,
        "lifetime_seconds": 3_600,
        "now": NOW,
    }
    fields.update(overrides)
    return fields


def _sub(tmp_path, name):  # type: ignore[no-untyped-def]
    """Owner-private 0700 test subdir: the byte-root gate rejects lax ancestors."""
    path = tmp_path / name
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _payload(size: int = 1_024) -> bytes:
    return bytes(i % 256 for i in range(size))


def _leased(store, worker, clock, pub="pub-01", instance="inst-1", acq="acq-1"):  # type: ignore[no-untyped-def]
    return store.acquire_upload_lease(
        worker_principal=worker,
        publication_id=pub,
        worker_instance_id=instance,
        lease_acquisition_id=acq,
        now=clock.now,
    )


def _publish(
    store: ExternalDeltaPublicationStore,
    observations: _FakeObservations,
    worker: Principal,
    clock: _Clock,
    payload: bytes,
    pub: str = "pub-01",
    instance: str = "inst-1",
    acq: str = "acq-1",
    **obs_kwargs: Any,
) -> DeltaPublicationView | None:
    lease = _leased(store, worker, clock, pub, instance, acq)
    assert lease is not None
    observations.bind(
        _observation(
            payload,
            pub=pub,
            worker_id=worker.principal_id,
            instance=instance,
            generation=lease.lease_generation,
            **obs_kwargs,
        )
    )
    return store.publish_output(
        worker_principal=worker,
        publication_id=pub,
        worker_instance_id=instance,
        lease_generation=lease.lease_generation,
        byte_stream=io.BytesIO(payload),
    )


def _journal_events(path: Path) -> list:
    import json

    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_intent_pins_trusted_source_version_and_server_fence(tmp_path: Path) -> None:
    store, journal_path, _, _, _, _, policy, _, _ = _harness(tmp_path)
    view = store.create_intent(principal=_operator(), **_intent_kwargs())
    assert view.status is DeltaPublicationStatusV1.PENDING
    assert view.source_contract_version == V3_CONTRACT
    assert view.output_id == "delta-out-pub-01"
    assert view.upload_fence_id == "upload-fence-pub-01"
    assert view.lease_generation == 0
    assert view.policy_digest == policy.canonical_digest()
    events = _journal_events(journal_path)
    assert len(events) == 1
    assert events[0]["kind"] == "delta-publication-intent-created"
    assert events[0]["sourceContractVersion"] == V3_CONTRACT


def test_v2_source_pins_v2_descriptor(tmp_path: Path) -> None:
    store, journal_path, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store._source.live = True  # noqa: SLF001
    store._source.version = V2_CONTRACT  # noqa: SLF001
    view = store.create_intent(principal=_operator(), **_intent_kwargs())
    assert view.source_contract_version == V2_CONTRACT
    published = _publish(store, observations, _worker(), clock, _payload(), version=V2_CONTRACT)
    assert published is not None
    assert published.descriptor.source_contract_version == V2_CONTRACT


def test_workers_and_viewers_cannot_create_intent(tmp_path: Path) -> None:
    store, _, _, _, _, _, _, _, _ = _harness(tmp_path)
    with pytest.raises(PermissionError):
        store.create_intent(principal=_worker(), **_intent_kwargs())
    with pytest.raises(PermissionError):
        store.create_intent(principal=_processing_worker(), **_intent_kwargs())
    with pytest.raises(PermissionError):
        store.create_intent(principal=_viewer(), **_intent_kwargs())


def test_mcp_client_scope_is_enforced_on_intent(tmp_path: Path) -> None:
    store, _, _, _, _, _, _, _, _ = _harness(tmp_path)
    view = store.create_intent(principal=_mcp_client(), **_intent_kwargs())
    assert view.organization_id == "org-a"
    with pytest.raises(PermissionError):
        store.create_intent(
            principal=_mcp_client(site="site-foreign"), **_intent_kwargs(publication_id="pub-02")
        )


def test_oidc_operator_scope_is_enforced_in_store(tmp_path: Path) -> None:
    store, _, _, _, _, _, _, observations, clock = _harness(tmp_path)
    scoped = _scoped_operator(frozenset({"site-a"}), frozenset({"work-area-a"}))
    store.create_intent(principal=scoped, **_intent_kwargs(publication_id="pub-scoped"))
    _publish(store, observations, _worker(), clock, _payload(), pub="pub-scoped")
    view, _ = store.get_current_with_disposition("pub-scoped", principal=scoped, now=NOW)
    assert view is not None
    foreign_site = _scoped_operator(frozenset({"site-other"}), frozenset({"work-area-a"}))
    with pytest.raises(PermissionError, match="outside caller scope"):
        store.create_intent(principal=foreign_site, **_intent_kwargs(publication_id="pub-x"))
    foreign_area = _scoped_operator(frozenset({"site-a"}), frozenset({"area-other"}))
    with pytest.raises(PermissionError, match="outside caller scope"):
        store.create_intent(principal=foreign_area, **_intent_kwargs(publication_id="pub-y"))
    view, disposition = store.get_current_with_disposition(
        "pub-scoped", principal=foreign_site, now=NOW
    )
    assert view is None and disposition is DeltaPublicationDispositionV1.NOT_FOUND
    assert store.read_bytes("pub-scoped", principal=foreign_area, offset=0, length=8) is None


def test_intent_caps_fail_closed(tmp_path: Path) -> None:
    store, journal_path, _, _, _, _, _, _, _ = _harness(tmp_path)
    with pytest.raises(ValueError, match="lifetime"):
        store.create_intent(principal=_operator(), **_intent_kwargs(lifetime_seconds=86_401))
    with pytest.raises(ValueError, match="cell cap"):
        store.create_intent(
            principal=_operator(), **_intent_kwargs(grid_rows=2_000, grid_columns=2_000)
        )
    assert _journal_events(journal_path) == []


def test_intent_requires_current_witness_matching_full_grid(tmp_path: Path) -> None:
    store, journal_path, _, source, _, _, _, _, _ = _harness(tmp_path)
    source.live = False
    with pytest.raises(RuntimeError, match="not currently available"):
        store.create_intent(principal=_operator(), **_intent_kwargs())
    source.live = True
    with pytest.raises(RuntimeError, match="does not match"):
        store.create_intent(
            principal=_operator(),
            **_intent_kwargs(publication_id="pub-grid", transform_digest=_digest("other")),
        )
    assert _journal_events(journal_path) == []


def test_idempotent_retry_compares_full_binding_and_rechecks_currentness(
    tmp_path: Path,
) -> None:
    store, journal_path, _, source, _, _, _, _, _ = _harness(tmp_path)
    first = store.create_intent(principal=_operator(), **_intent_kwargs())
    second = store.create_intent(principal=_operator(), **_intent_kwargs())
    assert first.upload_fence_id == second.upload_fence_id
    assert len(_journal_events(journal_path)) == 1
    with pytest.raises(ValueError, match="already bound"):
        store.create_intent(
            principal=_operator(),
            **_intent_kwargs(bounds=(100.0, 196.0, 104.0, 201.0)),
        )
    source.live = False
    with pytest.raises(RuntimeError, match="not currently available"):
        store.create_intent(principal=_operator(), **_intent_kwargs())


def test_idempotent_retry_survives_full_capacity(tmp_path: Path) -> None:
    lone_store, lone_journal, _, _, _, _, _, _, _ = _harness(
        _sub(tmp_path, "lone"), max_active_publications=1
    )
    lone_store.create_intent(principal=_operator(), **_intent_kwargs())
    retried = lone_store.create_intent(principal=_operator(), **_intent_kwargs())
    assert retried.status is DeltaPublicationStatusV1.PENDING
    assert len(_journal_events(lone_journal)) == 1
    with pytest.raises(RuntimeError, match="capacity"):
        lone_store.create_intent(
            principal=_operator(), **_intent_kwargs(publication_id="pub-other")
        )


def test_lease_binds_holder_instance_generation_and_expiry(tmp_path: Path) -> None:
    store, journal_path, _, _, authority, _, _, _, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    lease = _leased(store, _worker(), clock)
    assert lease is not None and lease.lease_generation == 1
    assert lease.lease_holder_principal_id == "analysis-worker-1"
    assert lease.lease_holder_instance_id == "inst-1"
    assert lease.lease_expires_at == NOW + timedelta(seconds=600)
    assert len(_journal_events(journal_path)) == 2
    assert _journal_events(journal_path)[1]["kind"] == "delta-publication-upload-leased"
    worker_calls = [call for call in authority.runtime_calls if call["publication_id"] == "pub-01"]
    assert worker_calls and all(
        call["worker_principal_id"] == "analysis-worker-1" and call["lease_generation"] == 1
        for call in worker_calls
    )


def test_opposite_worker_or_instance_cannot_use_lease(tmp_path: Path) -> None:
    store, journal_path, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    lease = _leased(store, _worker(), clock)
    assert lease is not None
    other = _worker(principal_id="analysis-worker-2")
    assert _leased(store, other, clock, acq="acq-other") is None
    assert _leased(store, _worker(), clock, instance="inst-2", acq="acq-2") is None
    # Same holder/instance/acquisition reclaims the identical live lease.
    same = _leased(store, _worker(), clock)
    assert same is not None and same.lease_generation == 1
    assert len(_journal_events(journal_path)) == 2
    # A spent acquisition id can never mint another lease.
    clock.now = NOW + timedelta(seconds=601)
    assert _leased(store, _worker(), clock) is None
    fresh = store.acquire_upload_lease(
        worker_principal=_worker(),
        publication_id="pub-01",
        worker_instance_id="inst-1",
        lease_acquisition_id="acq-fresh",
        now=clock.now,
    )
    assert fresh is not None and fresh.lease_generation == 2


def test_upload_requires_live_lease_and_holder_binding(tmp_path: Path) -> None:
    store, journal_path, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    payload = _payload()
    # No lease at all: nothing is staged or journaled.
    assert (
        store.publish_output(
            worker_principal=_worker(),
            publication_id="pub-01",
            worker_instance_id="inst-1",
            lease_generation=1,
            byte_stream=io.BytesIO(payload),
        )
        is None
    )
    assert len(_journal_events(journal_path)) == 1
    lease = _leased(store, _worker(), clock)
    assert lease is not None
    other = _worker(principal_id="analysis-worker-2")
    assert (
        store.publish_output(
            worker_principal=other,
            publication_id="pub-01",
            worker_instance_id="inst-1",
            lease_generation=1,
            byte_stream=io.BytesIO(payload),
        )
        is None
    )
    assert (
        store.publish_output(
            worker_principal=_worker(),
            publication_id="pub-01",
            worker_instance_id="inst-1",
            lease_generation=99,
            byte_stream=io.BytesIO(payload),
        )
        is None
    )
    assert len(_journal_events(journal_path)) == 2
    observations.bind(_observation(payload, worker_id="analysis-worker-1"))
    view = store.publish_output(
        worker_principal=_worker(),
        publication_id="pub-01",
        worker_instance_id="inst-1",
        lease_generation=1,
        byte_stream=io.BytesIO(payload),
    )
    assert view is not None and view.status is DeltaPublicationStatusV1.PUBLISHED
    assert view.descriptor.source_contract_version == V3_CONTRACT


def test_publish_happy_path_seals_float64_descriptor_without_url(tmp_path: Path) -> None:
    store, journal_path, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    payload = _payload()
    view = _publish(store, observations, _worker(), clock, payload)
    assert view is not None and view.status is DeltaPublicationStatusV1.PUBLISHED
    descriptor = view.descriptor
    assert descriptor.dtype == "FLOAT64"
    assert descriptor.delta_sign == "CURRENT_MINUS_BASELINE"
    assert descriptor.output_sha256 == "sha256:" + hashlib.sha256(payload).hexdigest()
    assert descriptor.output_size_bytes == len(payload)
    assert descriptor.publication_digest == descriptor.canonical_digest()
    wire = descriptor.model_dump(by_alias=True, mode="json")
    assert "downloadUrl" not in wire and "url" not in wire and "path" not in wire
    assert len(_journal_events(journal_path)) == 3


def test_publish_rejects_hash_size_and_cap_violations(tmp_path: Path) -> None:
    store, journal_path, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    lease = _leased(store, _worker(), clock)
    assert lease is not None
    payload = _payload()

    observations.bind(_observation(payload))
    other_bytes = bytes((byte + 1) % 256 for byte in payload)
    assert other_bytes != payload
    with pytest.raises(ValueError, match="hash"):
        store.publish_output(
            worker_principal=_worker(),
            publication_id="pub-01",
            worker_instance_id="inst-1",
            lease_generation=lease.lease_generation,
            byte_stream=io.BytesIO(other_bytes),
        )

    class _ShortStream(io.RawIOBase):
        def __init__(self) -> None:
            self._done = False

        def readable(self) -> bool:
            return True

        def read(self, size: int = -1) -> bytes:
            if self._done:
                return b""
            self._done = True
            return payload[: len(payload) // 2]

    with pytest.raises(ValueError, match="size"):
        store.publish_output(
            worker_principal=_worker(),
            publication_id="pub-01",
            worker_instance_id="inst-1",
            lease_generation=lease.lease_generation,
            byte_stream=_ShortStream(),
        )
    assert len(_journal_events(journal_path)) == 2
    tiny, _, _, _, _, _, _, tiny_observations, tiny_clock = _harness(
        _sub(tmp_path, "tiny"), max_output_bytes=8
    )
    tiny.create_intent(principal=_operator(), **_intent_kwargs(publication_id="pub-tiny"))
    tiny_lease = _leased(tiny, _worker(), tiny_clock, pub="pub-tiny", acq="acq-tiny")
    assert tiny_lease is not None
    big = _payload(16)
    # The accepted observation itself exceeds the byte cap: no staging, no journal.
    tiny_observations.bind(
        _observation(big, pub="pub-tiny", generation=tiny_lease.lease_generation)
    )
    assert (
        tiny.publish_output(
            worker_principal=_worker(),
            publication_id="pub-tiny",
            worker_instance_id="inst-1",
            lease_generation=tiny_lease.lease_generation,
            byte_stream=io.BytesIO(big),
        )
        is None
    )
    assert len(_journal_events(_sub(tmp_path, "tiny") / "delta-publications.jsonl")) == 2


def test_publish_fails_closed_on_source_policy_expiry(tmp_path: Path) -> None:
    store, journal_path, _, source, authority, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    lease = _leased(store, _worker(), clock)
    assert lease is not None
    payload = _payload()

    observations.bind(_observation(payload))

    def attempt():  # type: ignore[no-untyped-def]
        return store.publish_output(
            worker_principal=_worker(),
            publication_id="pub-01",
            worker_instance_id="inst-1",
            lease_generation=lease.lease_generation,
            byte_stream=io.BytesIO(payload),
        )

    source.live = False
    assert attempt() is None
    source.live = True
    authority.policy_current = False
    assert attempt() is None
    authority.policy_current = True
    # The trusted clock, not a caller timestamp, decides expiry: advancing it
    # past the lease/expiry window fails the finish check closed.
    clock.now = NOW + timedelta(seconds=601)
    assert attempt() is None
    assert len(_journal_events(journal_path)) == 2
    clock.now = NOW
    assert attempt() is not None


def test_read_currentness_rechecks_everything_per_read(tmp_path: Path) -> None:
    store, _, _, source, authority, egress, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    payload = _payload()
    _publish(store, observations, _worker(), clock, payload)
    view, disposition = store.get_current_with_disposition("pub-01", principal=_operator(), now=NOW)
    assert disposition is DeltaPublicationDispositionV1.AVAILABLE and view is not None
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) == payload[:8]
    with pytest.raises(ValueError, match="exceeds"):
        store.read_bytes("pub-01", principal=_operator(), offset=0, length=len(payload) + 1)
    source.live = False
    assert store.get_current("pub-01", principal=_operator(), now=NOW) is None
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) is None
    source.live = True
    authority.runtime_current = False
    _, disposition = store.get_current_with_disposition("pub-01", principal=_operator(), now=NOW)
    assert disposition is DeltaPublicationDispositionV1.RUNTIME_NOT_CURRENT
    authority.runtime_current = True
    egress.allowed = False
    _, disposition = store.get_current_with_disposition("pub-01", principal=_operator(), now=NOW)
    assert disposition is DeltaPublicationDispositionV1.EGRESS_DENIED
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) is None
    egress.allowed = True
    clock.now = NOW + timedelta(seconds=3_601)
    _, disposition = store.get_current_with_disposition("pub-01", principal=_operator(), now=NOW)
    assert disposition is DeltaPublicationDispositionV1.EXPIRED
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) is None


def test_mid_read_revocation_or_egress_loss_leaks_no_bytes(tmp_path: Path) -> None:
    """Old ordering trusted the pre-guard snapshot; the post-stream recheck must not."""
    for mode in ("source", "egress"):
        case_path = _sub(tmp_path, mode)
        store, _, _, source, _, egress, _, observations, clock = _harness(case_path)
        store.create_intent(principal=_operator(), **_intent_kwargs())
        _publish(store, observations, _worker(), clock, _payload())
        if mode == "source":
            source.max_calls = 1
        else:
            egress.max_calls = 1
        assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) is None
        _, disposition = store.get_current_with_disposition(
            "pub-01", principal=_operator(), now=NOW
        )
        assert disposition is not DeltaPublicationDispositionV1.AVAILABLE


def test_post_stream_expiry_uses_trusted_clock_not_caller_time(tmp_path: Path) -> None:
    """A stream that outlives the intent must fail even though it started current."""
    store, journal_path, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs(lifetime_seconds=600))
    _publish(store, observations, _worker(), clock, _payload())
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) == _payload()[:8]
    real_bytes = store._bytes  # noqa: SLF001 - white-box time-advance seam for this test

    class _AdvancingPort:
        def __init__(self, inner):  # type: ignore[no-untyped-def]
            self._inner = inner

        def stage_stream(self, **kwargs):  # type: ignore[no-untyped-def]
            return self._inner.stage_stream(**kwargs)

        def commit(self, **kwargs):  # type: ignore[no-untyped-def]
            return self._inner.commit(**kwargs)

        def discard(self, **kwargs):  # type: ignore[no-untyped-def]
            return self._inner.discard(**kwargs)

        def exists(self, **kwargs):  # type: ignore[no-untyped-def]
            return self._inner.exists(**kwargs)

        def open_read(self, **kwargs):  # type: ignore[no-untyped-def]
            clock.now = NOW + timedelta(seconds=601)
            return self._inner.open_read(**kwargs)

    store._bytes = _AdvancingPort(real_bytes)  # noqa: SLF001
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) is None
    _, disposition = store.get_current_with_disposition("pub-01", principal=_operator(), now=NOW)
    assert disposition is DeltaPublicationDispositionV1.EXPIRED
    clock.now = NOW


def test_content_tamper_same_size_fails_closed_on_read(tmp_path: Path) -> None:
    store, _, byte_root, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    payload = _payload()
    _publish(store, observations, _worker(), clock, payload)
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) == payload[:8]
    target = byte_root / "delta-out-pub-01.tiff"
    tampered = bytearray(payload)
    tampered[0] ^= 0xFF
    assert len(tampered) == len(payload)
    target.write_bytes(bytes(tampered))
    view, disposition = store.get_current_with_disposition("pub-01", principal=_operator(), now=NOW)
    assert view is None and disposition is DeltaPublicationDispositionV1.BYTES_UNAVAILABLE
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) is None
    target.write_bytes(target.read_bytes()[: len(payload) - 1])
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) is None


def test_revoke_keeps_historical_descriptor_immutable(tmp_path: Path) -> None:
    store, journal_path, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    payload = _payload()
    published = _publish(store, observations, _worker(), clock, payload)
    assert published is not None
    before = published.descriptor.canonical_digest()
    revoked = store.revoke(
        principal=_operator(), publication_id="pub-01", reason="SUPERSEDED", now=NOW
    )
    assert revoked is not None and revoked.status is DeltaPublicationStatusV1.REVOKED
    assert revoked.descriptor.canonical_digest() == before
    assert revoked.reason == "SUPERSEDED"
    view, disposition = store.get_current_with_disposition("pub-01", principal=_operator(), now=NOW)
    assert view is None and disposition is DeltaPublicationDispositionV1.REVOKED
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) is None
    assert len(_journal_events(journal_path)) == 4


def test_cancel_and_failure_close_the_fence(tmp_path: Path) -> None:
    store, journal_path, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs(publication_id="pub-c"))
    canceled = store.cancel_intent(
        principal=_operator(), publication_id="pub-c", reason="NO_LONGER_NEEDED", now=NOW
    )
    assert canceled is not None and canceled.status is DeltaPublicationStatusV1.CANCELED
    assert (
        store.acquire_upload_lease(
            worker_principal=_worker(),
            publication_id="pub-c",
            worker_instance_id="inst-1",
            lease_acquisition_id="acq-c",
            now=NOW,
        )
        is None
    )
    store.create_intent(principal=_operator(), **_intent_kwargs(publication_id="pub-f"))
    lease = _leased(store, _worker(), clock, pub="pub-f", acq="acq-f")
    assert lease is not None
    failed = store.record_upload_failure(
        worker_principal=_worker(),
        publication_id="pub-f",
        worker_instance_id="inst-1",
        lease_generation=lease.lease_generation,
        reason="WORKER_OOM",
        now=NOW,
    )
    assert failed is not None and failed.status is DeltaPublicationStatusV1.FAILED
    assert (
        store.publish_output(
            worker_principal=_worker(),
            publication_id="pub-f",
            worker_instance_id="inst-1",
            lease_generation=lease.lease_generation,
            byte_stream=io.BytesIO(_payload()),
        )
        is None
    )
    _, disposition = store.get_current_with_disposition("pub-f", principal=_operator(), now=NOW)
    assert disposition is DeltaPublicationDispositionV1.FAILED


def test_foreign_and_unknown_are_indistinguishable_on_read(tmp_path: Path) -> None:
    store, _, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    _publish(store, observations, _worker(), clock, _payload())
    foreign = _operator(org="org-b")
    for principal, publication_id in ((foreign, "pub-01"), (_operator(), "pub-missing")):
        view, disposition = store.get_current_with_disposition(
            publication_id, principal=principal, now=NOW
        )
        assert view is None and disposition is DeltaPublicationDispositionV1.NOT_FOUND


def test_analysis_worker_cannot_read_arbitrary_site(tmp_path: Path) -> None:
    store, _, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    _publish(store, observations, _worker(), clock, _payload())
    with pytest.raises(PermissionError):
        store.get_current("pub-01", principal=_worker(), now=NOW)
    with pytest.raises(PermissionError):
        store.read_bytes("pub-01", principal=_worker(), offset=0, length=8)


def test_mcp_client_read_scope_is_enforced(tmp_path: Path) -> None:
    store, _, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    _publish(store, observations, _worker(), clock, _payload())
    view, _ = store.get_current_with_disposition("pub-01", principal=_mcp_client(), now=NOW)
    assert view is not None
    view, disposition = store.get_current_with_disposition(
        "pub-01", principal=_mcp_client(site="site-foreign"), now=NOW
    )
    assert view is None and disposition is DeltaPublicationDispositionV1.NOT_FOUND


def test_store_exposes_no_raw_byte_paths(tmp_path: Path) -> None:
    store, _, byte_root, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    _publish(store, observations, _worker(), clock, _payload())
    for name in ("byte_root", "root", "path", "file_path", "raw_path", "download_url"):
        assert not hasattr(store, name), name
    view, _ = store.get_current_with_disposition("pub-01", principal=_operator(), now=NOW)
    assert view is not None
    assert str(byte_root) not in repr(view)
    assert str(byte_root) not in repr(view.descriptor)


def test_router_auth_boundary_with_existing_mechanisms(tmp_path: Path) -> None:
    import hashlib as _hashlib

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ksi_core.identity.auth import AuthRegistry, PrincipalTokenRecord, mount_auth

    store, _, _, _, _, _, _, observations, _ = _harness(tmp_path)
    router = build_external_delta_publication_router(store=store, clock=lambda: NOW)
    app = FastAPI()
    app.include_router(router)
    operator_token = "delta-operator-token"
    worker_token = "delta-worker-token"
    processing_token = "delta-processing-token"
    mount_auth(
        app,
        AuthRegistry(
            records=(
                PrincipalTokenRecord(
                    token_sha256=_hashlib.sha256(operator_token.encode()).hexdigest(),
                    principal=_operator(),
                ),
                PrincipalTokenRecord(
                    token_sha256=_hashlib.sha256(worker_token.encode()).hexdigest(),
                    principal=_worker(),
                ),
                PrincipalTokenRecord(
                    token_sha256=_hashlib.sha256(processing_token.encode()).hexdigest(),
                    principal=_processing_worker(),
                ),
            )
        ),
    )
    client = TestClient(app, raise_server_exceptions=False)
    operator = {"Authorization": "Bearer " + operator_token}
    worker = {"Authorization": "Bearer " + worker_token}
    processing = {"Authorization": "Bearer " + processing_token}
    assert (
        client.post(
            "/v1/sites/site-a/work-areas/work-area-a/delta-publications",
            headers=processing,
            json={},
        ).status_code
        == 403
    )
    body = {
        "publicationId": "pub-01",
        "sourceCalculationIdentityDigest": CALC_DIGEST,
        "sourceNumericResultIdentityDigest": NUMERIC_DIGEST,
        "sourceCoverageWitnessDigest": COVERAGE_DIGEST,
        "lifetimeSeconds": 3_600,
    }
    created = client.post(
        "/v1/sites/site-a/work-areas/work-area-a/delta-publications",
        headers=operator,
        json=body,
    )
    assert created.status_code == 200, created.text
    leased = client.post(
        "/v1/internal/delta-publication-uploads/pub-01/lease",
        headers=worker,
        json={"workerInstanceId": "inst-1", "leaseAcquisitionId": "acq-1"},
    )
    assert leased.status_code == 200, leased.text
    generation = leased.json()["leaseGeneration"]
    assert generation == 1
    payload = _payload()
    observations.bind(_observation(payload, generation=generation))
    uploaded = client.post(
        "/v1/internal/delta-publication-uploads/pub-01/bytes",
        headers=dict(worker, **{"Content-Type": "application/octet-stream"}),
        params={
            "worker_instance_id": "inst-1",
            "lease_generation": generation,
        },
        content=payload,
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["descriptor"]["dtype"] == "FLOAT64"
    seen = client.get(
        "/v1/sites/site-a/work-areas/work-area-a/delta-publications/pub-01", headers=operator
    )
    assert seen.status_code == 200, seen.text
    processing_upload = client.post(
        "/v1/internal/delta-publication-uploads/pub-01/bytes",
        headers=dict(processing, **{"Content-Type": "application/octet-stream"}),
        params={
            "worker_instance_id": "inst-1",
            "lease_generation": generation,
        },
        content=payload,
    )
    assert processing_upload.status_code in (401, 403)
    assert (
        client.get("/v1/sites/site-a/work-areas/work-area-a/delta-publications/pub-01").status_code
        == 401
    )


def test_publish_without_observation_fails_closed(tmp_path: Path) -> None:
    """A valid lease plus arbitrary caller bytes never publish without acceptance."""
    store, journal_path, _, _, _, _, _, _, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    lease = _leased(store, _worker(), clock)
    assert lease is not None
    payload = _payload()
    assert (
        store.publish_output(
            worker_principal=_worker(),
            publication_id="pub-01",
            worker_instance_id="inst-1",
            lease_generation=lease.lease_generation,
            byte_stream=io.BytesIO(payload),
        )
        is None
    )
    assert len(_journal_events(journal_path)) == 2
    _, disposition = store.get_current_with_disposition("pub-01", principal=_operator(), now=NOW)
    assert disposition is DeltaPublicationDispositionV1.NOT_YET_PUBLISHED


def test_publish_with_mismatched_observation_fails_closed(tmp_path: Path) -> None:
    store, journal_path, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    lease = _leased(store, _worker(), clock)
    assert lease is not None
    payload = _payload()

    def attempt(obs):  # type: ignore[no-untyped-def]
        observations.bind(obs)
        return store.publish_output(
            worker_principal=_worker(),
            publication_id="pub-01",
            worker_instance_id="inst-1",
            lease_generation=lease.lease_generation,
            byte_stream=io.BytesIO(payload),
        )

    assert attempt(_observation(payload, generation=lease.lease_generation + 1)) is None
    assert attempt(_observation(payload, worker_id="analysis-worker-2")) is None
    assert attempt(_observation(payload, instance="inst-other")) is None
    assert attempt(_observation(payload, version=V2_CONTRACT)) is None
    # Bytes that do not match the accepted observation fail at staging:
    # nothing is published or journaled either way.
    with pytest.raises(ValueError, match="hash"):
        attempt(_observation(payload, sha=_digest("other-bytes")))
    with pytest.raises(ValueError, match="size"):
        attempt(_observation(payload, size=len(payload) + 1))
    assert len(_journal_events(journal_path)) == 2


def test_observation_rotated_between_checks_fails_closed(tmp_path: Path) -> None:
    store, journal_path, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    lease = _leased(store, _worker(), clock)
    assert lease is not None
    payload = _payload()
    good = _observation(payload)

    def attempt():  # type: ignore[no-untyped-def]
        return store.publish_output(
            worker_principal=_worker(),
            publication_id="pub-01",
            worker_instance_id="inst-1",
            lease_generation=lease.lease_generation,
            byte_stream=io.BytesIO(payload),
        )

    observations.script = [good, None]
    assert attempt() is None
    assert len(_journal_events(journal_path)) == 2
    rotated = _observation(_payload(1_023))
    observations.script = [good, rotated]
    assert attempt() is None
    assert len(_journal_events(journal_path)) == 2
    observations.script = []
    observations.bind(good)
    assert attempt() is not None


def test_published_event_persists_observation_binding(tmp_path: Path) -> None:
    store, journal_path, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    payload = _payload()
    view = _publish(store, observations, _worker(), clock, payload)
    assert view is not None
    events = _journal_events(journal_path)
    published = next(e for e in events if e["kind"] == "delta-publication-published")
    bound = _observation(payload)
    assert published["observationDigest"] == bound.canonical_digest()
    assert published["observation"] == bound.canonical_payload()


def test_large_output_slice_is_bounded_and_verified(tmp_path: Path) -> None:
    store, _, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    payload = _payload(300_000)
    assert len(payload) > 4 * 65_536
    view = _publish(store, observations, _worker(), clock, payload)
    assert view is not None
    offset = 100_000
    assert (
        store.read_bytes("pub-01", principal=_operator(), offset=offset, length=16)
        == payload[offset : offset + 16]
    )
    with pytest.raises(ValueError, match="range"):
        store.read_bytes("pub-01", principal=_operator(), offset=0, length=len(payload) + 1)


def test_byte_store_owner_hardening(tmp_path: Path) -> None:
    import os as _os
    import stat as _stat

    root = tmp_path / "bytes"
    keeper = FilesystemDeltaByteStore(root)
    assert _stat.S_IMODE(_os.stat(root).st_mode) == 0o700
    assert _stat.S_IMODE(_os.stat(root / ".staging").st_mode) == 0o700
    payload = _payload(64)
    staged = keeper.stage_stream(
        stream=io.BytesIO(payload),
        expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        expected_size_bytes=len(payload),
        max_bytes=1_000_000,
    )
    assert _stat.S_IMODE(_os.stat(staged).st_mode) == 0o600
    keeper.discard(staged=staged)
    assert not staged.exists()

    with pytest.raises(ValueError):
        FilesystemDeltaByteStore(Path("relative/root"))
    with pytest.raises(ValueError):
        FilesystemDeltaByteStore(tmp_path / ".." / "escape")
    link_root = tmp_path / "linked"
    real_root = tmp_path / "real"
    real_root.mkdir()
    link_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(ValueError):
        FilesystemDeltaByteStore(link_root)
    file_root = tmp_path / "file-root"
    file_root.write_bytes(b"x")
    with pytest.raises(ValueError):
        FilesystemDeltaByteStore(file_root)


def test_committed_byte_alias_or_mode_drift_fails_closed_on_read(tmp_path: Path) -> None:
    import os as _os

    store, _, byte_root, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    payload = _payload()
    _publish(store, observations, _worker(), clock, payload)
    final = byte_root / "delta-out-pub-01.tiff"
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) == payload[:8]

    swapped = byte_root / "swap.bin"
    swapped.write_bytes(payload)
    final.unlink()
    final.symlink_to(swapped)
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) is None
    final.unlink()
    final.write_bytes(payload)
    _os.link(final, byte_root / "hardlink.bin")
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) is None
    (byte_root / "hardlink.bin").unlink()
    _os.chmod(final, 0o644)
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) is None


def test_lease_truncated_by_short_intent_and_late_lease(tmp_path: Path) -> None:
    store, journal_path, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs(lifetime_seconds=30))
    lease = _leased(store, _worker(), clock)
    assert lease is not None
    assert lease.lease_expires_at == NOW + timedelta(seconds=30)
    payload = _payload()
    observations.bind(_observation(payload, generation=lease.lease_generation))
    view = store.publish_output(
        worker_principal=_worker(),
        publication_id="pub-01",
        worker_instance_id="inst-1",
        lease_generation=lease.lease_generation,
        byte_stream=io.BytesIO(payload),
    )
    assert view is not None and view.status is DeltaPublicationStatusV1.PUBLISHED
    clock.now = NOW + timedelta(seconds=31)
    assert store.read_bytes("pub-01", principal=_operator(), offset=0, length=8) is None
    _, disposition = store.get_current_with_disposition("pub-01", principal=_operator(), now=NOW)
    assert disposition is DeltaPublicationDispositionV1.EXPIRED

    clock.now = NOW
    store.create_intent(
        principal=_operator(), **_intent_kwargs(publication_id="pub-late", lifetime_seconds=30)
    )
    clock.now = NOW + timedelta(seconds=25)
    late_lease = _leased(store, _worker(), clock, pub="pub-late", acq="acq-late")
    assert late_lease is not None
    assert late_lease.lease_expires_at == NOW + timedelta(seconds=30)
    late_payload = _payload(16)
    observations.bind(
        _observation(late_payload, pub="pub-late", generation=late_lease.lease_generation)
    )
    late_view = store.publish_output(
        worker_principal=_worker(),
        publication_id="pub-late",
        worker_instance_id="inst-1",
        lease_generation=late_lease.lease_generation,
        byte_stream=io.BytesIO(late_payload),
    )
    assert late_view is not None and late_view.status is DeltaPublicationStatusV1.PUBLISHED
    clock.now = NOW


def test_cancel_revoke_stamp_trusted_clock_not_caller_time(tmp_path: Path) -> None:
    import json as _json

    store, journal_path, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs(publication_id="pub-c"))
    canceled = store.cancel_intent(
        principal=_operator(),
        publication_id="pub-c",
        reason="STALE",
        now=NOW - timedelta(seconds=3_600),
    )
    assert canceled is not None and canceled.status is DeltaPublicationStatusV1.CANCELED
    events = _journal_events(journal_path)
    assert events[-1]["canceledAt"] == NOW.isoformat()

    store.create_intent(principal=_operator(), **_intent_kwargs(publication_id="pub-r"))
    _publish(store, observations, _worker(), clock, _payload(), pub="pub-r", acq="acq-r")
    revoked = store.revoke(
        principal=_operator(),
        publication_id="pub-r",
        reason="SUPERSEDED",
        now=NOW + timedelta(seconds=7_200),
    )
    assert revoked is not None and revoked.status is DeltaPublicationStatusV1.REVOKED
    events = _journal_events(journal_path)
    assert events[-1]["revokedAt"] == NOW.isoformat()
    raw = _json.loads(journal_path.read_text().splitlines()[-1])
    assert raw["revokedAt"] == NOW.isoformat()


def test_publish_respects_changed_worker_grants(tmp_path: Path) -> None:
    scoped = _worker(sites=frozenset({"site-a"}), areas=frozenset({"work-area-a"}))
    narrowed = _worker(
        principal_id="analysis-worker-1",
        sites=frozenset({"site-other"}),
        areas=frozenset({"area-other"}),
    )
    store, journal_path, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs(publication_id="pub-g"))
    lease = _leased(store, scoped, clock, pub="pub-g", acq="acq-g")
    assert lease is not None
    assert (
        store.intent_for_worker("pub-g", worker_principal=narrowed, worker_instance_id="inst-1")
        is None
    )
    payload = _payload()
    assert (
        store.publish_output(
            worker_principal=narrowed,
            publication_id="pub-g",
            worker_instance_id="inst-1",
            lease_generation=lease.lease_generation,
            byte_stream=io.BytesIO(payload),
        )
        is None
    )
    assert (
        store.record_upload_failure(
            worker_principal=narrowed,
            publication_id="pub-g",
            worker_instance_id="inst-1",
            lease_generation=lease.lease_generation,
            reason="CHANGED_GRANTS",
            now=NOW,
        )
        is None
    )
    assert len(_journal_events(journal_path)) == 2
    observations.bind(
        _observation(
            payload, pub="pub-g", worker_id="analysis-worker-1", generation=lease.lease_generation
        )
    )
    view = store.publish_output(
        worker_principal=scoped,
        publication_id="pub-g",
        worker_instance_id="inst-1",
        lease_generation=lease.lease_generation,
        byte_stream=io.BytesIO(payload),
    )
    assert view is not None and view.status is DeltaPublicationStatusV1.PUBLISHED


def test_repeated_lease_rechecks_currentness_before_return(tmp_path: Path) -> None:
    store, journal_path, _, source, authority, _, _, _, clock = _harness(tmp_path)
    for index, publication_id in enumerate(("pub-s", "pub-p", "pub-r")):
        store.create_intent(principal=_operator(), **_intent_kwargs(publication_id=publication_id))
        lease = _leased(store, _worker(), clock, pub=publication_id, acq=f"acq-{index}")
        assert lease is not None
    assert len(_journal_events(journal_path)) == 6

    source.live = False
    assert _leased(store, _worker(), clock, pub="pub-s", acq="acq-0") is None
    source.live = True
    authority.policy_current = False
    assert _leased(store, _worker(), clock, pub="pub-p", acq="acq-1") is None
    authority.policy_current = True
    authority.runtime_current = False
    assert _leased(store, _worker(), clock, pub="pub-r", acq="acq-2") is None
    authority.runtime_current = True
    assert len(_journal_events(journal_path)) == 6
    assert _journal_events(journal_path)[1]["kind"] == "delta-publication-upload-leased"


def test_intent_matches_scope_predicate(tmp_path: Path) -> None:
    store, _, _, _, _, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    assert (
        store.intent_matches_scope(
            principal=_operator(),
            publication_id="pub-01",
            site_id="site-a",
            work_area_id="work-area-a",
        )
        is True
    )
    assert (
        store.intent_matches_scope(
            principal=_operator(),
            publication_id="pub-01",
            site_id="site-wrong",
            work_area_id="work-area-a",
        )
        is False
    )
    assert (
        store.intent_matches_scope(
            principal=_operator(),
            publication_id="pub-01",
            site_id="site-a",
            work_area_id="area-wrong",
        )
        is False
    )
    assert (
        store.intent_matches_scope(
            principal=_operator(org="org-b"),
            publication_id="pub-01",
            site_id="site-a",
            work_area_id="work-area-a",
        )
        is False
    )
    assert (
        store.intent_matches_scope(
            principal=_operator(),
            publication_id="pub-missing",
            site_id="site-a",
            work_area_id="work-area-a",
        )
        is False
    )
    assert (
        store.intent_matches_scope(
            principal=_operator(),
            publication_id="not a publication?!",
            site_id="site-a",
            work_area_id="work-area-a",
        )
        is False
    )
    scoped = _scoped_operator(frozenset({"site-a"}), frozenset({"area-other"}))
    assert (
        store.intent_matches_scope(
            principal=scoped,
            publication_id="pub-01",
            site_id="site-a",
            work_area_id="work-area-a",
        )
        is False
    )
    _publish(store, observations, _worker(), clock, _payload())
    assert (
        store.intent_matches_scope(
            principal=_operator(),
            publication_id="pub-01",
            site_id="site-a",
            work_area_id="work-area-a",
        )
        is True
    )


def test_request_publication_derives_grid_from_source(tmp_path: Path) -> None:
    store, journal_path, _, _, _, _, _, _, clock = _harness(tmp_path)
    assert clock.now == NOW
    view = store.request_publication(
        principal=_operator(),
        publication_id="pub-req",
        site_id="site-a",
        work_area_id="work-area-a",
        source_calculation_identity_digest=CALC_DIGEST,
        source_numeric_result_identity_digest=NUMERIC_DIGEST,
        source_coverage_witness_digest=COVERAGE_DIGEST,
        lifetime_seconds=3_600,
    )
    assert view.status is DeltaPublicationStatusV1.PENDING
    assert view.grid_rows == GRID_ROWS and view.grid_columns == GRID_COLUMNS
    assert view.output_id == "delta-out-pub-req"
    events = _journal_events(journal_path)
    assert len(events) == 1
    assert events[0]["sourceContractVersion"] == V3_CONTRACT
    assert events[0]["transform"] == list(TRANSFORM)
    assert events[0]["bounds"] == list(BOUNDS)

    with pytest.raises(RuntimeError, match="not currently available"):
        store.request_publication(
            principal=_operator(),
            publication_id="pub-unknown",
            site_id="site-a",
            work_area_id="work-area-a",
            source_calculation_identity_digest=_digest("unknown-calc"),
            source_numeric_result_identity_digest=NUMERIC_DIGEST,
            source_coverage_witness_digest=COVERAGE_DIGEST,
            lifetime_seconds=3_600,
        )
    with pytest.raises(RuntimeError, match="not currently available"):
        store.request_publication(
            principal=_operator(),
            publication_id="pub-borrowed",
            site_id="site-b",
            work_area_id="work-area-b",
            source_calculation_identity_digest=CALC_DIGEST,
            source_numeric_result_identity_digest=NUMERIC_DIGEST,
            source_coverage_witness_digest=COVERAGE_DIGEST,
            lifetime_seconds=3_600,
        )
    with pytest.raises(TypeError):
        store.request_publication(
            principal=_operator(),
            publication_id="pub-grid",
            site_id="site-a",
            work_area_id="work-area-a",
            source_calculation_identity_digest=CALC_DIGEST,
            source_numeric_result_identity_digest=NUMERIC_DIGEST,
            source_coverage_witness_digest=COVERAGE_DIGEST,
            lifetime_seconds=3_600,
            transform=TRANSFORM,
        )
    assert len(_journal_events(journal_path)) == 1


def test_worker_discovery_lists_only_acquirable_pending(tmp_path: Path) -> None:
    store, journal_path, _, source, authority, _, _, observations, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs(publication_id="pub-free"))
    store.create_intent(principal=_operator(), **_intent_kwargs(publication_id="pub-held"))
    store.create_intent(principal=_operator(), **_intent_kwargs(publication_id="pub-done"))
    store.create_intent(principal=_operator(), **_intent_kwargs(publication_id="pub-gone"))
    held = _leased(store, _worker(), clock, pub="pub-held", acq="acq-held")
    assert held is not None
    observations.bind(_observation(_payload(), pub="pub-done", generation=1))
    done_lease = _leased(store, _worker(), clock, pub="pub-done", acq="acq-done")
    assert done_lease is not None
    done = store.publish_output(
        worker_principal=_worker(),
        publication_id="pub-done",
        worker_instance_id="inst-1",
        lease_generation=done_lease.lease_generation,
        byte_stream=io.BytesIO(_payload()),
    )
    assert done is not None
    canceled = store.cancel_intent(
        principal=_operator(), publication_id="pub-gone", reason="NOPE", now=NOW
    )
    assert canceled is not None
    assert store.list_pending_for_worker(worker_principal=_worker()) == ("pub-free",)
    assert len(_journal_events(journal_path)) == 8

    other = _worker(principal_id="analysis-worker-2")
    discovered = store.list_pending_for_worker(worker_principal=other)
    assert discovered == ("pub-free",)
    assert all(type(item) is str for item in discovered)
    assert store.list_pending_for_worker(worker_principal=_worker(org="org-b")) == ()
    narrowed = _worker(sites=frozenset({"site-other"}))
    assert store.list_pending_for_worker(worker_principal=narrowed) == ()
    with pytest.raises(PermissionError):
        store.list_pending_for_worker(worker_principal=_operator())
    with pytest.raises(PermissionError):
        store.list_pending_for_worker(worker_principal=_processing_worker())
    with pytest.raises(ValueError):
        store.list_pending_for_worker(worker_principal=_worker(), limit=0)
    with pytest.raises(ValueError):
        store.list_pending_for_worker(worker_principal=_worker(), limit=51)

    source.live = False
    assert store.list_pending_for_worker(worker_principal=_worker()) == ()
    source.live = True
    authority.policy_current = False
    assert store.list_pending_for_worker(worker_principal=_worker()) == ()
    authority.policy_current = True
    authority.runtime_current = False
    assert store.list_pending_for_worker(worker_principal=_worker()) == ()
    authority.runtime_current = True
    assert store.list_pending_for_worker(worker_principal=_worker()) == ("pub-free",)
    assert len(_journal_events(journal_path)) == 8


def test_worker_discovery_limit_and_expiry(tmp_path: Path) -> None:
    store, _, _, _, _, _, _, _, clock = _harness(tmp_path)
    for index in range(3):
        store.create_intent(principal=_operator(), **_intent_kwargs(publication_id=f"pub-{index}"))
    assert store.list_pending_for_worker(worker_principal=_worker(), limit=2) == (
        "pub-0",
        "pub-1",
    )
    assert store.list_pending_for_worker(worker_principal=_worker()) == (
        "pub-0",
        "pub-1",
        "pub-2",
    )
    clock.now = NOW + timedelta(seconds=3_601)
    assert store.list_pending_for_worker(worker_principal=_worker()) == ()
    clock.now = NOW


def test_worker_discovery_excludes_attempt_capped_intents(tmp_path: Path) -> None:
    store, _, _, _, _, _, _, _, clock = _harness(_sub(tmp_path, "capped"), max_upload_attempts=1)
    store.create_intent(principal=_operator(), **_intent_kwargs(publication_id="pub-cap"))
    assert store.list_pending_for_worker(worker_principal=_worker()) == ("pub-cap",)
    lease = _leased(store, _worker(), clock, pub="pub-cap", acq="acq-cap")
    assert lease is not None
    assert store.list_pending_for_worker(worker_principal=_worker()) == ()
    other = _worker(principal_id="analysis-worker-2")
    assert store.list_pending_for_worker(worker_principal=other) == ()


def test_upload_attempts_capped_without_append(tmp_path: Path) -> None:
    store, journal_path, _, _, _, _, _, _, clock = _harness(tmp_path, max_upload_attempts=2)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    first = _leased(store, _worker(), clock, acq="acq-1")
    assert first is not None and first.lease_generation == 1
    assert len(_journal_events(journal_path)) == 2
    same = _leased(store, _worker(), clock, acq="acq-1")
    assert same is not None and same.lease_generation == 1
    assert len(_journal_events(journal_path)) == 2
    clock.now = NOW + timedelta(seconds=601)
    second = store.acquire_upload_lease(
        worker_principal=_worker(),
        publication_id="pub-01",
        worker_instance_id="inst-1",
        lease_acquisition_id="acq-2",
        now=clock.now,
    )
    assert second is not None and second.lease_generation == 2
    assert len(_journal_events(journal_path)) == 3
    clock.now = NOW + timedelta(seconds=1_202)
    assert (
        store.acquire_upload_lease(
            worker_principal=_worker(),
            publication_id="pub-01",
            worker_instance_id="inst-1",
            lease_acquisition_id="acq-3",
            now=clock.now,
        )
        is None
    )
    assert len(_journal_events(journal_path)) == 3
    clock.now = NOW


def test_worker_discovery_lists_lapsed_lease_for_recovery(tmp_path: Path) -> None:
    store, journal_path, _, _, _, _, _, _, clock = _harness(tmp_path)
    store.create_intent(principal=_operator(), **_intent_kwargs())
    assert store.list_pending_for_worker(worker_principal=_worker()) == ("pub-01",)
    lease = _leased(store, _worker(), clock)
    assert lease is not None
    assert store.list_pending_for_worker(worker_principal=_worker()) == ()
    clock.now = NOW + timedelta(seconds=601)
    assert store.list_pending_for_worker(worker_principal=_worker()) == ("pub-01",)
    other = _worker(principal_id="analysis-worker-2")
    assert store.list_pending_for_worker(worker_principal=other) == ("pub-01",)
    assert len(_journal_events(journal_path)) == 2
    retaken = store.acquire_upload_lease(
        worker_principal=other,
        publication_id="pub-01",
        worker_instance_id="inst-2",
        lease_acquisition_id="acq-other",
        now=clock.now,
    )
    assert retaken is not None and retaken.lease_generation == 2
    assert (
        store.acquire_upload_lease(
            worker_principal=_worker(),
            publication_id="pub-01",
            worker_instance_id="inst-1",
            lease_acquisition_id="acq-1",
            now=clock.now,
        )
        is None
    )
    assert len(_journal_events(journal_path)) == 3
    clock.now = NOW
