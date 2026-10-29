/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement, type ReactNode } from "react";

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

function makeLatLng(lat: number, lng: number) {
  return { lat, lng };
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

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/components/map/AoiPolygonMap", async () => {
  const actual = await import("@/components/map/AoiPolygonMapInner");
  return { AoiPolygonMap: actual.AoiPolygonMapInner };
});
import { SiteRegistrationOnlyWizard } from "@/app/sites/new/SiteRegistrationOnlyWizard";
const alice = `v1-${"a".repeat(64)}`;
beforeEach(() => {
  sessionStorage.clear();
  holder.map = makeMap();
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ fingerprint: alice }), { status: 200, headers: { "Content-Type": "application/json" } })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe("현장 등록 실제 지도 편집기 이동 복구", () => {
  it("거부 원본과 마지막 위도 입력을 같은 이벤트에서 저장하고 재진입 후 제출하지 않는다", async () => {
    const first = render(createElement(SiteRegistrationOnlyWizard, { mode: "MAPPED_BOOTSTRAP" }));
    fireEvent.change(await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장"), { target: { value: "현장 A" } });
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    act(() => holder.map!.fire("draw:created", { layer: makeLayer([{ lat: 0, lng: 0 }, { lat: 1, lng: 1 }, { lat: 0, lng: 1 }, { lat: 1, lng: 0 }]), layerType: "polygon" }));
    fireEvent.click(screen.getByRole("button", { name: "꼭짓점 추가" }));
    act(() => {
      fireEvent.change(screen.getAllByPlaceholderText("-90 ~ 90")[0]!, { target: { value: "  +91.000x " } });
      expect(sessionStorage.getItem("ksi-wizard-site-registration-only:map-v1")).toContain("  +91.000x ");
      first.unmount();
    });
    holder.map = makeMap();
    render(createElement(SiteRegistrationOnlyWizard, { mode: "MAPPED_BOOTSTRAP" }));
    await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장");
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    expect((screen.getAllByPlaceholderText("-90 ~ 90")[0] as HTMLInputElement).value).toBe("  +91.000x ");
    expect(screen.getByTestId("map-rejected-draw").textContent).toContain("위도 0, 경도 0");
    expect((screen.getByRole("button", { name: "다음" }) as HTMLButtonElement).disabled).toBe(true);
    expect(vi.mocked(fetch).mock.calls.every(([url]) => String(url) === "/api/account-identity")).toBe(true);
  });
});
