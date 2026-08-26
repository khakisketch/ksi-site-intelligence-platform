import { describe, expect, it } from "vitest";

import { presentAcquisitionProgress } from "@/app/field/acquisition-progress";
import type { AcquisitionProgressView, AcquisitionRunStage } from "@/lib/core-api/types";

function progress(stage: AcquisitionRunStage): AcquisitionProgressView {
  return {
    schemaVersion: "1.0",
    runId: "acq-run-1",
    workOrderId: "obs-work-1",
    siteId: "site-1",
    cycleNumber: 1,
    stage,
    nextAction: stage === "READY_FOR_FLIGHT" ? "OPERATE_WITH_PILOT_2" : "WAIT_GATEWAY_DELIVERY",
    detail: "Core canonical detail",
    readiness: {
      siteId: "site-1",
      status: "CONNECTIVITY_STALE",
      readyForMissionIssue: false,
      reasons: ["Gateway heartbeat가 만료됐다"],
      evaluatedAt: "2026-08-21T10:00:00Z",
      profile: null,
      connectivity: null,
      inFlightContractPolicy: "REMAINS_VALID_UNTIL_CONTRACT_EXPIRY",
    },
    mission: { missionId: "mission-1", issued: true, executionStatus: "ACTIVATED" },
    gateway: {
      latestReceipt: null,
      succeededCapabilities: ["WAYLINE_DELIVERY", "EDGE_DOWNLINK"],
      failedCapabilities: [],
    },
    contractActivation: {
      state: stage === "READY_FOR_FLIGHT" ? "ACTIVATED" : "PENDING",
      activatedAt: stage === "READY_FOR_FLIGHT" ? "2026-08-21T09:59:00Z" : null,
    },
    media: { state: "NOT_STARTED", itemCount: 0, sourceBundleDigest: null },
    processing: { state: "NOT_STARTED", jobIds: [] },
    evaluatedAt: "2026-08-21T10:00:00Z",
    inFlightContractPolicy: "REMAINS_VALID_UNTIL_CONTRACT_EXPIRY",
  };
}

describe("presentAcquisitionProgress", () => {
  it("reserves the ready wording for signed Edge activation", () => {
    expect(presentAcquisitionProgress(progress("CONTRACT_PENDING")).label).not.toBe(
      "비행 준비 완료",
    );
    expect(presentAcquisitionProgress(progress("READY_FOR_FLIGHT")).label).toBe(
      "비행 준비 완료",
    );
  });

  it("warns without auto-stop language when an active contract loses connectivity", () => {
    const view = presentAcquisitionProgress(progress("READY_FOR_FLIGHT"));
    expect(view.activeContractOfflineWarning).toContain("활성화된 계약은 유효");
    expect(view.activeContractOfflineWarning).toContain("자동 중단하지 않습니다");
    expect(view.gatewayReceiptSummary).toBe("이번 비행 임무 전달 기록 2/5");
  });

  it("fails closed when the progress API cannot be read", () => {
    const view = presentAcquisitionProgress(null);
    expect(view.label).toBe("진행상태 확인 불가");
    expect(view.tone).toBe("warning");
  });
});
