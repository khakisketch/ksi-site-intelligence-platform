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
      tab="space"
      {...props}
    />,
  );
}

function workspaceNav(html: string): string {
  const start = html.indexOf('aria-label="현장 영역 메뉴"');
  expect(start).toBeGreaterThan(-1);
  const navOpen = html.lastIndexOf("<nav", start);
  const navClose = html.indexOf("</nav>", start);
  expect(navClose).toBeGreaterThan(navOpen);
  return html.slice(navOpen, navClose);
}

describe("site header workspace navigation", () => {
  it("uses the canonical space and analysis tab labels", () => {
    expect(SITE_TABS).toEqual([
      { key: "space", label: "공간" },
      { key: "analysis", label: "분석" },
    ]);
  });

  it("shows exactly two directly visible section links without top-level work-orders or settings entries", () => {
    const nav = workspaceNav(headerHtml({}));
    const links = nav.match(/<a[\s>]/g) ?? [];
    expect(links).toHaveLength(2);
    for (const label of ["공간", "분석"]) {
      expect(nav).toContain(`>${label}<`);
    }
    expect(nav).not.toContain("작업 기록");
    expect(nav).not.toContain("section=work-orders");
    expect(nav).not.toContain("현장 메뉴");
  });

  it("marks the current section with aria-current in the two-link nav", () => {
    const nav = workspaceNav(headerHtml({ tab: "space" }));
    expect(nav.match(/aria-current="page"/g)).toHaveLength(1);
    const current = nav.match(/<a[^>]*aria-current="page"[^>]*>([^<]*)</);
    expect(current?.[1]).toBe("공간");
  });

  it("preserves the validated scope and epoch on the two section links", () => {
    const html = headerHtml({ tab: "space", selectedEpochId: "epoch-9", scopedWorkAreaId: "wa-a" });
    const nav = workspaceNav(html);
    expect(nav).toContain("/sites/site-1/analysis?workAreaId=wa-a");
    expect(nav).toContain("/sites/site-1?workAreaId=wa-a");
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

  it("keeps header Results as a records-first browse handoff without request hints", () => {
    const visualContext = { workAreaId: "wa-a", visualAAssetRef: `ksa-v1-${"a".repeat(64)}`,
      visualBAssetRef: `ksa-v1-${"b".repeat(64)}` };
    const nav = workspaceNav(headerHtml({ scopedWorkAreaId: "wa-a", visualContext }));
    const href = nav.match(/href="([^"]+)"[^>]*>분석</)?.[1]?.replaceAll("&amp;", "&");
    const url = new URL(href!, "https://console.test");
    // 둘러보기 맥락(A/B)은 싣되, 요청 힌트 6건과 #new-analysis-request는 싣지
    // 않는다 — 최상위 결과 이동이 둘러보기를 새 요청으로 바꾸지 않는다.
    expect(url.hash).toBe("");
    expect(url.searchParams.get("visualAAssetRef")).toBe(visualContext.visualAAssetRef);
    expect(url.searchParams.get("visualBAssetRef")).toBe(visualContext.visualBAssetRef);
    expect(url.searchParams.get("hintBaselineWorkOrderId")).toBeNull();
    expect(url.searchParams.get("hintCurrentWorkOrderId")).toBeNull();
    expect(nav).not.toContain("#new-analysis-request");
    expect(nav).not.toContain("hintBaseline");
    expect(nav).not.toContain("hintCurrent");
  });

  it("retains the work-orders key for legacy URLs", () => {
    expect(normalizeSiteTab("work-orders")).toBe("work-orders");
    expect(normalizeSiteTab("work")).toBe("work-orders");
    expect(normalizeSiteTab("records")).toBe("work-orders");
  });

  it("keeps the records route in the data context, not as a fourth tab", () => {
    const materials = headerHtml({ tab: "space", scopedWorkAreaId: "wa-a" });
    // The header owns two destination tabs only. Observation-work records stay
    // a legacy/canonical route owned by the materials context menu (「더 보기」).
    expect(workspaceNav(materials).match(/<a[\s>]/g)).toHaveLength(2);
    expect(materials).not.toContain("section=work-orders");
    expect(headerHtml({ tab: "manage" })).not.toContain("section=work-orders");
    const legacy = headerHtml({ tab: "work-orders", scopedWorkAreaId: "wa-a" });
    expect(workspaceNav(legacy)).toMatch(/aria-current="page"[^>]*>공간</);
  });
});
