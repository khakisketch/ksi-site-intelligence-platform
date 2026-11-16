// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/map/WorkAreaChoiceMapInner", () => ({
  WorkAreaChoiceMapInner: ({ shapes }: { shapes: { id: string }[] }) => <div data-testid="map-inner" data-ids={shapes.map((shape) => shape.id).join(",")} />,
}));

import { AreaLocationMap } from "@/app/sites/[siteId]/areas/AreaLocationMap";
import type { WorkArea } from "@/lib/core-api/types";

const area: WorkArea = {
  schemaVersion: "v1", workAreaId: "area-1", siteId: "site-1", name: "1영역", crs: "EPSG:4326", status: "ACTIVE",
  supersedes: null, createdAt: "2026-11-03T00:00:00Z",
  polygon: { type: "Polygon", coordinates: [[[127, 37], [127.01, 37], [127.01, 37.01], [127, 37]]] },
};

afterEach(cleanup);

describe("영역 위치 지도", () => {
  it("접혀 있으면 지도를 불러오지 않고, 펼치면 고른 영역만 올린다", async () => {
    const { container } = render(<AreaLocationMap area={area} defaultOpen={false} />);
    expect(screen.queryByTestId("map-inner")).toBeNull();
    const details = container.querySelector("details")!;
    details.open = true;
    fireEvent(details, new Event("toggle"));
    expect((await screen.findByTestId("map-inner")).getAttribute("data-ids")).toBe("area-1");
    expect(screen.getByText(/자료가 이 자리에 놓인다는 뜻은 아닙니다/)).toBeTruthy();
  });

  it("자료를 보여 주지 못하는 상태에서는 처음부터 펼쳐 둔다", async () => {
    render(<AreaLocationMap area={area} defaultOpen />);
    expect(await screen.findByTestId("map-inner")).toBeTruthy();
  });
});
