/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";

const notifyMock = vi.hoisted(() => vi.fn());

// mock 지도가 채우는 A 꼭짓점과 같은 링 — toZonePolygon 출력과 일치해야 성공 대조를 통과한다.
const A_TRIANGLE = [
  { latDeg: 37.5, lonDeg: 127 },
  { latDeg: 37.5, lonDeg: 127.01 },
  { latDeg: 37.51, lonDeg: 127.01 },
];
// 외부·프로그램 경로로 들어오는 B — UI 잠금을 우회하는 변경 시뮬레이션용.
const B_TRIANGLE = [
  { latDeg: 37.6, lonDeg: 127.1 },
  { latDeg: 37.6, lonDeg: 127.11 },
  { latDeg: 37.61, lonDeg: 127.11 },
];

vi.mock("@/components/map/AoiPolygonMap", () => ({
  AoiPolygonMap: ({
    value,
    onChange,
    readOnly,
    onPendingChange,
  }: {
    value?: { latDeg: number; lonDeg: number }[];
    onChange?: (next: { latDeg: number; lonDeg: number }[]) => void;
    readOnly?: boolean;
    onPendingChange?: (pending: { blocked: boolean; reason: string | null }) => void;
  }) =>
    createElement(
      "div",
      { "data-testid": "mock-map" },
      createElement("span", { "data-testid": "mock-vertex-count" }, String(value?.length ?? 0)),
      // 실제 map prop 값 대조용 — 수량으로는 A/B를 가릴 수 없으므로 원본 JSON을 둔다.
      createElement(
        "span",
        { "data-testid": "mock-vertices-json" },
        JSON.stringify(value ?? []),
      ),
      readOnly
        ? createElement("span", { "data-testid": "mock-map-locked" }, "지도 잠김")
        : null,
      onChange && !readOnly
        ? createElement(
            "button",
            {
              type: "button",
              onClick: () => onChange([...A_TRIANGLE]),
            },
            "꼭짓점 채우기",
          )
        : null,
      // UI 잠금을 우회하는 외부·프로그램 경로(낡은 이벤트 등) 시뮬레이션.
      onChange
        ? createElement(
            "button",
            {
              type: "button",
              onClick: () => onChange([...B_TRIANGLE]),
            },
            "외부 지도 변경(B)",
          )
        : null,
      onPendingChange
        ? createElement(
            "button",
            {
              type: "button",
              onClick: () =>
                onPendingChange({
                  blocked: true,
                  reason: "지도에서 경계를 편집하는 중입니다. 완료·취소하기 전에는 등록할 수 없습니다.",
                }),
            },
            "편집 시작",
          )
        : null,
      onPendingChange
        ? createElement(
            "button",
            {
              type: "button",
              onClick: () => onPendingChange({ blocked: false, reason: null }),
            },
            "편집 종료",
          )
        : null,
      onPendingChange
        ? createElement(
            "button",
            {
              type: "button",
              onClick: () =>
                onPendingChange({
                  blocked: true,
                  reason: "지도에서 경계를 그리는 중입니다. 완료·취소하기 전에는 등록할 수 없습니다.",
                }),
            },
            "그리기 시작",
          )
        : null,
      onPendingChange
        ? createElement(
            "button",
            {
              type: "button",
              onClick: () => onPendingChange({ blocked: false, reason: null }),
            },
            "그리기 종료",
          )
        : null,
      onPendingChange
        ? createElement(
            "button",
            {
              type: "button",
              onClick: () =>
                onPendingChange({
                  blocked: true,
                  reason: "입력한 좌표 3개를 아직 지도에 반영하지 않았습니다. 반영하기 전에는 등록할 수 없습니다.",
                }),
            },
            "미반영 입력",
          )
        : null,
      onPendingChange
        ? createElement(
            "button",
            {
              type: "button",
              onClick: () => onPendingChange({ blocked: false, reason: null }),
            },
            "입력 해소",
          )
        : null,
    ),
}));
vi.mock("@/components/ui/StatusBadge", () => ({
  StateBadge: ({ label }: { label: string }) => createElement("span", null, label),
}));
vi.mock("@/components/ui/ErrorState", () => ({
  ErrorState: ({ message }: { message: string }) =>
    createElement("div", { role: "alert" }, message),
}));
vi.mock("@/components/ui/ToastProvider", () => ({ useToast: () => ({ notify: notifyMock }) }));
vi.mock("@/components/ui/ConfirmDialog", () => ({ ConfirmDialog: () => null }));
vi.mock("@/components/ui/ActionUnavailable", () => ({
  ActionUnavailable: ({ label, description }: { label: string; description: string }) =>
    createElement("div", null, `${label}: ${description}`),
}));

import { WorkAreaPanel } from "@/app/sites/[siteId]/work-areas/WorkAreaPanel";

const SITE = "site-1";

// mock 지도가 채우는 꼭짓점과 같은 링 — toZonePolygon 출력과 일치해야 성공 대조를 통과한다.
const SENT_RING = [
  [127, 37.5],
  [127.01, 37.5],
  [127.01, 37.51],
  [127, 37.5],
];
// 외부 경로 B 삼각형의 링.
const B_RING = [
  [127.1, 37.6],
  [127.11, 37.6],
  [127.11, 37.61],
  [127.1, 37.6],
];

function area(overrides: Record<string, unknown> = {}) {
  return {
    schemaVersion: "1",
    workAreaId: "wa-site-1-0001",
    siteId: SITE,
    name: "기존 구역",
    polygon: { type: "Polygon", coordinates: [SENT_RING] },
    crs: "EPSG:4326",
    status: "ACTIVE",
    supersedes: null,
    createdAt: "2026-10-01T00:00:00Z",
    ...overrides,
  };
}

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function fillForm() {
  fireEvent.change(screen.getByPlaceholderText("3공구 성토부"), { target: { value: "새 구역" } });
  fireEvent.click(screen.getByRole("button", { name: "꼭짓점 채우기" }));
}

const FP_A = `v1-${"a".repeat(64)}`;
const FP_B = `v1-${"b".repeat(64)}`;

function isIdentity(url: unknown): boolean {
  return String(url).includes("/api/account-identity");
}

function identityOk(fingerprint: string = FP_A): Response {
  return jsonResponse({ fingerprint }, 200);
}

function postCalls(): unknown[][] {
  return vi.mocked(fetch).mock.calls.filter((call) => {
    const init = call[1] as RequestInit | undefined;
    return init?.method === "POST";
  });
}

function postCall(index: number): RequestInit | undefined {
  return postCalls()[index]?.[1] as RequestInit | undefined;
}

function postCount(): number {
  return postCalls().length;
}

async function awaitReady(): Promise<void> {
  await screen.findByText(/이름과 경계 편집 원문/);
}

async function awaitGateFailed(): Promise<void> {
  await screen.findByText(/계정 또는 임시 저장 내용을 확인하지 못했습니다/);
}

function setLiveFingerprint(fingerprint: string | null): void {
  (vi.mocked(fetch) as unknown as { __liveFp?: string | null }).__liveFp = fingerprint;
}

function renderPanel(initial: unknown[] = [], fingerprint: string | null = FP_A) {
  return render(
    <WorkAreaPanel
      siteId={SITE}
      siteCrs="EPSG:5186"
      canWrite
      initialWorkAreas={initial as never[]}
      workAreaListError={null}
      accountIdentity={fingerprint === null ? null : { fingerprint }}
    />,
  );
}

