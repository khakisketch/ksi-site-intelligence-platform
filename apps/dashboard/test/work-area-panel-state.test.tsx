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
    // SSR 시점에는 live identity 확인 전이므로 편집 UI를 노출하지 않고 목록만 둔다.
    expect(html).toContain("현재 계정과 임시 저장 내용을 확인하고 있습니다.");
    expect(html).toContain("hidden");
    expect(html).toContain("아직 등록된 작업구역이 없습니다");
  });

  it("keeps the list visible while the edit form stays gated before identity check", () => {
    const html = renderToStaticMarkup(
      <WorkAreaPanel
        {...common}
        canWrite
        initialWorkAreas={[]}
        workAreaListError={null}
        accountIdentity={{ fingerprint: `v1-${"a".repeat(64)}` }}
      />,
    );
    // 서버 prop이 있어도 SSR에서는 live GET 전이라 폼이 hidden 경계 안에 있다.
    expect(html).toContain("현재 계정과 임시 저장 내용을 확인하고 있습니다.");
    expect(html).toContain("hidden");
    // 목록(빈 안내)은 가리지 않는다.
    expect(html).toContain("아직 등록된 작업구역이 없습니다. 위 지도에서 이름과 범위를 정해 등록하세요.");
  });
});

describe("WorkAreaPanel mobile handoff", () => {
  it("hands off to the same account on a laptop without promising cross-device drafts", () => {
    const html = renderToStaticMarkup(<WorkAreaPanel {...common} canWrite workAreaListError={null} />);
    expect(html).toContain("노트북에서 같은 계정으로 이 현장의 ‘작업구역’ 화면을 열어 이어가세요.");
    expect(html).toContain("작은 화면에서는 아래 목록과 구역 범위 보기로 확인만 할 수 있습니다.");
    expect(html).toContain("입력 중인 내용·임시 기록은 이 탭에만 있어 다른 기기로 이어지지 않습니다.");
    // 식별자 반출 없음 — 안내 문구에 기술 참조·원본 좌표가 실리지 않는다.
    expect(html).not.toContain("workAreaId");
  });

  it("keeps the writer empty state actionable on desktop and honest on mobile", () => {
    const html = renderToStaticMarkup(<WorkAreaPanel {...common} canWrite workAreaListError={null} />);
    expect(html).toContain("아직 등록된 작업구역이 없습니다. 위 지도에서 이름과 범위를 정해 등록하세요.");
    expect(html).toContain("작은 화면에서는 등록 폼이 열리지 않으므로");
  });

  it("does not push laptop continuation to viewers without write permission", () => {
    const html = renderToStaticMarkup(<WorkAreaPanel {...common} canWrite={false} workAreaListError={null} />);
    expect(html).toContain("이 현장에 등록된 작업구역이 없습니다. 현장 담당자에게 구역 등록을 요청하세요.");
    expect(html).not.toContain("노트북에서 같은 계정으로");
  });
});
