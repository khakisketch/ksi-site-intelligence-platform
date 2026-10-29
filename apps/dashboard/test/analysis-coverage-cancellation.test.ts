import { createHash } from "node:crypto";
import { expect, it, vi } from "vitest";

vi.mock("@/lib/core-api/session", () => ({ getSessionToken: async () => "generated-session" }));
vi.mock("@/lib/core-api/env", () => ({ coreApiBaseUrl: () => "http://core.test" }));
import { getAnalysisCoverage } from "@/lib/core-api/analysis-coverage";

it("cancels the real metadata/evidence client chain as well as range reads", async () => {
  const wire = { contractVersion:"external-relative-volume-coverage-witness.v2", rows:1,columns:1,rowOffset:0,columnOffset:0,
    selectedMaskB64:"gA==",commonValidMaskB64:"gA==",unavailableMaskB64:"AA==",thresholdExcludedMaskB64:"AA==",
    selectedCellCount:1,commonValidCellCount:1,unavailableCellCount:0,thresholdExcludedCellCount:0,cellAreaM2:1,selectedAreaM2:1,commonValidAreaM2:1,
    bounds:[0,0,1,1],coverageWitnessDigest:`sha256:${"a".repeat(64)}` };
  const payload = new TextEncoder().encode(JSON.stringify(wire));
  const digest = `sha256:${createHash("sha256").update(payload).digest("hex")}`;
  let started!: () => void, release!: (error: Error) => void;
  const evidenceStarted = new Promise<void>((done) => { started = done; });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    if (url.includes("/evidence")) return new Promise<Response>((_resolve, reject) => {
      release = reject; started();
      init.signal?.addEventListener("abort", () => reject(new DOMException("Canceled", "AbortError")), { once:true });
    });
    if (!url.endsWith("/coverage")) return new Response(JSON.stringify({siteId:"site-1",analysisId:"analysis-1",workAreaId:"area-1",executionState:"COMPLETED",
      suitabilityState:"PROVISIONAL_ACCURACY_UNVERIFIED",evidenceDigest:"evidence-1",result:{resultId:"result-1",reportDigest:digest,numericResultIdentityDigest:digest,coverage:wire}}),{headers:{"Content-Type":"application/json"}});
    const [,a,b] = /^bytes=(\d+)-(\d+)$/.exec(new Headers(init.headers).get("Range")!)!;
    const start=Number(a),end=Number(b);
    return new Response(payload.slice(start,end+1),{status:206,headers:{"Content-Type":"application/vnd.ksi.analysis-coverage+json",
      "Content-Length":String(end-start+1),"Content-Range":`bytes ${start}-${end}/${payload.length}`,"X-KSI-Coverage-Total-Length":String(payload.length),"X-KSI-Coverage-Digest":digest}});
  }));
  const controller = new AbortController();
  const pending = getAnalysisCoverage("site-1","analysis-1",controller.signal).then(() => "resolved", error => error.status);
  try {
    await evidenceStarted;
    controller.abort();
    const outcome = await Promise.race([pending, new Promise((done) => setTimeout(() => done("still-running"), 50))]);
    expect(outcome).toBe(504);
  } finally { release(new Error("test cleanup")); await pending; vi.unstubAllGlobals(); }
});
