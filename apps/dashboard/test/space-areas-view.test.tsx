/** @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  site: vi.fn(),
  permissions: vi.fn(),
  areas: vi.fn(),
  orders: vi.fn(),
  analyses: vi.fn(),
  assets: vi.fn(),
  workspace: vi.fn(),
  header: vi.fn(),
  replace: vi.fn(),
}));

vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/permissions", () => ({ hasAllPermissions: mocked.permissions }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ listObservationWorkOrders: mocked.orders }));
vi.mock("@/lib/core-api/analysis", () => ({ listAnalyses: mocked.analyses }));
vi.mock("@/lib/core-api/spatial-assets", () => ({ listSpatialAssets: mocked.assets }));
vi.mock("@/lib/core-api/spatial-workspace", () => ({ listSpatialWorkspaceObservations: mocked.workspace }));
vi.mock("@/app/sites/[siteId]/SiteHeader", () => ({ SiteHeader: mocked.header }));
vi.mock("@/components/map/WorkAreaChoiceMapInner", () => ({
  WorkAreaChoiceMapInner: ({ shapes, selectedId, onSelect }: { shapes: { id: string }[]; selectedId: string; onSelect: (id: string) => void }) =>
    <div data-testid="map-inner" data-selected={selectedId} data-ids={shapes.map((shape) => shape.id).join(",")}>
      <button type="button" onClick={() => onSelect("area-2")}>지도에서 두 번째 영역</button>
    </div>,
}));
vi.mock("next/navigation", () => ({
  notFound: () => { throw new Error("NEXT_NOT_FOUND"); },
  useRouter: () => ({ refresh: () => {}, replace: mocked.replace }),
  redirect: (url: string) => { throw new Error(`NEXT_REDIRECT;replace;${url};307;`); },
}));

import SiteDetailPage from "@/app/sites/[siteId]/page";
import { fireEvent } from "@testing-library/react";

const ring = (x: number) => ({ type: "Polygon", coordinates: [[[x, 37], [x + 0.01, 37], [x + 0.01, 37.01], [x, 37]]] });
const area = (workAreaId: string, name: string, extra: Record<string, unknown> = {}) => ({
  schemaVersion: "v1", workAreaId, siteId: "site-1", name, polygon: ring(127), crs: "EPSG:4326",
  status: "ACTIVE", supersedes: null, createdAt: "2026-11-03T00:00:00Z", ...extra,
});

afterEach(() => { cleanup(); vi.resetAllMocks(); });

beforeEach(() => {
  mocked.header.mockReturnValue(<div data-testid="site-header" />);
  mocked.site.mockResolvedValue({
    siteId: "site-1", name: "현장 하나", status: "UNMAPPED", aoi: null, resumeTarget: null,
    siteFrame: { crs: "EPSG:5186", transformVersion: "v1" },
    registeredAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-01T00:00:00Z",
  });
  mocked.permissions.mockResolvedValue(false);
  mocked.areas.mockResolvedValue({ workAreas: [
    area("area-1", "1영역 북측"),
    area("area-2", "2영역 성토부", { supersedes: "area-0", createdAt: "2026-11-09T00:00:00Z" }),
    area("area-0", "옛 1영역", { status: "ARCHIVED", createdAt: "2026-10-01T00:00:00Z" }),
  ] });
  mocked.orders.mockResolvedValue([]);
});

const openAreas = (query: Record<string, string> = {}) => SiteDetailPage({
  params: Promise.resolve({ siteId: "site-1" }),
  searchParams: Promise.resolve({ panel: "areas", ...query }),
});

describe("공간 영역 보기", () => {
  it("영역 목록과 지도를 함께 두고, 자료·분석 조회는 하지 않는다", async () => {
    render(await openAreas({ workAreaId: "area-2" }));
    const tabs = within(screen.getByRole("navigation", { name: "공간 보기" }));
    expect(tabs.getByRole("link", { name: "영역" }).getAttribute("aria-current")).toBe("page");
    expect(tabs.getByRole("link", { name: "자료" }).getAttribute("href")).toBe("/sites/site-1?workAreaId=area-2");

    const list = within(screen.getByRole("region", { name: "영역 목록" }));
    expect(list.getByText("영역 2개")).toBeTruthy();
    expect(list.getByRole("link", { name: /2영역 성토부/ }).getAttribute("aria-current")).toBe("true");
    expect(list.getByRole("link", { name: /1영역 북측/ }).getAttribute("aria-current")).toBeNull();
    expect(list.getByText(/이전 범위\(옛 1영역\)를 대체/)).toBeTruthy();

    // 지도는 사용 중인 영역만 올린다 — 보관된 영역은 골랐을 때만 올라간다.
    const map = await screen.findByTestId("map-inner");
    expect(map.getAttribute("data-ids")).toBe("area-1,area-2");
    expect(map.getAttribute("data-selected")).toBe("area-2");
    expect(mocked.assets).not.toHaveBeenCalled();
    expect(mocked.analyses).not.toHaveBeenCalled();
    expect(mocked.workspace).not.toHaveBeenCalled();
  });

  it("고른 영역의 자료 보기로 이어지고, 지도에서 고르면 같은 주소 규칙으로 옮긴다", async () => {
    render(await openAreas({ workAreaId: "area-1" }));
    const selected = within(screen.getByRole("region", { name: "고른 영역" }));
    expect(selected.getByRole("link", { name: "이 영역 자료 보기" }).getAttribute("href")).toBe("/sites/site-1?workAreaId=area-1");
    fireEvent.click(await screen.findByRole("button", { name: "지도에서 두 번째 영역" }));
    expect(mocked.replace).toHaveBeenCalledWith("/sites/site-1?panel=areas&workAreaId=area-2", { scroll: false });
  });

  it("쓰기 권한이 없으면 추가·범위 바꾸기·보관 길을 보이지 않는다", async () => {
    render(await openAreas({ workAreaId: "area-1" }));
    expect(screen.queryByRole("link", { name: "범위 바꾸기·보관" })).toBeNull();
    expect(screen.queryByRole("link", { name: "+ 추가" })).toBeNull();
  });

  it("쓰기 권한이 있으면 영역 관리 보기로 이어 준다", async () => {
    mocked.permissions.mockResolvedValue(true);
    render(await openAreas({ workAreaId: "area-1" }));
    expect(screen.getByRole("link", { name: "범위 바꾸기·보관" }).getAttribute("href")).toBe("/sites/site-1?panel=areas&workAreaId=area-1&manage=1");
    expect(screen.getByRole("link", { name: "+ 추가" })).toBeTruthy();
  });

  it("보관된 영역을 고르면 그 영역도 지도에 올리고 범위 바꾸기는 막는다", async () => {
    mocked.permissions.mockResolvedValue(true);
    render(await openAreas({ workAreaId: "area-0" }));
    expect((await screen.findByTestId("map-inner")).getAttribute("data-ids")).toBe("area-1,area-2,area-0");
    expect(screen.queryByRole("link", { name: "범위 바꾸기·보관" })).toBeNull();
    expect(screen.getByText("보관됨")).toBeTruthy();
  });

  it("영역이 없으면 첫 영역을 안내하고, 읽기 실패는 빈 목록으로 단정하지 않는다", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [] });
    render(await openAreas());
    expect(screen.getByText("등록된 영역이 없습니다")).toBeTruthy();
    expect(screen.getByText("영역을 등록하면 이곳 지도에 그려집니다.")).toBeTruthy();
    cleanup();
    mocked.areas.mockRejectedValue(new Error("down"));
    render(await openAreas());
    expect(screen.getByText("영역 목록을 불러오지 못했습니다. 잠시 후 다시 열어 보세요.")).toBeTruthy();
    expect(screen.queryByText("등록된 영역이 없습니다")).toBeNull();
  });
});
