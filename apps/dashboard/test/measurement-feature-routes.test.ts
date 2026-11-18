import { beforeEach, describe, expect, it, vi } from "vitest";

import { CoreApiError } from "@/lib/core-api/client";

const mocked = vi.hoisted(() => ({ session: vi.fn(), create: vi.fn(), revise: vi.fn(), origin: vi.fn() }));
vi.mock("@/lib/core-api/session", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/core-api/session")>();
  return { ...actual, getSessionToken: mocked.session };
});
vi.mock("@/lib/core-api/measurement", () => ({
  createMeasurementFeatureWithToken: mocked.create,
  reviseMeasurementFeatureWithToken: mocked.revise,
}));
vi.mock("@/lib/core-api/origin-guard", () => ({ isCrossSiteMutation: mocked.origin }));

import { POST as createPost } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/measurement-features/route";
import { POST as revisePost } from "@/app/api/sites/[siteId]/work-areas/[workAreaId]/measurement-features/[featureId]/revisions/route";

const FEATURE_ID = `mf-${"1".repeat(32)}`;
const line = { crs: "EPSG:4326", vertices: [[127, 37], [127.001, 37]] };
const revision = { featureId: FEATURE_ID };
const ctx = (extra: Record<string, string> = {}) => ({ params: Promise.resolve({ siteId: "site 1", workAreaId: "area-1", featureId: FEATURE_ID, ...extra }) });
const post = (body: unknown, key: string | null = "line-1") => new Request("http://console.test/api", {
  method: "POST",
  headers: { origin: "http://console.test", host: "console.test", "content-type": "application/json", ...(key ? { "Idempotency-Key": key } : {}) },
  body: typeof body === "string" ? body : JSON.stringify(body),
}) as never;
const createBody = { workAreaId: "area-1", name: "북쪽 경사면", line };
const reviseBody = { expectedRevision: 1, name: "수정", line };

beforeEach(() => {
  vi.resetAllMocks();
  mocked.origin.mockReturnValue(false);
  mocked.session.mockResolvedValue("token");
  mocked.create.mockResolvedValue(revision);
  mocked.revise.mockResolvedValue(revision);
});

describe("측정 선 저장 BFF", () => {
  it("저장을 같은 토큰·키로 Core에 보낸다", async () => {
    const response = await createPost(post(createBody), ctx());
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ revision });
    expect(mocked.create).toHaveBeenCalledWith("site 1", "area-1", createBody, "line-1", "token");
  });

  it("고치기는 본 개정 번호와 함께 보낸다", async () => {
    const response = await revisePost(post(reviseBody), ctx());
    expect(response.status).toBe(201);
    expect(mocked.revise).toHaveBeenCalledWith("site 1", "area-1", FEATURE_ID, reviseBody, "line-1", "token");
  });

  it("다른 출처의 요청은 Core를 부르지 않고 막는다", async () => {
    mocked.origin.mockReturnValue(true);
    expect((await createPost(post(createBody), ctx())).status).toBe(403);
    expect((await revisePost(post(reviseBody), ctx())).status).toBe(403);
    expect(mocked.create).not.toHaveBeenCalled();
    expect(mocked.revise).not.toHaveBeenCalled();
  });

  it("본문의 구역이 주소의 구역과 다르면 거부한다", async () => {
    expect((await createPost(post({ ...createBody, workAreaId: "area-2" }), ctx())).status).toBe(422);
    expect(mocked.create).not.toHaveBeenCalled();
  });

  it("형식이 틀린 본문·키·선 식별자는 Core에 보내지 않는다", async () => {
    expect((await createPost(post({ ...createBody, line: { ...line, crs: "EPSG:5186" } }), ctx())).status).toBe(422);
    expect((await createPost(post({ ...createBody, extra: 1 }), ctx())).status).toBe(422);
    expect((await createPost(post(createBody, null), ctx())).status).toBe(400);
    expect((await createPost(post(createBody, "bad key"), ctx())).status).toBe(400);
    expect((await createPost(post("{nope"), ctx())).status).toBe(400);
    expect((await revisePost(post({ ...reviseBody, expectedRevision: undefined }), ctx())).status).toBe(422);
    expect((await revisePost(post(reviseBody), ctx({ featureId: "x" }))).status).toBe(400);
    expect(mocked.create).not.toHaveBeenCalled();
    expect(mocked.revise).not.toHaveBeenCalled();
  });

  it("세션이 없으면 Core를 부르지 않고 401이다", async () => {
    const { MissingSessionError } = await import("@/lib/core-api/session");
    mocked.session.mockRejectedValue(new MissingSessionError());
    expect((await createPost(post(createBody), ctx())).status).toBe(401);
    expect(mocked.create).not.toHaveBeenCalled();
  });

  it("Core의 거부는 상태와 코드를 그대로 전한다", async () => {
    mocked.revise.mockRejectedValue(new CoreApiError(409, { verdict: "REVISION_CONFLICT", detail: "x" }));
    const response = await revisePost(post(reviseBody), ctx());
    expect(response.status).toBe(409);
    expect((await response.json()).code).toBe("REVISION_CONFLICT");
    mocked.create.mockRejectedValue(new CoreApiError(404, { detail: "작업구역을 찾을 수 없다" }));
    expect((await createPost(post(createBody), ctx())).status).toBe(404);
  });
});
