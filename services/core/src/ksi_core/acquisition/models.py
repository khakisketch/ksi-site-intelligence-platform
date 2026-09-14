"""Wire models for AcquisitionDeploymentProfile v1 and ConnectivitySnapshot v1."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from ksi_core.foundation.api_base import CamelModel
from ksi_core.foundation.identifiers import is_path_safe_identifier


class OperatingMode(StrEnum):
    RC_ATTENDED = "RC_ATTENDED"
    DOCK_AUTOMATED = "DOCK_AUTOMATED"


class GatewayKind(StrEnum):
    RC_PLUS_2 = "RC_PLUS_2"
    DOCK_3 = "DOCK_3"


class GatewayTransport(StrEnum):
    WIFI = "WIFI"
    CELLULAR = "CELLULAR"
    ETHERNET = "ETHERNET"


class InternetGate(StrEnum):
    REQUIRED_FOR_MISSION_ISSUE = "REQUIRED_FOR_MISSION_ISSUE"


class ManifoldDirectMode(StrEnum):
    DISABLED = "DISABLED"
    CONNECTIVITY_ADD_ON = "CONNECTIVITY_ADD_ON"


class RoutingPolicy(StrEnum):
    RC_STANDARD = "RC_STANDARD"
    ROLE_SPLIT_DIRECT_EDGE = "ROLE_SPLIT_DIRECT_EDGE"


class MediaPolicy(StrEnum):
    RESULTS_IMMEDIATE_RAW_POSTFLIGHT = "RESULTS_IMMEDIATE_RAW_POSTFLIGHT"


class MsdkBridgeMode(StrEnum):
    DISABLED = "DISABLED"
    CONDITIONAL_PREFLIGHT_POSTFLIGHT = "CONDITIONAL_PREFLIGHT_POSTFLIGHT"


class ConnectionState(StrEnum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    UNKNOWN = "UNKNOWN"


class DirectEdgeState(StrEnum):
    DISABLED = "DISABLED"
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    UNKNOWN = "UNKNOWN"


class SyncState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    ACTIVATED = "ACTIVATED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class AcquisitionCapability(StrEnum):
    WAYLINE_DELIVERY = "WAYLINE_DELIVERY"
    EDGE_DOWNLINK = "EDGE_DOWNLINK"
    EDGE_UPLINK = "EDGE_UPLINK"
    MEDIA_PULL = "MEDIA_PULL"
    MEDIA_UPLOAD = "MEDIA_UPLOAD"


class CapabilityStatus(StrEnum):
    NOT_VERIFIED = "NOT_VERIFIED"
    VERIFIED = "VERIFIED"
    BLOCKED = "BLOCKED"


class ReadinessStatus(StrEnum):
    READY = "READY"
    PROFILE_MISSING = "PROFILE_MISSING"
    DOCK_ADAPTER_NOT_IMPLEMENTED = "DOCK_ADAPTER_NOT_IMPLEMENTED"
    CONNECTIVITY_MISSING = "CONNECTIVITY_MISSING"
    CONNECTIVITY_STALE = "CONNECTIVITY_STALE"
    GATEWAY_OFFLINE = "GATEWAY_OFFLINE"
    INTERNET_REQUIRED = "INTERNET_REQUIRED"
    DEVICE_MISMATCH = "DEVICE_MISMATCH"
    TRANSPORT_NOT_ALLOWED = "TRANSPORT_NOT_ALLOWED"
    CAPABILITY_NOT_VERIFIED = "CAPABILITY_NOT_VERIFIED"


class AcquisitionRunStage(StrEnum):
    """WorkOrder 한 회차의 조정 단계.

    이 값은 비행 상태를 추측하지 않는다. ``READY_FOR_FLIGHT`` 는 서명 계약의
    Edge activation 사실이 기존 MissionExecution 원장에 기록된 뒤에만 나온다.
    """

    WAITING_READINESS = "WAITING_READINESS"
    WAITING_PLAN = "WAITING_PLAN"
    MISSION_ISSUED = "MISSION_ISSUED"
    WAYLINE_PENDING = "WAYLINE_PENDING"
    CONTRACT_PENDING = "CONTRACT_PENDING"
    READY_FOR_FLIGHT = "READY_FOR_FLIGHT"
    MEDIA_SYNCING = "MEDIA_SYNCING"
    MEDIA_VERIFYING = "MEDIA_VERIFYING"
    PROCESSING = "PROCESSING"
    REVIEW_READY = "REVIEW_READY"
    BLOCKED = "BLOCKED"


class AcquisitionNextAction(StrEnum):
    APPROVE_WORK_ORDER = "APPROVE_WORK_ORDER"
    CHECK_ACQUISITION_READINESS = "CHECK_ACQUISITION_READINESS"
    OPEN_MISSION_WIZARD = "OPEN_MISSION_WIZARD"
    WAIT_GATEWAY_DELIVERY = "WAIT_GATEWAY_DELIVERY"
    WAIT_CONTRACT_ACTIVATION = "WAIT_CONTRACT_ACTIVATION"
    OPERATE_WITH_PILOT_2 = "OPERATE_WITH_PILOT_2"
    WAIT_MEDIA_SYNC = "WAIT_MEDIA_SYNC"
    VERIFY_SOURCE_MEDIA = "VERIFY_SOURCE_MEDIA"
    WAIT_PROCESSING = "WAIT_PROCESSING"
    REVIEW_RESULTS = "REVIEW_RESULTS"
    RESOLVE_BLOCKER = "RESOLVE_BLOCKER"
    NONE = "NONE"


class GatewayOperationOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class AcquisitionMediaState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    SYNCING = "SYNCING"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"


class AcquisitionProcessingState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AnalysisReadinessStatus(StrEnum):
    """분석 가능 여부의 **파생** 판정(비행 상태가 아니다).

    상태를 사람이 쓰거나 Edge가 확정할 수 없게, Coverage·품질·원본·시간·처리
    원장에서 읽어 projector가 매번 계산한다(REQ-INT-102, INV-017).
    """

    EVIDENCE_NOT_ASSEMBLED = "EVIDENCE_NOT_ASSEMBLED"
    WAITING_MISSION = "WAITING_MISSION"
    WAITING_COVERAGE = "WAITING_COVERAGE"
    COVERAGE_GAP = "COVERAGE_GAP"
    WAITING_CAPTURE_QUALITY = "WAITING_CAPTURE_QUALITY"
    CAPTURE_QUALITY_GAP = "CAPTURE_QUALITY_GAP"
    WAITING_MEDIA = "WAITING_MEDIA"
    INTEGRITY_GAP = "INTEGRITY_GAP"
    CAPTURE_TIME_INCOMPLETE = "CAPTURE_TIME_INCOMPLETE"
    TEMPORAL_POLICY_UNDECLARED = "TEMPORAL_POLICY_UNDECLARED"
    TEMPORAL_COHERENCE_GAP = "TEMPORAL_COHERENCE_GAP"
    WAITING_PROCESSING = "WAITING_PROCESSING"
    PROCESSING_FAILED = "PROCESSING_FAILED"
    READY = "READY"


class ObservationEpochView(CamelModel):
    """WorkOrder 회차에서 결정적으로 파생한 v1 Observation Epoch.

    v1은 한 회차=한 sortie=한 Mission만 허용한다. 이 객체는 새 mutable 원장이
    아니라 기존 WorkOrder/AcquisitionRun/SourceMedia 사실의 읽기 모델이다.
    """

    epoch_id: str
    work_order_id: str
    cycle_number: Annotated[int, Field(ge=1)]
    mission_id: str | None
    sortie_count: Literal[1] = 1
    max_capture_span_seconds: Annotated[int, Field(ge=1, le=86_400)] | None
    temporal_policy_schema_version: str | None
    capture_window_status: str
    captured_from: datetime | None
    captured_to: datetime | None


class AnalysisReadinessView(CamelModel):
    """분석 시작/검토 가능 여부의 evidence-derived view (INV-017)."""

    status: AnalysisReadinessStatus
    ready: bool
    detail: str
    epoch: ObservationEpochView
    evidence_refs: tuple[str, ...]
    evaluated_at: datetime


Identifier = Annotated[str, Field(min_length=1, max_length=200)]


def _identifier(value: str) -> str:
    if not is_path_safe_identifier(value):
        raise ValueError("경로-안전 식별자만 허용한다")
    return value


class AcquisitionDeploymentProfileV1(CamelModel):
    schema_version: Literal["1.0"]
    site_id: Identifier
    operating_mode: OperatingMode
    gateway_kind: GatewayKind
    gateway_transports: tuple[GatewayTransport, ...]
    internet_gate: InternetGate
    manifold_direct_mode: ManifoldDirectMode
    routing_policy: RoutingPolicy
    media_policy: MediaPolicy
    msdk_bridge_mode: MsdkBridgeMode
    edge_device_id: Identifier
    gateway_device_id: Identifier

    @field_validator("site_id", "edge_device_id", "gateway_device_id")
    @classmethod
    def valid_identifier(cls, value: str) -> str:
        return _identifier(value)

    @model_validator(mode="after")
    def consistent_deployment(self) -> AcquisitionDeploymentProfileV1:
        transports = set(self.gateway_transports)
        if not transports or len(transports) != len(self.gateway_transports):
            raise ValueError("gatewayTransports는 중복 없는 비어 있지 않은 목록이어야 한다")
        if self.edge_device_id == self.gateway_device_id:
            raise ValueError("edgeDeviceId와 gatewayDeviceId는 서로 다른 장치 신원이어야 한다")
        if self.operating_mode is OperatingMode.RC_ATTENDED:
            if self.gateway_kind is not GatewayKind.RC_PLUS_2:
                raise ValueError("RC_ATTENDED는 RC_PLUS_2 gateway만 허용한다")
            if GatewayTransport.WIFI not in transports:
                raise ValueError("RC 기본 제품은 WIFI transport를 반드시 포함해야 한다")
            if not transports <= {GatewayTransport.WIFI, GatewayTransport.CELLULAR}:
                raise ValueError("RC_PLUS_2는 WIFI 또는 CELLULAR transport만 허용한다")
        else:
            if self.gateway_kind is not GatewayKind.DOCK_3:
                raise ValueError("DOCK_AUTOMATED는 DOCK_3 gateway만 허용한다")
            if not transports <= {GatewayTransport.ETHERNET, GatewayTransport.CELLULAR}:
                raise ValueError("DOCK_3는 ETHERNET 또는 CELLULAR transport만 허용한다")
            if self.msdk_bridge_mode is not MsdkBridgeMode.DISABLED:
                raise ValueError("MSDK Bridge는 RC attended profile에서만 허용한다")
        direct = self.manifold_direct_mode is ManifoldDirectMode.CONNECTIVITY_ADD_ON
        if direct != (self.routing_policy is RoutingPolicy.ROLE_SPLIT_DIRECT_EDGE):
            raise ValueError("Connectivity Add-on과 ROLE_SPLIT_DIRECT_EDGE는 함께 설정해야 한다")
        return self


class CapabilityReceiptV1(CamelModel):
    capability: AcquisitionCapability
    hardware_model: Annotated[str, Field(min_length=1, max_length=100)]
    firmware_version: Annotated[str, Field(min_length=1, max_length=100)]
    status: CapabilityStatus
    checked_at: datetime
    evidence_ref: Annotated[str, Field(max_length=500)] | None

    @model_validator(mode="after")
    def verified_requires_evidence(self) -> CapabilityReceiptV1:
        if self.checked_at.tzinfo is None:
            raise ValueError("checkedAt은 tz-aware여야 한다")
        if self.status is CapabilityStatus.VERIFIED and not self.evidence_ref:
            raise ValueError("VERIFIED capability에는 evidenceRef가 필수다")
        return self


class ConnectivitySnapshotV1(CamelModel):
    schema_version: Literal["1.0"]
    snapshot_id: Identifier
    site_id: Identifier
    gateway_device_id: Identifier
    edge_device_id: Identifier
    observed_at: datetime
    expires_at: datetime
    transport: GatewayTransport
    internet_reachable: bool
    gateway_state: ConnectionState
    edge_state: ConnectionState
    direct_edge_state: DirectEdgeState
    queued_event_count: Annotated[int, Field(ge=0)]
    queued_media_count: Annotated[int, Field(ge=0)]
    last_success_receipt_id: Identifier | None
    mission_contract_sync: SyncState
    raw_media_sync: SyncState
    capabilities: tuple[CapabilityReceiptV1, ...]

    @field_validator(
        "snapshot_id", "site_id", "gateway_device_id", "edge_device_id", "last_success_receipt_id"
    )
    @classmethod
    def valid_identifier(cls, value: str | None) -> str | None:
        return _identifier(value) if value is not None else value

    @model_validator(mode="after")
    def valid_snapshot(self) -> ConnectivitySnapshotV1:
        if self.observed_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("observedAt/expiresAt은 tz-aware여야 한다")
        if self.expires_at <= self.observed_at:
            raise ValueError("expiresAt은 observedAt보다 뒤여야 한다")
        if self.expires_at - self.observed_at > timedelta(minutes=5):
            raise ValueError("ConnectivitySnapshot TTL은 5분을 넘을 수 없다")
        features = [item.capability for item in self.capabilities]
        if len(features) != len(set(features)):
            raise ValueError("capability receipt는 기능별 최대 1개만 허용한다")
        if any(item.checked_at > self.observed_at for item in self.capabilities):
            raise ValueError("capability checkedAt은 snapshot observedAt 이후일 수 없다")
        return self


class AcquisitionReadinessView(CamelModel):
    site_id: str
    status: ReadinessStatus
    ready_for_mission_issue: bool
    reasons: tuple[str, ...]
    evaluated_at: datetime
    profile: AcquisitionDeploymentProfileV1 | None
    connectivity: ConnectivitySnapshotV1 | None
    in_flight_contract_policy: Literal["REMAINS_VALID_UNTIL_CONTRACT_EXPIRY"]


class AcquisitionRunV1(CamelModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: Identifier
    organization_id: Identifier
    work_order_id: Identifier
    site_id: Identifier
    cycle_number: Annotated[int, Field(ge=1)]
    mission_id: Identifier | None = None
    created_at: datetime
    created_by: Identifier
    updated_at: datetime

    @field_validator(
        "run_id",
        "organization_id",
        "work_order_id",
        "site_id",
        "mission_id",
        "created_by",
    )
    @classmethod
    def valid_run_identifier(cls, value: str | None) -> str | None:
        return _identifier(value) if value is not None else value

    @model_validator(mode="after")
    def aware_run_timestamps(self) -> AcquisitionRunV1:
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("createdAt/updatedAt은 tz-aware여야 한다")
        if self.updated_at < self.created_at:
            raise ValueError("updatedAt은 createdAt보다 앞설 수 없다")
        return self


class GatewayOperationReceiptRequest(CamelModel):
    schema_version: Literal["1.0"] = "1.0"
    receipt_id: Identifier
    idempotency_key: Annotated[str, Field(min_length=1, max_length=300)]
    site_id: Identifier
    mission_id: Identifier
    capability: AcquisitionCapability
    transport: GatewayTransport
    outcome: GatewayOperationOutcome
    artifact_digest: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    observed_at: datetime

    @field_validator("receipt_id", "site_id", "mission_id")
    @classmethod
    def valid_receipt_identifier(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("idempotency_key")
    @classmethod
    def safe_idempotency_key(cls, value: str) -> str:
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
            raise ValueError("idempotencyKey에는 제어문자를 사용할 수 없다")
        return value

    @model_validator(mode="after")
    def aware_observed_at(self) -> GatewayOperationReceiptRequest:
        if self.observed_at.tzinfo is None:
            raise ValueError("observedAt은 tz-aware여야 한다")
        return self


class GatewayOperationReceiptV1(GatewayOperationReceiptRequest):
    organization_id: Identifier
    gateway_device_id: Identifier
    received_at: datetime

    @field_validator("organization_id", "gateway_device_id")
    @classmethod
    def valid_binding_identifier(cls, value: str) -> str:
        return _identifier(value)

    @model_validator(mode="after")
    def aware_received_at(self) -> GatewayOperationReceiptV1:
        if self.received_at.tzinfo is None:
            raise ValueError("receivedAt은 tz-aware여야 한다")
        return self


class AcquisitionMissionProgressView(CamelModel):
    mission_id: str | None
    issued: bool
    execution_status: str | None


class AcquisitionGatewayProgressView(CamelModel):
    latest_receipt: GatewayOperationReceiptV1 | None
    succeeded_capabilities: tuple[AcquisitionCapability, ...]
    failed_capabilities: tuple[AcquisitionCapability, ...]


class AcquisitionContractProgressView(CamelModel):
    state: Literal["NOT_ISSUED", "PENDING", "ACTIVATED"]
    activated_at: datetime | None


class AcquisitionMediaProgressView(CamelModel):
    state: AcquisitionMediaState
    item_count: Annotated[int, Field(ge=0)]
    source_bundle_digest: str | None


class AcquisitionProcessingProgressView(CamelModel):
    state: AcquisitionProcessingState
    job_ids: tuple[str, ...]


class AcquisitionProgressView(CamelModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str | None
    work_order_id: str
    site_id: str
    cycle_number: Annotated[int, Field(ge=1)]
    stage: AcquisitionRunStage
    next_action: AcquisitionNextAction
    detail: str
    readiness: AcquisitionReadinessView
    mission: AcquisitionMissionProgressView
    gateway: AcquisitionGatewayProgressView
    contract_activation: AcquisitionContractProgressView
    media: AcquisitionMediaProgressView
    processing: AcquisitionProcessingProgressView
    # 모든 조립이 Coverage/CaptureQuality/Media/Processing 원장을 갖는 것은 아니다.
    # None은 READY가 아니라 "증거 projection이 장착되지 않음"을 뜻한다.
    analysis_readiness: AnalysisReadinessView | None = None
    evaluated_at: datetime
    in_flight_contract_policy: Literal["REMAINS_VALID_UNTIL_CONTRACT_EXPIRY"]


RC_REQUIRED_CAPABILITIES = frozenset(AcquisitionCapability)


__all__ = [
    "AcquisitionCapability",
    "AnalysisReadinessStatus",
    "AnalysisReadinessView",
    "AcquisitionDeploymentProfileV1",
    "AcquisitionContractProgressView",
    "AcquisitionGatewayProgressView",
    "AcquisitionMediaProgressView",
    "AcquisitionMediaState",
    "AcquisitionMissionProgressView",
    "AcquisitionNextAction",
    "AcquisitionProcessingProgressView",
    "AcquisitionProcessingState",
    "AcquisitionProgressView",
    "AcquisitionReadinessView",
    "AcquisitionRunStage",
    "AcquisitionRunV1",
    "CapabilityReceiptV1",
    "CapabilityStatus",
    "ConnectionState",
    "ConnectivitySnapshotV1",
    "DirectEdgeState",
    "GatewayKind",
    "GatewayOperationOutcome",
    "GatewayOperationReceiptRequest",
    "GatewayOperationReceiptV1",
    "GatewayTransport",
    "InternetGate",
    "ManifoldDirectMode",
    "MediaPolicy",
    "MsdkBridgeMode",
    "OperatingMode",
    "ObservationEpochView",
    "RC_REQUIRED_CAPABILITIES",
    "ReadinessStatus",
    "RoutingPolicy",
    "SyncState",
]
