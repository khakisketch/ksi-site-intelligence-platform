import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
  site: vi.fn(),
  areas: vi.fn(),
  catalog: vi.fn(),
  detail: vi.fn(),
  workOrders: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) =>
    createElement("a", { href, ...props }, children),
}));
vi.mock("next/navigation", () => ({ notFound: () => { throw new Error("NEXT_NOT_FOUND"); } }));
vi.mock("@/app/field/resolve-session", () => ({ resolveFieldSession: mocked.session }));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/spatial-assets", () => ({
  listSpatialAssets: mocked.catalog,
  getSpatialAsset: mocked.detail,
}));
vi.mock("@/lib/core-api/observation-work-orders", () => ({
  listObservationWorkOrders: mocked.workOrders,
}));
vi.mock("@/app/field/OperationsSessionFailure", () => ({
  OperationsSessionFailure: ({ verdict }: { verdict: { notice?: string } }) => createElement("p", null, verdict.notice ?? "로그인 필요"),
}));
vi.mock("@/components/ui/ErrorState", () => ({
  ErrorState: ({ message, detail }: { message: string; detail?: string }) => createElement("div", { role: "alert" }, `${message} ${detail ?? ""}`),
}));
vi.mock("@/lib/core-api/client", () => {
  class CoreApiError extends Error {
    constructor(readonly status: number, readonly retryAfterSeconds?: number) { super(`Core ${status}`); }
  }
  return { CoreApiError };
});

import SpatialAssetsPage from "@/app/sites/[siteId]/spatial-assets/page";

const digest = (letter: string) => `sha256:${letter.repeat(64)}`;
const assetRef = `ksa-v1-${"a".repeat(64)}`;
const workArea = { workAreaId: "area-1", name: "북측 작업구역", status: "ACTIVE" };

function asset(
  workAreaId = "area-1",
  kind = "dsm",
  captureInterval: { startedAt: string | null; endedAt: string | null } = { startedAt: null, endedAt: null },
) {
  return {
    assetRef,
    siteId: "site-1",
    workAreaId,
    workOrderId: "order-1",
    observationEpochId: "epoch-1",
    submissionRef: `ers-v1-${"b".repeat(64)}`,
    revision: 2,
    artifactId: "artifact-1",
    kind,
    lifecycleState: "SEALED",
    declared: {
      factClass: "DECLARED", fileName: "north-dsm.tif", format: "GeoTIFF", contentType: "image/tiff",
      sha256: "c".repeat(64), sizeBytes: 1234, crs: "EPSG:32652", verticalReference: null,
      gsdM: 0.05, submittedAt: "2026-09-30T01:00:00Z", producerCompletedAt: "2026-09-30T00:50:00Z",
      captureStartedAt: captureInterval.startedAt, captureEndedAt: captureInterval.endedAt,
    },
    observed: {
      factClass: "OBSERVED", manifestDigest: digest("d"), observedAt: "2026-09-30T01:01:00Z",
      sha256: "c".repeat(64), sizeBytes: 1234, contentType: "image/tiff",
    },
    inspection: {
      state: "COMPLETED", outcome: "MEASURED", reason: null, reportDigest: digest("e"), inspectorBuildDigest: digest("f"),
      raster: {
        factClass: "INSPECTED", sourceReportDigest: digest("e"), inspectorBuildDigest: digest("f"),
        observedCrsIdentifier: "EPSG:32652", observedCrsWkt: null, observedCrsDigest: digest("1"),
        observedVerticalReference: null, transform: [0.05, 0, 500000, 0, -0.05, 4000000],
        footprintWkt: "POLYGON((0 0,1 0,1 1,0 0))", footprintDigest: digest("2"), width: 200, height: 100,
      },
    },
    dataAccess: "NOT_AVAILABLE_FROM_CATALOG",
    analysisStatus: "NOT_EVALUATED",
    supportedActions: ["VIEW_METADATA"],
  };
}

const callPage = (query: Record<string, string | string[] | undefined> = {}) => SpatialAssetsPage({
  params: Promise.resolve({ siteId: "site-1" }),
  searchParams: Promise.resolve(query),
});

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ"] } });
  mocked.site.mockResolvedValue({ siteId: "site-1", name: "현장 1", status: "BASELINE_MAPPING", aoi: null, resumeTarget: null, siteFrame: { crs: "EPSG:5186", transformVersion: "v1" }, registeredAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-01T00:00:00Z" });
  mocked.areas.mockResolvedValue({ workAreas: [workArea] });
  mocked.catalog.mockResolvedValue({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [asset()], nextCursor: null, hasMore: false });
  mocked.detail.mockResolvedValue(asset());
  mocked.workOrders.mockResolvedValue([{ workOrderId: "order-1", siteId: "site-1", organizationId: "org-1", name: "북측 1차 관측", workAreaIds: ["area-1"] }]);
});

