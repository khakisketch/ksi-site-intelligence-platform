/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement, useEffect, useState } from "react";

const mocked = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn(), mountEmpty: false }));

vi.mock("next/navigation", () => ({ useRouter: () => mocked }));

const EDITING_REASON =
  "지도에서 경계를 편집하는 중입니다. 완료·취소하기 전에는 등록할 수 없습니다.";
const INVALID_REASON =
  "꼭짓점 2 위도가 범위(-90~90)를 벗어났습니다. 지도에 반영하거나 되돌리기 전에는 등록할 수 있습니다.";

const AOI_ORIG = [
  { latDeg: 37.5, lonDeg: 127 },
  { latDeg: 37.51, lonDeg: 127 },
  { latDeg: 37.51, lonDeg: 127.01 },
  { latDeg: 37.5, lonDeg: 127.01 },
];

const AOI_NEW = [
  { latDeg: 37.6, lonDeg: 127 },
  { latDeg: 37.61, lonDeg: 127 },
  { latDeg: 37.61, lonDeg: 127.01 },
  { latDeg: 37.6, lonDeg: 127.01 },
];

vi.mock("@/components/map/AoiPolygonMap", () => ({
  AoiPolygonMap: ({
    onChange,
    onPendingChange,
    initialSnapshot,
    onSnapshotChange,
  }: {
    initialSnapshot?: { rows: {lat: string; lon: string}[]; rejectedDraws: {vertices: typeof AOI_ORIG; reason: string}[] };
    onSnapshotChange?: (snapshot: { rows: {lat: string; lon: string}[]; rejectedDraws: {vertices: typeof AOI_ORIG; reason: string}[] }) => void;
    onChange?: (next: unknown) => void;
    onPendingChange?: (pending: { blocked: boolean; reason: string | null }) => void;
  }) => {
    const [keyboard, setKeyboard] = useState(initialSnapshot?.rows[0]?.lat ?? "");
    const [rejected, setRejected] = useState(initialSnapshot?.rejectedDraws.length ? "거부 포인터 원문" : "");
    useEffect(() => {
      if (mocked.mountEmpty && initialSnapshot) onSnapshotChange?.({ rows: [], rejectedDraws: [] });
      if (initialSnapshot) onPendingChange?.({blocked: true, reason: INVALID_REASON});
      // Simulate one mount-time callback, not an edit.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    return createElement(
      "div",
      { "data-testid": "mock-map" },
      createElement("input", { "aria-label": "지연 전달 원문", value: keyboard, onChange: (e: React.ChangeEvent<HTMLInputElement>) => setKeyboard(e.target.value) }),
      createElement("input", { "aria-label": "키보드 원문", value: keyboard, onChange: (e: React.ChangeEvent<HTMLInputElement>) => { setKeyboard(e.target.value); onSnapshotChange?.({rows: [{lat: e.target.value, lon: ""}], rejectedDraws: rejected ? [{vertices: AOI_ORIG, reason: INVALID_REASON}] : []}); onPendingChange?.({ blocked: true, reason: INVALID_REASON }); } }),
      createElement("button", { type: "button", onClick: () => onPendingChange?.({ blocked: true, reason: INVALID_REASON }) }, "지연 알림 전달"),
      createElement("button", { type: "button", onClick: () => { setRejected("거부 포인터 원문"); onSnapshotChange?.({rows: [{lat: keyboard, lon: ""}], rejectedDraws: [{vertices: AOI_ORIG, reason: INVALID_REASON}]}); onPendingChange?.({ blocked: true, reason: INVALID_REASON }); } }, "거부 포인터 생성"),
      rejected && createElement("p", null, rejected),
      createElement("button", { type: "button", onClick: () => { setKeyboard(""); setRejected(""); onSnapshotChange?.({ rows: [], rejectedDraws: [] }); onPendingChange?.({ blocked: false, reason: null }); } }, "지도 입력 해소"),
      createElement(
        "button",
        {
          type: "button",
          onClick: () => {
            onChange?.(AOI_ORIG);
            onPendingChange?.({ blocked: false, reason: null });
          },
        },
        "범위 채우기",
      ),
      createElement(
        "button",
        {
          type: "button",
          onClick: () => onPendingChange?.({ blocked: true, reason: EDITING_REASON }),
        },
        "편집 시작",
      ),
      createElement(
        "button",
        {
          type: "button",
          onClick: () => onPendingChange?.({ blocked: false, reason: null }),
        },
        "편집 취소",
      ),
      createElement(
        "button",
        {
          type: "button",
          onClick: () => onPendingChange?.({ blocked: true, reason: INVALID_REASON }),
        },
        "잘못된 좌표",
      ),
      createElement(
        "button",
        {
          type: "button",
          onClick: () => {
            onChange?.(AOI_NEW);
            onPendingChange?.({ blocked: false, reason: null });
          },
        },
        "새 범위 반영",
      ),
    );
  },
}));

import { SiteRegistrationOnlyWizard } from "@/app/sites/new/SiteRegistrationOnlyWizard";
import { createHash } from "node:crypto";

function fingerprint(org: string, actor: string): string {
  return `v1-${createHash("sha256").update(JSON.stringify(["ksi-observation-continuity-v1", org, actor])).digest("hex")}`;
}

const ALICE = fingerprint("org-a", "alice");

function echoSite(siteId: string, name: string, vertices: unknown): unknown {
  return {
    site: {
      siteId,
      name,
      siteFrame: {
        crs: "EPSG:5186",
        verticalDatum: "KNGeoid2018",
        unit: "meter",
        transformVersion: "1.0.0",
      },
      aoi: { vertices: structuredClone(vertices) },
      dataResidency: null,
      aiEgressAllowed: false,
    },
  };
}

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function sentBody(callIndex = 0): Record<string, unknown> {
  const init = requestMock.mock.calls[callIndex]?.[1] as RequestInit | undefined;
  return JSON.parse(typeof init?.body === "string" ? init.body : "{}") as Record<string, unknown>;
}

async function fillToMapStep() {
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
  fireEvent.change(await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장"), {
    target: { value: "현장 A" },
  });
  fireEvent.click(screen.getByRole("button", { name: "다음" }));
  fireEvent.click(screen.getByRole("button", { name: "범위 채우기" }));
  fireEvent.change(screen.getByPlaceholderText("EPSG:5186"), { target: { value: "EPSG:5186" } });
  fireEvent.change(screen.getByPlaceholderText("KNGeoid2018"), { target: { value: "KNGeoid2018" } });
}

