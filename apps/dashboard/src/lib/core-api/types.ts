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
   * 이 임무를 수행할 것으로 신고된 장비(INV-010). null 이면 배정을 신고하지
   * 않은 것 — 그 임무는 인증된 어느 EDGE_DEVICE 든 커버리지를 보고할 수 있다.
   */
  assignedDeviceId: string | null;
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
  /**
   * Coverage Recovery 권고(MASTER_PRD §15.2) — completionState 가 COMPLETED 가
   * 아니거나(COMPLETED_WITH_GAPS/ABORTED_SAFE/FAILED 전부) 사유있는 미관찰 Cell 이
   * 남아 있으면 true. 자동 재발급을 트리거하지 않는다 — 운영자가 원본 site AOI 로
   * SPATIAL_REFRESH 임무를 재발급하라는 신호일 뿐이다.
   */
  recoveryRecommended: boolean;
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

// ── Phase 3/4 표면 (2026-08-08 신설) ────────────────────────────────────────
//
// 서버 응답의 camelCase 를 그대로 옮긴다 — 화면이 판정을 다시 계산하지 않는다.
// 특히 productionSupported·revisitRecommended·reobservationRecommended 는 전부
// **서버가 계산한 파생값**이다: 화면이 state 문자열이나 비율을 보고 스스로
// 판단하면 규칙이 두 곳에 생기고, 그 갈라짐은 화면에서 보이지 않는다.

export interface DefectCandidate {
  schemaVersion: "1.0";
  defectCandidateId: string;
  defectType: "CRACK";
  sourceMediaId: string;
  imageSize: { widthPx: number; heightPx: number };
  geometry: { format: "IMAGE_POLYGON_2D"; payload: Array<[number, number]> | null };
  model: { modelId: string; sourceDigests: Record<string, string> };
  confidence: number;
  measurements?: { areaPx2?: number; lengthPx?: number; meanWidthPx?: number };
}

export interface DefectCandidateItem {
  candidate: DefectCandidate;
  reportedBy: string | null;
  recordedAt: string;
}

export interface DefectCandidateListView {
  missionId: string;
  candidateCount: number;
  /** 후보가 하나라도 걸린 사진 id(정렬됨) — 화면이 전체를 훑어 집계하지 않게 서버가 낸다. */
  sourceMediaIds: string[];
  candidates: DefectCandidateItem[];
}

export interface ChangeDetectionResult {
  schemaVersion: "1.0";
  changeDetectionId: string;
  baseline: { jobId: string; artifactId: string };
  current: { jobId: string; artifactId: string };
  distanceThresholdM: number;
  pointCount: number;
  candidateCount: number;
  candidateRatio: number;
  maxDistanceM: number | null;
  computedAt: string;
}

export interface ChangeDetectionView {
  missionId: string;
  resultCount: number;
  latest: ChangeDetectionResult;
  reportedBy: string | null;
  recordedAt: string;
  /** 이 조회가 **실제로 쓴** 임계값 — 권고가 무슨 기준으로 켜졌는지 화면이 밝힐 수 있게. */
  revisitRatioThreshold: number;
  revisitRecommended: boolean;
}

/** 구역 하나의 절토·성토 — 부호는 `netM3` 하나로만 말한다(양수 cut/fill). */
export interface ZoneVolumeDelta {
  zoneId: string;
  cutM3: number;
  fillM3: number;
  netM3: number;
  areaM2: number;
  thresholdM: number;
  /**
   * **양쪽 epoch 모두** 검증된 RMSE 가 있을 때만 값이다(INV-024). 기본 엔진
   * (ODM)에는 구조화된 GCP/검사점 리포트가 없어 지금은 항상 null 이며, 그때
   * `uncertaintyNote` 가 왜 없는지를 말한다 — 화면은 이 둘을 함께 보여야 한다.
   */
  uncertaintyM3: number | null;
  uncertaintyNote: string;
}

