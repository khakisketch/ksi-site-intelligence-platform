"""Guarded AI metadata publication: ack only after final pre-header recheck.

A successful response carries ``X-KSI-Spatial-Data-AI-Egress: ALLOWED`` only
after a genuine credential refresh, a guarded local authorization recheck, a
bounded audit append, a second credential refresh immediately before headers
with the same synchronous recheck immediately before the protected header
handoff, and a third genuine credential refresh with its own synchronous
recheck immediately before the protected body handoff. The header ack stays
valid for its own moment but never authorizes the later bytes. Denials,
stale projections and audit failures yield the AI error envelope with no ack
and no protected body; a denial after headers sends no error JSON and no
successful EOF. The coordinator is never held during remote auth.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from time import monotonic
from typing import TypeVar

from fastapi import HTTPException
from ksi_event_contracts.spatial_data_ai import SpatialDataAiErrorV1, SpatialDataAiReasonV1
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response
from starlette.types import Receive, Scope, Send

from ksi_core.domains.external.delivery.credential_currentness import (
    SpatialDataCredentialCurrentness,
)
from ksi_core.domains.external.delivery.errors import (
    SpatialDataAiDomainError,
    SpatialDataDomainError,
    ai_remediation_for,
    ai_retryable,
)
from ksi_core.identity.auth import Principal

AI_EGRESS_HEADER = b"x-ksi-spatial-data-ai-egress"
AI_EGRESS_ALLOWED = b"ALLOWED"
AI_UNAVAILABLE_MESSAGE = "Spatial data AI request unavailable."

_StageT = TypeVar("_StageT")


class _DisconnectedStop(Exception):
    """Internal signal: the client went away; end quietly, never ack."""


def _digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


_HTTP_STATUS_REASON: dict[int, SpatialDataAiReasonV1] = {
    400: "INVALID_REQUEST_BOUNDS",
    401: "PERMISSION_DENIED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    409: "REPORT_CONFLICT",
    422: "INVALID_REQUEST_BOUNDS",
    429: "CONCURRENCY_LIMIT_EXCEEDED",
    499: "CANCELED",
    503: "CURRENTNESS_UNAVAILABLE",
}


def _reason_for_status(status: int) -> SpatialDataAiReasonV1:
    """Closest closed AI reason for one HTTP failure status; never raw detail."""
    if status in _HTTP_STATUS_REASON:
        return _HTTP_STATUS_REASON[status]
    if status >= 500:
        return "CURRENTNESS_UNAVAILABLE"
    return "PERMISSION_DENIED"


def ai_error_response(error: BaseException) -> JSONResponse:
    """Closed AI refusal envelope; never a raw body, path or secret."""
    if isinstance(error, (SpatialDataAiDomainError, SpatialDataDomainError)):
        reason, status, retryable = error.reason, error.status_code, error.retryable
    elif isinstance(error, HTTPException):
        status = error.status_code
        if type(status) is not int or not 400 <= status <= 599:
            status = 500
        reason, retryable = _reason_for_status(status), False
    else:
        reason, status, retryable = "CURRENTNESS_UNAVAILABLE", 503, True
    envelope = SpatialDataAiErrorV1(
        reason=reason,
        message=AI_UNAVAILABLE_MESSAGE,
        retryable=ai_retryable(status, retryable),
        remediation=ai_remediation_for(str(reason)),
    )
    headers = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        envelope.model_dump(by_alias=True, mode="json"), status_code=status, headers=headers
    )


class SpatialDataAiMetadataResponse(Response):
    """One guarded AI metadata send; neither caller Principals nor stale bytes.

    ``recheck`` runs guarded local authorization for a freshly resolved
    principal and returns canonical body bytes; ``audit`` records the permitted
    send. Credential refresh stays outside coordinator locks; the final recheck
    runs synchronously after the audit, immediately before headers, and the
    bearer is refreshed a third time with its own synchronous recheck
    immediately before the body — the header ack never authorizes later
    bytes. An optional ``preflight`` runs once, bounded, after the first
    credential refresh and before the audit: it may perform bounded remote
    inspection-authority resolution outside coordinator locks, while every
    later ``recheck`` stays genuinely local. Every awaited stage —
    credential refreshes, rechecks, audit, header/body sends and
    the refusal send — runs inside the remaining monotonic publication budget
    while racing client disconnect; a stalled stage ends in a bounded denial
    with no ack, never a hang and never a late success. The audit records the
    permitted publication attempt even when a stage is abandoned afterwards:
    thread work cannot be CPU-preempted, so no success JSON, ack or duplicate
    send ever follows a timeout.
    """

    media_type = "application/json"

    def __init__(
        self,
        *,
        body: bytes,
        status_code: int,
        credentials: SpatialDataCredentialCurrentness,
        clock: Callable[[], datetime],
        max_json_bytes: int,
        started: datetime,
        deadline_seconds: float,
        mono_started: float,
        recheck: Callable[[Principal], bytes],
        audit: Callable[[Principal, bytes], None],
        preflight: Callable[[Principal], bytes] | None = None,
    ) -> None:
        if type(body) is not bytes or not body:
            raise ValueError("guarded AI response requires prepared canonical bytes")
        if status_code not in (200, 201):
            raise ValueError("AI metadata responses are 200 or 201 only")
        if not callable(clock) or not callable(recheck) or not callable(audit):
            raise ValueError("guarded AI response requires clock/recheck/audit closures")
        if preflight is not None and not callable(preflight):
            raise ValueError("guarded AI preflight must be a callable or null")
        if type(max_json_bytes) is not int or max_json_bytes <= 0:
            raise ValueError("guarded AI response requires a positive JSON bound")
        if len(body) > max_json_bytes:
            raise ValueError("prepared AI response exceeds the JSON bound")
        if started.tzinfo is None or started.utcoffset() != UTC.utcoffset(started):
            raise ValueError("guarded AI response requires a UTC-aware publication start")
        if (
            type(deadline_seconds) not in (int, float)
            or not math.isfinite(deadline_seconds)
            or not deadline_seconds > 0
        ):
            raise ValueError("guarded AI response requires a finite positive deadline")
        if (
            type(mono_started) not in (int, float)
            or not math.isfinite(mono_started)
            or mono_started < 0
        ):
            raise ValueError("guarded AI response requires a finite monotonic start")
        super().__init__(
            content=body,
            status_code=status_code,
            media_type=self.media_type,
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )
        self._prepared = body
        self._prepared_digest = _digest(body)
        self._credentials = credentials
        self._clock = clock
        self._max_json_bytes = max_json_bytes
        self._started = started
        self._deadline_seconds = float(deadline_seconds)
        self._mono_start = float(mono_started)
        self._recheck = recheck
        self._audit = audit
        self._preflight = preflight

    def _remaining(self) -> float:
        """Monotonic publication budget left; the injected clock stays authority time."""
        return self._deadline_seconds - (monotonic() - self._mono_start)

    def _check_budget(self) -> None:
        if self._remaining() <= 0:
            raise SpatialDataAiDomainError("DEADLINE_EXCEEDED", 503, True)

    async def _await_stage(
        self, make_stage: Callable[[], Awaitable[_StageT]], disconnected: asyncio.Event
    ) -> _StageT:
        """Await one stage within the remaining budget, racing disconnect.

        The stage awaitable is constructed lazily by ``make_stage`` only
        after the budget/disconnect precheck passes, so a rejected stage
        never leaves an unawaited coroutine behind. A stalled stage is
        abandoned (its thread work is not CPU-preempted and may still append
        an audit attempt); a disconnect ends the publication quietly. Neither
        path ever sends success or an ack.
        """
        remaining = self._remaining()
        if remaining <= 0 or disconnected.is_set():
            if disconnected.is_set():
                raise _DisconnectedStop()
            raise SpatialDataAiDomainError("DEADLINE_EXCEEDED", 503, True)
        task = asyncio.ensure_future(make_stage())
        waiter = asyncio.create_task(disconnected.wait())
        try:
            done, _ = await asyncio.wait(
                {task, waiter}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
            if task in done:
                return task.result()
            if disconnected.is_set():
                raise _DisconnectedStop()
            raise SpatialDataAiDomainError("DEADLINE_EXCEEDED", 503, True)
        finally:
            if not waiter.done():
                waiter.cancel()
            if not task.done():
                task.cancel()
            for pending in (waiter, task):
                with suppress(asyncio.CancelledError):
                    await pending

    async def _refuse(
        self, scope: Scope, receive: Receive, send: Send, error: BaseException
    ) -> None:
        await ai_error_response(error)(scope, receive, send)

    async def _send_guarded_headers(
        self, late_principal: Principal, send: Send, disconnected: asyncio.Event
    ) -> bytes:
        """Final synchronous authorization immediately before the actual send.

        Runs as the first step of the bounded header-send task: no await
        separates this check from the transport send call below, so a
        revocation queued by the event loop cannot slip between authorization
        and send (application scheduling is covered; only the actual awaited
        transport handoff afterwards is disclosed as unavoidable). Returns
        the exact body the headers frame.
        """
        late = self._recheck(late_principal)
        self._check_bounded(late)
        if _digest(late) != self._prepared_digest:
            raise SpatialDataAiDomainError("REPORT_CONFLICT", 409)
        self._check_deadline()
        self._check_budget()
        if disconnected.is_set():
            raise _DisconnectedStop()
        start_headers = [
            (key, value) for key, value in self.raw_headers if key.lower() != b"content-length"
        ]
        start_headers.append((b"content-length", str(len(late)).encode("ascii")))
        await send(
            {
                "type": "http.response.start",
                "status": self.status_code,
                "headers": [*start_headers, (AI_EGRESS_HEADER, AI_EGRESS_ALLOWED)],
            }
        )
        return late

    async def _send_guarded_body(
        self, principal: Principal, send: Send, disconnected: asyncio.Event
    ) -> None:
        """Final synchronous authorization immediately before the actual body.

        ``principal`` must be a freshly resolved bearer from the bounded
        body credential refresh in ``__call__`` — never a principal captured
        before the headers. Re-runs the guarded local authorization
        synchronously with no await between this check and the transport
        send call below, so a revocation applied after the headers left
        still denies the body (application scheduling is covered; only the
        actual awaited transport handoff afterwards is disclosed as
        unavoidable). A denial after headers sends no error JSON and no
        successful EOF: the transport stays interrupted, and the
        already-sent header ack keeps only its timestamp validity, never a
        delivery promise.
        """
        fresh = self._recheck(principal)
        self._check_bounded(fresh)
        if _digest(fresh) != self._prepared_digest:
            raise SpatialDataAiDomainError("REPORT_CONFLICT", 409)
        self._check_deadline()
        self._check_budget()
        if disconnected.is_set():
            raise _DisconnectedStop()
        await send({"type": "http.response.body", "body": fresh, "more_body": False})

    def _check_bounded(self, body: bytes) -> None:
        if type(body) is not bytes or not body or len(body) > self._max_json_bytes:
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)

    def _check_deadline(self) -> None:
        elapsed = (self._clock() - self._started).total_seconds()
        if not elapsed >= 0 or elapsed > self._deadline_seconds:
            raise SpatialDataAiDomainError("DEADLINE_EXCEEDED", 503, True)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        disconnected = asyncio.Event()

        async def watch() -> None:
            # A broken receive channel is a disconnect: stop fail-closed with
            # no ack, never continue sending on a channel known to be broken.
            try:
                while True:
                    message = await receive()
                    if message.get("type") == "http.disconnect":
                        disconnected.set()
                        return
            except asyncio.CancelledError:
                raise
            except Exception:
                disconnected.set()
                return

        watcher = asyncio.create_task(watch())
        headers_sent = False
        try:
            self._check_deadline()
            self._check_budget()
            if disconnected.is_set():
                return
            # Genuine refresh first: remote auth never runs inside coordinator locks.
            principal = await self._await_stage(
                lambda: run_in_threadpool(self._credentials.resolve, now=self._clock()),
                disconnected,
            )
            self._check_deadline()
            self._check_budget()
            if disconnected.is_set():
                return
            preflight = self._preflight
            if preflight is None:
                fresh = await self._await_stage(
                    lambda: run_in_threadpool(self._recheck, principal), disconnected
                )
            else:
                # Bounded remote inspection preflight runs once, outside
                # coordinator locks, before the audit; every later recheck
                # stays genuinely local. Drift between prepare and preflight
                # is a typed stale conflict, never stale bytes.
                fresh = await self._await_stage(
                    lambda: run_in_threadpool(preflight, principal), disconnected
                )
            self._check_bounded(fresh)
            if _digest(fresh) != self._prepared_digest:
                raise SpatialDataAiDomainError("REPORT_CONFLICT", 409)
            self._check_deadline()
            self._check_budget()
            if disconnected.is_set():
                return
            # The audit records the permitted publication attempt, not client
            # delivery: a later denial keeps this attempt event.
            await self._await_stage(
                lambda: run_in_threadpool(self._audit, principal, fresh), disconnected
            )
            self._check_deadline()
            self._check_budget()
            if disconnected.is_set():
                return
            late_principal = await self._await_stage(
                lambda: run_in_threadpool(self._credentials.resolve, now=self._clock()),
                disconnected,
            )
            self._check_deadline()
            self._check_budget()
            if disconnected.is_set():
                return
            # The bounded header-send task owns the final synchronous
            # authorization: no await separates that check from the actual
            # send call inside it, so application scheduling cannot slip a
            # revocation between authorization and send. Only the actual
            # awaited transport handoff afterwards is unavoidable — and bytes
            # handed to transport can never be recalled.
            await self._await_stage(
                lambda: self._send_guarded_headers(late_principal, send, disconnected),
                disconnected,
            )
            headers_sent = True
            # Genuine bearer currentness for these exact bytes: the header
            # ack only proves rights at its own moment, so the bearer is
            # refreshed again — bounded, off coordinator locks — before the
            # body. A token revoked, expired, rescoped or re-identified after
            # the headers left is refused here with no error JSON and no
            # successful EOF (see _send_guarded_body).
            body_principal = await self._await_stage(
                lambda: run_in_threadpool(self._credentials.resolve, now=self._clock()),
                disconnected,
            )
            self._check_deadline()
            self._check_budget()
            if disconnected.is_set():
                return
            # The bounded body-send task owns the same synchronous
            # authorization immediately before its handoff, now over the
            # freshly resolved body principal: a revocation applied after
            # the headers left denies the body with no error JSON and no
            # successful EOF (see _send_guarded_body).
            await self._await_stage(
                lambda: self._send_guarded_body(body_principal, send, disconnected),
                disconnected,
            )
        except _DisconnectedStop:
            return
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError) or not isinstance(exc, Exception):
                raise
            error = exc
            if not headers_sent and not disconnected.is_set():
                with suppress(_DisconnectedStop, SpatialDataAiDomainError):
                    await self._await_stage(
                        lambda: self._refuse(scope, receive, send, error), disconnected
                    )
            # After headers, no JSON, modified length or successful EOF.
        finally:
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
