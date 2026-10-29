/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import { createHash } from "node:crypto";

import { ExternalObservationCreateForm as Form } from "@/app/sites/[siteId]/observations/new/ExternalObservationCreateForm";

const fingerprint = `v1-${createHash("sha256").update(JSON.stringify(["ksi-observation-continuity-v1", "org-a", "alice"])).digest("hex")}`;
function ExternalObservationCreateForm(props: ComponentProps<typeof Form>) {
  return <Form accountIdentity={{ fingerprint }} {...props} />;
}

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
  it("does not submit when the original account could not be verified", async () => {
    render(<ExternalObservationCreateForm
      siteId="site-1"
      siteName="서쪽 현장"
      workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]}
      accountIdentity={null}
    />);
    fireEvent.change(screen.getByLabelText("작업 이름"), { target: { value: "외부 비교" } });
    fireEvent.click(screen.getByLabelText("동측 절토면"));
    const submit = screen.getByRole("button", { name: "관측 자료 등록 계속" }) as HTMLButtonElement;
    fireEvent.click(submit);
    expect(submit.disabled).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByText(/계정을 확인하지 못해/)).toBeTruthy();
  });

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
    expect(screen.getByRole("link", { name: "작업구역 목록 보기" }).getAttribute("href")).toBe("/sites/site-1/work-areas");
    expect(screen.getByText(/모바일에서는 목록을 확인할 수 있습니다/).textContent).toContain("같은 계정");
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
    expect(screen.queryAllByText(/촬영 간격 기준을 미리 골랐습니다/)).toHaveLength(0);
    // 범위 공지는 데스크톱 폼과 작은 화면 요약에 하나씩만 둔다(한 번에 하나만 보인다).
    expect(screen.getAllByText(/선택한 구역에서 시작합니다/)).toHaveLength(2);
    expect(screen.getAllByText(/파일은 다음 화면에서 제출합니다/)).toHaveLength(2);
    // 하나 고른 범위는 돌아가기 링크에 싣는다.
    expect(screen.getByRole("link", { name: "현장으로 돌아가기" }).getAttribute("href")).toBe("/sites/site-1?workAreaId=wa-1");
  });

  it.each([
    ["401", "세션이 만료되어 작업을 만들지 못했습니다"],
    ["403", "작업 등록 권한이 없어 작업을 만들지 못했습니다"],
    ["404", "작업 범위를 확인하지 못해 작업을 만들지 못했습니다"],
  ] as const)("releases the frozen attempt with actionable recovery on definitive %s rejection", async (status, message) => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValueOnce({ ok: false, status: Number(status), json: async () => ({}) });
    render(<ExternalObservationCreateForm siteId="site-1" siteName="서쪽 현장" workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]} />);
    fireEvent.change(screen.getByLabelText("작업 이름"), { target: { value: "외부 비교" } });
    fireEvent.click(screen.getByLabelText("동측 절토면"));
    fireEvent.click(screen.getByRole("button", { name: "관측 자료 등록 계속" }));
    expect(await screen.findByText(new RegExp(message))).toBeTruthy();
    // 확정 거부는 같은 키 재시도로 묶지 않는다. 초안은 그대로 두고 편집 가능.
    expect(screen.queryByRole("button", { name: "같은 요청 다시 시도" })).toBeNull();
    expect((screen.getByLabelText("작업 이름") as HTMLInputElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "관측 자료 등록 계속" }) as HTMLButtonElement).disabled).toBe(false);
    // 첫 시도 거부는 만든 것이 없으므로, 다음 제출은 새 키로 나간다.
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ workOrderId: "work-order-7" }) });
    fireEvent.click(screen.getByRole("button", { name: "관측 자료 등록 계속" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/field/work-orders/work-order-7#external-submissions"));
    const keys = fetchMock.mock.calls.map(([, options]) => (options as RequestInit).headers);
    expect(keys).toHaveLength(2);
    expect(keys[0]).not.toEqual(keys[1]);
  });

  it.each([
    ["401"],
    ["403"],
    ["404"],
  ] as const)("preserves the frozen key on same-key retry denied with %s", async (status) => {
    fetchMock.mockReset();
    fetchMock.mockRejectedValueOnce(new Error("lost response"));
    render(<ExternalObservationCreateForm siteId="site-1" siteName="서쪽 현장" workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]} />);
    fireEvent.change(screen.getByLabelText("작업 이름"), { target: { value: "외부 비교" } });
    fireEvent.click(screen.getByLabelText("동측 절토면"));
    fireEvent.click(screen.getByRole("button", { name: "관측 자료 등록 계속" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    // 모호한 첫 시도 뒤 같은 키 재시도가 거부돼도 원래 동결을 버리지 않는다.
    fetchMock.mockResolvedValueOnce({ ok: false, status: Number(status), json: async () => ({}) });
    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    expect(await screen.findByText(/이전 요청이 처리되었는지는 알 수 없습니다/)).toBeTruthy();
    // 부재를 단정하지 않고, 같은 키 재시도 경로가 살아 있다.
    expect(screen.queryByText(/만들지 못했습니다/)).toBeNull();
    expect(screen.getByRole("button", { name: "같은 요청 다시 시도" })).toBeTruthy();
    expect((screen.getByLabelText("작업 이름") as HTMLInputElement).disabled).toBe(true);
    // 작업 목록 링크는 동결된 시도의 작업명·현장으로 미리 검색하고 새 탭으로
    // 연다 — 같은 탭 이동은 이 화면의 동결 키·본문을 날려 같은 키 복구를 깬다.
    const queueLink = screen.getByRole("link", { name: "작업 목록 확인(새 탭)" });
    expect(queueLink).toBeTruthy();
    expect(queueLink.getAttribute("href")).toBe(`/field?q=${encodeURIComponent("외부 비교")}&site=${encodeURIComponent("site-1")}`);
    expect(queueLink.getAttribute("target")).toBe("_blank");
    expect(queueLink.getAttribute("rel")).toContain("noopener");
    // 링크 노출 뒤에도 동결은 그대로다 — 입력 잠금과 같은 키 재시도 경로가 산다.
    expect((screen.getByLabelText("작업 이름") as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "같은 요청 다시 시도" })).toBeTruthy();
    expect(screen.getByText(/같은 이름이 있다고 해서 원래 요청이 성공했다고 단정하지 마세요/)).toBeTruthy();
    expect(screen.getByText(/같은 요청으로 다시 시도해도 중복 등록되지 않습니다/)).toBeTruthy();
    // 같은 키로 다시 보내면 중복 없이 이어진다. 세 호출이 모두 같은 키다.
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ workOrderId: "work-order-8" }) });
    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/field/work-orders/work-order-8#external-submissions"));
    const keys = fetchMock.mock.calls.map(([, options]) => (options as RequestInit).headers);
    expect(keys).toHaveLength(3);
    expect(keys[0]).toEqual(keys[1]);
    expect(keys[1]).toEqual(keys[2]);
    const bodies = fetchMock.mock.calls.map(([, options]) => (options as RequestInit).body);
    expect(bodies[0]).toEqual(bodies[1]);
    expect(bodies[1]).toEqual(bodies[2]);
  });

  it("preserves the frozen key when a same-key retry is rejected with 422", async () => {
    fetchMock.mockReset();
    fetchMock.mockRejectedValueOnce(new Error("lost response"));
    render(<ExternalObservationCreateForm siteId="site-1" siteName="서쪽 현장" workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]} />);
    fireEvent.change(screen.getByLabelText("작업 이름"), { target: { value: "외부 비교" } });
    fireEvent.click(screen.getByLabelText("동측 절토면"));
    fireEvent.click(screen.getByRole("button", { name: "관측 자료 등록 계속" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    // 모호한 첫 시도 뒤 같은 키 재시도가 422로 거부돼도 원래 동결을 버리지
    // 않는다 — 검증·정책이 바뀌면 이미 접수된 요청의 재시도도 거부될 수 있다.
    fetchMock.mockResolvedValueOnce({ ok: false, status: 422, json: async () => ({ code: "INVALID" }) });
    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    expect(await screen.findByText(/이전 요청이 처리되었는지는 알 수 없습니다/)).toBeTruthy();
    expect(screen.getByText(/재시도가 거부될 수 있습니다/)).toBeTruthy();
    expect(screen.queryByText("입력을 확인해 수정한 뒤 다시 요청하세요.")).toBeNull();
    expect(screen.getByRole("button", { name: "같은 요청 다시 시도" })).toBeTruthy();
    expect((screen.getByLabelText("작업 이름") as HTMLInputElement).disabled).toBe(true);
    // 작업 목록 링크는 동결된 시도의 작업명·현장으로 미리 검색하고 새 탭으로
    // 연다 — 같은 탭 이동은 이 화면의 동결 키·본문을 날려 같은 키 복구를 깬다.
    const queueLink422 = screen.getByRole("link", { name: "작업 목록 확인(새 탭)" });
    expect(queueLink422.getAttribute("href")).toBe(`/field?q=${encodeURIComponent("외부 비교")}&site=${encodeURIComponent("site-1")}`);
    expect(queueLink422.getAttribute("target")).toBe("_blank");
    expect(queueLink422.getAttribute("rel")).toContain("noopener");
    // 링크 노출 뒤에도 동결은 그대로다 — 입력 잠금과 같은 키 재시도 경로가 산다.
    expect(screen.getByRole("button", { name: "같은 요청 다시 시도" })).toBeTruthy();
    // 같은 키로 다시 보내면 중복 없이 이어진다. 세 호출이 모두 같은 키·내용이다.
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ workOrderId: "work-order-9" }) });
    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/field/work-orders/work-order-9#external-submissions"));
    const keys = fetchMock.mock.calls.map(([, options]) => (options as RequestInit).headers);
    expect(keys).toHaveLength(3);
    expect(keys[0]).toEqual(keys[1]);
    expect(keys[1]).toEqual(keys[2]);
    const bodies = fetchMock.mock.calls.map(([, options]) => (options as RequestInit).body);
    expect(bodies[0]).toEqual(bodies[1]);
    expect(bodies[1]).toEqual(bodies[2]);
  });

  it("requires the same account on 401 recovery and limits cross-principal retry", async () => {
    fetchMock.mockReset();
    fetchMock.mockRejectedValueOnce(new Error("lost response"));
    render(<ExternalObservationCreateForm siteId="site-1" siteName="서쪽 현장" workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]} />);
    fireEvent.change(screen.getByLabelText("작업 이름"), { target: { value: "외부 비교" } });
    fireEvent.click(screen.getByLabelText("동측 절토면"));
    fireEvent.click(screen.getByRole("button", { name: "관측 자료 등록 계속" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    fetchMock.mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) });
    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    expect(await screen.findByText(/같은 계정으로 다시 로그인/)).toBeTruthy();
    // 같은 키를 다른 계정으로 다시 보내면 서버로 나가지 않고 막는다는 점을 명시한다.
    expect(screen.getByText(/다른 계정에서 같은 요청을 다시 시도하면 이 화면에서 새 작업을 만들지 않습니다/)).toBeTruthy();
    // 원래 동결은 유지된다.
    expect(screen.getByRole("button", { name: "같은 요청 다시 시도" })).toBeTruthy();
  });

  it("sends the original account continuity with the frozen key and preserves it on account-change refusal", async () => {
    fetchMock.mockReset();
    fetchMock.mockRejectedValueOnce(new Error("lost response"));
    render(<ExternalObservationCreateForm
      siteId="site-1"
      siteName="서쪽 현장"
      workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]}
      accountIdentity={{ fingerprint }}
    />);
    fireEvent.change(screen.getByLabelText("작업 이름"), { target: { value: "외부 비교" } });
    fireEvent.click(screen.getByLabelText("동측 절토면"));
    fireEvent.click(screen.getByRole("button", { name: "관측 자료 등록 계속" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    const firstHeaders = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
    expect(firstHeaders["x-ksi-continuity-fingerprint"]).toBe(fingerprint);

    // 다른 계정으로 바뀐 뒤 같은 키 재시도는 BFF가 Core 호출 없이 409로 끊는다.
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({ code: "ACCOUNT_CONTINUITY_MISMATCH" }),
    });
    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    expect(await screen.findByText(/계정이 바뀌어 같은 요청을 다시 보내지 않았습니다/)).toBeTruthy();
    const retryHeaders = (fetchMock.mock.calls[1][1] as RequestInit).headers as Record<string, string>;
    // 재시도는 원래 키·내용·연속성을 그대로 싣는다.
    expect(retryHeaders["Idempotency-Key"]).toBe(firstHeaders["Idempotency-Key"]);
    expect(retryHeaders["x-ksi-continuity-fingerprint"]).toBe(fingerprint);
    expect((fetchMock.mock.calls[1][1] as RequestInit).body).toBe((fetchMock.mock.calls[0][1] as RequestInit).body);
    // 동결 유지: 같은 키 재시도 경로가 살아 있다.
    expect(screen.getByRole("button", { name: "같은 요청 다시 시도" })).toBeTruthy();
    expect((screen.getByLabelText("작업 이름") as HTMLInputElement).disabled).toBe(true);

    // 원래 계정으로 돌아오면 같은 키 재시도가 같은 작업을 돌려준다.
    fetchMock.mockResolvedValueOnce({ ok: true, status: 201, json: async () => ({ workOrderId: "work-order-10" }) });
    fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/field/work-orders/work-order-10#external-submissions"));
    const replayHeaders = (fetchMock.mock.calls[2][1] as RequestInit).headers as Record<string, string>;
    expect(replayHeaders["Idempotency-Key"]).toBe(firstHeaders["Idempotency-Key"]);
    expect(replayHeaders["x-ksi-continuity-fingerprint"]).toBe(fingerprint);
  });

  it("offers an explicit new start after an uncertain failure without losing the draft", async () => {
    fetchMock.mockRejectedValueOnce(new Error("lost response"));
    render(<ExternalObservationCreateForm siteId="site-1" siteName="서쪽 현장" workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]} />);
    fireEvent.change(screen.getByLabelText("작업 이름"), { target: { value: "외부 비교" } });
    fireEvent.click(screen.getByLabelText("동측 절토면"));
    fireEvent.click(screen.getByRole("button", { name: "관측 자료 등록 계속" }));
    expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "같은 요청 다시 시도" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "새 요청으로 시작" }));
    // 초안은 유지하고, 잠금만 푼다. 다음 제출은 새 키로 나간다.
    expect((screen.getByLabelText("작업 이름") as HTMLInputElement).value).toBe("외부 비교");
    expect(screen.getByRole("button", { name: "관측 자료 등록 계속" })).toBeTruthy();
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ workOrderId: "work-order-9" }) });
    fireEvent.click(screen.getByRole("button", { name: "관측 자료 등록 계속" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/field/work-orders/work-order-9#external-submissions"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((fetchMock.mock.calls[0][1] as RequestInit).headers).not.toEqual((fetchMock.mock.calls[1][1] as RequestInit).headers);
  });

  it("locks name, areas, and submit until hydration, with a visible reason", async () => {
    const { renderToString } = await import("react-dom/server");
    // Fresh: nothing submittable before hydration.
    const fresh = renderToString(<ExternalObservationCreateForm
      siteId="site-1"
      siteName="서쪽 현장"
      workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]}
    />);
    expect(fresh).toContain("화면을 준비하고 있습니다");
    const freshDoc = document.createElement("div");
    freshDoc.innerHTML = fresh;
    expect((freshDoc.querySelector('input[aria-label="작업 이름"]') as HTMLInputElement).disabled).toBe(true);
    expect((freshDoc.querySelector('input[aria-label="동측 절토면"]') as HTMLInputElement).disabled).toBe(true);
    expect((freshDoc.querySelector("button.btn-primary") as HTMLButtonElement).disabled).toBe(true);
    // 준비 중에는 필수 입력 안내 3건이 아니라 준비 안내만 보인다.
    expect(fresh).not.toContain("작업 이름을 입력하고 비교할 작업구역을 하나 이상 선택하세요");
    expect(fresh).not.toContain("비교할 작업구역을 하나 이상 선택하세요");
    // Repeat: server values present, still locked before hydration. JS 없이
    // SSR만으로는 어떤 경우에도 제출할 수 없다.
    const repeat = renderToString(<ExternalObservationCreateForm
      siteId="site-1"
      siteName="서쪽 현장"
      workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]}
      initialWorkAreaIds={["wa-1"]}
      suggestedName="1차 관측 · 2회차"
    />);
    const repeatDoc = document.createElement("div");
    repeatDoc.innerHTML = repeat;
    expect((repeatDoc.querySelector('input[aria-label="작업 이름"]') as HTMLInputElement).disabled).toBe(true);
    expect((repeatDoc.querySelector("button.btn-primary") as HTMLButtonElement).disabled).toBe(true);
    expect(repeat).toContain("화면을 준비하고 있습니다");
    expect(repeat).toContain("1차 관측 · 2회차");
  });

  it("opens the gate on hydration and submits the server repeat draft unchanged", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const { act } = await import("react");
    const { renderToString } = await import("react-dom/server");
    const { hydrateRoot } = await import("react-dom/client");
    const props = {
      siteId: "site-1",
      siteName: "서쪽 현장",
      workAreas: [{ workAreaId: "wa-1", name: "동측 절토면" }],
      initialWorkAreaIds: ["wa-1"],
      suggestedName: "1차 관측 · 2회차",
    };
    const container = document.createElement("div");
    container.innerHTML = renderToString(<ExternalObservationCreateForm {...props} />);
    document.body.appendChild(container);
    // 잠긴 입력칸에는 실제 사용자 입력이 들어갈 수 없다. 네이티브 직접 대입은
    // 자동화 흔적일 뿐이며, hydration 뒤에도 state·본문에 스며들면 안 된다.
    (container.querySelector('input[aria-label="작업 이름"]') as HTMLInputElement).value = "흔적 값";
    (container.querySelector('input[aria-label="동측 절토면"]') as HTMLInputElement).checked = false;
    let root: { unmount: () => void } | undefined;
    await act(async () => {
      const mounted = hydrateRoot(container, <ExternalObservationCreateForm {...props} />);
      root = { unmount: () => mounted.unmount() };
    });
    try {
      // 잠금 해제: 안내가 사라지고 서버 초안 그대로 제출 가능해야 한다.
      expect(container.textContent).not.toContain("화면을 준비하고 있습니다");
      expect((container.querySelector('input[aria-label="작업 이름"]') as HTMLInputElement).value).toBe("1차 관측 · 2회차");
      expect((container.querySelector('input[aria-label="동측 절토면"]') as HTMLInputElement).checked).toBe(true);
      expect((screen.getByRole("button", { name: "관측 자료 등록 계속" }) as HTMLButtonElement).disabled).toBe(false);
      fireEvent.click(screen.getByRole("button", { name: "관측 자료 등록 계속" }));
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)).toEqual({
        name: "1차 관측 · 2회차",
        workAreaIds: ["wa-1"],
        scheduleId: null,
        executionMode: "EXTERNAL_RECONSTRUCTION",
      });
      expect(push).toHaveBeenCalledWith("/field/work-orders/work-order-1#external-submissions");
    } finally {
      root?.unmount();
      container.remove();
    }
  });

  it("keeps a fresh form gated until genuine post-hydration input, then posts exactly that", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const { act } = await import("react");
    const { renderToString } = await import("react-dom/server");
    const { hydrateRoot } = await import("react-dom/client");
    const realProps = {
      siteId: "site-1",
      siteName: "서쪽 현장",
      workAreas: [{ workAreaId: "wa-1", name: "동측 절토면" }, { workAreaId: "wa-2", name: "서측 제방" }],
    };
    const container = document.createElement("div");
    container.innerHTML = renderToString(<ExternalObservationCreateForm {...realProps} />);
    document.body.appendChild(container);
    let root: { unmount: () => void } | undefined;
    await act(async () => {
      const mounted = hydrateRoot(container, <ExternalObservationCreateForm {...realProps} />);
      root = { unmount: () => mounted.unmount() };
    });
    try {
      // hydration 뒤에도 입력 전에는 잠금과 동일하게 막히고, 필수 입력 안내가 보인다.
      expect((screen.getByRole("button", { name: "관측 자료 등록 계속" }) as HTMLButtonElement).disabled).toBe(true);
      expect(screen.getByText("작업 이름을 입력하고 비교할 작업구역을 하나 이상 선택하세요.")).toBeTruthy();
      // hydration 이후의 실제 사용자 입력만 state가 된다.
      fireEvent.change(container.querySelector('input[aria-label="작업 이름"]') as HTMLInputElement, { target: { value: "사후 입력" } });
      fireEvent.click(container.querySelector('input[aria-label="동측 절토면"]') as HTMLInputElement);
      fireEvent.click(container.querySelector('input[aria-label="서측 제방"]') as HTMLInputElement);
      expect((screen.getByRole("button", { name: "관측 자료 등록 계속" }) as HTMLButtonElement).disabled).toBe(false);
      fireEvent.click(screen.getByRole("button", { name: "관측 자료 등록 계속" }));
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)).toEqual({
        name: "사후 입력",
        workAreaIds: ["wa-1", "wa-2"],
        scheduleId: null,
        executionMode: "EXTERNAL_RECONSTRUCTION",
      });
    } finally {
      root?.unmount();
      container.remove();
    }
  });

  it("blocks submit after a genuine uncheck without sending the unchecked area", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const { act } = await import("react");
    const { renderToString } = await import("react-dom/server");
    const { hydrateRoot } = await import("react-dom/client");
    const props = {
      siteId: "site-1",
      siteName: "서쪽 현장",
      workAreas: [{ workAreaId: "wa-1", name: "동측 절토면" }],
      initialWorkAreaIds: ["wa-1"],
      suggestedName: "1차 관측 · 2회차",
    };
    const container = document.createElement("div");
    container.innerHTML = renderToString(<ExternalObservationCreateForm {...props} />);
    document.body.appendChild(container);
    let root: { unmount: () => void } | undefined;
    await act(async () => {
      const mounted = hydrateRoot(container, <ExternalObservationCreateForm {...props} />);
      root = { unmount: () => mounted.unmount() };
    });
    try {
      // hydration 뒤 실제 해제는 선택에서 빠지고, 강제 클릭으로도 나가지 않는다.
      fireEvent.click(container.querySelector('input[aria-label="동측 절토면"]') as HTMLInputElement);
      expect((screen.getByRole("button", { name: "관측 자료 등록 계속" }) as HTMLButtonElement).disabled).toBe(true);
      expect(screen.getByText("비교할 작업구역을 하나 이상 선택하세요.")).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "관측 자료 등록 계속" }));
      await waitFor(() => expect(fetchMock).not.toHaveBeenCalled());
    } finally {
      root?.unmount();
      container.remove();
    }
  });

  it("freezes an SSR-hydrated draft on an ambiguous failure and retries it unchanged", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const { act } = await import("react");
    const { renderToString } = await import("react-dom/server");
    const { hydrateRoot } = await import("react-dom/client");
    fetchMock.mockRejectedValueOnce(new Error("lost response"));
    const props = {
      siteId: "site-1",
      siteName: "서쪽 현장",
      workAreas: [{ workAreaId: "wa-1", name: "동측 절토면" }],
    };
    const container = document.createElement("div");
    container.innerHTML = renderToString(<ExternalObservationCreateForm {...props} />);
    document.body.appendChild(container);
    let root: { unmount: () => void } | undefined;
    await act(async () => {
      const mounted = hydrateRoot(container, <ExternalObservationCreateForm {...props} />);
      root = { unmount: () => mounted.unmount() };
    });
    try {
      fireEvent.change(container.querySelector('input[aria-label="작업 이름"]') as HTMLInputElement, { target: { value: "동결 초안" } });
      fireEvent.click(container.querySelector('input[aria-label="동측 절토면"]') as HTMLInputElement);
      fireEvent.click(screen.getByRole("button", { name: "관측 자료 등록 계속" }));
      expect(await screen.findByText(/응답을 확인하지 못했습니다/)).toBeTruthy();
      expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)).toEqual({
        name: "동결 초안",
        workAreaIds: ["wa-1"],
        scheduleId: null,
        executionMode: "EXTERNAL_RECONSTRUCTION",
      });
      // 준비 게이트는 초안 state만 열고 동결 본문을 덮지 않으므로 재시도는 같은 키·내용이다.
      fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ workOrderId: "work-order-1" }) });
      fireEvent.click(screen.getByRole("button", { name: "같은 요청 다시 시도" }));
      await waitFor(() => expect(push).toHaveBeenCalledWith("/field/work-orders/work-order-1#external-submissions"));
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect((fetchMock.mock.calls[1][1] as RequestInit).body).toBe((fetchMock.mock.calls[0][1] as RequestInit).body);
      expect((fetchMock.mock.calls[1][1] as RequestInit).headers).toEqual((fetchMock.mock.calls[0][1] as RequestInit).headers);
    } finally {
      root?.unmount();
      container.remove();
    }
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
    // 데스크톱 폼과 작은 화면 요약에 하나씩 둔다(한 번에 하나만 보인다).
    expect(screen.getAllByText(/이전 관측의 활성 작업구역/)).toHaveLength(2);
  });

  it("shows a read-only range summary for compact screens without any mutating control", () => {
    render(<ExternalObservationCreateForm
      siteId="site-1"
      siteName="서쪽 현장"
      workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }, { workAreaId: "wa-2", name: "서측 제방" }]}
      initialWorkAreaIds={["wa-1"]}
      templateNotice="이전 관측의 활성 작업구역과 촬영 간격 기준을 미리 골랐습니다. 관측 자료를 등록하기 전에 범위를 확인하세요."
    />);
    const summary = screen.getByTestId("compact-registration-summary");
    expect(summary.textContent).toContain("이전 관측의 활성 작업구역");
    expect(summary.textContent).toContain("동측 절토면");
    expect(summary.textContent).toContain("서측 제방");
    expect(summary.textContent).toContain("선택 제안");
    // 읽기 전용과 쓰기 분리를 명시한다.
    expect(summary.textContent).toContain("읽기 전용");
    expect(summary.textContent).toContain("화면 폭 1024px 이상");
    expect(summary.textContent).toContain("같은 계정으로 새로 입력");
    expect(summary.textContent).toContain("옮겨가지 않습니다");
    expect(summary.textContent).toContain("외부 비교 기록에서 목록을 확인");
    expect(summary.textContent).toContain("파일은 다음 화면에서 제출합니다");
    // 다른 기기로 이어진다는 약속을 하지 않는다.
    expect(summary.textContent).not.toContain("이어가");
    // 식별자 원문이 그대로 노출되지 않는다.
    expect(summary.textContent).not.toContain("wa-1");
    expect(summary.textContent).not.toContain("wa-2");
    expect(summary.textContent).not.toContain(fingerprint);
    // 요약에는 입력·선택·단추·링크를 두지 않는다.
    expect(summary.querySelector("button, input, select, textarea, a")).toBeNull();
  });

  it("states viewport width and same-account re-entry without cross-device draft promises", () => {
    render(<ExternalObservationCreateForm
      siteId="site-1"
      siteName="서쪽 현장"
      workAreas={[{ workAreaId: "wa-1", name: "동측 절토면" }]}
    />);
    const notice = document.querySelector('[data-responsive-action-notice="WORK_ORDERS_WRITE"]');
    expect(notice).not.toBeNull();
    expect(notice!.textContent).toContain("화면 폭 1024px 이상");
    expect(notice!.textContent).toContain("같은 계정으로 새로 입력");
    expect(notice!.textContent).toContain("옮겨가지 않으며");
    expect(notice!.textContent).toContain("권한은 등록 시점에 다시 확인");
    // 기기 종류가 아니라 창 폭 기준임을 말하고, 이어쓰기 약속을 하지 않는다.
    expect(notice!.textContent).not.toContain("이어가");
    expect(notice!.textContent).not.toContain("노트북에서 계속");
    // 목록 읽기는 쓰기 경계 밖에 그대로 있다.
    expect(screen.getByRole("link", { name: /외부 비교 기록/ }).getAttribute("href")).toBe("/sites/site-1/observations");
    // 연속성 식별자는 화면 텍스트·주소로 나가지 않는다.
    expect(document.body.textContent).not.toContain(fingerprint);
    for (const link of Array.from(document.querySelectorAll("a"))) {
      expect(link.getAttribute("href") ?? "").not.toContain(fingerprint);
      expect(link.getAttribute("href") ?? "").not.toContain("x-ksi-continuity");
    }
  });
});
