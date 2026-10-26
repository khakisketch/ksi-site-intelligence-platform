/** @vitest-environment jsdom */
import { webcrypto } from "node:crypto";
import { createHash } from "node:crypto";

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.stubGlobal("crypto", webcrypto);

import {
  DeltaPublicationPanel,
  deltaDispositionFromCode,
  deltaTerminalCopy,
  type DeltaPublicationSource,
} from "@/app/sites/[siteId]/analysis/DeltaPublicationPanel";

const digest = (marker: string) => `sha256:${marker.repeat(64).slice(0, 64)}`;
const source: DeltaPublicationSource = {
  sourceCalculationIdentityDigest: digest("a"),
  sourceNumericResultIdentityDigest: digest("b"),
  sourceCoverageWitnessDigest: digest("c"),
};
const props = {
  siteId: "site-1",
  workAreaId: "area-1",
  workAreaLabel: "1구역",
  source,
  canRequest: true,
  lifetimeSeconds: 3600,
  downloadBudgetBytes: 4 * 1024 * 1024,
};

function keyOf(url: string): string {
  const segments = new URL(url, "http://localhost").pathname.split("/").filter((part) => part.length > 0);
  const last = segments[segments.length - 1] ?? "";
  // 조각 조회(`/bytes`)에서는 끝에서 두 번째가 식별자다.
  const raw = last === "bytes" ? (segments[segments.length - 2] ?? "") : last;
  return decodeURIComponent(raw);
}

function intentJsonFor(publicationId: string, overrides: Record<string, unknown> = {}) {
  return {
    publicationId,
    siteId: "site-1",
    workAreaId: "area-1",
    sourceCalculationIdentityDigest: source.sourceCalculationIdentityDigest,
    sourceNumericResultIdentityDigest: source.sourceNumericResultIdentityDigest,
    sourceCoverageWitnessDigest: source.sourceCoverageWitnessDigest,
    outputId: `delta-out-${publicationId}`,
    status: "PENDING",
    issuedAt: "2026-10-26T00:00:00Z",
    expiresAt: new Date(Date.now() + 3600_000).toISOString(),
    ...overrides,
  };
}

function detailJsonFor(publicationId: string, payload: Uint8Array, overrides: Record<string, unknown> = {}) {
  const hash = createHash("sha256").update(payload).digest("hex");
  // 최상위와 서술자는 같은 발행의 같은 시각을 싣는다(서버도 항목에서 복사한다).
  const issuedAt = "2026-10-26T00:00:00Z";
  const expiresAt = new Date(Date.now() + 3600_000).toISOString();
  return {
    publicationId,
    siteId: "site-1",
    workAreaId: "area-1",
    outputId: `delta-out-${publicationId}`,
    status: "PUBLISHED",
    issuedAt,
    expiresAt,
    descriptor: {
      publicationId,
      siteId: "site-1",
      workAreaId: "area-1",
      sourceCalculationIdentityDigest: source.sourceCalculationIdentityDigest,
      sourceNumericResultIdentityDigest: source.sourceNumericResultIdentityDigest,
      sourceCoverageWitnessDigest: source.sourceCoverageWitnessDigest,
      deltaSign: "CURRENT_MINUS_BASELINE",
      gridRows: 2,
      gridColumns: 2,
      gridCrsIdentifier: "EPSG:5186",
      verticalUnit: "metre",
      dtype: "FLOAT64",
      outputId: `delta-out-${publicationId}`,
      outputSha256: `sha256:${hash}`,
      outputSizeBytes: payload.length,
      issuedAt,
      expiresAt,
      ...overrides,
    },
  };
}

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}

function base64Of(payload: Uint8Array): string {
  return Buffer.from(payload).toString("base64");
}

/** BFF 목 — 요청 식별자를 그대로 메아리한다(범위 검증이 통과하는 정상 서버). */
function stubBff(handler: {
  onPost?: (publicationId: string) => Response | Promise<Response>;
  onDetail?: (publicationId: string) => Response | Promise<Response>;
  onBytes?: (publicationId: string, offset: number, length: number) => Response | Promise<Response>;
}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (init?.method === "POST") {
      const sent = JSON.parse(String(init.body));
      return handler.onPost?.(sent.publicationId) ?? json(intentJsonFor(sent.publicationId), 202);
    }
    if (url.includes("/bytes?")) {
      const search = new URL(url, "http://localhost").searchParams;
      return handler.onBytes?.(keyOf(url), Number(search.get("offset")), Number(search.get("length")))
        ?? json({ message: "no bytes handler" }, 500);
    }
    return handler.onDetail?.(keyOf(url)) ?? json({ message: "not available" }, 404);
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.stubGlobal("crypto", webcrypto);
});

