import "server-only";

import { coreFetch, coreFetchWithToken } from "./client";
import type { ExternalSubmissionCandidate } from "../external-reconstruction-submission";
import type { ExternalSubmissionCandidateV3 } from "../external-reconstruction-submission";

export type ExternalRevisionView = {
  submissionRef: string;
  submission: ExternalSubmissionCandidate;
  state: "REGISTERED" | "SEALED";
  manifest: unknown | null;
};

export type ExternalUploadGrant = {
  artifactId: "ortho" | "dsm";
  objectKey: string;
  uploadUrl: string;
  requiredHeaders: Record<string, string>;
};

export type ExternalInspectionState =
  | "INSPECTION_PENDING_SEAL"
  | "INSPECTION_PENDING_POLICY"
  | "INSPECTION_PENDING"
  | "INSPECTION_QUEUED"
  | "INSPECTION_RUNNING"
  | "INSPECTION_REPORTED"
  | "INSPECTION_FAILED_INCOMPLETE";

export type ExternalDisplayState =
  | "PENDING_INSPECTION"
  | "PENDING_POLICY"
  | "NOT_REQUIRED"
  | "QUEUED"
  | "RUNNING"
  | "SEALED"
  | "RETRY_EXHAUSTED";

/** Core-owned inspection facts. The browser never derives a measurement status from them. */
export type ExternalArtifactInspectionView = {
  registrationState: "REGISTERED" | "SEALED";
  sealState: "UNSEALED" | "SEALED";
  inspection: {
    state: ExternalInspectionState;
    phase: "INSPECTION" | "DISPLAY" | "COMPLETE" | "FAILED_INCOMPLETE" | null;
    outcome: Array<{ artifactId: string; outcome: string; reason: string | null }> | null;
    request: unknown | null;
    report: unknown | null;
  };
  display: {
    state: ExternalDisplayState;
    sanitizedDisplayRef: string | null;
    receiptDigest: string | null;
  };
};

/** One short-lived, Core-scoped capability for a sanitized derived display artifact only. */
export type ExternalSanitizedDisplayDownload = {
  sanitizedDisplayRef: string;
  receiptDigest: string;
  observedDerivativeSha256: string;
  observedDerivativeSizeBytes: number;
  observedDerivativeContentType: string;
  downloadUrl: string;
  expiresAt: string;
  requiredHeaders: Record<string, string>;
};

const base = (workOrderId: string) =>
  `/v1/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-submissions`;

export async function listExternalReconstructionSubmissions(workOrderId: string): Promise<ExternalRevisionView[]> {
  return (await coreFetch<{ submissions: ExternalRevisionView[] }>(base(workOrderId))).submissions;
}

export function registerExternalReconstructionSubmission(
  workOrderId: string,
  submission: ExternalSubmissionCandidate,
): Promise<ExternalRevisionView> {
  return coreFetch(base(workOrderId), { method: "POST", body: submission });
}

/**
 * V3 missing-info intake (additive). Upload grants, seal, inspection, revision
 * reads, and the revision list stay on the version-agnostic routes keyed by
 * the server-issued opaque submissionRef — only registration is versioned.
 * Auth rides the existing user session via coreFetch; no admin fallback.
 */
export function registerExternalReconstructionSubmissionV3(
  workOrderId: string,
  submission: ExternalSubmissionCandidateV3,
): Promise<ExternalRevisionView> {
  return coreFetch(`${base(workOrderId)}-v3`, { method: "POST", body: submission });
}

/**
 * 같은 토큰으로 whoami와 V3 선언을 잇는 연속성 검사 경로 전용 — 토큰을 두 번
 * 읽으면 검사와 변이 사이 세션 교체(TOCTOU)가 생긴다. 기존 호출부는 그대로 둔다.
 */
export function registerExternalReconstructionSubmissionV3WithToken(
  workOrderId: string,
  submission: ExternalSubmissionCandidateV3,
  token: string,
): Promise<ExternalRevisionView> {
  return coreFetchWithToken(`${base(workOrderId)}-v3`, token, { method: "POST", body: submission });
}

/**
 * 같은 토큰으로 whoami와 등록 맥락 읽기를 잇는 연속성 검사 경로 전용. 기존
 * 호출부는 그대로 둔다.
 */
