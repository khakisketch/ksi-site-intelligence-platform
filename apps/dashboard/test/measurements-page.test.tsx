import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
  site: vi.fn(),
  areas: vi.fn(),
  features: vi.fn(),
  jobs: vi.fn(),
  result: vi.fn(),
  job: vi.fn(),
  revision: vi.fn(),
  comparison: vi.fn(),
  catalog: vi.fn(),
  asset: vi.fn(),
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
vi.mock("@/lib/core-api/session", () => ({ getSessionToken: async () => "reader" }));
vi.mock("@/app/field/OperationsSessionFailure", () => ({ OperationsSessionFailure: () => createElement("p", null, "로그인 필요") }));
vi.mock("@/app/sites/[siteId]/SiteHeader", () => ({ SiteHeader: () => createElement("header", null, "현장 머리") }));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/spatial-assets", () => ({ listSpatialAssets: mocked.catalog, getSpatialAsset: mocked.asset }));
vi.mock("@/lib/core-api/measurement", () => ({
  listMeasurementFeatures: mocked.features,
  listSurfaceProfileJobs: mocked.jobs,
  getSurfaceProfileResult: mocked.result,
  getSurfaceProfileJob: mocked.job,
  getMeasurementFeatureRevision: mocked.revision,
  getSurfaceProfileComparisonWithToken: mocked.comparison,
}));
vi.mock("@/components/ui/ErrorState", () => ({
  ErrorState: ({ message }: { message: string }) => createElement("div", { role: "alert" }, message),
}));
vi.mock("@/lib/core-api/client", () => ({
  CoreApiError: class CoreApiError extends Error {
    constructor(readonly status: number, _body?: unknown, readonly retryAfterSeconds?: number) { super(`Core ${status}`); }
  },
}));

import MeasurementsPage from "@/app/sites/[siteId]/measurements/page";
import { CoreApiError } from "@/lib/core-api/client";
import { measurementLoginReturn } from "@/lib/measurement-source";

const DIGEST = `sha256:${"a".repeat(64)}`;
const FEATURE_ID = `mf-${"1".repeat(32)}`;
const asset = (n: number) => `ksa-v1-${String(n).repeat(64)}`;
const jobId = (n: number) => `spj-${String(n).repeat(32)}`;
const area = { workAreaId: "area-1", name: "북측 작업구역", status: "ACTIVE" };

const feature = {
  featureId: FEATURE_ID, siteId: "site-1", workAreaId: "area-1", revision: 2, name: "북쪽 경사면", kind: "LINE",
  line: { crs: "EPSG:5186", vertices: [[200000, 500000], [200030, 500000]] }, lineDigest: DIGEST, createdAt: "2026-11-01T00:00:00Z",
};

function job(n: number, overrides: Record<string, unknown> = {}) {
  return {
    jobId: jobId(n), assetRef: asset(n), siteId: "site-1", workAreaId: "area-1",
    feature: { featureId: FEATURE_ID, revision: 2, lineDigest: DIGEST },
    createdAt: `2026-11-1${n}T00:00:00Z`, executionState: "COMPLETED", availability: "AVAILABLE", reason: null, ...overrides,
  };
}

function resultFor(n: number, offset: number, overrides: Record<string, unknown> = {}) {
  const samples = Array.from({ length: 5 }, (_, i) => (i === 2
    ? { index: i, distanceM: i * 7.5, x: 200000 + i * 7.5, y: 500000, elevationM: null, invalidReason: "NODATA" }
    : { index: i, distanceM: i * 7.5, x: 200000 + i * 7.5, y: 500000, elevationM: 100 + offset + i * 0.5, invalidReason: null }));
  return {
    job: job(n),
    result: {
      assetRef: asset(n), lineDigest: DIGEST, feature: { featureId: FEATURE_ID, revision: 2, lineDigest: DIGEST },
      horizontalCrs: "EPSG:5186", lineLengthM: 30, sampleSpacingM: 7.5, samples, validCount: 4, unknownCount: 1,
      minimumM: 100 + offset, maximumM: 102 + offset, ...overrides,
    },
  };
}

