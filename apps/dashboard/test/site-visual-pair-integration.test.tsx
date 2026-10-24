/** @vitest-environment jsdom */
import { renderToStaticMarkup } from "react-dom/server";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";
import { SiteWorkspaceCompare } from "@/app/sites/[siteId]/SiteWorkspaceCompare";
import { SiteWorkspaceResults } from "@/app/sites/[siteId]/SiteWorkspaceResults";
import { SiteWindowedPixelViewer } from "@/app/sites/[siteId]/SiteWindowedPixelViewer";
import { AnalysisRequestPanel } from "@/app/sites/[siteId]/analysis/AnalysisRequestPanel";
import { resolveExplicitComparison, type WorkspaceServerFacts } from "@/lib/site-workspace-entry";

const ref = (digit: string) => `ksa-v1-${digit.repeat(64)}`;
const SUB_A = `ers-v1-${"a".repeat(64)}`;
const SUB_B = `ers-v1-${"b".repeat(64)}`;

const area = {
  schemaVersion: "1.0",
  siteId: "site-1",
  workAreaId: "area-1",
  name: "구역",
  polygon: { type: "Polygon", coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 0]]]] },
  crs: "EPSG:5186",
  status: "ACTIVE",
  supersedes: null,
  createdAt: "2026-10-10T00:00:00Z",
} as never;

const catalogAssets = [
  { assetRef: ref("1"), workAreaId: "area-1", workOrderId: "w-a", observationEpochId: "epoch-a", kind: "ortho", submissionRef: SUB_A, revision: 1, declared: { fileName: "o1.tif" }, inspection: { raster: null, outcome: "PASS" }, analysisStatus: "NOT_EVALUATED" },
  { assetRef: ref("2"), workAreaId: "area-1", workOrderId: "w-b", observationEpochId: "epoch-b", kind: "dsm", submissionRef: SUB_B, revision: 1, declared: { fileName: "d1.tif" }, inspection: { raster: null, outcome: "PASS" }, analysisStatus: "NOT_EVALUATED" },
  { assetRef: ref("3"), workAreaId: "area-1", workOrderId: "w-c", observationEpochId: "epoch-c", kind: "ortho", submissionRef: SUB_A, revision: 1, declared: { fileName: "o3.tif" }, inspection: { raster: null, outcome: "PASS" }, analysisStatus: "NOT_EVALUATED" },
] as never;