export function getExternalReconstructionContextWithToken(
  workOrderId: string,
  token: string,
): Promise<ExternalReconstructionContext> {
  return coreFetchWithToken<ExternalReconstructionContext>(
    `/v1/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-context`,
    token,
  );
}

/**
 * 같은 토큰으로 whoami와 등록 목록 읽기를 잇는 연속성 검사 경로 전용. 기존
 * 호출부는 그대로 둔다.
 */
export async function listExternalReconstructionSubmissionsWithToken(
  workOrderId: string,
  token: string,
): Promise<ExternalRevisionView[]> {
  return (await coreFetchWithToken<{ submissions: ExternalRevisionView[] }>(base(workOrderId), token)).submissions;
}

export async function requestExternalReconstructionUploadGrants(
  workOrderId: string,
  submissionRef: string,
  revision: number,
): Promise<ExternalUploadGrant[]> {
  const path = `${base(workOrderId)}/${encodeURIComponent(submissionRef)}/revisions/${revision}/upload-grants`;
  return (await coreFetch<{ grants: ExternalUploadGrant[] }>(path, { method: "POST" })).grants;
}

/**
 * 같은 토큰으로 whoami와 업로드 승인을 잇는 연속성 검사 경로 전용 — 토큰을 두
 * 번 읽으면 검사와 승인 사이 세션 교체(TOCTOU)가 생긴다. 기존 호출부는 그대로 둔다.
 */
export async function requestExternalReconstructionUploadGrantsWithToken(
  workOrderId: string,
  submissionRef: string,
  revision: number,
  token: string,
): Promise<ExternalUploadGrant[]> {
  const path = `${base(workOrderId)}/${encodeURIComponent(submissionRef)}/revisions/${revision}/upload-grants`;
  return (await coreFetchWithToken<{ grants: ExternalUploadGrant[] }>(path, token, { method: "POST" })).grants;
}

export function sealExternalReconstructionSubmission(
  workOrderId: string,
  submissionRef: string,
  revision: number,
): Promise<ExternalRevisionView> {
  return coreFetch(`${base(workOrderId)}/${encodeURIComponent(submissionRef)}/revisions/${revision}/seal`, { method: "POST" });
}

/**
 * 같은 토큰으로 whoami와 봉인을 잇는 연속성 검사 경로 전용. 기존 호출부는 그대로 둔다.
 */
export function sealExternalReconstructionSubmissionWithToken(
  workOrderId: string,
  submissionRef: string,
  revision: number,
  token: string,
): Promise<ExternalRevisionView> {
  return coreFetchWithToken(`${base(workOrderId)}/${encodeURIComponent(submissionRef)}/revisions/${revision}/seal`, token, { method: "POST" });
}

export type ExternalRevisionDetailView = {
  submissionRef: string;
  /** Versioned wire dict (v1 or v3) — 반드시 호출부가 계약 버전을 확인하고 쓴다. */
  submission: unknown;
  state: "REGISTERED" | "SEALED";
  manifest: unknown | null;
};

function assertRevisionPath(workOrderId: string, submissionRef: string, revision: number): void {
  if (typeof workOrderId !== "string" || workOrderId.length < 1 || workOrderId.length > 255) {
    throw new TypeError("workOrderId가 올바르지 않습니다");
  }
  if (!/^ers-v1-[0-9a-f]{64}$/.test(submissionRef)) {
    throw new TypeError("submissionRef가 올바르지 않습니다");
  }
  if (!Number.isSafeInteger(revision) || revision < 1) {
    throw new TypeError("revision이 올바르지 않습니다");
  }
}

/**
 * 선택한 자산 하나에 묶인 제출서 revision 1건을 읽는다 — 목록 N+1 조회가 아니다.
 * Core의 기존 버전별 revision GET을 그대로 쓰며, 권한은 호출자의 운영자
 * 세션으로 확인한다(관리자 대체 경로 없음). 반환된 submission의 계약 버전과
 * 귀속은 호출부가 검증해야 한다.
 */
export function getExternalReconstructionSubmission(
  workOrderId: string,
  submissionRef: string,
  revision: number,
): Promise<ExternalRevisionDetailView> {
  assertRevisionPath(workOrderId, submissionRef, revision);
  return coreFetch<ExternalRevisionDetailView>(
    `${base(workOrderId)}/${encodeURIComponent(submissionRef)}/revisions/${revision}`,
  );
}