const requestMock = vi.fn();
let identityResponse: () => Promise<Response>;

beforeEach(() => {
  window.sessionStorage.clear();
  mocked.mountEmpty = false;
  identityResponse = async () => jsonResponse({ fingerprint: ALICE }, 200);
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
    String(input) === "/api/account-identity"
      ? identityResponse()
      : requestMock(input, init),
  ));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});

describe("현장 등록 지도 미반영 차단 (사용자 이벤트)", () => {
  it("편집 중에는 다음이 막히고 이유가 보이며 POST로 갈 수 없다", async () => {
    await fillToMapStep();
    fireEvent.click(screen.getByRole("button", { name: "편집 시작" }));

    const next = screen.getByRole("button", { name: "다음" });
    expect((next as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(EDITING_REASON)).toBeTruthy();
    // 다음 단계로 넘어가지 못하므로 등록 버튼도 없고 POST도 없다.
    expect(screen.queryByRole("button", { name: "현장 등록" })).toBeNull();
    expect(requestMock).not.toHaveBeenCalled();
  });

  it("잘못된 키보드 입력도 막히고 이유가 보인다", async () => {
    await fillToMapStep();
    fireEvent.click(screen.getByRole("button", { name: "잘못된 좌표" }));

    expect((screen.getByRole("button", { name: "다음" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(screen.getByText(INVALID_REASON)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "현장 등록" })).toBeNull();
    expect(requestMock).not.toHaveBeenCalled();
  });

  it("편집 취소하면 원래 AOI 그대로 진행·제출된다", async () => {
    await fillToMapStep();
    fireEvent.click(screen.getByRole("button", { name: "편집 시작" }));
    expect((screen.getByRole("button", { name: "다음" }) as HTMLButtonElement).disabled).toBe(
      true,
    );

    fireEvent.click(screen.getByRole("button", { name: "편집 취소" }));
    expect((screen.getByRole("button", { name: "다음" }) as HTMLButtonElement).disabled).toBe(
      false,
    );
    expect(screen.queryByText(EDITING_REASON)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });
    const issued = "site-12345678-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A", AOI_ORIG), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    // 취소 뒤에는 원래 커밋 AOI가 그대로 보내진다.
    expect(
      ((sentBody(0).aoi ?? {}) as Record<string, unknown>).vertices,
    ).toEqual(AOI_ORIG);
  });

  it("새 값을 반영하면 보낸 AOI가 새 값이다", async () => {
    await fillToMapStep();
    fireEvent.click(screen.getByRole("button", { name: "편집 시작" }));
    fireEvent.click(screen.getByRole("button", { name: "새 범위 반영" }));
    expect((screen.getByRole("button", { name: "다음" }) as HTMLButtonElement).disabled).toBe(
      false,
    );

    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });
    const issued = "site-abcdefab-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A", AOI_NEW), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    // 반영한 새 AOI가 그대로 보내진다(이전 값 아님).
    expect(
      ((sentBody(0).aoi ?? {}) as Record<string, unknown>).vertices,
    ).toEqual(AOI_NEW);
  });

  it("미반영 상태는 초안·영수증에 저장되지 않는다", async () => {
    await fillToMapStep();
    fireEvent.click(screen.getByRole("button", { name: "편집 시작" }));
    fireEvent.click(screen.getByRole("button", { name: "편집 취소" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });
    const issued = "site-12345678-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A", AOI_ORIG), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.", { selector: "p" })).toBeTruthy();

    const draft = JSON.parse(
      window.sessionStorage.getItem("ksi-wizard-site-registration-only") ?? "{}",
    ) as Record<string, unknown>;
    expect(Object.keys(draft)).not.toContain("aoiPending");
    expect(JSON.stringify(draft)).not.toContain("blocked");
    const receipt = JSON.parse(
      window.sessionStorage.getItem("ksi-wizard-site-registration-only:success") ?? "null",
    ) as Record<string, unknown> | null;
    expect(receipt).toMatchObject({ siteId: issued });
    expect(JSON.stringify(receipt ?? {})).not.toContain("blocked");
  });
});