export interface VolumeChangeReport {
  schemaVersion: string;
  volumeChangeId: string;
  baseline: { jobId: string; artifactId: string };
  current: { jobId: string; artifactId: string };
  crs: string;
  /** `ellipsoidal_native` = 지오이드 미적용 타원체고(정표고로 못 바꾼 상태). */
  verticalDatum: string;
  zones: ZoneVolumeDelta[];
  computedAt: string;
}

export interface VolumeChangeEntry {
  report: VolumeChangeReport;
  reportedBy: string | null;
  recordedAt: string;
}

export interface VolumeChangeListView {
  missionId: string;
  reportCount: number;
  /** 최신 리포트의 전 구역 순변화 — 서버가 계산해 싣는다(화면이 합산하지 않는다). */
  latestTotalNetM3: number | null;
  reports: VolumeChangeEntry[];
}

/**
 * ODM 산출물 하나의 등록 계약 payload 그대로다(Core `processing_artifact` 스키마).
 * 화면이 실제로 쓰는 필드만 좁혀 선언한다 — 나머지(digest·lineage 등)는 지금
 * 화면에 필요 없다.
 */
export interface ProcessingArtifactSummary {
  artifactId: string;
  /** `"ortho"` | `"dsm"` | `"dtm"` | `"mesh"` | `"point_cloud"` | `"camera_poses"` | `"report"`. */
  kind: string;
}

/** GET /v1/processing-jobs/{jobId} — 화면이 쓰는 필드만. */
export interface ProcessingJobArtifactsView {
  jobId: string;
  status: string;
  artifacts: ProcessingArtifactSummary[];
}

/** GET /v1/processing-jobs/{jobId}/artifacts/{artifactId}/download 응답. */
export interface ArtifactFileView {
  name: string;
  objectKey: string;
  downloadUrl: string;
}

export interface ArtifactDownloadResponse {
  verdict: string;
  objectKey: string | null;
  downloadUrl: string | null;
  expiresAt: string | null;
  // 산출물이 파일 여러 개(메시 등)일 때만 채워진다 — 주 파일을 포함해 전부
  // 나열한다(mesh-multi-file-artifact-persistence).
  files: ArtifactFileView[] | null;
  detail: string | null;
}

export interface KinematicState {
  entityId: string;
  observedAt: string;
  siteFrame: string;
  position: [number, number, number];
  positionCovariance: number[];
  velocity: [number, number, number];
  velocityCovariance: number[];
  headingDeg: number | null;
  sourceClass: string;
}

export interface EquipmentStateItem {
  state: KinematicState;
  reportedBy: string | null;
  recordedAt: string;
  /** 공분산 trace 의 제곱근(RMS 반경 근사) — 좌표축 회전에 불변. */
  positionUncertaintyM: number;
}

export interface EquipmentStateListView {
  siteId: string;
  entityCount: number;
  entities: EquipmentStateItem[];
}

export interface RiskAssessmentView {
  siteId: string;
  equipmentEntityId: string;
  subjectEntityId: string;
  observationGapS: number;
  closestApproachM: number;
  closestApproachTimeS: number;
  /** null 은 "위험 없음"이 아니라 **"이 지평선 안에서는 확인되지 않음"**이다. */
  timeToCollisionS: number | null;
  horizonS: number;
  combinedRadiusM: number;
  positionUncertaintyThresholdM: number;
  reobservationRecommended: boolean;
}

export type EquipmentSupportLevel =
  | "DATASET_AVAILABLE"
  | "BASELINE_DETECTION"
  | "FIELD_VALIDATED"
  | "GEO_VALIDATED"
  | "RISK_VALIDATED"
  | "PRODUCTION_SUPPORTED";

