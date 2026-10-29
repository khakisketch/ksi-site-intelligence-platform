import { describe, expect, it, vi } from "vitest";

// Leaflet/지도는 Node 테스트에서 올리지 않는다 — 키보드 대안의 순수 판정과
// 소스 계약(포인터 전용 도구 보존·네이티브 입력·정직한 오류)만 본다.
vi.mock("leaflet", () => ({
  default: { polygon: vi.fn(), drawLocal: { draw: { toolbar: {} }, edit: { toolbar: {} } } },
}));
vi.mock("leaflet-draw", () => ({}));
vi.mock("react-leaflet", () => ({
  MapContainer: () => null,
  TileLayer: () => null,
  useMap: () => null,
}));

import fs from "node:fs";
import path from "node:path";

const innerPath = path.resolve(process.cwd(), "src/components/map/AoiPolygonMapInner.tsx");
const innerSource = fs.readFileSync(innerPath, "utf8");
const outerSource = fs.readFileSync(
  path.resolve(process.cwd(), "src/components/map/AoiPolygonMap.tsx"),
  "utf8",
);

describe("AOI 키보드 입력 대안(순수 판정)", () => {
  it("포인터 그리기 계약을 유지한다", () => {
    expect(innerSource).toContain("function applyKoreanDrawLabels");
    expect(innerSource).toContain("경계 그리기");
    expect(innerSource).toContain("allowIntersection: false");
    expect(innerSource).toContain("drawError");
  });

  it("키보드 대안을 지도와 같은 파일에서 제공한다", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    expect(typeof mod.validateKeyboardVertices).toBe("function");
    expect(typeof mod.parseKeyboardCoordinate).toBe("function");
    expect(typeof mod.AoiKeyboardEditor).toBe("function");
  });

  it("유효한 위경도를 그대로 통과시킨다", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    const rows = [
      { lat: "37.5665", lon: "126.978" },
      { lat: "37.5660", lon: "126.979" },
      { lat: "37.5655", lon: "126.977" },
    ];
    const result = mod.validateKeyboardVertices(rows);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.vertices).toEqual([
        { latDeg: 37.5665, lonDeg: 126.978 },
        { latDeg: 37.566, lonDeg: 126.979 },
        { latDeg: 37.5655, lonDeg: 126.977 },
      ]);
    }
  });

  it("빈 입력·숫자가 아님을 정직하게 막는다", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    expect(mod.parseKeyboardCoordinate("", "lat").ok).toBe(false);
    expect(mod.parseKeyboardCoordinate("북위", "lat").ok).toBe(false);
    expect(mod.parseKeyboardCoordinate("Infinity", "lon").ok).toBe(false);
    const result = mod.validateKeyboardVertices([
      { lat: "", lon: "126.978" },
      { lat: "37.5660", lon: "126.979" },
      { lat: "37.5655", lon: "126.977" },
    ]);
    expect(result.ok).toBe(false);
  });

  it("위경도 범위를 추측 없이 막는다", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    const latOut = mod.validateKeyboardVertices([
      { lat: "91", lon: "126.978" },
      { lat: "37.5660", lon: "126.979" },
      { lat: "37.5655", lon: "126.977" },
    ]);
    expect(latOut.ok).toBe(false);
    const lonOut = mod.validateKeyboardVertices([
      { lat: "37.5665", lon: "190" },
      { lat: "37.5660", lon: "126.979" },
      { lat: "37.5655", lon: "126.977" },
    ]);
    expect(lonOut.ok).toBe(false);
  });

  it("3점 미만·256점 초과를 막는다", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    const few = mod.validateKeyboardVertices([
      { lat: "37.5665", lon: "126.978" },
      { lat: "37.5660", lon: "126.979" },
    ]);
    expect(few.ok).toBe(false);
    const many = Array.from({ length: 257 }, (_, i) => ({
      lat: "37.5",
      lon: String(126.9 + i * 0.0001),
    }));
    expect(mod.validateKeyboardVertices(many).ok).toBe(false);
  });

  it("중복점·자기교차는 포인터 그리기와 같은 강도로 막는다", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    const dup = mod.validateKeyboardVertices([
      { lat: "37.5665", lon: "126.978" },
      { lat: "37.5665", lon: "126.978" },
      { lat: "37.5655", lon: "126.977" },
    ]);
    expect(dup.ok).toBe(false);
    // 나비넥타이(bow-tie): 변 0-1과 변 2-0이 교차한다.
    const bowtie = mod.validateKeyboardVertices([
      { lat: "0", lon: "0" },
      { lat: "1", lon: "1" },
      { lat: "0", lon: "1" },
      { lat: "1", lon: "0" },
    ]);
    expect(bowtie.ok).toBe(false);
  });

  it("십진 원문이 다른 두 점이 숫자 변환으로 같아지면 중복으로 단정하지 않는다", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    const rounded = mod.validateKeyboardVertices([
      { lat: "0", lon: "1" },
      { lat: "0", lon: "1.0000000000000001" },
      { lat: "1", lon: "0" },
    ]);
    expect(rounded.ok).toBe(false);
    if (!rounded.ok) {
      expect(rounded).toHaveProperty("uncertain", true);
      expect(rounded.reason).not.toMatch(/같은 점입니다/);
    }
    const exact = mod.validateKeyboardVertices([
      { lat: "0", lon: "1" },
      { lat: "0.0", lon: "1.0" },
      { lat: "1", lon: "0" },
    ]);
    expect(exact.ok).toBe(false);
    if (!exact.ok) expect(exact.reason).toMatch(/같은 점입니다/);
  });

  it("교차하지 않는 미세 사각형과 진짜 교차를 함께 판정한다 (eps 스냅 회귀)", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    // 평행하고 닿지 않는 미세 사각형 — 예전 1e-12 스냅이 "변 1↔3 교차"로 거부했다.
    const quad = mod.validateKeyboardVertices([
      { lat: "37.5", lon: "127" },
      { lat: "37.50001", lon: "127.00001" },
      { lat: "37.5000101", lon: "127.00001" },
      { lat: "37.5000001", lon: "127" },
    ]);
    expect(quad.ok).toBe(true);
    // 진짜 교차(나비넥타이)는 같은 실행에서 계속 막는다.
    const bowtie = mod.validateKeyboardVertices([
      { lat: "0", lon: "0" },
      { lat: "1", lon: "1" },
      { lat: "0", lon: "1" },
      { lat: "1", lon: "0" },
    ]);
    expect(bowtie.ok).toBe(false);
  });

  it("미세 사각형은 역순·순환 시작점에서도 통과한다", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    const quadRows = [
      { lat: "37.5", lon: "127" },
      { lat: "37.50001", lon: "127.00001" },
      { lat: "37.5000101", lon: "127.00001" },
      { lat: "37.5000001", lon: "127" },
    ];
    expect(mod.validateKeyboardVertices([...quadRows].reverse()).ok).toBe(true);
    expect(
      mod.validateKeyboardVertices([...quadRows.slice(2), ...quadRows.slice(0, 2)]).ok,
    ).toBe(true);
  });

  it("정수 완전 직선 삼각형은 면적 0 퇴화로 막는다 (불확실 아님)", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    // 십진·제출값 양쪽에서 정확히 0이므로 확실한 퇴화다 — 판단 보류가 아니다.
    const straight = mod.validateKeyboardVertices([
      { lat: "0", lon: "0" },
      { lat: "1", lon: "1" },
      { lat: "2", lon: "2" },
    ]);
    expect(straight.ok).toBe(false);
    if (!straight.ok) {
      expect(straight.reason).toMatch(/면적이 0/);
      expect(straight).not.toHaveProperty("uncertain", true);
    }
  });

  it("Number.MIN_VALUE 규모도 거짓 퇴화가 아니라 통과한다", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    const tiny = mod.validateKeyboardVertices([
      { lat: "0", lon: "0" },
      { lat: "0", lon: "5e-324" },
      { lat: "5e-324", lon: "0" },
    ]);
    expect(tiny.ok).toBe(true);
  });

  it("변 위 중간 공선점은 통과하고 인접 되짚기는 막는다", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    // 변 위 중간점 — 단순 오각형 그대로다.
    expect(
      mod.validateKeyboardVertices([
        { lat: "0", lon: "0" },
        { lat: "0", lon: "1" },
        { lat: "0", lon: "2" },
        { lat: "2", lon: "2" },
        { lat: "2", lon: "0" },
      ]).ok,
    ).toBe(true);
    // 되짚기: C(위도 0, 경도 1)가 인접하지 않은 변 A-B 위에 정확히 얹힌다.
    const retrace = mod.validateKeyboardVertices([
      { lat: "0", lon: "0" },
      { lat: "0", lon: "2" },
      { lat: "0", lon: "1" },
      { lat: "2", lon: "2" },
      { lat: "2", lon: "0" },
    ]);
    expect(retrace.ok).toBe(false);
    if (!retrace.ok) expect(retrace.reason).toMatch(/교차/);
  });

  it("음수 좌표 삼각형은 올바른 부호로 통과한다 (sign 비트 회귀)", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    // (lat,lon)=(0,-1),(0,1),(1,0) 합성 정삼각형 — 부호를 버리면 uncertain/오판한다.
    const tri = mod.validateKeyboardVertices([
      { lat: "0", lon: "-1" },
      { lat: "0", lon: "1" },
      { lat: "1", lon: "0" },
    ]);
    expect(tri.ok).toBe(true);
  });

  it("4사분면 사각형은 통과하고 부호 혼합 bow-tie는 막는다", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    const square = mod.validateKeyboardVertices([
      { lat: "-1", lon: "-1" },
      { lat: "-1", lon: "1" },
      { lat: "1", lon: "1" },
      { lat: "1", lon: "-1" },
    ]);
    expect(square.ok).toBe(true);
    const bowtie = mod.validateKeyboardVertices([
      { lat: "-1", lon: "-1" },
      { lat: "1", lon: "1" },
      { lat: "-1", lon: "1" },
      { lat: "1", lon: "-1" },
    ]);
    expect(bowtie.ok).toBe(false);
  });

  it("+0/-0과 ±MIN_VALUE를 거짓 퇴화로 보지 않는다", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    expect(
      mod.validateKeyboardVertices([
        { lat: "0", lon: "0" },
        { lat: "-0", lon: "1" },
        { lat: "1", lon: "0" },
      ]).ok,
    ).toBe(true);
    expect(
      mod.validateKeyboardVertices([
        { lat: "0", lon: "-5e-324" },
        { lat: "0", lon: "5e-324" },
        { lat: "5e-324", lon: "0" },
      ]).ok,
    ).toBe(true);
  });

  it("십진 정밀도 한계를 넘기면 판단 보류로 막는다 (계산 상한, 기하 정책 아님)", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    // 같은 십진 원리(일직선)이지만 자릿수가 계산 한계를 넘으면 double만으로
    // 통과시키지 않는다 — 서버 판단을 대신하지도 않는다.
    const longZero = "37.5665" + "0".repeat(45);
    const over = mod.validateKeyboardVertices([
      { lat: "37.5665", lon: "126.978" },
      { lat: "37.5666", lon: "126.979" },
      { lat: longZero, lon: "126.98" },
    ]);
    expect(over.ok).toBe(false);
    if (!over.ok) {
      expect(over).toHaveProperty("uncertain", true);
      expect(over.reason).toMatch(/계산 한계/);
    }
  });

  it("미반영 판정은 십진 의미를 본다 (정식 표기는 풀고 뭉개진 표기는 막는다)", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    const committed = [
      { latDeg: 37.5, lonDeg: 127 },
      { latDeg: 37.5, lonDeg: 127.01 },
      { latDeg: 37.51, lonDeg: 127.01 },
    ];
    const sameMeaning = [
      { lat: "+37.5", lon: "127" },
      { lat: "37.5000", lon: "127.01" },
      { lat: "37.51", lon: "1.2701e2" },
    ];
    expect(mod.computeKeyboardPending(sameMeaning, committed)).toEqual({
      blocked: false,
      reason: null,
    });
    // 반올림으로 뭉개진 표기는 같은 double이어도 미반영으로 둔다.
    const rounded = [
      { lat: "37.50000000000000000000000000001", lon: "127" },
      { lat: "37.5", lon: "127.01" },
      { lat: "37.51", lon: "127.01" },
    ];
    const pending = mod.computeKeyboardPending(rounded, committed);
    expect(pending.blocked).toBe(true);
    expect(pending.reason).toMatch(/반영/);
  });

  it("미반영 판정은 십진 의미를 본다 (정식 표기는 풀고 뭉개진 표기는 막는다)", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    const committed = [
      { latDeg: 37.5, lonDeg: 127 },
      { latDeg: 37.5, lonDeg: 127.01 },
      { latDeg: 37.51, lonDeg: 127.01 },
    ];
    // "+37.5"·"37.5000"·"1e-3"은 정식 표기와 같은 유리수이므로 clean이다.
    expect(
      mod.computeKeyboardPending(
        [
          { lat: "+37.5", lon: "127" },
          { lat: "37.5000", lon: "127.01" },
          { lat: "37.51", lon: "1.2701e2" },
        ],
        committed,
      ),
    ).toEqual({ blocked: false, reason: null });
    // 반올림으로 뭉개진 표기는 같은 double이어도 미반영으로 둔다.
    const rounded = mod.computeKeyboardPending(
      [
        { lat: "37.50000000000000000000000000001", lon: "127" },
        { lat: "37.5", lon: "127.01" },
        { lat: "37.51", lon: "127.01" },
      ],
      committed,
    );
    expect(rounded.blocked).toBe(true);
    expect(rounded.reason).toMatch(/반영/);
  });

  it("지도에 그려 확인할 수 없는 입력은 판단 보류로 막는다 (투영 한계)", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    // 89°는 지도에서 85.05°와 같은 픽셀에 그려진다 — 제출값과 화면이 달라진다.
    const polar = mod.validateKeyboardVertices([
      { lat: "89", lon: "-10" },
      { lat: "89", lon: "10" },
      { lat: "88", lon: "0" },
    ]);
    expect(polar.ok).toBe(false);
    if (!polar.ok) {
      expect(polar).toHaveProperty("uncertain", true);
      expect(polar.reason).toMatch(/판단하지 못했습니다/);
      expect(polar.reason).toMatch(/85\.05/);
      expect(polar.reason).not.toMatch(/교차|면적이 0/);
    }
    // 날짜변경선을 가로지르는 변도 지도에 가로질러 그려진다.
    const dateline = mod.validateKeyboardVertices([
      { lat: "0", lon: "179" },
      { lat: "0", lon: "-179" },
      { lat: "1", lon: "0" },
    ]);
    expect(dateline.ok).toBe(false);
    if (!dateline.ok) {
      expect(dateline).toHaveProperty("uncertain", true);
      expect(dateline.reason).toMatch(/날짜변경선/);
    }
    // 한계 안쪽(경계값 포함)은 그대로 통과한다 — 범위를 좁히지 않는다.
    expect(
      mod.validateKeyboardVertices([
        { lat: "85.0511287798", lon: "-10" },
        { lat: "85.0511287798", lon: "10" },
        { lat: "84", lon: "0" },
      ]).ok,
    ).toBe(true);
    expect(
      mod.validateKeyboardVertices([
        { lat: "0", lon: "179.9" },
        { lat: "0", lon: "180" },
        { lat: "1", lon: "179.9" },
      ]).ok,
    ).toBe(true);
  });

  it("정확 접촉(T-접촉)은 지도 그리기와 같은 강도로 막는다", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    // E(위도 0, 경도 1)가 변 A-B 위에 정확히 얹힌 고리 — 단순 폴리곤이 아니다.
    const touch = mod.validateKeyboardVertices([
      { lat: "0", lon: "0" },
      { lat: "0", lon: "2" },
      { lat: "1", lon: "2" },
      { lat: "1", lon: "1" },
      { lat: "0", lon: "1" },
    ]);
    expect(touch.ok).toBe(false);
    if (!touch.ok) expect(touch.reason).toMatch(/교차/);
  });
  it("십진 완전 일직선·부동소수 어긋남은 불확실로 막는다 (단정 금지)", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    // 십진수로는 정확히 일직선이지만 double로는 미세하게 어긋나는 입력 —
    // 교차라고도 등록 가능하다고도 말하지 않고 판단 보류로 막는다.
    const flat = mod.validateKeyboardVertices([
      { lat: "37.5665", lon: "126.978" },
      { lat: "37.5666", lon: "126.979" },
      { lat: "37.5667", lon: "126.98" },
    ]);
    expect(flat.ok).toBe(false);
    if (!flat.ok) {
      expect(flat).toHaveProperty("uncertain", true);
      expect(flat.reason).toMatch(/판단하지 못했습니다/);
      expect(flat.reason).not.toMatch(/교차/);
    }
  });

  it("극소 합법 삼각형은 통과한다 (1e-12 임의 하한 회귀)", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    const tiny = mod.validateKeyboardVertices([
      { lat: "37.5665", lon: "126.978" },
      { lat: "37.5665", lon: "126.9780008" },
      { lat: "37.5665008", lon: "126.978" },
    ]);
    expect(tiny.ok).toBe(true);
    if (tiny.ok) {
      expect(tiny.vertices).toEqual([
        { latDeg: 37.5665, lonDeg: 126.978 },
        { latDeg: 37.5665, lonDeg: 126.9780008 },
        { latDeg: 37.5665008, lonDeg: 126.978 },
      ]);
    }
  });

  it("십진수가 아닌 문자열을 예기치 않게 해석하지 않는다", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    expect(mod.parseKeyboardCoordinate("0x10", "lon").ok).toBe(false);
    expect(mod.parseKeyboardCoordinate("0b11", "lat").ok).toBe(false);
    expect(mod.parseKeyboardCoordinate("0o17", "lon").ok).toBe(false);
    expect(mod.parseKeyboardCoordinate("12ab", "lat").ok).toBe(false);
    expect(mod.parseKeyboardCoordinate("1,5", "lat").ok).toBe(false);
    // 십진 지수·소수점 생략·부호는 십진수라 받는다.
    expect(mod.parseKeyboardCoordinate("1e-3", "lon").ok).toBe(true);
    expect(mod.parseKeyboardCoordinate(".5", "lat").ok).toBe(true);
    expect(mod.parseKeyboardCoordinate("+37.5", "lat").ok).toBe(true);
    const hexRow = mod.validateKeyboardVertices([
      { lat: "37.5665", lon: "0x10" },
      { lat: "37.5660", lon: "126.979" },
      { lat: "37.5655", lon: "126.977" },
    ]);
    expect(hexRow.ok).toBe(false);
  });

  it("256 경계는 통과하고 257은 상한으로 막는다", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    const circle = (n: number) =>
      Array.from({ length: n }, (_, i) => {
        const a = (i / n) * 2 * Math.PI;
        return { lat: String(37.5 + 0.001 * Math.cos(a)), lon: String(127 + 0.001 * Math.sin(a)) };
      });
    expect(mod.validateKeyboardVertices(circle(256)).ok).toBe(true);
    const over = mod.validateKeyboardVertices(circle(257));
    expect(over.ok).toBe(false);
    if (!over.ok) expect(over.reason).toMatch(/256/);
    // 상한 초과 문구는 잘랐다는 말이 아니라 유지·다시 그리라는 말이다.
    expect(mod.vertexLimitMessage(257)).toMatch(/257개/);
    expect(mod.vertexLimitMessage(257)).toMatch(/상한 256개/);
    expect(mod.vertexLimitMessage(257)).toMatch(/그대로 유지/);
  });

  it("포인터 진행 중 상태 판정을 공유한다", async () => {
    const mod = await import("@/components/map/AoiPolygonMapInner");
    expect(mod.pointerPendingState("idle")).toEqual({ blocked: false, reason: null });
    for (const mode of ["draw", "edit", "delete"] as const) {
      const pending = mod.pointerPendingState(mode);
      expect(pending.blocked).toBe(true);
      expect(pending.reason).toMatch(/완료·취소하기 전에는 등록할 수 없습니다/);
    }
    expect(mod.pointerPendingState("draw").reason).toMatch(/그리는 중/);
    expect(mod.pointerPendingState("edit").reason).toMatch(/편집하는 중/);
    expect(mod.pointerPendingState("delete").reason).toMatch(/삭제하는 중/);
    // 미반영 판정: clean이면 열리고, 행이 다르면 막는다.
    expect(
      mod.computeKeyboardPending([], []),
    ).toEqual({ blocked: false, reason: null });
    const committed = [
      { latDeg: 37.5, lonDeg: 127 },
      { latDeg: 37.5, lonDeg: 127.01 },
      { latDeg: 37.51, lonDeg: 127.01 },
    ];
    expect(
      mod.computeKeyboardPending(
        [
          { lat: "37.5", lon: "127" },
          { lat: "37.5", lon: "127.01" },
          { lat: "37.51", lon: "127.01" },
        ],
        committed,
      ).blocked,
    ).toBe(false);
    const dirty = mod.computeKeyboardPending(
      [
        { lat: "37.5", lon: "127" },
        { lat: "37.5", lon: "127.01" },
        { lat: "37.52", lon: "127.01" },
      ],
      committed,
    );
    expect(dirty.blocked).toBe(true);
    expect(dirty.reason).toMatch(/등록할 수 없습니다/);
  });

  it("네이티브 키보드 조작 계약을 소스로 고정한다", () => {
    expect(innerSource).toContain("<fieldset");
    expect(innerSource).toContain("<legend");
    expect(innerSource).toContain("aria-describedby");
    expect(innerSource).toContain('role="alert"');
    expect(innerSource).toContain("현재 지도 값 불러오기");
    expect(innerSource).toContain("지도에 반영");
    expect(innerSource).toContain("EPSG:4326");
    // 숫자·범위를 추측하지 않는다 — 입력 행은 빈칸으로 시작하고(불러오기는
    // 지도 값을 그대로 옮긴다), 제출되는 기본 좌표가 소스에 없다. 지도 중심
    // 기본값(서울 시야, 데이터 아님)은 제외하고 키보드 입력기 범위로 본다.
    const editorStart = innerSource.indexOf("export function AoiKeyboardEditor");
    expect(editorStart).toBeGreaterThan(-1);
    const editorEnd = innerSource.indexOf("export function AoiPolygonMapInner", editorStart);
    expect(editorEnd).toBeGreaterThan(editorStart);
    const editorSource = innerSource.slice(editorStart, editorEnd);
    expect(editorSource).toContain("toKeyboardRows(value)");
    expect(editorSource).not.toContain("37.5665");
    expect(editorSource).not.toContain("126.978");
    expect(editorSource).not.toMatch(/useState<\s*KeyboardVertexRow\[\]\s*>\(\(\) => \[\{/);
    // readOnly(보기 전용)에서는 키보드 입력기를 내지 않는다.
    expect(innerSource).toContain("const editable = !readOnly");
    expect(innerSource).toContain("{editable && (");
    expect(innerSource).toContain("onPendingChange={setKeyboardPending}");
    // 외부 값(포인터 그리기·정정 불러오기)과 동기화해 화면·제출이 갈라지지 않는다.
    expect(innerSource).toContain("group.clearLayers()");
    expect(innerSource).toContain("[map, value]");
    // 자기 커밋·지우기는 외부 변경으로 오판하지 않는다.
    expect(innerSource).toContain("lastValueRef.current = result.vertices");
    expect(innerSource).toContain("lastValueRef.current = []");
  });

  it("상한 초과 포인터 입력을 조용히 자르지 않는다", () => {
    // emit에 slice 절단이 없고, 초과하면 보내지 않고 복원·명시한다.
    expect(innerSource).not.toContain("vertices.slice(0, _MAX_AOI_VERTICES)");
    expect(innerSource).toContain("function vertexLimitMessage");
    expect(innerSource).toContain("if (vertices.length > _MAX_AOI_VERTICES)");
    expect(innerSource).toContain("L.popup({ closeButton: true })");
    // 초과·교차·퇴화·불확실은 공통 경계(rejectRing)로 복원·명시하고 보내지 않는다.
    expect(innerSource).toContain("rejectRing(vertexLimitMessage(vertices.length), last)");
    expect(innerSource).toContain("evaluateRingGeometry(vertices, null)");
    // 복원은 최신 커밋값을 본다(마운트 스냅샷 재생 금지).
    expect(innerSource).toContain("const committed = valueRef.current");
  });

  it("포인터 진행 중 생명주기를 실제 Leaflet 이벤트에 연결한다", () => {
    for (const name of [
      "L.Draw.Event.DRAWSTART",
      "L.Draw.Event.DRAWSTOP",
      "L.Draw.Event.EDITSTART",
      "L.Draw.Event.EDITSTOP",
      "L.Draw.Event.DELETESTART",
      "L.Draw.Event.DELETESTOP",
    ]) {
      expect(innerSource).toContain(`map.on(${name}`);
      expect(innerSource).toContain(`map.off(${name}`);
    }
    // 완료(CREATED·EDITED·DELETED)는 각 정지보다 항상 먼저 오므로 반영 뒤
    // 해제되고, 취소는 생성·되돌린 뒤 정지한다 — 어느 경우도 미완성을 보내지 않는다.
    expect(innerSource).toContain("pointerPendingState(");
    expect(innerSource).toContain("function pointerPendingState");
    // 청소 시점에도 막힘을 남기지 않는다.
    expect(innerSource).toContain("pointerPendingState(\"idle\")");
    // 포인터/거부/키보드 막힘의 우선순위 및 여러 원본 보존은
    // aoi-draw-lifecycle.test.tsx의 실제 이벤트 흐름으로 검증한다.
    expect(innerSource).toContain('data-testid="map-rejected-draw"');
    expect(innerSource).toContain('data-testid="map-reject-discard"');
    // 포인터 진행 중에는 키보드 입력을 비활성화한다(입력 방식 엇갈림 방지).
    expect(innerSource).toContain("disabled={pointerPending.blocked}");
    expect(innerSource).toContain("<fieldset");
    expect(innerSource).toContain("disabled={disabled}");
  });

  it("겉 포장은 로딩·입력기·미반영 알림을 함께 둔다", () => {
    expect(outerSource).toContain("SkeletonBlock");
    expect(outerSource).toContain("AoiPolygonMapInner");
    expect(outerSource).toContain("onPendingChange");
    expect(outerSource).toContain("AoiMapPendingState");
  });
});