const callPage = (query: Record<string, string | string[] | undefined> = { workAreaId: "area-1" }) => MeasurementsPage({
  params: Promise.resolve({ siteId: "site-1" }),
  searchParams: Promise.resolve(query),
});
const render = async (query?: Record<string, string | string[] | undefined>) => renderToStaticMarkup(await callPage(query));

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue({ kind: "ready", principal: {
    principalId: "operator-1", organizationId: "org-1", kind: "OPERATOR", role: "ADMIN",
    permissions: ["SITES_READ", "SPATIAL_DATA_READ", "SPATIAL_DATA_REQUEST"],
  } });
  mocked.site.mockResolvedValue({ siteId: "site-1", name: "Floreat 검증 현장", status: "BASELINE_MAPPING" });
  mocked.areas.mockResolvedValue({ workAreas: [area] });
  mocked.features.mockResolvedValue({ features: [feature] });
  mocked.jobs.mockResolvedValue({ items: [job(3), job(1)] });
  mocked.catalog.mockResolvedValue({ siteId: "site-1", workAreaId: "area-1", assets: [
    { assetRef: asset(1), kind: "dsm", declared: { captureDate: "2026-03-14", captureStartedAt: null } },
    { assetRef: asset(3), kind: "dsm", declared: { captureDate: "2026-11-02", captureStartedAt: null } },
  ], nextCursor: null, hasMore: false });
  mocked.result.mockImplementation(async (_s: string, _a: string, id: string) => (id === jobId(1) ? resultFor(1, 0) : resultFor(3, 0.8)));
});

