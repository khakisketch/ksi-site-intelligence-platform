import Link from "next/link";
import { notFound } from "next/navigation";

import { ExternalSiteResultSummary } from "@/components/external-results/ExternalSiteResultSummary";
import { ResponsiveNotice } from "@/components/responsive/ResponsiveActionBoundary";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { CoreApiError } from "@/lib/core-api/client";
import { getObservationWorkOrder, getObservationWorkOrderOperations, listReobservationDrafts } from "@/lib/core-api/observation-work-orders";
import { getExternalReconstructionContext, listExternalReconstructionSubmissions, resolveExternalWorkOrderExecutionContext } from "@/lib/core-api/external-reconstruction";
import { getExternalRelativeVolumeReport, getSiteExternalRelativeVolumeReport, listSiteExternalVolumeHistory } from "@/lib/core-api/external-result-workflow";
import { isExternalRelativeVolumeReportReference } from "@/lib/external-relative-volume-references";
import { getSite } from "@/lib/core-api/sites";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { formatKoreanDateTime } from "@/lib/datetime";
import { SITE_NAME_UNAVAILABLE, formatWorkAreaSummary, formatWorkAreaTechnicalRefs, indexWorkAreaNames } from "@/lib/work-context-names";
import { resolveFieldSession } from "@/app/field/resolve-session";
import { formatCountKo } from "@/lib/number-format";
import { OperationsSessionFailure } from "@/app/field/OperationsSessionFailure";
import { ExternalReconstructionPanel } from "@/app/field/ExternalReconstructionPanel";
import type { TrustedExternalResultLink } from "@/app/field/ExternalResultWorkflowPanel";
import { WorkOrderOperationsPanel } from "@/app/field/WorkOrderOperationsPanel";
import { OperationsWorkHeader } from "@/app/field/OperationsWorkHeader";
import { deriveExternalWorkOrderStage } from "@/app/field/external-work-order-stage";
import { presentWorkOrder } from "@/app/field/work-order-stage";

export const metadata = { title: "관측 작업 · KSI" };

async function resolveTrustedReportLink(
  siteId: string,
  workOrderId: string,
  organizationId: string,
  workAreaIds: readonly string[],
  reportRef: string,
): Promise<TrustedExternalResultLink | null> {
  if (!isExternalRelativeVolumeReportReference(reportRef)) return null;
  const projection = await getSiteExternalRelativeVolumeReport(siteId, reportRef).catch(() => null);
  const summary = projection?.state === "AVAILABLE" ? projection.result ?? null : null;
  if (
    !summary
    || typeof summary.reportRef !== "string"
    || summary.reportRef !== reportRef
    || typeof summary.reportDigest !== "string"
    || summary.reportDigest.length === 0
    || typeof summary.workAreaId !== "string"
    || !workAreaIds.includes(summary.workAreaId)
    || summary.currentWorkOrderId !== workOrderId
    || summary.baselineWorkOrderId === null
    || summary.sourceWorkOrderId !== summary.baselineWorkOrderId
  ) return null;

  const view = await getExternalRelativeVolumeReport(reportRef).catch(() => null);
  if (!view?.request || !view.report) return null;
  const { request, report } = view;
  const baselineSubject = request?.baseline?.subject;
  const currentSubject = request?.current?.subject;
  const zoneSnapshot = request?.zoneSnapshot;
  const exact = report?.reportId === reportRef
    && report.reportDigest === summary.reportDigest
    && report.requestId === request.requestId
    && report.requestDigest === request.requestDigest
    && request.currentWorkOrderId === workOrderId
    && baselineSubject?.workOrderId === summary.baselineWorkOrderId
    && currentSubject?.workOrderId === workOrderId
    && baselineSubject?.siteId === siteId
    && currentSubject?.siteId === siteId
    && baselineSubject?.organizationId === organizationId
    && currentSubject?.organizationId === organizationId
    && zoneSnapshot?.organizationId === organizationId
    && zoneSnapshot?.siteId === siteId
    && zoneSnapshot?.workAreaId === summary.workAreaId;
  return exact
    ? { reportRef, reportDigest: summary.reportDigest, view }
    : null;
}

