import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const page = readFileSync(
  join(process.cwd(), "src/app/field/work-orders/[workOrderId]/page.tsx"),
  "utf8",
);
const action = readFileSync(join(process.cwd(), "src/app/field/WorkOrderActionPanel.tsx"), "utf8");
const wizard = readFileSync(
  join(process.cwd(), "src/app/sites/[siteId]/surveys/new/SurveyWizard.tsx"),
  "utf8",
);

describe("WorkOrder acquisition UI wiring", () => {
  it("orders one human action, acquisition progress, then connection detail", () => {
    const primary = page.indexOf("지금 할 일");
    const progress = page.indexOf("<AcquisitionProgressCard");
    const connectivity = page.indexOf("<AcquisitionReadinessCard");
    expect(primary).toBeGreaterThan(-1);
    expect(progress).toBeGreaterThan(primary);
    expect(connectivity).toBeGreaterThan(progress);
  });

  it("opens the existing Mission Wizard only when Core asks for a plan", () => {
    expect(action).toContain('nextAction === "OPEN_MISSION_WIZARD"');
    expect(action).toContain("workOrderId=");
    expect(action).toContain("비행 준비");
    expect(action).toContain('action="MISSIONS_ISSUE"');
    expect(action).toContain('action="WORK_ORDERS_WRITE"');
    expect(action).toContain('action="REOBSERVATION_APPROVE"');
  });

  it("preserves WorkOrder lineage in the MissionPlanRequest", () => {
    expect(wizard).toContain("initialWorkOrderId");
    expect(wizard).toContain("{ workOrderId: initialWorkOrderId }");
  });
});
