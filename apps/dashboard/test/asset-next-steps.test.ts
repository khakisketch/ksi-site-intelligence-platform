import { describe, expect, it } from "vitest";

import { assetNextSteps } from "@/lib/asset-next-steps";

const assetRef = `ksa-v1-${"a".repeat(64)}`;
const base = { siteId: "site 1", workAreaId: "area/1", assetRef, kind: "dsm", lifecycleState: "SEALED", inspection: { outcome: "MEASURED", state: "COMPLETED" } };

describe("assetNextSteps", () => {
  it("검사된 DSM 은 공간 보기와 측정 선 단면 읽기를 구역 범위와 함께 안내한다", () => {
    expect(assetNextSteps(base)).toEqual([
      { key: "viewer", label: "공간에서 보기", href: `/sites/site%201?workAreaId=area%2F1&assetRef=${assetRef}` },
      { key: "measurements", label: "측정 선에서 단면 읽기", href: `/sites/site%201/measurements?workAreaId=area%2F1&assetRef=${assetRef}` },
    ]);
  });

  it("정사영상은 공간 보기만 안내한다", () => {
    expect(assetNextSteps({ ...base, kind: "ortho" })).toEqual([
      { key: "viewer", label: "공간에서 보기", href: `/sites/site%201?workAreaId=area%2F1&assetRef=${assetRef}` },
    ]);
  });

  it("실제 격자 좌표계가 단면 지원 범위 밖인 DSM은 공간 보기만 연다", () => {
    const asset = { ...base, inspection: { ...base.inspection, raster: { observedCrsIdentifier: "EPSG:32634" } } };
    expect(assetNextSteps(asset).map(({ key }) => key)).toEqual(["viewer"]);
  });

  it("검사로 파일 정보가 확인되지 않았거나 실패·미제출·이전 등록이면 아무것도 안내하지 않는다", () => {
    expect(assetNextSteps({ ...base, inspection: { outcome: null, state: "PENDING" } })).toEqual([]);
    expect(assetNextSteps({ ...base, inspection: { outcome: "REJECTED", state: "COMPLETED" } })).toEqual([]);
    expect(assetNextSteps({ ...base, inspection: { outcome: "MEASURED", state: "FAILED" } })).toEqual([]);
    expect(assetNextSteps({ ...base, lifecycleState: "UNSEALED" })).toEqual([]);
    expect(assetNextSteps({ ...base, lifecycleState: "SUPERSEDED" })).toEqual([]);
  });
});
