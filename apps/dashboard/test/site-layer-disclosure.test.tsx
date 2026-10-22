/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import Link from "next/link";
import { SiteLayerDisclosure } from "@/app/sites/[siteId]/SiteLayerDisclosure";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const contents = <div id="layer-portal"><Link href="/sites/site-1?assetRef=dsm">DSM</Link></div>;
function media(desktop: boolean) {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: desktop, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
}

describe("responsive native layer disclosure", () => {
  it("opens on a desktop and keeps a reachable summary instead of visually overriding closed content", () => {
    media(true);
    const { container } = render(<SiteLayerDisclosure>{contents}</SiteLayerDisclosure>);
    expect(container.querySelector("details")!.open).toBe(true);
    expect(screen.getByRole("heading", { name: "표시 레이어" })).toBeTruthy();
    fireEvent.click(screen.getByText("표시 레이어"));
    expect(container.querySelector("details")!.open).toBe(false);
    expect(container.querySelectorAll("#layer-portal")).toHaveLength(1);
  });

  it("starts closed on a phone, keeps its portal in DOM, and supports explicit opening", () => {
    media(false);
    const { container } = render(<SiteLayerDisclosure>{contents}</SiteLayerDisclosure>);
    expect(container.querySelector("details")!.open).toBe(false);
    expect(container.querySelectorAll("#layer-portal")).toHaveLength(1);
    fireEvent.click(screen.getByText("표시 레이어"));
    expect(container.querySelector("details")!.open).toBe(true);
  });

  it("retains a native clickable summary in SSR without requiring a new pseudo-element", () => {
    const html = renderToStaticMarkup(<SiteLayerDisclosure>{contents}</SiteLayerDisclosure>);
    expect(html).toContain("<summary");
    expect(html).toContain('id="layer-portal"');
    expect(html).not.toContain("::details-content");
    expect(html).not.toContain("lg:hidden");
  });
});