describe("측정 선 화면", () => {
  const linkedPair = { workAreaId: "area-1", feature: FEATURE_ID, ref: jobId(1), cur: jobId(3), comparison: "saved-decision" };
  const sourceQuery = { workAreaId: "area-1", assetRef: asset(1) };
  const source = { siteId: "site-1", ...sourceQuery, kind: "dsm", lifecycleState: "SEALED", inspection: { state: "INSPECTION_REPORTED", outcome: "MEASURED" }, declared: { fileName: "spring-survey.tif", captureDate: "2020-05-22" } };

  it("로그인 후 고른 자료와 선으로 복귀하고 임의의 쿼리는 전달하지 않는다", () => {
    const query = { ...sourceQuery, feature: FEATURE_ID, ref: "", token: "discard" };
    const link = new URL(measurementLoginReturn("site-1", false, query), "http://localhost");
    expect([...link.searchParams.keys()]).toEqual(["workAreaId", "assetRef", "feature", "ref"]);
    expect(link.searchParams.get("assetRef")).toBe(asset(1));
    const editor = new URL(measurementLoginReturn("site-1", true, { ...linkedPair, ...sourceQuery, featureId: FEATURE_ID, token: "discard" }), "http://localhost");
    expect(editor.pathname).toBe("/sites/site-1/measurements/new");
    expect([...editor.searchParams.keys()]).toEqual(["workAreaId", "assetRef", "feature", "ref", "cur", "comparison", "featureId"]);
    expect(editor.searchParams.get("feature")).toBe(FEATURE_ID);
    expect(editor.searchParams.get("featureId")).toBe(FEATURE_ID);
    expect(editor.searchParams.get("token")).toBeNull();
    const invalid = measurementLoginReturn("site-1", false, { workAreaId: "area-1", assetRef: "private-invalid-ref", feature: "../elsewhere", cur: ["not-a-job"] });
    expect(invalid).toBe("/sites/site-1/measurements?workAreaId=area-1&assetRef=invalid&feature=invalid&cur=invalid");
    expect(invalid).not.toContain("private-invalid-ref");
    expect(invalid).not.toContain("elsewhere");
  });

  it("최근 자료와 선 작업 목록에 없는 선택 자료도 정확히 찾아 그 날짜만 연다", async () => {
    mocked.asset.mockResolvedValue(source);
    mocked.catalog.mockResolvedValue({ siteId: "site-1", workAreaId: "area-1", assets: [], hasMore: true });
    mocked.jobs.mockImplementation(async (_s, _a, options) => {
      if (!options.assetRef) return { items: [job(3)] };
      if (options.executionGroup === "COMPLETED") return { items: [job(1)] };
      if (options.executionGroup === "ACTIVE") return { items: [] };
      return { items: Array.from({ length: 8 }, (_, i) => job(1, { jobId: `spj-${i.toString(16).padStart(32, "0")}`, executionState: "CANCELED" })) };
    });
    const html = await render(sourceQuery);
    expect(mocked.asset).toHaveBeenCalledWith("site-1", "area-1", asset(1));
    expect(mocked.jobs).toHaveBeenCalledWith("site-1", "area-1", { assetRef: asset(1), featureId: FEATURE_ID, featureRevision: 2, limit: 1, executionGroup: "COMPLETED" });
    expect(mocked.result.mock.calls).toEqual([["site-1", "area-1", jobId(1)]]);
    expect(html).toContain("spring-survey.tif");
    expect(html).toContain("2020-05-22");
    expect(html).toContain(`href="/sites/site-1?workAreaId=area-1&amp;assetRef=${asset(1)}"`);
    expect(html).toContain('name="assetRef"');
    expect(html).toContain("단면을 읽었습니다.");
  });

  it("선택 자료를 읽은 적이 없는 선에서 다른 날짜를 대체 표시하지 않고 선 선택과 요청을 유지한다", async () => {
    mocked.asset.mockResolvedValue(source);
    mocked.session.mockResolvedValue({ kind: "ready", principal: { permissions: ["SITES_READ", "SITES_WRITE", "SPATIAL_DATA_READ", "SPATIAL_DATA_REQUEST"] } });
    mocked.features.mockResolvedValue({ features: [feature, { ...feature, name: "북쪽 사면 보조선", featureId: `mf-${"2".repeat(32)}` }] });
    mocked.jobs.mockImplementation(async (_s, _a, options) => ({ items: options.assetRef ? [] : [job(3)] }));
    const html = await render(sourceQuery);
    expect(mocked.result).not.toHaveBeenCalled();
    expect(html).toContain('id="measurement-feature"');
    expect(html).toContain("북쪽 사면 보조선");
    expect(html).toContain("아직 요청하지 않았습니다.");
    expect(html).toContain(">단면 요청</button>");
    expect(html).toContain(`/measurements/new?workAreaId=area-1&amp;assetRef=${asset(1)}`);
    expect(html).not.toContain("2026-11-02");
  });

  it.each([{ ...source, kind: "ortho" }, { ...source, workAreaId: "different-area" }, { ...source, lifecycleState: "SUPERSEDED" }])("지정한 자료가 현재 구역의 검사된 DSM이 아니면 다른 자료를 열지 않는다", async (unavailable) => {
    mocked.asset.mockResolvedValue(unavailable);
    const html = await render(sourceQuery);
    expect(html).toContain("선택한 DSM을 이 작업구역에서 열 수 없습니다");
    expect(html).not.toContain(`href="/sites/site-1?workAreaId=area-1&amp;assetRef=${asset(1)}"`);
    expect(mocked.jobs).not.toHaveBeenCalled();
    expect(mocked.features).not.toHaveBeenCalled();
  });

  it("작업구역 누락·잘못된 자료 참조·고정 비교와의 혼용은 자료 조회 전에 거부한다", async () => {
    for (const query of [{ assetRef: asset(1) }, { ...sourceQuery, assetRef: [asset(1), asset(2)] }, { ...linkedPair, assetRef: asset(1) }]) {
      expect(await render(query)).toContain("주소의 선택 값이 올바르지 않습니다");
    }
    expect(mocked.asset).not.toHaveBeenCalled();
    expect(mocked.result).not.toHaveBeenCalled();
  });
  it("고유 주소는 최근 목록 밖의 단면까지 읽고 저장한 판정만 조회한다", async () => {
    mocked.jobs.mockResolvedValueOnce({ items: [job(3), job(2, { assetRef: asset(1) })] });
    mocked.job.mockResolvedValueOnce(job(1));
    mocked.comparison.mockResolvedValueOnce({
      contractVersion: "surface-profile-comparison.v1", decisionId: linkedPair.comparison,
      baselineJobId: linkedPair.ref, currentJobId: linkedPair.cur, decisionDigest: DIGEST,
      verdict: "BLOCKED", reasons: ["COMPATIBILITY_MAPPING_MISSING"], remediations: ["AUTHORIZE_COMPATIBILITY_MAPPING"], result: null,
    });
    const html = await render(linkedPair);
    expect(mocked.job).toHaveBeenCalledWith("site-1", "area-1", jobId(1));
    expect(mocked.comparison).toHaveBeenCalledWith("site-1", "area-1", {
      baselineJobId: jobId(1), currentJobId: jobId(3), decisionId: linkedPair.comparison,
    }, "reader");
    expect(html).toContain("호환성 매핑이 등록되지 않았습니다");
    expect(html).not.toContain("높이차 CSV 내보내기");
  });
  it("철회된 비교 주소에서 날짜별 단면은 읽고 비교 수치는 숨긴다", async () => {
    mocked.comparison.mockRejectedValueOnce(new CoreApiError(409, {}));
    const html = await render(linkedPair);
    expect(html).toContain("이 비교를 열 수 없습니다");
    expect(html).toContain("날짜별 높이 CSV 내보내기");
    expect(html).not.toContain("높이차 CSV 내보내기");
  });
  it("선을 고친 뒤에도 고유 주소는 두 작업의 이전 선 개정과 당시 판정을 읽는다", async () => {
    mocked.features.mockResolvedValueOnce({ features: [{ ...feature, revision: 3, lineDigest: `sha256:${"e".repeat(64)}` }] });
    mocked.revision.mockResolvedValueOnce(feature);
    mocked.comparison.mockResolvedValueOnce({
      contractVersion: "surface-profile-comparison.v1", decisionId: linkedPair.comparison,
      baselineJobId: linkedPair.ref, currentJobId: linkedPair.cur, decisionDigest: DIGEST,
      verdict: "BLOCKED", reasons: ["COMPATIBILITY_MAPPING_MISSING"], remediations: ["AUTHORIZE_COMPATIBILITY_MAPPING"], result: null,
    });
    const html = await render(linkedPair);
    expect(mocked.revision).toHaveBeenCalledWith("site-1", "area-1", { featureId: FEATURE_ID, revision: 2, lineDigest: DIGEST });
    expect(html).toContain("저장 당시 측정 선 개정");
    expect(html).toContain("호환성 매핑이 등록되지 않았습니다");
    expect(html).not.toContain("이 선 고치기");
  });
  it("작업구역을 고르기 전에는 Core의 선·작업을 읽지 않는다", async () => {
    const html = await render({});
    expect(html).toContain("작업구역을 선택");
    expect(mocked.features).not.toHaveBeenCalled();
    expect(mocked.jobs).not.toHaveBeenCalled();
  });

  it("날짜별 단면을 기준·현재로 보여 주고 필요한 결과만 읽는다", async () => {
    const html = await render();
    expect(mocked.jobs).toHaveBeenCalledWith("site-1", "area-1", { limit: 8, featureId: FEATURE_ID });
    expect(html).toContain("북쪽 경사면");
    expect(html).toContain("기준 2026-03-14");
    expect(html).toContain("현재 2026-11-02");
    expect(mocked.result).toHaveBeenCalledTimes(2);
    expect(mocked.result).toHaveBeenCalledWith("site-1", "area-1", jobId(1));
    expect(mocked.result).toHaveBeenCalledWith("site-1", "area-1", jobId(3));
    // 값 없는 지점은 이유와 함께 센다. 0으로 채우지 않는다.
    expect(html).toContain("자료 없음 1");
    expect(html).toContain("측량 성과가 아닙니다");
  });

  it("완료 영수증의 수직 기준 출처를 숫자 옆에 보인다(선언은 선언이라고)", async () => {
    const observed = { provenance: "OBSERVED", observed: { identifier: "EPSG:5773", basis: "EGM96 height" }, declared: null };
    const declared = {
      provenance: "DECLARED", observed: null,
      declared: { declarationId: `vrd-${"1".repeat(32)}`, declarationDigest: DIGEST, datum: "orthometric_kngeoid2018", unit: "metre", basis: "Terra", declaredBy: "operator-1", declaredAt: "2026-11-17T00:00:00Z" },
    };
    mocked.result.mockImplementation(async (_s: string, _a: string, id: string) => {
      const view = id === jobId(1) ? resultFor(1, 0) : resultFor(3, 0.8);
      return { ...view, job: { ...view.job, receipt: { verticalReference: id === jobId(1) ? observed : declared } } };
    });
    const html = await render();
    expect(html).toContain("파일에서 확인 · EPSG:5773");
    expect(html).toContain("사용자 선언 · 정표고(KNGeoid2018)");
    expect(html).toContain("수직 기준이 달라");
  });

  it("영수증이 없으면 수직 기준을 모른다고 쓴다", async () => {
    const html = await render();
    expect(html).toContain("수직 기준 확인 불가");
  });

  it("쓰기 권한이 있고 구역이 열려 있으면 선 그리기·고치기 진입을 보인다", async () => {
    mocked.session.mockResolvedValue({ kind: "ready", principal: {
      principalId: "operator-1", organizationId: "org-1", kind: "OPERATOR", role: "ADMIN",
      permissions: ["SITES_READ", "SITES_WRITE", "SPATIAL_DATA_READ"],
    } });
    const html = await render();
    expect(html).toContain(`href="/sites/site-1/measurements/new?workAreaId=area-1&amp;feature=${FEATURE_ID}"`);
    expect(html).toContain(`href="/sites/site-1/measurements/new?workAreaId=area-1&amp;feature=${FEATURE_ID}&amp;featureId=${FEATURE_ID}"`);
    expect(html).toContain("이 선 고치기");
  });

  it("새 선 취소는 선택한 선과 명시한 날짜를 보존하고 기본 날짜 선택은 고정하지 않는다", async () => {
    mocked.session.mockResolvedValue({ kind: "ready", principal: {
      principalId: "operator-1", organizationId: "org-1", kind: "OPERATOR", role: "ADMIN",
      permissions: ["SITES_READ", "SITES_WRITE", "SPATIAL_DATA_READ"],
    } });
    mocked.comparison.mockResolvedValueOnce({
      contractVersion: "surface-profile-comparison.v1", decisionId: linkedPair.comparison,
      baselineJobId: linkedPair.ref, currentJobId: linkedPair.cur, decisionDigest: DIGEST,
      verdict: "BLOCKED", reasons: ["COMPATIBILITY_MAPPING_MISSING"], remediations: ["AUTHORIZE_COMPATIBILITY_MAPPING"], result: null,
    });
    const html = await render(linkedPair);
    expect(html).toContain(`href="/sites/site-1/measurements/new?workAreaId=area-1&amp;feature=${FEATURE_ID}&amp;ref=${jobId(1)}&amp;cur=${jobId(3)}&amp;comparison=${linkedPair.comparison}"`);
    const unpinned = await render({ workAreaId: "area-1", feature: FEATURE_ID });
    expect(unpinned).toContain(`href="/sites/site-1/measurements/new?workAreaId=area-1&amp;feature=${FEATURE_ID}"`);
    expect(unpinned).not.toContain(`&amp;ref=${jobId(1)}`);
    expect(unpinned).not.toContain(`&amp;cur=${jobId(3)}`);
  });

  describe("날짜별 단면 요청", () => {
    const sealed = (n: number, date: string, kind = "dsm", lifecycleState = "SEALED") => ({ assetRef: asset(n), kind, lifecycleState, declared: { captureDate: date, captureStartedAt: null } });
    const writer = (extra: string[] = []) => mocked.session.mockResolvedValue({ kind: "ready", principal: {
      principalId: "operator-1", organizationId: "org-1", kind: "OPERATOR", role: "ADMIN",
      permissions: ["SITES_READ", "SPATIAL_DATA_READ", "SITES_WRITE", "SPATIAL_DATA_REQUEST", ...extra],
    } });
    const catalog = (assets: unknown[]) => mocked.catalog.mockResolvedValue({ siteId: "site-1", workAreaId: "area-1", assets, nextCursor: null, hasMore: false });

    it("봉인된 DSM마다 요청 상태를 보이고, 요청하지 않은 날짜에 요청 버튼을 연다", async () => {
      writer();
      catalog([sealed(1, "2026-03-14"), sealed(3, "2026-11-02"), sealed(5, "2026-11-09")]);
      const html = await render();
      expect(mocked.catalog).toHaveBeenCalledWith("site-1", "area-1", { limit: 50, order: "capture-desc" });
      expect(html).toContain("날짜별 단면");
      expect(html).toContain("2026-11-09");
      expect(html).toContain('data-request-state="none"');
      expect(html).toContain('data-request-state="done"');
      expect(html).toContain("단면 요청");
    });

    it("DSM이 아니거나 봉인 전인 자료는 요청 대상이 아니다", async () => {
      writer();
      catalog([sealed(1, "2026-03-14"), sealed(3, "2026-11-02", "ortho"), sealed(5, "2026-11-09", "dsm", "UNSEALED")]);
      const html = await render();
      expect(html).not.toContain("2026-11-09");
      expect(html).toContain("2026-03-14");
      expect(html.match(/data-request-state=/g)).toHaveLength(1);
    });

    it("DSM이 없으면 요청 패널을 열지 않는다", async () => {
      writer();
      catalog([sealed(3, "2026-11-02", "ortho")]);
      expect(await render()).not.toContain("날짜별 단면");
    });

    it("거부된 파일과 단면 지원 범위 밖에서 검사된 DSM은 사유와 자료 상세만 제공한다", async () => {
      writer();
      catalog([
        { ...sealed(5, "2024-06-24"), inspection: { state: "INSPECTION_REPORTED", outcome: "REJECTED", raster: null } },
        { ...sealed(6, "2024-07-05"), inspection: { state: "INSPECTION_REPORTED", outcome: "MEASURED", raster: { observedCrsIdentifier: "EPSG:32634" } } },
      ]);
      const html = await render();
      expect(html).toContain("파일 검사에서 거부된 DSM입니다.");
      expect(html).toContain("수평 좌표계(EPSG:32634)는 현재 단면 분석 지원 범위 밖입니다.");
      expect(html).toContain("자료 상세 열기");
      expect(html).not.toContain(">단면 요청</button>");
    });

    it("쓰기·요청 권한이 모두 있어야 요청 버튼이 열리고, 없으면 상태만 보인다", async () => {
      catalog([sealed(1, "2026-03-14"), sealed(5, "2026-11-09")]);
      const partial = async (permissions: string[]) => {
        mocked.session.mockResolvedValue({ kind: "ready", principal: { principalId: "o", organizationId: "org-1", kind: "OPERATOR", role: "ADMIN", permissions } });
        return render();
      };
      for (const permissions of [["SITES_READ", "SPATIAL_DATA_READ", "SITES_WRITE"], ["SITES_READ", "SPATIAL_DATA_READ", "SPATIAL_DATA_REQUEST"], ["SITES_READ", "SPATIAL_DATA_READ"]]) {
        const html = await partial(permissions);
        expect(html).toContain("날짜별 단면");
        expect(html).not.toContain(">단면 요청</button>");
        expect(html).toContain("작업 등록 권한이 있는 계정");
      }
      writer();
      expect(await render()).toContain(">단면 요청</button>");
    });

    it("보관된 구역에서는 요청하지 않는다", async () => {
      writer();
      mocked.areas.mockResolvedValue({ workAreas: [{ ...area, status: "ARCHIVED" }] });
      catalog([sealed(1, "2026-03-14"), sealed(5, "2026-11-09")]);
      expect(await render()).not.toContain(">단면 요청</button>");
    });

    it("진행 중이거나 실패한 요청을 이 선의 정확한 개정에 한해 보인다", async () => {
      writer();
      catalog([sealed(1, "2026-03-14"), sealed(5, "2026-11-09"), sealed(6, "2026-11-12")]);
      mocked.jobs.mockResolvedValue({ items: [
        job(1),
        job(5, { executionState: "RUNNING", availability: "NOT_READY" }),
        job(6, { executionState: "FAILED", availability: "UNAVAILABLE", reason: "LINE_OUTSIDE_SURFACE" }),
        job(6, { feature: { featureId: FEATURE_ID, revision: 1, lineDigest: DIGEST }, executionState: "COMPLETED" }),
      ] });
      const html = await render();
      expect(html).toContain("단면을 읽는 중입니다");
      expect(html).toContain("이 선이 등록된 범위에 닿지 않았습니다");
      expect(html).toContain("요청 취소");
      expect(html).toContain("다시 요청");
    });

    it("단면 기능이 연결되지 않은 환경에서는 요청 패널을 열지 않는다", async () => {
      writer();
      catalog([sealed(1, "2026-03-14")]);
      mocked.jobs.mockRejectedValue(new CoreApiError(404, {}));
      const html = await render();
      expect(html).not.toContain("날짜별 단면");
      expect(html).toContain("단면 기능이 연결되어 있지 않아");
    });

    it("결과가 하나도 없어도 요청 패널은 보인다(첫 요청을 할 수 있어야 한다)", async () => {
      writer();
      catalog([sealed(1, "2026-03-14")]);
      mocked.jobs.mockResolvedValue({ items: [] });
      const html = await render();
      expect(html).toContain("날짜별 단면");
      expect(html).toContain("이 선의 단면 결과가 없습니다");
    });
  });

  it("쓰기 권한이 없으면 진입을 보이지 않는다", async () => {
    const html = await render();
    expect(html).not.toContain("/measurements/new");
  });

  it("보관된 구역에는 진입을 보이지 않는다", async () => {
    mocked.session.mockResolvedValue({ kind: "ready", principal: {
      principalId: "operator-1", organizationId: "org-1", kind: "OPERATOR", role: "ADMIN",
      permissions: ["SITES_READ", "SITES_WRITE", "SPATIAL_DATA_READ"],
    } });
    mocked.areas.mockResolvedValue({ workAreas: [{ ...area, status: "ARCHIVED" }] });
    expect(await render()).not.toContain("/measurements/new");
  });

  it("선이 하나도 없을 때 쓰기 권한이 있으면 그리기로 안내한다", async () => {
    mocked.session.mockResolvedValue({ kind: "ready", principal: {
      principalId: "operator-1", organizationId: "org-1", kind: "OPERATOR", role: "ADMIN",
      permissions: ["SITES_READ", "SITES_WRITE", "SPATIAL_DATA_READ"],
    } });
    mocked.features.mockResolvedValueOnce({ features: [] });
    const html = await render();
    expect(html).toContain("측정 선 그리기");
    expect(html).toContain("/measurements/new?workAreaId=area-1");
  });

  it("저장한 선이 없으면 빈 상태다", async () => {
    mocked.features.mockResolvedValueOnce({ features: [] });
    const html = await render();
    expect(html).toContain("저장한 측정 선이 없습니다");
    expect(mocked.jobs).not.toHaveBeenCalled();
  });

  it("단면 결과가 없으면 그렇게 말한다", async () => {
    mocked.jobs.mockResolvedValueOnce({ items: [] });
    const html = await render();
    expect(html).toContain("이 선의 단면 결과가 없습니다");
    expect(mocked.result).not.toHaveBeenCalled();
  });

  it("단면 기능이 연결되지 않은 환경(404)은 빈 결과로 위장하지 않는다", async () => {
    mocked.jobs.mockRejectedValueOnce(new CoreApiError(404, {}));
    const html = await render();
    expect(html).toContain("연결되어 있지 않아");
    expect(html).not.toContain("이 선의 단면 결과가 없습니다");
  });

  it("현재 날짜의 읽기 권한이 없으면 그 날짜는 숨기고 기준만 보여 준다", async () => {
    mocked.result.mockImplementation(async (_s: string, _a: string, id: string) => {
      if (id === jobId(3)) throw new CoreApiError(403, {});
      return resultFor(1, 0);
    });
    const html = await render();
    expect(html).toContain("접근 권한이 없어 표시하지 않습니다");
    expect(html).toContain('data-series="ref"');
    expect(html).not.toContain('data-series="cur"');
  });

  it("권한이 철회된 완료 작업은 결과를 요청하지도 않는다", async () => {
    mocked.jobs.mockResolvedValueOnce({ items: [job(3, { availability: "ACCESS_REVOKED" }), job(1)] });
    const html = await render();
    expect(html).toContain("접근 권한이 철회되어 표시하지 않습니다");
    expect(mocked.result).toHaveBeenCalledTimes(1);
    expect(mocked.result).toHaveBeenCalledWith("site-1", "area-1", jobId(1));
  });

  it("결과가 요청한 선·자료와 어긋나면 표시하지 않는다", async () => {
    mocked.result.mockImplementation(async (_s: string, _a: string, id: string) =>
      id === jobId(3) ? resultFor(3, 0.8, { lineDigest: `sha256:${"f".repeat(64)}` }) : resultFor(1, 0));
    const html = await render();
    expect(html).toContain("요청한 선과 일치하지 않아");
    expect(html).not.toContain('data-series="cur"');
  });

  it("결과의 자료가 요청한 날짜의 자료와 다르면 표시하지 않는다", async () => {
    mocked.result.mockImplementation(async (_s: string, _a: string, id: string) =>
      id === jobId(3) ? resultFor(3, 0.8, { assetRef: asset(9) }) : resultFor(1, 0));
    const html = await render();
    expect(html).toContain("요청한 선과 일치하지 않아");
    expect(html).not.toContain('data-series="cur"');
  });

  it("실패한 날짜는 이유를 업무 말로 알린다", async () => {
    mocked.jobs.mockResolvedValueOnce({ items: [job(1), job(3), job(2, { executionState: "FAILED", availability: "UNAVAILABLE", reason: "LINE_OUTSIDE_SURFACE" })] });
    mocked.catalog.mockResolvedValueOnce({ siteId: "site-1", workAreaId: "area-1", assets: [
      { assetRef: asset(2), kind: "dsm", declared: { captureDate: "2026-06-02", captureStartedAt: null } },
      { assetRef: asset(1), kind: "dsm", declared: { captureDate: "2026-03-14", captureStartedAt: null } },
      { assetRef: asset(3), kind: "dsm", declared: { captureDate: "2026-11-02", captureStartedAt: null } },
    ], nextCursor: null, hasMore: false });
    const html = await render();
    expect(html).toContain("2026-06-02");
    expect(html).toContain("이 선이 등록된 범위에 닿지 않았습니다");
  });

  it("선을 고치기 전 개정의 결과는 섞지 않고 개수만 알린다", async () => {
    const old = job(2, { feature: { featureId: FEATURE_ID, revision: 1, lineDigest: `sha256:${"b".repeat(64)}` } });
    mocked.jobs.mockResolvedValueOnce({ items: [old, job(3), job(1)] });
    const html = await render();
    expect(html).toContain("고치기 전 개정의 결과 1건은 이 화면에서 제외했습니다");
    expect(mocked.result).not.toHaveBeenCalledWith("site-1", "area-1", jobId(2));
  });

  it("geometry digest가 같아도 다른 저장 선 개정의 결과는 선택하지 않는다", async () => {
    const old = job(2, { feature: { featureId: FEATURE_ID, revision: 1, lineDigest: DIGEST } });
    mocked.jobs.mockResolvedValueOnce({ items: [old, job(3), job(1)] });
    const html = await render({ workAreaId: "area-1", ref: old.jobId });
    expect(html).toContain("고치기 전 개정의 결과 1건은 이 화면에서 제외했습니다");
    expect(mocked.result).not.toHaveBeenCalledWith("site-1", "area-1", old.jobId);
    expect(mocked.result).toHaveBeenCalledWith("site-1", "area-1", jobId(1));
    expect(mocked.result).toHaveBeenCalledWith("site-1", "area-1", jobId(3));
  });

  it("다른 작업구역의 작업은 걸러낸다", async () => {
    mocked.jobs.mockResolvedValueOnce({ items: [job(3, { workAreaId: "area-9" }), job(1)] });
    await render();
    expect(mocked.result).not.toHaveBeenCalledWith("site-1", "area-1", jobId(3));
  });

  it("읽기 권한이 없으면 Core를 부르지 않는다", async () => {
    mocked.session.mockResolvedValue({ kind: "ready", principal: { principalId: "p", organizationId: "o", kind: "OPERATOR", role: "VIEWER", permissions: ["SITES_READ"] } });
    const html = await render();
    expect(html).toContain("볼 권한이 없습니다");
    expect(mocked.areas).not.toHaveBeenCalled();
    expect(mocked.features).not.toHaveBeenCalled();
  });

  it("주소 값이 여럿이면 거부한다", async () => {
    const html = await render({ workAreaId: ["a", "b"] });
    expect(html).toContain("올바르지 않습니다");
    expect(mocked.features).not.toHaveBeenCalled();
  });

  it("모르는 작업구역은 선택지를 다시 보여 준다", async () => {
    const html = await render({ workAreaId: "other" });
    expect(html).toContain("작업구역을 확인할 수 없거나");
    expect(mocked.features).not.toHaveBeenCalled();
  });

  it("주소의 날짜 값은 형식이 맞는 것만 따른다", async () => {
    await render({ workAreaId: "area-1", ref: "not-a-job", cur: "<script>" });
    expect(mocked.result).toHaveBeenCalledWith("site-1", "area-1", jobId(1));
    expect(mocked.result).toHaveBeenCalledWith("site-1", "area-1", jobId(3));
  });
});
