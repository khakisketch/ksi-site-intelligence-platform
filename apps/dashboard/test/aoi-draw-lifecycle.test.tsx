/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createElement, StrictMode, type ReactNode } from "react";

// DrawControl의 Leaflet 배선을 행위 수준에서 검증한다 — 가짜 지도·가짜 레이어로
// 실제 이벤트 흐름(CREATED→정지, 취소→되돌림→정지, 상한 초과 fail-closed)을
// 재현한다. 이벤트 심볼→문자열 결속은 아래 `leaflet-draw 실제 결속` 테스트가
// 설치된 패키지 소스에서 직접 고정하므로, 여기서 쓰는 문자열이 추측이 아니다.
const holder = vi.hoisted(() => {
  class FakeGroup {
    layers: unknown[] = [];
    addLayer(layer: unknown) {
      this.layers.push(layer);
      return this;
    }
    clearLayers() {
      this.layers = [];
      return this;
    }
    getLayers() {
      return [...this.layers];
    }
  }
  return {
    map: null as unknown as {
      listeners: Map<string, Set<(...args: never[]) => void>>;
      addedLayers: unknown[];
      on: (event: string, cb: (...args: never[]) => void) => unknown;
      off: (event: string, cb: (...args: never[]) => void) => unknown;
      addLayer: (layer: unknown) => unknown;
      removeLayer: () => unknown;
      addControl: () => unknown;
      removeControl: () => unknown;
      hasLayer: () => boolean;
      fitBounds: (...args: unknown[]) => void;
      getCenter: () => { lat: number; lng: number };
      fire: (event: string, data?: unknown) => void;
    } | null,
    popupContents: [] as string[],
    FakeGroup,
  };
});

describe("AoiKeyboardEditor 추가 행 포커스", () => {
  // jsdom does not synthesize a native click from Enter/Space. detail:0 models
  // the resulting keyboard-style click; actual keys are checked separately in
  // a source-matched Chromium component harness.
  it("키보드 활성화로 추가한 행의 위도로 이동하고 기존 폴리곤은 바꾸지 않는다", () => {
    const polygon = [{ latDeg: 37, lonDeg: 127 }, { latDeg: 38, lonDeg: 127 }, { latDeg: 37, lonDeg: 128 }];
    const onChange = vi.fn();
    const onPendingChange = vi.fn();
    const onRowsChange = vi.fn();
    render(createElement(AoiKeyboardEditor, { value: polygon, onChange, onPendingChange, onRowsChange }));
    const add = screen.getByRole("button", { name: "꼭짓점 추가" });
    add.focus();
    fireEvent.click(add, { detail: 0 });
    expect(document.activeElement).toBe(screen.getAllByPlaceholderText("-90 ~ 90")[3]);
    expect(onChange).not.toHaveBeenCalled();
    expect(onPendingChange).toHaveBeenLastCalledWith(expect.objectContaining({ blocked: true }));
    expect(onRowsChange).toHaveBeenLastCalledWith([{ lat: "37", lon: "127" }, { lat: "38", lon: "127" }, { lat: "37", lon: "128" }, { lat: "", lon: "" }]);
  });

  it("포인터 클릭이나 다른 위치에서의 호출은 입력 포커스를 강제로 옮기지 않는다", () => {
    render(createElement(AoiKeyboardEditor, { value: [], onChange: vi.fn() }));
    const add = screen.getByRole("button", { name: "꼭짓점 추가" });
    add.focus();
    fireEvent.click(add, { detail: 1 });
    expect(document.activeElement).toBe(add);
    const outside = document.createElement("button");
    document.body.append(outside);
    outside.focus();
    fireEvent.click(add, { detail: 0 });
    expect(document.activeElement).toBe(outside);
    outside.remove();
  });

  it("마지막 허용 행의 위도로 이동한 뒤 추가 버튼을 비활성화한다", () => {
    const initialRows = Array.from({ length: 255 }, () => ({ lat: "", lon: "" }));
    render(createElement(AoiKeyboardEditor, { value: [], onChange: vi.fn(), initialRows }));
    const add = screen.getByRole("button", { name: "꼭짓점 추가" });
    add.focus();
    fireEvent.click(add, { detail: 0 });
    expect(screen.getAllByPlaceholderText("-90 ~ 90")).toHaveLength(256);
    expect(document.activeElement).toBe(screen.getAllByPlaceholderText("-90 ~ 90")[255]);
    expect((add as HTMLButtonElement).disabled).toBe(true);
  });

  it("추가 콜백에서 사용자가 다른 곳으로 옮긴 포커스를 빼앗지 않는다", () => {
    const outside = document.createElement("button");
    document.body.append(outside);
    render(createElement(AoiKeyboardEditor, { value: [], onChange: vi.fn(), onRowsChange: () => outside.focus() }));
    const add = screen.getByRole("button", { name: "꼭짓점 추가" });
    add.focus();
    fireEvent.click(add, { detail: 0 });
    expect(document.activeElement).toBe(outside);
    outside.remove();
  });

  it("한 배치에서 연속 추가한 두 원문을 보존한다", () => {
    const onRowsChange = vi.fn();
    render(createElement(AoiKeyboardEditor, { value: [], onChange: vi.fn(), onRowsChange }));
    const add = screen.getByRole("button", { name: "꼭짓점 추가" });
    add.focus();
    act(() => {
      fireEvent.click(add, { detail: 0 });
      fireEvent.click(add, { detail: 0 });
    });
    expect(screen.getAllByPlaceholderText("-90 ~ 90")).toHaveLength(2);
    expect(document.activeElement).toBe(screen.getAllByPlaceholderText("-90 ~ 90")[1]);
    expect(onRowsChange).toHaveBeenLastCalledWith([{ lat: "", lon: "" }, { lat: "", lon: "" }]);
  });

  it("복구·비활성 렌더와 마지막 행에서 명시한 blur는 포커스를 빼앗지 않는다", () => {
    const outside = document.createElement("button");
    document.body.append(outside);
    outside.focus();
    const { rerender, unmount } = render(createElement(AoiKeyboardEditor, { value: [], onChange: vi.fn(), initialRows: [{ lat: "37", lon: "127" }] }));
    expect(document.activeElement).toBe(outside);
    rerender(createElement(AoiKeyboardEditor, { value: [], onChange: vi.fn(), disabled: true }));
    expect(document.activeElement).toBe(outside);
    unmount();
    expect(document.activeElement).toBe(outside);
    outside.remove();

    const initialRows = Array.from({ length: 255 }, () => ({ lat: "", lon: "" }));
    render(createElement(AoiKeyboardEditor, { value: [], onChange: vi.fn(), initialRows, onRowsChange: () => (document.activeElement as HTMLElement).blur() }));
    const add = screen.getByRole("button", { name: "꼭짓점 추가" });
    add.focus();
    fireEvent.click(add, { detail: 0 });
    expect(document.activeElement).toBe(document.body);
    expect((add as HTMLButtonElement).disabled).toBe(true);
  });
});

