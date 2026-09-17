"""Closed Core HTTP adapter for V2 measurement work (INV-024/051/053/060).

The injected validation client owns one bounded bearer session.  This adapter
owns only its lane/request/fence capability cache, never a Core runtime import,
object byte transport, or the injected client's lifecycle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from types import TracebackType
from typing import Any, Literal, Self, cast

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import Digest, ExternalValidationPolicyV1
from ksi_event_contracts.external_evidence import (
    ExternalEvidenceMeasurementPayloadV1,
    ExternalEvidenceRecordV1,
    ExternalEvidenceValidationRequestV1,
)
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1
from ksi_event_contracts.external_relative_volume import (
    ExternalRelativeVolumeExecutionPolicyV1,
    ExternalRelativeVolumeMeasurementPayloadV1,
    ExternalRelativeVolumeRequestV1,
)
from ksi_event_contracts.external_single_volume import (
    ExternalSingleVolumeExecutionPolicyV1,
    ExternalSingleVolumeMeasurementPayloadV1,
    ExternalSingleVolumeRequestV1,
)
from ksi_event_contracts.inspector_execution_manifest import InspectorExecutionManifestV1
from pydantic import ConfigDict, Field, StrictInt, ValidationError, field_validator

from ksi_processing_controller.external_inspector_protocol import (
    LocalLeaseFenceV1,
    ProtocolLimitsV1,
)
from ksi_processing_controller.external_measurement_protocol import (
    MeasurementInputV2,
    MeasurementLaunchRequestV2,
)
from ksi_processing_controller.external_measurement_result import (
    CheckpointAggregateV2,
    MeasurementResultV2,
    RelativeVolumeAggregateV2,
    SingleVolumeAggregateV2,
)
from ksi_processing_controller.external_object_streams import ExternalObjectCapabilityV1
from ksi_processing_controller.external_validation_core_client import (
    ExternalCoreClientError,
    ExternalValidationCoreClient,
)

MeasurementOperationV2 = Literal["CHECKPOINT_VALIDATION", "RELATIVE_VOLUME", "SINGLE_VOLUME"]
_EVIDENCE_BASE = "/v1/internal/external-validation/evidence-validations"
_VOLUME_BASE = "/v1/internal/external-validation/relative-volumes"
_SINGLE_VOLUME_BASE = "/v1/internal/external-validation/single-volumes"
_VOLUME_BASES: dict[str, str] = {
    "RELATIVE_VOLUME": _VOLUME_BASE,
    "SINGLE_VOLUME": _SINGLE_VOLUME_BASE,
}
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}\Z")
_FAILURE_REASON = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_MAX_CACHE_KEYS = 32


class ExternalMeasurementCoreClientError(RuntimeError):
    """Safe adapter failure code with no Core text, capability, or bearer value."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _Wire(_CamelModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class _VolumePendingItem(_Wire):
    request_ref: str
    issued_at: datetime

    @field_validator("issued_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _aware(value)


class _PendingList(_Wire):
    items: tuple[_VolumePendingItem, ...] = Field(max_length=200)


class _EvidencePendingItem(_Wire):
    validation_id: str
    issued_at: datetime

    @field_validator("issued_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _aware(value)


class _EvidencePendingList(_Wire):
    items: tuple[_EvidencePendingItem, ...] = Field(max_length=100)


class _LeaseResponse(_Wire):
    verdict: Literal["LEASED", "LEASE_RENEWED"]
    fence: LocalLeaseFenceV1
    lease_expires_at: datetime

    @field_validator("lease_expires_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _aware(value)


class _EvidenceLeaseResponse(_LeaseResponse):
    request: ExternalEvidenceValidationRequestV1


class _VolumeRequestView(_Wire):
    request_ref: str
    status: str
    current_work_order_id: str
    decision_digest: str
    issued_at: datetime
    deadline_at: datetime
    report_ref: str | None = None
    report_digest: str | None = None

    @field_validator("issued_at", "deadline_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _aware(value)


class _VolumeLeaseResponse(_LeaseResponse):
    request: _VolumeRequestView
    detail: str | None = None


class _CapabilityWire(_Wire):
    role: Literal["TARGET_DSM", "CHECKPOINT_CSV", "BASELINE_DSM", "CURRENT_DSM"]
    artifact_id: str | None = None
    observed_sha256: str | None = None
    observed_size_bytes: StrictInt | None = None
    content_type: str | None = None
    download_url: str
    required_headers: dict[str, str]
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def _aware_optional(cls, value: datetime | None) -> datetime | None:
        return _aware(value) if value is not None else None


class _VolumeWorkerInput(_Wire):
    request: ExternalRelativeVolumeRequestV1
    execution_policy: ExternalRelativeVolumeExecutionPolicyV1
    validation_policy: ExternalValidationPolicyV1
    volume_evidence_records: tuple[ExternalEvidenceRecordV1, ExternalEvidenceRecordV1]
    inputs: tuple[_CapabilityWire, _CapabilityWire]


class _VolumeInputResponse(_Wire):
    verdict: Literal["INPUT_READY"]
    input: _VolumeWorkerInput
    detail: str | None = None


class _SingleVolumeWorkerInput(_Wire):
    request: ExternalSingleVolumeRequestV1
    execution_policy: ExternalSingleVolumeExecutionPolicyV1
    validation_policy: ExternalValidationPolicyV1
    evidence_record: ExternalEvidenceRecordV1
    inputs: tuple[_CapabilityWire, _CapabilityWire]


class _SingleVolumeInputResponse(_Wire):
    verdict: Literal["INPUT_READY"]
    input: _SingleVolumeWorkerInput
    detail: str | None = None


class _EvidenceInputResponse(_Wire):
    verdict: Literal["LEASED"]
    request: ExternalEvidenceValidationRequestV1
    context: ExternalEvidenceMeasurementContextV1
    validation_policy: ExternalValidationPolicyV1
    bindings: tuple[_CapabilityWire, _CapabilityWire]


class _EvidenceTerminalResponse(_Wire):
    verdict: Literal["VALIDATED", "REJECTED"]
    record: ExternalEvidenceRecordV1 | None = None


class _EvidenceMeasurementTerminalResponse(_Wire):
    """A completed checkpoint measurement must return its sealed Core record."""

    verdict: Literal["VALIDATED", "REJECTED"]
    record: ExternalEvidenceRecordV1


class _VolumeReportedRequestView(_Wire):
    """The report endpoint's success projection, with an explicit report identity."""

    request_ref: str
    status: Literal["SUCCEEDED"]
    current_work_order_id: str
    decision_digest: Digest
    issued_at: datetime
    deadline_at: datetime
    report_ref: str
    report_digest: Digest

    @field_validator("issued_at", "deadline_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        return _aware(value)


class _VolumeReportedTerminalResponse(_Wire):
    """A completed volume report must return the matching Core request projection."""

    verdict: Literal["REPORTED"]
    request: _VolumeReportedRequestView
    fence: LocalLeaseFenceV1 | None = None
    lease_expires_at: datetime | None = None
    detail: str | None = None

    @field_validator("lease_expires_at")
    @classmethod
    def _aware_optional(cls, value: datetime | None) -> datetime | None:
        return _aware(value) if value is not None else None


class _VolumeTerminalResponse(_Wire):
    verdict: Literal["REPORTED", "FAILED"]
    request: _VolumeRequestView | None = None
    fence: LocalLeaseFenceV1 | None = None
    lease_expires_at: datetime | None = None
    detail: str | None = None

    @field_validator("lease_expires_at")
    @classmethod
    def _aware_optional(cls, value: datetime | None) -> datetime | None:
        return _aware(value) if value is not None else None


@dataclass(frozen=True, slots=True)
class PendingMeasurementWorkV1:
    operation: MeasurementOperationV2
    request_id: str
    issued_at: datetime


@dataclass(frozen=True, slots=True)
class MeasurementLeaseGrantV1:
    operation: MeasurementOperationV2
    request_id: str
    fence: LocalLeaseFenceV1
    lease_expires_at: datetime


_CacheKey = tuple[MeasurementOperationV2, str, LocalLeaseFenceV1]


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must have a timezone")
    return value


def _operation(value: str) -> MeasurementOperationV2:
    if value not in {"CHECKPOINT_VALIDATION", "RELATIVE_VOLUME", "SINGLE_VOLUME"}:
        raise ExternalMeasurementCoreClientError("INVALID_MEASUREMENT_OPERATION")
    return cast(MeasurementOperationV2, value)


def _request_id(value: str) -> str:
    if type(value) is not str or _SAFE_ID.fullmatch(value) is None:
        raise ExternalMeasurementCoreClientError("INVALID_RESOURCE_ID")
    return value


def _fence_headers(fence: LocalLeaseFenceV1) -> dict[str, str]:
    return {
        "X-KSI-Worker-Instance-Id": fence.worker_instance_id,
        "X-KSI-Lease-Acquisition-Id": fence.lease_acquisition_id,
        "X-KSI-Lease-Generation": str(fence.lease_generation),
    }


class ExternalMeasurementCoreClient:
    """Maps current Core worker bodies into exact V2 launches and observations.

    The injected ``ExternalValidationCoreClient`` remains caller-owned.  Closing
    this adapter clears its own authority cache only, so inspection/display
    lanes can continue to use the shared bounded bearer transport.
    """

    def __init__(self, *, core_client: ExternalValidationCoreClient) -> None:
        if not isinstance(core_client, ExternalValidationCoreClient):
            raise TypeError("measurement client requires the bounded validation Core client")
        self._core = core_client
        self._lock = RLock()
        self._capabilities: dict[_CacheKey, tuple[ExternalObjectCapabilityV1, ...]] = {}
        self._attempt_tokens: dict[_CacheKey, object] = {}
        self._pending: dict[_CacheKey, object] = {}
        self._terminals: dict[_CacheKey, tuple[object, object]] = {}
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

    def close(self) -> None:
        """Clear only this adapter's transient authority; never close injected Core IO."""
        with self._lock:
            self._closed = True
            self._capabilities.clear()
            self._attempt_tokens.clear()
            self._pending.clear()
            self._terminals.clear()

    def _require_open(self) -> None:
        with self._lock:
            if self._closed:
                raise ExternalMeasurementCoreClientError("CLIENT_CLOSED")

    def _begin_terminal(
        self, operation: MeasurementOperationV2, request_id: str, fence: LocalLeaseFenceV1
    ) -> tuple[_CacheKey, object, object]:
        """Atomically bind a terminal mutation to the retained launch attempt.

        ``release`` and ``close`` remove this local authority before this gate.
        Once this method succeeds the terminal request has begun; it intentionally
        does not hold the local lock across Core IO.
        """

        key: _CacheKey = (operation, request_id, fence)
        with self._lock:
            if self._closed:
                raise ExternalMeasurementCoreClientError("CLIENT_CLOSED")
            attempt_token = self._attempt_tokens.get(key)
            if key not in self._capabilities or attempt_token is None:
                raise ExternalMeasurementCoreClientError("ATTEMPT_NOT_RETAINED")
            if key in self._terminals:
                raise ExternalMeasurementCoreClientError("ATTEMPT_TERMINAL_IN_FLIGHT")
            terminal_token = object()
            self._terminals[key] = (terminal_token, attempt_token)
            return key, terminal_token, attempt_token

    def _finish_terminal(
        self, key: _CacheKey, terminal_token: object, attempt_token: object
    ) -> None:
        """Drop only the capability generation held by this terminal operation."""

        with self._lock:
            terminal_owner = self._terminals.get(key)
            if (
                terminal_owner is None
                or terminal_owner[0] is not terminal_token
                or terminal_owner[1] is not attempt_token
            ):
                return
            self._terminals.pop(key, None)
            if self._attempt_tokens.get(key) is attempt_token:
                self._capabilities.pop(key, None)
                self._attempt_tokens.pop(key, None)

    @staticmethod
    def fence_from_grant(
        worker_instance_id: str, lease_acquisition_id: str, lease_generation: int
    ) -> LocalLeaseFenceV1:
        try:
            return LocalLeaseFenceV1(
                worker_instance_id=worker_instance_id,
                lease_acquisition_id=lease_acquisition_id,
                lease_generation=lease_generation,
            )
        except (TypeError, ValueError, ValidationError):
            raise ExternalMeasurementCoreClientError("INVALID_LEASE_FENCE") from None

    def _request(
        self,
        method: str,
        path: str,
        *,
        deadline_monotonic: float,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        accepted_statuses: tuple[int, ...] = (200,),
    ) -> dict[str, Any]:
        try:
            # Intentional package-private composition: one bounded bearer session,
            # no second response decoder or raw httpx escape hatch.
            return self._core._request(  # noqa: SLF001
                method,
                path,
                deadline=deadline_monotonic,
                headers=headers,
                body=body,
                accepted_statuses=accepted_statuses,
            )
        except ExternalCoreClientError as exc:
            raise ExternalMeasurementCoreClientError(exc.code) from None

    def list_pending(
        self,
        operation: MeasurementOperationV2,
        *,
        deadline_monotonic: float,
        limit: int = 50,
    ) -> tuple[PendingMeasurementWorkV1, ...]:
        self._require_open()
        operation = _operation(operation)
        maximum = 100 if operation == "CHECKPOINT_VALIDATION" else 200
        if type(limit) is not int or not 1 <= limit <= maximum:
            raise ExternalMeasurementCoreClientError("INVALID_QUEUE_LIMIT")
        try:
            if operation == "CHECKPOINT_VALIDATION":
                evidence_items = _EvidencePendingList.model_validate(
                    self._request(
                        "GET",
                        f"{_EVIDENCE_BASE}?limit={limit}",
                        deadline_monotonic=deadline_monotonic,
                    )
                ).items
                return tuple(
                    PendingMeasurementWorkV1(
                        operation, _request_id(item.validation_id), item.issued_at
                    )
                    for item in evidence_items
                )
            base = _VOLUME_BASES[operation]
            volume_items = _PendingList.model_validate(
                self._request(
                    "GET", f"{base}?limit={limit}", deadline_monotonic=deadline_monotonic
                )
            ).items
            return tuple(
                PendingMeasurementWorkV1(operation, _request_id(item.request_ref), item.issued_at)
                for item in volume_items
            )
        except (ValidationError, ValueError, TypeError):
            raise ExternalMeasurementCoreClientError("INVALID_CORE_RESPONSE") from None

    def claim(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        *,
        worker_instance_id: str,
        acquisition_id: str,
        deadline_monotonic: float,
    ) -> MeasurementLeaseGrantV1:
        self._require_open()
        operation = _operation(operation)
        request_id = _request_id(request_id)
        proposed = self._claim_fence(worker_instance_id, acquisition_id)
        try:
            if operation == "CHECKPOINT_VALIDATION":
                evidence_response = _EvidenceLeaseResponse.model_validate(
                    self._request(
                        "POST",
                        f"{_EVIDENCE_BASE}/{request_id}/lease",
                        deadline_monotonic=deadline_monotonic,
                        headers={**_fence_headers(proposed), "X-KSI-Lease-Generation": "0"},
                        accepted_statuses=(200,),
                    )
                )
                if evidence_response.request.validation_id != request_id:
                    raise ExternalMeasurementCoreClientError("LEASE_BINDING_MISMATCH")
                response_fence = evidence_response.fence
                response_expiry = evidence_response.lease_expires_at
                response_verdict = evidence_response.verdict
            else:
                volume_response = _VolumeLeaseResponse.model_validate(
                    self._request(
                        "POST",
                        f"{_VOLUME_BASES[operation]}/{request_id}/lease",
                        deadline_monotonic=deadline_monotonic,
                        body={
                            "workerInstanceId": worker_instance_id,
                            "leaseAcquisitionId": acquisition_id,
                            "leaseGeneration": 0,
                            "mode": "CLAIM",
                        },
                        accepted_statuses=(200, 201),
                    )
                )
                if volume_response.request.request_ref != request_id:
                    raise ExternalMeasurementCoreClientError("LEASE_BINDING_MISMATCH")
                response_fence = volume_response.fence
                response_expiry = volume_response.lease_expires_at
                response_verdict = volume_response.verdict
            if (
                response_fence.worker_instance_id != worker_instance_id
                or response_fence.lease_acquisition_id != acquisition_id
                or response_fence.lease_generation < 1
                or response_verdict not in {"LEASED", "LEASE_RENEWED"}
            ):
                raise ExternalMeasurementCoreClientError("LEASE_BINDING_MISMATCH")
            return MeasurementLeaseGrantV1(
                operation, request_id, response_fence, response_expiry
            )
        except ValidationError:
            raise ExternalMeasurementCoreClientError("INVALID_CORE_RESPONSE") from None

    def heartbeat(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        fence: LocalLeaseFenceV1,
        *,
        deadline_monotonic: float,
    ) -> MeasurementLeaseGrantV1 | None:
        self._require_open()
        operation = _operation(operation)
        request_id = _request_id(request_id)
        fence = self.fence_from_grant(
            fence.worker_instance_id, fence.lease_acquisition_id, fence.lease_generation
        )
        try:
            if operation == "CHECKPOINT_VALIDATION":
                evidence_response = _EvidenceLeaseResponse.model_validate(
                    self._request(
                        "POST",
                        f"{_EVIDENCE_BASE}/{request_id}/heartbeat",
                        deadline_monotonic=deadline_monotonic,
                        headers=_fence_headers(fence),
                    )
                )
                bound = evidence_response.request.validation_id == request_id
                response_fence = evidence_response.fence
                response_expiry = evidence_response.lease_expires_at
                response_verdict = evidence_response.verdict
            else:
                volume_response = _VolumeLeaseResponse.model_validate(
                    self._request(
                        "POST",
                        f"{_VOLUME_BASES[operation]}/{request_id}/heartbeat",
                        deadline_monotonic=deadline_monotonic,
                        body={
                            "workerInstanceId": fence.worker_instance_id,
                            "leaseAcquisitionId": fence.lease_acquisition_id,
                            "leaseGeneration": fence.lease_generation,
                        },
                    )
                )
                bound = volume_response.request.request_ref == request_id
                response_fence = volume_response.fence
                response_expiry = volume_response.lease_expires_at
                response_verdict = volume_response.verdict
            expected_verdict = "LEASED" if operation == "CHECKPOINT_VALIDATION" else "LEASE_RENEWED"
            if response_fence != fence or not bound or response_verdict != expected_verdict:
                raise ExternalMeasurementCoreClientError("LEASE_BINDING_MISMATCH")
            return MeasurementLeaseGrantV1(
                operation, request_id, response_fence, response_expiry
            )
        except (ExternalMeasurementCoreClientError, ValidationError):
            self.release(operation, request_id, fence)
            return None

    def current_input(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        fence: LocalLeaseFenceV1,
        *,
        attempt_nonce: str,
        deadline_monotonic: float,
    ) -> MeasurementLaunchRequestV2 | None:
        operation = _operation(operation)
        request_id = _request_id(request_id)
        fence = self.fence_from_grant(
            fence.worker_instance_id, fence.lease_acquisition_id, fence.lease_generation
        )
        key: _CacheKey = (operation, request_id, fence)
        token = object()
        with self._lock:
            if (
                self._closed
                or key in self._terminals
                or len(set(self._capabilities) | set(self._pending) | {key}) > _MAX_CACHE_KEYS
            ):
                return None
            self._capabilities.pop(key, None)
            self._attempt_tokens.pop(key, None)
            self._pending[key] = token
        try:
            if operation == "CHECKPOINT_VALIDATION":
                evidence_body = _EvidenceInputResponse.model_validate(
                    self._request(
                        "GET",
                        f"{_EVIDENCE_BASE}/{request_id}/input",
                        deadline_monotonic=deadline_monotonic,
                        headers=_fence_headers(fence),
                    )
                )
                launch, capabilities = self._checkpoint_launch(evidence_body, fence, attempt_nonce)
            elif operation == "SINGLE_VOLUME":
                single_body = _SingleVolumeInputResponse.model_validate(
                    self._request(
                        "GET",
                        f"{_SINGLE_VOLUME_BASE}/{request_id}/input",
                        deadline_monotonic=deadline_monotonic,
                        headers=_fence_headers(fence),
                    )
                )
                launch, capabilities = self._single_volume_launch(
                    single_body, fence, attempt_nonce
                )
            else:
                volume_body = _VolumeInputResponse.model_validate(
                    self._request(
                        "GET",
                        f"{_VOLUME_BASE}/{request_id}/input",
                        deadline_monotonic=deadline_monotonic,
                        headers=_fence_headers(fence),
                    )
                )
                launch, capabilities = self._volume_launch(volume_body, fence, attempt_nonce)
            if launch.request_id != request_id or launch.operation != operation:
                raise ExternalMeasurementCoreClientError("INPUT_BINDING_MISMATCH")
            with self._lock:
                if self._closed or self._pending.get(key) is not token:
                    return None
                self._capabilities[key] = capabilities
                self._attempt_tokens[key] = token
            return launch
        except (ExternalMeasurementCoreClientError, ValidationError, ValueError, TypeError):
            return None
        finally:
            with self._lock:
                if self._pending.get(key) is token:
                    self._pending.pop(key, None)

    def capability_for(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        fence: LocalLeaseFenceV1,
        artifact: MeasurementInputV2,
    ) -> ExternalObjectCapabilityV1:
        operation = _operation(operation)
        request_id = _request_id(request_id)
        fence = self.fence_from_grant(
            fence.worker_instance_id, fence.lease_acquisition_id, fence.lease_generation
        )
        try:
            artifact = MeasurementInputV2.model_validate(artifact)
        except (ValidationError, ValueError, TypeError):
            raise ExternalMeasurementCoreClientError("INVALID_INPUT_IDENTITY") from None
        with self._lock:
            matching = [
                capability
                for capability in self._capabilities.get((operation, request_id, fence), ())
                if capability.artifact == artifact
            ]
            if len(matching) != 1:
                raise ExternalMeasurementCoreClientError("INPUT_CAPABILITY_UNAVAILABLE")
            capability = matching[0]
            return ExternalObjectCapabilityV1(
                artifact=capability.artifact,
                url=capability.url,
                required_headers=capability.required_headers,
            )

    def release(
        self, operation: MeasurementOperationV2, request_id: str, fence: LocalLeaseFenceV1
    ) -> None:
        self._require_open()
        try:
            key: _CacheKey = (
                _operation(operation),
                _request_id(request_id),
                self.fence_from_grant(
                    fence.worker_instance_id, fence.lease_acquisition_id, fence.lease_generation
                ),
            )
        except (AttributeError, ExternalMeasurementCoreClientError):
            return
        with self._lock:
            self._capabilities.pop(key, None)
            self._attempt_tokens.pop(key, None)
            self._pending.pop(key, None)
            self._terminals.pop(key, None)

    def submit_result(
        self,
        launch: MeasurementLaunchRequestV2,
        result: MeasurementResultV2,
        *,
        manifest: InspectorExecutionManifestV1,
        limits: ProtocolLimitsV1,
        computed_at: datetime,
        deadline_monotonic: float,
    ) -> None:
        key: _CacheKey | None = None
        terminal_token: object | None = None
        attempt_token: object | None = None
        try:
            launch = MeasurementLaunchRequestV2.model_validate(launch).sealed()
            result = MeasurementResultV2.model_validate(result).validate_for(
                request=launch, manifest=manifest, limits=limits
            )
            _aware(computed_at)
            key, terminal_token, attempt_token = self._begin_terminal(
                launch.operation, launch.request_id, launch.fence
            )
            if result.status == "FAILED":
                assert result.reason is not None
                self._submit_incomplete_failure(
                    launch.operation,
                    launch.request_id,
                    launch.fence,
                    result.reason,
                    deadline_monotonic=deadline_monotonic,
                )
                return
            if launch.operation == "CHECKPOINT_VALIDATION":
                checkpoint_payload = self._checkpoint_payload(launch, result, computed_at)
                response = self._request(
                    "POST",
                    f"{_EVIDENCE_BASE}/{launch.request_id}/measurement",
                    deadline_monotonic=deadline_monotonic,
                    headers=_fence_headers(launch.fence),
                    body=checkpoint_payload.model_dump(by_alias=True, mode="json"),
                )
                try:
                    evidence_terminal = _EvidenceMeasurementTerminalResponse.model_validate(
                        response
                    )
                except ValidationError:
                    raise ExternalMeasurementCoreClientError("INVALID_CORE_RESPONSE") from None
                self._require_evidence_measurement_terminal(
                    evidence_terminal, launch, checkpoint_payload
                )
            else:
                volume_payload: (
                    ExternalRelativeVolumeMeasurementPayloadV1
                    | ExternalSingleVolumeMeasurementPayloadV1
                ) = (
                    self._single_volume_payload(launch, result)
                    if launch.operation == "SINGLE_VOLUME"
                    else self._volume_payload(launch, result)
                )
                computed_at_wire = computed_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
                response = self._request(
                    "POST",
                    f"{_VOLUME_BASES[launch.operation]}/{launch.request_id}/report",
                    deadline_monotonic=deadline_monotonic,
                    headers=_fence_headers(launch.fence),
                    body={
                        "payload": volume_payload.model_dump(by_alias=True, mode="json"),
                        "computedAt": computed_at_wire,
                    },
                    accepted_statuses=(200, 201),
                )
                try:
                    volume_terminal = _VolumeReportedTerminalResponse.model_validate(response)
                except ValidationError:
                    raise ExternalMeasurementCoreClientError("INVALID_CORE_RESPONSE") from None
                self._require_volume_report_terminal(volume_terminal, launch)
        except (ValidationError, ValueError, TypeError) as exc:
            if isinstance(exc, ExternalMeasurementCoreClientError):
                raise
            raise ExternalMeasurementCoreClientError("INVALID_MEASUREMENT_RESULT") from None
        finally:
            if key is not None and terminal_token is not None and attempt_token is not None:
                self._finish_terminal(key, terminal_token, attempt_token)

    def record_incomplete_failure(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        fence: LocalLeaseFenceV1,
        reason: str,
        *,
        deadline_monotonic: float,
    ) -> None:
        self._require_open()
        operation = _operation(operation)
        request_id = _request_id(request_id)
        fence = self.fence_from_grant(
            fence.worker_instance_id, fence.lease_acquisition_id, fence.lease_generation
        )
        if type(reason) is not str or _FAILURE_REASON.fullmatch(reason) is None:
            raise ExternalMeasurementCoreClientError("INVALID_FAILURE_REASON")
        key, terminal_token, attempt_token = self._begin_terminal(operation, request_id, fence)
        try:
            self._submit_incomplete_failure(
                operation,
                request_id,
                fence,
                reason,
                deadline_monotonic=deadline_monotonic,
            )
        finally:
            self._finish_terminal(key, terminal_token, attempt_token)

    def _submit_incomplete_failure(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        fence: LocalLeaseFenceV1,
        reason: str,
        *,
        deadline_monotonic: float,
    ) -> None:
        """Submit a terminal failure only after the caller acquired the attempt gate."""

        try:
            if operation == "CHECKPOINT_VALIDATION":
                response = self._request(
                    "POST",
                    f"{_EVIDENCE_BASE}/{request_id}/incomplete-failure",
                    deadline_monotonic=deadline_monotonic,
                    headers=_fence_headers(fence),
                    body={"reason": reason},
                )
                if _EvidenceTerminalResponse.model_validate(response).verdict != "REJECTED":
                    raise ExternalMeasurementCoreClientError("INVALID_CORE_RESPONSE")
            else:
                response = self._request(
                    "POST",
                    f"{_VOLUME_BASES[operation]}/{request_id}/incomplete-failure",
                    deadline_monotonic=deadline_monotonic,
                    headers=_fence_headers(fence),
                    body={"reason": reason},
                )
                if _VolumeTerminalResponse.model_validate(response).verdict != "FAILED":
                    raise ExternalMeasurementCoreClientError("INVALID_CORE_RESPONSE")
        except ValidationError:
            raise ExternalMeasurementCoreClientError("INVALID_CORE_RESPONSE") from None

    @staticmethod
    def _require_evidence_measurement_terminal(
        terminal: _EvidenceMeasurementTerminalResponse,
        launch: MeasurementLaunchRequestV2,
        payload: ExternalEvidenceMeasurementPayloadV1,
    ) -> None:
        request = launch.checkpoint_request
        context = launch.evidence_context
        record = terminal.record
        if (
            request is None
            or context is None
            or record.validation_id != request.validation_id
            or record.subject_digest != request.subject_digest
            or record.evidence_manifest_digest != context.evidence_manifest_digest
            or record.target_dsm_observed_sha256 != launch.inputs[0].observed_sha256
            or record.policy_digest != launch.validation_policy.policy_digest
            or record.measurement_payload != payload
            or record.core_verdict.value != terminal.verdict
        ):
            raise ExternalMeasurementCoreClientError("TERMINAL_BINDING_MISMATCH")

    @staticmethod
    def _require_volume_report_terminal(
        terminal: _VolumeReportedTerminalResponse, launch: MeasurementLaunchRequestV2
    ) -> None:
        request: ExternalRelativeVolumeRequestV1 | ExternalSingleVolumeRequestV1 | None = (
            launch.single_volume_request
            if launch.operation == "SINGLE_VOLUME"
            else launch.volume_request
        )
        returned = terminal.request
        if (
            request is None
            or returned.request_ref != request.request_id
            or returned.current_work_order_id != request.current_work_order_id
            or returned.decision_digest != request.decision_digest
            or returned.issued_at != request.issued_at
            # The sealed V2 request retains issuedAt but does not retain Core's
            # report deadline.  Core enforces that deadline and lease server-side;
            # here only a structurally impossible returned interval can be rejected.
            or returned.deadline_at <= returned.issued_at
        ):
            raise ExternalMeasurementCoreClientError("TERMINAL_BINDING_MISMATCH")
        try:
            _request_id(returned.report_ref)
        except ExternalMeasurementCoreClientError:
            raise ExternalMeasurementCoreClientError("TERMINAL_BINDING_MISMATCH") from None

    @staticmethod
    def _claim_fence(worker_instance_id: str, acquisition_id: str) -> LocalLeaseFenceV1:
        # Core accepts only this zero generation as initial-claim sentinel.  The
        # returned positive fence is mandatory for all subsequent calls.
        return ExternalMeasurementCoreClient.fence_from_grant(
            worker_instance_id, acquisition_id, 1
        )

    @staticmethod
    def _volume_launch(
        body: _VolumeInputResponse, fence: LocalLeaseFenceV1, attempt_nonce: str
    ) -> tuple[MeasurementLaunchRequestV2, tuple[ExternalObjectCapabilityV1, ...]]:
        material = body.input
        request, execution, policy = (
            material.request,
            material.execution_policy,
            material.validation_policy,
        )
        inputs = (
            MeasurementInputV2(
                role="BASELINE_DSM",
                artifact_id=request.baseline.dsm_artifact_id,
                observed_sha256=request.baseline.observed_sha256,
                observed_size_bytes=request.baseline.observed_size_bytes,
            ),
            MeasurementInputV2(
                role="CURRENT_DSM",
                artifact_id=request.current.dsm_artifact_id,
                observed_sha256=request.current.observed_sha256,
                observed_size_bytes=request.current.observed_size_bytes,
            ),
        )
        launch = MeasurementLaunchRequestV2(
            operation="RELATIVE_VOLUME",
            inputs=inputs,
            validation_policy=policy,
            checkpoint_request=None,
            evidence_context=None,
            volume_request=request,
            volume_execution_policy=execution,
            volume_evidence_records=material.volume_evidence_records,
            fence=fence,
            attempt_nonce=attempt_nonce,
        ).sealed()
        return launch, ExternalMeasurementCoreClient._capabilities_for(
            launch.inputs, material.inputs
        )

    @staticmethod
    def _single_volume_launch(
        body: _SingleVolumeInputResponse, fence: LocalLeaseFenceV1, attempt_nonce: str
    ) -> tuple[MeasurementLaunchRequestV2, tuple[ExternalObjectCapabilityV1, ...]]:
        material = body.input
        request = material.request
        by_role = {capability.role: capability for capability in material.inputs}
        evidence = by_role.get("CHECKPOINT_CSV")
        if (
            set(by_role) != {"TARGET_DSM", "CHECKPOINT_CSV"}
            or evidence is None
            or evidence.artifact_id is None
            or evidence.observed_sha256 is None
            or evidence.observed_size_bytes is None
        ):
            raise ExternalMeasurementCoreClientError("INPUT_BINDING_MISMATCH")
        inputs = (
            MeasurementInputV2(
                role="TARGET_DSM",
                artifact_id=request.target.dsm_artifact_id,
                observed_sha256=request.target.observed_sha256,
                observed_size_bytes=request.target.observed_size_bytes,
            ),
            MeasurementInputV2(
                role="CHECKPOINT_CSV",
                artifact_id=evidence.artifact_id,
                observed_sha256=evidence.observed_sha256,
                observed_size_bytes=evidence.observed_size_bytes,
            ),
        )
        launch = MeasurementLaunchRequestV2(
            operation="SINGLE_VOLUME",
            inputs=inputs,
            validation_policy=material.validation_policy,
            checkpoint_request=None,
            evidence_context=None,
            volume_request=None,
            volume_execution_policy=None,
            volume_evidence_records=(material.evidence_record,),
            single_volume_request=request,
            single_volume_execution_policy=material.execution_policy,
            fence=fence,
            attempt_nonce=attempt_nonce,
        ).sealed()
        return launch, ExternalMeasurementCoreClient._capabilities_for(
            launch.inputs, material.inputs
        )

    @staticmethod
    def _single_volume_payload(
        launch: MeasurementLaunchRequestV2, result: MeasurementResultV2
    ) -> ExternalSingleVolumeMeasurementPayloadV1:
        request = launch.single_volume_request
        execution = launch.single_volume_execution_policy
        if (
            request is None
            or execution is None
            or not isinstance(result.aggregate, SingleVolumeAggregateV2)
            or request.request_digest is None
            or execution.policy_digest is None
        ):
            raise ExternalMeasurementCoreClientError("RESULT_BINDING_MISMATCH")
        return ExternalSingleVolumeMeasurementPayloadV1(
            request_digest=request.request_digest,
            decision_digest=request.decision_digest,
            target_dsm_digest=request.target.observed_sha256,
            zone_snapshot_digest=request.zone_snapshot.canonical_digest(),
            execution_policy_digest=execution.policy_digest,
            algorithm_build_digest=launch.execution_manifest_digest,
            config_digest=execution.config_digest,
            metrics=result.aggregate.metrics,
        )

    @staticmethod
    def _checkpoint_launch(
        body: _EvidenceInputResponse, fence: LocalLeaseFenceV1, attempt_nonce: str
    ) -> tuple[MeasurementLaunchRequestV2, tuple[ExternalObjectCapabilityV1, ...]]:
        bindings = {binding.role: binding for binding in body.bindings}
        if set(bindings) != {"TARGET_DSM", "CHECKPOINT_CSV"}:
            raise ExternalMeasurementCoreClientError("INPUT_BINDING_MISMATCH")
        target, evidence = bindings["TARGET_DSM"], bindings["CHECKPOINT_CSV"]
        if (
            target.artifact_id is None
            or target.observed_sha256 is None
            or target.observed_size_bytes is None
            or evidence.artifact_id is None
            or evidence.observed_sha256 is None
            or evidence.observed_size_bytes is None
        ):
            raise ExternalMeasurementCoreClientError("INPUT_BINDING_MISMATCH")
        inputs = (
            MeasurementInputV2(
                role="TARGET_DSM",
                artifact_id=target.artifact_id,
                observed_sha256=target.observed_sha256,
                observed_size_bytes=target.observed_size_bytes,
            ),
            MeasurementInputV2(
                role="CHECKPOINT_CSV",
                artifact_id=evidence.artifact_id,
                observed_sha256=evidence.observed_sha256,
                observed_size_bytes=evidence.observed_size_bytes,
            ),
        )
        launch = MeasurementLaunchRequestV2(
            operation="CHECKPOINT_VALIDATION",
            inputs=inputs,
            validation_policy=body.validation_policy,
            checkpoint_request=body.request,
            evidence_context=body.context,
            volume_request=None,
            volume_execution_policy=None,
            volume_evidence_records=(),
            fence=fence,
            attempt_nonce=attempt_nonce,
        ).sealed()
        return launch, ExternalMeasurementCoreClient._capabilities_for(inputs, body.bindings)

    @staticmethod
    def _capabilities_for(
        inputs: tuple[MeasurementInputV2, MeasurementInputV2],
        raw: tuple[_CapabilityWire, _CapabilityWire],
    ) -> tuple[ExternalObjectCapabilityV1, ExternalObjectCapabilityV1]:
        by_role = {capability.role: capability for capability in raw}
        if len(by_role) != 2 or set(by_role) != {item.role for item in inputs}:
            raise ExternalMeasurementCoreClientError("INPUT_BINDING_MISMATCH")
        capabilities: list[ExternalObjectCapabilityV1] = []
        for item in inputs:
            capability = by_role[item.role]
            if (
                capability.artifact_id is not None
                and capability.artifact_id != item.artifact_id
                or capability.observed_sha256 is not None
                and capability.observed_sha256 != item.observed_sha256
                or capability.observed_size_bytes is not None
                and capability.observed_size_bytes != item.observed_size_bytes
            ):
                raise ExternalMeasurementCoreClientError("INPUT_BINDING_MISMATCH")
            try:
                capabilities.append(
                    ExternalObjectCapabilityV1(
                        artifact=item,
                        url=capability.download_url,
                        required_headers=capability.required_headers,
                    )
                )
            except (TypeError, ValueError):
                raise ExternalMeasurementCoreClientError("INVALID_STORAGE_CAPABILITY") from None
        return cast(
            tuple[ExternalObjectCapabilityV1, ExternalObjectCapabilityV1], tuple(capabilities)
        )

    @staticmethod
    def _checkpoint_payload(
        launch: MeasurementLaunchRequestV2, result: MeasurementResultV2, computed_at: datetime
    ) -> ExternalEvidenceMeasurementPayloadV1:
        if (
            launch.checkpoint_request is None
            or launch.evidence_context is None
            or not isinstance(result.aggregate, CheckpointAggregateV2)
        ):
            raise ExternalMeasurementCoreClientError("RESULT_BINDING_MISMATCH")
        request = launch.checkpoint_request
        context = launch.evidence_context
        aggregate = result.aggregate
        return ExternalEvidenceMeasurementPayloadV1(
            validation_id=request.validation_id,
            evidence_manifest_digest=context.evidence_manifest_digest,
            target_dsm_observed_sha256=launch.inputs[0].observed_sha256,
            policy_digest=launch.validation_policy.policy_digest or "",
            measured_checkpoint_count=aggregate.measured_checkpoint_count,
            mean_error_m=aggregate.mean_error_m,
            mae_m=aggregate.mae_m,
            rmse_m=aggregate.rmse_m,
            max_abs_error_m=aggregate.max_abs_error_m,
            measured_at=computed_at,
        )

    @staticmethod
    def _volume_payload(
        launch: MeasurementLaunchRequestV2, result: MeasurementResultV2
    ) -> ExternalRelativeVolumeMeasurementPayloadV1:
        if (
            launch.volume_request is None
            or launch.volume_execution_policy is None
            or not isinstance(result.aggregate, RelativeVolumeAggregateV2)
            or launch.volume_request.request_digest is None
            or launch.volume_execution_policy.policy_digest is None
        ):
            raise ExternalMeasurementCoreClientError("RESULT_BINDING_MISMATCH")
        request = launch.volume_request
        execution = launch.volume_execution_policy
        request_digest = request.request_digest
        execution_policy_digest = execution.policy_digest
        if request_digest is None or execution_policy_digest is None:
            raise ExternalMeasurementCoreClientError("RESULT_BINDING_MISMATCH")
        return ExternalRelativeVolumeMeasurementPayloadV1(
            request_digest=request_digest,
            decision_digest=request.decision_digest,
            baseline_dsm_digest=request.baseline.observed_sha256,
            current_dsm_digest=request.current.observed_sha256,
            zone_snapshot_digest=request.zone_snapshot.canonical_digest(),
            execution_policy_digest=execution_policy_digest,
            algorithm_build_digest=launch.execution_manifest_digest,
            config_digest=execution.config_digest,
            metrics=result.aggregate.metrics,
        )


__all__ = [
    "ExternalMeasurementCoreClient",
    "ExternalMeasurementCoreClientError",
    "MeasurementLeaseGrantV1",
    "MeasurementOperationV2",
    "PendingMeasurementWorkV1",
]