async function resolveSuccessorSourceReportRef({
  workOrder,
  binding,
  organizationId,
}: {
  workOrder: Awaited<ReturnType<typeof getObservationWorkOrder>>;
  binding: NonNullable<Awaited<ReturnType<typeof getExternalReconstructionContext>>>["externalPlanningBinding"];
  organizationId: string;
}): Promise<{ reportRef: string; sourceCycleNumber: number } | null> {
  if (
    !binding
    || binding.organizationId !== organizationId
    || binding.siteId !== workOrder.siteId
    || binding.successorWorkOrderId !== workOrder.workOrderId
  ) return null;
  const source = await getObservationWorkOrder(binding.sourceWorkOrderId).catch(() => null);
  if (
    !source
    || source.workOrderId !== binding.sourceWorkOrderId
    || source.siteId !== workOrder.siteId
    || source.organizationId !== organizationId
  ) return null;

  const reportRefs = Array.isArray(source.reportRefs)
    ? source.reportRefs.filter(isExternalRelativeVolumeReportReference)
    : [];
  const matches = await Promise.all(reportRefs.map(async (reportRef) => {
    const trusted = await resolveTrustedReportLink(source.siteId, source.workOrderId, organizationId, source.workAreaIds, reportRef);
    if (!trusted || trusted.reportDigest !== binding.reportDigest) return null;
    const proposals = Array.isArray(trusted.view.proposals) ? trusted.view.proposals : [];
    const proposal = proposals.find(({ proposal, approvalReceipt }) => (
      proposal.proposalRef === binding.proposalId
      && proposal.version === binding.proposalVersion
      && proposal.proposalDigest === binding.proposalDigest
      && proposal.reportRef === reportRef
      && proposal.reportDigest === binding.reportDigest
      && proposal.decisionDigest === binding.decisionDigest
      && approvalReceipt?.successorWorkOrderId === workOrder.workOrderId
    ));
    return proposal ? reportRef : null;
  }));
  const reportRef = matches.find((ref): ref is string => ref !== null);
  return reportRef ? { reportRef, sourceCycleNumber: source.cycleNumber } : null;
}

