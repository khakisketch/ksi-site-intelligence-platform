/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkAreaHistorySelect } from "@/app/sites/[siteId]/spatial-data-requests/WorkAreaHistorySelect";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function HistoryForm() {
  return <form action="/sites/site-1/spatial-data-requests" method="get">
    <label htmlFor="spatial-request-work-area">작업구역 선택</label>
    <WorkAreaHistorySelect value="north">
      <option value="north">북측 절토구역</option>
      <option value="south">남측 성토구역</option>
    </WorkAreaHistorySelect>
    <p id="spatial-request-work-area-help">구역을 바꾸면 요청 이력을 불러옵니다.</p>
    <button type="submit">요청 이력 불러오기</button>
  </form>;
}

describe("WorkAreaHistorySelect", () => {
  it("submits the selected scope through the existing GET form without carrying a prior cursor or request", () => {
    const submit = vi.spyOn(HTMLFormElement.prototype, "requestSubmit").mockImplementation(() => {});
    render(<HistoryForm />);
    fireEvent.change(screen.getByLabelText("작업구역 선택"), { target: { value: "south" } });
    expect(submit).toHaveBeenCalledTimes(1);
    const form = screen.getByRole("button").closest("form")!;
    expect(form.method).toBe("get");
    expect(form.getAttribute("action")).toBe("/sites/site-1/spatial-data-requests");
    expect([...new FormData(form).entries()]).toEqual([["workAreaId", "south"]]);
  });

  it("retains a labelled native select and submit button in server markup for no-JS use", () => {
    const html = renderToStaticMarkup(<HistoryForm />);
    expect(html).toContain('name="workAreaId"');
    expect(html).toContain('value="north" selected=""');
    expect(html).toContain('type="submit">요청 이력 불러오기');
    expect(html).toContain('aria-describedby="spatial-request-work-area-help"');
  });
});
