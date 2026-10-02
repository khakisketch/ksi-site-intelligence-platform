"""Raw ASGI success/abort contract; a send acknowledgement is not client receipt evidence."""

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from ksi_core.domains.external.delivery.audit import SpatialDataAuditEventV1
from spatial_data_download_fixture import delivery_graph, prepare
from starlette.types import Message


def stream(
    graph: SimpleNamespace,
    *,
    head: bool = False,
    after_send: Any = None,
    disconnect: bool = False,
    block: bool = False,
    cancel: bool = False,
) -> Any:
    from ksi_core.domains.external.delivery.download_response import SpatialDataDownloadResponse

    prepared = prepare(graph)
    response = SpatialDataDownloadResponse(prepared, head_only=head)
    messages = []

    async def run() -> Any:
        async def send(message: Message) -> None:
            if block and message["type"] == "http.response.body":
                await asyncio.Event().wait()
            if cancel and message["type"] == "http.response.body":
                raise asyncio.CancelledError()
            messages.append(message)
            if after_send:
                after_send(message)

        async def receive() -> Message:
            if disconnect:
                return {"type": "http.disconnect"}
            await asyncio.Event().wait()
            raise AssertionError("unset receive event unexpectedly returned")

        await response(
            {
                "type": "http",
                "method": "HEAD" if head else "GET",
                "headers": [],
                "asgi": {"version": "3.0"},
            },
            receive,
            send,
        )

    asyncio.run(run())
    return messages, prepared


def actions(graph: SimpleNamespace, prepared: Any) -> tuple[SpatialDataAuditEventV1, ...]:
    return graph.audit.events(
        organization_id=graph.graph.principal.organization_id,
        session_id=prepared.session_id,
        limit=graph.graph.data_policy.max_list_records,
    )


def test_asgi_full_hashed_output_has_safe_exact_headers_and_durable_handoff_count(
    tmp_path: Path,
) -> None:
    graph = delivery_graph(tmp_path)
    messages, prepared = stream(graph)
    start = messages[0]
    assert start["status"] == 200
    headers = dict(start["headers"])
    assert headers[b"content-length"] == b"1024"
    assert headers[b"cache-control"] == b"private, no-store"
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"x-content-sha256"] == graph.observation.sha256.encode()
    assert (
        headers[b"content-disposition"]
        == f'attachment; filename="{graph.issued.job_id}.tif"'.encode()
    )
    assert b"location" not in headers and b"content-encoding" not in headers
    assert b"".join(m.get("body", b"") for m in messages) == graph.payload
    assert messages[-1]["more_body"] is False
    history = actions(graph, prepared)
    assert [event.action for event in history] == [
        "DOWNLOAD_ADMITTED",
        "STREAM_STARTED",
        "STREAM_COMPLETED",
    ]
    assert history[-1].sent_bytes == 1024
    assert graph.service.active_downloads == 0 and list(graph.spool.iterdir()) == []


def test_asgi_head_rechecks_current_rights_and_sends_no_content(tmp_path: Path) -> None:
    graph = delivery_graph(tmp_path)
    messages, prepared = stream(graph, head=True)
    assert (
        messages[0]["status"] == 200 and dict(messages[0]["headers"])[b"content-length"] == b"1024"
    )
    assert all(not item.get("body") for item in messages)
    assert [e.action for e in actions(graph, prepared)] == [
        "DOWNLOAD_ADMITTED",
        "HEAD_STARTED",
        "HEAD_COMPLETED",
    ]
    assert graph.service.active_downloads == 0


@pytest.mark.parametrize("change", ["scope", "credential", "audit"])
@pytest.mark.parametrize("head", [False, True])
def test_asgi_deny_after_spool_before_success_headers(
    tmp_path: Path, change: str, head: bool
) -> None:
    from ksi_core.domains.external.delivery.download_response import SpatialDataDownloadResponse

    graph = delivery_graph(tmp_path)
    prepared = prepare(graph)
    if change == "scope":
        graph.credentials.principal = replace(graph.graph.principal, organization_id="foreign")
    elif change == "credential":
        graph.credentials.enabled = False
    else:
        graph.audit.close()
    messages = []

    async def send(item: Message) -> None:
        messages.append(item)

    async def receive() -> Message:
        await asyncio.Event().wait()
        raise AssertionError("unset receive event unexpectedly returned")

    asyncio.run(
        SpatialDataDownloadResponse(prepared, head_only=head)(
            {"type": "http", "headers": [], "method": "HEAD" if head else "GET"}, receive, send
        )
    )
    assert not any(m["type"] == "http.response.start" and m["status"] == 200 for m in messages)
    assert graph.service.active_downloads == 0 and list(graph.spool.iterdir()) == []