export interface EquipmentSupportView {
  classId: string;
  state: EquipmentSupportLevel;
  evidenceRefs: string[];
  modelVersion: string | null;
  riskPackVersion: string | null;
  /** **이 값이 true 인 것만 상용 지원으로 표시한다**(REQ-MODEL-101). 서버 파생값. */
  productionSupported: boolean;
  updatedAt: string;
  updatedBy: string;
}

export interface EquipmentSupportListView {
  classCount: number;
  productionSupportedCount: number;
  classes: EquipmentSupportView[];
}

export interface SourceMediaViewResponse {
  mediaId: string;
  contentType: string;
  viewUrl: string;
  expiresAt: string;
  /** 업로더가 **신고한** 화소수 — 결함 후보 폴리곤의 좌표계 기준이다. */
  width: number;
  height: number;
  sha256: string;
}

// ── 원본 사진 업로드 · 재구성 발행 (M3, B1/B2) ──────────────────────────────
//
// 파일 바이트는 대시보드 서버를 거치지 않는다 — presigned uploadUrl 로 브라우저가
// 스토리지에 직접 PUT 한다(EvidencePanel 과 동일 원칙, ADR-KSI-010 §1).

export interface SourceMediaFileClaim {
  mediaId: string;
  sha256: string;
  bytes: number;
  width: number;
  height: number;
  contentType: string;
}

export interface SourceMediaItemResultView {
  mediaId: string;
  verdict: string;
  objectKey: string | null;
  uploadUrl: string | null;
  expiresAt: string | null;
  detail: string | null;
}

export interface SourceMediaBatchResponse {
  verdict: string;
  detail: string | null;
  results: SourceMediaItemResultView[];
}

export type SourceMediaBundleStatus = "OPEN" | "SEALED";

export interface SourceMediaBundleView {
  missionId: string;
  status: SourceMediaBundleStatus;
  mediaCount: number;
  sourceBundleDigest: string | null;
  sealedAt: string | null;
  /** null 이면 아직 아무도 안 쟀다 — "검증 실패"와 다르다(모듈 docstring). */
  verifiedAt: string | null;
  lastMismatchAt: string | null;
}

export interface SourceMediaSealResponse {
  verdict: string;
  detail: string | null;
  bundle: SourceMediaBundleView | null;
}

/** POST /v1/missions/{missionId}/processing-jobs 요청 — 무엇으로 어디서 돌릴지만. */
export interface ProcessingJobIssueInput {
  provider: "odm";
  engineVersion: string;
  engineDigest: string;
  executionLocus: string;
  licenseBasis: { licenseId: string; tier: string; attributionRequired: boolean };
  processingParams: Record<string, unknown>;
}

/** 발급/조회 응답의 job 필드 — 화면이 쓰는 필드만 좁혀 선언한다(ProcessingJobView 전체 아님). */
export interface ProcessingJobSummary {
  jobId: string;
  status: string;
  issuedAt: string;
  detail: string | null;
}

export interface ProcessingJobMutationResponse {
  verdict: string;
  detail: string | null;
  job: ProcessingJobSummary | null;
}

export interface ProcessingJobListSummary {
  jobs: ProcessingJobSummary[];
}

// ── 두 시점 비교(W2) ────────────────────────────────────────────────────────

/**
 * 현장 단위 epoch 목록의 항목 — `GET /v1/sites/{siteId}/processing-jobs`.
 *
 * 임무별 목록과 같은 서버 모델(`ProcessingJobView`)이라 `artifacts` 가 함께 온다.
 * 화면은 그 배열로 "이 epoch 에 point_cloud·dsm 이 있는가"를 판단한다 — 비교
 * 가능 여부를 제출 전에 보여주기 위해 산출물마다 다시 조회하지 않는다.
 */
export interface SiteProcessingJobSummary {
  jobId: string;
  missionId: string;
  siteId: string;
  status: string;
  issuedAt: string;
  detail: string | null;
  artifacts: ProcessingArtifactSummary[];
}

export interface SiteProcessingJobListResponse {
  jobs: SiteProcessingJobSummary[];
}

