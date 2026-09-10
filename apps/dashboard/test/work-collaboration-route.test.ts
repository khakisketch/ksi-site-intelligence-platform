import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ session: vi.fn(), assign: vi.fn() }));
vi.mock("@/lib/core-api/session", () => ({ getSessionToken: mocked.session }));
vi.mock("@/lib/core-api/observation-work-orders", () => ({ assignObservationWorkOrderToMe: mocked.assign }));

import { POST } from "@/app/api/observation-work-orders/[workOrderId]/operations/assignment/route";

const context = { params: Promise.resolve({ workOrderId: "work-1" }) };

beforeEach(() => {
  vi.resetAllMocks();
  mocked.session.mockResolvedValue("token");
  mocked.assign.mockResolvedValue({ workOrderId: "work-1" });
});

describe("member assignment BFF", () => {
  it("rejects a member assignment without its explicit target before it reaches Core", async () => {
    const response = await POST(new Request("http://console.test/api", {
      method: "POST",
      headers: { host: "console.test", origin: "http://console.test", "content-type": "application/json", "idempotency-key": "assign-1" },
      body: JSON.stringify({ expectedOperationsRevision: 2, action: "ASSIGN_TO_MEMBER" }),
    }) as never, context);
    expect(response.status).toBe(400);
    expect(mocked.assign).not.toHaveBeenCalled();
  });

  it("forwards the exact member assignment body and idempotency key", async () => {
    const response = await POST(new Request("http://console.test/api", {
      method: "POST",
      headers: { host: "console.test", origin: "http://console.test", "content-type": "application/json", "idempotency-key": "assign-2" },
      body: JSON.stringify({ expectedOperationsRevision: 2, action: "ASSIGN_TO_MEMBER", assigneePrincipalId: "operator-b" }),
    }) as never, context);
    expect(response.status).toBe(200);
    expect(mocked.assign).toHaveBeenCalledWith("work-1", 2, "ASSIGN_TO_MEMBER", "assign-2", "operator-b");
  });

  it("accepts the Core-compatible 255 character member id", async () => {
    const principalId = "a".repeat(255);
    const response = await POST(new Request("http://console.test/api", {
      method: "POST",
      headers: { host: "console.test", origin: "http://console.test", "content-type": "application/json", "idempotency-key": "assign-3" },
      body: JSON.stringify({ expectedOperationsRevision: 2, action: "ASSIGN_TO_MEMBER", assigneePrincipalId: principalId }),
    }) as never, context);
    expect(response.status).toBe(200);
    expect(mocked.assign).toHaveBeenCalledWith("work-1", 2, "ASSIGN_TO_MEMBER", "assign-3", principalId);
  });
});
