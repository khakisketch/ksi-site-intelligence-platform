/** @vitest-environment jsdom */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DataRow } from "@/components/ui/DataRow";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { Panel } from "@/components/ui/Panel";
import { Stat } from "@/components/ui/Stat";
import { StepIndicator } from "@/components/ui/StepIndicator";

afterEach(cleanup);

describe("shared console primitives", () => {
  it("step indicator shows order only unless a current step is given", () => {
    const { rerender } = render(<StepIndicator steps={["작업구역", "파일 제출", "검사 확인"]} label="자료 등록 순서" />);
    const list = screen.getByRole("list", { name: "자료 등록 순서" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(list.querySelector("[aria-current]")).toBeNull();
    expect(list.textContent).not.toContain("지난 단계");

    rerender(<StepIndicator steps={["작업구역", "파일 제출", "검사 확인"]} current={1} label="자료 등록 순서" />);
    const current = screen.getByRole("list").querySelector('[aria-current="step"]');
    expect(current?.textContent).toContain("파일 제출");
    expect(screen.getAllByText("(지난 단계)", { exact: false })).toHaveLength(1);
  });

  it("data row drops empty facts instead of printing placeholders", () => {
    render(<ul><DataRow title="범위 승인" meta={["A 현장", null, "", undefined, false, "1회차"]} status={<span>승인 대기</span>} /></ul>);
    const row = screen.getByRole("listitem");
    expect(row.textContent).toContain("A 현장");
    expect(row.textContent).toContain("1회차");
    expect(row.querySelectorAll("p > span")).toHaveLength(2);
  });

  it("inline notice carries its message and recovery action with a status role", () => {
    render(<InlineNotice action={<a href="#sites">현장 전체 열기</a>}>일부 정보를 확인하지 못했습니다.</InlineNotice>);
    const notice = screen.getByRole("status");
    expect(notice.textContent).toContain("일부 정보를 확인하지 못했습니다.");
    expect(within(notice).getByRole("link", { name: "현장 전체 열기" }).getAttribute("href")).toBe("#sites");
  });

  it("panel exposes its heading at the requested level and stat keeps label/value paired", () => {
    render(<Panel title="분석 이력" headingLevel={3}><dl><Stat label="변화량" value="12.4" unit="m³" /></dl></Panel>);
    expect(screen.getByRole("heading", { level: 3, name: "분석 이력" })).toBeTruthy();
    expect(screen.getByText("변화량").tagName).toBe("DT");
    expect(screen.getByText("12.4").closest("dd")?.textContent).toContain("m³");
  });
});
