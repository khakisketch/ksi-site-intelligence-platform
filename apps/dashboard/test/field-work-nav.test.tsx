/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FieldWorkNav } from "@/app/field/FieldWorkNav";

afterEach(cleanup);

describe("field work navigation", () => {
  it("marks exactly one current view among observation records and received work", () => {
    render(<FieldWorkNav active="orders" showTeam={false} />);
    const nav = screen.getByRole("navigation", { name: "업무 보기 방식" });
    expect(nav).toBeTruthy();
    expect(screen.getByRole("link", { name: "관측 작업" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "받은 업무" }).getAttribute("aria-current")).toBeNull();
  });

  it("shows the team entry only when permitted and keeps org-record meaning", () => {
    render(<FieldWorkNav active="inbox" showTeam={true} />);
    const team = screen.getByRole("link", { name: "팀 관리" });
    expect(team.getAttribute("href")).toBe("/field/team");
    expect(team.getAttribute("aria-current")).toBeNull();
    expect(screen.getByRole("link", { name: "받은 업무" }).getAttribute("aria-current")).toBe("page");
  });

  it("hides the team entry without permission instead of a dead link", () => {
    render(<FieldWorkNav active="orders" showTeam={false} />);
    expect(screen.queryByRole("link", { name: "팀 관리" })).toBeNull();
    expect(screen.getByRole("link", { name: "관측 작업" }).getAttribute("href")).toBe("/field");
    expect(screen.getByRole("link", { name: "받은 업무" }).getAttribute("href")).toBe("/field/inbox");
  });
});