function sentContinuity(callIndex: number): string | null {
  const init = postCall(callIndex);
  const headers = init?.headers as Record<string, string> | undefined;
  return headers?.["x-ksi-continuity-fingerprint"] ?? null;
}

function echoArea(workAreaId: string, name = "새 구역") {
  return {
    schemaVersion: "1",
    workAreaId,
    siteId: SITE,
    name,
    polygon: { type: "Polygon", coordinates: [SENT_RING] },
    crs: "EPSG:4326",
    status: "ACTIVE",
    supersedes: null,
    createdAt: "2026-10-28T00:00:00Z",
  };
}

beforeEach(() => {
  window.sessionStorage.clear();
  const queue: Array<(url: string | URL | Request, init?: RequestInit) => Promise<Response>> = [];
  const mock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    if (isIdentity(url)) {
      const live = (mock as unknown as { __liveFp?: string | null }).__liveFp ?? FP_A;
      if (live === null) return jsonResponse(null, 500);
      return identityOk(live);
    }
    const next = queue.shift();
    if (next) return next(url, init);
    throw new Error(`unexpected fetch ${String(url)}`);
  });
  (mock as unknown as { __liveFp?: string | null }).__liveFp = FP_A;
  const originalImpl = mock.mockImplementation.bind(mock);
  // identity GET은 큐를 소비하지 않고 항상 live 지문으로 답한다.
  // 변이·목록 once는 호출 순서대로 큐에 쌓고, identity 선행과 무관하게
  // 변이·목록 순서 그대로 소비한다.
  (mock as unknown as { mockRejectedValueOnce: unknown }).mockRejectedValueOnce = (error: unknown) => {
    queue.push(() => Promise.reject(error));
    return mock;
  };
  (mock as unknown as { mockResolvedValueOnce: unknown }).mockResolvedValueOnce = (value: unknown) => {
    queue.push(async () => value as Response);
    return mock;
  };
  (mock as unknown as { mockReturnValueOnce: unknown }).mockReturnValueOnce = (value: unknown) => {
    queue.push(async () => value as Response);
    return mock;
  };
  // custom mockImplementation은 identity를 선행 분리하고 변이·목록만 원본에 위임한다.
  (mock as unknown as { mockImplementation: unknown }).mockImplementation = (
    fn: (url: string | URL | Request, init?: RequestInit) => Promise<Response> | unknown,
  ) => {
    queue.length = 0;
    originalImpl(async (url: string | URL | Request, init?: RequestInit) => {
      if (isIdentity(url)) {
        const live = (mock as unknown as { __liveFp?: string | null }).__liveFp ?? FP_A;
        if (live === null) return jsonResponse(null, 500);
        return identityOk(live);
      }
      return fn(url, init) as Promise<Response>;
    });
    return mock;
  };
  (mock as unknown as { mockImplementationOnce: unknown }).mockImplementationOnce = (
    fn: (url: string | URL | Request, init?: RequestInit) => Promise<Response> | unknown,
  ) => {
    queue.push(async (url: string | URL | Request, init?: RequestInit) => fn(url, init) as Promise<Response>);
    return mock;
  };
  vi.stubGlobal("fetch", mock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.resetAllMocks();
  notifyMock.mockClear();
  window.sessionStorage.clear();
});

describe("WorkAreaPanel 불명 복구 (사용자 이벤트)", () => {
  it("네트워크 예외 → unknown 패널이 뜨고 입력이 보존되며 등록 버튼이 잠긴다", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    expect(await screen.findByTestId("work-area-unknown-panel")).toBeTruthy();
    expect(screen.getByPlaceholderText("3공구 성토부")).toHaveProperty("value", "새 구역");
    expect(screen.getByRole("button", { name: "등록" })).toHaveProperty("disabled", true);
  });

  it("쓰기(재전송)는 노트북 경계 안, 읽기(목록 확인)는 밖에 있다", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");

    // 재전송 POST 버튼은 hidden lg:contents 경계 안 — 390px·키보드 모두 닿지 않는다
    const retry = screen.getByTestId("work-area-retry-button");
    expect(retry.closest("div.hidden")).not.toBeNull();
    // 목록 확인(읽기 전용)은 경계 밖이라 작은 화면에서도 열린다
    const verify = screen.getByTestId("work-area-verify-button");
    expect(verify.closest("div.hidden")).toBeNull();
    // 둘 다 네이티브 버튼이라 키보드로 닿는다
    expect(retry.tagName).toBe("BUTTON");
    expect(verify.tagName).toBe("BUTTON");
  });

  it("불명 패널의 작은 화면 인계는 같은 계정·같은 화면을 가리키고 기기 간 이전을 약속하지 않는다", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    const panel = await screen.findByTestId("work-area-unknown-panel");
    expect(panel.textContent).toMatch(/노트북에서 같은 계정으로/);
    expect(panel.textContent).toMatch(/이 현장의 ‘작업구역’ 화면/);
    expect(panel.textContent).toMatch(/이 탭의 임시 기록은\s*다른 기기로 옮겨가지 않습니다/);
    expect(panel.textContent).toContain("원래 기록으로 재전송하려면 이 탭의 화면 폭을 1024px 이상으로 넓히세요");
    // 식별자 반출 없음 — 새로 둔 작은 화면 인계 문구에 기술 참조가 실리지 않는다.
    const mobileHints = Array.from(panel.querySelectorAll("p.lg\\:hidden"));
    expect(mobileHints.length).toBeGreaterThan(0);
    for (const hint of mobileHints) expect(hint.textContent).not.toMatch(/workAreaId/);
  });

  it("명시 재전송이 확정 거부면 첫 불명이 그대로 남는다", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");

    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ verdict: "TOO_MANY_ACTIVE", detail: "상한", workArea: null }, 409),
    );
    fireEvent.click(screen.getByTestId("work-area-retry-button"));
    await waitFor(() => {
      expect(screen.getByTestId("work-area-unknown-panel")).toBeTruthy();
    });
    const records = screen.getAllByTestId("work-area-retry-outcome");
    expect(records).toHaveLength(1);
    expect(records[0]!.textContent).toMatch(/확인되지 않은 이전 요청/);
  });

  it("명시 재전송이 성공해도 첫 불명의 중복 가능성을 정직하게 알린다", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");

    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ verdict: "REGISTERED", detail: null, workArea: echoArea("wa-site-1-0002") }, 201),
    );
    fireEvent.click(screen.getByTestId("work-area-retry-button"));
    const records = await screen.findAllByTestId("work-area-retry-outcome");
    expect(records).toHaveLength(1);
    expect(records[0]!.textContent).toMatch(/wa-site-1-0002/);
    expect(records[0]!.textContent).toMatch(/확인되지 않은 이전 요청/);
    expect(screen.getByText(/모두 1건/)).toBeTruthy();
    // 첫 불명이 해소된 것이 아니므로 패널이 닫히지 않는다
    expect(screen.getByTestId("work-area-unknown-panel")).toBeTruthy();
  });

  it("세 번 시도해도 이력이 빠짐없이 남고 건수로 말한다 (거짓 축소 금지)", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");

    // 재전송 #1: 불명
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down again"));
    fireEvent.click(screen.getByTestId("work-area-retry-button"));
    await waitFor(() => {
      expect(screen.getAllByTestId("work-area-retry-outcome")).toHaveLength(1);
    });

    // 재전송 #2: 불명 — '둘'이 아니라 모두 3건(첫 요청 + 재전송 2)
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down third"));
    fireEvent.click(screen.getByTestId("work-area-retry-button"));
    await waitFor(() => {
      expect(screen.getAllByTestId("work-area-retry-outcome")).toHaveLength(2);
    });
    expect(screen.getByText(/모두 3건/)).toBeTruthy();

    // 재전송 #3: 성공 — 이전 기록을 덮지 않고 ID를 남긴다
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ verdict: "REGISTERED", detail: null, workArea: echoArea("wa-site-1-0004") }, 201),
    );
    fireEvent.click(screen.getByTestId("work-area-retry-button"));
    await waitFor(() => {
      expect(screen.getAllByTestId("work-area-retry-outcome")).toHaveLength(3);
    });
    const history = within(screen.getByTestId("work-area-retry-history"));
    expect(history.getByText(/wa-site-1-0004/)).toBeTruthy();
    expect(screen.getByTestId("work-area-unknown-panel")).toBeTruthy();
  });

  it("연속 클릭은 1회만 POST한다 (동기 single-flight)", async () => {
    let resolvePost!: (r: Response) => void;
    const gate = new Promise<Response>((resolve) => {
      resolvePost = resolve;
    });
    vi.mocked(fetch).mockReturnValueOnce(gate as Promise<Response>);
    renderPanel();
    await awaitReady();
    fillForm();
    const submit = screen.getByRole("button", { name: "등록" });
    fireEvent.click(submit);
    fireEvent.click(submit);
    resolvePost(jsonResponse({ verdict: "REGISTERED", detail: null, workArea: echoArea("wa-site-1-0001", "새 구역") }, 201));
    await waitFor(() => {
      expect(postCount()).toBe(1);
    });
  });

  it("목록 조회 실패는 불명으로 알리고, 빈 목록은 부재 증명이 아님을 말한다", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");

    vi.mocked(fetch).mockRejectedValueOnce(new Error("list down"));
    fireEvent.click(screen.getByRole("button", { name: "작업구역 목록 다시 불러오기" }));
    expect(await screen.findByTestId("work-area-verify-outcome")).toHaveProperty(
      "textContent",
      expect.stringMatching(/다시 읽지 못했습니다/),
    );

    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ workAreas: [] }, 200));
    fireEvent.click(screen.getByRole("button", { name: "작업구역 목록 다시 불러오기" }));
    const verify = await screen.findByTestId("work-area-verify-outcome");
    expect(verify.textContent).toMatch(/증명이 아닙니다/);
    // 이름·모양 매칭 성공 단정이 없다
    expect(verify.textContent).not.toMatch(/이미 등록된 것입니다/);
  });

  it("깨진 목록은 이전 상태를 보존하고 불명으로 알린다", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    renderPanel([area()]);
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");

    // ID·site만 있고 화면 필드(createdAt 등)가 없는 깨진 목록
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ workAreas: [{ siteId: SITE, workAreaId: "wa-site-1-0009" }] }, 200),
    );
    fireEvent.click(screen.getByRole("button", { name: "작업구역 목록 다시 불러오기" }));
    expect(await screen.findByTestId("work-area-verify-outcome")).toHaveProperty(
      "textContent",
      expect.stringMatching(/다시 읽지 못했습니다/),
    );
    // 이전 목록이 그대로 있다
    expect(screen.getByText("기존 구역")).toBeTruthy();
  });
});

