import Link from "next/link";
import { notFound } from "next/navigation";

import { StateBadge } from "@/components/ui/StatusBadge";
import { CoreApiError } from "@/lib/core-api/client";
import {
  getObservationWorkOrder,
  listReobservationDrafts,
} from "@/lib/core-api/observation-work-orders";
import { getSite } from "@/lib/core-api/sites";
import type { ReobservationDraftView } from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";

import { CopilotPanel } from "../../CopilotPanel";
import { FieldBlocked, FieldHeader, FieldInlineLogin } from "../../FieldShell";
import { WorkOrderActionPanel } from "../../WorkOrderActionPanel";
import { resolveFieldSession } from "../../resolve-session";
import { presentWorkOrder } from "../../work-order-stage";

export const metadata = { title: "현장 작업 · KSI" };

const STEP_LABELS = ["준비", "전달", "수집", "분석", "결과"] as const;

export default async function FieldWorkOrderPage({
  params,
}: {
  params: Promise<{ workOrderId: string }>;
}) {
  const { workOrderId } = await params;
  const next = "/field/work-orders/" + encodeURIComponent(workOrderId);
  const session = await resolveFieldSession();
  if (session.kind === "blocked") {
    return session.verdict.kind === "login" ? (
      <FieldInlineLogin next={next} notice={session.verdict.notice} />
    ) : (
      <FieldBlocked message={session.verdict.message} retryHref={next} />
    );
  }

  let workOrder;
  try {
    workOrder = await getObservationWorkOrder(workOrderId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    throw error;
  }
  const [site, drafts] = await Promise.all([
    getSite(workOrder.siteId).catch(() => null),
    listReobservationDrafts(workOrder.workOrderId).catch(() => []),
  ]);
  const pendingDraft = latestPendingDraft(drafts);
  const presentation = presentWorkOrder(workOrder.status);
  const showCopilot = workOrder.status === "REVIEW_READY" || workOrder.status === "COMPLETED";

  return (
    <div className="field-controls flex flex-col">
      <FieldHeader principal={session.principal}>
        <div className="flex flex-col gap-1">
          <h1 className="text-[19px] font-bold tracking-tight break-keep">{workOrder.name}</h1>
          <p className="text-[12.5px] break-keep text-ink-2">
            {site?.name ?? "현장"} · {workOrder.workAreaIds.length}개 구역 ·{" "}
            {workOrder.cycleNumber}회차
          </p>
        </div>
      </FieldHeader>

      <main className="flex flex-col gap-4 p-4">
        <Link href="/field" className="btn btn-field w-fit">
          ← 오늘 작업
        </Link>

        <section className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-col gap-1">
              <span className="text-[12px] font-semibold text-ink-muted">
                {presentation.step}/5 단계
              </span>
              <h2 className="text-[18px] font-bold tracking-tight">{presentation.label}</h2>
            </div>
            <StateBadge label={presentation.label} tone={presentation.tone} />
          </div>

          <ol aria-label="작업 진행 단계" className="grid grid-cols-5 gap-1">
            {STEP_LABELS.map((label, index) => {
              const step = index + 1;
              const reached = step <= presentation.step;
              return (
                <li key={label} className="flex min-w-0 flex-col gap-1">
                  <span
                    aria-hidden="true"
                    className={"h-2 rounded-full " + (reached ? "bg-accent" : "bg-line-strong")}
                  />
                  <span className="truncate text-center text-[11px] text-ink-2">{label}</span>
                </li>
              );
            })}
          </ol>

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
            version={workOrder.version}
            presentation={presentation}
            pendingDraft={pendingDraft}
          />
        </section>

        {showCopilot && (
          <CopilotPanel siteId={workOrder.siteId} workOrderId={workOrder.workOrderId} />
        )}

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
                  className="btn btn-field w-fit"
                >
                  수동 임무 복구 열기
                </Link>
              ))
            )}
          </div>
        </details>
      </main>
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
