import Link from "next/link";
import { notFound } from "next/navigation";

import { ErrorState } from "@/components/ui/ErrorState";
import { PrintReportButton } from "@/components/reports/PrintReportButton";
import { isSingleVolumeResult } from "@/components/external-results/SingleVolumeResult";
import { TeamReportShare } from "@/components/external-results/TeamReportShare";
import { CoreApiError } from "@/lib/core-api/client";
import {
  getExternalRelativeVolumeReport,
  getExternalSingleVolumeReport,
  getSiteExternalRelativeVolumeReport,
  type ExternalRelativeVolumeReportView,
  type ExternalSingleVolumeReportView,
} from "@/lib/core-api/external-result-workflow";
import { getObservationWorkOrderOperations } from "@/lib/core-api/observation-work-orders";
import { resolveExactReportSafeDerivativePair } from "@/lib/core-api/external-report-display";
import type { ExactReportSafeDerivativePair } from "@/lib/external-report-display-types";
import { getSite } from "@/lib/core-api/sites";
import { listWorkAreas } from "@/lib/core-api/workAreas";

import { OperationsSessionFailure } from "@/app/field/OperationsSessionFailure";
import { resolveFieldSession } from "@/app/field/resolve-session";

import { ExternalObservationHistory } from "../ExternalObservationHistory";
import { ExternalReportFollowupTrace, type ReportSuccessorTrace } from "./ExternalReportFollowupTrace";
import { ExternalReportSafeDerivativeComparison } from "./ExternalReportSafeDerivativeComparison";

export const metadata = { title: "외부 관측 결과 · KSI" };

const unavailablePair = (reason: string): ExactReportSafeDerivativePair => ({ state: "UNAVAILABLE", reason });

function isExactReportDetail(
  detail: ExternalRelativeVolumeReportView,
  projection: NonNullable<Awaited<ReturnType<typeof getSiteExternalRelativeVolumeReport>>["result"]>,
  siteId: string,
  reportRef: string,
  organizationId: string,
): boolean {
  const { request, report } = detail;
  return report.reportId === reportRef
    && report.reportDigest === projection.reportDigest
    && request.currentWorkOrderId === projection.currentWorkOrderId
    && projection.sourceWorkOrderId === projection.currentWorkOrderId
    && request.baseline.subject.workOrderId === projection.baselineWorkOrderId
    && request.current.subject.workOrderId === projection.currentWorkOrderId
    && request.baseline.subject.siteId === siteId
    && request.current.subject.siteId === siteId
    && request.baseline.subject.organizationId === organizationId
    && request.current.subject.organizationId === organizationId;
}

function isExactSingleReportDetail(
  detail: ExternalSingleVolumeReportView,
  projection: NonNullable<Awaited<ReturnType<typeof getSiteExternalRelativeVolumeReport>>["result"]>,
  siteId: string,
  reportRef: string,
  organizationId: string,
): boolean {
  const { request, report } = detail;
  return report.reportId === reportRef
    && report.reportDigest === projection.reportDigest
    && request.currentWorkOrderId === projection.currentWorkOrderId
    && projection.sourceWorkOrderId === projection.currentWorkOrderId
    && request.target.subject.workOrderId === projection.currentWorkOrderId
    && request.target.subject.siteId === siteId
    && request.target.subject.organizationId === organizationId;
}

async function resolveSuccessorTrace(
  detail: ExternalRelativeVolumeReportView | ExternalSingleVolumeReportView,
  reportRef: string,
  reportDigest: string,
  scope: { organizationId: string; siteId: string },
): Promise<ReportSuccessorTrace[]> {
  const review = detail.review;
  if (review === null || review === undefined || review.reportRef !== reportRef || review.report.reportDigest !== reportDigest) return [];
  const successorIds = [...new Set((detail.proposals ?? []).flatMap((entry) => (
    entry.approvalReceipt !== null
      && entry.proposal.reportRef === reportRef
      && entry.proposal.reportDigest === reportDigest
      && entry.proposal.reviewRef === review.reviewRef
      && entry.proposal.reviewDigest === review.reviewDigest
      ? [entry.approvalReceipt.successorWorkOrderId]
      : []
  )))];
  return Promise.all(successorIds.map(async (workOrderId) => {
    const operations = await getObservationWorkOrderOperations(workOrderId).catch(() => null);
    const verified = operations !== null
      && operations.workOrderId === workOrderId
      && operations.organizationId === scope.organizationId
      && operations.siteId === scope.siteId;
    return {
      workOrderId,
      workflowStatus: verified ? operations.workflowStatus : null,
      closeNote: verified ? operations.closeNote : null,
    };
  }));
}