function observation(assetRef: string, epoch: string, submissionRef: string, workOrderId: string, captureDate: string | null) {
  return {
    observationEpochId: epoch,
    workAreaId: "area-1",
    workOrderId,
    assetRef,
    submissionRef,
    revision: 1,
    kind: assetRef === ref("1") ? "ortho" : "dsm",
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

const facts = {
  siteId: "site-1",
  authorizedWorkAreaIds: ["area-1"],
  entryDefault: null,
  observations: [
    observation(ref("1"), "epoch-a", SUB_A, "w-a", "2026-10-06"),
    observation(ref("2"), "epoch-b", SUB_B, "w-b", "2026-10-13"),
    {
      ...observation(ref("3"), "epoch-c", SUB_A, "w-c", null),
      chronologyCandidate: true,
      captureStartedAt: "2026-10-20T03:00:00Z",
      captureEndedAt: "2026-10-20T03:30:00Z",
    },
  ],
  analyses: [],
} as unknown as WorkspaceServerFacts;

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("visual pair routed integration (rendered)", () => {
  it("renders one A/B flow with a visible pair->analysis CTA carrying hints and return refs", () => {
    const html = renderToStaticMarkup(
      <SiteWorkspaceCompare
        sitePath="/sites/site-1"
        areas={[area]}
        selectedWorkAreaId="area-1"
        catalogAssets={catalogAssets}
        projectionState="ready"
        workspaceHasMore={false}
        baselineRequestedRef={null}
        currentRequestedRef={null}
        resolution={{ status: "prompt" }}
        visualARequestedRef={ref("1")}
        visualBRequestedRef={ref("2")}
        visualPair={{ status: "ready", basis: "explicit-visual", workAreaId: "area-1", sideA: facts.observations[0]!, sideB: facts.observations[1]! }}
        canCreateAnalysis
        canCreateWorkOrder={false}
        scopedCompareHref={`/sites/site-1/analysis?workAreaId=area-1&hintBaselineWorkOrderId=w-a&hintBaselineSubmissionRef=${SUB_A}&hintBaselineRevision=1&hintCurrentWorkOrderId=w-b&hintCurrentSubmissionRef=${SUB_B}&hintCurrentRevision=1&visualAAssetRef=${ref("1")}&visualBAssetRef=${ref("2")}`}
        exploreHref="/sites/site-1"
        facts={facts}
      />,
    );
    expect(html).toContain("독립 보기 — 정합 근거 없음");
    expect(html).toContain("이 쌍으로 분석 조건 확인");
    expect(html).toContain("hintBaselineSubmissionRef=");
    expect(html).toContain("hintCurrentSubmissionRef=");
    expect(html).toContain("visualAAssetRef=");
    expect(html).toContain("visualBAssetRef=");
    expect(html).toContain("관측 A");
    expect(html).toContain("관측 B");
    // The legacy strict form is a labelled disclosure, not a second primary form.
    expect(html).toContain("기존 시간 순서 보기");
    const [beforeDisclosure, afterDisclosure] = html.split("기존 시간 순서 보기");
    expect(beforeDisclosure).not.toContain("나란히 보기</button>");
    expect(afterDisclosure).toContain("나란히 보기</button>");
  });

  it("shows the invalid pair notice and never copies unknown refs into navigation", () => {
    const ghost = `ksa-v1-${"f".repeat(64)}`;
    const html = renderToStaticMarkup(
      <SiteWorkspaceCompare
        sitePath="/sites/site-1"
        areas={[area]}
        selectedWorkAreaId="area-1"
        catalogAssets={catalogAssets}
        projectionState="ready"
        workspaceHasMore={false}
        baselineRequestedRef={null}
        currentRequestedRef={null}
        resolution={{ status: "prompt" }}
        visualARequestedRef={ref("1")}
        visualBRequestedRef={ghost}
        visualPair={{ status: "unresolvable", intent: "comparison", reason: "unknown-asset", headline: "요청한 비교 대상을 확인할 수 없습니다", detail: "막힘" }}
        canCreateAnalysis
        canCreateWorkOrder={false}
        scopedCompareHref="/sites/site-1/analysis?workAreaId=area-1"
        exploreHref="/sites/site-1"
        facts={facts}
      />,
    );
    expect(html).toContain("요청한 비교 대상을 확인할 수 없습니다");
    expect(html).not.toContain(ghost);
    expect(html).not.toContain("이 쌍으로 분석 조건 확인");
  });

  it("keeps stored-result links frozen while preserving the return context", () => {
    const html = renderToStaticMarkup(
      <SiteWorkspaceResults
        sitePath="/sites/site-1"
        areaLabel="구역"
        areaAnalyses={[{
          analysisId: "analysis-1",
          siteId: "site-1",
          workAreaId: "area-1",
          executionState: "COMPLETED",
          suitabilityState: "EVALUATED",
          createdAt: "2026-10-14T00:00:00Z",
          resultId: null,
          metrics: null,
          limitationCount: 0,
          analysisHref: "/x",
        }]}
        analysesKnown
        explicitResult={null}
        explicitDetail={null}
        leadDetail={null}
        facts={facts}
        canCreateAnalysis={false}
        scopedCompareHref="/sites/site-1/analysis?workAreaId=area-1"
        visualContext={{ workAreaId: "area-1", visualAAssetRef: ref("1"), visualBAssetRef: ref("2") }}
      />,
    );
    expect(html).toContain(`analysisId=analysis-1`);
    expect(html).toContain(`visualAAssetRef=${ref("1")}`);
    expect(html).toContain(`visualBAssetRef=${ref("2")}`);
    expect(html).toContain("독립 보기로 돌아가기");
  });

  it("copies only the canonical pair into header navigation, never unknown requests", () => {
    const site = { siteId: "site-1", name: "현장", status: "UNMAPPED", registeredAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-02T00:00:00Z", siteFrame: { crs: "EPSG:5186", transformVersion: "v1" }, aoi: null, resumeTarget: null } as never;
    const withPair = renderToStaticMarkup(
      <SiteHeader
        site={site}
        selectedEpochId={null}
        tab="workspace"
        canCreateWorkOrder={false}
        canEditAoi={false}
        scopedWorkAreaId="area-1"
        scopedAssetRef={null}
        visualContext={{
          workAreaId: "area-1",
          visualAAssetRef: ref("1"),
          visualBAssetRef: ref("2"),
        }}
      />,
    );
    expect(withPair).not.toContain("hintBaselineSubmissionRef=");
    expect(withPair).not.toContain("#new-analysis-request");
    expect(withPair).toContain(`visualAAssetRef=${ref("1")}`);
    const withoutPair = renderToStaticMarkup(
      <SiteHeader site={site} selectedEpochId={null} tab="workspace" canCreateWorkOrder={false} canEditAoi={false} />,
    );
    expect(withoutPair).not.toContain("visualAAssetRef");
    expect(withoutPair).not.toContain("hintBaseline");
  });

  it("renders per-side layer switches as URLs carrying the exact chosen ref", () => {
    const layers = [
      { assetRef: ref("1"), observationEpochId: "epoch-a", kind: "ortho", kindLabel: "정사영상", isDsm: false, fileName: "o1.tif", revision: 1, submissionRef: SUB_A, inspectedRaster: null, observedCrsIdentifier: "EPSG:5186", observedCrsDigest: "dd", inspectionOutcome: "MEASURED", verticalReference: null },
      { assetRef: `ksa-v1-${"c".repeat(64)}`, observationEpochId: "epoch-a", kind: "dsm", kindLabel: "DSM", isDsm: true, fileName: "d1.tif", revision: 1, submissionRef: SUB_A, inspectedRaster: null, observedCrsIdentifier: "EPSG:5186", observedCrsDigest: "dd", inspectionOutcome: "MEASURED", verticalReference: null },
    ] as never;
    const html = renderToStaticMarkup(
      <SiteWindowedPixelViewer
        siteId="site-1"
        workAreaId="area-1"
        layers={layers}
        jobs={[]}
        jobsState="unavailable"
        canRead={false}
        canRequest={false}
        requestsHref="/x"
        workAreaRing={null}
        workAreaCrs="EPSG:5186"
        observationHeading="관측 A"
        idPrefix="t"
        selectedAssetRef={ref("1")}
        layerSelectHref={`/sites/site-1?mode=compare&workAreaId=area-1&visualAAssetRef=${ref("1")}&visualBAssetRef=${ref("2")}`}
        layerSelectParam="visualAAssetRef"
      />,
    );
    expect(html).toContain(`visualAAssetRef=${encodeURIComponent(`ksa-v1-${"c".repeat(64)}`)}`);
    expect(html).toContain('aria-current="true"');
  });

  it("keeps the legacy strict helper negatives unchanged (date-only still refused)", () => {
    expect(resolveExplicitComparison(facts, {
      workAreaId: "area-1",
      baselineAssetRef: ref("1"),
      currentAssetRef: ref("2"),
    })).toMatchObject({ status: "unresolvable" });
  });
});

describe("analysis handoff panel (rendered draft, frozen inputs, no auto POST)", () => {
  const selector = (workOrderId: string, submissionRef: string) => ({ workOrderId, submissionRef, revision: 1 });
  const observations = [
    { selector: selector("w-a", SUB_A), observationEpochId: "epoch-a", captureStartedAt: "2026-10-06T03:00:00Z", captureEndedAt: "2026-10-06T03:30:00Z", workAreaIds: ["area-1"] },
    { selector: selector("w-b", SUB_B), observationEpochId: "epoch-b", captureStartedAt: "2026-10-13T03:00:00Z", captureEndedAt: "2026-10-13T03:30:00Z", workAreaIds: ["area-1"] },
  ] as never;

  function stubFetch(posts: string[]) {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if ((init?.method ?? "GET").toUpperCase() === "POST") posts.push(url);
      return Promise.resolve(new Response(JSON.stringify({ siteId: "site-1", items: [], nextCursor: null }), { status: 200 }));
    }));
  }

  it("prefills the exact matched pair and stays read-only until the explicit action", () => {
    const posts: string[] = [];
    stubFetch(posts);
    render(<AnalysisRequestPanel
      siteId="site-1"
      organizationId="org-1"
      principalId="operator-1"
      workAreas={[{ workAreaId: "area-1", name: "1구역" }]}
      observations={observations}
      siteObservations={observations}
      initialPage={{ siteId: "site-1", items: [], nextCursor: null }}
      initialSelectedDetail={null}
      canCreate
      initialAnalysisId={null}
      initialWorkAreaId="area-1"
      initialBaselineSelector={{ workOrderId: "w-a", submissionRef: SUB_A, revision: 1 }}
      initialCurrentSelector={{ workOrderId: "w-b", submissionRef: SUB_B, revision: 1 }}
    />);
    const baseline = screen.getByLabelText("기준 관측") as HTMLSelectElement;
    const current = screen.getByLabelText("현재 관측") as HTMLSelectElement;
    expect(baseline.value).not.toBe("");
    expect(current.value).not.toBe("");
    expect(baseline.value).not.toBe(current.value);
    expect(posts.filter((url) => /analyses/.test(url))).toEqual([]);
  });

  it("leaves a deep result untouched and reachable when hints point at missing candidates", () => {
    const posts: string[] = [];
    stubFetch(posts);
    const ghost = `ers-v1-${"f".repeat(64)}`;
    render(<AnalysisRequestPanel
      siteId="site-1"
      organizationId="org-1"
      principalId="operator-1"
      workAreas={[{ workAreaId: "area-1", name: "1구역" }]}
      observations={observations}
      siteObservations={observations}
      initialPage={{ siteId: "site-1", items: [], nextCursor: null }}
      initialSelectedDetail={null}
      canCreate
      initialAnalysisId="analysis-frozen"
      initialWorkAreaId="area-1"
      initialBaselineSelector={{ workOrderId: "w-a", submissionRef: ghost, revision: 1 }}
      initialCurrentSelector={{ workOrderId: "w-b", submissionRef: SUB_B, revision: 1 }}
      exactHintNotice="요청한 관측을 분석 후보에서 확인하지 못했습니다. 기준·현재 관측을 직접 선택하세요."
      visualContext={{ workAreaId: "area-1", visualAAssetRef: ref("1"), visualBAssetRef: ref("2") }}
      visualReturnHref={`/sites/site-1?mode=compare&workAreaId=area-1&visualAAssetRef=${ref("1")}&visualBAssetRef=${ref("2")}`}
    />);
    expect(screen.getByText(/요청한 관측을 분석 후보에서 확인하지 못했습니다/)).toBeTruthy();
    const returnLinks = screen.getAllByRole("link", { name: "독립 보기로 돌아가기" });
    expect(returnLinks.length).toBeGreaterThanOrEqual(1);
    for (const link of returnLinks) {
      expect(link.getAttribute("href")).toBe(`/sites/site-1?mode=compare&workAreaId=area-1&visualAAssetRef=${ref("1")}&visualBAssetRef=${ref("2")}`);
    }
    expect(posts.filter((url) => /analyses/.test(url))).toEqual([]);
  });
});
