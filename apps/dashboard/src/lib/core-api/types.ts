// contracts/api/openapi-core.yaml (v1.4.0) + services/core/src/ksi_core 응답 모델과 1:1 대응.
// 필드명은 서버의 alias_generator=to_camel 산출물 그대로(카멜케이스) 사용한다.

export const SITE_STATUSES = [
  "UNMAPPED",
  "BASELINE_MAPPING",
  "MODEL_PROCESSING",
  "MODEL_VALIDATION",
  "PROVISIONAL_AUTONOMY",
  "PATROL_READY",
  "PATROL_ACTIVE",
  "MODEL_STALE",
  "REMAP_REQUIRED",
  "SUSPENDED",
] as const;
export type SiteStatus = (typeof SITE_STATUSES)[number];

export interface SiteFrame {
  crs: string;
  verticalDatum: string;
  unit: "meter";
  transformVersion: string;
}

export interface SiteView {
  siteId: string;
  name: string;
  siteFrame: SiteFrame;
  status: SiteStatus;
  resumeTarget: SiteStatus | null;
  registeredAt: string;
  updatedAt: string;
}

export const EVENT_STATUSES = [
  "OBSERVATION",
  "CANDIDATE",
  "EVIDENCE_COLLECTION",
  "FINDING",
  "CONFIRMED_EVENT",
  "DISMISSED",
  "UNRESOLVED",
] as const;
export type EventStatus = (typeof EVENT_STATUSES)[number];

export const EVENT_SEVERITIES = ["CANDIDATE", "MEDIUM", "HIGH", "CRITICAL"] as const;
export type EventSeverity = (typeof EVENT_SEVERITIES)[number];

export const TRIAGE_STATUSES = [
  "NONE",
  "ASSIGNED",
  "ACTION_IN_PROGRESS",
  "REINSPECTION_REQUESTED",
  "RESOLVED",
  "CLOSED",
] as const;
export type TriageStatus = (typeof TRIAGE_STATUSES)[number];

export interface EventSummaryResponse {
  eventKey: string;
  eventId: string;
  siteId: string;
  missionId: string;
  // 무슨 일이 일어났는가. 목록 행의 1순위 정보다.
  // 자유 문자열이며 사람이 읽을 라벨 변환은 labels.ts 가 맡는다. 저장된 bundle 에
  // 이 키가 없는 레코드는 null 로 온다(서버가 목록 전체를 죽이지 않고 낮춰 응답).
  eventType: string | null;
  status: EventStatus;
  severity: EventSeverity | null;
  triage: TriageStatus;
  assignee: string | null;
  edgeDeviceId: string;
  occurredAt: string;
  receivedAt: string;
}

/** 증거 1건. 열람 URL 은 없다 — URL 이 곧 인가라 별도 요청으로 발급받는다. */
export interface EvidenceSummary {
  artifactId: string;
  contentType: string;
  registeredAt: string;
  registeredBy: string;
  /** 값이 있으면 보관 정책으로 폐기된 것 — "없음"과 구분해서 보여준다. */
  tombstonedAt: string | null;
  tombstoneReason: string | null;
}

export interface EventDetailResponse extends EventSummaryResponse {
  lastConflictAt: string | null;
  bundle: Record<string, unknown>;
  transitions: Array<Record<string, unknown>>;
  evidence: EvidenceSummary[];
}

/** POST /api/events/{eventKey}/evidence 응답 — presigned PUT URL. */
export interface EvidenceUploadResponse {
  artifactId: string;
  objectKey: string;
  uploadUrl: string;
  expiresAt: string;
}

/** GET /api/events/{eventKey}/evidence/{artifactId} 응답 — presigned GET URL. */
export interface EvidenceViewResponse {
  artifactId: string;
  contentType: string;
  viewUrl: string;
  expiresAt: string;
  registeredAt: string;
  registeredBy: string;
}

export interface EventTransitionInput {
  targetStatus?: EventStatus;
  triageTarget?: TriageStatus;
  reason?: string;
  assignee?: string;
}