/**
 * 비교 계산이 실제로 쓰는 고정 기준값 — `GET /v1/comparison-policy`.
 *
 * **화면은 이 값을 표시만 한다**(대표자 확정: 사용자가 임계값을 입력하지 않는다).
 * 숫자를 화면 코드에 복제하지 않는 이유는 계산 쪽이 바뀌어도 화면이 옛 숫자를
 * 계속 말하게 되기 때문이다 — 서버가 정본을 내려준다.
 */
export interface ComparisonPolicyView {
  schemaVersion: string;
  policyVersion: string;
  distanceThresholdM: number;
  volumeThresholdM: number;
  revisitRatioThreshold: number;
}

/** 비교 요청 1건의 계약 payload(`comparison-request.v1.json`). */
export interface ComparisonRequestContract {
  schemaVersion: string;
  requestId: string;
  missionId: string;
  siteId: string;
  baselineJobId: string;
  currentJobId: string;
  pointCloudBaseline: ArtifactRefView | null;
  pointCloudCurrent: ArtifactRefView | null;
  changeDetectionEligible: boolean;
  changeDetectionIneligibleReason: string | null;
  dsmBaseline: ArtifactRefView | null;
  dsmCurrent: ArtifactRefView | null;
  volumeChangeEligible: boolean;
  volumeChangeIneligibleReason: string | null;
  zones: Record<string, Record<string, unknown>> | null;
  zoneCrs: string | null;
  /** 이 요청이 실제로 쓸/쓴 기준값의 불변 스냅샷 — 시스템 값이 바뀌어도 그대로다. */
  policy: ComparisonPolicyView;
  status: string;
  requestedAt: string;
  requestedBy: string;
  updatedAt: string;
  /** 종료 상태에서만 채워진다 — FAILED 로 끝난 이유. */
  detail: string | null;
}

export interface ArtifactRefView {
  jobId: string;
  artifactId: string;
}

export interface ComparisonRequestMutationResponse {
  verdict: string;
  request: ComparisonRequestContract | null;
  detail: string | null;
}

export interface ComparisonRequestListResponse {
  requests: ComparisonRequestContract[];
}

/** `GET /v1/comparison-requests/{requestId}` — 계약 payload + 운영 메타. */
export interface ComparisonRequestDetailView {
  request: ComparisonRequestContract;
  leaseWorkerId: string | null;
  leaseExpiresAt: string | null;
}

/** 제출 본문 — 무엇을 비교할지와 확정한 구역만 정한다(임계값 자리는 없다). */
export interface ComparisonRequestCreateInput {
  baselineJobId: string;
  currentJobId: string;
  zones?: Record<string, Record<string, unknown>> | null;
  zoneCrs?: string | null;
}

// ── 설계 기준면 · 설계 대비 잔량 (M4-A) ─────────────────────────────────────
//
// 이 블록의 규율 하나: **선언(declared)과 관측(observed)을 절대 한 평면에 섞지
// 않는다.** 서버 계약(contracts/schemas/design-surface.v1.json)이 두 블록을
// 이름으로 갈라 두었고, 화면이 그것을 하나로 합치는 순간 사용자는 "내가 적은
// 값"과 "파일에서 읽어낸 값"을 구분할 수 없게 된다 — 그 구분이 이 기능의 전부다.

export const DESIGN_SURFACE_STATUSES = [
  "REGISTERED",
  "SEALED",
  "VERIFIED",
  "REJECTED",
] as const;
export type DesignSurfaceStatus = (typeof DESIGN_SURFACE_STATUSES)[number];

/**
 * 설계면이 비교 입력이 되지 못하는 typed 사유 8종
 * (`ksi_core.design_surfaces.DesignSurfaceRejectionReason`).
 *
 * 서버가 코드를 주고 화면이 한국어로 옮긴다(labels.ts) — 서버의 `detail` 문장을
 * 그대로 띄우면 내부 어휘가 사용자에게 새어 나간다.
 */
