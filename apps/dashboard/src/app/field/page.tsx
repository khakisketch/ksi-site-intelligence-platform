import Link from "next/link";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { listAllEventsCached, listSitesCached } from "@/lib/core-api/cached";
import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import {
  listObservationWorkOrderOperations,
  listObservationWorkOrdersForOrganization,
} from "@/lib/core-api/observation-work-orders";
import type {
  EventSummaryResponse,
  ObservationWorkOrderOperationsView,
  ObservationWorkOrderView,
  SiteView,
} from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";
import { resolveOperatorNextAction } from "@/lib/operator-next-action";

import { OperationsSessionFailure } from "./OperationsSessionFailure";
import { resolveFieldSession } from "./resolve-session";
import { presentWorkOrder } from "./work-order-stage";
import { WorkQueueOperationsNotices } from "./WorkQueueOperationsNotices";
import { deriveWorkQueueOperationalNotices, summarizeWorkQueue, workOrderActionLabel } from "./work-queue";

export const metadata = { title: "작업 · KSI" };

type WorkResult =
  | {
      sites: SiteView[];
      workOrders: ObservationWorkOrderView[];
      events: EventSummaryResponse[] | null;
      operations: ObservationWorkOrderOperationsView[] | null;
      eventError: CoreApiError | null;
      operationsError: CoreApiError | null;
      error: null;
    }
  | {
      sites: SiteView[];
      workOrders: null;
      events: null;
      operations: null;
      eventError: null;
      operationsError: null;
      error: CoreApiError;
    };

const WORK_GROUPS = [
  { key: "decisionRequired", label: "결정 필요", description: "승인·결과 검토·막힘 해소가 필요한 작업" },
  { key: "inFlight", label: "진행 중", description: "수집·전송·처리가 진행 중인 작업" },
  { key: "operationsUnavailable", label: "운영 상태 확인 필요", description: "담당·기한·업무 종료 상태를 확인한 뒤 이어갈 작업" },
  { key: "completed", label: "완료", description: "완료되거나 취소되어 이력으로 남은 작업" },
] as const;

async function fetchTodayWork(canReadOperations: boolean): Promise<WorkResult> {
  let sites: SiteView[];
  try {
    sites = await listSitesCached();
  } catch (error) {
    if (error instanceof CoreApiError) {
      return {
        sites: [], workOrders: null, events: null, operations: null,
        eventError: null, operationsError: null, error,
      };
    }
    throw error;
  }
  try {
    const workOrders = await listObservationWorkOrdersForOrganization();
    const [events, operations] = await Promise.allSettled([
      listAllEventsCached(),
      canReadOperations ? listObservationWorkOrderOperations() : Promise.resolve(null),
    ]);
    return {
      sites,
      workOrders,
      events: events.status === "fulfilled" ? events.value.events : null,
      operations: operations.status === "fulfilled" ? operations.value : null,
      eventError: events.status === "rejected" && events.reason instanceof CoreApiError ? events.reason : null,
      operationsError: operations.status === "rejected" && operations.reason instanceof CoreApiError
        ? operations.reason
        : null,
      error: null,
    };
  } catch (error) {
    if (error instanceof CoreApiError) {
      return {
        sites, workOrders: null, events: null, operations: null,
        eventError: null, operationsError: null, error,
      };
    }
    throw error;
  }
}