describe("delta publication panel", () => {
  it("stays separate from calculation status and never requests on mount", () => {
    const fetchMock = vi.fn(async () => json(intentJsonFor("delta-x")));
    vi.stubGlobal("fetch", fetchMock);
    render(<DeltaPublicationPanel {...props} />);

    expect(screen.getByRole("heading", { name: "차분 파일" })).toBeTruthy();
    expect(screen.getByText("미요청")).toBeTruthy();
    expect(screen.getByRole("button", { name: "내보내기 준비 요청" })).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText(/수치 결과는 그대로 유지됩니다/)).toBeTruthy();
  });

  it("posts exactly the three source digests with the lifetime on explicit request", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      calls.push({ url, init });
      if (url.endsWith("/delta-publications")) {
        return json(intentJsonFor(JSON.parse(String(init?.body)).publicationId));
      }
      return json({ message: "not available" }, 404);
    }));
    render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));

    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());
    expect(calls).toHaveLength(1);
    expect(calls[0]!.url).toBe("/api/sites/site-1/work-areas/area-1/delta-publications");
    const sent = JSON.parse(String(calls[0]!.init?.body));
    expect(sent).toEqual({
      publicationId: expect.stringMatching(/^delta-/),
      ...source,
      lifetimeSeconds: 3600,
    });
    expect(Object.keys(sent)).toHaveLength(5);
    // 원시 URL·토큰을 싣지 않는다 — BFF 상대 경로만 쓴다.
    expect(calls[0]!.url).not.toMatch(/^https?:/);
    expect(JSON.stringify(sent)).not.toMatch(/token|core\.test/i);
  });

  it("shows the server-echoed FLOAT64 profile and availability once published", async () => {
    const payload = new Uint8Array([1, 2, 3, 4, 5, 6, 7, 8]);
    vi.stubGlobal("fetch", stubBff({
      onDetail: (publicationId) => json(detailJsonFor(publicationId, payload)),
    }));
    render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());

    fireEvent.click(await screen.findByRole("button", { name: "상태 다시 확인" }));
    await waitFor(() => expect(screen.getByText("사용 가능")).toBeTruthy());
    expect(screen.getByText("FLOAT64")).toBeTruthy();
    expect(screen.getByText("현재 − 기준")).toBeTruthy();
    expect(screen.getByText("미터")).toBeTruthy();
    expect(screen.getByRole("button", { name: "차분 파일 내려받기" })).toBeTruthy();
    // 수치 결과는 별도 유지 문구가 함께 보인다.
    expect(screen.getByText(/이 파일과 별개로 유지됩니다/)).toBeTruthy();
  });

  it("reuses the idempotent publication key on ambiguous retry instead of mutating again", async () => {
    const posted: string[] = [];
    let attempts = 0;
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      attempts += 1;
      if (attempts === 1) throw new TypeError("network down");
      const id = JSON.parse(String(init?.body)).publicationId;
      posted.push(id);
      return json(intentJsonFor(id), 202);
    }));
    render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "다시 시도" })).toBeTruthy());
    // 라이브 영역과 본문이 같은 문장을 가지므로 복수로 읽는다.
    expect(screen.getAllByText(/수치 결과에는 영향이 없습니다/).length).toBeGreaterThan(0);
    // 수치 실패로 표현하지 않는다.
    expect(screen.queryByText(/수치.*실패|계산.*실패/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());
    expect(posted).toHaveLength(1);
  });

  it("treats request errors as export-only and never as numeric failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ verdict: "DELTA_SOURCE_OR_AUTHORITY_UNAVAILABLE" }, 409)));
    render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "다시 시도" })).toBeTruthy());
    const matches = screen.getAllByText(/기준 계산·수치·범위 근거를 현재 확인할 수 없어/);
    expect(matches.length).toBeGreaterThan(0);
    expect(matches[0]!.textContent).toContain("수치 결과에는 영향이 없습니다");
    expect(screen.queryByText(/수치 결과를 .*하지 못|수치.*실패/)).toBeNull();
  });

  it("expires honestly and requests fresh after expiry instead of reusing the dead key", async () => {
    const posted: string[] = [];
    vi.stubGlobal("fetch", stubBff({
      onPost: (publicationId) => {
        posted.push(publicationId);
        return json(intentJsonFor(publicationId, { expiresAt: new Date(Date.now() - 1000).toISOString() }), 202);
      },
    }));
    render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());

    fireEvent.click(await screen.findByRole("button", { name: "상태 다시 확인" }));
    await waitFor(() => expect(screen.getByText("만료됨")).toBeTruthy());
    expect(screen.getAllByText(/유효 기한이 지났습니다/).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "다시 요청" }));
    await waitFor(() => expect(posted).toHaveLength(2));
    expect(posted[0]).not.toBe(posted[1]);
  });

  it("gates the write action behind permission without hiding status", async () => {
    const fetchMock = vi.fn(async () => json(intentJsonFor("delta-x")));
    vi.stubGlobal("fetch", fetchMock);
    render(<DeltaPublicationPanel {...props} canRequest={false} />);

    expect(screen.getByText("미요청")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    expect(screen.getByText(/현장 쓰기 권한이 있는 담당자에게 요청하세요/)).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps the write action inside the incumbent ANALYSIS_REQUEST boundary on small screens", () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(intentJsonFor("delta-x"))));
    render(<DeltaPublicationPanel {...props} />);
    expect(document.querySelector('[data-responsive-action-notice="ANALYSIS_REQUEST"]')).not.toBeNull();
    // 상태·배지는 경계 밖에 그대로 보인다.
    expect(screen.getByText("미요청")).toBeTruthy();
  });

  it("aborts in-flight status checks on unmount without exposing anything", async () => {
    const signals: AbortSignal[] = [];
    let release!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.signal) signals.push(init.signal);
      const url = typeof input === "string" ? input : input.toString();
      if (init?.method === "POST") {
        return json(intentJsonFor(JSON.parse(String(init.body)).publicationId), 202);
      }
      if (url.includes("/delta-publications")) {
        return new Promise<Response>((resolve) => { release = resolve; });
      }
      return json({ message: "unexpected" }, 500);
    }));
    const view = render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "상태 다시 확인" }));
    await waitFor(() => expect(signals.length).toBeGreaterThanOrEqual(2));
    const inFlight = signals[signals.length - 1]!;
    expect(inFlight.aborted).toBe(false);
    view.unmount();
    expect(inFlight.aborted).toBe(true);
    release(json(detailJsonFor("delta-late", new Uint8Array([1]))));
  });

  it("downloads guarded chunks and verifies hash and size before exposing any file", async () => {
    const payload = new Uint8Array([10, 20, 30, 40, 50, 60, 70, 80]);
    vi.stubGlobal("fetch", stubBff({
      onDetail: (publicationId) => json(detailJsonFor(publicationId, payload)),
      onBytes: (publicationId, offset, length) => {
        expect(length).toBeLessThanOrEqual(1024 * 1024);
        return json({ publicationId, offset, contentBase64: base64Of(payload.slice(offset, offset + length)) });
      },
    }));
    const created: string[] = [];
    Object.defineProperty(URL, "createObjectURL", {
      value: vi.fn(() => { created.push("blob:mock"); return "blob:mock"; }),
      configurable: true,
    });
    Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
    const seenNames: string[] = [];
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      seenNames.push(this.download);
    });

    render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());
    fireEvent.click(await screen.findByRole("button", { name: "상태 다시 확인" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "차분 파일 내려받기" })).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "차분 파일 내려받기" }));
    });
    await waitFor(() => expect(created).toHaveLength(1));
    expect(seenNames[0]).toMatch(/^delta-.*\.tiff$/);
    expect(screen.getByText(/내려받기 전후로 파일 정보를 대조한 뒤 내려받았습니다/)).toBeTruthy();
    clickSpy.mockRestore();
  });

  it("exposes no file when a chunk is tampered with", async () => {
    const payload = new Uint8Array([10, 20, 30, 40, 50, 60, 70, 80]);
    vi.stubGlobal("fetch", stubBff({
      onDetail: (publicationId) => json(detailJsonFor(publicationId, payload)),
      onBytes: (publicationId, offset) => {
        const tampered = Uint8Array.from(payload);
        tampered[0] = 99;
        return json({ publicationId, offset, contentBase64: base64Of(tampered.slice(offset)) });
      },
    }));
    const created: string[] = [];
    Object.defineProperty(URL, "createObjectURL", {
      value: vi.fn(() => { created.push("blob:mock"); return "blob:mock"; }),
      configurable: true,
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());
    fireEvent.click(await screen.findByRole("button", { name: "상태 다시 확인" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "차분 파일 내려받기" })).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "차분 파일 내려받기" }));
    });
    await waitFor(() => expect(screen.getAllByText(/파일 확인값이 서술자와 달라/).length).toBeGreaterThan(0));
    expect(created).toHaveLength(0);
  });

  it("refuses the download when the descriptor exceeds the explicit delivery budget", async () => {
    const payload = new Uint8Array([1, 2, 3, 4]);
    vi.stubGlobal("fetch", stubBff({
      onDetail: (publicationId) => json(detailJsonFor(publicationId, payload)),
    }));
    render(<DeltaPublicationPanel {...props} downloadBudgetBytes={2} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());
    fireEvent.click(await screen.findByRole("button", { name: "상태 다시 확인" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "차분 파일 내려받기" })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "차분 파일 내려받기" }));
    expect((await screen.findAllByText(/전송 예산.*넘겨 내려받지 않습니다/)).length).toBeGreaterThan(0);
  });
});

