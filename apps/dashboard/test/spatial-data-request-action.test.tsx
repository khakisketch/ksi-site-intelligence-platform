/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

import { SpatialDataRequestAction } from "@/app/sites/[siteId]/spatial-assets/SpatialDataRequestAction";

const grid = { transform: [1, 0, 200000, 0, -1, 550000], width: 1024, height: 1024 };
const digest = `sha256:${"a".repeat(64)}`;

function renderAction(overrides: Partial<Parameters<typeof SpatialDataRequestAction>[0]> = {}) {
  return render(
    <SpatialDataRequestAction
      siteId="site-1"
      workAreaId="area-1"
      assetRef={`ksa-v1-${"b".repeat(64)}`}
      inspectedRaster={grid}
      observedCrsIdentifier="EPSG:7850"
      observedCrsDigest={digest}
      canRequest
      {...overrides}
    />,
  );
}

function center512Body() {
  return {
    assetRef: `ksa-v1-${"b".repeat(64)}`,
    // 가운데 512×512 창(원점 256, 256)에서 유도된 정확한 네이티브 사각형.
    requestedBounds: [200256, 549232, 200768, 549744],
    observedCrsDigest: digest,
    resolutionMode: "NATIVE",
    purpose: "GENERAL_DATA_USE",
  };
}

