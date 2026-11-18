import { describe, expect, it } from "vitest";

import {
  MAX_LINE_VERTICES,
  approxLengthM,
  createLineBody,
  insertVertex,
  lineIssues,
  lineNameIssue,
  moveVertex,
  outsideAreaCount,
  pointInRing,
  removeVertex,
  reviseLineBody,
  roundCoordinate,
  rowsToVertices,
  savedLineToEditorVertices,
  verticesToRows,
  type LineVertex,
} from "@/lib/measurement-line";

const A: LineVertex = [127.0, 37.0];
const B: LineVertex = [127.001, 37.0];
const C: LineVertex = [127.001, 37.001];

describe("lineIssues", () => {
  it("서로 다른 두 점 이상이면 저장할 수 있다", () => {
    expect(lineIssues([A, B])).toEqual([]);
    expect(lineIssues([A, B, C])).toEqual([]);
  });
  it("점이 모자라면 이유를 말한다", () => {
    expect(lineIssues([])).toEqual(["지도에서 두 점 이상을 눌러 선을 그리세요."]);
    expect(lineIssues([A])).toEqual(["지도에서 두 점 이상을 눌러 선을 그리세요."]);
  });
  it("같은 점뿐이면 선이 아니다", () => {
    expect(lineIssues([A, [...A] as LineVertex])).toEqual(["서로 다른 두 점이 있어야 선이 됩니다."]);
  });
  it("점이 많으면 막는다(상한 포함은 허용)", () => {
    const many = (count: number) => Array.from({ length: count }, (_, i) => [127 + i * 1e-5, 37] as LineVertex);
    expect(lineIssues(many(MAX_LINE_VERTICES))).toEqual([]);
    expect(lineIssues(many(MAX_LINE_VERTICES + 1))[0]).toContain("256개까지");
  });
  it("범위 밖·유한하지 않은 좌표를 막는다", () => {
    expect(lineIssues([A, [181, 37]])[0]).toContain("범위를 벗어난");
    expect(lineIssues([A, [127, 91]])[0]).toContain("범위를 벗어난");
    expect(lineIssues([A, [Number.NaN, 37]])[0]).toContain("범위를 벗어난");
    expect(lineIssues([A, [Number.POSITIVE_INFINITY, 37]])[0]).toContain("범위를 벗어난");
  });
});

describe("approxLengthM", () => {
  it("위도 1도는 약 111.2 km다", () => {
    expect(approxLengthM([[127, 37], [127, 38]])).toBeGreaterThan(111_000);
    expect(approxLengthM([[127, 37], [127, 38]])).toBeLessThan(111_400);
  });
  it("구간 길이를 더한다", () => {
    const ab = approxLengthM([A, B]);
    const bc = approxLengthM([B, C]);
    expect(approxLengthM([A, B, C])).toBeCloseTo(ab + bc, 6);
    expect(approxLengthM([A])).toBe(0);
  });
});

describe("pointInRing / outsideAreaCount", () => {
  const ring: LineVertex[] = [[127, 37], [127.01, 37], [127.01, 37.01], [127, 37.01], [127, 37]];
  it("안과 밖을 가르고 경계 위는 안으로 본다", () => {
    expect(pointInRing([127.005, 37.005], ring)).toBe(true);
    expect(pointInRing([127.02, 37.005], ring)).toBe(false);
    expect(pointInRing([127.005, 37], ring)).toBe(true);
    expect(pointInRing([127, 37], ring)).toBe(true);
    // 오른쪽·위쪽 변 위의 점도 안이다(광선 판정만으로는 빠지는 자리)
    expect(pointInRing([127.01, 37.005], ring)).toBe(true);
    expect(pointInRing([127.005, 37.01], ring)).toBe(true);
    expect(pointInRing([127.01, 37.01], ring)).toBe(true);
  });
  it("구역 밖 점의 수를 센다", () => {
    expect(outsideAreaCount([[127.005, 37.005], [127.02, 37.005], [126.9, 37]], ring)).toBe(2);
  });
  it("구역 모양을 모르면 모른다고 답한다", () => {
    expect(outsideAreaCount([A, B], null)).toBeNull();
    expect(outsideAreaCount([A, B], [A, B])).toBeNull();
  });
});

