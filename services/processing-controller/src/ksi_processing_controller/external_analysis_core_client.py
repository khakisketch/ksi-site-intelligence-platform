"""Bounded authenticated HTTP client for the local Analysis worker routes.

This module owns only the six internal worker calls.  Object capabilities are
kept inside validated input responses and are consumed by the separate object
transport; they are never logged or exposed through this client API.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import re
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlsplit

import httpx
from ksi_event_contracts.external_analysis_worker import (
    ANALYSIS_ATTEMPT_DIGEST_HEADER,
    ANALYSIS_WORKER_INSTANCE_ID_HEADER,
    AnalysisWorkerFailureRequestV1,
    AnalysisWorkerInputResponseV1,
    AnalysisWorkerLeaseRequestV1,
    AnalysisWorkerLeaseViewV1,
    AnalysisWorkerMutationViewV1,
    AnalysisWorkerPendingItemV1,
    AnalysisWorkerPendingListV1,
    AnalysisWorkerRenewRequestV1,
    AnalysisWorkerReportRequestV1,
)
from ksi_event_contracts.external_relative_volume_calculation import (
    AnalysisExecutionAttemptV2,
    RelativeVolumeCalculationFailureV2,
    RelativeVolumeCalculationReportV2,
)
from pydantic import ValidationError

_BASE = "v1/internal/analysis-jobs"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}\Z")


class ExternalAnalysisCoreClientError(RuntimeError):
    """Safe error code: never contains a bearer token, URL, or server text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _resource_id(value: object) -> str:
    if type(value) is not str or _SAFE_ID.fullmatch(value) is None:
        raise ExternalAnalysisCoreClientError("INVALID_RESOURCE_ID")
    return value


def _trusted_base_url(value: object) -> str:
    if type(value) is not str or not value or len(value) > 16_384:
        raise ValueError("Core base URL is malformed")
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(ord(character) <= 32 for character in value)
        ):
            raise ValueError
        _ = parsed.port
        address = ipaddress.ip_address(parsed.hostname)
        if "%" in parsed.hostname or getattr(address, "scope_id", None) is not None:
            raise ValueError
        if parsed.scheme == "http" and not address.is_loopback:
            raise ValueError
        if any(segment in {"", ".", ".."} for segment in parsed.path.split("/")[1:]):
            raise ValueError
    except ValueError:
        raise ValueError(
            "Core base URL must use an explicit trusted literal IP HTTP(S) origin"
        ) from None
    return value.rstrip("/")


def _token(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(ord(character) <= 32 or ord(character) > 126 for character in value)
    ):
        raise ValueError("worker token is malformed")
    return value


