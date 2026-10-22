import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
import type { SiteView } from "@/lib/core-api/types";
import { siteTabHref } from "@/lib/operator-journey";

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

describe("siteTabHref", () => {
  it("goes direct to actual routes without scope", () => {
    const scope = { workAreaId: null, assetRef: null };
    expect(siteTabHref("site-1", "analysis", {}, scope)).toBe("/sites/site-1/analysis");
    expect(siteTabHref("site-1", "materials", {}, scope)).toBe("/sites/site-1/spatial-assets");
    expect(siteTabHref("site-1", "overview", {}, scope)).toBe("/sites/site-1");
    expect(siteTabHref("site-1", "work-orders", {}, scope)).toBe("/sites/site-1?section=work-orders");
    expect(siteTabHref("site-1", "manage", {}, scope)).toBe("/sites/site-1?section=manage");
  });

  it("carries a validated scope and scopes assetRef to the same catalog only", () => {
    const scope = { workAreaId: "wa-a", assetRef: "asset-1" };
    expect(siteTabHref("site-1", "analysis", {}, scope)).toBe(
      "/sites/site-1/analysis?workAreaId=wa-a&assetRef=asset-1",
    );
    expect(siteTabHref("site-1", "materials", {}, scope)).toBe(
      "/sites/site-1/spatial-assets?workAreaId=wa-a&assetRef=asset-1",
    );
    // 탐색으로 돌아갈 때 정확한 관측을 잃지 않도록 현황·작업·관리에도 싣는다.
    expect(siteTabHref("site-1", "overview", {}, scope)).toBe("/sites/site-1?workAreaId=wa-a&assetRef=asset-1");
    expect(siteTabHref("site-1", "work-orders", {}, scope)).toBe(
      "/sites/site-1?section=work-orders&workAreaId=wa-a&assetRef=asset-1",
    );
    expect(siteTabHref("site-1", "manage", {}, scope)).toBe(
      "/sites/site-1?section=manage&workAreaId=wa-a&assetRef=asset-1",
    );
  });

  it("drops assetRef without its work area", () => {
    expect(siteTabHref("site-1", "materials", {}, { workAreaId: null, assetRef: "asset-1" })).toBe(
      "/sites/site-1/spatial-assets",
    );
    expect(siteTabHref("site-1", "analysis", {}, { workAreaId: null, assetRef: "asset-1" })).toBe(
      "/sites/site-1/analysis",
    );
    expect(siteTabHref("site-1", "overview", {}, { workAreaId: null, assetRef: "asset-1" })).toBe(
      "/sites/site-1",
    );
  });
});

describe("SiteHeader scoped navigation", () => {
  it("links analysis and materials direct with scope in the directly visible nav", () => {
    const html = headerHtml({ scopedWorkAreaId: "wa-a", scopedAssetRef: "asset-1" });
    // 데스크톱·모바일 구분 없는 직접 nav 하나에 같은 목적지를 둔다.
    expect(html.match(/\/sites\/site-1\/analysis\?workAreaId=wa-a/g)?.length).toBe(1);
    expect(html.match(/\/sites\/site-1\/spatial-assets\?workAreaId=wa-a&amp;assetRef=asset-1/g)?.length).toBe(1);
    expect(html).not.toContain("section=analysis");
    expect(html).not.toContain("section=materials");
    // 네 영역을 펼침 없이 바로 보인다 — 이름 없는 아이콘-only 진입 금지.
    const nav = html.slice(html.indexOf('aria-label="현장 업무 메뉴"'));
    expect(nav.match(/<a[\s>]/g)?.length).toBe(4);
    expect(nav).not.toContain("section=work-orders");
    expect(html).toContain("공간 보기");
    expect(html).toContain("설정");
    expect(html).toContain("자료");
    expect(html).toContain("분석·결과");
    expect(html).toContain('aria-current="page"');
  });

  it("keeps in-page sections and old deep-URL compat for work and manage", () => {
    const html = headerHtml({ scopedWorkAreaId: "wa-a" });
    expect(html).toContain("/sites/site-1?section=manage&amp;workAreaId=wa-a");
    expect(html).toContain("/sites/site-1?section=manage#site-aoi");
    // 옛 작업 URL은 자료 맥락의 하위 길로 범위를 함께 싣는다 — 다섯 번째
    // 최상위 구간이 아니다. 표준 목적지(canonical helper)와 같다.
    const materials = headerHtml({ tab: "materials", scopedWorkAreaId: "wa-a" });
    expect(materials).toContain("/sites/site-1?section=work-orders&amp;workAreaId=wa-a");
    expect(siteTabHref("site-1", "work-orders", {}, { workAreaId: "wa-a", assetRef: null })).toBe(
      "/sites/site-1?section=work-orders&workAreaId=wa-a",
    );
  });

  it("never leaks an unverified scope (page maps it to null)", () => {
    const html = headerHtml({});
    expect(html).toContain("/sites/site-1/analysis");
    expect(html).not.toContain("workAreaId");
    expect(html).not.toContain("assetRef");
  });

  it("preserves a validated scope on the new-registration action, never on AOI setup", () => {
    const html = headerHtml({
      tab: "work-orders",
      canCreateWorkOrder: true,
      scopedWorkAreaId: "wa-a",
    });
    expect(html).toContain("/sites/site-1/observations/new?workAreaId=wa-a");
  });

  it("leaves work-area setup without a scope query", () => {
    const html = headerHtml({
      tab: "work-orders",
      canCreateWorkOrder: false,
      canEditAoi: true,
      scopedWorkAreaId: "wa-a",
    });
    expect(html).toContain("/sites/site-1/work-areas");
    expect(html).not.toContain("/sites/site-1/work-areas?workAreaId");
  });

  it("shows no preparation action without the role grant", () => {
    const ready = { ...site, status: "PATROL_READY" } as SiteView;
    const html = renderToStaticMarkup(
      <SiteHeader
        site={ready}
        selectedEpochId={null}
        tab="work-orders"
        latestExternalReportAt={null}
        latestExternalReportKnown={false}
        canCreateWorkOrder={false}
        canEditAoi={false}
        scopedWorkAreaId="wa-a"
      />,
    );
    expect(html).not.toContain("observations/new");
  });
});
