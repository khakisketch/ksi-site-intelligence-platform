"""Durable, grounded human reobservation proposals for external volume reviews.

This module accepts only a report reference, one existing WorkArea identifier, a
bounded reason, and an idempotency key from the human boundary.  It resolves the
sealed review, source, Site, and WorkArea itself.  Approval is deliberately
forwarded to the accepted 5A WorkOrder kernel; this store never writes an
approval status or a successor WorkOrder event.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_reobservation import (
    ExternalReobservationApprovalInputV1,
    ExternalReobservationApprovalReceiptV1,
    ExternalReobservationProposalAuthorityV1,
    ExternalWorkAreaSnapshotV1,
)
from ksi_event_contracts.external_result_review import (
    ExternalReobservationProposalV1,
    ExternalResultReviewReceiptV1,
    external_reobservation_proposal_wire_dict,
)
from ksi_event_contracts.work_area import WorkArea, WorkAreaStatus
from pydantic import Field, ValidationError, field_validator

from ksi_core.domains.external.workflow.external_result_reviews import (
    ExternalResultReviewSourceV1,
    ExternalResultReviewStore,
)
from ksi_core.domains.sites.observation_work_orders import (
    ExternalReobservationApprovalResult,
    ExternalReobservationProposalAuthorityPort,
    ObservationWorkOrderStore,
)
from ksi_core.domains.sites.sites import SiteStore
from ksi_core.domains.sites.work_areas import WorkAreaStore
from ksi_core.foundation.api_base import CamelModel
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.foundation.identifiers import is_path_safe_identifier
from ksi_core.identity.auth import Permission, Principal, require_permission

_LOGGER = logging.getLogger(__name__)
_VERSION = 1
_EVENT_KIND = "external-reobservation-proposed"


class ExternalReobservationProposalRecoveryError(RuntimeError):
    """A proposal journal cannot establish a sealed, exact proposal lineage."""


class ExternalReobservationProposalConflictError(RuntimeError):
    """The same idempotency key or deterministic proposal ref changed intent."""


class ExternalReobservationProposalUnavailableError(RuntimeError):
    """A current source, scoped Site, or exact active WorkArea is unavailable."""


def _digest(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _event_digest(event: dict[str, Any]) -> str:
    return _digest({key: value for key, value in event.items() if key != "eventDigest"})


def _require_utc(value: datetime, *, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field} must be UTC-aware")


def _review_target(review: ExternalResultReviewReceiptV1) -> ExternalWorkAreaSnapshotV1:
    """Derive the sole allowed target from the reviewed report zone, never intent."""

    zone = review.authority.zone_snapshot
    return ExternalWorkAreaSnapshotV1(
        work_area_id=zone.work_area_id,
        revision=1,
        polygon=zone.polygon,
        crs=zone.crs,
    ).sealed()


def _area_target(area: WorkArea) -> ExternalWorkAreaSnapshotV1:
    return ExternalWorkAreaSnapshotV1(
        work_area_id=area.work_area_id,
        revision=1,
        polygon=area.polygon,
        crs=area.crs,
    ).sealed()


def _target_matches_review(
    review: ExternalResultReviewReceiptV1, area: WorkArea
) -> ExternalWorkAreaSnapshotV1 | None:
    target = _area_target(area)
    return target if target == _review_target(review) else None


def _proposal_intent_digest(
    review: ExternalResultReviewReceiptV1,
    target: ExternalWorkAreaSnapshotV1,
    *,
    reason: str | None,
) -> str:
    if review.review_digest is None or target.snapshot_digest is None:
        raise ValueError("review and target must be sealed")
    return _digest(
        {
            "domain": "external-reobservation-proposal-intent.v1",
            "organizationId": review.organization_id,
            "reviewRef": review.review_ref,
            "reviewDigest": review.review_digest,
            "targetSnapshotDigest": target.snapshot_digest,
            "reason": reason,
        }
    )


def _proposal_ref(intent_digest: str) -> str:
    return "erop-v1-" + intent_digest.removeprefix("sha256:")


class ExternalReobservationProposalStore:
    """Append-only version-one proposals, with idempotent exact intent recovery."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self._journal = journal
        self._coordinator = coordinator
        self._by_ref: dict[str, ExternalReobservationProposalV1] = {}
        self._by_idempotency: dict[tuple[str, str], ExternalReobservationProposalV1] = {}
        self._lock = threading.RLock()
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException:
            journal.close()
            raise

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    @staticmethod
    def _validate_sealed(proposal: ExternalReobservationProposalV1) -> None:
        if (
            proposal.proposal_digest is None
            or proposal.proposal_digest != proposal.canonical_digest()
        ):
            raise ValueError("external reobservation proposal must be sealed")

    def _apply(self, raw: object) -> None:
        if type(raw) is not dict:
            raise ExternalReobservationProposalRecoveryError(
                "proposal journal event must be an object"
            )
        expected = {"kind", "version", "proposal", "idempotencyKey", "eventDigest"}
        if (
            set(raw) != expected
            or raw.get("kind") != _EVENT_KIND
            or type(raw.get("version")) is not int
            or raw["version"] != _VERSION
            or type(raw.get("idempotencyKey")) is not str
            or not is_path_safe_identifier(raw["idempotencyKey"])
            or type(raw.get("eventDigest")) is not str
            or raw["eventDigest"] != _event_digest(raw)
        ):
            raise ExternalReobservationProposalRecoveryError(
                "proposal journal event has an invalid shape"
            )
        try:
            proposal = ExternalReobservationProposalV1.model_validate(raw["proposal"])
            self._validate_sealed(proposal)
        except (TypeError, ValueError, ValidationError) as exc:
            raise ExternalReobservationProposalRecoveryError(
                "proposal journal record is invalid"
            ) from exc
        key = (proposal.organization_id, raw["idempotencyKey"])
        existing = self._by_ref.get(proposal.proposal_ref)
        if existing is not None and existing != proposal:
            raise ExternalReobservationProposalRecoveryError(
                "proposalRef has divergent durable content"
            )
        prior_for_key = self._by_idempotency.get(key)
        if prior_for_key is not None and prior_for_key != proposal:
            raise ExternalReobservationProposalRecoveryError(
                "idempotency key has divergent durable content"
            )
        self._by_ref[proposal.proposal_ref] = proposal
        self._by_idempotency[key] = proposal

    def create(
        self,
        *,
        review: ExternalResultReviewReceiptV1,
        target: ExternalWorkAreaSnapshotV1,
        reason: str | None,
        actor: str,
        created_at: datetime,
        idempotency_key: str,
    ) -> ExternalReobservationProposalV1:
        """Append one proposal after the caller has atomically rechecked inputs."""

        _require_utc(created_at, field="created_at")
        if not is_path_safe_identifier(actor) or not is_path_safe_identifier(idempotency_key):
            raise ValueError("actor and idempotency_key must be path-safe identifiers")
        try:
            # ``model_copy`` intentionally bypasses Pydantic validation.  This
            # durable producer may receive such a copied trusted-model object,
            # so reconstruct canonical models before reading any references or
            # deriving an idempotency intent.
            # Do not use ``model_dump(mode="json")`` for this boundary: it
            # serializes a copied ``True`` strict integer as ``1`` and would
            # hide the invalid raw object before the authoritative validator.
            review_wire = dict(review.__dict__)
            target_wire = dict(target.__dict__)
            if type(target_wire.get("revision")) is not int:
                raise ValueError("proposal target revision must be an exact integer")
            review = ExternalResultReviewReceiptV1.model_validate(review_wire)
            target = ExternalWorkAreaSnapshotV1.model_validate(target_wire)
        except (AttributeError, TypeError, ValueError, ValidationError) as exc:
            raise ValueError("proposal review or target is invalid") from exc
        if review.review_digest is None or review.review_digest != review.canonical_digest():
            raise ValueError("proposal review must be sealed")
        if target.snapshot_digest is None or target.snapshot_digest != target.canonical_digest():
            raise ValueError("proposal target must be sealed")
        if target != _review_target(review):
            raise ValueError("proposal target must be the exact report-zone WorkArea")
        intent_digest = _proposal_intent_digest(review, target, reason=reason)
        proposal = ExternalReobservationProposalV1(
            proposal_ref=_proposal_ref(intent_digest),
            version=1,
            organization_id=review.organization_id,
            site_id=review.site_id,
            source_work_order_id=review.source_work_order_id,
            review_ref=review.review_ref,
            review_digest=review.review_digest,
            report_ref=review.report_ref,
            report_digest=review.report.report_digest or "",
            decision_digest=review.decision.decision_digest or "",
            zone_digest=review.authority.zone_snapshot.definition_digest or "",
            evidence_digests=review.authority.evidence_record_digests,
            target_work_areas=(target,),
            reason=reason,
            created_by=actor,
            created_at=created_at,
        ).sealed()
        self._validate_sealed(proposal)
        key = (proposal.organization_id, idempotency_key)
        with self._coordinator.mutation(), self._lock:
            existing_for_key = self._by_idempotency.get(key)
            if existing_for_key is not None:
                if not self._proposal_matches_intent(existing_for_key, proposal):
                    raise ExternalReobservationProposalConflictError(
                        "EXTERNAL_REOBSERVATION_PROPOSAL_CONFLICT"
                    )
                return existing_for_key.model_copy(deep=True)
            existing_by_ref = self._by_ref.get(proposal.proposal_ref)
            if existing_by_ref is not None:
                if not self._proposal_matches_intent(existing_by_ref, proposal):
                    raise ExternalReobservationProposalConflictError(
                        "EXTERNAL_REOBSERVATION_PROPOSAL_CONFLICT"
                    )
                # A later key for the same immutable intent is safe to bind to the
                # existing durable proposal.  Persist it as the same event shape
                # so restart preserves retry semantics.
                raw = {
                    "kind": _EVENT_KIND,
                    "version": _VERSION,
                    "proposal": external_reobservation_proposal_wire_dict(existing_by_ref),
                    "idempotencyKey": idempotency_key,
                }
                raw["eventDigest"] = _event_digest(raw)
                self._journal.append(raw)
                self._apply(raw)
                return existing_by_ref.model_copy(deep=True)
            if self._journal.sealed_reason is not None:
                raise JournalSealedError(self._journal.sealed_reason)
            raw = {
                "kind": _EVENT_KIND,
                "version": _VERSION,
                "proposal": external_reobservation_proposal_wire_dict(proposal),
                "idempotencyKey": idempotency_key,
            }
            raw["eventDigest"] = _event_digest(raw)
            self._journal.append(raw)
            self._apply(raw)
            return proposal.model_copy(deep=True)

    @staticmethod
    def _proposal_matches_intent(
        existing: ExternalReobservationProposalV1,
        proposal: ExternalReobservationProposalV1,
    ) -> bool:
        return (
            existing.organization_id == proposal.organization_id
            and existing.review_ref == proposal.review_ref
            and existing.review_digest == proposal.review_digest
            and existing.target_work_areas == proposal.target_work_areas
            and existing.reason == proposal.reason
        )

    def recover_create_retry(
        self,
        *,
        organization_id: str,
        report_ref: str,
        target_work_area_ids: tuple[str, ...],
        reason: str | None,
        idempotency_key: str,
    ) -> ExternalReobservationProposalV1 | None:
        """Return only the exact durable proposal for a lost-response retry.

        This deliberately uses the retained human intent rather than current
        report or WorkArea state.  A later administrative close must not turn a
        response to an already durable proposal into a fresh authority lookup.
        """

        with self._lock:
            existing = self._by_idempotency.get((organization_id, idempotency_key))
            if existing is None:
                return None
            if (
                existing.report_ref != report_ref
                or tuple(item.work_area_id for item in existing.target_work_areas)
                != target_work_area_ids
                or existing.reason != reason
            ):
                raise ExternalReobservationProposalConflictError(
                    "EXTERNAL_REOBSERVATION_PROPOSAL_CONFLICT"
                )
            return existing.model_copy(deep=True)

    def get_scoped(
        self, proposal_ref: str, *, organization_id: str
    ) -> ExternalReobservationProposalV1 | None:
        with self._lock:
            proposal = self._by_ref.get(proposal_ref)
            if proposal is None or proposal.organization_id != organization_id:
                return None
            return proposal.model_copy(deep=True)

    def organization_ids(self) -> frozenset[str]:
        """Durable owners for startup verification, including orphaned records."""
        with self._lock:
            return frozenset(item.organization_id for item in self._by_ref.values())

    def list_scoped(self, *, organization_id: str) -> tuple[ExternalReobservationProposalV1, ...]:
        """Return sealed proposals for read-only startup graph validation."""

        with self._lock:
            records = [
                proposal.model_copy(deep=True)
                for proposal in self._by_ref.values()
                if proposal.organization_id == organization_id
            ]
        return tuple(sorted(records, key=lambda proposal: proposal.proposal_ref))

    def resolve_historical(
        self,
        *,
        proposal_ref: str,
        version: int,
        proposal_digest: str,
        evaluated_at: datetime,
    ) -> ExternalReobservationProposalV1 | None:
        """Return only a sealed proposal that existed at the requested instant."""

        _require_utc(evaluated_at, field="evaluated_at")
        if type(version) is not int or isinstance(version, bool):
            return None
        with self._lock:
            proposal = self._by_ref.get(proposal_ref)
            if proposal is None:
                return None
            candidate = proposal.model_copy(deep=True)
        if (
            candidate.version != version
            or candidate.proposal_digest != proposal_digest
            or candidate.created_at > evaluated_at
        ):
            return None
        try:
            self._validate_sealed(candidate)
        except ValueError:
            return None
        return candidate