function makeLatLng(lat: number, lng: number) {
  return { lat, lng };
}

function circlePoints(n: number) {
  return Array.from({ length: n }, (_, i) => {
    const a = (i / n) * 2 * Math.PI;
    return makeLatLng(37.5 + 0.001 * Math.cos(a), 127 + 0.001 * Math.sin(a));
  });
}

function makeLayer(points: { lat: number; lng: number }[]) {
  return {
    getLatLngs: () => [points],
    getBounds: () => ({
      getCenter: () => ({ lat: 0, lng: 0 }),
    }),
    addTo: () => undefined,
  };
}

function makeMap() {
  const listeners = new Map<string, Set<(...args: never[]) => void>>();
  const addedLayers: unknown[] = [];
  const map = {
    listeners,
    addedLayers,
    on: (event: string, cb: (...args: never[]) => void) => {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event)!.add(cb);
      return map;
    },
    off: (event: string, cb: (...args: never[]) => void) => {
      listeners.get(event)?.delete(cb);
      return map;
    },
    addLayer: (layer: unknown) => {
      addedLayers.push(layer);
      return map;
    },
    removeLayer: () => map,
    addControl: () => map,
    removeControl: () => map,
    hasLayer: () => true,
    fitBounds: vi.fn(),
    getCenter: () => ({ lat: 0, lng: 0 }),
    fire: (event: string, data?: unknown) => {
      listeners.get(event)?.forEach((cb) => (cb as (d: unknown) => void)(data));
    },
  };
  return map;
}

vi.mock("leaflet", () => ({
  default: {
    polygon: (latlngs: [number, number][]) => makeLayer(latlngs.map(([lat, lng]) => makeLatLng(lat, lng))),
    popup: () => {
      const api = {
        setLatLng: () => api,
        setContent: (content: string) => {
          holder.popupContents.push(content);
          return api;
        },
        openOn: () => api,
      };
      return api;
    },
    drawLocal: {
      draw: {
        toolbar: { actions: {}, finish: {}, undo: {}, buttons: {} },
        handlers: { polygon: { tooltip: {} } },
      },
      edit: {
        toolbar: { actions: { save: {}, cancel: {}, clearAll: {} }, buttons: {} },
        handlers: { edit: { tooltip: {} }, remove: { tooltip: {} } },
      },
    },
    Control: { Draw: class DrawStub {} },
    Draw: {
      Event: {
        CREATED: "draw:created",
        EDITED: "draw:edited",
        DELETED: "draw:deleted",
        DRAWSTART: "draw:drawstart",
        DRAWSTOP: "draw:drawstop",
        EDITSTART: "draw:editstart",
        EDITSTOP: "draw:editstop",
        DELETESTART: "draw:deletestart",
        DELETESTOP: "draw:deletestop",
      },
    },
    FeatureGroup: holder.FakeGroup,
  },
}));
vi.mock("leaflet-draw", () => ({}));
vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children?: ReactNode }) => createElement("div", null, children),
  TileLayer: () => null,
  useMap: () => holder.map,
}));

import fs from "node:fs";
import path from "node:path";

import { AoiKeyboardEditor, AoiPolygonMapInner, DrawControl } from "@/components/map/AoiPolygonMapInner";

const A = [
  { latDeg: 37.5, lonDeg: 127 },
  { latDeg: 37.5, lonDeg: 127.01 },
  { latDeg: 37.51, lonDeg: 127.01 },
];

afterEach(() => {
  cleanup();
  holder.map = null;
  holder.popupContents = [];
});

function setup(value: { latDeg: number; lonDeg: number }[]) {
  holder.map = makeMap() as unknown as typeof holder.map;
  const onChange = vi.fn();
  const onPointerPending = vi.fn();
  const onRejectedChange = vi.fn();
  const rendered = render(
    createElement(DrawControl, { value, onChange, onPointerPending, onRejectedChange }),
  );
  return { map: holder.map!, onChange, onPointerPending, onRejectedChange, rendered };
}

