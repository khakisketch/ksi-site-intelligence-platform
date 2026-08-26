import Link from "next/link";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { listAllEventsCached, listSitesCached } from "@/lib/core-api/cached";
import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { listObservationWorkOrdersForOrganization } from "@/lib/core-api/observation-work-orders";
import type {
  EventSummaryResponse,
  ObservationWorkOrderView,
  SiteView,
} from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";
import { resolveOperatorNextAction } from "@/lib/operator-next-action";

import { OperationsSessionFailure } from "./OperationsSessionFailure";
import { resolveFieldSession } from "./resolve-session";
import { presentWorkOrder } from "./work-order-stage";
import { summarizeWorkQueue, workOrderActionLabel } from "./work-queue";

export const metadata = { title: "작업 · KSI" };

type WorkResult =
  | {
      sites: SiteView[];
      workOrders: ObservationWorkOrderView[];
      events: EventSummaryResponse[];
      error: null;
    }
  | { sites: SiteView[]; workOrders: null; events: null; error: CoreApiError };

const WORK_GROUPS = [
  { key: "decisionRequired", label: "결정 필요", description: "승인·결과 검토·막힘 해소가 필요한 작업" },
  { key: "inFlight", label: "진행 중", description: "수집·전송·처리가 진행 중인 작업" },
  { key: "completed", label: "완료", description: "완료되거나 취소되어 이력으로 남은 작업" },
] as const;

async function fetchTodayWork(): Promise<WorkResult> {
  let sites: SiteView[];
  try {
    sites = await listSitesCached();
  } catch (error) {
    if (error instanceof CoreApiError) {
      return { sites: [], workOrders: null, events: null, error };
    }
    throw error;
  }
  try {
    const [workOrders, eventResponse] = await Promise.all([
      listObservationWorkOrdersForOrganization(),
      listAllEventsCached(),
    ]);
    return { sites, workOrders, events: eventResponse.events, error: null };
  } catch (error) {
    if (error instanceof CoreApiError) {
      return { sites, workOrders: null, events: null, error };
    }
    throw error;
  }
}

export default async function FieldWorkListPage() {
  const session = await resolveFieldSession();
  if (session.kind === "blocked") {
    return <OperationsSessionFailure verdict={session.verdict} next="/field" />;
  }

  const result = await fetchTodayWork();
  const siteNames = new Map(result.sites.map((site) => [site.siteId, site.name]));
  const queueSummary = result.workOrders ? summarizeWorkQueue(result.workOrders) : null;
  const nextAction =
    result.workOrders && result.events
      ? resolveOperatorNextAction({
          events: result.events,
          workOrders: result.workOrders,
          sites: result.sites,
          permissions: session.principal.permissions,
        })
      : null;

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <p className="text-[12.5px] break-keep text-ink-2">
        현장별로 지금 검토할 일과 조사 진행을 이어갑니다.
      </p>

      {result.workOrders && result.workOrders.length > 0 && (
        <section className="overflow-hidden rounded-lg border border-line bg-surface">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line px-4 py-3">
            <h2 className="text-[15px] font-bold tracking-tight break-keep">작업 현황</h2>
            <p className="text-[12.5px] break-keep text-ink-2">
              결정이 필요한 작업부터 확인하세요.
            </p>
          </div>
          <div className="grid gap-px bg-line sm:grid-cols-3">
            <div className="bg-surface px-4 py-3">
              <p className="text-[12px] font-semibold text-ink-muted">결정 필요</p>
              <p className="mt-1 text-[22px] font-bold tracking-tight num">
                {queueSummary ? queueSummary.decisionRequired.length : "—"}
              </p>
            </div>
            <div className="bg-surface px-4 py-3">
              <p className="text-[12px] font-semibold text-ink-muted">진행 중</p>
              <p className="mt-1 text-[22px] font-bold tracking-tight num">
                {queueSummary ? queueSummary.inFlight.length : "—"}
              </p>
            </div>
            <div className="bg-surface px-4 py-3">
              <p className="text-[12px] font-semibold text-ink-muted">완료</p>
              <p className="mt-1 text-[22px] font-bold tracking-tight num">
                {queueSummary ? queueSummary.completed.length : "—"}
              </p>
            </div>
          </div>
        </section>
      )}

      {result.error ? (
          <ErrorState
            message={humanizeApiError(
              result.error.code,
              result.error.status,
              result.error.serverMessage,
            )}
            detail={result.error.serverMessage}
            retryable
          />
        ) : result.workOrders.length === 0 ? (
          <EmptyState
            compact
            inline
            title="현재 진행할 작업이 없습니다"
            description="현재 작업 원장에는 진행 중인 항목이 없습니다. 새 조사나 검토가 필요해지면 현장명과 필요한 행동이 이곳에 표시됩니다."
            action={
              nextAction
                ? {
                    label: nextAction.siteId
                      ? `${siteNames.get(nextAction.siteId) ?? "선택한 현장"} · ${nextAction.label}`
                      : nextAction.label,
                    href: nextAction.href,
                    desktopOnly: true,
                  }
                : undefined
            }
          />
        ) : (
          <div className="flex flex-col gap-5">
            {WORK_GROUPS.map((group) => {
              const orders = queueSummary?.[group.key] ?? [];
              if (orders.length === 0) return null;
              return (
                <section key={group.key} className="flex flex-col gap-2">
                  <div className="flex items-baseline gap-2 px-1">
                    <h2 className="text-[15px] font-bold">{group.label}</h2>
                    <span className="num text-[12px] text-ink-muted">{orders.length}건</span>
                    <span className="hidden text-[12px] text-ink-2 sm:inline">{group.description}</span>
                  </div>
                  <ul className="flex flex-col divide-y divide-line rounded-xl border border-line bg-surface px-4">
                    {orders.map((workOrder) => {
                      const presentation = presentWorkOrder(workOrder.status);
                      return (
                        <li key={workOrder.workOrderId}>
                          <Link
                            href={`/field/work-orders/${encodeURIComponent(workOrder.workOrderId)}`}
                            className="tap-target -mx-2 grid gap-1 rounded-lg px-2 py-3 hover:bg-sunk sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                          >
                            <span className="min-w-0">
                              <span className="block text-[14px] font-semibold break-keep">{workOrder.name}</span>
                              <span className="mt-0.5 block text-[12.5px] break-keep text-ink-2">
                                {siteNames.get(workOrder.siteId) ?? "현장 이름을 확인할 수 없음"} · {workOrderActionLabel(workOrder.status)}
                              </span>
                            </span>
                            <span className="flex flex-wrap items-center gap-2 sm:justify-end">
                              <StateBadge label={presentation.label} tone={presentation.tone} />
                              <span className="num text-[11.5px] whitespace-nowrap text-ink-muted">
                                {formatKoreanDateTime(workOrder.updatedAt, { dateStyle: "short", timeStyle: "short" })}
                              </span>
                            </span>
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })}
          </div>
        )}
    </div>
  );
}
