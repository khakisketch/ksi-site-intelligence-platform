"""Dedicated data-worker Core transport; no Analysis authority or object endpoint access.

HTTP phase timeouts and bounded streaming responses are transport controls, not host
containment proof. The isolated raster child never receives this client or its bearer.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from datetime import datetime
from time import monotonic
from typing import Any, Self
from urllib.parse import urlsplit

import httpx
from ksi_event_contracts.spatial_data import (
    SpatialDataAttemptV1,
    SpatialDataFrozenJobV1,
    SpatialDataJobViewV1,
    SpatialDataReasonV1,
)
from ksi_event_contracts.spatial_data_authority import (
    SpatialDataActivationV1,
    SpatialDataPolicyV1,
    SpatialDataRuntimeV1,
)
from ksi_event_contracts.spatial_data_worker import (
    TRANSIENT_STORAGE_REASONS,
    SpatialDataCompleteRequestV1,
    SpatialDataFailureRequestV1,
    SpatialDataLeaseRequestV1,
    SpatialDataLeaseViewV1,
    SpatialDataOutputUploadRequestV1,
    SpatialDataOutputUploadViewV1,
    SpatialDataRenewRequestV1,
    SpatialDataUploadDeclarationV1,
    SpatialDataWorkerInputResponseV1,
    SpatialDataWorkerInputV1,
    SpatialDataWorkerMutationViewV1,
    SpatialDataWorkerPendingPageV1,
)
from pydantic import BaseModel

BASE = "/v1/internal/spatial-data-jobs"
_JOB = re.compile(r"sdj-v1-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")


class SpatialDataCoreClientError(RuntimeError):
    """Safe local reason only; no endpoint, body, credential or exception reflection."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _nonfinite(value: str) -> Any:
    raise ValueError("nonfinite JSON")


class SpatialDataCoreClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        activation: SpatialDataActivationV1,
        policy: SpatialDataPolicyV1,
        runtime: SpatialDataRuntimeV1,
        clock: Callable[[], datetime],
        maximum_response_bytes: int,
        request_timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
        refresh_credentials: Callable[[], str] | None = None,
        authority_is_current: Callable[[], bool] | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or not callable(clock)
            or type(token) is not str
            or not 1 <= len(token) <= 4096
            or any(ord(char) <= 32 or ord(char) > 126 for char in token)
        ):
            raise ValueError(
                "explicit secure Core origin, clock and separate bounded bearer required"
            )
        for value in (activation, policy, runtime):
            validated = type(value).model_validate(value.model_dump())
            if getattr(validated, validated._digest_field) != validated.canonical_digest():
                raise ValueError("sealed distinct data authority required")
        if (
            activation.policy_digest != policy.policy_digest
            or activation.runtime_digest != runtime.runtime_digest
            or type(maximum_response_bytes) is not int
            or not 0 < maximum_response_bytes <= policy.max_snapshot_bytes
            or type(request_timeout_seconds) not in (int, float)
            or not math.isfinite(request_timeout_seconds)
            or not 0 < request_timeout_seconds <= policy.resource_envelope.max_deadline_seconds
        ):
            raise ValueError(
                "exact data authority and explicit finite response/timeout budgets required"
            )
        self._activation = activation.model_copy(deep=True)
        self._policy = policy.model_copy(deep=True)
        self._runtime = runtime.model_copy(deep=True)
        self._clock = clock
        self._maximum = maximum_response_bytes
        self._timeout = request_timeout_seconds
        self._token = token
        self._refresh_credentials = refresh_credentials
        self._authority_is_current = authority_is_current
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=request_timeout_seconds,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()
        self._token = ""

    def _path(self, job_id: str, tail: str) -> str:
        if type(job_id) is not str or _JOB.fullmatch(job_id) is None:
            raise SpatialDataCoreClientError("INVALID_REQUEST")
        return BASE + "/" + job_id + "/" + tail

    def _check_attempt(self, attempt: SpatialDataAttemptV1) -> SpatialDataAttemptV1:
        try:
            attempt = SpatialDataAttemptV1.model_validate(attempt.model_dump())
            if (
                attempt.attempt_digest != attempt.canonical_digest()
                or attempt.worker_instance_id != self._activation.worker_instance_id
                or attempt.worker_principal_id != self._activation.worker_principal_id
                or not attempt.acquired_at <= self._clock() < attempt.lease_until
            ):
                raise ValueError("attempt not current for activated worker")
            return attempt
        except ValueError as exc:
            raise SpatialDataCoreClientError("FENCE_CONFLICT") from exc

    def _request(
        self,
        method: str,
        path: str,
        model: type[BaseModel],
        *,
        body: BaseModel | None = None,
        attempt: SpatialDataAttemptV1 | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        if not self._activation.is_current_at(self._clock()) or not self._token:
            raise SpatialDataCoreClientError("ACTIVATION_UNAVAILABLE")
        try:
            if self._authority_is_current is not None and self._authority_is_current() is not True:
                raise ValueError("fresh data authority unavailable")
            token = (
                self._refresh_credentials()
                if self._refresh_credentials is not None
                else self._token
            )
            if (
                type(token) is not str
                or not 1 <= len(token) <= 4096
                or any(ord(c) <= 32 or ord(c) > 126 for c in token)
            ):
                raise ValueError("fresh bounded credential unavailable")
        except Exception as exc:
            raise SpatialDataCoreClientError("ACTIVATION_UNAVAILABLE") from exc
        headers = {
            "Authorization": "Bearer " + token,
            "X-Spatial-Data-Worker-Instance-Id": self._activation.worker_instance_id,
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
        }
        if attempt is not None:
            attempt = self._check_attempt(attempt)
            headers["X-Spatial-Data-Attempt-Digest"] = attempt.attempt_digest or ""
        try:
            content = (
                json.dumps(
                    body.model_dump(by_alias=True, mode="json"),
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                if body is not None
                else None
            )
            if content is not None and len(content) > self._policy.max_json_bytes:
                raise SpatialDataCoreClientError("RESOURCE_LIMIT_EXCEEDED")
            started = monotonic()
            self._client.cookies.clear()
            with self._client.stream(
                method, path, headers=headers, content=content, params=params
            ) as response:
                if response.status_code not in (200, 201):
                    raise SpatialDataCoreClientError("CORE_REQUEST_DENIED")
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise SpatialDataCoreClientError("INVALID_CORE_RESPONSE")
                payload = bytearray()
                for chunk in response.iter_bytes(chunk_size=min(65536, self._maximum)):
                    if monotonic() - started >= self._timeout:
                        raise SpatialDataCoreClientError("CORE_TIMEOUT")
                    if len(payload) + len(chunk) > self._maximum:
                        raise SpatialDataCoreClientError("RESOURCE_LIMIT_EXCEEDED")
                    payload.extend(chunk)
            if monotonic() - started >= self._timeout:
                raise SpatialDataCoreClientError("CORE_TIMEOUT")
            value = json.loads(
                payload.decode("utf-8", errors="strict"),
                object_pairs_hook=_pairs,
                parse_constant=_nonfinite,
            )
            return model.model_validate(value)
        except SpatialDataCoreClientError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise SpatialDataCoreClientError("CORE_UNAVAILABLE") from exc
        except (ValueError, TypeError, RecursionError) as exc:
            raise SpatialDataCoreClientError("INVALID_CORE_RESPONSE") from exc

    def pending(self, *, limit: int) -> tuple[SpatialDataFrozenJobV1, ...]:
        if type(limit) is not int or not 1 <= limit <= self._policy.max_pending_records:
            raise SpatialDataCoreClientError("INVALID_REQUEST")
        page = self._request("GET", BASE, SpatialDataWorkerPendingPageV1, params={"limit": limit})
        if len(page.items) > limit:
            raise SpatialDataCoreClientError("RESOURCE_LIMIT_EXCEEDED")
        for job in page.items:
            if (
                job.job_digest != job.canonical_digest()
                or job.organization_id != self._activation.organization_id
                or job.policy != self._policy
                or job.runtime != self._runtime
            ):
                raise SpatialDataCoreClientError("INVALID_CORE_RESPONSE")
        return page.items

    def lease(self, *, job_id: str, acquisition_id: str) -> SpatialDataAttemptV1:
        path = self._path(job_id, "lease")
        try:
            body = SpatialDataLeaseRequestV1(
                worker_instance_id=self._activation.worker_instance_id,
                acquisition_id=acquisition_id,
            )
        except ValueError as exc:
            raise SpatialDataCoreClientError("INVALID_REQUEST") from exc
        response = self._request("POST", path, SpatialDataLeaseViewV1, body=body)
        if response.job_id != job_id:
            raise SpatialDataCoreClientError("INVALID_CORE_RESPONSE")
        return self._check_attempt(response.attempt)

    def renew(self, *, attempt: SpatialDataAttemptV1) -> SpatialDataAttemptV1:
        response = self._request(
            "POST",
            self._path(attempt.job_id, "renew"),
            SpatialDataLeaseViewV1,
            body=SpatialDataRenewRequestV1(attempt=attempt),
            attempt=attempt,
        )
        if response.attempt.fence_digest() != attempt.fence_digest():
            raise SpatialDataCoreClientError("FENCE_CONFLICT")
        return self._check_attempt(response.attempt)

    def input(self, *, attempt: SpatialDataAttemptV1) -> SpatialDataWorkerInputV1:
        response = self._request(
            "GET",
            self._path(attempt.job_id, "input"),
            SpatialDataWorkerInputResponseV1,
            attempt=attempt,
        )
        value = response.input
        if (
            value.attempt != attempt
            or value.activation != self._activation
            or value.job.policy != self._policy
            or value.runtime != self._runtime
            or value.source_capability.expires_at <= self._clock()
        ):
            raise SpatialDataCoreClientError("INVALID_CORE_RESPONSE")
        return value

    def output_upload(
        self, *, declaration: SpatialDataUploadDeclarationV1
    ) -> SpatialDataOutputUploadViewV1:
        response = self._request(
            "POST",
            self._path(declaration.attempt.job_id, "output-upload"),
            SpatialDataOutputUploadViewV1,
            body=SpatialDataOutputUploadRequestV1(declaration=declaration),
            attempt=declaration.attempt,
        )
        capability = response.capability
        parsed = urlsplit(capability.upload_url)
        if (
            response.upload_digest != declaration.upload_digest
            or capability.receipt_digest != declaration.receipt.receipt_digest
            or capability.sha256 != declaration.sha256
            or capability.size_bytes != declaration.size_bytes
            or capability.content_type != declaration.content_type
            or not self._clock()
            < capability.expires_at
            <= min(declaration.attempt.lease_until, self._activation.valid_until)
            or f"{parsed.scheme}://{parsed.netloc}" not in self._activation.trusted_endpoint_origins
        ):
            raise SpatialDataCoreClientError("INVALID_CORE_RESPONSE")
        return response

    def complete(
        self, *, attempt: SpatialDataAttemptV1, upload_digest: str
    ) -> SpatialDataJobViewV1:
        response = self._request(
            "POST",
            self._path(attempt.job_id, "complete"),
            SpatialDataWorkerMutationViewV1,
            attempt=attempt,
            body=SpatialDataCompleteRequestV1(attempt=attempt, upload_digest=upload_digest),
        )
        if response.job.job_id != attempt.job_id:
            raise SpatialDataCoreClientError("INVALID_CORE_RESPONSE")
        return response.job

    def failure(
        self, *, attempt: SpatialDataAttemptV1, reason: SpatialDataReasonV1
    ) -> SpatialDataJobViewV1:
        body = SpatialDataFailureRequestV1(
            attempt=attempt, reason=reason, retryable=reason in TRANSIENT_STORAGE_REASONS
        )
        response = self._request(
            "POST",
            self._path(attempt.job_id, "failure"),
            SpatialDataWorkerMutationViewV1,
            body=body,
            attempt=attempt,
        )
        if response.job.job_id != attempt.job_id:
            raise SpatialDataCoreClientError("INVALID_CORE_RESPONSE")
        return response.job
