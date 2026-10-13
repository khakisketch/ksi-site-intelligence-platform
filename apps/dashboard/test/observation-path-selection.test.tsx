// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

import { ExternalObservationCreateForm } from "@/app/sites/[siteId]/observations/new/ExternalObservationCreateForm";

afterEach(cleanup);

describe("ExternalObservationCreateForm path selection", () => {
  it("marks the selected path with an explicit label, not a border colour alone", () => {
    render(
      <ExternalObservationCreateForm
        siteId="site-1"
        siteName="A 현장"
        workAreas={[{ workAreaId: "area-1", name: "1구역" }]}
      />,
    );
    const selectedCard = screen.getByRole("button", { name: /외부 산출물 등록/ });
    expect(selectedCard.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText(/선택됨/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: /^외부 산출물 등록$/ })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: /^외부 산출물 작업$/ })).toBeNull();
  });
});
