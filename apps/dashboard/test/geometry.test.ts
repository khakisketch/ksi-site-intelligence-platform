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

  it("음수 사분면 볼록 사각형도 볼록이다 (sign 비트 회귀)", () => {
    expect(
      isConvexPolygon(
        poly([
          [-1, -1],
          [1, -1],
          [1, 1],
          [-1, 1],
        ]),
      ),
    ).toBe(true);
  });

  it("부호 혼합 bow-tie는 오목으로 거부한다 (sign 비트 회귀)", () => {
    expect(
      isConvexPolygon(
        poly([
          [-1, -1],
          [1, 1],
          [-1, 1],
          [1, -1],
        ]),
      ),
    ).toBe(false);
  });

  it("역순·순환 시작점에서도 같은 도형은 같은 판정이다", () => {
    const quad: [number, number][] = [
      [-1, -1],
      [1, -1],
      [1, 1],
      [-1, 1],
    ];
    expect(isConvexPolygon(poly([...quad].reverse()))).toBe(true);
    expect(isConvexPolygon(poly([...quad.slice(2), ...quad.slice(0, 2)]))).toBe(true);
  });

  it("미세하지만 유효한 볼록 삼각형·사각형은 통과한다 (고정 1e-12 스냅 회귀)", () => {
    // 예전 코드는 외적 절댓값 1e-12 스냅으로 이런 작은 볼록을 일직선·오목으로
    // 오판했다. [경도, 위도] 순서에 주의.
    expect(
      isConvexPolygon(
        poly([
          [126.978, 37.5665],
          [126.9780008, 37.5665],
          [126.978, 37.5665008],
        ]),
      ),
    ).toBe(true);
    expect(
      isConvexPolygon(
        poly([
          [127, 37.5],
          [127.00001, 37.50001],
          [127.00001, 37.5000101],
          [127, 37.5000001],
        ]),
      ),
    ).toBe(true);
  });

  it("미세 사각형도 순서 반전·순환 시작점에 관계없이 볼록이다", () => {
    const quad: [number, number][] = [
      [127, 37.5],
      [127.00001, 37.50001],
      [127.00001, 37.5000101],
      [127, 37.5000001],
    ];
    expect(isConvexPolygon(poly([...quad].reverse()))).toBe(true);
    expect(isConvexPolygon(poly([...quad.slice(2), ...quad.slice(0, 2)]))).toBe(true);
  });

  it("미세한 오목 dent는 크기와 무관하게 거부한다", () => {
    expect(
      isConvexPolygon(
        poly([
          [127, 37.5],
          [127.00002, 37.5],
          [127.00002, 37.50002],
          [127.00001, 37.50001],
          [127, 37.50002],
        ]),
      ),
    ).toBe(false);
  });

  it("이진수에서 정확히 공선인 삼각형은 볼록이 아니다 (정확 0 스킵 유지)", () => {
    // .5 단위 좌표는 이진수에서도 정확하므로 외적이 정확히 0이라 투표가 없고,
    // 부호가 한 번도 정해지지 않는다.
    expect(
      isConvexPolygon(
        poly([
          [126.5, 37.5],
          [127.0, 38.0],
          [127.5, 38.5],
        ]),
      ),
    ).toBe(false);
  });

  it("십진 표기상 공선이어도 이진 제출값이 삼각형이면 볼록이다", () => {
    // 모든 비퇴화 삼각형은 수학적으로 볼록하다. 십진 "126.978/37.5665…" 표기는
    // 일직선처럼 보여도 제출 double 값은 미세 삼각형을 이루므로 볼록이 맞다 —
    // 예전 1e-12 스냅은 이를 오목으로 오판했다. 십진 의도와 제출값의 1ulp급
    // 차이는 boolean API에서 구분하지 않으며(위자드 한계로 보고), 정확히 0인
    // 경우만 투표에서 제외하는 보수 방향을 유지한다.
    expect(
      isConvexPolygon(
        poly([
          [126.978, 37.5665],
          [126.979, 37.5666],
          [126.98, 37.5667],
        ]),
      ),
    ).toBe(true);
  });

  it("변 위 중간점이 있어도 볼록 판정은 유지된다", () => {
    expect(isConvexPolygon(poly([[0, 0], [1, 0], [2, 0], [2, 0.00001], [0, 0.00001]]))).toBe(true);
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
