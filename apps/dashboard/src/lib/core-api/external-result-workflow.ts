import "server-only";

import { coreFetch } from "./client";
import type { ExternalResultProjectionView, ExternalResultSummaryView } from "./types";

export type ExternalRelativeVolumeStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";

export type ExternalRelativeVolumeRequestView = {
  requestRef: string;
  status: ExternalRelativeVolumeStatus;
  currentWorkOrderId: string;
  decisionDigest: string;
  issuedAt: string;
  deadlineAt: string;
  reportRef: string | null;
  reportDigest: string | null;
};

export type ExternalRelativeVolumeMutation = {
  verdict: string;
  request: ExternalRelativeVolumeRequestView | null;
  detail: string | null;
};

export type ExternalVolumeSubject = {
  organizationId: string;
  siteId: string;
  workOrderId: string;
  submissionId: string;
  revision: number;
  submissionDigest: string;
  manifestDigest: string;
};

export type ExternalVolumeInputBinding = {
  subject: ExternalVolumeSubject;
  inspectionReportDigest: string;
  dsmArtifactId: string;
  observedSha256: string;
  observedSizeBytes: number;
  observedCrsDigest: string;
  observedVerticalReferenceDigest: string;
  capturedFrom: string;
  capturedTo: string;
};

export type ExternalVolumeZoneSnapshot = {
  contractVersion: "external-volume-zone-snapshot.v1";
  organizationId: string;
  siteId: string;
  workAreaId: string;
  revision: 1;
  polygon: Record<string, unknown>;
  crs: string;
  observedCrsDigest: string;
  analysisVerticalReferenceDigest: string;
  definitionDigest: string | null;
};

export type ExternalRelativeVolumeRequest = {
  contractVersion: "external-relative-volume-request.v1";
  requestId: string;
  currentWorkOrderId: string;
  decisionId: string;
  decisionDigest: string;
  baseline: ExternalVolumeInputBinding;
  current: ExternalVolumeInputBinding;
  evidenceRecordDigests: string[];
  validationPolicyDigest: string;
  executionPolicyDigest: string;
  zoneSnapshot: ExternalVolumeZoneSnapshot;
  issuedAt: string;
  idempotencyKey: string;
  requestDigest: string | null;
};

export type ExternalRelativeVolumeMetrics = {
  zoneCellCount: number;
  commonValidCellCount: number;
  zoneAreaM2: number;
  measuredAreaM2: number;
  commonValidFraction: number;
  cutM3: number;
  fillM3: number;
  netM3: number;
  thresholdM: number;
  uncertaintyM3: number | null;
  uncertaintyNote: string;
};

export type ExternalRelativeVolumeReport = {
  contractVersion: "external-relative-volume-report.v1";
  reportId: string;
  requestId: string;
  requestDigest: string;
  payload: {
    factClass: "OBSERVED";
    requestDigest: string;
    decisionDigest: string;
    baselineDsmDigest: string;
    currentDsmDigest: string;
    zoneSnapshotDigest: string;
    executionPolicyDigest: string;
    algorithmBuildDigest: string;
    configDigest: string;
    metrics: ExternalRelativeVolumeMetrics;
  };
  measurementPayloadDigest: string | null;
  workerInstanceId: string;
  leaseAcquisitionId: string;
  leaseGeneration: number;
  computedAt: string;
  reportedAt: string;
  reportDigest: string | null;
};

export type ExternalRelativeVolumeExecutionPolicy = {
  contractVersion: "external-relative-volume-execution-policy.v1";
  policyId: string;
  version: number;
  algorithmBuildDigest: string;
  configDigest: string;
  thresholdM: number;
  minimumCommonValidFraction: number;
  uncertaintyMethod: "INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1";
  resourceEnvelopeDigest: string;
  authorityRecordDigest: string;
  syntheticTestOnly: boolean;
  policyDigest: string | null;
};

