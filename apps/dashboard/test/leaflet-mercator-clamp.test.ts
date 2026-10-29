/** @vitest-environment jsdom */
import { describe, expect, it } from "vitest";

import L from "leaflet";

describe("설치된 Leaflet Web-Mercator 한계 (실측)", () => {
  it("85.0511287798·89·90은 같은 Y로 clamp된다", () => {
    const y85 = L.CRS.EPSG3857.project(L.latLng(85.0511287798, 0)).y;
    const y89 = L.CRS.EPSG3857.project(L.latLng(89, 0)).y;
    const y90 = L.CRS.EPSG3857.project(L.latLng(90, 0)).y;
    // 리뷰어 측정값과 같은 clamp.
    expect(y85).toBe(20037508.34278071);
    expect(y89).toBe(20037508.34278071);
    expect(y90).toBe(20037508.34278071);
    // 89° 입력은 지도에서 85.05°와 같은 픽셀에 그려진다 — 표시가 다르다.
    expect(y89).toBe(y85);
  });

  it("날짜변경선을 가로지르는 경도는 화면 양끝으로 벌어진다", () => {
    const x179 = L.CRS.EPSG3857.project(L.latLng(0, 179)).x;
    const xm179 = L.CRS.EPSG3857.project(L.latLng(0, -179)).x;
    // 같은 자오선 부근인데도 화면상 거리는 지도 전체 너비급이다.
    expect(Math.abs(x179 - xm179)).toBeGreaterThan(30_000_000);
  });
});
