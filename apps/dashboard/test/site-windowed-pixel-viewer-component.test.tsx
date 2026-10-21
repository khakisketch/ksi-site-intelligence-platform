/** @vitest-environment jsdom */
import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("geotiff", () => ({
  fromArrayBuffer: vi.fn(),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import { fromArrayBuffer } from "geotiff";
import {
  SiteWindowedPixelCompare,
  SiteWindowedPixelViewer,
  type WindowedPixelViewerProps,
} from "@/app/sites/[siteId]/SiteWindowedPixelViewer";
import type { PreparedWindowJob, WindowedViewerLayer } from "@/lib/site-windowed-pixel-viewer";

const fromArrayBufferMock = fromArrayBuffer as unknown as ReturnType<typeof vi.fn>;
const digestOf = (bytes: Uint8Array): string => `sha256:${bytesToHex(sha256(bytes))}`;
const assetRef = `ksa-v1-${"b".repeat(64)}`;
const dsmRef = `ksa-v1-${"d".repeat(64)}`;

/** 작은 합성 격자 — 1022×915, 북위, EPSG:7850(비-WGS84 평면). */
const grid = { transform: [1, 0, 0, 0, -1, 512], width: 1022, height: 915 };

function layer(overrides: Partial<WindowedViewerLayer> = {}): WindowedViewerLayer {
  return {
    assetRef,
    observationEpochId: "epoch-2021",
    kind: "ortho",
    kindLabel: "정사영상",
    isDsm: false,
    fileName: "floreat_2021_ortho.tif",
    revision: 2,
    submissionRef: "sub-1",
    inspectedRaster: { ...grid },
    observedCrsIdentifier: "EPSG:7850",
    observedCrsDigest: `sha256:${"c".repeat(64)}`,
    inspectionOutcome: "MEASURED",
    verticalReference: null,
    ...overrides,
  };
}

const dsmLayer: WindowedViewerLayer = {
  ...layer({ assetRef: dsmRef, kind: "dsm", kindLabel: "지표면 높이 자료(DSM)", isDsm: true, fileName: "floreat_2021_dsm.tif", inspectionOutcome: "MEASURED", verticalReference: "확인 불가" }),
};

function receiptFor(jobId: string, ref: string, pixelWindow: [number, number, number, number]) {
  return {
    jobId,
    receiptDigest: null,
    artifactKind: "ortho" as const,
    outputSizeBytes: 4,
    outputSha256: digestOf(new Uint8Array([7, 7, 7, 7])),
    requestedBounds: [0, 0, 2, 2] as [number, number, number, number],
    actualBounds: [0, 0, 2, 2] as [number, number, number, number],
    pixelWindow,
    width: 2,
    height: 2,
    observedCrsIdentifier: "EPSG:7850",
    observedCrsDigest: `sha256:${"c".repeat(64)}`,
    accuracyAssessed: false as const,
    attribution: "attr",
    modificationNotice: "mod",
    limitations: [],
    preparedAt: "2026-10-21T00:00:00Z",
  };
}

function jobsFor(): PreparedWindowJob[] {
  return [
    {
      jobId: "sdj-v1-00000000-0000-0000-0000-000000000011",
      assetRef,
      executionState: "COMPLETED",
      availability: "AVAILABLE",
      createdAt: "2026-10-21T00:00:00Z",
      receipt: receiptFor("sdj-v1-00000000-0000-0000-0000-000000000011", assetRef, [0, 0, 512, 512]),
    },
    {
      jobId: "sdj-v1-00000000-0000-0000-0000-000000000022",
      assetRef,
      executionState: "RUNNING",
      availability: "NOT_READY",
      createdAt: "2026-10-21T00:00:00Z",
      receipt: null,
    },
  ];
}

function propsFor(overrides: Partial<WindowedPixelViewerProps> = {}): WindowedPixelViewerProps {
  return {
    siteId: "site-1",
    workAreaId: "area-1",
    layers: [layer(), dsmLayer],
    jobs: jobsFor(),
    jobsState: "ready",
    canRead: true,
    canRequest: true,
    requestsHref: "/sites/site-1/spatial-data-requests?workAreaId=area-1",
    workAreaRing: [[0, 0], [2, 0], [2, 2], [0, 2]],
    workAreaCrs: "EPSG:7850",
    observationHeading: "정사영상 · 2021 포착 (날짜만 확인 · 시각 미상) · 등록 버전 2",
    idPrefix: "windowed-test",
    ...overrides,
  };
}

function stubCanvas() {
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    putImageData: vi.fn(),
    clearRect: vi.fn(),
    drawImage: vi.fn(),
    imageSmoothingEnabled: true,
  } as unknown as CanvasRenderingContext2D);
  vi.stubGlobal("ImageData", class {
    constructor(
      public readonly data: Uint8ClampedArray,
      public readonly width: number,
      public readonly height: number,
    ) {}
  });
}

function stubGeotiffRgb() {
  fromArrayBufferMock.mockResolvedValue({
    getImageCount: async () => 1,
    getImage: async () => ({
      getWidth: () => 2,
      getHeight: () => 2,
      getSamplesPerPixel: () => 3,
      getBitsPerSample: () => 8,
      getGDALNoData: () => null,
      readRasters: async () => new Uint8Array([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255]),
    }),
  });
}

function stubGeotiffSingleBand() {
  fromArrayBufferMock.mockResolvedValue({
    getImageCount: async () => 1,
    getImage: async () => ({
      getWidth: () => 2,
      getHeight: () => 2,
      getSamplesPerPixel: () => 1,
      getBitsPerSample: () => 32,
      getGDALNoData: () => -9999,
      readRasters: async () => new Float32Array([10, 20, 30, 40]),
    }),
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  fromArrayBufferMock.mockReset();
});

describe("site windowed pixel viewer", () => {
  it("renders the adapter frame without fetching or preparing on entry", () => {
    const fetchMock = vi.fn(async () => new Response(new Uint8Array([7, 7, 7, 7]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<SiteWindowedPixelViewer {...propsFor()} />);

    expect(screen.getByText("임시 시각화 어댑터 · 실제 파일의 준비된 창")).toBeTruthy();
    expect(screen.getByText(/이 화면은 감사 판정을 하지 않습니다/)).toBeTruthy();
    expect(screen.getByText(/볼 수 있다는 뜻이 쓸 수 있다는 뜻이 아닙니다/)).toBeTruthy();
    expect(screen.getByText(/그릴 수 있는지만 말합니다/)).toBeTruthy();
    expect(screen.getByText(/종합 판정.*두지 않습니다/)).toBeTruthy();
    expect(screen.getByText("이미 준비된 창 보기")).toBeTruthy();
    expect(screen.getByText("이 구역의 창 준비 요청")).toBeTruthy();
    // 진입 시 쓰기·읽기 모두 나가지 않는다.
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByText(/검증 완료/)).toBeNull();
  });

  it("paints a SHA-verified window in the native plane without geographic claims", async () => {
    stubCanvas();
    stubGeotiffRgb();
    const calls: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return new Response(new Uint8Array([7, 7, 7, 7]), { status: 200, headers: { "content-type": "image/tiff" } });
    }));
    render(<SiteWindowedPixelViewer {...propsFor()} />);

    fireEvent.click(screen.getAllByRole("button", { name: "이 창 보기" })[0]!);
    await screen.findByText(/실제 파일 · 준비된 창 · 2 × 2 픽셀/);
    expect(screen.getByText(/EPSG:7850 · \[0, 0, 2, 2\]/)).toBeTruthy();
    expect(screen.getByText(/지도 재투영이 아닙니다/)).toBeTruthy();
    expect(screen.getByText(/같은 좌표 평면의 작업구역 경계/)).toBeTruthy();
    // 한 창 보기와 이어 보기 모두 표시용임을 밝힌다 — 같은 문구가 두 자리에 있다.
    expect(screen.getByText(/확대·이동은 화면 표시용이며 측정값이 아닙니다/)).toBeTruthy();
    expect(screen.getByText(/이 보기의 이동·확대는 화면 표시용이며 측정값이 아닙니다/)).toBeTruthy();
    // 같은 출처 상대 경로로만 읽는다 — 외부 타일·절대 URL이 없다.
    expect(calls.length).toBeGreaterThan(0);
    for (const call of calls) expect(call.url.startsWith("/api/")).toBe(true);
  });

  it("refuses bytes that fail the size and hash gates", async () => {
    stubCanvas();
    stubGeotiffRgb();
    vi.stubGlobal("fetch", vi.fn(async () => (
      new Response(new Uint8Array([9, 9]), { status: 200, headers: { "content-type": "image/tiff" } })
    )));
    render(<SiteWindowedPixelViewer {...propsFor()} />);

    fireEvent.click(screen.getAllByRole("button", { name: "이 창 보기" })[0]!);
    await screen.findByText(/받은 바이트가 Core 준비 기록.*달라/);
  });

  it("maps a foreign or expired window to one message without existence disclosure", async () => {
    stubCanvas();
    stubGeotiffRgb();
    for (const status of [403, 404]) {
      cleanup();
      vi.stubGlobal("fetch", vi.fn(async () => (
        new Response(JSON.stringify({ code: "NOT_FOUND" }), { status, headers: { "content-type": "application/json" } })
      )));
      render(<SiteWindowedPixelViewer {...propsFor()} />);
      fireEvent.click(screen.getAllByRole("button", { name: "이 창 보기" })[0]!);
      await screen.findByText(/다른 계정이 준비한 창은 이 화면에서 열 수 없습니다/);
      cleanup();
    }
  });

  it("shows DSM as relative shading with per-window stretch honesty", async () => {
    stubCanvas();
    stubGeotiffSingleBand();
    const dsmReceipt = {
      ...receiptFor("sdj-v1-00000000-0000-0000-0000-000000000033", dsmRef, [0, 0, 2, 2]),
      artifactKind: "dsm" as const,
    };
    vi.stubGlobal("fetch", vi.fn(async () => (
      new Response(new Uint8Array([7, 7, 7, 7]), { status: 200, headers: { "content-type": "image/tiff" } })
    )));
    render(<SiteWindowedPixelViewer {...propsFor({
      jobs: [{
        jobId: "sdj-v1-00000000-0000-0000-0000-000000000033",
        assetRef: dsmRef,
        executionState: "COMPLETED",
        availability: "AVAILABLE",
        createdAt: "2026-10-21T00:00:00Z",
        receipt: dsmReceipt,
      }],
    })} />);

    fireEvent.click(screen.getByRole("button", { name: "지표면 높이 자료(DSM)" }));
    fireEvent.click(screen.getByRole("button", { name: "이 창 보기" }));
    await screen.findByText(/화면용 상대 음영/);
    expect(screen.getByText("어두움 — 밝음 · 상대 음영이며 측정값이 아님")).toBeTruthy();
    // 창별 늘이기 정직 문구는 한 창 보기와 이어 보기 모두에 그대로 있다.
    expect(screen.getAllByText(/창이 다르면 밝기가 달라도 높이 차이로 읽지 마세요/)).toHaveLength(2);
    expect(screen.queryByText(/검증 완료/)).toBeNull();
  });

  it("moves to the adjacent window draft and posts one bounded PREPARE", async () => {
    stubCanvas();
    const posts: Array<{ url: string; body: Record<string, unknown>; key: string | null }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      const headers = new Headers(init?.headers);
      posts.push({ url, body, key: headers.get("Idempotency-Key") });
      return new Response(
        JSON.stringify({ jobId: "sdj-v1-00000000-0000-0000-0000-000000000044", executionState: "QUEUED" }),
        { status: 201, headers: { "content-type": "application/json" } },
      );
    }));
    render(<SiteWindowedPixelViewer {...propsFor({ layers: [layer()] })} />);

    // 가운데 초안(원점 255, 201)에서 오른쪽 이웃으로 — 격자 끝 510에 고정.
    fireEvent.click(screen.getByRole("button", { name: "이웃 창 →" }));
    expect((screen.getByLabelText(/원점 열/) as HTMLInputElement).value).toBe("510");
    expect(screen.getByText(/이웃 창으로 초안을 옮겼습니다/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "받기 요청 만들기" }));
    await screen.findByText(/받기 요청을 만들었습니다/);
    expect(posts).toHaveLength(1);
    expect(posts[0]!.url).toBe("/api/sites/site-1/work-areas/area-1/spatial-data-requests");
    expect(posts[0]!.body.assetRef).toBe(assetRef);
    expect(posts[0]!.body.resolutionMode).toBe("NATIVE");
    expect(posts[0]!.body.purpose).toBe("GENERAL_DATA_USE");
    expect(posts[0]!.body.requestedBounds).toEqual([510, -201, 1022, 311]);
    expect(typeof posts[0]!.key).toBe("string");
  });

  it("shows the honest unavailable state for a reader who may not prepare", () => {
    const fetchMock = vi.fn(async () => new Response(new Uint8Array([7, 7, 7, 7]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<SiteWindowedPixelViewer {...propsFor({ canRequest: false })} />);
    // 권한 없음 트리거만 보인다 — 사유는 눌러야 열리는 팝오버에 있다(기존 동작).
    expect(screen.getByRole("button", { name: "이 구역의 창 준비 요청" })).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the honest unavailable state for a viewer who may not read", () => {
    const fetchMock = vi.fn(async () => new Response(new Uint8Array([7, 7, 7, 7]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<SiteWindowedPixelViewer {...propsFor({ canRead: false })} />);
    expect(screen.getByRole("button", { name: "이미 준비된 창 보기" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "이 창 보기" })).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps denied and unavailable job lists separate from empty", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(new Uint8Array([7, 7, 7, 7]), { status: 200 })));
    const { unmount } = render(<SiteWindowedPixelViewer {...propsFor({ jobsState: "denied" })} />);
    expect(screen.getByText(/조회할 권한이 없습니다/)).toBeTruthy();
    unmount();
    render(<SiteWindowedPixelViewer {...propsFor({ jobsState: "unavailable" })} />);
    expect(screen.getByText(/불러오지 못했습니다. 잠시 후 다시 확인하세요/)).toBeTruthy();
  });
});

describe("site windowed pixel compare", () => {
  it("warns honestly when the two epochs share no display plane", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(new Uint8Array([7, 7, 7, 7]), { status: 200 })));
    render(
      <SiteWindowedPixelCompare
        siteId="site-1"
        workAreaId="area-1"
        baselineHeading="기준"
        currentHeading="비교"
        baselineLayers={[]}
        currentLayers={[]}
        baselineCrs="EPSG:7850"
        currentCrs="EPSG:5186"
        jobs={[]}
        jobsState="ready"
        canRead
        canRequest={false}
        requestsHref="/sites/site-1/spatial-data-requests?workAreaId=area-1"
        workAreaRing={null}
        workAreaCrs="EPSG:7850"
      />,
    );
    expect(screen.getByText(/위치 기준이 달라 동기화된 공간 비교를 하지 않습니다/)).toBeTruthy();
    expect(screen.getByText(/그 창 안에서만 늘이기한 상대 음영/)).toBeTruthy();
  });

  it("co-locates two panes on the shared plane without claiming alignment", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(new Uint8Array([7, 7, 7, 7]), { status: 200 })));
    render(
      <SiteWindowedPixelCompare
        siteId="site-1"
        workAreaId="area-1"
        baselineHeading="기준"
        currentHeading="비교"
        baselineLayers={[]}
        currentLayers={[]}
        baselineCrs="EPSG:7850"
        currentCrs="EPSG:7850"
        jobs={[]}
        jobsState="ready"
        canRead
        canRequest={false}
        requestsHref="/sites/site-1/spatial-data-requests?workAreaId=area-1"
        workAreaRing={null}
        workAreaCrs="EPSG:7850"
      />,
    );
    expect(screen.getByText(/동기화된 공간 비교.*지원하지 않습니다/)).toBeTruthy();
    expect(screen.getByText(/화면을 겹쳐도 분석 근거가 되지 않습니다/)).toBeTruthy();
  });
});
