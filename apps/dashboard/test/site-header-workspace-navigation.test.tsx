import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
import type { SiteView } from "@/lib/core-api/types";
import { normalizeSiteTab, SITE_TABS } from "@/lib/site-epochs";

const site = { siteId: "site-1", name: "동측 현장", status: "UNMAPPED", resumeTarget: null, aoi: null } as SiteView;

function headerHtml(props: Partial<Parameters<typeof SiteHeader>[0]> = {}) {
  return renderToStaticMarkup(
    <SiteHeader
      site={site}
      selectedEpochId={null}
      tab="workspace"
      latestExternalReportAt={null}
      latestExternalReportKnown={false}
      canCreateWorkOrder={false}
      canEditAoi={false}
      {...props}
    />,
  );
}

function workspaceNav(html: string): string {
  const start = html.indexOf('aria-label="현장 업무 메뉴"');
  expect(start).toBeGreaterThan(-1);
  const navOpen = html.lastIndexOf("<nav", start);
  const navClose = html.indexOf("</nav>", start);
  expect(navClose).toBeGreaterThan(navOpen);
  return html.slice(navOpen, navClose);
}

describe("site header workspace navigation", () => {
  it("keeps the workspace tab labels", () => {
    const labels = new Map(SITE_TABS.map((tab) => [tab.key, tab.label] as const));
    expect(labels.get("workspace")).toBe("작업공간");
    expect(labels.get("materials")).toBe("자료");
    expect(labels.get("results")).toBe("결과");
    expect(labels.get("manage")).toBe("설정");
    expect(labels.get("work-orders")).toBe("관측 작업 기록");
  });

  it("shows exactly three directly visible section links without top-level work-orders or settings entries", () => {
    const nav = workspaceNav(headerHtml({}));
    const links = nav.match(/<a[\s>]/g) ?? [];
    expect(links).toHaveLength(3);
    for (const label of ["작업공간", "자료", "결과"]) {
      expect(nav).toContain(`>${label}<`);
    }
    expect(nav).not.toContain("관측 작업 기록");
    expect(nav).not.toContain("section=work-orders");
    expect(nav).not.toContain("현장 메뉴");
  });

  it("marks the current section with aria-current in the three-link nav", () => {
    const nav = workspaceNav(headerHtml({ tab: "materials" }));
    expect(nav.match(/aria-current="page"/g)).toHaveLength(1);
    const current = nav.match(/<a[^>]*aria-current="page"[^>]*>([^<]*)</);
    expect(current?.[1]).toBe("자료");
  });

  it("preserves the validated scope and epoch on the three section links", () => {
    const html = headerHtml({ tab: "workspace", selectedEpochId: "epoch-9", scopedWorkAreaId: "wa-a" });
    const nav = workspaceNav(html);
    expect(nav).toContain("/sites/site-1/analysis?workAreaId=wa-a");
    expect(nav).toContain("/sites/site-1/spatial-assets?workAreaId=wa-a");
    // 설정은 최상위 nav가 아니라 머리 설정 메뉴에 둔다 — nav에는 싣지 않는다.
    expect(nav).not.toContain("section=manage");
    expect(html).toContain("section=manage");
    expect(nav).toContain("workAreaId=wa-a");
    expect(nav).toContain("epoch=epoch-9");
    // 범위가 없을 때는 조용히 뺀다 — 없는 값을 지어내지 않는다.
    const bare = workspaceNav(headerHtml({}));
    expect(bare).not.toContain("workAreaId");
    expect(bare).not.toContain("assetRef");
  });

  it("opens the condition form rather than the history when handing off an exact visual pair", () => {
    const visualContext = { workAreaId: "wa-a", visualAAssetRef: `ksa-v1-${"a".repeat(64)}`,
      visualBAssetRef: `ksa-v1-${"b".repeat(64)}`,
      hintBaseline: { workOrderId: "work-a", submissionRef: `ers-v1-${"a".repeat(64)}`, revision: 1 },
      hintCurrent: { workOrderId: "work-b", submissionRef: `ers-v1-${"b".repeat(64)}`, revision: 2 } };
    const nav = workspaceNav(headerHtml({ scopedWorkAreaId: "wa-a", visualContext }));
    const href = nav.match(/href="([^"]+)"[^>]*>결과</)?.[1]?.replaceAll("&amp;", "&");
    const url = new URL(href!, "https://console.test");
    expect(url.hash).toBe("#new-analysis-request");
    expect(url.searchParams.get("hintCurrentRevision")).toBe("2");
    expect(url.searchParams.get("visualAAssetRef")).toBe(visualContext.visualAAssetRef);
    expect(workspaceNav(headerHtml({ scopedWorkAreaId: "wa-a" }))).not.toContain("#new-analysis-request");
  });

  it("retains the work-orders key for legacy URLs", () => {
    expect(SITE_TABS.some((tab) => tab.key === "work-orders")).toBe(true);
    expect(normalizeSiteTab("work-orders")).toBe("work-orders");
    expect(normalizeSiteTab("work")).toBe("work-orders");
    expect(normalizeSiteTab("records")).toBe("work-orders");
  });

  it("keeps observation-work records in the data context without mislabelling them as area management", () => {
    const materials = headerHtml({ tab: "materials", scopedWorkAreaId: "wa-a" });
    expect(materials).toContain("자료 · ");
    expect(materials).toContain("관측 작업 기록");
    expect(materials).toContain("/sites/site-1?section=work-orders&amp;workAreaId=wa-a");
    // 자료 하위 길 문단에는 구역 관리 링크를 두지 않는다 — 설정 메뉴의 전역
    // 작업구역 관리와 섞지 않는다.
    const recordsStart = materials.indexOf("자료 · ");
    expect(materials.slice(recordsStart)).not.toContain("작업구역 관리");
    expect(headerHtml({ tab: "manage" })).not.toContain("section=work-orders");
    const legacy = headerHtml({ tab: "work-orders", scopedWorkAreaId: "wa-a" });
    expect(workspaceNav(legacy)).toMatch(/aria-current="page"[^>]*>자료</);
    expect(legacy).toContain("관측 작업 기록");
  });
});
