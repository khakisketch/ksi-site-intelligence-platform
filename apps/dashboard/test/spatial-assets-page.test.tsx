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
  revision: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) =>
    createElement("a", { href, ...props }, children),
}));
vi.mock("next/navigation", () => ({
  notFound: () => { throw new Error("NEXT_NOT_FOUND"); },
  useRouter: () => ({ refresh: vi.fn() }),
}));
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
vi.mock("@/lib/core-api/external-reconstruction", () => ({
  getExternalReconstructionSubmission: mocked.revision,
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
  mocked.revision.mockRejectedValue(new Error("revision unavailable"));
});

describe("spatial asset catalog page", () => {
  it("auto-selects the single ACTIVE WorkArea on the bare route and keeps its scope in links", async () => {
    const html = renderToStaticMarkup(await callPage());
    expect(mocked.catalog).toHaveBeenCalledWith("site-1", "area-1", { limit: 50, cursor: undefined });
    expect(html).toContain("현장에 등록된 작업구역이 하나뿐이라 해당 구역의 자료를 표시합니다.");
    expect(html).toContain("불러온 1 · 검사 완료 1");
    expect(html).toContain("?workAreaId=area-1&amp;assetRef=");
  });

  it("stays on an explicit prompt with multiple areas instead of guessing a scope", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [workArea, { workAreaId: "area-2", name: "남측 작업구역", status: "ACTIVE" }] });
    const html = renderToStaticMarkup(await callPage());
    expect(mocked.catalog).not.toHaveBeenCalled();
    expect(html).toContain("작업구역을 선택하면 해당 구역의 자료가 표시됩니다.");
  });

  it("fails closed on an unknown WorkArea instead of falling back to a known one", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "foreign-area" }));
    expect(html).toContain("작업구역을 확인할 수 없거나 접근 권한이 없습니다.");
    expect(mocked.catalog).not.toHaveBeenCalled();
    expect(mocked.detail).not.toHaveBeenCalled();
  });

  it("carries the auto-selected single area into the detail request and the analysis handoff", async () => {
    mocked.session.mockResolvedValueOnce({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ", "SITES_WRITE"] } });
    const html = renderToStaticMarkup(await callPage({ assetRef }));
    expect(mocked.catalog).toHaveBeenCalledWith("site-1", "area-1", { limit: 50, cursor: undefined });
    expect(mocked.detail).toHaveBeenCalledWith("site-1", "area-1", assetRef);
    // 헤더의 분석 목적지에도 검증된 관측 출처가 실린다 — 돌아올 때 잃지 않는다.
    expect(html).toContain(`href="/sites/site-1/analysis?workAreaId=area-1&amp;assetRef=${assetRef}"`);
    expect(html).toContain(`/sites/site-1/analysis?workAreaId=area-1&amp;hintCurrentWorkOrderId=order-1&amp;hintCurrentSubmissionRef=ers-v1-${"b".repeat(64)}&amp;hintCurrentRevision=2#new-analysis-request`);
  });

  it("labels declarations, byte observations and inspection as separate facts", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    expect(html).toContain("제출자 입력 정보 있음");
    expect(html).toContain("저장 파일 확인 기록 있음");
    expect(html).toContain("파일 검사:");
    expect(html).toContain("north-dsm.tif");
    expect(html).toContain("DSM");
    expect(html).toContain("지표면 높이 자료(DSM) · 촬영 구간 미기재");
    // 목록 머리의 반복 설명 대신 현재 구역의 상태 요약을 먼저 보여준다.
    expect(html).toContain("불러온 1 · 검사 완료 1");
    expect(html).not.toContain("카탈로그에서 바이트 다운로드는 제공되지 않습니다.");
    expect(html).not.toContain("분석 상태는 평가되지 않았습니다.");
    expect(html).toContain("?workAreaId=area-1&amp;assetRef=");
    expect(html).not.toContain("objectKey");
    expect(html).not.toContain("https://");
  });

  it("requests the exact selected detail from Core and displays it beside the list", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    expect(mocked.detail).toHaveBeenCalledWith("site-1", "area-1", assetRef);
    expect(html).toContain("관측 자료 상세");
    expect(html).toContain("북측 1차 관측");
    expect(html).toContain("북측 작업구역");
    expect(html).toContain("파일 정보·처리 상세 보기");
    expect(html).toContain("관측 기록 ID · epoch-1");
    expect(html).toContain("작업 지시 ID · order-1");
    expect(html).not.toContain("기술 참조 · epoch epoch-1 · 작업 order-1");
    expect(html).toContain("EPSG:32652");
    expect(html).toContain("상태: 검사 완료 · 결과: 파일 정보 확인됨");
    expect(html).toContain("지표면 높이 자료(DSM) · image/tiff");
    expect(html).toContain("파일 검사 완료는 형식·격자 확인이며, 측량·정산 근거나 분석 사용 가능 판정이 아닙니다.");
    expect(html).toContain("이 화면에서 판정하지 않음");
  });

  it("offers the selected observation to the comparison form only with analysis permission", async () => {
    mocked.session.mockResolvedValueOnce({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ", "SITES_WRITE"] } });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    expect(html).toContain("이 자료를 현재 관측으로 선택");
    expect(html).toContain(`/sites/site-1/analysis?workAreaId=area-1&amp;hintCurrentWorkOrderId=order-1&amp;hintCurrentSubmissionRef=ers-v1-${"b".repeat(64)}&amp;hintCurrentRevision=2#new-analysis-request`);
    expect(html).toContain("분석 실행은 결과 화면에서 합니다.");
  });

  it("does not offer a comparison handoff to readers or without a selected detail", async () => {
    const readerHtml = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    expect(readerHtml).not.toContain("이 자료를 현재 관측으로 선택");
    const listOnlyHtml = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(listOnlyHtml).not.toContain("이 자료를 현재 관측으로 선택");
  });

  it("offers the file-preparation request only with the data-request permission", async () => {
    const readerHtml = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    expect(readerHtml).toContain("자료 받기 요청</button>");
    expect(readerHtml).not.toContain("자료 받기 요청은 권한 있는 담당자가 만들 수 있습니다");
    expect(readerHtml).not.toContain("받기 요청 만들기");

    mocked.session.mockResolvedValueOnce({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ", "SPATIAL_DATA_REQUEST"] } });
    const writerHtml = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    expect(writerHtml).toContain("받기 요청 만들기");
    expect(writerHtml).toContain("준비 완료는 정확도나 분석 사용 가능 여부를 보증하지 않습니다");
    expect(writerHtml).toContain("/sites/site-1/spatial-data-requests?workAreaId=area-1");
  });

  it("connects the list rows to work name, area, capture window and version", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    expect(html).toContain("등록된 관측 작업명 · 북측 1차 관측");
    expect(html).toContain("작업구역명 · 북측 작업구역");
    expect(html).toContain("등록 버전 2");
    expect(html).toContain("파일 정보·처리 상세 보기");
    expect(html).toContain(`자산 참조 · ${assetRef}`);
  });

  it("groups the catalog by observation bundle instead of a flat file list", async () => {
    const second = {
      ...asset(),
      assetRef: `ksa-v1-${"c".repeat(64)}`,
      kind: "ortho",
      observationEpochId: "epoch-2",
      declared: { ...asset().declared, fileName: "north-ortho.tif" },
    };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [asset(), second], nextCursor: null, hasMore: false });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(html.match(/촬영 구간 미기재 · 1/g)?.length).toBe(2);
    expect(html).toContain("불러온 2 · 검사 완료 2");
  });

  it("marks failed processing with its cause and a re-request path", async () => {
    const failed = {
      ...asset(),
      inspection: { ...asset().inspection, state: "FAILED", outcome: "REJECTED", reason: "검사 정책 불일치" },
    };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [failed], nextCursor: null, hasMore: false });
    mocked.detail.mockResolvedValueOnce(failed);
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    expect(html).toContain("불러온 1 · 검사 완료 0");
    expect(html).toContain("검사 정책 불일치");
    expect(html).toContain("구역 자료 준비에서 재처리 요청");
    expect(html).toContain("/sites/site-1/spatial-data-requests?workAreaId=area-1");
  });

  it("marks unverified and unsealed records without blocking their metadata", async () => {
    const pending = { ...asset(), assetRef: `ksa-v1-${"d".repeat(64)}`, inspection: { ...asset().inspection, state: "INSPECTION_PENDING", outcome: null } };
    const opened = { ...pending, assetRef: `ksa-v1-${"e".repeat(64)}`, lifecycleState: "UNSEALED", inspection: asset().inspection };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [pending, opened], nextCursor: null, hasMore: false });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    expect(html).toContain("상태 · 검사 결과 확인 전");
    expect(html).toContain("상태 · 파일 제출 미완료");
  });

  it("stays honest when work names are unavailable and distinguishes duplicate file names", async () => {
    mocked.workOrders.mockRejectedValueOnce(new Error("work orders unavailable"));
    const first = asset();
    const second = { ...asset(), assetRef: `ksa-v1-${"b".repeat(64)}`, revision: 3 };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [first, second], nextCursor: null, hasMore: false });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    expect(html).toContain("등록된 관측 작업명 · 확인 불가");
    expect(html).toContain("등록 버전 2");
    expect(html).toContain("등록 버전 3");
    expect(html).toContain("같은 파일명이 이 목록에 여러 건 있습니다");
    expect(html).toContain("펼쳐서 등록 버전·촬영 구간으로 구분하세요");
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
    expect(html).toContain("관측 자료 상세");
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
    expect(html).toContain("파일 검사 · 적용 대상 아님");
    expect(html).not.toContain("격자 크기");
  });

  it("does not display an inexact byte count beyond JavaScript's safe integer range", async () => {
    const large = asset();
    large.declared.sizeBytes = Number.MAX_SAFE_INTEGER + 1;
    large.observed!.sizeBytes = Number.MAX_SAFE_INTEGER + 1;
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [large], nextCursor: null, hasMore: false });
    mocked.detail.mockResolvedValueOnce(large);
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    // 행은 바이트 사실을 싣지 않는다 — 선언·관측 상세에서만 센다.
    expect(html.match(/정확한 크기 표시 불가/g)).toHaveLength(2);
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

