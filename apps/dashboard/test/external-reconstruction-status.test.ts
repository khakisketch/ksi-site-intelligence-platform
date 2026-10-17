import { describe, expect, it } from "vitest";

import { presentExternalInspectionStatus } from "@/app/field/external-reconstruction-status";
import type { ExternalArtifactInspectionView } from "@/lib/core-api/external-reconstruction";

function inspection(overrides: Record<string, unknown> = {}): ExternalArtifactInspectionView {
  return {
    registrationState: "SEALED",
    sealState: "SEALED",
    inspection: { state: "INSPECTION_PENDING", phase: null, outcome: null, request: null, report: null },
    display: { state: "PENDING_INSPECTION", sanitizedDisplayRef: null, receiptDigest: null },
    ...overrides,
  } as ExternalArtifactInspectionView;
}

describe("external reconstruction inspection presentation", () => {
  it("keeps registration, policy, queue, running, report, display preparation, and ready as separate operator stages", () => {
    expect(presentExternalInspectionStatus(inspection({ registrationState: "REGISTERED", sealState: "UNSEALED", inspection: { state: "INSPECTION_PENDING_SEAL", phase: null, outcome: null, request: null, report: null } })).title).toBe("자료 등록됨 · 파일 제출 마무리 필요");
    const policy = presentExternalInspectionStatus(inspection({ inspection: { state: "INSPECTION_PENDING_POLICY", phase: null, outcome: null, request: null, report: null } }));
    expect(policy.title).toBe("검사 기준 확인 필요");
    expect(policy.autoRefresh).toBe(false);
    expect(policy.nextAction).toMatch(/관리자/);
    expect(presentExternalInspectionStatus(inspection({ inspection: { state: "INSPECTION_QUEUED", phase: "INSPECTION", outcome: null, request: null, report: null } })).title).toBe("파일 검사 대기열");
    expect(presentExternalInspectionStatus(inspection({ inspection: { state: "INSPECTION_RUNNING", phase: "INSPECTION", outcome: null, request: null, report: null } })).title).toBe("파일 검사 중");
    expect(presentExternalInspectionStatus(inspection({ inspection: { state: "INSPECTION_REPORTED", phase: "COMPLETE", outcome: [], request: null, report: null }, display: { state: "QUEUED", sanitizedDisplayRef: null, receiptDigest: null } })).title).toBe("정제 정사영상 준비 대기열");
    expect(presentExternalInspectionStatus(inspection({ inspection: { state: "INSPECTION_REPORTED", phase: "COMPLETE", outcome: [], request: null, report: null }, display: { state: "RUNNING", sanitizedDisplayRef: null, receiptDigest: null } })).title).toBe("정제 정사영상 준비 중");
    expect(presentExternalInspectionStatus(inspection({ inspection: { state: "INSPECTION_REPORTED", phase: "COMPLETE", outcome: [], request: null, report: null }, display: { state: "SEALED", sanitizedDisplayRef: "sda-v1-ready", receiptDigest: `sha256:${"a".repeat(64)}` } })).title).toBe("정제 정사영상 표시 가능");
  });

  it("keeps artifact failure reasons specific and marks only live server states for bounded refresh", () => {
    const incomplete = presentExternalInspectionStatus(inspection({
      inspection: {
        state: "INSPECTION_FAILED_INCOMPLETE",
        phase: "FAILED_INCOMPLETE",
        outcome: [
          { artifactId: "ortho", outcome: "REJECTED", reason: "GeoTIFF 좌표계 정보를 읽지 못했습니다." },
          { artifactId: "dsm", outcome: "MISSING", reason: "선언된 DSM 바이트가 없습니다." },
        ],
        request: null,
        report: null,
      },
    }));
    expect(incomplete.title).toBe("파일 검사 불완료");
    expect(incomplete.artifactReasons).toEqual([
      "정사영상: GeoTIFF 좌표계 정보를 읽지 못했습니다.",
      "DSM: 선언된 DSM 바이트가 없습니다.",
    ]);
    expect(incomplete.autoRefresh).toBe(false);
    expect(presentExternalInspectionStatus(inspection({
      inspection: { state: "INSPECTION_FAILED_INCOMPLETE", phase: "FAILED_INCOMPLETE", outcome: [], request: null, report: null },
    })).nextAction).not.toMatch(/아래 산출물별 사유/);
    expect(presentExternalInspectionStatus(inspection({
      inspection: {
        state: "INSPECTION_FAILED_INCOMPLETE", phase: "FAILED_INCOMPLETE",
        outcome: [{ artifactId: "ortho", outcome: "REJECTED", reason: "MISSING_CRS" }], request: null, report: null,
      },
    })).artifactReasons).toEqual(["정사영상: 좌표계 선언이 없습니다."]);
    expect(presentExternalInspectionStatus(inspection({
      inspection: {
        state: "INSPECTION_FAILED_INCOMPLETE", phase: "FAILED_INCOMPLETE",
        outcome: [{ artifactId: "ortho", outcome: "REJECTED", reason: "UNKNOWN_MACHINE_CODE" }], request: null, report: null,
      },
    })).artifactReasons).toEqual(["정사영상: 추가 확인이 필요합니다. 파일 정보 · 처리 상세의 사유 코드를 확인하세요."]);
    expect(presentExternalInspectionStatus(inspection({ inspection: { state: "INSPECTION_RUNNING", phase: "INSPECTION", outcome: null, request: null, report: null } })).autoRefresh).toBe(true);
    expect(presentExternalInspectionStatus(inspection({ inspection: { state: "INSPECTION_REPORTED", phase: "COMPLETE", outcome: [], request: null, report: null }, display: { state: "RETRY_EXHAUSTED", sanitizedDisplayRef: null, receiptDigest: null } })).nextAction).toMatch(/상태를 새로고침/);
  });

  it("never treats a malformed unknown state as ready or as an automatic retry signal", () => {
    const unknown = presentExternalInspectionStatus(inspection({ inspection: { state: "UNKNOWN" }, display: { state: "UNKNOWN" } }) as never);
    expect(unknown.title).toBe("검사 상태를 확인할 수 없음");
    expect(unknown.autoRefresh).toBe(false);
    expect(unknown.nextAction).toMatch(/새로고침/);
  });
});
