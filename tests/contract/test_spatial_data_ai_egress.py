"""Task2 RED: current AI metadata rights enforced at the response boundary.

New AI identity reads are denied when current grant/consent/credential lapse,
while generic V1 history survives. Unknown/foreign reads stay identical 404s.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from ksi_core.durable_journal import DurableJournal
from ksi_core.identity.auth import (
    AuthRegistry,
    Principal,
    PrincipalKind,
    PrincipalTokenRecord,
    mount_auth,
)
from ksi_event_contracts.spatial_data import SpatialDataPurposeV1, SpatialDataRequestV1
from pydantic import ValidationError
from spatial_data_fixture import make_grant
from spatial_data_job_fixture import NOW, issue, job_graph, job_store
from spatial_data_source_fixture import source_identity
from starlette.types import Message

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Coroutine, Iterator
    from contextlib import AbstractContextManager
    from datetime import datetime

    from ksi_core.domains.external.delivery.credential_currentness import (
        SpatialDataCredentialCurrentness,
    )
    from ksi_core.domains.external.delivery.metadata_response import (
        SpatialDataAiMetadataResponse,
    )
    from starlette.responses import Response


def ai_principal(area_id: str) -> Principal:
    return Principal(
        "ai-client-1",
        PrincipalKind.SPATIAL_DATA_MCP_CLIENT,
        None,
        None,
        "organization-1",
        allowed_site_ids=frozenset({"site-1"}),
        allowed_work_area_ids=frozenset({area_id}),
    )


class AiAuthority:
    """Test-only currentness resolving the AI principal alongside the operator."""

    def __init__(self, graph: SimpleNamespace, ai: Principal) -> None:
        self.coordinator = graph.coordinator
        self._principals = {
            (graph.principal.principal_id, graph.principal.organization_id): graph.principal,
            (ai.principal_id, ai.organization_id): ai,
        }
        self.enabled = True

    def resolve_requester(
        self, *, principal_id: str, organization_id: str, now: datetime
    ) -> Principal | None:
        return self._principals.get((principal_id, organization_id))

    def is_current(self, *, policy: Any, runtime: Any, activation: Any, now: datetime) -> bool:
        return self.enabled and activation.is_current_at(now)


def ai_lane(tmp_path: Path, *, consent: bool = True, issue_job: bool = True) -> SimpleNamespace:
    from ksi_core.domains.external.delivery.ai_egress import SpatialDataAiEgress
    from ksi_core.domains.external.delivery.metadata_audit import (
        SpatialDataMetadataAuditStore,
    )

    graph = job_graph(tmp_path)
    record = graph.sites._sites["site-1"]  # noqa: SLF001
    # Test-only consent switch; journal restart coverage belongs to Task5 replay.
    graph.sites._sites["site-1"] = replace(record, ai_egress_allowed=consent)  # noqa: SLF001
    ai = ai_principal(graph.area.work_area_id)
    graph.authority = AiAuthority(graph, ai)
    store = job_store(graph)
    measurements = graph.source.inspection.measurements
    assert measurements is not None
    grant = make_grant(
        grant_id="local-ai-grant",
        organization_id=ai.organization_id,
        beneficiary_principal_id=ai.principal_id,
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        asset_ref=graph.source.asset_ref,
        observed_crs_digest=measurements.observed_crs_digest,
        allowed_bounds=(0, 0, 2, 2),
        operations=("PREPARE", "READ"),
        purposes=("EXTERNAL_AI",),
        processing_location="site_onprem",
        policy_digest=graph.data_policy.policy_digest,
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(hours=1),
    )
    view = None
    if issue_job:
        graph.grants.provision(grant)
        request = SpatialDataRequestV1(
            asset_ref=graph.source.asset_ref,
            requested_bounds=(0, 0, 1, 1),
            observed_crs_digest=measurements.observed_crs_digest,
            resolution_mode="NATIVE",
            purpose=SpatialDataPurposeV1.EXTERNAL_AI,
        )
        view = store.issue(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            request=request,
            principal=ai,
            idempotency_key="ai-one",
            now=NOW,
        )
    audit = SpatialDataMetadataAuditStore(
        DurableJournal(tmp_path / "metadata-audit.jsonl"), policy=graph.data_policy
    )
    egress = SpatialDataAiEgress(store, graph.sources, graph.authorizer, audit, clock=lambda: NOW)
    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(token.encode()).hexdigest(), principal=principal
                )
                for token, principal in (("ai-token", ai), ("operator-token", graph.principal))
            ]
        ),
    )
    graph.ai = ai
    graph.ai_grant = grant
    graph.ai_view = view
    graph.ai_store = store
    graph.ai_audit = audit
    graph.ai_egress = egress
    graph.ai_app = app
    return graph


def ai_credentials(
    graph: SimpleNamespace, token: str = "ai-token"
) -> SpatialDataCredentialCurrentness:
    from ksi_core.domains.external.delivery.credential_currentness import (
        SpatialDataCredentialCurrentness,
    )

    return SpatialDataCredentialCurrentness(
        Request({"type": "http", "app": graph.ai_app}),
        token,
        expected_principal_id=graph.ai.principal_id,
        expected_organization_id=graph.ai.organization_id,
    )


def revoke(graph: SimpleNamespace) -> None:
    from ksi_event_contracts.spatial_data_authority import SpatialDataRevocationV1

    grant = graph.ai_grant
    graph.grants.revoke(
        SpatialDataRevocationV1(
            grant_id=grant.grant_id,
            revision=grant.revision,
            organization_id=grant.organization_id,
            grant_digest=grant.grant_digest,
            revoked_at=NOW,
            reason="test rights withdrawn",
        ).sealed()
    )


def send_metadata(
    response: SpatialDataAiMetadataResponse,
) -> tuple[list[Message], int, dict[bytes, bytes]]:
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    async def receive() -> Message:
        await asyncio.Event().wait()
        raise AssertionError("receive unexpectedly returned")

    asyncio.run(response({"type": "http", "method": "GET", "headers": []}, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    return messages, start["status"], dict(start["headers"])


def ai_router_app(graph: SimpleNamespace) -> TestClient:
    from ksi_core.domains.external.delivery.api import build_spatial_data_router

    app = graph.ai_app
    app.include_router(
        build_spatial_data_router(
            jobs=graph.ai_store,
            grants=graph.authorizer,
            sources=graph.sources,
            downloads=None,
            egress=graph.ai_egress,
            clock=lambda: NOW,
        )
    )
    return TestClient(app)


def test_revoked_ai_metadata_denied_but_generic_history_survives(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    generic = issue(graph.ai_store, graph, key="generic-one")
    assert graph.ai_store.get(job_id=generic.job_id, principal=graph.principal, now=NOW).job_id
    revoke(graph)
    with pytest.raises(SpatialDataDomainError) as failure:
        graph.ai_store.require_ai_metadata(job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW)
    assert (failure.value.reason, failure.value.status_code) == ("ACCESS_REVOKED", 403)
    # Generic history survives revocation for its otherwise authorized requester.
    survived = graph.ai_store.get(job_id=generic.job_id, principal=graph.principal, now=NOW)
    assert survived.job_id == generic.job_id
    # Unknown and foreign reads are identical non-disclosing 404s.
    for job_id, principal in (
        ("sdj-v1-00000000-0000-4000-8000-000000000099", graph.ai),
        (graph.ai_view.job_id, replace(graph.ai, organization_id="foreign-org")),
    ):
        with pytest.raises(SpatialDataDomainError) as unknown:
            graph.ai_store.require_ai_metadata(job_id=job_id, principal=principal, now=NOW)
        assert (unknown.value.reason, unknown.value.status_code) == ("NOT_FOUND", 404)


def test_ai_general_job_and_purpose_header_downgrade_refused(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    generic = issue(graph.ai_store, graph, key="generic-two")
    with pytest.raises(SpatialDataDomainError) as failure:
        graph.ai_store.require_ai_metadata(job_id=generic.job_id, principal=graph.ai, now=NOW)
    assert (failure.value.reason, failure.value.status_code) == ("NOT_FOUND", 404)
    measurements = graph.source.inspection.measurements
    assert measurements is not None
    downgraded = SpatialDataRequestV1(
        asset_ref=graph.source.asset_ref,
        requested_bounds=(0, 0, 1, 1),
        observed_crs_digest=measurements.observed_crs_digest,
        resolution_mode="NATIVE",
        purpose=SpatialDataPurposeV1.GENERAL_DATA_USE,
    )
    with pytest.raises(SpatialDataDomainError) as issuance:
        graph.ai_store.issue(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            request=downgraded,
            principal=graph.ai,
            idempotency_key="ai-downgrade",
            now=NOW,
        )
    assert (issuance.value.reason, issuance.value.status_code) == ("PERMISSION_DENIED", 403)
    client = ai_router_app(graph)
    response = client.post(
        f"/v1/sites/site-1/work-areas/{graph.area.work_area_id}/spatial-data-requests",
        json={
            "assetRef": graph.source.asset_ref,
            "requestedBounds": [0, 0, 1, 1],
            "observedCrsDigest": measurements.observed_crs_digest,
            "resolutionMode": "NATIVE",
            "purpose": "GENERAL_DATA_USE",
        },
        headers={"Authorization": "Bearer ai-token", "Idempotency-Key": "ai-http-downgrade"},
    )
    assert response.status_code == 403
    body = response.json()
    assert body["reason"] == "PERMISSION_DENIED"
    assert "x-ksi-spatial-data-ai-egress" not in {k.lower() for k in response.headers}


def test_replacement_grant_cannot_resurrect_job(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    revoke(graph)
    graph.grants.provision(
        graph.ai_grant.model_copy(update={"revision": 2, "grant_digest": None}).sealed()
    )
    with pytest.raises(SpatialDataDomainError) as failure:
        graph.ai_store.require_ai_metadata(job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW)
    assert (failure.value.reason, failure.value.status_code) == ("ACCESS_REVOKED", 403)


def test_cancel_checks_ai_read_before_append(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    revoke(graph)
    before = len(list(graph.ai_store._journal.replay()))  # noqa: SLF001
    with pytest.raises(SpatialDataDomainError):
        graph.ai_store.cancel(job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW)
    after = list(graph.ai_store._journal.replay())  # noqa: SLF001
    assert len(after) == before
    assert not any(
        event.get("state") == "CANCELED" and event.get("jobId") == graph.ai_view.job_id
        for event in after
    )
    # Control: permitted cancel still appends exactly one terminal event.
    permitted = ai_lane(tmp_path / "permitted")
    canceled = permitted.ai_store.cancel(
        job_id=permitted.ai_view.job_id, principal=permitted.ai, now=NOW
    )
    assert canceled.execution_state.value == "CANCELED"


def test_consent_or_token_revoked_between_handler_and_headers(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    credentials = ai_credentials(graph)
    view = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    response = graph.ai_egress.prepare_job_response(
        credentials=credentials,
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=view,
        status=200,
        operation="GET_JOB",
    )
    revoke(graph)
    messages, status, headers = send_metadata(response)
    assert status == 403
    assert b"x-ksi-spatial-data-ai-egress" not in headers
    assert all(m.get("more_body", True) or not m.get("body") for m in messages)
    assert graph.ai_audit.count == 0

    rotated = ai_lane(tmp_path / "rotated")
    prepared = rotated.ai_egress.prepare_job_response(
        credentials=ai_credentials(rotated),
        site_id="site-1",
        work_area_id=rotated.area.work_area_id,
        view=rotated.ai_store.require_ai_metadata(
            job_id=rotated.ai_view.job_id, principal=rotated.ai, now=NOW
        ),
        status=200,
        operation="GET_JOB",
    )
    rotated.ai_app.state.auth_registry = AuthRegistry([])
    messages, status, headers = send_metadata(prepared)
    assert status == 401
    assert b"x-ksi-spatial-data-ai-egress" not in headers
    assert rotated.ai_audit.count == 0


def test_audit_seal_or_limit_refuses_metadata(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.metadata_audit import (
        SpatialDataMetadataAuditStore,
    )

    graph = ai_lane(tmp_path)
    graph.ai_audit.close()
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=graph.ai_store.require_ai_metadata(
            job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
        ),
        status=200,
        operation="GET_JOB",
    )
    _, status, headers = send_metadata(response)
    assert status == 503
    assert b"x-ksi-spatial-data-ai-egress" not in headers

    tiny = SpatialDataMetadataAuditStore(
        DurableJournal(tmp_path / "tiny-audit.jsonl"), policy=graph.data_policy
    )
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    with pytest.raises(SpatialDataDomainError, match="RESOURCE_LIMIT_EXCEEDED"):
        for _ in range(
            graph.data_policy.max_pending_records * graph.data_policy.max_list_records + 1
        ):
            tiny.append(
                principal=graph.ai,
                site_id="site-1",
                work_area_id=graph.area.work_area_id,
                operation="GET_JOB",
                payload_digest="sha256:" + "d" * 64,
                reason=None,
                now=NOW,
            )


def test_ai_scope_requires_current_consent_before_enumeration(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path, consent=False, issue_job=False)
    with pytest.raises(SpatialDataDomainError) as denied:
        graph.sources.require_ai_scope("site-1", graph.area.work_area_id, graph.ai)
    assert (denied.value.reason, denied.value.status_code) == ("AI_EGRESS_DENIED", 403)
    with pytest.raises(SpatialDataDomainError) as generic:
        graph.sources.require_ai_scope("site-1", graph.area.work_area_id, graph.principal)
    assert (generic.value.reason, generic.value.status_code) == ("PERMISSION_DENIED", 403)
    allowed = ai_lane(tmp_path / "allowed")
    area = allowed.sources.require_ai_scope("site-1", allowed.area.work_area_id, allowed.ai)
    assert area.work_area_id == allowed.area.work_area_id


def test_ai_error_envelope_is_closed_and_old_model_untouched(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import (
        SpatialDataAiDomainError,
        SpatialDataDomainError,
    )
    from ksi_event_contracts.spatial_data_ai import SpatialDataAiErrorV1

    stale = SpatialDataAiDomainError("SPATIAL_DATA_CURSOR_STALE", 409)
    assert stale.reason == "SPATIAL_DATA_CURSOR_STALE"
    with pytest.raises(ValidationError):
        SpatialDataDomainError("SPATIAL_DATA_CURSOR_STALE", 409)
    envelope = SpatialDataAiErrorV1(
        reason="AI_EGRESS_DENIED",
        message="Spatial data AI request unavailable.",
        retryable=False,
        remediation=("CHECK_AI_CONSENT",),
    )
    assert envelope.reason == "AI_EGRESS_DENIED"
    assert "jobId" not in envelope.model_dump(by_alias=True, mode="json")


def test_metadata_audit_replay_seal_digest_sequence_limits(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
    from ksi_core.domains.external.delivery.metadata_audit import (
        SpatialDataMetadataAuditRecoveryError,
        SpatialDataMetadataAuditStore,
    )

    graph = ai_lane(tmp_path)
    graph.ai_audit.append(
        principal=graph.ai,
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        operation="GET_JOB",
        payload_digest="sha256:" + "e" * 64,
        reason=None,
        now=NOW,
    )
    replayed = SpatialDataMetadataAuditStore(
        DurableJournal.open_read_only(tmp_path / "metadata-audit.jsonl"),
        policy=graph.data_policy,
    )
    assert replayed.count == 1
    with pytest.raises(ValueError, match="operation"):
        graph.ai_audit.append(
            principal=graph.ai,
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            operation="FORGED_ACTION",
            payload_digest=None,
            reason=None,
            now=NOW,
        )
    with (tmp_path / "metadata-audit.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"recordType":"spatial-data-metadata-audit.v1","sequence":999}\n')
    graph.ai_audit.close()
    with pytest.raises(SpatialDataMetadataAuditRecoveryError):
        SpatialDataMetadataAuditStore(
            DurableJournal(tmp_path / "metadata-audit.jsonl"), policy=graph.data_policy
        )
    with pytest.raises(SpatialDataDomainError, match="AUDIT_UNAVAILABLE"):
        graph.ai_audit.append(
            principal=graph.ai,
            site_id="site-1",
            work_area_id="other-area",
            operation="GET_JOB",
            payload_digest="not-a-digest",
            reason="NOT_FOUND",
            now=NOW,
        )


def test_ai_list_filters_before_pagination_without_hiding_resource_failures(
    tmp_path: Path,
) -> None:
    graph = ai_lane(tmp_path)
    page = graph.ai_store.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        cursor=None,
        limit=8,
        now=NOW,
    )
    assert [item.job_id for item in page.items] == [graph.ai_view.job_id]
    revoke(graph)
    denied = graph.ai_store.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        cursor=None,
        limit=8,
        now=NOW,
    )
    assert denied.items == () and denied.next_cursor is None


def test_ai_egress_requires_exact_participants(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.ai_egress import SpatialDataAiEgress
    from ksi_core.domains.external.delivery.api import build_spatial_data_router

    graph = ai_lane(tmp_path)
    other = ai_lane(tmp_path / "other")
    with pytest.raises(ValueError, match="coordinator"):
        SpatialDataAiEgress(
            graph.ai_store,
            graph.sources,
            other.authorizer,
            graph.ai_audit,
            clock=lambda: NOW,
        )
    with pytest.raises(ValueError, match="clock"):
        SpatialDataAiEgress(
            graph.ai_store,
            graph.sources,
            graph.authorizer,
            graph.ai_audit,
            clock="not-a-clock",  # type: ignore[arg-type]
        )
    router = build_spatial_data_router(
        jobs=graph.ai_store,
        grants=graph.authorizer,
        sources=graph.sources,
        downloads=None,
        clock=lambda: NOW,
    )
    app = FastAPI()
    app.state.auth_registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"ai-token").hexdigest(), principal=graph.ai
            )
        ]
    )
    app.include_router(router)
    response = TestClient(app).get(
        f"/v1/sites/site-1/work-areas/{graph.area.work_area_id}/spatial-data-requests/{graph.ai_view.job_id}",
        headers={"Authorization": "Bearer ai-token"},
    )
    assert response.status_code == 503
    assert "x-ksi-spatial-data-ai-egress" not in {k.lower() for k in response.headers}


def test_ai_metadata_response_carries_ack_only_on_guarded_success(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    view = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=view,
        status=200,
        operation="GET_JOB",
    )
    messages, status, headers = send_metadata(response)
    assert status == 200
    assert headers[b"x-ksi-spatial-data-ai-egress"] == b"ALLOWED"
    assert graph.ai_audit.count == 1
    assert source_identity(graph) == graph.source.asset_ref


def test_ai_download_ack_follows_authorize_and_never_marks_errors(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.download_response import (
        SpatialDataDownloadResponse,
    )
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    data_policy = graph.data_policy

    def prepared_for(kind: PrincipalKind, *, fail: str | None = None) -> Any:
        principal = graph.ai if kind is PrincipalKind.SPATIAL_DATA_MCP_CLIENT else graph.principal

        class StubOutput:
            job = graph.ai_store._records[graph.ai_view.job_id].job  # noqa: SLF001

        class StubService:
            def clock(self) -> datetime:
                return NOW

        class StubPrepared:
            service = StubService()
            policy = data_policy
            started = monotonic()
            size_bytes = 0
            sha256 = "sha256:" + "0" * 64
            output = StubOutput()
            spool: Any = None

            def authorize(self, now: datetime) -> Principal:
                if fail is not None:
                    raise SpatialDataDomainError(fail, 403)
                return principal

            def check_deadline(self) -> None:
                return None

            def audit(self, *args: Any, **kwargs: Any) -> None:
                return None

            def read_spool_chunk(self) -> bytes:
                return b""

            def close(self) -> None:
                return None

        stub = StubPrepared()
        stub.spool = SimpleNamespace(seek=lambda _: None)
        return stub

    async def run(prepared: Any) -> tuple[int, dict[bytes, bytes]]:
        messages: list[Message] = []

        async def send(message: Message) -> None:
            messages.append(message)

        async def receive() -> Message:
            await asyncio.Event().wait()
            raise AssertionError("receive unexpectedly returned")

        await SpatialDataDownloadResponse(prepared)(
            {"type": "http", "method": "GET", "headers": []}, receive, send
        )
        start = next(m for m in messages if m["type"] == "http.response.start")
        return start["status"], dict(start["headers"])

    status, headers = asyncio.run(run(prepared_for(PrincipalKind.SPATIAL_DATA_MCP_CLIENT)))
    assert status == 200
    assert headers[b"x-ksi-spatial-data-ai-egress"] == b"ALLOWED"
    status, headers = asyncio.run(run(prepared_for(PrincipalKind.SPATIAL_DATA_CLIENT)))
    assert status == 200
    assert b"x-ksi-spatial-data-ai-egress" not in headers
    status, headers = asyncio.run(
        run(prepared_for(PrincipalKind.SPATIAL_DATA_MCP_CLIENT, fail="ACCESS_REVOKED"))
    )
    assert status == 403
    assert b"x-ksi-spatial-data-ai-egress" not in headers


# ---- Fix round 1 (review C1/I1-I4/P1/P2): behavioral RED before repair ----
# Each test below fails on the pre-fix snapshot for a genuine behavioral reason
# (wrong status, mutated journal, extra planning call, wrong framing), never for
# a fixture/import error. Tests that already hold document locked semantics.


def _second_area(graph: SimpleNamespace) -> Any:
    return graph.work_areas.register(
        "site-1",
        name="area-2",
        crs="EPSG:5186",
        supersedes=None,
        polygon={"type": "Polygon", "coordinates": [[[2, 0], [4, 0], [4, 2], [2, 2], [2, 0]]]},
        actor="operator-1",
        now=NOW,
    ).work_area


def _remount_ai_registry(graph: SimpleNamespace, ai: Principal) -> None:
    graph.ai_app.state.auth_registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"ai-token").hexdigest(), principal=ai
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"operator-token").hexdigest(),
                principal=graph.principal,
            ),
        ]
    )


def _ai_issue_request(graph: SimpleNamespace) -> SpatialDataRequestV1:
    from ksi_event_contracts.spatial_data import SpatialDataPurposeV1, SpatialDataRequestV1

    measurements = graph.source.inspection.measurements
    assert measurements is not None
    return SpatialDataRequestV1(
        asset_ref=graph.source.asset_ref,
        requested_bounds=(0, 0, 1, 1),
        observed_crs_digest=measurements.observed_crs_digest,
        resolution_mode="NATIVE",
        purpose=SpatialDataPurposeV1.EXTERNAL_AI,
    )


def test_fix1_ai_cancel_mismatched_path_denied_without_mutation(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    area2 = _second_area(graph)
    _remount_ai_registry(
        graph,
        replace(
            graph.ai,
            allowed_work_area_ids=frozenset({graph.area.work_area_id, area2.work_area_id}),
        ),
    )
    client = ai_router_app(graph)
    before = list(graph.ai_store._journal.replay())  # noqa: SLF001
    response = client.post(
        f"/v1/sites/site-1/work-areas/{area2.work_area_id}"
        f"/spatial-data-requests/{graph.ai_view.job_id}/cancel",
        headers={"Authorization": "Bearer ai-token"},
    )
    assert response.status_code == 404
    assert list(graph.ai_store._journal.replay()) == before  # noqa: SLF001


class _StubDownloads:
    """Route-level byte port: records preparation demand, serves fixed bytes."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def response(
        self,
        *,
        job_id: str,
        principal: Principal,
        credentials: SpatialDataCredentialCurrentness,
        now: datetime,
        head_only: bool,
    ) -> Response:
        from starlette.responses import Response as _Response

        self.calls.append({"job_id": job_id, "head_only": head_only})
        return _Response(content=b"FAKETIFFBYTES", media_type="image/tiff")


