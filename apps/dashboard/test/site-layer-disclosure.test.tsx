/** @vitest-environment jsdom */
import Link from "next/link";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { SiteLayerDisclosure } from "@/app/sites/[siteId]/SiteLayerDisclosure";

afterEach(cleanup);

it("keeps layer selection and its single portal directly reachable", () => {
  const { container } = render(<SiteLayerDisclosure>
    <div id="layer-portal"><Link href="/sites/site-1?assetRef=dsm">DSM</Link></div>
  </SiteLayerDisclosure>);
  expect(screen.getByRole("heading", { name: "표시 레이어" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "DSM" }).getAttribute("href")).toBe("/sites/site-1?assetRef=dsm");
  expect(container.querySelectorAll("#layer-portal")).toHaveLength(1);
  expect(container.querySelector("details")).toBeNull();
});
