"use client";

import L from "leaflet";
import "leaflet-draw";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { MapContainer, TileLayer, useMap } from "react-leaflet";

import type { AoiVertex } from "@/lib/core-api/types";

// Site/WorkArea의 WGS84 화면 입력·읽기 전용 표시. 원본 CRS 변환은 호출부의
// display-geometry가 맡으며 여기서 자료의 위치 정확도나 분석 적합성을 판정하지 않는다.
// leaflet-draw는 전역 L에 컨트롤을 붙이므로 클라이언트 전용으로 로드한다.

const _MAX_AOI_VERTICES = 256;

/** 키보드 입력이 지도와 공유하는 좌표계 — 지도 출력과 같은 WGS84 위경도다. */
export const KEYBOARD_CRS_LABEL = "EPSG:4326";

export interface KeyboardVertexRow {
  lat: string;
  lon: string;
}

/** Optional in-memory handoff. Active Leaflet gestures are not captured. */
export interface AoiRawSnapshot {
  rows: KeyboardVertexRow[];
  rejectedDraws: Array<{ vertices: AoiVertex[]; reason: string }>;
}

export type ParseCoordinateResult = { ok: true; value: number } | { ok: false; reason: string };

/**
 * 키보드 입력 한 칸의 순수 판정 — 빈칸·십진수 아님·무한대·위경도 범위를
 * 추측 없이 막는다. `Number()`는 "0x10"을 16으로 읽는 등 십진 위경도가
 * 아닌 문자열을 예기치 않게 해석하므로, 십진수 모양을 정규식으로 먼저
 * 고정한다(지수 표기 `1e-3`은 십진수라 받는다). 범위(위도 -90~90,
 * 경도 -180~180)는 Core 양쪽 계약(`AreaOfInterest`·`assert_polygon_is_usable`)이
 * EPSG:4326에 매기는 범위와 같은 바닥이다. 제출값을 만들지 않으며,
 * placeholder 예시 숫자를 둔 적도 없다 — 빈칸은 빈칸으로 막는다.
 */
export function parseKeyboardCoordinate(
  text: string,
  axis: "lat" | "lon",
): ParseCoordinateResult {
  const trimmed = text.trim();
  const label = axis === "lat" ? "위도" : "경도";
  if (trimmed === "") return { ok: false, reason: `${label}를 입력하세요.` };
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(trimmed)) {
    return { ok: false, reason: `${label} "${trimmed}"은 십진수 숫자 형식이 아닙니다.` };
  }
  const value = Number(trimmed);
  if (!Number.isFinite(value)) {
    return { ok: false, reason: `${label} "${trimmed}"은 숫자가 아닙니다.` };
  }
  if (axis === "lat" && (value < -90 || value > 90)) {
    return { ok: false, reason: `위도 ${value}°은 범위(-90~90)를 벗어났습니다.` };
  }
  if (axis === "lon" && (value < -180 || value > 180)) {
    return { ok: false, reason: `경도 ${value}°은 범위(-180~180)를 벗어났습니다.` };
  }
  return { ok: true, value };
}

export type ValidateKeyboardResult =
  | { ok: true; vertices: AoiVertex[] }
  | { ok: false; reason: string; rowIndex?: number }
  | { ok: false; uncertain: true; reason: string; rowIndex?: never };

/**
 * 배정밀도(double) 좌표 외적의 정확한 부호 — 임의 epsilon 없음.
 *
 * 작은 도형에서는 외적 값이 1e-12 아래로 내려간다. 예전 코드는 절댓값
 * epsilon으로 0에 스냅한 뒤 bbox 포함만으로 "선 위"를 판정했으므로, 평행하고
 * 닿지 않는 미세 사각형까지 교차로 거부했다(외적 1e-12가 스냅되고 bbox
 * 모서리가 걸리면 접촉으로 둔갑한다). double은 가수×2^지수 꼴의 정확한
 * 이진 유리수이므로 BigInt로 외적 부호를 정확히 계산한다 — 지리 면적·거리
 * 한계가 아니라 제출된 값 그대로의 판정이라 새 정책이 아니다. 포인터
 * (Leaflet.draw `segmentsIntersect`, 엄격 부등식)와 일반 케이스의 결론이
 * 같고, 정확 접촉(T-접촉·공선 중첩)도 지도 그리기와 같은 강도로 막는다.
 */
function _pow2(n: number): bigint {
  return BigInt(2) ** BigInt(Math.max(0, Math.floor(n)));
}

