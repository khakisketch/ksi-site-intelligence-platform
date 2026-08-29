import { describe, expect, it } from "vitest";

import {
  checkpointNextAction,
  isTerminalCheckpointValidation,
  selectableCheckpointEpochs,
  shouldPollCheckpointValidation,
} from "@/components/missions/CheckpointValidationPanel";
import type { CheckpointValidationView, SiteProcessingJobSummary } from "@/lib/core-api/types";

function job(overrides: Partial<SiteProcessingJobSummary>): SiteProcessingJobSummary {
  return {
    jobId: "job-1",
    missionId: "mission-1",
    siteId: "site-1",
    status: "SUCCEEDED",
    issuedAt: "2026-08-29T03:00:00Z",
    detail: null,
    artifacts: [{ artifactId: "dsm-1", kind: "dsm" }],
    captureWindow: { status: "COMPLETE", capturedFrom: null, capturedTo: null },
    ...overrides,
  };
}

function validation(status: CheckpointValidationView["status"]): CheckpointValidationView {
  return {
    schemaVersion: "1.0",
    validationId: "validation-1",
    organizationId: "org-1",
    missionId: "mission-1",
    siteId: "site-1",
    dsm: { jobId: "job-1", artifactId: "dsm-1" },
    dsmDigest: "sha256:" + "a".repeat(64),
    dsmCrs: "EPSG:5186",
    dsmVerticalReference: { datum: "ellipsoidal", basis: "fixture", source: "pipeline_declared" },
    declared: {
      filename: "checkpoints.csv",
      sha256: "b".repeat(64),
      sizeBytes: 100,
      crs: "EPSG:5186",
      verticalReference: { datum: "ellipsoidal", basis: "fixture", source: "user_declared" },
      independentFromProcessingAttested: true,
      independenceBasis: "separate survey",
    },
    validationProfileId: "ksi-dsm-checkpoint-nearest-v1",
    validationProfileDigest: "sha256:" + "c".repeat(64),
    status,
    registeredAt: "2026-08-29T03:00:00Z",
    registeredBy: "admin",
    sealedAt: status === "REGISTERED" ? null : "2026-08-29T03:01:00Z",
    observed:
      status === "VALIDATED"
        ? {
            checkpointSha256: "b".repeat(64),
            checkpointSizeBytes: 100,
            dsmDigest: "sha256:" + "a".repeat(64),
            dsmCrs: "EPSG:5186",
            pointCount: 3,
            meanErrorM: 0,
            maeM: 0.1,
            rmseM: 0.1,
            maxAbsErrorM: 0.1,
            measuredAt: "2026-08-29T03:02:00Z",
            measuredBy: "worker",
          }
        : null,
    rejectionReason: status === "REJECTED" ? "INVALID_CHECKPOINT_CSV" : null,
    rejectionDetail: status === "REJECTED" ? "header mismatch" : null,
  };
}

describe("selectableCheckpointEpochs", () => {
  it("완료된 DSM epoch만 최신 순으로 고른다", () => {
    const epochs = selectableCheckpointEpochs([
      job({ jobId: "old", issuedAt: "2026-08-01T00:00:00Z" }),
      job({ jobId: "running", status: "RUNNING" }),
      job({ jobId: "no-dsm", artifacts: [{ artifactId: "ortho-1", kind: "ortho" }] }),
      job({ jobId: "new", issuedAt: "2026-08-02T00:00:00Z", artifacts: [{ artifactId: "dsm-2", kind: "dsm" }] }),
    ]);

    expect(epochs).toEqual([
      { jobId: "new", missionId: "mission-1", issuedAt: "2026-08-02T00:00:00Z", artifactId: "dsm-2" },
      { jobId: "old", missionId: "mission-1", issuedAt: "2026-08-01T00:00:00Z", artifactId: "dsm-1" },
    ]);
  });
});

describe("checkpoint terminal states", () => {
  it("terminal 두 상태를 구분한다", () => {
    expect(isTerminalCheckpointValidation("REGISTERED")).toBe(false);
    expect(isTerminalCheckpointValidation("SEALED")).toBe(false);
    expect(isTerminalCheckpointValidation("VALIDATED")).toBe(true);
    expect(isTerminalCheckpointValidation("REJECTED")).toBe(true);
  });

  it("업로드 전 REGISTERED가 아니라 worker가 처리 가능한 SEALED만 폴링한다", () => {
    expect(shouldPollCheckpointValidation("REGISTERED")).toBe(false);
    expect(shouldPollCheckpointValidation("SEALED")).toBe(true);
    expect(shouldPollCheckpointValidation("VALIDATED")).toBe(false);
    expect(shouldPollCheckpointValidation("REJECTED")).toBe(false);
  });

  it("다음 행동은 원장 상태별로 구분한다", () => {
    expect(checkpointNextAction(validation("REGISTERED"))).toContain("올린 뒤 봉인");
    expect(checkpointNextAction(validation("SEALED"))).toContain("계산 중");
    expect(checkpointNextAction(validation("VALIDATED"))).toContain("원장에 고정");
    expect(checkpointNextAction(validation("REJECTED"))).toContain("새 CSV");
  });
});
