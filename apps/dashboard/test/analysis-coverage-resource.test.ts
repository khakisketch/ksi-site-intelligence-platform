import { createHash } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ session: vi.fn(), detail: vi.fn(), evidence: vi.fn() }));
vi.mock("@/lib/core-api/session", () => ({ getSessionToken: mocks.session }));
vi.mock("@/lib/core-api/analysis", () => ({ getAnalysis: mocks.detail, getAnalysisEvidence: mocks.evidence }));
vi.mock("@/lib/core-api/env", () => ({ coreApiBaseUrl: () => "http://core.test" }));

import { getAnalysisCoverage } from "@/lib/core-api/analysis-coverage";

const witness = {
  contractVersion: "external-relative-volume-coverage-witness.v2",
  rows: 2, columns: 2, rowOffset: 0, columnOffset: 0,
  selectedMaskB64: "8A==", commonValidMaskB64: "8A==", unavailableMaskB64: "AA==", thresholdExcludedMaskB64: "AA==",
  selectedCellCount: 4, commonValidCellCount: 4, unavailableCellCount: 0, thresholdExcludedCellCount: 0,
  cellAreaM2: 1, selectedAreaM2: 4, commonValidAreaM2: 4, bounds: [0, 0, 2, 2],
  coverageWitnessDigest: `sha256:${"a".repeat(64)}`,
};
const payload = new TextEncoder().encode(JSON.stringify(witness));
const digest = `sha256:${createHash("sha256").update(payload).digest("hex")}`;
const detail = {
  siteId: "site-1", workAreaId: "area-1", analysisId: "analysis-1", executionState: "COMPLETED",
  suitabilityState: "PROVISIONAL_ACCURACY_UNVERIFIED", evidenceDigest: "evidence-1",
  baseline: { workOrderId: "work-a", submissionRef: "submission-a", revision: 1 },
  result: { resultId: "result-1", reportDigest: `sha256:${"b".repeat(64)}`,
    numericResultIdentityDigest: `sha256:${"c".repeat(64)}`, metrics: { thresholdM: 0 },
    coverage: { ...witness } },
};

function rangeFetch(override?: (start: number, end: number, response: Response) => Response) {
  mocks.evidence.mockResolvedValue({ analysisId: "analysis-1", evidenceDigest: "evidence-1", items: [{
    kind: "EPOCH_IDENTITY", epoch: "BASELINE", selector: detail.baseline,
    observedCrsIdentifier: "EPSG:5186", transform: [1,0,0,0,-1,2],
  }] });
  return vi.fn(async (_url: string, init: RequestInit) => {
    const range = new Headers(init.headers).get("Range")!;
    const [, a, b] = /^bytes=(\d+)-(\d+)$/.exec(range)!;
    const start = Number(a), end = Number(b);
    const response = new Response(payload.slice(start, end + 1), { status: 206, headers: {
      "Content-Type": "application/vnd.ksi.analysis-coverage+json",
      "Content-Range": `bytes ${start}-${end}/${payload.length}`,
      "Content-Length": String(end - start + 1), "X-KSI-Coverage-Total-Length": String(payload.length),
      "X-KSI-Coverage-Digest": digest,
    } });
    return override?.(start, end, response) ?? response;
  });
}

afterEach(() => { vi.unstubAllGlobals(); vi.resetAllMocks(); });

