import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";

type Orderable = Pick<SpatialAssetCatalogItem, "assetRef" | "declared">;

/** 촬영 시작 시각, 없으면 촬영 날짜(날짜만 아는 자료). 둘 다 없거나 읽을 수 없으면 null. */
function captureMillis(item: Orderable): number | null {
  const { captureStartedAt, captureDate } = item.declared;
  for (const text of [captureStartedAt, captureDate]) {
    if (!text) continue;
    const millis = Date.parse(text);
    if (Number.isFinite(millis)) return millis;
  }
  return null;
}

/**
 * 자료 표를 보여 주는 순서 — 촬영이 늦은 자료가 위, 촬영 시점을 모르는 자료는 맨 아래.
 * Core 목록은 자료 참조(해시) 순이라 시간과 무관하다. 여기서는 보여 주는 순서만 정하고
 * 어느 자료가 최신 기준인지는 말하지 않는다. 같은 시점이면 자료 참조 순으로 고정한다.
 */
export function sortByCaptureDescending<T extends Orderable>(items: readonly T[]): T[] {
  return [...items].sort((a, b) => {
    const left = captureMillis(a);
    const right = captureMillis(b);
    if (left !== right) {
      if (left === null) return 1;
      if (right === null) return -1;
      return right - left;
    }
    return a.assetRef < b.assetRef ? -1 : a.assetRef > b.assetRef ? 1 : 0;
  });
}
