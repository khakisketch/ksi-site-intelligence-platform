/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SiteListProvider } from "@/components/nav/SiteListContext";
import { MobileSiteSwitcher } from "@/components/nav/MobileSiteSwitcher";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function renderSwitcher() {
  return render(
    <SiteListProvider
      sites={[
        { siteId: "site-a", name: "Floreat public sample", status: "BASELINE_MAPPING" },
        { siteId: "site-b", name: "Product Sample Field", status: "UNMAPPED" },
      ]}
    >
      <MobileSiteSwitcher siteId="site-a" section="materials" />
    </SiteListProvider>,
  );
}

describe("MobileSiteSwitcher", () => {
  it("opens a sheet and preserves the current site section", async () => {
    renderSwitcher();
    const trigger = screen.getByRole("button", { name: /현장 변경/ });
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "현장 변경" });
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    const link = screen.getByRole("link", { name: /Product Sample Field/ });
    expect(link.getAttribute("href")).toBe("/sites/site-b/spatial-assets");
    expect(screen.getAllByText("현재 현장").length).toBeGreaterThan(0);
  });

  it("closes with Escape and restores focus", async () => {
    renderSwitcher();
    const trigger = screen.getByRole("button", { name: /현장 변경/ });
    fireEvent.click(trigger);
    await waitFor(() => expect(document.activeElement?.textContent).toContain("Floreat"));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "현장 변경" })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});
