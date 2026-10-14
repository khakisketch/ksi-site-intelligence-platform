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

function renderActions() {
  return render(<SpatialDataRequestActions siteId="site-1" workAreaId="area-1" requestId={requestId} canCancel />);
}

it("requires a second explicit confirmation and reports the authoritative canceled state", async () => {
  fetchMock.mockResolvedValue(new Response(JSON.stringify({ jobId: requestId, executionState: "CANCELED" }), { status: 200 }));
  renderActions();
  fireEvent.click(screen.getByRole("button", { name: "요청 취소" }));
  fireEvent.click(screen.getByRole("button", { name: "취소를 확인" }));
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("CANCELED"));
  expect(fetchMock).toHaveBeenCalledWith(apiPath, expect.objectContaining({ method: "POST", cache: "no-store" }));
  expect(fetchMock.mock.calls[0]?.[1]).not.toHaveProperty("body");
  expect(mocked.refresh).toHaveBeenCalledOnce();
});

it("does not present a completion as canceled when the request changed before cancellation", async () => {
  fetchMock.mockResolvedValue(new Response(JSON.stringify({ jobId: requestId, executionState: "COMPLETED" }), { status: 200 }));
  renderActions();
  fireEvent.click(screen.getByRole("button", { name: "요청 취소" }));
  fireEvent.click(screen.getByRole("button", { name: "취소를 확인" }));
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("취소 전에 요청이 완료되었습니다"));
  expect(screen.getByRole("status").textContent).toContain("COMPLETED");
  expect(screen.getByRole("status").textContent).not.toContain("취소되었습니다");
});

it("shows the Core refusal code verbatim without claiming a state change", async () => {
  fetchMock.mockResolvedValue(new Response(JSON.stringify({ code: "PERMISSION_DENIED", message: "Denied" }), { status: 403 }));
  renderActions();
  fireEvent.click(screen.getByRole("button", { name: "요청 취소" }));
  fireEvent.click(screen.getByRole("button", { name: "취소를 확인" }));
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("PERMISSION_DENIED"));
  expect(mocked.refresh).not.toHaveBeenCalled();
});
