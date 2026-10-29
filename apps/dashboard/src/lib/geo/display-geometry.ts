import proj4 from "proj4";

import type { AoiVertex } from "@/lib/core-api/types";

import { registerKoreaProjections } from "./proj4-defs";

/**
 * 등록된 작업구역 기하의 **화면 표시 전용** 변환(U02 P1 안전 기초).
 *
 * `polygonToVertices`(`@/lib/work-areas`)는 CRS를 받지 않고 모든 숫자를
 * 경위도로 취급한다 — 투영좌표(EPSG:5186 등, 단위 m) 구역의 "다시 그리기"가
 * 지구 반대편 수평선이 된 원인이다. 이 함수는 그 자리에 쓴다: 알려진 좌표계만
 * WGS84(`AoiVertex`)로 되돌리고, 모르는 것은 정직하게 막는다.
 *
 * 규율(원본·계보 불변, INV-020/051/053/060/061):
 * - 입력 `polygon`·`crs`를 바꾸지 않는다. 반환된 꼭짓점은 지도 표시·새 구역
 *   그리기의 **출발점**일 뿐, 원래 구역·CRS·불변 계보를 고치지 않는다.
 * - 구멍(hole)·MultiPolygon은 "지원되는 만큼만" 보여주지 않고 막는다.
 *   구멍을 버리고 바깥 경계만 보여주면 실제 범위와 다른 그림이 된다.
 * - 알려진 정의만 쓴다(`proj4-defs.ts` 등록분 + proj4 내장 WGS84).
 *   임의 EPSG 네트워크 조회는 하지 않는다.
 * - 실패 사유(`reason`)는 기하·CRS 사실만 간결하게 적는다. "다시 그리기" 같은
 *   다음 행동 안내는 호출자가 붙인다 — 이 헬퍼는 작업구역 정정뿐 아니라 읽기
 *   전용 공간 확인(현장 상세·자산 footprint)에서도 쓰이므로, 특정 화면의
 *   행동 문구가 섞이면 다른 자리에서 거짓말이 된다.
 * - 표시 전용이다. 이 변환은 원본 재투영·재표본화가 아니며, 정량·정산·정확도
 *   적합성을 증명하지 않는다(SDP-REQ01/02/04/06).
 */

export type DisplayVerticesResult =
  | { ok: true; vertices: AoiVertex[] }
  | { ok: false; reason: string };

/** `proj4-defs.ts`가 등록하는 정의와 같은 집합 — 여기가 바뀌면 저기도 함께. */
const SUPPORTED_PROJECTED_CRS = new Set([
  "EPSG:5185",
  "EPSG:5186",
  "EPSG:5187",
  "EPSG:5188",
  "EPSG:5179",
]);

/** 한 구역 미리보기가 다룰 상한 — 초과는 비정상으로 보고 막는다. */
const MAX_DISPLAY_VERTICES = 512;

/** 투영좌표(m)로 믿기 어려운 절댓값 — 초과는 범위 밖으로 보고 막는다. */
const MAX_PROJECTED_ABS = 10_000_000;

function fail(reason: string): DisplayVerticesResult {
  return { ok: false, reason };
}