it("미반영 지도 원문은 계정 재확인 대기·실패·다른 계정에서 숨기고 A 복귀에 보존한다", async () => {
  await fillToMapStep();
  fireEvent.change(screen.getByLabelText("키보드 원문"), { target: { value: "키보드 미반영 B" } });
  fireEvent.click(screen.getByRole("button", { name: "거부 포인터 생성" }));
  expect((screen.getByRole("button", { name: "다음" }) as HTMLButtonElement).disabled).toBe(true);
  let reply: (response: Response) => void = () => {};
  identityResponse = () => new Promise<Response>((resolve) => { reply = resolve; });
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  expect(screen.queryByRole("textbox", { name: "키보드 원문" })).toBeNull();
  const preservedMap = screen.getByTestId("mock-map");
  expect(preservedMap.closest("[hidden][inert]")).not.toBeNull();
  await act(async () => reply(jsonResponse({ fingerprint: ALICE }, 200)));
  expect((await screen.findByRole("textbox", { name: "키보드 원문" }) as HTMLInputElement).value).toBe("키보드 미반영 B");
  expect(screen.getByText("거부 포인터 원문")).toBeTruthy();
  identityResponse = () => new Promise<Response>((resolve) => { reply = resolve; });
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(screen.queryByRole("textbox", { name: "키보드 원문" })).toBeNull();
  expect(screen.queryByRole("button", { name: "거부 포인터 생성" })).toBeNull();
  await act(async () => reply(jsonResponse({}, 503)));
  expect(await screen.findByText(/현재 계정을 확인할 수 없습니다/)).toBeTruthy();
  expect(screen.queryByRole("textbox", { name: "키보드 원문" })).toBeNull();
  identityResponse = async () => jsonResponse({ fingerprint: `v1-${"b".repeat(64)}` }, 200);
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(await screen.findByRole("heading", { name: "다른 계정의 입력입니다" })).toBeTruthy();
  expect(screen.getByText(/원래 계정으로 돌아온 뒤/)).toBeTruthy();
  expect(screen.getByText(/탭을 닫거나 새로고침하지 마세요/)).toBeTruthy();
  expect(screen.queryByRole("textbox", { name: "키보드 원문" })).toBeNull();
  identityResponse = async () => jsonResponse({ fingerprint: ALICE }, 200);
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect((await screen.findByRole("textbox", { name: "키보드 원문" }) as HTMLInputElement).value).toBe("키보드 미반영 B");
  expect(screen.getByText("거부 포인터 원문")).toBeTruthy();
  expect((screen.getByRole("button", { name: "다음" }) as HTMLButtonElement).disabled).toBe(true);
  expect(requestMock).not.toHaveBeenCalled();
});


