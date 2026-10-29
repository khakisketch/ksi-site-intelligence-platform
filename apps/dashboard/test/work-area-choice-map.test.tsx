// @vitest-environment jsdom
import { Suspense } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/map/WorkAreaChoiceMapInner", () => ({
  WorkAreaChoiceMapInner: ({ shapes }: { shapes: { id: string }[] }) =>
    <div data-testid="map-inner" data-count={shapes.length} />,
}));

import { WorkAreaChoiceMap } from "@/components/map/WorkAreaChoiceMap";
import type { WorkArea } from "@/lib/core-api/types";

const polygon = { type: "Polygon", coordinates: [[
  [127.0, 37.0], [127.1, 37.0], [127.1, 37.1], [127.0, 37.0],
]] };
const holed = { type: "Polygon", coordinates: [
  [[127.0, 37.0], [127.1, 37.0], [127.1, 37.1], [127.0, 37.0]],
  [[127.0, 37.0], [127.1, 37.0], [127.1, 37.1], [127.0, 37.0]],
] };

function makeArea(workAreaId: string, name: string, polygon: Record<string, unknown>, crs: string): WorkArea {
  return { schemaVersion: "v1", workAreaId, siteId: "site-a", name, polygon, crs,
    status: "ACTIVE", supersedes: null, createdAt: "2026-10-27T00:00:00Z" };
}

function renderMap(areas: WorkArea[]) {
  return render(
    <Suspense fallback={<div>지도 불러오는 중</div>}>
      <WorkAreaChoiceMap areas={areas} selectedId="" onSelect={() => {}} disabled={false} />
    </Suspense>,
  );
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("WorkAreaChoiceMap omission note", () => {
  it("shows exact non-CRS reasons even when nothing is drawable", async () => {
    renderMap([makeArea("area-hole", "구멍 구역", holed, "EPSG:4326")]);
    const note = await screen.findByRole("note");
    expect(note.textContent).toContain("지도에 표시되지 않은 구역 1개");
    expect(note.textContent).toContain("구멍 구역");
    expect(note.textContent).not.toContain("좌표계");
  });
  it("shows the note for mixed drawable and omitted areas", async () => {
    renderMap([
      makeArea("area-ok", "동측 구역", polygon, "EPSG:4326"),
      makeArea("area-crs", "서측 구역", polygon, "EPSG:9999"),
    ]);
    await screen.findByTestId("map-inner");
    const note = await screen.findByRole("note");
    expect(note.textContent).toContain("서측 구역");
  });
  it("shows no note when every area is drawable", async () => {
    renderMap([makeArea("area-ok", "동측 구역", polygon, "EPSG:4326")]);
    await screen.findByTestId("map-inner");
    expect(screen.queryByRole("note")).toBeNull();
  });
});
