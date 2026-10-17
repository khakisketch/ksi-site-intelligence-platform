import proj4 from "proj4";
import { describe, expect, it } from "vitest";

import type { AoiVertex } from "@/lib/core-api/types";
import { toZonePolygon } from "@/lib/comparison-submit";
import { toDisplayVertices } from "@/lib/geo/display-geometry";
import { registerKoreaProjections } from "@/lib/geo/proj4-defs";

// U02 P1 — 투영좌표(m) 구역을 위경도(°)로 잘못 읽으면 "다시 그리기"가 지구
// 반대편 수평선이 된다. 이 헬퍼는 알려진 좌표계만 화면용 WGS84로 되돌리고,
// 모르는 것은 막는다. 원본·CRS·계보는 건드리지 않는다.

const SEOnUsquare: AoiVertex[] = [
  { latDeg: 37.5, lonDeg: 127.0 },
  { latDeg: 37.5, lonDeg: 127.1 },
  { latDeg: 37.6, lonDeg: 127.1 },
  { latDeg: 37.6, lonDeg: 127.0 },
];

function to5186(vertices: readonly AoiVertex[]): Record<string, unknown> {
  registerKoreaProjections();
  const ring = vertices.map((v) => proj4("EPSG:4326", "EPSG:5186", [v.lonDeg, v.latDeg]));
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) ring.push([first[0], first[1]]);
  return { type: "Polygon", coordinates: [ring] };
}

