import "server-only";

import type { ExternalRelativeVolumeReportView } from "./external-result-workflow";
import {
  getExternalArtifactInspection,
  listExternalReconstructionSubmissions,
  type ExternalRevisionView,
} from "./external-reconstruction";
import type { ExactReportSafeDerivativePair, ExactSafeDerivative } from "../external-report-display-types";

type ReportSubject = ExternalRelativeVolumeReportView["request"]["baseline"]["subject"];
type Scope = { organizationId: string; siteId: string };

const UNAVAILABLE_REASON = "기준 또는 현재 관측의 보관된 표시 결속을 현재 확인하지 못했습니다.";

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function hasExactBinding(revision: ExternalRevisionView, subject: ReportSubject, scope: Scope): boolean {
  const manifest = record(revision.manifest);
  return revision.state === "SEALED"
    && revision.submission.organizationId === scope.organizationId
    && revision.submission.siteId === scope.siteId
    && revision.submission.submissionId === subject.submissionId
    && revision.submission.revision === subject.revision
    && revision.submission.submissionDigest === subject.submissionDigest
    && subject.organizationId === scope.organizationId
    && subject.siteId === scope.siteId
    && manifest?.organizationId === scope.organizationId
    && manifest?.siteId === scope.siteId
    && manifest?.submissionId === subject.submissionId
    && manifest?.submissionRevision === subject.revision
    && manifest?.submissionDigest === subject.submissionDigest
    && manifest?.manifestDigest === subject.manifestDigest;
}

function hasExpectedInspectionReport(report: unknown, expectedDigest: string): boolean {
  return record(report)?.reportDigest === expectedDigest;
}

async function resolveSubject(
  role: ExactSafeDerivative["role"],
  binding: ExternalRelativeVolumeReportView["request"]["baseline"],
  scope: Scope,
): Promise<ExactSafeDerivative | null> {
  const { subject } = binding;
  if (subject.organizationId !== scope.organizationId || subject.siteId !== scope.siteId) return null;

  const matches = (await listExternalReconstructionSubmissions(subject.workOrderId))
    .filter((revision) => hasExactBinding(revision, subject, scope));

  // A report subject must resolve to one retained revision. Choosing one of
  // multiple matches would silently change the report's evidence binding.
  if (matches.length !== 1) return null;
  const revision = matches[0];
  const inspection = await getExternalArtifactInspection(
    subject.workOrderId,
    revision.submissionRef,
    revision.submission.revision,
  );
  if (
    inspection.registrationState !== "SEALED"
    || inspection.sealState !== "SEALED"
    || inspection.inspection.state !== "INSPECTION_REPORTED"
    || !hasExpectedInspectionReport(inspection.inspection.report, binding.inspectionReportDigest)
    || inspection.display.state !== "SEALED"
    || typeof inspection.display.sanitizedDisplayRef !== "string"
    || typeof inspection.display.receiptDigest !== "string"
  ) return null;

  return {
    role,
    workOrderId: subject.workOrderId,
    submissionRef: revision.submissionRef,
    revision: revision.submission.revision,
    sanitizedDisplayRef: inspection.display.sanitizedDisplayRef,
    receiptDigest: inspection.display.receiptDigest,
    capturedFrom: binding.capturedFrom,
    capturedTo: binding.capturedTo,
  };
}

/**
 * Finds visual comparison inputs by matching every report-retained identity
 * and digest against server-issued submission references. It intentionally
 * fails closed rather than deriving an opaque submission reference.
 */
export async function resolveExactReportSafeDerivativePair(
  view: ExternalRelativeVolumeReportView,
  scope: Scope,
): Promise<ExactReportSafeDerivativePair> {
  try {
    const [baseline, current] = await Promise.all([
      resolveSubject("baseline", view.request.baseline, scope),
      resolveSubject("current", view.request.current, scope),
    ]);
    if (baseline === null || current === null) return { state: "UNAVAILABLE", reason: UNAVAILABLE_REASON };
    return { state: "READY", baseline, current };
  } catch {
    return { state: "UNAVAILABLE", reason: UNAVAILABLE_REASON };
  }
}
