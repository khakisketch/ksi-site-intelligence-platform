/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ExternalObservationCreateForm } from "@/app/sites/[siteId]/observations/new/ExternalObservationCreateForm";

const push = vi.fn();
const fetchMock = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("crypto", { randomUUID: vi.fn().mockReturnValueOnce("create-1").mockReturnValue("create-2") });
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({ workOrderId: "work-order-1" }) });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe("ExternalObservationCreateForm", () => {
  it("explains why the registration action is disabled and avoids exposing a synthetic work-area id", () => {
    render(<ExternalObservationCreateForm siteId="site-1" siteName="서쪽 현장" workAreas={[{ workAreaId: "wa-generated-1", name: "wa-generated-1" }]} />);

    expect(screen.getByText("작업 이름을 입력하고 비교할 작업구역을 하나 이상 선택하세요.")).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "이름을 확인할 수 없는 작업구역 1" })).toBeTruthy();
    expect(screen.queryByText("wa-generated-1")).toBeNull();
    expect((screen.getByRole("button", { name: "관측 자료 등록 계속" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("creates one external ingress with a stable idempotency key and opens its work detail", async () => {
    render(<ExternalObservationCreateForm siteId="site-1" siteName="서쪽 현장" workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]} />);
    expect(screen.getByRole("heading", { name: "관측 자료 등록" })).toBeTruthy();
    expect(screen.getByText("서쪽 현장")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "외부 산출물 등록" })).toBeNull();
    expect(screen.getByText("등록할 자료의 작업 이름과 범위를 선택하세요.")).toBeTruthy();
    expect(screen.getByRole("list", { name: "자료 등록 흐름" }).querySelector('[aria-current="step"]')?.textContent).toBe("1. 작업구역");
    expect(screen.getByRole("link", { name: "현장으로 돌아가기" }).getAttribute("href")).toBe("/sites/site-1");
    expect(screen.getByLabelText("작업 이름").getAttribute("maxlength")).toBe("200");
    fireEvent.change(screen.getByLabelText("작업 이름"), { target: { value: "9월 6일 현황 비교" } });
    fireEvent.click(screen.getByLabelText("동측 절토면"));
    fireEvent.click(screen.getByRole("button", { name: "관측 자료 등록 계속" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sites/site-1/observation-work-orders",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "Idempotency-Key": "external-create-1" }),
        body: JSON.stringify({
          name: "9월 6일 현황 비교",
          workAreaIds: ["wa-1"],
          scheduleId: null,
          executionMode: "EXTERNAL_RECONSTRUCTION",
        }),
      }),
    );
    expect(push).toHaveBeenCalledWith("/field/work-orders/work-order-1#external-submissions");
  });

  it("shows a repeat name suggestion as an editable value and does not submit it automatically", () => {
    render(<ExternalObservationCreateForm
      siteId="site-1"
      siteName="서쪽 현장"
      workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]}
      initialWorkAreaIds={["wa-1"]}
      suggestedName="1차 관측 · 2회차"
    />);

    const name = screen.getByLabelText("작업 이름") as HTMLInputElement;
    expect(name.value).toBe("1차 관측 · 2회차");
    expect((screen.getByRole("button", { name: "관측 자료 등록 계속" }) as HTMLButtonElement).disabled).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.change(name, { target: { value: "운영자가 바꾼 이름" } });
    expect(name.value).toBe("운영자가 바꾼 이름");
  });

  it("keeps external-result creation separate and gives a recovery link when no work area is available", () => {
    render(<ExternalObservationCreateForm siteId="site-1" siteName="서쪽 현장" workAreas={[]} />);
    expect(screen.getByRole("link", { name: "작업구역 만들기" }).getAttribute("href")).toBe("/sites/site-1/work-areas");
    expect(screen.getByRole("link", { name: /외부 비교 기록/ }).getAttribute("href")).toBe("/sites/site-1/observations");
    expect(screen.queryByRole("button", { name: "관측 자료 등록 계속" })).toBeNull();
  });

  it("does not send a second create while the first response is still unknown", async () => {
    let resolveResponse: ((value: unknown) => void) | undefined;
    fetchMock.mockImplementation(() => new Promise((resolve) => { resolveResponse = resolve; }));
    render(<ExternalObservationCreateForm siteId="site-1" siteName="서쪽 현장" workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]} />);
    fireEvent.change(screen.getByLabelText("작업 이름"), { target: { value: "외부 비교" } });
    fireEvent.click(screen.getByLabelText("동측 절토면"));
    const submit = screen.getByRole("button", { name: "관측 자료 등록 계속" });
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolveResponse?.({ ok: true, json: async () => ({ workOrderId: "work-order-1" }) });
    await waitFor(() => expect(push).toHaveBeenCalledWith("/field/work-orders/work-order-1#external-submissions"));
  });

  it("allows a corrected request after a confirmed validation failure, using a new key", async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: false, status: 422, json: async () => ({ code: "INVALID_INPUT" }) })
      .mockResolvedValueOnce({ ok: true, status: 201, json: async () => ({ workOrderId: "work-order-2" }) });
    render(<ExternalObservationCreateForm siteId="site-1" siteName="서쪽 현장" workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]} />);
    fireEvent.change(screen.getByLabelText("작업 이름"), { target: { value: "외부 비교" } });
    fireEvent.click(screen.getByLabelText("동측 절토면"));
    fireEvent.click(screen.getByRole("button", { name: "관측 자료 등록 계속" }));

    expect(await screen.findByText("입력을 확인해 수정한 뒤 다시 요청하세요.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "관측 자료 등록 계속" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls.map(([, options]) => (options as RequestInit).headers)).toEqual([
      expect.objectContaining({ "Idempotency-Key": "external-create-1" }),
      expect.objectContaining({ "Idempotency-Key": "external-create-2" }),
    ]);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/field/work-orders/work-order-2#external-submissions"));
  });

  it("shows no repeat notice for a fresh scope and keeps one file-flow explainer", async () => {
    render(<ExternalObservationCreateForm
      siteId="site-1"
      siteName="서쪽 현장"
      workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]}
      initialWorkAreaIds={["wa-1"]}
      scopeNotice="선택한 구역에서 시작합니다. 범위가 맞는지 확인하고 필요하면 바꾸세요."
    />);
    // 반복 진입이 아닌데 이전 비교 문구가 나오면 안 된다.
    expect(screen.queryByText(/이전 비교에 사용한/)).toBeNull();
    expect(screen.queryByText(/촬영 간격 기준을 미리 골랐습니다/)).toBeNull();
    expect(screen.getByText(/선택한 구역에서 시작합니다/)).toBeTruthy();
    // 작업→파일 흐름 설명은 CTA 근처 하나만 둔다.
    expect(screen.getAllByText(/파일은 다음 화면에서 제출합니다/)).toHaveLength(1);
    // 하나 고른 범위는 돌아가기 링크에 싣는다.
    expect(screen.getByRole("link", { name: "현장으로 돌아가기" }).getAttribute("href")).toBe("/sites/site-1?workAreaId=wa-1");
  });

  it("keeps the return link bare when nothing or several areas are selected", () => {
    render(<ExternalObservationCreateForm
      siteId="site-1"
      siteName="서쪽 현장"
      workAreas={[{ workAreaId: "wa-1", name: "A구역" }, { workAreaId: "wa-2", name: "B구역" }]}
    />);
    expect(screen.getByRole("link", { name: "현장으로 돌아가기" }).getAttribute("href")).toBe("/sites/site-1");
    fireEvent.click(screen.getByLabelText("A구역"));
    fireEvent.click(screen.getByLabelText("B구역"));
    expect(screen.getByRole("link", { name: "현장으로 돌아가기" }).getAttribute("href")).toBe("/sites/site-1");
  });

  it("shows the repeat template notice only when an actual repeat template is provided", () => {
    render(<ExternalObservationCreateForm
      siteId="site-1"
      siteName="서쪽 현장"
      workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]}
      initialWorkAreaIds={["wa-1"]}
      templateNotice="이전 관측의 활성 작업구역과 촬영 간격 기준을 미리 골랐습니다. 관측 자료를 등록하기 전에 범위를 확인하세요."
    />);
    expect(screen.getByText(/이전 관측의 활성 작업구역/)).toBeTruthy();
  });
});
