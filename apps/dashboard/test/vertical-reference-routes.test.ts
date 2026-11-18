import { beforeEach, describe, expect, it, vi } from "vitest";

import { CoreApiError } from "@/lib/core-api/client";

const mocked = vi.hoisted(() => ({ session: vi.fn(), declare: vi.fn(), withdraw: vi.fn(), origin: vi.fn() }));
vi.mock("@/lib/core-api/session", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/session")>();
  return { ...actual, getSessionToken: mocked.session };
});
vi.mock("@/lib/core-api/vertical-reference", () => ({
  declareVerticalReferenceWithToken: mocked.declare,
  withdrawVerticalReferenceWithToken: mocked.withdraw,
}));
vi.mock("@/lib/core-api/origin-guard", () => ({ isCrossSiteMutation: mocked.origin }));

import { POST as declarePost } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/spatial-assets/[assetRef]/vertical-reference/declarations/route";
import { POST as withdrawPost } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/spatial-assets/[assetRef]/vertical-reference/withdrawals/route";

const ASSET = `ksa-v1-${"a".repeat(64)}`;
const context = (assetRef = ASSET) => ({ params: Promise.resolve({ siteId: "site 1", workAreaId: "area/1", assetRef }) });
const record = { declarationId: `vrd-${"1".repeat(32)}` };
const post = (body: unknown, key: string | null = "declare-1") => new Request("http://console.test/api", {
  method: "POST",
  headers: { origin: "http://console.test", host: "console.test", "content-type": "application/json", ...(key ? { "Idempotency-Key": key } : {}) },
  body: typeof body === "string" ? body : JSON.stringify(body),
}) as never;
const declareBody = { datum: "orthometric_kngeoid2018", unit: "metre", basis: "Terra에서 내보냄", expectedSequence: 0 };

beforeEach(() => {
  vi.resetAllMocks();
  mocked.origin.mockReturnValue(false);
  mocked.session.mockResolvedValue("token");
  mocked.declare.mockResolvedValue(record);
  mocked.withdraw.mockResolvedValue(record);
});

describe("수직 기준 선언 BFF", () => {
  it("선언을 같은 토큰·키로 Core에 보내고 경로 값을 풀어 쓴다", async () => {
    const response = await declarePost(post(declareBody), context());
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ declaration: record });
    expect(mocked.declare).toHaveBeenCalledWith("site 1", "area/1", ASSET, declareBody, "declare-1", "token");
  });

  it("철회도 같다", async () => {
    const response = await withdrawPost(post({ expectedSequence: 1 }, "withdraw-1"), context());
    expect(response.status).toBe(201);
    expect(mocked.withdraw).toHaveBeenCalledWith("site 1", "area/1", ASSET, { expectedSequence: 1 }, "withdraw-1", "token");
  });

  it("다른 출처의 요청은 Core를 부르지 않고 막는다", async () => {
    mocked.origin.mockReturnValue(true);
    expect((await declarePost(post(declareBody), context())).status).toBe(403);
    expect((await withdrawPost(post({ expectedSequence: 1 }), context())).status).toBe(403);
    expect(mocked.declare).not.toHaveBeenCalled();
    expect(mocked.withdraw).not.toHaveBeenCalled();
  });

  it("형식이 틀린 본문·키·자료 참조는 Core에 보내지 않는다", async () => {
    expect((await declarePost(post({ ...declareBody, unit: "foot" }), context())).status).toBe(422);
    expect((await declarePost(post({ ...declareBody, siteId: "other" }), context())).status).toBe(422);
    expect((await declarePost(post(declareBody, null), context())).status).toBe(400);
    expect((await declarePost(post(declareBody, "bad key with spaces"), context())).status).toBe(400);
    expect((await declarePost(post(declareBody), context("not-an-asset"))).status).toBe(400);
    expect((await withdrawPost(post({ expectedSequence: 0 }), context())).status).toBe(422);
    expect((await declarePost(post("{not json"), context())).status).toBe(400);
    expect(mocked.declare).not.toHaveBeenCalled();
    expect(mocked.withdraw).not.toHaveBeenCalled();
  });

  it("세션이 없으면 Core를 부르지 않고 401이다", async () => {
    const { MissingSessionError } = await import("@/lib/core-api/session");
    mocked.session.mockRejectedValue(new MissingSessionError());
    expect((await declarePost(post(declareBody), context())).status).toBe(401);
    expect(mocked.declare).not.toHaveBeenCalled();
  });

  it("Core의 거부는 상태와 코드를 그대로 전한다(성공으로 바꾸지 않는다)", async () => {
    mocked.declare.mockRejectedValue(new CoreApiError(409, { verdict: "OBSERVED_REFERENCE_PRESENT", detail: "x" }));
    const response = await declarePost(post(declareBody), context());
    expect(response.status).toBe(409);
    expect((await response.json()).code).toBe("OBSERVED_REFERENCE_PRESENT");
    mocked.withdraw.mockRejectedValue(new CoreApiError(404, { detail: "자료를 찾을 수 없다" }));
    expect((await withdrawPost(post({ expectedSequence: 1 }), context())).status).toBe(404);
  });
});
