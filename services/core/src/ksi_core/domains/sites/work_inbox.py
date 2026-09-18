"""Recipient-only in-app notices derived from durable work and share facts.

There is deliberately no email, webhook, push token, arbitrary URL, or free
message surface here.  A notification points only at one scoped WorkOrder or
exact retained external report.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import Field, ValidationError, field_validator, model_validator

from ksi_core.domains.sites.external_report_resolver import SINGLE_VOLUME_REPORT_REF_PREFIX
from ksi_core.domains.sites.observation_work_orders import (
    ObservationWorkOrderStore,
    WorkOrderAssignmentTransition,
)
from ksi_core.domains.sites.organization_work_roster import (
    OrganizationWorkRosterStatus,
    OrganizationWorkRosterStore,
)
from ksi_core.foundation.api_base import CamelModel, iso_utc
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.foundation.identifiers import is_path_safe_identifier
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, require_permission


class WorkInboxNotificationKind(StrEnum):
    WORK_ORDER_ASSIGNED = "WORK_ORDER_ASSIGNED"
    EXTERNAL_REPORT_SHARED = "EXTERNAL_REPORT_SHARED"


class WorkInboxTarget(CamelModel):
    kind: Literal["WORK_ORDER", "EXTERNAL_REPORT"]
    work_order_id: str | None = Field(default=None, min_length=1, max_length=255)
    site_id: str | None = Field(default=None, min_length=1, max_length=255)
    report_ref: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def _exact_typed_target(self) -> WorkInboxTarget:
        if self.kind == "WORK_ORDER":
            if (
                self.work_order_id is None
                or self.site_id is not None
                or self.report_ref is not None
            ):
                raise ValueError("WORK_ORDER target must contain only workOrderId")
        elif self.site_id is None or self.report_ref is None or self.work_order_id is not None:
            raise ValueError("EXTERNAL_REPORT target must contain siteId and reportRef only")
        return self


class WorkInboxItem(CamelModel):
    notification_ref: str = Field(min_length=1, max_length=255)
    kind: WorkInboxNotificationKind
    target: WorkInboxTarget
    sender_principal_id: str = Field(min_length=1, max_length=255)
    created_at: datetime
    unread: bool


class WorkInboxPage(CamelModel):
    items: list[WorkInboxItem]
    next_cursor: str | None = None


class ExternalReportShare(CamelModel):
    schema_version: Literal["1.0"]
    share_ref: str = Field(min_length=1, max_length=255)
    organization_id: str = Field(min_length=1, max_length=255)
    sender_principal_id: str = Field(min_length=1, max_length=255)
    recipient_principal_id: str = Field(min_length=1, max_length=255)
    site_id: str = Field(min_length=1, max_length=255)
    report_ref: str = Field(min_length=1, max_length=255)
    report_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("createdAt must be UTC")
        return value


class WorkInboxReadReceipt(CamelModel):
    schema_version: Literal["1.0"]
    organization_id: str = Field(min_length=1, max_length=255)
    recipient_principal_id: str = Field(min_length=1, max_length=255)
    notification_ref: str = Field(min_length=1, max_length=255)
    read_at: datetime

    @field_validator("read_at")
    @classmethod
    def _read_at_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("readAt must be UTC")
        return value


class _HistoricalReportResolver(Protocol):
    def resolve_historical_report_ref(
        self, report_ref: str, *, organization_id: str, now: datetime | None = None
    ) -> Any | None: ...


@runtime_checkable
class _EquivalenceCheckedReportResolver(Protocol):
    """A resolver that can prove which dependencies it wraps (``ExternalVolumeReportResolver``).

    ``uses_exact_dependencies`` needs this because the mounted composite
    resolver is built once inside the workspace graph; a caller proving the
    graph's wiring away from that build site cannot compare it by identity to
    a freshly-built stand-in, only by asking what it wraps.
    """

    def uses(self, relative: object, single: object) -> bool: ...


class WorkInboxStoreRecoveryError(RuntimeError):
    pass


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(char in "0123456789abcdef" for char in value[7:])
    )


def _key_hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fingerprint(value: dict[str, str]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
    )


def _share_fingerprint(share: ExternalReportShare) -> str:
    return _fingerprint(
        {
            "recipientPrincipalId": share.recipient_principal_id,
            "reportRef": share.report_ref,
        }
    )


def _read_fingerprint(receipt: WorkInboxReadReceipt) -> str:
    return _fingerprint({"notificationRef": receipt.notification_ref})


def _assignment_notification_ref(item: WorkOrderAssignmentTransition) -> str:
    material = "\0".join(
        (
            item.organization_id,
            item.work_order_id,
            str(item.operations_revision),
            item.recipient_principal_id,
        )
    )
    return "work-inbox-assignment-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _share_notification_ref(share: ExternalReportShare) -> str:
    return "work-inbox-share-" + share.share_ref.removeprefix("external-report-share-")


class WorkInboxStore:
    """Shares/read receipts plus replay-derived assignments, scoped per recipient."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        work_orders: ObservationWorkOrderStore,
        roster: OrganizationWorkRosterStore,
        report_resolver: _HistoricalReportResolver | None = None,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        if coordinator is not None and (
            work_orders.operations_coordinator is not coordinator
            or roster.coordinator is not coordinator
        ):
            raise ValueError("work inbox must share the Core operations coordinator")
        if work_orders.operations_coordinator is not roster.coordinator:
            raise ValueError("work inbox requires one work-order and roster coordinator")
        self._journal = journal
        self._work_orders = work_orders
        self._roster = roster
        self._report_resolver = report_resolver
        self._coordinator = coordinator or work_orders.operations_coordinator
        self._shares: dict[tuple[str, str], ExternalReportShare] = {}
        self._share_idempotency: dict[tuple[str, str, str], tuple[str, ExternalReportShare]] = {}
        self._read_receipts: dict[tuple[str, str, str], WorkInboxReadReceipt] = {}
        self._read_idempotency: dict[tuple[str, str, str], tuple[str, WorkInboxReadReceipt]] = {}
        self._lock = threading.Lock()
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException:
            journal.close()
            raise

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def uses_exact_dependencies(
        self,
        *,
        work_orders: ObservationWorkOrderStore,
        roster: OrganizationWorkRosterStore,
        report_resolver: object | None,
        single_report_resolver: object | None = None,
    ) -> bool:
        """Prove the mounted router reads the same durable Core participants.

        ``report_resolver`` is compared by identity first — the exact shape
        every non-composite caller (a relative-only resolver, or none) has
        always used.  When the mounted resolver is instead the composite
        ``ExternalVolumeReportResolver``, identity never holds for a resolver
        built at the call site, so the composite is asked what it wraps
        through ``uses`` instead.
        """

        if self._work_orders is not work_orders or self._roster is not roster:
            return False
        if self._report_resolver is report_resolver:
            return True
        resolver = self._report_resolver
        if isinstance(resolver, _EquivalenceCheckedReportResolver):
            return resolver.uses(report_resolver, single_report_resolver)
        return False

    def _apply(self, raw: dict[str, Any]) -> None:
        try:
            kind = raw["kind"]
            if kind == "external-report-shared":
                if set(raw) != {"kind", "ts", "actor", "share", "idempotency"}:
                    raise ValueError("report share event keys are not exact")
                if not isinstance(raw["share"], dict) or raw["share"].get("schemaVersion") != "1.0":
                    raise ValueError("report share schemaVersion is invalid")
                share = ExternalReportShare.model_validate(raw["share"])
                if raw["actor"] != share.sender_principal_id or raw["ts"] != iso_utc(
                    share.created_at
                ):
                    raise ValueError("report share event audit does not match share")
                binding = raw["idempotency"]
                if not isinstance(binding, dict) or set(binding) != {"keyHash", "fingerprint"}:
                    raise ValueError("report share idempotency binding is malformed")
                key_hash, fingerprint = binding["keyHash"], binding["fingerprint"]
                if not _is_digest(key_hash) or not _is_digest(fingerprint):
                    raise ValueError("report share idempotency binding is malformed")
                if fingerprint != _share_fingerprint(share):
                    raise ValueError("report share idempotency fingerprint is invalid")
                share_key = (share.organization_id, share.share_ref)
                idem_key = (share.organization_id, raw["actor"], key_hash)
                if share_key in self._shares or idem_key in self._share_idempotency:
                    raise ValueError("duplicate report share identity or idempotency key")
                self._shares[share_key] = share
                self._share_idempotency[idem_key] = (fingerprint, share)
            elif kind == "work-inbox-notification-read":
                if set(raw) != {"kind", "ts", "actor", "receipt", "idempotency"}:
                    raise ValueError("work inbox read event keys are not exact")
                receipt_raw = raw["receipt"]
                if not isinstance(receipt_raw, dict):
                    raise ValueError("work inbox read schemaVersion is invalid")
                if receipt_raw.get("schemaVersion") != "1.0":
                    raise ValueError("work inbox read schemaVersion is invalid")
                receipt = WorkInboxReadReceipt.model_validate(receipt_raw)
                if raw["actor"] != receipt.recipient_principal_id or raw["ts"] != iso_utc(
                    receipt.read_at
                ):
                    raise ValueError("work inbox read event audit does not match receipt")
                binding = raw["idempotency"]
                if not isinstance(binding, dict) or set(binding) != {"keyHash", "fingerprint"}:
                    raise ValueError("work inbox read idempotency binding is malformed")
                key_hash, fingerprint = binding["keyHash"], binding["fingerprint"]
                if not _is_digest(key_hash) or not _is_digest(fingerprint):
                    raise ValueError("work inbox read idempotency binding is malformed")
                if fingerprint != _read_fingerprint(receipt):
                    raise ValueError("work inbox read idempotency fingerprint is invalid")
                if receipt.notification_ref not in self._historical_notification_refs(
                    organization_id=receipt.organization_id,
                    recipient_principal_id=receipt.recipient_principal_id,
                ):
                    raise ValueError(
                        "work inbox read receipt does not bind a historical notification"
                    )
                receipt_key = (
                    receipt.organization_id,
                    receipt.recipient_principal_id,
                    receipt.notification_ref,
                )
                idem_key = (receipt.organization_id, raw["actor"], key_hash)
                if receipt_key in self._read_receipts or idem_key in self._read_idempotency:
                    raise ValueError("duplicate work inbox read receipt or idempotency key")
                self._read_receipts[receipt_key] = receipt
                self._read_idempotency[idem_key] = (fingerprint, receipt)
            else:
                raise ValueError("work inbox journal kind is invalid")
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise WorkInboxStoreRecoveryError(f"work inbox journal replay failed: {exc}") from exc

    @staticmethod
    def _report_site_and_digest(resolved: object) -> tuple[str, str] | None:
        """Extract the only two exact report facts an inbox share may retain."""

        request = getattr(resolved, "request", None)
        report = getattr(resolved, "report", None)
        zone = getattr(request, "zone_snapshot", None)
        site_id = getattr(zone, "site_id", None)
        digest = getattr(report, "report_digest", None)
        if (
            not isinstance(site_id, str)
            or not is_path_safe_identifier(site_id)
            or not isinstance(digest, str)
            or not _is_digest(digest)
        ):
            return None
        return site_id, digest

    def _resolve_exact_report(
        self, report_ref: str, *, organization_id: str, now: datetime
    ) -> tuple[str, str] | None:
        if self._report_resolver is None:
            raise RuntimeError("EXTERNAL_REPORT_SHARING_UNAVAILABLE")
        if not is_path_safe_identifier(report_ref):
            return None
        resolved = self._report_resolver.resolve_historical_report_ref(
            report_ref, organization_id=organization_id, now=now
        )
        return self._report_site_and_digest(resolved) if resolved is not None else None

    def _live_items(
        self, *, organization_id: str, recipient_principal_id: str, now: datetime
    ) -> list[WorkInboxItem]:
        items: list[WorkInboxItem] = []
        receipts = self._read_receipts
        for transition in self._work_orders.list_assignment_transitions(
            organization_id=organization_id, recipient_principal_id=recipient_principal_id
        ):
            # A current scoped resource recheck prevents the journal from
            # becoming a disclosure path if an underlying record changes.
            if (
                self._work_orders.get(transition.work_order_id, organization_id=organization_id)
                is None
            ):
                continue
            notification_ref = _assignment_notification_ref(transition)
            items.append(
                WorkInboxItem(
                    notification_ref=notification_ref,
                    kind=WorkInboxNotificationKind.WORK_ORDER_ASSIGNED,
                    target=WorkInboxTarget(
                        kind="WORK_ORDER", work_order_id=transition.work_order_id
                    ),
                    sender_principal_id=transition.actor_principal_id,
                    created_at=transition.occurred_at,
                    unread=(organization_id, recipient_principal_id, notification_ref)
                    not in receipts,
                )
            )
        for share in self._shares.values():
            if (
                share.organization_id != organization_id
                or share.recipient_principal_id != recipient_principal_id
            ):
                continue
            try:
                exact = self._resolve_exact_report(
                    share.report_ref, organization_id=organization_id, now=now
                )
            except RuntimeError:
                exact = None
            if exact != (share.site_id, share.report_digest):
                continue
            notification_ref = _share_notification_ref(share)
            items.append(
                WorkInboxItem(
                    notification_ref=notification_ref,
                    kind=WorkInboxNotificationKind.EXTERNAL_REPORT_SHARED,
                    target=WorkInboxTarget(
                        kind="EXTERNAL_REPORT", site_id=share.site_id, report_ref=share.report_ref
                    ),
                    sender_principal_id=share.sender_principal_id,
                    created_at=share.created_at,
                    unread=(organization_id, recipient_principal_id, notification_ref)
                    not in receipts,
                )
            )
        return sorted(
            items, key=lambda item: (item.created_at, item.notification_ref), reverse=True
        )

    def _historical_notification_refs(
        self, *, organization_id: str, recipient_principal_id: str
    ) -> set[str]:
        """Return retained source identities without re-opening live resource access.

        Replay validates a receipt against the event that originally made it
        possible.  New reads still use :meth:`_live_items`, which rechecks
        current scoped resources before exposing a notification.
        """

        assignment_refs = {
            _assignment_notification_ref(transition)
            for transition in self._work_orders.list_assignment_transitions(
                organization_id=organization_id,
                recipient_principal_id=recipient_principal_id,
            )
        }
        share_refs = {
            _share_notification_ref(share)
            for share in self._shares.values()
            if share.organization_id == organization_id
            and share.recipient_principal_id == recipient_principal_id
        }
        return assignment_refs | share_refs

    def list_for_recipient(
        self,
        *,
        organization_id: str,
        recipient_principal_id: str,
        unread_only: bool,
        after: str | None = None,
        limit: int = 20,
        now: datetime | None = None,
    ) -> WorkInboxPage:
        if not all(
            is_path_safe_identifier(value) for value in (organization_id, recipient_principal_id)
        ):
            raise ValueError("work inbox identifiers must be path-safe")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        when = (now or datetime.now(UTC)).astimezone(UTC)
        with self._coordinator.guarded_read(), self._lock:
            items = self._live_items(
                organization_id=organization_id,
                recipient_principal_id=recipient_principal_id,
                now=when,
            )
            start = 0
            if after is not None:
                try:
                    start = next(
                        index + 1
                        for index, item in enumerate(items)
                        if item.notification_ref == after
                    )
                except StopIteration as exc:
                    raise LookupError("work inbox cursor was not found") from exc
            remaining = items[start:]
            if unread_only:
                remaining = [item for item in remaining if item.unread]
            page = remaining[:limit]
            return WorkInboxPage(
                items=page,
                next_cursor=page[-1].notification_ref
                if len(page) < len(remaining) and page
                else None,
            )

    def share_report(
        self,
        report_ref: str,
        *,
        organization_id: str,
        recipient_principal_id: str,
        actor: str,
        idempotency_key: str,
        now: datetime,
    ) -> ExternalReportShare:
        if not all(
            is_path_safe_identifier(value)
            for value in (organization_id, recipient_principal_id, actor, report_ref)
        ):
            raise ValueError("report share identifiers must be path-safe")
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key.strip()) <= 255:
            raise ValueError("Idempotency-Key must be a nonblank value up to 255 characters")
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise ValueError("report share timestamp must be UTC")
        key_hash = _key_hash(idempotency_key)
        # Include the route reportRef and recipient in retry binding. The server
        # obtains organization/site/digest after the prior retry check.
        pending_fingerprint = _fingerprint(
            {"recipientPrincipalId": recipient_principal_id, "reportRef": report_ref}
        )
        with self._coordinator.mutation(), self._lock:
            prior = self._share_idempotency.get((organization_id, actor, key_hash))
            if prior is not None:
                prior_fingerprint, share = prior
                if prior_fingerprint != pending_fingerprint:
                    raise RuntimeError("WORK_INBOX_IDEMPOTENCY_CONFLICT")
                return share.model_copy(deep=True)
            recipient = self._roster.get_member(
                recipient_principal_id, organization_id=organization_id
            )
            if recipient is None or recipient.status is not OrganizationWorkRosterStatus.ACTIVE:
                raise LookupError("work inbox recipient was not found")
            exact = self._resolve_exact_report(
                report_ref, organization_id=organization_id, now=now.astimezone(UTC)
            )
            if exact is None:
                raise LookupError("external relative volume report was not found")
            site_id, report_digest = exact
            share_ref = (
                "external-report-share-"
                + hashlib.sha256(
                    "\0".join(
                        (
                            organization_id,
                            actor,
                            recipient_principal_id,
                            report_ref,
                            report_digest,
                            key_hash,
                        )
                    ).encode("utf-8")
                ).hexdigest()[:32]
            )
            share = ExternalReportShare(
                schema_version="1.0",
                share_ref=share_ref,
                organization_id=organization_id,
                sender_principal_id=actor,
                recipient_principal_id=recipient_principal_id,
                site_id=site_id,
                report_ref=report_ref,
                report_digest=report_digest,
                created_at=now.astimezone(UTC),
            )
            raw = {
                "kind": "external-report-shared",
                "ts": iso_utc(share.created_at),
                "actor": actor,
                "share": share.model_dump(by_alias=True, mode="json"),
                "idempotency": {"keyHash": key_hash, "fingerprint": pending_fingerprint},
            }
            self._journal.append(raw)
            self._apply(raw)
            return share.model_copy(deep=True)

    def mark_read(
        self,
        notification_ref: str,
        *,
        organization_id: str,
        recipient_principal_id: str,
        idempotency_key: str,
        now: datetime,
    ) -> WorkInboxReadReceipt:
        if not all(
            is_path_safe_identifier(value)
            for value in (organization_id, recipient_principal_id, notification_ref)
        ):
            raise LookupError("work inbox notification was not found")
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key.strip()) <= 255:
            raise ValueError("Idempotency-Key must be a nonblank value up to 255 characters")
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise ValueError("work inbox timestamp must be UTC")
        key_hash = _key_hash(idempotency_key)
        fingerprint = _fingerprint({"notificationRef": notification_ref})
        with self._coordinator.mutation(), self._lock:
            prior = self._read_idempotency.get((organization_id, recipient_principal_id, key_hash))
            if prior is not None:
                prior_fingerprint, receipt = prior
                if prior_fingerprint != fingerprint:
                    raise RuntimeError("WORK_INBOX_IDEMPOTENCY_CONFLICT")
                return receipt.model_copy(deep=True)
            existing = self._read_receipts.get(
                (organization_id, recipient_principal_id, notification_ref)
            )
            if existing is not None:
                return existing.model_copy(deep=True)
            if not any(
                item.notification_ref == notification_ref
                for item in self._live_items(
                    organization_id=organization_id,
                    recipient_principal_id=recipient_principal_id,
                    now=now.astimezone(UTC),
                )
            ):
                raise LookupError("work inbox notification was not found")
            receipt = WorkInboxReadReceipt(
                schema_version="1.0",
                organization_id=organization_id,
                recipient_principal_id=recipient_principal_id,
                notification_ref=notification_ref,
                read_at=now.astimezone(UTC),
            )
            raw = {
                "kind": "work-inbox-notification-read",
                "ts": iso_utc(receipt.read_at),
                "actor": recipient_principal_id,
                "receipt": receipt.model_dump(by_alias=True, mode="json"),
                "idempotency": {"keyHash": key_hash, "fingerprint": fingerprint},
            }
            self._journal.append(raw)
            self._apply(raw)
            return receipt.model_copy(deep=True)


