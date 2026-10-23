import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
import type { SiteView } from "@/lib/core-api/types";

const site = { siteId: "site-1", name: "동측 현장", status: "UNMAPPED", resumeTarget: null, aoi: null } as SiteView;
const visualA = `ksa-v1-${"a".repeat(64)}`;
const visualB = `ksa-v1-${"b".repeat(64)}`;

function compactHtml(props: Partial<Parameters<typeof SiteHeader>[0]> = {}) {
  return renderToStaticMarkup(
    <SiteHeader
      site={site}
      selectedEpochId={null}
      tab="materials"
      canCreateWorkOrder={false}
      canEditAoi={false}
      variant="compact"
      {...props}
    />,
  );
}

describe("site header compact variant", () => {
  it("keeps the three section links with the validated scope", () => {
    const html = compactHtml({ scopedWorkAreaId: "wa-a", scopedAssetRef: visualA });
    expect(html).toContain('aria-label="현장 업무 메뉴"');
    expect(html).toContain("/sites/site-1/spatial-assets?workAreaId=wa-a");
    expect(html).toContain("/sites/site-1/analysis?workAreaId=wa-a");
    expect(html).toContain(`assetRef=${visualA}`);
    expect(html.match(/aria-current="page"/g)).toHaveLength(1);
  });

  it("carries the exact visual pair without inventing order hints", () => {
    const html = compactHtml({
      scopedWorkAreaId: "wa-a",
      visualContext: { workAreaId: "wa-a", visualAAssetRef: visualA, visualBAssetRef: visualB },
    });
    expect(html).toContain(`visualAAssetRef=${visualA}`);
    expect(html).toContain(`visualBAssetRef=${visualB}`);
    expect(html).not.toContain("hintBaseline");
    expect(html).not.toContain("hintCurrent");
  });

  it("keeps settings reachable from one disclosure without duplicating the records link", () => {
    const html = compactHtml({ scopedWorkAreaId: "wa-a" });
    expect(html).toContain("설정·정보");
    expect(html).toContain("작업구역 관리");
    expect(html).toContain("현장 전체 범위");
    // 자료 맥락 하위 행은 한 줄 머리에서 빼고, 작업공간·자료 화면의 「더 보기」가
    // 관측 작업 기록으로 이어진다 — 같은 링크를 두 자리에 두지 않는다.
    expect(html).not.toContain("관측 작업 기록");
    // 기본 머리의 큰 블록·펼침은 두지 않는다.
    expect(html).not.toContain("현장 정보·범위");
    expect(html).not.toContain("text-[16px]");
  });
});
