import { describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
  create: vi.fn(),
  list: vi.fn(),
  evidence: vi.fn(),
  mutation: vi.fn(),
}));

vi.mock("@/lib/core-api/session", () => ({ getSessionToken: mocked.session }));
vi.mock("@/lib/core-api/analysis", () => ({ createAnalysis: mocked.create, listAnalyses: mocked.list, getAnalysisEvidence: mocked.evidence }));
vi.mock("@/lib/core-api/origin-guard", () => ({ isCrossSiteMutation: mocked.mutation }));

import { POST } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/analyses/route";
import { GET as GETAnalyses } from "@/app/api/sites/[siteId]/analyses/route";
import { GET as GETEvidence } from "@/app/api/sites/[siteId]/analyses/[analysisId]/evidence/route";

describe("analysis list proxy", () => {
  it("forwards bounded V2 cursor pagination through the authenticated session", async () => {
    mocked.session.mockResolvedValue("operator-token");
    mocked.list.mockResolvedValue({ siteId: "site-1", items: [], nextCursor: "next-cursor" });
    const request = new Request("http://console.test/api/sites/site-1/analyses?limit=12&cursor=opaque_cursor-1");
    const response = await GETAnalyses(request as never, {
      params: Promise.resolve({ siteId: "site-1" }),
    });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ siteId: "site-1", items: [], nextCursor: "next-cursor" });
    expect(mocked.session).toHaveBeenCalledOnce();
    expect(mocked.list).toHaveBeenCalledWith("site-1", { limit: 12, cursor: "opaque_cursor-1" });
  });

  it.each(["limit=0", "limit=51", "limit=1&limit=2", "cursor=", `cursor=${"x".repeat(513)}`])(
    "rejects invalid V2 page query %s before Core",
    async (query) => {
      mocked.session.mockResolvedValue("operator-token");
      mocked.list.mockReset();
      const response = await GETAnalyses(
        new Request(`http://console.test/api/sites/site-1/analyses?${query}`) as never,
        { params: Promise.resolve({ siteId: "site-1" }) },
      );
      expect(response.status).toBe(400);
      expect(mocked.list).not.toHaveBeenCalled();
    },
  );
});

describe("analysis evidence proxy", () => {
  it("forwards bounded evidence pagination through the authenticated session", async () => {
    mocked.session.mockResolvedValue("operator-token");
    mocked.evidence.mockResolvedValue({ analysisId: "analysis-1", evidenceRevision: 2, evidenceDigest: "sha256:abc", items: [], nextCursor: null });
    const response = await GETEvidence(
      new Request("http://console.test/api/sites/site-1/analyses/analysis-1/evidence?limit=7&cursor=opaque_cursor-2") as never,
      { params: Promise.resolve({ siteId: "site-1", analysisId: "analysis-1" }) },
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ analysisId: "analysis-1", evidenceRevision: 2 });
    expect(mocked.evidence).toHaveBeenCalledWith("site-1", "analysis-1", { limit: 7, cursor: "opaque_cursor-2" });
  });

  it.each(["limit=0", "limit=33", "limit=1&limit=2", "cursor=", `cursor=${"x".repeat(513)}`])(
    "rejects invalid evidence page query %s before Core",
    async (query) => {
      mocked.session.mockResolvedValue("operator-token");
      mocked.evidence.mockReset();
      const response = await GETEvidence(
        new Request(`http://console.test/api/sites/site-1/analyses/analysis-1/evidence?${query}`) as never,
        { params: Promise.resolve({ siteId: "site-1", analysisId: "analysis-1" }) },
      );
      expect(response.status).toBe(400);
      expect(mocked.evidence).not.toHaveBeenCalled();
    },
  );
});

