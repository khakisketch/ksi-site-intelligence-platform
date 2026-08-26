/**
 * Browser-only synthetic Site fixture.
 *
 * This module lives below `e2e/`, outside the production import closure. It
 * deliberately creates no Mission, Gateway receipt, Edge state, processing
 * result, or DJI capability evidence; those remain NOT_VERIFIED until HIL.
 */
export function siteWorkspaceScenario(siteId: string, name = "E2E 현장 작업공간") {
  return {
    siteId,
    name,
    siteFrame: {
      crs: "EPSG:5186",
      verticalDatum: "KNGeoid2018",
      unit: "meter",
      transformVersion: "1.0.0",
    },
    aoi: {
      vertices: [
        { latDeg: 37.5, lonDeg: 127.0 },
        { latDeg: 37.5, lonDeg: 127.001 },
        { latDeg: 37.501, lonDeg: 127.001 },
        { latDeg: 37.501, lonDeg: 127.0 },
      ],
    },
    aiEgressAllowed: false,
  } as const;
}

/**
 * WorkOrder 초안을 만들 수 있는 실제 Core 경로를 위한 최소 작업구역이다. 이 좌표는
 * 브라우저 회귀의 결정적 fixture일 뿐 측량·현장·비행 데이터가 아니다.
 */
export function siteWorkspaceWorkArea(index: number) {
  const origin = 127 + index * 0.01;
  return {
    name: `E2E 작업구역 ${index + 1}`,
    crs: "EPSG:4326",
    polygon: {
      type: "Polygon",
      coordinates: [[
        [origin, 37.5],
        [origin + 0.001, 37.5],
        [origin + 0.001, 37.501],
        [origin, 37.501],
        [origin, 37.5],
      ]],
    },
  } as const;
}
