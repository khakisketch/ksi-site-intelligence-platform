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
      tab="materials"
      canCreateWorkOrder={false}
      canEditAoi={false}
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
    expect(html).toContain('aria-label="현장 업무 메뉴"');
  });

  it("keeps exactly three underlined section links and one current section", () => {
    const html = headerHtml({ scopedWorkAreaId: "wa-a", scopedAssetRef: visualA });
    const navLabel = html.indexOf('aria-label="현장 업무 메뉴"');
    const navOpen = html.lastIndexOf("<nav", navLabel);
    const nav = html.slice(navOpen, html.indexOf("</nav>", navLabel));
    expect(nav.match(/<a[\s>]/g)).toHaveLength(3);
    expect(nav.match(/aria-current="page"/g)).toHaveLength(1);
    for (const label of ["작업공간", "자료", "결과"]) expect(nav).toContain(`>${label}<`);
    expect(nav).not.toContain("관측 작업 기록");
    expect(nav).not.toContain("section=manage");
  });

  it("preserves the validated scope and exact visual pair", () => {
    const html = headerHtml({
      scopedWorkAreaId: "wa-a",
      scopedAssetRef: visualA,
      visualContext: { workAreaId: "wa-a", visualAAssetRef: visualA, visualBAssetRef: visualB },
    });
    expect(html).toContain("/sites/site-1/spatial-assets?workAreaId=wa-a");
    expect(html).toContain("/sites/site-1/analysis?workAreaId=wa-a");
    expect(html).toContain(`visualAAssetRef=${visualA}`);
    expect(html).toContain(`visualBAssetRef=${visualB}`);
    expect(html).not.toContain("hintBaseline");
    expect(html).not.toContain("hintCurrent");
  });

  it("keeps site settings in one disclosure without duplicating the records tab", () => {
    const html = headerHtml({ scopedWorkAreaId: "wa-a" });
    expect(html).toContain("설정·정보");
    expect(html).toContain("작업구역 관리");
    expect(html).toContain("현장 전체 범위");
    expect(html).toContain("/sites/site-1?section=manage#site-aoi");
    // 관측 작업 기록은 자료 문맥의 「더 보기」가 소유한다 — 헤더에 중복하지 않는다.
    expect(html).not.toContain("관측 작업 기록");
  });

  it("drops unverified scope instead of inventing query parameters", () => {
    const html = headerHtml({});
    expect(html).toContain("/sites/site-1/spatial-assets");
    expect(html).toContain("/sites/site-1/analysis");
    expect(html).not.toContain("workAreaId");
    expect(html).not.toContain("assetRef");
  });
});
