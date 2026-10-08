import Link from "next/link";
import { notFound } from "next/navigation";

import { ExternalSiteResultSummary } from "@/components/external-results/ExternalSiteResultSummary";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { CoreApiError } from "@/lib/core-api/client";
import { getObservationWorkOrder, getObservationWorkOrderOperations, listReobservationDrafts } from "@/lib/core-api/observation-work-orders";
import { getExternalReconstructionContext, listExternalReconstructionSubmissions, resolveExternalWorkOrderExecutionContext } from "@/lib/core-api/external-reconstruction";
import { getSiteExternalRelativeVolumeReport, listSiteExternalVolumeHistory } from "@/lib/core-api/external-result-workflow";
import { getSite } from "@/lib/core-api/sites";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { resolveFieldSession } from "@/app/field/resolve-session";
import { OperationsSessionFailure } from "@/app/field/OperationsSessionFailure";
import { ExternalReconstructionPanel } from "@/app/field/ExternalReconstructionPanel";
import { WorkOrderOperationsPanel } from "@/app/field/WorkOrderOperationsPanel";
import { OperationsWorkHeader } from "@/app/field/OperationsWorkHeader";
import { deriveExternalWorkOrderStage } from "@/app/field/external-work-order-stage";
import { presentWorkOrder } from "@/app/field/work-order-stage";

export const metadata = { title: "관측 작업 · KSI" };

