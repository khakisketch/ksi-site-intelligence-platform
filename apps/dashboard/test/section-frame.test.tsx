import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SectionFrame } from "@/components/section/SectionFrame";

const frame = (props: { drawer?: boolean; drawerOpen?: boolean } = {}) => renderToStaticMarkup(
  <SectionFrame
    contextLabel="보기 조건"
    context={<p>컨텍스트</p>}
    inspectorLabel="선택 상세"
    inspector={<p>상세</p>}
    {...(props.drawer ? { drawerLabel: "기록", drawer: <p>서랍 내용</p>, drawerOpen: props.drawerOpen } : {})}
  >
    <p>본문</p>
  </SectionFrame>,
);

describe("SectionFrame (3단 탐색의 2·3단 배치)", () => {
  it("컨텍스트·본문·상세를 이 순서로 두고 이름 있는 영역으로 노출한다", () => {
    const html = frame();
    expect(html.indexOf("컨텍스트")).toBeLessThan(html.indexOf("본문"));
    expect(html.indexOf("본문")).toBeLessThan(html.indexOf("상세"));
    expect(html).toContain('<aside aria-label="보기 조건"');
    expect(html).toContain('<aside aria-label="선택 상세"');
    expect(html).toContain('id="section-inspector"');
  });

  it("열마다 따로 스크롤하는 것은 xl 이상뿐이다", () => {
    const html = frame();
    for (const cls of ["xl:overflow-y-auto", "xl:flex-row", "xl:w-[248px]", "xl:w-[340px]"]) expect(html).toContain(cls);
    expect(html).not.toMatch(/(?<![:\w-])overflow-y-auto/);
  });

  it("1280px 미만에서는 본문 → 상세 → 서랍 순으로 쌓는다", () => {
    const html = frame({ drawer: true });
    // 문서 순서는 컨텍스트·본문·서랍·상세이고, 좁은 화면의 시각 순서는 order 로만 바꾼다.
    expect(html).toContain("contents xl:flex");
    expect(html.indexOf("order-4")).toBeLessThan(html.indexOf("order-3"));
    for (const order of ["order-1", "order-2", "order-3", "order-4"]) expect(html).toContain(order);
    expect(html.match(/xl:order-none/g)).toHaveLength(4);
  });

  it("서랍은 있을 때만 그리고 기본은 접힘이다", () => {
    expect(frame()).not.toContain("<details");
    const closed = frame({ drawer: true });
    expect(closed).toContain("서랍 내용");
    expect(closed).toContain('data-section-drawer="true"');
    expect(closed).not.toContain('open=""');
    expect(frame({ drawer: true, drawerOpen: true })).toContain('open=""');
  });
});
