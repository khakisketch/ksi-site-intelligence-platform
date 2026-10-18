// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

import { ExternalObservationCreateForm } from "@/app/sites/[siteId]/observations/new/ExternalObservationCreateForm";

afterEach(cleanup);

describe("ExternalObservationCreateForm path selection", () => {
  it("offers one clear workflow without a redundant method choice", () => {
    render(
      <ExternalObservationCreateForm
        siteId="site-1"
        siteName="A 현장"
        workAreas={[{ workAreaId: "area-1", name: "1구역" }]}
      />,
    );
    // Sole workflow heading, not a method-choice card grid.
    expect(screen.getByRole("heading", { name: "A 현장 · 관측 자료 등록" })).toBeTruthy();
    expect(screen.getAllByRole("heading")).toHaveLength(1);
    expect(screen.queryByRole("heading", { name: "외부 산출물 등록" })).toBeNull();
    expect(screen.queryByRole("button", { name: /외부 산출물 등록/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /비행/ })).toBeNull();
    // Next step is explicit: the action stays disabled until scope is complete.
    const submit = screen.getByRole("button", { name: "관측 자료 등록 계속" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect(screen.getByText("작업 이름을 입력하고 비교할 작업구역을 하나 이상 선택하세요.")).toBeTruthy();
    // The preserved comparison record stays a plain navigation link, not a competing action.
    expect(screen.getByRole("link", { name: /외부 비교 기록/ }).getAttribute("href")).toBe("/sites/site-1/observations");
  });

  it("requires a genuine work name and work-area scope with no flight path", () => {
    render(
      <ExternalObservationCreateForm
        siteId="site-1"
        siteName="A 현장"
        workAreas={[{ workAreaId: "area-1", name: "1구역" }]}
      />,
    );
    fireEvent.change(screen.getByLabelText("작업 이름"), { target: { value: "9월 현황 비교" } });
    fireEvent.click(screen.getByLabelText("1구역"));
    expect((screen.getByRole("button", { name: "관측 자료 등록 계속" }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText(/비행을 시작합니다/)).toBeNull();
  });
});
