import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ areas: vi.fn(), who: vi.fn() }));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) =>
    createElement("a", { href, ...props }, children),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/sites/site-1/work-areas", notFound: () => { throw new Error("NEXT_NOT_FOUND"); } }));
vi.mock("@/lib/core-api/auth", () => ({ whoAmI: mocked.who }));
vi.mock("@/components/nav/AccountDisplayBoundary", () => ({ AccountDisplayBoundary: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("@/app/sites/[siteId]/work-areas/WorkAreaPanel", () => ({
  WorkAreaPanel: ({ initialWorkAreas, workAreaListError, accountIdentity }: { initialWorkAreas: unknown[]; workAreaListError: { message: string } | null; accountIdentity: { fingerprint: string } | null }) =>
    createElement("div", {
      "data-area-count": initialWorkAreas.length,
      "data-list-error": workAreaListError !== null,
      "data-account-identity": accountIdentity ? accountIdentity.fingerprint : "absent",
    }, workAreaListError?.message ?? "목록 준비됨"),
}));

import { SpaceAreasManage } from "@/app/sites/[siteId]/areas/SpaceAreasManage";
import { CoreApiError } from "@/lib/core-api/client";
import { workAreaListFailure } from "@/app/sites/[siteId]/areas/work-area-list-failure";
import type { SiteView, WorkArea } from "@/lib/core-api/types";

const site = { siteId: "site-1", name: "현장 1", status: "BASELINE_MAPPING", aoi: null, resumeTarget: null, siteFrame: { crs: "EPSG:5186", transformVersion: "v1" }, registeredAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-01T00:00:00Z" } as unknown as SiteView;

// 페이지가 목록을 읽고 실패를 사람 말로 옮긴 뒤 관리 보기에 넘기는 흐름을 같은 모양으로 재현한다.
async function callPage(selectedId: string | null = null) {
  let workAreas: WorkArea[] = [];
  let workAreaError = null;
  try { workAreas = (await mocked.areas(site.siteId, { includeArchived: true })).workAreas; }
  catch (error) { workAreaError = workAreaListFailure(error); }
  return SpaceAreasManage({ site, workAreas, workAreaError, canWrite: false, selectedId });
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.areas.mockResolvedValue({ workAreas: [] });
  mocked.who.mockResolvedValue(null);
});

describe("영역 관리 보기 — 목록 읽기 상태", () => {
  it("처음 읽는 영역 탭으로 돌아가는 길을 고른 영역과 함께 둔다", async () => {
    const html = renderToStaticMarkup(await callPage("area-1"));
    expect(html).toContain("/sites/site-1?panel=areas&amp;workAreaId=area-1");
    expect(html).toContain("지도로 보기");
  });

  it("keeps a successful empty list distinct from a rejected list read", async () => {
    const empty = renderToStaticMarkup(await callPage());
    expect(empty).toContain("data-area-count=\"0\"");
    expect(empty).toContain("data-list-error=\"false\"");

    mocked.areas.mockRejectedValueOnce(new CoreApiError(503, {}, 12));
    const failed = renderToStaticMarkup(await callPage());
    expect(failed).toContain("data-area-count=\"0\"");
    expect(failed).toContain("data-list-error=\"true\"");
    expect(failed).toContain("일시적으로 불러오지 못했습니다.");
  });

  it("gives access-specific guidance for a denied WorkArea read", async () => {
    mocked.areas.mockRejectedValueOnce(new CoreApiError(403, {}));
    const html = renderToStaticMarkup(await callPage());
    expect(html).toContain("프로젝트 담당자에게 조회 권한을 요청하세요.");
    expect(html).toContain("data-list-error=\"true\"");
  });

  it("does not treat a missing WorkArea-list response as an empty site", async () => {
    mocked.areas.mockRejectedValueOnce(new CoreApiError(404, {}));
    const html = renderToStaticMarkup(await callPage());
    expect(html).toContain("현장 영역 목록을 확인할 수 없습니다.");
    expect(html).toContain("data-list-error=\"true\"");
  });

  it("passes the server-verified account fingerprint for guarded retransmit", async () => {
    mocked.who.mockResolvedValue({
      principalId: "alice",
      organizationId: "org-a",
      kind: "OPERATOR",
      role: "FIELD_OPERATOR",
      deviceId: null,
      permissions: ["SITES_READ", "SITES_WRITE"],
    });
    const html = renderToStaticMarkup(await callPage());
    expect(html).toContain("data-account-identity=\"v1-");
  });

  it("leaves the fingerprint empty when identity is unavailable (reads stay open)", async () => {
    mocked.who.mockRejectedValue(new Error("whoami down"));
    const html = renderToStaticMarkup(await callPage());
    expect(html).toContain("data-account-identity=\"absent\"");
    // 목록 읽기는 그대로 시도된다
    expect(html).toContain("data-area-count=\"0\"");
  });
});
