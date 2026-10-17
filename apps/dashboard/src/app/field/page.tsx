import Link from "next/link";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import {
  listObservationWorkOrderOperations,
  listObservationWorkOrdersForOrganization,
} from "@/lib/core-api/observation-work-orders";
import { resolveFieldSession } from "./resolve-session";
import { OperationsSessionFailure } from "./OperationsSessionFailure";
import { WorkQueueOperationsNotices } from "./WorkQueueOperationsNotices";
import { deriveWorkQueueOperationalNotices, summarizeWorkQueue } from "./work-queue";
import { presentWorkOrder } from "./work-order-stage";

export const metadata = { title: "작업 · KSI" };

const GROUPS = [
  ["decisionRequired", "결정 필요", "범위 검토와 결과 확인이 필요한 작업"],
  ["inFlight", "진행 중", "수집·전송·처리 중인 작업"],
  ["operationsUnavailable", "운영 상태 확인 필요", "담당·기한 상태를 확인할 작업"],
  ["completed", "완료", "완료되거나 종료된 작업"],
] as const;

const SUMMARY_GROUPS = [
  ["decisionRequired", "결정 필요"],
  ["inFlight", "진행 중"],
  ["operationsUnavailable", "운영 상태 확인 필요"],
  ["completed", "완료"],
] as const;

export default async function FieldWorkListPage() {
  const session = await resolveFieldSession();
  if (session.kind === "blocked") return <OperationsSessionFailure verdict={session.verdict} next="/field" />;
  let workOrders;
  try {
    workOrders = await listObservationWorkOrdersForOrganization();
  } catch (error) {
    const message = error instanceof CoreApiError
      ? humanizeApiError(error.code, error.status, error.serverMessage)
      : "요청을 처리하지 못했습니다.";
    return <div className="p-4 sm:p-5"><ErrorState message={message} retryable /></div>;
  }
  const operations = session.principal.permissions.includes("WORK_ORDERS_WRITE")
    ? await listObservationWorkOrderOperations().catch(() => null)
    : null;
  const byId = new Map((operations ?? []).map((item) => [item.workOrderId, item]));
  const summary = summarizeWorkQueue(workOrders, byId);
  const notices = operations
    ? deriveWorkQueueOperationalNotices(workOrders, byId, session.principal.principalId, new Date())
    : [];
  const canCreateObservation = session.principal.permissions.includes("WORK_ORDERS_WRITE");

  return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[12.5px] text-ink-2">플랫폼 작업 원장에 기록된 관측 작업과 외부 결과 흐름입니다.</p>
          <div className="flex items-center gap-3">
            <Link href="/field/inbox" className="tap-target text-[13px] font-semibold text-ink-2 hover:underline">받은 업무</Link>
            <Link href="/field/team" className="tap-target text-[13px] font-semibold text-ink-2 hover:underline">팀 관리</Link>
            {canCreateObservation ? (
              <Link href="/field/new" className="btn btn-primary tap-target">새 관측 시작</Link>
            ) : (
              <p className="text-[12px] leading-5 text-ink-2">새 관측 시작은 작업 등록 권한이 있는 계정에서 할 수 있습니다.</p>
            )}
          </div>
        </header>
        <WorkQueueOperationsNotices notices={notices} />
        {workOrders.length === 0 ? (
          <EmptyState title="등록된 관측 작업이 없습니다" description="현장 화면에서 작업구역을 확인하고 새 관측 작업을 시작할 수 있습니다." action={{ label: "현장 보기", href: "/sites" }} />
        ) : (
          <>
            <section className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line lg:grid-cols-4" aria-label="작업 요약">
              {SUMMARY_GROUPS.map(([key, label]) => (
                <div key={key} className="min-w-0 bg-surface px-3 py-3 sm:px-4">
                  <p className="text-[12px] font-semibold text-ink-muted">{label}</p>
                  <p className="num mt-1 text-[22px] font-bold tracking-tight">{summary[key].length}</p>
                </div>
              ))}
            </section>
            {GROUPS.map(([key, label, description]) => {
              const rows = summary[key];
              return (
                <section key={key} className="overflow-hidden rounded-lg border border-line bg-surface" aria-labelledby={`work-${key}`}>
                  <div className="border-b border-line px-4 py-3">
                    <div className="flex items-baseline justify-between gap-3">
                      <h2 id={`work-${key}`} className="text-[15px] font-bold">{label}</h2>
                      <span className="num text-[12px] text-ink-muted">{rows.length}</span>
                    </div>
                    <p className="mt-1 text-[12px] text-ink-2">{description}</p>
                  </div>
                  {rows.length === 0 ? (
                    <p className="px-4 py-4 text-[12.5px] text-ink-muted">이 구분에 표시할 작업이 없습니다.</p>
                  ) : (
                    <ul className="divide-y divide-line">
                      {rows.map((order) => {
                        const state = presentWorkOrder(order.status, order.executionMode);
                        return (
                          <li key={order.workOrderId}>
                            <Link href={`/field/work-orders/${encodeURIComponent(order.workOrderId)}`} className="tap-target flex flex-wrap items-center justify-between gap-3 px-4 py-3 hover:bg-sunk">
                              <span className="min-w-0">
                                <span className="block break-keep text-[13px] font-semibold">{order.name}</span>
                              </span>
                              <StateBadge label={state.label} tone={state.tone} />
                            </Link>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </section>
              );
            })}
          </>
        )}
      </div>
  );
}
