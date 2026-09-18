import Link from "next/link";
import { notFound } from "next/navigation";

import { StateBadge } from "@/components/ui/StatusBadge";
import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { CoreApiError } from "@/lib/core-api/client";
import { getAcquisitionProgress } from "@/lib/core-api/acquisition-coordination";
import { getAcquisitionReadiness } from "@/lib/core-api/acquisition-connectivity";
import {
  getObservationWorkOrder,
  getObservationWorkOrderOperations,
  listReobservationDrafts,
} from "@/lib/core-api/observation-work-orders";
import {
  getExternalReconstructionContext,
  listExternalReconstructionSubmissions,
  resolveExternalWorkOrderExecutionContext,
} from "@/lib/core-api/external-reconstruction";
import {
  getExternalRelativeVolumeReport,
  getExternalSingleVolumeReport,
  getSiteExternalRelativeVolumeReport,
} from "@/lib/core-api/external-result-workflow";
import { getSite } from "@/lib/core-api/sites";
import { getLatestSiteBriefing, getSiteWorkspace } from "@/lib/core-api/site-workspace";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import type { ReobservationDraftView } from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";
import { isExternalRelativeVolumeReportReference } from "@/lib/external-relative-volume-references";
import { isExternalSingleVolumeReportReference } from "@/lib/external-single-volume-references";

import { CopilotPanel } from "../../CopilotPanel";
import { ExternalReconstructionPanel } from "../../ExternalReconstructionPanel";
import type { TrustedExternalResultLink } from "../../ExternalResultWorkflowPanel";
import { AcquisitionProgressCard } from "../../AcquisitionProgressCard";
import { AcquisitionReadinessCard } from "../../AcquisitionReadinessCard";
import { OperationsSessionFailure } from "../../OperationsSessionFailure";
import { OperationsWorkHeader } from "../../OperationsWorkHeader";
import { WorkOrderActionPanel } from "../../WorkOrderActionPanel";
import { WorkOrderOperationsPanel } from "../../WorkOrderOperationsPanel";
import { resolveFieldSession } from "../../resolve-session";
import { deriveExternalWorkOrderStage } from "../../external-work-order-stage";
import { presentWorkOrder } from "../../work-order-stage";

export const metadata = { title: "현장 작업 · KSI" };

