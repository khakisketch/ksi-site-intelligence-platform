/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkAreaPanel } from "@/app/sites/[siteId]/work-areas/WorkAreaPanel";
import type { WorkArea } from "@/lib/core-api/types";

const notifyMock = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/ToastProvider", () => ({ useToast: () => ({ notify: notifyMock }) }));
vi.mock("@/components/ui/ConfirmDialog", () => ({
  ConfirmDialog: ({ open, title, description, confirmLabel, onConfirm, onCancel, pending }: {
    open: boolean; title: string; description?: React.ReactNode; confirmLabel: string;
    onConfirm: () => void; onCancel: () => void; pending?: boolean;
  }) => open ? (
    <div role="dialog" aria-label={title}>
      <p>{title}</p>
      <div>{description}</div>
      <button disabled={pending} onClick={onConfirm}>{confirmLabel}</button>
      <button onClick={onCancel}>취소</button>
    </div>
  ) : null,
}));
vi.mock("@/components/ui/ActionUnavailable", () => ({
  ActionUnavailable: ({ label, description }: { label: string; description: string }) => (
    <div><span>{label}</span><span>{description}</span></div>
  ),
}));
vi.mock("@/components/map/AoiPolygonMap", () => ({
  AoiPolygonMap: ({ value, onChange }: { value: { latDeg: number; lonDeg: number }[]; onChange: (next: { latDeg: number; lonDeg: number }[]) => void }) => (
    <button aria-label="꼭짓점 추가" onClick={() => onChange([...value, { latDeg: 37.5, lonDeg: 127.0 }, { latDeg: 37.6, lonDeg: 127.1 }, { latDeg: 37.5, lonDeg: 127.2 }])}>꼭짓점 추가</button>
  ),
}));
vi.mock("@/components/ui/StatusBadge", () => ({ StateBadge: ({ label }: { label: string }) => <span>{label}</span> }));
vi.mock("@/components/ui/ErrorState", () => ({ ErrorState: ({ message }: { message: string }) => <div role="alert">{message}</div> }));
vi.mock("@/components/responsive/ResponsiveActionBoundary", () => ({
  ResponsiveActionBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  ResponsiveNotice: () => null,
}));

function activeArea(name = "동측 절토면"): WorkArea {
  return {
    schemaVersion: "1.0",
    workAreaId: "area-1",
    siteId: "site-1",
    name,
    polygon: { type: "Polygon", coordinates: [[[127.0, 37.5], [127.1, 37.6], [127.2, 37.5], [127.0, 37.5]]] },
    crs: "EPSG:4326",
    status: "ACTIVE",
    supersedes: null,
    createdAt: "2026-09-01T00:00:00Z",
  };
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); notifyMock.mockClear(); });

describe("WorkAreaPanel archive confirmation", () => {
  it("names the exact area, posts nothing on cancel, and keeps the list", () => {
    vi.stubGlobal("fetch", vi.fn());
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} />);

    fireEvent.click(screen.getByRole("button", { name: "구역 보관" }));
    const dialog = screen.getByRole("dialog", { name: "구역을 보관할까요?" });
    expect(within(dialog).getByText(/동측 절토면/)).toBeTruthy();
    expect(within(dialog).getByText(/이 화면에서 되돌릴 수 없습니다/)).toBeTruthy();
    expect(within(dialog).getByText(/이미 낸 리포트는 그대로 유지됩니다/)).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "취소" }));
    expect(fetch).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText("동측 절토면")).toBeTruthy();
    expect(notifyMock).not.toHaveBeenCalled();
  });

  it("posts the archive exactly once after confirmation and toasts the verified result", async () => {
    const archived = { ...activeArea(), status: "ARCHIVED" as const };
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ workArea: archived }) });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} />);

    fireEvent.click(screen.getByRole("button", { name: "구역 보관" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "구역을 보관할까요?" })).getByRole("button", { name: "구역 보관" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/sites/site-1/work-areas/area-1/archive");
    await waitFor(() => expect(notifyMock).toHaveBeenCalledWith('"동측 절토면"을 보관했습니다.'));
  });

  it("toasts a complete registration and keeps the no-permission listing as a blocked action", async () => {
    const created = activeArea("새 구역");
    const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ workArea: created }) });
    vi.stubGlobal("fetch", fetchMock);
    const { unmount } = render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[]} workAreaListError={null} />);

    fireEvent.change(screen.getByPlaceholderText("3공구 성토부"), { target: { value: "새 구역" } });
    fireEvent.click(screen.getByRole("button", { name: "꼭짓점 추가" }));
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(notifyMock).toHaveBeenCalledWith('작업구역 "새 구역"을 등록했습니다.'));
    unmount();
    cleanup();

    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite={false} initialWorkAreas={[activeArea()]} workAreaListError={null} />);
    expect(screen.getByText("작업구역 등록")).toBeTruthy();
    expect(screen.getByText("현재 계정으로는 작업구역을 등록하거나 보관할 수 없습니다. 현장 담당자에게 문의하세요.")).toBeTruthy();
    expect(document.body.textContent).not.toContain("SITES_WRITE");
    expect(screen.getByText("동측 절토면")).toBeTruthy();
  });

  it("shows an archive failure in the affected card only and retries through re-confirmation", async () => {
    const other = { ...activeArea(), workAreaId: "area-2", name: "서측 성토면" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ workArea: { ...activeArea(), status: "ARCHIVED" as const } }) });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea(), other]} workAreaListError={null} />);

    fireEvent.click(screen.getAllByRole("button", { name: "구역 보관" })[0]!);
    fireEvent.click(within(screen.getByRole("dialog", { name: "구역을 보관할까요?" })).getByRole("button", { name: "구역 보관" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    const card = alerts[0]!.closest("li");
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).getByText("동측 절토면")).toBeTruthy();
    expect(alerts[0]!.textContent).toContain("작업구역 보관에 실패했습니다");
    expect(screen.getByText("서측 성토면")).toBeTruthy();
    expect(notifyMock).not.toHaveBeenCalled();

    fireEvent.click(within(card as HTMLElement).getByRole("button", { name: "보관 다시 시도" }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("dialog", { name: "구역을 보관할까요?" })).toBeTruthy();
    fireEvent.click(within(screen.getByRole("dialog", { name: "구역을 보관할까요?" })).getByRole("button", { name: "구역 보관" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(notifyMock).toHaveBeenCalledWith('"동측 절토면"을 보관했습니다.'));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
