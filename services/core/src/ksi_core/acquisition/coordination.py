"""Durable WorkOrder acquisition coordination without inventing device facts.

``AcquisitionRun`` records only the durable relationship between one approved
WorkOrder cycle, one Mission, and Gateway operation receipts. Mission execution,
source media, and processing remain authoritative in their existing journals.
The progress projector joins those facts at read time; it never marks an DJI
capability verified and never interprets a stale heartbeat as cancellation of an
already activated Mission Contract (INV-001/002, INV-010~013, INV-040~042).
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from ksi_domain.enums import MissionExecutionStatus
from ksi_event_contracts.observation_work_order import (
    ObservationWorkOrder,
    ObservationWorkOrderExecutionMode,
    ObservationWorkOrderStatus,
)

from ksi_core.acquisition.analysis_readiness import AnalysisReadinessProjector
from ksi_core.acquisition.models import (
    AcquisitionCapability,
    AcquisitionContractProgressView,
    AcquisitionGatewayProgressView,
    AcquisitionMediaProgressView,
    AcquisitionMediaState,
    AcquisitionMissionProgressView,
    AcquisitionNextAction,
    AcquisitionProcessingProgressView,
    AcquisitionProcessingState,
    AcquisitionProgressView,
    AcquisitionRunStage,
    AcquisitionRunV1,
    GatewayOperationOutcome,
    GatewayOperationReceiptRequest,
    GatewayOperationReceiptV1,
)
from ksi_core.api_base import iso_utc
from ksi_core.durable_journal import DurableJournal
from ksi_core.observation_work_orders import ExternalReconstructionExecutionDenied

if TYPE_CHECKING:
    from ksi_core.acquisition.store import AcquisitionConnectivityStore
    from ksi_core.mission_execution import MissionExecutionStore
    from ksi_core.processing_jobs import ProcessingJobStore
    from ksi_core.source_media import SourceMediaStore


class AcquisitionCoordinationRecoveryError(RuntimeError):
    """The coordination journal cannot be replayed without guessing."""


class AcquisitionCoordinationConflictError(ValueError):
    """An idempotency or one-run/one-mission invariant was violated."""


class AcquisitionExternalReconstructionDenied(ExternalReconstructionExecutionDenied):
    """A direct assembly cannot turn a customer upload WorkOrder into an AcquisitionRun."""


class AcquisitionCoordinationStore:
    """Append-only run/receipt store keyed by organization, WorkOrder, and cycle."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        work_order_execution_guard: Callable[[ObservationWorkOrder], None] | None = None,
    ) -> None:
        self._journal = journal
        self._lock = threading.RLock()
        self._runs: dict[tuple[str, str, int], AcquisitionRunV1] = {}
        self._mission_to_run: dict[tuple[str, str], tuple[str, str, int]] = {}
        self._receipts: dict[tuple[str, str], GatewayOperationReceiptV1] = {}
        self._receipt_order: list[tuple[str, str]] = []
        # Transport is deliberately excluded. A direct/RC fallback keeps the same
        # idempotency key and digest, while each observation has its own receiptId.
        self._idempotency: dict[tuple[str, str], tuple[str, AcquisitionCapability, str]] = {}
        # Assembly injects WorkOrderStore.assert_execution_allowed. The optional
        # seam preserves ordinary managed-only test assemblies until that shared
        # store is supplied; an external successor can only be created through
        # the separately closed WorkOrder authority port.
        self._work_order_execution_guard = work_order_execution_guard
        try:
            self._replay(journal.replay())
        except BaseException:
            journal.close()
            raise

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    @staticmethod
    def _run_key(run: AcquisitionRunV1) -> tuple[str, str, int]:
        return (run.organization_id, run.work_order_id, run.cycle_number)

    @staticmethod
    def _run_id(organization_id: str, work_order_id: str, cycle_number: int) -> str:
        raw = f"{organization_id}\0{work_order_id}\0{cycle_number}".encode()
        return f"acq-run-{hashlib.sha256(raw).hexdigest()[:24]}"

    def _replay(self, records: list[dict[str, Any]]) -> None:
        try:
            for raw in records:
                kind = raw["kind"]
                if kind == "acquisition-run-created":
                    run = AcquisitionRunV1.model_validate(raw["run"])
                    key = self._run_key(run)
                    if key in self._runs:
                        raise ValueError("duplicate AcquisitionRun key")
                    self._runs[key] = run
                elif kind == "acquisition-run-mission-linked":
                    organization_id = str(raw["organizationId"])
                    work_order_id = str(raw["workOrderId"])
                    cycle_number = int(raw["cycleNumber"])
                    mission_id = str(raw["missionId"])
                    updated_at = datetime.fromisoformat(str(raw["ts"]))
                    key = (organization_id, work_order_id, cycle_number)
                    existing_run = self._runs.get(key)
                    if existing_run is None:
                        raise ValueError("mission link before AcquisitionRun")
                    if existing_run.mission_id is not None:
                        raise ValueError("AcquisitionRun has multiple mission links")
                    mission_key = (organization_id, mission_id)
                    if mission_key in self._mission_to_run:
                        raise ValueError("mission linked to multiple AcquisitionRuns")
                    linked = existing_run.model_copy(
                        update={"mission_id": mission_id, "updated_at": updated_at}
                    )
                    self._runs[key] = linked
                    self._mission_to_run[mission_key] = key
                elif kind == "gateway-operation-receipt-recorded":
                    receipt = GatewayOperationReceiptV1.model_validate(raw["receipt"])
                    self._apply_receipt(receipt, replaying=True)
                else:
                    raise ValueError(f"unknown kind={kind!r}")
        except (KeyError, TypeError, ValueError) as exc:
            raise AcquisitionCoordinationRecoveryError(
                f"acquisition coordination journal 재생 실패: {exc}"
            ) from exc

    def _apply_receipt(self, receipt: GatewayOperationReceiptV1, *, replaying: bool) -> None:
        receipt_key = (receipt.organization_id, receipt.receipt_id)
        if receipt_key in self._receipts:
            raise ValueError("duplicate receiptId")
        mission_key = (receipt.organization_id, receipt.mission_id)
        if mission_key not in self._mission_to_run:
            raise ValueError("receipt mission is not linked to an AcquisitionRun")
        idempotency_key = (receipt.organization_id, receipt.idempotency_key)
        fingerprint = (receipt.mission_id, receipt.capability, receipt.artifact_digest)
        previous = self._idempotency.get(idempotency_key)
        if previous is not None and previous != fingerprint:
            raise ValueError("idempotencyKey reused with a different mission/capability/digest")
        self._idempotency[idempotency_key] = fingerprint
        self._receipts[receipt_key] = receipt
        self._receipt_order.append(receipt_key)
        if not replaying:
            return

    def ensure_run(
        self,
        work_order: ObservationWorkOrder,
        *,
        actor: str,
        now: datetime,
    ) -> AcquisitionRunV1:
        if now.tzinfo is None:
            raise ValueError("now는 tz-aware여야 한다")
        if work_order.execution_mode is ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION:
            raise AcquisitionExternalReconstructionDenied("EXTERNAL_RECONSTRUCTION_ONLY")
        if self._work_order_execution_guard is not None:
            self._work_order_execution_guard(work_order)
        key = (
            work_order.organization_id,
            work_order.work_order_id,
            work_order.cycle_number,
        )
        with self._lock:
            existing = self._runs.get(key)
            if existing is not None:
                return existing
            run = AcquisitionRunV1(
                run_id=self._run_id(*key),
                organization_id=work_order.organization_id,
                work_order_id=work_order.work_order_id,
                site_id=work_order.site_id,
                cycle_number=work_order.cycle_number,
                created_at=now,
                created_by=actor,
                updated_at=now,
            )
            self._journal.append(
                {
                    "kind": "acquisition-run-created",
                    "ts": iso_utc(now),
                    "actor": actor,
                    "run": run.model_dump(mode="json", by_alias=True),
                }
            )
            self._runs[key] = run
            return run

    def get_run(
        self, work_order_id: str, *, organization_id: str, cycle_number: int
    ) -> AcquisitionRunV1 | None:
        with self._lock:
            return self._runs.get((organization_id, work_order_id, cycle_number))

    def link_mission(
        self,
        work_order: ObservationWorkOrder,
        mission_id: str,
        *,
        actor: str,
        now: datetime,
    ) -> AcquisitionRunV1:
        if now.tzinfo is None:
            raise ValueError("now는 tz-aware여야 한다")
        if work_order.execution_mode is ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION:
            raise AcquisitionExternalReconstructionDenied("EXTERNAL_RECONSTRUCTION_ONLY")
        if self._work_order_execution_guard is not None:
            self._work_order_execution_guard(work_order)
        key = (
            work_order.organization_id,
            work_order.work_order_id,
            work_order.cycle_number,
        )
        with self._lock:
            run = self._runs.get(key)
            if run is None:
                run = self.ensure_run(work_order, actor=actor, now=now)
            if run.mission_id == mission_id:
                return run
            if run.mission_id is not None:
                raise AcquisitionCoordinationConflictError(
                    "한 AcquisitionRun 회차에는 Mission 하나만 연결할 수 있다"
                )
            mission_key = (work_order.organization_id, mission_id)
            linked_elsewhere = self._mission_to_run.get(mission_key)
            if linked_elsewhere is not None and linked_elsewhere != key:
                raise AcquisitionCoordinationConflictError(
                    "Mission은 같은 조직의 다른 AcquisitionRun에 이미 연결됐다"
                )
            self._journal.append(
                {
                    "kind": "acquisition-run-mission-linked",
                    "ts": iso_utc(now),
                    "actor": actor,
                    "organizationId": work_order.organization_id,
                    "workOrderId": work_order.work_order_id,
                    "cycleNumber": work_order.cycle_number,
                    "missionId": mission_id,
                }
            )
            linked = run.model_copy(update={"mission_id": mission_id, "updated_at": now})
            self._runs[key] = linked
            self._mission_to_run[mission_key] = key
            return linked

    def run_for_mission(self, mission_id: str, *, organization_id: str) -> AcquisitionRunV1 | None:
        with self._lock:
            key = self._mission_to_run.get((organization_id, mission_id))
            return self._runs.get(key) if key is not None else None

    @staticmethod
    def _same_receipt(
        existing: GatewayOperationReceiptV1,
        request: GatewayOperationReceiptRequest,
        *,
        organization_id: str,
        gateway_device_id: str,
    ) -> bool:
        return (
            existing.organization_id == organization_id
            and existing.gateway_device_id == gateway_device_id
            and existing.schema_version == request.schema_version
            and existing.receipt_id == request.receipt_id
            and existing.idempotency_key == request.idempotency_key
            and existing.site_id == request.site_id
            and existing.mission_id == request.mission_id
            and existing.capability is request.capability
            and existing.transport is request.transport
            and existing.outcome is request.outcome
            and existing.artifact_digest == request.artifact_digest
            and existing.observed_at == request.observed_at
        )

    def record_receipt(
        self,
        request: GatewayOperationReceiptRequest,
        *,
        organization_id: str,
        gateway_device_id: str,
        actor: str,
        now: datetime,
    ) -> tuple[GatewayOperationReceiptV1, bool]:
        """Return ``(receipt, created)``; identical nonce retries are read-only."""

        if now.tzinfo is None:
            raise ValueError("now는 tz-aware여야 한다")
        if request.observed_at > now + timedelta(minutes=1):
            raise ValueError("observedAt은 Core 시각보다 1분 이상 미래일 수 없다")
        receipt_key = (organization_id, request.receipt_id)
        with self._lock:
            existing = self._receipts.get(receipt_key)
            if existing is not None:
                if self._same_receipt(
                    existing,
                    request,
                    organization_id=organization_id,
                    gateway_device_id=gateway_device_id,
                ):
                    return existing, False
                raise AcquisitionCoordinationConflictError(
                    "receiptId를 다른 내용으로 재사용할 수 없다"
                )
            if (organization_id, request.mission_id) not in self._mission_to_run:
                raise LookupError("AcquisitionRun에 연결된 Mission을 찾을 수 없다")
            idempotency_key = (organization_id, request.idempotency_key)
            fingerprint = (request.mission_id, request.capability, request.artifact_digest)
            previous = self._idempotency.get(idempotency_key)
            if previous is not None and previous != fingerprint:
                raise AcquisitionCoordinationConflictError(
                    "idempotencyKey를 다른 Mission, capability 또는 digest에 재사용할 수 없다"
                )
            receipt = GatewayOperationReceiptV1(
                **request.model_dump(),
                organization_id=organization_id,
                gateway_device_id=gateway_device_id,
                received_at=now,
            )
            self._journal.append(
                {
                    "kind": "gateway-operation-receipt-recorded",
                    "ts": iso_utc(now),
                    "actor": actor,
                    "receipt": receipt.model_dump(mode="json", by_alias=True),
                }
            )
            self._apply_receipt(receipt, replaying=False)
            return receipt, True

    def receipts_for_mission(
        self, mission_id: str, *, organization_id: str
    ) -> list[GatewayOperationReceiptV1]:
        with self._lock:
            return [
                self._receipts[key]
                for key in self._receipt_order
                if key[0] == organization_id and self._receipts[key].mission_id == mission_id
            ]


