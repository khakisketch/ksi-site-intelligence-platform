import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ session: vi.fn(), site: vi.fn(), areas: vi.fn(), features: vi.fn(), source: vi.fn(), loginReturn: vi.fn() }));
const captured = vi.hoisted(() => ({ props: null as Record<string, unknown> | null, blockedNext: null as string | null }));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) => createElement("a", { href, ...props }, children),
}));
vi.mock("next/navigation", () => ({ notFound: () => { throw new Error("NEXT_NOT_FOUND"); }, useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/app/field/resolve-session", () => ({ resolveFieldSession: mocked.session }));
vi.mock("@/app/field/OperationsSessionFailure", () => ({ OperationsSessionFailure: ({ next }: { next: string }) => { captured.blockedNext = next; return createElement("p", null, "로그인 필요"); } }));
vi.mock("@/app/sites/[siteId]/SiteHeader", () => ({ SiteHeader: () => createElement("header", null, "현장 머리") }));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/measurement", () => ({ listMeasurementFeatures: mocked.features }));
vi.mock("@/lib/measurement-source", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/measurement-source")>();
  return { ...actual, getMeasurementSource: mocked.source, measurementLoginReturn: mocked.loginReturn };
});
vi.mock("@/components/ui/ErrorState", () => ({
  ErrorState: ({ message }: { message: string }) => createElement("div", { role: "alert" }, message),
}));
vi.mock("@/lib/core-api/client", () => ({
  CoreApiError: class CoreApiError extends Error { constructor(readonly status: number, body?: unknown) { super(`Core ${status}`); void body; } },
}));
vi.mock("@/app/sites/[siteId]/measurements/new/LineEditor", () => ({
  LineEditor: (props: Record<string, unknown>) => { captured.props = props; return createElement("div", { "data-testid": "editor" }); },
}));

import NewMeasurementLinePage from "@/app/sites/[siteId]/measurements/new/page";
import { CoreApiError } from "@/lib/core-api/client";

const DIGEST = `sha256:${"a".repeat(64)}`;
const FEATURE_ID = `mf-${"1".repeat(32)}`;
const ASSET_REF = `ksa-v1-${"b".repeat(64)}`;
const geoArea = { workAreaId: "area-1", siteId: "site-1", name: "북측 작업구역", status: "ACTIVE", crs: "EPSG:4326", polygon: { type: "Polygon", coordinates: [[[127, 37], [127.01, 37], [127.01, 37.01], [127, 37.01], [127, 37]]] } };
const feature = (crs: string, vertices: number[][]) => ({
  featureId: FEATURE_ID, siteId: "site-1", workAreaId: "area-1", revision: 3, name: "북쪽 경사면", kind: "LINE", line: { crs, vertices }, lineDigest: DIGEST, createdAt: "2026-11-01T00:00:00Z",
});
const call = async (query: Record<string, string | string[] | undefined> = { workAreaId: "area-1" }) =>
  renderToStaticMarkup(await NewMeasurementLinePage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve(query) }));

beforeEach(() => {
  vi.resetAllMocks();
  captured.props = null;
  captured.blockedNext = null;
  mocked.loginReturn.mockReturnValue("/sites/site-1/measurements/new?workAreaId=area-1&featureId=mf-safe&assetRef=ksa-v1-safe");
  mocked.session.mockResolvedValue({ kind: "ready", principal: { principalId: "u", organizationId: "o", kind: "OPERATOR", role: "ADMIN", permissions: ["SITES_READ", "SITES_WRITE"] } });
  mocked.site.mockResolvedValue({ siteId: "site-1", name: "현장", status: "BASELINE_MAPPING" });
  mocked.areas.mockResolvedValue({ workAreas: [geoArea] });
  mocked.features.mockResolvedValue({ features: [feature("EPSG:4326", [[127.001, 37.001], [127.002, 37.002]])] });
  mocked.source.mockResolvedValue(null);
});

