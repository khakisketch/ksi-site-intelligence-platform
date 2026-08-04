import { describe, expect, it } from "vitest";

/**
 * 조사 수준 프리셋은 SurveyWizard.tsx 의 LEVEL_PRESETS 사본이다.
 *
 * 서버(packages/mission-planning coverage.py)는 진행방향 촬영 간격이 스캔선
 * 간격보다 성기면 422 로 거부한다 — 프리셋이 그 규칙을 어기면 사용자는 조사
 * 계획을 다 채우고 발급 단계에서야 실패를 본다. 값을 바꿀 때 이 테스트가 먼저 막는다.
 *
 * 사본인 이유: 위저드는 "use client" + Leaflet 의존이라 vitest 노드 환경에서
 * import 할 수 없다. 값이 갈라지면 여기와 SurveyWizard.tsx 를 함께 갱신해야 한다.
 */
const LEVEL_PRESETS = {
  FAST: { spacingM: 30, captureIntervalM: 22, autoFlightSpeedMs: 8 },
  STANDARD: { spacingM: 20, captureIntervalM: 15, autoFlightSpeedMs: 5 },
  PRECISE: { spacingM: 10, captureIntervalM: 7, autoFlightSpeedMs: 3 },
} as const;

const MIN_CAPTURE_INTERVAL_M = 0.1;

describe("조사 수준 프리셋", () => {
  it.each(Object.entries(LEVEL_PRESETS))(
    "%s — 촬영 간격이 격자 간격 이하다(서버 결합 게이트)",
    (_level, preset) => {
      expect(preset.captureIntervalM).toBeLessThanOrEqual(preset.spacingM);
    },
  );

  it.each(Object.entries(LEVEL_PRESETS))(
    "%s — 촬영 간격이 서버 하한 이상이다",
    (_level, preset) => {
      expect(preset.captureIntervalM).toBeGreaterThanOrEqual(MIN_CAPTURE_INTERVAL_M);
    },
  );

  it("정밀할수록 격자·촬영 간격이 함께 촘촘해진다", () => {
    const levels = [LEVEL_PRESETS.FAST, LEVEL_PRESETS.STANDARD, LEVEL_PRESETS.PRECISE];
    for (let i = 1; i < levels.length; i += 1) {
      expect(levels[i].spacingM).toBeLessThan(levels[i - 1].spacingM);
      expect(levels[i].captureIntervalM).toBeLessThan(levels[i - 1].captureIntervalM);
    }
  });
});
