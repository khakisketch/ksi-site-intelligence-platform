import type { GeoTiffRawHeader } from "@/lib/geo/geotiff-header";
import { resolveGeoTiffCrs } from "@/lib/geo/geotiff-overlay";
import { proj4, registerKoreaProjections } from "@/lib/geo/proj4-defs";

/**
 * 올리기 화면이 "이 파일이 선택한 작업구역을 덮는가"를 눈으로 보이게 하는 순수 계산.
 *
 * 파일 머리말의 범위와 좌표계만 쓴다(픽셀을 읽지 않는다). 안내일 뿐 판정이 아니며,
 * 구역 포함 여부를 Core가 거부 조건으로 쓰지도 않는다. 좌표계를 읽지 못하거나 지원하지
 * 않으면 null로 두고 어떤 결론도 만들지 않는다.
 */

/** [경도, 위도]. */
export type LonLat = readonly [number, number];

export type FileFootprint = { crs: string; ring: readonly LonLat[] };

/** 구역이 파일 범위 안에 통째로 있는가(covers), 일부만 걸치는가(partial), 겹치지 않는가(disjoint). */
export type AreaCoverage = "covers" | "partial" | "disjoint";

/** 파일 범위의 네 모서리를 WGS84로 옮긴 사각형. 읽지 못하면 null. */
export function fileFootprintWgs84(header: GeoTiffRawHeader): FileFootprint | null {
  const box = header.boundingBox;
  if (!box || box.length !== 4 || !box.every(Number.isFinite)) return null;
  const [minX, minY, maxX, maxY] = box;
  if (!(minX < maxX) || !(minY < maxY)) return null;
  let crs: string;
  try {
    crs = resolveGeoTiffCrs(header.geoKeys);
  } catch {
    return null;
  }
  registerKoreaProjections();
  try {
    const corners = [[minX, minY], [minX, maxY], [maxX, maxY], [maxX, minY]] as const;
    const ring = corners.map(([x, y]) => {
      const [lon, lat] = proj4(crs, "EPSG:4326", [x, y]);
      return [lon!, lat!] as const;
    });
    if (!ring.every(([lon, lat]) => Number.isFinite(lon) && Number.isFinite(lat) && Math.abs(lon) <= 180 && Math.abs(lat) <= 90)) return null;
    return { crs, ring };
  } catch {
    return null;
  }
}

/** 등록된 작업구역(GeoJSON Polygon, 경도·위도)의 바깥 링. 모양을 신뢰할 수 없으면 null. */
export function areaRingOf(polygon: Record<string, unknown> | null | undefined): LonLat[] | null {
  const ring = (polygon as { coordinates?: unknown[] } | null | undefined)?.coordinates?.[0];
  if (!Array.isArray(ring) || ring.length < 4) return null;
  const points: LonLat[] = [];
  for (const point of ring) {
    if (!Array.isArray(point) || point.length < 2) return null;
    const [lon, lat] = point as unknown[];
    if (typeof lon !== "number" || typeof lat !== "number" || !Number.isFinite(lon) || !Number.isFinite(lat)) return null;
    points.push([lon, lat]);
  }
  const first = points[0]!;
  const last = points[points.length - 1]!;
  if (first[0] === last[0] && first[1] === last[1]) points.pop();
  return points.length >= 3 ? points : null;
}

function insideRing(point: LonLat, ring: readonly LonLat[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]!;
    const [xj, yj] = ring[j]!;
    if ((yi > point[1]) !== (yj > point[1]) && point[0] < ((xj - xi) * (point[1] - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function cross(o: LonLat, a: LonLat, b: LonLat): number {
  return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
}

function segmentsCross(a: LonLat, b: LonLat, c: LonLat, d: LonLat): boolean {
  const d1 = cross(c, d, a);
  const d2 = cross(c, d, b);
  const d3 = cross(a, b, c);
  const d4 = cross(a, b, d);
  return ((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0));
}

/** 구역이 파일 범위와 어떻게 놓이는지. 구역 모양을 읽지 못하면 null. */
export function coverageOfArea(footprint: FileFootprint, areaPolygon: Record<string, unknown> | null | undefined): AreaCoverage | null {
  const area = areaRingOf(areaPolygon);
  if (!area) return null;
  const quad = footprint.ring;
  if (area.every((point) => insideRing(point, quad))) return "covers";
  if (area.some((point) => insideRing(point, quad)) || quad.some((point) => insideRing(point, area))) return "partial";
  for (let i = 0; i < area.length; i += 1) {
    const a = area[i]!;
    const b = area[(i + 1) % area.length]!;
    for (let j = 0; j < quad.length; j += 1) {
      if (segmentsCross(a, b, quad[j]!, quad[(j + 1) % quad.length]!)) return "partial";
    }
  }
  return "disjoint";
}
