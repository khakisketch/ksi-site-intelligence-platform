/** @vitest-environment jsdom */
import { renderToStaticMarkup } from "react-dom/server";
import { cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import { SiteExploreCanvas } from "@/app/sites/[siteId]/SiteExploreCanvas";
import { SiteMosaicViewport } from "@/app/sites/[siteId]/SiteMosaicViewport";
import { SiteWindowedPixelViewer } from "@/app/sites/[siteId]/SiteWindowedPixelViewer";
import { SiteWorkspaceCompare } from "@/app/sites/[siteId]/SiteWorkspaceCompare";
import { SiteWorkspaceResults } from "@/app/sites/[siteId]/SiteWorkspaceResults";

/**
 * SSR/하이드레이션 회귀 — 브라우저 파서가 고쳐 쓰기 전에 구조가 맞아야 한다.
 * `<p>` 안에 블록 요소(div/aside/ul/section/details/form/제목 등)가 들어가면
 * React #418 하이드레이션 실패로 실제 화면이 깨진다. 정적 마크업에서 잡는다.
 */
const BLOCK = new Set([
  "div", "aside", "ul", "ol", "li", "section", "details", "form",
  "h1", "h2", "h3", "h4", "h5", "h6", "header", "footer", "nav",
  "table", "thead", "tbody", "tr", "td", "dl", "dt", "dd",
  "figure", "figcaption", "main", "article", "p",
]);
const VOID = new Set([
  "area", "base", "br", "col", "embed", "hr", "img", "input",
  "link", "meta", "param", "source", "track", "wbr",
]);

function invalidParagraphNesting(html: string): string[] {
  const issues: string[] = [];
  const stack: string[] = [];
  const re = /<\/?([a-zA-Z][a-zA-Z0-9]*)(\s[^>]*)?\/?>/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(html)) !== null) {
    const full = match[0];
    const tag = match[1]!.toLowerCase();
    const closing = full.startsWith("</");
    const selfClosing = full.endsWith("/>") || VOID.has(tag);
    if (closing) {
      const open = stack.lastIndexOf(tag);
      if (open >= 0) stack.splice(open);
      continue;
    }
    if (selfClosing) continue;
    if (BLOCK.has(tag) && stack.includes("p")) {
      issues.push(`<${tag}> inside <p> near: …${html.slice(Math.max(0, (match.index ?? 0) - 80), (match.index ?? 0))}«HERE»`);
    }
    stack.push(tag);
  }
  return issues;
}

const grid = { transform: [1, 0, 0, 0, -1, 512], width: 1022, height: 915 };

const layer = {
  assetRef: "a1",
  observationEpochId: "epoch-1",
  kind: "ortho",
  kindLabel: "정사영상",
  isDsm: false,
  fileName: "tile.tif",
  revision: 1,
  submissionRef: "s1",
  inspectedRaster: { ...grid },
  observedCrsIdentifier: "EPSG:5186",
  observedCrsDigest: "dd",
  inspectionOutcome: "MEASURED" as const,
  verticalReference: null,
};

const area = {
  schemaVersion: "1.0",
  siteId: "site-1",
  workAreaId: "tiny-1",
  name: "구역",
  polygon: { type: "Polygon", coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 0]]]] },
  crs: "EPSG:5186",
  status: "ACTIVE",
  supersedes: null,
  createdAt: "2026-10-10T00:00:00Z",
};

const facts = {
  siteId: "site-1",
  authorizedWorkAreaIds: ["tiny-1"],
  entryDefault: null,
  observations: [],
  analyses: [],
};

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("site workspace SSR paragraph nesting", () => {
  it("keeps the mosaic free of block-inside-paragraph", () => {
    const html = renderToStaticMarkup(
      <SiteMosaicViewport
        siteId="site-1"
        workAreaId="tiny-1"
        assetRef="a1"
        grid={grid}
        observedCrsDigest="dd"
        observedCrsIdentifier="EPSG:5186"
        isDsm={false}
        jobs={[]}
        canRequest
        requestsHref="/x"
      />,
    );
    expect(invalidParagraphNesting(html)).toEqual([]);
  });

  it("keeps the explore viewer free of block-inside-paragraph", () => {
    for (const slimHeader of [false, true]) {
      const html = renderToStaticMarkup(
        <SiteWindowedPixelViewer
          siteId="site-1"
          workAreaId="tiny-1"
          layers={[layer]}
          jobs={[]}
          jobsState="ready"
          canRead
          canRequest={false}
          requestsHref="/x"
          workAreaRing={null}
          workAreaCrs="EPSG:5186"
          observationHeading="정사영상 · 2021 포착"
          idPrefix="t"
          slimHeader={slimHeader}
        />,
      );
      expect(invalidParagraphNesting(html)).toEqual([]);
    }
  });

  it("keeps the canvas, compare prompt and results free of block-inside-paragraph", () => {
    const canvas = renderToStaticMarkup(
      <SiteExploreCanvas
        sitePath="/sites/site-1"
        areas={[area as never]}
        selectedWorkAreaId="tiny-1"
        captureOptions={[{ assetRef: "a1", label: "정사영상 · 2021 포착", title: "t", selected: true }]}
        selectedCaption="정사영상 · 2021 포착 · 등록 버전 1"
        coverageNote="부분 보기"
      >
        <div>canvas</div>
      </SiteExploreCanvas>,
    );
    const compare = renderToStaticMarkup(
      <SiteWorkspaceCompare
        sitePath="/sites/site-1"
        areas={[area as never]}
        selectedWorkAreaId="tiny-1"
        catalogAssets={[]}
        projectionState="ready"
        workspaceHasMore={false}
        baselineRequestedRef={null}
        currentRequestedRef={null}
        resolution={{ status: "prompt" }}
        canCreateAnalysis
        scopedCompareHref="/x"
        exploreHref="/y"
        facts={facts as never}
      />,
    );
    const results = renderToStaticMarkup(
      <SiteWorkspaceResults
        sitePath="/sites/site-1"
        areaLabel="구역"
        areaAnalyses={[{
          analysisId: "a1",
          siteId: "site-1",
          workAreaId: "tiny-1",
          executionState: "COMPLETED",
          suitabilityState: "EVALUATED",
          createdAt: "2026-10-14T00:00:00Z",
          resultId: null,
          metrics: null,
          limitationCount: 0,
          analysisHref: "/sites/site-1/analysis?analysisId=a1",
        }]}
        analysesKnown
        explicitResult={null}
        explicitDetail={null}
        leadDetail={null}
        facts={facts as never}
        canCreateAnalysis={false}
        scopedCompareHref="/x"
      />,
    );
    expect(invalidParagraphNesting(canvas)).toEqual([]);
    expect(invalidParagraphNesting(compare)).toEqual([]);
    expect(invalidParagraphNesting(results)).toEqual([]);
  });
});