it("지도 원문 변경 후 부모 pending 전달 전에도 계정 재확인으로 지도 상태가 사라지지 않는다", async () => {
  await fillToMapStep();
  fireEvent.change(screen.getByRole("textbox", { name: "지연 전달 원문" }), { target: { value: "효과 전달 전 원문 B" } });
  expect((screen.getByRole("button", { name: "다음" }) as HTMLButtonElement).disabled).toBe(false);
  let reply: (response: Response) => void = () => {};
  identityResponse = () => new Promise<Response>((resolve) => { reply = resolve; });
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(screen.queryByRole("textbox", { name: "지연 전달 원문" })).toBeNull();
  await act(async () => reply(jsonResponse({ fingerprint: ALICE }, 200)));
  expect((await screen.findByRole("textbox", { name: "지연 전달 원문" }) as HTMLInputElement).value).toBe("효과 전달 전 원문 B");
  identityResponse = async () => jsonResponse({ fingerprint: `v1-${"b".repeat(64)}` }, 200);
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(await screen.findByRole("heading", { name: "다른 계정의 입력입니다" })).toBeTruthy();
  expect(screen.queryByRole("textbox", { name: "지연 전달 원문" })).toBeNull();
  expect(screen.getByTestId("mock-map").closest("[hidden][inert]")).not.toBeNull();
  identityResponse = async () => jsonResponse({ fingerprint: ALICE }, 200);
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect((await screen.findByRole("textbox", { name: "지연 전달 원문" }) as HTMLInputElement).value).toBe("효과 전달 전 원문 B");
  fireEvent.click(screen.getByRole("button", { name: "지연 알림 전달" }));
  expect((screen.getByRole("button", { name: "다음" }) as HTMLButtonElement).disabled).toBe(true);
  expect(requestMock).not.toHaveBeenCalled();
});

it("탭이 포커스를 잃으면 지도 원문을 숨기고 원래 계정 확인 뒤 다시 보여준다", async () => {
  await fillToMapStep();
  fireEvent.change(screen.getByRole("textbox", { name: "키보드 원문" }), { target: { value: "미반영 위도 원문" } });
  fireEvent.click(screen.getByRole("button", { name: "거부 포인터 생성" }));

  act(() => {
    window.dispatchEvent(new Event("blur"));
    // 이벤트가 끝나기 전 감춰야 다른 탭에서 돌아오는 첫 프레임 전에 반영된다.
    expect(screen.queryByRole("textbox", { name: "키보드 원문" })).toBeNull();
    expect(screen.getByTestId("mock-map").closest("[hidden][inert]")).not.toBeNull();
  });

  identityResponse = async () => jsonResponse({ fingerprint: `v1-${"b".repeat(64)}` }, 200);
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect(await screen.findByRole("heading", { name: "다른 계정의 입력입니다" })).toBeTruthy();
  expect(screen.queryByRole("textbox", { name: "키보드 원문" })).toBeNull();

  identityResponse = async () => jsonResponse({ fingerprint: ALICE }, 200);
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect((await screen.findByRole("textbox", { name: "키보드 원문" }) as HTMLInputElement).value).toBe("미반영 위도 원문");
  expect(screen.getByText("거부 포인터 원문")).toBeTruthy();
  expect((screen.getByRole("button", { name: "다음" }) as HTMLButtonElement).disabled).toBe(true);
  expect(requestMock).not.toHaveBeenCalled();
});

