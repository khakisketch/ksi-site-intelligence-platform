/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WorkAreaPanel } from "@/app/sites/[siteId]/work-areas/WorkAreaPanel";
import type { WorkArea } from "@/lib/core-api/types";

vi.mock("@/components/ui/ToastProvider", () => ({ useToast: () => ({ notify: vi.fn() }) }));
vi.mock("@/components/ui/ConfirmDialog", () => ({
  ConfirmDialog: ({ open, title, description, onConfirm, onCancel }: {
    open: boolean; title: string; description?: React.ReactNode;
    onConfirm: () => void; onCancel: () => void;
  }) => open ? (
    <div role="dialog" aria-label={title}>
      {description}
      <button onClick={onConfirm}>구역 보관</button>
      <button onClick={onCancel}>취소</button>
    </div>
  ) : null,
}));
vi.mock("@/components/responsive/ResponsiveActionBoundary", () => ({
  ResponsiveActionBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  ResponsiveNotice: () => null,
}));
vi.mock("@/components/map/AoiPolygonMap", () => {
  function LocalEditor({ onPendingChange }: {
    onPendingChange?: (state: { blocked: boolean; reason: string | null }) => void;
  }) {
    const [draft, setDraft] = useState("");
    return (
      <input
        aria-label="미반영 좌표"
        value={draft}
        onChange={(event) => {
          setDraft(event.target.value);
          onPendingChange?.({ blocked: true, reason: "지도에 반영하지 않은 좌표가 있습니다." });
        }}
      />
    );
  }
  return {
    AoiPolygonMap: ({ readOnly, onPendingChange }: {
      readOnly?: boolean;
      onPendingChange?: (state: { blocked: boolean; reason: string | null }) => void;
    }) => readOnly ? <p>읽기 전용 지도</p> : <LocalEditor onPendingChange={onPendingChange} />,
  };
});

const area: WorkArea = {
  schemaVersion: "1.0",
  workAreaId: "area-1",
  siteId: "site-1",
  name: "합성 구역",
  polygon: { type: "Polygon", coordinates: [[[127, 37.5], [127.1, 37.5], [127, 37.6], [127, 37.5]]] },
  crs: "EPSG:4326",
  status: "ACTIVE",
  supersedes: null,
  createdAt: "2026-09-01T00:00:00Z",
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); window.sessionStorage.clear(); });

const FP = `v1-${"a".repeat(64)}`;

function isIdentity(url: unknown): boolean {
  return String(url).includes("/api/account-identity");
}

function identityResponse(): Response {
  return new Response(JSON.stringify({ fingerprint: FP }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function postCalls(fetchMock: ReturnType<typeof vi.fn>): unknown[][] {
  return fetchMock.mock.calls.filter((call) => {
    const init = call[1] as RequestInit | undefined;
    return init?.method === "POST";
  });
}

async function awaitReady(): Promise<void> {
  await screen.findByText(/이름과 경계 편집 원문/);
}

describe("다른 구역 보관 중 미반영 경계", () => {
  it("보관이 실패해도 미반영 입력을 조용히 버리지 않는다", async () => {
    window.sessionStorage.clear();
    let reply: (response: unknown) => void = () => {};
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return identityResponse();
      if (init?.method === "POST") return new Promise((resolve) => { reply = resolve; });
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[area]} workAreaListError={null} accountIdentity={{ fingerprint: FP }} />);
    await awaitReady();
    fireEvent.change(screen.getByLabelText("미반영 좌표"), { target: { value: "입력 B" } });

    const archive = screen.getByRole("button", { name: "구역 보관" }) as HTMLButtonElement;
    if (archive.disabled) {
      expect(screen.getByText(/입력 중인 경계를 반영하거나 되돌린 뒤 구역을 보관/)).toBeTruthy();
      fireEvent.click(archive);
      expect((screen.getByLabelText("미반영 좌표") as HTMLInputElement).value).toBe("입력 B");
      expect(postCalls(fetchMock)).toHaveLength(0);
      return;
    }
    fireEvent.click(archive);
    const dialog = screen.getByRole("dialog", { name: "구역을 보관할까요?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "구역 보관" }));
    await waitFor(() => expect(postCalls(fetchMock)).toHaveLength(1));
    reply({ ok: false, status: 403, json: async () => ({}) });
    await waitFor(() => expect(screen.getByText(/작업구역 보관에 실패했습니다/)).toBeTruthy());
    expect((screen.getByLabelText("미반영 좌표") as HTMLInputElement).value).toBe("입력 B");
  });
});
