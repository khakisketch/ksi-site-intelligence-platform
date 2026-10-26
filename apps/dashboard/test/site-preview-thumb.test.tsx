/** @vitest-environment jsdom */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("geotiff", () => ({ fromArrayBuffer: vi.fn() }));

import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";
import { fromArrayBuffer } from "geotiff";
import { SitePreviewThumb } from "@/components/site/SitePreviewThumb";
import { SiteVisualTileProvider, useSiteVisualTile } from "@/components/site/SiteVisualTile";

const fromArrayBufferMock = fromArrayBuffer as unknown as ReturnType<typeof vi.fn>;

const digestOf = (bytes: Uint8Array): string => `sha256:${bytesToHex(sha256(bytes))}`;

function descriptor(overrides: Record<string, unknown> = {}) {
  const siteId = (overrides.siteId as string | undefined) ?? "site-1";
  return {
    available: true,
    siteId,
    workAreaId: "area-1",
    workAreaName: "Floreat common-extent",
    requestId: "sdj-v1-00000000-0000-0000-0000-000000000001",
    assetRef: `ksa-v1-${"a".repeat(64)}`,
    artifactKind: "ortho",
    fileHref:
      `/api/sites/${siteId}/work-areas/area-1/spatial-data-requests/sdj-v1-00000000-0000-0000-0000-000000000001/file`,
    outputSha256: digestOf(new Uint8Array([7, 7, 7, 7])),
    outputSizeBytes: 4,
    width: 2,
    height: 2,
    preparedAt: "2026-10-21T00:00:00Z",
    asset: {
      revision: 1,
      gsdM: 0.05,
      captureStartedAt: "2021-08-17T00:00:00Z",
      captureEndedAt: "2021-08-17T00:10:00Z",
      captureDate: null,
      attribution: "Floreat public sample (CC BY 4.0)",
      modificationNotice: "Windowed crop; no reprojection.",
    },
    partial: true,
    siteHref: `/sites/${siteId}?workAreaId=area-1&assetRef=${`ksa-v1-${"a".repeat(64)}`}`,
    ...overrides,
  };
}

function fireVisible() {
  observerApi.fire();
}

let observerApi: { fire(): void } = { fire() {} };

function stubObserver() {
  let fire: (() => void) | null = null;
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      observe = vi.fn();
      disconnect = vi.fn();
      unobserve = vi.fn();
      constructor(callback: IntersectionObserverCallback) {
        fire = () => callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
      }
    },
  );
  const api = {
    fire() {
      fire?.();
    },
  };
  observerApi = api;
  return api;
}

function stubCanvas() {
  const putImageData = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ putImageData } as unknown as CanvasRenderingContext2D);
  vi.stubGlobal(
    "ImageData",
    class {
      constructor(
        public readonly data: Uint8ClampedArray,
        public readonly width: number,
        public readonly height: number,
      ) {}
    },
  );
  return putImageData;
}

function stubGeotiffRgb() {
  fromArrayBufferMock.mockResolvedValue({
    getImageCount: async () => 1,
    getImage: async () => ({
      getWidth: () => 2,
      getHeight: () => 2,
      getSamplesPerPixel: () => 3,
      getBitsPerSample: () => 8,
      readRasters: async () => new Uint8Array([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255]),
    }),
  });
}

beforeEach(() => {
  stubCanvas();
  stubGeotiffRgb();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  fromArrayBufferMock.mockReset();
});

