import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  site: vi.fn(),
  areas: vi.fn(),
  identity: vi.fn(),
  screenProps: null as Record<string, unknown> | null,
}));

vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/auth", () => ({ whoAmI: mocked.identity }));
vi.mock("@/components/nav/ConsolePage", () => ({
  ConsolePage: ({ children }: { children: React.ReactNode }) => createElement("main", null, children),
}));
vi.mock("@/components/nav/site-context", () => ({ siteDataHref: () => "/data" }));
vi.mock("@/components/responsive/ResponsiveActionBoundary", () => ({
  ResponsiveActionBoundary: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/components/site/ExternalResultFolderPicker", () => ({ ExternalResultFolderPicker: () => null }));
vi.mock("@/app/sites/[siteId]/upload/UploadCompletion", () => ({ UploadCompletion: () => null }));
vi.mock("@/app/sites/[siteId]/upload/UploadMap", () => ({ UploadMap: () => null }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => createElement("a", { href }, children) }));
vi.mock("next/navigation", () => ({ notFound: () => { throw new Error("NEXT_NOT_FOUND"); } }));
vi.mock("@/app/sites/[siteId]/upload/UploadScreen", () => ({
  UploadScreen: (props: Record<string, unknown>) => {
    mocked.screenProps = props;
    return createElement("div");
  },
}));

import SiteUploadPage from "@/app/sites/[siteId]/upload/page";

describe("SiteUploadPage", () => {
  beforeEach(() => {
    mocked.screenProps = null;
    mocked.site.mockResolvedValue({ siteId: "site-1", name: "Sunflower" });
    mocked.areas.mockResolvedValue({
      workAreas: [{
        workAreaId: "area-32635",
        name: "Native projected area",
        status: "ACTIVE",
        crs: "EPSG:32635",
        polygon: {
          type: "Polygon",
          coordinates: [[
            [215843.76323177927, 4727946.649519713],
            [216109.17223298742, 4727946.649519713],
            [216109.17223298742, 4728217.935922389],
            [215843.76323177927, 4728217.935922389],
            [215843.76323177927, 4727946.649519713],
          ]],
        },
      }],
    });
    mocked.identity.mockResolvedValue({
      kind: "OPERATOR", principalId: "operator-1", organizationId: "org-1", permissions: ["WORK_ORDERS_WRITE"],
    });
  });

  it("passes a WGS84 display copy while retaining the selected work area identity", async () => {
    renderToStaticMarkup(await SiteUploadPage({
      params: Promise.resolve({ siteId: "site-1" }),
      searchParams: Promise.resolve({ workAreaId: "area-32635" }),
    }));

    const props = mocked.screenProps as { workAreas: { workAreaId: string; polygon: Record<string, unknown> | null }[]; initialWorkAreaId: string };
    expect(props.initialWorkAreaId).toBe("area-32635");
    expect(props.workAreas[0]!.workAreaId).toBe("area-32635");
    const ring = (props.workAreas[0]!.polygon!.coordinates as number[][][])[0]!;
    expect(ring).toHaveLength(5);
    expect(ring[0]![0]).toBeCloseTo(23.53348, 4);
    expect(ring[0]![1]).toBeCloseTo(42.65153, 4);
    expect(ring[0]).toEqual(ring.at(-1));
    expect(ring[0]![0]).toBeLessThan(180);
  });

  it("retains registration context when the work area CRS cannot be displayed", async () => {
    mocked.areas.mockResolvedValue({
      workAreas: [{
        workAreaId: "area-unknown",
        name: "Unknown CRS",
        status: "ACTIVE",
        crs: "EPSG:999999",
        polygon: { type: "Polygon", coordinates: [[[1, 2], [3, 2], [3, 4], [1, 4], [1, 2]]] },
      }],
    });

    renderToStaticMarkup(await SiteUploadPage({
      params: Promise.resolve({ siteId: "site-1" }),
      searchParams: Promise.resolve({ workAreaId: "area-unknown" }),
    }));

    const props = mocked.screenProps as { workAreas: { workAreaId: string; polygon: Record<string, unknown> | null }[]; initialWorkAreaId: string };
    expect(props.initialWorkAreaId).toBe("area-unknown");
    expect(props.workAreas[0]!.workAreaId).toBe("area-unknown");
    expect(props.workAreas[0]!.polygon).toBeNull();
  });
});
