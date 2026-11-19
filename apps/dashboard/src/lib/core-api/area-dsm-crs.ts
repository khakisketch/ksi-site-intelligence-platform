import "server-only";

import { listSpatialAssets } from "@/lib/core-api/spatial-assets";
import { summarizeAreaDsmCrs, type AreaDsmCrs } from "@/lib/crs-match";

/**
 * 올리기 화면이 새 파일과 대조할 "이 구역에 이미 있는 DSM의 좌표계" 요약.
 *
 * Core의 현재 구역 범위 확인을 거친 목록 읽기만 쓴다(새 API·권한 없음). 읽지 못하면 그 구역은
 * null이고, 화면은 대조 블록만 생략한다 — 올리기 자체를 막지 않는다.
 */
export async function loadAreaDsmCrs(siteId: string, workAreaIds: readonly string[]): Promise<Record<string, AreaDsmCrs | null>> {
  const entries = await Promise.all(
    workAreaIds.map(async (workAreaId): Promise<[string, AreaDsmCrs | null]> => {
      try {
        const page = await listSpatialAssets(siteId, workAreaId, { limit: 50, order: "capture-desc" });
        return [workAreaId, summarizeAreaDsmCrs(page.assets, page.hasMore)];
      } catch {
        return [workAreaId, null];
      }
    }),
  );
  return Object.fromEntries(entries);
}
