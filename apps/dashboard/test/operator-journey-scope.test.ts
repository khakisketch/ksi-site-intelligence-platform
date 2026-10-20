import { describe, expect, it } from "vitest";

import {
  resolveAnalysisCurrentHint,
  resolveAnalysisScope,
  resolveRegistrationScope,
  resolveWorkOrderContinuation,
} from "@/lib/operator-journey";

const areas = [
  { workAreaId: "wa-a", name: "A구역", status: "ACTIVE" },
  { workAreaId: "wa-b", name: "B구역", status: "ACTIVE" },
  { workAreaId: "wa-old", name: "보관 구역", status: "ARCHIVED" },
];

describe("operator journey scope", () => {
  it("registration prefers repeat template over conflicting query", () => {
    const result = resolveRegistrationScope({
      areas,
      rawWorkAreaId: "wa-b",
      repeatWorkAreaIds: ["wa-a"],
    });
    expect(result.initialWorkAreaIds).toEqual(["wa-a"]);
    expect(result.scopeNotice).toBeNull();
  });

  it("registration accepts valid single scoped query", () => {
    const result = resolveRegistrationScope({ areas, rawWorkAreaId: "wa-a", repeatWorkAreaIds: [] });
    expect(result.initialWorkAreaIds).toEqual(["wa-a"]);
    expect(result.scopeNotice).not.toBeNull();
  });

  it("registration rejects array/foreign/archived without leaking or silent switch", () => {
    for (const raw of [["wa-a"], "wa-foreign", "wa-old", " ", "x".repeat(250)]) {
      const result = resolveRegistrationScope({ areas, rawWorkAreaId: raw as unknown, repeatWorkAreaIds: [] });
      expect(result.initialWorkAreaIds).toEqual([]);
      expect(result.invalidRequested).toBe(true);
      expect(result.scopeNotice).toMatch(/직접 선택/);
    }
  });

  it("registration preselects only single active area when no explicit request", () => {
    const single = resolveRegistrationScope({
      areas: [areas[0]!],
      rawWorkAreaId: undefined,
      repeatWorkAreaIds: [],
    });
    expect(single.initialWorkAreaIds).toEqual(["wa-a"]);
    const multi = resolveRegistrationScope({ areas, rawWorkAreaId: undefined, repeatWorkAreaIds: [] });
    expect(multi.initialWorkAreaIds).toEqual([]);
    expect(multi.scopeNotice).toBeNull();
  });

  it("analysis scope defers to pending attempt and deeplink", () => {
    expect(
      resolveAnalysisScope({ areas, rawWorkAreaId: "wa-a", hasPendingAttempt: true, hasAnalysisDeepLink: false }).initialWorkAreaId,
    ).toBe("");
    expect(
      resolveAnalysisScope({ areas, rawWorkAreaId: "wa-a", hasPendingAttempt: false, hasAnalysisDeepLink: true }).initialWorkAreaId,
    ).toBe("");
  });

  it("analysis scope preselects only single active area when no explicit request", () => {
    const single = resolveAnalysisScope({ areas: [areas[0]!], rawWorkAreaId: undefined, hasPendingAttempt: false, hasAnalysisDeepLink: false });
    expect(single.initialWorkAreaId).toBe("wa-a");
    expect(single.scopeNotice).toMatch(/범위/);
    const multi = resolveAnalysisScope({ areas, rawWorkAreaId: undefined, hasPendingAttempt: false, hasAnalysisDeepLink: false });
    expect(multi.initialWorkAreaId).toBe("");
    expect(multi.scopeNotice).toBeNull();
  });

  it("analysis current hint requires exact single candidate in scope", () => {
    const candidates = [
      { selector: { workOrderId: "wo-1" }, workAreaIds: ["wa-a"] },
      { selector: { workOrderId: "wo-1" }, workAreaIds: ["wa-a"] },
    ];
    const ambiguous = resolveAnalysisCurrentHint({
      candidates,
      workAreaId: "wa-a",
      rawCurrentWorkOrderId: "wo-1",
      hasPendingAttempt: false,
      hasAnalysisDeepLink: false,
    });
    expect(ambiguous.currentWorkOrderId).toBeNull();

    const exact = resolveAnalysisCurrentHint({
      candidates: [{ selector: { workOrderId: "wo-1" }, workAreaIds: ["wa-a"] }],
      workAreaId: "wa-a",
      rawCurrentWorkOrderId: "wo-1",
      hasPendingAttempt: false,
      hasAnalysisDeepLink: false,
    });
    expect(exact.currentWorkOrderId).toBe("wo-1");

    const wrongArea = resolveAnalysisCurrentHint({
      candidates: [{ selector: { workOrderId: "wo-1" }, workAreaIds: ["wa-a"] }],
      workAreaId: "wa-b",
      rawCurrentWorkOrderId: "wo-1",
      hasPendingAttempt: false,
      hasAnalysisDeepLink: false,
    });
    expect(wrongArea.currentWorkOrderId).toBeNull();
  });

  it("work order continuation only for exact one active scope", () => {    expect(resolveWorkOrderContinuation({ areas, workAreaIds: ["wa-a"] }).workAreaId).toBe("wa-a");
    expect(resolveWorkOrderContinuation({ areas, workAreaIds: ["wa-a", "wa-b"] }).workAreaId).toBeNull();
    expect(resolveWorkOrderContinuation({ areas, workAreaIds: ["wa-old"] }).workAreaId).toBeNull();
    // 비활성·모르는 연결을 걸러내고 하나로 만들지 않는다 — 다구역 작업은 목록 선택으로 둔다.
    expect(resolveWorkOrderContinuation({ areas, workAreaIds: ["wa-a", "wa-old"] }).workAreaId).toBeNull();
    expect(resolveWorkOrderContinuation({ areas, workAreaIds: ["wa-a", "wa-foreign"] }).workAreaId).toBeNull();
    expect(resolveWorkOrderContinuation({ areas, workAreaIds: [] }).workAreaId).toBeNull();
    // 같은 구역의 중복 기록은 숨은 다구역이 아니므로 그대로 둔다.
    expect(resolveWorkOrderContinuation({ areas, workAreaIds: ["wa-a", "wa-a"] }).workAreaId).toBe("wa-a");
  });
});

