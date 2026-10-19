// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: mocked.refresh }) }));

import { SpatialDataRequestActions } from "@/app/sites/[siteId]/spatial-data-requests/SpatialDataRequestActions";

const requestId = "sdj-v1-12345678-1234-1234-1234-123456789abc";
const apiPath = `/api/sites/site-1/work-areas/area-1/spatial-data-requests/${requestId}/cancel`;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  mocked.refresh.mockReset();
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderActions(overrides: Partial<Parameters<typeof SpatialDataRequestActions>[0]> = {}) {
  return render(<SpatialDataRequestActions siteId="site-1" workAreaId="area-1" requestId={requestId} canCancel {...overrides} />);
}

function confirmCancellation() {
  fireEvent.click(screen.getByRole("button", { name: "요청 취소" }));
  expect(screen.getByText("자료 준비 요청을 취소할까요?")).toBeTruthy();
  const confirm = screen.getAllByRole("button", { name: "요청 취소", hidden: true })[1]!;
  fireEvent.click(confirm);
}

it("requires an explicit modal confirmation and reports the authoritative canceled state", async () => {
  fetchMock.mockResolvedValue(new Response(JSON.stringify({ jobId: requestId, executionState: "CANCELED" }), { status: 200 }));
  renderActions();
  expect(fetchMock).not.toHaveBeenCalled();
  confirmCancellation();
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("요청 상태를 확인했습니다: 취소됨."));
  expect(fetchMock).toHaveBeenCalledWith(apiPath, expect.objectContaining({ method: "POST", cache: "no-store" }));
  expect(fetchMock.mock.calls[0]?.[1]).not.toHaveProperty("body");
  expect(mocked.refresh).toHaveBeenCalledOnce();
});

it("writes nothing when the confirmation is dismissed", async () => {
  fetchMock.mockResolvedValue(new Response(JSON.stringify({ jobId: requestId, executionState: "CANCELED" }), { status: 200 }));
  renderActions();
  fireEvent.click(screen.getByRole("button", { name: "요청 취소" }));
  expect(screen.getByText("자료 준비 요청을 취소할까요?")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "취소", hidden: true }));
  expect(screen.queryByText("자료 준비 요청을 취소할까요?")).toBeNull();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(mocked.refresh).not.toHaveBeenCalled();
});

it("explains a denied cancellation in a popover without writing", async () => {
  renderActions({ canCancel: false });
  const trigger = screen.getByRole("button", { name: "요청 취소" });
  expect(trigger.hasAttribute("disabled")).toBe(false);
  expect(screen.queryByText(/요청을 취소할 권한이 없습니다/)).toBeNull();
  fireEvent.click(trigger);
  expect(screen.getByText(/요청을 취소할 권한이 없습니다/)).toBeTruthy();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByText(/요청을 취소할 권한이 없습니다/)).toBeNull();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(mocked.refresh).not.toHaveBeenCalled();
});

it("does not present a completion as canceled when the request changed before cancellation", async () => {
  fetchMock.mockResolvedValue(new Response(JSON.stringify({ jobId: requestId, executionState: "COMPLETED" }), { status: 200 }));
  renderActions();
  confirmCancellation();
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("요청이 취소되지 않았습니다"));
  expect(screen.getByRole("status").textContent).toContain("처리가 완료됐습니다");
  expect(screen.getByRole("status").textContent).not.toContain("COMPLETED");
  expect(screen.getByRole("status").textContent).not.toContain("취소되었습니다");
});

it("explains a denied cancellation without exposing a permission code or claiming a state change", async () => {
  fetchMock.mockResolvedValue(new Response(JSON.stringify({ code: "PERMISSION_DENIED", message: "Denied" }), { status: 403 }));
  renderActions();
  confirmCancellation();
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("요청을 취소할 권한이 없습니다"));
  expect(screen.getByRole("status").textContent).not.toContain("PERMISSION_DENIED");
  expect(mocked.refresh).not.toHaveBeenCalled();
});
