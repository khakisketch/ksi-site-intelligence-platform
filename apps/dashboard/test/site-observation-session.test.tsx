/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ session: vi.fn() }));
vi.mock("@/app/field/resolve-session", () => ({ resolveFieldSession: mocked.session }));
vi.mock("@/app/field/OperationsSessionFailure", () => ({
  OperationsSessionFailure: ({ next }: { next: string }) => <p data-testid="session-failure">{next}</p>,
}));

import SiteObservationDetailPage from "@/app/sites/[siteId]/observations/[reportRef]/page";
import SiteObservationHistoryPage from "@/app/sites/[siteId]/observations/page";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("외부 관측 이력 세션 복구", () => {
  it("keeps the exact history address when the session has expired", async () => {
    mocked.session.mockResolvedValue({ kind: "blocked", verdict: { kind: "login" } });
    render(await SiteObservationHistoryPage({
      params: Promise.resolve({ siteId: "site-1" }),
      searchParams: Promise.resolve({ after: "external-relative-volume-report-cursor" }),
    }));
    expect(screen.getByTestId("session-failure").textContent).toBe("/sites/site-1/observations");
  });

  it("keeps the exact report address without a query token when the session has expired", async () => {
    mocked.session.mockResolvedValue({ kind: "blocked", verdict: { kind: "login" } });
    render(await SiteObservationDetailPage({
      params: Promise.resolve({ siteId: "site-1", reportRef: "external-relative-volume-report-aaaaaaaa" }),
    }));
    expect(screen.getByTestId("session-failure").textContent).toBe(
      "/sites/site-1/observations/external-relative-volume-report-aaaaaaaa",
    );
  });
});
