/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";

import SiteDetailLoading from "@/app/sites/[siteId]/loading";
import { SkeletonBlock, SkeletonList } from "@/components/ui/Skeleton";

afterEach(cleanup);

describe("accessible loading skeletons", () => {
  it.each([
    ["list", SkeletonList],
    ["block", SkeletonBlock],
  ] as const)("exposes the %s loading state as a named busy status", (_name, Skeleton) => {
    render(<Skeleton />);

    const status = screen.getByRole("status", { name: "불러오는 중" });
    expect(status.getAttribute("aria-busy")).toBe("true");
  });

  it("explains a persistent site loading state and provides a no-JavaScript recovery", () => {
    const html = renderToStaticMarkup(<SiteDetailLoading />);
    expect(html).toContain("현장 화면을 불러오는 중입니다");
    expect(html).toContain("연결을 확인하고 새로고침하세요");
    expect(html).toMatch(/<noscript[^>]*>[\s\S]*자바스크립트[\s\S]*<\/noscript>/);
  });
});