describe("DrawControl 포인터 생명주기 (행위)", () => {
  it("초기 범위·거부 복원·외부값 반영은 모두 배경 타일보다 세밀하게 맞춘다", () => {
    const { map, onChange, onPointerPending, onRejectedChange, rendered } = setup(A);
    expect(map.fitBounds).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ maxZoom: 26 }));
    vi.mocked(map.fitBounds).mockClear();
    act(() => map.fire("draw:created", {
      layer: makeLayer([{ lat: 0, lng: 0 }, { lat: 1, lng: 1 }, { lat: 0, lng: 1 }, { lat: 1, lng: 0 }]),
      layerType: "polygon",
    }));
    expect(onChange).not.toHaveBeenCalled();
    expect(map.fitBounds).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ maxZoom: 26 }));
    vi.mocked(map.fitBounds).mockClear();
    const changed = A.map((v) => ({ latDeg: v.latDeg + 0.1, lonDeg: v.lonDeg + 0.1 }));
    rendered.rerender(createElement(DrawControl, { value: changed, onChange, onPointerPending, onRejectedChange }));
    expect(map.fitBounds).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ maxZoom: 26 }));
  });

  it("읽기 전용 미리보기도 벡터를 세밀하게 맞춘다", () => {
    holder.map = makeMap() as unknown as typeof holder.map;
    render(createElement(AoiPolygonMapInner, { value: A, readOnly: true }));
    expect(holder.map!.fitBounds).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ maxZoom: 26 }));
  });

  it("StrictMode 재설정 후에도 기존 반영 범위는 한 개만 표시한다", () => {
    holder.map = makeMap() as unknown as typeof holder.map;
    render(createElement(StrictMode, null, createElement(DrawControl, { value: A, onChange: vi.fn() })));
    const group = (holder.map!.addedLayers as InstanceType<typeof holder.FakeGroup>[]).find(
      (layer) => layer instanceof holder.FakeGroup,
    )!;
    expect(group.getLayers()).toHaveLength(1);
  });

  it("포인터 편집 중 같은 좌표의 새 배열이 와도 미반영 모양을 덮지 않는다", () => {
    const { map, onChange, onPointerPending, onRejectedChange, rendered } = setup(A);
    const group = (map.addedLayers as InstanceType<typeof holder.FakeGroup>[]).find(
      (layer) => layer instanceof holder.FakeGroup,
    )!;
    const draft = [{ lat: 37.6, lng: 127 }, { lat: 37.6, lng: 127.01 }, { lat: 37.61, lng: 127.01 }];
    act(() => {
      map.fire("draw:editstart", { handler: "edit" });
      group.clearLayers();
      group.addLayer(makeLayer(draft));
    });
    rendered.rerender(createElement(DrawControl, {
      value: A.map((vertex) => ({ ...vertex })), onChange, onPointerPending, onRejectedChange,
    }));
    expect((group.getLayers()[0] as ReturnType<typeof makeLayer>).getLatLngs()[0]).toEqual(draft);
    expect(onChange).not.toHaveBeenCalled();
    expect(onPointerPending).toHaveBeenLastCalledWith(expect.objectContaining({ blocked: true }));
  });

  it("편집 중 외부 범위가 바뀌면 편집 B와 새 반영 C를 섞지 않는다", () => {
    const { map, onChange, onPointerPending, onRejectedChange, rendered } = setup(A);
    const group = (map.addedLayers as InstanceType<typeof holder.FakeGroup>[]).find(
      (layer) => layer instanceof holder.FakeGroup,
    )!;
    const draft = [{ lat: 37.6, lng: 127 }, { lat: 37.6, lng: 127.01 }, { lat: 37.61, lng: 127.01 }];
    const changed = [{ latDeg: 38, lonDeg: 128 }, { latDeg: 38, lonDeg: 128.01 }, { latDeg: 38.01, lonDeg: 128.01 }];
    act(() => {
      map.fire("draw:editstart", { handler: "edit" });
      group.clearLayers();
      group.addLayer(makeLayer(draft));
    });
    rendered.rerender(createElement(DrawControl, { value: changed, onChange, onPointerPending, onRejectedChange }));
    expect((group.getLayers()[0] as ReturnType<typeof makeLayer>).getLatLngs()[0]).toEqual(draft);
    act(() => {
      map.fire("draw:edited", { layers: [] });
      map.fire("draw:editstop", { handler: "edit" });
    });
    expect(onChange).not.toHaveBeenCalled();
    expect(onRejectedChange).toHaveBeenCalledWith({
      vertices: draft.map(({ lat, lng }) => ({ latDeg: lat, lonDeg: lng })),
      reason: expect.stringMatching(/편집 중.*바뀌어/),
    });
    expect(group.getLayers()).toHaveLength(1);
    expect((group.getLayers()[0] as ReturnType<typeof makeLayer>).getLatLngs()[0]).toEqual(
      changed.map((v) => ({ lat: v.latDeg, lng: v.lonDeg })),
    );
  });

  it("삭제 취소 중 외부 범위가 바뀌면 옛 A와 새 C를 중복 표시하지 않는다", () => {
    const { map, onChange, onPointerPending, onRejectedChange, rendered } = setup(A);
    const group = (map.addedLayers as InstanceType<typeof holder.FakeGroup>[]).find(
      (layer) => layer instanceof holder.FakeGroup,
    )!;
    const changed = [{ latDeg: 38, lonDeg: 128 }, { latDeg: 38, lonDeg: 128.01 }, { latDeg: 38.01, lonDeg: 128.01 }];
    act(() => {
      map.fire("draw:deletestart", { handler: "remove" });
      group.clearLayers();
    });
    rendered.rerender(createElement(DrawControl, { value: changed, onChange, onPointerPending, onRejectedChange }));
    expect(group.getLayers()).toHaveLength(0);
    act(() => {
      // Leaflet의 삭제 취소가 옛 A를 되돌린 뒤 stop을 발생시키는 순서.
      group.addLayer(makeLayer(A.map((v) => ({ lat: v.latDeg, lng: v.lonDeg }))));
      map.fire("draw:deletestop", { handler: "remove" });
    });
    expect(onChange).not.toHaveBeenCalled();
    expect(group.getLayers()).toHaveLength(1);
    expect((group.getLayers()[0] as ReturnType<typeof makeLayer>).getLatLngs()[0]).toEqual(
      changed.map((v) => ({ lat: v.latDeg, lng: v.lonDeg })),
    );
  });

  it("leaflet-draw 실제 결속 — 심볼이 설치된 패키지의 문자열과 같다", () => {
    const dist = fs.readFileSync(
      path.resolve(process.cwd(), "node_modules/leaflet-draw/dist/leaflet.draw-src.js"),
      "utf8",
    );
    for (const [symbol, literal] of [
      ["DRAWSTART", "draw:drawstart"],
      ["DRAWSTOP", "draw:drawstop"],
      ["EDITSTART", "draw:editstart"],
      ["EDITSTOP", "draw:editstop"],
      ["DELETESTART", "draw:deletestart"],
      ["DELETESTOP", "draw:deletestop"],
    ]) {
      expect(dist).toContain(`L.Draw.Event.${symbol} = '${literal}'`);
    }
  });

  it("그리기 시작→정지로 막힘·해제를 알린다", () => {
    const { map, onPointerPending, onChange } = setup([]);
    map.fire("draw:drawstart", { layerType: "polygon" });
    expect(onPointerPending).toHaveBeenLastCalledWith(
      expect.objectContaining({ blocked: true, reason: expect.stringMatching(/그리는 중/) }),
    );
    map.fire("draw:drawstop", { layerType: "polygon" });
    expect(onPointerPending).toHaveBeenLastCalledWith({ blocked: false, reason: null });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("편집·삭제 시작→정지로 막힘·해제를 알린다", () => {
    const { map, onPointerPending } = setup(A);
    map.fire("draw:editstart", { handler: "edit" });
    expect(onPointerPending).toHaveBeenLastCalledWith(
      expect.objectContaining({ blocked: true, reason: expect.stringMatching(/편집하는 중/) }),
    );
    map.fire("draw:editstop", { handler: "edit" });
    expect(onPointerPending).toHaveBeenLastCalledWith({ blocked: false, reason: null });
    map.fire("draw:deletestart", { handler: "remove" });
    expect(onPointerPending).toHaveBeenLastCalledWith(
      expect.objectContaining({ blocked: true, reason: expect.stringMatching(/삭제하는 중/) }),
    );
    map.fire("draw:deletestop", { handler: "remove" });
    expect(onPointerPending).toHaveBeenLastCalledWith({ blocked: false, reason: null });
  });

  it("완료(CREATED)는 상한 안에서 그대로 전달하고 자르지 않는다", () => {
    const { map, onChange } = setup([]);
    const points = circlePoints(4);
    map.fire("draw:created", { layer: makeLayer(points), layerType: "polygon" });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(points.map((p) => ({ latDeg: p.lat, lonDeg: p.lng })));
    expect(holder.popupContents).toHaveLength(0);
  });

  it("음수 좌표 도형도 부호를 살려 전달한다 (sign 비트 회귀)", () => {
    const { map, onChange } = setup([]);
    const points = [
      { lat: -1, lng: -1 },
      { lat: -1, lng: 1 },
      { lat: 1, lng: 1 },
      { lat: 1, lng: -1 },
    ];
    map.fire("draw:created", { layer: makeLayer(points), layerType: "polygon" });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(points.map((p) => ({ latDeg: p.lat, lonDeg: p.lng })));
    const reversed = [...points].reverse();
    map.fire("draw:created", { layer: makeLayer(reversed), layerType: "polygon" });
    expect(onChange).toHaveBeenCalledTimes(2);
    expect(onChange).toHaveBeenLastCalledWith(
      reversed.map((p) => ({ latDeg: p.lat, lonDeg: p.lng })),
    );
  });

  it("포인터 정확 퇴화·정확 중복도 보내지 않고 복원·명시한다 (키보드와 공통 경계)", () => {
    const { map, onChange } = setup(A);
    // 정수 완전 직선: 제출 double에서도 정확히 0이다. 포인터에는 입력
    // 문자열이 없어 십진 의도를 확정할 수 없으므로 판단 보류로 막는다.
    map.fire("draw:created", {
      layer: makeLayer([
        { lat: 0, lng: 0 },
        { lat: 1, lng: 1 },
        { lat: 2, lng: 2 },
      ]),
      layerType: "polygon",
    });
    expect(onChange).not.toHaveBeenCalled();
    expect(holder.popupContents).toHaveLength(1);
    expect(holder.popupContents[0]).toMatch(/판단하지 못했습니다/);
    // 포인터에는 십진 원문이 없으므로 엇갈림이 아니라 원문 부재가 근거다.
    expect(holder.popupContents[0]).toMatch(/십진 원문/);
    expect(holder.popupContents[0]).not.toMatch(/엇갈립니다/);
    // 정확 중복도 같은 경계로 막는다.
    map.fire("draw:created", {
      layer: makeLayer([
        { lat: 0, lng: 0 },
        { lat: 1, lng: 0 },
        { lat: 1, lng: 0 },
        { lat: 0, lng: 1 },
      ]),
      layerType: "polygon",
    });
    expect(onChange).not.toHaveBeenCalled();
    expect(holder.popupContents).toHaveLength(2);
    expect(holder.popupContents[1]).toMatch(/같은 점/);
  });

  it("월드 복사로 범위를 벗어난 포인터 입력은 감싸지 않고 막는다", () => {
    const { map, onChange, onRejectedChange } = setup(A);
    // 경도 181/182 — Leaflet 월드 복사 이동이 만들 수 있는 값. Core 계약과
    // 같은 -180..180을 강제하되, 클램프·감쌈 없이 기존값을 복원하고 원본을 보존한다.
    act(() => {
      map.fire("draw:created", {
        layer: makeLayer([
          { lat: 37.5, lng: 181 },
          { lat: 37.5, lng: 182 },
          { lat: 37.51, lng: 182 },
        ]),
        layerType: "polygon",
      });
    });
    expect(onChange).not.toHaveBeenCalled();
    expect(holder.popupContents).toHaveLength(1);
    expect(holder.popupContents[0]).toMatch(/벗어났습니다/);
    expect(holder.popupContents[0]).toMatch(/-180/);
    // 거부된 좌표 원본이 그대로 전달된다 — 조용히 버리지 않는다.
    expect(onRejectedChange).toHaveBeenCalledTimes(1);
    expect(onRejectedChange.mock.calls[0]![0]).toEqual({
      vertices: [
        { latDeg: 37.5, lonDeg: 181 },
        { latDeg: 37.5, lonDeg: 182 },
        { latDeg: 37.51, lonDeg: 182 },
      ],
      reason: expect.stringMatching(/범위/),
    });
  });

  it("날짜변경선을 가로지르는 포인터 입력도 표시 한계로 막고 보존한다", () => {
    const { map, onChange, onRejectedChange } = setup(A);
    act(() => {
      map.fire("draw:created", {
        layer: makeLayer([
          { lat: 0, lng: 179 },
          { lat: 0, lng: -179 },
          { lat: 1, lng: 0 },
        ]),
        layerType: "polygon",
      });
    });
    expect(onChange).not.toHaveBeenCalled();
    expect(holder.popupContents).toHaveLength(1);
    expect(holder.popupContents[0]).toMatch(/판단하지 못했습니다/);
    expect(holder.popupContents[0]).toMatch(/날짜변경선/);
    expect(onRejectedChange).toHaveBeenCalledTimes(1);
    expect(onRejectedChange.mock.calls[0]![0]).toEqual({
      vertices: [
        { latDeg: 0, lonDeg: 179 },
        { latDeg: 0, lonDeg: -179 },
        { latDeg: 1, lonDeg: 0 },
      ],
      reason: expect.stringMatching(/날짜변경선/),
    });
  });

  it("상한 초과 CREATED는 보내지 않고 기존 반영값을 복원·명시한다", () => {
    const { map, onChange } = setup(A);
    // 마운트 시 A가 그룹에 올라가 있다 — 초과 도형이 그려져도 A로 돌아온다.
    map.fire("draw:created", { layer: makeLayer(circlePoints(257)), layerType: "polygon" });
    expect(onChange).not.toHaveBeenCalled();
    expect(holder.popupContents).toHaveLength(1);
    expect(holder.popupContents[0]).toMatch(/257개/);
    expect(holder.popupContents[0]).toMatch(/상한 256개/);
    expect(holder.popupContents[0]).toMatch(/그대로 유지/);
  });

  it("상한 초과 EDITED도 보내지 않고 기존 반영값으로 복원한다", () => {
    const { map, onChange } = setup(A);
    // 편집 저장은 그룹의 마지막 레이어를 읽는다 — 257점 레이어로 교체한 뒤
    // 저장 이벤트를 쏴 실제 경로(편집 저장 → emit)를 재현한다.
    const group = (map.addedLayers as InstanceType<typeof holder.FakeGroup>[]).find(
      (l) => l instanceof holder.FakeGroup,
    )!;
    expect(group).toBeTruthy();
    group.clearLayers();
    group.addLayer(makeLayer(circlePoints(257)));
    map.fire("draw:edited", { layers: [] });
    expect(onChange).not.toHaveBeenCalled();
    expect(holder.popupContents).toHaveLength(1);
    expect(holder.popupContents[0]).toMatch(/257개/);
    // 그룹은 커밋값 A로 복원됐다.
    const restored = group.getLayers();
    expect(restored).toHaveLength(1);
    expect((restored[0] as ReturnType<typeof makeLayer>).getLatLngs()[0]).toEqual(
      A.map((v) => ({ lat: v.latDeg, lng: v.lonDeg })),
    );
  });

  it("삭제 완료(DELETED)는 빈 값을 보낸다", () => {
    const { map, onChange } = setup(A);
    // 삭제 저장은 비어 있는 그룹을 읽는다.
    const group = (map.addedLayers as InstanceType<typeof holder.FakeGroup>[]).find(
      (l) => l instanceof holder.FakeGroup,
    )!;
    group.clearLayers();
    map.fire("draw:deleted", { layers: [] });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it("청소 시점에 막힘을 남기지 않고 리스너를 뗀다", () => {
    const { map, onPointerPending, rendered } = setup([]);
    map.fire("draw:drawstart", { layerType: "polygon" });
    expect(onPointerPending).toHaveBeenLastCalledWith(expect.objectContaining({ blocked: true }));
    rendered.unmount();
    expect(onPointerPending).toHaveBeenLastCalledWith({ blocked: false, reason: null });
    for (const name of [
      "draw:created",
      "draw:edited",
      "draw:deleted",
      "draw:drawstart",
      "draw:drawstop",
      "draw:editstart",
      "draw:editstop",
      "draw:deletestart",
      "draw:deletestop",
    ]) {
      expect(map.listeners.get(name)?.size ?? 0).toBe(0);
    }
  });
});

describe("AoiKeyboardEditor 실제 입력 이벤트 (행위)", () => {
  function renderEditor(value: { latDeg: number; lonDeg: number }[]) {
    const onChange = vi.fn();
    const onPendingChange = vi.fn();
    const rendered = render(
      createElement(AoiKeyboardEditor, { value, onChange, onPendingChange }),
    );
    return { onChange, onPendingChange, rendered };
  }

  function addRows(count: number) {
    const add = screen.getByRole("button", { name: "꼭짓점 추가" });
    for (let i = 0; i < count; i++) fireEvent.click(add);
  }

  function fillRow(index: number, lat: string, lon: string) {
    fireEvent.change(screen.getAllByPlaceholderText("-90 ~ 90")[index]!, {
      target: { value: lat },
    });
    fireEvent.change(screen.getAllByPlaceholderText("-180 ~ 180")[index]!, {
      target: { value: lon },
    });
  }

  function commit() {
    fireEvent.click(screen.getByRole("button", { name: "지도에 반영" }));
  }

  it("십진 표기 차이(+37.5/37.5000/1e-3)는 반영 뒤 미반영으로 잠그지 않는다", () => {
    const { onChange, onPendingChange, rendered } = renderEditor([]);
    addRows(3);
    fillRow(0, "+37.5", "127");
    fillRow(1, "37.5000", "127.01");
    fillRow(2, "37.52", "1.27e2");
    // 타이핑 중에는 미반영으로 막힌다.
    expect(onPendingChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ blocked: true }),
    );
    commit();
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith([
      { latDeg: 37.5, lonDeg: 127 },
      { latDeg: 37.5, lonDeg: 127.01 },
      { latDeg: 37.52, lonDeg: 127 },
    ]);
    // 부모가 커밋값을 반영하면 수치상 clean이므로 막힘이 풀린다 —
    // 문자열 표기 차이로 영원히 잠그지 않는다.
    const committed = onChange.mock.calls[0]![0] as { latDeg: number; lonDeg: number }[];
    rendered.rerender(
      createElement(AoiKeyboardEditor, { value: committed, onChange, onPendingChange }),
    );
    expect(onPendingChange).toHaveBeenLastCalledWith({ blocked: false, reason: null });
  });

  it("판단 보류 입력은 반영하지 않고 이유를 밝힌다", () => {
    const { onChange } = renderEditor([]);
    addRows(3);
    fillRow(0, "37.5665", "126.978");
    fillRow(1, "37.5666", "126.979");
    fillRow(2, "37.5667", "126.98");
    commit();
    expect(onChange).not.toHaveBeenCalled();
    const alert = screen.getByTestId("keyboard-uncertain");
    expect(alert.textContent).toMatch(/판단하지 못했습니다/);
    expect(alert.textContent).not.toMatch(/교차/);
  });

  it("변환으로 달라지는 입력은 기존 값이 없어도 반영하지 않는다", () => {
    const { onChange, onPendingChange } = renderEditor([]);
    addRows(3);
    // 제출 double과 같은 값이지만 십진 표기가 다른 입력.
    fillRow(0, "37.50000000000000000000000000001", "127");
    fillRow(1, "37.5", "127.01");
    fillRow(2, "37.51", "127.01");
    commit();
    expect(onChange).not.toHaveBeenCalled();
    expect(onPendingChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ blocked: true }),
    );
    expect(screen.getByTestId("keyboard-uncertain").textContent).toMatch(/제출 좌표/);
  });

  it("십진 원문과 변환값이 다르면 기존 A를 변환된 B로 바꾸지 않는다", () => {
    const { onChange, onPendingChange } = renderEditor(A);
    fillRow(0, "37.60000000000000000000000000001", "127");
    commit();
    expect(onChange).not.toHaveBeenCalled();
    expect(onPendingChange).toHaveBeenLastCalledWith(expect.objectContaining({ blocked: true }));
    expect((screen.getAllByPlaceholderText("-90 ~ 90")[0] as HTMLInputElement).value).toBe(
      "37.60000000000000000000000000001",
    );
    expect(screen.getByTestId("keyboard-uncertain").textContent).toMatch(/제출 좌표/);
  });
});

