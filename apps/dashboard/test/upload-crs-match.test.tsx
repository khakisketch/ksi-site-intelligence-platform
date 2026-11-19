/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) => createElement("a", { href, ...props }, children),
}));

import { UploadScreen, type UploadScreenDeps } from "@/app/sites/[siteId]/upload/UploadScreen";
import type { AreaDsmCrs } from "@/lib/crs-match";
import type { GeoTiffRawHeader } from "@/lib/geo/geotiff-header";
import { inspectCandidate } from "@/lib/site-upload-files";

const layout = {
  compression: 8, predictor: 1, photometric: 1, planarConfiguration: 1, extraSamples: [], hasNoDataTag: true, scale: null, offset: null,
  georeferenced: true, modelType: 1, projLinearUnits: 9001, verticalCsType: null, verticalUnits: null,
};
const dsmIn = (projectedCs: number, boundingBox: [number, number, number, number]): GeoTiffRawHeader => ({
  width: 100, height: 100, samplesPerPixel: 1, bitsPerSample: 32, sampleFormat: 3, geoKeys: { ProjectedCSTypeGeoKey: projectedCs },
  software: null, dateTime: null, pixelSize: [1, 1], boundingBox, layout,
});
const headers: Record<string, GeoTiffRawHeader> = {
  "korea.tif": dsmIn(5186, [200000, 550000, 201000, 551000]),
  "utm.tif": dsmIn(32652, [300000, 3900000, 301000, 3901000]),
  "bessel.tif": dsmIn(5174, [200000, 550000, 201000, 551000]),
  "ortho.tif": { ...dsmIn(5186, [200000, 550000, 201000, 551000]), samplesPerPixel: 3, bitsPerSample: 8, sampleFormat: 1, layout: { ...layout, photometric: 2 } },
};
const file = (name: string) => Object.defineProperty(new File([new Uint8Array(1)], name), "size", { value: 1234 }) as File;

const area = (groups: Array<[string, number]>, truncated = false): AreaDsmCrs => ({
  groups: groups.map(([crs, count]) => ({ crs, count, firstDate: "2026-10-02", lastDate: "2026-11-04" })),
  total: groups.reduce((sum, [, count]) => sum + count, 0),
  truncated,
});

function deps(): UploadScreenDeps {
  return {
    inspect: (f, id, polygon) => inspectCandidate(f, id, polygon, { read: async () => headers[f.name]! }),
    hash: async (f) => ({ file: f, sha256: "a".repeat(64), size: f.size }),
    createSession: () => ({ run: async () => ({ workOrderId: "wo-1", submissionRef: "ers-v1-ref", revision: 1 }) }),
    readInspection: async () => null,
  };
}

async function open(areaDsmCrs: Record<string, AreaDsmCrs | null> | undefined, names: string[]) {
  render(
    <UploadScreen
      siteId="site-1" siteName="북측 현장" initialWorkAreaId={null}
      workAreas={[{ workAreaId: "wa-1", name: "북측 1차 구역", polygon: null }]}
      accountIdentity={{ fingerprint: `v1-${"e".repeat(64)}` }}
      areaDsmCrs={areaDsmCrs} deps={deps()}
    />,
  );
  await act(async () => { fireEvent.change(screen.getByLabelText("자료 파일 고르기"), { target: { files: names.map(file) } }); });
}

const block = () => screen.getByRole("group", { name: "좌표계 대조" });

afterEach(cleanup);