function queuedResponse(jobId: string) {
  return new Response(JSON.stringify({ jobId, executionState: "QUEUED", availability: "NOT_READY", assetRef: `ksa-v1-${"b".repeat(64)}`, siteId: "site-1", workAreaId: "area-1", createdAt: "2026-10-18T01:00:00Z" }), { status: 201, headers: { "content-type": "application/json" } });
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("spatial data request action", () => {
  it("posts the bounded window derived from the inspected grid with one stable idempotency key", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return queuedResponse("sdj-v1-00000000-0000-0000-0000-000000000001");
    }));

    renderAction();
    // 기본 가운데 512×512 창과 유도된 요청 범위를 그대로 보여준다.
    expect(screen.getByText(/원점 256, 256/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "받기 요청 만들기" }));
    await screen.findByText(/받기 요청을 만들었습니다/);

    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/api/sites/site-1/work-areas/area-1/spatial-data-requests");
    const body = JSON.parse(calls[0].init.body as string) as Record<string, unknown>;
    expect(body).toEqual(center512Body());
    const key = (calls[0].init.headers as Record<string, string>)["Idempotency-Key"];
    expect(key).toMatch(/^sdreq-[0-9a-f-]{36}$/);
    // 같은 요청을 다시 만들지 않는다 — 성공 뒤 버튼은 잠긴다.
    expect(screen.getByRole("button", { name: "요청 만듦" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("link", { name: "구역 자료 준비에서 확인" }).getAttribute("href"))
      .toBe("/sites/site-1/spatial-data-requests?workAreaId=area-1");
  });

  it("sends the edited window, not the full inspected bounds", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return queuedResponse("sdj-v1-00000000-0000-0000-0000-000000000002");
    }));

    renderAction();
    fireEvent.change(screen.getByLabelText(/너비/), { target: { value: "128" } });
    fireEvent.change(screen.getByLabelText(/높이/), { target: { value: "64" } });
    fireEvent.change(screen.getByLabelText(/원점 열/), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText(/원점 행/), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "받기 요청 만들기" }));
    await screen.findByText(/받기 요청을 만들었습니다/);

    const body = JSON.parse(calls[0].init.body as string) as Record<string, unknown>;
    expect(body.requestedBounds).toEqual([200000, 549936, 200128, 550000]);
  });

  it("requests a tiny 2x3 grid whole without a fictitious minimum", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return queuedResponse("sdj-v1-00000000-0000-0000-0000-000000000003");
    }));

    renderAction({ inspectedRaster: { transform: [1, 0, 200000, 0, -1, 550000], width: 2, height: 3 } });
    expect(screen.getByText(/너비 2 × 높이 3/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "받기 요청 만들기" }));
    await screen.findByText(/받기 요청을 만들었습니다/);

    const body = JSON.parse(calls[0].init.body as string) as Record<string, unknown>;
    expect(body.requestedBounds).toEqual([200000, 549997, 200002, 550000]);
  });

  it("requests a 64x64 grid whole and keeps the whole-grid shortcut honest", async () => {
    const calls: Array<{ url: string; init: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return queuedResponse("sdj-v1-00000000-0000-0000-0000-000000000004");
    }));

    renderAction({ inspectedRaster: { transform: [0.5, 0, 100000, 0, -0.5, 200000], width: 64, height: 64 } });
    fireEvent.click(screen.getByRole("button", { name: "전체 격자 사용" }));
    fireEvent.click(screen.getByRole("button", { name: "받기 요청 만들기" }));
    await screen.findByText(/받기 요청을 만들었습니다/);

    const body = JSON.parse(calls[0].init.body as string) as Record<string, unknown>;
    expect(body.requestedBounds).toEqual([100000, 199968, 100032, 200000]);
  });

  it("fits a narrow grid without oversize and disables the whole-grid shortcut", () => {
    renderAction({ inspectedRaster: { transform: [1, 0, 0, 0, -1, 2000], width: 100, height: 2000 } });
    expect(screen.getByText(/너비 100 × 높이 512/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "전체 격자 사용" }).hasAttribute("disabled")).toBe(true);
  });

  it("blocks an oversized width with a truthful message and no request", async () => {
    const fetchSpy = vi.fn(async () => new Response("{}", { status: 201 }));
    vi.stubGlobal("fetch", fetchSpy);

    renderAction();
    fireEvent.change(screen.getByLabelText(/너비/), { target: { value: "513" } });
    expect(screen.getByText(/너비·높이는 1 이상 512 이하의 정수/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "받기 요청 만들기" }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "받기 요청 만들기" }));
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("blocks an out-of-bounds window with a truthful message and no request", async () => {
    const fetchSpy = vi.fn(async () => new Response("{}", { status: 201 }));
    vi.stubGlobal("fetch", fetchSpy);

    renderAction();
    fireEvent.change(screen.getByLabelText(/원점 열/), { target: { value: "900" } });
    expect(screen.getByText(/픽셀 창이 검사 격자를 벗어납니다/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "받기 요청 만들기" }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "받기 요청 만들기" }));
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("explains a missing inspection without inventing bounds", () => {
    renderAction({ inspectedRaster: null, observedCrsIdentifier: null, observedCrsDigest: null });
    expect(screen.getByText(/검사된 격자 정보를 확인하지 못해/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "받기 요청 만들기" }).hasAttribute("disabled")).toBe(true);
  });

  it("explains a rotated grid without inventing bounds", () => {
    renderAction({ inspectedRaster: { transform: [1, 0.2, 200000, 0.2, -1, 550000], width: 1024, height: 1024 } });
    expect(screen.getByText(/회전되거나 비표준 격자/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "받기 요청 만들기" }).hasAttribute("disabled")).toBe(true);
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

  it("explains the permission requirement in a popover instead of a dead control", () => {
    renderAction({ canRequest: false });
    const trigger = screen.getByRole("button", { name: "자료 받기 요청" });
    expect(trigger.hasAttribute("disabled")).toBe(false);
    expect(screen.queryByText(/자료 받기 요청은 권한 있는 담당자가 만들 수 있습니다/)).toBeNull();
    fireEvent.click(trigger);
    expect(screen.getByText(/자료 받기 요청은 권한 있는 담당자가 만들 수 있습니다/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "받기 요청 만들기" })).toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText(/자료 받기 요청은 권한 있는 담당자가 만들 수 있습니다/)).toBeNull();
  });

  it("labels the request and actual bounds as separate facts", () => {
    renderAction();
    const section = screen.getByText("이 자료 받기 요청").closest("section")!;
    expect(within(section).getByText(/요청 범위\(네이티브 좌표\)/)).toBeTruthy();
    expect(within(section).getByText(/실제 출력 범위는 준비가 끝난 뒤/)).toBeTruthy();
  });
});
