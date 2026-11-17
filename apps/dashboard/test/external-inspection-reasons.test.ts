import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { presentExternalInspectionStatus } from "@/app/field/external-reconstruction-status";
import type { ExternalArtifactInspectionView } from "@/lib/core-api/external-reconstruction";
import { describeInspectionReason } from "@/lib/external-inspection-reasons";

// 검사기가 REJECTED 로 돌려주는 사유 코드 목록이다(external_geotiff_inspector.py 의 _rejected 호출).
const INSPECTOR_REASONS = [
  "RESOURCE_LIMIT_EXCEEDED", "MALFORMED_TIFF", "UNSAFE_EXTERNAL_REFERENCE",
  "AMBIGUOUS_GEOREFERENCE", "UNMASKED_NONFINITE_SAMPLE", "UNSUPPORTED_RASTER",
];

function rejected(reason: string): ExternalArtifactInspectionView {
  return {
    registrationState: "SEALED", sealState: "SEALED",
    inspection: { state: "INSPECTION_FAILED_INCOMPLETE", phase: "FAILED_INCOMPLETE", outcome: [{ artifactId: "dsm", outcome: "REJECTED", reason }], request: null, report: null },
    display: { state: "PENDING_INSPECTION", sanitizedDisplayRef: null, receiptDigest: null },
  } as ExternalArtifactInspectionView;
}

describe("검사 거부 사유 번역", () => {
  it("검사기가 내는 모든 사유 코드에 설명과 다시 내보내는 방법이 있다", () => {
    for (const code of INSPECTOR_REASONS) {
      const described = describeInspectionReason(code);
      expect(described, code).not.toBeNull();
      expect(described?.text.length).toBeGreaterThan(10);
      expect(described?.fix.length).toBeGreaterThan(10);
      expect(described?.text).not.toContain(code);
    }
  });

  it("검사기 소스의 사유 코드 목록과 어긋나지 않는다", () => {
    const source = readFileSync(resolve(__dirname, "../../../services/processing-controller/src/ksi_processing_controller/external_geotiff_inspector.py"), "utf8");
    const found = [...source.matchAll(/_rejected\(artifact_id, observed_sha256, "([A-Z_]+)"\)/g)].map((match) => match[1]);
    expect(new Set(found)).toEqual(new Set(INSPECTOR_REASONS));
  });

  it("모르는 코드와 객체 내장 이름은 null 로 접는다", () => {
    for (const code of ["UNKNOWN_MACHINE_CODE", "constructor", "toString", "__proto__", ""]) {
      expect(describeInspectionReason(code), code).toBeNull();
    }
  });

  it("작업 상세의 산출물별 사유 목록에 번역과 방법이 함께 나온다", () => {
    const reasons = presentExternalInspectionStatus(rejected("MALFORMED_TIFF")).artifactReasons;
    expect(reasons).toHaveLength(1);
    expect(reasons[0]).toMatch(/^DSM: 파일을 TIFF로 읽지 못했거나/);
    expect(reasons[0]).toContain("Float32 한 밴드로 다시 내보내 보세요");
    expect(reasons[0]).not.toContain("추가 확인이 필요합니다");
  });

  it("모르는 코드는 기존 일반 문구를 유지한다", () => {
    expect(presentExternalInspectionStatus(rejected("SOMETHING_NEW")).artifactReasons).toEqual(["DSM: 추가 확인이 필요합니다. 파일·식별 상세의 사유 코드를 확인하세요."]);
  });
});