describe("delta publication identity and download reverification", () => {
  const newSource: DeltaPublicationSource = {
    sourceCalculationIdentityDigest: digest("n"),
    sourceNumericResultIdentityDigest: digest("m"),
    sourceCoverageWitnessDigest: digest("o"),
  };

  it("resets to idle on source change and never reuses the old publication key", async () => {
    const posted: string[] = [];
    vi.stubGlobal("fetch", stubBff({
      onPost: (publicationId) => {
        posted.push(publicationId);
        return json(intentJsonFor(publicationId), 202);
      },
      onDetail: (publicationId) => json(detailJsonFor(publicationId, new Uint8Array([1, 2]))),
    }));
    const view = render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());
    fireEvent.click(await screen.findByRole("button", { name: "상태 다시 확인" }));
    await waitFor(() => expect(screen.getByText("사용 가능")).toBeTruthy());
    expect(screen.getByText("EPSG:5186")).toBeTruthy();

    view.rerender(<DeltaPublicationPanel {...props} source={newSource} />);
    await waitFor(() => expect(screen.getByText("미요청")).toBeTruthy());
    // 낡은 파일 주석이 새 선택 결과에 남지 않는다.
    expect(screen.queryByText("EPSG:5186")).toBeNull();
    expect(screen.queryByText("사용 가능")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(posted).toHaveLength(2));
    expect(posted[0]).not.toBe(posted[1]);
  });

  it("aborts a deferred request on identity change and ignores its late response", async () => {
    const signals: AbortSignal[] = [];
    let resolvePost!: (value: Response) => void;
    const bodies: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.signal) signals.push(init.signal);
      const url = typeof input === "string" ? input : input.toString();
      if (init?.method === "POST") {
        bodies.push(JSON.parse(String(init.body)).publicationId);
        return new Promise<Response>((resolve) => { resolvePost = resolve; });
      }
      return json({ message: "not available" }, 404);
    }));
    const view = render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(bodies).toHaveLength(1));

    view.rerender(<DeltaPublicationPanel {...props} source={newSource} />);
    await waitFor(() => expect(signals.some((signal) => signal.aborted)).toBe(true));
    await waitFor(() => expect(screen.getByText("미요청")).toBeTruthy());

    // 낡은 요청의 늦은 응답이 상태를 되살리지 않는다.
    resolvePost(json(intentJsonFor(bodies[0]!), 202));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.getByText("미요청")).toBeTruthy();
    expect(screen.queryByText("준비 중")).toBeNull();
  });

  it("stops pending mutations on permission revoke without firing new mutations", async () => {
    const postSignals: AbortSignal[] = [];
    let resolvePost!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST" && init?.signal) postSignals.push(init.signal);
      const url = typeof input === "string" ? input : input.toString();
      if (init?.method === "POST") {
        return new Promise<Response>((resolve) => { resolvePost = resolve; });
      }
      return json({ message: "not available" }, 404);
    }));
    const view = render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(postSignals.length).toBeGreaterThan(0));

    view.rerender(<DeltaPublicationPanel {...props} canRequest={false} />);
    await waitFor(() => expect(screen.getByText("미요청")).toBeTruthy());
    expect(postSignals.some((signal) => signal.aborted)).toBe(true);
    // 늦은 응답이 요청을 되살리지 않는다.
    resolvePost(json(intentJsonFor("delta-late"), 202));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.getByText("미요청")).toBeTruthy();
    // 권한 회수 후에는 쓰기 요청이 나가지 않는다.
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    expect(screen.getByText(/현장 쓰기 권한이 있는 담당자에게 요청하세요/)).toBeTruthy();
  });

  it("lets an in-flight download finish across permission revoke and never promises client-side security", async () => {
    const payload = new Uint8Array([7, 8, 9, 10]);
    vi.stubGlobal("fetch", stubBff({
      onDetail: (publicationId) => json(detailJsonFor(publicationId, payload)),
      onBytes: (publicationId, offset, length) =>
        json({ publicationId, offset, contentBase64: base64Of(payload.slice(offset, offset + length)) }),
    }));
    const created: string[] = [];
    Object.defineProperty(URL, "createObjectURL", {
      value: vi.fn(() => { created.push("blob:mock"); return "blob:mock"; }),
      configurable: true,
    });
    Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    const view = render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());
    fireEvent.click(await screen.findByRole("button", { name: "상태 다시 확인" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "차분 파일 내려받기" })).toBeTruthy());

    const downloadPromise = (async () => {
      fireEvent.click(screen.getByRole("button", { name: "차분 파일 내려받기" }));
    })();
    view.rerender(<DeltaPublicationPanel {...props} canRequest={false} />);
    await downloadPromise;
    await waitFor(() => expect(created).toHaveLength(1));
  });

  it("assembles a real multi-chunk payload above 512KiB before exposing any file", async () => {
    const payload = new Uint8Array(600_000);
    for (let i = 0; i < payload.length; i += 1) payload[i] = i % 251;
    const requestedLengths: number[] = [];
    vi.stubGlobal("fetch", stubBff({
      onDetail: (publicationId) => json(detailJsonFor(publicationId, payload)),
      onBytes: (publicationId, offset, length) => {
        requestedLengths.push(length);
        return json({ publicationId, offset, contentBase64: base64Of(payload.slice(offset, offset + length)) });
      },
    }));
    const created: string[] = [];
    Object.defineProperty(URL, "createObjectURL", {
      value: vi.fn(() => { created.push("blob:mock"); return "blob:mock"; }),
      configurable: true,
    });
    Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<DeltaPublicationPanel {...props} downloadBudgetBytes={4 * 1024 * 1024} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());
    fireEvent.click(await screen.findByRole("button", { name: "상태 다시 확인" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "차분 파일 내려받기" })).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "차분 파일 내려받기" }));
    });
    await waitFor(() => expect(created).toHaveLength(1));
    // 600_000바이트는 512KiB 조각 2개로만 온다.
    expect(requestedLengths).toEqual([524_288, 600_000 - 524_288]);
  });

  it("exposes no file when the post-download reverification is forbidden", async () => {
    const payload = new Uint8Array([1, 2, 3, 4]);
    let detailCalls = 0;
    vi.stubGlobal("fetch", stubBff({
      onDetail: (publicationId) => {
        detailCalls += 1;
        // 내려받기 직전 확인은 통과하고, 파일 완성 직후 확인에서 거부된다.
        if (detailCalls >= 3) return json({ code: "DELTA_SCOPE_DENIED" }, 403);
        return json(detailJsonFor(publicationId, payload));
      },
      onBytes: (publicationId, offset, length) =>
        json({ publicationId, offset, contentBase64: base64Of(payload.slice(offset, offset + length)) }),
    }));
    const created: string[] = [];
    Object.defineProperty(URL, "createObjectURL", {
      value: vi.fn(() => { created.push("blob:mock"); return "blob:mock"; }),
      configurable: true,
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());
    // call 1: 상태 다시 확인.
    fireEvent.click(await screen.findByRole("button", { name: "상태 다시 확인" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "차분 파일 내려받기" })).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "차분 파일 내려받기" }));
    });
    // call 2: 내려받기 직전, call 3: 파일 완성 직후(거부).
    await waitFor(() => expect(detailCalls).toBeGreaterThanOrEqual(3));
    await waitFor(() => expect(screen.getAllByText(/조회할 권한이 없어/).length).toBeGreaterThan(0));
    expect(created).toHaveLength(0);
  });

  it("expires honestly on post-download reverification instead of exposing a stale file", async () => {
    const payload = new Uint8Array([1, 2, 3, 4]);
    let detailCalls = 0;
    vi.stubGlobal("fetch", stubBff({
      onDetail: (publicationId) => {
        detailCalls += 1;
        if (detailCalls >= 3) {
          // Core는 최상위와 서술자에 같은 발행 시각을 싣는다 — 둘 다 만료로 답한다.
          const past = new Date(Date.now() - 1000).toISOString();
          const expired = detailJsonFor(publicationId, payload, { expiresAt: past, issuedAt: past });
          return json({ ...expired, expiresAt: past, issuedAt: past });
        }
        return json(detailJsonFor(publicationId, payload));
      },
      onBytes: (publicationId, offset, length) =>
        json({ publicationId, offset, contentBase64: base64Of(payload.slice(offset, offset + length)) }),
    }));
    const created: string[] = [];
    Object.defineProperty(URL, "createObjectURL", {
      value: vi.fn(() => { created.push("blob:mock"); return "blob:mock"; }),
      configurable: true,
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());
    fireEvent.click(await screen.findByRole("button", { name: "상태 다시 확인" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "차분 파일 내려받기" })).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "차분 파일 내려받기" }));
    });
    await waitFor(() => expect(screen.getByText("만료됨")).toBeTruthy());
    expect(created).toHaveLength(0);
  });

  it("never retries automatically after a 403 and offers no mutation retry", async () => {
    let posts = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      posts += 1;
      return json({ code: "DELTA_SCOPE_DENIED" }, 403);
    }));
    render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));

    await waitFor(() => expect(screen.getAllByText(/요청 권한이 없습니다/).length).toBeGreaterThan(0));
    // 자동 재시도도, 변이 재시도 단추도 없다 — 잠금 안내만 남는다.
    expect(posts).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(screen.getByText(/같은 요청을 반복해도 해결되지 않습니다/)).toBeTruthy();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(posts).toBe(1);
  });

  it("rejects a non-canonical chunk before any file is exposed", async () => {
    const payload = new Uint8Array([1, 2, 3, 4]);
    vi.stubGlobal("fetch", stubBff({
      onDetail: (publicationId) => json(detailJsonFor(publicationId, payload)),
      onBytes: (publicationId, offset) => json({ publicationId, offset, contentBase64: "AB==" }),
    }));
    const created: string[] = [];
    Object.defineProperty(URL, "createObjectURL", {
      value: vi.fn(() => { created.push("blob:mock"); return "blob:mock"; }),
      configurable: true,
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());
    fireEvent.click(await screen.findByRole("button", { name: "상태 다시 확인" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "차분 파일 내려받기" })).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "차분 파일 내려받기" }));
    });
    await waitFor(() => expect(screen.getAllByText(/조각 형식을 확인할 수 없습니다/).length).toBeGreaterThan(0));
    expect(created).toHaveLength(0);
  });
});

