import { beforeEach, describe, expect, it, vi } from "vitest";

import { CoreApiError } from "@/lib/core-api/client";

const mocked = vi.hoisted(() => ({ session: vi.fn(), decide: vi.fn(), issue: vi.fn(), cancel: vi.fn(), result: vi.fn(), origin: vi.fn() }));
vi.mock("@/lib/core-api/session", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/session")>();
  return { ...actual, getSessionToken: mocked.session };
});
vi.mock("@/lib/core-api/measurement", () => ({
  requestAssetHeightDecisionWithToken: mocked.decide,
  issueSurfaceProfileJobWithToken: mocked.issue,
  cancelSurfaceProfileJobWithToken: mocked.cancel,
  getSurfaceProfileResult: mocked.result,
}));
vi.mock("@/lib/core-api/origin-guard", () => ({ isCrossSiteMutation: mocked.origin }));

import { POST as cancelPost } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/surface-profile-jobs/[jobId]/cancel/route";
import { GET as resultGet } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/surface-profile-jobs/[jobId]/result/route";
import { POST as requestPost } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/surface-profile-requests/route";

const ASSET = `ksa-v1-${"a".repeat(64)}`;
const FEATURE = { featureId: `mf-${"1".repeat(32)}`, revision: 2, lineDigest: `sha256:${"b".repeat(64)}` };
const JOB_ID = `spj-${"2".repeat(32)}`;

describe("현재 권한으로 단일 단면 다시 읽기", () => {
  const get = () => new Request("http://console.test/api") as Parameters<typeof resultGet>[0];
  it("정확한 결과만 캐시 없이 반환하고 다른 구역 응답을 거부한다", async () => {
    const view = {
      job: { jobId: JOB_ID, siteId: "site 1", workAreaId: "area/1", assetRef: ASSET, feature: FEATURE, executionState: "COMPLETED", availability: "AVAILABLE" },
      result: { feature: FEATURE, assetRef: ASSET, lineDigest: FEATURE.lineDigest, resultDigest: `sha256:${"d".repeat(64)}` },
    };
    mocked.result.mockResolvedValueOnce(view);
    const allowed = await resultGet(get(), ctx());
    expect(allowed.status).toBe(200);
    expect(allowed.headers.get("cache-control")).toContain("no-store");
    mocked.result.mockResolvedValueOnce({ ...view, job: { ...view.job, workAreaId: "other" } });
    const changed = await resultGet(get(), ctx());
    expect(changed.status).toBe(502);
    expect(await changed.text()).not.toContain("resultDigest");
  });

  it("현재 읽기 권한이 거절되면 수치를 반환하지 않는다", async () => {
    mocked.result.mockRejectedValueOnce(new CoreApiError(403, { reason: "ACCESS_REVOKED" }));
    const denied = await resultGet(get(), ctx());
    expect(denied.status).toBe(403);
    expect(await denied.text()).not.toContain("samples");
  });
});
const ctx = (extra: Record<string, string> = {}) => ({ params: Promise.resolve({ siteId: "site 1", workAreaId: "area/1", jobId: JOB_ID, ...extra }) });
const post = (body: unknown, key: string | null = "req-1") => new Request("http://console.test/api", {
  method: "POST",
  headers: { origin: "http://console.test", host: "console.test", "content-type": "application/json", ...(key ? { "Idempotency-Key": key } : {}) },
  body: typeof body === "string" ? body : JSON.stringify(body),
}) as never;
const body = { assetRef: ASSET, feature: FEATURE };
const eligible = { decisionId: "external-use-decision-1", verdict: "ELIGIBLE", reasons: ["HEIGHT_ELIGIBLE"], remediations: [] };
const job = { jobId: JOB_ID };

beforeEach(() => {
  vi.resetAllMocks();
  mocked.origin.mockReturnValue(false);
  mocked.session.mockResolvedValue("token");
  mocked.decide.mockResolvedValue(eligible);
  mocked.issue.mockResolvedValue(job);
  mocked.cancel.mockResolvedValue(job);
});

