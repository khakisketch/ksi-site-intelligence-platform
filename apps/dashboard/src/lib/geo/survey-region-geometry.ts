import type { ChangeRegion } from "@/lib/core-api/types";

/**
 * 전수측량 후보 구역의 **화면 표시 전용** 변환.
 *
 * 서버 계약(`ChangeRegionSetReport.regions`)의 WGS84 볼록 껍질
 * (`convexHullPolygonWgs84`)만 지도에 올린다. native CRSHull(`polygon`·
 * `convexHullPolygon`)은 지도에 그리지 않는다 — 단위가 미터인 투영좌표를
 * 위경도로 오독하면 지구 반대편 그림이 된다(display-geometry.ts U02 P1과
 * 같은 사고). 입력·원본을 바꾸지 않으며, 그릴 수 없는 구역은 사유와 함께
 * 돌려준다(호출자가 목록 선택을 막지 않고 누락을 알린다).
 */

export type SurveyRegionShape = {
  regionId: string;
  /** Leaflet 순서 [위도, 경도]. */
  positions: [number, number][];
};

export type UnsupportedSurveyRegion = { regionId: string; reason: string };

/** 배경 지도(Web Mercator)가 그릴 수 있는 위도 한계 — 초과 구역은 올리지 않는다. */
const MAX_MERCATOR_LAT = 85.05112878;

function fail(regionId: string, reason: string): UnsupportedSurveyRegion {
  return { regionId, reason };
}

function toPositions(
  regionId: string,
  hull: NonNullable<ChangeRegion["convexHullPolygonWgs84"]>,
): { ok: true; positions: [number, number][] } | { ok: false; reason: string } {
  if (hull.type !== "Polygon") {
    return { ok: false, reason: `"${hull.type}" 기하는 지도에 올리지 않습니다.` };
  }
  const rings: unknown = hull.coordinates;
  if (!Array.isArray(rings) || rings.length === 0) {
    return { ok: false, reason: "껍질 좌표를 읽지 못했습니다." };
  }
  if (rings.length > 1) {
    return { ok: false, reason: "링이 2개 이상인 껍질은 지도에 올리지 않습니다." };
  }
  const ring: unknown = rings[0];
  if (!Array.isArray(ring) || ring.length < 4) {
    return { ok: false, reason: "껍질 꼭짓점이 3개 미만입니다." };
  }
  const positions: [number, number][] = [];
  for (const point of ring) {
    if (!Array.isArray(point) || point.length < 2) {
      return { ok: false, reason: "껍질 좌표를 읽지 못했습니다." };
    }
    const [lonDeg, latDeg] = point as unknown[];
    if (
      typeof lonDeg !== "number" ||
      typeof latDeg !== "number" ||
      !Number.isFinite(lonDeg) ||
      !Number.isFinite(latDeg)
    ) {
      return { ok: false, reason: "숫자가 아닌 껍질 좌표가 있습니다." };
    }
    if (lonDeg < -180 || lonDeg > 180 || latDeg < -90 || latDeg > 90) {
      return { ok: false, reason: `위경도 범위를 벗어난 값(${lonDeg}, ${latDeg})이 있습니다.` };
    }
    if (Math.abs(latDeg) > MAX_MERCATOR_LAT) {
      return { ok: false, reason: "배경 지도 표시 범위를 벗어난 구역입니다." };
    }
    positions.push([latDeg, lonDeg]);
  }
  const distinct = new Set(positions.map(([lat, lon]) => `${lat},${lon}`));
  if (distinct.size < 3) {
    return { ok: false, reason: "서로 다른 껍질 꼭짓점이 3개 미만입니다." };
  }
  return { ok: true, positions };
}

/**
 * 그릴 수 있는 구역과 지도에 올리지 못한 구역을 나눈다. 서버가 hull 계산에
 * 실패한 구역(`convexHullPolygonWgs84: null`)은 서버가 적은 사유
 * (`aoiDraftUnavailableReason`)를 그대로 전달한다.
 */
export function partitionSurveyRegionDisplay(
  regions: ChangeRegion[],
): { supported: SurveyRegionShape[]; unsupported: UnsupportedSurveyRegion[] } {
  const supported: SurveyRegionShape[] = [];
  const unsupported: UnsupportedSurveyRegion[] = [];
  for (const region of regions) {
    const hull = region.convexHullPolygonWgs84;
    if (hull === null) {
      unsupported.push(fail(
        region.regionId,
        region.aoiDraftUnavailableReason ?? "볼록 껍질을 계산하지 못했습니다.",
      ));
      continue;
    }
    const converted = toPositions(region.regionId, hull);
    if (converted.ok) {
      supported.push({ regionId: region.regionId, positions: converted.positions });
    } else {
      unsupported.push(fail(region.regionId, converted.reason));
    }
  }
  return { supported, unsupported };
}

/**
 * 그릴 수 없는 구역의 이름·사유 목록 문구. 그릴 수 있는 구역이 하나도 없을
 * 때도 같은 문구를 쓰므로, 원인이 hull 계산 실패가 아닐 때 hull 탓으로
 * 돌리지 않는다. 목록 선택을 막지 않는다.
 */
export function unsupportedSurveyRegionsNote(unsupported: UnsupportedSurveyRegion[]): string | null {
  if (unsupported.length === 0) return null;
  return `지도에 표시되지 않은 후보 ${unsupported.length}개: `
    + `${unsupported.map((item) => `${item.regionId}(${item.reason})`).join(" · ")} `
    + "목록에서는 모두 선택할 수 있으며, 좌표를 추정해 그리지 않습니다.";
}