export default async function FieldWorkListPage() {
  const session = await resolveFieldSession();
  if (session.kind === "blocked") {
    return <OperationsSessionFailure verdict={session.verdict} next="/field" />;
  }

  const result = await fetchTodayWork(session.principal.permissions.includes("WORK_ORDERS_WRITE"));
  const siteNames = new Map(result.sites.map((site) => [site.siteId, site.name]));
  const operationsByWorkOrderId = new Map(
    (result.operations ?? []).map((operations) => [operations.workOrderId, operations]),
  );
  const queueSummary = result.workOrders
    ? summarizeWorkQueue(result.workOrders, operationsByWorkOrderId)
    : null;
  const operationalNotices = result.workOrders && result.operations
    ? deriveWorkQueueOperationalNotices(
        result.workOrders,
        operationsByWorkOrderId,
        session.principal.principalId,
        new Date(),
      )
    : [];
  const nextAction =
    result.workOrders && result.events
      ? resolveOperatorNextAction({
          events: result.events,
          workOrders: result.workOrders.filter(
            (workOrder) => operationsByWorkOrderId.get(workOrder.workOrderId)?.workflowStatus !== "CLOSED",
          ),
          sites: result.sites,
          permissions: session.principal.permissions,
        })
      : null;

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[12.5px] break-keep text-ink-2">
          현장별로 지금 검토할 일과 조사 진행을 이어갑니다.
        </p>
        {/* 세 액션이 같은 .btn 모양이면 우선순위가 없다(F18) — 이 화면에서 새 작업을
            시작하는 유일한 동작인 "새 관측 시작"만 1차 버튼이고, 나머지 둘은 낮은
            무게의 텍스트 링크로 물러난다. */}
        <div className="flex flex-wrap items-center gap-3">
          <Link href="/field/inbox" className="text-[13px] font-semibold text-ink-2 hover:text-ink-1 hover:underline">받은 업무</Link>
          <Link href="/field/team" className="hidden text-[13px] font-semibold text-ink-2 hover:text-ink-1 hover:underline lg:inline">팀 관리</Link>
          <Link href="/field/new" className="btn btn-primary hidden lg:inline-flex">새 관측 시작</Link>
        </div>
      </div>

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
            {result.eventError && (
              <p className="rounded-lg border border-line bg-sunk px-3 py-2 text-[13px] leading-5 text-ink-2">
                확인 항목을 지금 불러오지 못했습니다. 작업 목록은 최신 원장으로 계속 표시합니다.
              </p>
            )}
            {(result.operationsError || result.operations === null) && (
              <p className="rounded-lg border border-line bg-sunk px-3 py-2 text-[13px] leading-5 text-ink-2">
                {result.operationsError
                  ? "담당·기한·업무 종료 상태를 지금 불러오지 못했습니다. 외부 작업을 진행 중으로 분류하지 않습니다."
                  : "담당·기한·업무 종료 상태는 작업 운영 권한이 있는 계정에서 확인할 수 있습니다. 외부 작업을 진행 중으로 분류하지 않습니다."}
              </p>
            )}
            <WorkQueueOperationsNotices notices={operationalNotices} />
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
                      const operations = operationsByWorkOrderId.get(workOrder.workOrderId);
                      const closed = operations?.workflowStatus === "CLOSED";
                      const presentation = closed
                        ? { label: "업무 종료", tone: "neutral" as const }
                        : presentWorkOrder(workOrder.status, workOrder.executionMode);
                      const assignment = operations?.workflowStatus === "OPEN"
                        ? operations.assigneePrincipalId === session.principal.principalId
                          ? "담당 · 내 작업"
                          : operations.assigneePrincipalId
                            ? "담당 · 배정됨"
                            : "담당 · 미배정"
                        : null;
                      return (
                        <li key={workOrder.workOrderId}>
                          <Link
                            href={`/field/work-orders/${encodeURIComponent(workOrder.workOrderId)}`}
                            className="tap-target -mx-2 grid gap-1 rounded-lg px-2 py-3 hover:bg-sunk sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                          >
                            <span className="min-w-0">
                              <span className="block text-[14px] font-semibold break-keep">{workOrder.name}</span>
                              <span className="mt-0.5 block text-[12.5px] break-keep text-ink-2">
                                {siteNames.get(workOrder.siteId) ?? "현장 이름을 확인할 수 없음"} · {closed
                                  ? "업무 종료"
                                  : group.key === "operationsUnavailable"
                                    ? "운영 상태 확인 필요"
                                  : workOrderActionLabel(workOrder.status, workOrder.executionMode)}{assignment ? ` · ${assignment}` : ""}{operations?.workflowStatus === "OPEN" && operations.dueAt ? ` · 마감 ${formatKoreanDateTime(operations.dueAt, { dateStyle: "short", timeStyle: "short" })}` : ""}
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
