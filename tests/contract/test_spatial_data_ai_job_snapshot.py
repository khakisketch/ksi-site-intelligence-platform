"""Task5 RED: owner-selected single-job snapshot survives worker progress.

Deterministic barrier proof for the publication race proved by the Primary
probe (Core audit append, then genuine worker QUEUED->COMPLETED => false
REPORT_CONFLICT with unchanged rights): single-job publication must carry a
private OWNER-selected canonical snapshot bound to the immutable issued-job
identity (job/source/frozen-grant/requester/scope/purpose), tolerating only
legal mutable execution/availability/receipt/reason drift. Tamper, wrong
store, forged witness, changed immutable binding, replacement grant, new
source, expiry, revocation, GENERAL purpose and unknown scope must refuse
before protected bytes. Lists keep strict snapshot-409; generic V1 untouched.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import spatial_data_mcp_fixture as fixture
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.spatial_data import (
    SpatialDataExecutionStateV1,
    SpatialDataJobViewV1,
    SpatialDataPurposeV1,
    SpatialDataRequestV1,
)
from spatial_data_job_fixture import NOW, issue, lease, reserve_and_complete
from test_spatial_data_ai_egress import ai_credentials, ai_lane, revoke, send_metadata

fixture.ensure_source_path()

SITE = "site-1"


def _owner_view(graph: SimpleNamespace) -> SpatialDataJobViewV1:
    return graph.ai_store.require_ai_metadata(
        job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
    )


def _owner_bytes(view: SpatialDataJobViewV1) -> bytes:
    return canonical_json_bytes(view.model_dump(by_alias=True, mode="json"))


def _sent_body(messages: list[Any]) -> bytes:
    bodies = [
        m
        for m in messages
        if m["type"] == "http.response.body" and m.get("more_body", True) is False
    ]
    assert len(bodies) == 1, "exactly one protected body send expected"
    return bodies[0]["body"]


def _no_protected_body(messages: list[Any]) -> None:
    assert all(m.get("more_body", True) or not m.get("body") for m in messages)


def _journal_lines(path: Path) -> int:
    with open(path, encoding="utf-8") as handle:
        return sum(1 for _ in handle)


# -- deterministic race: worker progress must not conflict ------------------


def test_worker_progress_between_prepare_and_send_publishes_snapshot(tmp_path: Path) -> None:
    """QUEUED capture stays a truthful point-in-time after genuine COMPLETED."""
    graph = ai_lane(tmp_path)
    store = graph.ai_store
    journal = graph.path / "jobs.jsonl"
    prepared_view = _owner_view(graph)
    assert prepared_view.execution_state.value == "QUEUED"
    jobs_before = _journal_lines(journal)
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id=SITE,
        work_area_id=graph.area.work_area_id,
        view=prepared_view,
        status=200,
        operation="GET_JOB",
    )
    # Prepare itself selects; it never appends job journal events.
    assert _journal_lines(journal) == jobs_before
    # Genuine worker progression AFTER capture, before publication.
    attempt = lease(store, graph, graph.ai_view)
    reserve_and_complete(store, graph, graph.ai_view, attempt)
    assert (
        store.require_ai_metadata(
            job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW
        ).execution_state.value
        == "COMPLETED"
    )
    jobs_captured = _journal_lines(journal)
    messages, status, headers = send_metadata(response)
    assert status == 200, "worker progress must not conflict with a bound snapshot"
    assert headers[b"x-ksi-spatial-data-ai-egress"] == b"ALLOWED"
    body = _sent_body(messages)
    payload = json.loads(body)
    assert payload["jobId"] == graph.ai_view.job_id
    assert payload["executionState"] == "QUEUED", "emitted bytes are the capture point-in-time"
    assert body == _owner_bytes(prepared_view)
    # Audit hashes ACTUAL emitted bytes; publication appends no job journal events.
    assert graph.ai_audit.count == 1
    assert _journal_lines(journal) == jobs_captured


def test_forged_caller_view_fields_are_never_published(tmp_path: Path) -> None:
    """A caller-supplied typed view is routing only; bytes come from the owner."""
    graph = ai_lane(tmp_path)
    real = _owner_view(graph)
    forged = real.model_copy(update={"execution_state": SpatialDataExecutionStateV1.CANCELED})
    assert _owner_bytes(forged) != _owner_bytes(real)
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id=SITE,
        work_area_id=graph.area.work_area_id,
        view=forged,
        status=200,
        operation="GET_JOB",
    )
    messages, status, _ = send_metadata(response)
    assert status == 200
    assert _sent_body(messages) == _owner_bytes(real)


def test_unknown_job_view_refused_at_prepare_without_audit(tmp_path: Path) -> None:
    """A view for a job the owner never issued refuses before protected bytes."""
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    real = _owner_view(graph)
    forged = real.model_copy(update={"job_id": "sdj-v1-00000000000000000000000000"})
    with pytest.raises(SpatialDataDomainError):
        graph.ai_egress.prepare_job_response(
            credentials=ai_credentials(graph),
            site_id=SITE,
            work_area_id=graph.area.work_area_id,
            view=forged,
            status=200,
            operation="GET_JOB",
        )
    assert graph.ai_audit.count == 0


def test_general_purpose_job_invisible_to_ai_snapshot(tmp_path: Path) -> None:
    """GENERAL_DATA_USE jobs stay non-disclosing 404s for the AI snapshot."""
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    general = issue(graph.ai_store, graph, key="general-one")
    assert general.job_id
    with pytest.raises(SpatialDataDomainError) as exc:
        graph.ai_store.seal_ai_job_snapshot(job_id=general.job_id, principal=graph.ai, now=NOW)
    assert exc.value.status_code == 404
    with pytest.raises(SpatialDataDomainError):
        graph.ai_egress.prepare_job_response(
            credentials=ai_credentials(graph),
            site_id=SITE,
            work_area_id=graph.area.work_area_id,
            view=general,
            status=200,
            operation="GET_JOB",
        )
    assert graph.ai_audit.count == 0


# -- snapshot seal/verify unit proof ----------------------------------------


def test_snapshot_seal_binds_immutable_issued_job_identity(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    store = graph.ai_store
    snapshot = store.seal_ai_job_snapshot(job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW)
    record = store._records[graph.ai_view.job_id]  # noqa: SLF001
    job = record.job
    assert snapshot.job_id == job.job_id
    assert snapshot.body == _owner_bytes(_owner_view(graph))
    assert snapshot.body_digest == "sha256:" + hashlib.sha256(snapshot.body).hexdigest()
    assert snapshot.job_digest == job.job_digest
    assert snapshot.source_digest == job.source.source_digest
    assert snapshot.grant_id == job.grant.grant_id
    assert snapshot.grant_revision == job.grant.revision
    assert snapshot.grant_digest == job.grant.grant_digest
    assert snapshot.requester_principal_id == job.requester_principal_id
    assert snapshot.organization_id == job.organization_id
    assert snapshot.policy_digest == job.policy.policy_digest
    assert snapshot.purpose == SpatialDataPurposeV1.EXTERNAL_AI
    assert store.verify_ai_job_snapshot(snapshot=snapshot, principal=graph.ai, now=NOW) == (
        snapshot.body
    )


def test_snapshot_tampered_body_or_view_fails_verification(tmp_path: Path) -> None:
    """dataclasses.replace forgery of the sealed bytes or view must fail."""
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    store = graph.ai_store
    snapshot = store.seal_ai_job_snapshot(job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW)
    with pytest.raises(SpatialDataDomainError):
        store.verify_ai_job_snapshot(
            snapshot=replace(snapshot, body=b'{"forged":true}'),
            principal=graph.ai,
            now=NOW,
        )
    real = _owner_view(graph)
    forged_view = real.model_copy(update={"execution_state": SpatialDataExecutionStateV1.CANCELED})
    with pytest.raises(SpatialDataDomainError):
        store.verify_ai_job_snapshot(
            snapshot=replace(snapshot, view=forged_view),
            principal=graph.ai,
            now=NOW,
        )
    with pytest.raises(SpatialDataDomainError):
        store.verify_ai_job_snapshot(
            snapshot=replace(snapshot, grant_digest="sha256:" + "0" * 64),
            principal=graph.ai,
            now=NOW,
        )
    with pytest.raises(SpatialDataDomainError):
        bogus_snapshot: Any = "not-a-snapshot"
        store.verify_ai_job_snapshot(
            snapshot=bogus_snapshot,
            principal=graph.ai,
            now=NOW,
        )


def test_snapshot_from_wrong_store_refused(tmp_path: Path) -> None:
    """A witness issued by another store never verifies here."""
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    first = ai_lane(tmp_path / "first")
    second = ai_lane(tmp_path / "second")
    snapshot = first.ai_store.seal_ai_job_snapshot(
        job_id=first.ai_view.job_id, principal=first.ai, now=NOW
    )
    with pytest.raises(SpatialDataDomainError):
        second.ai_store.verify_ai_job_snapshot(snapshot=snapshot, principal=second.ai, now=NOW)


def test_existing_whole_view_guard_still_refuses_mismatched_bytes(tmp_path: Path) -> None:
    """Layered defense: the unchanged metadata guard never emits unselected bytes."""
    from time import monotonic as _monotonic

    from ksi_core.domains.external.delivery.metadata_response import (
        SpatialDataAiMetadataResponse,
    )

    graph = ai_lane(tmp_path)
    real = _owner_view(graph)
    body = _owner_bytes(real)
    forged = canonical_json_bytes({"forged": True})
    assert forged != body
    response = SpatialDataAiMetadataResponse(
        body=body,
        status_code=200,
        credentials=ai_credentials(graph),
        clock=lambda: NOW,
        max_json_bytes=graph.data_policy.max_json_bytes,
        started=NOW,
        deadline_seconds=graph.data_policy.stream_deadline_seconds,
        mono_started=_monotonic(),
        recheck=lambda principal: forged,
        audit=lambda principal, fresh: None,
    )
    messages, status, headers = send_metadata(response)
    assert status == 409
    assert b"x-ksi-spatial-data-ai-egress" not in headers
    _no_protected_body(messages)


# -- rights negatives through the snapshot send path -------------------------


def test_replacement_grant_refuses_snapshot_before_bytes(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id=SITE,
        work_area_id=graph.area.work_area_id,
        view=_owner_view(graph),
        status=200,
        operation="GET_JOB",
    )
    graph.grants.provision(
        graph.ai_grant.model_copy(update={"grant_id": "replacement", "grant_digest": None}).sealed()
    )
    messages, status, headers = send_metadata(response)
    assert status == 403
    assert b"x-ksi-spatial-data-ai-egress" not in headers
    _no_protected_body(messages)
    assert graph.ai_audit.count == 0


def test_consent_withdrawn_after_capture_refuses_snapshot(tmp_path: Path) -> None:
    from dataclasses import replace as _replace

    graph = ai_lane(tmp_path)
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id=SITE,
        work_area_id=graph.area.work_area_id,
        view=_owner_view(graph),
        status=200,
        operation="GET_JOB",
    )
    record = graph.sites._sites[SITE]  # noqa: SLF001
    graph.sites._sites[SITE] = _replace(record, ai_egress_allowed=False)  # noqa: SLF001
    messages, status, headers = send_metadata(response)
    assert status == 403
    assert b"x-ksi-spatial-data-ai-egress" not in headers
    _no_protected_body(messages)
    assert graph.ai_audit.count == 0


def test_revocation_after_capture_refuses_snapshot_without_audit(tmp_path: Path) -> None:
    graph = ai_lane(tmp_path)
    journal = graph.path / "jobs.jsonl"
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id=SITE,
        work_area_id=graph.area.work_area_id,
        view=_owner_view(graph),
        status=200,
        operation="GET_JOB",
    )
    jobs_before = _journal_lines(journal)
    revoke(graph)
    messages, status, headers = send_metadata(response)
    assert status == 403
    assert b"x-ksi-spatial-data-ai-egress" not in headers
    _no_protected_body(messages)
    assert graph.ai_audit.count == 0
    assert _journal_lines(journal) == jobs_before


def test_get_after_completion_and_cancel_after_lease_stay_valid(tmp_path: Path) -> None:
    """GET/CANCEL in valid post-progress states publish without false conflict."""
    graph = ai_lane(tmp_path)
    store = graph.ai_store
    attempt = lease(store, graph, graph.ai_view)
    reserve_and_complete(store, graph, graph.ai_view, attempt)
    completed = _owner_view(graph)
    assert completed.execution_state.value == "COMPLETED"
    assert completed.receipt is not None
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id=SITE,
        work_area_id=graph.area.work_area_id,
        view=completed,
        status=200,
        operation="GET_JOB",
    )
    messages, status, headers = send_metadata(response)
    assert status == 200
    assert headers[b"x-ksi-spatial-data-ai-egress"] == b"ALLOWED"
    assert json.loads(_sent_body(messages))["executionState"] == "COMPLETED"

    rerun = ai_lane(tmp_path / "rerun")
    leased = lease(rerun.ai_store, rerun, rerun.ai_view)
    assert leased.attempt_digest is not None
    canceled = rerun.ai_store.cancel(job_id=rerun.ai_view.job_id, principal=rerun.ai, now=NOW)
    assert canceled.execution_state.value == "CANCELED"
    response = rerun.ai_egress.prepare_job_response(
        credentials=ai_credentials(rerun),
        site_id=SITE,
        work_area_id=rerun.area.work_area_id,
        view=canceled,
        status=200,
        operation="CANCEL_JOB",
    )
    messages, status, _ = send_metadata(response)
    assert status == 200
    assert json.loads(_sent_body(messages))["executionState"] == "CANCELED"


def test_post_header_progress_sends_but_post_header_revoke_denies_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Headers frame capture bytes; body still needs fresh rights at its handoff."""
    graph = ai_lane(tmp_path)
    store = graph.ai_store
    attempt = lease(store, graph, graph.ai_view)
    original = store.require_ai_metadata
    calls = {"count": 0}

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "require_ai_metadata", counting, raising=False)
    try:
        real_verify = store.verify_ai_job_snapshot
    except AttributeError:
        pytest.fail("snapshot verification hook missing: race repair not implemented")
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id=SITE,
        work_area_id=graph.area.work_area_id,
        view=_owner_view(graph),
        status=200,
        operation="GET_JOB",
    )
    seen = {"count": 0}

    def progressing(*args: Any, **kwargs: Any) -> Any:
        seen["count"] += 1
        result = real_verify(*args, **kwargs)
        if seen["count"] == 2:
            # Genuine worker completion strictly after the header authorization.
            reserve_and_complete(store, graph, graph.ai_view, attempt)
        return result

    monkeypatch.setattr(store, "verify_ai_job_snapshot", progressing, raising=False)
    messages, status, headers = send_metadata(response)
    assert status == 200
    assert headers[b"x-ksi-spatial-data-ai-egress"] == b"ALLOWED"
    assert json.loads(_sent_body(messages))["executionState"] == "RUNNING"
    assert graph.ai_audit.count == 1


