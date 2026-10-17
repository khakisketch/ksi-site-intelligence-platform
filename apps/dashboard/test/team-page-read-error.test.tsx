/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const rosterMock = vi.hoisted(() => ({
  implementation: async (): Promise<unknown> => ({ members: [] }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/field/team",
  useRouter: () => ({ refresh: vi.fn() }),
}));
vi.mock("@/app/field/resolve-session", () => ({
  resolveFieldSession: async () => ({ kind: "ready", principal: { role: "ADMIN", principalId: "operator-a" } }),
}));
vi.mock("@/lib/core-api/work-collaboration", () => ({
  listOrganizationWorkRoster: (...args: unknown[]) => (rosterMock.implementation as (...callArgs: unknown[]) => Promise<unknown>)(...args),
}));
vi.mock("@/app/field/team/TeamRosterPanel", () => ({ TeamRosterPanel: () => null }));

import { CoreApiError } from "@/lib/core-api/client";
import FieldTeamPage from "@/app/field/team/page";

afterEach(() => {
  cleanup();
  rosterMock.implementation = async () => ({ members: [] });
});

describe("field team read errors", () => {
  it("explains a permission denial with a queue return path and no retry", async () => {
    rosterMock.implementation = async () => { throw new CoreApiError(403, {}); };
    render(await FieldTeamPage());
    expect(screen.getByText(/조회할 권한이 없습니다/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "작업으로 돌아가기" }).getAttribute("href")).toBe("/field");
    expect(screen.queryByRole("button", { name: "다시 시도" })).toBeNull();
  });

  it("keeps a neutral absence message for a generic 404 with a manual retry", async () => {
    rosterMock.implementation = async () => { throw new CoreApiError(404, {}); };
    render(await FieldTeamPage());
    expect(screen.getByText(/확인할 수 없습니다/)).toBeTruthy();
    expect(screen.getByText(/비었다는 뜻은 아닙니다/)).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/구성|설정/);
    expect(screen.getByRole("button", { name: "다시 시도" })).toBeTruthy();
  });

  it("offers a retry only for a transient server failure", async () => {
    rosterMock.implementation = async () => { throw new CoreApiError(503, {}); };
    render(await FieldTeamPage());
    expect(screen.getByText(/잠시 후 다시 시도하세요/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "다시 시도" })).toBeTruthy();
  });
});
