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
      {...props}
    />,
  );
}

describe("spatial workbench frame", () => {
  it("keeps the stage first with a closed catalog drawer and no ghost inspector column", () => {
    const html = frameHtml();
    expect(html).toContain("맥락막대");
    expect(html).toContain("선택한 자료 미리보기");
    // 목록 드로어는 닫혀 있다 — 열기 단추만 둔다.
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('aria-controls="workbench-catalog"');
    expect(html).not.toContain("목록 내용");
    // 정보가 닫히면 자리·열을 차지하지 않는다.
    expect(html).not.toContain("test-inspector");
    expect(html).not.toContain("선택 자료 정보");
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

  it("renders no inspector column when it is closed", () => {
    const html = frameHtml({
      inspector: <p>선택한 것만</p>,
      inspectorOpen: false,
    });
    expect(html).not.toContain("선택한 것만");
    expect(html).not.toContain("test-inspector");
  });

  it("keeps an example banner above the context bar when given", () => {
    const html = frameHtml({ banner: <p role="note">디자인 예시</p> });
    expect(html).toContain("디자인 예시");
    expect(html.indexOf("디자인 예시")).toBeLessThan(html.indexOf("맥락막대"));
  });
});
