/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SiteExploreCanvas } from "@/app/sites/[siteId]/SiteExploreCanvas";
import { SiteWorkspaceCompare } from "@/app/sites/[siteId]/SiteWorkspaceCompare";
import { SiteDisplayLegend } from "@/app/sites/[siteId]/SiteDisplayLegend";
import type { WorkArea } from "@/lib/core-api/types";
import type { WorkspaceServerFacts } from "@/lib/site-workspace-entry";

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
      const { unmount } = render(canvas({ mode }));
      const rail = screen.getByRole("complementary", { name: "공간 보기 선택" });
      const link = rail.querySelector('a[href*="/work-areas"]')!;
      expect(link.textContent).toBe("작업구역 관리");
      expect(link.getAttribute("href")).toBe("/sites/site-1/work-areas?workAreaId=area-1");
      expect(rail.textContent!.indexOf("작업구역")).toBeLessThan(rail.textContent!.indexOf("관측 시점"));
      expect(rail.textContent!.indexOf("관측 시점")).toBeLessThan(rail.textContent!.indexOf("표시 레이어"));
      expect(screen.getByRole("region", { name: "공간자료 뷰어" })).toBeTruthy();
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

const VISUAL_SUB_A = `ers-v1-${"a".repeat(64)}`;
const VISUAL_SUB_B = `ers-v1-${"b".repeat(64)}`;
const visualRef = (digit: string) => `ksa-v1-${digit.repeat(64)}`;

function visualObservation(assetRef: string, epoch: string, submissionRef: string, workOrderId: string, captureDate: string, kind = "dsm") {
  return {
    observationEpochId: epoch,
    workAreaId: "area-1",
    workOrderId,
    assetRef,
    submissionRef,
    revision: 1,
    kind,
    displayReady: true,
    inspectedRasterAvailable: true,
    chronologyCandidate: false,
    captureSourcesAgree: true,
    viewAvailable: true,
    viewUnavailableReason: null,
    viewAssetRef: assetRef,
    newerRevisionPending: false,
    newerRevisionState: null,
    captureStartedAt: null,
    captureEndedAt: null,
    captureDate,
  };
}

const visualFacts = {
  siteId: "site-1",
  authorizedWorkAreaIds: ["area-1"],
  entryDefault: null,
  observations: [
    visualObservation(visualRef("1"), "epoch-a", VISUAL_SUB_A, "w-a", "2026-10-06", "ortho"),
    visualObservation(visualRef("2"), "epoch-b", VISUAL_SUB_B, "w-b", "2026-10-13", "dsm"),
  ],
  analyses: [],
} as unknown as WorkspaceServerFacts;

const visualCatalog = [
  { assetRef: visualRef("1"), workAreaId: "area-1", workOrderId: "w-a", observationEpochId: "epoch-a", kind: "ortho", submissionRef: VISUAL_SUB_A, revision: 1, declared: { fileName: "o1.tif" }, inspection: { raster: null, outcome: "PASS" } },
  { assetRef: visualRef("2"), workAreaId: "area-1", workOrderId: "w-b", observationEpochId: "epoch-b", kind: "dsm", submissionRef: VISUAL_SUB_B, revision: 1, declared: { fileName: "d1.tif" }, inspection: { raster: null, outcome: "PASS" } },
];

const visualAreas = [{ workAreaId: "area-1", name: "검증 구역", status: "ACTIVE" }];

function compareControls(a = visualRef("1"), b = visualRef("2")) {
  return <SiteWorkspaceCompare
    sitePath="/sites/site-1"
    areas={visualAreas as never}
    selectedWorkAreaId="area-1"
    catalogAssets={visualCatalog as never}
    projectionState="ready"
    workspaceHasMore={false}
    baselineRequestedRef={null}
    currentRequestedRef={null}
    resolution={{ status: "prompt" }}
    visualARequestedRef={a}
    visualBRequestedRef={b}
    visualPair={{ status: "prompt" }}
    canCreateAnalysis
    canCreateWorkOrder={false}
    scopedCompareHref="/sites/site-1/analysis?workAreaId=area-1"
    exploreHref="/sites/site-1"
    facts={visualFacts}
  />;
}

function compareRailLayers() {
  return <div className="flex flex-col gap-3">
    <nav aria-label="관측 A 표시 레이어" className="flex flex-col gap-1">
      <p className="text-[12px] text-ink-muted">관측 A</p>
      <div id="workspace-visual-a-layer-controls" />
    </nav>
    <nav aria-label="관측 B 표시 레이어" className="flex flex-col gap-1">
      <p className="text-[12px] text-ink-muted">관측 B</p>
      <div id="workspace-visual-b-layer-controls" />
    </nav>
  </div>;
}