export function getExternalArtifactInspection(
  workOrderId: string,
  submissionRef: string,
  revision: number,
): Promise<ExternalArtifactInspectionView> {
  return coreFetch(`${base(workOrderId)}/${encodeURIComponent(submissionRef)}/revisions/${revision}/inspection`);
}

export function getExternalSanitizedDisplayDownload(
  workOrderId: string,
  submissionRef: string,
  revision: number,
  sanitizedDisplayRef: string,
): Promise<ExternalSanitizedDisplayDownload> {
  return coreFetch(`${base(workOrderId)}/${encodeURIComponent(submissionRef)}/revisions/${revision}/display-artifacts/${encodeURIComponent(sanitizedDisplayRef)}/download`);
}

export type ExternalReconstructionContext = {
  workOrderId: string;
  siteId: string;
  expectedEpochId: string;
  cycleNumber: number;
  workOrderVersion: number;
  executionMode: "MANAGED_ACQUISITION" | "EXTERNAL_RECONSTRUCTION" | null;
  externalPlanningBinding: ExternalPlanningOnlyWorkOrderBinding | null;
};

export type ExternalPlanningOnlyWorkOrderBinding = {
  contractVersion: "external-planning-only-work-order-binding.v1";
  mode: "EXTERNAL_REOBSERVATION_PLANNING";
  organizationId: string;
  siteId: string;
  sourceWorkOrderId: string;
  successorWorkOrderId: string;
  approvalId: string;
  approvedBy: string;
  approvedAt: string;
  proposalId: string;
  proposalVersion: number;
  proposalDigest: string;
  reportDigest: string;
  decisionDigest: string;
  zoneDigest: string;
  evidenceDigests: string[];
  targetWorkAreas: Array<{ workAreaId: string; revision: 1; snapshotDigest: string | null }>;
  temporalPolicy: { schemaVersion: "1.0"; maxCaptureSpanSeconds: number } | null;
  acquisitionRunAllowed: false;
  missionIssuanceAllowed: false;
  bindingDigest: string | null;
};

export type ExternalWorkOrderExecutionContext =
  | "MANAGED"
  | "EXTERNAL_INGRESS"
  | "EXTERNAL_REOBSERVATION_PLANNING"
  | "UNVERIFIED";

export function resolveExternalWorkOrderExecutionContext(
  workOrder: {
    workOrderId: string;
    organizationId: string;
    siteId: string;
    cycleNumber: number;
    version: number;
    executionMode: "MANAGED_ACQUISITION" | "EXTERNAL_RECONSTRUCTION" | null;
  },
  context: ExternalReconstructionContext | null,
): ExternalWorkOrderExecutionContext {
  if (
    !context ||
    context.workOrderId !== workOrder.workOrderId ||
    context.siteId !== workOrder.siteId ||
    context.cycleNumber !== workOrder.cycleNumber ||
    context.workOrderVersion !== workOrder.version ||
    context.executionMode !== workOrder.executionMode
  ) {
    return "UNVERIFIED";
  }
  if (context.externalPlanningBinding === null) {
    return context.executionMode === "EXTERNAL_RECONSTRUCTION" ? "EXTERNAL_INGRESS" : "MANAGED";
  }
  const binding = context.externalPlanningBinding;
  return binding.contractVersion === "external-planning-only-work-order-binding.v1" &&
    binding.mode === "EXTERNAL_REOBSERVATION_PLANNING" &&
    binding.organizationId === workOrder.organizationId &&
    binding.siteId === workOrder.siteId &&
    binding.successorWorkOrderId === workOrder.workOrderId &&
    binding.acquisitionRunAllowed === false &&
    binding.missionIssuanceAllowed === false
    && (context.executionMode === "EXTERNAL_RECONSTRUCTION" || context.executionMode === null)
    ? "EXTERNAL_REOBSERVATION_PLANNING"
    : "UNVERIFIED";
}

