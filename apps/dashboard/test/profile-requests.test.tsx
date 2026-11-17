/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: nav.refresh, push: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) => createElement("a", { href, ...props }, children),
}));

import { ProfileRequests, type RequestableAsset } from "@/app/sites/[siteId]/measurements/ProfileRequests";

const DIGEST = `sha256:${"a".repeat(64)}`;
const FEATURE = { featureId: `mf-${"1".repeat(32)}`, revision: 2, lineDigest: DIGEST };
const ASSET = `ksa-v1-${"3".repeat(64)}`;
const row = (overrides: Partial<RequestableAsset> = {}): RequestableAsset => ({
  assetRef: ASSET, label: "2026-11-02", state: "none", jobId: null, reason: null, assetHref: "/sites/site-1?panel=materials", ...overrides,
});
const fetchMock = vi.fn();
const reply = (status: number, body: unknown) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const show = (rows: RequestableAsset[], canRequest = true) => render(<ProfileRequests siteId="site 1" workAreaId="area-1" feature={FEATURE} rows={rows} canRequest={canRequest} />);

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  nav.refresh.mockReset();
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("날짜별 단면 요청", () => {
  it("자료와 저장된 선 개정만 보내고, 성공하면 화면을 새로 읽는다", async () => {
    fetchMock.mockResolvedValue(reply(200, { job: {} }));
    show([row()]);
    fireEvent.click(screen.getByRole("button", { name: "단면 요청" }));
    await waitFor(() => expect(nav.refresh).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/sites/site%201/work-areas/area-1/surface-profile-requests");
    expect(JSON.parse(init.body)).toEqual({ assetRef: ASSET, feature: FEATURE });
    expect(init.headers["Idempotency-Key"]).toMatch(/^console-/);
  });

  it("응답을 모르는 실패는 같은 키로 다시 보내고, 서버가 답한 뒤에는 새 키를 쓴다", async () => {
    fetchMock.mockRejectedValueOnce(new Error("net")).mockResolvedValueOnce(reply(503, { code: "X" })).mockResolvedValueOnce(reply(200, {}));
    show([row()]);
    const press = () => fireEvent.click(screen.getByRole("button", { name: /단면 요청|다시 요청/ }));
    press();
    await screen.findByText(/응답을 확인하지 못했습니다/);
    press();
    await screen.findByText(/지금은 요청할 수 없습니다/);
    press();
    await waitFor(() => expect(nav.refresh).toHaveBeenCalled());
    const keys = fetchMock.mock.calls.map((call) => call[1].headers["Idempotency-Key"]);
    expect(keys[0]).toBe(keys[1]);
    expect(keys[2]).not.toBe(keys[1]);
  });

  it("높이 판정이 막히면 사유·다음 조치와 자료 상세 링크를 보인다", async () => {
    fetchMock.mockResolvedValue(reply(409, { code: "HEIGHT_NOT_ELIGIBLE", decision: { verdict: "BLOCKED", reasons: ["VERTICAL_REFERENCE_UNKNOWN"], remediations: ["OBSERVE_VERTICAL_REFERENCE"] } }));
    show([row()]);
    fireEvent.click(screen.getByRole("button", { name: "단면 요청" }));
    expect(await screen.findByText("수직기준을 파일에서 확인하지 못했습니다")).toBeTruthy();
    expect(screen.getByText(/자료 상세에서 수직 기준을 선언하세요/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "자료 상세 열기" }).getAttribute("href")).toBe("/sites/site-1?panel=materials");
    expect(nav.refresh).not.toHaveBeenCalled();
  });

  it("Core가 거부한 이유를 업무 말로 보인다", async () => {
    fetchMock.mockResolvedValue(reply(422, { code: "LINE_OUTSIDE_SURFACE" }));
    show([row()]);
    fireEvent.click(screen.getByRole("button", { name: "단면 요청" }));
    expect(await screen.findByText("이 선이 등록된 범위에 닿지 않았습니다.")).toBeTruthy();
  });

  it("상태별 안내와 버튼: 실패·취소는 다시 요청할 수 있고, 완료·읽기 불가에는 버튼이 없다", () => {
    show([
      row({ assetRef: `ksa-v1-${"1".repeat(64)}`, label: "A", state: "failed", jobId: "j", reason: "LINE_OUTSIDE_SURFACE" }),
      row({ assetRef: `ksa-v1-${"2".repeat(64)}`, label: "B", state: "canceled", jobId: "j" }),
      row({ assetRef: `ksa-v1-${"4".repeat(64)}`, label: "C", state: "done", jobId: "j" }),
      row({ assetRef: `ksa-v1-${"5".repeat(64)}`, label: "D", state: "unavailable", jobId: "j", reason: "ACCESS_REVOKED" }),
    ]);
    expect(screen.getAllByRole("button", { name: "다시 요청" })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "단면 요청" })).toBeNull();
    expect(screen.getByText(/읽지 못했습니다\. 이 선이 등록된 범위에 닿지 않았습니다\./)).toBeTruthy();
    expect(screen.getByText("요청을 취소했습니다.")).toBeTruthy();
    expect(screen.getByText("단면을 읽었습니다.")).toBeTruthy();
    expect(screen.getByText("읽은 결과가 있지만 지금은 표시할 수 없습니다.")).toBeTruthy();
  });

  it("권한이 없으면 상태만 보이고 요청 버튼은 없다", () => {
    show([row(), row({ assetRef: `ksa-v1-${"2".repeat(64)}`, state: "active", jobId: "j" })], false);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/작업 등록 권한이 있는 계정/)).toBeTruthy();
  });

  it("진행 중인 요청은 취소할 수 있고, 취소 뒤 화면을 새로 읽는다", async () => {
    fetchMock.mockResolvedValue(reply(200, { job: {} }));
    show([row({ state: "active", jobId: `spj-${"2".repeat(32)}` })]);
    expect(screen.getByText(/단면을 읽는 중입니다/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "요청 취소" }));
    await waitFor(() => expect(nav.refresh).toHaveBeenCalled());
    expect(fetchMock.mock.calls[0]![0]).toBe(`/api/sites/site%201/work-areas/area-1/surface-profile-jobs/spj-${"2".repeat(32)}/cancel`);
    expect(fetchMock.mock.calls[0]![1].method).toBe("POST");
  });

  it("취소가 거부돼도 이유를 말하고 상태를 다시 읽는다", async () => {
    fetchMock.mockResolvedValue(reply(409, { code: "INVALID_STATE" }));
    show([row({ state: "active", jobId: `spj-${"2".repeat(32)}` })]);
    fireEvent.click(screen.getByRole("button", { name: "요청 취소" }));
    await waitFor(() => expect(nav.refresh).toHaveBeenCalled());
    expect(screen.getByRole("alert").textContent).toMatch(/단면을 요청하지 못했습니다/);
  });

  it("진행 중인 동안만 주기적으로 새로 읽고, 한도 뒤에는 멈춘다", () => {
    vi.useFakeTimers();
    const { unmount } = show([row({ state: "active", jobId: "j" })]);
    act(() => { vi.advanceTimersByTime(3000 * 3); });
    expect(nav.refresh).toHaveBeenCalledTimes(3);
    act(() => { vi.advanceTimersByTime(3000 * 60); });
    expect(nav.refresh.mock.calls.length).toBeLessThanOrEqual(40);
    unmount();
    nav.refresh.mockReset();
    show([row({ state: "done", jobId: "j" })]);
    act(() => { vi.advanceTimersByTime(3000 * 5); });
    expect(nav.refresh).not.toHaveBeenCalled();
  });

  it("요청 중에는 다른 요청을 겹쳐 보내지 않는다", async () => {
    let resolve: (value: unknown) => void = () => {};
    fetchMock.mockReturnValue(new Promise((r) => { resolve = r; }));
    show([row(), row({ assetRef: `ksa-v1-${"2".repeat(64)}`, label: "B" })]);
    const [first, second] = screen.getAllByRole("button", { name: "단면 요청" });
    fireEvent.click(first!);
    fireEvent.click(second!);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect((screen.getByRole("button", { name: "요청하는 중" }) as HTMLButtonElement).disabled).toBe(true);
    await act(async () => { resolve(reply(200, {})); });
  });
});