it("포커스를 잃은 뒤 늦게 도착한 계정 확인은 숨긴 지도 원문을 다시 표시하지 않는다", async () => {
  await fillToMapStep();
  fireEvent.change(screen.getByRole("textbox", { name: "키보드 원문" }), { target: { value: "지연 응답 전 원문" } });
  let resolveIdentity: (response: Response) => void = () => {};
  identityResponse = () => new Promise<Response>((resolve) => { resolveIdentity = resolve; });
  await act(async () => window.dispatchEvent(new Event("focus")));
  fireEvent.blur(window);
  await act(async () => resolveIdentity(jsonResponse({ fingerprint: ALICE }, 200)));
  expect(screen.queryByRole("textbox", { name: "키보드 원문" })).toBeNull();
  expect(screen.getByTestId("mock-map").closest("[hidden][inert]")).not.toBeNull();

  identityResponse = async () => jsonResponse({ fingerprint: ALICE }, 200);
  await act(async () => window.dispatchEvent(new Event("focus")));
  expect((await screen.findByRole("textbox", { name: "키보드 원문" }) as HTMLInputElement).value).toBe("지연 응답 전 원문");
  expect(requestMock).not.toHaveBeenCalled();
});

it("가려진 탭은 focus 이벤트만으로 신원을 다시 확인하거나 원문을 보여주지 않는다", async () => {
  await fillToMapStep();
  fireEvent.change(screen.getByRole("textbox", { name: "키보드 원문" }), { target: { value: "숨긴 탭 원문" } });
  const state = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  try {
    fireEvent(document, new Event("visibilitychange"));
    expect(screen.queryByRole("textbox", { name: "키보드 원문" })).toBeNull();
    const calls = vi.mocked(fetch).mock.calls.length;
    await act(async () => window.dispatchEvent(new Event("focus")));
    expect(vi.mocked(fetch).mock.calls.length).toBe(calls);
    expect(screen.queryByRole("textbox", { name: "키보드 원문" })).toBeNull();

    state.mockReturnValue("visible");
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    expect((await screen.findByRole("textbox", { name: "키보드 원문" }) as HTMLInputElement).value).toBe("숨긴 탭 원문");
  } finally {
    state.mockRestore();
  }
});



it("마지막 지도 원문과 거부 경계는 다른 화면 이동 뒤 같은 탭에 복구되고 제출을 막는다", async () => {
  await fillToMapStep();
  fireEvent.click(screen.getByRole("button", { name: "거부 포인터 생성" }));
  fireEvent.change(screen.getByRole("textbox", { name: "키보드 원문" }), { target: { value: "  91.000x " } });
  cleanup();
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
  await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장");
  fireEvent.click(screen.getByRole("button", { name: "다음" }));
  expect((screen.getByRole("textbox", { name: "키보드 원문" }) as HTMLInputElement).value).toBe("  91.000x ");
  expect(screen.getByText("거부 포인터 원문")).toBeTruthy();
  expect((screen.getByRole("button", { name: "다음" }) as HTMLButtonElement).disabled).toBe(true);
  expect(requestMock).not.toHaveBeenCalled();
});

const MAP_KEY = "ksi-wizard-site-registration-only:map-v1";
const DRAFT_KEY = "ksi-wizard-site-registration-only";

it.each([`${MAP_KEY}:backup`, `${DRAFT_KEY}:map-draft-backup`, `${DRAFT_KEY}:success-draft-backup`])("잔존 백업 %s은 자동 복구 없이 별도 탭 행동만 안내한다", async (backupKey) => {
  await fillToMapStep();
  fireEvent.change(screen.getByRole("textbox", { name: "키보드 원문" }), { target: { value: "원본 입력" } });
  const map = sessionStorage.getItem(MAP_KEY);
  const draft = sessionStorage.getItem(DRAFT_KEY);
  cleanup();
  const backup = '{ "raw": "미확정 요청 원문" }';
  sessionStorage.setItem(backupKey, backup);
  const receipt = JSON.stringify({ mode: "MAPPED_BOOTSTRAP", siteId: "site-original", name: "private", fingerprint: ALICE });
  sessionStorage.setItem(`${DRAFT_KEY}:success`, receipt);
  identityResponse = async () => jsonResponse({ fingerprint: `v1-${"b".repeat(64)}` }, 200);
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" />);
  await screen.findByRole("heading", { name: "지도 입력을 안전하게 복구할 수 없습니다" });
  expect(screen.getByText(/남은 백업은 자동으로 복구하거나 삭제하지 않습니다/)).toBeTruthy();
  expect(screen.getByText(/요청 결과가 확정되는 것은 아닙니다/)).toBeTruthy();
  for (const name of ["별도 탭에서 현장 목록 확인하기", "별도 탭에서 새로 시작하기"]) {
    const link = screen.getByRole("link", { name });
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    fireEvent.click(link, { button: 0, ctrlKey: true });
  }
  expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
  expect(screen.queryByRole("button", { name: /현장 등록|다음/ })).toBeNull();
  expect(sessionStorage.getItem(backupKey)).toBe(backup);
  expect(sessionStorage.getItem(MAP_KEY)).toBe(map);
  expect(sessionStorage.getItem(DRAFT_KEY)).toBe(draft);
  expect(sessionStorage.getItem(`${DRAFT_KEY}:success`)).toBe(receipt);
  expect(requestMock).not.toHaveBeenCalled();
});