/** double 한 값을 정확한 이진 유리수(가수×2^지수)로 푼다. 부호 비트를 반드시 반영한다. */
const _scratchView = new DataView(new ArrayBuffer(8));
function _doubleParts(x: number): { m: bigint; e: number } {
  _scratchView.setFloat64(0, x);
  const bits =
    BigInt(_scratchView.getUint32(0)) * BigInt(4294967296) + BigInt(_scratchView.getUint32(4));
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
function _orientSignP(
  ax: _Dyadic,
  ay: _Dyadic,
  bx: _Dyadic,
  by: _Dyadic,
  cx: _Dyadic,
  cy: _Dyadic,
): -1 | 0 | 1 {
  const dx1 = _subDyadic(bx, ax);
  const dy1 = _subDyadic(by, ay);
  const dx2 = _subDyadic(cx, ax);
  const dy2 = _subDyadic(cy, ay);
  const cross = _subDyadic(_mulDyadic(dx1, dy2), _mulDyadic(dy1, dx2));
  if (cross.m === BigInt(0)) return 0;
  return cross.m > BigInt(0) ? 1 : -1;
}

/**
 * 10의 거듭제곱 BigInt — 십진 정밀도 계산용. 지수는 0 이상으로만 쓴다.
 */
function _pow10(n: number): bigint {
  return BigInt(10) ** BigInt(Math.max(0, Math.floor(n)));
}

/**
 * 십진 문자열을 정확한 유리수(정수 가수×10^지수)로 푼다.
 * `parseKeyboardCoordinate`가 받아들인 형식만 온다는 전제이며, 실패·과대
 * 정밀도(자릿수 40 초과·지수 절댓값 6000 초과)는 null(판정 불능)을 돌린다 —
 * float64 의미를 넘는 입력의 십진 의도는 확정할 수 없으므로 double 판정에
 * 맡기고 서버가 최종 판단한다.
 */
interface DecimalExact {
  m: bigint;
  e: number;
}

function _decimalExact(text: string): DecimalExact | null {
  const match = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/.exec(text.trim());
  if (!match) return null;
  const negative = match[1] === "-";
  const intPart = match[2] ?? "";
  const fracPart = match[3] ?? match[4] ?? "";
  const digits = `${intPart}${fracPart}`;
  if (digits === "" || digits.length > 40) return null;
  const exp = match[5] === undefined ? 0 : Number.parseInt(match[5], 10);
  if (!Number.isFinite(exp) || Math.abs(exp) > 6000) return null;
  const magnitude = BigInt(digits === "" ? "0" : digits);
  return { m: negative ? -magnitude : magnitude, e: exp - fracPart.length };
}

interface DecPoint {
  x: DecimalExact;
  y: DecimalExact;
}

function _decCmp(a: DecimalExact, b: DecimalExact): -1 | 0 | 1 {
  const e = Math.min(a.e, b.e);
  const am = a.m * _pow10(a.e - e);
  const bm = b.m * _pow10(b.e - e);
  if (am === bm) return 0;
  return am > bm ? 1 : -1;
}

function _decSub(a: DecimalExact, b: DecimalExact): DecimalExact {
  const e = Math.min(a.e, b.e);
  return { m: a.m * _pow10(a.e - e) - b.m * _pow10(b.e - e), e };
}

function _decMul(a: DecimalExact, b: DecimalExact): DecimalExact {
  return { m: a.m * b.m, e: a.e + b.e };
}

function _decSign(v: DecimalExact): -1 | 0 | 1 {
  if (v.m === BigInt(0)) return 0;
  return v.m > BigInt(0) ? 1 : -1;
}

/** 외적의 십진 정확 부호 — 입력 문자열 그대로의 판정이다. */
function _decOrientSign(a: DecPoint, b: DecPoint, c: DecPoint): -1 | 0 | 1 {
  const dx1 = _decSub(b.x, a.x);
  const dy1 = _decSub(b.y, a.y);
  const dx2 = _decSub(c.x, a.x);
  const dy2 = _decSub(c.y, a.y);
  return _decSign(_decSub(_decMul(dx1, dy2), _decMul(dy1, dx2)));
}

function _decOnSegment(a: DecPoint, b: DecPoint, p: DecPoint): boolean {
  const minX = _decCmp(a.x, b.x) <= 0 ? a.x : b.x;
  const maxX = _decCmp(a.x, b.x) >= 0 ? a.x : b.x;
  const minY = _decCmp(a.y, b.y) <= 0 ? a.y : b.y;
  const maxY = _decCmp(a.y, b.y) >= 0 ? a.y : b.y;
  return (
    _decCmp(minX, p.x) <= 0 &&
    _decCmp(p.x, maxX) <= 0 &&
    _decCmp(minY, p.y) <= 0 &&
    _decCmp(p.y, maxY) <= 0
  );
}

/**
 * 정확히 한 직선 위일 때만 구간의 bbox 포함을 본다 — 부동소수 오차 개입 없음.
 * 부호가 0이 아닐 때는 호출하지 않는다(스냅 판정 금지).
 */
function _onSegmentExact(
  a: readonly [number, number],
  b: readonly [number, number],
  p: readonly [number, number],
): boolean {
  return (
    Math.min(a[0], b[0]) <= p[0] &&
    p[0] <= Math.max(a[0], b[0]) &&
    Math.min(a[1], b[1]) <= p[1] &&
    p[1] <= Math.max(a[1], b[1])
  );
}

type PairKind = "cross" | "touch" | "miss";

type PairPoint = { x: _Dyadic; y: _Dyadic; nx: number; ny: number };

function _pairKindDouble(p1: PairPoint, p2: PairPoint, q1: PairPoint, q2: PairPoint): PairKind {
  const d1 = _orientSignP(q1.x, q1.y, q2.x, q2.y, p1.x, p1.y);
  const d2 = _orientSignP(q1.x, q1.y, q2.x, q2.y, p2.x, p2.y);
  const d3 = _orientSignP(p1.x, p1.y, p2.x, p2.y, q1.x, q1.y);
  const d4 = _orientSignP(p1.x, p1.y, p2.x, p2.y, q2.x, q2.y);
  if (d1 > 0 !== d2 > 0 && d3 > 0 !== d4 > 0) return "cross";
  if (d1 === 0 && _onSegmentExact([q1.nx, q1.ny], [q2.nx, q2.ny], [p1.nx, p1.ny])) return "touch";
  if (d2 === 0 && _onSegmentExact([q1.nx, q1.ny], [q2.nx, q2.ny], [p2.nx, p2.ny])) return "touch";
  if (d3 === 0 && _onSegmentExact([p1.nx, p1.ny], [p2.nx, p2.ny], [q1.nx, q1.ny])) return "touch";
  if (d4 === 0 && _onSegmentExact([p1.nx, p1.ny], [p2.nx, p2.ny], [q2.nx, q2.ny])) return "touch";
  return "miss";
}

function _pairKindDecimal(a: DecPoint, b: DecPoint, c: DecPoint, d: DecPoint): PairKind {
  const d1 = _decOrientSign(c, d, a);
  const d2 = _decOrientSign(c, d, b);
  const d3 = _decOrientSign(a, b, c);
  const d4 = _decOrientSign(a, b, d);
  if (d1 > 0 !== d2 > 0 && d3 > 0 !== d4 > 0) return "cross";
  if (d1 === 0 && _decOnSegment(c, d, a)) return "touch";
  if (d2 === 0 && _decOnSegment(c, d, b)) return "touch";
  if (d3 === 0 && _decOnSegment(a, b, c)) return "touch";
  if (d4 === 0 && _decOnSegment(a, b, d)) return "touch";
  return "miss";
}

/** double 제출값 고리의 부호 있는 면적 2배가 정확히 0인지 — 유한 입력 전제. */
function _doubleShoelaceIsZero(parts: readonly { x: _Dyadic; y: _Dyadic }[]): boolean {
  const terms: _Dyadic[] = [];
  for (let i = 0; i < parts.length; i++) {
    const p = parts[i]!;
    const q = parts[(i + 1) % parts.length]!;
    terms.push(_subDyadic(_mulDyadic(p.x, q.y), _mulDyadic(q.x, p.y)));
  }
  const e = Math.min(...terms.map((t) => t.e));
  let sum = BigInt(0);
  for (const t of terms) sum += t.m * _pow2(t.e - e);
  return sum === BigInt(0);
}

/** 십진 입력 고리의 부호 있는 면적 2배가 정확히 0인지. */
function _decimalShoelaceIsZero(points: readonly DecPoint[]): boolean {
  const terms: { m: bigint; e: number }[] = [];
  for (let i = 0; i < points.length; i++) {
    const p = points[i]!;
    const q = points[(i + 1) % points.length]!;
    terms.push({ m: p.x.m * q.y.m, e: p.x.e + q.y.e });
    terms.push({ m: -(q.x.m * p.y.m), e: q.x.e + p.y.e });
  }
  const e = Math.min(...terms.map((t) => t.e));
  let sum = BigInt(0);
  for (const t of terms) sum += t.m * _pow10(t.e - e);
  return sum === BigInt(0);
}

/**
 * 고리 판정의 공통 경계 — 포인터 emit와 키보드 commit이 같은 바닥을 쓴다.
 *
 * - 확실한 교차·접촉·퇴화와 확실한 비교차를 가른다. 확실함은 제출된 double
 *   값과(키보드에서는) 입력 문자열 십진값 양쪽에서 정확히 일치할 때뿐이다 —
 *   유한 JS 좌표의 평면모델 기준이며, 지도 타일의 픽셀 반올림이나 좌표계
 *   투영 정확도는 주장하지 않는다.
 * - 양쪽이 엇갈리면 `uncertain`이다. 임의 면적·거리 한계를 새로 정하지
 *   않으며, 기하·좌표를 변경·반올림·unwrap하지도 않는다. 불확실하면
 *   호출부가 제출하지 않고 원본·미반영을 그대로 보존한다.
 * - 유한하지 않은 좌표는 `uncertain`이다(조용히 통과·거부하지 않는다).
 * - 위경도 범위 밖(Core 계약 -90..90/-180..180)은 `range`로 명시 차단한다 —
 *   특히 포인터 경로(월드 복사 이동)의 범위 이탈을 감싸거나 클램프하지 않는다.
 */
/**
 * Web-Mercator(L.CRS.EPSG3857, Leaflet 기본 타일 좌표계)가 정확히 그릴 수 있는
 * 최대 위도. atan(sinh(π))를 도(°)로 환산한 값(≈85.0511°)으로, 이를 넘으면
 * Leaflet이 Y를 clamp 값(20037508.34278071)에 고정해 89° 입력도 85.05°와
 * 같은 픽셀에 그린다(설치된 Leaflet 실측으로 고정, `leaflet-mercator-clamp`
 * 테스트 참조). 투영 한계이지 제품 지리 정책이 아니다.
 */
const MAX_MERCATOR_LAT = (Math.atan(Math.sinh(Math.PI)) * 180) / Math.PI;

export type RingVerdict =
  | { kind: "ok" }
  | { kind: "duplicate"; i: number; j: number }
  | { kind: "intersect"; i: number; j: number }
  | { kind: "degenerate" }
  | { kind: "range"; axis: "lat" | "lon"; index: number; value: number }
  | { kind: "uncertain"; detail: string };

export function evaluateRingGeometry(
  vertices: readonly AoiVertex[],
  typed: readonly { lat: string; lon: string }[] | null,
): RingVerdict {
  const n = vertices.length;
  if (n < 3) return { kind: "ok" }; // 개수 판정은 호출부 몫이다.
  for (const v of vertices) {
    if (!Number.isFinite(v.latDeg) || !Number.isFinite(v.lonDeg)) {
      return { kind: "uncertain", detail: "유한하지 않은 좌표가 있어 관계를 확정할 수 없습니다." };
    }
  }
  // 위경도 범위 — Core 계약(-90..90, -180..180)과 같은 바닥이다. Leaflet은
  // 월드 복사 이동 시 경도 ±180 밖의 값을 낼 수 있으므로, 포인터 경로도
  // 여기서 명시적으로 막는다. 감싸거나 클램프하지 않으며(좌표 변경 금지),
  // 호출부가 제출하지 않고 원본·미반영을 그대로 보존한다.
  for (let i = 0; i < n; i++) {
    const v = vertices[i]!;
    if (v.latDeg < -90 || v.latDeg > 90) {
      return { kind: "range", axis: "lat", index: i, value: v.latDeg };
    }
    if (v.lonDeg < -180 || v.lonDeg > 180) {
      return { kind: "range", axis: "lon", index: i, value: v.lonDeg };
    }
  }
  // 표시 한계 — 지도에 그려 확인할 수 없는 입력은 제출하지 않는다.
  // 위도는 Web-Mercator clamp(≈85.05°)를 넘으면 실제와 다른 픽셀에 그려지고,
  // 경도 변이 날짜변경선을 넘으면(|Δ|>180) 지도에 가로질러 그려진다.
  // 어느 쪽도 좌표를 바꾸거나 감싸지 않으며, 제품의 지리 범위·정확도
  // 정책이 아니라 Leaflet 투영의 표현 한계다(실측 근거는 테스트 참조).
  const points = vertices.map((v) => [v.lonDeg, v.latDeg] as const);
  for (let i = 0; i < n; i++) {
    if (Math.abs(vertices[i]!.latDeg) > MAX_MERCATOR_LAT) {
      return {
        kind: "uncertain",
        detail: `위도 ${vertices[i]!.latDeg}°는 지도 투영(Leaflet Web-Mercator)의 그리기 한계(≈85.05°)를 넘어 지도에 실제 위치와 다르게 그려집니다.`,
      };
    }
    const q = vertices[(i + 1) % n]!;
    if (Math.abs(vertices[i]!.lonDeg - q.lonDeg) > 180) {
      return {
        kind: "uncertain",
        detail: `경도 ${vertices[i]!.lonDeg}°에서 ${q.lonDeg}°로 이어지는 변이 날짜변경선을 넘어 지도에 가로질러 그려집니다.`,
      };
    }
  }
  // 정밀도 계산의 입력 파싱은 고리당 한 번만 한다 — 쌍별 검사에서 재사용한다.
  // (판정은 동일하고 DataView/BigInt 재할당만 줄인다.)
  const dparts = vertices.map((v) => ({
    x: _doubleParts(v.lonDeg),
    y: _doubleParts(v.latDeg),
    nx: v.lonDeg,
    ny: v.latDeg,
  }));
  // 십진 정밀 좌표(키보드 입력 원문). 포인터 경로에는 원문이 없으므로
  // double 판정만 쓴다(아래 분기별 안내 참조).
  let typedDec: DecPoint[] | null = null;
  if (typed !== null && typed.length === n) {
    const list: DecPoint[] = [];
    let feasible = true;
    for (const row of typed) {
      const lat = _decimalExact(row.lat);
      const lon = _decimalExact(row.lon);
      if (lat === null || lon === null) {
        feasible = false;
        break;
      }
      list.push({ x: lon, y: lat });
    }
    if (feasible) typedDec = list;
  }
  if (typed !== null && typedDec === null) {
    // 십진 증명을 할 수 없는 키보드 입력 — double만으로 통과시키지 않고
    // 판단 보류로 막는다. 계산 한계(자릿수 40·지수 ±6000 초과)는 기하 정책이
    // 아니라 무한정 BigInt 계산을 막는 상한이며, 여기서 막힌 입력은
    // 되돌리기(불러오기)로 정식 표기로 되돌릴 수 있다.
    return {
      kind: "uncertain",
      detail: "십진 입력의 자릿수·지수가 계산 한계를 넘어 관계를 확정할 수 없습니다.",
    };
  }
  const decPoints = (i: number): DecPoint => typedDec![i]!;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if (points[i]![0] !== points[j]![0] || points[i]![1] !== points[j]![1]) continue;
      // 키보드 원문이 서로 다른데 double 변환으로 같은 점이 되었다면
      // 실제로 같은 점이라고 단정하지 않는다. 두 입력과 기존 값은 그대로 둔다.
      if (typedDec !== null && (
        _decCmp(decPoints(i).x, decPoints(j).x) !== 0 ||
        _decCmp(decPoints(i).y, decPoints(j).y) !== 0
      )) {
        return { kind: "uncertain", detail: `꼭짓점 ${i + 1}과 ${j + 1}은 십진 입력이 다르지만 제출 좌표로 변환하면 같아집니다.` };
      }
      return { kind: "duplicate", i, j };
    }
  }
  // 변 bbox — plain number 비교만으로 겹치지 않으면 만날 수 없다(정확하므로
  // 판정이 바뀌지 않는다). 겹치는 쌍만 정밀 판정으로 넘겨 BigInt 비용을 줄인다.
  const eb = points.map((_, i) => {
    const a = points[i]!;
    const b = points[(i + 1) % n]!;
    return {
      minX: Math.min(a[0], b[0]),
      maxX: Math.max(a[0], b[0]),
      minY: Math.min(a[1], b[1]),
      maxY: Math.max(a[1], b[1]),
    };
  });
  const disjoint = (i: number, j: number): boolean =>
    eb[i]!.maxX < eb[j]!.minX ||
    eb[j]!.maxX < eb[i]!.minX ||
    eb[i]!.maxY < eb[j]!.minY ||
    eb[j]!.maxY < eb[i]!.minY;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      if ((j + 1) % n === i || (i + 1) % n === j) continue;
      if (disjoint(i, j)) continue;
      const a = dparts[i]!;
      const b = dparts[(i + 1) % n]!;
      const c = dparts[j]!;
      const d = dparts[(j + 1) % n]!;
      const dd = _pairKindDouble(a, b, c, d);
      if (typedDec === null) {
        if (dd !== "miss") return { kind: "intersect", i, j };
        continue;
      }
      const dec = _pairKindDecimal(
        decPoints(i),
        decPoints((i + 1) % n),
        decPoints(j),
        decPoints((j + 1) % n),
      );
      if (dd === dec) {
        if (dd !== "miss") return { kind: "intersect", i, j };
        continue;
      }
      return {
        kind: "uncertain",
        detail: `변 ${i + 1}↔${j + 1}의 위치 관계가 십진 입력과 제출 좌표에서 엇갈립니다.`,
      };
    }
  }
  const ddZero = _doubleShoelaceIsZero(dparts);
  const decZero = typedDec === null ? null : _decimalShoelaceIsZero(typedDec);
  if (ddZero && decZero === true) return { kind: "degenerate" };
  if (ddZero && decZero === null) {
    // 포인터 경로: 제출된 double은 정확히 0이지만 확인할 십진 원문이 없다.
    // 십진 불일치 얘기를 하지 않고, 원문 부재를 근거로 판단 보류한다.
    return {
      kind: "uncertain",
      detail: "제출 좌표는 면적 0이지만 확인할 십진 원문이 없어 확정할 수 없습니다.",
    };
  }
  if (ddZero || decZero === true) {
    return {
      kind: "uncertain",
      detail: "면적 0 여부가 십진 입력과 제출 좌표에서 엇갈립니다.",
    };
  }
  return { kind: "ok" };
}

