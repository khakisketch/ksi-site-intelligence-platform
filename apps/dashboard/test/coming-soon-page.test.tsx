/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  notFound: () => { throw new Error("NEXT_NOT_FOUND"); },
}));

import ComingSoonPage from "@/app/coming-soon/[section]/page";

afterEach(cleanup);

describe("coming-soon 범위 안내", () => {
  it("fleet은 제품 범위 밖이라고 안내하고 계정·도움말로 보낸다", async () => {
    render(await ComingSoonPage({ params: Promise.resolve({ section: "fleet" }) }));
    expect(screen.getByText("장비 운용은 제품 범위 밖입니다")).toBeTruthy();
    expect(screen.queryByText(/준비 중/)).toBeNull();
    expect(screen.getByRole("link", { name: "계정·도움말" }).getAttribute("href")).toBe("/more");
  });

  it.each(["data", "unknown", "constructor"])("메뉴에 없는 %s는 준비 중으로 꾸미지 않고 notFound로 끝난다", async (section) => {
    await expect(ComingSoonPage({ params: Promise.resolve({ section }) })).rejects.toThrow("NEXT_NOT_FOUND");
  });
});