describe("WorkAreaPanel 대체 등록 보관 확인 (사용자 이벤트)", () => {
  const OLD_ID = "wa-site-1-0001";

  function oldArea() {
    return area({ workAreaId: OLD_ID, name: "기존 구역" });
  }

  /** 요청 본문을 에코하는 Core-like 성공 응답 — 원본 대조를 통과한다. */
  function mockSupersedeFlow(listAfter: unknown[] | "fail") {
    vi.mocked(fetch).mockImplementation(async (url: string | URL | Request, init?: RequestInit) => {
      const u = String(url);
      if (init?.method === "POST" && u.endsWith("/work-areas")) {
        const input = JSON.parse(String(init.body ?? "{}")) as Record<string, unknown>;
        return jsonResponse(
          {
            verdict: "REGISTERED",
            detail: null,
            workArea: {
              schemaVersion: "1",
              workAreaId: "wa-site-1-0002",
              siteId: SITE,
              name: input.name,
              polygon: input.polygon,
              crs: input.crs,
              status: "ACTIVE",
              supersedes: input.supersedes ?? null,
              createdAt: "2026-10-28T00:00:00Z",
            },
          },
          201,
        );
      }
      if (u.includes("/work-areas?")) {
        if (listAfter === "fail") throw new Error("list down");
        return jsonResponse({ workAreas: listAfter }, 200);
      }
      throw new Error(`unexpected fetch ${u}`);
    });
  }

  async function startSupersede() {
    renderPanel([oldArea()]);
    await awaitReady();
    fireEvent.click(screen.getByRole("button", { name: "범위 바꾸기(새 구역)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "대신할 구역으로 등록" })).toHaveProperty("disabled", false));
  }

  function submitSupersede() {
    fireEvent.click(screen.getByRole("button", { name: "대신할 구역으로 등록" }));
  }

  it("이전 ID가 ARCHIVED로 관측될 때만 보관을 확정한다", async () => {
    const createdEcho = {
      schemaVersion: "1",
      workAreaId: "wa-site-1-0002",
      siteId: SITE,
      name: "기존 구역",
      polygon: { type: "Polygon", coordinates: [SENT_RING] },
      crs: "EPSG:4326",
      status: "ACTIVE",
      supersedes: OLD_ID,
      createdAt: "2026-10-28T00:00:00Z",
    };
    mockSupersedeFlow([createdEcho, { ...oldArea(), status: "ARCHIVED" }]);
    await startSupersede();
    submitSupersede();
    await waitFor(() => {
      expect(notifyMock).toHaveBeenCalledWith("새 작업구역을 등록하고 이전 구역을 보관했습니다.");
    });
    expect(screen.getByText("보관됨")).toBeTruthy();
  });

  it("이전 ID가 여전히 ACTIVE면 보관 성공을 주장하지 않는다", async () => {
    mockSupersedeFlow([
      {
        schemaVersion: "1",
        workAreaId: "wa-site-1-0002",
        siteId: SITE,
        name: "기존 구역",
        polygon: { type: "Polygon", coordinates: [SENT_RING] },
        crs: "EPSG:4326",
        status: "ACTIVE",
        supersedes: OLD_ID,
        createdAt: "2026-10-28T00:00:00Z",
      },
      oldArea(),
    ]);
    await startSupersede();
    submitSupersede();
    const notice = await screen.findByText(/아직 사용 중으로 보입니다/);
    expect(notice).toBeTruthy();
    expect(screen.queryByText("새 작업구역을 등록하고 이전 구역을 보관했습니다.")).toBeNull();
    expect(notifyMock).not.toHaveBeenCalledWith(
      "새 작업구역을 등록하고 이전 구역을 보관했습니다.",
    );
  });

  it("이전 ID가 목록에 없으면 보관 미확인으로만 안내한다", async () => {
    mockSupersedeFlow([
      {
        schemaVersion: "1",
        workAreaId: "wa-site-1-0002",
        siteId: SITE,
        name: "기존 구역",
        polygon: { type: "Polygon", coordinates: [SENT_RING] },
        crs: "EPSG:4326",
        status: "ACTIVE",
        supersedes: OLD_ID,
        createdAt: "2026-10-28T00:00:00Z",
      },
    ]);
    await startSupersede();
    submitSupersede();
    expect(await screen.findByText(/목록에 없어/)).toBeTruthy();
    expect(screen.queryByText("새 작업구역을 등록하고 이전 구역을 보관했습니다.")).toBeNull();
  });

  it("대체 등록 뒤 목록을 읽지 못하면 새 구역 등록만 확정한다", async () => {
    mockSupersedeFlow("fail");
    await startSupersede();
    submitSupersede();
    expect(await screen.findByText(/보관됐는지는 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText("새 작업구역을 등록하고 이전 구역을 보관했습니다.")).toBeNull();
  });

  it("createdAt이 빠진 성공 본문은 unknown이다 (정렬 crash 방지)", async () => {    vi.mocked(fetch).mockImplementation(async (url: string | URL | Request, init?: RequestInit) => {
      const u = String(url);
      if (init?.method === "POST" && u.endsWith("/work-areas")) {
        const input = JSON.parse(String(init.body ?? "{}")) as Record<string, unknown>;
        const echo = {
          schemaVersion: "1",
          workAreaId: "wa-site-1-0002",
          siteId: SITE,
          name: input.name,
          polygon: input.polygon,
          crs: input.crs,
          status: "ACTIVE",
          supersedes: input.supersedes ?? null,
        };
        return jsonResponse({ verdict: "REGISTERED", detail: null, workArea: echo }, 201);
      }
      throw new Error(`unexpected fetch ${u}`);
    });
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    expect(await screen.findByTestId("work-area-unknown-panel")).toBeTruthy();
    expect(notifyMock).not.toHaveBeenCalled();
  });
});

describe("WorkAreaPanel 확인 기록 보존 (사용자 이벤트)", () => {
  type PostHandler = (init?: RequestInit) => Promise<Response>;

  function mockPosts(handlers: PostHandler[]) {
    const queue = [...handlers];
    vi.mocked(fetch).mockImplementation(async (url: string | URL | Request, init?: RequestInit) => {
      const u = String(url);
      if (init?.method === "POST" && u.endsWith("/work-areas")) {
        const next = queue.shift();
        if (!next) throw new Error("unexpected extra POST");
        return next(init);
      }
      if (u.includes("/work-areas?")) return jsonResponse({ workAreas: [] }, 200);
      throw new Error(`unexpected fetch ${u}`);
    });
  }

  const rejectOnce = () => Promise.reject(new Error("network down"));

  const echoOnce =
    (workAreaId: string): PostHandler =>
    async (init?: RequestInit) => {
      const input = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      return jsonResponse(
        {
          verdict: "REGISTERED",
          detail: null,
          workArea: {
            schemaVersion: "1",
            workAreaId,
            siteId: SITE,
            name: input.name,
            polygon: input.polygon,
            crs: input.crs,
            status: "ACTIVE",
            supersedes: input.supersedes ?? null,
            createdAt: "2026-10-28T00:00:00Z",
          },
        },
        201,
      );
    };

  it("입력 비우고 새로 시작해도 이전 불명 수와 확정 ID가 남고, 새 입력이 가능하며 즉시 쓰지 않는다", async () => {
    mockPosts([rejectOnce, rejectOnce, echoOnce("wa-site-1-0002")]);
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");

    // 재전송 #1: 불명
    fireEvent.click(screen.getByTestId("work-area-retry-button"));
    await screen.findAllByTestId("work-area-retry-outcome");

    // 재전송 #2: 성공(확정 ID 발생) — 그래도 첫 불명은 해소되지 않는다
    fireEvent.click(screen.getByTestId("work-area-retry-button"));
    await waitFor(() => {
      expect(screen.getAllByTestId("work-area-retry-outcome")).toHaveLength(2);
    });

    const callsBeforeAbandon = vi.mocked(fetch).mock.calls.length;
    fireEvent.click(screen.getByTestId("work-area-abandon-button"));

    // 이전 불명 수(첫 요청 + 재전송 #1 = 2건)와 확정 ID에 접근 가능
    const episode = await screen.findByTestId("work-area-episode-log");
    expect(within(episode).getByText(/wa-site-1-0002/)).toBeTruthy();
    expect(within(episode).getByText(/확인되지 않은 채 남긴 요청: 2건/)).toBeTruthy();
    expect(within(episode).getByText(/묶음 1/)).toBeTruthy();
    // 불명 패널은 닫히고 새 입력을 받을 수 있다
    expect(screen.queryByTestId("work-area-unknown-panel")).toBeNull();
    const nameInput = screen.getByPlaceholderText("3공구 성토부") as HTMLInputElement;
    expect(nameInput.disabled).toBe(false);
    expect(nameInput.value).toBe("");
    // 쓰기 호출은 즉시 발생하지 않는다
    expect(vi.mocked(fetch).mock.calls.length).toBe(callsBeforeAbandon);
    // 확인 화면을 다시 여는 버튼은 변이가 아니다. 원본의 재전송은 별도 선택이다.
    expect(within(episode).getByRole("button", { name: /원래 요청 다시 확인/ })).toBeTruthy();
  });

  it("두 번째 신규 불명으로 넘어가도 이전 이력이 덮이지 않는다", async () => {
    mockPosts([rejectOnce, rejectOnce]);
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");
    fireEvent.click(screen.getByTestId("work-area-abandon-button"));
    expect(await screen.findByTestId("work-area-episode-log")).toBeTruthy();

    // 새 입력으로 두 번째 요청 — 이전 묶음과 섞지 않는다
    fireEvent.change(screen.getByPlaceholderText("3공구 성토부"), {
      target: { value: "두 번째 구역" },
    });
    fireEvent.click(screen.getByRole("button", { name: "꼭짓점 채우기" }));
    const callsBefore = vi.mocked(fetch).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");
    expect(vi.mocked(fetch).mock.calls.length).toBe(callsBefore + 1);

    // 이전 묶음 그대로, 새 불명은 별도 패널·새 이력
    const log = screen.getByTestId("work-area-episode-log");
    const episodes = within(log).getAllByTestId("work-area-episode-record");
    expect(episodes).toHaveLength(1);
    expect(episodes[0]?.textContent).toMatch(/묶음 1/);
    expect(episodes[0]?.textContent).toMatch(/확인되지 않은 채 남긴 요청: 1건/);
    expect(screen.getByTestId("work-area-unknown-panel").textContent).toMatch(/두 번째 구역/);
    expect(screen.queryAllByTestId("work-area-retry-outcome")).toHaveLength(0);
  });
});

describe("WorkAreaPanel 계정 경계 (사용자 이벤트)", () => {
  it("첫 POST도 확인값을 싣고, 재전송은 원본 확인값을 싣는다", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");
    // 첫 POST부터 화면 계정의 확인값을 싣는다 — 무헤더 폴백 없음
    expect(sentContinuity(0)).toBe(FP_A);

    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ verdict: "REGISTERED", detail: null, workArea: echoArea("wa-site-1-0002") }, 201),
    );
    fireEvent.click(screen.getByTestId("work-area-retry-button"));
    await screen.findAllByTestId("work-area-retry-outcome");
    expect(sentContinuity(1)).toBe(FP_A);
  });

  it("계정 B에서 재전송하면 BFF가 막고 원본 기록은 그대로 남는다", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");

    // B 계정 세션의 BFF가 ACCOUNT_CONTINUITY_MISMATCH로 끊었다고 가정한다
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ message: "계정이 바뀌었습니다.", code: "ACCOUNT_CONTINUITY_MISMATCH" }, 409),
    );
    fireEvent.click(screen.getByTestId("work-area-retry-button"));
    const records = await screen.findAllByTestId("work-area-retry-outcome");
    expect(records).toHaveLength(1);
    expect(records[0]!.textContent).toMatch(/계정이 바뀌/);
    // Core POST는 재전송 1회뿐이고(차단 응답), 원본 불명 패널·이력이 유지된다
    expect(postCount()).toBe(2);
    expect(screen.getByTestId("work-area-unknown-panel")).toBeTruthy();
    expect(screen.getByTestId("work-area-retry-history")).toBeTruthy();
  });

  it("계정 B 세션에서는 편집 UI가 열리지 않고 Core 호출 없이 fail-closed한다", async () => {
    // A 화면에서 열었지만 세션이 B인 채 — live identity가 prop과 달라 draftGate가
    // 실패하고 편집 폼 자체가 노출되지 않으므로 첫 POST도 나가지 않는다 (Core 무호출).
    setLiveFingerprint(FP_B);
    renderPanel();
    await awaitGateFailed();
    expect(screen.getByText(/계정 또는 임시 저장 내용을 확인하지 못했습니다/)).toBeTruthy();
    // 편집 UI 비노출 — 이름 입력·등록 버튼이 없다
    expect(screen.queryByPlaceholderText("3공구 성토부")).toBeNull();
    expect(screen.queryByRole("button", { name: "등록" })).toBeNull();
    // Core POST가 나가지 않았으므로 '결과 불명'이 아니라 미전송이다
    expect(postCount()).toBe(0);
    expect(screen.queryByTestId("work-area-unknown-panel")).toBeNull();
    expect(screen.queryByTestId("work-area-retry-history")).toBeNull();
  });

  it("확인값이 없으면 편집 UI가 열리지 않고 첫 POST를 보내지 않는다 (읽기는 가능)", async () => {
    renderPanel([], null);
    await awaitGateFailed();
    // 신원 미확인 시 편집 UI 비노출 — 새 계약의 fail-closed다
    expect(screen.getByText(/계정 또는 임시 저장 내용을 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.queryByPlaceholderText("3공구 성토부")).toBeNull();
    expect(screen.queryByRole("button", { name: "등록" })).toBeNull();
    // POST가 나가지 않았고 불명도 아니다
    expect(postCount()).toBe(0);
    expect(screen.queryByTestId("work-area-unknown-panel")).toBeNull();
    // 빈 목록 안내는 그대로 보인다
    expect(screen.getByText(/아직 등록된 작업구역이 없습니다/)).toBeTruthy();
  });

  it("확인값이 없어도 기존 목록 읽기는 그대로 보인다", async () => {
    renderPanel([area()], null);
    await awaitGateFailed();
    expect(screen.getByText("기존 구역")).toBeTruthy();
    expect(screen.queryByTestId("work-area-unknown-panel")).toBeNull();
  });

  it("A 불명 → B 재전송 차단 → A 복귀 후 원본으로 명시 재시도하면 별도 ID가 관측된다", async () => {
    // A 세션에서 첫 POST(확인값 FP_A 첨부), 응답 유실
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");
    expect(sentContinuity(0)).toBe(FP_A);

    // B 세션에서 같은 화면의 재전송 — BFF가 409로 끊었다고 가정 (Core 무변이)
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse(
        { message: "계정이 바뀌어 같은 요청을 다시 보내지 않았습니다.", code: "ACCOUNT_CONTINUITY_MISMATCH" },
        409,
      ),
    );
    fireEvent.click(screen.getByTestId("work-area-retry-button"));
    const blocked = await screen.findAllByTestId("work-area-retry-outcome");
    expect(blocked).toHaveLength(1);
    expect(blocked[0]!.textContent).toMatch(/계정이 바뀌어/);
    // 원본 불명 패널·이력이 그대로 남는다
    expect(screen.getByTestId("work-area-unknown-panel")).toBeTruthy();
    expect(screen.getByTestId("work-area-retry-history")).toBeTruthy();

    // A로 복귀해 원본 확인값으로 명시 재시도 — 별도 성공 ID가 관측된다
    vi.mocked(fetch).mockImplementationOnce(async (url: string | URL | Request, init?: RequestInit) => {
      const input = JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>;
      const headers = init?.headers as Record<string, string>;
      expect(headers["x-ksi-continuity-fingerprint"]).toBe(FP_A);
      return jsonResponse(
        {
          verdict: "REGISTERED",
          detail: null,
          workArea: {
            schemaVersion: "1",
            workAreaId: "wa-site-1-0007",
            siteId: SITE,
            name: input.name,
            polygon: input.polygon,
            crs: input.crs,
            status: "ACTIVE",
            supersedes: input.supersedes ?? null,
            createdAt: "2026-10-29T00:00:00Z",
          },
        },
        201,
      );
    });
    fireEvent.click(screen.getByTestId("work-area-retry-button"));
    await waitFor(() => {
      expect(screen.getAllByTestId("work-area-retry-outcome")).toHaveLength(2);
    });
    const history = screen.getByTestId("work-area-retry-history");
    expect(within(history).getByText(/wa-site-1-0007/)).toBeTruthy();
    // 첫 불명은 여전히 해소되지 않았다
    expect(screen.getByTestId("work-area-unknown-panel")).toBeTruthy();
  });
});