describe("측정 선 그리기 화면(서버)", () => {
  it("새 선: 구역 경계를 지도용 닫힌 고리로 넘기고 빈 선으로 연다", async () => {
    const html = await call();
    expect(html).toContain("측정 선 그리기");
    expect(captured.props).toMatchObject({ siteId: "site-1", workAreaId: "area-1", areaName: "북측 작업구역", initialVertices: [], initialName: "", editing: null, convertedFromCrs: null });
    const ring = captured.props!.ring as number[][];
    expect(ring[0]).toEqual([127, 37]);
    expect(ring[ring.length - 1]).toEqual(ring[0]);
    expect(ring).toHaveLength(5);
    expect(mocked.features).not.toHaveBeenCalled();
  });

  it("새 선의 취소 복귀 선택은 유지하지만 초안에는 기존 선을 불러오지 않는다", async () => {
    const ref = `spj-${"1".repeat(32)}`;
    const cur = `spj-${"3".repeat(32)}`;
    const html = await call({ workAreaId: "area-1", feature: FEATURE_ID, ref, cur, comparison: "saved-decision" });
    expect(html).toContain("측정 선 그리기");
    expect(captured.props).toMatchObject({
      initialVertices: [], initialName: "", editing: null,
      returnHref: `/sites/site-1/measurements?workAreaId=area-1&feature=${FEATURE_ID}&ref=${ref}&cur=${cur}&comparison=saved-decision`,
    });
    expect(mocked.features).not.toHaveBeenCalled();
  });

  it("복귀 주소의 잘못된 선택은 원문 없이 오류 표식으로 고정 경로에 남긴다", async () => {
    const html = await call({ workAreaId: "area-1", feature: "../other-site", ref: ["untrusted"], cur: "bad-job" });
    expect(html).toContain("측정 선 그리기");
    expect(captured.props!.returnHref).toBe("/sites/site-1/measurements?workAreaId=area-1&feature=invalid&ref=invalid&cur=invalid");
    expect(captured.props!.returnHref).not.toContain("other-site");
    expect(captured.props!.returnHref).not.toContain("untrusted");
  });

  it("선택한 DSM의 검사 격자와 촬영일을 편집기에 전달하고 주소를 보존한다", async () => {
    mocked.source.mockResolvedValue({
      assetRef: ASSET_REF,
      siteId: "site-1",
      workAreaId: "area-1",
      kind: "dsm",
      lifecycleState: "SEALED",
      declared: { fileName: "Bonggil_2020_autumn.tif", captureDate: "2020-10-20", captureStartedAt: null },
      inspection: { raster: { observedCrsIdentifier: "EPSG:4326", footprintWkt: "POLYGON ((127.001 37.001, 127.004 37.001, 127.004 37.004, 127.001 37.004, 127.001 37.001))" } },
    });
    await call({ workAreaId: "area-1", assetRef: ASSET_REF });
    expect(mocked.source).toHaveBeenCalledWith("site-1", "area-1", ASSET_REF);
    expect(captured.props).toMatchObject({
      source: { assetRef: ASSET_REF, fileName: "Bonggil_2020_autumn.tif", captureDate: "2020-10-20" },
      focusRing: [[127.001, 37.001], [127.004, 37.001], [127.004, 37.004], [127.001, 37.004]],
      returnHref: `/sites/site-1/measurements?workAreaId=area-1&assetRef=${ASSET_REF}`,
    });
  });

  it("자료 주소가 잘못됐으면 Core에서 자산을 읽지 않는다", async () => {
    expect(await call({ workAreaId: "area-1", assetRef: "invalid" })).toContain("자료의 주소가 올바르지 않습니다");
    expect(mocked.source).not.toHaveBeenCalled();
  });

  it("선택한 자료가 더 이상 유효한 DSM이 아니면 일반 선으로 자동 전환하지 않는다", async () => {
    const html = await call({ workAreaId: "area-1", assetRef: ASSET_REF });
    expect(html).toContain("검사된 DSM이 아니거나");
    expect(captured.props).toBeNull();
  });

  it("쓰기 권한이 없으면 편집기를 열지 않는다", async () => {
    mocked.session.mockResolvedValue({ kind: "ready", principal: { principalId: "u", organizationId: "o", kind: "OPERATOR", role: "VIEWER", permissions: ["SITES_READ"] } });
    const html = await call();
    expect(html).toContain("저장할 권한이 없습니다");
    expect(captured.props).toBeNull();
    expect(mocked.areas).not.toHaveBeenCalled();
  });

  it("로그인이 필요할 때 정해진 내부 편집 주소와 선택을 보존할 helper에 넘긴다", async () => {
    const query = { workAreaId: "area-1", featureId: FEATURE_ID, assetRef: ASSET_REF };
    mocked.session.mockResolvedValue({ kind: "blocked", verdict: { kind: "login", message: "로그인이 필요합니다" } });
    expect(await call(query)).toContain("로그인 필요");
    expect(mocked.loginReturn).toHaveBeenCalledWith("site-1", true, query);
    expect(captured.blockedNext).toBe("/sites/site-1/measurements/new?workAreaId=area-1&featureId=mf-safe&assetRef=ksa-v1-safe");
    expect(mocked.site).not.toHaveBeenCalled();
  });

  it.each([
    ["구역을 고르지 않음", {}],
    ["구역이 배열", { workAreaId: ["a", "b"] }],
  ])("주소가 올바르지 않으면 열지 않는다: %s", async (_name, query) => {
    const html = await call(query as Record<string, string | string[] | undefined>);
    expect(captured.props).toBeNull();
    expect(html).toMatch(/작업구역을 먼저 선택하세요/);
  });

  it("없는 구역이거나 다른 현장의 구역이면 열지 않는다", async () => {
    expect(await call({ workAreaId: "area-9" })).toContain("작업구역을 확인할 수 없거나");
    mocked.areas.mockResolvedValue({ workAreas: [{ ...geoArea, siteId: "site-2" }] });
    expect(await call()).toContain("작업구역을 확인할 수 없거나");
    expect(captured.props).toBeNull();
  });

  it("보관된 구역에는 저장할 수 없다고 말한다", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [{ ...geoArea, status: "ARCHIVED" }] });
    expect(await call()).toContain("보관된 작업구역에는 측정 선을 저장할 수 없습니다");
    expect(captured.props).toBeNull();
  });

  it("구역 모양을 지도에 올릴 수 없으면 경계 없이 연다(안에 있다고 하지 않는다)", async () => {
    mocked.areas.mockResolvedValue({ workAreas: [{ ...geoArea, crs: "EPSG:5174" }] });
    await call();
    expect(captured.props!.ring).toBeNull();
  });

  it("고치기: 저장된 개정의 선·이름·번호를 넘긴다", async () => {
    const html = await call({ workAreaId: "area-1", featureId: FEATURE_ID });
    expect(html).toContain("측정 선 고치기");
    expect(captured.props).toMatchObject({ initialName: "북쪽 경사면", editing: { featureId: FEATURE_ID, revision: 3 }, convertedFromCrs: null, initialVertices: [[127.001, 37.001], [127.002, 37.002]] });
  });

  it("한국 투영좌표계로 저장된 선은 경위도로 바꿔 넘기고 그 사실을 알린다", async () => {
    mocked.features.mockResolvedValue({ features: [feature("EPSG:5186", [[200000, 600000], [200100, 600000]])] });
    await call({ workAreaId: "area-1", featureId: FEATURE_ID });
    expect(captured.props!.convertedFromCrs).toBe("EPSG:5186");
    const [first, second] = captured.props!.initialVertices as number[][];
    // 중부원점 원점(경도 127, 위도 38)에서 동쪽으로 100 m
    expect(first![0]).toBeCloseTo(127, 4);
    expect(first![1]).toBeCloseTo(38, 4);
    expect(second![0]).toBeGreaterThan(first![0]!);
    expect(second![0]! - first![0]!).toBeLessThan(0.002);
  });

  it("모르는 좌표계의 선은 고칠 수 없다고 말한다", async () => {
    mocked.features.mockResolvedValue({ features: [feature("EPSG:32617", [[500000, 4000000], [500100, 4000000]])] });
    expect(await call({ workAreaId: "area-1", featureId: FEATURE_ID })).toContain("고칠 수 없습니다");
    expect(captured.props).toBeNull();
  });

  it("다른 구역의 선이거나 없는 선이면 열지 않는다", async () => {
    mocked.features.mockResolvedValue({ features: [{ ...feature("EPSG:4326", [[127, 37], [127.1, 37]]), workAreaId: "area-2" }] });
    expect(await call({ workAreaId: "area-1", featureId: FEATURE_ID })).toContain("고칠 선을 찾을 수 없습니다");
    expect(captured.props).toBeNull();
  });

  it("선 주소 형식이 틀리면 Core를 읽지 않는다", async () => {
    expect(await call({ workAreaId: "area-1", featureId: "x" })).toContain("주소가 올바르지 않습니다");
    expect(mocked.features).not.toHaveBeenCalled();
  });

  it("선을 읽지 못하면 새 선으로 위장하지 않는다", async () => {
    mocked.features.mockRejectedValue(new CoreApiError(503, {}));
    expect(await call({ workAreaId: "area-1", featureId: FEATURE_ID })).toContain("고칠 선을 불러오지 못했습니다");
    expect(captured.props).toBeNull();
  });
});
