import { describe, expect, it } from "vitest";

import { isConvexPolygon } from "@/lib/geometry";
import type { AoiVertex } from "@/lib/core-api/types";

// lawnmower(매핑) 패턴은 볼록 AOI 에서만 전체 커버를 보증한다 — 서버가 비볼록을
// NON_CONVEX_AOI 로 거부하므로, 이 함수가 느슨해지면 운영자는 "다 그리고 발급 눌렀는데
// 실패"를 겪는다. 반대로 너무 빡빡하면 정상 폴리곤을 못 그린다.

function poly(points: [number, number][]): AoiVertex[] {
  return points.map(([lonDeg, latDeg]) => ({ lonDeg, latDeg }));
}

describe("볼록 판정", () => {
  it("사각형은 볼록이다", () => {
    expect(isConvexPolygon(poly([[0, 0], [1, 0], [1, 1], [0, 1]]))).toBe(true);
  });

  it("정점 순서가 반대(시계/반시계)여도 볼록이다", () => {
    expect(isConvexPolygon(poly([[0, 1], [1, 1], [1, 0], [0, 0]]))).toBe(true);
  });

  it("삼각형은 볼록이다", () => {
    expect(isConvexPolygon(poly([[0, 0], [2, 0], [1, 1]]))).toBe(true);
  });

  it("오목한 ㄱ자 폴리곤은 거부한다", () => {
    expect(isConvexPolygon(poly([[0, 0], [2, 0], [2, 2], [1, 1], [0, 2]]))).toBe(false);
  });
});

describe("퇴화 입력", () => {
  it("정점이 3개 미만이면 폴리곤이 아니다", () => {
    expect(isConvexPolygon([])).toBe(false);
    expect(isConvexPolygon(poly([[0, 0]]))).toBe(false);
    expect(isConvexPolygon(poly([[0, 0], [1, 1]]))).toBe(false);
  });

  it("전부 공선(면적 0)이면 볼록이 아니다 — 독립 재검토 2차 B-4", () => {
    // 모든 외적이 0 이라 부호가 한 번도 정해지지 않는다. 이걸 볼록으로 통과시키면
    // 면적 0 짜리 AOI 가 발급 단계까지 흘러간다.
    expect(isConvexPolygon(poly([[0, 0], [1, 1], [2, 2]]))).toBe(false);
    expect(isConvexPolygon(poly([[0, 0], [1, 1], [2, 2], [3, 3]]))).toBe(false);
  });

  it("변 위에 중간점이 끼어도(부분 공선) 볼록 판정은 유지된다", () => {
    // 지도 클릭으로 그리면 한 변 위에 점이 하나 더 찍히는 일이 흔하다 —
    // 이걸 오목으로 판정하면 정상 작도를 거부하게 된다.
    expect(isConvexPolygon(poly([[0, 0], [1, 0], [2, 0], [2, 2], [0, 2]]))).toBe(true);
  });
});