export type ExternalEvidenceView = {
  evidenceRef: string;
  state: "DECLARED" | "SEALED_BYTE_OBSERVED";
  targetDsmArtifactId: string;
  targetDsmObservedSha256: string;
  declaredContentDigest: string;
  declaredContentType: string;
  independenceBasis: string;
  declaredAt: string;
  observedObjectDigest?: string;
  observedSizeBytes?: number;
  observedContentType?: string;
  observedAt?: string;
  measurementSummaries?: Array<{ coreVerdict: "VALIDATED" | "REJECTED"; measuredCheckpointCount: number; meanErrorM: number; maeM: number; rmseM: number; recordedAt: string }>;
};

export type ExternalEvidenceGrant = { evidenceRef: string; uploadUrl: string; expiresAt: string; requiredHeaders: Record<string, string> };
export type ExternalUseDecision = { decisionId: string; use: string; verdict: "ELIGIBLE" | "RESTRICTED" | "BLOCKED"; reasons: string[]; remediations: string[]; decidedAt: string; decisionDigest: string };

function evidenceBase(workOrderId: string, submissionRef: string, revision: number): string {
  return `${base(workOrderId)}/${encodeURIComponent(submissionRef)}/revisions/${revision}/evidence`;
}
function decisionBase(workOrderId: string, submissionRef: string, revision: number): string {
  return `${base(workOrderId)}/${encodeURIComponent(submissionRef)}/revisions/${revision}/use-decisions`;
}
export async function listExternalEvidence(workOrderId: string, submissionRef: string, revision: number): Promise<ExternalEvidenceView[]> {
  return (await coreFetch<{ items: ExternalEvidenceView[] }>(evidenceBase(workOrderId, submissionRef, revision))).items;
}
export function declareExternalEvidence(workOrderId: string, submissionRef: string, revision: number, intent: { targetDsmArtifactId: string; declaredContentDigest: string; declaredContentType: string; independenceBasis: string }, idempotencyKey: string): Promise<ExternalEvidenceView> {
  return coreFetch(evidenceBase(workOrderId, submissionRef, revision), { method: "POST", body: intent, headers: { "Idempotency-Key": idempotencyKey } });
}
/**
 * 같은 토큰으로 whoami와 선언을 잇는 연속성 검사 경로 전용 — 토큰을 두 번
 * 읽으면 검사와 변이 사이 세션 교체(TOCTOU)가 생긴다. 기존 호출부는 그대로 둔다.
 */
export function declareExternalEvidenceWithToken(workOrderId: string, submissionRef: string, revision: number, intent: { targetDsmArtifactId: string; declaredContentDigest: string; declaredContentType: string; independenceBasis: string }, idempotencyKey: string, token: string): Promise<ExternalEvidenceView> {
  return coreFetchWithToken(evidenceBase(workOrderId, submissionRef, revision), token, { method: "POST", body: intent, headers: { "Idempotency-Key": idempotencyKey } });
}
export function grantExternalEvidenceUpload(workOrderId: string, submissionRef: string, revision: number, evidenceRef: string, idempotencyKey: string): Promise<ExternalEvidenceGrant> {
  return coreFetch(`${evidenceBase(workOrderId, submissionRef, revision)}/${encodeURIComponent(evidenceRef)}/upload-grant`, { method: "POST", headers: { "Idempotency-Key": idempotencyKey } });
}
/** 같은 토큰으로 whoami와 업로드 승인을 잇는 연속성 검사 경로 전용. 기존 호출부는 그대로 둔다. */
export function grantExternalEvidenceUploadWithToken(workOrderId: string, submissionRef: string, revision: number, evidenceRef: string, idempotencyKey: string, token: string): Promise<ExternalEvidenceGrant> {
  return coreFetchWithToken(`${evidenceBase(workOrderId, submissionRef, revision)}/${encodeURIComponent(evidenceRef)}/upload-grant`, token, { method: "POST", headers: { "Idempotency-Key": idempotencyKey } });
}
export function sealExternalEvidence(workOrderId: string, submissionRef: string, revision: number, evidenceRef: string, idempotencyKey: string): Promise<ExternalEvidenceView> {
  return coreFetch(`${evidenceBase(workOrderId, submissionRef, revision)}/${encodeURIComponent(evidenceRef)}/seal`, { method: "POST", headers: { "Idempotency-Key": idempotencyKey } });
}
/** 같은 토큰으로 whoami와 봉인을 잇는 연속성 검사 경로 전용. 기존 호출부는 그대로 둔다. */
export function sealExternalEvidenceWithToken(workOrderId: string, submissionRef: string, revision: number, evidenceRef: string, idempotencyKey: string, token: string): Promise<ExternalEvidenceView> {
  return coreFetchWithToken(`${evidenceBase(workOrderId, submissionRef, revision)}/${encodeURIComponent(evidenceRef)}/seal`, token, { method: "POST", headers: { "Idempotency-Key": idempotencyKey } });
}
export function requestExternalSingleUseDecision(workOrderId: string, submissionRef: string, revision: number, use: "DISPLAY" | "HEIGHT", idempotencyKey: string): Promise<{ decision: ExternalUseDecision }> {
  return coreFetch(`${decisionBase(workOrderId, submissionRef, revision)}/single`, { method: "POST", body: { use }, headers: { "Idempotency-Key": idempotencyKey } });
}
/**
 * 같은 토큰으로 whoami와 결정을 잇는 연속성 검사 경로 전용 — 토큰을 두 번
 * 읽으면 검사와 변이 사이 세션 교체(TOCTOU)가 생긴다. 기존 호출부는 그대로 둔다.
 */
