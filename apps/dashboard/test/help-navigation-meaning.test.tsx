/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import HelpPage from "@/app/help/page";

afterEach(cleanup);

it("explains site areas and distinguishes organization records from received work", () => {
  render(<HelpPage />);
  expect(screen.getByText(/현장의 작업공간은 구역과 관측 시점을/).textContent).toContain("조직의 작업 기록");
  expect(screen.getByText(/현장의 작업공간은 구역과 관측 시점을/).textContent).toContain("나에게 배정되거나 공유된 항목");
  expect(screen.getByRole("link", { name: /현장과 결과 살펴보기/ }).getAttribute("href")).toBe("/sites");
  expect(screen.getByRole("link", { name: /관측 자료 등록하기/ }).getAttribute("href")).toBe("/field/new");
  expect(screen.getByRole("link", { name: /조직의 관측 작업 기록 보기/ }).getAttribute("href")).toBe("/field");
});
