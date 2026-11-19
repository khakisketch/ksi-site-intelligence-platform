import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { CoreApiError } from "@/lib/core-api/client";

const mocked = vi.hoisted(() => ({ session: vi.fn(), request: vi.fn(), read: vi.fn(), origin: vi.fn() }));
vi.mock("@/lib/core-api/session", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/session")>();
  return { ...actual, getSessionToken: mocked.session };
});
vi.mock("@/lib/core-api/measurement", () => ({
  requestSurfaceProfileComparisonWithToken: mocked.request,
  getSurfaceProfileComparisonWithToken: mocked.read,
}));
vi.mock("@/lib/core-api/origin-guard", () => ({ isCrossSiteMutation: mocked.origin }));

import {
  GET,
  POST,
} from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/surface-profile-comparisons/route";

const baselineJobId = "spj-" + "1".repeat(32);
const currentJobId = "spj-" + "2".repeat(32);
const ctx = () => ({ params: Promise.resolve({ siteId: "site 1", workAreaId: "area/1" }) });
const post = (body: unknown, key = "compare-1") => new NextRequest("http://console.test/api", {
  method: "POST",
  headers: { origin: "http://console.test", host: "console.test", "content-type": "application/json", "Idempotency-Key": key },
  body: JSON.stringify(body),
});
const response = {
  contractVersion: "surface-profile-comparison.v1", baselineJobId, currentJobId, decisionId: "decision-1",
  decisionDigest: `sha256:${"a".repeat(64)}`, verdict: "BLOCKED", reasons: ["POLICY_UNAVAILABLE"],
  remediations: ["AUTHORIZE_POLICY"], result: null,
};

beforeEach(() => {
  vi.resetAllMocks();
  mocked.origin.mockReturnValue(false);
  mocked.session.mockResolvedValue("session-token");
  mocked.request.mockResolvedValue(response);
  mocked.read.mockResolvedValue(response);
});

describe("두 시점 단면 비교 BFF", () => {
  it("명시된 POST만 Core에 보내고 저장된 두 작업 식별자와 멱등 키를 전달한다", async () => {
    const res = await POST(post({ baselineJobId, currentJobId }), ctx());
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(response);
    expect(mocked.request).toHaveBeenCalledWith("site 1", "area/1", { baselineJobId, currentJobId }, "compare-1", "session-token");
  });

  it.each([
    [{ baselineJobId, currentJobId, verdict: "ELIGIBLE" }],
    [{ baselineJobId, currentJobId: baselineJobId }],
    [{ baselineJobId: "other", currentJobId }],
  ])("거짓 작업·임의 결과 필드를 가진 POST는 거부한다", async (body) => {
    expect((await POST(post(body), ctx())).status).toBe(422);
    expect(mocked.request).not.toHaveBeenCalled();
  });

  it("현재 세션으로 저장된 같은 비교를 읽는다", async () => {
    const req = new NextRequest(
      "http://console.test/api?baseline_job_id=" + baselineJobId + "&current_job_id=" + currentJobId + "&decision_id=decision-1",
    );
    const res = await GET(req, ctx());
    expect(res.status).toBe(200);
    expect(mocked.read).toHaveBeenCalledWith("site 1", "area/1", { baselineJobId, currentJobId, decisionId: "decision-1" }, "session-token");
  });

  it("잘못된 조회 식별자는 Core로 보내지 않는다", async () => {
    const req = new NextRequest("http://console.test/api?baseline_job_id=x&current_job_id=" + currentJobId + "&decision_id=decision-1");
    expect((await GET(req, ctx())).status).toBe(400);
    expect(mocked.read).not.toHaveBeenCalled();
  });

  it("검증 불가 응답은 Core의 표준 거부 코드로 돌려준다", async () => {
    mocked.request.mockRejectedValue(new CoreApiError(422, { reason: "PLAN_MISMATCH", message: "x", retryable: false, remediation: ["CONTACT_OPERATOR"] }));
    const res = await POST(post({ baselineJobId, currentJobId }), ctx());
    expect(res.status).toBe(422);
    expect((await res.json()).code).toBe("PLAN_MISMATCH");
  });
});
