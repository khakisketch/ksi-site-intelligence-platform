import type { AoiVertex } from "@/lib/core-api/types";

// lawnmower(매핑) 패턴은 볼록 AOI 에서만 전체 커버를 보증한다 — 서버가 비볼록을
// NON_CONVEX_AOI 로 거부한다(packages/mission-planning/src/ksi_mission_planning/coverage.py).
// 미리 걸러 "그려보고서야 발급 실패"를 막는다(§7 구현 노트와 동일한 정신).

// --- 정확한 외적 부호 (임의 epsilon 없음) ---
//
// 작은 도형에서는 외적 값이 1e-12 아래로 내려간다. 예전 코드는 절댓값 기준으로
// 0에 스냅했으므로 미세하지만 유효한 볼록 AOI를 일직선(투표 제외)·오목(부호
// 뒤집힘)으로 오판했다. double은 가수×2^지수 꼴의 정확한 이진 유리수이므로
// BigInt로 부호를 정확히 계산한다 — 지리 면적 한계·좌표 보정이 아니라 제출된
// 값 그대로의 판정이라 새 정책이 아니다. 지도 교차 판정
// (`AoiPolygonMapInner`의 `_orientSign`)과 같은 수학을 쓴다. 파일이 달라
// 복제한다 — 한쪽을 고치면 다른 쪽의 회귀를 함께 돌릴 것.
//
// 불확실성 한계: 여기서 확정하는 것은 유한 JS 좌표의 평면모델 기준이다.
// 입력 문자열의 십진 의도(예: "37.5000001")나 지도 투영 반올림과의 1ulp급
// 차이는 이 boolean API에서 구분하지 않는다 — 정확히 0인 변은 투표하지
// 않으므로 유효하다고 단정하지 않는 보수 방향이다. 호출자(현장 등록
// 위자드)는 boolean만 소비해 전부 "오목" 문구로 내보내므로, 퇴화·불확실과
// 진짜 오목을 구분해 설명하려면 위자드 문구 경로의 변경이 별도로 필요하다.
function _pow2(n: number): bigint {
  return BigInt(2) ** BigInt(Math.max(0, Math.floor(n)));
}

function _doubleParts(x: number): { m: bigint; e: number } {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const bits =
    BigInt(view.getUint32(0)) * BigInt(4294967296) + BigInt(view.getUint32(4));
  const negative = (bits >> BigInt(63)) === BigInt(1);
  const expBits = Number((bits >> BigInt(52)) % BigInt(2048));
  const frac = bits % _pow2(52);
  let out: { m: bigint; e: number };
  if (expBits === 0) out = { m: frac, e: -1074 }; // 비정규수·±0
  // Infinity/NaN — 유한 검사가 선행하므로 도달 불가, 방어 분기다.
  else if (expBits === 2047) out = { m: BigInt(0), e: 0 };
  else out = { m: _pow2(52) + frac, e: expBits - 1075 };
  return negative ? { m: -out.m, e: out.e } : out;
}

type _Dyadic = { m: bigint; e: number };

function _subDyadic(a: _Dyadic, b: _Dyadic): _Dyadic {
  const e = Math.min(a.e, b.e);
  return { m: a.m * _pow2(a.e - e) - b.m * _pow2(b.e - e), e };
}

function _mulDyadic(a: _Dyadic, b: _Dyadic): _Dyadic {
  return { m: a.m * b.m, e: a.e + b.e };
}

/** 외적 (b-a)×(c-a)의 정확한 부호 — 제출된 double 값 그대로의 판정이다. */
function _orientSign(
  ax: number,
  ay: number,
  bx: number,
  by: number,
  cx: number,
  cy: number,
): -1 | 0 | 1 {
  const dx1 = _subDyadic(_doubleParts(bx), _doubleParts(ax));
  const dy1 = _subDyadic(_doubleParts(by), _doubleParts(ay));
  const dx2 = _subDyadic(_doubleParts(cx), _doubleParts(ax));
  const dy2 = _subDyadic(_doubleParts(cy), _doubleParts(ay));
  const cross = _subDyadic(_mulDyadic(dx1, dy2), _mulDyadic(dy1, dx2));
  if (cross.m === BigInt(0)) return 0;
  return cross.m > BigInt(0) ? 1 : -1;
}

export function isConvexPolygon(vertices: AoiVertex[]): boolean {
  if (vertices.length < 3) return false;
  let sign = 0;
  const n = vertices.length;
  for (let i = 0; i < n; i++) {
    const a = vertices[i];
    const b = vertices[(i + 1) % n];
    const c = vertices[(i + 2) % n];
    const currentSign = _orientSign(
      a.lonDeg,
      a.latDeg,
      b.lonDeg,
      b.latDeg,
      c.lonDeg,
      c.latDeg,
    );
    if (currentSign === 0) continue; // 정확히 일직선 — 부호 판정 보류
    if (sign === 0) {
      sign = currentSign;
    } else if (currentSign !== sign) {
      return false;
    }
  }
  // 모든 변이 정확히 일직선(면적 0)이면 부호가 한 번도 정해지지 않는다 — 이런
  // 퇴화 폴리곤을 볼록으로 통과시키지 않는다(독립 재검토 2차 B-4).
  return sign !== 0;
}