describe("toDisplayVertices", () => {
  it("EPSG:4326은 그대로 되돌린다(경도·위도 → 위도·경도)", () => {
    const result = toDisplayVertices(toZonePolygon(SEOnUsquare)!, "EPSG:4326");
    expect(result).toEqual({ ok: true, vertices: SEOnUsquare });
  });

  it("좌표계 표기의 대소문자·여백은 받아들인다", () => {
    const result = toDisplayVertices(toZonePolygon(SEOnUsquare)!, "  epsg:4326 ");
    expect(result.ok).toBe(true);
  });

  it("감사 현장 값 EPSG:5186 [200000,549999.8]을 위경도로 되돌린다 — 미터 값을 도로 읽지 않는다", () => {
    const polygon = {
      type: "Polygon",
      coordinates: [
        [
          [200000, 549999.8],
          [200100, 549999.8],
          [200100, 550099.8],
          [200000, 549999.8],
        ],
      ],
    };
    const result = toDisplayVertices(polygon, "EPSG:5186");
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    // proj4 검증값: [200000,549999.8] → [127.0, 37.5495…].
    expect(result.vertices[0].lonDeg).toBeCloseTo(127.0, 6);
    expect(result.vertices[0].latDeg).toBeCloseTo(37.549516, 5);
    for (const v of result.vertices) {
      expect(Math.abs(v.lonDeg)).toBeLessThanOrEqual(180);
      expect(Math.abs(v.latDeg)).toBeLessThanOrEqual(90);
    }
  });

  it("투영 왕복해도 같은 꼭짓점이다", () => {
    const polygon = to5186(SEOnUsquare);
    const result = toDisplayVertices(polygon, "EPSG:5186");
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.vertices).toHaveLength(SEOnUsquare.length);
    for (const [i, v] of result.vertices.entries()) {
      expect(v.latDeg).toBeCloseTo(SEOnUsquare[i].latDeg, 6);
      expect(v.lonDeg).toBeCloseTo(SEOnUsquare[i].lonDeg, 6);
    }
  });

  it("지원하지 않는 좌표계는 막는다 — EPSG:4326으로 단정하지 않는다", () => {
    for (const crs of ["EPSG:3857", "EPSG:32652", "EPSG:9999", ""]) {
      const result = toDisplayVertices(toZonePolygon(SEOnUsquare)!, crs);
      expect(result.ok).toBe(false);
      if (!result.ok) expect(result.reason).toContain("지원하지 않습니다");
    }
  });

  it("구멍이 있는 폴리곤은 막는다 — 바깥 경계만 보여주지 않는다", () => {
    const outer = (toZonePolygon(SEOnUsquare)! as { coordinates: number[][][] }).coordinates[0];
    const hole = [
      [127.02, 37.52],
      [127.03, 37.52],
      [127.03, 37.53],
      [127.02, 37.52],
    ];
    const result = toDisplayVertices(
      { type: "Polygon", coordinates: [outer, hole] },
      "EPSG:4326",
    );
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toContain("구멍");
  });

  it("MultiPolygon은 막는다", () => {
    const outer = (toZonePolygon(SEOnUsquare)! as { coordinates: number[][][] }).coordinates;
    const result = toDisplayVertices(
      { type: "MultiPolygon", coordinates: [outer] },
      "EPSG:4326",
    );
    expect(result.ok).toBe(false);
  });

  it("NaN·무한대 좌표는 막는다", () => {
    for (const bad of [Number.NaN, Number.POSITIVE_INFINITY]) {
      const result = toDisplayVertices(
        {
          type: "Polygon",
          coordinates: [
            [
              [127.0, 37.5],
              [127.1, 37.5],
              [bad, 37.6],
              [127.0, 37.5],
            ],
          ],
        },
        "EPSG:4326",
      );
      expect(result.ok).toBe(false);
    }
  });

  it("위경도로 주장된 범위를 벗어난 값(투영좌표 오독 서명)은 막는다", () => {
    const result = toDisplayVertices(
      {
        type: "Polygon",
        coordinates: [
          [
            [200000, 549999.8],
            [200100, 549999.8],
            [200100, 550099.8],
            [200000, 549999.8],
          ],
        ],
      },
      "EPSG:4326",
    );
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toContain("범위를 벗어난");
  });

  it("투영좌표 범위를 벗어난 값은 막는다", () => {
    const result = toDisplayVertices(
      {
        type: "Polygon",
        coordinates: [
          [
            [200000, 549999.8],
            [99_000_000, 549999.8],
            [200100, 550099.8],
            [200000, 549999.8],
          ],
        ],
      },
      "EPSG:5186",
    );
    expect(result.ok).toBe(false);
  });

  it("상한을 넘는 꼭짓점은 막는다", () => {
    const ring: number[][] = [];
    for (let i = 0; i < 600; i += 1) {
      ring.push([127.0 + i * 0.00001, 37.5 + (i % 2) * 0.00001]);
    }
    ring.push([...ring[0]]);
    const result = toDisplayVertices({ type: "Polygon", coordinates: [ring] }, "EPSG:4326");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toContain("너무 많습니다");
  });

  it("상한 검사는 점 순회보다 먼저다 — 한계 뒤의 망가진 점까지 돌지 않는다", () => {
    const ring: unknown[] = [];
    for (let i = 0; i < 600; i += 1) {
      ring.push([127.0 + i * 0.00001, 37.5]);
    }
    ring.push("망가진 점");
    const result = toDisplayVertices({ type: "Polygon", coordinates: [ring] }, "EPSG:4326");
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toContain("너무 많습니다");
  });

  it("같은 점만 반복된 링은 막는다 — 선·점을 폴리곤인 것처럼 내지 않는다", () => {
    const samePoint = {
      type: "Polygon",
      coordinates: [[[127.0, 37.5], [127.0, 37.5], [127.0, 37.5], [127.0, 37.5]]],
    };
    const sameResult = toDisplayVertices(samePoint, "EPSG:4326");
    expect(sameResult.ok).toBe(false);
    if (!sameResult.ok) expect(sameResult.reason).toContain("서로 다른 꼭짓점");

    const twoPoints = {
      type: "Polygon",
      coordinates: [[[127.0, 37.5], [127.1, 37.5], [127.0, 37.5]]],
    };
    expect(toDisplayVertices(twoPoints, "EPSG:4326").ok).toBe(false);
  });

  it("실패 사유는 기하·CRS 사실만 적는다 — 호출자별 행동 안내를 섞지 않는다", () => {
    const failures: Array<Record<string, unknown>> = [
      { polygon: toZonePolygon(SEOnUsquare)!, crs: "EPSG:3857" },
      { polygon: {}, crs: "EPSG:4326" },
      {
        polygon: { type: "MultiPolygon", coordinates: [[[[127.0, 37.5]]]] },
        crs: "EPSG:4326",
      },
      {
        polygon: {
          type: "Polygon",
          coordinates: [
            [[127.0, 37.5], [127.1, 37.5], [127.1, 37.6], [127.0, 37.5]],
            [[127.02, 37.52], [127.03, 37.52], [127.03, 37.53], [127.02, 37.52]],
          ],
        },
        crs: "EPSG:4326",
      },
      {
        polygon: {
          type: "Polygon",
          coordinates: [[[200000, 549999.8], [200100, 549999.8], [200100, 550099.8], [200000, 549999.8]]],
        },
        crs: "EPSG:4326",
      },
    ];
    for (const { polygon, crs } of failures) {
      const result = toDisplayVertices(polygon as Record<string, unknown>, crs as string);
      expect(result.ok).toBe(false);
      if (!result.ok) {
        // "다시 그리기" 같은 다음 행동 안내는 정정 호출자가 붙인다.
        expect(result.reason).not.toContain("처음부터 그려");
        expect(result.reason).not.toContain("원래 구역");
      }
    }
  });

  it("망가진 모양은 막는다 — 반쯤 읽은 좌표로 폴리곤을 만들지 않는다", () => {
    const cases: Array<Record<string, unknown>> = [
      {},
      { type: "Polygon" },
      { type: "Polygon", coordinates: [] },
      { type: "Polygon", coordinates: [[[127.0]]] },
      { type: "Polygon", coordinates: [[[127.0, 37.5]]] },
    ];
    for (const polygon of cases) {
      expect(toDisplayVertices(polygon, "EPSG:4326").ok).toBe(false);
    }
  });
});
