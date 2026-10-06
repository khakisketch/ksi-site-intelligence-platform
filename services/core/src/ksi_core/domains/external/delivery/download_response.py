"""Guarded ASGI byte sends: no successful EOF after authorization/deadline failure."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from time import monotonic

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.types import Message, Receive, Scope, Send

from ksi_core.domains.external.delivery.api import error_response
from ksi_core.domains.external.delivery.downloads import SpatialDataPreparedDownload
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.identity.auth import Principal, PrincipalKind


class SpatialDataDownloadResponse(Response):
    def __init__(self, prepared: SpatialDataPreparedDownload, *, head_only: bool = False):
        super().__init__(
            content=b"",
            media_type="image/tiff",
            headers={
                "Content-Length": str(prepared.size_bytes),
                "Content-Disposition": f'attachment; filename="{prepared.output.job.job_id}.tif"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Content-SHA256": prepared.sha256,
            },
        )
        self.prepared, self.head_only = prepared, head_only

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        prepared = self.prepared
        started = False
        headers_sent = False
        terminal = False
        sent_bytes = 0
        disconnected = asyncio.Event()

        async def watch_disconnect() -> None:
            try:
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        disconnected.set()
                        return
                    await asyncio.sleep(0)
            except Exception:
                disconnected.set()

        watcher = asyncio.create_task(watch_disconnect())
        waiting_disconnect = asyncio.create_task(disconnected.wait())

        async def bounded_wait[Result](task: asyncio.Task[Result]) -> Result:
            budget = prepared.policy.stream_deadline_seconds - (monotonic() - prepared.started)
            try:
                done, _ = await asyncio.wait(
                    {task, waiting_disconnect},
                    timeout=max(0, budget),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if task in done:
                    return await task
                if disconnected.is_set():
                    raise SpatialDataDomainError("CANCELED", 499)
                raise SpatialDataDomainError("DEADLINE_EXCEEDED", 503)
            finally:
                if not task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task

        async def authorize() -> Principal:
            if disconnected.is_set():
                raise SpatialDataDomainError("CANCELED", 499)
            prepared.check_deadline()

            async def refresh() -> Principal:
                # Late auth is read-only: it owns no spool, audit append or byte send.
                return await run_in_threadpool(prepared.authorize, prepared.service.clock())

            principal = await bounded_wait(asyncio.create_task(refresh()))
            prepared.check_deadline()
            if disconnected.is_set():
                raise SpatialDataDomainError("CANCELED", 499)
            return principal

        async def guarded_send(message: Message) -> None:
            await authorize()

            async def handoff() -> None:
                await send(message)

            await bounded_wait(asyncio.create_task(handoff()))

        try:
            pre_principal = await authorize()
            await run_in_threadpool(
                prepared.audit, "HEAD_STARTED" if self.head_only else "STREAM_STARTED"
            )
            started = True
            start_headers = list(self.raw_headers)
            if pre_principal.kind is PrincipalKind.SPATIAL_DATA_MCP_CLIENT:
                # Attestation of this response's authorization only: the ack is
                # added after prepared.authorize succeeded, never preflight and
                # never on error responses below.
                start_headers.append((b"x-ksi-spatial-data-ai-egress", b"ALLOWED"))
            # Last authorization occurs after durable audit, immediately before headers.
            await guarded_send(
                {"type": "http.response.start", "status": 200, "headers": start_headers}
            )
            headers_sent = True
            if not self.head_only:
                prepared.spool.seek(0)
                while chunk := prepared.read_spool_chunk():
                    await guarded_send(
                        {"type": "http.response.body", "body": chunk, "more_body": True}
                    )
                    sent_bytes += len(chunk)
                await authorize()
            await guarded_send({"type": "http.response.body", "body": b"", "more_body": False})
            await run_in_threadpool(
                prepared.audit,
                "HEAD_COMPLETED" if self.head_only else "STREAM_COMPLETED",
                sent_bytes=sent_bytes,
            )
            terminal = True
        except BaseException as exc:
            reason = (
                exc.reason
                if isinstance(exc, SpatialDataDomainError)
                else "PERMISSION_DENIED"
                if isinstance(exc, HTTPException)
                else "CANCELED"
                if isinstance(exc, (asyncio.CancelledError, OSError))
                else "STORAGE_UNAVAILABLE"
            )
            if not terminal:
                with suppress(SpatialDataDomainError):
                    await run_in_threadpool(
                        prepared.audit,
                        "STREAM_INTERRUPTED" if started else "DENIED",
                        sent_bytes=sent_bytes,
                        reason=reason,
                    )
            if not isinstance(exc, Exception):
                raise
            if not headers_sent and not disconnected.is_set():
                failure = (
                    exc
                    if isinstance(exc, SpatialDataDomainError)
                    else SpatialDataDomainError("PERMISSION_DENIED", exc.status_code)
                    if isinstance(exc, HTTPException)
                    else SpatialDataDomainError("STORAGE_UNAVAILABLE", 503)
                )

                async def error_send(message: Message) -> None:
                    if self.head_only and message["type"] == "http.response.body":
                        message = {**message, "body": b""}
                    await send(message)

                budget = prepared.policy.stream_deadline_seconds - (monotonic() - prepared.started)
                if budget > 0:
                    response = error_response(failure)
                    if failure.status_code == 401:
                        response.headers["WWW-Authenticate"] = "Bearer"
                    with suppress(TimeoutError):
                        async with asyncio.timeout(budget):
                            await response(scope, receive, error_send)
            # After headers, no JSON, modified Content-Length or successful EOF.
        finally:
            try:
                watcher.cancel()
                waiting_disconnect.cancel()
                with suppress(asyncio.CancelledError):
                    await watcher
                with suppress(asyncio.CancelledError):
                    await waiting_disconnect
            finally:
                prepared.close()
