import { describe, expect, it } from "vitest";

import { presentAcquisitionReadiness } from "@/app/field/acquisition-readiness";
import type { AcquisitionProgressView, AcquisitionReadinessView } from "@/lib/core-api/types";

function readiness(overrides: Partial<AcquisitionReadinessView> = {}): AcquisitionReadinessView {
  return {
    siteId: "site-1",
    status: "INTERNET_REQUIRED",
    readyForMissionIssue: false,
    reasons: ["새 KSI 임무 발급 전 RC 인터넷이 필요하다"],
    evaluatedAt: "2026-08-21T09:00:00Z",
    profile: {
      schemaVersion: "1.0",
      siteId: "site-1",
      operatingMode: "RC_ATTENDED",
      gatewayKind: "RC_PLUS_2",
      gatewayTransports: ["WIFI", "CELLULAR"],
      internetGate: "REQUIRED_FOR_MISSION_ISSUE",
      manifoldDirectMode: "DISABLED",
      routingPolicy: "RC_STANDARD",
      mediaPolicy: "RESULTS_IMMEDIATE_RAW_POSTFLIGHT",
      msdkBridgeMode: "CONDITIONAL_PREFLIGHT_POSTFLIGHT",
      edgeDeviceId: "manifold-1",
      gatewayDeviceId: "rc-1",
    },
    connectivity: {
      schemaVersion: "1.0",
      snapshotId: "snapshot-1",
      siteId: "site-1",
      gatewayDeviceId: "rc-1",
      edgeDeviceId: "manifold-1",
      observedAt: "2026-08-21T09:00:00Z",
      expiresAt: "2026-08-21T09:02:00Z",
      transport: "WIFI",
      internetReachable: false,
      gatewayState: "CONNECTED",
      edgeState: "CONNECTED",
      directEdgeState: "DISABLED",
      queuedEventCount: 0,
      queuedMediaCount: 12,
      lastSuccessReceiptId: null,
      missionContractSync: "ACTIVATED",
      rawMediaSync: "PENDING",
      capabilities: [],
    },
    inFlightContractPolicy: "REMAINS_VALID_UNTIL_CONTRACT_EXPIRY",
    ...overrides,
  };
}

describe("presentAcquisitionReadiness", () => {
  it("separates RC, Manifold, direct, contract, and raw media states", () => {
    const result = presentAcquisitionReadiness(readiness());
    expect(result.label).toBe("새 비행 임무 발급 차단");
    expect(result.rows.map((row) => row.label)).toEqual([
      "RC 인터넷",
      "Manifold 연결",
      "직접망 Add-on",
      "계약 동기화",
      "원본 동기화",
    ]);
    expect(result.rows[1].value).toBe("연결됨");
    expect(result.rows[2].value).toBe("사용 안 함");
    expect(result.rows[3].value).toBe("활성화 확인");
    expect(result.rows[4].value).toBe("동기화 중");
  });

  it("fails closed when Core readiness cannot be read", () => {
    const result = presentAcquisitionReadiness(null);
    expect(result.label).toBe("연결 상태 확인 불가");
    expect(result.tone).toBe("warning");
  });

  it("uses canonical progress for active contract and media status", () => {
    const progress = {
      contractActivation: { state: "ACTIVATED", activatedAt: "2026-08-21T09:00:00Z" },
      media: { state: "VERIFIED", itemCount: 12, sourceBundleDigest: "sha256:abc" },
    } as AcquisitionProgressView;
    const result = presentAcquisitionReadiness(readiness(), progress);
    expect(result.label).toBe("활성 계약 유지 · 새 비행 임무 차단");
    expect(result.rows[3].value).toBe("활성화 확인");
    expect(result.rows[4].value).toBe("검증 완료");
  });
});