def _ai_file_client(
    graph: SimpleNamespace, *, downloads: _StubDownloads | None, egress: str = "present"
) -> TestClient:
    from ksi_core.domains.external.delivery.api import build_spatial_data_router

    app = FastAPI()
    mount_auth(
        app,
        AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(token.encode()).hexdigest(), principal=principal
                )
                for token, principal in (
                    ("ai-token", graph.ai),
                    ("operator-token", graph.principal),
                )
            ]
        ),
    )
    options: dict = {
        "jobs": graph.ai_store,
        "grants": graph.authorizer,
        "sources": graph.sources,
        "downloads": downloads,
        "clock": lambda: NOW,
    }
    if egress == "present":
        options["egress"] = graph.ai_egress
    app.include_router(build_spatial_data_router(**options))
    return TestClient(app)


def test_fix1_ai_file_missing_egress_refused_before_preparation(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    stub = _StubDownloads()
    client = _ai_file_client(graph, downloads=stub, egress="missing")
    response = client.get(
        f"/v1/sites/site-1/work-areas/{graph.area.work_area_id}"
        f"/spatial-data-requests/{graph.ai_view.job_id}/file",
        headers={"Authorization": "Bearer ai-token"},
    )
    assert response.status_code == 503
    assert stub.calls == []
    assert "x-ksi-spatial-data-ai-egress" not in {k.lower() for k in response.headers}


def test_fix1_ai_file_revoked_consent_checked_before_job_lookup(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    stub = _StubDownloads()
    client = _ai_file_client(graph, downloads=stub)
    record = graph.sites._sites["site-1"]  # noqa: SLF001
    graph.sites._sites["site-1"] = replace(record, ai_egress_allowed=False)  # noqa: SLF001
    response = client.get(
        f"/v1/sites/site-1/work-areas/{graph.area.work_area_id}"
        "/spatial-data-requests/sdj-v1-00000000-0000-4000-8000-000000000099/file",
        headers={"Authorization": "Bearer ai-token"},
    )
    assert response.status_code == 403
    assert response.json()["reason"] == "AI_EGRESS_DENIED"
    assert stub.calls == []
    assert "x-ksi-spatial-data-ai-egress" not in {k.lower() for k in response.headers}


def test_fix1_ai_file_revoked_consent_denies_known_job_without_ack(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    stub = _StubDownloads()
    client = _ai_file_client(graph, downloads=stub)
    record = graph.sites._sites["site-1"]  # noqa: SLF001
    graph.sites._sites["site-1"] = replace(record, ai_egress_allowed=False)  # noqa: SLF001
    url = (
        f"/v1/sites/site-1/work-areas/{graph.area.work_area_id}"
        f"/spatial-data-requests/{graph.ai_view.job_id}/file"
    )
    for method in ("get", "head"):
        response = getattr(client, method)(url, headers={"Authorization": "Bearer ai-token"})
        assert response.status_code == 403
        if method == "get":
            assert response.json()["reason"] == "AI_EGRESS_DENIED"
            assert b"FAKETIFFBYTES" not in response.content
        else:
            assert response.content == b""
    assert stub.calls == []
    assert "x-ksi-spatial-data-ai-egress" not in {k.lower() for k in response.headers}


def test_fix1_generic_file_route_unchanged(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    generic = issue(graph.ai_store, graph, key="generic-file")
    stub = _StubDownloads()
    client = _ai_file_client(graph, downloads=stub)
    response = client.get(
        f"/v1/sites/site-1/work-areas/{graph.area.work_area_id}"
        f"/spatial-data-requests/{generic.job_id}/file",
        headers={"Authorization": "Bearer operator-token"},
    )
    assert response.status_code == 200
    assert response.content == b"FAKETIFFBYTES"
    assert [call["job_id"] for call in stub.calls] == [generic.job_id]
    assert "x-ksi-spatial-data-ai-egress" not in {k.lower() for k in response.headers}


def test_fix1_ai_metadata_ambiguous_grants_denied(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    graph.grants.provision(
        graph.ai_grant.model_copy(update={"revision": 2, "grant_digest": None}).sealed()
    )
    with pytest.raises(SpatialDataDomainError) as failure:
        graph.ai_store.require_ai_metadata(job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW)
    assert (failure.value.reason, failure.value.status_code) == ("AMBIGUOUS_GRANT", 403)


def test_fix1_ai_metadata_authorization_plans_no_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ksi_core.domains.external.delivery.jobs as jobs_module

    graph = ai_lane(tmp_path)
    calls: list[int] = []
    real = jobs_module.plan_external_native_window

    def spy(**kwargs: Any) -> Any:
        calls.append(1)
        return real(**kwargs)

    monkeypatch.setattr(jobs_module, "plan_external_native_window", spy)
    view = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    assert view.job_id == graph.ai_view.job_id
    # Exactly one planning call survives: the availability probe. Authorization
    # itself must plan zero native windows.
    assert len(calls) == 1


def test_fix1_metadata_selector_permits_subpixel_grant_pixel_path_denies(
    tmp_path: Path,
) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
    from ksi_geo_spatial.external_native_window_geometry import plan_external_native_window

    graph = ai_lane(tmp_path)
    revoke(graph)
    subpixel = graph.ai_grant.model_copy(
        update={"revision": 2, "grant_digest": None, "allowed_bounds": (0, 0, 0.5, 0.5)}
    ).sealed()
    graph.grants.provision(subpixel)
    selected = graph.authorizer.select_metadata_current(
        source=graph.source, principal=graph.ai, policy=graph.data_policy, now=NOW
    )
    assert selected == subpixel
    measurements = graph.source.inspection.measurements
    assert measurements is not None
    geometry = plan_external_native_window(
        requested_bounds=(0, 0, 1, 1),
        measurements=measurements,
        requested_crs_digest=measurements.observed_crs_digest,
    )
    with pytest.raises(SpatialDataDomainError) as failure:
        graph.authorizer.require_current(
            grant_id=subpixel.grant_id,
            revision=2,
            source=graph.source,
            principal=graph.ai,
            purpose="EXTERNAL_AI",
            requested_bounds=(0, 0, 1, 1),
            geometry=geometry,
            operation="READ",
            policy=graph.data_policy,
            now=NOW,
        )
    assert failure.value.reason == "OUTPUT_OUTSIDE_GRANT"


def test_fix1_metadata_selector_denial_matrix(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    def fresh_lane(name: str) -> SimpleNamespace:
        return ai_lane(tmp_path / name, issue_job=False)

    # CRS mismatch and processing-location mismatch close with GRANT_REQUIRED.
    for name, override in (
        ("crs", {"observed_crs_digest": "sha256:" + "f" * 64}),
        ("location", {"processing_location": "vendor_cloud"}),
        ("policy", {"policy_digest": "sha256:" + "f" * 64}),
    ):
        graph = fresh_lane(name)
        measurements = graph.source.inspection.measurements
        assert measurements is not None
        payload = {
            "grant_id": "local-ai-grant",
            "organization_id": "organization-1",
            "beneficiary_principal_id": "ai-client-1",
            "site_id": "site-1",
            "work_area_id": graph.area.work_area_id,
            "asset_ref": graph.source.asset_ref,
            "observed_crs_digest": measurements.observed_crs_digest,
            "allowed_bounds": (0, 0, 2, 2),
            "operations": ("PREPARE", "READ"),
            "purposes": ("EXTERNAL_AI",),
            "processing_location": "site_onprem",
            "policy_digest": graph.data_policy.policy_digest,
            "valid_from": NOW - timedelta(minutes=1),
            "valid_until": NOW + timedelta(hours=1),
        }
        payload.update(override)
        graph.grants.provision(make_grant(**payload))
        with pytest.raises(SpatialDataDomainError) as failure:
            graph.authorizer.select_metadata_current(
                source=graph.source, principal=graph.ai, policy=graph.data_policy, now=NOW
            )
        assert (failure.value.reason, failure.value.status_code) == ("GRANT_REQUIRED", 403)

    # Unsealed policy and sealed dependency journals fail closed with 503.
    graph = fresh_lane("sealed")
    graph.grants.provision(graph.ai_grant)
    with pytest.raises(SpatialDataDomainError) as failure:
        graph.authorizer.select_metadata_current(
            source=graph.source,
            principal=graph.ai,
            policy=graph.data_policy.model_copy(update={"policy_digest": None}),
            now=NOW,
        )
    assert (failure.value.reason, failure.value.status_code) == ("POLICY_UNAVAILABLE", 503)

    graph = fresh_lane("dependency")
    graph.authorizer._grants._journal.close()  # noqa: SLF001
    with pytest.raises(SpatialDataDomainError) as failure:
        graph.authorizer.select_metadata_current(
            source=graph.source, principal=graph.ai, policy=graph.data_policy, now=NOW
        )
    assert (failure.value.reason, failure.value.status_code) == ("CURRENTNESS_UNAVAILABLE", 503)

    # More beneficiary grants than the explicit list bound refuse with 503.
    graph = ai_lane(tmp_path / "resource", issue_job=False)
    measurements = graph.source.inspection.measurements
    assert measurements is not None
    base = {
        "grant_id": "local-ai-grant",
        "organization_id": "organization-1",
        "beneficiary_principal_id": "ai-client-1",
        "site_id": "site-1",
        "work_area_id": graph.area.work_area_id,
        "asset_ref": graph.source.asset_ref,
        "observed_crs_digest": measurements.observed_crs_digest,
        "allowed_bounds": (0, 0, 2, 2),
        "operations": ("PREPARE", "READ"),
        "purposes": ("EXTERNAL_AI",),
        "processing_location": "site_onprem",
        "policy_digest": graph.data_policy.policy_digest,
        "valid_from": NOW - timedelta(minutes=1),
        "valid_until": NOW + timedelta(hours=1),
    }
    for revision in range(1, graph.data_policy.max_list_records + 2):
        graph.grants.provision(make_grant(**base, revision=revision))
    with pytest.raises(SpatialDataDomainError) as failure:
        graph.authorizer.select_metadata_current(
            source=graph.source, principal=graph.ai, policy=graph.data_policy, now=NOW
        )
    assert (failure.value.reason, failure.value.status_code) == ("RESOURCE_LIMIT_EXCEEDED", 503)


def test_fix1_replacement_with_tampered_license_cannot_resurrect(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    revoke(graph)
    tampered = graph.ai_grant.model_copy(
        update={
            "revision": 2,
            "grant_digest": None,
            "license_provenance_digest": "sha256:" + "c" * 64,
        }
    ).sealed()
    graph.grants.provision(tampered)
    with pytest.raises(SpatialDataDomainError) as failure:
        graph.ai_store.require_ai_metadata(job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW)
    assert (failure.value.reason, failure.value.status_code) == ("ACCESS_REVOKED", 403)


def test_fix1_frozen_grant_state_inspection(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    assert graph.authorizer.frozen_grant_state(grant=graph.ai_grant, now=NOW) == "CURRENT"
    revoke(graph)
    assert graph.authorizer.frozen_grant_state(grant=graph.ai_grant, now=NOW) == "REVOKED"
    unknown = graph.ai_grant.model_copy(
        update={"grant_id": "never-provisioned", "grant_digest": None}
    ).sealed()
    assert graph.authorizer.frozen_grant_state(grant=unknown, now=NOW) == "ABSENT"


def test_fix1_prepare_only_grant_cannot_issue_ai_job(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path, issue_job=False)
    measurements = graph.source.inspection.measurements
    assert measurements is not None
    graph.grants.provision(
        make_grant(
            grant_id="local-ai-grant",
            organization_id="organization-1",
            beneficiary_principal_id="ai-client-1",
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            asset_ref=graph.source.asset_ref,
            observed_crs_digest=measurements.observed_crs_digest,
            allowed_bounds=(0, 0, 2, 2),
            operations=("PREPARE",),
            purposes=("EXTERNAL_AI",),
            processing_location="site_onprem",
            policy_digest=graph.data_policy.policy_digest,
            valid_from=NOW - timedelta(minutes=1),
            valid_until=NOW + timedelta(hours=1),
        )
    )
    journal = graph.ai_store._journal  # noqa: SLF001
    before = list(journal.replay())
    with pytest.raises(SpatialDataDomainError) as failure:
        graph.ai_store.issue(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            request=_ai_issue_request(graph),
            principal=graph.ai,
            idempotency_key="ai-prepare-only",
            now=NOW,
        )
    assert (failure.value.reason, failure.value.status_code) == ("PERMISSION_DENIED", 403)
    assert list(journal.replay()) == before


def test_fix1_ambiguous_grants_deny_ai_retry_at_store(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    graph.grants.provision(
        graph.ai_grant.model_copy(update={"revision": 2, "grant_digest": None}).sealed()
    )
    with pytest.raises(SpatialDataDomainError) as failure:
        graph.ai_store.issue_with_outcome(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            request=_ai_issue_request(graph),
            principal=graph.ai,
            idempotency_key="ai-one",
            now=NOW,
        )
    assert (failure.value.reason, failure.value.status_code) == ("AMBIGUOUS_GRANT", 403)


def test_fix1_revoked_grant_ai_retry_denied_at_store(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    revoke(graph)
    with pytest.raises(SpatialDataDomainError) as failure:
        graph.ai_store.issue_with_outcome(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            request=_ai_issue_request(graph),
            principal=graph.ai,
            idempotency_key="ai-one",
            now=NOW,
        )
    assert (failure.value.reason, failure.value.status_code) == ("ACCESS_REVOKED", 403)


def test_fix1_ai_list_resource_exhaustion_raises(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    for revision in range(2, graph.data_policy.max_list_records + 2):
        graph.grants.provision(
            graph.ai_grant.model_copy(update={"revision": revision, "grant_digest": None}).sealed()
        )
    with pytest.raises(SpatialDataDomainError) as failure:
        graph.ai_store.list(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            principal=graph.ai,
            cursor=None,
            limit=8,
            now=NOW,
        )
    assert (failure.value.reason, failure.value.status_code) == ("RESOURCE_LIMIT_EXCEEDED", 503)


def test_fix1_ai_list_sealed_dependency_raises(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    graph.authorizer._grants._journal.close()  # noqa: SLF001
    with pytest.raises(SpatialDataDomainError) as failure:
        graph.ai_store.list(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            principal=graph.ai,
            cursor=None,
            limit=8,
            now=NOW,
        )
    assert (failure.value.reason, failure.value.status_code) == ("CURRENTNESS_UNAVAILABLE", 503)


def test_fix1_ai_route_expired_token_denied_without_ack(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    graph.ai_app.state.auth_registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"ai-token").hexdigest(),
                principal=graph.ai,
                not_after=NOW - timedelta(seconds=1),
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"operator-token").hexdigest(),
                principal=graph.principal,
            ),
        ]
    )
    client = ai_router_app(graph)
    response = client.get(
        f"/v1/sites/site-1/work-areas/{graph.area.work_area_id}"
        f"/spatial-data-requests/{graph.ai_view.job_id}",
        headers={"Authorization": "Bearer ai-token"},
    )
    assert response.status_code == 401
    assert "x-ksi-spatial-data-ai-egress" not in {k.lower() for k in response.headers}


def test_fix1_ai_send_time_scope_refresh_denied(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    credentials = ai_credentials(graph)
    view = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    response = graph.ai_egress.prepare_job_response(
        credentials=credentials,
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=view,
        status=200,
        operation="GET_JOB",
    )
    _remount_ai_registry(graph, replace(graph.ai, allowed_work_area_ids=frozenset({"elsewhere"})))
    messages, status, headers = send_metadata(response)
    assert status == 404
    assert b"x-ksi-spatial-data-ai-egress" not in headers


def test_fix1_ai_cancel_unknown_job_denied_without_mutation(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    client = ai_router_app(graph)
    before = list(graph.ai_store._journal.replay())  # noqa: SLF001
    response = client.post(
        f"/v1/sites/site-1/work-areas/{graph.area.work_area_id}"
        "/spatial-data-requests/sdj-v1-00000000-0000-4000-8000-000000000099/cancel",
        headers={"Authorization": "Bearer ai-token"},
    )
    assert response.status_code == 404
    assert list(graph.ai_store._journal.replay()) == before  # noqa: SLF001


def _framing_of(response: SpatialDataAiMetadataResponse) -> tuple[int, dict[bytes, bytes], bytes]:
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    async def receive() -> Message:
        await asyncio.Event().wait()
        raise AssertionError("receive unexpectedly returned")

    asyncio.run(response({"type": "http", "method": "GET", "headers": []}, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), body


def test_fix1_ai_metadata_framing_matches_body(tmp_path: Path) -> None:
    from ksi_domain.canonical_json import canonical_json_bytes

    graph = ai_lane(tmp_path)
    view = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=view,
        status=200,
        operation="GET_JOB",
    )
    status, headers, body = _framing_of(response)
    assert status == 200
    assert body != b""
    assert headers[b"content-length"] == str(len(body)).encode()
    assert body == canonical_json_bytes(view.model_dump(by_alias=True, mode="json"))


def _assert_framed(expected: bytes, response: SpatialDataAiMetadataResponse) -> None:
    status, headers, body = _framing_of(response)
    assert status in (200, 201)
    assert headers[b"content-length"] == str(len(body)).encode()
    assert body == expected
    assert headers[b"x-ksi-spatial-data-ai-egress"] == b"ALLOWED"


def test_fix1_ai_metadata_framing_all_operations(tmp_path: Path) -> None:
    from ksi_domain.canonical_json import canonical_json_bytes

    graph = ai_lane(tmp_path)
    credentials = ai_credentials(graph)
    created = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    # Each prepared response is sent before the next state mutation: the
    # digest guard must refuse genuinely stale projections, never fresh ones.
    _assert_framed(
        canonical_json_bytes(created.model_dump(by_alias=True, mode="json")),
        graph.ai_egress.prepare_job_response(
            credentials=credentials,
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            view=created,
            status=201,
            operation="CREATE_JOB",
        ),
    )
    page = graph.ai_store.list(
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        cursor=None,
        limit=8,
        now=NOW,
    )
    _assert_framed(
        canonical_json_bytes(page.model_dump(by_alias=True, mode="json")),
        graph.ai_egress.prepare_job_page_response(
            credentials=credentials,
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            page=page,
            cursor=None,
            limit=8,
        ),
    )
    fetched = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    _assert_framed(
        canonical_json_bytes(fetched.model_dump(by_alias=True, mode="json")),
        graph.ai_egress.prepare_job_response(
            credentials=credentials,
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            view=fetched,
            status=200,
            operation="GET_JOB",
        ),
    )
    canceled = graph.ai_store.cancel(job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW)
    _assert_framed(
        canonical_json_bytes(canceled.model_dump(by_alias=True, mode="json")),
        graph.ai_egress.prepare_job_response(
            credentials=credentials,
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            view=canceled,
            status=200,
            operation="CANCEL_JOB",
        ),
    )


def test_fix1_ai_get_route_exact_bytes_over_http(tmp_path: Path) -> None:
    from ksi_domain.canonical_json import canonical_json_bytes

    graph = ai_lane(tmp_path)
    client = ai_router_app(graph)
    response = client.get(
        f"/v1/sites/site-1/work-areas/{graph.area.work_area_id}"
        f"/spatial-data-requests/{graph.ai_view.job_id}",
        headers={"Authorization": "Bearer ai-token"},
    )
    assert response.status_code == 200
    view = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    assert response.headers["content-length"] == str(len(response.content))
    assert response.content == canonical_json_bytes(view.model_dump(by_alias=True, mode="json"))
    assert response.headers["x-ksi-spatial-data-ai-egress"] == "ALLOWED"


def test_fix1_ai_metadata_publication_deadline_refuses_late_send(tmp_path: Path) -> None:
    import json

    graph = ai_lane(tmp_path)
    state = {"now": NOW}
    graph.ai_egress._clock = lambda: state["now"]  # noqa: SLF001
    view = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=view,
        status=200,
        operation="GET_JOB",
    )
    state["now"] = NOW + timedelta(seconds=graph.data_policy.stream_deadline_seconds + 1)
    messages, status, headers = send_metadata(response)
    assert status == 503
    assert b"x-ksi-spatial-data-ai-egress" not in headers
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    assert json.loads(body)["reason"] == "DEADLINE_EXCEEDED"
    assert graph.ai_audit.count == 0


def test_fix1_ai_metadata_disconnect_sends_no_headers(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    view = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=view,
        status=200,
        operation="GET_JOB",
    )
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    async def receive() -> Message:
        return {"type": "http.disconnect"}

    asyncio.run(response({"type": "http", "method": "GET", "headers": []}, receive, send))
    assert all(m["type"] != "http.response.start" for m in messages)
    assert graph.ai_audit.count <= 1


def test_fix1_ai_metadata_cancellation_propagates_without_ack(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    view = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=view,
        status=200,
        operation="GET_JOB",
    )
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    async def receive() -> Message:
        await asyncio.Event().wait()
        raise AssertionError("receive unexpectedly returned")

    async def main() -> None:
        task = asyncio.create_task(
            response({"type": "http", "method": "GET", "headers": []}, receive, send)
        )
        task.cancel()
        await task

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main())
    assert messages == []
    assert graph.ai_audit.count == 0


def test_fix1_ai_metadata_final_recheck_runs_without_extra_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ksi_core.domains.external.delivery.metadata_response as metadata_response_module
    from starlette.concurrency import run_in_threadpool as real_pool

    graph = ai_lane(tmp_path)
    calls: list[str] = []

    async def counting(func: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(getattr(func, "__name__", type(func).__name__))
        return await real_pool(func, *args, **kwargs)

    monkeypatch.setattr(metadata_response_module, "run_in_threadpool", counting)
    view = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=view,
        status=200,
        operation="GET_JOB",
    )
    messages, status, headers = send_metadata(response)
    assert status == 200
    # resolve, recheck, audit, late resolve, body resolve — the final gates
    # run inline.
    assert len(calls) == 5


def test_fix1_ai_metadata_late_revocation_refused_but_attempt_audited(
    tmp_path: Path,
) -> None:
    from ksi_core.domains.external.delivery.credential_currentness import (
        SpatialDataCredentialCurrentness,
    )

    graph = ai_lane(tmp_path)

    class _Revoking(SpatialDataCredentialCurrentness):
        __slots__ = ("_invocations",)
        _invocations: int

        def resolve(self, *, now: datetime) -> Principal:
            principal = super().resolve(now=now)
            self._invocations += 1
            # Prepare seals from the local expected identity without a
            # credential refresh, so the post-audit header refresh is the 2nd
            # resolve.
            if self._invocations == 2:
                revoke(graph)
            return principal

    credentials = _Revoking(
        Request({"type": "http", "app": graph.ai_app}),
        "ai-token",
        expected_principal_id=graph.ai.principal_id,
        expected_organization_id=graph.ai.organization_id,
    )
    credentials._invocations = 0  # noqa: SLF001
    view = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    response = graph.ai_egress.prepare_job_response(
        credentials=credentials,
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=view,
        status=200,
        operation="GET_JOB",
    )
    messages, status, headers = send_metadata(response)
    assert status == 403
    assert b"x-ksi-spatial-data-ai-egress" not in headers
    # The audit records the permitted publication attempt, not delivery.
    assert graph.ai_audit.count == 1


def test_fix1_ai_error_reason_matches_status() -> None:
    import json

    from fastapi import HTTPException
    from ksi_core.domains.external.delivery.metadata_response import ai_error_response

    for status_code, reason in (
        (404, "NOT_FOUND"),
        (401, "PERMISSION_DENIED"),
        (409, "REPORT_CONFLICT"),
        (503, "CURRENTNESS_UNAVAILABLE"),
    ):
        response = ai_error_response(HTTPException(status_code=status_code))
        assert response.status_code == status_code
        assert json.loads(bytes(response.body))["reason"] == reason


# ---- Fix round 2 (P2 real bounded awaits, P3 uniqueness before creation) ----
# RED before repair: P3 issuance appends despite conflicting READ-only rights;
# P2 stages hang (outer watchdog is the only cancellation) with clock constant.


def test_fix2_ai_issue_overlapping_read_only_grant_refused_without_append(
    tmp_path: Path,
) -> None:
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path, issue_job=False)
    measurements = graph.source.inspection.measurements
    assert measurements is not None
    graph.grants.provision(graph.ai_grant)
    narrow = make_grant(
        grant_id="read-only-narrow",
        organization_id="organization-1",
        beneficiary_principal_id="ai-client-1",
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        asset_ref=graph.source.asset_ref,
        observed_crs_digest=measurements.observed_crs_digest,
        allowed_bounds=(0, 0, 0.1, 0.1),
        operations=("READ",),
        purposes=("EXTERNAL_AI",),
        processing_location="site_onprem",
        policy_digest=graph.data_policy.policy_digest,
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(hours=1),
    )
    graph.grants.provision(narrow)
    journal = graph.ai_store._journal  # noqa: SLF001
    before = list(journal.replay())
    with pytest.raises(SpatialDataDomainError) as failure:
        graph.ai_store.issue(
            site_id="site-1",
            work_area_id=graph.area.work_area_id,
            request=_ai_issue_request(graph),
            principal=graph.ai,
            idempotency_key="ai-narrow-conflict",
            now=NOW,
        )
    assert (failure.value.reason, failure.value.status_code) == ("AMBIGUOUS_GRANT", 403)
    assert list(journal.replay()) == before


def _fix2_direct_response(
    *,
    deadline: float,
    credentials: SpatialDataCredentialCurrentness | SimpleNamespace | None = None,
    recheck: Callable[[Principal], bytes] | None = None,
    audit: Callable[[Principal, bytes], None] | None = None,
    body: bytes = b'{"ok":true}',
    mono_past_seconds: float = 0.0,
) -> SpatialDataAiMetadataResponse:
    from time import monotonic

    from ksi_core.domains.external.delivery.metadata_response import (
        SpatialDataAiMetadataResponse,
    )

    # Sync closures: run_in_threadpool executes (never awaits) them, so an
    # async def here would silently never run.
    def _stable_recheck(principal: Principal) -> bytes:
        return body

    def _audit(principal: Principal, fresh: bytes) -> None:
        if audit is not None:
            audit(principal, fresh)

    options: dict = {
        "body": body,
        "status_code": 200,
        "credentials": credentials
        if credentials is not None
        else SimpleNamespace(resolve=lambda *, now: None),
        "clock": lambda: NOW,
        "max_json_bytes": 65536,
        "started": NOW,
        "deadline_seconds": deadline,
        "mono_started": monotonic() - mono_past_seconds,
        "recheck": recheck if recheck is not None else _stable_recheck,
        "audit": _audit,
    }
    try:
        return SpatialDataAiMetadataResponse(**options)
    except TypeError:
        # Pre-fix constructor has no monotonic start yet; the RED run then
        # proves stalled stages hang instead of completing within budget.
        options.pop("mono_started")
        return SpatialDataAiMetadataResponse(**options)


def _fix2_never_receive() -> Callable[[], Coroutine[Any, Any, Message]]:
    async def receive() -> Message:
        await asyncio.Event().wait()
        raise AssertionError("receive unexpectedly returned")

    return receive


def _fix2_run(
    response: SpatialDataAiMetadataResponse,
    *,
    receive: Callable[[], Coroutine[Any, Any, Message]],
    outer_timeout: float = 10.0,
) -> tuple[list, float]:
    from time import monotonic

    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    async def main() -> None:
        await asyncio.wait_for(
            response({"type": "http", "method": "GET", "headers": []}, receive, send),
            timeout=outer_timeout,
        )

    started = monotonic()
    asyncio.run(main())
    return messages, monotonic() - started


def test_fix2_stalled_credential_resolve_bounded(tmp_path: Path) -> None:
    import threading

    gate = threading.Event()
    try:
        graph = ai_lane(tmp_path)

        def blocked_resolve(*, now: datetime) -> Principal:
            gate.wait(30)
            return graph.ai

        response = _fix2_direct_response(
            deadline=0.05,
            credentials=SimpleNamespace(resolve=blocked_resolve),
        )

        async def receive() -> Message:
            await asyncio.Event().wait()
            raise AssertionError("receive unexpectedly returned")

        messages, elapsed = _fix2_run(response, receive=receive)
        assert elapsed < 3.0
        # Budget exhausted by the stall: the refusal send is skipped, the
        # publication ends quietly with no ack and no success.
        assert messages == []
        assert graph.ai_audit.count == 0
    finally:
        gate.set()


def test_fix2_stalled_recheck_bounded(tmp_path: Path) -> None:
    import threading

    gate = threading.Event()
    try:
        graph = ai_lane(tmp_path)

        def blocked_recheck(principal: Principal) -> bytes:
            gate.wait(30)
            return b'{"ok":true}'

        response = _fix2_direct_response(
            deadline=0.05,
            credentials=ai_credentials(graph),
            recheck=blocked_recheck,
        )

        async def receive() -> Message:
            await asyncio.Event().wait()
            raise AssertionError("receive unexpectedly returned")

        messages, elapsed = _fix2_run(response, receive=receive)
        assert elapsed < 3.0
        assert messages == []
        assert graph.ai_audit.count == 0
    finally:
        gate.set()


def test_fix2_denial_with_remaining_budget_sends_refusal(tmp_path: Path) -> None:
    import json

    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)

    def denied_recheck(principal: Principal) -> bytes:
        raise SpatialDataDomainError("ACCESS_REVOKED", 403)

    response = _fix2_direct_response(
        deadline=5.0,
        credentials=ai_credentials(graph),
        recheck=denied_recheck,
    )
    messages, elapsed = _fix2_run(response, receive=_fix2_never_receive())
    assert elapsed < 3.0
    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 403
    assert b"x-ksi-spatial-data-ai-egress" not in dict(start["headers"])
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    assert json.loads(body)["reason"] == "ACCESS_REVOKED"


def test_fix2_stalled_audit_bounded(tmp_path: Path) -> None:
    import threading

    gate = threading.Event()
    try:
        graph = ai_lane(tmp_path)

        def blocked_audit(principal: Principal, fresh: bytes) -> None:
            gate.wait(30)

        response = _fix2_direct_response(
            deadline=0.05,
            credentials=ai_credentials(graph),
            audit=blocked_audit,
        )

        async def receive() -> Message:
            await asyncio.Event().wait()
            raise AssertionError("receive unexpectedly returned")

        messages, elapsed = _fix2_run(response, receive=receive)
        assert elapsed < 3.0
        # The blocked audit stage is abandoned; nothing is sent afterwards.
        assert messages == []
    finally:
        gate.set()


def test_fix2_stalled_header_send_bounded(tmp_path: Path) -> None:
    import threading

    gate = threading.Event()
    try:
        response = _fix2_direct_response(deadline=0.05)

        async def receive() -> Message:
            await asyncio.Event().wait()
            raise AssertionError("receive unexpectedly returned")

        sent: list[Message] = []

        async def send(message: Message) -> None:
            if message["type"] == "http.response.start":
                await asyncio.sleep(30)
                return
            sent.append(message)

        from time import monotonic

        async def main() -> None:
            await asyncio.wait_for(
                response({"type": "http", "method": "GET", "headers": []}, receive, send),
                timeout=10.0,
            )

        started = monotonic()
        asyncio.run(main())
        assert monotonic() - started < 3.0
        # The blocked header send was abandoned: no start, no ack, no body.
        assert sent == []
    finally:
        gate.set()


def test_fix2_stalled_body_send_no_eof_after_headers(tmp_path: Path) -> None:
    import threading

    gate = threading.Event()
    try:
        response = _fix2_direct_response(deadline=0.05)

        async def receive() -> Message:
            await asyncio.Event().wait()
            raise AssertionError("receive unexpectedly returned")

        sent: list[Message] = []

        async def send(message: Message) -> None:
            if message["type"] == "http.response.body":
                await asyncio.sleep(30)
                return
            sent.append(message)

        from time import monotonic

        async def main() -> None:
            await asyncio.wait_for(
                response({"type": "http", "method": "GET", "headers": []}, receive, send),
                timeout=10.0,
            )

        started = monotonic()
        asyncio.run(main())
        assert monotonic() - started < 3.0
        # Headers (with legitimately earned ack) went out; EOF never completes.
        assert [m["type"] for m in sent] == ["http.response.start"]
        assert not any(m.get("more_body", True) is False for m in sent)
    finally:
        gate.set()


def test_fix2_stalled_refusal_send_bounded(tmp_path: Path) -> None:
    import threading

    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    gate = threading.Event()
    try:
        graph = ai_lane(tmp_path)

        def denied_recheck(principal: Principal) -> bytes:
            raise SpatialDataDomainError("ACCESS_REVOKED", 403)

        response = _fix2_direct_response(
            deadline=0.05,
            credentials=ai_credentials(graph),
            recheck=denied_recheck,
        )

        async def receive() -> Message:
            await asyncio.Event().wait()
            raise AssertionError("receive unexpectedly returned")

        sent: list[Message] = []

        async def send(message: Message) -> None:
            await asyncio.sleep(30)
            sent.append(message)

        from time import monotonic

        async def main() -> None:
            await asyncio.wait_for(
                response({"type": "http", "method": "GET", "headers": []}, receive, send),
                timeout=10.0,
            )

        started = monotonic()
        asyncio.run(main())
        assert monotonic() - started < 3.0
        # The blocked refusal send is abandoned: no headers, no ack, no body.
        assert sent == []
    finally:
        gate.set()


def test_fix2_disconnect_while_blocked_stops(tmp_path: Path) -> None:
    import threading

    gate = threading.Event()
    try:
        graph = ai_lane(tmp_path)

        def blocked_recheck(principal: Principal) -> bytes:
            gate.wait(30)
            return b'{"ok":true}'

        response = _fix2_direct_response(
            deadline=5.0,
            credentials=ai_credentials(graph),
            recheck=blocked_recheck,
        )

        async def receive() -> Message:
            await asyncio.sleep(0.05)
            return {"type": "http.disconnect"}

        messages, elapsed = _fix2_run(response, receive=receive)
        assert elapsed < 2.0
        assert all(m["type"] != "http.response.start" for m in messages)
        assert graph.ai_audit.count == 0
    finally:
        gate.set()


def test_fix2_no_task_leak_after_bounded_stages(tmp_path: Path) -> None:
    import threading

    gate = threading.Event()
    try:
        graph = ai_lane(tmp_path)

        def blocked_recheck(principal: Principal) -> bytes:
            gate.wait(30)
            return b'{"ok":true}'

        response = _fix2_direct_response(
            deadline=0.05,
            credentials=ai_credentials(graph),
            recheck=blocked_recheck,
        )

        async def receive() -> Message:
            await asyncio.Event().wait()
            raise AssertionError("receive unexpectedly returned")

        async def main() -> list[Message]:
            messages: list[Message] = []

            async def send(message: Message) -> None:
                messages.append(message)

            await asyncio.wait_for(
                response({"type": "http", "method": "GET", "headers": []}, receive, send),
                timeout=10.0,
            )
            await asyncio.sleep(0)
            lingering = [
                task
                for task in asyncio.all_tasks()
                if not task.done() and task is not asyncio.current_task()
            ]
            assert lingering == []
            return messages

        asyncio.run(main())
    finally:
        gate.set()


def test_fix2_infinite_deadline_rejected() -> None:
    from ksi_core.domains.external.delivery.credential_currentness import (
        SpatialDataCredentialCurrentness,
    )
    from ksi_core.domains.external.delivery.metadata_response import (
        SpatialDataAiMetadataResponse,
    )
    from starlette.requests import Request

    with pytest.raises(ValueError, match="finite positive deadline"):
        SpatialDataAiMetadataResponse(
            body=b'{"ok":true}',
            status_code=200,
            # Genuine credential object (never resolved: the deadline check raises
            # first); the SimpleNamespace doubles stay in the dict-built path below.
            credentials=SpatialDataCredentialCurrentness(
                Request({"type": "http"}),
                "ai-token",
                expected_principal_id="ai-client-1",
                expected_organization_id="organization-1",
            ),
            clock=lambda: NOW,
            max_json_bytes=65536,
            started=NOW,
            deadline_seconds=float("inf"),
            **_mono_started_option(),
            recheck=lambda principal: b'{"ok":true}',
            audit=lambda principal, fresh: None,
        )


def _mono_started_option() -> dict:
    import inspect

    from ksi_core.domains.external.delivery.metadata_response import (
        SpatialDataAiMetadataResponse,
    )

    if "mono_started" not in inspect.signature(SpatialDataAiMetadataResponse.__init__).parameters:
        return {}
    from time import monotonic

    return {"mono_started": monotonic()}


# ---- Fix round 3 (P4 unawaited-coroutine leak, P5 send-scheduling hole) ----
# RED before repair, run with -W error::RuntimeWarning for the P4 set.
#
# Dealloc-time RuntimeWarnings cannot raise even under -W error (they fire
# mid-unwind and land on sys.unraisablehook), so the P4 tests capture that
# hook directly: any "never awaited" coroutine is a genuine failure.


def _fix3_capture_unraisable() -> AbstractContextManager[list[Any]]:
    import contextlib
    import sys

    @contextlib.contextmanager
    def capture() -> Iterator[list[Any]]:
        captured: list = []
        prev = sys.unraisablehook
        sys.unraisablehook = captured.append
        try:
            yield captured
        finally:
            sys.unraisablehook = prev

    return capture()


def _fix3_assert_no_unawaited(captured: list) -> None:
    leaks = [
        args
        for args in captured
        if "never awaited"
        in " ".join(
            str(part)
            for part in (
                getattr(args, "exc_value", ""),
                getattr(args, "err_msg", ""),
                getattr(args, "object", ""),
            )
        )
    ]
    assert leaks == [], f"unawaited coroutines leaked: {leaks!r}"


def _fix3_blocking_stage(gate: threading.Event) -> Callable[..., None]:
    import threading

    assert isinstance(gate, threading.Event)

    def blocked(*args: Any, **kwargs: Any) -> None:
        gate.wait(30)

    return blocked


def test_fix3_exhausted_entry_rejects_quietly_without_warnings(tmp_path: Path) -> None:
    import gc

    graph = ai_lane(tmp_path)
    response = _fix2_direct_response(deadline=0.05, mono_past_seconds=10.0)
    with _fix3_capture_unraisable() as captured:
        messages, elapsed = _fix2_run(response, receive=_fix2_never_receive())
        gc.collect()
    _fix3_assert_no_unawaited(captured)
    assert elapsed < 3.0
    assert messages == []
    assert graph.ai_audit.count == 0


def _fix3_stalled_variant(tmp_path: Path, *, stage: str) -> None:
    import gc
    import threading

    gate = threading.Event()
    try:
        graph = ai_lane(tmp_path)
        blocked = _fix3_blocking_stage(gate)
        options: dict = {"deadline": 0.05, "credentials": ai_credentials(graph)}
        if stage == "resolve":
            options["credentials"] = SimpleNamespace(
                resolve=lambda *, now: (blocked(), graph.ai)[1]
            )
        elif stage == "recheck":
            options["recheck"] = blocked
        elif stage == "audit":
            options["audit"] = blocked
        elif stage == "late-resolve":
            state = {"calls": 0}
            base = ai_credentials(graph)
            real_resolve = base.resolve

            def late_blocking_resolve(*, now: datetime) -> Principal:
                state["calls"] += 1
                if state["calls"] == 2:
                    blocked()
                return real_resolve(now=now)

            options["credentials"] = SimpleNamespace(resolve=late_blocking_resolve)
        elif stage == "header-send":
            pass
        else:
            raise AssertionError(f"unknown stage {stage}")
        response = _fix2_direct_response(**options)

        sent: list[Message] = []

        async def send(message: Message) -> None:
            if stage == "header-send" and message["type"] == "http.response.start":
                await asyncio.sleep(30)
                return
            sent.append(message)

        from time import monotonic

        async def main() -> None:
            await asyncio.wait_for(
                response(
                    {"type": "http", "method": "GET", "headers": []}, _fix2_never_receive(), send
                ),
                timeout=10.0,
            )

        started = monotonic()
        with _fix3_capture_unraisable() as captured:
            asyncio.run(main())
            gc.collect()
        _fix3_assert_no_unawaited(captured)
        assert monotonic() - started < 3.0
        assert sent == []
        assert graph.ai_audit.count == 0
    finally:
        gate.set()


def test_fix3_stalled_resolve_rejects_without_warnings(tmp_path: Path) -> None:
    _fix3_stalled_variant(tmp_path, stage="resolve")


def test_fix3_stalled_recheck_rejects_without_warnings(tmp_path: Path) -> None:
    _fix3_stalled_variant(tmp_path, stage="recheck")


def test_fix3_stalled_audit_rejects_without_warnings(tmp_path: Path) -> None:
    _fix3_stalled_variant(tmp_path, stage="audit")


def test_fix3_stalled_late_resolve_rejects_without_warnings(tmp_path: Path) -> None:
    _fix3_stalled_variant(tmp_path, stage="late-resolve")


def test_fix3_stalled_header_send_rejects_without_warnings(tmp_path: Path) -> None:
    _fix3_stalled_variant(tmp_path, stage="header-send")


def test_fix3_revoke_queued_during_final_check_cannot_precede_send(
    tmp_path: Path,
) -> None:
    graph = ai_lane(tmp_path)
    view = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=view,
        status=200,
        operation="GET_JOB",
    )
    events: list[str] = []
    calls = {"n": 0}
    loop_box: dict = {}
    real_recheck = response._recheck  # noqa: SLF001

    def ordered_recheck(principal: Principal) -> bytes:
        calls["n"] += 1
        result = real_recheck(principal)
        if calls["n"] == 2:
            events.append("check")

            def do_revoke() -> None:
                revoke(graph)
                events.append("revoke")

            loop_box["loop"].call_soon_threadsafe(do_revoke)
        return result

    response._recheck = ordered_recheck  # noqa: SLF001
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)
        if message["type"] == "http.response.start":
            events.append("send")

    async def receive() -> Message:
        await asyncio.Event().wait()
        raise AssertionError("unreachable: no inbound traffic")

    async def main() -> None:
        loop_box["loop"] = asyncio.get_running_loop()
        await asyncio.wait_for(
            response({"type": "http", "method": "GET", "headers": []}, receive, send),
            timeout=10.0,
        )

    asyncio.run(main())
    assert "revoke" in events, "the late revocation must actually run"
    assert "send" in events
    # The send precedes the queued revocation: rights were valid at send time
    # (disclosed transport handoff afterwards), never revoked-before-send.
    assert events.index("send") < events.index("revoke")
    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 200
    assert dict(start["headers"])[b"x-ksi-spatial-data-ai-egress"] == b"ALLOWED"
    assert graph.ai_audit.count == 1


def test_fix3_effective_revoke_before_final_send_denied(tmp_path: Path) -> None:
    import json

    from ksi_core.domains.external.delivery.credential_currentness import (
        SpatialDataCredentialCurrentness,
    )

    graph = ai_lane(tmp_path)
    loop_box: dict = {}
    state = {"calls": 0}

    class _RevokingLate(SpatialDataCredentialCurrentness):
        __slots__ = ()

        def resolve(self, *, now: datetime) -> Principal:
            principal = super().resolve(now=now)
            state["calls"] += 1
            # Prepare seals from the local expected identity without a
            # credential refresh, so the late header refresh is the 2nd
            # resolve.
            if state["calls"] == 2:
                loop_box["loop"].call_soon_threadsafe(lambda: revoke(graph))
            return principal

    view = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    credentials = _RevokingLate(
        Request({"type": "http", "app": graph.ai_app}),
        "ai-token",
        expected_principal_id=graph.ai.principal_id,
        expected_organization_id=graph.ai.organization_id,
    )
    response = graph.ai_egress.prepare_job_response(
        credentials=credentials,
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=view,
        status=200,
        operation="GET_JOB",
    )
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    async def main() -> None:
        loop_box["loop"] = asyncio.get_running_loop()
        await asyncio.wait_for(
            response(
                {"type": "http", "method": "GET", "headers": []},
                _fix2_never_receive(),
                send,
            ),
            timeout=10.0,
        )

    asyncio.run(main())
    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 403
    assert b"x-ksi-spatial-data-ai-egress" not in dict(start["headers"])
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    assert json.loads(body)["reason"] == "ACCESS_REVOKED"
    # The audit records the permitted attempt, not a delivery.
    assert graph.ai_audit.count == 1


# ---- Fix round 4 (P6 body-handoff recheck, broken-receive lock) ----
# RED before repair: a synchronous revocation inside the actual transport
# send callback — applied immediately after an authorized http.response.start
# while zero metadata bytes had been handed to the transport — still sees
# the protected jobId JSON body emitted afterwards. The header ack was
# valid at its timestamp; the body needs its own synchronous recheck
# immediately before its handoff, with no scheduling gap in between.


def _fix4_prepare(graph: SimpleNamespace) -> SpatialDataAiMetadataResponse:
    view = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    return graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=view,
        status=200,
        operation="GET_JOB",
    )


def _fix4_start_revoking_run(
    graph: SimpleNamespace, response: SpatialDataAiMetadataResponse, revoke_now: Callable[[], None]
) -> tuple[list[Message], list[str]]:
    """Drive one publication; revoke synchronously on http.response.start.

    The revocation runs inside the actual transport send callback, so rights
    are already gone while no metadata bytes have been handed over yet.
    """
    events: list[str] = []
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)
        if message["type"] == "http.response.start":
            events.append("start")
            revoke_now()
            events.append("revoke")
        elif message["type"] == "http.response.body" and message.get("body"):
            events.append("body")

    async def receive() -> Message:
        await asyncio.Event().wait()
        raise AssertionError("unreachable: no inbound traffic")

    async def main() -> None:
        await asyncio.wait_for(
            response({"type": "http", "method": "GET", "headers": []}, receive, send),
            timeout=10.0,
        )

    asyncio.run(main())
    return messages, events


def _fix4_assert_no_protected_body_after_headers(
    graph: SimpleNamespace, messages: list[Message], events: list[str]
) -> None:
    assert "start" in events and "revoke" in events
    start = next(m for m in messages if m["type"] == "http.response.start")
    # The header ack was earned while rights were valid; it promises
    # nothing about the later body.
    assert start["status"] == 200
    assert dict(start["headers"])[b"x-ksi-spatial-data-ai-egress"] == b"ALLOWED"
    bodies = [m for m in messages if m["type"] == "http.response.body"]
    assert "body" not in events
    assert graph.ai_view.job_id.encode() not in b"".join(m.get("body", b"") for m in bodies)
    # After-header denial sends no error JSON and no successful EOF:
    # the transport stays interrupted.
    assert b'"reason"' not in b"".join(m.get("body", b"") for m in bodies)
    assert not any(m.get("more_body", True) is False for m in bodies)
    # The audit keeps the permitted attempt, not a delivery.
    assert graph.ai_audit.count == 1


def test_fix4_body_rights_revoked_after_headers_sends_no_protected_body(
    tmp_path: Path,
) -> None:
    graph = ai_lane(tmp_path)
    messages, events = _fix4_start_revoking_run(graph, _fix4_prepare(graph), lambda: revoke(graph))
    _fix4_assert_no_protected_body_after_headers(graph, messages, events)


def test_fix4_body_consent_revoked_after_headers_sends_no_protected_body(
    tmp_path: Path,
) -> None:
    graph = ai_lane(tmp_path)

    def deny_consent() -> None:
        record = graph.sites._sites["site-1"]  # noqa: SLF001
        graph.sites._sites["site-1"] = replace(record, ai_egress_allowed=False)  # noqa: SLF001

    messages, events = _fix4_start_revoking_run(graph, _fix4_prepare(graph), deny_consent)
    _fix4_assert_no_protected_body_after_headers(graph, messages, events)


def test_fix4_body_lane_unavailable_after_headers_sends_no_protected_body(
    tmp_path: Path,
) -> None:
    graph = ai_lane(tmp_path)

    def drop_lane() -> None:
        graph.authority.enabled = False

    messages, events = _fix4_start_revoking_run(graph, _fix4_prepare(graph), drop_lane)
    _fix4_assert_no_protected_body_after_headers(graph, messages, events)


def test_fix4_broken_receive_stops_without_ack(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    response = _fix4_prepare(graph)
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    async def receive() -> Message:
        raise RuntimeError("channel broken")

    async def main() -> None:
        await asyncio.wait_for(
            response({"type": "http", "method": "GET", "headers": []}, receive, send),
            timeout=10.0,
        )

    asyncio.run(main())
    assert b"x-ksi-spatial-data-ai-egress" not in b" ".join(
        b" ".join(dict(m.get("headers", [])).keys())
        for m in messages
        if m["type"] == "http.response.start"
    )
    assert graph.ai_view.job_id.encode() not in b"".join(
        m.get("body", b"") for m in messages if m["type"] == "http.response.body"
    )
    assert graph.ai_audit.count == 0


# ---- Fix round 5 (P7 body bearer refresh — genuine credential currentness) ----
# RED before repair: the transport send callback empties or replaces the
# genuine token registry (or advances the clock past token expiry) immediately
# after an authorized http.response.start while zero metadata bytes were
# handed over — yet the protected jobId JSON body is still emitted, because
# the body stage reuses the pre-header late_principal instead of refreshing
# the bearer. The header ack was valid at its own moment; it can never
# authorize the later bytes.


def test_fix5_body_token_registry_revoked_after_headers_sends_no_protected_body(
    tmp_path: Path,
) -> None:
    graph = ai_lane(tmp_path)

    def empty_registry() -> None:
        graph.ai_app.state.auth_registry = AuthRegistry([])

    messages, events = _fix4_start_revoking_run(graph, _fix4_prepare(graph), empty_registry)
    _fix4_assert_no_protected_body_after_headers(graph, messages, events)


def test_fix5_body_token_expiry_after_headers_sends_no_protected_body(
    tmp_path: Path,
) -> None:
    graph = ai_lane(tmp_path)
    graph.ai_app.state.auth_registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"ai-token").hexdigest(),
                principal=graph.ai,
                not_after=NOW + timedelta(seconds=2),
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(b"operator-token").hexdigest(),
                principal=graph.principal,
            ),
        ]
    )
    response = _fix4_prepare(graph)
    state = {"now": NOW}
    response._clock = lambda: state["now"]  # noqa: SLF001

    def expire_clock() -> None:
        # Genuine expiry inside the publication budget (deadline is 10s):
        # the bearer was valid at header time, expired before the body.
        state["now"] = NOW + timedelta(seconds=5)

    messages, events = _fix4_start_revoking_run(graph, response, expire_clock)
    _fix4_assert_no_protected_body_after_headers(graph, messages, events)


