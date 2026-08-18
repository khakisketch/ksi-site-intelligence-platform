import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// 격자 간격·촬영 간격·지상 해상도는 전부 DEFAULT_CAMERA 에서 파생된다. 그 상수가
// M4D 실측이 아니라는 사실이 코드 주석에만 있으면 사용자는 확정값으로 읽는다 —
// 값을 고치는 것은 FIELD-0a 의 일이고, 여기서 할 수 있는 것은 무엇에 기대고 있는지
// 밝히는 것이다(risk mapping-camera-constants-are-not-m4d, INV-040 의 정신).
const SURVEY = readFileSync(
  join(process.cwd(), "src/app/sites/[siteId]/surveys/new/SurveyWizard.tsx"),
  "utf8",
);
const SITE_REGISTRATION = readFileSync(
  join(process.cwd(), "src/app/sites/new/SiteRegistrationWizard.tsx"),
  "utf8",
);

describe("미검증 카메라 상수 고지", () => {
  it("[핵심] 파생 수치를 보여주는 자리에 근거가 미검증이라는 고지가 함께 있다", () => {
    expect(SURVEY).toContain("지상 해상도");
    expect(SURVEY).toContain("M4D 실측 전");
  });

  it("기체 식별번호 99 가 우리 기체 값이 아니라는 출처가 두 위저드 모두에 남아 있다", () => {
    // 99 는 M4T(열화상) 추정값이고 M4D 추정은 1000 이다. 근거 없는 매직넘버로
    // 두면 Pilot 2 가 거부하거나 다른 기체 프로파일로 해석해도 이유를 못 찾는다.
    for (const source of [SURVEY, SITE_REGISTRATION]) {
      expect(source).toContain("droneEnumValue: 99");
      expect(source).toContain("M4D");
    }
  });
});
