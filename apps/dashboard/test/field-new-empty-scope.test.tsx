/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

const mocked = vi.hoisted(() => ({ listSites: vi.fn() }));
vi.mock("@/app/field/resolve-session", () => ({
  resolveFieldSession: async () => ({
    kind: "ready",
    principal: { permissions: ["SITES_READ", "WORK_ORDERS_WRITE"] },
  }),
}));
vi.mock("@/lib/core-api/cached", () => ({ listSitesCached: mocked.listSites }));

import FieldNewObservationPage from "@/app/field/new/page";

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("관측 자료 등록의 빈 프로젝트 범위", () => {
  it("볼 수 있는 프로젝트이 없으면 기존 현장의 접근 권한 확인 경로를 제공한다", async () => {
    mocked.listSites.mockResolvedValue([]);
    render(await FieldNewObservationPage());
    expect(screen.getByText("현재 계정에서 선택할 수 있는 프로젝트이 없습니다")).toBeTruthy();
    expect(screen.getByText("찾는 프로젝트이 이미 있다면 관리자에게 이 계정의 프로젝트 접근 권한을 확인해 주세요.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "프로젝트 목록" }).getAttribute("href")).toBe("/sites");
    expect(screen.queryByText("먼저 프로젝트을 등록한 뒤 관측을 시작하세요.")).toBeNull();
  });

  it("목록 조회가 실패하면 빈 목록을 단정하지 않는다", async () => {
    mocked.listSites.mockRejectedValue(new Error("unavailable"));
    render(await FieldNewObservationPage());
    expect(screen.queryByText("현재 계정에서 선택할 수 있는 프로젝트이 없습니다")).toBeNull();
    expect(screen.getByText("프로젝트 목록을 불러오지 못했습니다.")).toBeTruthy();
  });
});
