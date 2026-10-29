// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(), site: vi.fn(), areas: vi.fn(), history: vi.fn(),
}));
vi.mock("server-only", () => ({}));
vi.mock("@/lib/core-api/session", () => ({ getSessionToken: vi.fn() }));
vi.mock("@/app/field/resolve-session", () => ({ resolveFieldSession: mocked.session }));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/external-result-workflow", () => ({ listSiteExternalVolumeHistory: mocked.history }));
vi.mock("next/navigation", () => ({
  notFound: () => { throw new Error("NEXT_NOT_FOUND"); },
  useRouter: () => ({ refresh: vi.fn() }),
}));

import SiteObservationHistoryPage from "@/app/sites/[siteId]/observations/page";
import { CoreApiError } from "@/lib/core-api/client";

const callPage = (after?: string) => SiteObservationHistoryPage({
  params: Promise.resolve({ siteId: "site-1" }),
  searchParams: Promise.resolve({ after }),
});

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue({ kind: "ready", principal: {
    principalId: "operator-1", organizationId: "org-1", kind: "OPERATOR",
    role: "FIELD_OPERATOR", deviceId: null, permissions: ["SITES_READ"],
  } });
  mocked.site.mockResolvedValue({ siteId: "site-1", name: "권한 확인된 현장", status: "BASELINE_MAPPING", aoi: null, resumeTarget: null, siteFrame: { crs: "EPSG:5186", transformVersion: "v1" }, registeredAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-01T00:00:00Z" });
  mocked.areas.mockResolvedValue({ workAreas: [] });
  mocked.history.mockResolvedValue({ items: [], nextCursor: null });
});
afterEach(cleanup);

function expectKnownContext() {
  expect(screen.getAllByText("권한 확인된 현장").length).toBeGreaterThan(0);
  expect(screen.getByRole("heading", { name: "외부 비교 기록" })).toBeTruthy();
  // 공통 현장 틀 유지 — 세 영역을 펼침 없이 바로 보인다. 결과 안의 하위
  // 목록에서도 현장 업무 메뉴와 구역 범위를 잃지 않는다.
  const menu = screen.getByRole("navigation", { name: "현장 업무 메뉴" });
  expect(menu).toBeTruthy();
  for (const [label, href] of [
    ["작업공간", "/sites/site-1"],
    ["결과", "/sites/site-1/analysis"],
    ["자료", "/sites/site-1/spatial-assets"],
  ] as const) {
    const links = screen.getAllByRole("link", { name: label });
    expect(links.length).toBeGreaterThan(0);
    expect(links.every((link) => link.getAttribute("href") === href)).toBe(true);
  }
  expect(screen.queryByRole("link", { name: "현장으로 돌아가기" })).toBeNull();
}

it("keeps verified Site context and does not offer futile retry for denied history", async () => {
  mocked.history.mockRejectedValue(new CoreApiError(403, { detail: "denied" }));
  render(await callPage());
  expectKnownContext();
  expect(screen.getByRole("alert").textContent).toContain("현장 담당자에게 조회 권한을 요청하세요.");
  expect(screen.queryByRole("button", { name: "다시 시도" })).toBeNull();
});

it("does not turn a history 404 into Site absence", async () => {
  mocked.history.mockRejectedValue(new CoreApiError(404, { detail: "unavailable" }));
  render(await callPage());
  expectKnownContext();
  expect(screen.getByRole("alert").textContent).toMatch(/불러오지 못/);
});

it("keeps history visible with a notice when only area names fail", async () => {
  mocked.areas.mockRejectedValue(new CoreApiError(503, { detail: "unavailable" }));
  render(await callPage());
  expectKnownContext();
  // 이력은 그대로 보이고, 이름 실패만 따로 알린다.
  expect(screen.queryByRole("alert")).toBeNull();
  const notice = screen.getByRole("status").textContent ?? "";
  expect(notice).toMatch(/작업구역 이름을 불러오지 못했습니다/);
  // 수치 존재를 단정하지 않고 실제 대체 표시를 설명한다.
  expect(notice).toMatch(/이름이 없는 행은 작업구역으로 표시됩니다/);
  expect(notice).not.toMatch(/수치/);
  expect(screen.getByText(/조회된 외부 비교 기록이 없습니다/)).toBeTruthy();
});

it("hides observation creation from history without write permission", async () => {
  render(await callPage());
  // 읽기 전용 고정(권한 SITES_READ)이라 등록 단추는 없다.
  expect(screen.queryByRole("link", { name: "관측 자료 등록" })).toBeNull();
});

it("preserves known context and retry for a transient history failure", async () => {
  mocked.history.mockRejectedValue(new CoreApiError(503, { detail: "unavailable" }, 3));
  render(await callPage());
  expectKnownContext();
  expect(screen.getByRole("button", { name: /다시 시도/ })).toBeTruthy();
});

it("does not let an earlier dependent denial mask an unresolved Site 404", async () => {
  mocked.site.mockImplementation(async () => {
    await Promise.resolve();
    await Promise.resolve();
    throw new CoreApiError(404, { detail: "unknown site" });
  });
  mocked.history.mockRejectedValue(new CoreApiError(403, { detail: "denied" }));
  await expect(callPage()).rejects.toThrow("NEXT_NOT_FOUND");
  expect(mocked.history).not.toHaveBeenCalled();
  expect(mocked.areas).not.toHaveBeenCalled();
});

it("does not disclose a Site name when Site lookup fails transiently", async () => {
  mocked.site.mockRejectedValue(new CoreApiError(503, { detail: "unavailable" }));
  render(await callPage());
  expect(screen.queryByText("권한 확인된 현장")).toBeNull();
  expect(screen.queryByRole("link", { name: "현장으로 돌아가기" })).toBeNull();
  expect(screen.getByRole("alert")).toBeTruthy();
});

it("retains the successful empty-history header and opaque pagination", async () => {
  mocked.history.mockResolvedValue({ items: [], nextCursor: "opaque/cursor" });
  render(await callPage("previous-cursor"));
  expectKnownContext();
  expect(mocked.history).toHaveBeenCalledWith("site-1", { after: "previous-cursor", limit: 50 });
  expect(screen.getByRole("link", { name: "이전 결과 더 보기" }).getAttribute("href"))
    .toBe("/sites/site-1/observations?after=opaque%2Fcursor");
  expect(screen.queryByRole("alert")).toBeNull();
});
