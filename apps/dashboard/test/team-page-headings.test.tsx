/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ pathname: "/field/team" }));
vi.mock("next/navigation", () => ({ usePathname: () => mocked.pathname }));
vi.mock("@/app/field/resolve-session", () => ({
  resolveFieldSession: async () => ({ kind: "ready", principal: { role: "ADMIN", principalId: "operator-a" } }),
}));
vi.mock("@/lib/core-api/work-collaboration", () => ({
  listOrganizationWorkRoster: async () => ({ members: [] }),
  listWorkInbox: async () => ({ items: [], nextCursor: null }),
}));
vi.mock("@/app/field/team/TeamRosterPanel", () => ({ TeamRosterPanel: () => null }));
vi.mock("@/app/field/inbox/WorkInboxPanel", () => ({ WorkInboxPanel: () => null }));

import { MainPageTitle } from "@/components/nav/PageTitle";
import FieldTeamPage from "@/app/field/team/page";
import FieldInboxPage from "@/app/field/inbox/page";

afterEach(cleanup);

describe("team collaboration page heading hierarchy", () => {
  it.each([
    ["/field/team", "팀 관리"],
    ["/field/inbox", "받은 업무"],
  ])("keeps the shell's unique h1 on %s", async (pathname, title) => {
    mocked.pathname = pathname;
    const body = pathname === "/field/team"
      ? await FieldTeamPage()
      : await FieldInboxPage({ searchParams: Promise.resolve({}) });
    render(<main><MainPageTitle fallback={title} />{body}</main>);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 2, name: title })).toBeTruthy();
  });
});
