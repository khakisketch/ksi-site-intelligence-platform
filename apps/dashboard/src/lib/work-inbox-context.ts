/**
 * 받은 업무 항목의 맥락 이름(서버 전용).
 *
 * 호출자가 넘긴 해당 페이지 항목에만 대해, 이미 인증된 범위에서 읽을 수 있는
 * 작업·현장 목록 API로 이름을 확인한다(중복 제거·병렬, 건별 실패 무시).
 * 페이지 크기(Core `limit: 20`)를 넘는 읽기는 하지 않으며, 새 Core 계약·
 * 스키마를 만들지 않는다. 이름은 표시에만 쓰고 권한·소속을 추론하지 않는다
 * (INV-060/061).
 */
import "server-only";

import { getObservationWorkOrder } from "@/lib/core-api/observation-work-orders";
import { getSite } from "@/lib/core-api/sites";
import type { WorkInboxItem } from "@/lib/core-api/work-collaboration";

export type WorkInboxContextByRef = Record<string, { workName: string | null; siteName: string | null }>;

export async function resolveWorkInboxContext(items: readonly WorkInboxItem[]): Promise<WorkInboxContextByRef> {
  const workOrderIds = [...new Set(items.flatMap((item) => item.target.kind === "WORK_ORDER" ? [item.target.workOrderId] : []))];
  const workOrders = await Promise.all(workOrderIds.map(async (workOrderId) => {
    try {
      return await getObservationWorkOrder(workOrderId);
    } catch {
      return null;
    }
  }));
  const workOrderById = new Map(workOrders.flatMap((order) => order === null ? [] : [[order.workOrderId, order] as const]));
  const siteIds = [...new Set([
    ...items.flatMap((item) => item.target.kind === "EXTERNAL_REPORT" ? [item.target.siteId] : []),
    ...[...workOrderById.values()].map((order) => order.siteId),
  ])];
  const sites = await Promise.all(siteIds.map(async (siteId) => {
    try {
      return await getSite(siteId);
    } catch {
      return null;
    }
  }));
  const siteNameById = new Map(sites.flatMap((site) => site === null ? [] : [[site.siteId, site.name] as const]));
  const contextByRef: WorkInboxContextByRef = {};
  for (const item of items) {
    if (item.target.kind === "WORK_ORDER") {
      const order = workOrderById.get(item.target.workOrderId) ?? null;
      contextByRef[item.notificationRef] = {
        workName: order?.name ?? null,
        siteName: order ? (siteNameById.get(order.siteId) ?? null) : null,
      };
    } else {
      contextByRef[item.notificationRef] = { workName: null, siteName: siteNameById.get(item.target.siteId) ?? null };
    }
  }
  return contextByRef;
}