describe("WorkAreaPanel 지도 진행 중·미반영 가드 (사용자 이벤트)", () => {
  function sentPolygon(callIndex: number): unknown {
    const init = postCall(callIndex);
    return JSON.parse(String(init?.body ?? "{}")).polygon;
  }

  it("편집 중에는 기존 유효 범위로 등록이 나가지 않고, 취소 후 원래 A로 등록된다", async () => {
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "편집 시작" }));
    // 기존 A(꼭짓점 3개)가 있어도 제출이 막히고 이유가 보인다
    expect(screen.getByRole("button", { name: "등록" })).toHaveProperty("disabled", true);
    expect(screen.getByTestId("work-area-map-pending").textContent).toMatch(/편집하는 중/);
    fireEvent.click(screen.getByRole("button", { name: "편집 시작" }));
    const callsBefore = vi.mocked(fetch).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    // 막힌 상태의 클릭은 POST를 보내지 않는다 — 임시 비활성화가 아니라 실제 차단이다
    expect(vi.mocked(fetch).mock.calls.length).toBe(callsBefore);

    // 취소(편집 종료, 값 변경 없음)하면 재활성되고 원래 A가 그대로 나간다
    fireEvent.click(screen.getByRole("button", { name: "편집 종료" }));
    expect(screen.getByRole("button", { name: "등록" })).toHaveProperty("disabled", false);
    expect(screen.queryByTestId("work-area-map-pending")).toBeNull();
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ verdict: "REGISTERED", detail: null, workArea: echoArea("wa-site-1-0002") }, 201),
    );
    const postBefore = postCount();
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await waitFor(() => {
      expect(vi.mocked(fetch)).toHaveBeenCalledTimes(callsBefore + 1);
    });
    expect(sentPolygon(postBefore)).toEqual({ type: "Polygon", coordinates: [SENT_RING] });
  });

  it("편집 완료로 새 값이 들어오면 완료 후 그 값이 나가고 낡은 A가 나가지 않는다", async () => {
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "편집 시작" }));
    expect(screen.getByTestId("work-area-map-pending")).toBeTruthy();
    // 편집 저장을 외부 경로로 재현 — B가 현재 입력이 된다
    fireEvent.click(screen.getByRole("button", { name: "외부 지도 변경(B)" }));
    fireEvent.click(screen.getByRole("button", { name: "편집 종료" }));
    expect(screen.getByRole("button", { name: "등록" })).toHaveProperty("disabled", false);
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ verdict: "REGISTERED", detail: null, workArea: echoArea("wa-site-1-0003") }, 201),
    );
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await waitFor(() => {
      expect(postCount()).toBe(1);
    });
    expect(sentPolygon(0)).toEqual({ type: "Polygon", coordinates: [B_RING] });
  });

  it("그리기 중 취소(값 변경 없음)는 차단 후 재활성하고 A를 유지한다", async () => {
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "그리기 시작" }));
    expect(screen.getByRole("button", { name: "등록" })).toHaveProperty("disabled", true);
    expect(screen.getByTestId("work-area-map-pending").textContent).toMatch(/그리는 중/);
    fireEvent.click(screen.getByRole("button", { name: "그리기 종료" }));
    expect(screen.getByRole("button", { name: "등록" })).toHaveProperty("disabled", false);
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ verdict: "REGISTERED", detail: null, workArea: echoArea("wa-site-1-0002") }, 201),
    );
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await waitFor(() => {
      expect(postCount()).toBe(1);
    });
    expect(sentPolygon(0)).toEqual({ type: "Polygon", coordinates: [SENT_RING] });
  });

  it("미반영 키보드 입력이 있으면 기존 A로 등록이 나가지 않고 해소 뒤 A가 나간다", async () => {
    renderPanel();
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "미반영 입력" }));
    expect(screen.getByRole("button", { name: "등록" })).toHaveProperty("disabled", true);
    expect(screen.getByTestId("work-area-map-pending").textContent).toMatch(/반영하지 않았습니다/);
    const callsBefore = vi.mocked(fetch).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    expect(vi.mocked(fetch).mock.calls.length).toBe(callsBefore);

    fireEvent.click(screen.getByRole("button", { name: "입력 해소" }));
    expect(screen.queryByTestId("work-area-map-pending")).toBeNull();
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ verdict: "REGISTERED", detail: null, workArea: echoArea("wa-site-1-0002") }, 201),
    );
    const postBefore = postCount();
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await waitFor(() => {
      expect(vi.mocked(fetch)).toHaveBeenCalledTimes(callsBefore + 1);
    });
    expect(sentPolygon(postBefore)).toEqual({ type: "Polygon", coordinates: [SENT_RING] });
  });

  it("정정 흐름에서도 편집 중 대체 등록이 막히고 취소 후 원래 범위로 나간다", async () => {
    const old = area({ workAreaId: "wa-site-1-0001", name: "기존 구역" });
    vi.mocked(fetch).mockImplementation(async (url: string | URL | Request, init?: RequestInit) => {
      const u = String(url);
      if (init?.method === "POST" && u.endsWith("/work-areas")) {
        const input = JSON.parse(String(init.body ?? "{}")) as Record<string, unknown>;
        return jsonResponse(
          {
            verdict: "REGISTERED",
            detail: null,
            workArea: {
              schemaVersion: "1",
              workAreaId: "wa-site-1-0002",
              siteId: SITE,
              name: input.name,
              polygon: input.polygon,
              crs: input.crs,
              status: "ACTIVE",
              supersedes: input.supersedes ?? null,
              createdAt: "2026-10-28T00:00:00Z",
            },
          },
          201,
        );
      }
      if (u.includes("/work-areas?")) {
        return jsonResponse(
          {
            workAreas: [
              {
                schemaVersion: "1",
                workAreaId: "wa-site-1-0002",
                siteId: SITE,
                name: "기존 구역",
                polygon: { type: "Polygon", coordinates: [SENT_RING] },
                crs: "EPSG:4326",
                status: "ACTIVE",
                supersedes: "wa-site-1-0001",
                createdAt: "2026-10-28T00:00:00Z",
              },
              { ...old, status: "ARCHIVED" },
            ],
          },
          200,
        );
      }
      throw new Error(`unexpected fetch ${u}`);
    });
    renderPanel([old]);
    await awaitReady();
    fireEvent.click(screen.getByRole("button", { name: "범위 바꾸기(새 구역)" }));
    await screen.findByRole("button", { name: "대신할 구역으로 등록" });

    fireEvent.click(screen.getByRole("button", { name: "편집 시작" }));
    expect(screen.getByRole("button", { name: "대신할 구역으로 등록" })).toHaveProperty("disabled", true);
    const callsBefore = vi.mocked(fetch).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "대신할 구역으로 등록" }));
    expect(vi.mocked(fetch).mock.calls.length).toBe(callsBefore);

    fireEvent.click(screen.getByRole("button", { name: "편집 종료" }));
    const postBefore = postCount();
    fireEvent.click(screen.getByRole("button", { name: "대신할 구역으로 등록" }));
    await waitFor(() => {
      expect(notifyMock).toHaveBeenCalledWith("새 작업구역을 등록하고 이전 구역을 보관했습니다.");
    });
    const post = postCall(postBefore) as RequestInit;
    const sentBody = JSON.parse(String(post.body)) as Record<string, unknown>;
    expect(sentBody.supersedes).toBe("wa-site-1-0001");
    expect(sentBody.polygon).toEqual({ type: "Polygon", coordinates: [SENT_RING] });
  });

  it("제출 대기 중 지도가 잠기고, 유실 뒤 외부 변경이 있어도 재전송은 동결된 A를 보낸다", async () => {
    renderPanel();
    await awaitReady();
    fillForm();
    const A_JSON = JSON.stringify([
      { latDeg: 37.5, lonDeg: 127 },
      { latDeg: 37.5, lonDeg: 127.01 },
      { latDeg: 37.51, lonDeg: 127.01 },
    ]);
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    // 제출 대기 중에는 지도를 바꿀 수 없고, 읽기 전용 지도는 전송 A를 보여준다
    expect(screen.getByTestId("mock-map-locked")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "꼭짓점 채우기" })).toBeNull();
    expect(screen.getByTestId("mock-vertices-json").textContent).toBe(A_JSON);
    expect(await screen.findByTestId("work-area-unknown-panel")).toBeTruthy();
    expect(screen.getByTestId("work-area-unknown-panel").textContent).toMatch(/새 구역/);

    // 유실 뒤 외부 경로로 B가 들어와도 명시적 재전송은 동결된 첫 요청(A)으로만 나간다
    fireEvent.click(screen.getByRole("button", { name: "외부 지도 변경(B)" }));
    // 입력 상태는 B지만 읽기 전용 지도·수량은 전송 A를 표시한다
    expect(screen.getByTestId("mock-vertices-json").textContent).toBe(A_JSON);
    expect(screen.getByTestId("work-area-unknown-panel").textContent).toMatch(/꼭짓점 3개/);
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down again"));
    fireEvent.click(screen.getByTestId("work-area-retry-button"));
    await screen.findAllByTestId("work-area-retry-outcome");
    expect(postCount()).toBe(2);
    const retryInit = postCall(1) as RequestInit;
    const retryBody = JSON.parse(String(retryInit.body)) as Record<string, unknown>;
    expect(retryBody.polygon).toEqual({
      type: "Polygon",
      coordinates: [SENT_RING],
    });
    expect(retryBody.name).toBe("새 구역");
    expect(retryBody.supersedes).toBeNull();
    expect((retryInit.headers as Record<string, string>)["x-ksi-continuity-fingerprint"]).toBe(FP_A);
    // 화면 표시도 원래 A 요청을 유지한다
    expect(screen.getByTestId("work-area-unknown-panel").textContent).toMatch(/새 구역/);
    expect(screen.getByTestId("mock-vertices-json").textContent).toBe(A_JSON);
  });

  it("대체 등록의 재전송도 동결된 supersedes와 원본 기하를 보낸다", async () => {
    const old = area({ workAreaId: "wa-site-1-0001", name: "기존 구역" });
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    renderPanel([old]);
    await awaitReady();
    fireEvent.click(screen.getByRole("button", { name: "범위 바꾸기(새 구역)" }));
    await screen.findByRole("button", { name: "대신할 구역으로 등록" });
    // 정정 폼은 기존 모양을 초기값으로 올린다 — mock 채우기는 같은 A 링이다.
    fireEvent.click(screen.getByRole("button", { name: "대신할 구역으로 등록" }));
    expect(await screen.findByTestId("work-area-unknown-panel")).toBeTruthy();

    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down again"));
    fireEvent.click(screen.getByTestId("work-area-retry-button"));
    await screen.findAllByTestId("work-area-retry-outcome");
    expect(postCount()).toBe(2);
    const retryInit = postCall(1) as RequestInit;
    const retryBody = JSON.parse(String(retryInit.body)) as Record<string, unknown>;
    // 원래 값이 null이었으면 현재값으로 채우지 않고 null을 보존한다.
    expect(retryBody.supersedes).toBe("wa-site-1-0001");
    expect(retryBody.polygon).toEqual({ type: "Polygon", coordinates: [SENT_RING] });
    expect(retryBody.name).toBe("기존 구역");
  });
});

