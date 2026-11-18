"""단면 일꾼 전용 Core 전송. 분석 권한이나 객체 저장소 접근은 갖지 않는다.

HTTP 단계 제한과 응답 크기 제한은 전송 제어이며 호스트 격리의 증거가 아니다.
이 클라이언트와 bearer는 계산 단계에 전달되지 않는다.
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
from ksi_event_contracts.surface_profile import SurfaceProfileResultV1
from ksi_event_contracts.surface_profile_job import (
    SURFACE_PROFILE_ATTEMPT_DIGEST_HEADER,
    SURFACE_PROFILE_WORKER_INSTANCE_ID_HEADER,
    TRANSIENT_JOB_REASONS,
    SurfaceProfileActivationV1,
    SurfaceProfileAttemptV1,
    SurfaceProfileCompleteRequestV1,
    SurfaceProfileFailureRequestV1,
    SurfaceProfileJobReasonV1,
    SurfaceProfileJobViewV1,
    SurfaceProfileLeaseRequestV1,
    SurfaceProfileLeaseViewV1,
    SurfaceProfilePolicyV1,
    SurfaceProfileReceiptV1,
    SurfaceProfileRenewRequestV1,
    SurfaceProfileRuntimeV1,
    SurfaceProfileWorkerInputResponseV1,
    SurfaceProfileWorkerInputV1,
    SurfaceProfileWorkerPendingPageV1,
)
from pydantic import BaseModel

BASE = "/v1/internal/surface-profile-jobs"
_JOB = re.compile(r"spj-[0-9a-f]{32}\Z")


class SurfaceProfileCoreClientError(RuntimeError):
    """안전한 지역 사유만 담는다. 주소·본문·자격·예외 문구는 반사하지 않는다."""

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


class SurfaceProfileCoreClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        activation: SurfaceProfileActivationV1,
        policy: SurfaceProfilePolicyV1,
        runtime: SurfaceProfileRuntimeV1,
        clock: Callable[[], datetime],
        maximum_response_bytes: int,
        maximum_request_bytes: int,
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
            raise ValueError("명시적 보안 Core 주소, 시계, 별도 bearer가 필요하다")
        for value in (activation, policy, runtime):
            validated = type(value).model_validate(value.model_dump())
            if getattr(validated, validated._digest_field) != validated.canonical_digest():
                raise ValueError("봉인된 단면 권한 스냅샷이 필요하다")
        envelope = policy.resource_envelope
        if (
            activation.policy_digest != policy.policy_digest
            or activation.runtime_digest != runtime.runtime_digest
            or type(maximum_response_bytes) is not int
            or type(maximum_request_bytes) is not int
            or not policy.max_result_bytes < maximum_request_bytes <= envelope.max_input_bytes
            or not 0 < maximum_response_bytes <= envelope.max_input_bytes
            or type(request_timeout_seconds) not in (int, float)
            or not math.isfinite(request_timeout_seconds)
            or not 0 < request_timeout_seconds <= envelope.max_deadline_seconds
        ):
            raise ValueError("정확한 단면 권한과 유한한 응답·요청·시간 예산이 필요하다")
        self._activation = activation.model_copy(deep=True)
        self._policy = policy.model_copy(deep=True)
        self._runtime = runtime.model_copy(deep=True)
        self._clock = clock
        self._max_response = maximum_response_bytes
        self._max_request = maximum_request_bytes
        self._timeout = float(request_timeout_seconds)
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
            raise SurfaceProfileCoreClientError("INVALID_REQUEST")
        return BASE + "/" + job_id + "/" + tail

    def _check_attempt(self, attempt: SurfaceProfileAttemptV1) -> SurfaceProfileAttemptV1:
        try:
            attempt = SurfaceProfileAttemptV1.model_validate(attempt.model_dump())
            # acquired_at은 Core 시계가 찍는다. 일꾼 시계가 조금 뒤처져도 방금 받은 attempt를
            # 거부하지 않도록 상한만 지역에서 확인한다. 만료된 attempt는 Core가 매번 거부한다.
            if (
                attempt.attempt_digest != attempt.canonical_digest()
                or attempt.worker_instance_id != self._activation.worker_instance_id
                or attempt.worker_principal_id != self._activation.worker_principal_id
                or not self._clock() < attempt.lease_until
            ):
                raise ValueError("활성화된 일꾼의 현재 attempt가 아니다")
            return attempt
        except ValueError as exc:
            raise SurfaceProfileCoreClientError("FENCE_CONFLICT") from exc

    def _request(
        self,
        method: str,
        path: str,
        model: type[BaseModel],
        *,
        body: BaseModel | None = None,
        attempt: SurfaceProfileAttemptV1 | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        if not self._activation.is_current_at(self._clock()) or not self._token:
            raise SurfaceProfileCoreClientError("ACTIVATION_UNAVAILABLE")
        try:
            if self._authority_is_current is not None and self._authority_is_current() is not True:
                raise ValueError("현재 권한을 확인할 수 없다")
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
                raise ValueError("현재 자격을 확인할 수 없다")
        except Exception as exc:
            raise SurfaceProfileCoreClientError("ACTIVATION_UNAVAILABLE") from exc
        headers = {
            "Authorization": "Bearer " + token,
            SURFACE_PROFILE_WORKER_INSTANCE_ID_HEADER: self._activation.worker_instance_id,
            "Content-Type": "application/json",
            "Accept-Encoding": "identity",
        }
        if attempt is not None:
            headers[SURFACE_PROFILE_ATTEMPT_DIGEST_HEADER] = (
                self._check_attempt(attempt).attempt_digest or ""
            )
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
            if content is not None and len(content) > self._max_request:
                raise SurfaceProfileCoreClientError("RESOURCE_LIMIT_EXCEEDED")
            started = monotonic()
            self._client.cookies.clear()
            with self._client.stream(
                method, path, headers=headers, content=content, params=params
            ) as response:
                if response.status_code != 200:
                    raise SurfaceProfileCoreClientError("CORE_REQUEST_DENIED")
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise SurfaceProfileCoreClientError("INVALID_CORE_RESPONSE")
                payload = bytearray()
                for chunk in response.iter_bytes(chunk_size=min(65536, self._max_response)):
                    if monotonic() - started >= self._timeout:
                        raise SurfaceProfileCoreClientError("CORE_TIMEOUT")
                    if len(payload) + len(chunk) > self._max_response:
                        raise SurfaceProfileCoreClientError("RESOURCE_LIMIT_EXCEEDED")
                    payload.extend(chunk)
            if monotonic() - started >= self._timeout:
                raise SurfaceProfileCoreClientError("CORE_TIMEOUT")
            value = json.loads(
                payload.decode("utf-8", errors="strict"),
                object_pairs_hook=_pairs,
                parse_constant=_nonfinite,
            )
            return model.model_validate(value)
        except SurfaceProfileCoreClientError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise SurfaceProfileCoreClientError("CORE_UNAVAILABLE") from exc
        except (ValueError, TypeError, RecursionError) as exc:
            raise SurfaceProfileCoreClientError("INVALID_CORE_RESPONSE") from exc

    def pending(self, *, limit: int) -> tuple[str, ...]:
        if type(limit) is not int or not 1 <= limit <= self._policy.max_list_records:
            raise SurfaceProfileCoreClientError("INVALID_REQUEST")
        page = self._request(
            "GET", BASE, SurfaceProfileWorkerPendingPageV1, params={"limit": limit}
        )
        if len(page.items) > limit:
            raise SurfaceProfileCoreClientError("RESOURCE_LIMIT_EXCEEDED")
        return tuple(item.job_id for item in page.items)

    def lease(self, *, job_id: str, acquisition_id: str) -> SurfaceProfileAttemptV1:
        path = self._path(job_id, "lease")
        try:
            body = SurfaceProfileLeaseRequestV1(
                worker_instance_id=self._activation.worker_instance_id,
                acquisition_id=acquisition_id,
            )
        except ValueError as exc:
            raise SurfaceProfileCoreClientError("INVALID_REQUEST") from exc
        response = self._request("POST", path, SurfaceProfileLeaseViewV1, body=body)
        if response.job_id != job_id:
            raise SurfaceProfileCoreClientError("INVALID_CORE_RESPONSE")
        return self._check_attempt(response.attempt)

    def renew(self, *, attempt: SurfaceProfileAttemptV1) -> SurfaceProfileAttemptV1:
        response = self._request(
            "POST",
            self._path(attempt.job_id, "renew"),
            SurfaceProfileLeaseViewV1,
            body=SurfaceProfileRenewRequestV1(attempt=attempt),
            attempt=attempt,
        )
        if response.attempt.fence_digest() != attempt.fence_digest():
            raise SurfaceProfileCoreClientError("FENCE_CONFLICT")
        return self._check_attempt(response.attempt)

    def input(self, *, attempt: SurfaceProfileAttemptV1) -> SurfaceProfileWorkerInputV1:
        response = self._request(
            "GET",
            self._path(attempt.job_id, "input"),
            SurfaceProfileWorkerInputResponseV1,
            attempt=attempt,
        )
        value = response.input
        if (
            value.attempt != attempt
            or value.activation != self._activation
            or value.job.policy != self._policy
            or value.job.runtime != self._runtime
            or value.source_capability.expires_at <= self._clock()
        ):
            raise SurfaceProfileCoreClientError("INVALID_CORE_RESPONSE")
        return value

    def complete(
        self,
        *,
        attempt: SurfaceProfileAttemptV1,
        result: SurfaceProfileResultV1,
        receipt: SurfaceProfileReceiptV1,
    ) -> SurfaceProfileJobViewV1:
        response = self._request(
            "POST",
            self._path(attempt.job_id, "complete"),
            SurfaceProfileJobViewV1,
            attempt=attempt,
            body=SurfaceProfileCompleteRequestV1(attempt=attempt, result=result, receipt=receipt),
        )
        if response.job_id != attempt.job_id:
            raise SurfaceProfileCoreClientError("INVALID_CORE_RESPONSE")
        return response

    def failure(
        self, *, attempt: SurfaceProfileAttemptV1, reason: SurfaceProfileJobReasonV1
    ) -> SurfaceProfileJobViewV1:
        response = self._request(
            "POST",
            self._path(attempt.job_id, "failure"),
            SurfaceProfileJobViewV1,
            attempt=attempt,
            body=SurfaceProfileFailureRequestV1(
                attempt=attempt, reason=reason, retryable=reason in TRANSIENT_JOB_REASONS
            ),
        )
        if response.job_id != attempt.job_id:
            raise SurfaceProfileCoreClientError("INVALID_CORE_RESPONSE")
        return response