describe("SitePreviewThumb", () => {
  it("loads only when visible and links the exact area-asset address", async () => {
    stubObserver();
    const bytes = new Uint8Array([7, 7, 7, 7]);
    const seen: Array<{ url: string; method?: string }> = [];
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      seen.push({ url, method: init?.method });
      if (url.endsWith("/preview")) {
        return new Response(JSON.stringify(descriptor()), { status: 200 });
      }
      return new Response(bytes as unknown as BodyInit, { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<SitePreviewThumb siteId="site-1" size="card" />);
    // Nothing loads before the box is visible.
    expect(fetchMock).not.toHaveBeenCalled();
    fireVisible();

    const link = await screen.findByRole("link", { name: /정사영상 미리보기 일부 범위 열기/ });
    expect(link.getAttribute("href")).toBe(
      `/sites/site-1?workAreaId=area-1&assetRef=${`ksa-v1-${"a".repeat(64)}`}`,
    );
    // 인식 우선: 보이는 자막은 촬영 날짜·자료 종류가 먼저, 기술 상 세는 펼침이 맡는다.
    expect(link.getAttribute("aria-label")).toMatch(/2021.*정사영상.*일부 범위.*Floreat common-extent/);
    // Exact source labels, never latest/whole-site claims.
    expect(link.textContent).toContain("정사영상");
    expect(link.textContent).toContain("2021");
    expect(link.textContent).toContain("부분 범위");
    expect(link.textContent).not.toMatch(/최신|전체 현장/);
    // 작업구역명·등록 버전·GSD는 보이는 자막에 두지 않고 펼침이 맡는다.
    expect(link.textContent).not.toContain("Floreat common-extent");
    expect(link.textContent).not.toContain("등록 버전");
    expect(link.textContent).not.toContain("제출 GSD");
    // 사진 밝기와 무관한 명시적 토큰 쌍 + 좁은 화면에서 잘리지 않는 정보 줄.
    const caption = link.querySelector("figcaption")!;
    expect(caption.classList.contains("bg-accent")).toBe(true);
    expect(caption.classList.contains("text-accent-on")).toBe(true);
    expect(caption.className).not.toMatch(/gradient|linear-to|transparent/);
    expect(caption.textContent).toContain("부분 범위");
    // Attribution is available OUTSIDE the link — hover-only title is not the path.
    expect(link.hasAttribute("title")).toBe(false);
    expect(link.querySelector("details,summary")).toBeNull();
    const info = screen.getByText("자료 정보").closest("details")!;
    expect(link.contains(info)).toBe(false);
    expect(info.textContent).toContain("Floreat common-extent");
    expect(info.textContent).toContain("등록 버전 1");
    expect(info.textContent).toContain("제출 GSD 0.05m");
    expect(info.textContent).toContain("Floreat public sample (CC BY 4.0)");
    await waitFor(() => {
      const canvas = link.querySelector("canvas")!;
      expect(canvas.width).toBe(2);
      expect(canvas.height).toBe(2);
    });
    // Read-only: every call is GET.
    expect(seen.length).toBeGreaterThanOrEqual(2);
    expect(seen.every((call) => !call.method || call.method === "GET")).toBe(true);
    expect(link.querySelector("input,button,select,textarea")).toBeNull();
  });

  it("labels single-band output as relative shading, not a measurement", async () => {
    stubObserver();
    const siteId = "site-2";
    const bytes = new Uint8Array([9, 9, 9, 9]);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/preview")) {
          return new Response(
            JSON.stringify(
              descriptor({
                siteId,
                artifactKind: "dsm",
                outputSha256: digestOf(bytes),
              }),
            ),
            { status: 200 },
          );
        }
        return new Response(bytes as unknown as BodyInit, { status: 200 });
      }),
    );
    fromArrayBufferMock.mockResolvedValue({
      getImageCount: async () => 1,
      getImage: async () => ({
        getWidth: () => 2,
        getHeight: () => 2,
        getSamplesPerPixel: () => 1,
        getBitsPerSample: () => 8,
        readRasters: async () => new Uint8Array([10, 20, 30, 40]),
        getGDALNoData: () => null,
      }),
    });

    render(<SitePreviewThumb siteId={siteId} size="card" />);
    fireVisible();
    const link = await screen.findByRole("link", { name: /미리보기 일부 범위 열기/ });
    expect(link.textContent).toContain("상대 음영");
    expect(link.textContent).not.toMatch(/정확도|측량|정산/);
    expect(link.textContent).toContain("부분 범위");
  });

  it("leads the card caption with capture date and kind, details on demand", async () => {
    stubObserver();
    const bytes = new Uint8Array([7, 7, 7, 7]);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/preview")) {
          return new Response(
            JSON.stringify(
              descriptor({
                siteId: "site-1",
                asset: {
                  revision: 1,
                  gsdM: 0.05,
                  captureStartedAt: null,
                  captureEndedAt: null,
                  captureDate: "2021-08-17",
                  attribution: "Floreat public sample (CC BY 4.0)",
                  modificationNotice: "Windowed crop; no reprojection.",
                },
              }),
            ),
            { status: 200 },
          );
        }
        return new Response(bytes as unknown as BodyInit, { status: 200 });
      }),
    );

    render(<SitePreviewThumb siteId="site-1" size="card" />);
    fireVisible();
    const link = await screen.findByRole("link", { name: /미리보기 일부 범위 열기/ });
    const caption = link.querySelector("figcaption")!.textContent!;
    // 날짜만 확인 caveat stays visible, kind next to it.
    expect(caption).toContain("2021. 8. 17. (날짜만 확인 · 시각 미상)");
    expect(caption).toContain("정사영상");
    expect(caption).toContain("부분 범위");
    expect(caption.indexOf("2021")).toBeLessThan(caption.indexOf("부분 범위"));
    // Technical values leave the first screen for the disclosure.
    expect(caption).not.toContain("등록 버전");
    expect(caption).not.toContain("제출 GSD");
    expect(caption).not.toContain("Floreat common-extent");
    const info = screen.getByText("자료 정보").closest("details")!;
    expect(info.textContent).toContain("Floreat common-extent");
    expect(info.textContent).toContain("등록 버전 1");
    expect(info.textContent).toContain("제출 GSD 0.05m");
    expect(info.textContent).toContain("Floreat public sample (CC BY 4.0)");
    // Disclosure stays outside the link and keyboard-operable.
    expect(link.contains(info)).toBe(false);
    expect(info.querySelector("summary")).not.toBeNull();
  });

  it("shows an honest unavailable state without touching bytes when nothing is allowed", async () => {
    stubObserver();
    const siteId = "site-3";
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ available: false, reason: "no-output" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<SitePreviewThumb siteId={siteId} size="card" />);
    fireVisible();
    await screen.findByText("미리보기 없음");
    // Descriptor only — no byte read attempted.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("link")).toBeNull();
    // Honesty is about display availability, never about holdings.
    expect(document.body.textContent).not.toMatch(/자료 없음|등록된 자료가 없|관측자료 없음/);
  });

  it("says cannot-verify on denial instead of pretending no output", async () => {
    stubObserver();
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith("/preview")) {
        return new Response(JSON.stringify({ message: "denied" }), { status: 403 });
      }
      return new Response("denied", { status: 403 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<SitePreviewThumb siteId="site-4" size="card" />);
    fireVisible();
    await screen.findByText("미리보기 권한 없음");
    expect(screen.queryByText("미리보기 없음")).toBeNull();
    expect(screen.queryByText("미리보기 확인 불가")).toBeNull();
    // 권한 거부는 자료 부재가 아니다 — 경쟁 행동 버튼도 새로 달지 않는다.
    expect(document.querySelector("canvas")).toBeNull();
    expect(document.body.textContent).not.toMatch(/자료 없음|등록된 자료가 없|관측자료 없음|보유 자료 없음/);
    expect(document.body.textContent).toMatch(/등록 자료가 없다는 뜻이 아닙니다/);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says could-not-check on unreadable lookup without claiming absence", async () => {
    stubObserver();
    const fetchMock = vi.fn(async () => new Response("missing", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<SitePreviewThumb siteId="site-4b" size="card" />);
    fireVisible();
    await screen.findByText("미리보기 확인 불가");
    expect(screen.queryByText("미리보기 없음")).toBeNull();
    expect(screen.queryByText("미리보기 권한 없음")).toBeNull();
    expect(document.querySelector("canvas")).toBeNull();
    expect(document.body.textContent).not.toMatch(/자료 없음|등록된 자료가 없|관측자료 없음|보유 자료 없음/);
    expect(document.body.textContent).toMatch(/등록 자료가 없다는 뜻이 아닙니다/);
    expect(document.body.textContent).toContain("현장을 열어 자료와 준비 상태를 다시 확인하세요.");
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows an honest neutral block when no preview pixels exist", async () => {
    // 뱃지가 상태를 먼저 말한다 — 없음은 중립색, 사진인 척하지 않는다.
    // 조회는 한 번만 돈다.
    stubObserver();
    const siteId = "site-composed";
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith("/preview")) {
        return new Response(JSON.stringify({ available: false, reason: "no-output" }), { status: 200 });
      }
      return new Response("bytes", { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<SitePreviewThumb siteId={siteId} size="card" />);
    fireVisible();
    const badge = await screen.findByText("미리보기 없음");
    expect(badge.closest("[data-site-visual-placeholder]")?.getAttribute("data-site-visual-placeholder")).toBe("empty");
    expect(fetchMock.mock.calls.filter(([url]) => (url as string).endsWith("/preview"))).toHaveLength(1);
    // 실제 픽셀을 꾸며내지 않고, 카드 크기를 유지하는 중립 표지와 복구 안내를 둔다.
    expect(document.querySelector("canvas")).toBeNull();
    expect(document.querySelector('[data-site-preview="card-empty"] [data-site-visual-placeholder]')).not.toBeNull();
    expect(document.querySelector('[data-site-preview="card-empty"]')?.className).not.toContain("aspect-");
    expect(document.querySelector('[data-site-preview="card-empty"] [role="img"]')?.getAttribute("aria-label")).toContain("실제 영상 미리보기가 아닙니다");
    expect(document.querySelector('[data-site-preview="card-empty"] [role="img"]')?.getAttribute("aria-label")).toContain("등록 자료 현황을 뜻하지 않습니다");
    expect(screen.queryByText("범위 도식 · 사진 아님")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("paints the unknown state with a caution tone, distinct from confirmed absence", async () => {
    stubObserver();
    const fetchMock = vi.fn(async () => new Response("missing", { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<SitePreviewThumb siteId="site-unknown-tone" size="card" />);
    fireVisible();
    const badge = await screen.findByText("미리보기 확인 불가");
    expect(badge.className).toMatch(/bg-high-bg/);
    expect(document.querySelector("canvas")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("keeps the composed-tile descriptor referentially stable across renders", async () => {
    // 합성 타일 검증기가 매 렌더 새 객체를 만들면 소비자의 effect 의존성이
    // 계속 바뀐다. 같은 기술서에서 같은 참조가 나오는지 직접 본다.
    const siteId = "site-stable";
    const tiles = {
      [siteId]: {
        available: true,
        siteId,
        workAreaId: "area-1",
        workAreaName: "합성 도식 구역",
        crs: "EPSG:5186",
        ring: [[200000, 549999.8], [200010, 549999.8], [200010, 550009.8], [200000, 549999.8]],
        vertexCount: 4,
        facts: [{ kind: "ortho", captureStartedAt: null, captureEndedAt: null, captureDate: "2021-08-17", lifecycleState: "SEALED" }],
        scannedAssetCount: 1,
        hasMoreAssets: false,
        siteHref: `/sites/${siteId}?workAreaId=area-1`,
      },
    };
    const seen: Array<unknown> = [];
    function Probe() {
      seen.push(useSiteVisualTile(siteId));
      return null;
    }
    const { rerender } = render(
      <SiteVisualTileProvider tiles={tiles}>
        <Probe />
      </SiteVisualTileProvider>,
    );
    rerender(
      <SiteVisualTileProvider tiles={tiles}>
        <Probe />
      </SiteVisualTileProvider>,
    );
    expect(seen.length).toBeGreaterThanOrEqual(2);
    expect(seen[0]).toBe(seen[seen.length - 1]);
  });

  it("fetches fresh on remount and does not hold a success across mounts", async () => {
    stubObserver();
    const bytes = new Uint8Array([7, 7, 7, 7]);
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith("/preview")) {
        return new Response(JSON.stringify(descriptor({ siteId: "site-5" })), { status: 200 });
      }
      return new Response(bytes as unknown as BodyInit, { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const first = render(<SitePreviewThumb siteId="site-5" size="card" />);
    fireVisible();
    await screen.findByRole("link", { name: /미리보기 일부 범위 열기/ });
    const descriptorCalls = fetchMock.mock.calls.filter(([url]) => (url as string).endsWith("/preview")).length;
    expect(descriptorCalls).toBe(1);
    first.unmount();
    cleanup();
    render(<SitePreviewThumb siteId="site-5" size="card" />);
    fireVisible();
    await screen.findByRole("link", { name: /미리보기 일부 범위 열기/ });
    expect(fetchMock.mock.calls.filter(([url]) => (url as string).endsWith("/preview")).length).toBe(2);
  });

  it("row cue carries partial, source, and capture info without implying whole data", async () => {
    stubObserver();
    const siteId = "site-6";
    const bytes = new Uint8Array([7, 7, 7, 7]);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/preview")) {
          return new Response(JSON.stringify(descriptor({ siteId })), { status: 200 });
        }
        return new Response(bytes as unknown as BodyInit, { status: 200 });
      }),
    );

    render(<SitePreviewThumb siteId={siteId} size="row" />);
    fireVisible();
    const link = await screen.findByRole("link", { name: /정사영상 미리보기 일부 범위 열기/ });
    expect(link.getAttribute("aria-label")).toContain("2021");
    expect(link.getAttribute("aria-label")).toContain("Floreat common-extent");
    // Attribution lives outside the link, reachable by assistive tech.
    const described = document.getElementById(link.getAttribute("aria-describedby")!);
    const accessibleText = `${link.getAttribute("aria-label")} ${described?.textContent}`;
    // Row cue carries site/area, date, kind, partial, attribution for assistive tech.
    expect(accessibleText).toContain("site-6");
    expect(accessibleText).toContain("Floreat common-extent");
    expect(accessibleText).toContain("2021");
    expect(accessibleText).toContain("정사영상");
    expect(accessibleText).toContain("부분 범위");
    expect(described?.textContent).toContain("Floreat public sample (CC BY 4.0)");
    expect(described?.textContent).toContain("등록 버전 1");
    expect(described?.textContent).toContain("제출 GSD 0.05m");
    expect(accessibleText).not.toMatch(/전체 현장|최신/);
    expect(link.querySelector("details,summary,input,button")).toBeNull();
  });

  it("states a refused lookup honestly with a neutral block", async () => {
    stubObserver();
    const siteId = "site-refused-composed";
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ message: "denied" }), { status: 403 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<SitePreviewThumb siteId={siteId} size="card" />);
    fireVisible();
    await screen.findByText("미리보기 권한 없음");
    expect(screen.queryByText("미리보기 없음")).toBeNull();
    expect(screen.queryByText("미리보기 확인 불가")).toBeNull();
    expect(document.querySelector("canvas")).toBeNull();
    expect(document.querySelector('[data-site-visual-placeholder="refused"]')).not.toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("does not share an old in-flight descriptor or abort signal with a new mount", async () => {
    stubObserver();
    let finishOld!: (response: Response) => void;
    const oldReply = new Promise<Response>((resolve) => { finishOld = resolve; });
    let lookups = 0;
    let oldSignal: AbortSignal | undefined;
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/preview")) {
        lookups += 1;
        if (lookups === 1) {
          oldSignal = init?.signal as AbortSignal;
          return oldReply;
        }
        return new Response(JSON.stringify({ available: false, reason: "no-output" }), { status: 200 });
      }
      throw new Error("No bytes are allowed for the new mount");
    });
    vi.stubGlobal("fetch", fetchMock);
    const first = render(<SitePreviewThumb siteId="site-8" size="card" />);
    fireVisible();
    await waitFor(() => expect(lookups).toBe(1));
    first.unmount();
    expect(oldSignal?.aborted).toBe(true);
    render(<SitePreviewThumb siteId="site-8" size="card" />);
    fireVisible();
    await screen.findByText("미리보기 없음");
    expect(lookups).toBe(2);
    finishOld(new Response(JSON.stringify(descriptor({ siteId: "site-8" })), { status: 200 }));
    await waitFor(() => expect(screen.queryByRole("link")).toBeNull());
    expect(fetchMock.mock.calls.every(([url]) => url.endsWith("/preview"))).toBe(true);
  });

  it("row loading state never claims unavailable", async () => {
    stubObserver();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        await new Promise(() => undefined);
        return new Response("never", { status: 200 });
      }),
    );

    render(<SitePreviewThumb siteId="site-7" size="row" />);
    fireVisible();
    const pending = await screen.findByRole("img", { name: "미리보기 불러오는 중" });
    expect(pending.getAttribute("aria-label")).not.toMatch(/없음|확인하지 못함/);
  });
});
