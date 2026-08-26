import { beforeEach, describe, expect, it, vi } from "vitest";

import { coreFetch } from "../src/lib/core-api/client";
import { listAllEvents } from "../src/lib/core-api/events";
import type { EventSummaryResponse } from "../src/lib/core-api/types";

vi.mock("../src/lib/core-api/client", () => ({
  coreFetch: vi.fn(),
}));

const coreFetchMock = vi.mocked(coreFetch);

function event(index: number): EventSummaryResponse {
  return {
    eventKey: `edge-1::event-${index}`,
    eventId: `event-${index}`,
    siteId: "site-1",
    missionId: "mission-1",
    eventType: "PERSON_PRESENT",
    status: "CANDIDATE",
    severity: null,
    triage: "NONE",
    assignee: null,
    evidenceCount: 0,
    edgeDeviceId: "edge-1",
    occurredAt: "2026-08-24T00:00:00Z",
    receivedAt: "2026-08-24T00:00:01Z",
  };
}

describe("listAllEvents", () => {
  beforeEach(() => {
    coreFetchMock.mockReset();
  });

  it("Core의 500건 요청 상한 뒤 다음 페이지까지 수집한다", async () => {
    const firstPage = Array.from({ length: 500 }, (_, index) => event(index));
    const secondPage = [event(500)];
    coreFetchMock
      .mockResolvedValueOnce({ events: firstPage, count: firstPage.length })
      .mockResolvedValueOnce({ events: secondPage, count: secondPage.length });

    const result = await listAllEvents({ siteId: "site-1" });

    expect(result.events).toHaveLength(501);
    expect(result.count).toBe(501);
    expect(coreFetchMock).toHaveBeenNthCalledWith(1, "/v1/events", {
      query: { siteId: "site-1", limit: 500, offset: 0 },
    });
    expect(coreFetchMock).toHaveBeenNthCalledWith(2, "/v1/events", {
      query: { siteId: "site-1", limit: 500, offset: 500 },
    });
  });

  it("후속 페이지 실패를 부분 성공으로 바꾸지 않는다", async () => {
    const firstPage = Array.from({ length: 500 }, (_, index) => event(index));
    coreFetchMock
      .mockResolvedValueOnce({ events: firstPage, count: firstPage.length })
      .mockRejectedValueOnce(new Error("Core unavailable"));

    await expect(listAllEvents()).rejects.toThrow("Core unavailable");
  });
});
