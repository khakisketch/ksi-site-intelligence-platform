"""Publish exactly one retained, sanitized derivative through existing sealed ports.

This module owns no Core route, object capability, or local candidate path.  It
only joins an exact SANITIZE terminal to the private-reader, bounded-PUT, and
Core-receipt contracts already owned by their respective adapters.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

from ksi_event_contracts.external_artifact_validation import ArtifactOutcome
from ksi_event_contracts.external_display_artifact import (
    SanitizedDisplayDeclarationV1,
    SanitizedDisplayReceiptV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind

from ksi_processing_controller.external_artifact_inspection_worker import (
    CurrentAuthorityLost,
    ExternalArtifactInputV1,
    ExternalInspectorLaunchContextV1,
    PrivateSanitizedCandidateOpenerPort,
    PrivateSanitizedCandidateReaderPort,
)
from ksi_processing_controller.external_inspector_protocol import (
    BoundByteReceiptV1,
    InspectorLaunchRequestV1,
    InspectorOperation,
    LocalLeaseFenceV1,
    ProtocolDeadline,
    ProtocolDeadlineExceeded,
)
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportError,
    SealedObjectByteSourceV1,
)
from ksi_processing_controller.external_validation_core_client import (
    ExternalCoreClientError,
    ExternalDisplayUploadCapability,
)

_SANITIZED_DERIVATIVE_CONTENT_TYPE = "image/tiff"
_RETRYABLE_CORE_CODES = frozenset(
    {
        "INVALID_CORE_RESPONSE",
        "CORE_HTTP_500",
        "CORE_HTTP_502",
        "CORE_HTTP_503",
        "CORE_HTTP_504",
    }
)
_RETRYABLE_OBJECT_CODES = frozenset(
    {
        "CONNECT_FAILED",
        "SOCKET_WRITE_FAILED",
        "SOCKET_READ_FAILED",
        "UNEXPECTED_HEADER_EOF",
        "UNEXPECTED_BODY_EOF",
    }
)
_MAX_SEAL_RECEIPT_ADJUDICATION_ATTEMPTS = 2


class ExternalDisplayPublicationError(RuntimeError):
    """Bounded local failure code; never carries a path, URL, header, or receipt."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class DisplayPublicationCorePort(Protocol):
    def grant_display_upload(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        declaration: SanitizedDisplayDeclarationV1,
        *,
        deadline_monotonic: float,
    ) -> ExternalDisplayUploadCapability: ...

    def seal_display_upload(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        grant: ExternalDisplayUploadCapability,
        *,
        deadline_monotonic: float,
    ) -> SanitizedDisplayReceiptV1: ...


class BoundedDisplayPutPort(Protocol):
    def put_bound_bytes(
        self,
        capability: object,
        sealed_source: SealedObjectByteSourceV1,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int,
    ) -> BoundByteReceiptV1: ...


class RetainedSanitizedCandidateOwnerPort(PrivateSanitizedCandidateOpenerPort, Protocol):
    """The sink retains sole ownership of candidate retirement."""

    def abort_attempt(self, request: InspectorLaunchRequestV1) -> None: ...


@dataclass(frozen=True, slots=True)
class _DisplayObjectCapability:
    """Private upload tuple consumed only by the bounded object transport."""

    artifact: ExternalArtifactInputV1
    url: str = field(repr=False)
    required_headers: Mapping[str, str] = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "artifact", ExternalArtifactInputV1.model_validate(self.artifact.__dict__)
        )
        object.__setattr__(self, "required_headers", MappingProxyType(dict(self.required_headers)))