describe("AoiPolygonMapInner 거부 보존 (행위)", () => {
  const B_TRI = [
    { latDeg: 37.6, lonDeg: 127.1 },
    { latDeg: 37.6, lonDeg: 127.11 },
    { latDeg: 37.61, lonDeg: 127.11 },
  ];

  function renderInner(value: { latDeg: number; lonDeg: number }[]) {
    holder.map = makeMap() as unknown as typeof holder.map;
    const onChange = vi.fn();
    const onPendingChange = vi.fn();
    const rendered = render(
      createElement(AoiPolygonMapInner, { value, onChange, onPendingChange }),
    );
    return { map: holder.map!, onChange, onPendingChange, rendered };
  }

  function latLngsOf(points: { lat: number; lng: number }[]) {
    return makeLayer(points.map((p) => ({ lat: p.lat, lng: p.lng })));
  }

  it("거부된 B는 원본 좌표와 함께 보존되고 제출이 막힌다", () => {
    const { map, onChange, onPendingChange } = renderInner(A);
    // 자가교차 bow-tie 그리기 → 거부된다.
    act(() => {
      map.fire("draw:created", {
        layer: latLngsOf([
          { lat: 0, lng: 0 },
          { lat: 1, lng: 1 },
          { lat: 0, lng: 1 },
          { lat: 1, lng: 0 },
        ]),
        layerType: "polygon",
      });
    });
    expect(onChange).not.toHaveBeenCalled();
    // 부모 차단은 막힘 + 사유로 전달된다.
    const lastPending = onPendingChange.mock.calls[onPendingChange.mock.calls.length - 1]![0] as {
      blocked: boolean;
      reason: string | null;
    };
    expect(lastPending.blocked).toBe(true);
    expect(lastPending.reason).toMatch(/교차/);
    // 원본 좌표가 그대로 보인다.
    const notice = screen.getByTestId("map-rejected-draw");
    expect(notice.textContent).toMatch(/0/);
    expect(notice.textContent).toMatch(/1/);
    // 명시적 버리기로 해소된다.
    fireEvent.click(screen.getByTestId("map-reject-discard"));
    expect(screen.queryByTestId("map-rejected-draw")).toBeNull();
  });

  it("두 번 연속 거부된 그리기는 앞의 원본도 지우지 않는다", () => {
    const { map, onChange, onPendingChange } = renderInner(A);
    act(() => {
      map.fire("draw:created", {
        layer: latLngsOf([{ lat: 0, lng: 0 }, { lat: 1, lng: 1 }, { lat: 0, lng: 1 }, { lat: 1, lng: 0 }]),
        layerType: "polygon",
      });
      map.fire("draw:created", {
        layer: latLngsOf([{ lat: 2, lng: 2 }, { lat: 3, lng: 3 }, { lat: 2, lng: 3 }, { lat: 3, lng: 2 }]),
        layerType: "polygon",
      });
    });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByTestId("map-rejected-draw").textContent).toMatch(/위도 0, 경도 0/);
    expect(screen.getByTestId("map-rejected-draw").textContent).toMatch(/위도 2, 경도 2/);
    expect(onPendingChange).toHaveBeenLastCalledWith(expect.objectContaining({ blocked: true }));
  });

  it("포인터·거부된 원본·키보드 미반영이 겹쳐도 각각 해소되기 전까지 제출을 막는다", () => {
    const { map, onPendingChange } = renderInner(A);
    act(() => {
      map.fire("draw:created", {
        layer: latLngsOf([{ lat: 0, lng: 0 }, { lat: 1, lng: 1 }, { lat: 0, lng: 1 }, { lat: 1, lng: 0 }]),
        layerType: "polygon",
      });
    });
    fireEvent.change(screen.getAllByPlaceholderText("-90 ~ 90")[0]!, { target: { value: "37.6" } });
    act(() => map.fire("draw:drawstart", { layerType: "polygon" }));
    expect(onPendingChange).toHaveBeenLastCalledWith(expect.objectContaining({ blocked: true, reason: expect.stringMatching(/그리는 중/) }));
    expect((screen.getAllByPlaceholderText("-90 ~ 90")[0]!.closest("fieldset") as HTMLFieldSetElement).disabled).toBe(true);
    act(() => map.fire("draw:drawstop", { layerType: "polygon" }));
    expect(onPendingChange).toHaveBeenLastCalledWith(expect.objectContaining({ blocked: true, reason: expect.stringMatching(/교차/) }));
    fireEvent.click(screen.getByTestId("map-reject-discard"));
    expect(onPendingChange).toHaveBeenLastCalledWith(expect.objectContaining({ blocked: true, reason: expect.stringMatching(/반영하지 않았습니다/) }));
    fireEvent.click(screen.getByRole("button", { name: "현재 지도 값 불러오기" }));
    expect(onPendingChange).toHaveBeenLastCalledWith({ blocked: false, reason: null });
  });

  it("유효한 다시 그리기가 들어오면 거부 기록은 해소된다", () => {
    const { map, onChange } = renderInner(A);
    act(() => {
      map.fire("draw:created", {
        layer: latLngsOf([
          { lat: 0, lng: 0 },
          { lat: 1, lng: 1 },
          { lat: 0, lng: 1 },
          { lat: 1, lng: 0 },
        ]),
        layerType: "polygon",
      });
    });
    expect(screen.getByTestId("map-rejected-draw")).toBeTruthy();
    act(() => {
      map.fire("draw:created", {
        layer: latLngsOf(B_TRI.map((v) => ({ lat: v.latDeg, lng: v.lonDeg }))),
        layerType: "polygon",
      });
    });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(B_TRI);
    expect(screen.queryByTestId("map-rejected-draw")).toBeNull();
  });

  it("키보드 반영은 거부 기록을 해소하고 값을 보낸다", () => {
    const { map, onChange } = renderInner([]);
    // 먼저 거부된 그리기를 만든다.
    act(() => {
      map.fire("draw:created", {
        layer: latLngsOf([
          { lat: 0, lng: 0 },
          { lat: 1, lng: 1 },
          { lat: 0, lng: 1 },
          { lat: 1, lng: 0 },
        ]),
        layerType: "polygon",
      });
    });
    expect(screen.getByTestId("map-rejected-draw")).toBeTruthy();
    // 유효한 키보드 반영은 값을 보내고 거부 기록을 해소한다.
    const add = screen.getByRole("button", { name: "꼭짓점 추가" });
    fireEvent.click(add);
    fireEvent.click(add);
    fireEvent.click(add);
    const lats = screen.getAllByPlaceholderText("-90 ~ 90");
    const lons = screen.getAllByPlaceholderText("-180 ~ 180");
    fireEvent.change(lats[0]!, { target: { value: "37.5" } });
    fireEvent.change(lons[0]!, { target: { value: "127" } });
    fireEvent.change(lats[1]!, { target: { value: "37.5" } });
    fireEvent.change(lons[1]!, { target: { value: "127.01" } });
    fireEvent.change(lats[2]!, { target: { value: "37.51" } });
    fireEvent.change(lons[2]!, { target: { value: "127.01" } });
    fireEvent.click(screen.getByRole("button", { name: "지도에 반영" }));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(A);
    expect(screen.queryByTestId("map-rejected-draw")).toBeNull();
  });
});

