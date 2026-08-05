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
  /** 설정된 적 없으면 null(등록 시 생략 또는 아직 PUT .../aoi 를 거치지 않음). */
  aoi: { vertices: AoiVertex[] } | null;
  /**
   * 데이터 반출 선언(INV-050). null 은 "미선언"이고 그 뜻은 **반출 불가**다 —
   * 화면이 null 을 "아직 모름"으로 읽어 허용처럼 보여주면 안 된다.
   */
  dataResidency: DataResidency | null;
}

/** 처리 작업의 벤더 클라우드 실행 가부를 정하는 현장 속성(INV-050). */
export interface DataResidency {
  egressAllowed: boolean;
  jurisdiction: string;
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
  /**
   * 현재 bundle 의 정규화 digest. 트리아지 전이 요청의 expectedBundleDigest 에
   * 그대로 실으면, 화면을 연 뒤 Edge 가 내용을 바꿨을 때 서버가 409 로 막는다
   * (직접 계산하면 JSON 표기 차이로 영구 409 가 되므로 이 값을 그대로 쓴다).
   */
  bundleDigest: string;
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

export const COMPLETION_STATES = [
  "COMPLETED",
  "COMPLETED_WITH_GAPS",
  "ABORTED_SAFE",
  "FAILED",
] as const;
export type CompletionState = (typeof COMPLETION_STATES)[number];

export interface MissionRecordResponse {
  missionId: string;
  siteId: string;
  missionType: MissionType;
  artifactKind: "pair" | "contract";
  kmzSha256: string | null;
  routePattern: "lawnmower" | "perimeter" | null;
  waypointCount: number | null;
  plannedCoverageRatio: number | null;
  issuedAt: string;
  issuedBy: string;
  /**
   * 파생 필드 — 이 임무에 대해 접수된 최신 CoverageReport 의 completionState(서버가
   * 조회 시점에 계산, 대시보드는 재계산하지 않는다). null 이면 "아직 보고가 없다"다 —
   * 발급됐지만 비행 전인지, 비행했는데 보고가 없는지는 이 값만으로 구분되지 않는다
   * (missions/[missionId] 상세의 GET .../coverage-report 404 와 함께 봐야 한다).
   */
  coverageCompletionState: CompletionState | null;
}

export const COVERAGE_CELL_STATES = [
  "OBSERVED_HIGH_CONFIDENCE",
  "OBSERVED_PARTIAL",
  "RECONSTRUCTION_READY",
  "EVENT_INSPECTED",
  "OCCLUDED",
  "UNREACHABLE",
  "NOT_OBSERVED",
  "UNSAFE",
  "SENSOR_LIMITED",
  "TIME_LIMITED",
  "BATTERY_LIMITED",
] as const;
export type CoverageCellState = (typeof COVERAGE_CELL_STATES)[number];

/** 구조 정본은 contracts/schemas/coverage-report.v1.1.json. */
export interface CoverageCell {
  cellId: string;
  state: CoverageCellState;
  quality?: number;
  geometryRef?: string;
}

export interface CoverageSummary {
  mandatoryHazardRatio: number;
  mandatoryAssetRatio: number;
  accessibleGeneralRatio: number;
  completionState: CompletionState;
}

/** 비행 1회의 커버리지 보고 본문(GET .../coverage-report 의 latest). */
export interface CoverageReport {
  missionId: string;
  siteId: string;
  timestamp: string;
  cells: CoverageCell[];
  summary: CoverageSummary;
}

export interface CoverageReportView {
  missionId: string;
  reportCount: number;
  latest: CoverageReport;
  /** 제출한 Principal id(보통 장비 id). 구 journal 재생 등으로 없으면 null. */
  reportedBy: string | null;
}

// 3역할(ADR-KSI-015 D1) — 구 5역할 중 현장관리·안전관리·드론운영 3개는
// FIELD_OPERATOR 하나로 합쳐졌다(구 역할 이름은 ADR-KSI-015 참조).
export type Role = "ADMIN" | "FIELD_OPERATOR" | "VIEWER";

export type Permission =
  | "SITES_READ"
  | "SITES_WRITE"
  | "MISSIONS_READ"
  | "MISSIONS_ISSUE"
  | "EVENTS_READ"
  | "EVENTS_TRIAGE"
  | "EDGE_SYNC_INGEST"
  // blast radius 가 큰 site 전이(자율 시작 승인·정식 순찰 승인·SUSPENDED
  // 진입/복귀)만 가르는 관리자 전용 권한(ADR-KSI-015 D2).
  | "SITES_AUTONOMY_APPROVE";

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

/**
 * 매핑 카메라 스펙 + 원하는 겹침 — 주면 서버가 격자 간격을 계산한다(권장 경로).
 *
 * 간격을 직접 적으면 서버는 그 값이 적정한지 판단할 근거가 없다. 겹침은 카메라
 * 촬영폭 없이 계산할 수 없기 때문이다(ADR-KSI-011 D3).
 */
export interface MissionPlanCameraInput {
  sensorWidthMm: number;
  focalLengthMm: number;
  /** across-track(라인 간격을 결정) */
  imageWidthPx: number;
  /** along-track(사진 간격을 결정) */
  imageHeightPx: number;
  /** 진행방향 겹침. 서버 하한 0.6 — 그 아래는 재구성이 실패한다. */
  frontOverlap?: number;
  /** 라인 간 겹침. 서버 하한 0.5. */
  sideOverlap?: number;
}

export interface MissionPlanRouteInput {
  altitudeM: number;
  /**
   * 주면 서버가 spacingM·captureIntervalM 을 계산하고 근거를 gridBasis 로 돌려준다.
   * spacingM/captureIntervalM 과 **함께 줄 수 없다**(422).
   */
  camera?: MissionPlanCameraInput;
  /** lawnmower 스캔선 간격(m) — camera 를 주지 않을 때만 쓴다. */
  spacingM?: number;
  /** lawnmower 진행방향 촬영 간격(m) — camera 를 주지 않을 때만 쓴다. */
  captureIntervalM?: number;
  sweepDirectionDeg?: number;
}

/** 서버가 간격을 계산한 근거 — camera 를 줬을 때만 실린다. */
export interface MissionPlanGridBasis {
  spacingM: number;
  captureIntervalM: number;
  /** 지상표본거리(m/px) */
  gsdM: number;
  footprintAcrossM: number;
  footprintAlongM: number;
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
  /** camera 로 계산했을 때만 실린다 — 직접 지정이면 null. */
  gridBasis: MissionPlanGridBasis | null;
  plannedCoverageRatio: number | null;
}
