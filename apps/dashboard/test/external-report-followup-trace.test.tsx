/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ExternalReportFollowupTrace } from "@/app/sites/[siteId]/observations/[reportRef]/ExternalReportFollowupTrace";

afterEach(cleanup);

describe("external report followup trace", () => {
  it("keeps the exact report route through review and shows only a retained approved successor status", () => {
    render(<ExternalReportFollowupTrace
      reportRef={`external-relative-volume-report-${"a".repeat(32)}`}
      baselineWorkOrderId="source-order"
      currentWorkOrderId="current-order"
      successors={[{ workOrderId: "successor-order", workflowStatus: "CLOSED", closeNote: "현장 확인 완료" }]}
    />);
    expect(screen.getByRole("link", { name: "결과 검토와 후속 작업" }).getAttribute("href")).toContain("/field/work-orders/current-order?reportRef=");
    expect(screen.getByRole("link", { name: "기준 작업 보기" }).getAttribute("href")).toBe("/field/work-orders/source-order");
    expect(screen.getByRole("link", { name: "승인된 후속 작업 보기" }).getAttribute("href")).toBe("/field/work-orders/successor-order");
    expect(screen.getByText("업무 종료")).toBeTruthy();
    expect(screen.getByText("현장 확인 완료")).toBeTruthy();
  });

  it("does not infer a successor when the exact report detail was not verified", () => {
    render(<ExternalReportFollowupTrace
      reportRef={`external-relative-volume-report-${"a".repeat(32)}`}
      baselineWorkOrderId="source-order"
      currentWorkOrderId="current-order"
      successors={null}
    />);
    expect(screen.queryByText("승인된 후속 작업")).toBeNull();
  });
});
