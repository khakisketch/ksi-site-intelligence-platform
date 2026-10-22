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
      tab="overview"
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
    expect(labels.get("overview")).toBe("공간 보기");
    expect(labels.get("materials")).toBe("자료");
    expect(labels.get("analysis")).toBe("분석·결과");
    expect(labels.get("manage")).toBe("설정");
    expect(labels.get("work-orders")).toBe("관측 작업 기록");
  });

  it("shows exactly four directly visible section links without a top-level work-orders entry", () => {
    const nav = workspaceNav(headerHtml({}));
    const links = nav.match(/<a[\s>]/g) ?? [];
    expect(links).toHaveLength(4);
    for (const label of ["공간 보기", "자료", "분석·결과", "설정"]) {
      expect(nav).toContain(`>${label}<`);
    }
    expect(nav).not.toContain("관측 작업 기록");
    expect(nav).not.toContain("section=work-orders");
    expect(nav).not.toContain("현장 메뉴");
  });

  it("marks the current section with aria-current in the four-link nav", () => {
    const nav = workspaceNav(headerHtml({ tab: "materials" }));
    expect(nav.match(/aria-current="page"/g)).toHaveLength(1);
    const current = nav.match(/<a[^>]*aria-current="page"[^>]*>([^<]*)</);
    expect(current?.[1]).toBe("자료");
  });

  it("preserves the validated scope and epoch on the four section links", () => {
    const html = headerHtml({ tab: "overview", selectedEpochId: "epoch-9", scopedWorkAreaId: "wa-a" });
    const nav = workspaceNav(html);
    expect(nav).toContain("/sites/site-1/analysis?workAreaId=wa-a");
    expect(nav).toContain("/sites/site-1/spatial-assets?workAreaId=wa-a");
    expect(nav).toContain("section=manage");
    expect(nav).toContain("workAreaId=wa-a");
    expect(nav).toContain("epoch=epoch-9");
    // 범위가 없을 때는 조용히 뺀다 — 없는 값을 지어내지 않는다.
    const bare = workspaceNav(headerHtml({}));
    expect(bare).not.toContain("workAreaId");
    expect(bare).not.toContain("assetRef");
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
    expect(materials).not.toContain("작업구역 관리");
    expect(headerHtml({ tab: "manage" })).not.toContain("section=work-orders");
    const legacy = headerHtml({ tab: "work-orders", scopedWorkAreaId: "wa-a" });
    expect(workspaceNav(legacy)).toMatch(/aria-current="page"[^>]*>자료</);
    expect(legacy).toContain("관측 작업 기록");
  });
});