describe("WorkAreaPanel 이탈 확인 (사용자 이벤트)", () => {
  function twoAreas() {
    return [
      area({
        workAreaId: "wa-site-1-0001",
        name: "기존 1구역",
        createdAt: "2026-10-01T00:00:00Z",
      }),
      area({
        workAreaId: "wa-site-1-0002",
        name: "기존 2구역",
        createdAt: "2026-10-02T00:00:00Z",
      }),
    ];
  }

  it("미반영 입력이 있으면 다른 구역으로 범위 바꾸기 전에 확인하고, 계속하면 보존된다", async () => {
    renderPanel(twoAreas());
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "미반영 입력" }));
    // 최신(2구역) 카드의 범위 바꾸기를 누른다 — 최신순 정렬이라 첫 번째다.
    fireEvent.click(screen.getAllByRole("button", { name: "범위 바꾸기(새 구역)" })[0]!);
    expect(screen.getByTestId("work-area-abandon-confirm")).toBeTruthy();
    expect(screen.getByTestId("work-area-abandon-confirm").textContent).toMatch(
      /입력 중인 내용이 있습니다/,
    );
    // 아직 전환되지 않았다 — 새 구역 등록 폼 그대로, 입력도 그대로다.
    expect(screen.getByRole("heading", { name: "새 작업구역 등록" })).toBeTruthy();
    expect((screen.getByPlaceholderText("3공구 성토부") as HTMLInputElement).value).toBe("새 구역");

    fireEvent.click(screen.getByRole("button", { name: "계속 입력하기" }));
    expect(screen.queryByTestId("work-area-abandon-confirm")).toBeNull();
    // 미반영 막힘이 유지된다 — 조용히 풀리지 않는다.
    expect(screen.getByRole("button", { name: "등록" })).toHaveProperty("disabled", true);
    expect(screen.getByTestId("work-area-map-pending")).toBeTruthy();
  });

  it("버리고 이동하면 확인 뒤에만 전환되고, 입력은 사라지고 기존값은 남는다", async () => {
    renderPanel(twoAreas());
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "미반영 입력" }));
    fireEvent.click(screen.getAllByRole("button", { name: "범위 바꾸기(새 구역)" })[0]!);
    expect(screen.getByTestId("work-area-abandon-confirm")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "입력 버리고 이동하기" }));
    expect(screen.queryByTestId("work-area-abandon-confirm")).toBeNull();
    // 2구역 정정 폼으로 전환됐다.
    expect(screen.getByRole("heading", { name: "구역 다시 그리기" })).toBeTruthy();
    expect((screen.getByPlaceholderText("3공구 성토부") as HTMLInputElement).value).toBe(
      "기존 2구역",
    );
  });

  it("그만두기도 미반영이면 확인하고, 버려야 초기화된다", async () => {
    renderPanel(twoAreas());
    await awaitReady();
    fireEvent.click(screen.getAllByRole("button", { name: "범위 바꾸기(새 구역)" })[0]!);
    await screen.findByRole("button", { name: "대신할 구역으로 등록" });
    fireEvent.click(screen.getByRole("button", { name: "미반영 입력" }));
    fireEvent.click(screen.getByRole("button", { name: "그만두고 새 구역으로 등록" }));
    expect(screen.getByTestId("work-area-abandon-confirm")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "계속 입력하기" }));
    // 정정 폼이 그대로 남는다.
    expect(screen.getByRole("heading", { name: "구역 다시 그리기" })).toBeTruthy();
    expect((screen.getByPlaceholderText("3공구 성토부") as HTMLInputElement).value).toBe(
      "기존 2구역",
    );

    fireEvent.click(screen.getByRole("button", { name: "그만두고 새 구역으로 등록" }));
    fireEvent.click(screen.getByRole("button", { name: "입력 버리고 이동하기" }));
    expect(screen.getByRole("heading", { name: "새 작업구역 등록" })).toBeTruthy();
    expect((screen.getByPlaceholderText("3공구 성토부") as HTMLInputElement).value).toBe("");
    expect(screen.getByTestId("mock-vertex-count").textContent).toBe("0");
  });

  it("미반영이 없으면 확인 없이 바로 전환된다", async () => {
    renderPanel(twoAreas());
    await awaitReady();
    fireEvent.click(screen.getAllByRole("button", { name: "범위 바꾸기(새 구역)" })[0]!);
    await screen.findByRole("button", { name: "대신할 구역으로 등록" });
    expect(screen.queryByTestId("work-area-abandon-confirm")).toBeNull();
    expect(screen.getByRole("heading", { name: "구역 다시 그리기" })).toBeTruthy();
  });

  it("새로고침·탭 닫기는 입력이 있으면 브라우저 확인을 띄운다", async () => {
    renderPanel();
    await awaitReady();
    const clean = window.dispatchEvent(new window.Event("beforeunload", { cancelable: true }));
    expect(clean).toBe(true);

    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "미반영 입력" }));
    const dirty = window.dispatchEvent(new window.Event("beforeunload", { cancelable: true }));
    expect(dirty).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "입력 해소" }));
    const resolved = window.dispatchEvent(
      new window.Event("beforeunload", { cancelable: true }),
    );
    expect(resolved).toBe(false);
  });
});