it("다른 계정 재진입에서는 숨기고 원래 계정 재진입에서만 원문을 복구한다", async () => {
  await fillToMapStep();
  fireEvent.change(screen.getByRole("textbox", { name: "키보드 원문" }), { target: { value: "원래 A의 원문" } });
  const raw = sessionStorage.getItem(MAP_KEY);
  cleanup();
  identityResponse = async () => jsonResponse({ fingerprint: `v1-${"b".repeat(64)}` }, 200);
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" />);
  expect(await screen.findByRole("heading", { name: "다른 계정의 입력입니다" })).toBeTruthy();
  expect(screen.queryByDisplayValue("원래 A의 원문")).toBeNull();
  expect(sessionStorage.getItem(MAP_KEY)).toBe(raw);
  cleanup();
  identityResponse = async () => jsonResponse({ fingerprint: ALICE }, 200);
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" />);
  await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장");
  fireEvent.click(screen.getByRole("button", { name: "다음" }));
  expect((screen.getByRole("textbox", { name: "키보드 원문" }) as HTMLInputElement).value).toBe("원래 A의 원문");
});

it("지도 기록과 삭제된 초안이 충돌하면 원문을 보존하고 차단한다", async () => {
  await fillToMapStep();
  fireEvent.change(screen.getByRole("textbox", { name: "키보드 원문" }), { target: { value: "남은 지도 원문" } });
  const raw = sessionStorage.getItem(MAP_KEY);
  cleanup();
  sessionStorage.removeItem(DRAFT_KEY);
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" />);
  expect(await screen.findByRole("heading", { name: "지도 입력을 안전하게 복구할 수 없습니다" })).toBeTruthy();
  expect(sessionStorage.getItem(MAP_KEY)).toBe(raw);
  expect(sessionStorage.getItem(DRAFT_KEY)).toBeNull();
  expect(requestMock).not.toHaveBeenCalled();
});

it.each(['{"version":2}', '{broken'])("미지원·손상 지도 기록은 원문을 덮지 않고 차단한다: %s", async (raw) => {
  sessionStorage.setItem(MAP_KEY, raw);
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" />);
  expect(await screen.findByRole("heading", { name: "지도 입력을 안전하게 복구할 수 없습니다" })).toBeTruthy();
  expect(sessionStorage.getItem(MAP_KEY)).toBe(raw);
  expect(requestMock).not.toHaveBeenCalled();
});

it("지도 저장 quota 실패는 화면 원문을 보존하고 경고·제출 차단한다", async () => {
  await fillToMapStep();
  const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(function(this: Storage, key, value) {
    if (key === MAP_KEY) throw new DOMException("quota", "QuotaExceededError");
    return originalSet.call(this, key, value);
  });
  try {
    fireEvent.change(screen.getByRole("textbox", { name: "키보드 원문" }), { target: { value: "저장 실패 원문" } });
    expect((screen.getByRole("textbox", { name: "키보드 원문" }) as HTMLInputElement).value).toBe("저장 실패 원문");
    expect(screen.getByRole("alert").textContent).toContain("이동하면 잃을 수");
    expect(screen.getByRole("alert").textContent).toContain("자동으로 복구하거나 삭제하지 않습니다");
    expect(screen.getByRole("link", { name: "별도 탭에서 새로 시작하기" }).getAttribute("rel")).toContain("noopener");
    expect((screen.getByRole("button", { name: "다음" }) as HTMLButtonElement).disabled).toBe(true);
    expect(requestMock).not.toHaveBeenCalled();
  } finally { spy.mockRestore(); }
});

