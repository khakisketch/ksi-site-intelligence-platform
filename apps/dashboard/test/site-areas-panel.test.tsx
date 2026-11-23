/** @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import { SiteAreasMap } from "@/app/sites/[siteId]/areas/SiteAreasMap";
import { SiteAreasPanel, type AreaAssetsInput } from "@/app/sites/[siteId]/areas/SiteAreasPanel";
import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";
import type { WorkArea } from "@/lib/core-api/types";

afterEach(cleanup);

const square = (x: number, y: number, w: number) => ({
  type: "Polygon",
  coordinates: [[[x, y], [x + w, y], [x + w, y + w], [x, y + w], [x, y]]],
});

function area(id: string, name: string, createdAt: string, x: number, extra: Partial<WorkArea> = {}): WorkArea {
  return {
    schemaVersion: "work-area.v1", workAreaId: id, siteId: "site-1", name, polygon: square(x, 550000, 100), crs: "EPSG:5186",
    status: "ACTIVE", supersedes: null, createdAt, ...extra,
  };
}

let counter = 0;
function dsm(crs: string, captureDate: string): SpatialAssetCatalogItem {
  counter += 1;
  return {
    assetRef: `ksa-v1-${String(counter).padStart(64, "0")}`, siteId: "site-1", workAreaId: "n", kind: "dsm", revision: 1,
    lifecycleState: "SEALED",
    declared: { fileName: `dsm-${counter}.tif`, captureStartedAt: null, captureEndedAt: null, captureDate },
    inspection: { state: "INSPECTION_REPORTED", outcome: "MEASURED", reason: null, raster: { observedCrsIdentifier: crs } },
  } as unknown as SpatialAssetCatalogItem;
}

const north = area("n", "북측 절토부", "2026-11-03T00:00:00Z", 200000);
const road = area("r", "진입로", "2026-11-02T00:00:00Z", 200200);
const yard = area("y", "야적장", "2026-11-01T00:00:00Z", 200400);
const oldRoad = area("old", "진입로 (이전 범위)", "2026-09-14T00:00:00Z", 200600, { status: "ARCHIVED" });
const newRoad = area("r2", "진입로", "2026-10-01T00:00:00Z", 200800, { supersedes: "old" });

const readyAssets = (...items: SpatialAssetCatalogItem[]): AreaAssetsInput => ({ status: "ready", assets: items, hasMore: false });

function panel(over: Partial<React.ComponentProps<typeof SiteAreasPanel>> = {}) {
  return render(
    <SiteAreasPanel
      siteId="site-1"
      sitePath="/sites/site-1"
      areas={[north, road, yard]}
      areasState="ready"
      canWrite="allowed"
      selectedWorkAreaId="n"
      assets={readyAssets(dsm("EPSG:5186", "2026-09-14"), dsm("EPSG:5186", "2026-11-12"))}
      {...over}
    />,
  );
}

describe("SiteAreasPanel · list", () => {
  it("lists active areas newest first with numbered badges, an approximate area and aria-current on the selected one", () => {
    panel({ selectedWorkAreaId: "r" });
    const list = screen.getByRole("list", { name: "사용 중 영역" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((row) => row.querySelector("a")!.textContent)).toEqual([
      expect.stringContaining("북측 절토부"), expect.stringContaining("진입로"), expect.stringContaining("야적장"),
    ]);
    expect(screen.getByText("사용 중 영역 3개")).toBeTruthy();
    const links = within(list).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("aria-current"))).toEqual([null, "true", null]);
    expect(links[1].getAttribute("href")).toBe("/sites/site-1?panel=areas&workAreaId=r");
    expect(links[0].textContent).toContain("약 10,000 ㎡");
    expect(rows[0].textContent).toMatch(/^1/);
    expect(rows[2].textContent).toMatch(/^3/);
  });

  it("gives the list badge the same category colour as the map marker", () => {
    const { container } = panel();
    const badge = within(screen.getByRole("list", { name: "사용 중 영역" })).getAllByRole("link")[1].querySelector("span")!;
    expect(badge.getAttribute("style")).toContain("var(--crs-2)");
    const marker = container.querySelector('[data-areas-map="mini"] [data-area-shape="r"]')!;
    expect(marker).toBeTruthy();
    expect(container.querySelector('[data-areas-map="mini"]')!.innerHTML).toContain("var(--crs-2)");
  });

  it("shows no count or coordinate chip on areas that are not selected, only on the selected one", () => {
    panel({ selectedWorkAreaId: "n" });
    const links = within(screen.getByRole("list", { name: "사용 중 영역" })).getAllByRole("link");
    expect(links[0].textContent).toContain("자료 2건 · 최근 11-12");
    expect(links[0].textContent).toContain("같은 좌표계 · EPSG:5186");
    for (const other of links.slice(1)) {
      expect(other.textContent).not.toMatch(/자료|좌표계|건/);
    }
  });

  it("says the summary covers the most recent 50 when the catalog has more pages", () => {
    panel({ assets: { status: "ready", assets: [dsm("EPSG:5186", "2026-11-12")], hasMore: true } });
    expect(screen.getAllByText(/최근 50건 기준/).length).toBeGreaterThan(0);
  });
});

describe("SiteAreasPanel · coordinate verdicts", () => {
  it("shows mixed coordinate systems as amber and leaves the comparability verdict to the analysis screen", () => {
    panel({ assets: readyAssets(dsm("EPSG:5186", "2026-10-02"), dsm("EPSG:32652", "2026-10-21")) });
    const chip = screen.getByText("좌표계 섞임").closest("span")!;
    expect(chip.className).toContain("bg-high-bg");
    expect(chip.className).not.toContain("crit");
    expect(screen.getByText(/같은 좌표계 자료끼리만 비교할 수 있으며, 가능 여부는 분석 화면에서 확인합니다/)).toBeTruthy();
    // 같은 좌표계끼리는 비교할 수 있으므로 "비교할 수 없다"고 단정하지 않는다.
    expect(screen.queryByText(/비교할 수 없습니다|비교 불가/)).toBeNull();
    expect(screen.getByText(/자료 EPSG:32652 · EPSG:5186/)).toBeTruthy();
  });

  it("does not call the area one coordinate system when only some DSMs were inspected", () => {
    const pending = {
      ...dsm("EPSG:5186", "2026-11-12"),
      inspection: { state: "PENDING", outcome: null, reason: null, raster: null },
    } as unknown as SpatialAssetCatalogItem;
    const { container } = panel({ assets: readyAssets(dsm("EPSG:5186", "2026-09-14"), pending) });
    expect(screen.queryByText("같은 좌표계 · EPSG:5186")).toBeNull();
    expect(screen.getAllByText(/일부만 확인/).length).toBeGreaterThan(0);
    expect(container.querySelector("[data-crs-basis]")!.textContent).toContain("검사가 끝난 DSM 1건(DSM 2건 중) 기준");
  });

  it("reads as not-yet-known when no DSM was inspected", () => {
    panel({ assets: readyAssets() });
    expect(screen.getAllByText("좌표계 확인 전").length).toBeGreaterThan(0);
    expect(screen.queryByText(/비교 불가/)).toBeNull();
  });

  it("does not turn an unreadable catalog into zero materials", () => {
    panel({ assets: { status: "denied" } });
    expect(screen.getAllByText(/자료 목록을 확인하지 못했습니다/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/0건/)).toBeNull();
    panel({ assets: { status: "unavailable" } });
    expect(screen.getAllByText(/자료 목록을 확인하지 못했습니다/).length).toBeGreaterThan(0);
  });
});

describe("SiteAreasPanel · selected area", () => {
  it("names the area, shows facts, the capture-date strip and the shortcuts", () => {
    const { container } = panel();
    const detail = screen.getByRole("region", { name: "고른 영역" });
    expect(within(detail).getByText("북측 절토부")).toBeTruthy();
    expect(within(detail).getByText("사용 중")).toBeTruthy();
    expect(within(detail).getByText("꼭짓점 4개")).toBeTruthy();
    expect(within(detail).getByText("구역 EPSG:5186")).toBeTruthy();
    expect(within(detail).getByRole("img", { name: "자료 날짜: 9월 14일, 11월 12일" })).toBeTruthy();
    expect(within(detail).getByRole("link", { name: "이 영역 자료 보기" }).getAttribute("href")).toBe("/sites/site-1/data?workAreaId=n");
    expect(within(detail).getByRole("link", { name: "선 단면 그리기" }).getAttribute("href")).toBe("/sites/site-1/measurements/new?workAreaId=n");
    expect(container.querySelector("[data-areas-detail]")).toBeTruthy();
  });

  it("never makes volume comparison look open: it is a locked link with the reason and a pointer to the analysis screen", () => {
    panel();
    const note = document.querySelector("[data-volume-compare-lock]")!;
    expect(note.textContent).toContain("체적 비교는 기본 잠김입니다. 두 날짜의 독립 근거와 호환성 승인이 있어야 열립니다.");
    expect(note.textContent).toContain("열림 여부는 분석 화면에서 확인합니다.");
    expect(within(note as HTMLElement).getByRole("link", { name: "분석 화면" }).getAttribute("href")).toBe("/sites/site-1/analysis?workAreaId=n");
    expect(document.body.textContent).not.toMatch(/체적 비교(가|를)? (열|가능)/);
  });
});

describe("SiteAreasPanel · archived", () => {
  it("folds archived areas away, read-only: no unarchive control, deletion and kept results explained", () => {
    const { container } = panel({ areas: [north, oldRoad, newRoad] });
    const details = container.querySelector("details[data-areas-archived]") as HTMLDetailsElement;
    expect(details).toBeTruthy();
    expect(details.hasAttribute("open")).toBe(false);
    expect(within(details).getByText("보관된 영역 1개")).toBeTruthy();
    expect(details.textContent).toContain("삭제 아님 · 이미 낸 결과 유지");
    expect(details.textContent).toContain("새 비교에서는 고를 수 없습니다");
    expect(details.textContent).toContain("09-14 등록 · 새 범위로 대체");
    expect(screen.queryByRole("button", { name: /해제|되돌리|복구|보관 취소/ })).toBeNull();
    expect(document.body.textContent).not.toMatch(/보관 해제|되돌리기|복구/);
  });

  it("opens an archived area read-only: no edit, no line profile, no comparison lock", () => {
    panel({ areas: [north, oldRoad, newRoad], selectedWorkAreaId: "old" });
    const detail = screen.getByRole("region", { name: "고른 영역" });
    expect(within(detail).getByText("보관됨")).toBeTruthy();
    expect(within(detail).getByRole("link", { name: "지난 자료 보기" })).toBeTruthy();
    expect(detail.textContent).toContain("새 범위로 대체되었습니다");
    expect(within(detail).queryByRole("link", { name: /영역 편집|선 단면/ })).toBeNull();
    expect(detail.querySelector("[data-volume-compare-lock]")).toBeNull();
  });
});

describe("SiteAreasPanel · permission", () => {
  it("offers draw and edit only to writers, and blocks both under 1024px with a continue-on-laptop notice", () => {
    panel();
    expect(screen.getByRole("link", { name: "영역 그리기" }).getAttribute("href")).toBe("/sites/site-1/work-areas");
    expect(screen.getByRole("link", { name: "영역 편집" }).getAttribute("href")).toBe("/sites/site-1/work-areas?workAreaId=n");
    const notice = document.querySelector('[data-responsive-action-notice="SITE_DEVICE_TRANSITION"]')!;
    expect(notice.textContent).toContain("노트북에서 이어서 하기");
    expect(notice.className).toContain("lg:hidden");
    expect(document.querySelector("[data-area-draw]")!.closest(".lg\\:contents")).toBeTruthy();
    expect(document.querySelector("[data-area-edit]")!.closest(".lg\\:contents")).toBeTruthy();
    expect(screen.getByText(/새 영역을 등록하고 이전 영역을 보관합니다/)).toBeTruthy();
  });

  it("view-only users get no draw/edit link, a plain note, and still reach the materials", () => {
    panel({ canWrite: "denied" });
    expect(screen.queryByRole("link", { name: /영역 그리기|영역 편집/ })).toBeNull();
    expect(screen.getByText("보기만 가능 · 편집은 담당자에게 요청")).toBeTruthy();
    expect(screen.getByRole("link", { name: "이 영역 자료 보기" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "선 단면 그리기" })).toBeNull();
    expect(document.querySelector('[data-responsive-action-notice]')).toBeNull();
  });

  it("does not claim a denial when the permission is unknown", () => {
    panel({ canWrite: "unknown" });
    expect(screen.queryByRole("link", { name: /영역 그리기|영역 편집/ })).toBeNull();
    expect(screen.getByText(/편집 권한을 확인하지 못해 보기만 가능합니다/)).toBeTruthy();
    expect(screen.queryByText(/보기만 가능 · 편집은 담당자에게 요청/)).toBeNull();
  });
});

describe("SiteAreasPanel · states", () => {
  it("invites writers to draw the first area, and tells others to ask the site owner", () => {
    panel({ areas: [], selectedWorkAreaId: null });
    expect(screen.getByText("아직 영역이 없습니다")).toBeTruthy();
    expect(screen.getByRole("link", { name: "첫 영역 그리기" }).getAttribute("href")).toBe("/sites/site-1/work-areas");
    cleanup();
    panel({ areas: [], selectedWorkAreaId: null, canWrite: "denied" });
    expect(screen.queryByRole("link", { name: "첫 영역 그리기" })).toBeNull();
    expect(screen.getByText("영역 등록 권한이 없습니다. 현장 담당자에게 문의하세요.")).toBeTruthy();
  });

  it("explains a denied list, and offers reload for an unavailable one", () => {
    panel({ areas: [], areasState: "denied", selectedWorkAreaId: null });
    expect(screen.getByRole("alert").textContent).toContain("영역 목록을 조회할 권한이 없습니다");
    cleanup();
    panel({ areas: [], areasState: "unavailable", selectedWorkAreaId: null });
    expect(screen.getByRole("alert").textContent).toContain("영역 목록을 불러오지 못했습니다");
    expect(screen.getByRole("button", { name: "영역 목록 다시 불러오기" })).toBeTruthy();
  });
});

describe("SiteAreasMap", () => {
  const mixedPlane = [north, road, { ...yard, workAreaId: "utm", crs: "EPSG:32652", polygon: square(300000, 4000000, 100) }];

  it("draws every active area, outlines the selected one, and states the display-only caveat", () => {
    const { container } = render(<SiteAreasMap areas={[north, road, yard]} selectedWorkAreaId="r" variant="stage" />);
    expect(container.querySelectorAll("[data-area-shape]")).toHaveLength(3);
    expect(container.querySelector('[data-area-shape="r"]')!.getAttribute("data-selected")).toBe("true");
    expect(container.querySelector('[data-area-shape="n"]')!.getAttribute("data-selected")).toBeNull();
    expect(screen.getByText("영역 3개")).toBeTruthy();
    expect(screen.getByText("영역 경계는 화면 표시용이며 분석 적합성을 뜻하지 않습니다.")).toBeTruthy();
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("진입로 선택됨");
    expect(container.innerHTML).not.toMatch(/모두 현장 범위 안/);
  });

  it("leaves areas on another coordinate plane off the map and says how many", () => {
    const { container } = render(<SiteAreasMap areas={mixedPlane} selectedWorkAreaId="n" variant="stage" />);
    expect(container.querySelectorAll("[data-area-shape]")).toHaveLength(2);
    expect(container.querySelector("[data-areas-map-omitted]")!.textContent).toBe("지도에 올리지 못한 영역 1개");
  });

  it("says so instead of drawing nothing when no area can be placed", () => {
    const multi = { ...north, polygon: { type: "MultiPolygon", coordinates: [square(0, 0, 10).coordinates] } };
    const { container } = render(<SiteAreasMap areas={[multi]} selectedWorkAreaId="n" variant="stage" />);
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.getByText("지도에 올릴 수 있는 영역이 없습니다.")).toBeTruthy();
  });
});
