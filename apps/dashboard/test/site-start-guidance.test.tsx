/** @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SiteStartGuidance } from "@/app/sites/[siteId]/SiteStartGuidance";

afterEach(cleanup);

describe("SiteStartGuidance", () => {
  it("uses the bounded records honestly and points to read-only analysis", () => {
    render(<SiteStartGuidance
      siteId="site-1"
      workAreaCount={2}
      observationWorkOrderCount={1}
      externalResultCount={50}
      hasMoreExternalResults
    />);

    const guide = within(screen.getByRole("region", { name: "현장 시작 안내" }));
    expect(guide.getByText("2개 목록됨")).toBeTruthy();
    expect(guide.getByText("1개 목록됨")).toBeTruthy();
    expect(guide.getByText("최근 페이지 50개 · 더 있음")).toBeTruthy();
    expect(guide.getByRole("link", { name: "분석 후보와 상태 확인" }).getAttribute("href")).toBe("/sites/site-1/analysis");
    expect(guide.queryByRole("button")).toBeNull();
    expect(guide.queryByText(/분석 준비 완료|정량 사용 가능/)).toBeNull();
  });

  it("distinguishes unknown queries from real empty lists", () => {
    render(<SiteStartGuidance
      siteId="site-1"
      workAreaCount={null}
      observationWorkOrderCount={0}
      externalResultCount={null}
      hasMoreExternalResults={null}
    />);

    const guide = within(screen.getByRole("region", { name: "현장 시작 안내" }));
    expect(guide.getAllByText("확인 불가")).toHaveLength(2);
    expect(guide.getByText("0개 목록됨")).toBeTruthy();
    expect(guide.getByText(/작업구역 목록을 확인할 수 없습니다/)).toBeTruthy();
    expect(guide.getByRole("link", { name: "공간 자산 현황 보기" }).getAttribute("href")).toBe("/sites/site-1?section=spatial-assets");
    expect(guide.queryByRole("link", { name: /등록|생성|새 관측/ })).toBeNull();
  });

  it("does not imply a complete result history when continuation state is unknown", () => {
    render(<SiteStartGuidance
      siteId="site-1"
      workAreaCount={1}
      observationWorkOrderCount={1}
      externalResultCount={3}
      hasMoreExternalResults={null}
    />);

    expect(screen.getByText("3개 표시됨 · 이어서 조회 여부 확인 불가")).toBeTruthy();
  });
});