export interface TransitionResponse {
  verdict: string;
  detail: string | null;
  event: EventDetailResponse | null;
}

export const MISSION_TYPES = [
  "UNIFIED_SITE_SURVEY",
  "BASELINE_MAPPING",
  "SPATIAL_REFRESH",
  "AUTONOMOUS_PATROL",
  "ASSET_INSPECTION",
  "PROGRESS_CAPTURE",
  "INCIDENT_SURVEY",
  "SURVEY_GRADE_MAPPING",
] as const;
export type MissionType = (typeof MISSION_TYPES)[number];

export interface MissionRecordResponse {
  missionId: string;
  siteId: string;
  missionType: MissionType;
  artifactKind: "pair" | "contract";
  kmzSha256: string | null;
  routePattern: "lawnmower" | "perimeter" | null;
  waypointCount: number | null;
  coverageRatio: number | null;
  issuedAt: string;
  issuedBy: string;
}

export type Role = "ADMIN" | "SITE_MANAGER" | "SAFETY_MANAGER" | "DRONE_OPERATOR" | "VIEWER";

export type Permission =
  | "SITES_READ"
  | "SITES_WRITE"
  | "MISSIONS_READ"
  | "MISSIONS_ISSUE"
  | "EVENTS_READ"
  | "EVENTS_TRIAGE"
  | "EDGE_SYNC_INGEST";

export interface WhoAmIResponse {
  principalId: string;
  kind: "OPERATOR" | "EDGE_DEVICE";
  role: Role | null;
  deviceId: string | null;
  permissions: Permission[];
}

// POST /v1/missions/plans (ADR-KSI-007, S1) — AOI + 임무타입 한 요청이 KMZ/WPML + 서명계약
// 짝을 낳는다. 대시보드 Wizard가 직접 호출하는 실경로(§ openapi /sites/{id}/missions 는
// x-status: planned 스케치일 뿐 미구현).

export interface FlightEnvelopeInput {
  allowedVolumes: string[];
  excludedVolumes: string[];
  minAltitudeM: number;
  maxAltitudeM: number;
  minimumStructureStandoffM?: number;
  minimumPersonStandoffM?: number;
}

export interface MissionPlanContractInput {
  missionId: string;
  siteId: string;
  missionType: MissionType;
  siteFrame: SiteFrame;
  flightEnvelope: FlightEnvelopeInput;
  objectives: string[];
  viewpointPolicyId: string;
  riskPolicyPackId: string;
  fallbackPolicyId: string;
  capturePolicyId: string;
  accessibleGeneralCoverage?: number;
  validForHours?: number;
}

export interface AoiVertex {
  latDeg: number;
  lonDeg: number;
}

export interface MissionPlanRouteInput {
  altitudeM: number;
  /** lawnmower 스캔선 간격(m) — 측면 중첩을 정한다. */
  spacingM?: number;
  /**
   * lawnmower 진행방향 촬영 간격(m) — 스캔선 위 촬영 지점 간격.
   * 매핑 계열에서 빠지면 서버가 422 로 거부한다(전방 중첩 0 → 재구성 불성립).
   */
  captureIntervalM?: number;
  sweepDirectionDeg?: number;
}

export interface MissionPlanDroneInput {
  droneEnumValue: number;
  droneSubEnumValue: number;
  payloadEnumValue: number;
  payloadPositionIndex?: 0 | 1 | 2;
}

export interface MissionPlanWaylineInput {
  autoFlightSpeedMs: number;
  takeoffSecurityHeightM: number;
  globalTransitionalSpeedMs: number;
}

export interface MissionPlanRequest {
  contract: MissionPlanContractInput;
  aoi: { vertices: AoiVertex[] };
  route: MissionPlanRouteInput;
  drone: MissionPlanDroneInput;
  wayline: MissionPlanWaylineInput;
}

export interface MissionPlanResponse {
  contract: Record<string, unknown>;
  kmzBase64: string;
  kmzSha256: string;
  routePattern: "lawnmower" | "perimeter";
  waypointCount: number;
  coverageRatio: number | null;
}
