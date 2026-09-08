import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  RESPONSIVE_ACTIONS,
  isCompactActionAllowed,
} from "@/components/responsive/responsive-actions";

describe("Operations Console responsive action matrix", () => {
  it.each([
    "READ",
    "EVENTS_TRIAGE",
    "ANALYSIS_REVIEW",
    "COPILOT_QUERY",
    "REPORT_ACCESS",
  ] as const)("%s 는 1024px 미만에서도 허용한다", (action) => {
    expect(isCompactActionAllowed(action)).toBe(true);
  });

  it.each([
    "WORK_ORDERS_WRITE",
    "REOBSERVATION_APPROVE",
    "MISSIONS_ISSUE",
    "SITE_DEVICE_TRANSITION",
    "MISSION_EXECUTION",
    "SOURCE_MEDIA_MUTATION",
    "RECOVERY_ACTION",
    "EXTERNAL_RECONSTRUCTION_MUTATION",
  ] as const)("%s 는 1024px 미만에서 노트북 안내로 대체한다", (action) => {
    expect(isCompactActionAllowed(action)).toBe(false);
  });

  it("모든 공개 action을 빠짐없이 판정한다", () => {
    expect(RESPONSIVE_ACTIONS).toHaveLength(13);
    expect(RESPONSIVE_ACTIONS.every((action) => typeof isCompactActionAllowed(action) === "boolean"))
      .toBe(true);
  });

  it("SSR부터 CSS 경계로 쓰기 행동을 숨기고 1024px에서만 원래 문맥에 복원한다", () => {
    const source = readFileSync(
      join(process.cwd(), "src/components/responsive/ResponsiveActionBoundary.tsx"),
      "utf8",
    );
    expect(source).toContain('className="hidden lg:contents"');
    expect(source).toContain("lg:hidden");
    expect(source).toContain("노트북에서 계속");
    expect(source).not.toContain("useSyncExternalStore");
  });
});
