import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  session: vi.fn(),
  target: vi.fn(),
  list: vi.fn(),
  create: vi.fn(),
  crossSite: vi.fn(),
  coreError: vi.fn(() => new Response(JSON.stringify({ message: "Core error" }), { status: 503 })),
}));

vi.mock("@/lib/core-api/session", () => ({ getSessionToken: mocked.session }));
vi.mock("@/lib/core-api/analysis", () => ({
  getAnalysisReviewTarget: mocked.target,
  listAnalysisReviews: mocked.list,
  createAnalysisReview: mocked.create,
}));
vi.mock("@/lib/core-api/origin-guard", () => ({ isCrossSiteMutation: mocked.crossSite }));
vi.mock("@/lib/core-api/route-handler-util", () => ({ coreApiErrorResponse: mocked.coreError }));

import { GET, POST } from "@/app/api/sites/[siteId]/analyses/[analysisId]/reviews/route";

const context = { params: Promise.resolve({ siteId: "site-1", analysisId: "analysis-1" }) };
const target = {
  resultId: "result-1",
  resultRevision: 1,
  reportDigest: `sha256:${"a".repeat(64)}`,
  numericResultIdentityDigest: `sha256:${"b".repeat(64)}`,
  calculationIdentityDigest: `sha256:${"c".repeat(64)}`,
  admissionDigest: `sha256:${"d".repeat(64)}`,
  evaluations: [
    { epoch: "BASELINE", evaluationId: "eval-baseline", revision: 1, evaluationDigest: `sha256:${"e".repeat(64)}` },
    { epoch: "CURRENT", evaluationId: "eval-current", revision: 2, evaluationDigest: `sha256:${"f".repeat(64)}` },
  ],
};
const receipt = {
  reviewRef: `arv2-${"1".repeat(64)}`,
  reviewerId: "operator-1",
  decision: "ACKNOWLEDGED",
  comment: "확인했습니다.",
  reviewedAt: "2026-10-15T10:00:00Z",
  receiptDigest: `sha256:${"2".repeat(64)}`,
  target,
  factualLimitations: ["HUMAN_REVIEW_IS_NOT_ACCURACY_VALIDATION"],
};

function post(body: unknown, headers: Record<string, string> = {}) {
  return new Request("http://console.test/api/sites/site-1/analyses/analysis-1/reviews", {
    method: "POST",
    headers: { origin: "http://console.test", host: "console.test", "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue("operator-token");
  mocked.crossSite.mockReturnValue(false);
  mocked.target.mockResolvedValue(target);
  mocked.list.mockResolvedValue({ items: [receipt], nextCursor: null });
  mocked.create.mockResolvedValue(receipt);
  mocked.coreError.mockImplementation(() => new Response(JSON.stringify({ message: "Core error" }), { status: 503 }));
});

describe("analysis review proxy", () => {
  it("returns bounded historical reviews with the separately resolved current target", async () => {
    const response = await GET(new Request("http://console.test/api/sites/site-1/analyses/analysis-1/reviews") as never, context);

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ target, items: [receipt], nextCursor: null });
    expect(mocked.session).toHaveBeenCalledOnce();
    expect(mocked.target).toHaveBeenCalledWith("site-1", "analysis-1");
    expect(mocked.list).toHaveBeenCalledWith("site-1", "analysis-1", { limit: 50 });
  });

  it("fetches a fresh target and generates the Core idempotency key on the server", async () => {
    const response = await POST(post({ decision: "ACKNOWLEDGED", comment: "  확인했습니다.  " }, { "Idempotency-Key": "browser-key-must-not-be-forwarded" }) as never, context);

    expect(response.status).toBe(201);
    expect(await response.json()).toEqual(receipt);
    expect(mocked.target).toHaveBeenCalledWith("site-1", "analysis-1");
    expect(mocked.create).toHaveBeenCalledWith(
      "site-1",
      "analysis-1",
      target,
      { decision: "ACKNOWLEDGED", comment: "확인했습니다." },
      expect.stringMatching(/^analysis-review-[0-9a-f-]{36}$/),
    );
    expect(mocked.create.mock.calls[0]?.[4]).not.toBe("browser-key-must-not-be-forwarded");
  });

  it("rejects cross-site mutations before session or Core access", async () => {
    mocked.crossSite.mockReturnValue(true);

    const response = await POST(post({ decision: "ACKNOWLEDGED", comment: "확인" }) as never, context);

    expect(response.status).toBe(403);
    expect(mocked.session).not.toHaveBeenCalled();
    expect(mocked.target).not.toHaveBeenCalled();
    expect(mocked.create).not.toHaveBeenCalled();
  });

  it.each([
    [{ decision: "UNKNOWN", comment: "확인" }],
    [{ decision: "ACKNOWLEDGED", comment: "   " }],
    [{ decision: "ACKNOWLEDGED", comment: "x".repeat(1_001) }],
    [{ decision: "ACKNOWLEDGED", comment: "확인", target }],
  ])("rejects browser input outside the decision/comment DTO: %j", async (body) => {
    const response = await POST(post(body) as never, context);

    expect(response.status).toBe(400);
    expect(mocked.target).not.toHaveBeenCalled();
    expect(mocked.create).not.toHaveBeenCalled();
  });

  it("maps Core errors through the shared route error shape", async () => {
    const error = new Error("Core review target changed");
    mocked.target.mockRejectedValue(error);

    const response = await POST(post({ decision: "ACKNOWLEDGED", comment: "확인" }) as never, context);

    expect(response.status).toBe(503);
    expect(mocked.coreError).toHaveBeenCalledWith(error);
    expect(mocked.create).not.toHaveBeenCalled();
  });
});
