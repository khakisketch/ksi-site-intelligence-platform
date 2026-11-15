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
  analyses: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) => {
    delete props.scroll;
    return createElement("a", { href, ...props }, children);
  },
}));
vi.mock("next/navigation", () => ({
  redirect: (href: string) => { throw new Error(href); },
  notFound: () => { throw new Error("NEXT_NOT_FOUND"); },
  useRouter: () => ({ refresh: vi.fn() }),
}));
async function principal() {
  return (await mocked.session()).principal;
}
vi.mock("@/lib/core-api/auth", () => ({ whoAmI: principal }));
vi.mock("@/lib/core-api/permissions", () => ({
  hasAllPermissions: async (permission: string) => (await principal()).permissions.includes(permission),
}));
vi.mock("@/lib/core-api/analysis", () => ({ listAnalyses: mocked.analyses }));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/spatial-assets", () => ({ listSpatialAssets: mocked.catalog, getSpatialAsset: mocked.detail }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ listObservationWorkOrders: mocked.workOrders }));
vi.mock("@/lib/core-api/external-reconstruction", () => ({ getExternalReconstructionSubmission: mocked.revision }));
vi.mock("@/lib/core-api/spatial-data-requests", () => ({ listSpatialDataRequests: mocked.prepared }));
vi.mock("@/components/ui/ErrorState", () => ({
  ErrorState: ({ message }: { message: string }) => createElement("div", { role: "alert" }, message),
}));
vi.mock("@/lib/core-api/client", () => {
  class CoreApiError extends Error {
    constructor(readonly status: number, readonly retryAfterSeconds?: number) { super(`Core ${status}`); }
  }
  return { CoreApiError };
});

import SiteDataPage from "@/app/sites/[siteId]/data/page";
import { CoreApiError } from "@/lib/core-api/client";

// 위 vi.mock 의 가짜 클래스는 상태 코드 하나만 받는다 — 실제 클래스 타입과 달라 한 곳에서만 좁혀 쓴다.
const coreError = (status: number) => new (CoreApiError as unknown as new (status: number) => Error)(status);

const digest = (letter: string) => `sha256:${letter.repeat(64)}`;
const refOf = (letter: string) => `ksa-v1-${letter.repeat(64)}`;
const assetRef = refOf("a");
const secondRef = refOf("c");
const northArea = { workAreaId: "area-1", name: "북측 작업구역", status: "ACTIVE" };
const southArea = { workAreaId: "area-2", name: "남측 작업구역", status: "ACTIVE" };
const oldArea = { workAreaId: "area-3", name: "보관 작업구역", status: "ARCHIVED" };

function asset(ref = assetRef, fileName = "north-dsm.tif", workAreaId = "area-1", state = "COMPLETED", outcome: string | null = "MEASURED") {
  return {
    assetRef: ref,
    siteId: "site-1",
    workAreaId,
    workOrderId: "order-1",
    observationEpochId: `epoch-${ref.slice(8, 10)}`,
    submissionRef: `ers-v1-${"b".repeat(64)}`,
    revision: 2,
    artifactId: "artifact-1",
    kind: "dsm",
    lifecycleState: "SEALED",
    declared: {
      factClass: "DECLARED", fileName, format: "GeoTIFF", contentType: "image/tiff",
      sha256: "c".repeat(64), sizeBytes: 1234, crs: "EPSG:32652", verticalReference: null,
      gsdM: 0.05, submittedAt: "2026-09-30T01:00:00Z", producerCompletedAt: "2026-09-30T00:50:00Z",
      captureStartedAt: null, captureEndedAt: null,
    },
    observed: {
      factClass: "OBSERVED", manifestDigest: digest("d"), observedAt: "2026-09-30T01:01:00Z",
      sha256: "c".repeat(64), sizeBytes: 1234, contentType: "image/tiff",
    },
    inspection: {
      state, outcome, reason: null, reportDigest: digest("e"), inspectorBuildDigest: digest("f"),
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

const page = (assets: unknown[], extra: Record<string, unknown> = {}) => ({
  siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope",
  assets, nextCursor: null, hasMore: false, ...extra,
});

const render = async (query: Record<string, string | undefined> = {}) =>
  renderToStaticMarkup(await SiteDataPage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve(query) }));

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue({ kind: "ready", principal: {
    organizationId: "org-1", principalId: "operator-1",
    permissions: ["SITES_READ", "SPATIAL_DATA_READ", "SPATIAL_DATA_REQUEST", "WORK_ORDERS_WRITE"],
  } });
  mocked.site.mockResolvedValue({ siteId: "site-1", name: "현장 1", status: "BASELINE_MAPPING", aoi: null });
  mocked.areas.mockResolvedValue({ workAreas: [northArea, southArea, oldArea] });
  mocked.analyses.mockResolvedValue({ items: [], nextCursor: null });
  mocked.catalog.mockResolvedValue(page([asset(), asset(secondRef, "south-dsm.tif", "area-1", "FAILED", "REJECTED")]));
  mocked.detail.mockImplementation(async (_s: string, _a: string, ref: string) => asset(ref));
  mocked.workOrders.mockResolvedValue([
    { workOrderId: "order-1", siteId: "site-1", organizationId: "org-1", name: "북측 1차 관측", workAreaIds: ["area-1"], status: "APPROVED", version: 1 },
  ]);
  mocked.revision.mockRejectedValue(new Error("revision unavailable"));
  mocked.prepared.mockResolvedValue({ siteId: "site-1", workAreaId: "area-1", items: [], nextCursor: null, hasMore: false });
});