export default async function SiteObservationDetailPage({
  params,
}: {
  params: Promise<{ siteId: string; reportRef: string }>;
}) {
  const { siteId, reportRef } = await params;
  const session = await resolveFieldSession();
  if (session.kind === "blocked") {
    return <OperationsSessionFailure
      verdict={session.verdict}
      next={`/sites/${encodeURIComponent(siteId)}/observations/${encodeURIComponent(reportRef)}`}
    />;
  }
  let loaded: {
    site: Awaited<ReturnType<typeof getSite>>;
    projection: Awaited<ReturnType<typeof getSiteExternalRelativeVolumeReport>>;
    areas: Awaited<ReturnType<typeof listWorkAreas>>;
  } | null = null;
  try {
    const [site, projection, areas] = await Promise.all([
      getSite(siteId),
      getSiteExternalRelativeVolumeReport(siteId, reportRef),
      listWorkAreas(siteId),
    ]);
    loaded = { site, projection, areas };
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
  }
  if (loaded === null) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="외부 관측 결과를 불러오지 못했습니다." retryable /></div>;
  }
  const names = new Map(loaded.areas.workAreas.map((area) => [area.workAreaId, area.name]));
  const projection = loaded.projection.state === "AVAILABLE" ? loaded.projection.result ?? null : null;
  // A SINGLE_VOLUME result has no baseline pair or relative report detail; its exact
  // single report is re-verified below before it feeds share or successor facts.
  const single = isSingleVolumeResult(projection);
  const detail = projection === null || single
    ? null
    : await getExternalRelativeVolumeReport(reportRef).catch(() => null);
  const singleDetail = projection === null || !single
    ? null
    : await getExternalSingleVolumeReport(reportRef).catch(() => null);
  const organizationId = session.principal.organizationId;
  const exactDetail = detail !== null && projection !== null && isExactReportDetail(detail, projection, siteId, reportRef, organizationId)
    ? detail
    : null;
  // The single exact view is trusted only when it re-verifies against the projection:
  // the same report id, the same retained report digest, and the same exact scope
  // binding as the relative path (current work order, source work order, and the
  // target subject's work order, site, and organization). No weaker binding is shown.
  const exactSingleDetail = singleDetail !== null && projection !== null
    && isExactSingleReportDetail(singleDetail, projection, siteId, reportRef, organizationId)
    ? singleDetail
    : null;
  const displayPair = exactDetail === null
    ? unavailablePair("보관된 보고서 상세와 현재 표시 결속을 함께 확인하지 못했습니다.")
    : await resolveExactReportSafeDerivativePair(exactDetail, {
      organizationId,
      siteId,
    });
  const verifiedDetail = exactDetail ?? exactSingleDetail;
  const successors = verifiedDetail === null || projection === null
    ? null
    : await resolveSuccessorTrace(verifiedDetail, reportRef, projection.reportDigest, {
      organizationId,
      siteId,
    });
  return <div className="mx-auto flex max-w-5xl flex-col gap-4 p-4 sm:p-5">
    <header className="flex flex-wrap items-end justify-between gap-3 border-b border-line pb-3">
      <div>
        <p className="text-[12.5px] text-ink-2">{loaded.site.name}</p>
        {single ? <>
          <h1 className="mt-1 text-[22px] font-bold tracking-tight">단일 시점 체적 결과</h1>
          <p className="mt-1 text-[13px] leading-5 text-ink-2">한 시점 관측으로 측정한 보관 체적 결과입니다.</p>
        </> : <>
          <h1 className="mt-1 text-[22px] font-bold tracking-tight">외부 관측 비교 결과</h1>
          <p className="mt-1 text-[13px] leading-5 text-ink-2">기준 관측과 현재 관측을 비교한 보관 결과입니다.</p>
        </>}
      </div>
      <div className="flex flex-wrap gap-2"><PrintReportButton /><Link href={`/sites/${encodeURIComponent(siteId)}/observations`} className="btn">관측 이력</Link></div>
    </header>
    <ExternalObservationHistory siteId={siteId} detailMode items={[{ reportRef, state: loaded.projection.state === "AVAILABLE" ? "AVAILABLE" : "HISTORICAL_SOURCE_UNAVAILABLE", result: loaded.projection.result ?? null }]} workAreaNames={names} />
    {!single && <ExternalReportSafeDerivativeComparison pair={displayPair} />}
    {verifiedDetail !== null && <TeamReportShare
      key={`${organizationId}:${session.principal.principalId}:${reportRef}`}
      reportRef={reportRef}
      siteId={siteId}
      organizationId={organizationId}
      principalId={session.principal.principalId}
      canWrite={session.principal.permissions.includes("WORK_ORDERS_WRITE")}
    />}
    {projection !== null && <ExternalReportFollowupTrace
      reportRef={reportRef}
      // Core's report_for_site merges both external volume families; a SINGLE_VOLUME
      // result has baselineWorkOrderId null and the trace shows no baseline link for it.
      baselineWorkOrderId={projection.baselineWorkOrderId}
      currentWorkOrderId={projection.currentWorkOrderId}
      successors={successors}
    />}
  </div>;
}
