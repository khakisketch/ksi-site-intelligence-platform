"""Byte delivery uses real Core job/grant/currentness authorities, not public URLs."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.identity.auth import PrincipalKind, Role
from spatial_data_job_fixture import NOW, issue, job_graph, job_store, lease, reserve_and_complete


def completed_graph(tmp_path: Path) -> tuple[SimpleNamespace, Any, Any, SimpleNamespace]:
    graph = job_graph(tmp_path)
    jobs = job_store(graph)
    job = issue(jobs, graph)
    accepted = reserve_and_complete(jobs, graph, job, lease(jobs, graph, job))
    return graph, jobs, job, accepted


def test_download_owner_resolves_only_accepted_immutable_output(tmp_path: Path) -> None:
    graph, jobs, job, accepted = completed_graph(tmp_path)
    result = jobs.require_download(job_id=job.job_id, principal=graph.principal, now=NOW)
    assert result.observation == accepted.observation
    assert result.target == accepted.target and result.receipt == accepted.receipt
    assert result.job.requester_principal_id == graph.principal.principal_id


@pytest.mark.parametrize(
    "change,reason",
    [
        ("foreign-org", "NOT_FOUND"),
        ("foreign-owner", "NOT_FOUND"),
        ("admin-owner", "NOT_FOUND"),
        ("revoked", "ACCESS_REVOKED"),
        ("retention", "RETENTION_EXPIRED"),
        ("lane", "CURRENTNESS_UNAVAILABLE"),
    ],
)
def test_download_currentness_is_not_historical_visibility_or_admin_sharing(
    tmp_path: Path, change: str, reason: str
) -> None:
    graph, jobs, job, _ = completed_graph(tmp_path)
    principal, now = graph.principal, NOW
    if change == "foreign-org":
        principal = replace(principal, organization_id="foreign")
    elif change in ("foreign-owner", "admin-owner"):
        principal = replace(
            principal,
            principal_id="another",
            kind=PrincipalKind.OPERATOR,
            role=Role.ADMIN if change == "admin-owner" else Role.FIELD_OPERATOR,
        )
    elif change == "retention":
        now += timedelta(seconds=graph.data_policy.retention_seconds)
    elif change == "revoked":
        from ksi_event_contracts.spatial_data_authority import SpatialDataRevocationV1

        graph.grants.revoke(
            SpatialDataRevocationV1(
                grant_id=graph.grant.grant_id,
                revision=graph.grant.revision,
                grant_digest=graph.grant.grant_digest,
                organization_id=graph.principal.organization_id,
                revoked_at=NOW,
                reason="withdrawn",
            ).sealed()
        )
    else:
        graph.authority.enabled = False
    with pytest.raises(SpatialDataDomainError, match=reason):
        jobs.require_download(job_id=job.job_id, principal=principal, now=now)


def test_queued_job_cannot_supply_download_bytes(tmp_path: Path) -> None:
    graph = job_graph(tmp_path)
    jobs = job_store(graph)
    job = issue(jobs, graph)
    with pytest.raises(SpatialDataDomainError, match="NOT_READY"):
        jobs.require_download(job_id=job.job_id, principal=graph.principal, now=NOW)


def test_download_spools_full_hash_and_releases_reserved_disk_on_close(tmp_path: Path) -> None:
    from spatial_data_download_fixture import delivery_graph, prepare

    graph = delivery_graph(tmp_path)
    prepared = prepare(graph)
    assert graph.storage.opened == graph.storage.closed == 1
    assert graph.service.active_downloads == 1
    assert graph.service.reserved_bytes == len(graph.payload)
    assert prepared.size_bytes == len(graph.payload) and prepared.sha256 == graph.observation.sha256
    assert b"".join(prepared.iter_chunks()) == graph.payload
    prepared.close()
    prepared.close()
    assert list(graph.spool.iterdir()) == []
    assert graph.service.active_downloads == graph.service.reserved_bytes == 0


@pytest.mark.parametrize(
    "change", ["wrong-hash", "short", "long", "wrong-version", "oversized-chunk", "not-bytes"]
)
def test_download_integrity_failure_never_returns_prepared_body_and_releases_quota(
    tmp_path: Path, change: str
) -> None:
    from contextlib import contextmanager

    from spatial_data_download_fixture import delivery_graph, prepare

    graph = delivery_graph(tmp_path)
    if change == "wrong-hash":
        graph.storage.payload = b"x" * len(graph.payload)
    elif change == "short":
        graph.storage.payload = graph.payload[:-1]
    elif change == "long":
        graph.storage.payload += b"x"
    elif change == "wrong-version":
        graph.storage.observation = replace(graph.observation, version_id="other-version")
    else:

        @contextmanager
        def hostile(*args: Any, **kwargs: Any) -> Iterator[Iterator[Any]]:
            yield iter(
                [
                    b"x" * (graph.graph.data_policy.stream_chunk_bytes + 1)
                    if change == "oversized-chunk"
                    else "not-bytes"
                ]
            )

        graph.storage.open_version = hostile
    with pytest.raises(SpatialDataDomainError, match="INTEGRITY_MISMATCH"):
        prepare(graph)
    assert graph.service.active_downloads == graph.service.reserved_bytes == 0
    assert list(graph.spool.iterdir()) == []


def test_download_fresh_scope_loss_after_spool_never_yields_prepared_response(
    tmp_path: Path,
) -> None:
    from spatial_data_download_fixture import delivery_graph, prepare

    graph = delivery_graph(tmp_path)
    graph.storage.after_read = lambda: setattr(
        graph.credentials, "principal", replace(graph.graph.principal, organization_id="foreign")
    )
    with pytest.raises(SpatialDataDomainError, match="NOT_FOUND"):
        prepare(graph)
    assert graph.storage.closed == 1 and list(graph.spool.iterdir()) == []
    assert graph.service.active_downloads == 0


def test_download_reserves_finite_concurrency_before_storage_io(tmp_path: Path) -> None:
    from spatial_data_download_fixture import delivery_graph, prepare

    graph = delivery_graph(tmp_path)
    first = [
        prepare(graph) for _ in range(graph.graph.data_policy.max_active_downloads_per_organization)
    ]
    with pytest.raises(SpatialDataDomainError, match="CONCURRENCY_LIMIT_EXCEEDED"):
        prepare(graph)
    assert graph.storage.opened == graph.graph.data_policy.max_active_downloads_per_organization
    for prepared in first:
        prepared.close()
    second = prepare(graph)
    second.close()


def test_download_baseexception_closes_private_spool_and_releases_reservation(
    tmp_path: Path,
) -> None:
    from contextlib import contextmanager

    from spatial_data_download_fixture import delivery_graph, prepare

    graph = delivery_graph(tmp_path)

    @contextmanager
    def interrupted(*args: Any, **kwargs: Any) -> Iterator[Iterator[bytes]]:
        def chunks() -> Iterator[bytes]:
            yield graph.payload[:64]
            raise KeyboardInterrupt()

        yield chunks()

    graph.storage.open_version = interrupted
    with pytest.raises(KeyboardInterrupt):
        prepare(graph)
    assert list(graph.spool.iterdir()) == []
    assert graph.service.active_downloads == graph.service.reserved_bytes == 0


def mounted_download(graph: SimpleNamespace) -> tuple[TestClient, str]:
    import hashlib

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ksi_core.auth import AuthRegistry, PrincipalTokenRecord, mount_auth
    from ksi_core.domains.external.delivery.api import build_spatial_data_router

    app = FastAPI()
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(token.encode()).hexdigest(), principal=principal
            )
            for token, principal in (
                ("local", graph.graph.principal),
                (
                    "foreign",
                    replace(
                        graph.graph.principal,
                        principal_id="foreign-reader",
                        organization_id="foreign",
                    ),
                ),
            )
        ]
    )
    mount_auth(app, registry)
    app.include_router(
        build_spatial_data_router(
            jobs=graph.jobs,
            grants=graph.graph.authorizer,
            sources=graph.graph.sources,
            downloads=graph.service,
            clock=lambda: NOW,
        )
    )
    return (
        TestClient(app),
        f"/v1/sites/site-1/work-areas/{graph.graph.area.work_area_id}/spatial-data-requests/{graph.issued.job_id}/file",
    )


@pytest.mark.parametrize("method", ["get", "head"])
def test_mounted_download_uses_actual_request_local_credentials_and_exact_no_cache_bytes(
    tmp_path: Path, method: str
) -> None:
    from spatial_data_download_fixture import delivery_graph

    graph = delivery_graph(tmp_path)
    client, url = mounted_download(graph)
    response = getattr(client, method)(url, headers={"Authorization": "Bearer local"})
    assert response.status_code == 200 and response.headers["content-length"] == "1024"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.content == (graph.payload if method == "get" else b"")
    assert graph.service.active_downloads == 0


@pytest.mark.parametrize(
    "value", ["bytes=0-1", "bytes=0-", "bytes=-1", "bytes=0-1,4-5", "garbage", ""]
)
@pytest.mark.parametrize("method", ["get", "head"])
def test_all_range_forms_refused_after_foreign_scope_check_without_storage_io(
    tmp_path: Path, value: str, method: str
) -> None:
    from spatial_data_download_fixture import delivery_graph

    graph = delivery_graph(tmp_path)
    client, url = mounted_download(graph)
    for token, expected in (("foreign", 404), ("local", 416)):
        response = getattr(client, method)(
            url, headers={"Authorization": "Bearer " + token, "Range": value}
        )
        assert response.status_code == expected
    assert graph.storage.opened == 0
