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
  resolveExternalWorkOrderExecutionContext,
} from "@/lib/core-api/external-reconstruction";
import { getExternalRelativeVolumeReport } from "@/lib/core-api/external-result-workflow";
import { getSite } from "@/lib/core-api/sites";
import { getSiteWorkspace } from "@/lib/core-api/site-workspace";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import type { ReobservationDraftView } from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";
import { isExternalRelativeVolumeReportReference } from "@/lib/external-relative-volume-references";

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
  const reportRef = isExternalRelativeVolumeReportReference(requestedReportRef)
    ? requestedReportRef
    : null;
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
  const [site, drafts, acquisitionProgress, readinessFallback, externalContext, resultWorkspace, exactReport, workAreas] = await Promise.all([
    getSite(workOrder.siteId).catch(() => null),
    listReobservationDrafts(workOrder.workOrderId).catch(() => []),
    getAcquisitionProgress(workOrder.workOrderId).catch(() => null),
    getAcquisitionReadiness(workOrder.siteId).catch(() => null),
    getExternalReconstructionContext(workOrder.workOrderId).catch(() => null),
    reportRef ? getSiteWorkspace(workOrder.siteId).catch(() => null) : Promise.resolve(null),
    reportRef ? getExternalRelativeVolumeReport(reportRef).catch(() => null) : Promise.resolve(null),
    reportRef ? listWorkAreas(workOrder.siteId).catch(() => null) : Promise.resolve(null),
  ]);
  let initialReport: TrustedExternalResultLink | undefined;
  let reportLinkNotice: string | null = null;
  if (requestedReportRef && !reportRef) {
    reportLinkNotice = "열려는 비교 결과 주소가 올바르지 않습니다. 현장 결과 목록에서 다시 열어 주세요.";
  } else if (reportRef) {
    const summary = resultWorkspace?.externalResult.state === "AVAILABLE"
      ? resultWorkspace.externalResult.result ?? null
      : null;
    if (summary !== null && exactReport !== null &&
      summary.currentWorkOrderId === workOrder.workOrderId &&
      summary.reportRef === reportRef &&
      exactReport.request.currentWorkOrderId === workOrder.workOrderId &&
      exactReport.report.reportId === reportRef &&
      exactReport.report.reportDigest === summary.reportDigest) {
      initialReport = {
        reportRef,
        reportDigest: summary.reportDigest,
        view: exactReport,
        workAreaName: workAreas?.workAreas.find(
          (area) => area.workAreaId === exactReport.request.zoneSnapshot.workAreaId,
        )?.name ?? null,
      };
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
  const cardPresentation = workflowClosed
    ? {
        label: "업무 종료",
        detail: "이 작업은 종료되었습니다. 새 산출물 등록과 비교·검토 요청은 시작할 수 없으며, 이미 등록한 파일과 결과는 계속 확인할 수 있습니다.",
        tone: "neutral" as const,
      }
    : planningOnly
    ? {
        label: "승인된 재관측 산출물 등록",
        detail: "승인된 재관측에 필요한 산출물을 등록하세요. 이 작업에서는 비행이나 장비를 실행하지 않습니다.",
        tone: "progress" as const,
      }
    : externalIngress
      ? {
          label: "외부 산출물 등록 준비",
          detail: "촬영 시각과 재구성 정보를 확인한 뒤 산출물을 등록하세요. 비행이나 장비 실행은 이 작업에서 시작하지 않습니다.",
          tone: "progress" as const,
        }
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