export type ExternalRelativeVolumeReviewAuthority = {
  contractVersion: "external-result-review-authority.v1";
  organizationId: string;
  siteId: string;
  currentWorkOrderId: string;
  decisionId: string;
  decisionDigest: string;
  compatibilityMappingDigest: string;
  baseline: ExternalVolumeInputBinding;
  current: ExternalVolumeInputBinding;
  evidenceRecordDigests: string[];
  validationPolicyDigest: string;
  zoneSnapshot: ExternalVolumeZoneSnapshot;
  executionPolicy: ExternalRelativeVolumeExecutionPolicy;
  authorizedActorIds: string[];
  validFrom: string;
  validUntil: string;
  historicalAuthorityDigest: string;
  baselineRmseM: number | null;
  currentRmseM: number | null;
  maximumZoneCellCount: number;
  maximumZoneAreaM2: number;
  syntheticTestOnly: boolean;
  authorityDigest: string | null;
};

export type ExternalRelativeVolumePairDecision = {
  contractVersion: "external-pair-use-decision.v1";
  decisionId: string;
  baselineSubject: ExternalVolumeSubject;
  baselineSubjectDigest: string;
  currentSubject: ExternalVolumeSubject;
  currentSubjectDigest: string;
  use: "VISUAL_COMPARISON" | "RELATIVE_VOLUME";
  policyDigest: string | null;
  baselineInspectionReportDigest: string | null;
  currentInspectionReportDigest: string | null;
  baselineSanitizedDisplayReceiptDigest: string | null;
  currentSanitizedDisplayReceiptDigest: string | null;
  evidenceRecordDigests: string[];
  zone: {
    zoneId: string;
    revision: number;
    definitionDigest: string;
    observedCrsDigest: string;
    observedVerticalReferenceDigest: string;
  } | null;
  compatibilityMappingDigest: string | null;
  verdict: "ELIGIBLE" | "RESTRICTED" | "BLOCKED";
  reasons: string[];
  remediations: string[];
  decidedAt: string;
  decisionDigest: string | null;
};

/** Lossless Console projection of Core's ExternalResultReviewReceiptV1. */
export type ExternalResultReview = {
  contractVersion: "external-result-review-receipt.v1";
  reviewRef: string;
  organizationId: string;
  siteId: string;
  sourceWorkOrderId: string;
  reportRef: string;
  request: ExternalRelativeVolumeRequest;
  report: ExternalRelativeVolumeReport;
  authority: ExternalRelativeVolumeReviewAuthority;
  decision: ExternalRelativeVolumePairDecision;
  reviewDigest: string | null;
  reviewedAt: string;
  factualLimitations: string[];
};

export type ExternalReobservationProposal = {
  proposalRef: string;
  version: number;
  reviewRef: string;
  reviewDigest: string;
  reportRef: string;
  reportDigest: string;
  decisionDigest: string;
  zoneDigest: string;
  evidenceDigests: string[];
  targetWorkAreas: Array<{ workAreaId: string; revision: 1; snapshotDigest: string | null }>;
  reason: string | null;
  proposalDigest: string | null;
  createdAt: string;
};

export type ExternalReobservationApprovalReceipt = {
  successorWorkOrderId: string;
  receiptDigest: string | null;
  approvedAt: string;
};

export type ExternalReobservationProposalView = {
  proposal: ExternalReobservationProposal;
  approvalReceipt: ExternalReobservationApprovalReceipt | null;
};

export type ExternalRelativeVolumeReportView = {
  request: ExternalRelativeVolumeRequest;
  report: ExternalRelativeVolumeReport;
  executionPolicy: ExternalRelativeVolumeExecutionPolicy;
  review: ExternalResultReview | null;
  proposals: ExternalReobservationProposalView[];
};

const requestBase = (workOrderId: string) =>
  `/v1/observation-work-orders/${encodeURIComponent(workOrderId)}/relative-volume-requests`;