/**
 * 키보드 행들의 순수 판정 — 통과분만 `onChange` 재료가 된다.
 *
 * 포인터 emit와 같은 공통 경계(`evaluateRingGeometry`)를 쓴다: 형식(십진수)·
 * 3점 미만·256점 초과·유한하지 않음·위경도 범위 밖·정확 중복점·확실한
 * 자기교차·확실한 퇴화(면적 정확 0)는 막는다. 작업구역 계약과 포인터
 * 그리기에 면적 하한이 없으므로 임계값을 새로 정하지 않는다 — 정확히 0일
 * 때만 퇴화로 막고, 십진 입력과 제출 좌표가 엇갈리는 머리털 끝 차이에서는
 * 교차라고도 등록 가능하다고도 말하지 않고 판단 보류로 막는다. 어느 쪽도
 * 기하·좌표를 변경·반올림·unwrap하지 않으며, 통과했다고 등록 확정을
 * 말하지 않는다. 확실함은 유한 JS 좌표의 평면모델 기준이며, 지도 타일의
 * 픽셀 반올림·좌표계 투영 정확도는 주장하지 않는다.
 */
export function validateKeyboardVertices(rows: readonly KeyboardVertexRow[]): ValidateKeyboardResult {
  if (rows.length < 3) {
    return { ok: false, reason: `꼭짓점을 3개 이상 입력하세요(지금 ${rows.length}개). 지도에서 그릴 때와 같은 기준입니다.` };
  }
  if (rows.length > _MAX_AOI_VERTICES) {
    return {
      ok: false,
      reason: `꼭짓점이 너무 많습니다(${rows.length}개, 상한 ${_MAX_AOI_VERTICES}개). 지도 그리기도 같은 상한입니다.`,
    };
  }
  const vertices: AoiVertex[] = [];
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i]!;
    const lat = parseKeyboardCoordinate(row.lat, "lat");
    if (!lat.ok) return { ok: false, reason: `꼭짓점 ${i + 1} ${lat.reason}`, rowIndex: i };
    const lon = parseKeyboardCoordinate(row.lon, "lon");
    if (!lon.ok) return { ok: false, reason: `꼭짓점 ${i + 1} ${lon.reason}`, rowIndex: i };
    vertices.push({ latDeg: lat.value, lonDeg: lon.value });
  }
  const verdict = evaluateRingGeometry(vertices, rows);
  if (verdict.kind === "duplicate") {
    return {
      ok: false,
      reason: `꼭짓점 ${verdict.i + 1}과 ${verdict.j + 1}이 같은 점입니다 — 같은 점을 두 번 지나면 구역이 될 수 없습니다.`,
      rowIndex: verdict.j,
    };
  }
  if (verdict.kind === "intersect") {
    return {
      ok: false,
      reason: `선이 서로 교차합니다(변 ${verdict.i + 1}↔${verdict.j + 1}). 현장 범위는 선이 서로 교차하지 않도록 그려야 합니다.`,
    };
  }
  if (verdict.kind === "degenerate") {
    return {
      ok: false,
      reason: "입력한 점이 정확히 한 직선 위에 있어 면적이 0입니다 — 구역이 아닙니다.",
    };
  }
  if (verdict.kind === "range") {
    // 키보드 입력은 parse 단계에서 걸리므로 도달 불가한 방어 분기다.
    // 포인터 경로(월드 복사 이동)가 실제 도달처다.
    const label = verdict.axis === "lat" ? "위도" : "경도";
    const bound = verdict.axis === "lat" ? "-90~90" : "-180~180";
    return {
      ok: false,
      reason: `꼭짓점 ${verdict.index + 1} ${label} ${verdict.value}°은 범위(${bound})를 벗어났습니다.`,
    };
  }
  if (verdict.kind === "uncertain") {
    return {
      ok: false,
      uncertain: true,
      reason: `입력한 점들의 위치 관계를 확정할 수 없습니다 — 판단하지 못했습니다. ${verdict.detail} 입력한 값과 기존 반영값은 바꾸지 않았습니다.`,
    };
  }
  return { ok: true, vertices };
}

