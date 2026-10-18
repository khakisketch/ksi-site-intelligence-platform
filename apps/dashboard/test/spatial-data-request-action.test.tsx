/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

import { SpatialDataRequestAction } from "@/app/sites/[siteId]/spatial-assets/SpatialDataRequestAction";

const bounds: [number, number, number, number] = [200000, 549968, 200032, 550000];
const digest = `sha256:${"a".repeat(64)}`;

function renderAction(overrides: Partial<Parameters<typeof SpatialDataRequestAction>[0]> = {}) {
  return render(
    <SpatialDataRequestAction
      siteId="site-1"
      workAreaId="area-1"
      assetRef={`ksa-v1-${"b".repeat(64)}`}
      requestedBounds={bounds}
      observedCrsDigest={digest}
      canRequest
      {...overrides}
    />,
  );
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("spatial data request action", () => {
  it("posts the exact native rectangle with one stable idempotency key", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify({ jobId: "sdj-v1-00000000-0000-0000-0000-000000000001", executionState: "QUEUED", availability: "NOT_READY", assetRef: `ksa-v1-${"b".repeat(64)}`, siteId: "site-1", workAreaId: "area-1", createdAt: "2026-10-18T01:00:00Z" }), { status: 201, headers: { "content-type": "application/json" } });
    }));

    renderAction();
    fireEvent.click(screen.getByRole("button", { name: "받기 요청 만들기" }));
    await screen.findByText(/받기 요청을 만들었습니다/);

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/api/sites/site-1/work-areas/area-1/spatial-data-requests");
    const body = JSON.parse(calls[0].init.body as string) as Record<string, unknown>;
    expect(body).toEqual({
      assetRef: `ksa-v1-${"b".repeat(64)}`,
      requestedBounds: bounds,
      observedCrsDigest: digest,
      resolutionMode: "NATIVE",
      purpose: "GENERAL_DATA_USE",
    });
    const key = (calls[0].init.headers as Record<string, string>)["Idempotency-Key"];
    expect(key).toMatch(/^sdreq-[0-9a-f-]{36}$/);
    // 같은 요청을 다시 만들지 않는다 — 성공 뒤 버튼은 잠긴다.
    expect(screen.getByRole("button", { name: "요청 만듦" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("link", { name: "구역 자료 준비에서 확인" }).getAttribute("href"))
      .toBe("/sites/site-1/spatial-data-requests?workAreaId=area-1");
  });

  it("translates Core's typed rights denial without inventing success", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ code: "GRANT_REQUIRED", reason: "GRANT_REQUIRED" }), { status: 403, headers: { "content-type": "application/json" } })));

    renderAction();
    fireEvent.click(screen.getByRole("button", { name: "받기 요청 만들기" }));
    await screen.findByText(/명시적 사용 권리가 아직 없습니다/);
    expect(screen.queryByText(/받기 요청을 만들었습니다/)).toBeNull();
    expect(screen.getByRole("button", { name: "받기 요청 만들기" }).hasAttribute("disabled")).toBe(false);
  });

  it("keeps an uncertain failure retryable with the same identity", async () => {
    const keys: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => {
      keys.push((init.headers as Record<string, string>)["Idempotency-Key"]);
      throw new Error("network down");
    }));

    renderAction();
    fireEvent.click(screen.getByRole("button", { name: "받기 요청 만들기" }));
    await screen.findByText(/Core 응답을 받지 못했습니다/);
    fireEvent.click(screen.getByRole("button", { name: "받기 요청 만들기" }));
    await waitFor(() => expect(keys).toHaveLength(2));
    expect(keys[0]).toBe(keys[1]);
  });

  it("explains the permission requirement instead of showing a dead control", () => {
    renderAction({ canRequest: false });
    expect(screen.getByText(/자료 받기 요청은 권한 있는 담당자가 만들 수 있습니다/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "받기 요청 만들기" })).toBeNull();
  });
});
