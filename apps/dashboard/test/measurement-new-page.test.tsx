import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ session: vi.fn(), site: vi.fn(), areas: vi.fn(), features: vi.fn() }));
const captured = vi.hoisted(() => ({ props: null as Record<string, unknown> | null }));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) => createElement("a", { href, ...props }, children),
}));
vi.mock("next/navigation", () => ({ notFound: () => { throw new Error("NEXT_NOT_FOUND"); }, useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/app/field/resolve-session", () => ({ resolveFieldSession: mocked.session }));
vi.mock("@/app/field/OperationsSessionFailure", () => ({ OperationsSessionFailure: () => createElement("p", null, "로그인 필요") }));
vi.mock("@/app/sites/[siteId]/SiteHeader", () => ({ SiteHeader: () => createElement("header", null, "현장 머리") }));
vi.mock("@/lib/core-api/sites", () => ({ getSite: mocked.site }));
vi.mock("@/lib/core-api/workAreas", () => ({ listWorkAreas: mocked.areas }));
vi.mock("@/lib/core-api/measurement", () => ({ listMeasurementFeatures: mocked.features }));
vi.mock("@/components/ui/ErrorState", () => ({
  ErrorState: ({ message }: { message: string }) => createElement("div", { role: "alert" }, message),
}));
vi.mock("@/lib/core-api/client", () => ({
  CoreApiError: class CoreApiError extends Error { constructor(readonly status: number, _body?: unknown) { super(`Core ${status}`); } },
}));
vi.mock("@/app/sites/[siteId]/measurements/new/LineEditor", () => ({
  LineEditor: (props: Record<string, unknown>) => { captured.props = props; return createElement("div", { "data-testid": "editor" }); },
}));

import NewMeasurementLinePage from "@/app/sites/[siteId]/measurements/new/page";
import { CoreApiError } from "@/lib/core-api/client";

const DIGEST = `sha256:${"a".repeat(64)}`;
const FEATURE_ID = `mf-${"1".repeat(32)}`;
const geoArea = { workAreaId: "area-1", siteId: "site-1", name: "북측 작업구역", status: "ACTIVE", crs: "EPSG:4326", polygon: { type: "Polygon", coordinates: [[[127, 37], [127.01, 37], [127.01, 37.01], [127, 37.01], [127, 37]]] } };
const feature = (crs: string, vertices: number[][]) => ({
  featureId: FEATURE_ID, siteId: "site-1", workAreaId: "area-1", revision: 3, name: "북쪽 경사면", kind: "LINE", line: { crs, vertices }, lineDigest: DIGEST, createdAt: "2026-11-01T00:00:00Z",
});
const call = async (query: Record<string, string | string[] | undefined> = { workAreaId: "area-1" }) =>
  renderToStaticMarkup(await NewMeasurementLinePage({ params: Promise.resolve({ siteId: "site-1" }), searchParams: Promise.resolve(query) }));

beforeEach(() => {
  vi.resetAllMocks();
  captured.props = null;
  mocked.session.mockResolvedValue({ kind: "ready", principal: { principalId: "u", organizationId: "o", kind: "OPERATOR", role: "ADMIN", permissions: ["SITES_READ", "SITES_WRITE"] } });
  mocked.site.mockResolvedValue({ siteId: "site-1", name: "현장", status: "BASELINE_MAPPING" });
  mocked.areas.mockResolvedValue({ workAreas: [geoArea] });
  mocked.features.mockResolvedValue({ features: [feature("EPSG:4326", [[127.001, 37.001], [127.002, 37.002]])] });
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

  it("쓰기 권한이 없으면 편집기를 열지 않는다", async () => {
    mocked.session.mockResolvedValue({ kind: "ready", principal: { principalId: "u", organizationId: "o", kind: "OPERATOR", role: "VIEWER", permissions: ["SITES_READ"] } });
    const html = await call();
    expect(html).toContain("저장할 권한이 없습니다");
    expect(captured.props).toBeNull();
    expect(mocked.areas).not.toHaveBeenCalled();
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
    mocked.features.mockResolvedValue({ features: [feature("EPSG:32652", [[500000, 4000000], [500100, 4000000]])] });
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
