import { describe, expect, it } from "vitest";

import { toZonePolygon } from "@/lib/comparison-submit";
import { partitionWorkAreas, polygonToVertices } from "@/lib/work-areas";
import type { AoiVertex, WorkArea } from "@/lib/core-api/types";

// 작업구역은 **기하가 굳는다**(M4-C). 그래서 "다시 그리기"가 유일한 정정 경로이고,
// 그 경로는 등록된 GeoJSON 을 지도 좌표로 되돌리는 데서 시작한다 — 이 되돌리기가
// 틀리면 사용자는 엉뚱한 범위를 고쳐 그려 등록하고, 그 결과가 리포트 범위가 된다.

function area(overrides: Partial<WorkArea> & { workAreaId: string }): WorkArea {
  return {
    schemaVersion: "1.0.0",
    siteId: "site-1",
    name: "구역",
    polygon: { type: "Polygon", coordinates: [[]] },
    crs: "EPSG:4326",
    status: "ACTIVE",
    supersedes: null,
    createdAt: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

const SQUARE: AoiVertex[] = [
  { latDeg: 37.5, lonDeg: 127.0 },
  { latDeg: 37.5, lonDeg: 127.1 },
  { latDeg: 37.6, lonDeg: 127.1 },
  { latDeg: 37.6, lonDeg: 127.0 },
];

describe("polygonToVertices", () => {
  it("toZonePolygon 의 역이다 — 왕복해도 같은 꼭짓점이다", () => {
    const polygon = toZonePolygon(SQUARE);
    expect(polygon).not.toBeNull();
    expect(polygonToVertices(polygon!)).toEqual(SQUARE);
  });

  it("경도·위도 순을 위도·경도로 되돌린다 — 뒤집으면 지구 반대편이 된다", () => {
    const vertices = polygonToVertices({
      type: "Polygon",
      coordinates: [
        [
          [127.0, 37.5],
          [127.1, 37.5],
          [127.1, 37.6],
          [127.0, 37.5],
        ],
      ],
    });
    expect(vertices[0]).toEqual({ latDeg: 37.5, lonDeg: 127.0 });
  });

  it("닫힌 링을 한 번만 연다 — 정정할 때마다 꼭짓점이 늘어나면 안 된다", () => {
    const once = polygonToVertices(toZonePolygon(SQUARE)!);
    const twice = polygonToVertices(toZonePolygon(once)!);
    expect(twice).toEqual(once);
    expect(twice).toHaveLength(4);
  });

  it("닫히지 않은 링은 그대로 둔다", () => {
    const vertices = polygonToVertices({
      coordinates: [
        [
          [127.0, 37.5],
          [127.1, 37.5],
          [127.1, 37.6],
        ],
      ],
    });
    expect(vertices).toHaveLength(3);
  });

  it("읽어낼 수 없는 모양은 빈 배열이다 — 반쯤 읽은 좌표로 폴리곤을 만들지 않는다", () => {
    expect(polygonToVertices(null)).toEqual([]);
    expect(polygonToVertices(undefined)).toEqual([]);
    expect(polygonToVertices({})).toEqual([]);
    expect(polygonToVertices({ coordinates: "nope" })).toEqual([]);
    expect(polygonToVertices({ coordinates: [[[127.0]]] })).toEqual([]);
    expect(polygonToVertices({ coordinates: [[["127.0", "37.5"]]] })).toEqual([]);
  });
});

describe("partitionWorkAreas", () => {
  it("고를 수 있는 것과 보관된 것을 가른다", () => {
    const { active, archived } = partitionWorkAreas([
      area({ workAreaId: "wa-1" }),
      area({ workAreaId: "wa-2", status: "ARCHIVED" }),
    ]);
    expect(active.map((a) => a.workAreaId)).toEqual(["wa-1"]);
    expect(archived.map((a) => a.workAreaId)).toEqual(["wa-2"]);
  });

  it("최신 등록이 위다 — 서버 응답 순서에 기대지 않는다", () => {
    const { active } = partitionWorkAreas([
      area({ workAreaId: "old", createdAt: "2026-08-01T00:00:00Z" }),
      area({ workAreaId: "new", createdAt: "2026-08-09T00:00:00Z" }),
      area({ workAreaId: "mid", createdAt: "2026-08-05T00:00:00Z" }),
    ]);
    expect(active.map((a) => a.workAreaId)).toEqual(["new", "mid", "old"]);
  });

  it("입력 배열을 뒤집어 놓지 않는다", () => {
    const input = [area({ workAreaId: "a", createdAt: "2026-08-01T00:00:00Z" }), area({ workAreaId: "b", createdAt: "2026-08-09T00:00:00Z" })];
    partitionWorkAreas(input);
    expect(input.map((a) => a.workAreaId)).toEqual(["a", "b"]);
  });
});
