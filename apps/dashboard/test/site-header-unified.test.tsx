import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
import type { SiteView } from "@/lib/core-api/types";

const site = { siteId: "site-1", name: "동측 현장", status: "UNMAPPED", resumeTarget: null, aoi: null } as SiteView;
const visualA = `ksa-v1-${"a".repeat(64)}`;
const visualB = `ksa-v1-${"b".repeat(64)}`;

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

describe("unified site header", () => {
  it("uses one site header with a site breadcrumb, title, and status", () => {
    const html = headerHtml({ scopedWorkAreaId: "wa-a", scopedAssetRef: visualA });
    expect(html).toContain('data-site-nav="true"');
    expect(html).toContain('href="/sites"');
    expect(html).toContain("동측 현장");
    expect(html).toContain("현장 등록됨");
    expect(html).toContain('aria-label="현장 영역 메뉴"');
  });

  it("keeps exactly two underlined section links and one current section", () => {
    const html = headerHtml({ scopedWorkAreaId: "wa-a", scopedAssetRef: visualA });
    const navLabel = html.indexOf('aria-label="현장 영역 메뉴"');
    const navOpen = html.lastIndexOf("<nav", navLabel);
    const nav = html.slice(navOpen, html.indexOf("</nav>", navLabel));
    expect(nav.match(/<a[\s>]/g)).toHaveLength(2);
    expect(nav.match(/aria-current="page"/g)).toHaveLength(1);
    for (const label of ["공간", "분석"]) expect(nav).toContain(`>${label}<`);
    expect(nav).not.toContain("작업 기록");
    expect(nav).not.toContain("section=manage");
  });

  it("moves the site sections to the desktop rail at lg without removing the mobile tabs", () => {
    const html = headerHtml({ scopedWorkAreaId: "wa-a" });
    const navLabel = html.indexOf('aria-label="현장 영역 메뉴"');
    const navOpen = html.lastIndexOf("<nav", navLabel);
    const nav = html.slice(navOpen, html.indexOf("</nav>", navLabel));
    expect(nav).toContain("lg:hidden");
    expect(nav).toContain("overflow-x-auto");
  });

  it("preserves the validated scope and exact visual pair", () => {
    const html = headerHtml({
      scopedWorkAreaId: "wa-a",
      scopedAssetRef: visualA,
      visualContext: { workAreaId: "wa-a", visualAAssetRef: visualA, visualBAssetRef: visualB },
    });
    expect(html).toContain("/sites/site-1?workAreaId=wa-a");
    expect(html).toContain("/sites/site-1/analysis?workAreaId=wa-a");
    expect(html).toContain(`visualAAssetRef=${visualA}`);
    expect(html).toContain(`visualBAssetRef=${visualB}`);
    expect(html).not.toContain("hintBaseline");
    expect(html).not.toContain("hintCurrent");
  });

  it("keeps settings separate from the tabs, with one link", () => {
    const html = headerHtml();
    expect(html.match(/aria-label="현장 설정"/g)).toHaveLength(1);
    expect(html).toContain("/sites/site-1?section=manage");
    expect(html).not.toContain("작업 기록");
  });

  it("leaves primary actions to each surface", () => {
    for (const tab of ["space", "analysis", "manage"] as const) {
      const html = headerHtml({ tab });
      expect(html).not.toContain("/observations/new");
      expect(html).not.toContain("/work-areas");
    }
  });

  it("drops unverified scope instead of inventing query parameters", () => {
    const html = headerHtml({});
    expect(html).toContain("/sites/site-1");
    expect(html).toContain("/sites/site-1/analysis");
    expect(html).not.toContain("workAreaId");
    expect(html).not.toContain("assetRef");
  });

  it("visually de-emphasizes a trailing license or sample parenthetical while preserving the full heading text", () => {
    const html = headerHtml({
      site: { ...site, name: "Floreat public sample (CC BY 4.0)" },
    });
    expect(html).toContain("<span>Floreat public sample</span>");
    expect(html).toContain(" (CC BY 4.0)</span>");
  });
});
