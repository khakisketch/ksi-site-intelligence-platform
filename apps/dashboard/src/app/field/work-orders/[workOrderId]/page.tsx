import Link from "next/link";
import { notFound } from "next/navigation";

import { ExternalSiteResultSummary } from "@/components/external-results/ExternalSiteResultSummary";
import { ResponsiveNotice } from "@/components/responsive/ResponsiveActionBoundary";
import { Disclosure } from "@/components/ui/Disclosure";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { CoreApiError } from "@/lib/core-api/client";
import { whoAmI } from "@/lib/core-api/auth";
import { continuityFingerprint } from "@/lib/core-api/work-order-continuity";
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
import { StepIndicator } from "@/components/ui/StepIndicator";
import { deriveExternalWorkOrderStage, EXTERNAL_STAGE_STEPS, externalStageStepIndex } from "@/app/field/external-work-order-stage";
import { presentWorkOrder } from "@/app/field/work-order-stage";
import { resolveWorkOrderContinuation } from "@/lib/operator-journey";

export const metadata = { title: "작업 · KSI" };

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
    return <div className="p-4 sm:p-5"><ErrorState message="작업 원장을 불러오지 못했습니다." retryable /></div>;
  }

  const [site, drafts, externalContext, workAreas, history, identity] = await Promise.all([
    getSite(workOrder.siteId).catch(() => null),
    listReobservationDrafts(workOrder.workOrderId).catch(() => null),
    getExternalReconstructionContext(workOrder.workOrderId).catch(() => null),
    // 보관 구역 포함 — 과거 작업이 보관된 구역을 가리킬 수 있다.
    listWorkAreas(workOrder.siteId, { includeArchived: true }).catch(() => null),
    listSiteExternalVolumeHistory(workOrder.siteId, { limit: 20 }).catch(() => null),
    // 사용 결정 재시도의 계정 연속성 비교값 — 서버에서 확인한 두 식별자의
    // 비교값일 뿐 자격 증명이나 인가가 아니다. 신원 부재면 새 요청은 막히고
    // 이미 동결된 재시도만 같은 키로 이어간다.
    whoAmI().catch(() => null),
  ]);
  // Core는 principal에 경로 안전 형식을 강제하지 않는다. 서버에서 정확한 두
  // 식별자의 ASCII 비교값을 만들고, 원문 식별자는 클라이언트에 내보내지 않는다.
  const accountIdentity = (() => {
    const fingerprint = continuityFingerprint(identity);
    const permissions = identity?.permissions;
    const permissionsVerified = Array.isArray(permissions) && permissions.every((permission) => typeof permission === "string");
    return fingerprint && permissionsVerified ? { fingerprint } : null;
  })();
  // OIDC-first 배포 경계: registry 발급(scoped) 운영자 신원에는 Core가 기존
  // 사용 결정 경로(POST/GET use-decisions)를 allowlist 밖으로 닫는다. 이 화면이
  // 그 버튼을 그대로 내놓으면 확정 403만 만든다. 신원 출처(registryScoped)는
  // 서버가 확인한 사실이며 권한 추론이 아니다. 모호한 경우(값 없음/LEGACY)는
  // 닫힘으로 표시하지 않고 기존 동작을 유지한다.
  const legacyDecisionClosed = identity?.registryScoped === true;
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
  // 목록 실패를 빈 목록으로 바꾸지 않는다 — 실패는 모름으로 둔다.
  const submissionsResult = externalWorkflow
    ? await listExternalReconstructionSubmissions(workOrder.workOrderId).then(
      (items) => ({ ok: true as const, items }),
      () => ({ ok: false as const, items: [] as Awaited<ReturnType<typeof listExternalReconstructionSubmissions>> }),
    )
    : { ok: true as const, items: [] as Awaited<ReturnType<typeof listExternalReconstructionSubmissions>> };
  const submissions = submissionsResult.items;
  const submissionsKnown = submissionsResult.ok;
  const latestItem = history?.items.find((item) => item.state === "AVAILABLE" && item.result?.currentWorkOrderId === workOrder.workOrderId);
  const projection = latestItem
    ? await getSiteExternalRelativeVolumeReport(workOrder.siteId, latestItem.reportRef).catch(() => null)
    : null;
  const ownResult = latestItem?.result ?? null;
  // 단일 현행 활성 구역일 때만 다음 확인 범위를 미리 좁힌다. 여러 구역·보관·
  // 모르는 연결이면 좁히지 않는다(목록에서 직접 고른다). 추가 조회 없음.
  const continuation = !planningBinding && externalExecutionContext === "EXTERNAL_INGRESS"
    ? resolveWorkOrderContinuation({
      areas: (workAreas?.workAreas ?? []).map((area) => ({ workAreaId: area.workAreaId, name: area.name, status: area.status })),
      workAreaIds: workOrder.workAreaIds,
    })
    : null;
  const hasRetainedSubmissions = submissionsKnown && submissions.length > 0;
  const submissionsUnknown = externalWorkflow && !submissionsKnown;
  const baseStage = externalWorkflow
    ? deriveExternalWorkOrderStage({
        planningOnly: externalExecutionContext === "EXTERNAL_REOBSERVATION_PLANNING",
        workflowClosed,
        sealedSubmissionCount: submissions.filter((item) => item.state === "SEALED").length,
        registeredSubmissionCount: submissions.filter((item) => item.state === "REGISTERED").length,
        latestResult: ownResult,
      })
    : null;
  // 목록 실패를 빈 목록으로 보지 않는다 — 모름이면 등록 준비 단계로 속이지 않고
  // 목록 재확인을 안내한다. 결과·종료가 이미 확정된 상태는 그대로 둔다.
  // anchor는 화면 내 실제 이동 대상과 같은 값만 둔다 — 상태 배너 아래 이동
  // 링크가 그 앵커를 그대로 쓴다.
  const stage = submissionsUnknown && !workflowClosed && !ownResult
    ? {
      stage: "REGISTER" as const,
      label: "등록 상태 확인 필요",
      detail: "산출물 등록 목록을 불러오지 못했습니다. 아래 이동에서 목록 다시 시도로 복구하세요. 목록이 복구돼도 상단 상태는 이전 정보일 수 있습니다. 화면을 새로고침하면 미제출 입력·파일 선택·동결된 요청이 사라지니, 진행 중인 입력·재시도가 있으면 먼저 마무리하세요.",
      tone: "warning" as const,
      anchor: "external-submissions",
    }
    : baseStage;
  // 상태 배너의 다음 행동은 화면 내 이동과 같은 문구·같은 앵커를 쓴다.
  // deriveExternalWorkOrderStage가 돌려주는 anchor는 지금까지 배너에서
  // 버려졌고, 사용자는 다음 기록이 화면 어디에 있는지 직접 찾아야 했다.
  const stageAnchorLabel =
    stage?.anchor === "external-submissions"
      ? workflowClosed ? "자료 검사 기록으로 이동" : "자료 등록·검사 기록으로 이동"
      : stage?.anchor === "external-volume"
        ? "비교 요청·제안 상태로 이동"
        : stage?.anchor === "external-result"
          ? "결과와 제안 결정으로 이동"
          : null;
  const siteReturnHref = continuation?.workAreaId
    ? `/sites/${encodeURIComponent(workOrder.siteId)}?workAreaId=${encodeURIComponent(continuation.workAreaId)}`
    : `/sites/${encodeURIComponent(workOrder.siteId)}`;
  const status = presentWorkOrder(workOrder.status, workOrder.executionMode);
  const pendingDrafts = (drafts ?? []).filter((draft) => draft.status === "PENDING");
  const unavailableRecords = [drafts === null ? "재관측 제안" : null, history === null ? "보존된 결과 목록" : null].filter(Boolean);
  const areaNameById = indexWorkAreaNames(workAreas?.workAreas ?? []);
  const areaSummary = formatWorkAreaSummary(workOrder.workAreaIds, areaNameById);
  const canViewSite = site !== null && session.principal.permissions.includes("SITES_READ");
  const canOperate = session.principal.permissions.includes("WORK_ORDERS_WRITE");
  const canRegister = session.principal.permissions.includes("SITES_WRITE");
  // 화면 폭 안내는 권한을 주지 않는다. 조회 전용이거나 일부 쓰기 권한만 있는
  // 계정에 노트북으로 옮기면 모든 행동을 할 수 있다고 안내하지 않는다.
  const compactWorkGuidance = canOperate && canRegister
    ? "노트북에서 같은 계정으로 이 작업 상세를 열어 담당·기한·작업 종료와 산출물 등록을 이어가세요."
    : canRegister
      ? "노트북에서 같은 계정으로 이 작업 상세를 열어 산출물 등록을 이어가세요."
      : "노트북에서 같은 계정으로 이 작업 상세를 열어 담당·기한 설정과 작업 종료를 이어가세요.";

  return (
    <div className="flex flex-col">
      <OperationsWorkHeader>
        <div className="flex flex-col gap-1">
          <h2 className="break-keep text-title font-bold tracking-tight">{externalWorkflow ? "관측 자료와 검사 확인" : workOrder.name}</h2>
          {externalWorkflow && <p className="break-keep text-caption text-ink-2">등록된 작업명 · {workOrder.name}</p>}
          <p className="break-keep text-caption text-ink-2">{site?.name ?? SITE_NAME_UNAVAILABLE} · {areaSummary} · {workOrder.cycleNumber}회차</p>
          {canViewSite && <Link href={`/sites/${encodeURIComponent(workOrder.siteId)}?panel=intake`} className="btn btn-sm w-fit">공간의 등록 진행 보기</Link>}
          <Disclosure label="식별 상세" className="text-ink-muted">
            <p className="mt-1 break-all">작업 {workOrder.workOrderId} · 현장 {workOrder.siteId} · 구역 {formatWorkAreaTechnicalRefs(workOrder.workAreaIds)}</p>
          </Disclosure>
        </div>
      </OperationsWorkHeader>

      <div className="flex flex-col gap-4 p-4 pb-24 lg:p-5">
        {/* 상세에서는 전역 업무 탭을 다시 내지 않는다 — 상단의 뒤로가기와 아래의
            목록 링크가 돌아가는 길이고, 이 화면의 첫 줄은 이 작업의 진행 상태다. */}
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-caption font-semibold text-ink-muted">플랫폼 작업 상태</h2>
            <StateBadge label={stage?.label ?? status.label} tone={stage?.tone ?? status.tone} />
          </div>
          {externalWorkflow && stage && (
            <StepIndicator
              steps={EXTERNAL_STAGE_STEPS}
              current={submissionsUnknown ? undefined : externalStageStepIndex(stage.stage) ?? undefined}
              label="작업 진행 순서"
              align="start"
            />
          )}
          <p className="max-w-[72ch] text-body text-ink-2">{stage?.detail ?? status.detail}</p>
          {stage?.anchor && stageAnchorLabel && (
            <Link href={`#${stage.anchor}`} className="btn btn-primary w-fit">
              {stageAnchorLabel}
            </Link>
          )}
          {workOrder.statusReason && <p className="rounded-lg bg-high-bg px-3 py-2 text-body text-high-ink">{workOrder.statusReason}</p>}
          {externalExecutionContext === "UNVERIFIED" && <p role="status" className="rounded-lg border border-line bg-sunk px-3 py-2 text-caption text-ink-2">작업 실행 유형을 확인하지 못했습니다. 관리형 실행 상태나 장비 동작을 표시하지 않습니다.</p>}
          {!externalWorkflow && externalExecutionContext !== "UNVERIFIED" && <p className="rounded-lg border border-line bg-sunk px-3 py-2 text-caption text-ink-2">이 작업에는 현재 플랫폼이 제공하는 외부 산출물 등록 흐름이 없습니다.</p>}
          {!planningBinding && externalExecutionContext === "EXTERNAL_INGRESS" && hasRetainedSubmissions && continuation && (() => {
            const sitePath = `/sites/${encodeURIComponent(workOrder.siteId)}`;
            const catalogHref = continuation.workAreaId
              ? `${sitePath}?panel=materials&workAreaId=${encodeURIComponent(continuation.workAreaId)}`
              : `${sitePath}?panel=materials`;
            const analysisHref = continuation.workAreaId
              ? `${sitePath}/analysis?request=new&workAreaId=${encodeURIComponent(continuation.workAreaId)}&currentWorkOrderId=${encodeURIComponent(workOrder.workOrderId)}#new-analysis-request`
              : `${sitePath}/analysis?request=new#new-analysis-request`;
            return <section className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3" aria-label="등록 자료 다음 확인">
              <div className="min-w-0 flex-1">
                <h2 className="text-body font-bold">등록 자료 다음 확인</h2>
                <p className="mt-1 text-caption leading-5 text-ink-2">
                  {continuation.workAreaId
                    ? "파일 검사 결과를 확인한 뒤 분석을 열어 비교 조건을 확인하세요. 분석에 사용할 수 있는 자료인지는 해당 화면에서 다시 확인합니다."
                    : "이 작업은 여러 구역에 걸쳐 있어 구역을 자동으로 고르지 않았습니다. 목록에서 구역과 관측을 직접 선택하세요."}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Link className="btn" href={catalogHref}>등록 자료 목록 보기</Link>
                <Link className="btn" href={analysisHref}>변화 분석에서 비교하기</Link>
              </div>
            </section>;
          })()}
        </section>

        {externalWorkflow && (canOperate || canRegister) && <ResponsiveNotice action="WORK_ORDERS_WRITE" reason={compactWorkGuidance} />}

        {reportLinkNotice && <InlineNotice>{reportLinkNotice} <Link className="font-semibold text-accent-text underline underline-offset-2" href={`/sites/${encodeURIComponent(workOrder.siteId)}/observations`}>외부 비교 기록</Link></InlineNotice>}

        {planningBinding && <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-sunk px-4 py-3" aria-label="다음 관측 안내">
          <div className="min-w-0 flex-1">
            <h2 className="text-body font-bold">다음 관측 준비</h2>
            <p className="mt-1 text-caption leading-5 text-ink-2">{t1ToT2 ? "산출물 제출을 마친 뒤 변화 분석 화면에서 기준 자료→비교 자료 분석을 요청하세요." : "산출물 제출을 마친 뒤 변화 분석 화면에서 기준·현재 관측을 선택해 분석을 요청하세요."}</p>
            {!sourceReportHref && <p role="status" className="mt-1 text-caption text-ink-muted">원본 결과와 승인 제안 연결을 확인할 수 없습니다.</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            {sourceReportHref && <Link className="btn" href={sourceReportHref}>원본 결과·제안 보기</Link>}
            <Link className="btn" href={`/sites/${encodeURIComponent(workOrder.siteId)}/analysis?request=new#new-analysis-request`}>변화 분석 열기</Link>
            <Link className="btn" href={`/sites/${encodeURIComponent(workOrder.siteId)}/observations/new?repeatWorkOrderId=${encodeURIComponent(workOrder.workOrderId)}`}>이 범위로 관측 자료 등록</Link>
          </div>
        </section>}

        {(externalWorkflow || latestItem || pendingDrafts.length > 0) && (
          <nav aria-label="작업 내 이동" className="flex flex-wrap gap-x-4 gap-y-1 text-caption font-semibold text-ink-2">
            {externalWorkflow && stage?.anchor !== "external-submissions" && <Link className="tap-target hover:underline" href="#external-submissions">{workflowClosed ? "자료 검사 기록으로 이동" : "자료 등록·검사 기록으로 이동"}</Link>}
            {latestItem && <Link className="tap-target hover:underline" href="#work-order-result">보존된 결과로 이동</Link>}
            {pendingDrafts.length > 0 && <Link className="tap-target hover:underline" href="#reobservation-drafts">재관측 제안으로 이동</Link>}
            {externalWorkflow && <Link className="tap-target hover:underline" href="#work-operations">작업 운영으로 이동</Link>}
          </nav>
        )}
        {unavailableRecords.length > 0 && <ErrorState tone="idle" message={`${unavailableRecords.join("·")} 확인 불가`} detail="해당 기록이 없다는 뜻이 아닙니다. 접근 권한과 서버 상태를 확인한 뒤 다시 시도하세요." retryable />}

        {externalWorkflow && <ExternalReconstructionPanel
          workOrderId={workOrder.workOrderId}
          siteId={workOrder.siteId}
          expectedEpochId={externalContext?.expectedEpochId ?? null}
          canWrite={canRegister}
          permissions={session.principal.permissions}
          requiresCaptureInterval={externalExecutionContext === "EXTERNAL_INGRESS"}
          newIntentAllowed={!workflowClosed}
          initialReport={initialReport ?? undefined}
          workAreaNames={Object.fromEntries(areaNameById)}
          accountIdentity={accountIdentity}
          legacyDecisionClosed={legacyDecisionClosed}
        />}

        {pendingDrafts.length > 0 && (
          <section id="reobservation-drafts" className="flex scroll-mt-5 flex-col gap-2 rounded-lg border border-line bg-surface p-4">
            <h2 className="text-lead font-bold">재관측 제안</h2>
            <p className="text-caption text-ink-2">승인 대기 초안은 승인 가능 여부를 추정하지 않고 표시합니다. 제안 생성과 결정은 외부 비교 화면에서 진행합니다.</p>
            {externalWorkflow && <Link className="w-fit text-caption font-semibold text-accent-text underline underline-offset-2" href={initialReport ? "#external-result" : "#external-volume"}>{initialReport ? "결과와 제안 결정으로 이동" : "비교 요청·제안 상태로 이동"}</Link>}
            <ul className="divide-y divide-line">
              {pendingDrafts.map((draft) => <li key={draft.draftId} className="py-2 text-caption"><p className="font-semibold">{draft.proposedEffort}</p><p className="mt-1 text-ink-muted">{formatCountKo(draft.targetRegionRefs.length)}개 구역 · 만료 {formatKoreanDateTime(draft.expiresAt, { dateStyle: "medium", timeStyle: "short" })}</p></li>)}
            </ul>
          </section>
        )}

        {latestItem ? <div id="work-order-result" className="scroll-mt-5">{projection ? <ExternalSiteResultSummary
          externalResult={projection}
          workAreaName={areaNameById.get(latestItem.result?.workAreaId ?? "") ?? null}
        /> : <p className="rounded-lg border border-line bg-surface px-4 py-3 text-caption text-ink-2">보존된 외부 비교 결과 상세를 확인할 수 없습니다.</p>}</div> : null}

        {externalWorkflow && <section id="work-operations" className="scroll-mt-5 rounded-xl border border-line bg-surface p-4" aria-label="작업 운영">
          <WorkOrderOperationsPanel
            workOrderId={workOrder.workOrderId}
            principalId={session.principal.principalId}
            initialOperations={operations}
            canWrite={canOperate}
            accountIdentity={accountIdentity}
          />
        </section>}

        <div className="flex flex-wrap gap-2">
          <Link href={siteReturnHref} className="btn">현장으로</Link>
          <Link href="/field" className="btn">작업 목록</Link>
        </div>
      </div>
    </div>
  );
}
