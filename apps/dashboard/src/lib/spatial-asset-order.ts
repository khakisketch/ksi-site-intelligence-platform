import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";

type Orderable = Pick<SpatialAssetCatalogItem, "assetRef" | "declared">;

/** Older data-table bookmarks carry a V1 reference-order cursor. */
export function isLegacySpatialAssetCursor(cursor: string): boolean {
  if (cursor.length === 0 || cursor.length > 1024 || !/^[A-Za-z0-9_-]+$/.test(cursor)) return false;
  try {
    const payload: unknown = JSON.parse(Buffer.from(cursor, "base64url").toString("utf8"));
    return typeof payload === "object" && payload !== null && !Array.isArray(payload)
      && (payload as Record<string, unknown>).version === 1;
  } catch {
    return false;
  }
}

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
 * Keep the former page-local display order for V1 bookmark continuations.
 * New capture-ordered pages retain Core's exact order, including sub-millisecond timestamps.
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