@dataclass(frozen=True, slots=True)
class _HistoricalProposalLineage:
    proposal: ExternalReobservationProposalV1
    review: ExternalResultReviewReceiptV1
    target: ExternalWorkAreaSnapshotV1


@dataclass(frozen=True, slots=True)
class _CurrentApprovalWitness:
    """Request-scoped preflight facts, never a mutable authority cache."""

    organization_id: str
    principal: Principal
    actor: str
    approval_input_digest: str
    review: ExternalResultReviewReceiptV1
    source: ExternalResultReviewSourceV1
    evaluated_at: datetime


_CURRENT_APPROVAL_WITNESS: ContextVar[_CurrentApprovalWitness | None] = ContextVar(
    "external_reobservation_current_approval_witness", default=None
)


class CoreExternalReobservationProposalAuthorityPort(ExternalReobservationProposalAuthorityPort):
    """Join review/proposal/Site/WorkArea currentness for the 5A kernel.

    The report source is preflighted before acquiring the shared coordinator.
    Once held, only retained local projections are rechecked and the guard stays
    open until 5A has completed its one WorkOrder journal append.
    """

    def __init__(
        self,
        *,
        reviews: ExternalResultReviewStore,
        proposals: ExternalReobservationProposalStore,
        sites: SiteStore,
        work_areas: WorkAreaStore,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        if not (
            reviews.coordinator is coordinator
            and proposals.coordinator is coordinator
            and sites.coordinator is coordinator
            and work_areas.coordinator is coordinator
        ):
            raise ValueError("external proposal authority participants must share one coordinator")
        self._reviews = reviews
        self._proposals = proposals
        self._sites = sites
        self._work_areas = work_areas
        self._coordinator = coordinator

    def uses_exact_participants(
        self,
        *,
        reviews: ExternalResultReviewStore,
        proposals: ExternalReobservationProposalStore,
        sites: SiteStore,
        work_areas: WorkAreaStore,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> bool:
        """Read-only identity assertion; never replace replay-time dependencies."""
        return (
            self._reviews is reviews
            and self._proposals is proposals
            and self._sites is sites
            and self._work_areas is work_areas
            and self._coordinator is coordinator
        )

    def _historical_lineage(
        self,
        *,
        organization_id: str,
        approval_input: ExternalReobservationApprovalInputV1,
        actor: str,
        approved_at: datetime,
    ) -> _HistoricalProposalLineage | None:
        if not is_path_safe_identifier(actor):
            return None
        proposal = self._proposals.resolve_historical(
            proposal_ref=approval_input.proposal_id,
            version=approval_input.proposal_version,
            proposal_digest=approval_input.proposal_digest,
            evaluated_at=approved_at,
        )
        if proposal is None or proposal.organization_id != organization_id:
            return None
        proposal_review = self._reviews.verify_historical(
            review_ref=proposal.review_ref,
            review_digest=proposal.review_digest,
            evaluated_at=proposal.created_at,
        )
        approval_review = self._reviews.resolve_historical(
            review_ref=proposal.review_ref,
            review_digest=proposal.review_digest,
            actor=actor,
            evaluated_at=approved_at,
        )
        if (
            proposal_review is None
            or approval_review is None
            or proposal_review != approval_review
            or not self._proposal_matches_review(proposal, approval_review)
        ):
            return None
        review = approval_review
        target: ExternalWorkAreaSnapshotV1 | None = None
        for at in (review.reviewed_at, proposal.created_at, approved_at):
            site = self._sites.historical_scoped_identity(
                proposal.site_id, organization_id=organization_id, at=at
            )
            area = self._work_areas.historical_active(
                proposal.target_work_areas[0].work_area_id,
                site_id=proposal.site_id,
                at=at,
            )
            if site is None or area is None:
                return None
            target = _target_matches_review(review, area)
            if target is None or target != proposal.target_work_areas[0]:
                return None
        assert target is not None
        return _HistoricalProposalLineage(proposal=proposal, review=review, target=target)

    @staticmethod
    def _proposal_matches_review(
        proposal: ExternalReobservationProposalV1, review: ExternalResultReviewReceiptV1
    ) -> bool:
        return (
            proposal.organization_id == review.organization_id
            and proposal.site_id == review.site_id
            and proposal.source_work_order_id == review.source_work_order_id
            and proposal.review_ref == review.review_ref
            and proposal.review_digest == review.review_digest
            and proposal.report_ref == review.report_ref
            and proposal.report_digest == review.report.report_digest
            and proposal.decision_digest == review.decision.decision_digest
            and proposal.zone_digest == review.authority.zone_snapshot.definition_digest
            and proposal.evidence_digests == review.authority.evidence_record_digests
            and proposal.target_work_areas == (_review_target(review),)
        )

    def resolve_historical(
        self,
        *,
        organization_id: str,
        approval_input: ExternalReobservationApprovalInputV1,
        actor: str,
        approved_at: datetime,
    ) -> ExternalReobservationProposalAuthorityV1 | None:
        _require_utc(approved_at, field="approved_at")
        lineage = self._historical_lineage(
            organization_id=organization_id,
            approval_input=approval_input,
            actor=actor,
            approved_at=approved_at,
        )
        if lineage is None:
            return None
        authority = lineage.proposal.approval_authority()
        return authority if _approval_input_matches(approval_input, authority) else None

    def verify_proposal_historical(self, proposal: ExternalReobservationProposalV1) -> bool:
        """Verify unapproved proposal lineage without inventing an approval actor."""

        try:
            self._proposals._validate_sealed(proposal)
        except ValueError:
            return False
        recovered = self._proposals.resolve_historical(
            proposal_ref=proposal.proposal_ref,
            version=proposal.version,
            proposal_digest=proposal.proposal_digest or "",
            evaluated_at=proposal.created_at,
        )
        if recovered != proposal:
            return False
        review = self._reviews.verify_historical(
            review_ref=proposal.review_ref,
            review_digest=proposal.review_digest,
            evaluated_at=proposal.created_at,
        )
        if review is None or not self._proposal_matches_review(proposal, review):
            return False
        for at in (review.reviewed_at, proposal.created_at):
            site = self._sites.historical_scoped_identity(
                proposal.site_id, organization_id=proposal.organization_id, at=at
            )
            area = self._work_areas.historical_active(
                proposal.target_work_areas[0].work_area_id,
                site_id=proposal.site_id,
                at=at,
            )
            if site is None or area is None:
                return False
            if _target_matches_review(review, area) != proposal.target_work_areas[0]:
                return False
        return True

    @contextmanager
    def preflight_approval(
        self,
        *,
        principal: Principal,
        organization_id: str,
        approval_input: ExternalReobservationApprovalInputV1,
        evaluated_at: datetime,
    ) -> Iterator[bool]:
        """Resolve current facts with the real approver before invoking 5A.

        The accepted 5A port contract intentionally has no Principal.  This
        ContextVar is immutable, request-scoped, reset in ``finally``, and
        cannot make a following request current.  The nested 5A guard consumes
        it only for the exact sealed input and still rechecks retained facts.
        """

        _require_utc(evaluated_at, field="evaluated_at")
        # Every nested entry shadows an outer request before any validation.
        # A denied request must not retain another request's live witness while
        # it runs its failure path.
        shadow_token = _CURRENT_APPROVAL_WITNESS.set(None)
        witness_token = None
        try:
            if (
                principal.organization_id != organization_id
                or approval_input.organization_id != organization_id
                or approval_input.approval_input_digest is None
                or not is_path_safe_identifier(principal.principal_id)
            ):
                yield False
                return
            proposal = self._proposals.get_scoped(
                approval_input.proposal_id, organization_id=organization_id
            )
            if proposal is None or proposal.version != approval_input.proposal_version:
                yield False
                return
            review = self._reviews.get_scoped(proposal.review_ref, organization_id=organization_id)
            if review is None or not self._proposal_matches_review(proposal, review):
                yield False
                return
            source = self._reviews.preflight_current_source(
                review, principal=principal, evaluated_at=evaluated_at
            )
            authority = proposal.approval_authority()
            if (
                source is None
                or principal.principal_id not in source.authority.authorized_actor_ids
                or not _approval_input_matches(approval_input, authority)
            ):
                yield False
                return
            witness = _CurrentApprovalWitness(
                organization_id=organization_id,
                principal=principal,
                actor=principal.principal_id,
                approval_input_digest=approval_input.approval_input_digest,
                review=review,
                source=source,
                evaluated_at=evaluated_at,
            )
            witness_token = _CURRENT_APPROVAL_WITNESS.set(witness)
            yield True
        finally:
            if witness_token is not None:
                _CURRENT_APPROVAL_WITNESS.reset(witness_token)
            _CURRENT_APPROVAL_WITNESS.reset(shadow_token)

    @contextmanager
    def guard_current(
        self,
        *,
        organization_id: str,
        approval_input: ExternalReobservationApprovalInputV1,
        actor: str,
        evaluated_at: datetime,
    ) -> Iterator[ExternalReobservationProposalAuthorityV1 | None]:
        _require_utc(evaluated_at, field="evaluated_at")
        witness = _CURRENT_APPROVAL_WITNESS.get()
        if (
            witness is None
            or witness.organization_id != organization_id
            or witness.actor != actor
            or witness.evaluated_at != evaluated_at
            or witness.approval_input_digest != approval_input.approval_input_digest
            or actor not in witness.source.authority.authorized_actor_ids
        ):
            yield None
            return
        proposal = self._proposals.get_scoped(
            approval_input.proposal_id, organization_id=organization_id
        )
        if proposal is None or proposal.version != approval_input.proposal_version:
            yield None
            return
        review = self._reviews.get_scoped(proposal.review_ref, organization_id=organization_id)
        if (
            review is None
            or review != witness.review
            or not self._proposal_matches_review(proposal, review)
        ):
            yield None
            return
        with self._coordinator.guarded_read():
            if not self._reviews.local_source_is_current(
                review, witness.source, principal=witness.principal, evaluated_at=evaluated_at
            ):
                yield None
                return
            current_proposal = self._proposals.get_scoped(
                proposal.proposal_ref, organization_id=organization_id
            )
            site = self._sites.get_scoped(proposal.site_id, organization_id)
            area = self._work_areas.get(proposal.target_work_areas[0].work_area_id)
            if (
                current_proposal != proposal
                or site is None
                or area is None
                or area.site_id != proposal.site_id
                or area.status is not WorkAreaStatus.ACTIVE
                or _target_matches_review(review, area) != proposal.target_work_areas[0]
            ):
                yield None
                return
            authority = proposal.approval_authority()
            yield authority if _approval_input_matches(approval_input, authority) else None


@dataclass(frozen=True, slots=True)
class ExternalReobservationProposalService:
    """Trusted orchestration used by an HTTP router and direct Core callers."""

    reviews: ExternalResultReviewStore
    proposals: ExternalReobservationProposalStore
    sites: SiteStore
    work_areas: WorkAreaStore
    work_orders: ObservationWorkOrderStore
    authority_port: CoreExternalReobservationProposalAuthorityPort
    coordinator: ExternalAuthorityCurrentnessCoordinator
    approval_listeners: list[Callable[[ExternalReobservationApprovalReceiptV1], None]] = field(
        default_factory=list, compare=False, repr=False
    )

    def bind_approval_listener(
        self, listener: Callable[[ExternalReobservationApprovalReceiptV1], None]
    ) -> None:
        """Bind a post-commit projection; approval never depends on it."""
        if listener not in self.approval_listeners:
            self.approval_listeners.append(listener)

    def _notify_approval_listeners(
        self, receipt: ExternalReobservationApprovalReceiptV1
    ) -> None:
        for listener in tuple(self.approval_listeners):
            try:
                listener(receipt)
            except Exception:
                _LOGGER.exception(
                    "external reobservation approval listener failed",
                    extra={"successor_work_order_id": receipt.successor_work_order_id},
                )

    def __post_init__(self) -> None:
        if not (
            self.reviews.coordinator is self.coordinator
            and self.proposals.coordinator is self.coordinator
            and self.sites.coordinator is self.coordinator
            and self.work_areas.coordinator is self.coordinator
        ):
            raise ValueError("proposal service participants must share one coordinator")
        if not self.authority_port.uses_exact_participants(
            reviews=self.reviews,
            proposals=self.proposals,
            sites=self.sites,
            work_areas=self.work_areas,
            coordinator=self.coordinator,
        ):
            raise ValueError("proposal service authority must use its exact durable participants")
        if not self.work_orders.uses_external_reobservation_authority(self.authority_port):
            raise ValueError("proposal service must use the WorkOrder replay authority")

    def create(
        self,
        *,
        organization_id: str,
        report_ref: str,
        target_work_area_ids: tuple[str, ...],
        reason: str | None,
        principal: Principal,
        actor: str,
        now: datetime,
        idempotency_key: str,
    ) -> ExternalReobservationProposalV1:
        _require_utc(now, field="now")
        if principal.organization_id != organization_id or actor != principal.principal_id:
            raise ValueError("proposal actor must be the scoped authenticated principal")
        if len(target_work_area_ids) != 1:
            raise ExternalReobservationProposalUnavailableError(
                "EXACTLY_ONE_REPORT_ZONE_TARGET_REQUIRED"
            )
        retained_retry = self.proposals.recover_create_retry(
            organization_id=organization_id,
            report_ref=report_ref,
            target_work_area_ids=target_work_area_ids,
            reason=reason,
            idempotency_key=idempotency_key,
        )
        if retained_retry is not None:
            return retained_retry
        review = self.reviews.get_for_report(report_ref, organization_id=organization_id)
        if review is None:
            raise LookupError("external result report review was not found")
        source = self.reviews.preflight_current_source(
            review, principal=principal, evaluated_at=now
        )
        if source is None:
            raise ExternalReobservationProposalUnavailableError(
                "EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE"
            )
        target_id = target_work_area_ids[0]
        with self.work_orders.guard_new_external_intent(
            review.source_work_order_id, organization_id=organization_id
        ), self.coordinator.mutation():
            if not self.reviews.local_source_is_current(
                review, source, principal=principal, evaluated_at=now
            ):
                raise ExternalReobservationProposalUnavailableError(
                    "EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE"
                )
            site = self.sites.get_scoped(review.site_id, organization_id)
            area = self.work_areas.get(target_id)
            if (
                site is None
                or area is None
                or area.site_id != review.site_id
                or area.status is not WorkAreaStatus.ACTIVE
            ):
                raise ExternalReobservationProposalUnavailableError(
                    "EXTERNAL_REOBSERVATION_TARGET_UNAVAILABLE"
                )
            target = _target_matches_review(review, area)
            if target is None:
                raise ExternalReobservationProposalUnavailableError(
                    "EXTERNAL_REOBSERVATION_TARGET_NOT_REPORT_ZONE"
                )
            return self.proposals.create(
                review=review,
                target=target,
                reason=reason,
                actor=actor,
                created_at=now,
                idempotency_key=idempotency_key,
            )

    def approve(
        self,
        *,
        organization_id: str,
        proposal_ref: str,
        expected_version: int,
        principal: Principal,
        actor: str,
        now: datetime,
        idempotency_key: str,
    ) -> ExternalReobservationApprovalResult:
        if principal.organization_id != organization_id or actor != principal.principal_id:
            raise ValueError("approval actor must be the scoped authenticated principal")
        proposal = self.proposals.get_scoped(proposal_ref, organization_id=organization_id)
        if proposal is None:
            raise LookupError("external reobservation proposal was not found")
        if proposal.version != expected_version:
            raise ExternalReobservationProposalConflictError(
                "EXTERNAL_REOBSERVATION_PROPOSAL_VERSION_CONFLICT"
            )
        approval_input = _approval_input_for(proposal)
        existing = self.work_orders.get_external_reobservation_approval(
            proposal_ref,
            expected_version=expected_version,
            organization_id=organization_id,
        )
        if existing is not None:
            # 5A owns the exact idempotent result.  It returns before either
            # historical or current authority resolution, which preserves the
            # original receipt after a client loses the HTTP response and later
            # current authority is revoked.
            return self.work_orders.approve_external_reobservation(
                approval_input,
                organization_id=organization_id,
                actor=actor,
                now=now,
                idempotency_key=idempotency_key,
            )
        with self.authority_port.preflight_approval(
            principal=principal,
            organization_id=organization_id,
            approval_input=approval_input,
            evaluated_at=now,
        ) as available:
            if not available:
                raise ExternalReobservationProposalUnavailableError(
                    "EXTERNAL_REOBSERVATION_CURRENT_AUTHORITY_UNAVAILABLE"
                )
            approved = self.work_orders.approve_external_reobservation(
                approval_input,
                organization_id=organization_id,
                actor=actor,
                now=now,
                idempotency_key=idempotency_key,
            )
        self._notify_approval_listeners(approved.approval_receipt)
        return approved

    def approval_receipt(
        self,
        *,
        organization_id: str,
        proposal_ref: str,
        expected_version: int,
    ) -> ExternalReobservationApprovalReceiptV1 | None:
        proposal = self.proposals.get_scoped(proposal_ref, organization_id=organization_id)
        if proposal is None or proposal.version != expected_version:
            return None
        return self.work_orders.get_external_reobservation_approval(
            proposal_ref,
            expected_version=expected_version,
            organization_id=organization_id,
        )


def _approval_input_for(
    proposal: ExternalReobservationProposalV1,
) -> ExternalReobservationApprovalInputV1:
    if proposal.proposal_digest is None:
        raise ValueError("proposal must be sealed")
    return ExternalReobservationApprovalInputV1(
        organization_id=proposal.organization_id,
        site_id=proposal.site_id,
        source_work_order_id=proposal.source_work_order_id,
        proposal_id=proposal.proposal_ref,
        proposal_version=proposal.version,
        proposal_digest=proposal.proposal_digest,
        report_digest=proposal.report_digest,
        decision_digest=proposal.decision_digest,
        zone_digest=proposal.zone_digest,
        evidence_digests=proposal.evidence_digests,
    ).sealed()


def _approval_input_matches(
    approval_input: ExternalReobservationApprovalInputV1,
    authority: ExternalReobservationProposalAuthorityV1,
) -> bool:
    return (
        approval_input.organization_id == authority.organization_id
        and approval_input.site_id == authority.site_id
        and approval_input.source_work_order_id == authority.source_work_order_id
        and approval_input.proposal_id == authority.proposal_id
        and approval_input.proposal_version == authority.proposal_version
        and approval_input.proposal_digest == authority.proposal_digest
        and approval_input.report_digest == authority.report_digest
        and approval_input.decision_digest == authority.decision_digest
        and approval_input.zone_digest == authority.zone_digest
        and approval_input.evidence_digests == authority.evidence_digests
    )


class ExternalReobservationProposalCreateRequest(CamelModel):
    report_ref: str = Field(min_length=1, max_length=255)
    target_work_area_ids: tuple[str, ...] = Field(min_length=1, max_length=1)
    reason: str | None = Field(default=None, min_length=1, max_length=1_000)

    @field_validator("report_ref", "target_work_area_ids", mode="after")
    @classmethod
    def _path_safe_identifiers(cls, value: Any) -> Any:
        values = (value,) if isinstance(value, str) else value
        if not all(is_path_safe_identifier(item) for item in values):
            raise ValueError("identifiers must be path-safe")
        return value


class ExternalReobservationProposalApprovalRequest(CamelModel):
    """The entire public approval body: no scope, digests, or source authority."""

    proposal_ref: str = Field(min_length=1, max_length=255)
    expected_version: int = Field(ge=1)

    @field_validator("proposal_ref")
    @classmethod
    def _proposal_ref_path_safe(cls, value: str) -> str:
        if not is_path_safe_identifier(value):
            raise ValueError("proposalRef must be path-safe")
        return value


class ExternalReobservationProposalView(CamelModel):
    proposal: ExternalReobservationProposalV1
    approval_receipt: ExternalReobservationApprovalReceiptV1 | None = None


def build_external_reobservation_proposal_router(
    service: ExternalReobservationProposalService,
    *,
    clock: Callable[[], datetime] | None = None,
) -> APIRouter:
    """Return an unmounted human router; app assembly and OpenAPI remain Root-owned."""

    now = clock or (lambda: datetime.now(UTC))
    router = APIRouter(
        prefix="/v1/external-reobservation-proposals", tags=["external-reobservation"]
    )

    @router.post("", response_model=ExternalReobservationProposalView, status_code=201)
    def create_proposal(
        request: ExternalReobservationProposalCreateRequest,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        principal: Principal = Depends(require_permission(Permission.WORK_ORDERS_WRITE)),  # noqa: B008
    ) -> ExternalReobservationProposalView:
        try:
            proposal = service.create(
                organization_id=principal.organization_id,
                report_ref=request.report_ref,
                target_work_area_ids=request.target_work_area_ids,
                reason=request.reason,
                principal=principal,
                actor=principal.principal_id,
                now=now(),
                idempotency_key=idempotency_key,
            )
        except LookupError as exc:
            raise HTTPException(
                status_code=404, detail="external result report review was not found"
            ) from exc
        except ExternalReobservationProposalConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            if str(exc) == "EXTERNAL_WORKFLOW_CLOSED":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise
        except (ExternalReobservationProposalUnavailableError, JournalSealedError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ExternalReobservationProposalView(proposal=proposal)

    @router.post("/approve", response_model=ExternalReobservationProposalView)
    def approve_proposal(
        request: ExternalReobservationProposalApprovalRequest,
        idempotency_key: str = Header(alias="Idempotency-Key"),
        principal: Principal = Depends(require_permission(Permission.REOBSERVATION_APPROVE)),  # noqa: B008
    ) -> ExternalReobservationProposalView:
        try:
            service.approve(
                organization_id=principal.organization_id,
                proposal_ref=request.proposal_ref,
                expected_version=request.expected_version,
                principal=principal,
                actor=principal.principal_id,
                now=now(),
                idempotency_key=idempotency_key,
            )
        except LookupError as exc:
            raise HTTPException(
                status_code=404, detail="external reobservation proposal was not found"
            ) from exc
        except ExternalReobservationProposalConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (RuntimeError, JournalSealedError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        proposal = service.proposals.get_scoped(
            request.proposal_ref, organization_id=principal.organization_id
        )
        assert proposal is not None
        return ExternalReobservationProposalView(
            proposal=proposal,
            approval_receipt=service.approval_receipt(
                organization_id=principal.organization_id,
                proposal_ref=request.proposal_ref,
                expected_version=request.expected_version,
            ),
        )

    return router


def verify_external_reobservation_graph(*, service: ExternalReobservationProposalService) -> None:
    """Fail startup on any dangling durable lineage, even without an approval."""
    organizations = (
        service.reviews.organization_ids()
        | service.proposals.organization_ids()
        | service.work_orders.external_reobservation_organization_ids()
    )
    for organization_id in sorted(organizations):
        verify_external_reobservation_organization_graph(
            organization_id=organization_id,
            work_orders=service.work_orders,
            authority_port=service.authority_port,
        )


def verify_external_reobservation_organization_graph(
    *,
    organization_id: str,
    work_orders: ObservationWorkOrderStore,
    authority_port: CoreExternalReobservationProposalAuthorityPort,
) -> None:
    """Verify every durable review/proposal and kernel receipt before mount."""

    for review in authority_port._reviews.list_scoped(organization_id=organization_id):
        historical_review = authority_port._reviews.verify_historical(
            review_ref=review.review_ref,
            review_digest=review.review_digest or "",
            evaluated_at=review.reviewed_at,
        )
        if historical_review != review:
            raise ExternalReobservationProposalRecoveryError(
                "durable review historical lineage is invalid"
            )
    for proposal in authority_port._proposals.list_scoped(organization_id=organization_id):
        if not authority_port.verify_proposal_historical(proposal):
            raise ExternalReobservationProposalRecoveryError(
                "durable proposal historical lineage is invalid"
            )

    for binding in work_orders.list_external_reobservation_bindings(
        organization_id=organization_id
    ):
        receipt = work_orders.get_external_reobservation_approval(
            binding.proposal_id,
            expected_version=binding.proposal_version,
            organization_id=organization_id,
        )
        if receipt is None:
            raise ExternalReobservationProposalRecoveryError(
                "approval binding has no joined receipt"
            )
        binding_proposal = authority_port._proposals.get_scoped(
            binding.proposal_id, organization_id=organization_id
        )
        if binding_proposal is None:
            raise ExternalReobservationProposalRecoveryError(
                "approval binding has no durable proposal"
            )
        approval_input = _approval_input_for(binding_proposal)
        authority = authority_port.resolve_historical(
            organization_id=organization_id,
            approval_input=approval_input,
            actor=receipt.approved_by,
            approved_at=receipt.approved_at,
        )
        if (
            authority is None
            or authority.authority_digest != binding_proposal.approval_authority().authority_digest
        ):
            raise ExternalReobservationProposalRecoveryError(
                "approval binding historical lineage is invalid"
            )


__all__ = [
    "CoreExternalReobservationProposalAuthorityPort",
    "ExternalReobservationProposalApprovalRequest",
    "ExternalReobservationProposalConflictError",
    "ExternalReobservationProposalCreateRequest",
    "ExternalReobservationProposalRecoveryError",
    "ExternalReobservationProposalService",
    "ExternalReobservationProposalStore",
    "ExternalReobservationProposalUnavailableError",
    "ExternalReobservationProposalView",
    "build_external_reobservation_proposal_router",
    "verify_external_reobservation_organization_graph",
]
