// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";

import SiteNotFound from "@/app/sites/[siteId]/not-found";

afterEach(cleanup);

it("keeps a safe site-list exit without claiming a scoped 404 proves deletion or absence", () => {
  render(<SiteNotFound />);
  expect(screen.getByRole("heading", { level: 2, name: "현장을 찾을 수 없습니다" })).toBeTruthy();
  expect(screen.queryByText(/존재하지 않|삭제되었습니다/)).toBeNull();
  expect(screen.getByText(/접근할 수 없습니다/)).toBeTruthy();
  expect(screen.getByRole("link", { name: "현장 목록으로" }).getAttribute("href")).toBe("/sites");
});
