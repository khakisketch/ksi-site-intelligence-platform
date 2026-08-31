import { summarizeCoverageCells } from "@/lib/core-api/coverage";
import type {
  CoverageReportView,
  CoverageRejectionListView,
  ReportExportCoverageSnapshot,
} from "@/lib/core-api/types";

/** One server-rendered coverage evidence state used by HTML, CSV and export audit. */
export type ReportCoverageEvidence =
  | {
      status: "REPORTED";
      missionId: string;
      report: CoverageReportView;
      rejections: CoverageRejectionListView;
    }
  | {
      status: "NOT_REPORTED";
      missionId: string;
      report: null;
      rejections: CoverageRejectionListView;
    }
  | {
      status: "UNAVAILABLE";
      missionId: string;
      report: CoverageReportView | null;
      rejections: CoverageRejectionListView | null;
      detail: string;
    };

export type CompleteReportCoverageEvidence = Exclude<
  ReportCoverageEvidence,
  { status: "UNAVAILABLE" }
>;

export function isCompleteCoverageEvidence(
  evidence: ReportCoverageEvidence,
): evidence is CompleteReportCoverageEvidence {
  return evidence.status !== "UNAVAILABLE";
}

function rejectionsMatch(
  source: CoverageRejectionListView,
  snapshot: ReportExportCoverageSnapshot,
): boolean {
  if (
    source.missionId !== snapshot.missionId ||
    source.rejectionCount !== snapshot.rejectionCount ||
    source.rejections.length !== snapshot.rejections.length
  ) {
    return false;
  }
  return source.rejections.every((item, index) => {
    const recorded = snapshot.rejections[index];
    return (
      recorded !== undefined &&
      item.verdict === recorded.verdict &&
      item.detail === recorded.detail &&
      item.reportedBy === recorded.reportedBy &&
      item.rejectedAt === recorded.rejectedAt
    );
  });
}

/**
 * The browser never computes Core's canonical report digest. It instead checks every
 * coverage value rendered into the document against the server-derived audit snapshot.
 */
export function coverageSnapshotMatchesEvidence(
  evidence: CompleteReportCoverageEvidence,
  snapshot: ReportExportCoverageSnapshot,
): boolean {
  if (
    evidence.missionId !== snapshot.missionId ||
    !rejectionsMatch(evidence.rejections, snapshot)
  ) {
    return false;
  }
  if (evidence.status === "NOT_REPORTED") {
    return (
      snapshot.availability === "NOT_REPORTED" &&
      snapshot.reportCount === 0 &&
      snapshot.reportDigest === null
    );
  }

  const { report } = evidence;
  const { latest } = report;
  const cells = summarizeCoverageCells(latest.cells);
  return (
    report.missionId === evidence.missionId &&
    latest.missionId === evidence.missionId &&
    snapshot.availability === "REPORTED" &&
    snapshot.reportDigest !== null &&
    snapshot.reportCount === report.reportCount &&
    snapshot.reportedBy === report.reportedBy &&
    snapshot.reportTimestamp === latest.timestamp &&
    snapshot.completionState === latest.summary.completionState &&
    snapshot.mandatoryHazardRatio === latest.summary.mandatoryHazardRatio &&
    snapshot.mandatoryAssetRatio === latest.summary.mandatoryAssetRatio &&
    snapshot.accessibleGeneralRatio === latest.summary.accessibleGeneralRatio &&
    snapshot.unobservedCellCount === cells.explainedGap + cells.unexplainedGap &&
    snapshot.recoveryRecommended === report.recoveryRecommended &&
    snapshot.ratioAttributionNote === report.ratioAttributionNote &&
    snapshot.plannedGeneralCoverageRatio === report.plannedGeneralCoverageRatio &&
    snapshot.plannedGeneralCoverageUnavailableReason ===
      report.plannedGeneralCoverageUnavailableReason
  );
}
