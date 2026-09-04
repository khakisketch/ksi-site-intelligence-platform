"""Short OCC commit boundary for Mission issuance (TASK-2).

Route generation, KMZ serialization and Ed25519 signing stay outside this
module's locks.  Only the final witness comparison and Mission journal append
run under the deterministic lock order::

    Site -> WorkOrder (optional) -> Acquisition (optional) -> Mission

The Mission lock is acquired by :meth:`MissionStore.record_issuance` and is
terminal in the audited participating call graph: after entering it the
coordinator never calls back into a prerequisite store.  Actual Site,
WorkOrder and Acquisition mutation paths are exercised concurrently in the
lock regression; any future nested path must preserve the absence of a reverse
edge instead of relying on a blanket "one lock per store" assumption.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ksi_domain.enums import MissionType
from ksi_domain.mission_gating import is_mission_type_allowed_at_site_status
from ksi_event_contracts.observation_work_order import ObservationWorkOrderStatus
from ksi_mission_contracts.signing import canonical_payload_bytes, sha256_digest

from ksi_core.mission_records import (
    AcquisitionAuthorizationWitness,
    IssuanceAuthorizationWitness,
    IssuanceConflictSubreason,
    IssuancePreconditionChangedError,
    MissionRecord,
    MissionRecordVerdict,
    MissionStore,
    SiteLookupResult,
    WorkOrderAuthorizationWitness,
    precheck_issuance,
)
from ksi_core.sites import SiteStore

if TYPE_CHECKING:
    from ksi_core.acquisition.store import AcquisitionConnectivityStore
    from ksi_core.observation_work_orders import ObservationWorkOrderStore


class MissionIssuanceRejected(RuntimeError):
    """Typed pre-signing/domain rejection without coupling stores to FastAPI."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _profile_digest(profile: Any) -> str:
    payload = profile.model_dump(mode="json", by_alias=True)
    return sha256_digest(canonical_payload_bytes(payload))