describe("단면 요청 BFF", () => {
  it("판정을 받은 뒤 그 판정으로 작업을 만들고, 두 쓰기에 서로 다른 파생 키를 쓴다", async () => {
    const response = await requestPost(post(body), ctx());
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ job });
    expect(mocked.decide).toHaveBeenCalledWith("site 1", "area/1", ASSET, "req-1:height", "token");
    expect(mocked.issue).toHaveBeenCalledWith("site 1", "area/1", { assetRef: ASSET, feature: FEATURE, heightDecisionId: "external-use-decision-1" }, "req-1:job", "token");
  });

  it("선택된 자료의 정확한 저장 선 개정으로 표본 간격을 Core 작업 생성까지 전달한다", async () => {
    const response = await requestPost(post({ ...body, sampleSpacingM: 2.5 }), ctx());
    expect(response.status).toBe(200);
    expect(mocked.issue).toHaveBeenCalledWith(
      "site 1", "area/1",
      { assetRef: ASSET, feature: FEATURE, heightDecisionId: "external-use-decision-1", sampleSpacingM: 2.5 },
      "req-1:job", "token",
    );
  });

  it("판정이 막히면 작업을 만들지 않고 사유를 그대로 돌려준다", async () => {
    mocked.decide.mockResolvedValue({ decisionId: "d", verdict: "BLOCKED", reasons: ["VERTICAL_REFERENCE_UNKNOWN"], remediations: ["OBSERVE_VERTICAL_REFERENCE"] });
    const response = await requestPost(post(body), ctx());
    expect(response.status).toBe(409);
    const value = await response.json();
    expect(value.code).toBe("HEIGHT_NOT_ELIGIBLE");
    expect(value.decision).toEqual({ verdict: "BLOCKED", reasons: ["VERTICAL_REFERENCE_UNKNOWN"], remediations: ["OBSERVE_VERTICAL_REFERENCE"] });
    expect(mocked.issue).not.toHaveBeenCalled();
  });

  it("제한적 판정(RESTRICTED)도 읽기 근거로 쓰지 않는다", async () => {
    mocked.decide.mockResolvedValue({ ...eligible, verdict: "RESTRICTED" });
    expect((await requestPost(post(body), ctx())).status).toBe(409);
    expect(mocked.issue).not.toHaveBeenCalled();
  });

  it("다른 출처의 요청은 Core를 부르지 않고 막는다", async () => {
    mocked.origin.mockReturnValue(true);
    expect((await requestPost(post(body), ctx())).status).toBe(403);
    expect((await cancelPost(post({}), ctx())).status).toBe(403);
    expect(mocked.decide).not.toHaveBeenCalled();
    expect(mocked.cancel).not.toHaveBeenCalled();
  });

  it("형식이 틀린 본문·키는 Core에 보내지 않는다(판정 식별자를 클라이언트가 정하지 못한다)", async () => {
    for (const bad of [
      { ...body, heightDecisionId: "d" },
      { assetRef: "x", feature: FEATURE },
      { assetRef: ASSET, feature: { ...FEATURE, revision: 0 } },
      { assetRef: ASSET, feature: { ...FEATURE, featureId: "x" } },
      { assetRef: ASSET, feature: { ...FEATURE, lineDigest: "x" } },
      { assetRef: ASSET, feature: { ...FEATURE, extra: 1 } },
      { assetRef: ASSET },
      null,
    ]) {
      expect((await requestPost(post(bad), ctx())).status, JSON.stringify(bad)).toBe(422);
    }
    expect((await requestPost(post(body, null), ctx())).status).toBe(400);
    expect((await requestPost(post(body, "bad key"), ctx())).status).toBe(400);
    expect((await requestPost(post(body, "k".repeat(241)), ctx())).status).toBe(400);
    expect((await requestPost(post("{nope"), ctx())).status).toBe(400);
    expect(mocked.decide).not.toHaveBeenCalled();
    expect(mocked.issue).not.toHaveBeenCalled();
  });

  it("세션이 없으면 Core를 부르지 않고 401이다", async () => {
    const { MissingSessionError } = await import("@/lib/core-api/session");
    mocked.session.mockRejectedValue(new MissingSessionError());
    expect((await requestPost(post(body), ctx())).status).toBe(401);
    expect(mocked.decide).not.toHaveBeenCalled();
  });

  it("Core의 거부는 상태와 코드를 그대로 전한다", async () => {
    mocked.decide.mockRejectedValue(new CoreApiError(404, { detail: "자료를 찾을 수 없다" }));
    expect((await requestPost(post(body), ctx())).status).toBe(404);
    mocked.decide.mockResolvedValue(eligible);
    mocked.issue.mockRejectedValue(new CoreApiError(422, { reason: "LINE_OUTSIDE_SURFACE", message: "x", retryable: false, remediation: ["CONTACT_OPERATOR"] }));
    const response = await requestPost(post(body), ctx());
    expect(response.status).toBe(422);
    expect((await response.json()).code).toBe("LINE_OUTSIDE_SURFACE");
  });

  it("높이 판정 뒤 단면 작업에 필요한 읽기 범위가 승인되지 않으면 GRANT_REQUIRED를 전한다", async () => {
    mocked.decide.mockResolvedValue(eligible);
    mocked.issue.mockRejectedValue(new CoreApiError(403, {
      reason: "GRANT_REQUIRED",
      message: "단면 작업을 사용할 수 없습니다.",
      retryable: false,
      remediation: ["CONTACT_OPERATOR"],
    }));
    const response = await requestPost(post(body), ctx());
    expect(response.status).toBe(403);
    expect((await response.json()).code).toBe("GRANT_REQUIRED");
  });
});

describe("단면 취소 BFF", () => {
  it("작업을 취소한다", async () => {
    const response = await cancelPost(post({}), ctx());
    expect(response.status).toBe(200);
    expect(mocked.cancel).toHaveBeenCalledWith("site 1", "area/1", JOB_ID, "token");
  });
  it("작업 식별자 형식이 틀리면 Core에 보내지 않는다", async () => {
    expect((await cancelPost(post({}), ctx({ jobId: "x" }))).status).toBe(400);
    expect(mocked.cancel).not.toHaveBeenCalled();
  });
  it("Core의 거부는 그대로 전한다", async () => {
    mocked.cancel.mockRejectedValue(new CoreApiError(409, { reason: "INVALID_STATE", message: "x", retryable: false, remediation: ["CONTACT_OPERATOR"] }));
    expect((await cancelPost(post({}), ctx())).status).toBe(409);
  });
});