def test_post_header_revoke_denies_body_without_error_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    graph = ai_lane(tmp_path)
    store = graph.ai_store
    response = graph.ai_egress.prepare_job_response(
        credentials=ai_credentials(graph),
        site_id=SITE,
        work_area_id=graph.area.work_area_id,
        view=_owner_view(graph),
        status=200,
        operation="GET_JOB",
    )
    try:
        real_verify = store.verify_ai_job_snapshot
    except AttributeError:
        pytest.fail("snapshot verification hook missing: race repair not implemented")
    seen = {"count": 0}

    def revoking(*args: Any, **kwargs: Any) -> Any:
        seen["count"] += 1
        if seen["count"] == 3:
            # Genuine rights withdrawal strictly after the headers left.
            revoke(graph)
        return real_verify(*args, **kwargs)

    monkeypatch.setattr(store, "verify_ai_job_snapshot", revoking, raising=False)
    messages, status, headers = send_metadata(response)
    assert headers[b"x-ksi-spatial-data-ai-egress"] == b"ALLOWED"
    assert all(m["type"] != "http.response.body" for m in messages), (
        "post-header denial sends no error JSON and no EOF"
    )
    assert graph.ai_audit.count == 1, "the permitted attempt stays recorded"


def test_ai_list_cursor_still_stale_409_on_projection_change(tmp_path: Path) -> None:
    """List/discovery cursors keep strict currentness; the repair is single-job only."""
    from ksi_core.domains.external.delivery.errors import SpatialDataAiDomainError

    graph = ai_lane(tmp_path)
    store = graph.ai_store
    second = store.issue(
        site_id=SITE,
        work_area_id=graph.area.work_area_id,
        request=SpatialDataRequestV1(
            asset_ref=graph.source.asset_ref,
            requested_bounds=(0, 0, 1, 1),
            observed_crs_digest=graph.source.inspection.measurements.observed_crs_digest,
            resolution_mode="NATIVE",
            purpose=SpatialDataPurposeV1.EXTERNAL_AI,
        ),
        principal=graph.ai,
        idempotency_key="ai-two",
        now=NOW,
    )
    first_page = store.list(
        site_id=SITE,
        work_area_id=graph.area.work_area_id,
        principal=graph.ai,
        cursor=None,
        limit=1,
        now=NOW,
    )
    assert first_page.next_cursor is not None
    attempt = lease(store, graph, second)
    reserve_and_complete(store, graph, second, attempt)
    with pytest.raises(SpatialDataAiDomainError) as exc:
        store.list(
            site_id=SITE,
            work_area_id=graph.area.work_area_id,
            principal=graph.ai,
            cursor=first_page.next_cursor,
            limit=1,
            now=NOW,
        )
    assert exc.value.status_code == 409
    assert exc.value.reason == "SPATIAL_DATA_CURSOR_STALE"


