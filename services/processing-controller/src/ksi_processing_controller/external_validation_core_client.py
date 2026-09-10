"""Fenced external-validation HTTP authority adapter (INV-051/053/060).

Capabilities never enter launcher models. This client neither parses rasters nor
imports Core runtime code. HTTP timeouts and response caps are transport controls;
they do not constitute host containment or a deadline guarantee for arbitrary IO.
"""

from __future__ import annotations

import base64
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from types import TracebackType
from typing import Any, Literal, Self
from urllib.parse import urlsplit

import httpx
from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import (
    ExternalArtifactInspectionReportV1,
    ExternalArtifactInspectionRequestV1,
    external_artifact_inspection_report_wire_dict,
)
from ksi_event_contracts.external_display_artifact import (
    SanitizedDisplayDeclarationV1,
    SanitizedDisplayReceiptV1,
    sanitized_display_declaration_wire_dict,
)
from pydantic import ConfigDict, Field, ValidationError, field_validator

from ksi_processing_controller.external_artifact_inspection_worker import (
    ExternalArtifactInputV1,
    ExternalInspectionCurrentInputV1,
    ExternalInspectionPhaseV1,
)
from ksi_processing_controller.external_inspector_protocol import (
    LocalLeaseFenceV1,
    ProtocolLimitsV1,
    ProtocolViolation,
    decode_json_frame,
)

_BASE = "/v1/internal/external-validation/inspections"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}\Z")
_FORBIDDEN_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie", "host"})
_FAILURE_REASON = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_SHA256_DIGEST = re.compile(r"sha256:([0-9a-f]{64})\Z")


