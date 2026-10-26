/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AnalysisStartGuide } from "@/app/sites/[siteId]/analysis/AnalysisStartGuide";

afterEach(cleanup);

describe("AnalysisStartGuide", () => {
  it("uses current Site records to guide an authorized user without claiming eligibility", () => {
    render(<AnalysisStartGuide
      siteId="site-1"
      workAreaCount={2}
      observationCount={3}
      analysisCount={4}
      hasMoreAnalyses={false}
      canCreate
      compact
    />);

    // 후보·구역이 있으면 접힌 도움말로 둔다 — 내용은 그대로 둔다.
    const summary = screen.getByText("변화 분석 시작 안내");
    expect(summary.closest("details")?.hasAttribute("open")).toBe(false);
    expect(screen.getByText("2개 확인됨")).toBeTruthy();
    expect(screen.getByText("3개 표시됨")).toBeTruthy();
    expect(screen.getByText("4개 표시됨")).toBeTruthy();
    expect(screen.getByRole("link", { name: "변화 분석 요청으로 이동" }).getAttribute("href")).toBe("#new-analysis-request");
    expect(screen.getByText(/등록은 검증이나 정량 사용 가능 판정이 아닙니다/)).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/분석 준비 완료|분석 가능/);
  });

  it("shows read-only next steps and no request action when records or permission are missing", () => {
    render(<AnalysisStartGuide
      siteId="site-1"
      workAreaCount={0}
      observationCount={1}
      analysisCount={0}
      hasMoreAnalyses={false}
      canCreate={false}
    />);

    expect(screen.getByText("등록된 작업구역 없음")).toBeTruthy();
    expect(screen.getByText("1개 표시됨")).toBeTruthy();
    expect(screen.getByRole("link", { name: "작업구역 현황 확인" }).getAttribute("href")).toBe("/sites/site-1/work-areas");
    expect(screen.getByRole("link", { name: "등록 자료·촬영 정보 확인" }).getAttribute("href")).toBe("/sites/site-1/spatial-assets");
    expect(screen.queryByRole("link", { name: "변화 분석 요청으로 이동" })).toBeNull();
    expect(document.body.textContent).not.toContain("SITES_WRITE");
  });

  it("explains absent comparison candidates without saying registered date-only materials are absent", () => {
    render(<AnalysisStartGuide
      siteId="site-1"
      workAreaId="area-1"
      workAreaCount={1}
      observationCount={0}
      analysisCount={0}
      hasMoreAnalyses={false}
      canCreate
    />);
    expect(screen.getByText(/촬영 날짜만 있거나 시각이 미상인 자료는 현재 시점 비교 후보에 포함되지 않습니다/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "등록 자료·촬영 정보 확인" }).getAttribute("href")).toBe("/sites/site-1/spatial-assets?workAreaId=area-1");
    expect(document.body.textContent).not.toContain("등록된 관측 자료가 없습니다");
    expect(screen.queryByRole("link", { name: "변화 분석 요청으로 이동" })).toBeNull();
  });

  it("labels analysis history as a bounded page when older records remain", () => {
    render(<AnalysisStartGuide
      siteId="site-1"
      workAreaCount={1}
      observationCount={2}
      analysisCount={50}
      hasMoreAnalyses
      canCreate
      compact
    />);

    expect(screen.getByText("변화 분석 시작 안내").closest("details")?.hasAttribute("open")).toBe(false);
    expect(screen.getByText("50개 표시됨")).toBeTruthy();
    expect(screen.getByText(/최근 페이지의 일부 기록입니다/)).toBeTruthy();
  });

  it("keeps the full guide when no executable pair can be chosen", () => {
    render(<AnalysisStartGuide
      siteId="site-1"
      workAreaCount={1}
      observationCount={1}
      analysisCount={0}
      hasMoreAnalyses={false}
      canCreate
    />);

    expect(screen.getByRole("heading", { name: "변화 분석 시작 안내" })).toBeTruthy();
    expect(screen.queryByText("변화 분석 시작 안내")?.closest("details")).toBeNull();
  });
});
