/** @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { CompareTimeStrip } from "@/app/sites/[siteId]/CompareTimeStrip";
import { SiteWorkspaceCompare } from "@/app/sites/[siteId]/SiteWorkspaceCompare";
import { buildCompareTimeline } from "@/app/sites/[siteId]/compare-timeline";
import type { SpatialAssetCatalogItem } from "@/lib/core-api/spatial-assets";
import type { WorkArea } from "@/lib/core-api/types";
import type { WorkspaceObservationFact, WorkspaceServerFacts } from "@/lib/site-workspace-entry";

afterEach(cleanup);

const AREA = "area-1";
const SITE_PATH = "/sites/site-1";
const ref = (n: number) => `ksa-v1-${String(n).padStart(64, "0")}`;

function fact(n: number, over: Partial<WorkspaceObservationFact> = {}): WorkspaceObservationFact {
  return {
    observationEpochId: `epoch-${n}`, workAreaId: AREA, workOrderId: `wo-${n}`, assetRef: ref(n), submissionRef: `sub-${n}`,
    revision: 1, kind: "dsm", captureStartedAt: null, captureEndedAt: null, captureDate: null, displayReady: true,
    inspectedRasterAvailable: true, chronologyCandidate: true, captureSourcesAgree: true, viewAvailable: true,
    viewUnavailableReason: null, viewAssetRef: ref(n), newerRevisionPending: false, newerRevisionState: null, ...over,
  };
}
function day(date: string): Partial<WorkspaceObservationFact> {
  return { captureStartedAt: `${date}T01:00:00Z`, captureEndedAt: `${date}T02:00:00Z` };
}
function catalog(n: number, crs: string, kind = "dsm"): SpatialAssetCatalogItem {
  return {
    assetRef: ref(n), kind, lifecycleState: "SEALED", declared: { captureDate: null, captureStartedAt: null },
    inspection: { outcome: "MEASURED", raster: { observedCrsIdentifier: crs } },
  } as unknown as SpatialAssetCatalogItem;
}
function facts(list: WorkspaceObservationFact[]): WorkspaceServerFacts {
  return { siteId: "site-1", authorizedWorkAreaIds: [AREA], entryDefault: null, observations: list, analyses: [] };
}

const LIST = [
  fact(1, day("2026-07-03")),
  fact(2, day("2026-08-21")),
  fact(3, { kind: "ortho", ...day("2026-09-11") }),
  fact(4, day("2026-10-02")),
  fact(5, day("2026-11-12")),
  fact(6, { chronologyCandidate: false, captureDate: "2026-09-14" }),
  fact(7, { chronologyCandidate: false }),
];
const CATALOG = [catalog(1, "EPSG:32652"), catalog(2, "EPSG:5186"), catalog(3, "EPSG:5186", "ortho"), catalog(4, "EPSG:5186"), catalog(5, "EPSG:5186")];

function strip(selected = true) {
  const model = buildCompareTimeline({
    facts: facts(LIST), workAreaId: AREA, catalogAssets: CATALOG,
    baselineAssetRef: selected ? ref(4) : null, currentAssetRef: selected ? ref(5) : null,
  });
  return render(
    <CompareTimeStrip model={model} sitePath={SITE_PATH} workAreaId={AREA}
      uploadHref={`${SITE_PATH}/upload?workAreaId=${AREA}`} canUpload analysisHref={`${SITE_PATH}/analysis?x=1`} />,
  );
}

describe("CompareTimeStrip", () => {
  it("점은 같은 GET 주소 파라미터로 이어지는 링크이고 고른 두 점은 aria-current다", () => {
    strip();
    const section = screen.getByRole("region", { name: "자료 날짜" });
    const current = within(section).getByRole("link", { name: /11월 12일.*이후로 선택됨/ });
    const baseline = within(section).getByRole("link", { name: /10월 2일.*이전으로 선택됨/ });
    expect(current.getAttribute("aria-current")).toBe("true");
    expect(baseline.getAttribute("aria-current")).toBe("true");
    const url = new URL(current.getAttribute("href")!, "http://x");
    expect(url.pathname).toBe(SITE_PATH);
    expect(url.searchParams.get("mode")).toBe("compare");
    expect(url.searchParams.get("workAreaId")).toBe(AREA);
    expect(url.searchParams.get("baselineAssetRef")).toBe(ref(4));
    expect(url.searchParams.get("currentAssetRef")).toBe(ref(5));
    // 점 주소의 키는 시간순 비교가 받는 네 개뿐이다(독립 보기 키와 함께 실리면 서버가 막는다).
    expect([...url.searchParams.keys()].sort()).toEqual(["baselineAssetRef", "currentAssetRef", "mode", "workAreaId"]);
    // 누를 수 있는 다른 점: 08-21은 바깥(앞쪽)이라 이전을 바꾼다.
    const other = within(section).getByRole("link", { name: /8월 21일.*이전으로 고르기/ });
    const otherUrl = new URL(other.getAttribute("href")!, "http://x");
    expect(otherUrl.searchParams.get("baselineAssetRef")).toBe(ref(2));
    expect(otherUrl.searchParams.get("currentAssetRef")).toBe(ref(5));
    expect(other.getAttribute("aria-current")).toBeNull();
    expect(section.textContent).toContain("41일 사이");
    expect(section.textContent).toContain("분석 좌표계 EPSG:5186");
  });

  it("좌표계가 다른 점과 높이 자료가 없는 점은 글자로 이유를 적고 링크가 아니다", () => {
    strip();
    const section = screen.getByRole("region", { name: "자료 날짜" });
    const different = within(section).getByRole("button", { name: /7월 3일.*좌표계 다름.*같은 좌표계 자료끼리만 비교.*고를 수 없음/ });
    expect((different as HTMLButtonElement).disabled).toBe(true);
    expect(section.textContent).toContain("좌표계 다름 · 32652");
    const noHeight = within(section).getByRole("button", { name: /9월 11일.*높이 자료 없음.*고를 수 없음/ });
    expect((noHeight as HTMLButtonElement).disabled).toBe(true);
    expect(section.textContent).toContain("높이 자료 없음");
    expect(within(section).queryAllByRole("link", { name: /7월 3일|9월 11일/ })).toHaveLength(0);
    // "비교 불가"를 단정하지 않는다.
    expect(section.textContent).not.toContain("비교 불가");
  });

  it("순서 미정 줄에 날짜만·미상 관측을 두고 점으로 그리지 않는다", () => {
    strip();
    const section = screen.getByRole("region", { name: "자료 날짜" });
    const row = section.querySelector("[data-compare-unordered]")!;
    expect(row.textContent).toContain("순서 미정");
    const items = [...row.querySelectorAll("li")].map((li) => li.textContent ?? "");
    expect(items.some((text) => text.includes("9월 14일") && text.includes("날짜만 확인"))).toBe(true);
    expect(items.some((text) => text.includes("촬영 시점 미상"))).toBe(true);
    expect(section.querySelector("[data-slot-date='2026-09-14']")).toBeNull();
    expect(within(row as HTMLElement).queryAllByRole("link")).toHaveLength(0);
  });

  it("체적·높이 차이 카드는 열려 있다고 말하지 않고 수락·정산·확정류 단어를 쓰지 않는다", () => {
    strip();
    const section = screen.getByRole("region", { name: "자료 날짜" });
    const notice = section.querySelector("[data-compare-volume]")!;
    expect(notice.textContent).toContain("체적·높이 차이는 이 화면에서 열려 있지 않습니다");
    expect(notice.textContent).toContain("분석 화면에서 확인합니다");
    expect(within(notice as HTMLElement).getByRole("link", { name: "분석 화면에서 확인" }).getAttribute("href")).toBe(`${SITE_PATH}/analysis?x=1`);
    expect(section.textContent).not.toMatch(/수락|정산|확정|승인/);
  });

  it("쌍이 없으면 날짜를 누르라고만 하고 이전·이후 이름표를 달지 않는다", () => {
    strip(false);
    const section = screen.getByRole("region", { name: "자료 날짜" });
    expect(section.textContent).toContain("날짜를 누르세요");
    expect(section.querySelector("[aria-current]")).toBeNull();
    const first = within(section).getByRole("link", { name: /8월 21일.*이전으로 고르기/ });
    const url = new URL(first.getAttribute("href")!, "http://x");
    expect(url.searchParams.get("baselineAssetRef")).toBe(ref(2));
    expect(url.searchParams.get("currentAssetRef")).toBe(ref(4));
  });

  it("높이 자료가 하나뿐이면 상태 카드와 올리기 링크를 보이고 점을 누를 수 없게 둔다", () => {
    const model = buildCompareTimeline({ facts: facts([fact(1, day("2026-10-02"))]), workAreaId: AREA, catalogAssets: [catalog(1, "EPSG:5186")] });
    render(<CompareTimeStrip model={model} sitePath={SITE_PATH} workAreaId={AREA} uploadHref={`${SITE_PATH}/upload`} canUpload analysisHref={null} />);
    const section = screen.getByRole("region", { name: "자료 날짜" });
    expect(section.querySelector("[data-compare-state='only-one']")!.textContent).toContain("비교할 높이 자료가 하나뿐입니다");
    expect(within(section).getByRole("link", { name: "높이 자료 올리기" })).toBeTruthy();
    expect(within(section).queryAllByRole("link", { name: /10월 2일/ })).toHaveLength(0);
    expect(section.querySelector("[data-compare-volume] a")).toBeNull(); // 권한이 없으면 링크를 두지 않는다
  });

  it("좌표계가 모두 달라 짝이 없으면 같은 좌표계 두 개가 필요하다고 알린다", () => {
    const model = buildCompareTimeline({
      facts: facts([fact(1, day("2026-10-02")), fact(2, day("2026-11-12"))]), workAreaId: AREA,
      catalogAssets: [catalog(1, "EPSG:5186"), catalog(2, "EPSG:32652")],
    });
    render(<CompareTimeStrip model={model} sitePath={SITE_PATH} workAreaId={AREA} />);
    const card = screen.getByRole("region", { name: "자료 날짜" }).querySelector("[data-compare-state='crs-mismatch']")!;
    expect(card.textContent).toContain("좌표계 다름 · 같은 좌표계 자료끼리만 비교");
    expect(card.textContent).toContain("같은 좌표계로 기록된 높이 자료 두 개");
    expect(card.textContent).toContain("5179 · 5185–5188 · UTM 51N · 52N");
    expect(card.textContent).not.toContain("비교 불가");
  });

  it("모든 점 링크가 시간순 비교 키 네 개만 싣는다", () => {
    strip();
    const links = [...document.querySelectorAll("[data-compare-timeline] ol a")];
    expect(links.length).toBeGreaterThan(1);
    for (const link of links) {
      const url = new URL(link.getAttribute("href")!, "http://x");
      expect([...url.searchParams.keys()].sort()).toEqual(["baselineAssetRef", "currentAssetRef", "mode", "workAreaId"]);
    }
  });

  it("분석 밖 좌표계는 흐리지 않고 회색 칩 '분석 밖 · 코드'만 붙인다", () => {
    const model = buildCompareTimeline({
      facts: facts([fact(1, day("2026-08-01")), fact(2, day("2026-08-20"))]), workAreaId: AREA,
      catalogAssets: [catalog(1, "EPSG:32750"), catalog(2, "EPSG:32750")],
    });
    render(<CompareTimeStrip model={model} sitePath={SITE_PATH} workAreaId={AREA} />);
    const section = screen.getByRole("region", { name: "자료 날짜" });
    expect(section.textContent).toContain("분석 밖 · 32750");
    expect(section.textContent).toContain("기준 좌표계 · 분석 밖 EPSG:32750");
    expect(within(section).getAllByRole("link", { name: /고르기$/ })).toHaveLength(2);
    expect(section.querySelector("[data-compare-state]")).toBeNull();
  });

  it("점 사이 최소 간격 76px(칩 폭 포함)을 지키도록 띠의 최소 폭을 잡는다", () => {
    const dated = [1, 2, 3, 4, 5, 6].map((n) => fact(n, day(`2026-10-0${n}`)));
    const model = buildCompareTimeline({ facts: facts(dated), workAreaId: AREA, catalogAssets: dated.map((_, i) => catalog(i + 1, "EPSG:5186")) });
    render(<CompareTimeStrip model={model} sitePath={SITE_PATH} workAreaId={AREA} />);
    const list = document.querySelector("[data-compare-timeline] ol") as HTMLElement;
    const lefts = model.slots.map((slot) => slot.leftPercent);
    const minGap = Math.min(...lefts.slice(1).map((value, i) => value - lefts[i]!));
    const minWidth = parseFloat(list.style.minWidth);
    expect((minWidth * minGap) / 100).toBeGreaterThanOrEqual(76);
    expect(list.parentElement!.className).toContain("overflow-x-auto");
  });

  it("선택한 두 관측이 띠에 없으면 아직 고르지 않았다고 하지 않는다", () => {
    const model = buildCompareTimeline({
      facts: facts([fact(1, { chronologyCandidate: false, captureDate: "2026-09-14" }), fact(2, day("2026-10-02")), fact(3, day("2026-11-02"))]),
      workAreaId: AREA, catalogAssets: [catalog(2, "EPSG:5186"), catalog(3, "EPSG:5186")],
      baselineAssetRef: ref(1), currentAssetRef: ref(2),
    });
    render(<CompareTimeStrip model={model} sitePath={SITE_PATH} workAreaId={AREA} />);
    const section = screen.getByRole("region", { name: "자료 날짜" });
    expect(section.textContent).toContain("선택한 두 관측이 이 띠에 없습니다");
    expect(section.textContent).not.toContain("아직 고르지 않았습니다");
    expect(section.querySelector("[aria-current]")).toBeNull();
  });

  it("해를 넘는 띠는 모든 점에 연도를 위 줄에 두고, 한 해 안이면 MM-DD 한 줄이다", () => {
    const multi = buildCompareTimeline({
      facts: facts([fact(1, day("2019-08-20")), fact(2, day("2021-08-17")), fact(3, day("2022-08-24"))]), workAreaId: AREA,
      catalogAssets: [1, 2, 3].map((n) => catalog(n, "EPSG:5186")),
    });
    const { unmount } = render(<CompareTimeStrip model={multi} sitePath={SITE_PATH} workAreaId={AREA} />);
    const slots = [...document.querySelectorAll("[data-slot-date]")];
    expect(slots.map((slot) => slot.textContent?.match(/(\d{4})(\d{2}-\d{2})/)?.slice(1).join("|"))).toEqual(["2019|08-20", "2021|08-17", "2022|08-24"]);
    unmount();
    strip(); // 같은 해(2026)
    expect(document.querySelector("[data-slot-date='2026-10-02']")!.textContent).toContain("10-02");
    expect(document.querySelector("[data-slot-date='2026-10-02']")!.textContent).not.toContain("2026");
  });

  it("띠 컨테이너는 가로로만 밀리고 세로 스크롤은 없으며 높이가 내용(연도 줄·칩·이름표)을 담는다", () => {
    const model = buildCompareTimeline({
      facts: facts([fact(1, day("2019-08-20")), fact(2, day("2021-08-17"))]), workAreaId: AREA,
      catalogAssets: [catalog(1, "EPSG:5186"), catalog(2, "EPSG:5186")], baselineAssetRef: ref(1), currentAssetRef: ref(2),
    });
    render(<CompareTimeStrip model={model} sitePath={SITE_PATH} workAreaId={AREA} />);
    const list = document.querySelector("[data-compare-timeline] ol") as HTMLElement;
    const scroller = list.parentElement!;
    expect(scroller.className).toContain("overflow-x-auto");
    expect(scroller.className).toContain("overflow-y-hidden");
    // 이름표 18 + 터치 44 + 연도 14 + 날짜·칩 18 이상. (실제 칩 잘림은 브라우저에서 메인이 다시 확인한다.)
    expect(parseFloat(list.style.height)).toBeGreaterThanOrEqual(18 + 44 + 14 + 18);
    const plain = (() => { cleanup(); strip(); return parseFloat((document.querySelector("[data-compare-timeline] ol") as HTMLElement).style.height); })();
    expect(parseFloat(list.style.height)).toBeGreaterThan(plain);
  });

  it("표시 준비 전이 원인이면 올리기 안내 없이 준비 전 건수만 알린다", () => {
    const model = buildCompareTimeline({
      facts: facts([1, 2, 3].map((n) => fact(n, { ...day(`2021-0${n}-10`), displayReady: false }))), workAreaId: AREA,
      catalogAssets: [1, 2, 3].map((n) => catalog(n, "EPSG:7850")),
    });
    render(<CompareTimeStrip model={model} sitePath={SITE_PATH} workAreaId={AREA} uploadHref={`${SITE_PATH}/upload`} canUpload analysisHref={null} />);
    const section = screen.getByRole("region", { name: "자료 날짜" });
    const card = section.querySelector("[data-compare-state='not-ready']")!;
    expect(card.textContent).toContain("표시 준비가 끝난 높이 자료가 두 개 이상 필요합니다");
    expect(card.textContent).toContain("지금 3건이 표시 준비 전입니다. 준비되면 이 띠에서 고를 수 있습니다.");
    expect(section.querySelector("[data-compare-state='only-one']")).toBeNull();
    expect(within(section).queryByRole("link", { name: "높이 자료 올리기" })).toBeNull();
    expect(section.textContent).not.toContain("노트북");
    expect(section.textContent).not.toMatch(/수락|정산|확정|승인/);
  });

  it("높이 자료가 0건이면 올리기 안내를 유지한다", () => {
    const model = buildCompareTimeline({ facts: facts([fact(1, { kind: "ortho", ...day("2026-10-02") })]), workAreaId: AREA, catalogAssets: [] });
    render(<CompareTimeStrip model={model} sitePath={SITE_PATH} workAreaId={AREA} uploadHref={`${SITE_PATH}/upload`} canUpload analysisHref={null} />);
    const section = screen.getByRole("region", { name: "자료 날짜" });
    expect(section.querySelector("[data-compare-state='only-one']")!.textContent).toContain("비교할 높이 자료가 없습니다");
    expect(within(section).getByRole("link", { name: "높이 자료 올리기" })).toBeTruthy();
    expect(section.textContent).toContain("올리기는 노트북에서 이어서 하세요.");
  });

  it("관측이 하나도 없으면 아무것도 그리지 않는다", () => {
    const model = buildCompareTimeline({ facts: facts([]), workAreaId: AREA, catalogAssets: [] });
    const { container } = render(<CompareTimeStrip model={model} sitePath={SITE_PATH} workAreaId={AREA} />);
    expect(container.innerHTML).toBe("");
  });
});

describe("SiteWorkspaceCompare presentation=timeline", () => {
  const area = {
    workAreaId: AREA, siteId: "site-1", name: "북측", status: "ACTIVE", geometries: [],
  } as unknown as WorkArea;

  function renderCompare(over: { baseline?: string; current?: string } = {}) {
    const server = facts(LIST);
    const baseline = over.baseline ? (server.observations.find((item) => item.assetRef === over.baseline) ?? null) : null;
    const current = over.current ? (server.observations.find((item) => item.assetRef === over.current) ?? null) : null;
    return render(
      <SiteWorkspaceCompare
        sitePath={SITE_PATH} areas={[area]} selectedWorkAreaId={AREA} catalogAssets={CATALOG}
        projectionState="ready" workspaceHasMore={false}
        baselineRequestedRef={over.baseline ?? null} currentRequestedRef={over.current ?? null}
        resolution={baseline && current ? { status: "ready", basis: "explicit", workAreaId: AREA, baseline, current } : { status: "prompt" }}
        canCreateAnalysis canCreateWorkOrder scopedCompareHref={`${SITE_PATH}/analysis`} exploreHref={SITE_PATH}
        facts={server} presentation="timeline"
      />,
    );
  }

  it("해석된 쌍을 이전·이후로 표시한다", () => {
    renderCompare({ baseline: ref(4), current: ref(5) });
    const section = screen.getByRole("region", { name: "자료 날짜" });
    expect(section.textContent).toContain("41일 사이");
    expect(within(section).getByRole("link", { name: /10월 2일.*이전으로 선택됨/ }).getAttribute("aria-current")).toBe("true");
  });

  it("독립 보기(visualA/B)가 주소에 있어도 점 주소에는 싣지 않는다", () => {
    render(
      <SiteWorkspaceCompare
        sitePath={SITE_PATH} areas={[area]} selectedWorkAreaId={AREA} catalogAssets={CATALOG}
        projectionState="ready" workspaceHasMore={false} baselineRequestedRef={null} currentRequestedRef={null}
        resolution={{ status: "prompt" }} visualARequestedRef={ref(2)} visualBRequestedRef={ref(4)}
        canCreateAnalysis canCreateWorkOrder scopedCompareHref={`${SITE_PATH}/analysis`} exploreHref={SITE_PATH}
        facts={facts(LIST)} presentation="timeline"
      />,
    );
    const links = [...document.querySelectorAll("[data-compare-timeline] ol a")];
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) {
      const keys = [...new URL(link.getAttribute("href")!, "http://x").searchParams.keys()];
      expect(keys).not.toContain("visualAAssetRef");
      expect(keys).not.toContain("visualBAssetRef");
      expect(keys.sort()).toEqual(["baselineAssetRef", "currentAssetRef", "mode", "workAreaId"]);
    }
  });

  it("쌍이 해석되지 않았으면 선택 표시 없이 고를 수 있는 점만 보인다", () => {
    renderCompare();
    const section = screen.getByRole("region", { name: "자료 날짜" });
    expect(section.querySelector("[aria-current]")).toBeNull();
    expect(within(section).getAllByRole("link", { name: /고르기$/ }).length).toBeGreaterThan(0);
  });
});