class AcquisitionProgressProjector:
    """Join canonical journals into an operator-facing acquisition progress view."""

    def __init__(
        self,
        *,
        coordination_store: AcquisitionCoordinationStore,
        connectivity_store: AcquisitionConnectivityStore,
        mission_execution_store: MissionExecutionStore | None = None,
        source_media_store: SourceMediaStore | None = None,
        processing_job_store: ProcessingJobStore | None = None,
        analysis_readiness_projector: AnalysisReadinessProjector | None = None,
    ) -> None:
        self._coordination = coordination_store
        self._connectivity = connectivity_store
        self._execution = mission_execution_store
        self._source_media = source_media_store
        self._processing = processing_job_store
        self._analysis_readiness = analysis_readiness_projector

    def project(
        self, work_order: ObservationWorkOrder, *, now: datetime
    ) -> AcquisitionProgressView:
        readiness = self._connectivity.readiness(
            work_order.site_id,
            organization_id=work_order.organization_id,
            now=now,
        )
        run = self._coordination.get_run(
            work_order.work_order_id,
            organization_id=work_order.organization_id,
            cycle_number=work_order.cycle_number,
        )
        mission_id = run.mission_id if run is not None else None
        analysis_readiness = (
            self._analysis_readiness.project(work_order, mission_id=mission_id, now=now)
            if self._analysis_readiness is not None
            else AnalysisReadinessProjector.not_assembled(
                work_order, mission_id=mission_id, now=now
            )
        )
        receipts = (
            self._coordination.receipts_for_mission(
                mission_id, organization_id=work_order.organization_id
            )
            if mission_id is not None
            else []
        )
        receipts.sort(key=lambda item: (item.observed_at, item.received_at, item.receipt_id))
        latest_receipt = receipts[-1] if receipts else None
        succeeded = {
            receipt.capability
            for receipt in receipts
            if receipt.outcome is GatewayOperationOutcome.SUCCEEDED
        }
        failed = {
            receipt.capability
            for receipt in receipts
            if receipt.outcome is GatewayOperationOutcome.FAILED
            and receipt.capability not in succeeded
        }

        execution_status: MissionExecutionStatus | None = None
        activated_at: datetime | None = None
        if mission_id is not None and self._execution is not None:
            execution_status = self._execution.effective_status(mission_id)
            for item in self._execution.history(mission_id):
                if item.after is MissionExecutionStatus.ACTIVATED:
                    activated_at = item.updated_at
                    break
        activated = execution_status in {
            MissionExecutionStatus.ACTIVATED,
            MissionExecutionStatus.COMPLETED,
            MissionExecutionStatus.ENDED_INCOMPLETE,
        }

        bundle = (
            self._source_media.get(mission_id)
            if mission_id is not None and self._source_media is not None
            else None
        )
        if bundle is not None and bundle.is_verified:
            media_state = AcquisitionMediaState.VERIFIED
        elif bundle is not None and bundle.is_sealed:
            media_state = AcquisitionMediaState.VERIFYING
        elif (
            bundle is not None
            or bool(
                succeeded & {AcquisitionCapability.MEDIA_PULL, AcquisitionCapability.MEDIA_UPLOAD}
            )
            or execution_status
            in {MissionExecutionStatus.COMPLETED, MissionExecutionStatus.ENDED_INCOMPLETE}
        ):
            media_state = AcquisitionMediaState.SYNCING
        else:
            media_state = AcquisitionMediaState.NOT_STARTED

        jobs = (
            self._processing.list_for_mission(mission_id)
            if mission_id is not None and self._processing is not None
            else []
        )
        processing_state = AcquisitionProcessingState.NOT_STARTED
        if jobs:
            processing_state = AcquisitionProcessingState(jobs[-1].status.value)

        stage, next_action, detail = self._derive_stage(
            work_order=work_order,
            run=run,
            readiness_ready=readiness.ready_for_mission_issue,
            receipts=receipts,
            succeeded=succeeded,
            activated=activated,
            execution_status=execution_status,
            media_state=media_state,
            processing_state=processing_state,
        )
        return AcquisitionProgressView(
            run_id=run.run_id if run is not None else None,
            work_order_id=work_order.work_order_id,
            site_id=work_order.site_id,
            cycle_number=work_order.cycle_number,
            stage=stage,
            next_action=next_action,
            detail=detail,
            readiness=readiness,
            mission=AcquisitionMissionProgressView(
                mission_id=mission_id,
                issued=mission_id is not None,
                execution_status=execution_status.value if execution_status is not None else None,
            ),
            gateway=AcquisitionGatewayProgressView(
                latest_receipt=latest_receipt,
                succeeded_capabilities=tuple(sorted(succeeded, key=lambda item: item.value)),
                failed_capabilities=tuple(sorted(failed, key=lambda item: item.value)),
            ),
            contract_activation=AcquisitionContractProgressView(
                state=("ACTIVATED" if activated else "PENDING" if mission_id else "NOT_ISSUED"),
                activated_at=activated_at,
            ),
            media=AcquisitionMediaProgressView(
                state=media_state,
                item_count=len(bundle.media) if bundle is not None else 0,
                source_bundle_digest=(bundle.source_bundle_digest if bundle is not None else None),
            ),
            processing=AcquisitionProcessingProgressView(
                state=processing_state,
                job_ids=tuple(job.job_id for job in jobs),
            ),
            analysis_readiness=analysis_readiness,
            evaluated_at=now,
            in_flight_contract_policy="REMAINS_VALID_UNTIL_CONTRACT_EXPIRY",
        )

    @staticmethod
    def _derive_stage(
        *,
        work_order: ObservationWorkOrder,
        run: AcquisitionRunV1 | None,
        readiness_ready: bool,
        receipts: list[GatewayOperationReceiptV1],
        succeeded: set[AcquisitionCapability],
        activated: bool,
        execution_status: MissionExecutionStatus | None,
        media_state: AcquisitionMediaState,
        processing_state: AcquisitionProcessingState,
    ) -> tuple[AcquisitionRunStage, AcquisitionNextAction, str]:
        if work_order.status in {
            ObservationWorkOrderStatus.BLOCKED,
            ObservationWorkOrderStatus.CANCELLED,
        }:
            return (
                AcquisitionRunStage.BLOCKED,
                AcquisitionNextAction.RESOLVE_BLOCKER
                if work_order.status is ObservationWorkOrderStatus.BLOCKED
                else AcquisitionNextAction.NONE,
                work_order.status_reason or "작업이 중단되었거나 취소되었습니다.",
            )
        if execution_status is MissionExecutionStatus.CANCELLED:
            return (
                AcquisitionRunStage.BLOCKED,
                AcquisitionNextAction.NONE,
                "사람이 Mission 실행을 취소했습니다. 자동으로 다시 발급하거나 진행하지 않습니다.",
            )
        if work_order.status in {
            ObservationWorkOrderStatus.AWAITING_APPROVAL,
        }:
            return (
                AcquisitionRunStage.WAITING_PLAN,
                AcquisitionNextAction.APPROVE_WORK_ORDER,
                "사람이 작업 범위와 목적을 승인해야 취득 준비를 시작합니다.",
            )
        if run is None or run.mission_id is None:
            if not readiness_ready:
                return (
                    AcquisitionRunStage.WAITING_READINESS,
                    AcquisitionNextAction.CHECK_ACQUISITION_READINESS,
                    "새 Mission 발급 전 RC 인터넷, 장치 binding, capability 증거가 필요합니다.",
                )
            return (
                AcquisitionRunStage.WAITING_PLAN,
                AcquisitionNextAction.OPEN_MISSION_WIZARD,
                "장비가 준비되었습니다. WorkOrder 정보로 비행 계획을 작성하세요.",
            )
        if processing_state is AcquisitionProcessingState.SUCCEEDED or work_order.status in {
            ObservationWorkOrderStatus.REVIEW_READY,
            ObservationWorkOrderStatus.COMPLETED,
        }:
            return (
                AcquisitionRunStage.REVIEW_READY,
                AcquisitionNextAction.REVIEW_RESULTS,
                "검증된 원본을 사용한 처리 결과를 사람이 검토할 수 있습니다.",
            )
        if processing_state in {
            AcquisitionProcessingState.FAILED,
            AcquisitionProcessingState.CANCELLED,
        }:
            return (
                AcquisitionRunStage.BLOCKED,
                AcquisitionNextAction.RESOLVE_BLOCKER,
                "처리 작업이 완료되지 못했습니다. 원본과 작업 로그를 확인하세요.",
            )
        if (
            processing_state
            in {AcquisitionProcessingState.QUEUED, AcquisitionProcessingState.RUNNING}
            or media_state is AcquisitionMediaState.VERIFIED
        ):
            return (
                AcquisitionRunStage.PROCESSING,
                AcquisitionNextAction.WAIT_PROCESSING,
                "봉인·검증된 원본을 기준으로 공간 처리를 진행합니다.",
            )
        if media_state is AcquisitionMediaState.VERIFYING:
            return (
                AcquisitionRunStage.MEDIA_VERIFYING,
                AcquisitionNextAction.VERIFY_SOURCE_MEDIA,
                "원본 전량의 digest와 메타데이터를 대조해야 처리를 시작할 수 있습니다.",
            )
        if media_state is AcquisitionMediaState.SYNCING:
            return (
                AcquisitionRunStage.MEDIA_SYNCING,
                AcquisitionNextAction.WAIT_MEDIA_SYNC,
                "착륙 후 원본을 회수하고 있습니다. 전량 봉인 전에는 처리를 시작하지 않습니다.",
            )
        if execution_status in {
            MissionExecutionStatus.COMPLETED,
            MissionExecutionStatus.ENDED_INCOMPLETE,
        }:
            return (
                AcquisitionRunStage.MEDIA_SYNCING,
                AcquisitionNextAction.WAIT_MEDIA_SYNC,
                "비행 종료 사실은 확인됐지만 원본 전량 회수는 아직 완료되지 않았습니다.",
            )
        if activated:
            return (
                AcquisitionRunStage.READY_FOR_FLIGHT,
                AcquisitionNextAction.OPERATE_WITH_PILOT_2,
                "서명 계약이 Manifold에서 활성화되었습니다. 이후 인터넷 단절만으로 "
                "자동 중단하지 않습니다.",
            )
        if AcquisitionCapability.WAYLINE_DELIVERY in succeeded:
            return (
                AcquisitionRunStage.CONTRACT_PENDING,
                AcquisitionNextAction.WAIT_CONTRACT_ACTIVATION,
                "경로 전달은 확인됐습니다. Edge의 서명 계약 활성화 영수증을 기다립니다.",
            )
        if receipts:
            return (
                AcquisitionRunStage.WAYLINE_PENDING,
                AcquisitionNextAction.WAIT_GATEWAY_DELIVERY,
                "Gateway 전달을 재시도 중입니다. capability별 영수증을 독립 확인합니다.",
            )
        return (
            AcquisitionRunStage.MISSION_ISSUED,
            AcquisitionNextAction.WAIT_GATEWAY_DELIVERY,
            "Mission과 서명 계약이 발급되었습니다. Gateway 전달 영수증을 기다립니다.",
        )


__all__ = [
    "AcquisitionCoordinationConflictError",
    "AcquisitionCoordinationRecoveryError",
    "AcquisitionCoordinationStore",
    "AcquisitionProgressProjector",
]
