/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

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
});