describe("spatial asset catalog page", () => {
  it("requires the operator to select a WorkArea before requesting its catalog", async () => {
    const html = renderToStaticMarkup(await callPage());
    expect(html).toContain("작업구역 선택");
    expect(html).toContain("북측 작업구역");
    expect(mocked.catalog).not.toHaveBeenCalled();
  });

  it("labels declarations, byte observations and inspection as separate facts", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(html).toContain("제출자 입력 정보 있음");
    expect(html).toContain("저장 파일 확인 기록 있음");
    expect(html).toContain("파일 검사:");
    expect(html).toContain("north-dsm.tif");
    expect(html).toContain("DSM");
    expect(html).toContain("지표면 높이 자료(DSM) · 촬영 구간 미기재");
    expect(html).toContain("파일의 등록 정보만 보여줍니다. 파일 받기와 분석 사용 가능 여부는 별도로 확인합니다.");
    expect(html).not.toContain("카탈로그에서 바이트 다운로드는 제공되지 않습니다.");
    expect(html).not.toContain("분석 상태는 평가되지 않았습니다.");
    expect(html).toContain("?workAreaId=area-1&amp;assetRef=");
    expect(html).not.toContain("objectKey");
    expect(html).not.toContain("https://");
  });

  it("requests the exact selected detail from Core and displays it beside the list", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    expect(mocked.detail).toHaveBeenCalledWith("site-1", "area-1", assetRef);
    expect(html).toContain("선택한 자료");
    expect(html).toContain("북측 1차 관측");
    expect(html).toContain("북측 작업구역");
    expect(html).toContain("파일 정보·처리 상세 보기");
    expect(html).toContain("관측 기록 ID · epoch-1");
    expect(html).toContain("작업 지시 ID · order-1");
    expect(html).not.toContain("기술 참조 · epoch epoch-1 · 작업 order-1");
    expect(html).toContain("EPSG:32652");
    expect(html).toContain("상태: 검사 완료 · 결과: 파일 정보 확인됨");
    expect(html).toContain("지표면 높이 자료(DSM) · image/tiff");
    expect(html).toContain("이 화면은 파일의 등록 정보만 제공합니다.");
    expect(html).toContain("분석 적합성은 평가되지 않았습니다.");
  });

  it("offers the selected observation to the comparison form only with analysis permission", async () => {
    mocked.session.mockResolvedValueOnce({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ", "SITES_WRITE"] } });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    expect(html).toContain("이 자료를 현재 관측으로 선택");
    expect(html).toContain("/sites/site-1/analysis?workAreaId=area-1&amp;currentWorkOrderId=order-1#new-analysis-request");
    expect(html).toContain("여기서 분석을 실행하지 않습니다.");
  });

  it("does not offer a comparison handoff to readers or without a selected detail", async () => {
    const readerHtml = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    expect(readerHtml).not.toContain("이 자료를 현재 관측으로 선택");
    const listOnlyHtml = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(listOnlyHtml).not.toContain("이 자료를 현재 관측으로 선택");
  });

  it("connects the list rows to work name, area, capture window and version", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(html).toContain("등록된 관측 작업명 · 북측 1차 관측");
    expect(html).toContain("작업구역명 · 북측 작업구역");
    expect(html).toContain("등록 버전 2");
    expect(html).toContain("파일 정보·처리 상세 보기");
    expect(html).toContain(`자산 참조 · ${assetRef}`);
  });

  it("stays honest when work names are unavailable and distinguishes duplicate file names", async () => {
    mocked.workOrders.mockRejectedValueOnce(new Error("work orders unavailable"));
    const first = asset();
    const second = { ...asset(), assetRef: `ksa-v1-${"b".repeat(64)}`, revision: 3 };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [first, second], nextCursor: null, hasMore: false });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(html).toContain("등록된 관측 작업명 · 확인 불가");
    expect(html).toContain("등록 버전 2");
    expect(html).toContain("등록 버전 3");
    expect(html).toContain("같은 파일명이 이 목록에 여러 건 있습니다");
    expect(html).toContain("파일의 등록 정보만 보여줍니다. 파일 받기와 분석 사용 가능 여부는 별도로 확인합니다.");
  });

  it("formats declared submission and capture timestamps in Seoul time", async () => {
    const withCaptureTimes = asset("area-1", "dsm", {
      startedAt: "2026-09-29T23:30:00Z",
      endedAt: "2026-09-30T00:30:00Z",
    });
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [withCaptureTimes], nextCursor: null, hasMore: false });
    mocked.detail.mockResolvedValueOnce(withCaptureTimes);

    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));

    expect(html).toContain("2026. 9. 30. 10:00");
    expect(html).toContain("2026. 9. 30. 09:50");
    expect(html).toContain("2026. 9. 30. 08:30 – 2026. 9. 30. 09:30");
    expect(html).toContain("지표면 높이 자료(DSM) · 2026. 9. 30. 08:30–09:30 촬영");
    expect(html).not.toContain("2026-09-30T01:00:00Z");
    expect(html).not.toContain("2026-09-29T23:30:00Z");
  });

  it("uses Core's opaque cursor for the next page and keeps WorkArea scope", async () => {
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [asset()], nextCursor: "opaque-cursor", hasMore: true });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", cursor: "current-cursor" }));
    expect(mocked.catalog).toHaveBeenCalledWith("site-1", "area-1", { limit: 50, cursor: "current-cursor" });
    expect(html).toContain("다음 자산 보기");
    expect(html).toContain("cursor=opaque-cursor");
    expect(html).toContain("처음부터 보기");
  });

  it("loads archived WorkAreas for existing catalog links and re-requests their scope", async () => {
    const archivedArea = { workAreaId: "old-area", name: "이전 구역", status: "ARCHIVED" };
    mocked.areas.mockResolvedValue({ workAreas: [workArea, archivedArea] });
    mocked.catalog.mockResolvedValue({ siteId: "site-1", workAreaId: "old-area", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [asset("old-area")], nextCursor: null, hasMore: false });
    mocked.detail.mockResolvedValueOnce(asset("old-area"));
    const html = renderToStaticMarkup(await callPage({ workAreaId: "old-area", assetRef }));
    expect(mocked.areas).toHaveBeenCalledWith("site-1", { includeArchived: true });
    expect(mocked.catalog).toHaveBeenCalledWith("site-1", "old-area", { limit: 50, cursor: undefined });
    expect(mocked.detail).toHaveBeenCalledWith("site-1", "old-area", assetRef);
    expect(html).toContain("이전 구역 · 보관됨");
    expect(html).toContain("선택한 자료");
    expect(html).toContain("north-dsm.tif");
  });

  it("keeps non-raster processing reports available as metadata without implying raster facts", async () => {
    const report = {
      ...asset("area-1", "report"),
      inspection: { state: "COMPLETED", outcome: "NOT_APPLICABLE", reason: null, reportDigest: null, inspectorBuildDigest: null, raster: null },
    };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [report], nextCursor: null, hasMore: false });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(html).toContain("처리 보고서");
    expect(html).not.toContain("(report)");
    expect(html).toContain("파일 검사: 적용 대상 아님");
    expect(html).not.toContain("격자 크기");
  });

  it("does not display an inexact byte count beyond JavaScript's safe integer range", async () => {
    const large = asset();
    large.declared.sizeBytes = Number.MAX_SAFE_INTEGER + 1;
    large.observed!.sizeBytes = Number.MAX_SAFE_INTEGER + 1;
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [large], nextCursor: null, hasMore: false });
    mocked.detail.mockResolvedValueOnce(large);
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    expect(html.match(/정확한 크기 표시 불가/g)).toHaveLength(3);
    expect(html).not.toContain("9,007,199,254,740,992 bytes");
  });

  it("keeps a foreign or stale WorkArea 404 distinct from a genuinely empty catalog", async () => {
    const { CoreApiError } = await import("@/lib/core-api/client");
    mocked.catalog.mockRejectedValueOnce(new CoreApiError(404, {}));
    const unavailable = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(unavailable).toContain("작업구역을 확인할 수 없거나 접근 권한이 없습니다.");
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [], nextCursor: null, hasMore: false });
    const empty = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(empty).toContain("이 작업구역에 등록된 자료가 없습니다");
    expect(empty).toContain("관측 자료가 이 작업구역에 등록되면 해당 자료의 메타데이터가 여기에 표시됩니다.");
  });

  it("fails closed on denied access, temporary Core failures, duplicate selection and detail 404", async () => {
    const { CoreApiError } = await import("@/lib/core-api/client");
    mocked.catalog.mockRejectedValueOnce(new CoreApiError(403, {}));
    expect(renderToStaticMarkup(await callPage({ workAreaId: "area-1" }))).toContain("현장 등록 자료 조회 권한이 없습니다. 현장 담당자에게 조회 권한을 요청하세요.");
    mocked.catalog.mockRejectedValueOnce(new CoreApiError(503, {}, 10));
    expect(renderToStaticMarkup(await callPage({ workAreaId: "area-1" }))).toContain("일시적으로 불러오지 못했습니다.");
    expect(renderToStaticMarkup(await callPage({ workAreaId: ["area-1", "area-2"] }))).toContain("작업구역을 하나만 선택하세요.");
    mocked.detail.mockRejectedValueOnce(new CoreApiError(404, {}));
    expect(renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }))).toContain("자산을 찾을 수 없거나 현재 조회할 수 없습니다.");
  });
});
