import { readFileSync } from "node:fs";
import { join } from "node:path";
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
  prepared: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) => {
    delete props.scroll;
    return createElement("a", { href, ...props }, children);
  },
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
vi.mock("@/lib/core-api/spatial-data-requests", () => ({
  listSpatialDataRequests: mocked.prepared,
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
  mocked.prepared.mockResolvedValue({ siteId: "site-1", workAreaId: "area-1", items: [], nextCursor: null, hasMore: false });
});

describe("spatial asset catalog page", () => {
  it("coalesces a known both-expired cause into one shared recovery instead of per-pane walls", async () => {
    const first = asset();
    const secondRef = `ksa-v1-${"c".repeat(64)}`;
    const second = { ...asset(), assetRef: secondRef, observationEpochId: "epoch-2", declared: { ...asset().declared, fileName: "second-dsm.tif" } };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [first, second], nextCursor: null, hasMore: false });
    // 두 칸의 선택 출력이 모두 보관 만료 — 스캔하지 않은 부재가 아니라 알려진 동일 사유다.
    mocked.session.mockResolvedValueOnce({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ", "SPATIAL_DATA_READ"] } });
    mocked.prepared.mockResolvedValueOnce({
      siteId: "site-1", workAreaId: "area-1", nextCursor: null, hasMore: false,
      items: [first.assetRef, secondRef].map((assetRef, index) => ({
        jobId: `sdj-v1-00000000-0000-4000-8000-00000000000${index + 1}`,
        assetRef, siteId: "site-1", workAreaId: "area-1",
        createdAt: "2026-09-30T02:00:00Z", executionState: "EXPIRED", availability: "RETENTION_EXPIRED",
        receipt: null,
      })),
    });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: first.assetRef, visualBAssetRef: secondRef }));
    // 같은 알려진 만료는 하나로 둔다 — 칸마다 단추·펼침 벽을 두지 않는다.
    expect(html.match(/미리보기 보관 기간이 끝났습니다\./g)).toHaveLength(1);
    // 뷰어는 접히고 헤드만 남는다.
    expect(html.match(/임시 시각화 어댑터/g)).toBeNull();
    expect(html).not.toContain("자료 범위 보기");
    expect(html).not.toContain("상세·준비");
    // 각 칸 머리의 관측 선택은 그대로 쓸 수 있다.
    expect(html).toContain('name="visualAAssetRef"');
    expect(html).toContain('name="visualBAssetRef"');
  });

  it("does not coalesce when an old expired record coexists with a newer available one", async () => {
    const first = asset();
    const secondRef = `ksa-v1-${"c".repeat(64)}`;
    const second = { ...asset(), assetRef: secondRef, observationEpochId: "epoch-2", declared: { ...asset().declared, fileName: "second-dsm.tif" } };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [first, second], nextCursor: null, hasMore: false });
    // A에는 오래된 만료와 새 사용 가능본이 함께 있다 — 만료로 묶으면 유효 픽셀이 숨겨진다.
    mocked.session.mockResolvedValueOnce({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ", "SPATIAL_DATA_READ"] } });
    mocked.prepared.mockResolvedValueOnce({
      siteId: "site-1", workAreaId: "area-1", nextCursor: null, hasMore: false,
      items: [
        { jobId: "sdj-v1-00000000-0000-4000-8000-000000000011", assetRef: first.assetRef, siteId: "site-1", workAreaId: "area-1", createdAt: "2026-09-30T02:00:00Z", executionState: "EXPIRED", availability: "RETENTION_EXPIRED", receipt: null },
        { jobId: "sdj-v1-00000000-0000-4000-8000-000000000012", assetRef: first.assetRef, siteId: "site-1", workAreaId: "area-1", createdAt: "2026-09-30T03:00:00Z", executionState: "COMPLETED", availability: "AVAILABLE", receipt: null },
        { jobId: "sdj-v1-00000000-0000-4000-8000-000000000013", assetRef: secondRef, siteId: "site-1", workAreaId: "area-1", createdAt: "2026-09-30T02:00:00Z", executionState: "EXPIRED", availability: "RETENTION_EXPIRED", receipt: null },
      ],
    });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: first.assetRef, visualBAssetRef: secondRef }));
    // 같은 사유 묶음이 아니다 — 공유 바가 없고 각 칸이 자기 보기를 둔다.
    expect(html).not.toContain("두 칸의 불러온 준비 기록이 모두");
    expect(html).toContain('name="visualAAssetRef"');
    expect(html).toContain('name="visualBAssetRef"');
    // 각 칸 헤드 아래에 자기 보기가 그대로 있다(공유 바로 접히지 않음).
    expect(html.match(/임시 시각화 어댑터/g)?.length).toBe(2);
  });

  it("shares one list-level recovery across both panes instead of repeating it per pane", async () => {
    const first = asset();
    const secondRef = `ksa-v1-${"c".repeat(64)}`;
    const second = { ...asset(), assetRef: secondRef, observationEpochId: "epoch-2", declared: { ...asset().declared, fileName: "second-dsm.tif" } };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [first, second], nextCursor: null, hasMore: false });
    // SPATIAL_DATA_READ 없음 → 준비 기록 조회 거부(두 칸 동일 사유).
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: first.assetRef, visualBAssetRef: secondRef }));
    // 같은 사유 회복은 하나로 둔다 — 칸마다 단추를 두지 않는다.
    expect(html.match(/준비 기록을 조회할 권한이 없습니다\./g)).toHaveLength(1);
    expect(html).not.toContain("준비 상태 다시 확인");
    // 각 칸 머리의 관측 선택은 그대로 쓸 수 있다.
    expect(html).toContain('name="visualAAssetRef"');
    expect(html).toContain('name="visualBAssetRef"');
  });
  it("keeps a valid B visible and preserves an explicit failed A during info/filter navigation", async () => {
    const refusedRef = `ksa-v1-${"9".repeat(64)}`;
    const second = { ...asset(), assetRef: `ksa-v1-${"c".repeat(64)}`, observationEpochId: "epoch-2", declared: { ...asset().declared, fileName: "second-dsm.tif" } };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [asset(), second], nextCursor: null, hasMore: false });
    const { CoreApiError } = await import("@/lib/core-api/client");
    mocked.detail.mockRejectedValueOnce(new CoreApiError(404, {}));
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: refusedRef, visualBAssetRef: second.assetRef, info: "1", q: "no-match" }));
    expect(html).toContain("선택한 B는 그대로 표시합니다.");
    expect(html).toContain("second-dsm.tif");
    expect(html).not.toContain('aria-label="현재 A로 선택됨"');
    expect(html).toContain(`visualAAssetRef=${refusedRef}&amp;visualBAssetRef=${second.assetRef}`);
    expect(html).toContain(`name="visualAAssetRef" value="${refusedRef}"`);
  });
  it("resolves an explicit visual selection even on an empty cursor page", async () => {
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [], nextCursor: null, hasMore: false });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", cursor: "empty-tail", visualAAssetRef: assetRef }));
    expect(mocked.detail).toHaveBeenCalledWith("site-1", "area-1", assetRef);
    expect(html).toContain('aria-label="선택한 자료 미리보기"');
    expect(html).not.toContain("이 작업구역에 등록된 자료가 없습니다");
  });
  it("auto-selects the single ACTIVE WorkArea on the bare route and previews its first record", async () => {
    const html = renderToStaticMarkup(await callPage());
    expect(mocked.catalog).toHaveBeenCalledWith("site-1", "area-1", { limit: 50, cursor: undefined });
    expect(html).toContain("현장에 등록된 작업구역이 하나뿐이라 해당 구역의 자료를 표시합니다.");
    // 목록은 닫힌 드로어에 둔다 — 열기 단추와 선택 미리보기가 먼저다.
    expect(html).toContain("목록");
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain(`visualAAssetRef=${assetRef}`);
    expect(html).toContain("목록 첫 자료");
    expect(html).toContain(">정보<");
    // 정보 서랍은 닫힘 상태로 마운트 유지하되 숨긴다 — 본문 제목은 열었을 때만 둔다.
    expect(html).toContain('id="material-inspector"');
    expect(html).toContain("display:none");
    expect(html).not.toContain(">선택 자료 정보<");
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
    const html = renderToStaticMarkup(await callPage({ assetRef, info: "1" }));
    expect(mocked.catalog).toHaveBeenCalledWith("site-1", "area-1", { limit: 50, cursor: undefined });
    expect(mocked.detail).toHaveBeenCalledWith("site-1", "area-1", assetRef);
    // 헤더의 분석 목적지에도 검증된 관측 출처가 실린다 — 돌아올 때 잃지 않는다.
    expect(html).toContain(`href="/sites/site-1/analysis?workAreaId=area-1&amp;assetRef=${assetRef}"`);
    expect(html).toContain(`/sites/site-1/analysis?workAreaId=area-1&amp;hintCurrentWorkOrderId=order-1&amp;hintCurrentSubmissionRef=ers-v1-${"b".repeat(64)}&amp;hintCurrentRevision=2#new-analysis-request`);
  });

  it("labels declarations, byte observations and inspection as separate facts", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
    expect(html).toContain("제출자 입력 정보 있음");
    expect(html).toContain("저장 파일 확인 기록 있음");
    expect(html).toContain("파일 검사:");
    expect(html).toContain("north-dsm.tif");
    expect(html).toContain("DSM");
    expect(html).toContain("지표면 높이 자료(DSM) · 촬영 구간 미기재");
    // 목록 요약은 닫힌 드로어에 둔다 — 칸 선택 상자와 정보 토글이 먼저다.
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain("카탈로그에서 바이트 다운로드는 제공되지 않습니다.");
    expect(html).not.toContain("분석 상태는 평가되지 않았습니다.");
    expect(html).toContain(`visualAAssetRef=${assetRef}`);
    expect(html).not.toContain("objectKey");
    expect(html).not.toContain("https://");
  });

  it("requests the exact selected detail from Core and displays it beside the list", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
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
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
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
    const readerHtml = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
    expect(readerHtml).toContain("자료 받기 요청</button>");
    expect(readerHtml).not.toContain("자료 받기 요청은 권한 있는 담당자가 만들 수 있습니다");
    expect(readerHtml).not.toContain("받기 요청 만들기");

    mocked.session.mockResolvedValueOnce({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ", "SPATIAL_DATA_REQUEST"] } });
    const writerHtml = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
    expect(writerHtml).toContain("받기 요청 만들기");
    expect(writerHtml).toContain("준비 완료는 정확도나 분석 사용 가능 여부를 보증하지 않습니다");
    expect(writerHtml).toContain("/sites/site-1/spatial-data-requests?workAreaId=area-1");
  });

  it("connects the list rows to work name, area, capture window and version", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
    expect(html).toContain("등록된 관측 작업명 · 북측 1차 관측");
    expect(html).toContain("작업구역명 · 북측 작업구역");
    expect(html).toContain("등록 버전 2");
    expect(html).toContain("파일 정보·처리 상세 보기");
    expect(html).toContain(`자산 참조 · ${assetRef}`);
  });

  it("offers same-kind records as per-pane observation options with exact versions", async () => {
    const dsm2 = {
      ...asset(),
      assetRef: `ksa-v1-${"c".repeat(64)}`,
      observationEpochId: "epoch-2",
      revision: 3,
      declared: { ...asset().declared, fileName: "south-dsm.tif" },
    };
    const ortho = {
      ...asset("area-1", "ortho"),
      assetRef: `ksa-v1-${"9".repeat(64)}`,
      observationEpochId: "epoch-3",
      declared: { ...asset().declared, fileName: "north-ortho.tif" },
    };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [asset(), dsm2, ortho], nextCursor: null, hasMore: false });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    // A 칸 선택 상자는 같은 종류(DSM)만 정확한 날짜·버전으로 고른다 — 다른
    // 종류나 시간 서열을 지어내지 않는다. 목록 드로어는 닫혀 있다.
    expect(html).toContain('id="pane-observation-visualAAssetRef"');
    expect(html).toContain(" · v2");
    expect(html).toContain(" · v3");
    expect(html).not.toContain('id="pane-observation-visualBAssetRef"');
    expect(html).toContain('aria-expanded="false"');
  });

  it("marks failed processing with its cause and a re-request path", async () => {
    const failed = {
      ...asset(),
      inspection: { ...asset().inspection, state: "FAILED", outcome: "REJECTED", reason: "검사 정책 불일치" },
    };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [failed], nextCursor: null, hasMore: false });
    mocked.detail.mockResolvedValueOnce(failed);
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
    expect(html).toContain("검사 정책 불일치");
    expect(html).toContain("구역 자료 준비에서 재처리 요청");
    expect(html).toContain("/sites/site-1/spatial-data-requests?workAreaId=area-1");
  });

  it("marks unverified and unsealed records without blocking their metadata", async () => {
    const pending = { ...asset(), assetRef: `ksa-v1-${"d".repeat(64)}`, inspection: { ...asset().inspection, state: "INSPECTION_PENDING", outcome: null } };
    const opened = { ...pending, assetRef: `ksa-v1-${"e".repeat(64)}`, lifecycleState: "UNSEALED", inspection: asset().inspection };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [pending, opened], nextCursor: null, hasMore: false });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", info: "1" }));
    expect(html).toContain("상태 · 검사 결과 확인 전");
    expect(html).toContain("선택 자료 정보");
  });

  it("stays honest when work names are unavailable and rails carry concise labels", async () => {
    mocked.workOrders.mockRejectedValueOnce(new Error("work orders unavailable"));
    const first = asset();
    const second = { ...asset(), assetRef: `ksa-v1-${"b".repeat(64)}`, revision: 3 };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [first, second], nextCursor: null, hasMore: false });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
    expect(html).toContain("등록된 관측 작업명 · 확인 불가");
    // 칸 선택 상자는 같은 종류의 정확한 버전만 고른다.
    expect(html).toContain(" · v2");
    expect(html).toContain(" · v3");
    expect(html).toContain("파일 정보·처리 상세 보기");
  });

  it("formats declared submission and capture timestamps in Seoul time", async () => {
    const withCaptureTimes = asset("area-1", "dsm", {
      startedAt: "2026-09-29T23:30:00Z",
      endedAt: "2026-09-30T00:30:00Z",
    });
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [withCaptureTimes], nextCursor: null, hasMore: false });
    mocked.detail.mockResolvedValueOnce(withCaptureTimes);

    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));

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
    const html = renderToStaticMarkup(await callPage({ workAreaId: "old-area", assetRef, info: "1" }));
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
    expect(html).toContain("보고서");
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
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
    // 레일은 바이트 사실을 싣지 않는다 — 정보 펼침의 선언·관측 상세에서만 센다.
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

  it("keeps the register and records entries on a genuinely empty catalog when authorized", async () => {
    mocked.session.mockResolvedValueOnce({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ", "WORK_ORDERS_WRITE"] } });
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [], nextCursor: null, hasMore: false });
    const empty = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(empty).toContain("이 작업구역에 등록된 자료가 없습니다");
    expect(empty).toContain("/sites/site-1/observations/new?workAreaId=area-1");
    expect(empty).toContain(">자료 등록<");
    expect(empty).toContain(">더 보기<");
    expect(empty).toContain("/sites/site-1?section=work-orders&amp;workAreaId=area-1");
    expect(empty).toContain("/sites/site-1/observations");
    expect(empty).toContain("/sites/site-1/spatial-data-requests?workAreaId=area-1");
  });

  it("shows records entries but no register path to readers on an empty catalog", async () => {
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [], nextCursor: null, hasMore: false });
    const empty = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(empty).toContain("이 작업구역에 등록된 자료가 없습니다");
    expect(empty).not.toContain("/sites/site-1/observations/new");
    expect(empty).toContain(">더 보기<");
    expect(empty).toContain("관측 작업 기록");
  });

  it("shows no register or records shortcut on denied or unknown scope", async () => {
    const { CoreApiError } = await import("@/lib/core-api/client");
    mocked.catalog.mockRejectedValueOnce(new CoreApiError(403, {}));
    const denied = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(denied).toContain("현장 등록 자료 조회 권한이 없습니다");
    expect(denied).not.toContain("이 작업구역에 등록된 자료가 없습니다");
    expect(denied).not.toContain("/sites/site-1/observations/new");
    // 문맥막대의 기존 도구모음은 그대로 두되, 빈 목록 행위는 싣지 않는다.
    expect(denied).not.toContain("관측 자료가 이 작업구역에 등록되면");
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
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));

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
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));

    expect(html).toContain("2022. 3. 4.");
    expect(html).toContain("재구성 소프트웨어: Terra (버전 미상)");
    expect(html).toContain("원본 보관: 고객 작업 장비");
    expect(html).toContain("KSI Export 2.0");
    expect(html).not.toContain("원자료 출처 (제출서 신고)");
  });

  it("keeps V1 records on the old semantics without new sections or notes", async () => {
    mocked.revision.mockResolvedValueOnce(v3Record({ ...v3Submission(), contractVersion: "external-reconstruction-submission.v1" }));
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));

    expect(mocked.revision).toHaveBeenCalledTimes(1);
    expect(html).toContain("관측 자료 상세");
    expect(html).not.toContain("등록 이력");
    expect(html).not.toContain("등록 이력(제출서)을 확인하지 못했습니다");
  });

  it("does not render a binding-mismatched foreign record or leak its source", async () => {
    mocked.revision.mockResolvedValueOnce(v3Record(v3Submission({ siteId: "site-9", organizationId: "org-9" })));
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));

    expect(html).toContain("관측 자료 상세");
    expect(html).not.toContain("CC BY 4.0");
    expect(html).not.toContain("https://example.test/floreat-2021");
    expect(html).not.toContain("등록 이력 (제출서 기준)");
    expect(html).toContain("등록 이력(제출서)을 확인하지 못했습니다");
  });

  it("keeps asset facts with a persistent note when the revision read fails", async () => {
    mocked.revision.mockRejectedValueOnce(new Error("Core 403"));
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));

    expect(html).toContain("관측 자료 상세");
    expect(html).toContain("north-dsm.tif");
    expect(html).toContain("등록 이력(제출서)을 확인하지 못했습니다");
    expect(html).not.toContain("Core 403");
  });

  it("previews the default record with one bounded history read", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", info: "1" }));

    expect(mocked.revision).toHaveBeenCalledTimes(1);
    expect(mocked.revision).toHaveBeenCalledWith("order-1", submissionRef, 2);
    expect(html).toContain("목록 첫 자료");
    expect(html).toContain("등록 이력(제출서)을 확인하지 못했습니다");
  });

  it("filters the loaded page and preserves the filter in pane scope and paging links", async () => {
    const second = {
      ...asset("area-1", "ortho"),
      assetRef: `ksa-v1-${"9".repeat(64)}`,
      observationEpochId: "epoch-2",
      declared: { ...asset().declared, fileName: "north-ortho.tif" },
    };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [asset(), second], nextCursor: "cursor-2", hasMore: true });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", kind: "ortho", state: "inspected" }));

    // 목록 드로어는 닫혀 있어도, 칸 이동·정보·페이징 주소에 같은 필터·범위가 실린다.
    expect(html).toContain("kind=ortho");
    expect(html).toContain("state=inspected");
    expect(html).toContain("cursor=cursor-2");
    // 미리보기는 필터와 무관하게 목록 첫 자료를 둔다 — 필터가 선택을 바꾸지 않는다.
    expect(html).toContain("목록 첫 자료");
  });

  it("says when no loaded record matches the filter instead of pretending the area is empty", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", q: "없는파일" }));
    // 필터가 빗나가도 선택 미리보기는 그대로 둔다 — 빈 구역으로 단정하지 않는다.
    expect(html).toContain("목록 첫 자료");
    expect(html).not.toContain("이 작업구역에 등록된 자료가 없습니다");
    expect(html).toContain("q=%EC%97%86%EB%8A%94%ED%8C%8C%EC%9D%BC");
  });

  it("marks the previewed record in the pane and keeps the scope in its links", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
    // 칸은 선택 자료를 보고, 파일 사실은 열린 정보에 둔다.
    expect(html).toContain("선택한 자료 미리보기");
    expect(html).toContain("관측 자료 상세");
    expect(html).toContain("선택 자료 정보");
    expect(html).not.toContain(">한 장으로<");
    // 옛 assetRef 진입은 그대로 왕복한다.
    expect(html).toContain(`assetRef=${assetRef}`);
  });

  it("marks attention records with their cause and a re-request path", async () => {
    const failed = {
      ...asset(),
      inspection: { ...asset().inspection, state: "FAILED", outcome: "REJECTED", reason: "검사 정책 불일치" },
    };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [failed], nextCursor: null, hasMore: false });
    mocked.detail.mockResolvedValueOnce(failed);
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
    expect(html).toContain("검사 정책 불일치");
    expect(html).toContain("구역 자료 준비에서 재처리 요청");
    expect(html).toContain("/sites/site-1/spatial-data-requests?workAreaId=area-1");
  });

  it("keeps the work area compact: text for one area, required select for many", async () => {
    const single = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    // 구역이 하나뿐이면 선택 상자 없이 구역명을 둔다.
    expect(single).not.toContain('id="spatial-work-area"');
    expect(single).toContain("작업구역 · 북측 작업구역");
    mocked.areas.mockResolvedValue({ workAreas: [workArea, { workAreaId: "area-2", name: "남측 작업구역", status: "ACTIVE" }] });
    const multi = renderToStaticMarkup(await callPage());
    // 작업구역은 필수, 필터 select 는 값이 비어도(전체) 제출되어야 한다.
    expect(multi).toMatch(/id="spatial-work-area"[^>]*required|required[^>]*id="spatial-work-area"/);
    expect(multi).not.toMatch(/id="spatial-kind"[^>]*required/);
    expect(multi).not.toMatch(/id="spatial-state"[^>]*required/);
    expect(multi).not.toContain("등록 자료 보기");
  });

  it("shows the verbatim file name in the detail without inferring capture facts", async () => {
    const dated = asset();
    dated.declared.fileName = "Site_EPSG7850_2021-05-04_ortho.tif";
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [dated], nextCursor: null, hasMore: false });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", info: "1" }));

    expect(html).toContain("등록 파일명 · Site_EPSG7850_2021-05-04_ortho.tif");
    expect(html).toContain("촬영 구간 미기재");
    expect(html).not.toContain("2021. 5. 4. 촬영");
  });
});

