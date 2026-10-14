/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SiteView } from "@/lib/core-api/types";

function site(overrides: Partial<SiteView> = {}): SiteView {
  return {
    siteId: "site-1",
    name: "A 현장",
    siteFrame: { crs: "EPSG:5186", verticalDatum: "EGM2008", unit: "meter", transformVersion: "v1" },
    status: "UNMAPPED",
    resumeTarget: null,
    registeredAt: "2026-09-01T00:00:00Z",
    updatedAt: "2026-09-01T00:00:00Z",
    aoi: null,
    dataResidency: null,
    aiEgressAllowed: false,
    modelMaxAgeDays: null,
    ...overrides,
  };
}

const mockedSession = vi.hoisted(() => ({
  resolve: async (): Promise<unknown> => ({ kind: "ready", principal: { kind: "OPERATOR", organizationId: "org-1", role: "ADMIN", principalId: "operator-a", deviceId: null, permissions: ["SITES_READ", "SITES_WRITE", "WORK_ORDERS_WRITE"] } }),
}));

vi.mock("@/app/field/resolve-session", () => ({
  resolveFieldSession: () => mockedSession.resolve(),
}));
vi.mock("@/lib/core-api/cached", () => ({
  listSitesCached: async () => [
    site({ siteId: "site-1", name: "A 현장", status: "UNMAPPED" }),
    site({ siteId: "site-2", name: "B 현장", status: "PATROL_READY" }),
  ],
}));

import FieldNewObservationPage from "@/app/field/new/page";

afterEach(cleanup);

describe("field/new site rows", () => {
  it("differentiates rows by each site's own status instead of repeating one sentence", async () => {
    render(await FieldNewObservationPage());
    expect(screen.queryByText("이 현장에서 외부 산출물 등록 또는 비행 계획을 시작합니다.")).toBeNull();
    expect(screen.getByText("미매핑")).toBeTruthy();
    expect(screen.getByText("순찰 준비 완료")).toBeTruthy();
  });

  it("blocks viewers before site selection with a guided next action", async () => {
    mockedSession.resolve = async () => ({
      kind: "ready",
      principal: { kind: "OPERATOR", organizationId: "org-1", role: "VIEWER", principalId: "viewer-1", deviceId: null, permissions: ["SITES_READ"] },
    });
    try {
      render(await FieldNewObservationPage());
      expect(screen.getByText("새 관측을 등록할 권한이 없습니다")).toBeTruthy();
      expect(screen.getByRole("link", { name: "작업으로 돌아가기" })).toBeTruthy();
      expect(screen.queryByText("A 현장")).toBeNull();
    } finally {
      mockedSession.resolve = async (): Promise<unknown> => ({ kind: "ready", principal: { kind: "OPERATOR", organizationId: "org-1", role: "ADMIN", principalId: "operator-a", deviceId: null, permissions: ["SITES_READ", "SITES_WRITE", "WORK_ORDERS_WRITE"] } });
    }
  });
});