export default async function FieldWorkOrderPage({ params }: { params: Promise<{ workOrderId: string }> }) {
  const { workOrderId } = await params;
  const session = await resolveFieldSession();
  if (session.kind === "blocked") return <OperationsSessionFailure verdict={session.verdict} next={`/field/work-orders/${encodeURIComponent(workOrderId)}`} />;

  let workOrder;
  try {
    workOrder = await getObservationWorkOrder(workOrderId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    return <div className="p-4 sm:p-5"><ErrorState message="관측 작업 원장을 불러오지 못했습니다." retryable /></div>;
  }

  const [site, drafts, externalContext, workAreas, history] = await Promise.all([
    getSite(workOrder.siteId).catch(() => null),
    listReobservationDrafts(workOrder.workOrderId).catch(() => []),
    getExternalReconstructionContext(workOrder.workOrderId).catch(() => null),
    listWorkAreas(workOrder.siteId).catch(() => null),
    listSiteExternalVolumeHistory(workOrder.siteId, { limit: 20 }).catch(() => null),
  ]);
  const externalExecutionContext = resolveExternalWorkOrderExecutionContext(workOrder, externalContext);
  const externalWorkflow = externalExecutionContext === "EXTERNAL_INGRESS" || externalExecutionContext === "EXTERNAL_REOBSERVATION_PLANNING";
  const operations = externalWorkflow
    ? await getObservationWorkOrderOperations(workOrder.workOrderId).catch(() => null)
    : null;
  const workflowClosed = operations?.workflowStatus === "CLOSED";
  const submissions = externalWorkflow
    ? await listExternalReconstructionSubmissions(workOrder.workOrderId).catch(() => [])
    : [];
  const latestItem = history?.items.find((item) => item.state === "AVAILABLE" && item.result?.currentWorkOrderId === workOrder.workOrderId);
  const projection = latestItem
    ? await getSiteExternalRelativeVolumeReport(workOrder.siteId, latestItem.reportRef).catch(() => null)
    : null;
  const ownResult = latestItem?.result ?? null;
  const stage = externalWorkflow
    ? deriveExternalWorkOrderStage({
        planningOnly: externalExecutionContext === "EXTERNAL_REOBSERVATION_PLANNING",
        workflowClosed,
        sealedSubmissionCount: submissions.filter((item) => item.state === "SEALED").length,
        registeredSubmissionCount: submissions.filter((item) => item.state === "REGISTERED").length,
        latestResult: ownResult,
      })
    : null;
  const status = presentWorkOrder(workOrder.status, workOrder.executionMode);
  const pendingDrafts = drafts.filter((draft) => draft.status === "PENDING");
  const areaNameById = new Map((workAreas?.workAreas ?? []).map((area) => [area.workAreaId, area.name]));

  return (
    <div className="flex flex-col">
      <OperationsWorkHeader>
        <div className="flex flex-col gap-1">
          <h2 className="break-keep text-[19px] font-bold tracking-tight">{workOrder.name}</h2>
          <p className="break-keep text-[12.5px] text-ink-2">{site?.name ?? "현장"} · {workOrder.workAreaIds.length}개 구역 · {workOrder.cycleNumber}회차</p>
        </div>
      </OperationsWorkHeader>

      <div className="flex flex-col gap-4 p-4 lg:p-5">
        <section className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div><span className="text-[12px] font-semibold text-ink-muted">플랫폼 작업 상태</span><h2 className="mt-1 text-[18px] font-bold">{stage?.label ?? status.label}</h2></div>
            <StateBadge label={stage?.label ?? status.label} tone={stage?.tone ?? status.tone} />
          </div>
          <p className="text-[13px] leading-5 text-ink-2">{stage?.detail ?? status.detail}</p>
          {workOrder.statusReason && <p className="rounded-lg bg-high-bg px-3 py-2 text-[13px] text-high-ink">{workOrder.statusReason}</p>}
          {externalExecutionContext === "UNVERIFIED" && <p role="status" className="rounded-lg border border-line bg-sunk px-3 py-2 text-[12.5px] text-ink-2">작업 실행 유형을 확인하지 못했습니다. 관리형 실행 상태나 장비 동작을 표시하지 않습니다.</p>}
          {!externalWorkflow && externalExecutionContext !== "UNVERIFIED" && <p className="rounded-lg border border-line bg-sunk px-3 py-2 text-[12.5px] text-ink-2">이 작업에는 현재 플랫폼이 제공하는 외부 산출물 등록 흐름이 없습니다.</p>}
        </section>

        {externalWorkflow && <WorkOrderOperationsPanel
          workOrderId={workOrder.workOrderId}
          principalId={session.principal.principalId}
          initialOperations={operations}
          canWrite={session.principal.permissions.includes("WORK_ORDERS_WRITE")}
        />}

        {externalWorkflow && <ExternalReconstructionPanel
          workOrderId={workOrder.workOrderId}
          siteId={workOrder.siteId}
          expectedEpochId={externalContext?.expectedEpochId ?? null}
          canWrite={session.principal.permissions.includes("SITES_WRITE")}
          permissions={session.principal.permissions}
          requiresCaptureInterval={externalExecutionContext === "EXTERNAL_INGRESS"}
          newIntentAllowed={!workflowClosed}
        />}

        {pendingDrafts.length > 0 && (
          <section className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4">
            <h2 className="text-[14px] font-bold">재관측 제안</h2>
            <p className="text-[12.5px] text-ink-2">승인 대기 초안은 승인 가능 여부를 추정하지 않고 표시합니다. 제안 생성과 결정은 외부 결과 화면에서 진행합니다.</p>
            <ul className="divide-y divide-line">
              {pendingDrafts.map((draft) => <li key={draft.draftId} className="py-2 text-[12.5px]"><p className="font-semibold">{draft.proposedEffort}</p><p className="mt-1 text-ink-muted">{draft.targetRegionRefs.length}개 구역 · {draft.expiresAt}</p></li>)}
            </ul>
          </section>
        )}

        {latestItem ? projection ? <ExternalSiteResultSummary
          externalResult={projection}
          workAreaName={areaNameById.get(latestItem.result?.workAreaId ?? "") ?? null}
        /> : <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] text-ink-2">보존된 외부 결과 상세를 확인할 수 없습니다.</p> : null}

        <div className="flex flex-wrap gap-2">
          <Link href={`/sites/${encodeURIComponent(workOrder.siteId)}`} className="btn">현장으로</Link>
          <Link href="/field" className="btn">작업 큐</Link>
        </div>
      </div>
    </div>
  );
}