it("지도 저장 실패 후 계정이 바뀌어도 원문을 숨기고 복구 안내를 유지한다", async () => {
  await fillToMapStep();
  fireEvent.change(screen.getByRole("textbox", { name: "키보드 원문" }), { target: { value: "기존 원문" } });
  const raw = sessionStorage.getItem(MAP_KEY);
  const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(function(this: Storage, key, value) {
    if (key === MAP_KEY) throw new DOMException("quota", "QuotaExceededError");
    return originalSet.call(this, key, value);
  });
  try {
    fireEvent.change(screen.getByRole("textbox", { name: "키보드 원문" }), { target: { value: "저장 실패 원문" } });
    fireEvent.blur(window);
    identityResponse = async () => jsonResponse({ fingerprint: `v1-${"b".repeat(64)}` }, 200);
    await act(async () => window.dispatchEvent(new Event("focus")));
    expect(await screen.findByRole("heading", { name: "다른 계정의 입력입니다" })).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: "키보드 원문" })).toBeNull();
    expect(screen.getByRole("alert").textContent).toContain("남은 백업은 자동으로 복구하거나 삭제하지 않습니다");
    expect(sessionStorage.getItem(MAP_KEY)).toBe(raw);
    expect(requestMock).not.toHaveBeenCalled();
  } finally { spy.mockRestore(); }
});
const originalSet = Storage.prototype.setItem;

it("재기록 readback 불일치는 이전 원문을 백업에 보존하고 차단한다", async () => {
  await fillToMapStep();
  fireEvent.change(screen.getByRole("textbox", { name: "키보드 원문" }), { target: { value: "이전 원문" } });
  const previous = sessionStorage.getItem(MAP_KEY);
  const originalGet = Storage.prototype.getItem;
  let written = false;
  const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(function(this: Storage, key, value) { originalSet.call(this, key, value); if (key === MAP_KEY) written = true; });
  const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(function(this: Storage, key) { if (key === MAP_KEY && written) return "mismatch"; return originalGet.call(this, key); });
  try {
    fireEvent.change(screen.getByRole("textbox", { name: "키보드 원문" }), { target: { value: "새 원문" } });
    expect(originalGet.call(sessionStorage, `${MAP_KEY}:backup`)).toBe(previous);
    expect(screen.getByRole("alert").textContent).toContain("이동하면 잃을 수");
    expect(requestMock).not.toHaveBeenCalled();
  } finally { set.mockRestore(); get.mockRestore(); }
});


it("지도 최초 mount의 빈 snapshot은 복구 원문을 덮지 못한다", async () => {
  await fillToMapStep();
  fireEvent.change(screen.getByRole("textbox", { name: "키보드 원문" }), { target: { value: "지켜야 할 원문" } });
  const raw = sessionStorage.getItem(MAP_KEY);
  cleanup();
  mocked.mountEmpty = true;
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" />);
  await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장");
  fireEvent.click(screen.getByRole("button", { name: "다음" }));
  expect(sessionStorage.getItem(MAP_KEY)).toBe(raw);
  expect(screen.getByRole("alert").textContent).toContain("이동하면 잃을 수");
  expect(requestMock).not.toHaveBeenCalled();
});

it("성공 영수증과 지도 원문이 함께 있으면 양쪽을 보존하고 자동 복원·제출을 차단한다", async () => {
  await fillToMapStep();
  fireEvent.change(screen.getByRole("textbox", { name: "키보드 원문" }), { target: { value: "미해결 원문" } });
  const map = sessionStorage.getItem(MAP_KEY);
  const draft = sessionStorage.getItem(DRAFT_KEY);
  cleanup();
  const receipt = JSON.stringify({ mode: "MAPPED_BOOTSTRAP", siteId: "site-12345678-1234-1234-1234-123456789012", name: "현장 A", fingerprint: ALICE });
  sessionStorage.setItem(`${DRAFT_KEY}:success`, receipt);
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" />);
  expect(await screen.findByRole("heading", { name: "지도 입력을 안전하게 복구할 수 없습니다" })).toBeTruthy();
  expect(screen.getByText(/요청 결과가 확정되는 것은 아닙니다/)).toBeTruthy();
  expect(sessionStorage.getItem(MAP_KEY)).toBe(map);
  expect(sessionStorage.getItem(DRAFT_KEY)).toBe(draft);
  expect(sessionStorage.getItem(`${DRAFT_KEY}:success`)).toBe(receipt);
  expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
  expect(requestMock).not.toHaveBeenCalled();
});


