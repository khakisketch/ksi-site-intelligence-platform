import { describe, expect, it } from "vitest";

import { presentAcquisitionProgress } from "@/app/field/acquisition-progress";
import type {
  AcquisitionProgressView,
  AcquisitionRunStage,
  AnalysisReadinessStatus,
} from "@/lib/core-api/types";

function progress(
  stage: AcquisitionRunStage,
  analysisStatus: AnalysisReadinessStatus | null = "WAITING_PROCESSING",
): AcquisitionProgressView {
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
    analysisReadiness:
      analysisStatus === null
        ? null
        : {
            status: analysisStatus,
            ready: analysisStatus === "READY",
            detail: `Core evidence detail: ${analysisStatus}`,
            epoch: {
              epochId: "obs-epoch-1",
              workOrderId: "obs-work-1",
              cycleNumber: 1,
              missionId: "mission-1",
              sortieCount: 1,
              maxCaptureSpanSeconds: 600,
              temporalPolicySchemaVersion: "1.0",
              captureWindowStatus: "COMPLETE",
              capturedFrom: "2026-08-21T09:00:00Z",
              capturedTo: "2026-08-21T09:10:00Z",
            },
            evidenceRefs: ["coverage-report:mission-1"],
            evaluatedAt: "2026-08-21T10:00:00Z",
          },
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
    expect(view.analysisLabel).toBe("분석 준비 확인 불가");
  });

  it("uses only Core's evidence-derived analysis readiness, never the workflow stage", () => {
    const blockedReview = presentAcquisitionProgress(
      progress("REVIEW_READY", "TEMPORAL_POLICY_UNDECLARED"),
    );
    expect(blockedReview.analysisLabel).toBe("촬영 시간 기준 미선언");
    expect(blockedReview.analysisTone).toBe("warning");
    expect(blockedReview.analysisDetail).toContain("TEMPORAL_POLICY_UNDECLARED");

    const ready = presentAcquisitionProgress(progress("PROCESSING", "READY"));
    expect(ready.analysisLabel).toBe("분석 준비 완료");
    expect(ready.analysisTone).toBe("positive");
  });

  it("fails closed when Core has not assembled analysis readiness evidence", () => {
    const view = presentAcquisitionProgress(progress("REVIEW_READY", null));
    expect(view.analysisLabel).toBe("분석 준비 확인 불가");
    expect(view.analysisTone).toBe("warning");
  });
});
