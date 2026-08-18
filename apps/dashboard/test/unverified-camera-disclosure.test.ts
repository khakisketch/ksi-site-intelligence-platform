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

  it("단일 출처가 무엇이 확정이고 무엇이 유도값인지 구분해 적어 둔다", () => {
    // 초점거리는 공식 미기재라 환산에서 역산한 값이다 — 그 구분이 사라지면
    // 화면의 지상 해상도가 실측 근거를 가진 숫자처럼 읽힌다.
    const aircraft = readFileSync(join(process.cwd(), "src/lib/aircraft.ts"), "utf8");
    expect(aircraft).toContain("유도");
    expect(aircraft).toContain("EXIF");
  });
});