describe("selected asset registration history (V3 submission record)", () => {
  const submissionRef = `ers-v1-${"b".repeat(64)}`;

  function v3Submission(overrides: Record<string, unknown> = {}) {
    return {
      contractVersion: "external-reconstruction-submission.v3",
      submissionId: "sub-1",
      revision: 2,
      organizationId: "org-1",
      siteId: "site-1",
      observationEpochId: "epoch-1",
      submittedAt: "2026-09-30T01:00:00Z",
      submittedBy: "operator-1",
      executionResponsibility: "customer_operator",
      executionLocus: "customer_workstation",
      producerDeclaration: {
        producerKnowledge: "UNKNOWN",
        softwareName: null,
        softwareVersion: null,
        buildIdentifier: null,
        producerRunIdentifier: null,
        configurationDigest: null,
        completedAt: null,
        sourceNote: null,
      },
      inputDeclaration: {
        rawMediaStoredByKsi: false,
        originalRetentionLocus: "unknown",
        originalRetentionDetail: null,
        localInputManifestDigest: null,
        imageCount: null,
        captureStartedAt: null,
        captureEndedAt: null,
        captureDate: "2021-06-15",
        captureBasis: "DATE_ONLY",
        upstreamSource: {
          sourceUri: "https://example.test/floreat-2021",
          sourceSha256: "d".repeat(64),
          licenceDeclaration: "CC BY 4.0",
          retrievalNote: null,
        },
        derivativeExport: {
          toolName: "KSI Export",
          toolVersion: "1.0",
          settingsDigest: null,
          exportedAt: null,
          exportNote: null,
        },
      },
      artifacts: [],
      ...overrides,
    };
  }

  function v3Record(submission: unknown, overrides: Record<string, unknown> = {}) {
    return {
      submissionRef,
      submission,
      state: "REGISTERED",
      manifest: null,
      ...overrides,
    };
  }

  it("reads one bounded revision for the selected asset and shows Core V3 date and provenance", async () => {
    mocked.revision.mockResolvedValueOnce(v3Record(v3Submission()));
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));

    expect(mocked.revision).toHaveBeenCalledTimes(1);
    expect(mocked.revision).toHaveBeenCalledWith("order-1", submissionRef, 2);
    expect(html).toContain("등록 이력");
    expect(html).toContain("2021. 6. 15.");
    expect(html).toContain("촬영 시각 미상");
    expect(html).toContain("재구성 소프트웨어: 미상");
    expect(html).toContain("원본 보관: 미상");
    expect(html).toContain("원자료 출처 (제출서 신고)");
    expect(html).toContain("공개 라이선스 신고: CC BY 4.0");
    expect(html).toContain("https://example.test/floreat-2021");
    expect(html).toContain("KSI 접근·사용 권한 부여와는 별개입니다");
    expect(html).toContain("제출 산출물 내보내기 (로컬 도구)");
    expect(html).toContain("KSI Export 1.0");
    expect(html).toContain("원자료의 재구성 소프트웨어나 KSI의 실행 사실을 뜻하지 않습니다");
    expect(html).toContain("정확도 평가가 아닙니다");
    expect(html).not.toContain("등록 이력(제출서)을 확인하지 못했습니다");
  });

  it("renders exact intervals and partial producers without inventing missing facts", async () => {
    mocked.revision.mockResolvedValueOnce(v3Record(v3Submission({
      producerDeclaration: {
        producerKnowledge: "PARTIAL",
        softwareName: "Terra",
        softwareVersion: null,
        buildIdentifier: null,
        producerRunIdentifier: null,
        configurationDigest: null,
        completedAt: null,
        sourceNote: null,
      },
      inputDeclaration: {
        rawMediaStoredByKsi: false,
        originalRetentionLocus: "customer_workstation",
        originalRetentionDetail: null,
        localInputManifestDigest: null,
        imageCount: null,
        captureStartedAt: "2022-03-04T01:00:00Z",
        captureEndedAt: "2022-03-04T02:00:00Z",
        captureDate: null,
        captureBasis: "EXACT_INTERVAL",
        upstreamSource: null,
        derivativeExport: {
          toolName: "KSI Export",
          toolVersion: "2.0",
          settingsDigest: `sha256:${"e".repeat(64)}`,
          exportedAt: "2022-03-05T00:00:00Z",
          exportNote: null,
        },
      },
    })));
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));

    expect(html).toContain("2022. 3. 4.");
    expect(html).toContain("재구성 소프트웨어: Terra (버전 미상)");
    expect(html).toContain("원본 보관: 고객 작업 장비");
    expect(html).toContain("KSI Export 2.0");
    expect(html).not.toContain("원자료 출처 (제출서 신고)");
  });

  it("keeps V1 records on the old semantics without new sections or notes", async () => {
    mocked.revision.mockResolvedValueOnce(v3Record({ ...v3Submission(), contractVersion: "external-reconstruction-submission.v1" }));
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));

    expect(mocked.revision).toHaveBeenCalledTimes(1);
    expect(html).toContain("관측 자료 상세");
    expect(html).not.toContain("등록 이력");
    expect(html).not.toContain("등록 이력(제출서)을 확인하지 못했습니다");
  });

  it("does not render a binding-mismatched foreign record or leak its source", async () => {
    mocked.revision.mockResolvedValueOnce(v3Record(v3Submission({ siteId: "site-9", organizationId: "org-9" })));
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));

    expect(html).toContain("관측 자료 상세");
    expect(html).not.toContain("CC BY 4.0");
    expect(html).not.toContain("https://example.test/floreat-2021");
    expect(html).not.toContain("등록 이력 (제출서 기준)");
    expect(html).toContain("등록 이력(제출서)을 확인하지 못했습니다");
  });

  it("keeps asset facts with a persistent note when the revision read fails", async () => {
    mocked.revision.mockRejectedValueOnce(new Error("Core 403"));
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));

    expect(html).toContain("관측 자료 상세");
    expect(html).toContain("north-dsm.tif");
    expect(html).toContain("등록 이력(제출서)을 확인하지 못했습니다");
    expect(html).not.toContain("Core 403");
  });

  it("does not fetch without a selection", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));

    expect(mocked.revision).not.toHaveBeenCalled();
    expect(html).toContain(">자료</h2>");
    expect(html).not.toContain("등록 이력");
    expect(html).not.toContain("등록 이력(제출서)을 확인하지 못했습니다");
  });

  it("filters the loaded page and keeps the filter in detail and paging links", async () => {
    const second = {
      ...asset("area-1", "ortho"),
      assetRef: `ksa-v1-${"9".repeat(64)}`,
      observationEpochId: "epoch-2",
      declared: { ...asset().declared, fileName: "north-ortho.tif" },
    };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [asset(), second], nextCursor: "cursor-2", hasMore: true });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", kind: "ortho", state: "inspected" }));

    // 필터는 이미 불러온 페이지 안에서만 적용되고, 걸러진 항목은 목록에 남지 않는다.
    expect(html).toContain("north-ortho.tif");
    expect(html).not.toContain("north-dsm.tif");
    // 집계는 필터가 아니라 불러온 자료 전체를 센다.
    expect(html).toContain("이번에 불러온 2건 기준");
    // 상세·다음 페이지로 갈 때 같은 필터가 유지된다.
    expect(html).toContain(`assetRef=${second.assetRef}`);
    expect(html).toContain("kind=ortho&amp;state=inspected&amp;cursor=cursor-2");
    expect(html).toContain("필터 초기화");
  });

  it("says when no loaded record matches the filter instead of pretending the area is empty", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", q: "없는파일" }));
    expect(html).toContain("조건에 맞는 자료가 없습니다");
    expect(html).not.toContain("이 작업구역에 등록된 자료가 없습니다");
    expect(html).toContain("필터 초기화");
  });

  it("expands the selected row inline with a close link that keeps the scope", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    // 상세는 행 아래에 한 번만 펼친다 — 목록 위의 별도 섹션이 아니다.
    expect(html.match(/관측 자료 상세/g)).toHaveLength(2); // sr-only 표제 + 펼침 영역 라벨
    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain(`/sites/site-1/spatial-assets?workAreaId=area-1"`);
    expect(html).toContain(">닫기</a>");
    // 닫은 뒤에도 목록 행으로 돌아갈 수 있다.
    expect(html).toContain("상세 보기");
  });

  it("emphasizes only the attention count in the inline summary", async () => {
    const failed = {
      ...asset(),
      inspection: { ...asset().inspection, state: "FAILED", outcome: "REJECTED", reason: "검사 정책 불일치" },
    };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [failed], nextCursor: null, hasMore: false });
    mocked.detail.mockResolvedValueOnce(failed);
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    expect(html).toContain("불러온 1 · 검사 완료 0");
    expect(html).toContain("확인 필요 1");
    expect(html).toContain("font-semibold text-high-ink");
  });

  it("keeps the work area select as the only required selection so filters can be cleared", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    // 작업구역은 필수, 필터 select 는 값이 비어도(전체) 제출되어야 한다.
    expect(html).toMatch(/id="spatial-work-area"[^>]*required|required[^>]*id="spatial-work-area"/);
    expect(html).not.toMatch(/id="spatial-kind"[^>]*required/);
    expect(html).not.toMatch(/id="spatial-state"[^>]*required/);
    expect(html).not.toContain("등록 자료 보기");
  });

  it("shows the verbatim file name in the list without inferring capture facts", async () => {
    const dated = asset();
    dated.declared.fileName = "Site_EPSG7850_2021-05-04_ortho.tif";
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [dated], nextCursor: null, hasMore: false });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));

    expect(html).toContain("파일명 · Site_EPSG7850_2021-05-04_ortho.tif");
    expect(html).toContain("촬영 구간 미기재");
    expect(html).not.toContain("2021. 5. 4. 촬영");
  });
});
