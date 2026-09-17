"""Join real Core report provenance, exact decisions, and independent use authority.

Relative and single-volume reports are both reviewable.  A report ref is
routed to the single family only when a single store is configured and the ref
carries the single report prefix; every other ref keeps the relative path.
"""

from dataclasses import fields
from datetime import datetime
from typing import Any

from ksi_event_contracts.external_result_review import ExternalResultReviewAuthorityV1
from ksi_event_contracts.external_single_volume_result_review import (
    ExternalSingleVolumeResultReviewAuthorityV1,
)

from ksi_core.domains.external.quantity.external_relative_volume_use_history import (
    ExternalRelativeVolumeHistoricalUseAuthorityPort,
)
from ksi_core.domains.external.quantity.external_relative_volumes import (
    ExternalRelativeVolumeExecutionAuthority,
    ExternalRelativeVolumeStore,
    ResolvedRelativeVolumeReport,
)
from ksi_core.domains.external.quantity.external_single_volume_use_history import (
    ExternalSingleVolumeHistoricalUseAuthorityPort,
)
from ksi_core.domains.external.quantity.external_single_volumes import (
    ExternalSingleVolumeExecutionAuthority,
    ExternalSingleVolumeStore,
    ResolvedSingleVolumeReport,
)
from ksi_core.domains.external.quantity.external_use_decisions import ExternalUseDecisionStore
from ksi_core.domains.external.workflow.external_result_reviews import (
    ExternalResultReviewSource,
    ExternalResultReviewSourceV1,
    ExternalSingleVolumeResultReviewSourceV1,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.identity.auth import Principal

_SINGLE_REPORT_PREFIX = "external-single-volume-report-"


def _execution_authority(
    authority: ExternalResultReviewAuthorityV1,
) -> ExternalRelativeVolumeExecutionAuthority:
    # Preserve Python scalar types; JSON serialization must not normalize an
    # unsafe copied Boolean before strict execution-authority validation.
    values: dict[str, Any] = {
        field.name: getattr(authority, field.name)
        for field in fields(ExternalRelativeVolumeExecutionAuthority)
    }
    values["authorized_actor_ids"] = frozenset(authority.authorized_actor_ids)
    return ExternalRelativeVolumeExecutionAuthority(**values)


def _single_execution_authority(
    authority: ExternalSingleVolumeResultReviewAuthorityV1,
) -> ExternalSingleVolumeExecutionAuthority:
    # Same scalar-preserving reconstruction as the relative family.
    values: dict[str, Any] = {
        field.name: getattr(authority, field.name)
        for field in fields(ExternalSingleVolumeExecutionAuthority)
    }
    values["authorized_actor_ids"] = frozenset(authority.authorized_actor_ids)
    return ExternalSingleVolumeExecutionAuthority(**values)


class CoreExternalResultReviewSourceAdapter:
    def __init__(
        self,
        *,
        volume_store: ExternalRelativeVolumeStore,
        decisions: ExternalUseDecisionStore,
        historical_use_authority: ExternalRelativeVolumeHistoricalUseAuthorityPort,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
        single_volume_store: ExternalSingleVolumeStore | None = None,
        single_historical_use_authority: ExternalSingleVolumeHistoricalUseAuthorityPort
        | None = None,
    ) -> None:
        if volume_store.coordinator is not coordinator or decisions.coordinator is not coordinator:
            raise ValueError("review source participants must share one coordinator")
        if (single_volume_store is None) != (single_historical_use_authority is None):
            raise ValueError("single-volume review source needs both its store and its use history")
        if single_volume_store is not None and single_volume_store.coordinator is not coordinator:
            raise ValueError("review source participants must share one coordinator")
        self._volumes = volume_store
        self._decisions = decisions
        self._history = historical_use_authority
        self._single_volumes = single_volume_store
        self._single_history = single_historical_use_authority

    def uses_volume_store(self, store: ExternalRelativeVolumeStore) -> bool:
        """Expose only immutable constructor identity for HTTP graph assembly."""
        return self._volumes is store

    def uses_single_volume_store(self, store: ExternalSingleVolumeStore) -> bool:
        """Expose only immutable constructor identity for HTTP graph assembly."""
        return self._single_volumes is not None and self._single_volumes is store

    def _is_single(self, report_ref: str) -> bool:
        return self._single_volumes is not None and report_ref.startswith(_SINGLE_REPORT_PREFIX)

    # -- relative family ------------------------------------------------------------------

    def _join(self, resolved: ResolvedRelativeVolumeReport) -> ExternalResultReviewSourceV1 | None:
        authority = resolved.execution_authority
        decision = self._decisions.resolve_historical_pair(
            organization_id=authority.organization_id,
            site_id=authority.site_id,
            decision_id=authority.decision_id,
            decision_digest=authority.decision_digest,
        )
        if decision is None:
            return None
        review_authority = ExternalResultReviewAuthorityV1.model_validate(
            authority.snapshot_payload()
        ).sealed()
        return ExternalResultReviewSourceV1(
            report_ref=resolved.report.report_id,
            request=resolved.request,
            report=resolved.report,
            authority=review_authority,
            decision=decision,
        )

    # -- single family --------------------------------------------------------------------

    def _join_single(
        self, resolved: ResolvedSingleVolumeReport
    ) -> ExternalSingleVolumeResultReviewSourceV1 | None:
        authority = resolved.execution_authority
        decision = self._decisions.resolve_historical_single_volume(
            organization_id=authority.organization_id,
            site_id=authority.site_id,
            decision_id=authority.decision_id,
            decision_digest=authority.decision_digest,
        )
        if decision is None:
            return None
        review_authority = ExternalSingleVolumeResultReviewAuthorityV1.model_validate(
            authority.snapshot_payload()
        ).sealed()
        return ExternalSingleVolumeResultReviewSourceV1(
            report_ref=resolved.report.report_id,
            request=resolved.request,
            report=resolved.report,
            authority=review_authority,
            decision=decision,
        )

    def resolve_current(
        self, *, organization_id: str, report_ref: str, principal: Principal, evaluated_at: datetime
    ) -> ExternalResultReviewSource | None:
        if principal.organization_id != organization_id:
            return None
        if self._is_single(report_ref):
            return self._resolve_current_single(
                organization_id=organization_id,
                report_ref=report_ref,
                principal=principal,
                evaluated_at=evaluated_at,
            )
        resolved = self._volumes.preflight_current_report_ref(
            report_ref, organization_id=organization_id, principal=principal, now=evaluated_at
        )
        if (
            resolved is None
            or resolved.report.reported_at > evaluated_at
            or principal.principal_id not in resolved.execution_authority.authorized_actor_ids
            or not resolved.execution_authority.is_current_at(evaluated_at)
            or not self._history_permits(resolved.execution_authority, evaluated_at=evaluated_at)
        ):
            return None
        return self._join(resolved)

    def _resolve_current_single(
        self, *, organization_id: str, report_ref: str, principal: Principal, evaluated_at: datetime
    ) -> ExternalSingleVolumeResultReviewSourceV1 | None:
        assert self._single_volumes is not None
        resolved = self._single_volumes.preflight_current_report_ref(
            report_ref, organization_id=organization_id, principal=principal, now=evaluated_at
        )
        if (
            resolved is None
            or resolved.report.reported_at > evaluated_at
            or principal.principal_id not in resolved.execution_authority.authorized_actor_ids
            or not resolved.execution_authority.is_current_at(evaluated_at)
            or not self._single_history_permits(
                resolved.execution_authority, evaluated_at=evaluated_at
            )
        ):
            return None
        return self._join_single(resolved)

    def resolve_historical(
        self, *, organization_id: str, report_ref: str, report_digest: str, evaluated_at: datetime
    ) -> ExternalResultReviewSource | None:
        if self._is_single(report_ref):
            assert self._single_volumes is not None
            single = self._single_volumes.resolve_historical_report_ref(
                report_ref, organization_id=organization_id, now=evaluated_at
            )
            if (
                single is None
                or single.report.reported_at > evaluated_at
                or single.report.report_digest != report_digest
                or not self._single_history_permits(
                    single.execution_authority, evaluated_at=evaluated_at
                )
            ):
                return None
            return self._join_single(single)
        resolved = self._volumes.resolve_historical_report_ref(
            report_ref, organization_id=organization_id, now=evaluated_at
        )
        if (
            resolved is None
            or resolved.report.reported_at > evaluated_at
            or resolved.report.report_digest != report_digest
        ):
            return None
        if not self._history_permits(resolved.execution_authority, evaluated_at=evaluated_at):
            return None
        return self._join(resolved)

    def _history_permits(
        self, retained: ExternalRelativeVolumeExecutionAuthority, *, evaluated_at: datetime
    ) -> bool:
        # Check replayability before a new durable review, outside the final
        # local guard. Current permission still comes from the actual Principal.
        permitted = self._history.resolve_historical_for_use(
            historical_authority_digest=retained.historical_authority_digest,
            decision_id=retained.decision_id,
            decision_digest=retained.decision_digest,
            evaluated_at=evaluated_at,
        )
        return (
            permitted is not None
            and permitted == retained
            and permitted.is_current_at(evaluated_at)
        )

    def _single_history_permits(
        self, retained: ExternalSingleVolumeExecutionAuthority, *, evaluated_at: datetime
    ) -> bool:
        if self._single_history is None:
            return False
        permitted = self._single_history.resolve_historical_for_use(
            historical_authority_digest=retained.historical_authority_digest,
            decision_id=retained.decision_id,
            decision_digest=retained.decision_digest,
            evaluated_at=evaluated_at,
        )
        return (
            permitted is not None
            and permitted == retained
            and permitted.is_current_at(evaluated_at)
        )

    def is_current(
        self, source: ExternalResultReviewSource, *, principal: Principal, evaluated_at: datetime
    ) -> bool:
        """Local recheck inside the caller's shared coordinator through append."""
        if (
            source.report.reported_at > evaluated_at
            or principal.organization_id != source.authority.organization_id
            or principal.principal_id not in source.authority.authorized_actor_ids
        ):
            return False
        if self._is_single(source.report_ref):
            if not isinstance(source, ExternalSingleVolumeResultReviewSourceV1):
                return False
            return self._single_is_current(source, principal=principal, evaluated_at=evaluated_at)
        if not isinstance(source, ExternalResultReviewSourceV1):
            return False
        try:
            execution = _execution_authority(source.authority)
        except (TypeError, ValueError):
            return False
        witness = ResolvedRelativeVolumeReport(
            request=source.request, report=source.report, execution_authority=execution
        )
        with self._volumes.guard_current_report_ref(
            source.report_ref,
            organization_id=principal.organization_id,
            principal=principal,
            witness=witness,
            now=evaluated_at,
        ) as current:
            return current is not None and self._join(current) == source

    def _single_is_current(
        self,
        source: ExternalSingleVolumeResultReviewSourceV1,
        *,
        principal: Principal,
        evaluated_at: datetime,
    ) -> bool:
        assert self._single_volumes is not None
        try:
            execution = _single_execution_authority(source.authority)
        except (TypeError, ValueError):
            return False
        witness = ResolvedSingleVolumeReport(
            request=source.request, report=source.report, execution_authority=execution
        )
        with self._single_volumes.guard_current_report_ref(
            source.report_ref,
            organization_id=principal.organization_id,
            principal=principal,
            witness=witness,
            now=evaluated_at,
        ) as current:
            return current is not None and self._join_single(current) == source