export default async function FieldWorkOrderPage({ params, searchParams }: {
  params: Promise<{ workOrderId: string }>;
  searchParams: Promise<{ reportRef?: string | string[] }>;
}) {
  const [{ workOrderId }, { reportRef: reportRefParam }] = await Promise.all([params, searchParams]);
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
    listReobservationDrafts(workOrder.workOrderId).catch(() => null),
    getExternalReconstructionContext(workOrder.workOrderId).catch(() => null),
    // 보관 구역 포함 — 과거 작업이 보관된 구역을 가리킬 수 있다.
    listWorkAreas(workOrder.siteId, { includeArchived: true }).catch(() => null),
    listSiteExternalVolumeHistory(workOrder.siteId, { limit: 20 }).catch(() => null),
  ]);
  const externalExecutionContext = resolveExternalWorkOrderExecutionContext(workOrder, externalContext);
  const externalWorkflow = externalExecutionContext === "EXTERNAL_INGRESS" || externalExecutionContext === "EXTERNAL_REOBSERVATION_PLANNING";
  const planningBinding = externalExecutionContext === "EXTERNAL_REOBSERVATION_PLANNING"
    ? externalContext?.externalPlanningBinding ?? null
    : null;
  const reportRef = typeof reportRefParam === "string" ? reportRefParam : null;
  const reportLinkRequested = reportRefParam !== undefined;
  const [initialReport, sourceReport] = await Promise.all([
    reportLinkRequested && reportRef !== null && externalExecutionContext === "EXTERNAL_INGRESS"
      ? resolveTrustedReportLink(workOrder.siteId, workOrder.workOrderId, session.principal.organizationId, workOrder.workAreaIds, reportRef)
      : Promise.resolve(null),
    planningBinding
      ? resolveSuccessorSourceReportRef({ workOrder, binding: planningBinding, organizationId: session.principal.organizationId })
      : Promise.resolve(null),
  ]);
  const reportLinkNotice = reportLinkRequested
    ? reportRef === null || !isExternalRelativeVolumeReportReference(reportRef)
      ? "요청한 비교 결과 주소를 확인하지 못했습니다. 외부 비교 기록에서 결과를 다시 선택하세요."
      : initialReport === null
        ? "요청한 비교 결과를 이 작업에 결속하지 못했습니다. 외부 비교 기록에서 다시 확인하세요."
        : null
    : null;
  const sourceReportHref = planningBinding && sourceReport
    ? `/field/work-orders/${encodeURIComponent(planningBinding.sourceWorkOrderId)}?reportRef=${encodeURIComponent(sourceReport.reportRef)}#external-result`
    : null;
  const t1ToT2 = sourceReport?.sourceCycleNumber === 1 && workOrder.cycleNumber === 2;
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
  const pendingDrafts = (drafts ?? []).filter((draft) => draft.status === "PENDING");
  const unavailableRecords = [drafts === null ? "재관측 제안" : null, history === null ? "보존된 결과 목록" : null].filter(Boolean);
  const areaNameById = indexWorkAreaNames(workAreas?.workAreas ?? []);
  const areaSummary = formatWorkAreaSummary(workOrder.workAreaIds, areaNameById);
  const operationsStateLabel = !operations
    ? "상태 확인 필요"
    : operations.workflowStatus === "CLOSED"
      ? "업무 종료"
      : operations.workflowStatus === "OPEN" ? "운영 중" : "운영 상태 확인 필요";

  return (
    <div className="flex flex-col">
      <OperationsWorkHeader>
        <div className="flex flex-col gap-1">
          <h2 className="break-keep text-[19px] font-bold tracking-tight">{externalWorkflow ? "관측 자료와 검사 확인" : workOrder.name}</h2>
          {externalWorkflow && <p className="break-keep text-[12.5px] text-ink-2">등록된 작업명 · {workOrder.name}</p>}
          <p className="break-keep text-[12.5px] text-ink-2">{site?.name ?? SITE_NAME_UNAVAILABLE} · {areaSummary} · {workOrder.cycleNumber}회차</p>
          <details className="text-[11.5px] text-ink-muted">
          <summary className="tap-target inline-flex cursor-pointer items-center font-semibold">파일 정보</summary>
            <p className="mt-1 break-all">작업 {workOrder.workOrderId} · 현장 {workOrder.siteId} · 구역 {formatWorkAreaTechnicalRefs(workOrder.workAreaIds)}</p>
          </details>
        </div>
      </OperationsWorkHeader>

      <div className="flex flex-col gap-4 p-4 pb-24 lg:p-5">
        <section className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-[12px] font-semibold text-ink-muted">플랫폼 작업 상태</h2>
            <StateBadge label={stage?.label ?? status.label} tone={stage?.tone ?? status.tone} />
          </div>
          <p className="text-[13px] leading-5 text-ink-2">{stage?.detail ?? status.detail}</p>
          {workOrder.statusReason && <p className="rounded-lg bg-high-bg px-3 py-2 text-[13px] text-high-ink">{workOrder.statusReason}</p>}
          {externalExecutionContext === "UNVERIFIED" && <p role="status" className="rounded-lg border border-line bg-sunk px-3 py-2 text-[12.5px] text-ink-2">작업 실행 유형을 확인하지 못했습니다. 관리형 실행 상태나 장비 동작을 표시하지 않습니다.</p>}
          {!externalWorkflow && externalExecutionContext !== "UNVERIFIED" && <p className="rounded-lg border border-line bg-sunk px-3 py-2 text-[12.5px] text-ink-2">이 작업에는 현재 플랫폼이 제공하는 외부 산출물 등록 흐름이 없습니다.</p>}
        </section>

        {externalWorkflow && <ResponsiveNotice action="WORK_ORDERS_WRITE" reason="노트북에서 같은 계정으로 이 작업 상세를 열어 담당·기한·업무 종료와 산출물 등록을 이어가세요." />}

        {reportLinkNotice && <p role="status" className="rounded-lg border border-line bg-sunk px-3 py-2 text-[12.5px] leading-5 text-ink-2">{reportLinkNotice} <Link className="font-semibold text-accent-text underline underline-offset-2" href={`/sites/${encodeURIComponent(workOrder.siteId)}/observations`}>외부 비교 기록</Link></p>}

        {planningBinding && <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-sunk px-4 py-3" aria-label="다음 관측 안내">
          <div className="min-w-0 flex-1">
            <h2 className="text-[13px] font-bold">다음 관측 준비</h2>
            <p className="mt-1 text-[12.5px] leading-5 text-ink-2">{t1ToT2 ? "산출물 제출을 마친 뒤 변화 분석 화면에서 기준 자료→비교 자료 분석을 요청하세요." : "산출물 제출을 마친 뒤 변화 분석 화면에서 기준·현재 관측을 선택해 분석을 요청하세요."}</p>
            {!sourceReportHref && <p role="status" className="mt-1 text-[12px] text-ink-muted">원본 결과와 승인 제안 연결을 확인할 수 없습니다.</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            {sourceReportHref && <Link className="btn" href={sourceReportHref}>원본 결과·제안 보기</Link>}
            <Link className="btn" href={`/sites/${encodeURIComponent(workOrder.siteId)}/analysis#new-analysis-request`}>변화 분석 열기</Link>
            <Link className="btn" href={`/sites/${encodeURIComponent(workOrder.siteId)}/observations/new?repeatWorkOrderId=${encodeURIComponent(workOrder.workOrderId)}`}>이 범위로 관측 자료 등록</Link>
          </div>
        </section>}

        {(externalWorkflow || latestItem || pendingDrafts.length > 0) && (
          <nav aria-label="다음 행동" className="flex flex-wrap gap-2 rounded-lg border border-line bg-sunk px-4 py-3">
            {externalWorkflow && <Link className="btn" href="#external-submissions">{workflowClosed ? "자료 검사 기록으로 이동" : "자료 등록·검사 기록으로 이동"}</Link>}
            {latestItem && <Link className="btn" href="#work-order-result">보존된 결과로 이동</Link>}
            {pendingDrafts.length > 0 && <Link className="btn" href="#reobservation-drafts">재관측 제안으로 이동</Link>}
            {externalWorkflow && <Link className="btn" href="#work-operations">작업 운영으로 이동</Link>}
          </nav>
        )}
        {unavailableRecords.length > 0 && <ErrorState tone="idle" message={`${unavailableRecords.join("·")} 확인 불가`} detail="해당 기록이 없다는 뜻이 아닙니다. 접근 권한과 서버 상태를 확인한 뒤 다시 시도하세요." retryable />}

        {externalWorkflow && <ExternalReconstructionPanel
          workOrderId={workOrder.workOrderId}
          siteId={workOrder.siteId}
          expectedEpochId={externalContext?.expectedEpochId ?? null}
          canWrite={session.principal.permissions.includes("SITES_WRITE")}
          permissions={session.principal.permissions}
          requiresCaptureInterval={externalExecutionContext === "EXTERNAL_INGRESS"}
          newIntentAllowed={!workflowClosed}
          initialReport={initialReport ?? undefined}
          workAreaNames={Object.fromEntries(areaNameById)}
        />}

        {pendingDrafts.length > 0 && (
          <section id="reobservation-drafts" className="flex scroll-mt-5 flex-col gap-2 rounded-lg border border-line bg-surface p-4">
            <h2 className="text-[14px] font-bold">재관측 제안</h2>
            <p className="text-[12.5px] text-ink-2">승인 대기 초안은 승인 가능 여부를 추정하지 않고 표시합니다. 제안 생성과 결정은 외부 비교 화면에서 진행합니다.</p>
            {externalWorkflow && <Link className="w-fit text-[12.5px] font-semibold text-accent-text underline underline-offset-2" href={initialReport ? "#external-result" : "#external-volume"}>{initialReport ? "결과와 제안 결정으로 이동" : "비교 요청·제안 상태로 이동"}</Link>}
            <ul className="divide-y divide-line">
              {pendingDrafts.map((draft) => <li key={draft.draftId} className="py-2 text-[12.5px]"><p className="font-semibold">{draft.proposedEffort}</p><p className="mt-1 text-ink-muted">{formatCountKo(draft.targetRegionRefs.length)}개 구역 · 만료 {formatKoreanDateTime(draft.expiresAt, { dateStyle: "medium", timeStyle: "short" })}</p></li>)}
            </ul>
          </section>
        )}

        {latestItem ? <div id="work-order-result" className="scroll-mt-5">{projection ? <ExternalSiteResultSummary
          externalResult={projection}
          workAreaName={areaNameById.get(latestItem.result?.workAreaId ?? "") ?? null}
        /> : <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] text-ink-2">보존된 외부 비교 결과 상세를 확인할 수 없습니다.</p>}</div> : null}

        {externalWorkflow && <details id="work-operations" className="scroll-mt-5 rounded-xl border border-line bg-surface">
          <summary className="tap-target flex cursor-pointer items-center justify-between gap-3 px-4 py-3">
            <span className="text-[15px] font-bold">작업 운영 · {operationsStateLabel}</span>
            <span className="flex items-center gap-2 text-[12px] font-semibold text-ink-2">담당·기한·업무 종료<svg aria-hidden="true" className="size-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="m6 9 6 6 6-6" /></svg></span>
          </summary>
          <div className="border-t border-line px-4 py-4">
            <WorkOrderOperationsPanel
              workOrderId={workOrder.workOrderId}
              principalId={session.principal.principalId}
              initialOperations={operations}
              canWrite={session.principal.permissions.includes("WORK_ORDERS_WRITE")}
            />
          </div>
        </details>}

        <div className="flex flex-wrap gap-2">
          <Link href={`/sites/${encodeURIComponent(workOrder.siteId)}`} className="btn">현장으로</Link>
          <Link href="/field" className="btn">작업 큐</Link>
        </div>
      </div>
    </div>
  );
}
