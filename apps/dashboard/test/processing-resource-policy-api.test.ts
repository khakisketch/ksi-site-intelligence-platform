import { beforeEach, describe, expect, it, vi } from "vitest";

import { coreFetch } from "../src/lib/core-api/client";
import { listProcessingResourcePolicies } from "../src/lib/core-api/processing-resource-policies";

vi.mock("../src/lib/core-api/client", () => ({
  coreFetch: vi.fn(),
}));

const coreFetchMock = vi.mocked(coreFetch);

describe("processing resource policy Core API client", () => {
  beforeEach(() => {
    coreFetchMock.mockReset();
  });

  it("인증을 포함하는 server-only coreFetch로 읽기 전용 registry를 조회한다", async () => {
    const payload = { currentPolicyId: "ksi-civil-pilot-r1", policies: [] };
    coreFetchMock.mockResolvedValue(payload);

    await expect(listProcessingResourcePolicies()).resolves.toEqual(payload);
    expect(coreFetchMock).toHaveBeenCalledWith("/v1/processing-resource-policies");
  });

  it("registry 인증/네트워크 실패를 정책 정상값으로 바꾸지 않고 호출자에게 전달한다", async () => {
    coreFetchMock.mockRejectedValue(new Error("unauthorized"));
    await expect(listProcessingResourcePolicies()).rejects.toThrow("unauthorized");
  });
});