function toKeyboardRows(value: readonly AoiVertex[]): KeyboardVertexRow[] {
  return value.map((v) => ({ lat: String(v.latDeg), lon: String(v.lonDeg) }));
}

/**
 * 상한 초과를 조용히 자르지 않기 위한 문구 — 포인터 그리기가 상한을 넘기면
 * 이 문장으로 명시하고 기존 반영값을 복원한다. 계약 상한(256)은 바꾸지 않는다.
 */
export function vertexLimitMessage(count: number): string {
  return `꼭짓점이 너무 많습니다(${count}개, 상한 ${_MAX_AOI_VERTICES}개). ${_MAX_AOI_VERTICES}개 이하로 다시 그려 주세요. 기존에 반영된 범위는 그대로 유지됩니다.`;
}

/**
 * 포인터 진행 중 상태의 순수 판정 — Leaflet.draw 실제 이벤트에 대응한다.
 *
 * - draw: 그리기 핸들러 활성(`draw:drawstart`~`draw:drawstop`). 완료는
 *   `draw:created`가 정지보다 먼저 오므로 반영 뒤 해제되고, 취소(Esc·취소
 *   버튼)는 생성 없이 정지하므로 원래 값이 그대로 남는다.
 * - edit: 편집 모드(`draw:editstart`~`draw:editstop`). 저장은 `draw:edited`
 *   뒤 정지, 취소는 되돌리기(revertLayers) 뒤 정지하므로 어느 쪽도 미반영
 *   값을 남기지 않는다.
 * - delete: 삭제 모드(`draw:deletestart`~`draw:deletestop`) — 저장·취소 모두
 *   같은 순서 보장이다.
 * - idle: 진행 중 아님 — 부모는 오늘과 완전히 같다(완화 없음).
 */
export function pointerPendingState(
  active: "draw" | "edit" | "delete" | "idle",
): AoiMapPendingState {
  switch (active) {
    case "draw":
      return {
        blocked: true,
        reason: "지도에서 경계를 그리는 중입니다. 완료·취소하기 전에는 등록할 수 없습니다.",
      };
    case "edit":
      return {
        blocked: true,
        reason: "지도에서 경계를 편집하는 중입니다. 완료·취소하기 전에는 등록할 수 없습니다.",
      };
    case "delete":
      return {
        blocked: true,
        reason: "지도에서 그린 경계를 삭제하는 중입니다. 완료·취소하기 전에는 등록할 수 없습니다.",
      };
    default:
      return { blocked: false, reason: null };
  }
}

/**
 * 지도 공유 콜백 — 미반영 키보드 입력이 부모의 등록·다음 동작을 막는 최소 계약.
 *
 * `blocked`이 true면 부모는 기존 유효 `value`가 있어도 제출·다음 단계로
 * 보내지 않고 `reason`을 그대로 보여준다(침묵 차단 금지). false면 오늘과
 * 완전히 같은 동작이다(완화 없음). transient UI 상태라 초안 저장소에
 * 넣지 않는다. `SiteRegistrationOnlyWizard`는 다른 소유 할당이라 직접
 * 연결하지 않았으며, 연결 요구는 outcome 반환의 위자드 통합 요구를 따른다.
 */
export interface AoiMapPendingState {
  blocked: boolean;
  reason: string | null;
}

/**
 * 입력 문자열의 십진 의미가 커밋된 숫자의 정식 표기와 같은 유리수인지 본다.
 * "+37.5"·"37.5000"·"1e-3"은 정식 표기("37.5"·"0.001")와 같아 clean이지만,
 * 반올림으로 뭉개진 "37.5000…01"은 다르다고 본다. 저장·전송 값을 바꾸지
 * 않으며, 다른 쪽이 맞다고 단정하지도 않는다 — 판단은 호출부 몫이다.
 */
function _sameDecimalMeaning(text: string, committed: number): boolean {
  const typed = _decimalExact(text);
  const canonical = _decimalExact(String(committed));
  if (typed === null || canonical === null) return false;
  const e = Math.min(typed.e, canonical.e);
  return typed.m * _pow10(typed.e - e) === canonical.m * _pow10(canonical.e - e);
}

/**
 * 미반영 판정의 순수 함수 — 입력 행이 반영된 값과 다르면 막는다.
 *
 * 비교는 문자열이 아니라 수치로 한다("+37.5"·"37.5000"·"1e-3"도 같은 값이면
 * clean이다). 그래야 반영 뒤 표기 차이만으로 영원히 막히지 않는다. 행이 비어
 * 값도 비었을 때만 clean이며, 행이 있으면 `validateKeyboardVertices`로 가려
 * 유효하면 "반영 전", 무효면 그 검증 사유(불확실 포함)로 막는다. 기존 유효
 * 범위는 그대로 보존되며(부모 `value`를 바꾸지 않는다), 명시적 반영·
 * 불러오기·지우기로만 해소된다.
 */
export function computeKeyboardPending(
  rows: readonly KeyboardVertexRow[],
  value: readonly AoiVertex[],
): AoiMapPendingState {
  let clean = rows.length === value.length;
  if (clean) {
    for (let i = 0; i < rows.length && clean; i++) {
      const lat = parseKeyboardCoordinate(rows[i]!.lat, "lat");
      const lon = parseKeyboardCoordinate(rows[i]!.lon, "lon");
      clean =
        lat.ok &&
        lon.ok &&
        lat.value === value[i]!.latDeg &&
        lon.value === value[i]!.lonDeg &&
        _sameDecimalMeaning(rows[i]!.lat, value[i]!.latDeg) &&
        _sameDecimalMeaning(rows[i]!.lon, value[i]!.lonDeg);
    }
  }
  if (clean) return { blocked: false, reason: null };
  const result = validateKeyboardVertices(rows);
  if (!result.ok) {
    return {
      blocked: true,
      reason: `${result.reason} 지도에 반영하거나 되돌리기 전에는 등록할 수 없습니다.`,
    };
  }
  return {
    blocked: true,
    reason: `입력한 좌표 ${rows.length}개를 아직 지도에 반영하지 않았습니다. “지도에 반영”을 누르거나 “현재 지도 값 불러오기”로 되돌리기 전에는 등록할 수 없습니다.`,
  };
}

/** Leaflet.draw가 기본으로 주는 영문 title/tooltip을 Console 언어에 맞춘다. */
function applyKoreanDrawLabels() {
  L.drawLocal.draw.toolbar.actions = { title: "도형 그리기 취소", text: "취소" };
  L.drawLocal.draw.toolbar.finish = { title: "경계 그리기 완료", text: "완료" };
  L.drawLocal.draw.toolbar.undo = { title: "마지막 점 삭제", text: "마지막 점 취소" };
  L.drawLocal.draw.toolbar.buttons.polygon = "경계 그리기";
  L.drawLocal.draw.handlers.polygon.tooltip = {
    start: "경계의 첫 점을 선택하세요.",
    cont: "다음 점을 선택하거나 첫 점을 눌러 완료하세요.",
    end: "첫 점을 눌러 경계를 완성하세요.",
  };
  L.drawLocal.edit.toolbar.actions.save = { title: "경계 편집 내용 반영", text: "편집 완료" };
  L.drawLocal.edit.toolbar.actions.cancel = { title: "경계 편집 취소", text: "취소" };
  L.drawLocal.edit.toolbar.actions.clearAll = { title: "그린 경계 전체 삭제", text: "전체 삭제" };
  L.drawLocal.edit.toolbar.buttons.edit = "경계 편집";
  L.drawLocal.edit.toolbar.buttons.editDisabled = "편집할 경계가 없습니다";
  L.drawLocal.edit.toolbar.buttons.remove = "그린 경계 삭제";
  L.drawLocal.edit.toolbar.buttons.removeDisabled = "삭제할 경계가 없습니다";
  L.drawLocal.edit.handlers.edit.tooltip = {
    text: "점을 끌어 경계를 수정하세요.",
    subtext: "취소하려면 취소를 누르세요.",
  };
  L.drawLocal.edit.handlers.remove.tooltip = { text: "그린 경계를 눌러 삭제하세요." };
}

function toVertices(layer: L.Polygon): AoiVertex[] {
  const latlngs = layer.getLatLngs()[0] as L.LatLng[];
  return latlngs.map((p) => ({ latDeg: p.lat, lonDeg: p.lng }));
}

function sameVertices(left: readonly AoiVertex[], right: readonly AoiVertex[]): boolean {
  return left.length === right.length && left.every((v, i) =>
    v.latDeg === right[i]!.latDeg && v.lonDeg === right[i]!.lonDeg,
  );
}

function replaceGroupPolygon(group: L.FeatureGroup, map: L.Map, vertices: readonly AoiVertex[]) {
  group.clearLayers();
  if (vertices.length >= 3) {
    const polygon = L.polygon(vertices.map((v) => [v.latDeg, v.lonDeg]));
    group.addLayer(polygon);
    map.fitBounds(polygon.getBounds(), { maxZoom: 26, padding: [24, 24] });
  }
}