describe("선택적 지도 원문 스냅샷", () => {
  it("키보드 빈칸과 원문을 이동 뒤 되살리되 자동 반영하지 않는다", () => {
    const onChange = vi.fn();
    const onSnapshotChange = vi.fn();
    holder.map = makeMap();
    const first = render(createElement(AoiPolygonMapInner, { value: [], onChange, onSnapshotChange } as never));
    fireEvent.click(screen.getByRole("button", { name: "꼭짓점 추가" }));
    fireEvent.change(screen.getAllByPlaceholderText("-90 ~ 90")[0]!, { target: { value: "+37.5000" } });
    const snapshot = onSnapshotChange.mock.lastCall?.[0];
    expect(snapshot.rows).toEqual([{ lat: "+37.5000", lon: "" }]);
    first.unmount();
    const pending = vi.fn();
    render(createElement(AoiPolygonMapInner, { value: [], onChange, onPendingChange: pending, initialSnapshot: snapshot } as never));
    expect((screen.getAllByPlaceholderText("-90 ~ 90")[0] as HTMLInputElement).value).toBe("+37.5000");
    expect((screen.getAllByPlaceholderText("-180 ~ 180")[0] as HTMLInputElement).value).toBe("");
    expect(pending).toHaveBeenLastCalledWith(expect.objectContaining({ blocked: true }));
    expect(onChange).not.toHaveBeenCalled();
  });
  it("연속 거부 원본도 리마운트 후 모두 남고 등록 차단을 알린다", () => {
    holder.map = makeMap();
    const onChange = vi.fn();
    const onSnapshotChange = vi.fn();
    const first = render(createElement(AoiPolygonMapInner, { value: [], onChange, onSnapshotChange } as never));
    act(() => {
      for (const n of [0, 2]) holder.map!.fire("draw:created", {
        layer: makeLayer([{ lat: n, lng: n }, { lat: n + 1, lng: n + 1 }, { lat: n, lng: n + 1 }, { lat: n + 1, lng: n }]),
        layerType: "polygon",
      });
    });
    const snapshot = onSnapshotChange.mock.lastCall?.[0];
    expect(snapshot.rejectedDraws).toHaveLength(2);
    first.unmount();
    holder.map = makeMap();
    const pending = vi.fn();
    render(createElement(AoiPolygonMapInner, { value: [], onChange, onPendingChange: pending, initialSnapshot: snapshot } as never));
    expect(screen.getByTestId("map-rejected-draw").textContent).toMatch(/위도 0, 경도 0/);
    expect(screen.getByTestId("map-rejected-draw").textContent).toMatch(/위도 2, 경도 2/);
    expect(pending).toHaveBeenLastCalledWith(expect.objectContaining({ blocked: true }));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("마지막 타이핑 이벤트 안에서 최신 원문을 전달한다", () => {
    holder.map = makeMap();
    const onSnapshotChange = vi.fn();
    render(createElement(AoiPolygonMapInner, { value: [], onChange: vi.fn(), onSnapshotChange }));
    fireEvent.click(screen.getByRole("button", { name: "꼭짓점 추가" }));
    act(() => {
      fireEvent.change(screen.getAllByPlaceholderText("-90 ~ 90")[0]!, { target: { value: "  +37.5000 " } });
      expect(onSnapshotChange.mock.lastCall?.[0].rows).toEqual([{ lat: "  +37.5000 ", lon: "" }]);
    });
  });

  it("연속 거부 이벤트는 렌더 전에 모든 원본을 전달한다", () => {
    holder.map = makeMap();
    const onSnapshotChange = vi.fn();
    render(createElement(AoiPolygonMapInner, { value: [], onChange: vi.fn(), onSnapshotChange }));
    act(() => {
      for (const n of [0, 2]) holder.map!.fire("draw:created", {
        layer: makeLayer([{ lat: n, lng: n }, { lat: n + 1, lng: n + 1 }, { lat: n, lng: n + 1 }, { lat: n + 1, lng: n }]),
        layerType: "polygon",
      });
      expect(onSnapshotChange.mock.lastCall?.[0].rejectedDraws).toHaveLength(2);
    });
  });

});
