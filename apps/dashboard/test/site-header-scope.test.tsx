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
      tab="space"
      {...props}
    />,
  );
}

describe("siteTabHref", () => {
  it("goes direct to actual routes without scope", () => {
    const scope = { workAreaId: null, assetRef: null };
    expect(siteTabHref("site-1", "analysis", {}, scope)).toBe("/sites/site-1/analysis");
    expect(siteTabHref("site-1", "materials", {}, scope)).toBe("/sites/site-1?panel=materials");
    expect(siteTabHref("site-1", "overview", {}, scope)).toBe("/sites/site-1");
    expect(siteTabHref("site-1", "work-orders", {}, scope)).toBe("/sites/site-1?panel=intake");
    expect(siteTabHref("site-1", "manage", {}, scope)).toBe("/sites/site-1?section=manage");
  });

  it("carries a validated scope and scopes assetRef to the same catalog only", () => {
    const scope = { workAreaId: "wa-a", assetRef: "asset-1" };
    expect(siteTabHref("site-1", "analysis", {}, scope)).toBe(
      "/sites/site-1/analysis?workAreaId=wa-a&assetRef=asset-1",
    );
    expect(siteTabHref("site-1", "materials", {}, scope)).toBe(
      "/sites/site-1?panel=materials&workAreaId=wa-a&assetRef=asset-1",
    );
    // 탐색으로 돌아갈 때 정확한 관측을 잃지 않도록 현황·작업·관리에도 싣는다.
    expect(siteTabHref("site-1", "overview", {}, scope)).toBe("/sites/site-1?workAreaId=wa-a&assetRef=asset-1");
    expect(siteTabHref("site-1", "work-orders", {}, scope)).toBe(
      "/sites/site-1?panel=intake&workAreaId=wa-a&assetRef=asset-1",
    );
    expect(siteTabHref("site-1", "manage", {}, scope)).toBe(
      "/sites/site-1?section=manage&workAreaId=wa-a&assetRef=asset-1",
    );
  });

  it("drops assetRef without its work area", () => {
    expect(siteTabHref("site-1", "materials", {}, { workAreaId: null, assetRef: "asset-1" })).toBe(
      "/sites/site-1?panel=materials",
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
  it("links analysis and space direct with scope in the directly visible nav", () => {
    const html = headerHtml({ scopedWorkAreaId: "wa-a", scopedAssetRef: "asset-1" });
    // 데스크톱·모바일 구분 없는 직접 nav 하나에 같은 목적지를 둔다.
    expect(html.match(/\/sites\/site-1\/analysis\?workAreaId=wa-a/g)?.length).toBe(1);
    expect(html.match(/\/sites\/site-1\?workAreaId=wa-a&amp;assetRef=asset-1/g)?.length).toBe(1);
    expect(html).not.toContain("section=analysis");
    expect(html).not.toContain("section=materials");
    // 세 영역을 펼침 없이 바로 보인다 — 이름 없는 아이콘-only 진입 금지.
    // 설정은 최상위 nav가 아니라 머리 설정 메뉴에 둔다. 끝 위치는 nav 닫힘으로
    // 끊는다(뒤따르는 설정 메뉴 링크를 세지 않는다).
    const navLabel = html.indexOf('aria-label="현장 영역 메뉴"');
    const navOpen = html.lastIndexOf("<nav", navLabel);
    const nav = html.slice(navOpen, html.indexOf("</nav>", navLabel));
    expect(nav.match(/<a[\s>]/g)?.length).toBe(2);
    expect(nav).not.toContain("section=work-orders");
    expect(nav).not.toContain("section=manage");
    expect(html).toContain("공간");
    expect(html).toContain("설정");
    expect(html).toContain("분석");
    expect(html).toContain('aria-current="page"');
  });

  it("keeps in-page sections and old deep-URL compat for work and manage", () => {
    const html = headerHtml({ scopedWorkAreaId: "wa-a" });
    expect(html).toContain("/sites/site-1?section=manage");
    // 옛 작업 URL은 최상위 탭이 아니라 자료 문맥의 「더 보기」가 소유한다 —
    // 헤더에 네 번째 탭이나 중복 링크를 만들지 않는다. 표준 목적지는
    // canonical helper가 그대로 유지한다.
    expect(html).not.toContain("section=work-orders");
    expect(siteTabHref("site-1", "work-orders", {}, { workAreaId: "wa-a", assetRef: null })).toBe(
      "/sites/site-1?panel=intake&workAreaId=wa-a",
    );
  });

  it("never leaks an unverified scope (page maps it to null)", () => {
    const html = headerHtml({});
    expect(html).toContain("/sites/site-1/analysis");
    expect(html).not.toContain("workAreaId");
    expect(html).not.toContain("assetRef");
  });

  it("leaves registration and work area actions to their owning screens", () => {
    for (const tab of ["space", "analysis", "manage"] as const) {
      const html = headerHtml({ tab, scopedWorkAreaId: "wa-a" });
      expect(html).not.toContain("observations/new");
      expect(html).not.toContain("/work-areas");
    }
  });
});
