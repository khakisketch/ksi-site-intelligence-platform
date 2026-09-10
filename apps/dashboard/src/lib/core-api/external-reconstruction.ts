import "server-only";

import { coreFetch } from "./client";
import type { ExternalSubmissionCandidate } from "../external-reconstruction-submission";

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

export async function requestExternalReconstructionUploadGrants(
  workOrderId: string,
  submissionRef: string,
  revision: number,
): Promise<ExternalUploadGrant[]> {
  const path = `${base(workOrderId)}/${encodeURIComponent(submissionRef)}/revisions/${revision}/upload-grants`;
  return (await coreFetch<{ grants: ExternalUploadGrant[] }>(path, { method: "POST" })).grants;
}

export function sealExternalReconstructionSubmission(
  workOrderId: string,
  submissionRef: string,
  revision: number,
): Promise<ExternalRevisionView> {
  return coreFetch(`${base(workOrderId)}/${encodeURIComponent(submissionRef)}/revisions/${revision}/seal`, { method: "POST" });
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
export function grantExternalEvidenceUpload(workOrderId: string, submissionRef: string, revision: number, evidenceRef: string, idempotencyKey: string): Promise<ExternalEvidenceGrant> {
  return coreFetch(`${evidenceBase(workOrderId, submissionRef, revision)}/${encodeURIComponent(evidenceRef)}/upload-grant`, { method: "POST", headers: { "Idempotency-Key": idempotencyKey } });
}
export function sealExternalEvidence(workOrderId: string, submissionRef: string, revision: number, evidenceRef: string, idempotencyKey: string): Promise<ExternalEvidenceView> {
  return coreFetch(`${evidenceBase(workOrderId, submissionRef, revision)}/${encodeURIComponent(evidenceRef)}/seal`, { method: "POST", headers: { "Idempotency-Key": idempotencyKey } });
}
export function requestExternalSingleUseDecision(workOrderId: string, submissionRef: string, revision: number, use: "DISPLAY" | "HEIGHT", idempotencyKey: string): Promise<{ decision: ExternalUseDecision }> {
  return coreFetch(`${decisionBase(workOrderId, submissionRef, revision)}/single`, { method: "POST", body: { use }, headers: { "Idempotency-Key": idempotencyKey } });
}
export function requestExternalPairUseDecision(workOrderId: string, submissionRef: string, revision: number, intent: { use: "VISUAL_COMPARISON" | "RELATIVE_VOLUME"; baselineWorkOrderId: string; baselineSubmissionRef: string; baselineRevision: number; zoneId?: string | null }, idempotencyKey: string): Promise<{ decision: ExternalUseDecision }> {
  return coreFetch(`${decisionBase(workOrderId, submissionRef, revision)}/pair`, { method: "POST", body: intent, headers: { "Idempotency-Key": idempotencyKey } });
}
export function getExternalUseDecision(workOrderId: string, submissionRef: string, revision: number, decisionId: string): Promise<{ decision: ExternalUseDecision }> {
  return coreFetch(`${decisionBase(workOrderId, submissionRef, revision)}/${encodeURIComponent(decisionId)}`);
}

export function getExternalReconstructionContext(workOrderId: string): Promise<ExternalReconstructionContext> {
  return coreFetch(`/v1/observation-work-orders/${encodeURIComponent(workOrderId)}/external-reconstruction-context`);
}