describe("operator journey long known IDs", () => {
  const longAreaId = `wa-long-${"x".repeat(250)}`;
  const longAreas = [...areas, { workAreaId: longAreaId, name: "긴 구역", status: "ACTIVE" }];
  const unknownLong = `wa-unknown-${"y".repeat(250)}`;

  it("accepts an exact known long area ID without truncation or substitution", () => {
    const registration = resolveRegistrationScope({ areas: longAreas, rawWorkAreaId: longAreaId, repeatWorkAreaIds: [] });
    expect(registration.initialWorkAreaIds).toEqual([longAreaId]);
    expect(registration.invalidRequested).toBe(false);
    const scope = resolveAnalysisScope({ areas: longAreas, rawWorkAreaId: longAreaId, hasPendingAttempt: false, hasAnalysisDeepLink: false });
    expect(scope.initialWorkAreaId).toBe(longAreaId);
    expect(scope.invalidRequested).toBe(false);
  });

  it("keeps unknown long values generic and never echoed", () => {
    const registration = resolveRegistrationScope({ areas: longAreas, rawWorkAreaId: unknownLong, repeatWorkAreaIds: [] });
    expect(registration.initialWorkAreaIds).toEqual([]);
    expect(registration.invalidRequested).toBe(true);
    expect(registration.scopeNotice).toMatch(/직접 선택/);
    expect(registration.scopeNotice).not.toContain(unknownLong.slice(0, 20));
    const scope = resolveAnalysisScope({ areas: longAreas, rawWorkAreaId: unknownLong, hasPendingAttempt: false, hasAnalysisDeepLink: false });
    expect(scope.initialWorkAreaId).toBe("");
    expect(scope.invalidRequested).toBe(true);
  });

  it("accepts an exact known long current work order ID for its single scope match", () => {
    const longWorkOrderId = `wo-long-${"z".repeat(250)}`;
    const exact = resolveAnalysisCurrentHint({
      candidates: [{ selector: { workOrderId: longWorkOrderId }, workAreaIds: [longAreaId] }],
      workAreaId: longAreaId,
      rawCurrentWorkOrderId: longWorkOrderId,
      hasPendingAttempt: false,
      hasAnalysisDeepLink: false,
    });
    expect(exact.currentWorkOrderId).toBe(longWorkOrderId);
    expect(exact.notice).toBeNull();
    const unknown = resolveAnalysisCurrentHint({
      candidates: [{ selector: { workOrderId: longWorkOrderId }, workAreaIds: [longAreaId] }],
      workAreaId: longAreaId,
      rawCurrentWorkOrderId: unknownLong,
      hasPendingAttempt: false,
      hasAnalysisDeepLink: false,
    });
    expect(unknown.currentWorkOrderId).toBeNull();
    expect(unknown.notice).toMatch(/직접 선택/);
  });
});