def test_fix5_body_scopes_removed_after_headers_sends_no_protected_body(
    tmp_path: Path,
) -> None:
    graph = ai_lane(tmp_path)

    def narrow_scopes() -> None:
        narrowed = replace(graph.ai, allowed_work_area_ids=frozenset({"elsewhere"}))
        graph.ai_app.state.auth_registry = AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(b"ai-token").hexdigest(), principal=narrowed
                ),
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(b"operator-token").hexdigest(),
                    principal=graph.principal,
                ),
            ]
        )

    messages, events = _fix4_start_revoking_run(graph, _fix4_prepare(graph), narrow_scopes)
    _fix4_assert_no_protected_body_after_headers(graph, messages, events)


def test_fix5_body_identity_kind_changed_after_headers_sends_no_protected_body(
    tmp_path: Path,
) -> None:
    graph = ai_lane(tmp_path)

    def swap_kind() -> None:
        swapped = replace(graph.ai, kind=PrincipalKind.SPATIAL_DATA_CLIENT)
        graph.ai_app.state.auth_registry = AuthRegistry(
            [
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(b"ai-token").hexdigest(), principal=swapped
                ),
                PrincipalTokenRecord(
                    token_sha256=hashlib.sha256(b"operator-token").hexdigest(),
                    principal=graph.principal,
                ),
            ]
        )

    messages, events = _fix4_start_revoking_run(graph, _fix4_prepare(graph), swap_kind)
    _fix4_assert_no_protected_body_after_headers(graph, messages, events)


