/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SiteExploreCanvas } from "@/app/sites/[siteId]/SiteExploreCanvas";
import { SiteDisplayLegend } from "@/app/sites/[siteId]/SiteDisplayLegend";
import type { WorkArea } from "@/lib/core-api/types";

const area = { workAreaId: "area-1", name: "검증 구역", status: "ACTIVE" } as WorkArea;
function canvas({ mode = "explore", detail = true }: { mode?: "explore" | "compare" | "results"; detail?: boolean } = {}) {
  return <SiteExploreCanvas sitePath="/sites/site-1" areas={[area]} selectedWorkAreaId="area-1"
    captureOptions={[{ assetRef: "asset-1", label: "2021. 8. 17. 촬영 (날짜만 확인 · 시각 미상)", title: "원본 1", selected: true }, { assetRef: "asset-2", label: "2022. 8. 17. 촬영 (날짜만 확인 · 시각 미상)", title: "원본 2", selected: false }]}
    selectedCaption="날짜만 확인 · 시각 미상" coverageNote={null} mode={mode}
    layers={<p>정사영상</p>} detail={detail ? <p>등록 파일의 메타데이터</p> : undefined}>
    <p>현재 계정에 준비된 표시 자료가 없습니다. 등록 자료가 없다는 뜻은 아닙니다.</p>
  </SiteExploreCanvas>;
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("workspace selection rail", () => {
  it("auto-submits the unchanged GET form with the chosen exact assetRef", () => {
    const submit = vi.spyOn(HTMLFormElement.prototype, "requestSubmit").mockImplementation(() => {});
    render(canvas());
    const select = screen.getByLabelText("관측 시점");
    fireEvent.change(select, { target: { value: "asset-2" } });
    expect(submit).toHaveBeenCalledTimes(1);
    const form = select.closest("form")!;
    expect(form.getAttribute("action")).toBe("/sites/site-1");
    expect(form.method).toBe("get");
    expect([...new FormData(form)]).toEqual([["workAreaId", "area-1"], ["assetRef", "asset-2"]]);
    expect(screen.queryByRole("button", { name: "보기" })).toBeNull();
    expect(form.querySelector("button")?.disabled).toBe(true);
  });

  it("defers selection and submit during IME composition until composition ends", () => {
    const submit = vi.spyOn(HTMLFormElement.prototype, "requestSubmit").mockImplementation(() => {});
    render(canvas());
    const select = screen.getByLabelText("관측 시점");
    fireEvent.compositionStart(select);
    fireEvent.change(select, { target: { value: "asset-2" } });
    expect(submit).not.toHaveBeenCalled();
    expect(fireEvent.submit(select.closest("form")!)).toBe(false);
    fireEvent.compositionEnd(select);
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it("server-renders an enabled no-JS fallback and the same precise date limit", () => {
    const html = renderToStaticMarkup(canvas());
    const doc = new DOMParser().parseFromString(html, "text/html");
    const form = doc.querySelector('select[name="assetRef"]')!.closest("form")!;
    const button = form.querySelector("button")!;
    expect(button.textContent).toBe("보기");
    expect(button.hasAttribute("hidden")).toBe(false);
    expect(button.hasAttribute("disabled")).toBe(false);
    expect(html).toContain("날짜만 확인 · 시각 미상");
  });

  it("keeps work-area management in the shared rail in every viewer mode", () => {
    for (const mode of ["explore", "compare", "results"] as const) {
      const { container, unmount } = render(canvas({ mode }));
      const rail = screen.getByRole("complementary", { name: "공간 보기 선택" });
      const link = rail.querySelector('a[href*="/work-areas"]')!;
      expect(link.textContent).toBe("작업구역 관리");
      expect(link.getAttribute("href")).toBe("/sites/site-1/work-areas?workAreaId=area-1");
      expect(rail.textContent!.indexOf("작업구역")).toBeLessThan(rail.textContent!.indexOf("관측 시점"));
      expect(rail.textContent!.indexOf("관측 시점")).toBeLessThan(rail.textContent!.indexOf("표시 레이어"));
      expect(container.querySelector('[aria-label="공간자료 뷰어"]')).toBeTruthy();
      unmount();
    }
  });

  it("reserves no third column until a selected item's native detail disclosure opens", () => {
    const { container, unmount } = render(canvas());
    const grid = screen.getByRole("region", { name: "선택 관측 화면" });
    expect(grid.className).toContain("lg:grid-cols-[260px_minmax(0,1fr)]");
    expect(grid.className).not.toContain("lg:has-[>details[open]]");
    expect(grid.className).toContain("xl:has-[>details[open]]:grid-cols-[260px_minmax(0,1fr)_320px]");
    const detail = container.querySelector("details[data-workspace-detail]")!;
    expect(detail.hasAttribute("open")).toBe(false);
    expect(detail.textContent).toContain("메타데이터");
    // Reading/focus order: the viewer precedes optional supporting metadata on phones.
    const viewer = container.querySelector('[aria-label="공간자료 뷰어"]')!;
    expect(viewer.compareDocumentPosition(detail) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    unmount();
    const noSelection = render(canvas({ detail: false }));
    expect(noSelection.container.querySelector("details[data-workspace-detail]")).toBeNull();
  });

  it("exposes four distinct explanatory legend states without claiming actual eligibility", () => {
    render(<SiteDisplayLegend />);
    for (const text of ["웹 미리보기 준비 필요", "원본의 유효 픽셀 영역 밖", "준비 중", "지도 표시와 정량 분석은 별개"]) expect(screen.getByText(text)).toBeTruthy();
    expect(screen.getByText(/정합·수직 기준·유효영역·독립 검사점/).textContent).toContain("확정하지 않습니다");
    expect(screen.getByText(/표시 준비 실패나 미확인 영역/)).toBeTruthy();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});