it("명시적으로 해소한 지도 원본은 확정 성공에만 정리하고 영수증을 남긴다", async () => {
  await fillToMapStep();
  fireEvent.change(screen.getByRole("textbox", { name: "키보드 원문" }), { target: { value: "미반영 원문" } });
  expect(sessionStorage.getItem(MAP_KEY)).toContain("미반영 원문");
  fireEvent.click(screen.getByRole("button", { name: "지도 입력 해소" }));
  fireEvent.click(screen.getByRole("button", { name: "다음" }));
  await screen.findByRole("button", { name: "현장 등록" });
  const issued = "site-12345678-1234-1234-1234-123456789012";
  requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A", AOI_ORIG), 201));
  fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
  expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
  expect(sessionStorage.getItem(MAP_KEY)).toBeNull();
  expect(sessionStorage.getItem(`${DRAFT_KEY}:success`)).toContain(issued);
});

it("지도 저장소를 읽지 못하면 존재 여부를 추측하지 않고 등록을 막는다", async () => {
  const draft = '{ "name": "기존 요청", "aoi": [], "originFingerprint": "' + ALICE + '" }';
  sessionStorage.setItem(DRAFT_KEY, draft);
  sessionStorage.setItem(MAP_KEY, '{ "unsupported": true }');
  const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(function(this: Storage, key) {
    if (key === MAP_KEY) throw new DOMException("unavailable", "SecurityError");
    return originalGetForFailure.call(this, key);
  });
  try {
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" />);
    expect(await screen.findByRole("heading", { name: "지도 입력을 안전하게 복구할 수 없습니다" })).toBeTruthy();
    expect(screen.getByText(/남은 백업은 자동으로 복구하거나 삭제하지 않습니다/)).toBeTruthy();
    expect(originalGetForFailure.call(sessionStorage, MAP_KEY)).toBe('{ "unsupported": true }');
    expect(originalGetForFailure.call(sessionStorage, DRAFT_KEY)).toBe(draft);
    expect(requestMock).not.toHaveBeenCalled();
  } finally { get.mockRestore(); }
});
const originalGetForFailure = Storage.prototype.getItem;

it("초안 지도 결속 기록의 readback 실패는 기존 초안 바이트를 백업하고 진입을 막는다", async () => {
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" />);
  fireEvent.change(await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장"), { target: { value: "결속 실패" } });
  const before = sessionStorage.getItem(DRAFT_KEY);
  let written = false;
  const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(function(this: Storage, key, value) { originalSet.call(this, key, value); if (key === DRAFT_KEY) written = true; });
  const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(function(this: Storage, key) { if (key === DRAFT_KEY && written) return "mismatch"; return originalGetForFailure.call(this, key); });
  try {
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    expect(originalGetForFailure.call(sessionStorage, `${DRAFT_KEY}:map-draft-backup`)).toBe(before);
    expect(screen.getByRole("heading", { name: "지도 입력을 안전하게 복구할 수 없습니다" })).toBeTruthy();
    expect(screen.queryByTestId("mock-map")).toBeNull();
  } finally { set.mockRestore(); get.mockRestore(); }
});

it("재진입 신원 확인 실패는 저장된 원문을 공개하거나 변경하지 않는다", async () => {
  await fillToMapStep();
  fireEvent.change(screen.getByRole("textbox", { name: "키보드 원문" }), { target: { value: "신원 확인 전 비공개" } });
  const map = sessionStorage.getItem(MAP_KEY);
  const draft = sessionStorage.getItem(DRAFT_KEY);
  cleanup();
  identityResponse = async () => jsonResponse({}, 503);
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" />);
  expect(await screen.findByText(/현재 계정을 확인할 수 없습니다/)).toBeTruthy();
  expect(screen.queryByDisplayValue("신원 확인 전 비공개")).toBeNull();
  expect(sessionStorage.getItem(MAP_KEY)).toBe(map);
  expect(sessionStorage.getItem(DRAFT_KEY)).toBe(draft);
  expect(requestMock).not.toHaveBeenCalled();
});
