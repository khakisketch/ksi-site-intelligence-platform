import Link from "next/link";
import { notFound } from "next/navigation";

import { ErrorState } from "@/components/ui/ErrorState";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { PageHeader } from "@/components/ui/PageHeader";
import { ConsolePage } from "@/components/nav/ConsolePage";
import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
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

function ObservationDetailReadFailure({
  siteId,
  siteName,
  error,
  subject = "관측 결과",
}: {
  siteId: string;
  siteName?: string;
  error: unknown;
  subject?: string;
}) {
  const apiError = error instanceof CoreApiError ? error : null;
  const denied = apiError?.status === 403;
  const retryable = apiError ? apiError.status >= 500 : true;
  const deniedSubject = subject === "관측 결과" ? `이 ${subject}` : subject;
  const message = denied
    ? `${deniedSubject}를 확인할 권한이 없습니다.`
    : retryable
      ? `${subject}를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.`
      : `${subject}를 확인할 수 없습니다.`;

  return <ConsolePage density="dense">
    <PageHeader title="외부 비교 결과" description={siteName} headingLevel={2} />
    <ErrorState
      message={message}
      tone={denied ? "high" : retryable ? "crit" : "idle"}
      retryable={retryable}
      retryAfterSeconds={apiError?.retryAfterSeconds}
      action={{ label: "외부 비교 이력", href: `/sites/${encodeURIComponent(siteId)}/observations` }}
    />
  </ConsolePage>;
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
  let site: Awaited<ReturnType<typeof getSite>>;
  try {
    site = await getSite(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    return <ObservationDetailReadFailure siteId={siteId} error={error} subject="현장 정보" />;
  }

  // 작업구역 이름은 표시 보조일 뿐이다. 이름 조회가 실패해도 보관 결과는
  // 가리지 않는다 — 이름 없는 행은 '작업구역'으로 표시하고, 이름 실패만 따로
  // 알린다. 이름 목록에는 권한 없는 자료가 담기지 않으므로(실패 시 빈 목록)
  // 노출이 없다.
  const [projectionResult, areasResult] = await Promise.allSettled([
    getSiteExternalRelativeVolumeReport(siteId, reportRef),
    listWorkAreas(siteId),
  ]);
  if (projectionResult.status === "rejected") {
    return <ObservationDetailReadFailure siteId={siteId} siteName={site.name} error={projectionResult.reason} />;
  }
  const projection = projectionResult.value;
  const areaNamesUnavailable = areasResult.status === "rejected";
  const names = new Map(
    (areasResult.status === "fulfilled" ? areasResult.value.workAreas : []).map((area) => [area.workAreaId, area.name]),
  );
  const resultProjection = projection.state === "AVAILABLE" ? projection.result ?? null : null;
  // A SINGLE_VOLUME result has no baseline pair or relative report detail; its exact
  // single report is re-verified below before it feeds share or successor facts.
  const single = isSingleVolumeResult(resultProjection);
  let detail: ExternalRelativeVolumeReportView | null = null;
  let singleDetail: ExternalSingleVolumeReportView | null = null;
  let detailReadError: unknown = null;
  if (resultProjection !== null && !single) {
    try {
      detail = await getExternalRelativeVolumeReport(reportRef);
    } catch (error) {
      detailReadError = error;
    }
  } else if (resultProjection !== null && single) {
    try {
      singleDetail = await getExternalSingleVolumeReport(reportRef);
    } catch (error) {
      detailReadError = error;
    }
  }
  const organizationId = session.principal.organizationId;
  const exactDetail = detail !== null && resultProjection !== null && isExactReportDetail(detail, resultProjection, siteId, reportRef, organizationId)
    ? detail
    : null;
  // The single exact view is trusted only when it re-verifies against the projection:
  // the same report id, the same retained report digest, and the same exact scope
  // binding as the relative path (current work order, source work order, and the
  // target subject's work order, site, and organization). No weaker binding is shown.
  const exactSingleDetail = singleDetail !== null && resultProjection !== null
    && isExactSingleReportDetail(singleDetail, resultProjection, siteId, reportRef, organizationId)
    ? singleDetail
    : null;
  const displayPair = exactDetail === null
    ? unavailablePair("보관된 보고서 상세와 현재 표시 결속을 함께 확인하지 못했습니다.")
    : await resolveExactReportSafeDerivativePair(exactDetail, {
      organizationId,
      siteId,
  });
  const verifiedDetail = exactDetail ?? exactSingleDetail;
  const successors = verifiedDetail === null || resultProjection === null
    ? null
    : await resolveSuccessorTrace(verifiedDetail, reportRef, resultProjection.reportDigest, {
      organizationId,
      siteId,
    });
  return <>
    <div className="print:hidden">
      <SiteHeader site={site} selectedEpochId={null} tab="analysis" />
    </div>
    <ConsolePage density="dense">
      <PageHeader title={single ? "단일 시점 체적 결과" : "외부 비교 결과"} headingLevel={2}
        actions={<><PrintReportButton /><Link href={`/sites/${encodeURIComponent(siteId)}/observations`} className="btn">외부 비교 이력</Link></>} />
    {areaNamesUnavailable && <InlineNotice>작업구역 이름을 불러오지 못했습니다. 이름이 없는 행은 작업구역으로 표시됩니다.</InlineNotice>}
    <ExternalObservationHistory siteId={siteId} detailMode items={[{ reportRef, state: projection.state === "AVAILABLE" ? "AVAILABLE" : "HISTORICAL_SOURCE_UNAVAILABLE", result: projection.result ?? null }]} workAreaNames={names} />
    {detailReadError !== null && <ErrorState
      message={detailReadError instanceof CoreApiError && detailReadError.status === 403
        ? "상세 근거를 확인할 권한이 없습니다."
        : detailReadError instanceof CoreApiError && detailReadError.status >= 500
          ? "상세 근거를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."
          : "상세 근거를 확인할 수 없습니다."}
      tone={detailReadError instanceof CoreApiError && detailReadError.status === 403 ? "high" : detailReadError instanceof CoreApiError && detailReadError.status >= 500 ? "crit" : "idle"}
      retryable={!(detailReadError instanceof CoreApiError) || detailReadError.status >= 500}
      retryAfterSeconds={detailReadError instanceof CoreApiError ? detailReadError.retryAfterSeconds : undefined}
    />}
    {exactDetail !== null && !single && <ExternalReportSafeDerivativeComparison pair={displayPair} />}
    {verifiedDetail !== null && <TeamReportShare
      key={`${organizationId}:${session.principal.principalId}:${reportRef}`}
      reportRef={reportRef}
      siteId={siteId}
      organizationId={organizationId}
      principalId={session.principal.principalId}
      canWrite={session.principal.permissions.includes("WORK_ORDERS_WRITE")}
    />}
    {verifiedDetail !== null && resultProjection !== null && <ExternalReportFollowupTrace
      reportRef={reportRef}
      // Core's report_for_site merges both external volume families; a SINGLE_VOLUME
      // result has baselineWorkOrderId null and the trace shows no baseline link for it.
      baselineWorkOrderId={resultProjection.baselineWorkOrderId}
      currentWorkOrderId={resultProjection.currentWorkOrderId}
      successors={successors}
    />}
    {verifiedDetail === null && resultProjection !== null && <section className="rounded-xl border border-line bg-surface p-4">
      <h2 className="text-title font-bold tracking-tight">검토·재관측 흐름</h2>
      <p className="mt-1 text-body leading-5 text-ink-2">상세 근거를 확인할 수 없어 검토·재관측 상태를 표시하지 않습니다.</p>
    </section>}
    </ConsolePage>
  </>;
}