describe("upload screen · coordinate system match", () => {
  it("shows a green 'comparable' band when the file shares the CRS of every DSM in the area", async () => {
    await open({ "wa-1": area([["EPSG:5186", 3]]) }, ["korea.tif"]);
    expect(block().getAttribute("data-crs-match")).toBe("same");
    expect(within(block()).getByRole("status").textContent).toBe("이 구역 DSM 3건과 비교할 수 있습니다");
    // 이 파일 줄과 구역의 기존 DSM 줄에 같은 좌표계 이름이 나란히 보인다.
    expect(within(block()).getAllByText("한국 중부원점 TM")).toHaveLength(2);
    expect(within(block()).getByRole("list", { name: "이 구역에 있는 DSM의 좌표계" }).textContent).toContain("3건 · 10/2~11/4");
    expect(within(block()).getAllByRole("img").map((icon) => icon.getAttribute("aria-label"))).toEqual(["같은 좌표계"]);
    expect(within(block()).queryByText("어떻게 하면 되나요")).toBeNull();
  });

  it("tells the operator the CRS differs, explains what still works, and where to set the output CRS", async () => {
    await open({ "wa-1": area([["EPSG:5186", 3]]) }, ["utm.tif"]);
    expect(block().getAttribute("data-crs-match")).toBe("different");
    expect(within(block()).getByRole("status").textContent).toBe("이 구역 DSM 3건과 좌표계가 달라 비교할 수 없습니다");
    const guide = within(block()).getByText("어떻게 하면 되나요").closest("details")!;
    expect(guide.textContent).toContain("이 파일만으로 보기·높이·단면은 됩니다");
    expect(guide.textContent).toContain("WGS84 UTM은 출력 좌표계를 따로 정하지 않았을 때");
    expect(guide.textContent).toContain("한국 중부원점 TM · EPSG:5186으로 다시 내보내려면");
    expect(guide.textContent).toContain("Select Output Coordinate System");
    expect(guide.textContent).toContain("Export DEM");
    expect(guide.textContent).toContain("프로그램 문서를 확인하세요");
  });

  it("counts same and different DSMs separately when the area already mixes CRS", async () => {
    await open({ "wa-1": area([["EPSG:5186", 1], ["EPSG:32652", 2]]) }, ["korea.tif"]);
    expect(block().getAttribute("data-crs-match")).toBe("mixed");
    expect(within(block()).getByRole("status").textContent).toBe("같은 좌표계 1건 · 다른 좌표계 2건");
    // 좌표계 줄마다 같음/다름 표시가 따로 붙는다(띠의 아이콘은 장식이라 읽히지 않는다).
    expect(within(block()).getAllByRole("img").map((icon) => icon.getAttribute("aria-label"))).toEqual(["같은 좌표계", "다른 좌표계"]);
  });

  it("names the first DSM of an area without inventing a comparison", async () => {
    await open({ "wa-1": area([]) }, ["korea.tif"]);
    expect(block().getAttribute("data-crs-match")).toBe("first");
    expect(within(block()).getByRole("status").textContent).toBe("이 구역의 첫 DSM입니다");
    expect(within(block()).queryByRole("list", { name: "이 구역에 있는 DSM의 좌표계" })).toBeNull();
  });

  it("says a CRS outside analysis support only allows viewing and uploading, never 'comparable'", async () => {
    await open({ "wa-1": area([["EPSG:5174", 3]]) }, ["bessel.tif"]);
    expect(block().getAttribute("data-crs-match")).toBe("not-analysis");
    expect(within(block()).getByRole("status").textContent).toBe("분석에 쓰지 않는 좌표계입니다. 보기와 올리기만 됩니다");
    expect(within(block()).queryByLabelText("같은 좌표계")).toBeNull();
    expect(block().textContent).toContain("EPSG:5179·5185~5188");
  });

  it("colors only the CRS the analysis accepts and leaves the rest gray", async () => {
    // 이 파일(5186)은 분석 좌표계라 색이 있고, 구역의 기존 DSM(32634)은 분석 밖이라 회색이다.
    await open({ "wa-1": area([["EPSG:32634", 2]]) }, ["korea.tif"]);
    const tiles = within(block()).getAllByText(/EPSG:/).map((node) => node.closest("div.rounded-lg")!);
    const swatchOf = (tile: Element) => (tile.querySelector("span[aria-hidden=true]") as HTMLElement).style.background;
    expect(swatchOf(tiles[0]!)).toBe("var(--crs-1)");
    expect(swatchOf(tiles[1]!)).toBe("var(--idle)");
    cleanup();
    await open({ "wa-1": area([["EPSG:5186", 3]]) }, ["bessel.tif"]);
    const file = within(block()).getAllByText(/EPSG:/).map((node) => node.closest("div.rounded-lg")!)[0]!;
    expect(swatchOf(file)).toBe("var(--idle)");
  });

  it("notes that only recent files were checked when the area has more than one page", async () => {
    await open({ "wa-1": area([["EPSG:5186", 50]], true) }, ["korea.tif"]);
    expect(block().textContent).toContain("최근 50건 기준입니다");
  });

  it("does not repeat a healthy CRS chip next to the match block, but keeps a warning chip", async () => {
    await open({ "wa-1": area([["EPSG:5186", 3]]) }, ["korea.tif"]);
    const card = screen.getByRole("region", { name: "DSM (높이)" });
    expect(within(card).queryByText("EPSG:5186", { selector: "span" })).toBeNull();
    cleanup();
    await open({ "wa-1": area([["EPSG:5186", 3]]) }, ["bessel.tif"]);
    expect(within(screen.getByRole("region", { name: "DSM (높이)" })).getByText("분석 좌표계 아님")).toBeTruthy();
  });

  it("adds nothing when the area's files could not be read or the screen was not given them", async () => {
    await open({ "wa-1": null }, ["korea.tif"]);
    expect(screen.queryByRole("group", { name: "좌표계 대조" })).toBeNull();
    cleanup();
    await open(undefined, ["korea.tif"]);
    expect(screen.queryByRole("group", { name: "좌표계 대조" })).toBeNull();
  });

  it("compares only the DSM card, not the orthophoto", async () => {
    await open({ "wa-1": area([["EPSG:5186", 3]]) }, ["ortho.tif"]);
    expect(screen.queryByRole("group", { name: "좌표계 대조" })).toBeNull();
  });
});
