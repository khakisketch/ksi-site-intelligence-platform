/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); window.sessionStorage.clear(); notifyMock.mockClear(); });

const FP_A = `v1-${"a".repeat(64)}`;

function isIdentity(url: unknown): boolean {
  return String(url).includes("/api/account-identity");
}

function identityOk(fingerprint: string = FP_A): Response {
  return new Response(JSON.stringify({ fingerprint }), {
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

describe("WorkAreaPanel archive confirmation", () => {
  it("does not emit an archive toast outside the panel after the account changes during a delayed response", async () => {
    let fingerprint = FP_A;
    let resolveArchive!: (value: Response) => void;
    const fetchMock = vi.fn((url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return Promise.resolve(identityOk(fingerprint));
      if (init?.method === "POST") return new Promise<Response>((resolve) => { resolveArchive = resolve; });
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={{ fingerprint: FP_A }} />);
    await awaitReady();
    fireEvent.click(screen.getByRole("button", { name: "구역 보관" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "구역 보관" }));
    await waitFor(() => expect(postCalls(fetchMock)).toHaveLength(1));
    fireEvent.blur(window);
    fingerprint = `v1-${"b".repeat(64)}`;
    fireEvent.focus(window);
    await screen.findByText(/현재 계정을 확인하지 못해 입력을 숨겼습니다/);
    await act(async () => resolveArchive(new Response(JSON.stringify({ workArea: { ...activeArea(), status: "ARCHIVED" } }), { status: 200 })));
    expect(notifyMock).not.toHaveBeenCalled();
  });

  it.each(["success", "failure", "lost"])("rechecks the authorized list after an interrupted %s response, including A → B → A", async (outcome) => {
    let fingerprint = FP_A;
    let resolveArchive!: (value: Response) => void;
    let rejectArchive!: (reason: Error) => void;
    let resolveList!: (value: Response) => void;
    const fetchMock = vi.fn((url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return Promise.resolve(identityOk(fingerprint));
      if (init?.method === "POST") return new Promise<Response>((resolve, reject) => { resolveArchive = resolve; rejectArchive = reject; });
      if (String(url).includes("include_archived")) return new Promise<Response>((resolve) => { resolveList = resolve; });
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={{ fingerprint: FP_A }} />);
    await awaitReady();
    fireEvent.click(screen.getByRole("button", { name: "구역 보관" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "구역 보관" }));
    await waitFor(() => expect(postCalls(fetchMock)).toHaveLength(1));
    fireEvent.blur(window);
    fingerprint = `v1-${"b".repeat(64)}`;
    fireEvent.focus(window);
    await screen.findByText(/현재 계정을 확인하지 못해 입력을 숨겼습니다/);
    fireEvent.blur(window);
    fingerprint = FP_A;
    fireEvent.focus(window);
    await act(async () => {
      if (outcome === "lost") rejectArchive(new Error("response lost"));
      else resolveArchive(new Response(JSON.stringify(outcome === "success" ? {workArea: {...activeArea(), status: "ARCHIVED"}} : {message: "A의 민감한 오류"}), {status: outcome === "success" ? 200 : 503}));
    });
    await waitFor(() => expect(resolveList).toBeTypeOf("function"));
    expect(screen.queryByRole("button", {name: "구역 보관"})).toBeNull();
    await act(async () => resolveList(new Response(JSON.stringify({workAreas: [{...activeArea(), status: "ARCHIVED"}]}), {status: 200})));
    await awaitReady();
    expect(notifyMock).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain("A의 민감한 오류");
    expect(postCalls(fetchMock)).toHaveLength(1);
    expect(screen.queryByRole("button", {name: "구역 보관"})).toBeNull();
  });

  it("discards an interrupted recovery list and keeps the panel concealed on a failed reread", async () => {
    let resolveArchive!: (value: Response) => void;
    const listResolvers: Array<(value: Response) => void> = [];
    const fetchMock = vi.fn((url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return Promise.resolve(identityOk());
      if (init?.method === "POST") return new Promise<Response>((resolve) => { resolveArchive = resolve; });
      if (String(url).includes("include_archived")) return new Promise<Response>((resolve) => listResolvers.push(resolve));
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={{fingerprint: FP_A}} />);
    await awaitReady();
    fireEvent.click(screen.getByRole("button", {name: "구역 보관"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", {name: "구역 보관"}));
    await waitFor(() => expect(postCalls(fetchMock)).toHaveLength(1));
    fireEvent.blur(window);
    await act(async () => resolveArchive(new Response("{}", {status: 503})));
    fireEvent.focus(window);
    await waitFor(() => expect(listResolvers).toHaveLength(1));
    fireEvent.blur(window);
    fireEvent.focus(window);
    await waitFor(() => expect(listResolvers).toHaveLength(2));
    await act(async () => listResolvers[0]!(new Response(JSON.stringify({workAreas: [activeArea("오래된 목록")]}), {status: 200})));
    expect(document.body.textContent).not.toContain("오래된 목록");
    await act(async () => listResolvers[1]!(new Response("{}", {status: 503})));
    await screen.findByText(/현재 계정을 확인하지 못해 입력을 숨겼습니다/);
    expect(screen.queryByRole("button", {name: "구역 보관"})).toBeNull();
    expect(postCalls(fetchMock)).toHaveLength(1);
    expect(notifyMock).not.toHaveBeenCalled();
  });

  it.each(["hidden", "unmount"])("suppresses delayed archive results after %s", async (transition) => {
    let resolveArchive!: (value: Response) => void;
    const fetchMock = vi.fn((url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return Promise.resolve(identityOk());
      if (init?.method === "POST") return new Promise<Response>((resolve) => { resolveArchive = resolve; });
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={{fingerprint: FP_A}} />);
    await awaitReady();
    fireEvent.click(screen.getByRole("button", {name: "구역 보관"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", {name: "구역 보관"}));
    await waitFor(() => expect(postCalls(fetchMock)).toHaveLength(1));
    if (transition === "hidden") {
      vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
      fireEvent(document, new Event("visibilitychange"));
    } else view.unmount();
    await act(async () => resolveArchive(new Response(JSON.stringify({workArea: {...activeArea(), status: "ARCHIVED"}}), {status: 200})));
    expect(notifyMock).not.toHaveBeenCalled();
    expect(postCalls(fetchMock)).toHaveLength(1);
    vi.restoreAllMocks();
  });

  it("preserves the draft and separates a refused 409 from an earlier lost archive response", async () => {
    let identity = FP_A;
    let attempts = 0;
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return identityOk(identity);
      if (String(url).includes("include_archived")) return Response.json({workAreas: [activeArea()]});
      if (init?.method === "POST") {
        attempts++;
        if (attempts === 1) throw new Error("response lost");
        identity = `v1-${"b".repeat(64)}`;
        return Response.json({code: "ACCOUNT_CONTINUITY_MISMATCH"}, {status: 409});
      }
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={{fingerprint: FP_A}} />);
    await awaitReady();
    fireEvent.change(screen.getByPlaceholderText("3공구 성토부"), {target: {value: "보존할 초안"}});
    fireEvent.click(screen.getByRole("button", {name: "구역 보관"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", {name: "구역 보관"}));
    await screen.findByText(/보관 결과를 확인하지 못했습니다/);
    fireEvent.click(screen.getByRole("button", {name: "보관 다시 시도"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", {name: "구역 보관"}));
    await screen.findByText(/현재 계정을 확인하지 못해 입력을 숨겼습니다/);
    expect(notifyMock).not.toHaveBeenCalled();
    identity = FP_A;
    fireEvent.focus(window);
    await awaitReady();
    expect(screen.getByText(/이번 보관 요청을 보내지 않았습니다. 이전 요청의 결과는 별도로 목록에서 확인하세요/)).toBeTruthy();
    expect((screen.getByPlaceholderText("3공구 성토부") as HTMLInputElement).value).toBe("보존할 초안");
    expect(postCalls(fetchMock)).toHaveLength(2);
  });

  it.each([null, {fingerprint: "bad"}])("does not send an archive with an unverified screen identity %s", async (accountIdentity) => {
    const fetchMock = vi.fn(async () => identityOk());
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={accountIdentity} />);
    await screen.findByText(/계정 또는 임시 저장 내용을 확인하지 못했습니다/);
    expect(screen.queryByRole("button", {name: "구역 보관"})).toBeNull();
    expect(postCalls(fetchMock)).toHaveLength(0);
  });

  it.each([
    ["other area", {verdict: "ARCHIVED", workArea: {...activeArea(), workAreaId: "other", status: "ARCHIVED", name: "다른 구역"}}],
    ["other site", {verdict: "ARCHIVED", workArea: {...activeArea(), siteId: "other", status: "ARCHIVED"}}],
    ["active", {verdict: "ARCHIVED", workArea: activeArea()}],
    ["changed name", {verdict: "ARCHIVED", workArea: {...activeArea(), name: "잘못된 이름", status: "ARCHIVED"}}],
    ["changed geometry", {verdict: "ARCHIVED", workArea: {...activeArea(), polygon: {type:"Polygon", coordinates:[]}, status: "ARCHIVED"}}],
    ["missing fields", {verdict: "ARCHIVED", workArea: {siteId:"site-1", workAreaId:"area-1", status:"ARCHIVED"}}],
    ["missing body", {}],
    ["missing verdict", {workArea:{...activeArea(),status:"ARCHIVED"}}],
    ["changed CRS", {verdict:"ARCHIVED", workArea:{...activeArea(), crs:"EPSG:3857", status:"ARCHIVED"}}],
    ["changed creation time", {verdict:"ARCHIVED", workArea:{...activeArea(), createdAt:"2020-01-01", status:"ARCHIVED"}}],
    ["changed supersedes", {verdict:"ARCHIVED", workArea:{...activeArea(), supersedes:"other", status:"ARCHIVED"}}],
    ["bad verdict", {verdict:"REGISTERED", workArea:{...activeArea(),status:"ARCHIVED"}}],
  ])("treats a 2xx %s archive echo as unconfirmed", async (_label, body) => {
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return identityOk();
      if (init?.method === "POST") return Response.json(body);
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={{fingerprint: FP_A}} />);
    await awaitReady();
    fireEvent.click(screen.getByRole("button", {name: "구역 보관"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", {name: "구역 보관"}));
    await screen.findByText(/보관 결과를 확인하지 못했습니다/);
    expect(notifyMock).not.toHaveBeenCalled();
    expect(screen.getByText("동측 절토면")).toBeTruthy();
    expect(document.body.textContent).not.toContain("잘못된 이름");
    expect(document.body.textContent).not.toContain("다른 구역");
    expect(postCalls(fetchMock)).toHaveLength(1);
  });

  it("does not claim failure or success when the 2xx response body is truncated", async () => {
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return identityOk();
      if (init?.method === "POST") return new Response('{"verdict":"ARCHIVED","workArea":', {status:200});
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={{fingerprint: FP_A}} />);
    await awaitReady();
    fireEvent.click(screen.getByRole("button", {name: "구역 보관"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", {name: "구역 보관"}));
    const message = await screen.findByText(/보관 결과를 확인하지 못했습니다/);
    expect(message.textContent).not.toContain("실패");
    expect(notifyMock).not.toHaveBeenCalled();
    expect(postCalls(fetchMock)).toHaveLength(1);
  });

  it("keeps an earlier commit-then-503 unconfirmed when a later attempt is rejected", async () => {
    let committed = false;
    let calls = 0;
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return identityOk();
      if (init?.method === "POST") {
        calls++;
        if (calls === 1) { committed = true; return Response.json({message:"gateway error"}, {status:503}); }
        return Response.json({code:"MISSING_SESSION", message:"세션이 만료되었습니다."}, {status:401});
      }
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={{fingerprint: FP_A}} />);
    await awaitReady();
    fireEvent.click(screen.getByRole("button", {name:"구역 보관"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", {name:"구역 보관"}));
    await screen.findByText(/보관 결과를 확인하지 못했습니다/);
    expect(committed).toBe(true); expect(notifyMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", {name:"보관 다시 시도"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", {name:"구역 보관"}));
    await screen.findByText(/이번 보관 요청/);
    expect(screen.getAllByText(/이전.*결과.*확인/).length).toBeGreaterThan(0);
    expect(postCalls(fetchMock)).toHaveLength(2);
    expect(notifyMock).not.toHaveBeenCalled();
  });

  it("rereads the current list after a simulated commit and 503 without claiming the earlier request succeeded", async () => {
    let committed = false;
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return identityOk();
      if (init?.method === "POST") { committed = true; return Response.json({message:"gateway"}, {status:503}); }
      if (String(url).includes("include_archived")) return Response.json({workAreas:[{...activeArea(), status: committed ? "ARCHIVED" : "ACTIVE"}]});
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={{fingerprint: FP_A}} />);
    await awaitReady();
    fireEvent.click(screen.getByRole("button", {name:"구역 보관"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", {name:"구역 보관"}));
    await screen.findByText(/보관 결과를 확인하지 못했습니다/);
    fireEvent.click(screen.getByRole("button", {name:"보관 상태 목록 다시 읽기"}));
    await screen.findByText(/이 목록은 조회 시점의 상태이며 이전 요청의 최종 결과를 증명하지 않습니다/);
    expect(screen.getByText("보관됨")).toBeTruthy();
    expect(screen.getByText(/이전 보관 요청의 결과가 미확인/)).toBeTruthy();
    expect(postCalls(fetchMock)).toHaveLength(1);
    expect(notifyMock).not.toHaveBeenCalled();
  });

  it.each([500, 502, 503, 504])( "treats HTTP %i as unconfirmed without another POST", async (status) => {
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return identityOk();
      if (init?.method === "POST") return Response.json({message:"실패했습니다"}, {status});
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={{fingerprint: FP_A}} />);
    await awaitReady();
    fireEvent.click(screen.getByRole("button", {name:"구역 보관"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", {name:"구역 보관"}));
    expect((await screen.findByText(/보관 결과를 확인하지 못했습니다/)).textContent).not.toContain("실패했습니다");
    expect(postCalls(fetchMock)).toHaveLength(1);
    expect(notifyMock).not.toHaveBeenCalled();
  });

  it("discards a delayed archive-list read after identity invalidation", async () => {
    let resolveList!: (response: Response) => void;
    const fetchMock = vi.fn((url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return Promise.resolve(identityOk());
      if (init?.method === "POST") return Promise.resolve(new Response("{}", {status:503}));
      if (String(url).includes("include_archived")) return new Promise<Response>(resolve => {resolveList = resolve;});
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={{fingerprint: FP_A}} />);
    await awaitReady();
    fireEvent.click(screen.getByRole("button", {name:"구역 보관"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", {name:"구역 보관"}));
    await screen.findByText(/보관 결과를 확인하지 못했습니다/);
    fireEvent.click(screen.getByRole("button", {name:"보관 상태 목록 다시 읽기"}));
    await waitFor(() => expect(resolveList).toBeTypeOf("function"));
    fireEvent.blur(window);
    await act(async () => resolveList(Response.json({workAreas:[activeArea("늦은 다른 목록")]})));
    expect(document.body.textContent).not.toContain("늦은 다른 목록");
    expect(notifyMock).not.toHaveBeenCalled();
    expect(postCalls(fetchMock)).toHaveLength(1);
  });

  it("restores an unconfirmed archive target after unmount and reload without sending again", async () => {
    let committed = false;
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return identityOk();
      if (init?.method === "POST") { committed = true; throw new Error("lost response"); }
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const props = {siteId:"site-1", siteCrs:"EPSG:4326", canWrite:true, initialWorkAreas:[activeArea()], workAreaListError:null, accountIdentity:{fingerprint:FP_A}};
    const view = render(<WorkAreaPanel {...props} />);
    await awaitReady();
    fireEvent.click(screen.getByRole("button", {name:"구역 보관"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", {name:"구역 보관"}));
    await screen.findByText(/보관 결과를 확인하지 못했습니다/);
    expect(committed).toBe(true);
    view.unmount();
    render(<WorkAreaPanel {...props} initialWorkAreas={[]} />);
    await awaitReady();
    expect(screen.getByText(/이전 보관 요청의 결과가 미확인/)).toBeTruthy();
    expect(screen.getByText(/동측 절토면/)).toBeTruthy();
    expect(postCalls(fetchMock)).toHaveLength(1);
  });

  it("restores only the original account and site after a lost response and a new explicit attempt", async () => {
    let fingerprint = FP_A;
    let attempts = 0;
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return identityOk(fingerprint);
      if (init?.method === "POST") { attempts++; if (attempts === 1) throw new Error("lost"); return Response.json({code:"ALREADY_ARCHIVED"}, {status:409}); }
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const props = {siteId:"site-1", siteCrs:"EPSG:4326", canWrite:true, initialWorkAreas:[activeArea()], workAreaListError:null, accountIdentity:{fingerprint:FP_A}};
    const a = render(<WorkAreaPanel {...props} />);
    await awaitReady();
    fireEvent.click(screen.getByRole("button", {name:"구역 보관"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", {name:"구역 보관"}));
    await screen.findByText(/보관 결과를 확인하지 못했습니다/);
    fireEvent.click(screen.getByRole("button", {name:"보관 다시 시도"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", {name:"구역 보관"}));
    await screen.findByText(/이 시도 거부/);
    expect(screen.getByText(/시도 1: 동측 절토면.*결과 미확인/)).toBeTruthy();
    a.unmount();
    fingerprint = `v1-${"b".repeat(64)}`;
    const b = render(<WorkAreaPanel {...props} accountIdentity={{fingerprint}} initialWorkAreas={[]} />);
    await awaitReady();
    expect(screen.queryByText(/동측 절토면/)).toBeNull();
    b.unmount();
    fingerprint = FP_A;
    const other = render(<WorkAreaPanel {...props} siteId="site-2" initialWorkAreas={[]} />);
    await awaitReady();
    expect(screen.queryByText(/동측 절토면/)).toBeNull();
    other.unmount();
    render(<WorkAreaPanel {...props} initialWorkAreas={[]} />);
    await awaitReady();
    expect(screen.getByText(/시도 1: 동측 절토면.*결과 미확인/)).toBeTruthy();
    expect(screen.getByText(/시도 2: 동측 절토면.*이 시도 거부/)).toBeTruthy();
    expect(postCalls(fetchMock)).toHaveLength(2);
  });

  it("does not POST when archive write-ahead storage fails", async () => {
    const fetchMock = vi.fn(async () => identityOk());
    vi.stubGlobal("fetch", fetchMock);
    const set = vi.spyOn(Storage.prototype, "setItem");
    const actual = set.getMockImplementation();
    set.mockImplementation(function(this: Storage, key: string, value: string) {
      if (key.startsWith("ksi.work-area.archive.v1:")) throw new Error("quota");
      return actual?.call(this,key,value);
    });
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={{fingerprint: FP_A}} />);
    await awaitReady();
    fireEvent.click(screen.getByRole("button", {name:"구역 보관"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", {name:"구역 보관"}));
    await screen.findByText(/기록을 안전하게 저장하지 못해 이번 요청을 보내지 않았습니다/);
    expect(postCalls(fetchMock)).toHaveLength(0);
    set.mockRestore();
  });

  it("does not overwrite an unsupported archive record", async () => {
    const key = `ksi.work-area.archive.v1:site-1:${FP_A}:not-supported`;
    window.sessionStorage.setItem(key, '{"version":99}');
    const fetchMock = vi.fn(async () => identityOk()); vi.stubGlobal("fetch",fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={{fingerprint: FP_A}} />);
    await screen.findByText(/계정 또는 임시 저장 내용을 확인하지 못했습니다/);
    expect(window.sessionStorage.getItem(key)).toBe('{"version":99}');
    expect(postCalls(fetchMock)).toHaveLength(0);
  });

  it("writes ahead once for repeated confirmation clicks and restores a late response after unmount", async () => {
    let resolve!: (response: Response) => void;
    const fetchMock = vi.fn((url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return Promise.resolve(identityOk());
      if (init?.method === "POST") return new Promise<Response>(done => {resolve=done;});
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch",fetchMock);
    const props={siteId:"site-1",siteCrs:"EPSG:4326",canWrite:true,initialWorkAreas:[activeArea()],workAreaListError:null,accountIdentity:{fingerprint:FP_A}};
    const first=render(<WorkAreaPanel {...props} />); await awaitReady();
    fireEvent.click(screen.getByRole("button",{name:"구역 보관"}));
    const confirm=within(screen.getByRole("dialog")).getByRole("button",{name:"구역 보관"});
    fireEvent.click(confirm); fireEvent.click(confirm);
    expect(postCalls(fetchMock)).toHaveLength(1);
    first.unmount();
    await act(async () => resolve(Response.json({verdict:"ARCHIVED",workArea:{...activeArea(),status:"ARCHIVED"}})));
    render(<WorkAreaPanel {...props} initialWorkAreas={[]} />); await awaitReady();
    expect(screen.getByText(/시도 1: 동측 절토면.*결과 미확인/)).toBeTruthy();
    expect(postCalls(fetchMock)).toHaveLength(1); expect(notifyMock).not.toHaveBeenCalled();
  });

  it("keeps a partial archive write and sends no POST on either attempt", async () => {
    const fetchMock = vi.fn(async () => identityOk()); vi.stubGlobal("fetch", fetchMock);
    const realSet = Storage.prototype.setItem;
    const set = vi.spyOn(Storage.prototype,"setItem").mockImplementation(function(this: Storage,key:string,value:string) {
      return realSet.call(this,key,key.startsWith("ksi.work-area.archive.v1:") ? "{" : value);
    });
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={{fingerprint:FP_A}} />);
    await awaitReady();
    fireEvent.click(screen.getByRole("button",{name:"구역 보관"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button",{name:"구역 보관"}));
    await screen.findByText(/기록을 안전하게 저장하지 못해/);
    fireEvent.click(screen.getByRole("button",{name:"보관 다시 시도"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button",{name:"구역 보관"}));
    expect(postCalls(fetchMock)).toHaveLength(0);
    expect(Object.keys(window.sessionStorage).some(key => key.startsWith("ksi.work-area.archive.v1:") && window.sessionStorage.getItem(key) === "{")).toBe(true);
    set.mockRestore();
  });

  it.each(["success", "rejected"])("warns when the %s receipt cannot be stored while keeping an earlier unknown", async (outcome) => {
    let calls = 0;
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return identityOk();
      if (init?.method === "POST") {
        calls++;
        if (calls === 1) throw new Error("lost");
        return outcome === "success"
          ? Response.json({verdict:"ARCHIVED",workArea:{...activeArea(),status:"ARCHIVED"}})
          : Response.json({message:"권한이 없습니다"},{status:403});
      }
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch",fetchMock);
    const props={siteId:"site-1",siteCrs:"EPSG:4326",canWrite:true,initialWorkAreas:[activeArea()],workAreaListError:null,accountIdentity:{fingerprint:FP_A}};
    const view=render(<WorkAreaPanel {...props} />); await awaitReady();
    fireEvent.click(screen.getByRole("button",{name:"구역 보관"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button",{name:"구역 보관"}));
    await screen.findByText(/보관 결과를 확인하지 못했습니다/);
    const original = Storage.prototype.setItem;
    const spy = vi.spyOn(Storage.prototype,"setItem").mockImplementation(function(this: Storage, key:string, value:string) {
      if (key.startsWith("ksi.work-area.archive.v1:") && key.endsWith(":result")) throw new Error("quota");
      return original.call(this,key,value);
    });
    fireEvent.click(screen.getByRole("button",{name:"보관 다시 시도"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button",{name:"구역 보관"}));
    const warning = await screen.findByText(/이번 응답이 탭 기록에 저장됐는지 확인하지 못했습니다/);
    expect(warning.textContent).toContain(outcome === "success" ? "보관 성공 응답을 확인했습니다" : "요청 거부 응답을 확인했습니다");
    expect(warning.textContent).toContain("탭을 닫으면 사라질 수 있습니다");
    expect(screen.getByText(/시도 1: 동측 절토면.*결과 미확인/)).toBeTruthy();
    expect(postCalls(fetchMock)).toHaveLength(2);
    view.unmount(); spy.mockRestore();
    render(<WorkAreaPanel {...props} initialWorkAreas={[]} />); await awaitReady();
    expect(screen.getByText(/시도 1: 동측 절토면.*결과 미확인/)).toBeTruthy();
    expect(screen.getByText(/시도 2: 동측 절토면.*결과 미확인/)).toBeTruthy();
    expect(postCalls(fetchMock)).toHaveLength(2);
  });

  it.each(["success", "rejected"])("reports ambiguous %s receipt readback without rewriting the original", async (outcome) => {
    let calls = 0;
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return identityOk();
      if (init?.method === "POST") { calls++; return outcome === "success" ? Response.json({verdict:"ARCHIVED",workArea:{...activeArea(),status:"ARCHIVED"}}) : Response.json({message:"권한이 없습니다"},{status:403}); }
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch",fetchMock);
    const props={siteId:"site-1",siteCrs:"EPSG:4326",canWrite:true,initialWorkAreas:[activeArea()],workAreaListError:null,accountIdentity:{fingerprint:FP_A}};
    const view=render(<WorkAreaPanel {...props} />); await awaitReady();
    const originalSet = Storage.prototype.setItem, originalGet = Storage.prototype.getItem;
    let pendingKey = "";
    const set = vi.spyOn(Storage.prototype,"setItem").mockImplementation(function(this: Storage,key:string,value:string) {
      originalSet.call(this,key,value); if (key.startsWith("ksi.work-area.archive.v1:") && key.endsWith(":result")) pendingKey=key;
    });
    const get = vi.spyOn(Storage.prototype,"getItem").mockImplementation(function(this: Storage,key:string) {
      if (pendingKey === key) { pendingKey=""; return null; }
      return originalGet.call(this,key);
    });
    fireEvent.click(screen.getByRole("button",{name:"구역 보관"}));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button",{name:"구역 보관"}));
    const warning=await screen.findByText(/이번 응답이 탭 기록에 저장됐는지 확인하지 못했습니다/);
    expect(warning.textContent).toContain(outcome === "success" ? "보관 성공 응답을 확인했습니다" : "요청 거부 응답을 확인했습니다");
    expect(warning.textContent).toContain("결과 미확인으로 표시될 수 있습니다");
    expect(warning.textContent).toContain("탭을 닫으면 사라질 수 있습니다");
    expect(calls).toBe(1); view.unmount(); set.mockRestore(); get.mockRestore();
    render(<WorkAreaPanel {...props} />); await awaitReady();
    const resultKey = Object.keys(window.sessionStorage).find(key => key.startsWith("ksi.work-area.archive.v1:") && key.endsWith(":result"));
    expect(resultKey).toBeTruthy();
    expect(JSON.parse(window.sessionStorage.getItem(resultKey!)!).outcome).toBe(outcome);
    expect(postCalls(fetchMock)).toHaveLength(1);
  });

  it("names the exact area, posts nothing on cancel, and keeps the list", async () => {
    window.sessionStorage.clear();
    const fetchMock = vi.fn(async (url: string | URL | Request) => {
      if (isIdentity(url)) return identityOk();
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={{ fingerprint: FP_A }} />);
    await awaitReady();

    fireEvent.click(screen.getByRole("button", { name: "구역 보관" }));
    const dialog = screen.getByRole("dialog", { name: "구역을 보관할까요?" });
    expect(within(dialog).getByText(/동측 절토면/)).toBeTruthy();
    expect(within(dialog).getByText(/이 화면에서 되돌릴 수 없습니다/)).toBeTruthy();
    expect(within(dialog).getByText(/이미 낸 리포트는 그대로 유지됩니다/)).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "취소" }));
    expect(postCalls(fetchMock)).toHaveLength(0);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByText("동측 절토면")).toBeTruthy();
    expect(notifyMock).not.toHaveBeenCalled();
  });

  it("posts the archive exactly once after confirmation and toasts the verified result", async () => {
    window.sessionStorage.clear();
    const archived = { ...activeArea(), status: "ARCHIVED" as const };
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return identityOk();
      if (init?.method === "POST" && String(url).endsWith("/archive")) {
        return { ok: true, json: async () => ({ verdict: "ARCHIVED", workArea: archived }) } as unknown as Response;
      }
      throw new Error(`unexpected fetch ${String(url)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea()]} workAreaListError={null} accountIdentity={{ fingerprint: FP_A }} />);
    await awaitReady();

    fireEvent.click(screen.getByRole("button", { name: "구역 보관" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "구역을 보관할까요?" })).getByRole("button", { name: "구역 보관" }));
    await waitFor(() => expect(postCalls(fetchMock)).toHaveLength(1));
    expect(postCalls(fetchMock)[0]?.[0]).toBe("/api/sites/site-1/work-areas/area-1/archive");
    expect(new Headers((postCalls(fetchMock)[0]?.[1] as RequestInit).headers).get("x-ksi-continuity-fingerprint")).toBe(FP_A);
    await waitFor(() => expect(notifyMock).toHaveBeenCalledWith('"동측 절토면"을 보관했습니다.'));
  });

  it("toasts a complete registration and keeps the no-permission listing as a blocked action", async () => {
    window.sessionStorage.clear();
    const created = activeArea("새 구역");
    // 실제 Core register는 요청 값을 그대로 저장해 돌려주므로, 목도 요청 본문을
    // 에코한다 — 고정 픽스처 polygon으로는 원본 대조(unknown)가 된다.
    const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) return identityOk();
      const input = JSON.parse(String((init as { body?: string } | undefined)?.body ?? "{}")) as Record<string, unknown>;
      return {
        ok: true,
        status: 201,
        json: async () => ({
          verdict: "REGISTERED",
          detail: null,
          workArea: { ...created, name: input.name, polygon: input.polygon, crs: input.crs },
        }),
      } as unknown as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    const { unmount } = render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[]} workAreaListError={null} accountIdentity={{ fingerprint: FP_A }} />);
    await awaitReady();

    fireEvent.change(screen.getByPlaceholderText("3공구 성토부"), { target: { value: "새 구역" } });
    fireEvent.click(screen.getByRole("button", { name: "꼭짓점 추가" }));
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await waitFor(() => expect(postCalls(fetchMock)).toHaveLength(1));
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
    window.sessionStorage.clear();
    const other = { ...activeArea(), workAreaId: "area-2", name: "서측 성토면" };
    const archiveQueue: Array<{ ok: boolean; status: number; body: unknown }> = [
      { ok: false, status: 403, body: {} },
      { ok: true, status: 200, body: { verdict: "ARCHIVED", workArea: { ...activeArea(), status: "ARCHIVED" as const } } },
    ];
    const fetchMock = vi.fn(async (url: string | URL | Request) => {
      if (isIdentity(url)) return identityOk();
      const next = archiveQueue.shift();
      if (!next) throw new Error("unexpected extra archive POST");
      return { ok: next.ok, status: next.status, json: async () => next.body } as unknown as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<WorkAreaPanel siteId="site-1" siteCrs="EPSG:4326" canWrite initialWorkAreas={[activeArea(), other]} workAreaListError={null} accountIdentity={{ fingerprint: FP_A }} />);
    await awaitReady();

    fireEvent.click(screen.getAllByRole("button", { name: "구역 보관" })[0]!);
    fireEvent.click(within(screen.getByRole("dialog", { name: "구역을 보관할까요?" })).getByRole("button", { name: "구역 보관" }));
    await waitFor(() => expect(postCalls(fetchMock)).toHaveLength(1));

    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    const card = alerts[0]!.closest("li");
    expect(card).not.toBeNull();
    expect(within(card as HTMLElement).getByText("동측 절토면")).toBeTruthy();
    expect(alerts[0]!.textContent).toContain("이번 보관 요청");
    expect(screen.getByText("서측 성토면")).toBeTruthy();
    expect(notifyMock).not.toHaveBeenCalled();

    fireEvent.click(within(card as HTMLElement).getByRole("button", { name: "보관 다시 시도" }));
    expect(postCalls(fetchMock)).toHaveLength(1);
    expect(screen.getByRole("dialog", { name: "구역을 보관할까요?" })).toBeTruthy();
    fireEvent.click(within(screen.getByRole("dialog", { name: "구역을 보관할까요?" })).getByRole("button", { name: "구역 보관" }));
    await waitFor(() => expect(postCalls(fetchMock)).toHaveLength(2));
    await waitFor(() => expect(notifyMock).toHaveBeenCalledWith('"동측 절토면"을 보관했습니다.'));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