/** 편집 컨트롤 없이 폴리곤만 그린다 — 현장 상세 화면처럼 "보여주기만" 하는 자리용. */
function ReadOnlyPolygon({ value }: { value: AoiVertex[] }) {
  const map = useMap();

  useEffect(() => {
    if (value.length < 3) return;
    const polygon = L.polygon(value.map((v) => [v.latDeg, v.lonDeg]));
    polygon.addTo(map);
    map.fitBounds(polygon.getBounds(), { maxZoom: 26, padding: [24, 24] });
    return () => {
      map.removeLayer(polygon);
    };
  }, [map, value]);

  return null;
}

export function DrawControl({
  value,
  onChange,
  onPointerPending,
  onRejectedChange,
}: {
  value: AoiVertex[];
  onChange: (vertices: AoiVertex[]) => void;
  /** 그리기·편집·삭제 진행 중을 부모에 알린다 — 미완성 값을 조용히 제출하지 않는 자리다. */
  onPointerPending?: (pending: AoiMapPendingState) => void;
  /**
   * 거부된 그리기(B)의 좌표 원본을 알린다 — 지도의 그리기 그룹은 복원되지만
   * 원본은 호출부가 보존해 명시적 버리기·다시 그리기·키보드 반영으로만 해소한다.
   */
  onRejectedChange?: (rejected: null | { vertices: AoiVertex[]; reason: string }) => void;
}) {
  const map = useMap();
  const groupRef = useRef<L.FeatureGroup>(new L.FeatureGroup());
  const pointerActiveRef = useRef(false);
  const externalChangeRef = useRef(false);
  const observedValueRef = useRef(value);
  // onChange 는 SiteRegistrationWizard 등에서 매 렌더 새로 만들어지는
  // 병합형 콜백(`(aoi) => update({aoi})`)일 수 있다 — 아래 effect 는 [map]
  // 에만 의존해 마운트 시 한 번만 리스너를 붙인다. ref 로 최신 콜백을 항상
  // 가리키게 하지 않으면 최초 마운트 시점의 onChange 스냅샷(그 시점의 다른
  // 폼 필드 값들을 닫고 있는)이 이후 모든 편집에 재생되어 다른 필드를
  // 덮어써 버린다. ref 갱신은 렌더 중이 아니라 커밋 후(effect, deps 없음)
  // 에 해야 한다 — 렌더 중 ref.current 대입은 react-hooks/refs 위반.
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  });
  // mount effect 안의 emit·복원은 최신 커밋값을 봐야 한다 — value 를 직접
  // 닫으면 마운트 시점 스냅샷이 재생된다(onChange 와 같은 이유).
  const valueRef = useRef(value);
  useEffect(() => {
    valueRef.current = value;
  });
  const onPointerPendingRef = useRef(onPointerPending);
  useEffect(() => {
    onPointerPendingRef.current = onPointerPending;
  });
  const onRejectedRef = useRef(onRejectedChange);
  useEffect(() => {
    onRejectedRef.current = onRejectedChange;
  });

  useEffect(() => {
    const group = groupRef.current;
    map.addLayer(group);
    applyKoreanDrawLabels();

    if (value.length >= 3) {
      const existing = L.polygon(value.map((v) => [v.latDeg, v.lonDeg]));
      group.addLayer(existing);
      map.fitBounds(existing.getBounds(), { maxZoom: 26, padding: [24, 24] });
    }

    const control = new L.Control.Draw({
      draw: {
        polygon: {
          allowIntersection: false,
          showArea: true,
          drawError: { message: "현장 범위는 선이 서로 교차하지 않도록 그려야 합니다." },
        },
        // AOI 는 폴리곤 하나만 필요 — 나머지 도형 도구는 노출하지 않는다(스코프 축소).
        polyline: false,
        rectangle: false,
        circle: false,
        circlemarker: false,
        marker: false,
      },
      edit: { featureGroup: group, remove: true },
    });
    map.addControl(control);

    /**
     * 공통 완료 경계 — 키보드 commit과 같은 `evaluateRingGeometry`로
     * 포인터 결과물을 가린다. 거부하면 보내지 않고 기존 반영값을 복원한 뒤
     * 사유를 명시한다(원본·미반영 보존, 조용한 제출 금지).
     */
    const rejectRing = (reason: string, layer: L.Polygon) => {
      // 거부된 B의 좌표는 레이어에서 직접 읽는다 — 호출부가 값을 고치지
      // 않아도 되며, 잘림·변환 없이 원본 그대로 보존된다.
      const rejected = toVertices(layer);
      const committed = valueRef.current;
      replaceGroupPolygon(group, map, committed);
      L.popup({ closeButton: true })
        .setLatLng(layer.getBounds().getCenter())
        .setContent(reason)
        .openOn(map);
      // 거부된 B는 지도에서 치웠지만 좌표 원본은 호출부에 보존한다 —
      // 조용히 버리면 아래 안내("바꾸지 않았다")가 거짓이 된다.
      onRejectedRef.current?.({ vertices: rejected, reason });
    };

    const emit = () => {
      const layers = group.getLayers() as L.Polygon[];
      const last = layers[layers.length - 1];
      if (externalChangeRef.current) {
        const reason = "편집 중 지도에 반영된 범위가 바뀌어 이 입력을 반영하지 않았습니다. 입력한 좌표는 별도로 보존했습니다.";
        if (last) rejectRing(reason, last);
        else {
          replaceGroupPolygon(group, map, valueRef.current);
          onRejectedRef.current?.({ vertices: [], reason: "삭제하는 동안 지도에 반영된 범위가 바뀌어 삭제하지 않았습니다. 삭제 시도는 확인 전까지 보존합니다." });
        }
        return;
      }
      if (!last) {
        onRejectedRef.current?.(null);
        onChangeRef.current([]);
        return;
      }
      const vertices = toVertices(last);
      if (vertices.length > _MAX_AOI_VERTICES) {
        // 상한 초과: 조용히 자르면 지도 화면(257점 이상)과 제출 원본(256점)이
        // 달라진다. 자르지도 보내지도 않고 기존 반영값을 복원한 뒤 초과를
        // 명시한다(계약 상한 자체는 바꾸지 않는다).
        rejectRing(vertexLimitMessage(vertices.length), last);
        return;
      }
      const verdict = evaluateRingGeometry(vertices, null);
      if (verdict.kind === "duplicate") {
        rejectRing(
          `꼭짓점 ${verdict.i + 1}과 ${verdict.j + 1}이 같은 점입니다 — 같은 점을 두 번 지나면 구역이 될 수 없습니다.`,
          last,
        );
        return;
      }
      if (verdict.kind === "intersect") {
        rejectRing(
          `선이 서로 교차합니다(변 ${verdict.i + 1}↔${verdict.j + 1}). 현장 범위는 선이 서로 교차하지 않도록 그려야 합니다.`,
          last,
        );
        return;
      }
      if (verdict.kind === "degenerate") {
        rejectRing("입력한 점이 정확히 한 직선 위에 있어 면적이 0입니다 — 구역이 아닙니다.", last);
        return;
      }
      if (verdict.kind === "range") {
        const label = verdict.axis === "lat" ? "위도" : "경도";
        const bound = verdict.axis === "lat" ? "-90~90" : "-180~180";
        rejectRing(
          `꼭짓점 ${verdict.index + 1} ${label} ${verdict.value}°은 범위(${bound})를 벗어났습니다. 지도 월드 이동으로 벗어난 값은 감싸지 않고 그대로 막습니다.`,
          last,
        );
        return;
      }
      if (verdict.kind === "uncertain") {
        rejectRing(
          `입력한 점들의 위치 관계를 확정할 수 없습니다 — 판단하지 못했습니다. ${verdict.detail} 입력한 값과 기존 반영값은 바꾸지 않았습니다.`,
          last,
        );
        return;
      }
      onRejectedRef.current?.(null);
      onChangeRef.current(vertices);
    };

    const onCreated = (e: L.LeafletEvent) => {
      group.clearLayers(); // AOI 폴리곤은 하나만 유지 — 새로 그리면 이전 것을 대체.
      group.addLayer((e as L.DrawEvents.Created).layer);
      emit();
    };
    const onEdited = () => emit();
    const onDeleted = () => emit();

    map.on(L.Draw.Event.CREATED, onCreated);
    map.on(L.Draw.Event.EDITED, onEdited);
    map.on(L.Draw.Event.DELETED, onDeleted);

    // 그리기·편집·삭제 진행 중에는 부모 제출을 막는다. 완료(CREATED·EDITED·
    // DELETED)는 각 정지보다 항상 먼저 오므로 반영 뒤 해제되고, 취소·삭제
    // 취소는 생성·되돌린 뒤 정지하므로 원래 값이 그대로 남는다. 어느 경우도
    // 미완성·미반영 값을 조용히 제출하지 않는다.
    const notifyPointer = (pending: AoiMapPendingState) => {
      onPointerPendingRef.current?.(pending);
    };
    const startPointer = (mode: "draw" | "edit" | "delete") => {
      pointerActiveRef.current = true;
      externalChangeRef.current = false;
      notifyPointer(pointerPendingState(mode));
    };
    const stopPointer = () => {
      pointerActiveRef.current = false;
      if (externalChangeRef.current) {
        // Leaflet 취소는 시작 당시 A를 되살릴 수 있다. 외부에서 C가 들어온
        // 경우에는 취소 처리 뒤 C 하나만 다시 그려 화면과 부모 값을 맞춘다.
        replaceGroupPolygon(group, map, valueRef.current);
        observedValueRef.current = valueRef.current;
        externalChangeRef.current = false;
      }
      notifyPointer(pointerPendingState("idle"));
    };
    const onDrawStart = () => startPointer("draw");
    const onDrawStop = stopPointer;
    const onEditStart = () => startPointer("edit");
    const onEditStop = stopPointer;
    const onDeleteStart = () => startPointer("delete");
    const onDeleteStop = stopPointer;
    map.on(L.Draw.Event.DRAWSTART, onDrawStart);
    map.on(L.Draw.Event.DRAWSTOP, onDrawStop);
    map.on(L.Draw.Event.EDITSTART, onEditStart);
    map.on(L.Draw.Event.EDITSTOP, onEditStop);
    map.on(L.Draw.Event.DELETESTART, onDeleteStart);
    map.on(L.Draw.Event.DELETESTOP, onDeleteStop);

    return () => {
      map.off(L.Draw.Event.CREATED, onCreated);
      map.off(L.Draw.Event.EDITED, onEdited);
      map.off(L.Draw.Event.DELETED, onDeleted);
      map.off(L.Draw.Event.DRAWSTART, onDrawStart);
      map.off(L.Draw.Event.DRAWSTOP, onDrawStop);
      map.off(L.Draw.Event.EDITSTART, onEditStart);
      map.off(L.Draw.Event.EDITSTOP, onEditStop);
      map.off(L.Draw.Event.DELETESTART, onDeleteStart);
      map.off(L.Draw.Event.DELETESTOP, onDeleteStop);
      map.removeControl(control);
      map.removeLayer(group);
      // StrictMode의 setup→cleanup→setup은 같은 그룹 ref를 재사용한다.
      // 내부 레이어도 비워야 기존 폴리곤이 두 번 올라가지 않는다.
      group.clearLayers();
      pointerActiveRef.current = false;
      externalChangeRef.current = false;
      // 청소 시점에도 막힘을 남기지 않는다 — 마운트 해제는 진행 중 상태의 끝이다.
      onPointerPendingRef.current?.(pointerPendingState("idle"));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 최초 마운트에만 컨트롤 부착, value 는 초기값으로만 사용, onChange 는 onChangeRef 로 최신값 참조
  }, [map]);

  // 키보드 입력·정정 불러오기로 value 가 바뀌면 지도 위 폴리곤을 같은 값으로
  // 맞춘다 — 바꾸기 전 화면과 제출값이 갈라지면 사용자는 엉뚱한 범위를 굳힌다.
  // 포인터로 그린 직후 부모가 같은 값을 돌려줄 때는 이미 일치하므로 손대지
  // 않아 진행 중인 그리기·편집을 끊지 않는다.
  useEffect(() => {
    const group = groupRef.current;
    if (!map.hasLayer(group)) return;
    if (pointerActiveRef.current) {
      // 같은 좌표의 새 배열만으로 편집 중 B를 A로 되돌리지 않는다. 실제로
      // 부모 좌표가 달라졌다면 완료 시 B를 덮어쓰지 않고 별도로 보존한다.
      if (!sameVertices(observedValueRef.current, value)) externalChangeRef.current = true;
      observedValueRef.current = value;
      return;
    }
    observedValueRef.current = value;
    const layers = group.getLayers() as L.Polygon[];
    const last = layers[layers.length - 1];
    const current = last ? toVertices(last) : [];
    if (sameVertices(current, value)) return;
    replaceGroupPolygon(group, map, value);
  }, [map, value]);

  return null;
}

