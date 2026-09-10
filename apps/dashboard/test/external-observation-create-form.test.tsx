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
  it("creates one external ingress with a stable idempotency key and opens its work detail", async () => {
    render(<ExternalObservationCreateForm siteId="site-1" siteName="서쪽 현장" workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]} />);
    expect(screen.getByRole("heading", { name: "서쪽 현장 · 새 관측 시작" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "현장으로 돌아가기" }).getAttribute("href")).toBe("/sites/site-1");
    expect(screen.getByLabelText("작업 이름").getAttribute("maxlength")).toBe("200");
    fireEvent.change(screen.getByLabelText("작업 이름"), { target: { value: "9월 6일 현황 비교" } });
    fireEvent.click(screen.getByLabelText("동측 절토면"));
    fireEvent.click(screen.getByRole("button", { name: "산출물 등록 시작" }));

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
    expect(push).toHaveBeenCalledWith("/field/work-orders/work-order-1");
  });

  it("keeps flight planning separate and gives a recovery link when no work area is available", () => {
    render(<ExternalObservationCreateForm siteId="site-1" siteName="서쪽 현장" workAreas={[]} />);
    expect(screen.getByRole("link", { name: "작업구역 만들기" }).getAttribute("href")).toBe("/sites/site-1/work-areas");
    expect(screen.getByRole("link", { name: /비행 계획 만들기/ }).getAttribute("href")).toBe("/sites/site-1/surveys/new");
    expect(screen.queryByRole("button", { name: "산출물 등록 시작" })).toBeNull();
  });

  it("does not send a second create while the first response is still unknown", async () => {
    let resolveResponse: ((value: unknown) => void) | undefined;
    fetchMock.mockImplementation(() => new Promise((resolve) => { resolveResponse = resolve; }));
    render(<ExternalObservationCreateForm siteId="site-1" siteName="서쪽 현장" workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]} />);
    fireEvent.change(screen.getByLabelText("작업 이름"), { target: { value: "외부 비교" } });
    fireEvent.click(screen.getByLabelText("동측 절토면"));
    const submit = screen.getByRole("button", { name: "산출물 등록 시작" });
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolveResponse?.({ ok: true, json: async () => ({ workOrderId: "work-order-1" }) });
    await waitFor(() => expect(push).toHaveBeenCalledWith("/field/work-orders/work-order-1"));
  });

  it("allows a corrected request after a confirmed validation failure, using a new key", async () => {
    fetchMock
      .mockResolvedValueOnce({ ok: false, status: 422, json: async () => ({ code: "INVALID_INPUT" }) })
      .mockResolvedValueOnce({ ok: true, status: 201, json: async () => ({ workOrderId: "work-order-2" }) });
    render(<ExternalObservationCreateForm siteId="site-1" siteName="서쪽 현장" workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]} />);
    fireEvent.change(screen.getByLabelText("작업 이름"), { target: { value: "외부 비교" } });
    fireEvent.click(screen.getByLabelText("동측 절토면"));
    fireEvent.click(screen.getByRole("button", { name: "산출물 등록 시작" }));

    expect(await screen.findByText("입력을 확인해 수정한 뒤 다시 요청하세요.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "산출물 등록 시작" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls.map(([, options]) => (options as RequestInit).headers)).toEqual([
      expect.objectContaining({ "Idempotency-Key": "external-create-1" }),
      expect.objectContaining({ "Idempotency-Key": "external-create-2" }),
    ]);
    await waitFor(() => expect(push).toHaveBeenCalledWith("/field/work-orders/work-order-2"));
  });
});