@pytest.mark.parametrize("change", ["scope", "credential", "lane"])
def test_asgi_midstream_revoke_preserves_length_but_never_sends_successful_eof(
    tmp_path: Path, change: str
) -> None:
    graph = delivery_graph(tmp_path)

    def after(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            if change == "scope":
                graph.credentials.principal = replace(
                    graph.graph.principal, organization_id="foreign"
                )
            elif change == "credential":
                graph.credentials.enabled = False
            else:
                graph.graph.authority.enabled = False

    messages, prepared = stream(graph, after_send=after)
    assert dict(messages[0]["headers"])[b"content-length"] == b"1024"
    assert sum(len(m.get("body", b"")) for m in messages) == 512
    assert not any(
        m["type"] == "http.response.body" and m.get("more_body") is False for m in messages
    )
    history = actions(graph, prepared)
    assert history[-1].action == "STREAM_INTERRUPTED" and history[-1].sent_bytes == 512
    assert all(e.action != "STREAM_COMPLETED" for e in history)
    assert graph.service.active_downloads == 0


def test_asgi_blocked_send_deadline_has_no_successful_eof_and_releases_spool(
    tmp_path: Path,
) -> None:
    graph = delivery_graph(tmp_path)
    prepared = prepare(graph)
    prepared.started -= graph.graph.data_policy.stream_deadline_seconds - 0.05
    from ksi_core.domains.external.delivery.download_response import SpatialDataDownloadResponse

    messages = []

    async def send(item: Message) -> None:
        if item["type"] == "http.response.body":
            await asyncio.Event().wait()
        messages.append(item)

    async def receive() -> Message:
        await asyncio.Event().wait()
        raise AssertionError("unset receive event unexpectedly returned")

    asyncio.run(
        SpatialDataDownloadResponse(prepared)(
            {"type": "http", "method": "GET", "headers": []}, receive, send
        )
    )
    assert actions(graph, prepared)[-1].reason == "DEADLINE_EXCEEDED"
    assert actions(graph, prepared)[-1].sent_bytes == 0
    assert graph.service.active_downloads == 0


def test_asgi_disconnect_and_cancellation_release_private_resources(tmp_path: Path) -> None:
    graph = delivery_graph(tmp_path)
    messages, prepared = stream(graph, disconnect=True)
    assert graph.service.active_downloads == 0
    assert all(e.action != "STREAM_COMPLETED" for e in actions(graph, prepared))
    with pytest.raises(asyncio.CancelledError):
        stream(graph, cancel=True)
    assert graph.service.active_downloads == 0 and list(graph.spool.iterdir()) == []


def test_asgi_failed_final_send_cannot_record_completed_stream(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.download_response import SpatialDataDownloadResponse

    graph = delivery_graph(tmp_path)
    prepared = prepare(graph)

    async def send(item: Message) -> None:
        if item["type"] == "http.response.body" and item.get("more_body") is False:
            raise OSError("client closed before final handoff")

    async def receive() -> Message:
        await asyncio.Event().wait()
        raise AssertionError("unset receive event unexpectedly returned")

    asyncio.run(
        SpatialDataDownloadResponse(prepared)(
            {"type": "http", "method": "GET", "headers": []}, receive, send
        )
    )
    history = actions(graph, prepared)
    assert all(item.action != "STREAM_COMPLETED" for item in history)
    assert history[-1].action == "STREAM_INTERRUPTED" and history[-1].sent_bytes == 1024
    assert graph.service.active_downloads == 0


def test_asgi_receive_transport_failure_still_closes_spool_and_quota(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.download_response import SpatialDataDownloadResponse

    graph = delivery_graph(tmp_path)
    prepared = prepare(graph)

    async def send(item: Message) -> None:
        await asyncio.sleep(0)

    async def receive() -> Message:
        raise OSError("receive transport stopped")

    asyncio.run(
        SpatialDataDownloadResponse(prepared)(
            {"type": "http", "method": "GET", "headers": []}, receive, send
        )
    )
    assert graph.service.active_downloads == 0 and prepared.closed


def test_asgi_fresh_credential_checks_never_block_receive_loop_thread(tmp_path: Path) -> None:
    import threading

    from ksi_core.domains.external.delivery.download_response import SpatialDataDownloadResponse

    graph = delivery_graph(tmp_path)
    prepared = prepare(graph)
    loop_thread = threading.get_ident()
    observed = []
    original = graph.credentials.resolve

    def resolve(*, now: Any) -> Any:
        observed.append(threading.get_ident())
        return original(now=now)

    graph.credentials.resolve = resolve

    async def send(item: Message) -> None:
        await asyncio.sleep(0)

    async def receive() -> Message:
        await asyncio.Event().wait()
        raise AssertionError("unset receive event unexpectedly returned")

    asyncio.run(
        SpatialDataDownloadResponse(prepared)(
            {"type": "http", "method": "GET", "headers": []}, receive, send
        )
    )
    assert observed and loop_thread not in observed


def test_asgi_authorization_wait_is_bounded_without_waiting_for_late_read_only_refresh(
    tmp_path: Path,
) -> None:
    import threading

    from ksi_core.domains.external.delivery.download_response import SpatialDataDownloadResponse

    graph = delivery_graph(tmp_path)
    prepared = prepare(graph)
    prepared.started -= graph.graph.data_policy.stream_deadline_seconds - 0.03
    release, entered = threading.Event(), threading.Event()
    original = graph.credentials.resolve

    def delayed(*, now: Any) -> Any:
        entered.set()
        assert release.wait(2)
        return original(now=now)

    graph.credentials.resolve = delayed
    messages = []

    async def send(item: Message) -> None:
        messages.append(item)

    async def receive() -> Message:
        await asyncio.Event().wait()
        raise AssertionError("unset receive event unexpectedly returned")

    async def run() -> None:
        task = asyncio.create_task(
            SpatialDataDownloadResponse(prepared)(
                {"type": "http", "method": "GET", "headers": []}, receive, send
            )
        )
        try:
            done, _ = await asyncio.wait({task}, timeout=0.2)
            assert task in done and entered.is_set()
            assert prepared.closed and graph.service.active_downloads == 0
        finally:
            release.set()
            await task

    asyncio.run(run())
    assert not any(
        item["type"] == "http.response.start" and item["status"] == 200 for item in messages
    )
