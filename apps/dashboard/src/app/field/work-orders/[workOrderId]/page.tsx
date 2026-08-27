import Link from "next/link";
import { notFound } from "next/navigation";

import { StateBadge } from "@/components/ui/StatusBadge";
import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { CoreApiError } from "@/lib/core-api/client";
import { getAcquisitionProgress } from "@/lib/core-api/acquisition-coordination";
import { getAcquisitionReadiness } from "@/lib/core-api/acquisition-connectivity";
import {
  getObservationWorkOrder,
  listReobservationDrafts,
} from "@/lib/core-api/observation-work-orders";
import { getSite } from "@/lib/core-api/sites";
import type { ReobservationDraftView } from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";

import { CopilotPanel } from "../../CopilotPanel";
import { AcquisitionProgressCard } from "../../AcquisitionProgressCard";
import { AcquisitionReadinessCard } from "../../AcquisitionReadinessCard";
import { OperationsSessionFailure } from "../../OperationsSessionFailure";
import { OperationsWorkHeader } from "../../OperationsWorkHeader";
import { WorkOrderActionPanel } from "../../WorkOrderActionPanel";
import { resolveFieldSession } from "../../resolve-session";
import { presentWorkOrder } from "../../work-order-stage";

export const metadata = { title: "현장 작업 · KSI" };

export default async function FieldWorkOrderPage({
  params,
}: {
  params: Promise<{ workOrderId: string }>;
}) {
  const { workOrderId } = await params;
  const next = "/field/work-orders/" + encodeURIComponent(workOrderId);
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
  const [site, drafts, acquisitionProgress, readinessFallback] = await Promise.all([
    getSite(workOrder.siteId).catch(() => null),
    listReobservationDrafts(workOrder.workOrderId).catch(() => []),
    getAcquisitionProgress(workOrder.workOrderId).catch(() => null),
    getAcquisitionReadiness(workOrder.siteId).catch(() => null),
  ]);
  const acquisitionReadiness = acquisitionProgress?.readiness ?? readinessFallback;
  const pendingDraft = latestPendingDraft(drafts);
  const presentation = presentWorkOrder(workOrder.status);
  // WorkOrder status and a successful ProcessingJob alone do not establish
  // evidence completeness. Copilot is available only after Core's derived
  // Analysis Readiness gate explicitly says ready.
  const showCopilot =
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
              <h2 className="text-[18px] font-bold tracking-tight">{presentation.label}</h2>
            </div>
            <StateBadge label={presentation.label} tone={presentation.tone} />
          </div>

          <p className="text-[14px] leading-6 break-keep text-ink-2">{presentation.detail}</p>
          {workOrder.statusReason && (
            <p className="rounded-lg bg-high-bg px-3 py-2 text-[13px] break-keep text-high-ink">
              {workOrder.statusReason}
            </p>
          )}
          {pendingDraft && (
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
          <WorkOrderActionPanel
            workOrderId={workOrder.workOrderId}
            siteId={workOrder.siteId}
            version={workOrder.version}
            presentation={presentation}
            pendingDraft={pendingDraft}
            acquisitionProgress={acquisitionProgress}
          />
        </section>

        <AcquisitionProgressCard progress={acquisitionProgress} />

        <AcquisitionReadinessCard
          readiness={acquisitionReadiness}
          progress={acquisitionProgress}
        />

        {showCopilot && (
          <CopilotPanel siteId={workOrder.siteId} workOrderId={workOrder.workOrderId} />
        )}

        <ResponsiveActionBoundary
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
        </ResponsiveActionBoundary>
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