export function issueExternalRelativeVolume(
  workOrderId: string,
  decisionRef: string,
  idempotencyKey: string,
): Promise<ExternalRelativeVolumeMutation> {
  return coreFetch(requestBase(workOrderId), {
    method: "POST",
    body: { decisionRef },
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

export async function listExternalRelativeVolumeRequests(
  workOrderId: string,
): Promise<ExternalRelativeVolumeRequestView[]> {
  return (await coreFetch<{ items: ExternalRelativeVolumeRequestView[] }>(requestBase(workOrderId))).items;
}

export function getExternalRelativeVolumeRequest(
  workOrderId: string,
  requestRef: string,
): Promise<ExternalRelativeVolumeRequestView> {
  return coreFetch(`${requestBase(workOrderId)}/${encodeURIComponent(requestRef)}`);
}

export function getExternalRelativeVolumeReport(
  reportRef: string,
): Promise<ExternalRelativeVolumeReportView> {
  return coreFetch(`/v1/external-relative-volume-reports/${encodeURIComponent(reportRef)}`);
}

export function reviewExternalRelativeVolumeReport(
  reportRef: string,
): Promise<{ review: ExternalResultReview }> {
  return coreFetch(`/v1/external-relative-volume-reports/${encodeURIComponent(reportRef)}/reviews`, {
    method: "POST",
  });
}

export function getExternalResultReview(reviewRef: string): Promise<{ review: ExternalResultReview }> {
  return coreFetch(`/v1/external-result-reviews/${encodeURIComponent(reviewRef)}`);
}

export function createExternalReobservationProposal(
  intent: { reportRef: string; targetWorkAreaIds: [string]; reason: string | null },
  idempotencyKey: string,
): Promise<ExternalReobservationProposalView> {
  return coreFetch("/v1/external-reobservation-proposals", {
    method: "POST",
    body: intent,
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

export function getExternalReobservationProposal(
  proposalRef: string,
): Promise<ExternalReobservationProposalView> {
  return coreFetch(`/v1/external-reobservation-proposals/${encodeURIComponent(proposalRef)}`);
}

export function approveExternalReobservationProposal(
  proposalRef: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<ExternalReobservationProposalView> {
  return coreFetch("/v1/external-reobservation-proposals/approve", {
    method: "POST",
    body: { proposalRef, expectedVersion },
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

export type ExternalRelativeVolumeHistoryItem = {
  reportRef: string;
  state: "AVAILABLE" | "HISTORICAL_SOURCE_UNAVAILABLE";
  result: ExternalResultSummaryView | null;
};

export type ExternalRelativeVolumeHistory = {
  items: ExternalRelativeVolumeHistoryItem[];
  nextCursor: string | null;
};

export function listSiteExternalRelativeVolumeHistory(
  siteId: string,
  options: { after?: string; limit?: number } = {},
): Promise<ExternalRelativeVolumeHistory> {
  return coreFetch<ExternalRelativeVolumeHistory>(
    `/v1/sites/${encodeURIComponent(siteId)}/external-relative-volume-reports`,
    { query: { after: options.after, limit: options.limit } },
  );
}

export function getSiteExternalRelativeVolumeReport(
  siteId: string,
  reportRef: string,
): Promise<ExternalResultProjectionView> {
  return coreFetch<ExternalResultProjectionView>(
    `/v1/sites/${encodeURIComponent(siteId)}/observations/${encodeURIComponent(reportRef)}`,
  );
}

// ── SINGLE_VOLUME (single-epoch boundary-base comparison) ──────────────────

const singleRequestBase = (workOrderId: string) =>
  `/v1/observation-work-orders/${encodeURIComponent(workOrderId)}/single-volume-requests`;

export function issueExternalSingleVolume(
  workOrderId: string,
  decisionRef: string,
  idempotencyKey: string,
): Promise<ExternalRelativeVolumeMutation> {
  return coreFetch(singleRequestBase(workOrderId), {
    method: "POST",
    body: { decisionRef },
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

export async function listExternalSingleVolumeRequests(
  workOrderId: string,
): Promise<ExternalRelativeVolumeRequestView[]> {
  return (await coreFetch<{ items: ExternalRelativeVolumeRequestView[] }>(singleRequestBase(workOrderId))).items;
}

export function getExternalSingleVolumeRequest(
  workOrderId: string,
  requestRef: string,
): Promise<ExternalRelativeVolumeRequestView> {
  return coreFetch(`${singleRequestBase(workOrderId)}/${encodeURIComponent(requestRef)}`);
}

export type ExternalSingleVolumeMetrics = {
  zoneCellCount: number;
  commonValidCellCount: number;
  zoneAreaM2: number;
  measuredAreaM2: number;
  commonValidFraction: number;
  cutM3: number;
  fillM3: number;
  netM3: number;
  thresholdM: number;
  uncertaintyM3: number | null;
  uncertaintyNote: string;
  baseRoughnessM: number;
  boundaryCellCount: number;
  boundarySampleCount: number;
  boundaryValidFraction: number;
};

export type ExternalSingleVolumeMeasurementPayload = {
  factClass: "OBSERVED";
  requestDigest: string;
  decisionDigest: string;
  targetDsmDigest: string;
  zoneSnapshotDigest: string;
  executionPolicyDigest: string;
  algorithmBuildDigest: string;
  configDigest: string;
  metrics: ExternalSingleVolumeMetrics;
};

export type ExternalSingleVolumeRequest = {
  contractVersion: "external-single-volume-request.v1";
  requestId: string;
  currentWorkOrderId: string;
  decisionId: string;
  decisionDigest: string;
  target: ExternalVolumeInputBinding;
  evidenceRecordDigests: string[];
  validationPolicyDigest: string;
  executionPolicyDigest: string;
  zoneSnapshot: ExternalVolumeZoneSnapshot;
  issuedAt: string;
  idempotencyKey: string;
  requestDigest: string | null;
};

export type ExternalSingleVolumeReport = {
  contractVersion: "external-single-volume-report.v1";
  reportId: string;
  requestId: string;
  requestDigest: string;
  payload: ExternalSingleVolumeMeasurementPayload;
  measurementPayloadDigest: string | null;
  workerInstanceId: string;
  leaseAcquisitionId: string;
  leaseGeneration: number;
  computedAt: string;
  reportedAt: string;
  reportDigest: string | null;
};

export type ExternalSingleVolumeExecutionPolicy = {
  contractVersion: "external-single-volume-execution-policy.v1";
  policyId: string;
  version: number;
  algorithmBuildDigest: string;
  configDigest: string;
  thresholdM: number;
  minimumCommonValidFraction: number;
  minimumBoundaryValidFraction: number;
  uncertaintyMethod: "SINGLE_EPOCH_BOUNDARY_BASE_RSS_AREA_BOUND_V1";
  baseSurfaceMethod: "BOUNDARY_LINEAR_INTERPOLATION_V1";
  resourceEnvelopeDigest: string;
  authorityRecordDigest: string;
  syntheticTestOnly: boolean;
  policyDigest: string | null;
};

export type ExternalSingleVolumeReportView = {
  request: ExternalSingleVolumeRequest;
  report: ExternalSingleVolumeReport;
  executionPolicy: ExternalSingleVolumeExecutionPolicy;
};

export function getExternalSingleVolumeReport(
  reportRef: string,
): Promise<ExternalSingleVolumeReportView> {
  return coreFetch(`/v1/external-single-volume-reports/${encodeURIComponent(reportRef)}`);
}

/** Merged newest-first history across both external volume families; `result.kind` distinguishes rows. */
export type ExternalVolumeHistoryItem = ExternalRelativeVolumeHistoryItem;

export function listSiteExternalVolumeHistory(
  siteId: string,
  options: { after?: string; limit?: number } = {},
): Promise<ExternalRelativeVolumeHistory> {
  return coreFetch<ExternalRelativeVolumeHistory>(
    `/v1/sites/${encodeURIComponent(siteId)}/external-volume-reports`,
    { query: { after: options.after, limit: options.limit } },
  );
}
