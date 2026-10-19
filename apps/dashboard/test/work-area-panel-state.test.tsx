import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/map/AoiPolygonMap", () => ({ AoiPolygonMap: () => createElement("div", null, "map") }));
vi.mock("@/components/ui/StatusBadge", () => ({ StateBadge: ({ label }: { label: string }) => createElement("span", null, label) }));
vi.mock("@/components/ui/ErrorState", () => ({
  ErrorState: ({ message, tone, retryable }: { message: string; tone: string; retryable: boolean }) =>
    createElement("div", { role: "alert", "data-tone": tone, "data-retryable": retryable }, message),
}));
vi.mock("@/components/ui/ToastProvider", () => ({ useToast: () => ({ notify: () => undefined }) }));
vi.mock("@/components/ui/ConfirmDialog", () => ({ ConfirmDialog: () => createElement("div", null, null) }));
vi.mock("@/components/ui/ActionUnavailable", () => ({
  ActionUnavailable: ({ label, description }: { label: string; description: string }) =>
    createElement("div", null, `${label}: ${description}`),
}));

import { WorkAreaPanel } from "@/app/sites/[siteId]/work-areas/WorkAreaPanel";

const common = { siteId: "site-1", siteCrs: "EPSG:4326", initialWorkAreas: [] };

describe("WorkAreaPanel list presentation", () => {
  it("does not show a zero count or true-empty copy when the list is unavailable", () => {
    const html = renderToStaticMarkup(<WorkAreaPanel
      {...common}
      canWrite={false}
      workAreaListError={{ message: "목록을 불러오지 못했습니다.", tone: "crit", retryable: true }}
    />);

    expect(html).toContain("목록을 불러오지 못했습니다.");
    expect(html).toContain("확인할 수 없음");
    expect(html).not.toContain(">0건<");
    expect(html).not.toContain("이 현장에 등록된 작업구역이 없습니다");
  });

  it("offers next-step guidance for a genuinely empty list without write permission", () => {
    const html = renderToStaticMarkup(<WorkAreaPanel {...common} canWrite={false} workAreaListError={null} />);
    expect(html).toContain("이 현장에 등록된 작업구역이 없습니다. 현장 담당자에게 구역 등록을 요청하세요.");
    expect(html).toContain(">0건<");
  });

  it("points a write-enabled operator to the existing registration form", () => {
    const html = renderToStaticMarkup(<WorkAreaPanel {...common} canWrite workAreaListError={null} />);
    expect(html).toContain("아직 등록된 작업구역이 없습니다. 위 지도에서 이름과 범위를 정해 등록하세요.");
  });
});
