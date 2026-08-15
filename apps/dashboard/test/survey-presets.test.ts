import { describe, expect, it } from "vitest";

/**
 * 조사 수준 프리셋은 SurveyWizard.tsx 의 LEVEL_PRESETS 사본이다.
 *
 * 수준은 이제 **겹침**으로 정한다 — 간격(m)은 카메라와 고도가 있어야 계산되고 그
 * 계산은 서버가 한다(ADR-KSI-011 D3). 서버는 겹침 하한(전방 0.6·측면 0.5) 미만을
 * 422 로 거부하므로, 프리셋이 그 아래로 내려가면 그 수준은 절대 발급되지 않는다.
 *
 * 사본인 이유: 위저드는 "use client" + Leaflet 의존이라 vitest 노드 환경에서
 * import 할 수 없다. 값이 갈라지면 여기와 SurveyWizard.tsx 를 함께 갱신해야 한다.
 */
const LEVEL_PRESETS = {
  FAST: { frontOverlap: 0.65, sideOverlap: 0.55, autoFlightSpeedMs: 8 },
  STANDARD: { frontOverlap: 0.8, sideOverlap: 0.7, autoFlightSpeedMs: 5 },
  PRECISE: { frontOverlap: 0.9, sideOverlap: 0.8, autoFlightSpeedMs: 3 },
} as const;

// 서버 하한(ksi_mission_planning.camera) — 이보다 낮으면 정합점이 부족해 재구성 실패.
const MIN_FRONT_OVERLAP = 0.6;
const MIN_SIDE_OVERLAP = 0.5;

describe("조사 수준 프리셋", () => {
  it.each(Object.entries(LEVEL_PRESETS))(
    "%s — 겹침이 서버 하한 이상이다",
    (_level, preset) => {
      expect(preset.frontOverlap).toBeGreaterThanOrEqual(MIN_FRONT_OVERLAP);
      expect(preset.sideOverlap).toBeGreaterThanOrEqual(MIN_SIDE_OVERLAP);
    },
  );

  it.each(Object.entries(LEVEL_PRESETS))(
    "%s — 겹침이 1.0 미만이다(1.0 이면 간격 0 이라 같은 자리에서 무한 촬영)",
    (_level, preset) => {
      expect(preset.frontOverlap).toBeLessThan(1.0);
      expect(preset.sideOverlap).toBeLessThan(1.0);
    },
  );

  it.each(Object.entries(LEVEL_PRESETS))(
    "%s — 진행방향 겹침이 라인 간 겹침보다 크다(사진측량 관례)",
    (_level, preset) => {
      expect(preset.frontOverlap).toBeGreaterThan(preset.sideOverlap);
    },
  );

  it("정밀할수록 겹침이 커지고 속도가 느려진다", () => {
    const levels = [LEVEL_PRESETS.FAST, LEVEL_PRESETS.STANDARD, LEVEL_PRESETS.PRECISE];
    for (let i = 1; i < levels.length; i += 1) {
      expect(levels[i].frontOverlap).toBeGreaterThan(levels[i - 1].frontOverlap);
      expect(levels[i].sideOverlap).toBeGreaterThan(levels[i - 1].sideOverlap);
      expect(levels[i].autoFlightSpeedMs).toBeLessThan(levels[i - 1].autoFlightSpeedMs);
    }
  });
});

/**
 * ``closestSurveyLevel`` 사본 — SurveyWizard.tsx 의 것과 동일 로직(같은 사본
 * 사유, 위 docstring). 서버가 제안한 연속값 겹침(ADR-KSI-019 G5)을 위저드의
 * 3단계 프리셋 중 가장 가까운 것으로 매핑한다 — 위저드가 세 단계로만 겹침을
 * 고를 수 있어서다.
 */
function closestSurveyLevel(frontOverlap: number, sideOverlap: number): keyof typeof LEVEL_PRESETS {
  let best: keyof typeof LEVEL_PRESETS = "STANDARD";
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const key of Object.keys(LEVEL_PRESETS) as Array<keyof typeof LEVEL_PRESETS>) {
    const preset = LEVEL_PRESETS[key];
    const distance =
      Math.abs(preset.frontOverlap - frontOverlap) + Math.abs(preset.sideOverlap - sideOverlap);
    if (distance < bestDistance) {
      best = key;
      bestDistance = distance;
    }
  }
  return best;
}

describe("closestSurveyLevel", () => {
  it("정확히 STANDARD 프리셋과 같은 겹침은 STANDARD를 고른다", () => {
    expect(closestSurveyLevel(0.8, 0.7)).toBe("STANDARD");
  });

  it("INTENSIVE 도출값(0.85/0.8)은 STANDARD보다 PRECISE에 더 가깝다", () => {
    // STANDARD 거리 = |0.85-0.8|+|0.8-0.7| = 0.15, PRECISE 거리 = |0.85-0.9|+|0.8-0.8| = 0.05
    expect(closestSurveyLevel(0.85, 0.8)).toBe("PRECISE");
  });

  it("FAST 프리셋과 같은 낮은 겹침은 FAST를 고른다", () => {
    expect(closestSurveyLevel(0.65, 0.55)).toBe("FAST");
  });

  it("항상 세 프리셋 중 하나를 반환한다 — 임의 값을 지어내지 않는다", () => {
    const result = closestSurveyLevel(0.72, 0.6);
    expect(Object.keys(LEVEL_PRESETS)).toContain(result);
  });
});
