import Link from "next/link";

import type { ObservationWorkOrderWorkflowStatus } from "@/lib/core-api/types";

export type ReportSuccessorTrace = {
  workOrderId: string;
  workflowStatus: ObservationWorkOrderWorkflowStatus | null;
  closeNote: string | null;
};

function successorStatusLabel(status: ObservationWorkOrderWorkflowStatus | null): string {
  if (status === null) return "현재 업무 상태를 확인하지 못했습니다";
  if (status === "CLOSED") return "업무 종료";
  if (status === "OPEN") return "업무 진행 중";
  return "업무 상태 기록 없음";
}

/** Links only to reports and successors already retained by the server. */
export function ExternalReportFollowupTrace({
  reportRef,
  baselineWorkOrderId,
  currentWorkOrderId,
  successors,
}: {
  reportRef: string;
  baselineWorkOrderId: string;
  currentWorkOrderId: string;
  /** Null means the report detail could not be re-verified, so no successor fact is shown. */
  successors: readonly ReportSuccessorTrace[] | null;
}) {
  const reviewHref = `/field/work-orders/${encodeURIComponent(currentWorkOrderId)}?reportRef=${encodeURIComponent(reportRef)}#external-result`;
  return <section className="rounded-xl border border-line bg-surface p-4">
    <h2 className="text-[16px] font-bold tracking-tight">검토·재관측 흐름</h2>
    <p className="mt-1 text-[13px] leading-5 text-ink-2">이 결과에 기록된 검토, 재관측 제안과 승인 이력은 결과에 결속된 작업 화면에서 확인합니다.</p>
    <div className="mt-3 flex flex-wrap gap-2">
      <Link className="btn" href={reviewHref}>결과 검토와 후속 작업</Link>
      {baselineWorkOrderId !== currentWorkOrderId && <Link className="btn" href={`/field/work-orders/${encodeURIComponent(baselineWorkOrderId)}`}>기준 작업 보기</Link>}
    </div>
    {successors !== null && successors.length > 0 && <div className="mt-3 border-t border-line pt-3">
      <h3 className="text-[13px] font-semibold">승인된 후속 작업</h3>
      <ul className="mt-2 flex flex-col gap-2">
        {successors.map((successor) => <li key={successor.workOrderId} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-sunk px-3 py-2 text-[13px]">
          <div><p className="font-semibold">{successorStatusLabel(successor.workflowStatus)}</p>{successor.closeNote && <p className="mt-0.5 text-[12px] leading-5 text-ink-2">{successor.closeNote}</p>}</div>
          <Link className="btn" href={`/field/work-orders/${encodeURIComponent(successor.workOrderId)}`}>승인된 후속 작업 보기</Link>
        </li>)}
      </ul>
    </div>}
  </section>;
}
