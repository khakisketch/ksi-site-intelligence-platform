import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
  site: vi.fn(),
  areas: vi.fn(),
  list: vi.fn(),
  detail: vi.fn(),
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
vi.mock("@/lib/core-api/spatial-data-requests", () => ({
  listSpatialDataRequests: mocked.list,
  getSpatialDataRequest: mocked.detail,
  isSpatialDataExecutionState: (value: unknown) => ["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELED", "EXPIRED"].includes(String(value)),
  isSpatialDataAvailability: (value: unknown) => ["NOT_READY", "AVAILABLE", "ACCESS_REVOKED", "ACCESS_EXPIRED", "RETENTION_EXPIRED", "UNAVAILABLE"].includes(String(value)),
}));
vi.mock("@/app/field/OperationsSessionFailure", () => ({
  OperationsSessionFailure: ({ verdict }: { verdict: { notice?: string } }) => createElement("p", null, verdict.notice ?? "로그인 필요"),
}));
vi.mock("@/components/ui/ErrorState", () => ({
  ErrorState: ({ message, detail }: { message: string; detail?: string }) => createElement("div", { role: "alert" }, `${message} ${detail ?? ""}`),
}));
vi.mock("@/lib/core-api/client", () => ({
  CoreApiError: class CoreApiError extends Error {
    constructor(readonly status: number, _body: unknown, readonly retryAfterSeconds?: number) { super(`Core ${status}`); }
  },
}));

import SpatialDataRequestsPage from "@/app/sites/[siteId]/spatial-data-requests/page";

const requestId = "sdj-v1-12345678-1234-1234-1234-123456789abc";
const area = { workAreaId: "area-1", name: "북측 작업구역", status: "ACTIVE" };
const digest = (value: string) => `sha256:${value.repeat(64)}`;

function receipt(jobId = requestId) {
  return {
    jobId,
    receiptDigest: digest("a"),
    artifactKind: "dsm",
    outputSizeBytes: 9_166_428,
    outputSha256: digest("b"),
    requestedBounds: [500000, 7100000, 501000, 7101000],
    actualBounds: [500010, 7100010, 500990, 7100990],
    pixelWindow: [20, 30, 2000, 2000],
    width: 2000,
    height: 2000,
    observedCrsIdentifier: "EPSG:7850",
    observedCrsDigest: digest("c"),
    accuracyAssessed: false,
    attribution: "KSI prepared from the registered source.",
    modificationNotice: "Windowed crop; no reprojection.",
    limitations: ["Not an accuracy assessment."],
    preparedAt: "2026-10-14T10:40:00Z",
  };
}

function job(overrides: Record<string, unknown> = {}) {
  return {
    jobId: requestId,
    assetRef: `ksa-v1-${"a".repeat(64)}`,
    siteId: "site-1",
    workAreaId: "area-1",
    createdAt: "2026-10-14T10:40:09.335020Z",
    executionState: "COMPLETED",
    availability: "AVAILABLE",
    reason: null,
    receipt: receipt(),
    ...overrides,
  };
}

const callPage = (query: Record<string, string | string[] | undefined> = {}) => SpatialDataRequestsPage({
  params: Promise.resolve({ siteId: "site-1" }),
  searchParams: Promise.resolve(query),
});

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue({ kind: "ready", principal: {
    principalId: "operator-1", organizationId: "org-1", kind: "OPERATOR", role: "ADMIN",
    permissions: ["SITES_READ", "SPATIAL_DATA_READ", "SPATIAL_DATA_REQUEST"],
  } });
  mocked.site.mockResolvedValue({ siteId: "site-1", name: "Floreat 검증 현장" });
  mocked.areas.mockResolvedValue({ workAreas: [area] });
  mocked.list.mockResolvedValue({ items: [job()], nextCursor: null });
  mocked.detail.mockResolvedValue(job());
});