describe("delta publication typed dispositions", () => {
  it("derives only the known bounded codes and never guesses unknown ones", () => {
    expect(deltaDispositionFromCode("DELTA_PUBLICATION_NOT_YET_PUBLISHED")).toBe("NOT_YET_PUBLISHED");
    expect(deltaDispositionFromCode("DELTA_PUBLICATION_EXPIRED")).toBe("EXPIRED");
    expect(deltaDispositionFromCode("DELTA_PUBLICATION_REVOKED")).toBe("REVOKED");
    expect(deltaDispositionFromCode("DELTA_PUBLICATION_CANCELED")).toBe("CANCELED");
    expect(deltaDispositionFromCode("DELTA_PUBLICATION_FAILED")).toBe("FAILED");
    expect(deltaDispositionFromCode("DELTA_PUBLICATION_SOURCE_NOT_CURRENT")).toBe("SOURCE_NOT_CURRENT");
    expect(deltaDispositionFromCode("DELTA_PUBLICATION_POLICY_NOT_CURRENT")).toBe("POLICY_NOT_CURRENT");
    expect(deltaDispositionFromCode("DELTA_PUBLICATION_RUNTIME_NOT_CURRENT")).toBe("RUNTIME_NOT_CURRENT");
    expect(deltaDispositionFromCode("DELTA_PUBLICATION_EGRESS_DENIED")).toBe("EGRESS_DENIED");
    expect(deltaDispositionFromCode("DELTA_PUBLICATION_BYTES_UNAVAILABLE")).toBe("BYTES_UNAVAILABLE");
    expect(deltaDispositionFromCode("DELTA_PUBLICATION_NOT_FOUND")).toBe("NOT_FOUND");
    // 구형 일반형·코드 없음·모르는 코드는 모호하게 둔다.
    expect(deltaDispositionFromCode("DELTA_PUBLICATION_NOT_AVAILABLE")).toBeNull();
    expect(deltaDispositionFromCode(undefined)).toBeNull();
    expect(deltaDispositionFromCode("DELTA_PUBLICATION_FUTURE_CODE")).toBeNull();
    expect(deltaDispositionFromCode("SOME_OTHER_ERROR")).toBeNull();
  });

  it("maps every terminal disposition to a closed message that never claims numeric failure", () => {
    const dispositions = [
      "EXPIRED", "REVOKED", "CANCELED", "FAILED", "SOURCE_NOT_CURRENT",
      "POLICY_NOT_CURRENT", "RUNTIME_NOT_CURRENT", "EGRESS_DENIED",
      "BYTES_UNAVAILABLE", "NOT_FOUND",
    ] as const;
    for (const disposition of dispositions) {
      const copy = deltaTerminalCopy(disposition);
      expect(copy.message).toContain("수치 결과에는 영향이 없습니다");
      expect(copy.message).not.toMatch(/수치.*실패|계산.*실패/);
    }
    expect(deltaTerminalCopy("EXPIRED").expired).toBe(true);
    expect(deltaTerminalCopy("FAILED").expired).toBe(false);
    expect(deltaTerminalCopy("SOURCE_NOT_CURRENT").message).toContain("기준 계산·수치·범위 근거가 바뀌어");
  });
});

