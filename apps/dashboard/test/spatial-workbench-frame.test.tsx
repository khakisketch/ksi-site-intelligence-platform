import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SpatialWorkbenchFrame } from "@/components/site/SpatialWorkbenchFrame";

function frameHtml(props: Partial<Parameters<typeof SpatialWorkbenchFrame>[0]> = {}) {
  return renderToStaticMarkup(
    <SpatialWorkbenchFrame
      contextBar={<p>맥락막대</p>}
      catalog={<nav aria-label="자료 목록">목록 내용</nav>}
      catalogLabel="자료 목록"
      stage={<section aria-label="선택한 자료 미리보기">무대</section>}
      inspectorId="test-inspector"
      inspectorLabel="선택 자료 정보"
      detailsHostId="workbench-test-details"
      {...props}
    />,
  );
}

describe("spatial workbench frame", () => {
  it("keeps the stage first with a closed catalog drawer and no visible inspector", () => {
    const html = frameHtml();
    expect(html).toContain("맥락막대");
    expect(html).toContain("선택한 자료 미리보기");
    // 목록 드로어는 닫혀 있다 — 열기 단추만 둔다.
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('aria-controls="workbench-catalog"');
    expect(html).not.toContain("목록 내용");
    // 정보가 닫히면 자리를 차지하지 않는다 — 자리는 마운트 유지하되 숨긴다.
    expect(html).toContain('id="test-inspector"');
    expect(html).toContain("display:none");
    expect(html).not.toContain("선택한 것만");
  });

  it("opens the catalog drawer without resizing the stage", () => {
    const html = frameHtml({ defaultCatalogOpen: true });
    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain('id="workbench-catalog"');
    expect(html).toContain("자료 목록");
    expect(html).toContain("목록 내용");
    expect(html).toContain("닫기");
    // 무대는 그대로 있다 — 드로어가 덮을 뿐 너비를 바꾸지 않는다.
    expect(html).toContain("선택한 자료 미리보기");
    expect(html.indexOf("선택한 자료 미리보기")).toBeLessThan(html.indexOf('id="workbench-catalog"'));
  });

  it("opens the inspector drawer only when asked and keeps the stage", () => {
    const html = frameHtml({
      inspector: <p>선택한 것만</p>,
      inspectorOpen: true,
    });
    expect(html).toContain("test-inspector");
    expect(html).toContain("선택 자료 정보");
    expect(html).toContain("선택한 것만");
    expect(html).toContain("선택한 자료 미리보기");
  });

  it("hides the inspector column when it is closed without unmounting the details host", () => {
    const html = frameHtml({
      inspector: <p>선택한 것만</p>,
      inspectorOpen: false,
    });
    // 틀과 접힘 자리는 마운트 유지하되 숨긴다 — 본문은 두지 않는다.
    expect(html).toContain("test-inspector");
    expect(html).toContain("display:none");
    expect(html).not.toContain("선택한 것만");
    expect(html).toContain("workbench-test-details");
  });

  it("keeps an example banner above the context bar when given", () => {
    const html = frameHtml({ banner: <p role="note">디자인 예시</p> });
    expect(html).toContain("디자인 예시");
    expect(html.indexOf("디자인 예시")).toBeLessThan(html.indexOf("맥락막대"));
  });

  it("puts the current selection and a sheet-only view action at the catalog foot", () => {
    const html = frameHtml({
      defaultCatalogOpen: true,
      catalogFooter: <p>현재 선택 · A · 정사영상</p>,
      catalogDismissLabel: "이 선택으로 보기",
    });
    expect(html).toContain("현재 선택 · A · 정사영상");
    expect(html).toContain("이 선택으로 보기");
    // 요약은 목록 시트 안, 무대 뒤가 아니라 목록 끝에 둔다.
    expect(html.indexOf("현재 선택")).toBeGreaterThan(html.indexOf("목록 내용"));
  });
});
