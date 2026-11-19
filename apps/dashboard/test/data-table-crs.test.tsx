import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({ default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => createElement("a", { href, ...props }, children) }));

import { DataTable } from "@/app/sites/[siteId]/data/DataTable";
import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";

let counter = 0;
function dsm(crs: string | null, captureDate = "2026-11-04", overrides: Partial<{ kind: string; outcome: string | null }> = {}): SpatialAssetCatalogItem {
  counter += 1;
  return {
    assetRef: `ksa-v1-${String(counter).padStart(64, "0")}`,
    siteId: "site-1",
    workAreaId: "area-1",
    kind: overrides.kind ?? "dsm",
    revision: 1,
    lifecycleState: "SEALED",
    declared: { fileName: `dsm-${counter}.tif`, captureStartedAt: null, captureEndedAt: null, captureDate },
    inspection: {
      state: "INSPECTION_REPORTED",
      outcome: overrides.outcome === undefined ? "MEASURED" : overrides.outcome,
      reason: null,
      raster: crs ? { observedCrsIdentifier: crs } : null,
    },
  } as unknown as SpatialAssetCatalogItem;
}

const render = (items: SpatialAssetCatalogItem[], extra: Partial<Parameters<typeof DataTable>[0]> = {}) =>
  renderToStaticMarkup(
    <DataTable siteId="site-1" workAreaId="area-1" items={items} selectedAssetRef={null} scope={{ workAreaId: "area-1" }} jobs={[]} canRead={false} {...extra} />,
  );

describe("DataTable · coordinate system summary", () => {
  it("summarises mixed CRS with a proportional bar, a legend, and the same color on each row", () => {
    const html = render([dsm("EPSG:5186"), dsm("EPSG:5186"), dsm("EPSG:5186"), dsm("EPSG:32652")]);
    expect(html).toContain("DSM 4건 · 좌표계 2가지");
    expect(html).toContain('data-crs-summary="mixed"');
    expect(html).toContain("한국 중부원점 TM 3건");
    expect(html).toContain("WGS84 UTM 52N 1건");
    expect(html).toContain("비교·체적은 같은 색끼리만 됩니다.");
    // 막대는 건수에 비례하고, 가장 많은 좌표계가 1번 색이다.
    expect(html).toContain("flex:3;background:var(--crs-1)");
    expect(html).toContain("flex:1;background:var(--crs-2)");
    // 행의 좌표 기준 칸도 같은 색 번호를 쓴다.
    expect((html.match(/background:var\(--crs-1\)/g) ?? []).length).toBeGreaterThanOrEqual(5);
    expect(html).toContain("EPSG:32652");
  });

  it("says every DSM can be compared when they share one analysis CRS", () => {
    const html = render([dsm("EPSG:5186"), dsm("EPSG:5186")]);
    expect(html).toContain("DSM 2건 · 좌표계 1가지");
    expect(html).toContain('data-crs-summary="single"');
    expect(html).toContain("모두 같은 좌표계라 서로 비교할 수 있습니다.");
  });

  it("never claims comparability for one CRS the analysis does not accept", () => {
    const html = render([dsm("EPSG:32634"), dsm("EPSG:32634")]);
    expect(html).toContain("분석 안 함");
    expect(html).toContain("분석에 쓰지 않는 좌표계입니다. 보기만 됩니다.");
    expect(html).not.toContain("서로 비교할 수 있습니다");
    // 비교할 수 없는 좌표계에는 범주 색을 주지 않는다(회색).
    expect(html).not.toContain("var(--crs-");
    expect(html).toContain("var(--idle)");
  });

  it("counts the whole page even when a search or filter shows only some rows", () => {
    const all = [dsm("EPSG:5186"), dsm("EPSG:5186"), dsm("EPSG:32652"), dsm("EPSG:32652")];
    const html = render([all[0]!], { summaryItems: all });
    expect(html).toContain("DSM 4건 · 좌표계 2가지");
    expect((html.match(/data-asset-row="true"/g) ?? []).length).toBe(1);
  });

  it("states that only this page was counted when the list continues elsewhere", () => {
    expect(render([dsm("EPSG:5186")], { partial: true })).toContain("이 페이지의 자료 기준입니다.");
    expect(render([dsm("EPSG:5186")])).not.toContain("이 페이지의 자료 기준입니다.");
  });

  it("leaves other kinds, unmeasured files and unknown CRS out of the DSM count and shows no color for them", () => {
    const html = render([dsm("EPSG:5186"), dsm("EPSG:5186", "2026-11-04", { kind: "ortho" }), dsm(null), dsm("EPSG:5186", "2026-11-04", { outcome: "REJECTED" })]);
    expect(html).toContain("DSM 1건 · 좌표계 1가지");
    expect(html).toContain("확인 불가");
  });

  it("adds no summary when no DSM has a measured CRS", () => {
    const html = render([dsm(null), dsm("EPSG:5186", "2026-11-04", { kind: "ortho" })]);
    expect(html).not.toContain("data-crs-summary");
    expect(html).not.toContain("좌표계 1가지");
  });
});
