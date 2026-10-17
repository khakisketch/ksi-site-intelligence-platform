/** @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SiteStartGuidance } from "@/app/sites/[siteId]/SiteStartGuidance";

afterEach(cleanup);

const base = {
  siteId: "site-1",
  workAreaCount: 2,
  observationWorkOrderCount: 3,
  externalResultCount: 4,
  hasMoreExternalResults: false as const,
};

describe("SiteStartGuidance workspace mode", () => {
  it("defaults to full guidance with CTA and next step", () => {
    render(<SiteStartGuidance {...base} />);
    const guide = within(screen.getByRole("region", { name: "현장 시작 안내" }));
    expect(guide.getByRole("link", { name: "비교할 자료 선택" }).getAttribute("href")).toBe("/sites/site-1/analysis");
    expect(guide.getByText(/다음 확인/)).toBeTruthy();
  });

  it("renders counts only when the spatial workspace already owns actions", () => {
    render(<SiteStartGuidance {...base} hasWorkspaceActions />);
    const guide = within(screen.getByRole("region", { name: "현장 시작 안내" }));
    expect(guide.getByText("2개 목록됨")).toBeTruthy();
    expect(guide.getByText("3개 목록됨")).toBeTruthy();
    expect(guide.getByText("4개 목록됨")).toBeTruthy();
    expect(guide.queryByRole("link")).toBeNull();
    expect(guide.queryByText(/다음 확인/)).toBeNull();
    expect(guide.queryByText(/비교할 자료 선택/)).toBeNull();
  });
});