describe("analysis create proxy", () => {
  it("rejects a cross-site mutation before Core and forwards only a same-origin selector request", async () => {
    mocked.session.mockResolvedValue("operator-token");
    mocked.mutation.mockReturnValueOnce(true).mockReturnValueOnce(false);
    mocked.create.mockResolvedValue({ analysisId: "analysis-1" });
    const crossSite = new Request("http://console.test/api/sites/site-1/work-areas/area-1/analyses", {
      method: "POST",
      headers: { origin: "https://elsewhere.test", "content-type": "application/json", "Idempotency-Key": "analysis-attempt-1" },
      body: JSON.stringify({ baseline: { workOrderId: "a", submissionRef: `ers-v1-${"a".repeat(64)}`, revision: 1 }, current: { workOrderId: "b", submissionRef: `ers-v1-${"b".repeat(64)}`, revision: 1 } }),
    });
    const denied = await POST(crossSite as never, { params: Promise.resolve({ siteId: "site-1", workAreaId: "area-1" }) });
    expect(denied.status).toBe(403);
    expect(mocked.create).not.toHaveBeenCalled();

    const sameOrigin = new Request("http://console.test/api/sites/site-1/work-areas/area-1/analyses", {
      method: "POST",
      headers: { origin: "http://console.test", "content-type": "application/json", "Idempotency-Key": "analysis-attempt-1" },
      body: JSON.stringify({ baseline: { workOrderId: "a", submissionRef: `ers-v1-${"a".repeat(64)}`, revision: 1 }, current: { workOrderId: "b", submissionRef: `ers-v1-${"b".repeat(64)}`, revision: 1 } }),
    });
    const accepted = await POST(sameOrigin as never, { params: Promise.resolve({ siteId: "site-1", workAreaId: "area-1" }) });
    expect(accepted.status).toBe(202);
    expect(mocked.create).toHaveBeenCalledWith("site-1", "area-1", expect.any(Object), "analysis-attempt-1");
  });

  it("rejects malformed selector requests and oversized idempotency keys before Core", async () => {
    mocked.session.mockResolvedValue("operator-token");
    mocked.mutation.mockReturnValue(false);
    mocked.create.mockReset();
    const makeRequest = (key: string, body: unknown) => new Request(
      "http://console.test/api/sites/site-1/work-areas/area-1/analyses",
      {
        method: "POST",
        headers: { origin: "http://console.test", "content-type": "application/json", "Idempotency-Key": key },
        body: JSON.stringify(body),
      },
    );
    const body = {
      baseline: { workOrderId: "work-a", submissionRef: `ers-v1-${"a".repeat(64)}`, revision: 1 },
      current: { workOrderId: "work-b", submissionRef: `ers-v1-${"b".repeat(64)}`, revision: 1 },
    };
    const tooLongKey = await POST(makeRequest("k".repeat(256), body) as never, {
      params: Promise.resolve({ siteId: "site-1", workAreaId: "area-1" }),
    });
    const malformedBody = await POST(makeRequest("stable-key", { ...body, extra: true }) as never, {
      params: Promise.resolve({ siteId: "site-1", workAreaId: "area-1" }),
    });
    expect(tooLongKey.status).toBe(400);
    expect(malformedBody.status).toBe(400);
    expect(mocked.create).not.toHaveBeenCalled();
  });

  it("stops reading a chunked create body as soon as it exceeds the byte limit", async () => {
    mocked.session.mockResolvedValue("operator-token");
    mocked.mutation.mockReturnValue(false);
    mocked.create.mockReset();
    let pulls = 0;
    let cancelled = false;
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        pulls += 1;
        if (pulls === 1) controller.enqueue(new Uint8Array(10_000).fill(32));
        else if (pulls === 2) controller.enqueue(new Uint8Array(6_385).fill(32));
        else {
          controller.enqueue(new TextEncoder().encode('{"unexpected":"tail"}'));
          controller.close();
        }
      },
      cancel() { cancelled = true; },
    }, { highWaterMark: 0 });
    const request = new Request("http://console.test/api/sites/site-1/work-areas/area-1/analyses", {
      method: "POST",
      headers: { origin: "http://console.test", "content-type": "application/json", "Idempotency-Key": "stable-key" },
      body,
      duplex: "half",
    } as RequestInit);

    const response = await POST(request as never, {
      params: Promise.resolve({ siteId: "site-1", workAreaId: "area-1" }),
    });

    expect(response.status).toBe(413);
    expect(pulls).toBe(2);
    expect(cancelled).toBe(true);
    expect(mocked.create).not.toHaveBeenCalled();
  });
});