describe("자료 섹션 화면 (ADR-KSI-043)", () => {
  it("선택 구역의 자료를 표로 보이고 구역·검색을 컨텍스트 패널에 둔다", async () => {
    const html = await render();
    expect(mocked.catalog).toHaveBeenCalledWith("site-1", "area-1", { limit: 50 });
    expect(html).toContain('aria-label="자료 보기 조건"');
    expect(html).toContain('aria-label="선택한 자료 상세"');
    expect(html.match(/data-asset-row="true"/g)).toHaveLength(2);
    for (const head of ["자료", "취득 시점", "좌표 기준", "파일 검사"]) expect(html).toContain(`>${head}</th>`);
    expect(html).toContain("north-dsm.tif");
    expect(html).toContain("EPSG:32652");
    expect(html).toContain("검사 완료");
    expect(html).toContain("검사 실패");
    // 구역은 링크로 바꾸고, 보관 구역은 접힘 안에 둔다.
    expect(html).toContain('href="/sites/site-1/data?workAreaId=area-2"');
    expect(html).toContain("보관된 구역 1");
    expect(html).toContain('action="/sites/site-1/data"');
  });

  it("분석 적합성을 이 화면에서 단정하지 않는다", async () => {
    const html = await render();
    expect(html).toContain("분석 사용 여부는 분석의 실행 전 점검에서 확인합니다.");
    expect(html).not.toContain("분석 가능");
    expect(html).not.toContain("적합");
  });

  it("행은 선택 주소(assetRef)와 인스펙터 이동 앵커를 가진다", async () => {
    const html = await render({ workAreaId: "area-1", q: "north" });
    expect(html).toContain(`href="/sites/site-1/data?workAreaId=area-1&amp;assetRef=${assetRef}&amp;q=north#section-inspector"`);
  });

  it("선택한 자료의 상세를 인스펙터에 그린다", async () => {
    const html = await render({ workAreaId: "area-1", assetRef });
    expect(mocked.detail).toHaveBeenCalledWith("site-1", "area-1", assetRef);
    expect(html).toContain('aria-label="관측 자료 상세"');
    expect(html).toContain('aria-current="true"');
    expect(html).toContain("파일·식별 상세");
    expect(html).toContain("이 자료 새로 준비 요청");
    expect(html).toContain("/sites/site-1/spatial-data-requests?workAreaId=area-1");
  });

  it("고르지 않았으면 안내만 두고 상세를 읽지 않는다", async () => {
    const html = await render();
    expect(mocked.detail).not.toHaveBeenCalled();
    expect(html).toContain("표에서 자료를 고르면");
  });

  it("목록에 없는 자료·형식이 틀린 자료 주소는 다른 자료로 바꾸지 않고 안내한다", async () => {
    const missing = await render({ workAreaId: "area-1", assetRef: refOf("9") });
    expect(missing).toContain("선택한 자료를 이번 목록에서 찾을 수 없습니다");
    expect(mocked.detail).not.toHaveBeenCalled();
    const malformed = await render({ workAreaId: "area-1", assetRef: "nope" });
    expect(malformed).toContain("자료 주소가 올바르지 않습니다");
  });

  it("검색은 불러온 페이지 안에서만 적용하고 비면 초기화 링크를 둔다", async () => {
    const some = await render({ workAreaId: "area-1", q: "south" });
    expect(some.match(/data-asset-row="true"/g)).toHaveLength(1);
    expect(some).toContain("south-dsm.tif");
    const none = await render({ workAreaId: "area-1", q: "없는이름" });
    expect(none).toContain("조건과 일치하는 자료가 없습니다");
    expect(none).toContain('href="/sites/site-1/data?workAreaId=area-1"');
    expect(none).not.toContain("data-asset-row");
  });

  it("커서를 전달하고 더 불러오기·첫 페이지를 조건과 함께 잇는다", async () => {
    mocked.catalog.mockResolvedValue(page([asset()], { hasMore: true, nextCursor: "next/+=" }));
    const html = await render({ workAreaId: "area-1", kind: "dsm", cursor: "previous" });
    expect(mocked.catalog).toHaveBeenCalledWith("site-1", "area-1", { limit: 50, cursor: "previous" });
    expect(html).toContain("등록된 자료 1개 이상");
    expect(html).toContain('href="/sites/site-1/data?workAreaId=area-1&amp;kind=dsm&amp;cursor=next%2F%2B%3D"');
    expect(html).toContain('href="/sites/site-1/data?workAreaId=area-1&amp;kind=dsm"');
    expect(html).toContain("불러온 1개 자료에서 검색합니다.");
  });

  it("알 수 없는 구역은 읽지 않고 안내하며, 다른 구역으로 조용히 바꾸지 않는다", async () => {
    const html = await render({ workAreaId: "area-x" });
    expect(mocked.catalog).not.toHaveBeenCalled();
    expect(html).toContain("작업구역을 확인할 수 없거나 접근 권한이 없습니다");
  });

  it("목록 읽기 실패와 권한 거부를 빈 목록으로 단정하지 않는다", async () => {
    mocked.catalog.mockRejectedValueOnce(coreError(403));
    expect(await render({ workAreaId: "area-1" })).toContain("이 구역의 자료를 볼 권한이 없습니다");
    mocked.catalog.mockRejectedValueOnce(coreError(500));
    const failed = await render({ workAreaId: "area-1" });
    expect(failed).toContain("비어 있다는 뜻이 아닙니다");
    expect(failed).not.toContain("등록된 자료가 없습니다");
  });

  it("자료가 하나도 없는 구역은 빈 상태를 말한다", async () => {
    mocked.catalog.mockResolvedValue(page([]));
    expect(await render({ workAreaId: "area-1" })).toContain("이 구역에 등록된 자료가 없습니다");
  });

  it("구역이 없으면 작업구역 관리로 안내한다", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [] });
    const html = await render();
    expect(mocked.catalog).not.toHaveBeenCalled();
    expect(html).toContain("등록된 작업구역이 없습니다");
    expect(html).toContain('href="/sites/site-1/work-areas"');
  });

  it("등록 진행은 접힌 하단 서랍이고 progress=1이면 펼친다", async () => {
    const closed = await render({ workAreaId: "area-1" });
    expect(closed).toMatch(/<details[^>]*data-section-drawer="true"/);
    expect(closed).not.toMatch(/<details[^>]*open=""[^>]*data-section-drawer/);
    expect(closed).not.toMatch(/<details[^>]*data-section-drawer[^>]*open=""/);
    expect(closed).toContain("북측 1차 관측");
    const open = await render({ workAreaId: "area-1", progress: "1" });
    expect(open).toMatch(/<details[^>]*open=""[^>]*>/);
  });

  it("자료 등록은 작업 생성 권한이 있고 활성 구역일 때만 둔다", async () => {
    expect(await render({ workAreaId: "area-1" })).toContain("/sites/site-1/observations/new?workAreaId=area-1");
    mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", principalId: "v", permissions: ["SITES_READ", "SPATIAL_DATA_READ"] } });
    expect(await render({ workAreaId: "area-1" })).not.toContain("observations/new");
    mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", principalId: "o", permissions: ["SITES_READ", "WORK_ORDERS_WRITE"] } });
    expect(await render({ workAreaId: "area-3" })).not.toContain("observations/new");
  });

  it("준비 기록 읽기를 못 해도 목록은 그리고, 읽을 권한이 없으면 읽지 않는다", async () => {
    mocked.prepared.mockRejectedValue(new Error("down"));
    expect((await render({ workAreaId: "area-1" })).match(/data-asset-row="true"/g)).toHaveLength(2);
    mocked.prepared.mockClear();
    mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", principalId: "v", permissions: ["SITES_READ"] } });
    await render({ workAreaId: "area-1" });
    expect(mocked.prepared).not.toHaveBeenCalled();
  });

  it("없는 프로젝트는 404로 보낸다", async () => {
    mocked.site.mockRejectedValue(coreError(404));
    await expect(render()).rejects.toThrow("NEXT_NOT_FOUND");
  });
});
