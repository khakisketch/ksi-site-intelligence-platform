// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DwellBar } from "@/app/events/DwellBar";
import type { EventSummaryResponse } from "@/lib/core-api/types";

afterEach(cleanup);

function event(overrides: Partial<EventSummaryResponse> = {}): EventSummaryResponse {
  return {
    eventKey: "event-1",
    eventId: "e-1",
    siteId: "site-1",
    missionId: "mission-1",
    eventType: "PERIMETER_INTRUSION",
    status: "OBSERVATION",
    severity: "CRITICAL",
    triage: "NONE",
    assignee: null,
    evidenceCount: 1,
    edgeDeviceId: "edge-1",
    occurredAt: new Date().toISOString(),
    receivedAt: new Date().toISOString(),
    ...overrides,
  };
}

describe("DwellBar", () => {
  it("gives a breached row a visually distinct treatment from a normal filling bar", () => {
    // CRITICAL target is 15 minutes; 30 minutes elapsed is well past it.
    const breached = event({ occurredAt: new Date(Date.now() - 30 * 60_000).toISOString() });
    render(<DwellBar event={breached} />);
    const bar = screen.getByTestId("dwell-bar");
    expect(bar.dataset.sla).toBe("breached");

    cleanup();

    // 2 minutes elapsed against a 15-minute target: still filling, not breached.
    const inProgress = event({ occurredAt: new Date(Date.now() - 2 * 60_000).toISOString() });
    render(<DwellBar event={inProgress} />);
    const okBar = screen.getByTestId("dwell-bar");
    expect(okBar.dataset.sla).not.toBe("breached");
  });

  it("never renders a bar for a settled event", () => {
    const settled = event({
      status: "CONFIRMED_EVENT",
      occurredAt: new Date(Date.now() - 30 * 60_000).toISOString(),
    });
    render(<DwellBar event={settled} />);
    expect(screen.queryByTestId("dwell-bar")).toBeNull();
  });
});