/**
 * 지도 그리기의 키보드 대안 — 같은 값을 내는 네이티브 입력기다.
 *
 * 포인터 그리기(Leaflet.draw 툴바 `<a>`·지도 클릭)는 키보드로 점을 찍을 수
 * 없어 첫 등록을 키보드로 마칠 수 없었다. 이 입력기는 같은 `value`·`onChange`
 * (`AoiVertex[]`, WGS84)를 쓰므로 지도 화면과 제출 geometry가 갈라지지 않는다:
 * 반영된 값은 아래에 숫자로 그대로 보이고, 지도 폴리곤도 같은 값으로 다시
 * 그려진다. 숫자·범위를 추측하지 않으며(빈칸은 빈칸으로 막는다), 형식·점 수·
 * 범위·확실한 교차·정확한 퇴화는 공통 경계와 같은 바닥으로 막고, 머리털 끝
 * 차이의 불확실함은 판단 보류로 막는다. 서버 최종 판정을 대신 주장하지
 * 않는다. 행이 반영된 값과 다르면 `onPendingChange`로 부모를 막는다 — 기존
 * 유효 범위가 그대로 제출되는 일을 막는 자리다. 읽기 전용에서는 렌더하지
 * 않는다(호출부 조건).
 */
export function AoiKeyboardEditor({
  value,
  onChange,
  onPendingChange,
  initialRows,
  onRowsChange,
  disabled = false,
}: {
  value: AoiVertex[];
  onChange: (vertices: AoiVertex[]) => void;
  /** 미반영 입력이 있으면 부모 제출을 막는 알림 — 없으면 부모는 오늘과 같다. */
  onPendingChange?: (pending: AoiMapPendingState) => void;
  /**
   * 포인터 그리기·편집·삭제 진행 중 true — 입력 방식을 하나로 묶어 화면과
   * 제출이 엇갈리지 않게 한다. `<fieldset disabled>`이라 키보드 포커스도
   * 들어가지 않으며, 사유를 문장으로 둔다(조용한 잠금 금지).
   */
  disabled?: boolean;
  initialRows?: KeyboardVertexRow[];
  onRowsChange?: (rows: KeyboardVertexRow[]) => void;
}) {
  const [rows, setRows] = useState<KeyboardVertexRow[]>(() => initialRows ?? toKeyboardRows(value));
  const rowsRef = useRef(rows);
  const addButtonRef = useRef<HTMLButtonElement>(null);
  const pendingFocusRef = useRef<number | null>(null);
  // 마지막 행에서 버튼이 비활성화되기 전에 포커스를 안전하게 옮긴다.
  const [keyboardAddPending, setKeyboardAddPending] = useState(false);
  const latitudeRefs = useRef(new Map<number, HTMLInputElement>());
  useLayoutEffect(() => {
    const index = pendingFocusRef.current;
    pendingFocusRef.current = null;
    if (index !== null && !disabled && document.activeElement === addButtonRef.current) {
      latitudeRefs.current.get(index)?.focus();
    }
    // The last add needs two synchronous commits: focus while the trigger still
    // owns focus, then disable it before paint. Deferring would expose an enabled
    // maxed-out control; guessing from body focus could steal owner focus.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- finalize the focus/disable DOM transaction
    if (keyboardAddPending) setKeyboardAddPending(false);
  }, [rows, disabled, keyboardAddPending]);
  const onRowsChangeRef = useRef(onRowsChange);
  useEffect(() => { onRowsChangeRef.current = onRowsChange; });
  function updateRows(next: KeyboardVertexRow[]) {
    rowsRef.current = next;
    onRowsChangeRef.current?.(next);
    setRows(next);
  }
  const [rowErrors, setRowErrors] = useState<Record<number, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  /**
   * 판단 보류 알림 — 교차라고도 등록 가능하다고도 말하지 않는다. 입력한 값과
   * 기존 반영값을 바꾸지 않고 제출하지 않은 채 둔다.
   */
  const [uncertainError, setUncertainError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [externalNote, setExternalNote] = useState<string | null>(null);
  const lastValueRef = useRef<AoiVertex[]>(value);
  const descId = useId();
  const errorId = useId();
  const statusId = useId();

  // 포인터 그리기·정정 불러오기로 value 가 바뀌면: 입력 중이 아니면 따라가고,
  // 입력 중이면 덮어쓰지 않고 불러오기를 안내한다(진행 중 입력을 파기 금지).
  useEffect(() => {
    const previous = lastValueRef.current;
    if (
      previous.length === value.length &&
      previous.every((p, i) => p.latDeg === value[i]!.latDeg && p.lonDeg === value[i]!.lonDeg)
    ) {
      return;
    }
    lastValueRef.current = value;
    const current = rowsRef.current;
    const untouched = toKeyboardRows(previous);
    const dirty =
      current.length !== untouched.length ||
      current.some((row, i) => row.lat !== untouched[i]!.lat || row.lon !== untouched[i]!.lon);
    if (!dirty) {
      setExternalNote(null);
      updateRows(toKeyboardRows(value));
    } else {
      setExternalNote(
        "지도에서 그린 모양이 바뀌었습니다. 입력 중인 내용은 그대로 두었습니다 — 지도 값을 쓰려면 아래 “현재 지도 값 불러오기”를 누르세요.",
      );
    }
  }, [value]);

  function commit() {
    const result = validateKeyboardVertices(rows);
    if (!result.ok) {
      if ("uncertain" in result && result.uncertain) {
        setRowErrors({});
        setFormError(null);
        setUncertainError(result.reason);
      } else {
        const nextRowErrors: Record<number, string> = {};
        if (result.rowIndex !== undefined) nextRowErrors[result.rowIndex] = result.reason;
        setRowErrors(nextRowErrors);
        setFormError(result.reason);
        setUncertainError(null);
      }
      setStatus(null);
      return;
    }
    if (rows.some((row, i) =>
      !_sameDecimalMeaning(row.lat, result.vertices[i]!.latDeg) ||
      !_sameDecimalMeaning(row.lon, result.vertices[i]!.lonDeg),
    )) {
      // Number()로 바뀐 값이 입력한 십진 원문과 다르면 폴리곤 전체가 다른
      // 모양일 수 있다. 기존 A를 변환된 B로 바꾸지 않고 원문을 남긴다.
      setRowErrors({});
      setFormError(null);
      setUncertainError("입력한 좌표와 제출 좌표의 숫자가 달라 그대로 반영할 수 없습니다. 입력한 값을 확인하거나 현재 지도 값을 불러오세요. 기존 범위와 입력은 그대로 유지됩니다.");
      setStatus(null);
      return;
    }
    setRowErrors({});
    setFormError(null);
    setUncertainError(null);
    setExternalNote(null);
    // 자기 커밋은 외부 변경이 아니다 — ref를 먼저 맞춰 둬야 반영 effect가
    // "지도에서 바뀜"으로 오판하지 않는다(입력 중이던 내용이 그대로인데도
    // 불러오기를 안내하면 거짓말이다).
    lastValueRef.current = result.vertices;
    onChange(result.vertices);
    setStatus(
      `${result.vertices.length}개 꼭짓점을 지도에 반영했습니다. 아래 반영된 좌표와 지도 모양이 같은지 확인하세요.`,
    );
  }

  function reloadFromMap() {
    updateRows(toKeyboardRows(value));
    setRowErrors({});
    setFormError(null);
    setUncertainError(null);
    setExternalNote(null);
    setStatus(
      value.length >= 3
        ? `현재 지도 값 ${value.length}개를 불러왔습니다.`
        : "현재 지도에 반영된 값이 없어 빈 입력으로 두었습니다.",
    );
  }

  function clearAll() {
    updateRows([]);
    setRowErrors({});
    setFormError(null);
    setUncertainError(null);
    setExternalNote(null);
    // commit()과 같은 이유 — 자기 지우기를 외부 변경으로 오판하지 않는다.
    lastValueRef.current = [];
    onChange([]);
    setStatus("입력을 모두 지웠습니다 — 지도에도 폴리곤이 없습니다.");
  }

  // 미반영 입력의 부모 차단 알림 — 행이 반영된 값과 다르면 기존 유효 범위가
  // 있어도 제출·다음 동작을 막는다. clean이면 오늘과 완전히 같다.
  useEffect(() => {
    if (!onPendingChange) return;
    onPendingChange(computeKeyboardPending(rows, value));
  }, [rows, value, onPendingChange]);

  return (
    <fieldset
      disabled={disabled}
      className="flex flex-col gap-2 rounded-lg border border-line bg-sunk p-3"
    >
      <legend className="px-1 text-[12.5px] font-semibold break-keep text-ink-1">
        키보드로 경계 입력(지도 그리기 대안)
      </legend>
      {disabled && (
        <p className="rounded-md border border-line bg-surface px-2 py-1 text-[12px] break-keep text-ink-2">
          지도에서 그리거나 편집하는 중에는 키보드 입력을 바꿀 수 없습니다. 지도 작업을
          완료·취소한 뒤 이어가세요.
        </p>
      )}
      <p id={descId} className="text-[12px] break-keep text-ink-2">
        지도와 같은 위경도({KEYBOARD_CRS_LABEL}) 값을 숫자로 입력합니다. 반영한 값이
        그대로 제출 범위가 되며, 지도 폴리곤도 같은 값으로 다시 그려집니다. 숫자를
        미리 채우지 않으며, 통과했다고 등록이 확정된 것은 아닙니다(최종 판정은 서버).
      </p>
      <p id={statusId} aria-live="polite" className="text-[12px] break-keep text-ink-2">
        {value.length >= 3
          ? `지금 지도에 반영된 값: 꼭짓점 ${value.length}개.`
          : "아직 반영된 꼭짓점이 없습니다 — 3개 이상 입력해 반영하세요."}
      </p>
      {value.length >= 3 && (
        <details className="text-[12px] text-ink-2">
          <summary className="tap-target cursor-pointer">반영된 좌표 {value.length}개 보기</summary>
          <ol className="mt-1 flex flex-col gap-1">
            {value.map((vertex, index) => (
              <li key={index} className="num break-token">
                꼭짓점 {index + 1}: 위도 {String(vertex.latDeg)}, 경도 {String(vertex.lonDeg)}
              </li>
            ))}
          </ol>
        </details>
      )}
      {externalNote !== null && (
        <p className="rounded-md border border-line bg-surface px-2 py-1 text-[12px] break-keep text-ink-2">
          {externalNote}
        </p>
      )}
      <ol className="flex flex-col gap-2">
        {rows.map((row, index) => {
          const latId = `${descId}-lat-${index}`;
          const lonId = `${descId}-lon-${index}`;
          const errId = `${errorId}-row-${index}`;
          const describedBy = rowErrors[index] ? `${descId} ${errId}` : descId;
          return (
            <li
              key={index}
              className="grid grid-cols-1 gap-2 rounded-md border border-line bg-surface p-2 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
            >
              <label className="flex flex-col gap-1 text-[12px] break-keep text-ink-2">
                <span>
                  꼭짓점 {index + 1} 위도(°) <span className="text-ink-muted">-90 ~ 90</span>
                </span>
                <input
                  id={latId}
                  ref={(node) => {
                    if (node) latitudeRefs.current.set(index, node);
                    else latitudeRefs.current.delete(index);
                  }}
                  type="text"
                  inputMode="decimal"
                  autoComplete="off"
                  placeholder="-90 ~ 90"
                  value={row.lat}
                  aria-describedby={describedBy}
                  aria-invalid={rowErrors[index] ? true : undefined}
                  onChange={(event) => {
                    const next = rows.slice();
                    next[index] = { lat: event.target.value, lon: row.lon };
                    updateRows(next);
                    setUncertainError(null);
                  }}
                  className="input"
                />
              </label>
              <label className="flex flex-col gap-1 text-[12px] break-keep text-ink-2">
                <span>
                  꼭짓점 {index + 1} 경도(°) <span className="text-ink-muted">-180 ~ 180</span>
                </span>
                <input
                  id={lonId}
                  type="text"
                  inputMode="decimal"
                  autoComplete="off"
                  placeholder="-180 ~ 180"
                  value={row.lon}
                  aria-describedby={describedBy}
                  aria-invalid={rowErrors[index] ? true : undefined}
                  onChange={(event) => {
                    const next = rows.slice();
                    next[index] = { lat: row.lat, lon: event.target.value };
                    updateRows(next);
                    setUncertainError(null);
                  }}
                  className="input"
                />
              </label>
              <button
                type="button"
                className="btn w-fit"
                aria-label={`꼭짓점 ${index + 1} 삭제`}
                onClick={() => {
                  updateRows(rows.filter((_, i) => i !== index));
                  setRowErrors({});
                  setFormError(null);
                  setUncertainError(null);
                }}
              >
                삭제
              </button>
              {rowErrors[index] && (
                <p id={errId} role="alert" className="text-[12px] font-semibold break-keep text-crit-ink sm:col-span-3">
                  {rowErrors[index]}
                </p>
              )}
            </li>
          );
        })}
      </ol>
      {rows.length === 0 && (
        <p className="text-[12px] break-keep text-ink-2">
          입력 행이 없습니다. 아래에서 꼭짓점을 추가하세요.
        </p>
      )}
      {formError !== null && (
        <p id={errorId} role="alert" className="rounded-md bg-crit-bg px-2 py-1 text-[12px] font-semibold break-keep text-crit-ink">
          {formError}
        </p>
      )}
      {uncertainError !== null && (
        <p
          data-testid="keyboard-uncertain"
          role="alert"
          className="rounded-md bg-crit-bg px-2 py-1 text-[12px] font-semibold break-keep text-crit-ink"
        >
          {uncertainError}
        </p>
      )}
      {status !== null && (
        <p className="rounded-md border border-line bg-surface px-2 py-1 text-[12px] break-keep text-ink-2">
          {status}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="btn w-fit"
          ref={addButtonRef}
          disabled={rows.length >= _MAX_AOI_VERTICES && !keyboardAddPending}
          onClick={(event) => {
            const current = rowsRef.current;
            if (disabled || current.length >= _MAX_AOI_VERTICES) return;
            pendingFocusRef.current = event.detail === 0 && document.activeElement === event.currentTarget
              ? current.length : null;
            setKeyboardAddPending(pendingFocusRef.current !== null);
            updateRows([...current, { lat: "", lon: "" }]);
            setUncertainError(null);
          }}
        >
          꼭짓점 추가
        </button>
        <button type="button" className="btn btn-primary w-fit" onClick={commit}>
          지도에 반영
        </button>
        <button type="button" className="btn w-fit" onClick={reloadFromMap}>
          현재 지도 값 불러오기
        </button>
        <button type="button" className="btn w-fit" onClick={clearAll}>
          모두 지우기
        </button>
      </div>
      <p className="text-[11.5px] break-keep text-ink-muted">
        형식·점 수·범위·확실한 교차·정확한 퇴화(면적 0)는 여기서도 막지만, 그 밖의
        판정(극지·범위·볼록 등)은 서버와 각 화면(현장 등록·작업구역)이 그대로 맡습니다.
        통과가 서버 판정을 대신하지 않습니다. 입력이 반영된 값과 다르면 등록이
        막힙니다. 경도가 ±180을 넘으면 감싸지 않고 범위로 막으며, 극지·날짜변경선
        부근의 정확도는 주장하지 않습니다 — 지도 타일은 배경일 뿐, 판정은 유한한
        좌표 숫자의 평면모델 기준입니다.
      </p>
    </fieldset>
  );
}

export function AoiPolygonMapInner({
  value,
  onChange,
  onPendingChange,
  initialSnapshot,
  onSnapshotChange,
  center = [37.5665, 126.978], // 서울 — 현장 등록 전 기본 시야일 뿐 데이터 아님.
  readOnly = false,
}: {
  value: AoiVertex[];
  /** readOnly 가 아니면 필수 — 서버 컴포넌트(현장 상세)에서 readOnly 로 쓸 땐 함수를 넘기지 않는다. */
  onChange?: (vertices: AoiVertex[]) => void;
  /** 미반영 키보드 입력이 있으면 부모 제출을 막는 알림 — 선택, 없으면 오늘과 같다. */
  onPendingChange?: (pending: AoiMapPendingState) => void;
  initialSnapshot?: AoiRawSnapshot;
  onSnapshotChange?: (snapshot: AoiRawSnapshot) => void;
  center?: [number, number];
  /** true 면 편집 컨트롤 없이 폴리곤만 표시한다(현장 상세처럼 보여주기 전용 자리). */
  readOnly?: boolean;
}) {
  const editable = !readOnly && typeof onChange === "function";
  // 포인터 진행 중(그리기·편집·삭제)과 키보드 미반영을 하나로 합친다.
  // 포인터가 막히면 키보드 입력을 비활성화해 입력 방식이 엇갈리지 않게 하고,
  // 부모에는 포인터 막힘을 우선해 알린다. 둘 다 clean이면 오늘과 같다.
  const [pointerPending, setPointerPending] = useState<AoiMapPendingState>({
    blocked: false,
    reason: null,
  });
  const [keyboardPending, setKeyboardPending] = useState<AoiMapPendingState>(() =>
    initialSnapshot ? computeKeyboardPending(initialSnapshot.rows, value) : { blocked: false, reason: null },
  );
  /**
   * 거부된 그리기(B)의 좌표 원본 — 지도의 그리기 그룹은 커밋값으로 복원되지만
   * 원본은 여기서 보존해 명시적 버리기로만 사라진다. 유효한 다시 그리기·
   * 편집 저장·삭제·키보드 반영이 들어오면 해소된 것으로 본다.
   */
  const [rejectedDraws, setRejectedDraws] = useState<Array<{
    vertices: AoiVertex[];
    reason: string;
  }>>(() => initialSnapshot?.rejectedDraws ?? []);
  const [snapshotRows, setSnapshotRows] = useState<KeyboardVertexRow[]>(
    () => initialSnapshot?.rows ?? toKeyboardRows(value),
  );
  const snapshotRef = useRef<AoiRawSnapshot>({ rows: snapshotRows, rejectedDraws });
  const onSnapshotChangeRef = useRef(onSnapshotChange);
  useEffect(() => { onSnapshotChangeRef.current = onSnapshotChange; });
  function publishRows(rows: KeyboardVertexRow[]) {
    snapshotRef.current = { ...snapshotRef.current, rows };
    onSnapshotChangeRef.current?.(snapshotRef.current);
    const pending = computeKeyboardPending(rows, value);
    onPendingChange?.(pointerPending.blocked ? pointerPending : rejectedDraws.length ? { blocked: true, reason: rejectedDraws[rejectedDraws.length - 1]!.reason } : pending);
    setSnapshotRows(rows);
  }
  function publishRejected(rejectedDraws: AoiRawSnapshot["rejectedDraws"]) {
    snapshotRef.current = { ...snapshotRef.current, rejectedDraws };
    onSnapshotChangeRef.current?.(snapshotRef.current);
    const pending = computeKeyboardPending(snapshotRef.current.rows, value);
    onPendingChange?.(pointerPending.blocked ? pointerPending : rejectedDraws.length ? { blocked: true, reason: rejectedDraws[rejectedDraws.length - 1]!.reason } : pending);
    setRejectedDraws(rejectedDraws);
  }
  const onPendingChangeRef = useRef(onPendingChange);
  useEffect(() => {
    onPendingChangeRef.current = onPendingChange;
  });
  const mergedBlocked =
    pointerPending.blocked || rejectedDraws.length > 0 || keyboardPending.blocked;
  const mergedReason = pointerPending.blocked
    ? pointerPending.reason
    : rejectedDraws.length > 0
      ? rejectedDraws[rejectedDraws.length - 1]!.reason
      : keyboardPending.reason;
  useEffect(() => {
    onPendingChangeRef.current?.({ blocked: mergedBlocked, reason: mergedReason });
  }, [mergedBlocked, mergedReason]);
  // 키보드 반영은 명시적 해소 수단이다 — 거부된 B가 있어도 유효한 반영을 막지
  // 않고, 반영이 되면 B는 해소된 것으로 본다(편집기는 editable일 때만 mount된다).
  const handleEditorCommit = (vertices: AoiVertex[]) => {
    publishRejected([]);
    (onChange as (vertices: AoiVertex[]) => void)(vertices);
  };
  const handleRejectedChange = (rejected: null | { vertices: AoiVertex[]; reason: string }) => {
    // 다음 그리기도 거부되면 앞의 원본을 덮지 않는다. 유효한 반영 또는
    // 명시적인 버리기로만 이 화면의 거부 기록을 해소한다.
    publishRejected(rejected === null ? [] : [...snapshotRef.current.rejectedDraws, rejected]);
  };
  return (
    <div className="flex flex-col gap-2">
      <div className="h-80 w-full overflow-hidden rounded-lg border border-line sm:h-96">
        <MapContainer
          center={center}
          zoom={16}
          maxZoom={26}
          style={{ height: "100%", width: "100%" }}
          className="rounded-lg"
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            // Zoom the vector, not the source's resolution. Reuse the last available
            // background tile; never request non-existent high-zoom OSM tiles.
            maxNativeZoom={19}
            maxZoom={26}
          />
          {readOnly ? (
            <ReadOnlyPolygon value={value} />
          ) : (
            <DrawControl
              value={value}
              onChange={onChange as (vertices: AoiVertex[]) => void}
              onPointerPending={setPointerPending}
              onRejectedChange={handleRejectedChange}
            />
          )}
        </MapContainer>
      </div>
      {editable && rejectedDraws.length > 0 && (
        <div
          role="status"
          data-testid="map-rejected-draw"
          className="flex flex-col gap-2 rounded-lg border border-line-strong bg-sunk p-3"
        >
          <p className="text-[12.5px] font-bold break-keep text-ink-1">
            지도에 반영하지 않은 그리기가 {rejectedDraws.length}건 있습니다
          </p>
          {rejectedDraws.map((rejected, recordIndex) => (
            <div key={recordIndex} className="flex flex-col gap-1">
              <p className="text-[12px] break-keep text-ink-2">{rejected.reason}</p>
              <details className="text-[12px] text-ink-2">
                <summary className="tap-target cursor-pointer">
                  그리기 {recordIndex + 1} 원본 좌표 {rejected.vertices.length}개 보기
                </summary>
                <ol className="mt-1 flex flex-col gap-1">
                  {rejected.vertices.map((vertex, index) => (
                    <li key={index} className="num break-token">
                      꼭짓점 {index + 1}: 위도 {String(vertex.latDeg)}, 경도 {String(vertex.lonDeg)}
                    </li>
                  ))}
                </ol>
              </details>
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn w-fit"
              data-testid="map-reject-discard"
              onClick={() => publishRejected([])}
            >
              {rejectedDraws.length > 1 ? "미반영 그리기 모두 버리기" : "버리기"}
            </button>
          </div>
          <p className="text-[11.5px] break-keep text-ink-muted">
            버리기 전에는 등록할 수 없습니다. 유효한 다시 그리기·편집 저장·
            키보드 반영이 들어오면 이 기록은 모두 해소됩니다.
          </p>
        </div>
      )}
      {editable && (
        <AoiKeyboardEditor
          value={value}
          onChange={handleEditorCommit}
          onPendingChange={setKeyboardPending}
          initialRows={snapshotRows}
          onRowsChange={publishRows}
          disabled={pointerPending.blocked}
        />
      )}
    </div>
  );
}