describe("materials visual browsing", () => {
  const secondRef = `ksa-v1-${"9".repeat(64)}`;

  it("keeps an honest compact state with extent metadata on demand when no prepared window exists", async () => {
    // 읽기 권한이 없으면 빈 목록으로 단정하지 않고 권한 없음만 말한다. 사진도
    // 범위 도식도 중앙에 두지 않는다.
    const denied = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(denied).toContain("준비 기록을 조회할 권한이 없습니다");
    expect(denied).not.toContain("범위 도식 · 사진 아님");
    // 읽을 수 있으면 정직한 현재 상태 한 줄과 복구 길만 먼저 둔다. 검사 격자에서
    // 유도한 범위 도식(사진 아님)은 정보 서랍 자리로 옮겨가므로 무대에는 두지
    // 않는다 — 서버 본문에는 자리만 두고, 접힘 본문은 하이드레이션 뒤에 든다.
    mocked.session.mockResolvedValueOnce({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ", "SPATIAL_DATA_READ"] } });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(html).toContain("준비된 표시 자료가 없습니다");
    expect(html).not.toContain("자료 범위 보기");
    expect(html).not.toContain("상세·준비");
    expect(html).not.toContain("범위 도식 · 사진 아님");
    expect(html).toContain('id="material-inspector-details"');
    expect(html).not.toContain("목록 첫 자료를 보여줍니다");
  });

  function pairCatalog() {
    const second = {
      ...asset("area-1", "ortho"),
      assetRef: secondRef,
      observationEpochId: "epoch-2",
      declared: { ...asset().declared, fileName: "north-ortho.tif" },
    };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [asset(), second], nextCursor: null, hasMore: false });
  }

  it("shows two exact records side by side without substituting either side", async () => {
    pairCatalog();
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: assetRef, visualBAssetRef: secondRef }));
    // 보기 방식은 한 줄 세그먼트다 — 한 장으로 돌아가는 링크를 그대로 둔다.
    expect(html).toContain("보기 방식");
    expect(html).toContain("나란히");
    expect(html).toContain(`visualBAssetRef=${secondRef}`);
    expect(html).toContain("작업공간에서 나란히 보기");
    // 실제 경로에는 내부 디자인 예시로 나가는 길을 두지 않는다.
    expect(html).not.toContain("밀어서 비교 예시");
    expect(html).not.toContain("/design-preview/materials");
    expect(html).toContain(`visualAAssetRef=${assetRef}`);
    expect(html).toContain(`visualBAssetRef=${secondRef}`);
    // 동기화·정합·수치 비교를 주장하지 않는다 — 쌍별 위치 기준 안내만 둔다.
    expect(html).toContain("두 칸은 같은 위치 기준(EPSG:32652)의 작업구역 경계와 함께 둡니다.");
    expect(html).not.toContain("목록 첫 자료");
  });

  it("leads the chosen pair to the canonical workspace compare with exact refs", async () => {
    pairCatalog();
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: assetRef, visualBAssetRef: secondRef }));
    // 자료 맥락의 쌍 선택은 작업공간 비교로 이어진다 — 같은 구역·같은 두
    // 참조를 싣고, 분석 조건 확인·기록 연결은 작업공간에서 잇는다.
    expect(html).toContain("작업공간에서 비교");
    expect(html).toContain("분석 조건 확인과 기록 연결은 작업공간에서 이어집니다");
    const bridge = html.match(/<a[^>]*href="([^"]*mode=compare[^"]*)"[^>]*>작업공간에서 비교<\/a>/);
    expect(bridge).toBeTruthy();
    const href = bridge![1]!.replace(/&amp;/g, "&");
    expect(href).toContain(`/sites/site-1?mode=compare`);
    expect(href).toContain(`workAreaId=area-1`);
    expect(href).toContain(`visualAAssetRef=${assetRef}`);
    expect(href).toContain(`visualBAssetRef=${secondRef}`);
    // 다리는 쌍별 위치 기준 안내보다 먼저 두며, 만료 회복이 1차일 때는
    // 조용한 동작으로 둔다(회복 CTA와 1차를 다투지 않는다).
    expect(bridge![0]).not.toContain("btn-primary");
    expect(html.indexOf("작업공간에서 비교")).toBeLessThan(html.indexOf("두 칸은 같은 위치 기준"));
    // 다리는 차단 회복보다 먼저 둔다 — 실패 무대를 스크롤해야 보이지 않는다.
    expect(html.indexOf("작업공간에서 비교")).toBeLessThan(html.indexOf("준비 기록을 조회할 권한이 없습니다"));
    // 기존 자료 비교 표시는 그대로 둔다 — 옛 주소·필터·권리가 깨지지 않는다.
    expect(html).toContain("선택한 두 자료 미리보기");
  });

  it("keeps the bridge primary when both sides are readable", async () => {
    pairCatalog();
    mocked.session.mockResolvedValueOnce({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ", "SPATIAL_DATA_READ"] } });
    mocked.prepared.mockResolvedValueOnce({
      siteId: "site-1", workAreaId: "area-1", nextCursor: null, hasMore: false,
      items: [assetRef, secondRef].map((ref, index) => ({
        jobId: `sdj-v1-00000000-0000-4000-8000-00000000002${index + 1}`,
        assetRef: ref, siteId: "site-1", workAreaId: "area-1",
        createdAt: "2026-09-30T03:00:00Z", executionState: "COMPLETED", availability: "AVAILABLE",
        receipt: null,
      })),
    });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: assetRef, visualBAssetRef: secondRef }));
    const bridge = html.match(/<a[^>]*href="([^"]*mode=compare[^"]*)"[^>]*>작업공간에서 비교<\/a>/);
    expect(bridge).toBeTruthy();
    expect(bridge![0]).toContain("btn-primary");
    expect(html).not.toContain("미리보기 보관 기간이 끝났습니다");
  });

  it("keeps a single view and an explicit notice when B is malformed", async () => {
    pairCatalog();
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: assetRef, visualBAssetRef: "broken" }));
    expect(html).toContain("두 번째 자료(B)의 참조가 올바르지 않습니다");
    expect(html).toContain("한 장");
    // B 칸이 없으므로 B 관측 선택 상자도 없다 — A 칸의 보기는 유지된다.
    expect(html).toContain("선택한 자료 미리보기");
    expect(html).not.toContain('id="pane-observation-visualBAssetRef"');
  });

  it("gives each mobile rail item a kind mark and two 44px A/B actions", () => {
    const source = readFileSync(join(process.cwd(), "src/app/sites/[siteId]/spatial-assets/page.tsx"), "utf8");
    expect(source).toContain("data-rail-item");
    expect(source).toContain("A로 보기");
    expect(source).toContain("B에 두기");
    expect(source).toContain("grid-cols-2");
    expect(source).toContain("min-h-11");
    expect(source).toContain("rounded-xl border");
    // No fake image or file-name-as-thumbnail: the type mark only states the kind.
    expect(source).toContain("KindGlyph");
  });

  it("keeps one segmented view switch with its purpose line and no toolbar example entry", async () => {
    pairCatalog();
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: assetRef, visualBAssetRef: secondRef }));
    // 보기 방식은 탭이 아니라 한 줄 세그먼트다.
    expect(html).toContain("보기 방식");
    expect(html).toContain('role="group"');
    expect(html).toContain('aria-labelledby="materials-view-mode-label"');
    expect(html).toContain("나란히 보기 · 등록 자료 확인·준비·열람");
    expect(html.match(/나란히 보기 · 등록 자료 확인·준비·열람/g)).toHaveLength(1);
    expect(html).toContain('aria-current="page"');
    // 내부 디자인 예시는 운영 화면의 도구·정보 서랍 어디에도 노출하지 않는다.
    expect(html).not.toContain("디자인 예시");
    const opened = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: assetRef, visualBAssetRef: secondRef, info: "1" }));
    expect(opened).toContain("선택 자료 정보");
    expect(opened).not.toContain("디자인 예시");
    expect(opened).not.toContain("/design-preview/materials");
  });

  it("keeps the empty state inside the product instead of linking to the design example", async () => {
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [], nextCursor: null, hasMore: false });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(html).toContain("이 작업구역에 등록된 자료가 없습니다");
    expect(html).not.toContain("디자인 예시");
    expect(html).not.toContain("/design-preview/materials");
  });

  it("prompts instead of substituting when the explicit A is outside the loaded page", async () => {
    pairCatalog();
    const foreignRef = `ksa-v1-${"f".repeat(64)}`;
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: foreignRef }));
    // 커서 페이지 밖 참조는 같은 범위에서 최대 2건까지 직접 확인한다.
    expect(mocked.detail).toHaveBeenCalledWith("site-1", "area-1", foreignRef);
    expect(html).toContain("선택한 첫 자료를 현재 목록에서 확인하지 못했습니다");
    expect(html).toContain("표시할 자료를 목록에서 고르세요");
    expect(html).not.toContain("목록 첫 자료");
  });

  it("collapses an identical pair to a single view with a notice", async () => {
    pairCatalog();
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: assetRef, visualBAssetRef: assetRef }));
    expect(html).toContain("같은 자료를 두 번 선택했습니다");
    expect(html).toContain(">한 장<");
    expect(html).not.toContain(">한 장으로<");
  });

  it("switches ortho and dsm of the same submission through exact refs only", async () => {
    const sibling = {
      ...asset("area-1", "ortho"),
      assetRef: secondRef,
      declared: { ...asset().declared, fileName: "north-ortho.tif" },
    };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [asset(), sibling], nextCursor: null, hasMore: false });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: assetRef }));
    expect(html).toContain(`visualAAssetRef=${secondRef}`);
    expect(html).toContain("정사영상");
    expect(html).toContain("지표면 높이 자료(DSM)");
  });

  it("renders a non-raster record as an honest file body, not a map", async () => {
    const report = {
      ...asset("area-1", "report"),
      assetRef: secondRef,
      inspection: { state: "COMPLETED", outcome: "NOT_APPLICABLE", reason: null, reportDigest: null, inspectorBuildDigest: null, raster: null },
    };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [report], nextCursor: null, hasMore: false });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: secondRef }));
    expect(html).toContain("이 형식은 미리보기를 두지 않습니다");
    expect(html).not.toContain("이어 보기");
  });

  it("keeps the default visual body read-only without prepare actions", async () => {
    const denied = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(denied).not.toContain("받기 요청 만들기");
    expect(denied).not.toContain("미리보기 준비");
    expect(denied).not.toContain("이 구역의 창 준비 요청");
    expect(denied).toContain("준비 기록을 조회할 권한이 없습니다");
    mocked.session.mockResolvedValueOnce({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ", "SPATIAL_DATA_READ"] } });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(html).not.toContain("받기 요청 만들기");
    expect(html).not.toContain("미리보기 준비");
    expect(html).not.toContain("이 구역의 창 준비 요청");
    // 준비 길은 정보 서랍 자리로 옮겨가므로 무대에는 두지 않는다.
    expect(html).toContain('id="material-inspector-details"');
  });

  it("reads prepared windows only with the data-read permission and never writes", async () => {
    renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(mocked.prepared).not.toHaveBeenCalled();
    mocked.session.mockResolvedValueOnce({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ", "SPATIAL_DATA_READ"] } });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(mocked.prepared).toHaveBeenCalledWith("site-1", "area-1", { limit: 50 });
    expect(html).toContain("준비된 표시 자료가 없습니다");
  });

  it("fetches an out-of-page A in the same scope and reads its history", async () => {
    const outside = {
      ...asset("area-1", "dsm"),
      assetRef: secondRef,
      observationEpochId: "epoch-9",
      declared: { ...asset().declared, fileName: "outside-dsm.tif" },
    };
    mocked.detail.mockResolvedValueOnce(outside);
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: secondRef, info: "1" }));
    expect(mocked.detail).toHaveBeenCalledWith("site-1", "area-1", secondRef);
    // 목록 밖에 있어도 같은 범위의 정확한 자료는 미리보기·정보에 둔다.
    expect(html).toContain("outside-dsm.tif");
    expect(html).toContain("한 장");
    expect(html).not.toContain("현재 목록에서 확인하지 못했습니다");
    // 선택 쪽의 제출서 이력도 bounded 1건으로 읽는다.
    expect(mocked.revision).toHaveBeenCalledWith("order-1", `ers-v1-${"b".repeat(64)}`, 2);
  });

  it("fails an out-of-page B opaque on 404 without leaking or substituting", async () => {
    const { CoreApiError } = await import("@/lib/core-api/client");
    const outsideRef = `ksa-v1-${"e".repeat(64)}`;
    pairCatalog();
    mocked.detail.mockRejectedValueOnce(new CoreApiError(404, {}));
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: assetRef, visualBAssetRef: outsideRef }));
    expect(mocked.detail).toHaveBeenCalledWith("site-1", "area-1", outsideRef);
    expect(html).toContain("선택한 두 번째 자료를 현재 목록에서 확인하지 못했습니다");
    expect(html).toContain("한 장");
    // 404의 원문·상태 코드는 드러내지 않는다. 상세 오류 경로도 타지 않는다.
    expect(html).not.toContain("Core 404");
    expect(html).not.toContain("자산을 찾을 수 없거나 현재 조회할 수 없습니다");
  });

  it("never fetches a malformed B", async () => {
    pairCatalog();
    renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: assetRef, visualBAssetRef: "broken!!" }));
    expect(mocked.detail).not.toHaveBeenCalled();
  });

  it("gates restricted records out of the preview without hiding their scope", async () => {
    const restricted = { ...asset(), assetRef: secondRef, dataAccess: "AVAILABLE_FROM_CATALOG", supportedActions: ["DOWNLOAD"] };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [restricted], nextCursor: null, hasMore: false });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: secondRef, info: "1" }));
    // 제한된 기록은 정보에서 제한을 밝히고, 미리보기는 파일형 본문을 두지 않는다.
    expect(html).toContain("선택 자료 정보");
    expect(html).toContain("Core 응답에 데이터 접근 또는 분석 상태 제한이 없어 미리보기를 표시하지 않았습니다");
    expect(html).toContain("Core 응답에 데이터 접근 또는 분석 상태 제한이 없어 상세를 표시하지 않았습니다");
  });

  it("keeps the A/B pair across paging", async () => {
    const outside = { ...asset("area-1", "ortho"), assetRef: secondRef, observationEpochId: "epoch-2" };
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [asset()], nextCursor: "opaque-cursor", hasMore: true });
    mocked.detail.mockResolvedValueOnce(outside);
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", cursor: "current-cursor", visualAAssetRef: assetRef, visualBAssetRef: secondRef }));
    expect(html).toContain(`visualAAssetRef=${assetRef}`);
    expect(html).toContain(`visualBAssetRef=${secondRef}`);
    expect(html).toContain("cursor=opaque-cursor");
  });

  it("does not invent chronological order for the independent A/B pair", async () => {
    pairCatalog();
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: assetRef, visualBAssetRef: secondRef }));
    expect(html).not.toContain("hintBaseline");
    expect(html).not.toContain("hintCurrent");
    // 정확한 선택 자체는 그대로 싣는다.
    expect(html).toContain(`visualAAssetRef=${assetRef}`);
    expect(html).toContain(`visualBAssetRef=${secondRef}`);
  });

  it("keeps an honest compact state — not a central diagram — when a prepared record exists but its bytes are unverified", async () => {
    // 영수증 메타데이터가 있어도 바이트 검증·디코딩 전에는 픽셀로 두지 않는다.
    // 정적 본문은 읽는 중 상태를 두며, 범위 도식은 펼침 안에서만 둔다.
    // (실측 503 사례: 메타데이터만으로 중앙 시각을 채우지 않는다.)
    mocked.session.mockResolvedValueOnce({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ", "SPATIAL_DATA_READ"] }});
    mocked.prepared.mockResolvedValueOnce({
      siteId: "site-1",
      workAreaId: "area-1",
      items: [{
        jobId: "sdj-v1-00000000-0000-4000-8000-000000000001",
        assetRef,
        siteId: "site-1",
        workAreaId: "area-1",
        createdAt: "2026-09-30T02:00:00Z",
        executionState: "COMPLETED",
        availability: "AVAILABLE",
        receipt: {
          jobId: "sdj-v1-00000000-0000-4000-8000-000000000001",
          artifactKind: "dsm",
          outputSizeBytes: 1234,
          outputSha256: digest("e"),
          requestedBounds: [500000, 4000000, 500010, 4000010],
          actualBounds: [500000, 4000000, 500010, 4000010],
          pixelWindow: [0, 200, 0, 100],
          width: 200,
          height: 100,
          observedCrsIdentifier: "EPSG:32652",
          observedCrsDigest: digest("1"),
          accuracyAssessed: false,
          attribution: "attr",
          modificationNotice: "mod",
          limitations: [],
          preparedAt: "2026-09-30T02:00:00Z",
        },
      }],
      nextCursor: null,
      hasMore: false,
    });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(html).toContain("자료 읽는 중");
    // 범위 도식은 서랍 자리로 옮겨가므로 무대에는 두지 않는다.
    expect(html).not.toContain("자료 범위 보기");
    expect(html).not.toContain("상세·준비");
    expect(html).not.toContain("범위 도식 · 사진 아님");
    expect(html).toContain('id="material-inspector-details"');
  });
});