export function toDisplayVertices(
  polygon: Record<string, unknown>,
  crs: string,
): DisplayVerticesResult {
  const code = crs.trim().toUpperCase();
  const geographic = code === "EPSG:4326";
  const projected = SUPPORTED_PROJECTED_CRS.has(code);
  if (!geographic && !projected) {
    return fail(`좌표계 "${crs}"은 미리보기를 지원하지 않습니다.`);
  }

  if (typeof polygon !== "object" || polygon === null) {
    return fail("폴리곤 좌표를 읽지 못했습니다.");
  }
  if (polygon.type !== "Polygon") {
    return fail(`"${String(polygon.type)}" 기하는 미리보기를 지원하지 않습니다.`);
  }
  const coordinates: unknown = polygon.coordinates;
  if (!Array.isArray(coordinates) || coordinates.length === 0) {
    return fail("폴리곤 좌표를 읽지 못했습니다.");
  }
  if (coordinates.length > 1) {
    return fail("구멍이 있는 폴리곤은 미리보기를 지원하지 않습니다.");
  }
  const ring: unknown = coordinates[0];
  if (!Array.isArray(ring)) {
    return fail("폴리곤 좌표를 읽지 못했습니다.");
  }
  // 상한 검사는 점 순회보다 먼저 — 비정상적인 큰 링을 끝까지 돌지 않는다.
  // 닫힌 링은 첫 점이 끝에 한 번 더 있으므로 +1까지 허용한다.
  if (ring.length > MAX_DISPLAY_VERTICES + 1) {
    return fail(`꼭짓점이 너무 많습니다(${ring.length}개, 상한 ${MAX_DISPLAY_VERTICES}개).`);
  }

  const points: Array<readonly [number, number]> = [];
  for (const point of ring) {
    if (!Array.isArray(point) || point.length < 2) {
      return fail("폴리곤 좌표를 읽지 못했습니다.");
    }
    const [x, y] = point as unknown[];
    if (
      typeof x !== "number" ||
      typeof y !== "number" ||
      !Number.isFinite(x) ||
      !Number.isFinite(y)
    ) {
      return fail("숫자가 아닌 좌표가 있습니다.");
    }
    points.push([x, y]);
  }

  // GeoJSON 링은 첫 점으로 닫힌다 — 되돌릴 때 한 번 연다.
  const last = points.length - 1;
  const closed =
    points.length >= 2 &&
    points[0][0] === points[last][0] &&
    points[0][1] === points[last][1];
  const distinct = closed ? points.slice(0, -1) : points;
  if (distinct.length < 3) {
    return fail("꼭짓점이 3개 미만입니다.");
  }
  // 같은 점만 반복된 링은 지도에 선·점으로만 보인다 — 폴리곤인 것처럼 내지 않는다.
  const actual = new Set(distinct.map(([x, y]) => `${x},${y}`));
  if (actual.size < 3) {
    return fail("서로 다른 꼭짓점이 3개 미만입니다.");
  }
  if (distinct.length > MAX_DISPLAY_VERTICES) {
    return fail(
      `꼭짓점이 너무 많습니다(${distinct.length}개, 상한 ${MAX_DISPLAY_VERTICES}개).`,
    );
  }

  if (geographic) {
    const vertices: AoiVertex[] = [];
    for (const [lonDeg, latDeg] of distinct) {
      if (lonDeg < -180 || lonDeg > 180 || latDeg < -90 || latDeg > 90) {
        return fail(`위경도 범위를 벗어난 값(${lonDeg}, ${latDeg})이 있습니다.`);
      }
      vertices.push({ latDeg, lonDeg });
    }
    return { ok: true, vertices };
  }

  registerKoreaProjections();
  const vertices: AoiVertex[] = [];
  for (const [easting, northing] of distinct) {
    if (Math.abs(easting) > MAX_PROJECTED_ABS || Math.abs(northing) > MAX_PROJECTED_ABS) {
      return fail(`투영좌표 범위를 벗어난 값(${easting}, ${northing})이 있습니다.`);
    }
    let lonDeg: number;
    let latDeg: number;
    try {
      const converted = proj4(code, "EPSG:4326", [easting, northing]);
      lonDeg = converted[0];
      latDeg = converted[1];
    } catch {
      return fail(`좌표계 "${crs}"를 위경도로 변환하지 못했습니다.`);
    }
    if (
      !Number.isFinite(lonDeg) ||
      !Number.isFinite(latDeg) ||
      lonDeg < -180 ||
      lonDeg > 180 ||
      latDeg < -90 ||
      latDeg > 90
    ) {
      return fail("변환된 좌표가 위경도 범위를 벗어났습니다.");
    }
    vertices.push({ latDeg, lonDeg });
  }
  return { ok: true, vertices };
}

export type SupportedWorkAreaShape = { id: string; name: string; positions: [number, number][] };
export type UnsupportedWorkArea = { workAreaId: string; name: string; reason: string };

/**
 * 그릴 수 없는 구역의 정확한 이름·사유 목록 문구. 그릴 수 있는 구역이
 * 하나도 없을 때도 같은 문구를 쓰므로, 원인이 좌표계가 아닐 때 좌표계
 * 탓으로 돌리지 않는다. 기하를 꾸미지 않으며, 목록 선택을 막지 않는다.
 */
export function unsupportedAreasNote(unsupported: UnsupportedWorkArea[]): string | null {
  if (unsupported.length === 0) return null;
  return `지도에 표시되지 않은 구역 ${unsupported.length}개: `
    + `${unsupported.map((item) => `${item.name}(${item.reason})`).join(" · ")} `
    + "등록된 이름 목록에서는 모두 선택할 수 있으며, 좌표를 추정해 그리지 않습니다.";
}

/**
 * 그릴 수 있는 구역과 지도에 올리지 못한 구역을 나눈다. 못 올린 구역도
 * 이름·사유를 그대로 돌려주므로 호출자가 목록 선택을 막지 않고 누락을
 * 알릴 수 있다. 기하를 꾸미지 않으며, 실패 사유는 표시 전용 문구다.
 */
export function partitionWorkAreaDisplay(
  areas: { workAreaId: string; name: string; polygon: Record<string, unknown>; crs: string }[],
): { supported: SupportedWorkAreaShape[]; unsupported: UnsupportedWorkArea[] } {
  const supported: SupportedWorkAreaShape[] = [];
  const unsupported: UnsupportedWorkArea[] = [];
  for (const area of areas) {
    const display = toDisplayVertices(area.polygon, area.crs);
    if (display.ok) {
      supported.push({ id: area.workAreaId, name: area.name,
        positions: display.vertices.map((vertex) => [vertex.latDeg, vertex.lonDeg]) });
    } else {
      unsupported.push({ workAreaId: area.workAreaId, name: area.name, reason: display.reason });
    }
  }
  return { supported, unsupported };
}