class ExternalReportShareIntent(CamelModel):
    recipient_principal_id: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def _recipient_is_path_safe(self) -> ExternalReportShareIntent:
        if not is_path_safe_identifier(self.recipient_principal_id):
            raise ValueError("recipientPrincipalId must be a path-safe identifier")
        return self


def _require_human(principal: Principal) -> Principal:
    if principal.kind is not PrincipalKind.OPERATOR:
        raise HTTPException(status_code=403, detail="HUMAN_AUTHORITY_REQUIRED")
    return principal


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, JournalSealedError):
        return HTTPException(status_code=503, detail="DURABLE_JOURNAL_UNAVAILABLE")
    if str(exc) == "EXTERNAL_REPORT_SHARING_UNAVAILABLE":
        return HTTPException(status_code=503, detail="EXTERNAL_REPORT_SHARING_UNAVAILABLE")
    if str(exc) == "WORK_INBOX_IDEMPOTENCY_CONFLICT":
        return HTTPException(
            status_code=409, detail="Idempotency-Key가 다른 inbox 요청에 이미 사용됐다"
        )
    return HTTPException(status_code=422, detail=str(exc))


def build_work_inbox_router(store: WorkInboxStore) -> APIRouter:
    router = APIRouter(tags=["work-inbox"])

    @router.get("/v1/work-inbox", response_model=WorkInboxPage)
    def list_work_inbox(
        unread_only: bool = Query(default=False, alias="unreadOnly"),  # noqa: B008
        after: str | None = Query(default=None, max_length=255),  # noqa: B008
        limit: int = Query(default=20, ge=1, le=50),  # noqa: B008
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008,E501
    ) -> WorkInboxPage:
        _require_human(principal)
        try:
            return store.list_for_recipient(
                organization_id=principal.organization_id,
                recipient_principal_id=principal.principal_id,
                unread_only=unread_only,
                after=after,
                limit=limit,
            )
        except (LookupError, ValueError) as exc:
            raise _http_error(exc) from exc

    @router.post("/v1/work-inbox/{notification_ref}/read", response_model=WorkInboxReadReceipt)
    def mark_work_inbox_read(
        notification_ref: str,
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008,E501
    ) -> WorkInboxReadReceipt:
        _require_human(principal)
        try:
            return store.mark_read(
                notification_ref,
                organization_id=principal.organization_id,
                recipient_principal_id=principal.principal_id,
                idempotency_key=idempotency_key,
                now=datetime.now(UTC),
            )
        except (JournalSealedError, LookupError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from exc

    def _share_external_report(
        report_ref: str,
        request: ExternalReportShareIntent,
        idempotency_key: str,
        principal: Principal,
        *,
        owns_ref: Callable[[str], bool],
        not_found_detail: str,
    ) -> ExternalReportShare:
        """Record one share through the family route that owns ``report_ref``.

        A ref of the other family never reaches the store: the route
        guards it up front, before any store call, so each family route's
        not-found answer stays fixed to its own family regardless of what
        the other family's resolver would have made of the ref.
        """

        _require_human(principal)
        if not owns_ref(report_ref):
            raise HTTPException(status_code=404, detail=not_found_detail)
        try:
            return store.share_report(
                report_ref,
                organization_id=principal.organization_id,
                recipient_principal_id=request.recipient_principal_id,
                actor=principal.principal_id,
                idempotency_key=idempotency_key,
                now=datetime.now(UTC),
            )
        except (JournalSealedError, LookupError, RuntimeError, ValueError) as exc:
            raise _http_error(exc) from exc

    _RELATIVE_SHARE_NOT_FOUND = "external relative volume report was not found"
    _SINGLE_SHARE_NOT_FOUND = "external single volume report was not found"

    @router.post(
        "/v1/external-relative-volume-reports/{report_ref}/shares",
        response_model=ExternalReportShare,
        status_code=201,
    )
    def share_external_report(
        report_ref: str,
        request: ExternalReportShareIntent,
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
        principal: Principal = Depends(require_permission(Permission.WORK_ORDERS_WRITE)),  # noqa: B008,E501
    ) -> ExternalReportShare:
        return _share_external_report(
            report_ref,
            request,
            idempotency_key,
            principal,
            owns_ref=lambda ref: not ref.startswith(SINGLE_VOLUME_REPORT_REF_PREFIX),
            not_found_detail=_RELATIVE_SHARE_NOT_FOUND,
        )

    @router.post(
        "/v1/external-single-volume-reports/{report_ref}/shares",
        response_model=ExternalReportShare,
        status_code=201,
    )
    def share_single_volume_external_report(
        report_ref: str,
        request: ExternalReportShareIntent,
        idempotency_key: str = Header(..., alias="Idempotency-Key"),
        principal: Principal = Depends(require_permission(Permission.WORK_ORDERS_WRITE)),  # noqa: B008,E501
    ) -> ExternalReportShare:
        return _share_external_report(
            report_ref,
            request,
            idempotency_key,
            principal,
            owns_ref=lambda ref: ref.startswith(SINGLE_VOLUME_REPORT_REF_PREFIX),
            not_found_detail=_SINGLE_SHARE_NOT_FOUND,
        )

    return router