export const DESIGN_SURFACE_REJECTION_REASONS = [
  "DIGEST_MISMATCH",
  "CRS_DECLARATION_MISMATCH",
  "UNSUPPORTED_CRS",
  "UNSUPPORTED_UNIT",
  "UNSUPPORTED_BAND_COUNT",
  "NO_FINITE_CELLS",
  "VERTICAL_DECLARATION_CONTRADICTED",
  "UNREADABLE_RASTER",
] as const;
export type DesignSurfaceRejectionReason = (typeof DESIGN_SURFACE_REJECTION_REASONS)[number];

/** 높이의 기준 + 그 기준을 아는 근거 + 귀속(`vertical_reference.VerticalReference`). */
export interface VerticalReference {
  /**
   * `ellipsoidal` · `ellipsoidal_native` · `orthometric_kngeoid2018` ·
   * `orthometric_kngeoid2024`.
   */
  datum: string;
  /** 왜 이 값을 아는가 — 비울 수 없다(계약이 강제). */
  basis: string;
  /** `user_declared`(업로더 주장) · `pipeline_declared`(우리 파이프라인 귀속). */
  source: string;
}

/** 업로더의 주장 한 벌 — **이 안의 값은 어느 것도 확인되지 않았다.** */
export interface DesignSurfaceDeclared {
  crs: string;
  lengthUnit: "meter";
  sha256: string;
  verticalReference: VerticalReference;
}

/** 신뢰 경로(워커)가 파일을 열어 **실제로 잰 값** 한 벌 — 판정은 들어 있지 않다. */
export interface DesignSurfaceObserved {
  sha256: string;
  crs: string;
  /** compound CRS 의 수직 성분. 대부분의 DEM 에는 없다(null 이 정상). */
  verticalCrsEpsg: number | null;
  width: number;
  height: number;
  bandCount: number;
  dtype: string;
  nodata: number | null;
  nodataIsNan: boolean;
  pixelSizeXM: number;
  pixelSizeYM: number;
  transform: [number, number, number, number, number, number];
  boundsMinX: number;
  boundsMinY: number;
  boundsMaxX: number;
  boundsMaxY: number;
  finiteCellCount: number;
  measuredAt: string;
  measuredBy: string;
}

/** 설계 기준면 자산 1건(`contracts/schemas/design-surface.v1.json`). */
export interface DesignSurface {
  schemaVersion: string;
  designSurfaceId: string;
  siteId: string;
  name: string;
  revision: string;
  format: "geotiff";
  declared: DesignSurfaceDeclared;
  /** 아직 아무도 재지 않았으면 null. REJECTED 인데 null 인 경우도 정상이다. */
  observed: DesignSurfaceObserved | null;
  status: DesignSurfaceStatus;
  /** REJECTED 일 때의 typed verdict — 그 외 상태에서는 null. */
  rejectionReason: string | null;
  registeredAt: string;
  registeredBy: string;
  /** 클라이언트가 업로드 완료를 **주장한** 시각이다 — 파일을 확인한 시각이 아니다. */
  sealedAt: string | null;
  verifiedAt: string | null;
}

/** POST /v1/sites/{siteId}/design-surfaces 요청 본문. */
export interface DesignSurfaceRegisterInput {
  name: string;
  revision: string;
  declared: DesignSurfaceDeclared;
}

export interface DesignSurfaceRegisterResponse {
  verdict: string;
  detail: string | null;
  designSurfaceId: string | null;
  objectKey: string | null;
  /** REGISTERED 일 때만 채워진다 — 발급 실패는 STORE_UNAVAILABLE 로 격하된다. */
  uploadUrl: string | null;
  expiresAt: string | null;
  surface: DesignSurface | null;
}

export interface DesignSurfaceSealResponse {
  verdict: string;
  detail: string | null;
  surface: DesignSurface | null;
}

