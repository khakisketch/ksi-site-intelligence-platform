import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SpatialWorkbenchFrame } from "@/components/site/SpatialWorkbenchFrame";

function frameHtml(props: Partial<Parameters<typeof SpatialWorkbenchFrame>[0]> = {}) {
  return renderToStaticMarkup(
    <SpatialWorkbenchFrame
      toolbar={<p>도구모음</p>}
      rail={<nav aria-label="자료 목록">레일</nav>}
      stage={<section aria-label="선택한 자료 미리보기">무대</section>}
      inspectorId="test-inspector"
      inspectorLabel="선택 자료 정보"
      {...props}
    />,
  );
}

describe("spatial workbench frame", () => {
  it("keeps the toolbar, rail and stage in one coherent order without a ghost inspector column", () => {
    const html = frameHtml();
    expect(html).toContain("도구모음");
    expect(html).toContain("자료 목록");
    expect(html).toContain("선택한 자료 미리보기");
    // 정보가 닫히면 자리·열을 차지하지 않는다.
    expect(html).not.toContain("test-inspector");
    expect(html).not.toContain("선택 자료 정보");
    expect(html).not.toContain("320px");
    // 휴대폰에서는 무대가 레일보다 먼저다.
    expect(html.indexOf("선택한 자료 미리보기")).toBeLessThan(html.indexOf("자료 목록"));
  });

  it("opens the inspector in its own bounded column and folds the rail away", () => {
    const html = frameHtml({
      inspector: <p>선택한 것만</p>,
      inspectorOpen: true,
    });
    expect(html).toContain("test-inspector");
    expect(html).toContain("선택 자료 정보");
    expect(html).toContain("선택한 것만");
    expect(html).toContain("320px");
    // 정보가 열리면 레일은 CSS로 접히고 무대+정보 2열이 된다 — 무대가
    // 좁아지거나 좌·우 보기가 세로로 꺾이지 않는다.
    expect(html).toContain("xl:hidden");
    expect(html).toContain("xl:col-start-1");
    expect(html).toContain("xl:col-start-2");
  });

  it("renders inspector content without the column when it is closed", () => {
    const html = frameHtml({
      inspector: <p>선택한 것만</p>,
      inspectorOpen: false,
    });
    expect(html).not.toContain("선택한 것만");
    expect(html).not.toContain("320px");
  });

  it("keeps an example banner above the toolbar when given", () => {
    const html = frameHtml({ banner: <p role="note">디자인 예시</p> });
    expect(html).toContain("디자인 예시");
    expect(html.indexOf("디자인 예시")).toBeLessThan(html.indexOf("도구모음"));
  });
});