describe("WorkAreaPanel 불명 원본 메모리 한계 고지 (사용자 이벤트)", () => {
  function dispatchBeforeUnload(): boolean {
    return window.dispatchEvent(new window.Event("beforeunload", { cancelable: true }));
  }

  it("불명 패널은 탭 보관의 휘발성과 재전송 기록을 먼저 밝힌다", async () => {
    renderPanel();
    await awaitReady();
    fillForm();
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    const panel = await screen.findByTestId("work-area-unknown-panel");
    // 탭 한정 보관과 닫힘 시 휘발성을 패널 안에서 먼저 밝힌다.
    expect(panel.textContent).toMatch(/이 탭에 임시 보관/);
    expect(panel.textContent).toMatch(/탭을 닫으면 사라질 수/);
    expect(panel.textContent).toMatch(/별도 요청으로 기록/);
    // 자동 성공·멱등 재시도로 잘못 표현하지 않는다.
    expect(panel.textContent).not.toMatch(/중복 등록이 되지 않습니다/);
    expect(panel.textContent).not.toMatch(/같은 요청 키로 다시 시도하면/);
  });

  it("불명이 열린 동안 새로고침·탭 닫기는 브라우저 경고를 띄운다", async () => {
    renderPanel();
    await awaitReady();
    expect(dispatchBeforeUnload()).toBe(true);
    fillForm();
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");
    // 원본·재전송 정보가 메모리 전용이므로 떠나기 전 확인시킨다.
    expect(dispatchBeforeUnload()).toBe(false);
  });

  it("불명 원본은 외부 변경 뒤에도 동결값을 유지하고 버려지지 않는다", async () => {
    renderPanel();
    await awaitReady();
    fillForm();
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");

    fireEvent.click(screen.getByRole("button", { name: "외부 지도 변경(B)" }));
    // 입력은 바뀌어도 불명 패널의 원본 표시(이름·수량)는 동결된 A 그대로다.
    const panel = screen.getByTestId("work-area-unknown-panel");
    expect(panel.textContent).toMatch(/새 구역/);
    expect(panel.textContent).toMatch(/꼭짓점 3개/);
    expect(screen.getByTestId("mock-vertices-json").textContent).toBe(
      JSON.stringify(A_TRIANGLE),
    );

    // '입력 비우고 새로 시작'은 원본을 파기하지 않고 확인 기록으로 옮긴다.
    fireEvent.click(screen.getByTestId("work-area-abandon-button"));
    const log = await screen.findByTestId("work-area-episode-log");
    expect(log.textContent).toMatch(/새 구역/);
    expect(log.textContent).toMatch(/확인되지 않은 채 남긴 요청: 1건/);
  });

  it("새 입력으로 전환한 뒤에도 원래 요청의 좌표와 계정 결속을 다시 확인할 수 있다", async () => {
    renderPanel();
    await awaitReady();
    fillForm();
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");
    const firstRequest = postCall(0)! as RequestInit;

    fireEvent.click(screen.getByTestId("work-area-abandon-button"));
    const log = await screen.findByTestId("work-area-episode-log");
    fireEvent.click(within(log).getByRole("button", { name: /원래 요청 다시 확인/ }));
    expect(await screen.findByTestId("work-area-unknown-panel")).toBeTruthy();
    expect(screen.getByTestId("mock-vertices-json").textContent).toBe(JSON.stringify(A_TRIANGLE));
    expect(postCount()).toBe(1);

    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByTestId("work-area-retry-button"));
    await waitFor(() => expect(postCount()).toBe(2));
    const retry = postCall(1)! as RequestInit;
    expect(retry.body).toBe(firstRequest.body);
    expect(new Headers(retry.headers).get("x-ksi-continuity-fingerprint")).toBe(
      new Headers(firstRequest.headers).get("x-ksi-continuity-fingerprint"),
    );
  });

  it("이전 불명을 새 입력으로 넘긴 뒤에도 새로고침 전에 경고한다", async () => {
    renderPanel();
    await awaitReady();
    fillForm();
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");
    fireEvent.click(screen.getByTestId("work-area-abandon-button"));
    await screen.findByTestId("work-area-episode-log");
    expect(dispatchBeforeUnload()).toBe(false);
  });

  it("새 입력이 있으면 이전 요청을 열면서 그 입력을 덮지 않는다", async () => {
    renderPanel();
    await awaitReady();
    fillForm();
    vi.mocked(fetch).mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "등록" }));
    await screen.findByTestId("work-area-unknown-panel");
    fireEvent.click(screen.getByTestId("work-area-abandon-button"));
    const log = await screen.findByTestId("work-area-episode-log");
    const input = screen.getByPlaceholderText("3공구 성토부") as HTMLInputElement;
    fireEvent.change(input, { target: { value: " " } });
    const restore = within(log).getByRole("button", { name: /원래 요청 다시 확인/ }) as HTMLButtonElement;
    expect(restore.disabled).toBe(true);
    expect(within(log).getByText(/새 입력을 비우거나 현재 요청 확인을 마친 뒤/)).toBeTruthy();
    fireEvent.click(restore);
    expect(input.value).toBe(" ");
    expect(screen.queryByTestId("work-area-unknown-panel")).toBeNull();
    expect(postCount()).toBe(1);
  });
});