export interface DesignSurfaceListResponse {
  surfaces: DesignSurface[];
}

/** 요청 1건의 조회 표현 — 지시 + 요청 시점 스냅샷 + 운영 메타. */
export interface DesignConformanceRequestView {
  requestId: string;
  /** 리포트 id — requestId 에서 결정적으로 도출된다. */
  designConformanceId: string;
  missionId: string;
  siteId: string;
  designSurfaceId: string;
  /** 요청 시점 VERIFIED 설계면의 **관측된** 해시(접두사 없는 16진). */
  designSurfaceSha256: string;
  current: ArtifactRefView;
  zones: Record<string, Record<string, unknown>>;
  zoneCrs: string;
  policy: ComparisonPolicyView;
  status: string;
  requestedAt: string;
  requestedBy: string;
  updatedAt: string;
  detail: string | null;
  leaseWorkerId: string | null;
  leaseExpiresAt: string | null;
  /** Core 가 차분 래스터 바이트를 직접 재해싱해 확인한 값 — 아직 없으면 null. */
  diffRasterDigest: string | null;
  diffRasterVerifiedAt: string | null;
}

export interface DesignConformanceRequestMutationResponse {
  verdict: string;
  request: DesignConformanceRequestView | null;
  detail: string | null;
}

export interface DesignConformanceRequestListResponse {
  requests: DesignConformanceRequestView[];
}

/**
 * 제출 본문 — 어느 설계면을 어느 재구성 결과와 견줄지 + 확정한 구역.
 *
 * 구역을 주는 길은 둘이고 **동시에 쓸 수 없다**(M4-C): 등록된 작업구역을 고르거나
 * (`workAreaIds`), 즉석 폴리곤을 싣거나(`zones`/`zoneCrs`). 앞의 것만 다음 시점의
 * 리포트와 이어져 진척이 나온다 — 즉석 폴리곤은 매번 좌표가 달라 시계열이 끊긴다.
 */
export interface DesignConformanceRequestCreateInput {
  designSurfaceId: string;
  currentJobId: string;
  workAreaIds?: string[] | null;
  zones?: Record<string, Record<string, unknown>> | null;
  zoneCrs?: string | null;
}

/**
 * 현장에 영구적으로 사는 작업구역(M4-C) — 기하는 등록 후 불변이다.
 *
 * 고치면 새 구역이고 `supersedes` 가 이전 것을 가리킨다(그때 이전 구역은 보관된다).
 * 제자리 수정을 허용하면 이미 그 구역으로 낸 리포트가 가리키는 범위가 사후에 바뀐다.
 */
export interface WorkArea {
  schemaVersion: string;
  workAreaId: string;
  siteId: string;
  name: string;
  polygon: Record<string, unknown>;
  crs: string;
  status: "ACTIVE" | "ARCHIVED";
  supersedes: string | null;
  createdAt: string;
}

export interface WorkAreaListResponse {
  workAreas: WorkArea[];
}

export interface WorkAreaResponse {
  verdict: string;
  detail: string | null;
  workArea: WorkArea | null;
}

export interface WorkAreaRegisterInput {
  name: string;
  polygon: Record<string, unknown>;
  crs: string;
  supersedes?: string | null;
}

/**
 * 구역 하나의 계획 대비 진척 — 절토와 성토를 **합치지 않는다**.
 *
 * 합계 하나로 뭉개면 "5000 깎고 5000 쌓는" 현장과 "아무것도 안 한" 현장이 같은
 * 숫자가 된다. 비율이 `null` 이면 그 방향의 계획이 없다는 뜻이고, `0%` 로 그리면
 * "할 일이 있는데 하나도 안 했다"는 반대 뜻이 된다 — `basis` 가 이유를 적는다.
 */