class ExternalDisplayPublicationWorker:
    """Consumes one exact retained candidate and returns only Core's sealed receipt.

    A retryable response-loss error leaves the candidate with its sink so a
    later call with the unchanged context retries the same declaration and
    source bytes.  All other failures retire the candidate before propagating.
    """

    def __init__(
        self,
        *,
        core: DisplayPublicationCorePort,
        candidate_opener: RetainedSanitizedCandidateOwnerPort,
        object_transport: BoundedDisplayPutPort,
    ) -> None:
        self._core = core
        self._candidate_opener = candidate_opener
        self._object_transport = object_transport

    def publish(self, context: ExternalInspectorLaunchContextV1) -> SanitizedDisplayReceiptV1:
        """Grant, stream, seal, and retire one retained derivative without buffering it."""
        reader: PrivateSanitizedCandidateReaderPort | None = None
        try:
            declaration = self._declaration_for(context)
            self._require_current(context)
            grant = self._core.grant_display_upload(
                context.retained_launch_request.request.request_id,
                context.retained_launch_request.fence,
                declaration,
                deadline_monotonic=context.retained_deadline.expires_at,
            )
            self._require_current(context)
            self._require_grant(grant, declaration)
            capability = self._object_capability(grant)
            reader = self._candidate_opener.open_private_candidate(
                context.retained_launch_request,
                context.retained_terminal,
                deadline=context.retained_deadline,
                wait_is_current=context.retained_authority_is_current,
                heartbeat_interval_millis=context.retained_heartbeat_interval_millis,
            )
            self._require_current(context)
            upload = self._object_transport.put_bound_bytes(
                capability,
                SealedObjectByteSourceV1(capability.artifact, reader),
                deadline=context.retained_deadline,
                wait_is_current=context.retained_authority_is_current,
                heartbeat_interval_millis=context.retained_heartbeat_interval_millis,
            )
            self._require_upload(upload, declaration)
            self._close_reader(reader)
            reader = None
            self._require_current(context)
            receipt = self._seal_with_receipt_adjudication(context, grant, declaration)
        except BaseException as exc:
            self._close_reader_quietly(reader)
            if not self._retryable_while_current(exc, context):
                self._retire_quietly(context)
            raise
        self._retire(context)
        return receipt

    @staticmethod
    def _declaration_for(
        context: ExternalInspectorLaunchContextV1,
    ) -> SanitizedDisplayDeclarationV1:
        if not isinstance(context, ExternalInspectorLaunchContextV1):
            raise TypeError("display publication requires an exact launch context")
        # Revalidate each model here.  ``model_copy`` may otherwise carry a
        # stale field into a frozen outer context without re-running validators.
        try:
            current = type(context.current).model_validate(context.current.__dict__)
            artifact = ExternalArtifactInputV1.model_validate(context.artifact.__dict__)
            launch = InspectorLaunchRequestV1.model_validate(context.launch_request.__dict__)
            terminal = type(context.terminal).model_validate(context.terminal.__dict__)
        except (TypeError, ValueError) as exc:
            raise ExternalDisplayPublicationError("INVALID_LAUNCH_CONTEXT") from exc
        if (
            current != context.retained_current
            or artifact != context.retained_artifact
            or launch != context.retained_launch_request
            or terminal != context.retained_terminal
            or context.deadline is not context.retained_deadline
            or context.authority_is_current is not context.retained_authority_is_current
            or context.heartbeat_interval_millis != context.retained_heartbeat_interval_millis
        ):
            raise ExternalDisplayPublicationError("INVALID_LAUNCH_CONTEXT")
        report = current.accepted_report
        if report is None:
            raise ExternalDisplayPublicationError("DISPLAY_REPORT_UNAVAILABLE")
        try:
            report = type(report).model_validate(report.__dict__)
        except (TypeError, ValueError) as exc:
            raise ExternalDisplayPublicationError("INVALID_DISPLAY_REPORT") from exc
        if (
            current.phase.value != "DISPLAY"
            or current.next_action.value != "SANITIZE_DISPLAY"
            or current.request != launch.request
            or current.policy != launch.policy
            or artifact not in current.artifacts
            or artifact.kind is not ProcessingArtifactKind.ORTHO
            or launch.operation is not InspectorOperation.SANITIZE
            or launch.sealed_byte_binding.artifact_id != artifact.entry_id
            or launch.sealed_byte_binding.observed_sha256 != artifact.observed_sha256
            or launch.sealed_byte_binding.observed_size_bytes != artifact.observed_size_bytes
            or terminal.result != "COMPLETED"
            or terminal.outcome != "SANITIZED"
            or terminal.output_sha256 is None
            or terminal.output_size_bytes is None
        ):
            raise ExternalDisplayPublicationError("DISPLAY_LAUNCH_BINDING_MISMATCH")
        try:
            terminal.validate_for(launch)
        except ValueError as exc:
            raise ExternalDisplayPublicationError("DISPLAY_TERMINAL_BINDING_MISMATCH") from exc
        policy_digest = current.policy.policy_digest
        if (
            policy_digest is None
            or report.report_digest is None
            or report != report.sealed()
            or report.request_id != current.request.request_id
            or report.subject != current.request.subject
            or report.subject_digest != current.request.subject.canonical_digest()
            or report.inspection_policy_digest != policy_digest
            or report.inspector_build_digest != current.policy.parser_build_digest
        ):
            raise ExternalDisplayPublicationError("DISPLAY_REPORT_BINDING_MISMATCH")
        outcomes = tuple(
            outcome
            for outcome in report.measurement_payload.outcomes
            if outcome.artifact_id == artifact.entry_id
            and outcome.observed_sha256 == artifact.observed_sha256
            and outcome.outcome is ArtifactOutcome.MEASURED
        )
        if len(outcomes) != 1 or outcomes[0].measurements is None:
            raise ExternalDisplayPublicationError("DISPLAY_REPORT_BINDING_MISMATCH")
        measurements = outcomes[0].measurements
        if measurements.band_count not in {3, 4} or measurements.dtype != "uint8":
            raise ExternalDisplayPublicationError("DISPLAY_REPORT_BINDING_MISMATCH")
        # A current DISPLAY lease authorizes the mutable grant/seal operations,
        # while this declaration identifies one immutable report/source/output.
        # Fence and attempt nonce identify an execution attempt, so including
        # either would make an interrupted upload unrecoverable after Core
        # grants a later DISPLAY lease for the same retained report.
        display_id = (
            "sda-v1-"
            + hashlib.sha256(
                "\n".join(
                    (
                        current.request.request_id,
                        report.subject_digest,
                        report.report_digest,
                        policy_digest,
                        current.policy.parser_build_digest,
                        artifact.entry_id,
                        artifact.kind.value,
                        artifact.observed_sha256,
                        str(artifact.observed_size_bytes),
                        terminal.output_sha256,
                        str(terminal.output_size_bytes),
                        _SANITIZED_DERIVATIVE_CONTENT_TYPE,
                    )
                ).encode("ascii")
            ).hexdigest()
        )
        return SanitizedDisplayDeclarationV1(
            display_id=display_id,
            request_id=current.request.request_id,
            source_subject_digest=report.subject_digest,
            source_report_digest=report.report_digest,
            policy_digest=policy_digest,
            inspector_build_digest=current.policy.parser_build_digest,
            declared_derivative_sha256=terminal.output_sha256,
            declared_derivative_size_bytes=terminal.output_size_bytes,
            declared_derivative_content_type=_SANITIZED_DERIVATIVE_CONTENT_TYPE,
        ).sealed()

    @staticmethod
    def _require_current(context: ExternalInspectorLaunchContextV1) -> None:
        try:
            context.retained_deadline.remaining()
            current = context.retained_authority_is_current()
            context.retained_deadline.remaining()
        except (ProtocolDeadlineExceeded, CurrentAuthorityLost) as exc:
            raise CurrentAuthorityLost(
                "display publication authority is no longer current"
            ) from exc
        except Exception as exc:
            raise CurrentAuthorityLost("display publication authority is unavailable") from exc
        if current is not True:
            raise CurrentAuthorityLost("display publication authority is no longer current")

    @staticmethod
    def _require_grant(
        grant: ExternalDisplayUploadCapability, declaration: SanitizedDisplayDeclarationV1
    ) -> None:
        if not isinstance(grant, ExternalDisplayUploadCapability):
            raise ExternalDisplayPublicationError("DISPLAY_GRANT_UNAVAILABLE")
        try:
            granted = SanitizedDisplayDeclarationV1.model_validate(
                grant.declaration.__dict__
            ).sealed()
        except (TypeError, ValueError) as exc:
            raise ExternalDisplayPublicationError("DISPLAY_GRANT_MISMATCH") from exc
        if grant.declaration != granted or granted != declaration:
            raise ExternalDisplayPublicationError("DISPLAY_GRANT_MISMATCH")

    @staticmethod
    def _object_capability(grant: ExternalDisplayUploadCapability) -> _DisplayObjectCapability:
        declaration = grant.declaration
        return _DisplayObjectCapability(
            artifact=ExternalArtifactInputV1(
                entry_id=declaration.display_id,
                kind=ProcessingArtifactKind.ORTHO,
                observed_sha256=declaration.declared_derivative_sha256,
                observed_size_bytes=declaration.declared_derivative_size_bytes,
                content_type=declaration.declared_derivative_content_type,
            ),
            url=grant.upload_url,
            required_headers=grant.required_headers,
        )

    @staticmethod
    def _require_upload(upload: object, declaration: SanitizedDisplayDeclarationV1) -> None:
        try:
            observed = BoundByteReceiptV1.model_validate(upload.__dict__)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ExternalDisplayPublicationError("DISPLAY_UPLOAD_RECEIPT_MISMATCH") from exc
        if (
            observed.observed_sha256 != declaration.declared_derivative_sha256
            or observed.observed_size_bytes != declaration.declared_derivative_size_bytes
        ):
            raise ExternalDisplayPublicationError("DISPLAY_UPLOAD_RECEIPT_MISMATCH")

    @staticmethod
    def _require_receipt(receipt: object, declaration: SanitizedDisplayDeclarationV1) -> None:
        try:
            sealed = SanitizedDisplayReceiptV1.model_validate(receipt.__dict__).sealed()
        except (AttributeError, TypeError, ValueError) as exc:
            raise ExternalDisplayPublicationError("DISPLAY_CORE_RECEIPT_MISMATCH") from exc
        if (
            receipt != sealed
            or sealed.display_id != declaration.display_id
            or sealed.request_id != declaration.request_id
            or sealed.declaration_digest != declaration.declaration_digest
            or sealed.source_subject_digest != declaration.source_subject_digest
            or sealed.source_report_digest != declaration.source_report_digest
            or sealed.policy_digest != declaration.policy_digest
            or sealed.inspector_build_digest != declaration.inspector_build_digest
            or sealed.observed_derivative_sha256 != declaration.declared_derivative_sha256
            or sealed.observed_derivative_size_bytes != declaration.declared_derivative_size_bytes
            or sealed.observed_derivative_content_type
            != declaration.declared_derivative_content_type
        ):
            raise ExternalDisplayPublicationError("DISPLAY_CORE_RECEIPT_MISMATCH")

    def _seal_with_receipt_adjudication(
        self,
        context: ExternalInspectorLaunchContextV1,
        grant: ExternalDisplayUploadCapability,
        declaration: SanitizedDisplayDeclarationV1,
    ) -> SanitizedDisplayReceiptV1:
        """Retry one uncertain terminal response without reviving a spent DISPLAY lease."""
        for attempt in range(_MAX_SEAL_RECEIPT_ADJUDICATION_ATTEMPTS):
            context.retained_deadline.remaining()
            try:
                receipt = self._core.seal_display_upload(
                    context.retained_launch_request.request.request_id,
                    context.retained_launch_request.fence,
                    grant,
                    deadline_monotonic=context.retained_deadline.expires_at,
                )
            except ExternalCoreClientError as exc:
                if exc.code not in _RETRYABLE_CORE_CODES or (
                    attempt + 1 == _MAX_SEAL_RECEIPT_ADJUDICATION_ATTEMPTS
                ):
                    raise
                continue
            self._require_receipt(receipt, declaration)
            return receipt
        raise AssertionError("terminal receipt adjudication exhausted without a response")

    @staticmethod
    def _close_reader(reader: PrivateSanitizedCandidateReaderPort) -> None:
        try:
            close = reader.close
            close()
        except Exception as exc:
            raise CurrentAuthorityLost("private display reader cleanup failed") from exc

    @staticmethod
    def _close_reader_quietly(reader: PrivateSanitizedCandidateReaderPort | None) -> None:
        if reader is None:
            return
        try:
            close = reader.close
            close()
        except BaseException:
            pass

    def _retire(self, context: ExternalInspectorLaunchContextV1) -> None:
        try:
            self._candidate_opener.abort_attempt(context.retained_launch_request)
        except Exception as exc:
            raise CurrentAuthorityLost("private display candidate cleanup failed") from exc

    def _retire_quietly(self, context: ExternalInspectorLaunchContextV1) -> None:
        with suppress(BaseException):
            self._candidate_opener.abort_attempt(context.retained_launch_request)

    @staticmethod
    def _retryable_while_current(
        exc: BaseException, context: ExternalInspectorLaunchContextV1
    ) -> bool:
        retryable_core = (
            isinstance(exc, ExternalCoreClientError) and exc.code in _RETRYABLE_CORE_CODES
        )
        retryable_object = (
            isinstance(exc, ExternalObjectTransportError) and exc.code in _RETRYABLE_OBJECT_CODES
        )
        if not (retryable_core or retryable_object):
            return False
        try:
            context.retained_deadline.remaining()
            return context.retained_authority_is_current() is True
        except BaseException:
            return False


__all__ = [
    "BoundedDisplayPutPort",
    "DisplayPublicationCorePort",
    "ExternalDisplayPublicationError",
    "ExternalDisplayPublicationWorker",
    "RetainedSanitizedCandidateOwnerPort",
]