def test_fix5_body_refresh_healthy_control_delivers_exact_framed_bytes(
    tmp_path: Path,
) -> None:
    from ksi_domain.canonical_json import canonical_json_bytes

    graph = ai_lane(tmp_path)
    view = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=view,
        status=200,
        operation="GET_JOB",
    )
    status, headers, body = _framing_of(response)
    assert status == 200
    assert headers[b"x-ksi-spatial-data-ai-egress"] == b"ALLOWED"
    assert body != b""
    assert headers[b"content-length"] == str(len(body)).encode()
    assert body == canonical_json_bytes(view.model_dump(by_alias=True, mode="json"))
    assert graph.ai_audit.count == 1


def test_fix5_no_mirrored_token_output_or_journal_raw_tokens(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    view = graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id="site-1",
        work_area_id=graph.area.work_area_id,
        view=view,
        status=200,
        operation="GET_JOB",
    )
    messages, status, _headers = send_metadata(response)
    assert status == 200
    denied_messages, _events = _fix4_start_revoking_run(
        graph, _fix4_prepare(graph), lambda: revoke(graph)
    )
    wire = b"".join(
        b" ".join(
            part
            for part in (
                m.get("body", b"") if isinstance(m.get("body", b""), bytes) else b"",
                b" ".join(v for _, v in m.get("headers", [])),
            )
        )
        for m in [*messages, *denied_messages]
        if m["type"] in ("http.response.start", "http.response.body")
    )
    assert b"ai-token" not in wire
    assert b"operator-token" not in wire
    journal_raw = (tmp_path / "metadata-audit.jsonl").read_bytes()
    assert b"ai-token" not in journal_raw
    assert b"operator-token" not in journal_raw