describe("delta publication second-review behaviors", () => {
  async function flushRounds(n = 8) {
    for (let i = 0; i < n; i += 1) {
      await act(async () => {});
    }
  }

  it("shows a retryable timeout error instead of a stuck spinner when a chunk times out", async () => {
    const payload = new Uint8Array([1, 2, 3, 4]);
    vi.stubGlobal("fetch", stubBff({
      onDetail: (publicationId) => json(detailJsonFor(publicationId, payload)),
      onBytes: () => Promise.reject(new DOMException("aborted", "AbortError")),
    }));
    const created: string[] = [];
    Object.defineProperty(URL, "createObjectURL", {
      value: vi.fn(() => { created.push("blob:mock"); return "blob:mock"; }),
      configurable: true,
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());
    fireEvent.click(await screen.findByRole("button", { name: "상태 다시 확인" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "차분 파일 내려받기" })).toBeTruthy());

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "차분 파일 내려받기" }));
    });
    // 스피너가 풀리고 재시도 가능한 오류가 보인다. 수치 실패가 아니다.
    await waitFor(() => expect(screen.getAllByText(/시간이 초과되어 중단했습니다/).length).toBeGreaterThan(0));
    expect(screen.getByRole("button", { name: "차분 파일 내려받기" })).toBeTruthy();
    // 결과 상태는 그대로 사용 가능 — 수치 실패로 둔갑하지 않는다.
    expect(screen.getByText("사용 가능")).toBeTruthy();
    expect(created).toHaveLength(0);
  });

  it("closes silently without a blob when the user cancels a download", async () => {
    const payload = new Uint8Array([1, 2, 3, 4]);
    let releaseBytes!: (value: Response) => void;
    vi.stubGlobal("fetch", stubBff({
      onDetail: (publicationId) => json(detailJsonFor(publicationId, payload)),
      onBytes: (publicationId, offset, length) => new Promise<Response>((resolve) => {
        releaseBytes = () => resolve(json({ publicationId, offset, contentBase64: base64Of(payload.slice(offset, offset + length)) }));
      }),
    }));
    const created: string[] = [];
    Object.defineProperty(URL, "createObjectURL", {
      value: vi.fn(() => { created.push("blob:mock"); return "blob:mock"; }),
      configurable: true,
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());
    fireEvent.click(await screen.findByRole("button", { name: "상태 다시 확인" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "차분 파일 내려받기" })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "차분 파일 내려받기" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "내려받기 취소" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "내려받기 취소" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "차분 파일 내려받기" })).toBeTruthy());
    // 취소 뒤 늦게 온 조각은 파일을 만들지 않고 오류도 남기지 않는다.
    releaseBytes(json({ publicationId: "delta-x", offset: 0, contentBase64: base64Of(payload) }));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(created).toHaveLength(0);
    expect(screen.queryByText(/시간이 초과/)).toBeNull();
  });

  it("closes a terminal FAILED intent immediately without polling", async () => {
    let posts = 0;
    let detailCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (init?.method === "POST") {
        posts += 1;
        const id = JSON.parse(String(init.body)).publicationId;
        return json(intentJsonFor(id, { status: "FAILED" }), 202);
      }
      detailCalls += 1;
      return json({ message: "not available" }, 404);
    }));
    render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));

    await waitFor(() => expect(screen.getByText("사용 불가")).toBeTruthy());
    expect(screen.getAllByText(/차분 파일 준비에 실패했습니다/).length).toBeGreaterThan(0);
    expect(posts).toBe(1);
    expect(detailCalls).toBe(0);
  });

  it("maps a typed expired 404 to expired without polling", async () => {
    vi.stubGlobal("fetch", stubBff({
      onDetail: () => json({ code: "DELTA_PUBLICATION_EXPIRED", message: "expired" }, 404),
    }));
    render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "상태 다시 확인" }));

    await waitFor(() => expect(screen.getByText("만료됨")).toBeTruthy());
  });

  it("maps a withdrawn source 404 to unavailable with a closed message", async () => {
    vi.stubGlobal("fetch", stubBff({
      onDetail: () => json({ code: "DELTA_PUBLICATION_SOURCE_NOT_CURRENT", message: "withdrawn" }, 404),
    }));
    render(<DeltaPublicationPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "상태 다시 확인" }));

    await waitFor(() => expect(screen.getByText("사용 불가")).toBeTruthy());
    expect(screen.getAllByText(/기준 계산·수치·범위 근거가 바뀌어/).length).toBeGreaterThan(0);
  });

  it("keeps polling only for not-yet-published and stops for canceled, with fake timers", async () => {
    vi.useFakeTimers();
    try {
      const posted: string[] = [];
      let detailCalls = 0;
      vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (init?.method === "POST") {
          const id = JSON.parse(String(init.body)).publicationId;
          posted.push(id);
          return json(intentJsonFor(id), 202);
        }
        detailCalls += 1;
        return json({ code: "DELTA_PUBLICATION_NOT_YET_PUBLISHED", message: "not yet" }, 404);
      }));
      render(<DeltaPublicationPanel {...props} />);
      fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
      await flushRounds();
      expect(screen.getByText("준비 중")).toBeTruthy();

      await act(async () => { vi.advanceTimersByTime(4000); });
      await flushRounds();
      expect(detailCalls).toBe(1);
      expect(screen.getByText("준비 중")).toBeTruthy();

      await act(async () => { vi.advanceTimersByTime(4000); });
      await flushRounds();
      expect(detailCalls).toBe(2);
      expect(screen.getByText("준비 중")).toBeTruthy();
      expect(posted).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  }, 15000);

  it("stops the automatic loop on a canceled code without new mutations", async () => {
    vi.useFakeTimers();
    try {
      let posts = 0;
      let detailCalls = 0;
      vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (init?.method === "POST") {
          posts += 1;
          const id = JSON.parse(String(init.body)).publicationId;
          return json(intentJsonFor(id), 202);
        }
        detailCalls += 1;
        return json({ code: "DELTA_PUBLICATION_CANCELED", message: "canceled" }, 404);
      }));
      render(<DeltaPublicationPanel {...props} />);
      fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
      await flushRounds();
      expect(screen.getByText("준비 중")).toBeTruthy();

      await act(async () => { vi.advanceTimersByTime(4000); });
      await flushRounds();
      expect(detailCalls).toBe(1);
      expect(screen.getByText("사용 불가")).toBeTruthy();

      await act(async () => { vi.advanceTimersByTime(12000); });
      await flushRounds();
      expect(detailCalls).toBe(1);
      expect(posts).toBe(1);
    } finally {
      vi.useRealTimers();
    }
  }, 15000);

  it("fires no poll and no new mutation after a 403, even as time passes", async () => {
    vi.useFakeTimers();
    try {
      let posts = 0;
      let detailCalls = 0;
      vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (init?.method === "POST") {
          posts += 1;
          return json({ code: "DELTA_SCOPE_DENIED" }, 403);
        }
        detailCalls += 1;
        return json({ message: "unexpected" }, 500);
      }));
      render(<DeltaPublicationPanel {...props} />);
      fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
      await flushRounds();
      expect(posts).toBe(1);

      await act(async () => { vi.advanceTimersByTime(12000); });
      await flushRounds();
      expect(posts).toBe(1);
      expect(detailCalls).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  }, 15000);
});

