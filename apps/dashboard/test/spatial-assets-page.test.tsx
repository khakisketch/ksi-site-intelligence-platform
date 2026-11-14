import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => {
  const catalog = vi.fn();
  return {
  session: vi.fn(),
  site: vi.fn(),
  areas: vi.fn(),
  catalog,
  lastPage: null as { assets?: Array<Record<string, unknown>> } | null,
  detail: vi.fn(),
  workOrders: vi.fn(),
  revision: vi.fn(),
  prepared: vi.fn(),
  workspace: vi.fn(),
  };
});

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
vi.mock("@/lib/core-api/analysis", () => ({ listAnalyses: async () => ({ items: [], nextCursor: null }) }));
vi.mock("@/lib/core-api/external-result-workflow", () => ({ listSiteExternalVolumeHistory: async () => ({ items: [], nextCursor: null }) }));
vi.mock("@/lib/core-api/spatial-workspace", () => ({ listSpatialWorkspaceObservations: mocked.workspace }));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/spatial-assets", () => ({
  listSpatialAssets: async (...args: unknown[]) => {
    const page = await mocked.catalog(...args);
    mocked.lastPage = page;
    return page;
  },
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

import SiteDetailPage from "@/app/sites/[siteId]/page";

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

const callPage = (query: Record<string, string | string[] | undefined> = {}) => {
  const { visualAAssetRef, visualBAssetRef, ...rest } = query;
  return SiteDetailPage({
    params: Promise.resolve({ siteId: "site-1" }),
    searchParams: Promise.resolve({
      panel: "materials",
      ...rest,
      ...(visualAAssetRef && visualBAssetRef
        ? { mode: "compare", visualAAssetRef, visualBAssetRef }
        : { assetRef: rest.assetRef ?? visualAAssetRef }),
    }),
  });
};

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", principalId: "operator-1", permissions: ["SITES_READ"] } });
  mocked.site.mockResolvedValue({ siteId: "site-1", name: "현장 1", status: "BASELINE_MAPPING", aoi: null, resumeTarget: null, siteFrame: { crs: "EPSG:5186", transformVersion: "v1" }, registeredAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-01T00:00:00Z" });
  mocked.areas.mockResolvedValue({ workAreas: [workArea] });
  mocked.catalog.mockResolvedValue({ siteId: "site-1", workAreaId: "area-1", scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY", scopeNote: "scope", assets: [asset()], nextCursor: null, hasMore: false });
  mocked.lastPage = null;
  mocked.detail.mockImplementation(async (_siteId: string, _areaId: string, ref: string) =>
    mocked.lastPage?.assets?.find((item) => item.assetRef === ref) ?? asset());
  mocked.workOrders.mockResolvedValue([{ workOrderId: "order-1", siteId: "site-1", organizationId: "org-1", name: "북측 1차 관측", workAreaIds: ["area-1"] }]);
  mocked.revision.mockRejectedValue(new Error("revision unavailable"));
  mocked.workspace.mockImplementation(async (siteId: string, workAreaId: string) => {
    const assets = (mocked.lastPage?.assets ?? []) as Array<ReturnType<typeof asset>>;
    return {
      siteId, workAreaId,
      entryDefault: { reason: assets.length ? "NO_VIEW_AVAILABLE_OBSERVATION" : "NO_OBSERVATIONS" },
      observations: assets.map((item) => ({
        observationEpochId: item.observationEpochId, workOrderId: item.workOrderId,
        viewAvailable: false,
        versions: [{ assetRef: item.assetRef, submissionRef: item.submissionRef, revision: item.revision, kind: item.kind }],
      })),
    };
  });
  mocked.prepared.mockResolvedValue({ siteId: "site-1", workAreaId: "area-1", items: [], nextCursor: null, hasMore: false });
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
  });

  it("says when no loaded record matches the filter instead of pretending the area is empty", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", q: "없는파일" }));
    // 필터가 빗나가도 선택 미리보기는 그대로 둔다 — 빈 구역으로 단정하지 않는다.
    expect(html).not.toContain("이 작업구역에 등록된 자료가 없습니다");
    expect(html).toContain("q=%EC%97%86%EB%8A%94%ED%8C%8C%EC%9D%BC");
  });

  it("marks the previewed record in the pane and keeps the scope in its links", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
    // 칸은 선택 자료를 보고, 파일 사실은 열린 정보에 둔다.
    expect(html).toContain("선택 관측 보기");
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
    expect(html).toContain("처리 실패는");
    expect(html).toContain("/sites/site-1/spatial-data-requests?workAreaId=area-1");
  });

  it("keeps the selected work area in the toolbar control", async () => {
    const single = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    // 구역이 하나뿐이면 선택 상자 없이 구역명을 둔다.
    expect(single).toContain('id="workspace-catalog-area"');
    expect(single).toContain("작업구역 · 북측 작업구역");
    mocked.areas.mockResolvedValue({ workAreas: [workArea, { workAreaId: "area-2", name: "남측 작업구역", status: "ACTIVE" }] });
    const multi = renderToStaticMarkup(await callPage());
    // 작업구역은 필수, 필터 select 는 값이 비어도(전체) 제출되어야 한다.
    expect(multi).toMatch(/id="workspace-catalog-area"[^>]*required|required[^>]*id="workspace-catalog-area"/);
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

function pageWith(items: ReturnType<typeof asset>[], nextCursor: string | null = null) {
  return { siteId: "site-1", workAreaId: "area-1", assets: items, nextCursor, hasMore: nextCursor !== null };
}

describe("materials panel in the canonical space", () => {
  it("keeps catalog scope, search, kind, state and the exact selection across pages", async () => {
    const first = asset();
    const second = { ...asset(), assetRef: `ksa-v1-${"c".repeat(64)}`, observationEpochId: "epoch-2",
      declared: { ...asset().declared, fileName: "south-dsm.tif" } };
    mocked.catalog.mockResolvedValue(pageWith([first, second], "opaque/next+="));
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, q: "north", kind: "dsm", state: "inspected", cursor: "previous" }));
    expect(mocked.catalog).toHaveBeenCalledWith("site-1", "area-1", { limit: 50, cursor: "previous" });
    expect(html).toContain('aria-label="자료 패널"');
    expect(html).toContain("north-dsm.tif");
    expect(html.match(/data-rail-item="true"/g)).toHaveLength(1);
    expect(html).toContain("검사 완료");
    expect(html).toContain(`/sites/site-1?panel=materials&amp;workAreaId=area-1&amp;assetRef=${assetRef}&amp;q=north&amp;kind=dsm&amp;state=inspected&amp;cursor=opaque%2Fnext%2B%3D`);
    expect(html).toContain("더 불러오기");
  });

  it("reports a filter miss without suggesting that the WorkArea is empty", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", q: "no-match" }));
    expect(html).toContain("이 페이지에 조건과 일치하는 자료가 없습니다");
    expect(html).not.toContain("에 확인된 관측이 없습니다");
  });

  it("keeps an exact asset available after its catalog page changes", async () => {
    mocked.catalog.mockResolvedValue(pageWith([]));
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", cursor: "empty-tail", assetRef, info: "1" }));
    expect(mocked.detail).toHaveBeenCalledExactlyOnceWith("site-1", "area-1", assetRef);
    expect(html).toContain("자료 정보");
    expect(html).toContain("관측 자료 상세");
    expect(html).toContain("north-dsm.tif");
  });

  it("keeps exact selected detail and declarations, observations and inspection distinct", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
    expect(mocked.detail).toHaveBeenCalledExactlyOnceWith("site-1", "area-1", assetRef);
    expect(html).toContain("파일·식별 상세");
    expect(html).toContain("제출자가 입력한 정보");
    expect(html).toContain("저장 파일 확인 정보");
    expect(html).toContain("파일 검사 결과");
    expect(html).toContain("EPSG:32652");
    expect(html).toContain("수직 기준");
    expect(html).toContain("북측 1차 관측");
    expect(html).toContain("관측 기록 ID · epoch-1");
    expect(html).not.toContain("objectKey");
  });

  it("keeps non-raster files as selected facts and states why they cannot be shown", async () => {
    const record = asset("area-1", "report");
    mocked.catalog.mockResolvedValue(pageWith([record]));
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
    expect(html).toContain("미리보기를 표시할 수 없습니다");
    expect(html).toContain("보고서 형식은 이 뷰어에서 열 수 없습니다");
    expect(html).toContain("파일·식별 상세");
    expect(html).not.toContain("등록 범위 도식");
  });

  it("gates the pixel preparation form to data-request permission", async () => {
    const readOnly = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
    expect(readOnly).not.toContain("이 자료 새로 준비 요청");
    expect(mocked.prepared).not.toHaveBeenCalled();
    mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", permissions: ["SPATIAL_DATA_READ", "SPATIAL_DATA_REQUEST"] } });
    const authorized = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
    expect(authorized).toContain("이 자료 새로 준비 요청");
    expect(mocked.prepared).toHaveBeenCalledExactlyOnceWith("site-1", "area-1", { limit: 50 });
  });

  it("sends a selected expired raster to its own preparation details", async () => {
    mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", permissions: ["SPATIAL_DATA_READ", "SPATIAL_DATA_REQUEST"] } });
    mocked.prepared.mockResolvedValue({
      items: [{ siteId: "site-1", workAreaId: "area-1", assetRef, jobId: "job-1", executionState: "EXPIRED",
        availability: "RETENTION_EXPIRED", createdAt: "2026-09-30T02:00:00Z", receipt: null }],
    });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef }));
    expect(html).toContain(">준비 요청</a>");
    expect(html).toContain(`assetRef=${assetRef}&amp;info=1`);
    expect(html).toContain("등록 범위 · 실제 픽셀 아님");
  });

  it("preserves an archived WorkArea for authorized historical catalog reads", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [{ ...workArea, status: "ARCHIVED" }] });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef, info: "1" }));
    expect(mocked.areas).toHaveBeenCalledWith("site-1", { includeArchived: true });
    expect(mocked.catalog).toHaveBeenCalledWith("site-1", "area-1", { limit: 50 });
    expect(html).toContain("관측 자료 상세");
    expect(html).toContain("보관됨");
  });

  it("rejects invalid cursors and foreign or repeated WorkAreas before reading materials", async () => {
    expect(renderToStaticMarkup(await callPage({ workAreaId: "foreign" }))).toContain("작업구역을 확인할 수 없거나 접근 권한이 없습니다");
    expect(renderToStaticMarkup(await callPage({ workAreaId: ["area-1", "foreign"] }))).toContain("작업구역을 확인할 수 없거나 접근 권한이 없습니다");
    expect(renderToStaticMarkup(await callPage({ workAreaId: "area-1", cursor: ["a", "b"] }))).toContain("페이지 주소가 올바르지 않습니다");
    expect(mocked.catalog).not.toHaveBeenCalled();
    expect(mocked.detail).not.toHaveBeenCalled();
  });

  it("distinguishes denied and failed catalog reads from a confirmed empty list", async () => {
    const { CoreApiError } = await import("@/lib/core-api/client");
    mocked.catalog.mockRejectedValueOnce(new CoreApiError(403, {}));
    const denied = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(denied).toContain("등록 자료 목록을 조회할 권한이 없습니다");
    expect(denied).not.toContain("에 확인된 관측이 없습니다");
    mocked.catalog.mockRejectedValueOnce(new CoreApiError(503, {}));
    const failed = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(failed).toContain("등록 자료 목록을 불러오지 못했습니다");
    expect(failed).not.toContain("에 확인된 관측이 없습니다");
  });

  it("fails closed on an unavailable explicit selection without substituting the first file", async () => {
    const missingRef = `ksa-v1-${"9".repeat(64)}`;
    mocked.detail.mockRejectedValueOnce(new Error("404"));
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", assetRef: missingRef, info: "1" }));
    expect(mocked.detail).toHaveBeenCalledExactlyOnceWith("site-1", "area-1", missingRef);
    expect(html).toContain("자료를 찾을 수 없거나 현재 조회할 수 없습니다");
    expect(html).not.toContain("관측 자료 상세");
    expect(html).not.toContain("등록 범위 도식");
  });

  it("shows two exact visual refs in the shared two-time viewer without a legacy viewer link", async () => {
    const first = asset();
    const second = { ...asset(), assetRef: `ksa-v1-${"c".repeat(64)}`, observationEpochId: "epoch-2",
      declared: { ...asset().declared, fileName: "second-dsm.tif" } };
    mocked.catalog.mockResolvedValue(pageWith([first, second]));
    mocked.session.mockResolvedValue({ kind: "ready", principal: { organizationId: "org-1", permissions: ["SPATIAL_DATA_READ"] } });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", visualAAssetRef: first.assetRef, visualBAssetRef: second.assetRef, info: "1" }));
    expect(html).toContain('name="visualAAssetRef"');
    expect(html).toContain('name="visualBAssetRef"');
    expect(html).toContain("각 칸은 독립된 보기입니다");
    expect(html).toContain(`name="visualAAssetRef" value="${first.assetRef}"`);
    expect(html).toContain(`name="visualBAssetRef" value="${second.assetRef}"`);
    expect(html).not.toContain("작업공간에서 비교");
  });
});
