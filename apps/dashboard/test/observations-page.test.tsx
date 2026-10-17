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
  mocked.site.mockResolvedValue({ name: "권한 확인된 현장" });
  mocked.areas.mockResolvedValue({ workAreas: [] });
  mocked.history.mockResolvedValue({ items: [], nextCursor: null });
});
afterEach(cleanup);

function expectKnownContext() {
  expect(screen.getByText("권한 확인된 현장")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "외부 비교 기록" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "현장으로 돌아가기" }).getAttribute("href")).toBe("/sites/site-1");
  expect(screen.getByRole("link", { name: "변화 분석" }).getAttribute("href")).toBe("/sites/site-1/analysis");
  expect(screen.getByRole("link", { name: "등록 자료" }).getAttribute("href")).toBe("/sites/site-1/spatial-assets");
}

it("keeps verified Site context and does not offer futile retry for denied history", async () => {
  mocked.history.mockRejectedValue(new CoreApiError(403, { detail: "denied" }));
  render(await callPage());
  expectKnownContext();
  expect(screen.getByRole("alert").textContent).toContain("현장 담당자에게 조회 권한을 요청하세요.");
  expect(screen.queryByRole("button", { name: "다시 시도" })).toBeNull();
});

it.each(["history", "areas"] as const)("does not turn a %s 404 into Site absence", async (dependency) => {
  mocked[dependency].mockRejectedValue(new CoreApiError(404, { detail: "unavailable" }));
  render(await callPage());
  expectKnownContext();
  expect(screen.getByRole("alert").textContent).toMatch(/불러오지 못/);
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