# -- actual barrier race over real Core + official SDK + genuine worker --------


# -- FIX1 provenance/boundedness barriers (focused review) ---------------------

INVARIANTS = "INV-040 no fake success; INV-051 provenance lineage; INV-060 cross-org privacy"


def _seal_of(snapshot: Any) -> Any:
    return getattr(snapshot, "seal", None)


def test_fix1_self_consistent_forgery_denied(tmp_path: Path) -> None:
    """A consistent triple-replace (view+body+digest) with changed mutable state must deny.

    Covers INV-040/INV-051: verify must prove owner provenance, not
    self-consistency of supplied bytes.
    """
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    store = graph.ai_store
    snapshot = store.seal_ai_job_snapshot(job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW)
    real = _owner_view(graph)
    forged_view = real.model_copy(update={"execution_state": SpatialDataExecutionStateV1.CANCELED})
    forged_body = _owner_bytes(forged_view)
    assert forged_body != snapshot.body
    forged = replace(
        snapshot,
        view=forged_view,
        body=forged_body,
        body_digest="sha256:" + hashlib.sha256(forged_body).hexdigest(),
    )
    with pytest.raises(SpatialDataDomainError):
        store.verify_ai_job_snapshot(snapshot=forged, principal=graph.ai, now=NOW)


def test_fix1_seal_tamper_and_foreign_key_denied(tmp_path: Path) -> None:
    """The per-store ephemeral seal binds the body; tamper or another key denies.

    Covers INV-051/INV-060: same-clone bytes from a different store never verify.
    """
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    store = graph.ai_store
    snapshot = store.seal_ai_job_snapshot(job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW)
    seal = _seal_of(snapshot)
    assert isinstance(seal, str) and seal, "owner snapshot must carry a store-bound seal"
    tampered = replace(
        snapshot, seal=("0" if seal.endswith("1") else "1").join(seal.rsplit(seal[-1], 1))
    )
    with pytest.raises(SpatialDataDomainError):
        store.verify_ai_job_snapshot(snapshot=tampered, principal=graph.ai, now=NOW)
    original_key = store._snapshot_key  # noqa: SLF001
    try:
        store._snapshot_key = b"\x00" * 32  # noqa: SLF001
        with pytest.raises(SpatialDataDomainError):
            store.verify_ai_job_snapshot(snapshot=snapshot, principal=graph.ai, now=NOW)
    finally:
        store._snapshot_key = original_key  # noqa: SLF001
    assert (
        store.verify_ai_job_snapshot(snapshot=snapshot, principal=graph.ai, now=NOW)
        == snapshot.body
    )