describe("bounded authenticated coverage reader", () => {
  it("discovers one byte then fetches exact bounded ranges, verifies bytes and rechecks the same current result", async () => {
    mocks.session.mockResolvedValue("human-session");
    mocks.detail.mockResolvedValue(detail);
    const fetch = rangeFetch(); vi.stubGlobal("fetch", fetch);
    expect(await getAnalysisCoverage("site-1", "analysis-1")).toMatchObject({
      siteId: "site-1", analysisId: "analysis-1", resultId: "result-1", coverage: witness,
    });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[0]![0]).toBe("http://core.test/v2/sites/site-1/analyses/analysis-1/coverage");
    expect(new Headers(fetch.mock.calls[0]![1].headers).get("Range")).toBe("bytes=0-0");
    expect(fetch.mock.calls.every(([, init]) => init.cache === "no-store" && init.redirect === "error")).toBe(true);
    expect(mocks.detail).toHaveBeenCalledTimes(2);
  });

  it.each(["digest", "range", "length", "body", "total"])('refuses a changed or malformed %s', async (kind) => {
    mocks.session.mockResolvedValue("human-session"); mocks.detail.mockResolvedValue(detail);
    vi.stubGlobal("fetch", rangeFetch((start, _end, response) => {
      if (kind === "digest") response.headers.set("X-KSI-Coverage-Digest", `sha256:${"d".repeat(64)}`);
      if (kind === "range") response.headers.set("Content-Range", `bytes 4-4/${payload.length}`);
      if (kind === "length") response.headers.set("Content-Length", "99999");
      if (kind === "total") response.headers.set("X-KSI-Coverage-Total-Length", "999999999");
      if (kind === "body" && start > 0) return new Response(new Uint8Array(payload.length - 1).fill(32), { status: 206, headers: response.headers });
      return response;
    }));
    await expect(getAnalysisCoverage("site-1", "analysis-1")).rejects.toThrow();
  });

  it("withholds masks if currentness or scope is lost during the read", async () => {
    mocks.session.mockResolvedValue("human-session");
    mocks.detail.mockResolvedValueOnce(detail).mockResolvedValueOnce({ ...detail, result: null });
    vi.stubGlobal("fetch", rangeFetch());
    await expect(getAnalysisCoverage("site-1", "analysis-1")).rejects.toMatchObject({ status: 409 });
  });

  it.each(["..", "x/y", "https://elsewhere.test", "x?bypass=1", "x#fragment"])("rejects non-resource identifiers %s before Core", async (id) => {
    await expect(getAnalysisCoverage(id, "analysis-1")).rejects.toMatchObject({ status: 400 });
    expect(mocks.detail).not.toHaveBeenCalled();
  });

  it("rejects a changed digest between slices before reassembling", async () => {
    mocks.session.mockResolvedValue("human-session"); mocks.detail.mockResolvedValue(detail);
    vi.stubGlobal("fetch", rangeFetch((start, _end, response) => {
      if (start > 0) response.headers.set("X-KSI-Coverage-Digest", `sha256:${"d".repeat(64)}`);
      return response;
    }));
    await expect(getAnalysisCoverage("site-1", "analysis-1")).rejects.toMatchObject({ status: 502 });
  });

  it("cancels an oversized streaming body instead of buffering it", async () => {
    mocks.session.mockResolvedValue("human-session"); mocks.detail.mockResolvedValue(detail);
    let canceled = false;
    vi.stubGlobal("fetch", rangeFetch((_start, _end, response) => new Response(new ReadableStream({
      start(controller) { controller.enqueue(new Uint8Array(2)); }, cancel() { canceled = true; },
    }), { status: 206, headers: response.headers })));
    await expect(getAnalysisCoverage("site-1", "analysis-1")).rejects.toThrow();
    expect(canceled).toBe(true);
  });

  it("does not follow a resource redirect or expose its body", async () => {
    mocks.session.mockResolvedValue("human-session"); mocks.detail.mockResolvedValue(detail);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("private upstream content", { status: 302, headers: { Location: "https://untrusted.test" } })));
    await expect(getAnalysisCoverage("site-1", "analysis-1")).rejects.toMatchObject({ status: 502 });
  });

  it("retains the grid without inventing a map reference when source geometry is absent", async () => {
    mocks.session.mockResolvedValue("human-session"); mocks.detail.mockResolvedValue(detail);
    vi.stubGlobal("fetch", rangeFetch());
    mocks.evidence.mockResolvedValue({analysisId:"analysis-1",evidenceDigest:"evidence-1",items:[]});
    expect((await getAnalysisCoverage("site-1","analysis-1")).gridReference).toBeNull();
  });

  it("refuses geometry from a different evidence revision", async () => {
    mocks.session.mockResolvedValue("human-session"); mocks.detail.mockResolvedValue(detail);
    vi.stubGlobal("fetch", rangeFetch());
    mocks.evidence.mockResolvedValue({analysisId:"analysis-1",evidenceDigest:"evidence-2",items:[]});
    await expect(getAnalysisCoverage("site-1","analysis-1")).rejects.toMatchObject({status:409});
  });

  it("never opens resource bytes for a blocked, foreign-scope or oversized summary", async () => {
    mocks.session.mockResolvedValue("human-session");
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    for (const response of [{ ...detail, result: null }, { ...detail, siteId: "foreign" },
      { ...detail, result: { ...detail.result, coverage: { ...witness, rows: 1e9 } } }]) {
      mocks.detail.mockResolvedValue(response);
      await expect(getAnalysisCoverage("site-1", "analysis-1")).rejects.toThrow();
    }
    expect(fetch).not.toHaveBeenCalled();
  });
});
