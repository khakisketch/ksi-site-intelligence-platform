"""Real mounted registry refresh cannot label credential denial as storage failure."""

import asyncio
import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, Request
from ksi_core.auth import AuthRegistry, PrincipalTokenRecord
from ksi_core.domains.external.delivery.credential_currentness import (
    SpatialDataCredentialCurrentness,
)
from ksi_core.domains.external.delivery.download_response import SpatialDataDownloadResponse
from spatial_data_http_fixture import http_lane
from spatial_data_job_fixture import NOW
from starlette.types import Message


@pytest.mark.parametrize("phase", ["spooling", "preheaders", "midstream"])
@pytest.mark.parametrize("mutation", ["principal", "organization", "missing"])
def test_real_credential_remap_has_permission_denial_audit_and_no_successful_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: str, mutation: str
) -> None:
    with http_lane(tmp_path, stream_chunk_bytes=128) as lane:
        status = lane.request_and_run()
        assert status["receipt"]["outputSizeBytes"] > lane.graph.data_policy.stream_chunk_bytes
        principal = lane.graph.principal
        request = Request({"type": "http", "app": lane.http.app})
        credentials = SpatialDataCredentialCurrentness(
            request,
            "local",
            expected_principal_id=principal.principal_id,
            expected_organization_id=principal.organization_id,
        )

        def remap() -> None:
            changed = replace(
                principal,
                **(
                    {"principal_id": "remapped"}
                    if mutation == "principal"
                    else {"organization_id": "remapped"}
                    if mutation == "organization"
                    else {}
                ),
            )
            assert isinstance(lane.http.app, FastAPI)
            lane.http.app.state.auth_registry = AuthRegistry(
                []
                if mutation == "missing"
                else [
                    PrincipalTokenRecord(
                        token_sha256=hashlib.sha256(b"local").hexdigest(), principal=changed
                    )
                ]
            )

        kwargs = dict(job_id=status["jobId"], principal=principal, credentials=credentials, now=NOW)
        if phase == "spooling":
            original = lane.provider.open_version

            @contextmanager
            def substituted(*args: Any, **kw: Any) -> Iterator[Any]:
                with original(*args, **kw) as chunks:
                    remap()
                    yield chunks

            monkeypatch.setattr(lane.provider, "open_version", substituted)
            with pytest.raises(HTTPException) as failure:
                lane.downloads.prepare(**kwargs)
            assert failure.value.status_code == 401
            events = list(lane.audit._journal.replay())
            assert events[-1]["event"]["reason"] == "PERMISSION_DENIED"
        else:
            prepared = lane.downloads.prepare(**kwargs)
            if phase == "preheaders":
                remap()
            messages = []

            async def send(message: Message) -> None:
                messages.append(message)
                if (
                    phase == "midstream"
                    and message["type"] == "http.response.body"
                    and message.get("body")
                ):
                    remap()

            async def receive() -> Message:
                await asyncio.Event().wait()
                raise AssertionError("unset receive event unexpectedly returned")

            asyncio.run(
                SpatialDataDownloadResponse(prepared)(
                    {"type": "http", "method": "GET", "headers": []}, receive, send
                )
            )
            history = lane.audit.events(
                organization_id=principal.organization_id,
                session_id=prepared.session_id,
                limit=lane.graph.data_policy.max_list_records,
            )
            assert history[-1].reason == "PERMISSION_DENIED"
            assert all(e.action != "STREAM_COMPLETED" for e in history)
            if phase == "preheaders":
                assert messages[0]["status"] == 401
                assert dict(messages[0]["headers"])[b"www-authenticate"] == b"Bearer"
            else:
                assert messages[0]["status"] == 200
                assert (
                    sum(len(m.get("body", b"")) for m in messages)
                    == lane.graph.data_policy.stream_chunk_bytes
                )
                assert not any(
                    m["type"] == "http.response.body" and m.get("more_body") is False
                    for m in messages
                )
        assert lane.downloads.active_downloads == 0 and list(lane.spool.iterdir()) == []