describe("compare selection rail (viewer-first compact)", () => {
  it("replaces dirty native selections when a layer URL or browser history changes the canonical pair", () => {
    const {rerender} = render(compareControls());
    fireEvent.change(screen.getByLabelText("관측 A"), {target:{value:visualRef("1")}});
    rerender(compareControls(visualRef("2"), visualRef("1")));
    expect((screen.getByLabelText("관측 A") as HTMLSelectElement).value).toBe(visualRef("2"));
    expect((screen.getByLabelText("관측 B") as HTMLSelectElement).value).toBe(visualRef("1"));
    rerender(compareControls());
    expect((screen.getByLabelText("관측 A") as HTMLSelectElement).value).toBe(visualRef("1"));
  });

  it("keeps one tight A/B flow: no card, no long paragraph, GET submit intact", () => {
    render(<SiteExploreCanvas sitePath="/sites/site-1" areas={visualAreas as never} selectedWorkAreaId="area-1"
      captureOptions={[]} selectedCaption={null} coverageNote={null} mode="compare"
      observationControls={compareControls()} layers={compareRailLayers()}>
      <p>보기 자리</p>
    </SiteExploreCanvas>);
    const rail = screen.getByRole("complementary", { name: "공간 보기 선택" });
    const selectA = within(rail).getByLabelText("관측 A") as HTMLSelectElement;
    const selectB = within(rail).getByLabelText("관측 B") as HTMLSelectElement;
    const controls = selectA.closest("form")!;
    // 레일에는 카드 장식·긴 개념 문구가 없다 — 상태 고지는 보기 자리에서 한다.
    expect(controls.className).not.toContain("rounded-lg");
    expect(controls.textContent).not.toContain("위치 맞춤");
    expect(within(controls).queryByRole("heading", { name: "독립 보기 — 정합 근거 없음" })).toBeNull();
    expect(selectA.className).toContain("tap-target");
    expect(selectB.className).toContain("tap-target");
    const apply = within(controls).getByRole("button", { name: "독립 보기로 나란히 두기" });
    expect(apply.className).toContain("tap-target");
    const form = selectA.closest("form")!;
    expect(form.method).toBe("get");
    expect(form.querySelector('input[name="mode"]')).toBeTruthy();
    expect(form.querySelector('input[name="workAreaId"]')).toBeTruthy();
    expect(form.querySelector('select[name="visualAAssetRef"]')).toBeTruthy();
    expect(form.querySelector('select[name="visualBAssetRef"]')).toBeTruthy();
    // 리터럴 정밀도는 선택지에 그대로 둔다(클리핑돼도 근거는 남는다).
    expect(selectA.textContent).toContain("날짜만 확인");
  });

  it("lays the rail out without stretching: area full row, controls in DOM order, layers closed", () => {
    const { container } = render(<SiteExploreCanvas sitePath="/sites/site-1" areas={visualAreas as never} selectedWorkAreaId="area-1"
      captureOptions={[]} selectedCaption={null} coverageNote={null} mode="compare"
      observationControls={compareControls()} layers={compareRailLayers()}>
      <p>보기 자리</p>
    </SiteExploreCanvas>);
    const rail = screen.getByRole("complementary", { name: "공간 보기 선택" });
    const aside = rail.closest("aside")!;
    expect(aside.className).toContain("items-start");
    expect(aside.className).toContain("content-start");
    // 작업구역 줄은 작은 화면에서 전폭 행이다.
    const areaRow = within(rail).getByText(/작업구역 ·/).closest("div")!.parentElement!;
    expect(areaRow.className).toContain("sm:col-span-full");
    // 포커스/DOM 순서: 구역 → 관측 A → 관측 B → 적용 → 표시 레이어.
    const inOrder = (first: Element, second: Element) =>
      Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
    const selectA = within(rail).getByLabelText("관측 A");
    const selectB = within(rail).getByLabelText("관측 B");
    const apply = within(rail).getByRole("button", { name: "독립 보기로 나란히 두기" });
    const layerSummary = within(rail).getByText("표시 레이어");
    expect(inOrder(areaRow, selectA)).toBe(true);
    expect(inOrder(selectA, selectB)).toBe(true);
    expect(inOrder(selectB, apply)).toBe(true);
    expect(inOrder(apply, layerSummary)).toBe(true);
    // 레이어 그룹은 기본 닫힘 펼침 하나이며, 포털 자리는 중복 없이 그대로 있다.
    const disclosure = layerSummary.closest("details")!;
    expect(disclosure.hasAttribute("open")).toBe(false);
    expect(container.querySelectorAll("#workspace-visual-a-layer-controls")).toHaveLength(1);
    expect(container.querySelectorAll("#workspace-visual-b-layer-controls")).toHaveLength(1);
  });

  it("shows the short unregistered status near panes with details on demand", () => {
    const { container } = render(<SiteWorkspaceCompare
      sitePath="/sites/site-1"
      areas={visualAreas as never}
      selectedWorkAreaId="area-1"
      catalogAssets={visualCatalog as never}
      projectionState="ready"
      workspaceHasMore={false}
      baselineRequestedRef={null}
      currentRequestedRef={null}
      resolution={{ status: "prompt" }}
      visualARequestedRef={visualRef("1")}
      visualBRequestedRef={visualRef("2")}
      visualPair={{ status: "ready", basis: "explicit-visual", workAreaId: "area-1", sideA: visualFacts.observations[0]!, sideB: visualFacts.observations[1]! }}
      canCreateAnalysis
      canCreateWorkOrder={false}
      scopedCompareHref="/sites/site-1/analysis?workAreaId=area-1"
      exploreHref="/sites/site-1"
      facts={visualFacts}
    />);
    // 보기 자리 상태 줄: 짧은 고지 + 고른 쌍 정체성(정밀도 그대로).
    // 같은 문구는 상태 줄과 펼침 앞머리에 각각 한 번씩만 둔다.
    expect(screen.getAllByText(/독립 보기 — 정합 근거 없음/)).toHaveLength(2);
    expect(container.textContent).toContain("관측 A(");
    expect(container.textContent).toContain("날짜만 확인");
    // 긴 개념은 펼침 안에 둔다 — 보기 자리 첫 화면을 막지 않는다.
    const banner = screen.getByRole("heading", { name: "독립 보기 — 정합 근거 없음" }).closest("div")!;
    const details = banner.querySelector("details")!;
    expect(details.textContent).toContain("화면을 겹쳐도 분석 근거가 되지 않");
    expect(banner.querySelector(":scope > p")!.textContent).not.toContain("화면을 겹쳐도");
    // 분석 조건 확인 CTA는 그대로 둔다.
    expect(within(banner).getByRole("link", { name: "이 쌍으로 분석 조건 확인" })).toBeTruthy();
  });
});
