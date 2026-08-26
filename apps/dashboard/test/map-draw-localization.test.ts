import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const mapSource = fs.readFileSync(
  path.resolve(process.cwd(), "src/components/map/AoiPolygonMapInner.tsx"),
  "utf8",
);

describe("AOI 지도 편집 접근성", () => {
  it("Leaflet Draw 제어의 운영자용 안내를 한국어로 제공한다", () => {
    expect(mapSource).toContain("function applyKoreanDrawLabels");
    expect(mapSource).toContain("현장 범위 다각형 그리기");
    expect(mapSource).toContain("현장 범위 편집");
    expect(mapSource).toContain("현장 범위 삭제");
    expect(mapSource).toContain("저장");
    expect(mapSource).toContain("취소");
  });
});