class ExternalCoreClientError(RuntimeError):
    """Safe bounded error code; no server text, URLs, or bearer values."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _Wire(_CamelModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class PendingExternalInspectionV1(_Wire):
    request_id: str
    issued_at: datetime
    phase: Literal["INSPECTION", "DISPLAY"]

    @field_validator("issued_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("issuedAt must have a timezone")
        return value


class _PendingList(_Wire):
    items: tuple[PendingExternalInspectionV1, ...] = Field(max_length=100)


class ExternalInspectionLeaseV1(_Wire):
    verdict: Literal["LEASED", "IDEMPOTENT"]
    request: ExternalArtifactInspectionRequestV1
    lease_expires_at: datetime
    phase: Literal["INSPECTION", "DISPLAY"]
    fence: LocalLeaseFenceV1

    @field_validator("lease_expires_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("leaseExpiresAt must have a timezone")
        return value


class _IncompleteInspectionFailureV1(_Wire):
    reason: str

    @field_validator("reason", mode="before")
    @classmethod
    def bounded_reason(cls, value: object) -> str:
        if type(value) is not str or _FAILURE_REASON.fullmatch(value) is None:
            raise ValueError("reason must be a bounded uppercase failure code")
        return value


class ExternalInspectionFailureResultV1(_Wire):
    verdict: Literal["QUEUED"]
    report: None
    phase: Literal["INSPECTION"]


class _DisplayGrantResponse(_Wire):
    verdict: Literal["DECLARATION_RECORDED"]
    phase: Literal["QUEUED", "RUNNING"]
    declaration: SanitizedDisplayDeclarationV1
    upload_url: str
    required_headers: dict[str, str]


class _DisplaySealResponse(_Wire):
    verdict: Literal["SEALED"]
    phase: Literal["SEALED"]
    receipt: SanitizedDisplayReceiptV1


@dataclass(frozen=True, slots=True)
class ExternalObjectCapability:
    """Worker-private, exact input binding; repr excludes transient authority."""

    artifact: ExternalArtifactInputV1
    download_url: str = field(repr=False)
    required_headers: dict[str, str] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ExternalDisplayUploadCapability:
    """Private Core-issued derivative capability; only a later sink may use it."""

    declaration: SanitizedDisplayDeclarationV1
    upload_url: str = field(repr=False)
    required_headers: dict[str, str] = field(repr=False)


def _path_id(value: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ExternalCoreClientError("INVALID_RESOURCE_ID")
    return value


def _fence_headers(fence: LocalLeaseFenceV1) -> dict[str, str]:
    fence = LocalLeaseFenceV1.model_validate(fence)
    return {
        "X-KSI-Worker-Instance-Id": fence.worker_instance_id,
        "X-KSI-Lease-Acquisition-Id": fence.lease_acquisition_id,
        "X-KSI-Lease-Generation": str(fence.lease_generation),
    }


def _valid_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 16_384 or any(ord(c) <= 32 for c in value):
        raise ExternalCoreClientError("INVALID_STORAGE_CAPABILITY")
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError
        _ = parsed.port
    except ValueError:
        raise ExternalCoreClientError("INVALID_STORAGE_CAPABILITY") from None
    return value


def _private_headers(raw: object) -> dict[str, str]:
    if (
        type(raw) is not dict
        or len(raw) > 32
        or any(
            not isinstance(k, str)
            or not isinstance(v, str)
            or re.fullmatch(r"[A-Za-z0-9!#$%&'*+.^_`|~-]{1,128}", k) is None
            or k.lower() in _FORBIDDEN_HEADERS
            or len(v) > 8192
            or any(ord(c) < 32 or ord(c) > 126 for c in v)
            for k, v in raw.items()
        )
        or len({k.lower() for k in raw}) != len(raw)
    ):
        raise ExternalCoreClientError("INVALID_STORAGE_CAPABILITY")
    return dict(raw)


def _capability(raw: object) -> ExternalObjectCapability:
    if not isinstance(raw, dict) or set(raw) != {
        "entryId",
        "kind",
        "observedSha256",
        "observedSizeBytes",
        "contentType",
        "downloadUrl",
        "requiredHeaders",
    }:
        raise ExternalCoreClientError("INVALID_STORAGE_CAPABILITY")
    headers = _private_headers(raw["requiredHeaders"])
    artifact = ExternalArtifactInputV1.model_validate(
        {k: v for k, v in raw.items() if k not in {"downloadUrl", "requiredHeaders"}}
    )
    return ExternalObjectCapability(artifact, _valid_url(raw["downloadUrl"]), headers)


def _bound_display_upload_headers(
    declaration: SanitizedDisplayDeclarationV1, raw: object
) -> dict[str, str]:
    headers = _private_headers(raw)
    normalized = {name.lower(): value for name, value in headers.items()}
    match = _SHA256_DIGEST.fullmatch(declaration.declared_derivative_sha256)
    if match is None:
        raise ExternalCoreClientError("DISPLAY_CAPABILITY_BINDING_MISMATCH")
    s3_checksum = base64.b64encode(bytes.fromhex(match.group(1))).decode("ascii")
    if normalized.get(
        "content-type"
    ) != declaration.declared_derivative_content_type or normalized.get(
        "x-amz-checksum-sha256"
    ) not in {declaration.declared_derivative_sha256, s3_checksum}:
        raise ExternalCoreClientError("DISPLAY_CAPABILITY_BINDING_MISMATCH")
    return headers


class ExternalValidationCoreClient:
    """A private Core session, with no object-storage request facility.

    A byte-source adapter must select a capability by request AND fence AND the
    complete immutable artifact. It must use its own unauthenticated transport.
    """

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str,
        maximum_response_bytes: int = 262_144,
        request_timeout_seconds: float = 5.0,
        transport: httpx.BaseTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        origin = urlsplit(_valid_url(base_url))
        if origin.path not in {"", "/"} or origin.query:
            raise ValueError("Core base URL must be an origin")
        if (
            not bearer_token
            or bearer_token.strip() != bearer_token
            or any(ord(c) <= 32 or ord(c) > 126 for c in bearer_token)
        ):
            raise ValueError("Core bearer token is malformed")
        if (
            type(maximum_response_bytes) is not int
            or not 128 <= maximum_response_bytes <= 4_194_304
        ):
            raise ValueError("response byte cap is invalid")
        if (
            isinstance(request_timeout_seconds, bool)
            or not math.isfinite(request_timeout_seconds)
            or request_timeout_seconds <= 0
        ):
            raise ValueError("request timeout is invalid")
        self._maximum_response_bytes = maximum_response_bytes
        self._timeout = request_timeout_seconds
        self._monotonic = monotonic
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            headers={"Authorization": f"Bearer {bearer_token}", "Accept-Encoding": "identity"},
        )
        self._lock = RLock()
        self._pending_inputs: dict[tuple[str, LocalLeaseFenceV1], object] = {}
        self._closed = False
        self._capabilities: dict[
            tuple[str, LocalLeaseFenceV1], tuple[ExternalObjectCapability, ...]
        ] = {}
        self._display_inputs: dict[
            tuple[str, LocalLeaseFenceV1], ExternalInspectionCurrentInputV1
        ] = {}
        self._display_declarations: dict[
            tuple[str, LocalLeaseFenceV1], SanitizedDisplayDeclarationV1
        ] = {}
        self._pending_display: dict[tuple[str, LocalLeaseFenceV1], object] = {}

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._pending_inputs.clear()
            self._capabilities.clear()
            self._display_inputs.clear()
            self._display_declarations.clear()
            self._pending_display.clear()
        self._client.close()

    def _remaining(self, deadline: float) -> float:
        if isinstance(deadline, bool) or not math.isfinite(deadline):
            raise ExternalCoreClientError("INVALID_DEADLINE")
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise ExternalCoreClientError("DEADLINE_EXCEEDED")
        return min(self._timeout, remaining)

    def _request(
        self,
        method: str,
        path: str,
        *,
        deadline: float,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        accepted_statuses: tuple[int, ...] = (200,),
    ) -> dict[str, Any]:
        if (
            type(accepted_statuses) is not tuple
            or not 1 <= len(accepted_statuses) <= 4
            or any(
                type(status) is not int or not 100 <= status <= 599
                for status in accepted_statuses
            )
        ):
            raise ExternalCoreClientError("INVALID_ACCEPTED_STATUS")
        timeout = self._remaining(deadline)
        try:
            with self._client.stream(
                method, path, headers=headers, timeout=timeout, json=body
            ) as response:
                if response.status_code not in accepted_statuses:
                    raise ExternalCoreClientError(f"CORE_HTTP_{response.status_code}")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ExternalCoreClientError("ENCODED_CORE_RESPONSE")
                response_bytes = bytearray()
                for chunk in response.iter_bytes():
                    self._remaining(deadline)
                    if len(response_bytes) + len(chunk) > self._maximum_response_bytes:
                        raise ExternalCoreClientError("CORE_RESPONSE_LIMIT")
                    response_bytes.extend(chunk)
                self._remaining(deadline)
            return decode_json_frame(
                bytes(response_bytes),
                ProtocolLimitsV1(
                    max_header_bytes=self._maximum_response_bytes,
                    max_input_bytes=1,
                    max_output_bytes=1,
                    max_chunk_bytes=1,
                    max_wire_duration_millis=1,
                ),
            )
        except (
            httpx.HTTPError,
            ProtocolViolation,
            ValueError,
            TypeError,
            RecursionError,
            OverflowError,
        ):
            raise ExternalCoreClientError("INVALID_CORE_RESPONSE") from None

    def list_pending(
        self, *, deadline_monotonic: float, limit: int = 50
    ) -> tuple[PendingExternalInspectionV1, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ExternalCoreClientError("INVALID_QUEUE_LIMIT")
        try:
            return _PendingList.model_validate(
                self._request("GET", f"{_BASE}?limit={limit}", deadline=deadline_monotonic)
            ).items
        except ValidationError:
            raise ExternalCoreClientError("INVALID_CORE_RESPONSE") from None

    def claim(
        self,
        request_id: str,
        *,
        worker_instance_id: str,
        acquisition_id: str,
        deadline_monotonic: float,
    ) -> ExternalInspectionLeaseV1:
        try:
            proposed = LocalLeaseFenceV1(
                worker_instance_id=worker_instance_id,
                lease_acquisition_id=acquisition_id,
                lease_generation=1,
            )
            headers = {**_fence_headers(proposed), "X-KSI-Lease-Generation": "0"}
            lease = ExternalInspectionLeaseV1.model_validate(
                self._request(
                    "POST",
                    f"{_BASE}/{_path_id(request_id)}/lease",
                    deadline=deadline_monotonic,
                    headers=headers,
                )
            )
            if (
                lease.request.request_id != request_id
                or lease.fence.worker_instance_id != worker_instance_id
                or lease.fence.lease_acquisition_id != acquisition_id
            ):
                raise ExternalCoreClientError("LEASE_BINDING_MISMATCH")
            return lease
        except ValidationError:
            raise ExternalCoreClientError("INVALID_CORE_RESPONSE") from None

    def current_input(
        self, request_id: str, fence: LocalLeaseFenceV1, *, deadline_monotonic: float
    ) -> ExternalInspectionCurrentInputV1 | None:
        key = (request_id, fence)
        token = object()
        with self._lock:
            if (
                self._closed
                or len(
                    set(self._capabilities)
                    | set(self._pending_inputs)
                    | set(self._display_inputs)
                    | set(self._display_declarations)
                    | set(self._pending_display)
                    | {key}
                )
                > 32
            ):
                return None
            self._capabilities.pop(key, None)
            previous_display = self._display_inputs.pop(key, None)
            previous_declaration = self._display_declarations.pop(key, None)
            self._pending_display.pop(key, None)
            self._pending_inputs[key] = token
        try:
            body = self._request(
                "GET",
                f"{_BASE}/{_path_id(request_id)}/input",
                deadline=deadline_monotonic,
                headers=_fence_headers(fence),
            )
            if (
                set(body)
                != {
                    "verdict",
                    "request",
                    "policy",
                    "artifacts",
                    "phase",
                    "nextAction",
                    "acceptedReport",
                }
                or body["verdict"] != "LEASED"
                or not isinstance(body["artifacts"], list)
            ):
                raise ExternalCoreClientError("INVALID_CORE_RESPONSE")
            capabilities = tuple(_capability(raw) for raw in body["artifacts"])
            projection = ExternalInspectionCurrentInputV1.model_validate(
                {
                    **{k: v for k, v in body.items() if k not in {"verdict", "artifacts"}},
                    "artifacts": tuple(cap.artifact for cap in capabilities),
                }
            )
            if projection.request.request_id != request_id:
                raise ExternalCoreClientError("INPUT_BINDING_MISMATCH")
            if (
                projection.phase is ExternalInspectionPhaseV1.INSPECTION
                and projection.accepted_report is not None
            ) or (
                projection.phase is ExternalInspectionPhaseV1.DISPLAY
                and projection.accepted_report is None
            ):
                raise ExternalCoreClientError("INPUT_BINDING_MISMATCH")
            if projection.phase is ExternalInspectionPhaseV1.DISPLAY:
                accepted = projection.accepted_report
                if (
                    accepted is None
                    or accepted.request_id != projection.request.request_id
                    or accepted.subject != projection.request.subject
                    or accepted.inspection_policy_digest != projection.policy.policy_digest
                    or accepted.inspector_build_digest != projection.policy.parser_build_digest
                    or accepted.report_digest is None
                ):
                    raise ExternalCoreClientError("INPUT_BINDING_MISMATCH")
            with self._lock:
                if self._closed or self._pending_inputs.get(key) is not token:
                    return None
                self._capabilities[key] = capabilities
                if projection.phase is ExternalInspectionPhaseV1.DISPLAY:
                    self._display_inputs[key] = projection
                    # Polling refreshes capabilities, while an unchanged full
                    # DISPLAY projection retains the exact pending declaration.
                    # Changed/failed/released/overlapping fetches never restore it.
                    if previous_display == projection and previous_declaration is not None:
                        self._display_declarations[key] = previous_declaration
            return projection
        except (ExternalCoreClientError, ValidationError, TypeError):
            return None
        finally:
            with self._lock:
                if self._pending_inputs.get(key) is token:
                    self._pending_inputs.pop(key, None)

    def heartbeat(
        self, request_id: str, fence: LocalLeaseFenceV1, *, deadline_monotonic: float
    ) -> bool:
        try:
            lease = ExternalInspectionLeaseV1.model_validate(
                self._request(
                    "POST",
                    f"{_BASE}/{_path_id(request_id)}/heartbeat",
                    deadline=deadline_monotonic,
                    headers=_fence_headers(fence),
                )
            )
            if lease.request.request_id == request_id and lease.fence == fence:
                return True
        except (ExternalCoreClientError, ValidationError):
            pass
        with self._lock:
            self._pending_inputs.pop((request_id, fence), None)
            self._capabilities.pop((request_id, fence), None)
            self._display_inputs.pop((request_id, fence), None)
            self._display_declarations.pop((request_id, fence), None)
            self._pending_display.pop((request_id, fence), None)
        return False

    def capability_for(
        self, request_id: str, fence: LocalLeaseFenceV1, artifact: ExternalArtifactInputV1
    ) -> ExternalObjectCapability:
        with self._lock:
            candidates = self._capabilities.get((request_id, fence), ())
            matching = [item for item in candidates if item.artifact == artifact]
            if len(matching) != 1:
                raise ExternalCoreClientError("INPUT_CAPABILITY_UNAVAILABLE")
            item = matching[0]
            return ExternalObjectCapability(
                item.artifact, item.download_url, dict(item.required_headers)
            )

    def release(self, request_id: str, fence: LocalLeaseFenceV1) -> None:
        """Drop transient capabilities when the caller finishes or cancels an attempt."""
        with self._lock:
            self._pending_inputs.pop((request_id, fence), None)
            self._capabilities.pop((request_id, fence), None)
            self._display_inputs.pop((request_id, fence), None)
            self._display_declarations.pop((request_id, fence), None)
            self._pending_display.pop((request_id, fence), None)

    def record_incomplete_failure(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        reason: str,
        *,
        deadline_monotonic: float,
    ) -> ExternalInspectionFailureResultV1:
        """Record one typed incomplete attempt, then drop its now-consumed authority."""
        try:
            failure = _IncompleteInspectionFailureV1(reason=reason)
        except ValidationError:
            raise ExternalCoreClientError("INVALID_FAILURE_REASON") from None
        try:
            response = ExternalInspectionFailureResultV1.model_validate(
                self._request(
                    "POST",
                    f"{_BASE}/{_path_id(request_id)}/incomplete-failure",
                    deadline=deadline_monotonic,
                    headers=_fence_headers(fence),
                    body=failure.model_dump(by_alias=True, mode="json"),
                )
            )
            return response
        except ValidationError:
            raise ExternalCoreClientError("INVALID_CORE_RESPONSE") from None
        finally:
            self.release(request_id, fence)

    def _start_display_operation(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        declaration: SanitizedDisplayDeclarationV1 | None = None,
    ) -> tuple[tuple[str, LocalLeaseFenceV1], ExternalInspectionCurrentInputV1, object]:
        key = (request_id, fence)
        with self._lock:
            current = self._display_inputs.get(key)
            existing = self._display_declarations.get(key)
            if self._closed or current is None:
                raise ExternalCoreClientError("DISPLAY_AUTHORITY_UNAVAILABLE")
            if declaration is not None and existing is not None and existing != declaration:
                raise ExternalCoreClientError("DISPLAY_DECLARATION_DIVERGENCE")
            if key in self._pending_display:
                raise ExternalCoreClientError("DISPLAY_OPERATION_PENDING")
            token = object()
            self._pending_display[key] = token
            return key, current, token

    def _finish_display_operation(self, key: tuple[str, LocalLeaseFenceV1], token: object) -> None:
        with self._lock:
            if self._pending_display.get(key) is token:
                self._pending_display.pop(key, None)

    @staticmethod
    def _bound_display_declaration(
        request_id: str,
        current: ExternalInspectionCurrentInputV1,
        declaration: SanitizedDisplayDeclarationV1,
    ) -> SanitizedDisplayDeclarationV1:
        try:
            sealed = SanitizedDisplayDeclarationV1.model_validate(declaration).sealed()
        except ValidationError:
            raise ExternalCoreClientError("INVALID_DISPLAY_DECLARATION") from None
        report = current.accepted_report
        if (
            current.phase is not ExternalInspectionPhaseV1.DISPLAY
            or report is None
            or report.report_digest is None
            or sealed.request_id != request_id
            or sealed.source_subject_digest != report.subject_digest
            or sealed.source_report_digest != report.report_digest
            or sealed.policy_digest != current.policy.policy_digest
            or sealed.inspector_build_digest != current.policy.parser_build_digest
        ):
            raise ExternalCoreClientError("DISPLAY_BINDING_MISMATCH")
        return sealed

    def grant_display_upload(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        declaration: SanitizedDisplayDeclarationV1,
        *,
        deadline_monotonic: float,
    ) -> ExternalDisplayUploadCapability:
        """Record one exact display declaration and receive its private upload authority."""
        key, current, token = self._start_display_operation(request_id, fence)
        try:
            sealed = self._bound_display_declaration(request_id, current, declaration)
            with self._lock:
                existing = self._display_declarations.get(key)
                if existing is not None and existing != sealed:
                    raise ExternalCoreClientError("DISPLAY_DECLARATION_DIVERGENCE")
            response = _DisplayGrantResponse.model_validate(
                self._request(
                    "POST",
                    f"{_BASE}/{_path_id(request_id)}/display-artifacts/upload-grants",
                    deadline=deadline_monotonic,
                    headers=_fence_headers(fence),
                    body=sanitized_display_declaration_wire_dict(sealed),
                )
            )
            response_declaration = response.declaration.sealed()
            if response.declaration.declaration_digest is None or response_declaration != sealed:
                raise ExternalCoreClientError("DISPLAY_DECLARATION_MISMATCH")
            capability = ExternalDisplayUploadCapability(
                sealed,
                _valid_url(response.upload_url),
                _bound_display_upload_headers(sealed, response.required_headers),
            )
            with self._lock:
                if (
                    self._closed
                    or self._pending_display.get(key) is not token
                    or self._display_inputs.get(key) != current
                ):
                    raise ExternalCoreClientError("DISPLAY_AUTHORITY_UNAVAILABLE")
                self._display_declarations[key] = sealed
            return capability
        except ValidationError:
            raise ExternalCoreClientError("INVALID_CORE_RESPONSE") from None
        finally:
            self._finish_display_operation(key, token)

    def seal_display_upload(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        grant: ExternalDisplayUploadCapability,
        *,
        deadline_monotonic: float,
    ) -> SanitizedDisplayReceiptV1:
        """Return Core's receipt only after it observes the exact declared derivative."""
        if not isinstance(grant, ExternalDisplayUploadCapability):
            raise ExternalCoreClientError("DISPLAY_DECLARATION_UNAVAILABLE")
        key, current, token = self._start_display_operation(request_id, fence, grant.declaration)
        try:
            declaration = self._bound_display_declaration(request_id, current, grant.declaration)
            with self._lock:
                if self._display_declarations.get(key) != declaration:
                    raise ExternalCoreClientError("DISPLAY_DECLARATION_UNAVAILABLE")
            response = _DisplaySealResponse.model_validate(
                self._request(
                    "POST",
                    f"{_BASE}/{_path_id(request_id)}/display-artifacts/"
                    f"{_path_id(declaration.display_id)}/seal",
                    deadline=deadline_monotonic,
                    headers=_fence_headers(fence),
                )
            )
            receipt = response.receipt
            if (
                receipt.receipt_digest is None
                or receipt != receipt.sealed()
                or receipt.display_id != declaration.display_id
                or receipt.request_id != request_id
                or receipt.declaration_digest != declaration.declaration_digest
                or receipt.source_subject_digest != declaration.source_subject_digest
                or receipt.source_report_digest != declaration.source_report_digest
                or receipt.policy_digest != declaration.policy_digest
                or receipt.inspector_build_digest != declaration.inspector_build_digest
                or receipt.observed_derivative_sha256 != declaration.declared_derivative_sha256
                or receipt.observed_derivative_size_bytes
                != declaration.declared_derivative_size_bytes
                or receipt.observed_derivative_content_type
                != declaration.declared_derivative_content_type
            ):
                raise ExternalCoreClientError("DISPLAY_RECEIPT_MISMATCH")
            with self._lock:
                if (
                    self._closed
                    or self._pending_display.get(key) is not token
                    or self._display_inputs.get(key) != current
                    or self._display_declarations.get(key) != declaration
                ):
                    raise ExternalCoreClientError("DISPLAY_AUTHORITY_UNAVAILABLE")
                self._capabilities.pop(key, None)
                self._display_inputs.pop(key, None)
                self._display_declarations.pop(key, None)
            return receipt
        except ValidationError:
            raise ExternalCoreClientError("INVALID_CORE_RESPONSE") from None
        finally:
            self._finish_display_operation(key, token)

    def record_report(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        report: ExternalArtifactInspectionReportV1,
        *,
        deadline_monotonic: float,
    ) -> ExternalArtifactInspectionReportV1:
        try:
            report = ExternalArtifactInspectionReportV1.model_validate(report).sealed()
            if (
                report.request_id != request_id
                or report.worker_instance_id != fence.worker_instance_id
                or report.lease_acquisition_id != fence.lease_acquisition_id
                or report.lease_generation != fence.lease_generation
            ):
                raise ExternalCoreClientError("REPORT_BINDING_MISMATCH")
            response = self._request(
                "POST",
                f"{_BASE}/{_path_id(request_id)}/report",
                deadline=deadline_monotonic,
                headers=_fence_headers(fence),
                body=external_artifact_inspection_report_wire_dict(report),
            )
            if (
                set(response) != {"verdict", "report", "phase"}
                or response["verdict"] not in {"REPORTED", "IDEMPOTENT"}
                or response["phase"] not in {"DISPLAY", "COMPLETE"}
            ):
                raise ExternalCoreClientError("INVALID_CORE_RESPONSE")
            retained = ExternalArtifactInspectionReportV1.model_validate(response["report"])
            if retained != report:
                raise ExternalCoreClientError("REPORT_ECHO_MISMATCH")
            return retained
        except ValidationError:
            raise ExternalCoreClientError("INVALID_CORE_RESPONSE") from None