describe("점 편집", () => {
  it("끼워 넣고 옮기고 지운다(원본은 바꾸지 않는다)", () => {
    const original: LineVertex[] = [A, B];
    const inserted = insertVertex(original, 1, [127.0005, 37.0004]);
    expect(inserted).toEqual([A, [127.0005, 37.0004], B]);
    expect(original).toEqual([A, B]);
    expect(moveVertex(inserted, 1, C)[1]).toEqual(C);
    expect(removeVertex(inserted, 1)).toEqual([A, B]);
  });
  it("범위 밖 위치는 안전하게 다룬다", () => {
    expect(insertVertex([A], 99, B)).toEqual([A, B]);
    expect(insertVertex([A], -5, B)).toEqual([B, A]);
    expect(moveVertex([A], 3, B)).toEqual([A]);
    expect(removeVertex([A], -1)).toEqual([A]);
  });
  it("누른 좌표를 같은 선이 같은 값이 되게 정리한다", () => {
    expect(roundCoordinate(127.123456789)).toBe(127.1234568);
    expect(insertVertex([], 0, [127.123456789, 37.987654321])).toEqual([[127.1234568, 37.9876543]]);
  });
});

describe("rowsToVertices", () => {
  it("위도·경도 줄을 [경도, 위도]로 읽는다", () => {
    expect(rowsToVertices([{ lat: "37.5", lon: "127.25" }, { lat: "37.51", lon: "127.26" }])).toEqual({ ok: true, vertices: [[127.25, 37.5], [127.26, 37.51]] });
  });
  it("줄마다 되돌려 쓸 수 있다", () => {
    expect(verticesToRows([[127.25, 37.5]])).toEqual([{ lat: "37.5", lon: "127.25" }]);
  });
  it.each([
    ["빈칸", { lat: "", lon: "127" }, "1번째 줄: 위도를 입력하세요."],
    ["16진수", { lat: "0x10", lon: "127" }, "십진수가 아닙니다"],
    ["문자", { lat: "abc", lon: "127" }, "십진수가 아닙니다"],
    ["위도 범위", { lat: "91", lon: "127" }, "-90~90"],
    ["경도 범위", { lat: "37", lon: "181" }, "-180~180"],
    ["지수 표기", { lat: "1e1", lon: "127" }, "십진수가 아닙니다"],
  ])("틀린 줄을 거부한다: %s", (_name, row, text) => {
    const result = rowsToVertices([row]);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toContain(text);
      expect(result.rowIndex).toBe(0);
    }
  });
  it("몇 번째 줄이 틀렸는지 알린다", () => {
    const result = rowsToVertices([{ lat: "37", lon: "127" }, { lat: "37", lon: "x" }]);
    expect(result).toMatchObject({ ok: false, rowIndex: 1 });
    expect(!result.ok && result.reason).toContain("2번째 줄");
  });
});

describe("이름과 본문", () => {
  it("이름은 앞뒤 공백을 지우고 1~255자다", () => {
    expect(lineNameIssue("  ")).not.toBeNull();
    expect(lineNameIssue("북쪽 경사면")).toBeNull();
    expect(lineNameIssue("가".repeat(255))).toBeNull();
    expect(lineNameIssue("가".repeat(256))).not.toBeNull();
  });
  it("저장 본문은 경위도 선이다(구역은 본문에 한 번만)", () => {
    expect(createLineBody("area-1", " 북쪽 ", [A, B])).toEqual({ workAreaId: "area-1", name: "북쪽", line: { crs: "EPSG:4326", vertices: [A, B] } });
    expect(reviseLineBody(2, "수정", [A, B])).toEqual({ expectedRevision: 2, name: "수정", line: { crs: "EPSG:4326", vertices: [A, B] } });
  });
});

