/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExternalObservationCreateForm } from "@/app/sites/[siteId]/observations/new/ExternalObservationCreateForm";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

afterEach(cleanup);

describe("registration multi-area catalog notice", () => {
  it("warns only when more than one area is checked (contract unchanged)", () => {
    render(<ExternalObservationCreateForm
      siteId="site-1"
      siteName="서쪽 현장"
      workAreas={[{ workAreaId: "wa-1", name: "A구역" }, { workAreaId: "wa-2", name: "B구역" }]}
    />);
    expect(screen.queryByRole("status")).toBeNull();
    fireEvent.click(screen.getByLabelText("A구역"));
    expect(screen.queryByRole("status")).toBeNull();
    fireEvent.click(screen.getByLabelText("B구역"));
    expect(screen.getByRole("status")?.textContent).toMatch(/구역별 자료 목록/);
  });
});
