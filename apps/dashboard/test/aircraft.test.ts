import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { M4D_DRONE, M4D_WIDE_CAMERA } from "../src/lib/aircraft";

describe("M4D 기본값 단일 출처", () => {
  it("기종·페이로드는 공식 표 값이다 (Cloud API Product Support, 2026-08-18)", () => {
    expect(M4D_DRONE).toEqual({
      droneEnumValue: 100,
      droneSubEnumValue: 0,
      payloadEnumValue: 98,
    });
  });

  it("카메라는 공식 스펙 유도값이고 GSD 는 교체 전 대비 0.5% 이내다", () => {
    expect(M4D_WIDE_CAMERA.imageWidthPx).toBe(5280);
    expect(M4D_WIDE_CAMERA.imageHeightPx).toBe(3956);
    // 교체 전 대체값(1인치급 13.2/8.8/5472) 대비 픽셀 지상 크기 관성 확인 —
    // 기본값 교체가 격자·촬영 간격을 급변시키지 않는다는 안전 성질.
    const before = 13.2 / (8.8 * 5472);
    const after =
      M4D_WIDE_CAMERA.sensorWidthMm /
      (M4D_WIDE_CAMERA.focalLengthMm * M4D_WIDE_CAMERA.imageWidthPx);
    expect(Math.abs(after - before) / before).toBeLessThan(0.005);
  });

  for (const wizard of [
    "src/app/sites/new/SiteRegistrationWizard.tsx",
    "src/app/sites/[siteId]/surveys/new/SurveyWizard.tsx",
  ]) {
    it(`${wizard} 는 공유 상수를 쓰고 구 값을 하드코딩하지 않는다`, () => {
      const source = readFileSync(join(process.cwd(), wizard), "utf8");
      expect(source).toContain('from "@/lib/aircraft"');
      expect(source).not.toMatch(/droneEnumValue:\s*99/);
      expect(source).not.toMatch(/payloadEnumValue:\s*65534/);
      expect(source).not.toMatch(/sensorWidthMm:\s*13\.2/);
    });
  }
});