export default async function FieldWorkOrderPage({
  params,
  searchParams,
}: {
  params: Promise<{ workOrderId: string }>;
  searchParams: Promise<{ reportRef?: string }>;
}) {
  const { workOrderId } = await params;
  const { reportRef: requestedReportRef } = await searchParams;
  const reportRef =
    isExternalRelativeVolumeReportReference(requestedReportRef) ||
    isExternalSingleVolumeReportReference(requestedReportRef)
      ? requestedReportRef
      : null;
  const isSingleVolumeReportRef = reportRef !== null && isExternalSingleVolumeReportReference(reportRef);
  const workOrderPath = "/field/work-orders/" + encodeURIComponent(workOrderId);
  const next = reportRef === null
    ? workOrderPath
    : `${workOrderPath}?reportRef=${encodeURIComponent(reportRef)}#external-result`;
  const session = await resolveFieldSession();
  if (session.kind === "blocked") {
    return <OperationsSessionFailure verdict={session.verdict} next={next} />;
  }

  let workOrder;
  try {
    workOrder = await getObservationWorkOrder(workOrderId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    throw error;
  }
  const [
    site,
    drafts,
    acquisitionProgress,
    readinessFallback,
    externalContext,
    resultWorkspace,
    exactRelativeReport,
    exactSingleReport,
    siteExactProjection,
    workAreas,
  ] = await Promise.all([
    getSite(workOrder.siteId).catch(() => null),
    listReobservationDrafts(workOrder.workOrderId).catch(() => []),
    getAcquisitionProgress(workOrder.workOrderId).catch(() => null),
    getAcquisitionReadiness(workOrder.siteId).catch(() => null),
    getExternalReconstructionContext(workOrder.workOrderId).catch(() => null),
    reportRef ? getSiteWorkspace(workOrder.siteId).catch(() => null) : Promise.resolve(null),
    reportRef && !isSingleVolumeReportRef
      ? getExternalRelativeVolumeReport(reportRef).catch(() => null)
      : Promise.resolve(null),
    reportRef && isSingleVolumeReportRef
      ? getExternalSingleVolumeReport(reportRef).catch(() => null)
      : Promise.resolve(null),
    reportRef
      ? getSiteExternalRelativeVolumeReport(workOrder.siteId, reportRef).catch(() => null)
      : Promise.resolve(null),
    reportRef ? listWorkAreas(workOrder.siteId).catch(() => null) : Promise.resolve(null),
  ]);
  // Exactly one of these is fetched, keyed by the ref's own family prefix.
  const exactReport = exactRelativeReport ?? exactSingleReport;
  let initialReport: TrustedExternalResultLink | undefined;
  let reportLinkNotice: string | null = null;
  if (requestedReportRef && !reportRef) {
    reportLinkNotice = "열려는 비교 결과 주소가 올바르지 않습니다. 현장 결과 목록에서 다시 열어 주세요.";
  } else if (reportRef) {
    // The site-scoped exact projection (not the site-latest summary) resolves
    // both families and is the only source trusted to confirm this ref is
    // still the retained report at its digest.
    const projection = siteExactProjection?.state === "AVAILABLE" ? siteExactProjection.result ?? null : null;
    if (
      exactReport !== null &&
      projection !== null &&
      exactReport.request.currentWorkOrderId === workOrder.workOrderId &&
      exactReport.report.reportId === reportRef &&
      exactReport.report.reportDigest === projection.reportDigest
    ) {
      // The trusted-link panel only renders RELATIVE_VOLUME views today; a
      // verified SINGLE_VOLUME deep link is accepted (no failure notice) but
      // is not yet wired into the panel.
      if (exactRelativeReport !== null) {
        initialReport = {
          reportRef,
          reportDigest: projection.reportDigest,
          view: exactRelativeReport,
          workAreaName: workAreas?.workAreas.find(
            (area) => area.workAreaId === exactRelativeReport.request.zoneSnapshot.workAreaId,
          )?.name ?? null,
        };
      }
    } else {
      reportLinkNotice = "이 작업에서 확인할 수 있는 최신 비교 결과인지 검증하지 못했습니다. 현장 결과 목록에서 다시 열어 주세요.";
    }
  }
  const externalExecutionContext = resolveExternalWorkOrderExecutionContext(workOrder, externalContext);
  const externalEpochId = externalExecutionContext === "UNVERIFIED" ? null : externalContext!.expectedEpochId;
  const planningOnly = externalExecutionContext === "EXTERNAL_REOBSERVATION_PLANNING";
  const externalIngress = externalExecutionContext === "EXTERNAL_INGRESS";
  const externalWorkflow = planningOnly || externalIngress;
  // Retained external planning successors predate executionMode. Resolve the
  // verified execution context before asking for their operations projection.
  const operations = externalWorkflow
    ? await getObservationWorkOrderOperations(workOrder.workOrderId).catch(() => null)
    : null;
  const workflowClosed = operations?.workflowStatus === "CLOSED";
  const managedExecution = externalExecutionContext === "MANAGED";
  const acquisitionReadiness = acquisitionProgress?.readiness ?? readinessFallback;
  const pendingDraft = latestPendingDraft(drafts);
  const presentation = presentWorkOrder(workOrder.status);
  // The external next action is derived from retained loop facts (registered
  // and sealed submissions, this order's latest result, review, approval); it
  // never infers processing, flight or device state.
  const [externalSubmissions, externalWorkspace] = externalWorkflow
    ? await Promise.all([
        listExternalReconstructionSubmissions(workOrder.workOrderId).catch(() => []),
        resultWorkspace ?? getSiteWorkspace(workOrder.siteId).catch(() => null),
      ])
    : [[], null];
  const ownExternalResult =
    externalWorkspace?.externalResult.state === "AVAILABLE" &&
    externalWorkspace.externalResult.result?.currentWorkOrderId === workOrder.workOrderId
      ? externalWorkspace.externalResult.result
      : null;
  // A deterministic briefing that cites this order's latest report is shown
  // next to the next action; other sites' or older briefings are not.
  const latestBriefing =
    externalWorkflow && ownExternalResult
      ? await getLatestSiteBriefing(workOrder.siteId).catch(() => null)
      : null;
  const externalBriefing =
    latestBriefing &&
    latestBriefing.citations.some(
      (citation) =>
        citation.objectType === "external-relative-volume-report" &&
        citation.objectId === ownExternalResult?.reportRef,
    )
      ? latestBriefing
      : null;
  const externalStage = externalWorkflow
    ? deriveExternalWorkOrderStage({
        planningOnly,
        workflowClosed,
        sealedSubmissionCount: externalSubmissions.filter((item) => item.state === "SEALED").length,
        registeredSubmissionCount: externalSubmissions.filter((item) => item.state === "REGISTERED").length,
        latestResult: ownExternalResult,
      })
    : null;
  const cardPresentation = externalStage
    ? { label: externalStage.label, detail: externalStage.detail, tone: externalStage.tone }
    : externalExecutionContext === "UNVERIFIED"
      ? {
          label: "작업 실행 정보 확인 필요",
          detail: "작업 실행 정보를 확인하지 못했습니다. 비행이나 장비 실행 준비 상태를 표시하지 않습니다.",
          tone: "caution" as const,
        }
      : presentation;
  // WorkOrder status and a successful ProcessingJob alone do not establish
  // evidence completeness. Copilot is available only after Core's derived
  // Analysis Readiness gate explicitly says ready.
  const showCopilot =
    managedExecution &&
    (workOrder.status === "REVIEW_READY" || workOrder.status === "COMPLETED") &&
    acquisitionProgress?.analysisReadiness?.ready === true;

  return (
    <div className="flex flex-col">
      <OperationsWorkHeader>
        <div className="flex flex-col gap-1">
          <h1 className="text-[19px] font-bold tracking-tight break-keep">{workOrder.name}</h1>
          <p className="text-[12.5px] break-keep text-ink-2">
            {site?.name ?? "현장"} · {workOrder.workAreaIds.length}개 구역 ·{" "}
            {workOrder.cycleNumber}회차
          </p>
        </div>
      </OperationsWorkHeader>

      <div className="flex flex-col gap-4 p-4 lg:p-5">
        <section className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink-muted">지금 할 일</span>
              <h2 className="text-[18px] font-bold tracking-tight">{cardPresentation.label}</h2>
            </div>
            <StateBadge label={cardPresentation.label} tone={cardPresentation.tone} />
          </div>

          <p className="text-[14px] leading-6 break-keep text-ink-2">{cardPresentation.detail}</p>
          {externalBriefing && (
            <div className="grid gap-px rounded-lg border border-line bg-line lg:grid-cols-3" data-testid="external-briefing">
              <div className="bg-surface px-3 py-3">
                <p className="text-[11.5px] font-bold text-ink-muted">무엇이 달라졌나</p>
                <p className="mt-1 text-[13px] leading-5 break-keep">{externalBriefing.whatChanged}</p>
              </div>
              <div className="bg-surface px-3 py-3">
                <p className="text-[11.5px] font-bold text-ink-muted">왜 중요한가</p>
                <p className="mt-1 text-[13px] leading-5 break-keep">{externalBriefing.whyItMatters}</p>
                <p className="mt-1 text-[12px] text-ink-2 break-keep">{externalBriefing.uncertainty}</p>
              </div>
              <div className="bg-surface px-3 py-3">
                <p className="text-[11.5px] font-bold text-ink-muted">지금 검토할 결정</p>
                <p className="mt-1 text-[13px] font-semibold leading-5 break-keep">{externalBriefing.decisionPrompt}</p>
              </div>
            </div>
          )}
          {reportLinkNotice && (
            <p role="alert" className="rounded-lg border border-high/30 bg-high-bg px-3 py-2 text-[13px] text-high-ink">
              {reportLinkNotice}
            </p>
          )}
          {workOrder.statusReason && (
            <p className="rounded-lg bg-high-bg px-3 py-2 text-[13px] break-keep text-high-ink">
              {workOrder.statusReason}
            </p>
          )}
          {managedExecution && pendingDraft && (
            <div className="rounded-lg border border-high/30 bg-high-bg px-3 py-3 text-[13px] text-high-ink">
              <p className="font-semibold">추가 촬영 제안</p>
              <p className="mt-1 break-keep">{pendingDraft.proposedEffort}</p>
              <p className="mt-1 text-[12px]">
                {pendingDraft.targetRegionRefs.length}개 구역 ·{" "}
                {formatKoreanDateTime(pendingDraft.expiresAt, {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}{" "}
                까지 승인 가능
              </p>
            </div>
          )}
          {planningOnly && (
            <p className="rounded-lg border border-line bg-sunk px-3 py-2 text-[13px] text-ink-2">
              이 작업은 승인된 재관측의 후속 작업입니다. 외부 산출물을 등록하는 흐름만 표시하며 비행이나 장비 실행은 제공하지 않습니다.
            </p>
          )}
          {externalIngress && (
            <p className="rounded-lg border border-line bg-sunk px-3 py-2 text-[13px] text-ink-2">
              이 작업은 외부에서 준비한 재구성 산출물을 등록하기 위한 작업입니다. 관리형 비행·수집 실행은 제공하지 않습니다.
            </p>
          )}
          {externalExecutionContext === "UNVERIFIED" && (
            <p className="rounded-lg border border-high/30 bg-high-bg px-3 py-2 text-[13px] text-high-ink">
              작업 실행 정보를 확인하지 못했습니다. 비행이나 장비 실행 제어를 표시하지 않습니다.
            </p>
          )}
          {managedExecution && <WorkOrderActionPanel
              workOrderId={workOrder.workOrderId}
              siteId={workOrder.siteId}
              version={workOrder.version}
              presentation={presentation}
              pendingDraft={pendingDraft}
              acquisitionProgress={acquisitionProgress}
            />}
        </section>

        {managedExecution && <AcquisitionProgressCard progress={acquisitionProgress} />}

        {managedExecution && <AcquisitionReadinessCard
          readiness={acquisitionReadiness}
          progress={acquisitionProgress}
        />}

        {externalWorkflow && (
          <WorkOrderOperationsPanel
            workOrderId={workOrder.workOrderId}
            principalId={session.principal.principalId}
            initialOperations={operations}
            canWrite={session.principal.permissions.includes("WORK_ORDERS_WRITE")}
          />
        )}

        <ExternalReconstructionPanel
          workOrderId={workOrder.workOrderId}
          siteId={workOrder.siteId}
          expectedEpochId={externalEpochId}
          canWrite={session.principal.permissions.includes("SITES_WRITE")}
          permissions={session.principal.permissions}
          initialReport={initialReport}
          requiresCaptureInterval={externalIngress}
          newIntentAllowed={!workflowClosed}
        />

        {showCopilot && (
          <CopilotPanel siteId={workOrder.siteId} workOrderId={workOrder.workOrderId} />
        )}

        {managedExecution && <ResponsiveActionBoundary
          action="RECOVERY_ACTION"
          reason="기술 ID와 수동 임무 복구는 노트북의 전문가 복구 화면에서만 다룹니다."
        >
          <details className="rounded-lg border border-line bg-surface px-4 py-3 text-[13px]">
            <summary className="min-h-11 cursor-pointer font-semibold">전문가 복구 정보</summary>
            <div className="flex flex-col gap-2 border-t border-line pt-3 text-ink-2">
              <p>
                자동 전달·회수가 막혔을 때만 사용합니다. 일반 작업자는 파일명이나 기술 ID를
                다룰 필요가 없습니다.
              </p>
              {workOrder.missionIds.length === 0 ? (
                <p>아직 연결된 비행 임무가 없습니다.</p>
              ) : (
                workOrder.missionIds.map((missionId) => (
                  <Link
                    key={missionId}
                    href={"/field/" + encodeURIComponent(missionId)}
                    className="btn w-fit"
                  >
                    수동 임무 복구 열기
                  </Link>
                ))
              )}
            </div>
          </details>
        </ResponsiveActionBoundary>}
      </div>
    </div>
  );
}

function latestPendingDraft(drafts: ReobservationDraftView[]): ReobservationDraftView | null {
  return (
    drafts
      .filter((draft) => draft.status === "PENDING")
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0] ?? null
  );
}