describe("savedLineToEditorVertices", () => {
  const identity = (_crs: string, vertex: readonly [number, number]): [number, number] => [vertex[0] / 1000, vertex[1] / 1000];
  it("경위도 선은 그대로 올린다", () => {
    expect(savedLineToEditorVertices({ crs: "EPSG:4326", vertices: [[127, 37], [127.001, 37.001]] }, identity)).toEqual({ ok: true, vertices: [[127, 37], [127.001, 37.001]], converted: false });
  });
  it("한국 투영좌표계 선은 변환해 올린다", () => {
    expect(savedLineToEditorVertices({ crs: "EPSG:5186", vertices: [[127000, 37000], [127001, 37001]] }, identity)).toEqual({ ok: true, vertices: [[127, 37], [127.001, 37.001]], converted: true });
  });
  it("한국 UTM(52N) 선도 변환해 올린다", () => {
    expect(savedLineToEditorVertices({ crs: "EPSG:32652", vertices: [[127000, 37000], [127001, 37001]] }, identity)).toEqual({ ok: true, vertices: [[127, 37], [127.001, 37.001]], converted: true });
  });
  it("모르는 좌표계는 고칠 수 없다고 답한다", () => {
    // 5174는 Bessel 구 좌표계, 32617은 한국 밖 UTM 존이다.
    for (const crs of ["EPSG:5174", "EPSG:32617"]) {
      expect(savedLineToEditorVertices({ crs, vertices: [[1, 1], [2, 2]] }, identity).ok).toBe(false);
    }
  });
  it("변환 결과가 범위 밖이면 거부한다", () => {
    expect(savedLineToEditorVertices({ crs: "EPSG:5186", vertices: [[999999999, 1], [2, 2]] }, identity).ok).toBe(false);
  });
});

import { parseCreateLineBody, parseReviseLineBody } from "@/lib/measurement-line";

describe("저장 본문 형식 검사(BFF)", () => {
  const line = { crs: "EPSG:4326", vertices: [[127, 37], [127.001, 37]] };
  const create = (overrides: Record<string, unknown> = {}) => ({ workAreaId: "area-1", name: " 북쪽 ", line, ...overrides });
  const revise = (overrides: Record<string, unknown> = {}) => ({ expectedRevision: 2, name: "수정", line, ...overrides });

  it("올바른 본문은 이름 공백만 정리해 받는다", () => {
    expect(parseCreateLineBody(create())).toEqual({ workAreaId: "area-1", name: "북쪽", line });
    expect(parseReviseLineBody(revise())).toEqual({ expectedRevision: 2, name: "수정", line });
  });

  it.each([
    ["객체가 아니다", null],
    ["모르는 필드", create({ siteId: "x" })],
    ["구역이 없다", create({ workAreaId: undefined })],
    ["이름이 비었다", create({ name: "  " })],
    ["이름이 너무 길다", create({ name: "가".repeat(256) })],
    ["다른 좌표계", create({ line: { ...line, crs: "EPSG:5186" } })],
    ["점이 하나", create({ line: { ...line, vertices: [[127, 37]] } })],
    ["같은 점뿐", create({ line: { ...line, vertices: [[127, 37], [127, 37]] } })],
    ["범위 밖 좌표", create({ line: { ...line, vertices: [[127, 37], [200, 37]] } })],
    ["문자열 좌표", create({ line: { ...line, vertices: [["127", "37"], [127, 37.1]] } })],
    ["세 값짜리 점", create({ line: { ...line, vertices: [[127, 37, 5], [127, 37.1]] } })],
    ["선에 모르는 필드", create({ line: { ...line, extra: 1 } })],
    ["점이 너무 많다", create({ line: { ...line, vertices: Array.from({ length: 257 }, (_, i) => [127 + i * 1e-5, 37]) } })],
  ])("만들기를 거부한다: %s", (_name, value) => {
    expect(parseCreateLineBody(value)).toBeNull();
  });

  it.each([
    ["개정 번호가 없다", revise({ expectedRevision: undefined })],
    ["개정 0", revise({ expectedRevision: 0 })],
    ["개정이 문자열", revise({ expectedRevision: "2" })],
    ["개정 상한 초과", revise({ expectedRevision: 101 })],
    ["구역을 바꾸려는 시도", revise({ workAreaId: "other" })],
    ["이름이 비었다", revise({ name: "" })],
    ["점이 하나", revise({ line: { ...line, vertices: [[127, 37]] } })],
  ])("고치기를 거부한다: %s", (_name, value) => {
    expect(parseReviseLineBody(value)).toBeNull();
  });
});
