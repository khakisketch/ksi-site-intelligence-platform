import Link from "next/link";

import { formatKoreanDateTime } from "@/lib/datetime";

import type { WorkQueueOperationalNotice } from "./work-queue";

type NoticeView = Pick<WorkQueueOperationalNotice, "overdue" | "dueSoon" | "assignedToMe"> & {
  workOrder: Pick<WorkQueueOperationalNotice["workOrder"], "workOrderId" | "name">;
  operations: Pick<WorkQueueOperationalNotice["operations"], "dueAt">;
};

/** Read-only, task-linked notices derived for the current queue render. */
export function WorkQueueOperationsNotices({ notices }: { notices: readonly NoticeView[] }) {
  if (notices.length === 0) return null;
  return (
    <section className="rounded-xl border border-line bg-surface" aria-labelledby="operations-notices-heading">
      <div className="border-b border-line px-4 py-3">
        <h2 id="operations-notices-heading" className="text-[15px] font-bold">운영 알림</h2>
        <p className="mt-1 text-[12.5px] leading-5 text-ink-2">이 화면을 연 시각을 기준으로 담당과 마감이 필요한 작업을 표시합니다.</p>
      </div>
      <ul className="divide-y divide-line px-4">
        {notices.map((notice) => (
          <li key={notice.workOrder.workOrderId}>
            <Link
              href={`/field/work-orders/${encodeURIComponent(notice.workOrder.workOrderId)}`}
              className="tap-target -mx-2 flex flex-wrap items-center justify-between gap-2 rounded-lg px-2 py-3 hover:bg-sunk"
            >
              <span className="min-w-0">
                <span className="block text-[14px] font-semibold break-keep">{notice.workOrder.name}</span>
                {notice.operations.dueAt && <span className="mt-0.5 block text-[12.5px] text-ink-2">마감 · {formatKoreanDateTime(notice.operations.dueAt, { dateStyle: "short", timeStyle: "short" })}</span>}
              </span>
              <span className="flex flex-wrap items-center justify-end gap-1.5 text-[11.5px] font-semibold">
                {notice.overdue && <span className="rounded-full bg-high-bg px-2 py-1 text-high-ink">마감 지남</span>}
                {notice.dueSoon && <span className="rounded-full bg-sunk px-2 py-1 text-ink-2">마감 임박</span>}
                {notice.assignedToMe && <span className="rounded-full bg-accent-bg px-2 py-1 text-accent-text">내 작업</span>}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