class ExternalAnalysisCoreClient:
    """A caller-owned local worker session with explicit bounded HTTP behavior."""

    def __init__(
        self,
        *,
        base_url: str,
        worker_token: str,
        worker_instance_id: str,
        maximum_response_bytes: int = 262_144,
        request_timeout_seconds: float = 5.0,
    ) -> None:
        trusted_url = _trusted_base_url(base_url)
        self._worker_instance_id = _resource_id(worker_instance_id)
        if (
            type(maximum_response_bytes) is not int
            or not 128 <= maximum_response_bytes <= 4_194_304
        ):
            raise ValueError("Core response byte cap is invalid")
        if (
            isinstance(request_timeout_seconds, bool)
            or not math.isfinite(request_timeout_seconds)
            or not 0 < request_timeout_seconds <= 120
        ):
            raise ValueError("Core request timeout is invalid")
        self._maximum_response_bytes = maximum_response_bytes
        self._timeout = request_timeout_seconds
        self._base_url = trusted_url + "/"
        self._headers = {
            "Authorization": "Bearer " + _token(worker_token),
            "Accept-Encoding": "identity",
        }
        self._calculation_ids: dict[str, str] = {}
        self._closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def worker_instance_id(self) -> str:
        return self._worker_instance_id

    @property
    def request_timeout_seconds(self) -> float:
        return self._timeout

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._calculation_ids.clear()

    def _require_open(self) -> None:
        if self._closed:
            raise ExternalAnalysisCoreClientError("CLIENT_CLOSED")

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_open()
        try:
            raw = asyncio.run(self._request_bytes(method, path, headers=headers, body=body))
        except TimeoutError:
            raise ExternalAnalysisCoreClientError("CORE_HTTP_TIMEOUT") from None
        except httpx.TimeoutException:
            raise ExternalAnalysisCoreClientError("CORE_HTTP_TIMEOUT") from None
        except httpx.HTTPError:
            raise ExternalAnalysisCoreClientError("CORE_HTTP_UNAVAILABLE") from None
        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ExternalAnalysisCoreClientError("INVALID_CORE_RESPONSE") from None
        if type(decoded) is not dict:
            raise ExternalAnalysisCoreClientError("INVALID_CORE_RESPONSE")
        return decoded

    async def _request_bytes(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None,
        body: dict[str, Any] | None,
    ) -> bytes:
        async with asyncio.timeout(self._timeout):
            async with httpx.AsyncClient(
                base_url=self._base_url,
                trust_env=False,
                follow_redirects=False,
                headers=self._headers,
            ) as client:
                async with client.stream(
                    method,
                    path,
                    headers=headers,
                    json=body,
                    timeout=None,
                ) as response:
                    if response.status_code != 200:
                        raise ExternalAnalysisCoreClientError(f"CORE_HTTP_{response.status_code}")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise ExternalAnalysisCoreClientError("ENCODED_CORE_RESPONSE")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > self._maximum_response_bytes:
                            raise ExternalAnalysisCoreClientError("CORE_RESPONSE_LIMIT")
                        raw.extend(chunk)
                    return bytes(raw)

    def list_pending(self) -> tuple[AnalysisWorkerPendingItemV1, ...]:
        try:
            return AnalysisWorkerPendingListV1.model_validate(
                self._request("GET", _BASE)
            ).items
        except ValidationError:
            raise ExternalAnalysisCoreClientError("INVALID_CORE_RESPONSE") from None

    def lease(
        self, analysis_id: str, lease_acquisition_id: str
    ) -> AnalysisWorkerLeaseViewV1:
        analysis_id = _resource_id(analysis_id)
        try:
            request = AnalysisWorkerLeaseRequestV1(
                worker_instance_id=self._worker_instance_id,
                lease_acquisition_id=lease_acquisition_id,
            )
            response = AnalysisWorkerLeaseViewV1.model_validate(
                self._request(
                    "POST",
                    f"{_BASE}/{analysis_id}:lease",
                    body=request.model_dump(by_alias=True, mode="json"),
                )
            )
        except ValidationError:
            raise ExternalAnalysisCoreClientError("INVALID_CORE_RESPONSE") from None
        if (
            response.analysis_id != analysis_id
            or response.attempt.worker_instance_id != self._worker_instance_id
            or response.attempt.lease_acquisition_id != lease_acquisition_id
        ):
            raise ExternalAnalysisCoreClientError("LEASE_BINDING_MISMATCH")
        self._calculation_ids[analysis_id] = response.calculation_request_id
        return response

    def input(
        self, analysis_id: str, attempt: AnalysisExecutionAttemptV2
    ) -> AnalysisWorkerInputResponseV1:
        analysis_id = _resource_id(analysis_id)
        attempt = AnalysisExecutionAttemptV2.model_validate(attempt)
        try:
            response = AnalysisWorkerInputResponseV1.model_validate(
                self._request(
                    "GET",
                    f"{_BASE}/{analysis_id}/input",
                    headers={
                        ANALYSIS_ATTEMPT_DIGEST_HEADER: attempt.canonical_digest(),
                        ANALYSIS_WORKER_INSTANCE_ID_HEADER: self._worker_instance_id,
                    },
                )
            )
        except ValidationError:
            raise ExternalAnalysisCoreClientError("INVALID_CORE_RESPONSE") from None
        input_value = response.input
        expected_calculation_id = self._calculation_ids.get(analysis_id)
        if (
            input_value.analysis_id != analysis_id
            or input_value.attempt != attempt
            or input_value.attempt.worker_instance_id != self._worker_instance_id
            or (
                expected_calculation_id is not None
                and input_value.calculation_request_id != expected_calculation_id
            )
        ):
            raise ExternalAnalysisCoreClientError("INPUT_BINDING_MISMATCH")
        self._calculation_ids[analysis_id] = input_value.calculation_request_id
        return response

    def renew(
        self, analysis_id: str, attempt: AnalysisExecutionAttemptV2
    ) -> AnalysisWorkerLeaseViewV1:
        analysis_id = _resource_id(analysis_id)
        attempt = AnalysisExecutionAttemptV2.model_validate(attempt)
        try:
            request = AnalysisWorkerRenewRequestV1(attempt=attempt)
            response = AnalysisWorkerLeaseViewV1.model_validate(
                self._request(
                    "POST",
                    f"{_BASE}/{analysis_id}:renew",
                    body=request.model_dump(by_alias=True, mode="json"),
                )
            )
        except ValidationError:
            raise ExternalAnalysisCoreClientError("INVALID_CORE_RESPONSE") from None
        renewed = response.attempt
        expected_calculation_id = self._calculation_ids.get(analysis_id)
        if (
            response.analysis_id != analysis_id
            or (
                expected_calculation_id is not None
                and response.calculation_request_id != expected_calculation_id
            )
            or renewed.authorization != attempt.authorization
            or renewed.authorization_digest != attempt.authorization_digest
            or renewed.worker_instance_id != self._worker_instance_id
            or renewed.worker_instance_id != attempt.worker_instance_id
            or renewed.lease_acquisition_id != attempt.lease_acquisition_id
            or renewed.lease_generation != attempt.lease_generation
        ):
            raise ExternalAnalysisCoreClientError("RENEW_BINDING_MISMATCH")
        self._calculation_ids[analysis_id] = response.calculation_request_id
        return response

    def report(self, analysis_id: str, report: RelativeVolumeCalculationReportV2) -> None:
        analysis_id = _resource_id(analysis_id)
        report = RelativeVolumeCalculationReportV2.model_validate(report)
        try:
            mutation = AnalysisWorkerMutationViewV1.model_validate(
                self._request(
                    "POST",
                    f"{_BASE}/{analysis_id}:report",
                    body=AnalysisWorkerReportRequestV1(report=report).model_dump(
                        by_alias=True, mode="json"
                    ),
                )
            )
        except ValidationError:
            raise ExternalAnalysisCoreClientError("INVALID_CORE_RESPONSE") from None
        self._require_terminal_mutation(analysis_id, mutation, report.attempt, "COMPLETED")
        self._calculation_ids.pop(analysis_id, None)

    def failure(self, analysis_id: str, failure: RelativeVolumeCalculationFailureV2) -> None:
        analysis_id = _resource_id(analysis_id)
        failure = RelativeVolumeCalculationFailureV2.model_validate(failure)
        try:
            mutation = AnalysisWorkerMutationViewV1.model_validate(
                self._request(
                    "POST",
                    f"{_BASE}/{analysis_id}:failure",
                    body=AnalysisWorkerFailureRequestV1(failure=failure).model_dump(
                        by_alias=True, mode="json"
                    ),
                )
            )
        except ValidationError:
            raise ExternalAnalysisCoreClientError("INVALID_CORE_RESPONSE") from None
        self._require_terminal_mutation(analysis_id, mutation, failure.attempt, "FAILED")
        self._calculation_ids.pop(analysis_id, None)

    def _require_terminal_mutation(
        self,
        analysis_id: str,
        mutation: AnalysisWorkerMutationViewV1,
        attempt: AnalysisExecutionAttemptV2,
        expected_state: str,
    ) -> None:
        expected_calculation_id = self._calculation_ids.get(analysis_id)
        if (
            mutation.analysis_id != analysis_id
            or mutation.execution_state != expected_state
            or (
                expected_calculation_id is not None
                and mutation.calculation_request_id != expected_calculation_id
            )
            or mutation.attempt != attempt
        ):
            raise ExternalAnalysisCoreClientError("TERMINAL_BINDING_MISMATCH")


__all__ = ["ExternalAnalysisCoreClient", "ExternalAnalysisCoreClientError"]
