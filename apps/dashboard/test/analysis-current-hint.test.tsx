/** @vitest-environment jsdom */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { AnalysisRequestPanel } from "@/app/sites/[siteId]/analysis/AnalysisRequestPanel";
import type { AnalysisListPage, AnalysisObservationOption } from "@/lib/core-api/analysis";

type Scoped = AnalysisObservationOption & { workAreaIds: string[] };

const selector = (workOrderId: string, digit: string) => ({
  workOrderId,
  submissionRef: `ers-v1-${digit.repeat(64)}`,
  revision: 1,
});

function option(workOrderId: string, digit: string, epoch: string, start: string, end: string, workAreaIds: string[]): Scoped {
  return { selector: selector(workOrderId, digit), observationEpochId: epoch, captureStartedAt: start, captureEndedAt: end, workAreaIds };
}

const observations: Scoped[] = [
  option("work-a1", "a", "epoch-a1", "2026-09-01T00:00:00Z", "2026-09-01T00:30:00Z", ["area-1"]),
  option("work-b1", "b", "epoch-b1", "2026-09-08T00:00:00Z", "2026-09-08T00:30:00Z", ["area-1"]),
  option("work-a2", "c", "epoch-a2", "2026-09-01T00:00:00Z", "2026-09-01T00:30:00Z", ["area-2"]),
  option("work-b2", "d", "epoch-b2", "2026-09-08T00:00:00Z", "2026-09-08T00:30:00Z", ["area-2"]),
];

const workAreas = [
  { workAreaId: "area-1", name: "1구역" },
  { workAreaId: "area-2", name: "2구역" },
];

function emptyPage(): AnalysisListPage {
  return { siteId: "site-1", items: [], nextCursor: null };
}

function renderPanel(overrides: Partial<Parameters<typeof AnalysisRequestPanel>[0]> = {}) {
  return render(<AnalysisRequestPanel
    siteId="site-1"
    organizationId="org-1"
    principalId="operator-1"
    workAreas={workAreas}
    observations={observations}
    initialPage={emptyPage()}
    initialSelectedDetail={null}
    canCreate
    initialAnalysisId={null}
    {...overrides}
  />);
}

afterEach(() => { cleanup(); window.sessionStorage.clear(); });
beforeEach(() => { window.sessionStorage.clear(); });

describe("AnalysisRequestPanel current preference", () => {
  it("preselects the hinted current observation only for its exact single scope match", () => {
    renderPanel({ initialWorkAreaId: "area-1", initialCurrentWorkOrderId: "work-b1" });
    expect((screen.getByLabelText("작업구역") as HTMLSelectElement).value).toBe("area-1");
    // work-b1 is the second candidate of area-1, the only match — preselected, not auto-submitted.
    expect((screen.getByLabelText("현재 관측") as HTMLSelectElement).value).toBe("1");
    expect((screen.getByLabelText("기준 관측") as HTMLSelectElement).value).toBe("");
    expect(screen.queryByText(/요청한 관측/)).toBeNull();
  });

  it("leaves current empty with truthful guidance when the hint is outside the analysis candidates", () => {
    renderPanel({
      initialWorkAreaId: "area-1",
      initialCurrentWorkOrderId: "work-unknown",
      currentHintNotice: "요청한 관측은 이 구역의 분석 후보에 없습니다. 현재 관측을 직접 선택하세요.",
    });
    expect((screen.getByLabelText("현재 관측") as HTMLSelectElement).value).toBe("");
    expect(screen.getByText(/분석 후보에 없습니다/).textContent).toMatch(/현재 관측을 직접 선택하세요/);
    expect(screen.getByRole("link", { name: "등록 자료와 검사 상태 확인" }).getAttribute("href")).toBe("/sites/site-1/spatial-assets?workAreaId=area-1");
    expect(screen.queryByRole("link", { name: "외부 비교 기록에서 확인" })).toBeNull();
  });

  it("lets a pending frozen attempt win over the URL hint", async () => {
    window.sessionStorage.setItem(
      "ksi.analysis.pending.v2:org-1:operator-1:site-1",
      JSON.stringify({
        version: 2,
        organizationId: "org-1",
        principalId: "operator-1",
        siteId: "site-1",
        attempt: {
          key: "analysis-frozen-1",
          workAreaId: "area-2",
          body: { baseline: selector("work-a2", "c"), current: selector("work-b2", "d") },
          activationBlockCode: null,
        },
      }),
    );
    renderPanel({ initialWorkAreaId: "area-1", initialCurrentWorkOrderId: "work-b1", currentHintNotice: "URL 힌트에만 해당하는 공지" });
    await waitFor(() => {
      expect((screen.getByLabelText("작업구역") as HTMLSelectElement).value).toBe("area-2");
    });
    // area-2 scoped indexes into the full candidate list: 2 (baseline) and 3 (current).
    expect((screen.getByLabelText("기준 관측") as HTMLSelectElement).value).toBe("2");
    expect((screen.getByLabelText("현재 관측") as HTMLSelectElement).value).toBe("3");
    expect(screen.queryByText("URL 힌트에만 해당하는 공지")).toBeNull();
  });
});