def test_fix1_prepare_never_invokes_credential_resolve(tmp_path: Path) -> None:
    """Slow/blocking OIDC must not stall prepare; prepare uses local ids only.

    Covers INV-040: no fake success and no unbounded wait before the bounded
    response stages own the real credential refresh.
    """
    graph = ai_lane(tmp_path)
    from datetime import datetime

    from ksi_core.domains.external.delivery.credential_currentness import (
        SpatialDataCredentialCurrentness,
    )
    from ksi_core.identity.auth import Principal

    class _Blocked(SpatialDataCredentialCurrentness):
        __slots__ = ()

        def resolve(self, *, now: datetime) -> Principal:
            raise AssertionError("prepare must not invoke remote credential resolve")

    from starlette.requests import Request

    credentials = _Blocked(
        Request({"type": "http", "app": graph.ai_app}),
        "ai-token",
        expected_principal_id=graph.ai.principal_id,
        expected_organization_id=graph.ai.organization_id,
    )
    response = graph.ai_egress.prepare_job_response(
        credentials=credentials,
        site_id=SITE,
        work_area_id=graph.area.work_area_id,
        view=_owner_view(graph),
        status=200,
        operation="GET_JOB",
    )
    assert response is not None


def test_fix1_expected_identity_mismatch_fail_closed(tmp_path: Path) -> None:
    """An expected id that does not match the sealed job/requester refuses.

    Covers INV-060: cross-organization identity never crosses into owner bytes.
    """
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    store = graph.ai_store
    with pytest.raises(SpatialDataDomainError):
        store.seal_ai_job_snapshot(
            job_id=graph.ai_view.job_id,
            expected_principal_id="foreign-principal",
            expected_organization_id=graph.ai.organization_id,
            now=NOW,
        )


