import "server-only";

import { coreFetch } from "./client";

export type AnalysisSelector = {
  workOrderId: string;
  submissionRef: string;
  revision: number;
};

export type AnalysisObservationOption = {
  selector: AnalysisSelector;
  observationEpochId: string;
  captureStartedAt: string;
  captureEndedAt: string;
};

export type AnalysisBlocker = {
  code: string;
  epoch: "BASELINE" | "CURRENT" | null;
  evidenceRef: string | null;
  detail: string | null;
};

export type AnalysisMetrics = {
  cutM3: number;
  fillM3: number;
  netM3: number;
  thresholdM: number;
  uncertaintyM3: number | null;
};

export type AnalysisCoverageSummary = {
  coverageWitnessDigest: string;
  rows: number;
  columns: number;
  selectedCellCount: number;
  commonValidCellCount: number;
  unavailableCellCount: number;
  thresholdExcludedCellCount: number;
  cellAreaM2: number;
  selectedAreaM2: number;
  commonValidAreaM2: number;
  bounds: [number, number, number, number];
};

export type AnalysisResult = {
  resultId: string;
  reportDigest: string;
  numericResultIdentityDigest: string;
  computedAt: string;
  metrics: AnalysisMetrics;
  coverage: AnalysisCoverageSummary;
  limitationCodes: string[];
};

export type AnalysisView = {
  analysisId: string;
  siteId: string;
  workAreaId: string;
  baseline: AnalysisSelector;
  current: AnalysisSelector;
  executionState: "NOT_STARTED" | "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED";
  suitabilityState: "BLOCKED" | "REMEDIATION_REQUIRED" | "PROVISIONAL_ACCURACY_UNVERIFIED" | "EVALUATED" | "REASSESSMENT_REQUIRED";
  blockers: AnalysisBlocker[];
  result: AnalysisResult | null;
  evidenceRevision: number;
  evidenceDigest: string;
  evidenceHref: string;
  coverageHref: string | null;
  createdAt: string;
};

export type AnalysisListItem = {
  analysisId: string;
  siteId: string;
  workAreaId: string;
  executionState: AnalysisView["executionState"];
  suitabilityState: AnalysisView["suitabilityState"];
  createdAt: string;
  resultId: string | null;
  metrics: AnalysisMetrics | null;
  limitationCount: number;
  analysisHref: string;
};

export type AnalysisListPage = {
  siteId: string;
  items: AnalysisListItem[];
  nextCursor: string | null;
};

type AnalysisEvidenceItemBase = {
  recordId: string;
  digest: string;
  href?: string | null;
  limitationCodes: string[];
};

export type AnalysisEpochEvidenceItem = AnalysisEvidenceItemBase & {
  kind: "EPOCH_IDENTITY";
  epoch: "BASELINE" | "CURRENT";
  selector: AnalysisSelector;
  observationEpochId: string;
  artifactId: string;
  observedSha256: string;
  observedSizeBytes: number;
  observedCrsIdentifier: string;
  observedCrsDigest: string;
  verticalReferenceIdentifier: string;
  verticalReferenceBasis: string;
  verticalUnit: "metre";
  transform: [number, number, number, number, number, number];
  transformDigest: string;
  inspectionReportDigest: string;
  inspectionReportRecordId: string;
  inputDigest: string;
};

export type AnalysisCalculationEvidenceItem = AnalysisEvidenceItemBase & {
  kind: "CALCULATION_IDENTITY";
  calculation: {
    calculationId: string;
    workAreaDefinitionDigest: string;
    baselineInputDigest: string;
    currentInputDigest: string;
    policy: {
      policyId: string;
      version: number;
      profileId: string;
      profileDigest: string;
      algorithmDigest: string;
      configDigest: string;
      policyDigest: string;
    };
    runtime: {
      workerExecutableDigest: string;
      workerBuildDigest: string;
      runtimeImageVersion: string;
      runtimeImageOciDigest: string;
      dependencyLockDigest: string;
    };
  };
};

export type AnalysisEvaluationEvidenceItem = AnalysisEvidenceItemBase & {
  kind: "EVALUATION";
  evaluationId: string;
  epoch: "BASELINE" | "CURRENT";
  revision: number;
  evaluationDigest: string;
  outcome: "PASS" | "FAIL" | "UNASSESSED" | "UNAVAILABLE";
  reasonCodes: string[];
  assessedAt: string;
};

