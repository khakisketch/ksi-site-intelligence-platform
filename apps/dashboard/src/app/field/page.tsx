import Link from "next/link";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { listSitesCached } from "@/lib/core-api/cached";
import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { listObservationWorkOrders } from "@/lib/core-api/observation-work-orders";
import type { ObservationWorkOrderView, SiteView } from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";

import { FieldBlocked, FieldHeader, FieldInlineLogin } from "./FieldShell";
import { PilotBridgeProbe } from "./PilotBridgeProbe";
import { resolveFieldSession } from "./resolve-session";
import { presentWorkOrder } from "./work-order-stage";

export const metadata = { title: "오늘 작업 · KSI" };

type WorkResult =
  | { sites: SiteView[]; workOrders: ObservationWorkOrderView[]; error: null }
  | { sites: SiteView[]; workOrders: null; error: CoreApiError };

async function fetchTodayWork(): Promise<WorkResult> {
  let sites: SiteView[];
  try {
    sites = await listSitesCached();
  } catch (error) {
    if (error instanceof CoreApiError) return { sites: [], workOrders: null, error };
    throw error;
  }
  const results = await Promise.allSettled(
    sites.map((site) => listObservationWorkOrders(site.siteId)),
  );
  const workOrders = results.flatMap((result) =>
    result.status === "fulfilled" ? result.value : [],
  );
  const firstError = results.find(
    (result): result is PromiseRejectedResult => result.status === "rejected",
  );
  if (firstError?.reason instanceof CoreApiError && workOrders.length === 0) {
    return { sites, workOrders: null, error: firstError.reason };
  }
  return {
    sites,
    workOrders: workOrders.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
    error: null,
  };
}

export default async function FieldWorkListPage() {
  const session = await resolveFieldSession();
  if (session.kind === "blocked") {
    return session.verdict.kind === "login" ? (
      <FieldInlineLogin next="/field" notice={session.verdict.notice} />
    ) : (
      <FieldBlocked message={session.verdict.message} retryHref="/field" />
    );
  }

  const result = await fetchTodayWork();
  const siteNames = new Map(result.sites.map((site) => [site.siteId, site.name]));

  return (
    <div className="field-controls flex flex-col">
      <FieldHeader principal={session.principal}>
        <div className="flex flex-col gap-1">
          <h1 className="text-[19px] font-bold tracking-tight break-keep">오늘 작업</h1>
          <p className="text-[12.5px] break-keep text-ink-2">
            작업 하나를 열고 승인하면 수집·전송·분석까지 같은 화면에서 이어집니다.
          </p>
        </div>
      </FieldHeader>

      <main className="flex flex-col gap-4 p-4">
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
            title="준비된 현장 작업이 없습니다"
            description="사무실에서 반복 관측 작업을 만들면 여기에 나타납니다. 현장에서는 KMZ나 사진 폴더를 준비할 필요가 없습니다."
          />
        ) : (
          <ul className="flex flex-col gap-3">
            {result.workOrders.map((workOrder) => {
              const presentation = presentWorkOrder(workOrder.status);
              return (
                <li key={workOrder.workOrderId}>
                  <Link
                    href={
                      "/field/work-orders/" + encodeURIComponent(workOrder.workOrderId)
                    }
                    className="flex min-h-[96px] flex-col justify-center gap-2 rounded-xl border border-line bg-surface px-4 py-4 hover:border-line-strong hover:bg-sunk"
                  >
                    <span className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-[16px] font-bold tracking-tight break-keep">
                        {workOrder.name}
                      </span>
                      <StateBadge label={presentation.label} tone={presentation.tone} />
                    </span>
                    <span className="text-[13px] break-keep text-ink-2">
                      {siteNames.get(workOrder.siteId) ?? "현장"} ·{" "}
                      {workOrder.workAreaIds.length}개 구역 · {workOrder.cycleNumber}회차
                    </span>
                    <span className="text-[12px] text-ink-muted">
                      {formatKoreanDateTime(workOrder.updatedAt, {
                        dateStyle: "medium",
                        timeStyle: "short",
                      })}{" "}
                      업데이트
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}

        <details className="rounded-lg border border-line bg-surface px-4 py-3 text-[13px]">
          <summary className="min-h-11 cursor-pointer font-semibold break-keep">
            연결 문제 시 복구 도구
          </summary>
          <div className="flex flex-col gap-3 border-t border-line pt-3 text-ink-2">
            <p className="break-keep">
              USB·SD·수동 임무 파일은 정상 작업이 아니라 자동 전달이 막혔을 때만
              사용합니다.
            </p>
            <Link href="/missions" className="btn btn-field w-fit">
              임무·파일 복구 열기
            </Link>
            <PilotBridgeProbe />
          </div>
        </details>
      </main>
    </div>
  );
}