export interface ZoneProgress {
  zoneId: string;
  zoneName: string | null;
  plannedCutM3: number;
  plannedFillM3: number;
  remainingCutM3: number;
  remainingFillM3: number;
  /** 계획 − 잔여. **음수일 수 있다**(되메우기·재시공·붕괴). */
  doneCutM3: number;
  doneFillM3: number;
  cutProgressRatio: number | null;
  fillProgressRatio: number | null;
  basis: string;
}

export interface DesignProgress {
  schemaVersion: string;
  siteId: string;
  designSurfaceId: string;
  designSurfaceSha256: string;
  baselineDesignConformanceId: string;
  /** 기준 시점 — **화면이 항상 함께 띄운다**(이미 시공된 뒤면 계획이 과소 계상된다). */
  baselineComputedAt: string;
  latestDesignConformanceId: string;
  latestComputedAt: string;
  thresholdM: number;
  zones: ZoneProgress[];
}

/** `progress` 와 `detail` 중 하나는 항상 채워진다 — 빈 표를 내지 않는다. */
export interface DesignProgressResponse {
  progress: DesignProgress | null;
  unmatchedZoneIds: string[];
  detail: string | null;
  /** 최신 리포트가 속한 임무 — 히트맵(임무 스코프 표면)으로 건너뛸 때만 쓰는 UI 편의값. */
  latestMissionId: string | null;
}

export interface ProgressBaselineResponse {
  verdict: string;
  detail: string | null;
}

/** 어느 설계면과 비교했는가 — 요청 시점 VERIFIED 스냅샷. */
export interface DesignSurfaceRef {
  designSurfaceId: string;
  sha256: string;
}

/**
 * 체적 집계에 실제로 쓴 높이차 격자 — 지도가 읽는 **단 하나의** 데이터 출처.
 *
 * 값 규약은 `설계 표고 − 현재 표고`: 양수 = 쌓아야 함, 음수 = 깎아야 함.
 */
export interface DiffRasterRef {
  diffRasterId: string;
  digest: string;
  format: "geotiff";
  crs: string;
  verticalReference: VerticalReference;
  width: number;
  height: number;
  pixelSizeXM: number;
  pixelSizeYM: number;
  transform: [number, number, number, number, number, number];
  /** 무효 셀(측정 불가)의 표현 — **0 이 아니라 NaN 이다**. */
  nodataEncoding: "nan";
  /** 이 값 미만의 |높이차| 는 체적 집계에서 제외됐다(범례가 이 값을 쓴다). */
  thresholdM: number;
  sizeBytes: number;
  coreVerifiedDigestAt: string;
}

/** contracts/schemas/design-conformance-report.v1.json. */
export interface DesignConformanceReport {
  schemaVersion: string;
  designConformanceId: string;
  designSurfaceRef: DesignSurfaceRef;
  current: ArtifactRefView;
  crs: string;
  verticalReference: VerticalReference;
  /** 구역별 잔량 — `cut` = 깎아야 할 양, `fill` = 쌓아야 할 양, `net = fill - cut`. */
  zones: ZoneVolumeDelta[];
  policy: ComparisonPolicyView;
  diffRaster: DiffRasterRef;
  computedAt: string;
}

export interface DesignConformanceEntry {
  report: DesignConformanceReport;
  reportedBy: string | null;
  recordedAt: string;
  /** Core 가 기록 시점에 직접 재계산한 digest — "확인된 사실"임을 말할 근거. */
  coreRecomputedDigest: string;
}

export interface DesignConformanceListView {
  missionId: string;
  reportCount: number;
  /** 최신 리포트의 전 구역 순 성토 필요량 — 서버가 계산해 준다. */
  latestTotalNetM3: number | null;
  reports: DesignConformanceEntry[];
}

/** 지도가 차분 래스터를 얻는 **유일한** 경로의 응답. */
export interface DiffRasterViewResponse {
  designConformanceId: string;
  diffRasterId: string;
  digest: string;
  sizeBytes: number;
  downloadUrl: string;
  expiresAt: string;
}