export type AnalysisCheckpointEvidenceItem = AnalysisEvidenceItemBase & {
  kind: "CHECKPOINT_FACT";
  evaluationId: string;
  epoch: "BASELINE" | "CURRENT";
  evaluationRevision: number;
  evidenceRef: string;
  contextId: string;
  contextDigest: string;
  evidenceManifestDigest: string;
  evidenceRecordId: string;
  evidenceRecordDigest: string;
  coreVerdict: "VALIDATED" | "REJECTED";
};

export type AnalysisAuthorityEvidenceItem = AnalysisEvidenceItemBase & {
  kind: "AUTHORITY_REFERENCE";
  referenceName:
    | "assessmentRequestId"
    | "admissionId"
    | "admissionDigest"
    | "calculationIdentityDigest"
    | "calculationRequestId"
    | "authorizationId"
    | "reportDigest"
    | "failureDigest";
  sourceDigest: string | null;
};

export type AnalysisReferenceEvidenceItem = AnalysisEvidenceItemBase & {
  kind: "SOURCE_REFERENCE";
  referenceKind: string;
  sourceDigest: string | null;
};

export type AnalysisNumericResultEvidenceItem = AnalysisEvidenceItemBase & {
  kind: "NUMERIC_RESULT";
  resultId: string;
  reportDigest: string;
  numericResultIdentityDigest: string;
  computedAt: string;
};

export type AnalysisLimitationEvidenceItem = AnalysisEvidenceItemBase & {
  kind: "LIMITATION";
  source: "BLOCKER" | "RESULT";
  code: string;
  epoch: "BASELINE" | "CURRENT" | null;
  evidenceRef: string | null;
  detail: string | null;
};

export type AnalysisEvidenceItem =
  | AnalysisEpochEvidenceItem
  | AnalysisCalculationEvidenceItem
  | AnalysisEvaluationEvidenceItem
  | AnalysisCheckpointEvidenceItem
  | AnalysisAuthorityEvidenceItem
  | AnalysisReferenceEvidenceItem
  | AnalysisNumericResultEvidenceItem
  | AnalysisLimitationEvidenceItem;

export type AnalysisEvidencePage = {
  analysisId: string;
  evidenceRevision: number;
  evidenceDigest: string;
  items: AnalysisEvidenceItem[];
  nextCursor: string | null;
};

export async function listAnalysisObservations(siteId: string): Promise<AnalysisObservationOption[]> {
  return (await coreFetch<{ items: AnalysisObservationOption[] }>(
    `/v1/sites/${encodeURIComponent(siteId)}/analysis-observations`,
  )).items;
}

export function listAnalyses(
  siteId: string,
  options: { limit?: number; cursor?: string | null } = {},
): Promise<AnalysisListPage> {
  return coreFetch(`/v2/sites/${encodeURIComponent(siteId)}/analyses`, {
    query: { limit: options.limit ?? 50, cursor: options.cursor ?? undefined },
  });
}

export function getAnalysis(siteId: string, analysisId: string): Promise<AnalysisView> {
  return coreFetch(`/v2/sites/${encodeURIComponent(siteId)}/analyses/${encodeURIComponent(analysisId)}`);
}

export function getAnalysisResult(siteId: string, analysisId: string): Promise<AnalysisView> {
  return getAnalysis(siteId, analysisId);
}

export function getAnalysisEvidence(
  siteId: string,
  analysisId: string,
  options: { limit?: number; cursor?: string | null } = {},
): Promise<AnalysisEvidencePage> {
  return coreFetch(
    `/v2/sites/${encodeURIComponent(siteId)}/analyses/${encodeURIComponent(analysisId)}/evidence`,
    { query: { limit: options.limit ?? 32, cursor: options.cursor ?? undefined } },
  );
}

export function createAnalysis(
  siteId: string,
  workAreaId: string,
  input: { baseline: AnalysisSelector; current: AnalysisSelector },
  idempotencyKey: string,
): Promise<AnalysisView> {
  return coreFetch(
    `/v2/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/analyses`,
    {
      method: "POST",
      body: input,
      headers: { "Idempotency-Key": idempotencyKey },
    },
  );
}