describe("delta publication fresh-metadata terminal mapping", () => {
  function stubBytesNeverCalled() {
    const calls: string[] = [];
    const handler = () => {
      calls.push("bytes");
      return json({ message: "must not fetch bytes" }, 500);
    };
    return { calls, handler };
  }

  async function reachReady(publicationId = "delta-key-1") {
    fireEvent.click(screen.getByRole("button", { name: "내보내기 준비 요청" }));
    await waitFor(() => expect(screen.getByText("준비 중")).toBeTruthy());
    fireEvent.click(await screen.findByRole("button", { name: "상태 다시 확인" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "차분 파일 내려받기" })).toBeTruthy());
    expect(publicationId).toBeTruthy();
  }

  it("drops to expired when the pre-download check reports typed expiry", async () => {
    const payload = new Uint8Array([1, 2, 3, 4]);
    const bytes = stubBytesNeverCalled();
    let detailCalls = 0;
    vi.stubGlobal("fetch", stubBff({
      onDetail: (publicationId) => {
        detailCalls += 1;
        if (detailCalls >= 2) return json({ code: "DELTA_PUBLICATION_EXPIRED", message: "Synthetic test: expired output" }, 404);
        return json(detailJsonFor(publicationId, payload));
      },
      onBytes: bytes.handler,
    }));
    const created: string[] = [];
    Object.defineProperty(URL, "createObjectURL", {
      value: vi.fn(() => { created.push("blob:mock"); return "blob:mock"; }),
      configurable: true,
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<DeltaPublicationPanel {...props} />);
    await reachReady();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "차분 파일 내려받기" }));
    });
    // 배지가 '사용 가능'에 머물지 않고 만료 단계로 내려간다.
    await waitFor(() => expect(screen.getByText("만료됨")).toBeTruthy());
    expect(screen.queryByText("사용 가능")).toBeNull();
    // 서술자와 내려받기 단추가 함께 거둬진다.
    expect(screen.queryByText("EPSG:5186")).toBeNull();
    expect(screen.queryByRole("button", { name: "차분 파일 내려받기" })).toBeNull();
    expect(bytes.calls).toHaveLength(0);
    expect(created).toHaveLength(0);
  });

  it.each([
    ["DELTA_PUBLICATION_REVOKED", /차분 파일이 회수되어 사용할 수 없습니다/],
    ["DELTA_PUBLICATION_SOURCE_NOT_CURRENT", /기준 계산·수치·범위 근거가 바뀌어/],
  ] as const)("drops a revoked/withdrawn pre-check to unavailable: %s", async (code, message) => {
    const payload = new Uint8Array([1, 2, 3, 4]);
    const bytes = stubBytesNeverCalled();
    let detailCalls = 0;
    vi.stubGlobal("fetch", stubBff({
      onDetail: (publicationId) => {
        detailCalls += 1;
        if (detailCalls >= 2) return json({ code, message: "Synthetic test" }, 404);
        return json(detailJsonFor(publicationId, payload));
      },
      onBytes: bytes.handler,
    }));
    const created: string[] = [];
    Object.defineProperty(URL, "createObjectURL", {
      value: vi.fn(() => { created.push("blob:mock"); return "blob:mock"; }),
      configurable: true,
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<DeltaPublicationPanel {...props} />);
    await reachReady();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "차분 파일 내려받기" }));
    });
    await waitFor(() => expect(screen.getByText("사용 불가")).toBeTruthy());
    expect(screen.getAllByText(message).length).toBeGreaterThan(0);
    expect(screen.queryByText("사용 가능")).toBeNull();
    expect(screen.queryByText("EPSG:5186")).toBeNull();
    expect(screen.queryByRole("button", { name: "차분 파일 내려받기" })).toBeNull();
    expect(bytes.calls).toHaveLength(0);
    expect(created).toHaveLength(0);
  });

  it.each([
    ["DELTA_PUBLICATION_REVOKED", "사용 불가"],
    ["DELTA_PUBLICATION_EXPIRED", "만료됨"],
  ] as const)("applies typed terminal on the post-hash check without a blob: %s", async (code, badge) => {
    const payload = new Uint8Array([1, 2, 3, 4]);
    let detailCalls = 0;
    const requestedLengths: number[] = [];
    vi.stubGlobal("fetch", stubBff({
      onDetail: (publicationId) => {
        detailCalls += 1;
        if (detailCalls >= 3) return json({ code, message: "Synthetic test" }, 404);
        return json(detailJsonFor(publicationId, payload));
      },
      onBytes: (publicationId, offset, length) => {
        requestedLengths.push(length);
        return json({ publicationId, offset, contentBase64: base64Of(payload.slice(offset, offset + length)) });
      },
    }));
    const created: string[] = [];
    Object.defineProperty(URL, "createObjectURL", {
      value: vi.fn(() => { created.push("blob:mock"); return "blob:mock"; }),
      configurable: true,
    });
    Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<DeltaPublicationPanel {...props} />);
    await reachReady();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "차분 파일 내려받기" }));
    });
    // 조각·해시는 통과했지만 마지막 확인에서 종료를 만나 파일 없이 닫는다.
    await waitFor(() => expect(detailCalls).toBeGreaterThanOrEqual(3));
    await waitFor(() => expect(screen.getByText(badge)).toBeTruthy());
    expect(requestedLengths).toEqual([4]);
    expect(screen.queryByText("사용 가능")).toBeNull();
    expect(screen.queryByRole("button", { name: "차분 파일 내려받기" })).toBeNull();
    expect(created).toHaveLength(0);
  });
});