def test_fix1_single_guard_no_public_require_reentry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seal/verify hold one shared coordinator guard; they never re-enter the
    public require path (which would release the guard mid-observation).

    Covers currentness/rights atomicity: grant/source mutation cannot slip
    between authorization and the binding read.
    """
    graph = ai_lane(tmp_path)
    store = graph.ai_store

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("seal/verify must use the single-guard locked path")

    monkeypatch.setattr(store, "require_ai_metadata", forbidden, raising=False)
    snapshot = store.seal_ai_job_snapshot(
        job_id=graph.ai_view.job_id,
        expected_principal_id=graph.ai.principal_id,
        expected_organization_id=graph.ai.organization_id,
        now=NOW,
    )
    assert (
        store.verify_ai_job_snapshot(snapshot=snapshot, principal=graph.ai, now=NOW)
        == snapshot.body
    )


def test_fix2_job_id_only_tamper_cannot_transfer_proof(tmp_path: Path) -> None:
    """Changing only the snapshot job_id never transfers the proof to another job.

    Covers INV-051: the per-store seal binds the exact job identity string
    alongside the digests, so a retargeted witness refuses even when every
    other field is untouched.
    """
    from ksi_core.domains.external.delivery.errors import SpatialDataDomainError

    graph = ai_lane(tmp_path)
    store = graph.ai_store
    snapshot = store.seal_ai_job_snapshot(job_id=graph.ai_view.job_id, principal=graph.ai, now=NOW)
    retargeted = replace(snapshot, job_id="sdj-v1-00000000000000000000009999")
    assert retargeted.body == snapshot.body
    with pytest.raises(SpatialDataDomainError):
        store.verify_ai_job_snapshot(snapshot=retargeted, principal=graph.ai, now=NOW)


def test_controlled_publication_race_publishes_without_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Barrier variant of the Primary probe: worker COMPLETED during CREATE_JOB
    publication must succeed with the capture point-in-time, unchanged rights."""
    import httpx
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    with fixture.task5_ai_lane(tmp_path) as lane:
        config = fixture.task5_sdk_config(lane.origin, name="snapshot-race")
        entered, release = threading.Event(), threading.Event()
        original = lane.metadata_audit.append

        def audit(**kwargs: Any) -> Any:
            result = original(**kwargs)
            if kwargs["operation"] == "CREATE_JOB":
                entered.set()
                assert release.wait(15), "bounded barrier timeout"
            return result

        monkeypatch.setattr(lane.metadata_audit, "append", audit)

        async def request() -> Any:
            async with (
                stdio_client(fixture.task5_sdk_parameters(config)) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                return await session.call_tool(
                    "ksi_create_spatial_data_request",
                    {
                        "siteId": "site-1",
                        "workAreaId": lane.area_id,
                        "assetRef": lane.assets["primary"]["asset_ref"],
                        "requestedBounds": list(fixture.TASK5_REQUEST_BOUNDS),
                        "observedCrsDigest": lane.assets["primary"]["observed_crs_digest"],
                        "idempotencyKey": "snapshot-controlled-publication",
                    },
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, request())
            try:
                assert entered.wait(15), "create did not reach audit"
                with httpx.Client(
                    base_url=lane.origin,
                    trust_env=False,
                    timeout=5,
                    headers={"Authorization": "Bearer " + fixture.TASK5_AI_TOKEN},
                ) as client:
                    page = client.get(lane.base, params={"limit": 2})
                    assert page.status_code == 200
                    items = page.json()["items"]
                    assert len(items) == 1
                    assert items[0]["executionState"] == "QUEUED"
                    # Genuine worker progression while publication is paused.
                    final = lane.run_worker(items[0]["jobId"])["executionState"]
                    assert final == "COMPLETED"
                release.set()
                result = future.result(timeout=20)
            finally:
                release.set()
        assert result.is_error is not True, (
            f"publication race must not conflict: {result.structured_content}"
        )
        payload = result.structured_content
        assert isinstance(payload, dict)
        assert payload["executionState"] == "QUEUED"
        assert payload["jobId"] == lane.consumer.status(payload["jobId"])["jobId"]
        durable = lane.consumer.status(payload["jobId"])
        assert durable["executionState"] == "COMPLETED"
