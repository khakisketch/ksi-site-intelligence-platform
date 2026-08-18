/** 비교 실패 사유의 **두 층 분리** 회귀.
 *
 * 2026-08-18 실제 파이프라인 종단 실행에서 나온 문장을 그대로 고정한다 — 운영자가
 * 첫 문장에서 좌표계 세대 지식을 요구받지 않아야 하고, 그렇다고 근거가 화면에서
 * 사라져서도 안 된다.
 */

import { describe, expect, it } from "vitest";

import { describeComparisonFailure } from "../src/lib/comparison-failure";

const REAL_CRS_DETAIL =
  "EPSG:32617 은 지원 투영좌표계가 아니다 — 허용: ['EPSG:5179', 'EPSG:5185', 'EPSG:5186', " +
  "'EPSG:5187', 'EPSG:5188']. 구 측지계(Bessel, EPSG:5173~5177)를 현행 KGD2002 와 섞으면 " +
  "수백 미터 오차가 조용히 들어온다";

describe("비교 실패 사유", () => {
  it("좌표계 실패는 사람이 읽는 문장이 앞에 오고 원문은 근거로 남는다", () => {
    const { summary, evidence } = describeComparisonFailure(REAL_CRS_DETAIL);
    expect(summary).toContain("한국 좌표계가 아니어서");
    // 첫 문장에 EPSG 코드가 나오면 안 된다 — 그게 이 함수의 존재 이유다.
    expect(summary).not.toContain("EPSG");
    expect(evidence).toBe(REAL_CRS_DETAIL);
  });

  it("구역이 빈 경우는 무엇을 고쳐야 하는지 말한다", () => {
    const { summary } = describeComparisonFailure("구역 안에 유효한 높이자료 셀이 없다");
    expect(summary).toContain("구역");
    expect(summary).toContain("다시 그려");
  });

  it("모르는 사유는 번역하지 않는다 — 지어낸 요약보다 원문이 낫다", () => {
    const raw = "워커가 알 수 없는 이유로 죽었다(exit 137)";
    const { summary, evidence } = describeComparisonFailure(raw);
    expect(summary).toBe(raw);
    // 요약이 곧 원문이면 같은 말을 두 번 쓰지 않는다.
    expect(evidence).toBeNull();
  });

  it("사유가 아예 없는 경우와 빈 문자열을 같게 다룬다", () => {
    for (const value of [null, "", "   "]) {
      const { summary, evidence } = describeComparisonFailure(value);
      expect(summary).toContain("사유를 기록하지 않아");
      expect(evidence).toBeNull();
    }
  });
});