class MissionIssuanceCommitter:
    """Capture authorization witnesses and conditionally append one MissionRecord."""

    def __init__(
        self,
        *,
        site_store: SiteStore,
        mission_store: MissionStore,
        work_order_store: ObservationWorkOrderStore | None = None,
        acquisition_store: AcquisitionConnectivityStore | None = None,
        acquisition_issue_gate_enabled: bool = False,
    ) -> None:
        if acquisition_issue_gate_enabled and acquisition_store is None:
            raise ValueError("acquisition issue gate에는 Acquisition store가 필요하다")
        self.site_store = site_store
        self.mission_store = mission_store
        self.work_order_store = work_order_store
        self.acquisition_store = acquisition_store
        self.acquisition_issue_gate_enabled = acquisition_issue_gate_enabled

    def _site_lookup(self, site_id: str, organization_id: str) -> SiteLookupResult | None:
        state = self.site_store.issuance_snapshot(site_id, organization_id=organization_id)
        if state is None:
            return None
        return SiteLookupResult(
            site_frame=dict(state.record.site_frame),
            status=state.record.status,
            issuance_revision=state.issuance_revision,
        )

    def capture_site_authorization(
        self,
        *,
        organization_id: str,
        site_id: str,
        mission_id: str,
        mission_type: MissionType,
        requested_site_frame: dict[str, object],
        request_digest: str,
        captured_at: datetime,
    ) -> MissionRecordVerdict | IssuanceAuthorizationWitness:
        if self.site_store.sealed_reason is not None:
            return MissionRecordVerdict.STORE_UNAVAILABLE
        return precheck_issuance(
            mission_store=self.mission_store,
            site_lookup=self._site_lookup,
            organization_id=organization_id,
            site_id=site_id,
            mission_id=mission_id,
            mission_type=mission_type,
            requested_site_frame=requested_site_frame,
            request_digest=request_digest,
            captured_at=captured_at,
        )

    def attach_work_order(
        self,
        witness: IssuanceAuthorizationWitness,
        *,
        work_order_id: str | None,
    ) -> IssuanceAuthorizationWitness:
        if work_order_id is None:
            return witness
        store = self.work_order_store
        if store is None:
            raise MissionIssuanceRejected(
                503, "WorkOrder Mission lineage coordinator가 조립되지 않았다"
            )
        with store.issuance_commit_guard(
            work_order_id, organization_id=witness.organization_id
        ) as order:
            if store.sealed_reason is not None:
                raise MissionIssuanceRejected(503, "STORE_UNAVAILABLE")
            if order is None:
                raise MissionIssuanceRejected(404, "관측 작업을 찾을 수 없다")
            if order.site_id != witness.site_id:
                raise MissionIssuanceRejected(
                    422, "WORK_ORDER_SITE_MISMATCH — WorkOrder와 Mission의 Site가 다르다"
                )
            if order.status is not ObservationWorkOrderStatus.APPROVED:
                raise MissionIssuanceRejected(
                    409,
                    "WORK_ORDER_NOT_APPROVED — 승인된 현재 회차에만 Mission을 발급한다",
                )
            work_order_witness = WorkOrderAuthorizationWitness(
                work_order_id=order.work_order_id,
                version=order.version,
                cycle_number=order.cycle_number,
                status=order.status.value,
            )
        return replace(witness, work_order=work_order_witness)

    def attach_acquisition(
        self, witness: IssuanceAuthorizationWitness, *, evaluated_at: datetime
    ) -> IssuanceAuthorizationWitness:
        if not self.acquisition_issue_gate_enabled:
            return witness
        store = self.acquisition_store
        if store is None:  # constructor guards this; fail closed if corrupted assembly.
            raise MissionIssuanceRejected(503, "Acquisition readiness store가 없다")
        with store.issuance_commit_guard(
            witness.site_id, organization_id=witness.organization_id
        ) as (profile, snapshot):
            if store.sealed_reason is not None:
                raise MissionIssuanceRejected(503, "STORE_UNAVAILABLE")
            readiness = store.readiness(
                witness.site_id,
                organization_id=witness.organization_id,
                now=evaluated_at,
            )
            if not readiness.ready_for_mission_issue or profile is None or snapshot is None:
                detail = readiness.reasons[0] if readiness.reasons else readiness.status.value
                raise MissionIssuanceRejected(409, f"ACQUISITION_NOT_READY — {detail}")
            acquisition_witness = AcquisitionAuthorizationWitness(
                profile_digest=_profile_digest(profile),
                snapshot_id=snapshot.snapshot_id,
                expires_at=snapshot.expires_at,
            )
        return replace(witness, acquisition=acquisition_witness)

    def commit(
        self, record: MissionRecord, witness: IssuanceAuthorizationWitness
    ) -> MissionRecordVerdict:
        """Atomically compare all witnesses and append/fsync the Mission record.

        Signing success is intentionally absent from the authority decision.  The
        signed bytes become authoritative only if this method returns ``RECORDED``.
        """

        if (
            record.issuance_schema_version != "1.0"
            or record.issuance_request_digest != witness.request_digest
            or record.authorization_witness != witness
            or record.organization_id != witness.organization_id
            or record.site_id != witness.site_id
        ):
            raise ValueError("MissionRecord와 authorization witness가 정확히 결속되지 않았다")

        with ExitStack() as stack:
            site_state = stack.enter_context(
                self.site_store.issuance_commit_guard(
                    witness.site_id, organization_id=witness.organization_id
                )
            )
            if self.site_store.sealed_reason is not None:
                return MissionRecordVerdict.STORE_UNAVAILABLE
            if site_state is None:
                raise IssuancePreconditionChangedError(
                    IssuanceConflictSubreason.SITE_ISSUANCE_REVISION_CONFLICT
                )
            current_frame_digest = sha256_digest(
                canonical_payload_bytes(site_state.record.site_frame)
            )
            if (
                site_state.issuance_revision != witness.site_issuance_revision
                or site_state.record.status is not witness.site_status
                or current_frame_digest != witness.site_frame_digest
                or not is_mission_type_allowed_at_site_status(
                    MissionType(record.mission_type), site_state.record.status
                )
            ):
                raise IssuancePreconditionChangedError(
                    IssuanceConflictSubreason.SITE_ISSUANCE_REVISION_CONFLICT
                )

            if witness.work_order is not None:
                if self.work_order_store is None:
                    raise IssuancePreconditionChangedError(
                        IssuanceConflictSubreason.WORK_ORDER_REVISION_CONFLICT
                    )
                current_order = stack.enter_context(
                    self.work_order_store.issuance_commit_guard(
                        witness.work_order.work_order_id,
                        organization_id=witness.organization_id,
                    )
                )
                if self.work_order_store.sealed_reason is not None:
                    return MissionRecordVerdict.STORE_UNAVAILABLE
                if (
                    current_order is None
                    or current_order.site_id != witness.site_id
                    or current_order.version != witness.work_order.version
                    or current_order.cycle_number != witness.work_order.cycle_number
                    or current_order.status.value != witness.work_order.status
                    or current_order.status is not ObservationWorkOrderStatus.APPROVED
                ):
                    raise IssuancePreconditionChangedError(
                        IssuanceConflictSubreason.WORK_ORDER_REVISION_CONFLICT
                    )

            if witness.acquisition is not None:
                if self.acquisition_store is None:
                    raise IssuancePreconditionChangedError(
                        IssuanceConflictSubreason.ACQUISITION_WITNESS_STALE
                    )
                profile, snapshot = stack.enter_context(
                    self.acquisition_store.issuance_commit_guard(
                        witness.site_id, organization_id=witness.organization_id
                    )
                )
                if self.acquisition_store.sealed_reason is not None:
                    return MissionRecordVerdict.STORE_UNAVAILABLE
                now = datetime.now(UTC)
                readiness = self.acquisition_store.readiness(
                    witness.site_id,
                    organization_id=witness.organization_id,
                    now=now,
                )
                if (
                    profile is None
                    or snapshot is None
                    or not readiness.ready_for_mission_issue
                    or _profile_digest(profile) != witness.acquisition.profile_digest
                    or snapshot.snapshot_id != witness.acquisition.snapshot_id
                    or snapshot.expires_at != witness.acquisition.expires_at
                    or now >= witness.acquisition.expires_at
                ):
                    raise IssuancePreconditionChangedError(
                        IssuanceConflictSubreason.ACQUISITION_WITNESS_STALE
                    )
            elif self.acquisition_issue_gate_enabled:
                raise IssuancePreconditionChangedError(
                    IssuanceConflictSubreason.ACQUISITION_WITNESS_STALE
                )

            # MissionStore takes its own lock here, last in the canonical order,
            # and keeps it through journal append/fsync + projection update.
            return self.mission_store.record_issuance(record)


__all__ = [
    "MissionIssuanceCommitter",
    "MissionIssuanceRejected",
]