describe("spatial data request Console surface", () => {
  it("mirrors the WorkArea selector and does not fetch jobs until one area is selected", async () => {
    const html = renderToStaticMarkup(await callPage());
    expect(html).toContain("구역 데이터 요청");
    expect(html).toContain("작업구역 선택");
    expect(html).toContain("북측 작업구역");
    expect(mocked.areas).toHaveBeenCalledWith("site-1", { includeArchived: true });
    expect(mocked.list).not.toHaveBeenCalled();
  });

  it("lists state, availability, created time, and the Core reason without inventing a summary", async () => {
    mocked.list.mockResolvedValueOnce({ items: [
      job({ executionState: "FAILED", availability: "NOT_READY", reason: "RASTER_PREPARATION_FAILED", receipt: null }),
      job({ jobId: "sdj-v1-22345678-1234-1234-1234-123456789abc", executionState: "CANCELED", availability: "UNAVAILABLE", reason: "ACTIVATION_UNAVAILABLE", receipt: null }),
    ], nextCursor: null });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(mocked.list).toHaveBeenCalledWith("site-1", "area-1", { limit: 50, cursor: undefined });
    expect(html).toContain(">실패</span>");
    expect(html).toContain("아직 준비되지 않음");
    expect(html).toContain("RASTER_PREPARATION_FAILED");
    expect(html).toContain(">취소됨</span>");
    expect(html).toContain("현재 접근 불가");
    expect(html).toContain("ACTIVATION_UNAVAILABLE");
    expect(html).toContain("2026. 10. 14.");
  });

  it("shows a COMPLETED receipt and download only when the Core receipt and availability agree", async () => {
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", requestId }));
    expect(mocked.detail).toHaveBeenCalledWith("site-1", "area-1", requestId);
    expect(html).toContain("Core 작업 receipt");
    expect(html).toContain("9,166,428 bytes");
    expect(html).toContain(digest("b"));
    expect(html).toContain("픽셀 창 (Core 순서)");
    expect(html).toContain("실제 bounds (Core 순서)");
    expect(html).toContain("EPSG:7850");
    expect(html).toContain("Attribution");
    expect(html).toContain("Modification notice");
    expect(html).toContain("정확도 평가");
    expect(html).toContain(`/api/sites/site-1/work-areas/area-1/spatial-data-requests/${requestId}/file`);
    expect(html).toContain("정확도 평가나 현장 적합성 판정이 아닙니다.");
  });

  it("never renders receipt or download success from a non-COMPLETED state, even if receipt is present", async () => {
    mocked.detail.mockResolvedValueOnce(job({ executionState: "FAILED", availability: "AVAILABLE", reason: "RASTER_PREPARATION_FAILED" }));
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", requestId }));
    expect(html).toContain("FAILED");
    expect(html).toContain("RASTER_PREPARATION_FAILED");
    expect(html).toContain("요청 상태가 COMPLETED가 아니므로 receipt와 파일 결과를 표시하지 않습니다.");
    expect(html).not.toContain("Core 작업 receipt");
    expect(html).not.toContain("준비된 파일 다운로드");
  });

  it("offers cancel only while active and only when the current operator has request permission", async () => {
    mocked.detail.mockResolvedValueOnce(job({ executionState: "RUNNING", availability: "NOT_READY", reason: null, receipt: null }));
    const running = renderToStaticMarkup(await callPage({ workAreaId: "area-1", requestId }));
    expect(running).toContain("요청 취소");
    expect(running).toContain("Core에서 취소할 수 있습니다");
    mocked.detail.mockResolvedValueOnce(job({ executionState: "CANCELED", availability: "UNAVAILABLE", reason: "CANCELED", receipt: null }));
    const canceled = renderToStaticMarkup(await callPage({ workAreaId: "area-1", requestId }));
    expect(canceled).not.toContain("요청 취소</button>");
    expect(canceled).toContain("CANCELED");

    mocked.session.mockResolvedValueOnce({ kind: "ready", principal: {
      principalId: "reader-1", organizationId: "org-1", kind: "OPERATOR", role: "VIEWER", permissions: ["SITES_READ", "SPATIAL_DATA_READ"],
    } });
    mocked.detail.mockResolvedValueOnce(job({ executionState: "RUNNING", availability: "NOT_READY", receipt: null }));
    const noCancelPermission = renderToStaticMarkup(await callPage({ workAreaId: "area-1", requestId }));
    expect(noCancelPermission).not.toContain("요청 취소</button>");
    expect(noCancelPermission).toContain("요청을 취소할 권한이 없습니다");
    expect(noCancelPermission).not.toContain("SPATIAL_DATA_REQUEST");
  });

  it("keeps archived WorkAreas selectable for existing request history", async () => {
    mocked.areas.mockResolvedValueOnce({ workAreas: [area, { workAreaId: "old-area", name: "이전 구역", status: "ARCHIVED" }] });
    mocked.list.mockResolvedValueOnce({ items: [], nextCursor: null });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "old-area" }));
    expect(html).toContain("이전 구역 · 보관됨");
    expect(mocked.list).toHaveBeenCalledWith("site-1", "old-area", { limit: 50, cursor: undefined });
  });

  it("preserves Core cursor paging under the same Site and WorkArea", async () => {
    mocked.list.mockResolvedValueOnce({ items: [job()], nextCursor: "opaque/cursor" });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1", cursor: "current-cursor" }));
    expect(mocked.list).toHaveBeenCalledWith("site-1", "area-1", { limit: 50, cursor: "current-cursor" });
    expect(html).toContain("다음 요청 보기");
    expect(html).toContain("cursor=opaque%2Fcursor");
    expect(html).toContain("처음부터 보기");
  });

  it("keeps an empty Core page distinct from missing permission or a failed query", async () => {
    mocked.list.mockResolvedValueOnce({ items: [], nextCursor: null });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(html).toContain("이 작업구역의 공간 데이터 요청이 없습니다");
    expect(html).not.toContain("조회할 권한이 없습니다");
  });

  it("fails closed when Core returns a request from another WorkArea", async () => {
    mocked.list.mockResolvedValueOnce({ items: [job({ workAreaId: "other-area" })], nextCursor: null });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(html).toContain("다른 항목이 있어 해당 항목을 숨겼습니다");
    expect(html).not.toContain(requestId);
  });

  it("does not call scoped request routes without SPATIAL_DATA_READ", async () => {
    mocked.session.mockResolvedValueOnce({ kind: "ready", principal: {
      principalId: "viewer-1", organizationId: "org-1", kind: "OPERATOR", role: "VIEWER", permissions: ["SITES_READ"],
    } });
    const html = renderToStaticMarkup(await callPage({ workAreaId: "area-1" }));
    expect(html).toContain("공간 데이터 요청을 볼 권한이 없습니다");
    expect(html).not.toContain("SPATIAL_DATA_READ");
    expect(mocked.areas).not.toHaveBeenCalled();
    expect(mocked.list).not.toHaveBeenCalled();
  });
});
