"""Durable exact reviews for externally measured relative- and single-volume results.

The source port is intentionally report-ref keyed.  It never treats a request
identifier as a report identifier and defaults closed until the reviewed 4B/4C
adapter is assembled.  Historical resolution is independent of this journal:
the review event only anchors the exact source snapshot it must re-resolve.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ExternalPairUseDecisionV1
from ksi_event_contracts.external_relative_volume import (
    ExternalRelativeVolumeReportV1,
    ExternalRelativeVolumeRequestV1,
)
from ksi_event_contracts.external_result_review import (
    ExternalResultReviewAuthorityV1,
    ExternalResultReviewReceiptV1,
    external_result_review_receipt_wire_dict,
)
from ksi_event_contracts.external_single_volume import (
    ExternalSingleVolumeDecisionV1,
    ExternalSingleVolumeReportV1,
    ExternalSingleVolumeRequestV1,
)
from ksi_event_contracts.external_single_volume_result_review import (
    SINGLE_VOLUME_REVIEW_FACTUAL_LIMITATIONS,
    ExternalSingleVolumeResultReviewAuthorityV1,
    ExternalSingleVolumeResultReviewReceiptV1,
    external_single_volume_result_review_receipt_wire_dict,
    parse_external_result_review_receipt,
)
from pydantic import ValidationError

from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import Principal

_LOGGER = logging.getLogger(__name__)
_VERSION = 1
_FACTUAL_LIMITATIONS = (
    "RELATIVE_VOLUME_IS_OPERATIONAL_ONLY",
    "ABSOLUTE_ACCURACY_NOT_CLAIMED",
    "NO_AUTOMATIC_REOBSERVATION_THRESHOLD",
)
# One review journal holds both families; the event kind must match the
# receipt contract so a relative line can never replay a single receipt.
_KIND_BY_CONTRACT = {
    "external-result-review-receipt.v1": "external-result-reviewed",
    "external-single-volume-result-review-receipt.v1": "external-single-volume-result-reviewed",
}


class ExternalResultReviewRecoveryError(RuntimeError):
    """The review journal cannot establish an exact independent lineage."""


@dataclass(frozen=True, slots=True)
class ExternalResultReviewSourceV1:
    """Trusted Core source snapshot; this is never a public request body."""

    report_ref: str
    request: ExternalRelativeVolumeRequestV1
    report: ExternalRelativeVolumeReportV1
    authority: ExternalResultReviewAuthorityV1
    decision: ExternalPairUseDecisionV1


@dataclass(frozen=True, slots=True)
class ExternalSingleVolumeResultReviewSourceV1:
    """Trusted Core single-epoch source snapshot; never a public request body."""

    report_ref: str
    request: ExternalSingleVolumeRequestV1
    report: ExternalSingleVolumeReportV1
    authority: ExternalSingleVolumeResultReviewAuthorityV1
    decision: ExternalSingleVolumeDecisionV1


ExternalResultReviewSource = ExternalResultReviewSourceV1 | ExternalSingleVolumeResultReviewSourceV1
AnyExternalResultReviewReceipt = (
    ExternalResultReviewReceiptV1 | ExternalSingleVolumeResultReviewReceiptV1
)


class ExternalResultReviewSourcePort(Protocol):
    """Resolve source authority by report reference, independently of reviews."""

    def resolve_current(
        self,
        *,
        organization_id: str,
        report_ref: str,
        principal: Principal,
        evaluated_at: datetime,
    ) -> ExternalResultReviewSource | None: ...

    def resolve_historical(
        self,
        *,
        organization_id: str,
        report_ref: str,
        report_digest: str,
        evaluated_at: datetime,
    ) -> ExternalResultReviewSource | None: ...

    def is_current(
        self, source: ExternalResultReviewSource, *, principal: Principal, evaluated_at: datetime
    ) -> bool:
        """Perform only a retained local recheck while the coordinator is held."""
        ...


class _ClosedExternalResultReviewSourcePort:
    def resolve_current(
        self,
        *,
        organization_id: str,
        report_ref: str,
        principal: Principal,
        evaluated_at: datetime,
    ) -> ExternalResultReviewSource | None:
        del organization_id, report_ref, principal, evaluated_at
        return None

    def resolve_historical(
        self,
        *,
        organization_id: str,
        report_ref: str,
        report_digest: str,
        evaluated_at: datetime,
    ) -> ExternalResultReviewSource | None:
        del organization_id, report_ref, report_digest, evaluated_at
        return None

    def is_current(
        self, source: ExternalResultReviewSource, *, principal: Principal, evaluated_at: datetime
    ) -> bool:
        del source, principal, evaluated_at
        return False


def _digest(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _event_digest(event: dict[str, Any]) -> str:
    return _digest({key: value for key, value in event.items() if key != "eventDigest"})


def _receipt_wire_dict(receipt: AnyExternalResultReviewReceipt) -> dict[str, Any]:
    if isinstance(receipt, ExternalSingleVolumeResultReviewReceiptV1):
        return external_single_volume_result_review_receipt_wire_dict(receipt)
    return external_result_review_receipt_wire_dict(receipt)


def _require_utc(value: datetime, *, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field} must be UTC-aware")


def _parse_utc(raw: object, *, field: str) -> datetime:
    if type(raw) is not str:
        raise ValueError(f"{field} must be a UTC timestamp string")
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    _require_utc(value, field=field)
    return value


class ExternalResultReviewStore:
    """Append-only review projection with independently re-resolved history."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        source_port: ExternalResultReviewSourcePort | None = None,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self._journal = journal
        self._source_port = source_port or _ClosedExternalResultReviewSourcePort()
        self._coordinator = coordinator
        self._reviews_by_ref: dict[str, AnyExternalResultReviewReceipt] = {}
        self._reviews_by_report_ref: dict[tuple[str, str], AnyExternalResultReviewReceipt] = {}
        self._review_listeners: list[Callable[[AnyExternalResultReviewReceipt], None]] = []
        self._lock = threading.RLock()
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException:
            journal.close()
            raise

    def bind_review_listener(
        self, listener: Callable[[AnyExternalResultReviewReceipt], None]
    ) -> None:
        """Bind a post-commit projection; the review receipt never depends on it."""
        with self._lock:
            if listener not in self._review_listeners:
                self._review_listeners.append(listener)

    def _notify_review_listeners(self, receipt: AnyExternalResultReviewReceipt) -> None:
        for listener in tuple(self._review_listeners):
            try:
                listener(receipt)
            except Exception:
                _LOGGER.exception(
                    "external result review listener failed",
                    extra={"review_ref": receipt.review_ref},
                )

    @property
    def source_port(self) -> ExternalResultReviewSourcePort:
        """Read-only constructor dependency; never replace replay-time authority."""
        return self._source_port

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    @staticmethod
    def _review_ref(source: ExternalResultReviewSource) -> str:
        report_digest = source.report.report_digest
        if report_digest is None:
            raise ValueError("review source report must be sealed")
        material = "\0".join((source.authority.organization_id, source.report_ref, report_digest))
        return "err-v1-" + hashlib.sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _receipt(
        source: ExternalResultReviewSource, *, reviewed_at: datetime
    ) -> AnyExternalResultReviewReceipt:
        if isinstance(source, ExternalSingleVolumeResultReviewSourceV1):
            return ExternalSingleVolumeResultReviewReceiptV1(
                review_ref=ExternalResultReviewStore._review_ref(source),
                organization_id=source.authority.organization_id,
                site_id=source.authority.site_id,
                source_work_order_id=source.authority.current_work_order_id,
                report_ref=source.report_ref,
                request=source.request,
                report=source.report,
                authority=source.authority,
                decision=source.decision,
                factual_limitations=SINGLE_VOLUME_REVIEW_FACTUAL_LIMITATIONS,
                reviewed_at=reviewed_at,
            ).sealed()
        receipt = ExternalResultReviewReceiptV1(
            review_ref=ExternalResultReviewStore._review_ref(source),
            organization_id=source.authority.organization_id,
            site_id=source.authority.site_id,
            source_work_order_id=source.authority.current_work_order_id,
            report_ref=source.report_ref,
            request=source.request,
            report=source.report,
            authority=source.authority,
            decision=source.decision,
            factual_limitations=_FACTUAL_LIMITATIONS,
            reviewed_at=reviewed_at,
        ).sealed()
        return receipt

    @staticmethod
    def _same_source(
        receipt: AnyExternalResultReviewReceipt, source: ExternalResultReviewSource
    ) -> bool:
        # A receipt only ever matches a source of its own family.
        if isinstance(receipt, ExternalSingleVolumeResultReviewReceiptV1) != isinstance(
            source, ExternalSingleVolumeResultReviewSourceV1
        ):
            return False
        return (
            receipt.report_ref == source.report_ref
            and receipt.request == source.request
            and receipt.report == source.report
            and receipt.authority == source.authority
            and receipt.decision == source.decision
        )

    def _apply(self, raw: object) -> None:
        if type(raw) is not dict:
            raise ExternalResultReviewRecoveryError("review journal event must be an object")
        expected = {"kind", "version", "review", "eventDigest"}
        if (
            set(raw) != expected
            or raw.get("kind") not in _KIND_BY_CONTRACT.values()
            or type(raw.get("version")) is not int
            or raw.get("version") != _VERSION
        ):
            raise ExternalResultReviewRecoveryError("review journal event has an invalid shape")
        if type(raw["eventDigest"]) is not str or raw["eventDigest"] != _event_digest(raw):
            raise ExternalResultReviewRecoveryError("review journal event digest is invalid")
        try:
            receipt = parse_external_result_review_receipt(raw["review"])
        except (TypeError, ValidationError) as exc:
            raise ExternalResultReviewRecoveryError("review journal receipt is invalid") from exc
        if _KIND_BY_CONTRACT[receipt.contract_version] != raw["kind"]:
            raise ExternalResultReviewRecoveryError("review journal kind does not match receipt")
        if receipt.review_digest is None or receipt.review_digest != receipt.canonical_digest():
            raise ExternalResultReviewRecoveryError("review journal receipt is unsealed")
        key = (receipt.organization_id, receipt.report_ref)
        existing = self._reviews_by_ref.get(receipt.review_ref)
        if existing is not None and existing != receipt:
            raise ExternalResultReviewRecoveryError("duplicate reviewRef has divergent content")
        report_existing = self._reviews_by_report_ref.get(key)
        if report_existing is not None and report_existing != receipt:
            raise ExternalResultReviewRecoveryError("reportRef has divergent review history")
        self._reviews_by_ref[receipt.review_ref] = receipt
        self._reviews_by_report_ref[key] = receipt

    def review(
        self,
        *,
        organization_id: str,
        report_ref: str,
        principal: Principal,
        evaluated_at: datetime,
    ) -> AnyExternalResultReviewReceipt:
        """Durably review one exact current source; missing authority is closed."""

        _require_utc(evaluated_at, field="evaluated_at")
        if (
            type(report_ref) is not str
            or not report_ref.strip()
            or report_ref != report_ref.strip()
        ):
            raise ValueError("report_ref is invalid")
        # Source resolution may perform independent historical/remote work.  It
        # occurs before coordinator entry; the retained object is rechecked
        # under the coordinator immediately before append.
        if principal.organization_id != organization_id:
            raise ValueError("review principal organization does not match request scope")
        source = self._source_port.resolve_current(
            organization_id=organization_id,
            report_ref=report_ref,
            principal=principal,
            evaluated_at=evaluated_at,
        )
        if source is None or source.authority.organization_id != organization_id:
            raise RuntimeError("EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE")
        receipt = self._receipt(source, reviewed_at=evaluated_at)
        key = (receipt.organization_id, report_ref)
        with self._coordinator.mutation(), self._lock:
            if not self._source_port.is_current(
                source, principal=principal, evaluated_at=evaluated_at
            ):
                raise RuntimeError("EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE")
            existing = self._reviews_by_report_ref.get(key)
            if existing is not None:
                if not self._same_source(existing, source):
                    raise RuntimeError("EXTERNAL_RESULT_REVIEW_CONFLICT")
                return existing.model_copy(deep=True)
            if self._journal.sealed_reason is not None:
                raise JournalSealedError(self._journal.sealed_reason)
            raw: dict[str, Any] = {
                "kind": _KIND_BY_CONTRACT[receipt.contract_version],
                "version": _VERSION,
                "review": _receipt_wire_dict(receipt),
            }
            raw["eventDigest"] = _event_digest(raw)
            self._journal.append(raw)
            self._apply(raw)
            recorded = receipt.model_copy(deep=True)
        self._notify_review_listeners(recorded)
        return recorded

    def get_scoped(
        self, review_ref: str, *, organization_id: str
    ) -> AnyExternalResultReviewReceipt | None:
        with self._lock:
            receipt = self._reviews_by_ref.get(review_ref)
            if receipt is None or receipt.organization_id != organization_id:
                return None
            return receipt.model_copy(deep=True)

    def get_for_report(
        self, report_ref: str, *, organization_id: str
    ) -> AnyExternalResultReviewReceipt | None:
        with self._lock:
            receipt = self._reviews_by_report_ref.get((organization_id, report_ref))
            return receipt.model_copy(deep=True) if receipt is not None else None

    def organization_ids(self) -> frozenset[str]:
        """Durable owners for startup verification, including orphaned records."""
        with self._lock:
            return frozenset(item.organization_id for item in self._reviews_by_ref.values())

    def list_scoped(self, *, organization_id: str) -> tuple[AnyExternalResultReviewReceipt, ...]:
        """Return sealed review records for read-only startup graph validation."""

        with self._lock:
            records = [
                receipt.model_copy(deep=True)
                for receipt in self._reviews_by_ref.values()
                if receipt.organization_id == organization_id
            ]
        return tuple(sorted(records, key=lambda receipt: receipt.review_ref))

    def _resolve_historical(
        self,
        *,
        review_ref: str,
        review_digest: str,
        evaluated_at: datetime,
        actor: str | None,
    ) -> AnyExternalResultReviewReceipt | None:
        """Verify source facts at review time and one later durable instant."""

        _require_utc(evaluated_at, field="evaluated_at")
        with self._lock:
            receipt = self._reviews_by_ref.get(review_ref)
            if receipt is None:
                return None
            candidate = receipt.model_copy(deep=True)
        if (
            candidate.review_digest != review_digest
            or candidate.reviewed_at > evaluated_at
            or candidate.report.report_digest is None
        ):
            return None
        review_source = self._source_port.resolve_historical(
            organization_id=candidate.organization_id,
            report_ref=candidate.report_ref,
            report_digest=candidate.report.report_digest,
            evaluated_at=candidate.reviewed_at,
        )
        if review_source is None or not self._same_source(candidate, review_source):
            return None
        source = review_source
        if evaluated_at != candidate.reviewed_at:
            later_source = self._source_port.resolve_historical(
                organization_id=candidate.organization_id,
                report_ref=candidate.report_ref,
                report_digest=candidate.report.report_digest,
                evaluated_at=evaluated_at,
            )
            if later_source is None or not self._same_source(candidate, later_source):
                return None
            source = later_source
        if actor is not None and (
            type(actor) is not str or actor not in source.authority.authorized_actor_ids
        ):
            return None
        return candidate

    def resolve_historical(
        self,
        *,
        review_ref: str,
        review_digest: str,
        actor: str,
        evaluated_at: datetime,
    ) -> AnyExternalResultReviewReceipt | None:
        """Verify durable source facts and the actual approval actor."""

        return self._resolve_historical(
            review_ref=review_ref,
            review_digest=review_digest,
            actor=actor,
            evaluated_at=evaluated_at,
        )

    def verify_historical(
        self,
        *,
        review_ref: str,
        review_digest: str,
        evaluated_at: datetime,
    ) -> AnyExternalResultReviewReceipt | None:
        """Verify source facts without inventing an undisclosed review actor."""

        return self._resolve_historical(
            review_ref=review_ref,
            review_digest=review_digest,
            actor=None,
            evaluated_at=evaluated_at,
        )

    def local_source_matches(
        self,
        receipt: AnyExternalResultReviewReceipt,
        source: ExternalResultReviewSource,
    ) -> bool:
        """Coordinator-held retained recheck used by the proposal authority port."""

        with self._lock:
            stored = self._reviews_by_ref.get(receipt.review_ref)
            return stored == receipt and self._same_source(receipt, source)

    def preflight_current_source(
        self,
        receipt: AnyExternalResultReviewReceipt,
        *,
        principal: Principal,
        evaluated_at: datetime,
    ) -> ExternalResultReviewSource | None:
        """Resolve a source before taking the shared currentness coordinator.

        Source implementations may need a separately owned historical or remote
        lookup.  The authority port calls this method before the coordinator and
        uses :meth:`local_source_is_current` inside its short final guard.
        """

        _require_utc(evaluated_at, field="evaluated_at")
        if principal.organization_id != receipt.organization_id:
            return None
        source = self._source_port.resolve_current(
            organization_id=receipt.organization_id,
            report_ref=receipt.report_ref,
            principal=principal,
            evaluated_at=evaluated_at,
        )
        if source is None or not self._same_source(receipt, source):
            return None
        return source

    def local_source_is_current(
        self,
        receipt: AnyExternalResultReviewReceipt,
        source: ExternalResultReviewSource,
        *,
        principal: Principal,
        evaluated_at: datetime,
    ) -> bool:
        """Coordinator-held exact retained recheck with no new source lookup."""

        return self.local_source_matches(receipt, source) and self._source_port.is_current(
            source, principal=principal, evaluated_at=evaluated_at
        )


__all__ = [
    "AnyExternalResultReviewReceipt",
    "ExternalResultReviewRecoveryError",
    "ExternalResultReviewSource",
    "ExternalResultReviewSourcePort",
    "ExternalResultReviewSourceV1",
    "ExternalResultReviewStore",
    "ExternalSingleVolumeResultReviewSourceV1",
]