describe("WorkAreaPanel 이탈 확인 접근성 (사용자 이벤트)", () => {
  function twoAreas() {
    return [
      area({
        workAreaId: "wa-site-1-0001",
        name: "기존 1구역",
        createdAt: "2026-10-01T00:00:00Z",
      }),
      area({
        workAreaId: "wa-site-1-0002",
        name: "기존 2구역",
        createdAt: "2026-10-02T00:00:00Z",
      }),
    ];
  }

  async function openConfirm() {
    renderPanel(twoAreas());
    await awaitReady();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: "미반영 입력" }));
    const switcher = screen.getAllByRole("button", { name: "범위 바꾸기(새 구역)" })[0]!;
    switcher.focus();
    fireEvent.click(switcher);
    return switcher;
  }

  it("모달이 아닌 인라인 확인으로 dialog 역할을 쓰지 않는다", async () => {
    await openConfirm();
    // 배경을 비활성화하지 않는 인라인 확인이므로 alertdialog가 아니다.
    expect(screen.queryByRole("alertdialog")).toBeNull();
    const group = screen.getByRole("group", { name: "입력 중인 내용 확인" });
    expect(
      within(group).getByRole("heading", { level: 3, name: "입력 중인 내용이 있습니다" }),
    ).toBeTruthy();
    // 선택지는 계속→버리기 순서로 이어진다.
    const buttons = within(group).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual(["계속 입력하기", "입력 버리고 이동하기"]);
  });

  it("열리면 확인 영역으로 초점이 이동하고 Esc는 취소 후 원래 버튼으로 돌아간다", async () => {
    const switcher = await openConfirm();
    const confirm = screen.getByTestId("work-area-abandon-confirm");
    expect(document.activeElement).toBe(confirm);

    fireEvent.keyDown(confirm, { key: "Escape" });
    expect(screen.queryByTestId("work-area-abandon-confirm")).toBeNull();
    expect(document.activeElement).toBe(switcher);
    // 미반영 입력이 그대로 보존됐다.
    expect(screen.getByRole("button", { name: "등록" })).toHaveProperty("disabled", true);
  });

  it("계속 입력하기는 원래 버튼으로, 버리고 이동하기는 바뀐 폼 제목으로 초점이 간다", async () => {
    const switcher = await openConfirm();
    fireEvent.click(screen.getByRole("button", { name: "계속 입력하기" }));
    expect(screen.queryByTestId("work-area-abandon-confirm")).toBeNull();
    expect(document.activeElement).toBe(switcher);

    fireEvent.click(switcher);
    fireEvent.click(screen.getByRole("button", { name: "입력 버리고 이동하기" }));
    expect(screen.queryByTestId("work-area-abandon-confirm")).toBeNull();
    const heading = screen.getByRole("heading", { name: "구역 다시 그리기" });
    expect(document.activeElement).toBe(heading);
    expect((screen.getByPlaceholderText("3공구 성토부") as HTMLInputElement).value).toBe(
      "기존 2구역",
    );
  });
});