export function requestExternalSingleUseDecisionWithToken(workOrderId: string, submissionRef: string, revision: number, use: "DISPLAY" | "HEIGHT", idempotencyKey: string, token: string): Promise<{ decision: ExternalUseDecision }> {
  return coreFetchWithToken(`${decisionBase(workOrderId, submissionRef, revision)}/single`, token, { method: "POST", body: { use }, headers: { "Idempotency-Key": idempotencyKey } });
}
export function requestExternalSingleVolumeDecision(workOrderId: string, submissionRef: string, revision: number, zoneId: string, idempotencyKey: string): Promise<{ decision: ExternalUseDecision }> {
  return coreFetch(`${decisionBase(workOrderId, submissionRef, revision)}/single-volume`, { method: "POST", body: { zoneId }, headers: { "Idempotency-Key": idempotencyKey } });
}
/** 같은 토큰으로 whoami와 결정을 잇는 연속성 검사 경로 전용. 기존 호출부는 그대로 둔다. */
export function requestExternalSingleVolumeDecisionWithToken(workOrderId: string, submissionRef: string, revision: number, zoneId: string, idempotencyKey: string, token: string): Promise<{ decision: ExternalUseDecision }> {
  return coreFetchWithToken(`${decisionBase(workOrderId, submissionRef, revision)}/single-volume`, token, { method: "POST", body: { zoneId }, headers: { "Idempotency-Key": idempotencyKey } });
}
export function requestExternalPairUseDecision(workOrderId: string, submissionRef: string, revision: number, intent: { use: "VISUAL_COMPARISON" | "RELATIVE_VOLUME"; baselineWorkOrderId: string; baselineSubmissionRef: string; baselineRevision: number; zoneId?: string | null }, idempotencyKey: string): Promise<{ decision: ExternalUseDecision }> {
  return coreFetch(`${decisionBase(workOrderId, submissionRef, revision)}/pair`, { method: "POST", body: intent, headers: { "Idempotency-Key": idempotencyKey } });
}
/** 같은 토큰으로 whoami와 결정을 잇는 연속성 검사 경로 전용. 기존 호출부는 그대로 둔다. */
export function requestExternalPairUseDecisionWithToken(workOrderId: string, submissionRef: string, revision: number, intent: { use: "VISUAL_COMPARISON" | "RELATIVE_VOLUME"; baselineWorkOrderId: string; baselineSubmissionRef: string; baselineRevision: number; zoneId?: string | null }, idempotencyKey: string, token: string): Promise<{ decision: ExternalUseDecision }> {
  return coreFetchWithToken(`${decisionBase(workOrderId, submissionRef, revision)}/pair`, token, { method: "POST", body: intent, headers: { "Idempotency-Key": idempotencyKey } });
}
export function getExternalUseDecision(workOrderId: string, submissionRef: string, revision: number, decisionId: string): Promise<{ decision: ExternalUseDecision }> {
  return coreFetch(`${decisionBase(workOrderId, submissionRef, revision)}/${encodeURIComponent(decisionId)}`);
}

export function getExternalReconstructionContext(workOrderId: string): Promise<ExternalReconstructionContext> {
  return coreFetch(`/v1/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-context`);
}
