import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

// 격자 간격·촬영 간격·지상 해상도는 전부 DEFAULT_CAMERA 에서 파생된다. 실측된 값과
// 공칭값의 경계를 숨기지 않고, 측량급 정확도로 오해할 표현을 막는다.
const SURVEY = readFileSync(
  join(process.cwd(), "src/app/sites/[siteId]/surveys/new/SurveyWizard.tsx"),
  "utf8",
);
const SITE_REGISTRATION = readFileSync(
  join(process.cwd(), "src/app/sites/new/SiteRegistrationWizard.tsx"),
  "utf8",
);

describe("M4D 카메라 상수 근거 고지", () => {
  it("[핵심] 파생 수치를 보여주는 자리에 실측·공칭값 경계가 함께 있다", () => {
    expect(SURVEY).toContain("지상 해상도");
    expect(SURVEY).toContain("원본 EXIF 실측값");
    expect(SURVEY).toContain("센서 폭은 4/3형");
    expect(SURVEY).toContain("측량급 정확도를 의미하지 않습니다");
    expect(SURVEY).not.toContain("M4D 실측 전");
  });

  it("기체 값은 한 곳에서만 온다 — 위저드에 매직넘버를 다시 심지 않는다", () => {
    // 이 단언은 2026-08-18 병합에서 바뀌었다. 기종·페이로드는 DJI Cloud API 공식
    // 표로 **확정**됐으므로(100/0/98) 예전 단언("droneEnumValue: 99 라는 추정값과
    // 그 출처가 남아 있다")은 더 이상 사실을 지키지 못한다. 대신 지키는 것은
    // "두 위저드가 각자 숫자를 들고 있지 않다"이다 — 그래야 EXIF 실측이 도착했을 때
    // aircraft.ts 한 곳만 고치면 되고, 한쪽만 고쳐 갈라지는 일이 없다.
    for (const source of [SURVEY, SITE_REGISTRATION]) {
      expect(source).toContain("M4D_DRONE");
      expect(source).toContain('from "@/lib/aircraft"');
      expect(source).not.toMatch(/droneEnumValue:\s*\d/);
    }
  });

  it("단일 출처가 실초점거리의 FIELD-0a EXIF 근거를 남긴다", () => {
    const aircraft = readFileSync(join(process.cwd(), "src/lib/aircraft.ts"), "utf8");
    expect(aircraft).toContain("12.29mm");
    expect(aircraft).toContain("WideCamera EXIF");
    expect(aircraft).toContain("EXIF");
  });
});
