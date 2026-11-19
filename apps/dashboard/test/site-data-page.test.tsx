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
  vertical: vi.fn(),
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
vi.mock("@/lib/core-api/vertical-reference", () => ({ getVerticalDeclarationState: mocked.vertical }));
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
      captureStartedAt: null as string | null, captureEndedAt: null as string | null,
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
  mocked.vertical.mockResolvedValue({ assetRef, observed: false, current: null, history: [] });
  mocked.prepared.mockResolvedValue({ siteId: "site-1", workAreaId: "area-1", items: [], nextCursor: null, hasMore: false });
});

describe("자료 섹션 화면 (ADR-KSI-043)", () => {
  it("새 페이지는 Core의 마이크로초 정밀 순서를 그대로 표시한다", async () => {
    const later = asset(refOf("z"), "마지막-마이크로초-최신.tif");
    later.declared.captureStartedAt = "2026-09-29T23:00:00.123457Z";
    const earlier = asset(refOf("a"), "마지막-마이크로초-이전.tif");
    earlier.declared.captureStartedAt = "2026-09-29T23:00:00.123456Z";
    mocked.catalog.mockResolvedValue(page([later, earlier]));

    const html = await render({ workAreaId: "area-1" });

    expect(mocked.catalog).toHaveBeenCalledWith("site-1", "area-1", { limit: 50, order: "capture-desc" });
    expect(html.indexOf("마지막-마이크로초-최신.tif")).toBeLessThan(
      html.indexOf("마지막-마이크로초-이전.tif"),
    );
  });

  it("이전 페이지 북마크는 기존 페이지 내 촬영 순서를 유지한다", async () => {
    const cursor = Buffer.from(JSON.stringify({
      after: refOf("m"),
      siteId: "site-1",
      version: 1,
      workAreaId: "area-1",
    })).toString("base64url");
    const later = asset(refOf("z"), "이전-화면-최신.tif");
    later.declared.captureStartedAt = "2026-09-29T23:00:00.124Z";
    const earlier = asset(refOf("a"), "이전-화면-이전.tif");
    earlier.declared.captureStartedAt = "2026-09-29T23:00:00.123Z";
    mocked.catalog.mockResolvedValue(page([earlier, later]));

    const html = await render({ workAreaId: "area-1", cursor });

    expect(mocked.catalog).toHaveBeenCalledWith("site-1", "area-1", {
      limit: 50,
      cursor,
      order: "asset-ref",
    });
    expect(html.indexOf("이전-화면-최신.tif")).toBeLessThan(
      html.indexOf("이전-화면-이전.tif"),
    );
  });

  it("선택 구역의 자료를 표로 보이고 구역·검색을 컨텍스트 패널에 둔다", async () => {
    const html = await render();
    expect(mocked.catalog).toHaveBeenCalledWith("site-1", "area-1", { limit: 50, order: "capture-desc" });
    expect(html).toContain('aria-label="자료 보기 조건"');
    expect(html).toContain('aria-label="선택한 자료 상세"');
    expect(html.match(/data-asset-row="true"/g)).toHaveLength(2);
    for (const head of ["자료", "취득 시점", "좌표 기준", "파일 검사"]) expect(html).toContain(`>${head}</th>`);
    expect(html).toContain("north-dsm.tif");
    expect(html).toContain("EPSG:32652");
    expect(html).toContain("검사 완료");
    expect(html).toContain("검사에서 거부됨");
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

  it.each([
    ["INSPECTION_FAILED_INCOMPLETE", "검사 미완료"],
    ["INSPECTION_PENDING", "검사 대기"],
  ])("보고서가 없는 %s를 표와 선택 상세에 같은 상태로 표시한다", async (state, label) => {
    const item = asset(assetRef, "coast-dsm.tif", "area-1", state, null);
    const observed = { ...item, inspection: { ...item.inspection, reportDigest: null, inspectorBuildDigest: null, raster: null } };
    mocked.catalog.mockResolvedValue({ ...page([]), assets: [observed] });
    mocked.detail.mockResolvedValue(observed);
    const html = await render({ workAreaId: "area-1", assetRef });
    expect(html.split("</table>")[0]).toContain(`>${label}</span>`);
    const detailHeader = html.split('aria-label="관측 자료 상세"')[1]?.split("<dl")[0];
    expect(detailHeader).toContain(`>${label}</span>`);
    if (state === "INSPECTION_FAILED_INCOMPLETE") {
      expect(html).toContain(`href="/field/work-orders/${item.workOrderId}"`);
      expect(html).toContain("등록 작업에서 검사 상태 확인");
    }
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

  it("검사를 마친 DSM 상세에서 공간 보기와 측정 선 단면 읽기로 이어진다", async () => {
    const html = await render({ workAreaId: "area-1", assetRef });
    expect(html).toContain('aria-label="이어서 할 일"');
    expect(html).toContain(`href="/sites/site-1?workAreaId=area-1&amp;assetRef=${assetRef}"`);
    expect(html).toContain(`href="/sites/site-1/measurements?workAreaId=area-1&amp;assetRef=${assetRef}"`);
  });

  it("표와 선택 상세에서 파일 거부 이유를 보여 주고 수정 GeoTIFF 등록 경로를 안내한다", async () => {
    const rejected = {
      ...asset(assetRef, "dsm.tif", "area-1", "INSPECTION_REPORTED", "REJECTED"),
      inspection: {
        ...asset().inspection,
        state: "INSPECTION_REPORTED",
        outcome: "REJECTED",
        reason: "AMBIGUOUS_GEOREFERENCE",
        raster: null,
      },
    };
    mocked.catalog.mockResolvedValue(page([rejected]));
    mocked.detail.mockResolvedValue(rejected);

    const html = await render({ workAreaId: "area-1", assetRef });
    const row = html.split("</table>")[0] ?? html;
    const detail = html.split('aria-label="관측 자료 상세"')[1] ?? "";

    expect(row).toContain(">검사에서 거부됨</span>");
    expect(row).not.toContain("검사 결과 기록됨");
    expect(detail).toContain("검사에서 거부됨");
    expect(detail).toContain("좌표계를 하나로 확정할 수 없습니다.");
    expect(detail).toContain("EPSG 번호가 있는 투영 좌표계");
    expect(detail).toContain(`href="/field/work-orders/order-1#external-submission-${rejected.submissionRef}-revision-2"`);
    expect(detail).toContain("원래 등록 작업 열기");
    expect(detail).not.toContain("이 자료 새로 준비 요청");
    expect(detail).not.toContain("처리 실패는");
    expect(detail).not.toContain("요청한 창은");
  });

  it("구역 목록에서 같은 촬영의 이전 거부 기록과 다시 검사한 수정본을 구별한다", async () => {
    const corrected = asset(secondRef, "dsm.tif");
    const original = {
      ...asset(assetRef, "dsm.tif"), revision: 1, lifecycleState: "SUPERSEDED", observationEpochId: corrected.observationEpochId,
      inspection: { ...asset().inspection, outcome: "REJECTED", reason: "AMBIGUOUS_GEOREFERENCE", raster: null },
    };
    mocked.catalog.mockResolvedValue(page([original, corrected]));
    mocked.detail.mockResolvedValueOnce(original);
    const history = await render({ workAreaId: "area-1", assetRef });
    const rows = history.split("</table>")[0];
    expect(rows).toContain("이전 등록 자료");
    expect(rows).toContain("검사에서 거부됨");
    expect(rows).toContain("파일 정보 확인됨");
    expect(history).toContain("같은 제출에 새 등록 버전이 있습니다.");
    expect(history).toContain(`#external-submission-${original.submissionRef}-revision-1"`);

    mocked.detail.mockResolvedValueOnce(corrected);
    const current = await render({ workAreaId: "area-1", assetRef: secondRef });
    expect(current).toContain(`#external-submission-${corrected.submissionRef}-revision-2"`);
    expect(current).toContain("등록 버전 2의 작업 기록 열기");
  });

  it("puts a reported rejection in 확인 필요 and keeps it out of 검사 완료", async () => {
    const measured = asset(assetRef, "measured.tif");
    const rejected = {
      ...asset(secondRef, "rejected.tif", "area-1", "INSPECTION_REPORTED", "REJECTED"),
      inspection: { ...asset().inspection, state: "INSPECTION_REPORTED", outcome: "REJECTED", reason: "UNSUPPORTED_RASTER" },
    };
    mocked.catalog.mockResolvedValue(page([measured, rejected]));

    const attention = await render({ workAreaId: "area-1", state: "attention" });
    const inspected = await render({ workAreaId: "area-1", state: "inspected" });

    expect(attention).toContain("rejected.tif");
    expect(attention).not.toContain("measured.tif");
    expect(inspected).toContain("measured.tif");
    expect(inspected).not.toContain("rejected.tif");

    mocked.catalog.mockResolvedValue(page([rejected]));
    mocked.detail.mockResolvedValue(rejected);
    const rejectedDetail = await render({ workAreaId: "area-1", assetRef: secondRef });
    expect(rejectedDetail).toContain("압축 방식, 색 방식, 밴드 구성 중 지원하지 않는 설정이 있습니다.");
    expect(rejectedDetail).toContain("압축은 LZW나 Deflate를 사용할 수 있습니다.");
    expect(rejectedDetail).toContain("반투명 영역이 있는 원본은 보존하세요.");
  });

  it("검사로 확인되지 않은 자료에는 이어서 할 일을 보이지 않는다", async () => {
    mocked.detail.mockResolvedValue(asset(assetRef, "north-dsm.tif", "area-1", "COMPLETED", "REJECTED"));
    const html = await render({ workAreaId: "area-1", assetRef });
    expect(html).not.toContain("이어서 할 일");
    expect(html).not.toContain("/measurements?workAreaId=");
  });

  it("수직 기준이 없는 검사된 DSM 상세에서 선언 상태를 읽어 선언 영역을 보인다", async () => {
    const html = await render({ workAreaId: "area-1", assetRef });
    expect(mocked.vertical).toHaveBeenCalledWith("site-1", "area-1", assetRef);
    expect(html).toContain('aria-label="수직 기준 선언"');
    expect(html).toContain("수직 기준(높이 기준)이 없어 높이·단면을 읽을 수 없습니다");
    expect(html).toContain("선언하기");
  });

  it("파일이 수직 기준을 담고 있으면 선언 영역을 보이지 않고 원장도 읽지 않는다", async () => {
    const withVertical = asset(assetRef);
    (withVertical.inspection.raster as { observedVerticalReference: unknown }).observedVerticalReference = { identifier: "EPSG:5773", basis: "EGM96 height" };
    mocked.detail.mockResolvedValue(withVertical);
    const html = await render({ workAreaId: "area-1", assetRef });
    expect(html).not.toContain('aria-label="수직 기준 선언"');
    expect(mocked.vertical).not.toHaveBeenCalled();
  });

  it("정사영상이거나 검사로 확인되지 않은 자료에는 선언 영역이 없다", async () => {
    mocked.detail.mockResolvedValue({ ...asset(assetRef), kind: "ortho" });
    expect(await render({ workAreaId: "area-1", assetRef })).not.toContain('aria-label="수직 기준 선언"');
    mocked.detail.mockResolvedValue(asset(assetRef, "north-dsm.tif", "area-1", "COMPLETED", "REJECTED"));
    expect(await render({ workAreaId: "area-1", assetRef })).not.toContain('aria-label="수직 기준 선언"');
    expect(mocked.vertical).not.toHaveBeenCalled();
  });

  it("선언 상태를 읽지 못하면 선언이 없다고 말하지 않는다", async () => {
    mocked.vertical.mockRejectedValue(new Error("down"));
    const html = await render({ workAreaId: "area-1", assetRef });
    expect(html).toContain("선언 상태를 불러오지 못했습니다");
    expect(html).toContain("선언이 없다는 뜻이 아닙니다");
    expect(html).not.toContain("선언하기");
  });

  it("작업 등록 권한이 없으면 선언 내용만 읽고 선언 조작은 없다", async () => {
    mocked.session.mockResolvedValue({ kind: "ready", principal: {
      organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ", "SPATIAL_DATA_READ"],
    } });
    const html = await render({ workAreaId: "area-1", assetRef });
    expect(html).toContain("작업 등록 권한이 있는 계정이 할 수 있습니다");
    expect(html).not.toContain("선언하기");
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

  it("측정에서 돌아온 자료가 다른 페이지에 있으면 같은 작업구역의 정확한 참조로 상세를 연다", async () => {
    mocked.catalog.mockResolvedValue({ ...page([asset(secondRef)]), hasMore: true, nextCursor: "following" });
    mocked.detail.mockResolvedValue(asset(assetRef, "return-to-spring.tif"));
    const html = await render({ workAreaId: "area-1", assetRef });
    expect(mocked.detail).toHaveBeenCalledWith("site-1", "area-1", assetRef);
    expect(html).toContain("return-to-spring.tif");
    expect(html).toContain(`measurements?workAreaId=area-1&amp;assetRef=${assetRef}`);
    expect(html).toContain("다음 페이지");
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

  it("현재 페이지를 검색하고 같은 조건으로 다음 페이지와 첫 페이지를 연다", async () => {
    mocked.catalog.mockResolvedValue(page([asset()], { hasMore: true, nextCursor: "next/+=" }));
    const html = await render({ workAreaId: "area-1", kind: "dsm", cursor: "previous" });
    expect(mocked.catalog).toHaveBeenCalledWith("site-1", "area-1", { limit: 50, cursor: "previous", order: "capture-desc" });
    expect(html).toContain("이 페이지의 자료 1개");
    expect(html).toContain('name="cursor" value="previous"');
    expect(html).toContain("다음 페이지");
    expect(html).toContain('href="/sites/site-1/data?workAreaId=area-1&amp;kind=dsm&amp;cursor=next%2F%2B%3D"');
    expect(html).toContain('href="/sites/site-1/data?workAreaId=area-1&amp;kind=dsm"');
    expect(html).toContain("이 페이지의 자료 1개에서 검색합니다.");
  });

  it("마지막 페이지의 검색·초기화와 빈 페이지 안내가 현재 위치를 지킨다", async () => {
    mocked.catalog.mockResolvedValue(page([asset()]));
    const filtered = await render({ workAreaId: "area-1", cursor: "last", q: "없는이름" });
    expect(filtered).toContain("이 페이지의 자료 1개");
    expect(filtered).toContain('name="cursor" value="last"');
    expect(filtered).toContain('href="/sites/site-1/data?workAreaId=area-1&amp;cursor=last"');
    expect(filtered).toContain("이 페이지의 자료 1개에서 검색합니다.");

    mocked.catalog.mockResolvedValue(page([]));
    const empty = await render({ workAreaId: "area-1", cursor: "last" });
    expect(empty).toContain("이 페이지에 자료가 없습니다");
    expect(empty).not.toContain("이 구역에 등록된 자료가 없습니다");
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
    const allowed = await render({ workAreaId: "area-1" });
    expect(allowed).toContain("/sites/site-1/upload?workAreaId=area-1");
    expect(allowed).toContain("/sites/site-1/observations/new?workAreaId=area-1");
    mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", principalId: "v", permissions: ["SITES_READ", "SPATIAL_DATA_READ"] } });
    const readOnly = await render({ workAreaId: "area-1" });
    expect(readOnly).not.toContain("observations/new");
    expect(readOnly).not.toContain("/upload");
    mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", principalId: "o", permissions: ["SITES_READ", "WORK_ORDERS_WRITE"] } });
    const archived = await render({ workAreaId: "area-3" });
    expect(archived).not.toContain("observations/new");
    expect(archived).not.toContain("/upload");
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
