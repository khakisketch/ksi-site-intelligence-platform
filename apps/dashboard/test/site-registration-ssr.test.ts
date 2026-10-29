/** @vitest-environment node */
import { describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToString } from "react-dom/server";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("@/components/map/AoiPolygonMap", () => ({
  AoiPolygonMap: () => createElement("div", { "data-testid": "mock-map" }),
}));

import { SiteRegistrationOnlyWizard } from "@/app/sites/new/SiteRegistrationOnlyWizard";

describe("현장 등록 SSR 초기 렌더 (hydration 일치)", () => {
  it("서버(저장소 없음) 렌더는 확인 화면이 아니라 입력 단계이며 깨지지 않는다", () => {
    const html = renderToString(
      createElement(SiteRegistrationOnlyWizard, { mode: "LEGACY_SITE_ID", accountFingerprint: null }),
    );
    expect(html).toContain("현장 등록");
    expect(html).not.toContain("현장이 등록되었습니다");
  });

  it("mapped 모드도 서버 렌더가 깨지지 않는다", () => {
    const html = renderToString(
      createElement(SiteRegistrationOnlyWizard, { mode: "MAPPED_BOOTSTRAP", accountFingerprint: "v1-abcd" }),
    );
    expect(html).toContain("현장 등록");
    expect(html).not.toContain("현장이 등록되었습니다");
  });
});
