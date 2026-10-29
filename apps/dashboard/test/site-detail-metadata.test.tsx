/** @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  site: vi.fn(),
  permissions: vi.fn(),
  areas: vi.fn(),
  orders: vi.fn(),
  history: vi.fn(),
  analyses: vi.fn(),
  assets: vi.fn(),
  header: vi.fn(),
}));

vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/permissions", () => ({ hasAllPermissions: mocked.permissions }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ listObservationWorkOrders: mocked.orders }));
vi.mock("@/lib/core-api/external-result-workflow", () => ({ listSiteExternalVolumeHistory: mocked.history }));
vi.mock("@/lib/core-api/analysis", () => ({ listAnalyses: mocked.analyses }));
vi.mock("@/lib/core-api/spatial-assets", () => ({ listSpatialAssets: mocked.assets }));
vi.mock("@/app/sites/[siteId]/SiteHeader", () => ({ SiteHeader: mocked.header }));
vi.mock("@/app/sites/[siteId]/observations/ExternalObservationHistory", () => ({ ExternalObservationHistory: () => <div /> }));
vi.mock("next/navigation", () => ({
  notFound: () => { throw new Error("NEXT_NOT_FOUND"); },
  useRouter: () => ({ refresh: () => {} }),
  redirect: (url: string) => {
    const error = new Error(`NEXT_REDIRECT;replace;${url};307;`);
    (error as Error & { digest: string }).digest = `NEXT_REDIRECT;replace;${url};307;`;
    throw error;
  },
}));

import * as SitePage from "@/app/sites/[siteId]/page";
import { renderToStaticMarkup } from "react-dom/server";

describe("Site document metadata boundary", () => {
  it("exports a route-local static neutral title without reading any site", () => {
    const page = SitePage as typeof SitePage & { metadata?: { title?: string }; generateMetadata?: unknown };
    expect(page.metadata).toEqual({ title: "현장 상세 · KSI" });
    expect(page.generateMetadata).toBeUndefined();
    expect(mocked.site).not.toHaveBeenCalled();
    const html = renderToStaticMarkup(<title>{page.metadata?.title}</title>);
    expect(html).toBe("<title>현장 상세 · KSI</title>");
  });
});
