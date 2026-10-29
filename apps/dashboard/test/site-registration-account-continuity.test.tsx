/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render as rtlRender, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement, type ReactElement } from "react";
import { createHash } from "node:crypto";

const mocked = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => mocked }));
vi.mock("@/components/map/AoiPolygonMap", () => ({
  AoiPolygonMap: ({ onChange }: { onChange?: (next: unknown) => void }) =>
    createElement(
      "div",
      { "data-testid": "mock-map" },
      onChange
        ? createElement(
            "button",
            {
              type: "button",
              onClick: () =>
                onChange([
                  { latDeg: 37.5, lonDeg: 127 },
                  { latDeg: 37.51, lonDeg: 127 },
                  { latDeg: 37.51, lonDeg: 127.01 },
                  { latDeg: 37.5, lonDeg: 127.01 },
                ]),
            },
            "범위 채우기",
          )
        : null,
    ),
}));

import { SiteRegistrationOnlyWizard } from "@/app/sites/new/SiteRegistrationOnlyWizard";
import { digestSitePostPayload } from "@/lib/site-registration/shared";

function fingerprint(org: string, actor: string): string {
  return `v1-${createHash("sha256").update(JSON.stringify(["ksi-observation-continuity-v1", org, actor])).digest("hex")}`;
}

const ALICE = fingerprint("org-a", "alice");
const BOB = fingerprint("org-a", "bob");

const AOI = [
  { latDeg: 37.5, lonDeg: 127 },
  { latDeg: 37.51, lonDeg: 127 },
  { latDeg: 37.51, lonDeg: 127.01 },
  { latDeg: 37.5, lonDeg: 127.01 },
];

describe("현장 등록 요청을 보내는 중 화면을 떠날 때", () => {
  for (const kind of ["mapped", "legacy"] as const) {
    it(`${kind} 요청은 POST 전에 원래 신원·본문 결속을 저장하고, 재진입 후 편집해도 지우지 않는다`, async () => {
      if (kind === "mapped") await goToConfirmMapped(ALICE);
      else await goToConfirmLegacy(ALICE);

      let storedWhenSent: Record<string, unknown> | null = null;
      requestMock.mockImplementationOnce(() => {
        storedWhenSent = JSON.parse(window.sessionStorage.getItem("ksi-wizard-site-registration-only") ?? "null");
        return new Promise<Response>(() => {});
      });
      fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
      expect(requestMock).toHaveBeenCalledTimes(1);
      const key = kind === "mapped" ? sentBody().bootstrapRequestId : sentBody().siteId;
      expect(storedWhenSent).toMatchObject({
        originFingerprint: ALICE,
        priorUnknowns: expect.arrayContaining([
          expect.objectContaining({ kind, key, originFingerprint: ALICE, payloadDigest: realDigest("현장 A"), name: "현장 A" }),
        ]),
      });

      cleanup();
      render(<SiteRegistrationOnlyWizard mode={kind === "mapped" ? "MAPPED_BOOTSTRAP" : "LEGACY_SITE_ID"} accountFingerprint={ALICE} />);
      const name = await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장");
      fireEvent.change(name, { target: { value: "새 현장 입력" } });
      await waitFor(() => {
        const draft = JSON.parse(window.sessionStorage.getItem("ksi-wizard-site-registration-only") ?? "null");
        expect(draft.priorUnknowns).toEqual(expect.arrayContaining([
          expect.objectContaining({ kind, key, originFingerprint: ALICE, payloadDigest: realDigest("현장 A"), name: "현장 A" }),
        ]));
      });
      expect(requestMock).toHaveBeenCalledTimes(1);
    });

    it(`${kind} 준비 기록을 저장하지 못하면 POST하지 않는다`, async () => {
      if (kind === "mapped") await goToConfirmMapped(ALICE);
      else await goToConfirmLegacy(ALICE);
      const key = "ksi-wizard-site-registration-only";
      const original = window.sessionStorage.getItem(key);
      const write = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); });
      try {
        fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
        expect(await screen.findByText(/등록 요청 정보를 저장하지 못해 요청을 보내지 않았습니다/)).toBeTruthy();
        expect(requestMock).not.toHaveBeenCalled();
        expect(window.sessionStorage.getItem(key)).toBe(original);
      } finally {
        write.mockRestore();
      }
    });

    it(`${kind} 첫 요청이 확정 실패면 준비 기록만 지운다`, async () => {
      if (kind === "mapped") await goToConfirmMapped(ALICE);
      else await goToConfirmLegacy(ALICE);
      requestMock.mockResolvedValueOnce(jsonResponse({ message: "형식을 확인하세요." }, 422));
      fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
      expect(await screen.findByText("형식을 확인하세요.")).toBeTruthy();
      await waitFor(() => {
        const draft = JSON.parse(window.sessionStorage.getItem("ksi-wizard-site-registration-only") ?? "null");
        expect(draft.priorUnknowns ?? []).toHaveLength(0);
      });
    });

    it(`${kind} 등록 버튼이 같은 이벤트 묶음에서 두 번 눌려도 POST는 하나만 보낸다`, async () => {
      if (kind === "mapped") await goToConfirmMapped(ALICE);
      else await goToConfirmLegacy(ALICE);
      requestMock.mockImplementation(() => new Promise<Response>(() => {}));
      const button = screen.getByRole("button", { name: "현장 등록" });
      act(() => {
        button.click();
        button.click();
      });
      expect(requestMock).toHaveBeenCalledTimes(1);
      const draft = JSON.parse(window.sessionStorage.getItem("ksi-wizard-site-registration-only") ?? "null");
      expect(draft.priorUnknowns).toHaveLength(1);
      expect(draft.priorUnknowns[0].key).toBe(kind === "mapped" ? sentBody().bootstrapRequestId : sentBody().siteId);
    });
  }
});

// 위저드가 실제로 POST하는 본문과 동일한 지문 — 모의 지도·좌표계·기본값 기준.
function realDigest(name: string): string {
  return digestSitePostPayload({
    name,
    aoi: AOI,
    crs: "EPSG:5186",
    verticalDatum: "KNGeoid2018",
    transformVersion: "1.0.0",
    egressChoice: "unset",
    jurisdiction: "",
    aiEgressAllowed: false,
  });
}

function echoSite(siteId: string, name: string): unknown {
  return {
    site: {
      siteId,
      name,
      siteFrame: { crs: "EPSG:5186", verticalDatum: "KNGeoid2018", unit: "meter", transformVersion: "1.0.0" },
      aoi: { vertices: structuredClone(AOI) },
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

const requestMock = vi.fn();
let currentIdentity: string | null = ALICE;
const identityMock = vi.fn(async (): Promise<Response> => currentIdentity
  ? jsonResponse({ fingerprint: currentIdentity }, 200)
  : jsonResponse({}, 503));
function render(element: ReactElement<{ accountFingerprint?: string | null }>) {
  currentIdentity = element.props.accountFingerprint ?? null;
  return rtlRender(element);
}

function sentHeaders(callIndex = 0): Headers {
  const init = requestMock.mock.calls[callIndex]?.[1] as RequestInit | undefined;
  return new Headers(init?.headers as HeadersInit | undefined);
}

function sentBody(callIndex = 0): Record<string, unknown> {
  const init = requestMock.mock.calls[callIndex]?.[1] as RequestInit | undefined;
  return JSON.parse(typeof init?.body === "string" ? init.body : "{}") as Record<string, unknown>;
}

async function goToConfirmLegacy(accountFingerprint: string | null = ALICE) {
  render(<SiteRegistrationOnlyWizard mode="LEGACY_SITE_ID" accountFingerprint={accountFingerprint} />);
  fireEvent.change(await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장"), {
    target: { value: "현장 A" },
  });
  fireEvent.change(screen.getByPlaceholderText("SITE-2026-001"), {
    target: { value: "site-A" },
  });
  fireEvent.click(screen.getByRole("button", { name: "다음" }));
  fireEvent.click(screen.getByRole("button", { name: "범위 채우기" }));
  fireEvent.change(screen.getByPlaceholderText("EPSG:5186"), { target: { value: "EPSG:5186" } });
  fireEvent.change(screen.getByPlaceholderText("KNGeoid2018"), { target: { value: "KNGeoid2018" } });
  fireEvent.click(screen.getByRole("button", { name: "다음" }));
  await screen.findByRole("button", { name: "현장 등록" });
}

async function goToConfirmMapped(accountFingerprint: string | null = ALICE) {
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={accountFingerprint} />);
  fireEvent.change(await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장"), {
    target: { value: "현장 A" },
  });
  fireEvent.click(screen.getByRole("button", { name: "다음" }));
  fireEvent.click(screen.getByRole("button", { name: "범위 채우기" }));
  fireEvent.change(screen.getByPlaceholderText("EPSG:5186"), { target: { value: "EPSG:5186" } });
  fireEvent.change(screen.getByPlaceholderText("KNGeoid2018"), { target: { value: "KNGeoid2018" } });
  fireEvent.click(screen.getByRole("button", { name: "다음" }));
  await screen.findByRole("button", { name: "현장 등록" });
}

beforeEach(() => {
  window.sessionStorage.clear();
  currentIdentity = ALICE;
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
    String(input) === "/api/account-identity" ? identityMock() : requestMock(input, init),
  ));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});

describe("현장 등록 계정 연속성 (사용자 이벤트)", () => {
  it("첫 제출에 현재 계정 지문을 싣는다", async () => {
    await goToConfirmMapped(ALICE);
    const issued = "site-12345678-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    expect(sentHeaders(0).get("x-ksi-continuity-fingerprint")).toBe(ALICE);
  });

  it("응답 유실 뒤 같은 키·같은 지문으로 재시도한다 (원래 계정 복구)", async () => {
    await goToConfirmMapped(ALICE);
    requestMock.mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText(/등록 결과를 확인하지 못했습니다/)).toBeTruthy();
    const firstKey = sentBody(0).bootstrapRequestId;

    const issued = "site-12345678-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    expect(sentBody(1).bootstrapRequestId).toBe(firstKey);
    expect(sentHeaders(1).get("x-ksi-continuity-fingerprint")).toBe(ALICE);
  });

  it("계정이 바뀌면 BFF 차단(409)을 확정 실패로 덮지 않고 입력을 보존한다", async () => {
    await goToConfirmMapped(ALICE);
    requestMock.mockResolvedValueOnce(
      jsonResponse({ message: "계정이 바뀌었습니다.", code: "ACCOUNT_CONTINUITY_MISMATCH" }, 409),
    );
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));

    expect(await screen.findByText(/입력은 그대로 있습니다/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "계정 정보 새로고침" })).toBeTruthy();
    expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
    expect(mocked.push).not.toHaveBeenCalled();
    // 입력과 요청 키는 그대로 — 다음 행동(원래 계정 복귀·목록 확인)이 가능하다.
    expect(window.sessionStorage.getItem("ksi-wizard-site-registration-only")).toContain("현장 A");
  });

  it("차단 뒤 계정 정보 새로고침은 라우터 새로고침만 하고 POST하지 않는다", async () => {
    await goToConfirmMapped(ALICE);
    requestMock.mockResolvedValueOnce(
      jsonResponse({ message: "계정이 바뀌었습니다.", code: "ACCOUNT_CONTINUITY_MISMATCH" }, 409),
    );
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    await screen.findByText(/입력은 그대로 있습니다/);
    const callsBefore = requestMock.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "계정 정보 새로고침" }));
    expect(mocked.refresh).toHaveBeenCalledTimes(1);
    expect(requestMock.mock.calls.length).toBe(callsBefore);
  });

  it("성공 확인은 원래 계정에서만 복원된다 (A 성공 → B 진입 복원 금지)", async () => {
    await goToConfirmMapped(ALICE);
    const issued = "site-12345678-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();

    cleanup();
    requestMock.mockClear();
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={BOB} />);
    await waitFor(() => {
      expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
    });
    expect(requestMock).not.toHaveBeenCalled();
  });

  it("401 뒤에도 이전 불명은 실패로 덮지 않는다 (같은 키 복구 가능)", async () => {
    await goToConfirmMapped(ALICE);
    requestMock.mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText(/등록 결과를 확인하지 못했습니다/)).toBeTruthy();

    requestMock.mockResolvedValueOnce(jsonResponse({ message: "세션이 만료되었습니다." }, 401));
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(await screen.findByText(/이전 요청의 결과는 여전히/)).toBeTruthy();
    expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
  });

  it("지문을 얻지 못한 새 초안은 POST하지 않고 계정 확인으로 fail-closed한다", async () => {
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={null} />);
    expect(await screen.findByText(/현재 계정을 확인할 수 없습니다/)).toBeTruthy();
    expect(screen.queryByPlaceholderText("예: OO산업단지 3공구 신축공사 현장")).toBeNull();
    expect(requestMock).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem("ksi-wizard-site-registration-only")).toBeNull();
  });

  it("지문 없는 구 초안(키만 있음)은 현재 지문으로 추측하지 않고 차단한다", async () => {
    window.sessionStorage.setItem(
      "ksi-wizard-site-registration-only",
      JSON.stringify({
        siteId: "",
        bootstrapRequestId: "22222222-2222-4333-8444-666666666666",
        name: "현장 A",
        aoi: [
          { latDeg: 37.5, lonDeg: 127 },
          { latDeg: 37.51, lonDeg: 127 },
          { latDeg: 37.51, lonDeg: 127.01 },
          { latDeg: 37.5, lonDeg: 127.01 },
        ],
        crs: "EPSG:5186",
        verticalDatum: "KNGeoid2018",
        transformVersion: "1.0.0",
        egressChoice: "unset",
        jurisdiction: "",
        aiEgressAllowed: false,
      }),
    );
    // 주체 미상 구 초안은 게이트가 먼저 막는다 — 입력 표시·전송 모두 금지.
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    expect(await screen.findByText("주인을 확인할 수 없는 입력입니다")).toBeTruthy();
    expect(screen.queryByDisplayValue("현장 A")).toBeNull();
    expect(screen.queryByRole("button", { name: "현장 등록" })).toBeNull();
    expect(requestMock).not.toHaveBeenCalled();
    // 원본은 그대로 보존된다 — 지우거나 현재 계정 것으로 바꾸지 않는다.
    const kept = JSON.parse(
      window.sessionStorage.getItem("ksi-wizard-site-registration-only") ?? "{}",
    ) as Record<string, unknown>;
    expect(kept.bootstrapRequestId).toBe("22222222-2222-4333-8444-666666666666");
    expect(kept.name).toBe("현장 A");
    expect(kept.originFingerprint).toBeUndefined();
  });

  it("차단 뒤 원래 계정으로 돌아오면 같은 키·지문 재시도가 막히지 않는다", async () => {
    await goToConfirmMapped(ALICE);
    requestMock.mockResolvedValueOnce(
      jsonResponse({ message: "계정이 바뀌었습니다.", code: "ACCOUNT_CONTINUITY_MISMATCH" }, 409),
    );
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    await screen.findByText(/입력은 그대로 있습니다/);
    const blockedKey = sentBody(0).bootstrapRequestId;

    // 원래 계정으로 복귀 — 하단 재시도 버튼이 막혀 있지 않아야 한다.
    const retryButton = screen.getByRole("button", { name: "다시 시도" });
    expect((retryButton as HTMLButtonElement).disabled).toBe(false);
    const issued = "site-12345678-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A"), 201));
    fireEvent.click(retryButton);
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    expect(sentBody(1).bootstrapRequestId).toBe(blockedKey);
    expect(sentHeaders(1).get("x-ksi-continuity-fingerprint")).toBe(ALICE);
  });

  it("B에게 A 입력 삭제 수단은 없고 원본이 그대로 보존된다", async () => {
    await goToConfirmMapped(ALICE);
    requestMock.mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText(/등록 결과를 확인하지 못했습니다/)).toBeTruthy();

    // 같은 탭에 B로 재진입 — 게이트가 A 입력을 숨기고 전송을 막는다.
    cleanup();
    requestMock.mockClear();
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={BOB} />);
    expect(await screen.findByText("다른 계정의 입력입니다")).toBeTruthy();
    expect(screen.queryByDisplayValue("현장 A")).toBeNull();
    expect((screen.getByRole("button", { name: "다음" }) as HTMLButtonElement).disabled).toBe(true);
    expect(requestMock).not.toHaveBeenCalled();

    // B에게는 입력을 지우는 수단이 없다 — 원본 삭제는 타 계정에 허용하지 않는다.
    expect(screen.queryByRole("button", { name: /지우기|새로 시작/ })).toBeNull();
    const draft = JSON.parse(
      window.sessionStorage.getItem("ksi-wizard-site-registration-only") ?? "{}",
    ) as { name?: unknown; priorUnknowns?: unknown[] };
    expect(draft.name).toBe("현장 A");
    expect(draft.priorUnknowns).toHaveLength(1);

    // A 복귀 시 입력·요청 키가 그대로 있어 같은 키로 복구된다.
    cleanup();
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    expect(await screen.findByDisplayValue("현장 A")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });
    const issued = "site-bbbbbbbb-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    const lastCall = requestMock.mock.calls.length - 1;
    expect(sentHeaders(lastCall).get("x-ksi-continuity-fingerprint")).toBe(ALICE);
  });

  it("B→A 왕복에서 A 입력·요청이 보존되고 같은 키로 복구된다", async () => {
    await goToConfirmMapped(ALICE);
    requestMock.mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText(/등록 결과를 확인하지 못했습니다/)).toBeTruthy();
    const firstKey = sentBody(0).bootstrapRequestId as string;

    cleanup();
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={BOB} />);
    expect(await screen.findByText("다른 계정의 입력입니다")).toBeTruthy();

    // A로 복귀 — 입력과 요청 키가 그대로 있어 같은 키로 복구된다.
    cleanup();
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    expect(await screen.findByDisplayValue("현장 A")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });

    const issued = "site-12345678-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    const lastCall = requestMock.mock.calls.length - 1;
    expect(sentBody(lastCall).bootstrapRequestId).toBe(firstKey);
    expect(sentHeaders(lastCall).get("x-ksi-continuity-fingerprint")).toBe(ALICE);
  });

  it("미해결 5건에서 신규 POST를 보내기 전 차단하고 명시적 정리 뒤 진행한다", async () => {
    const unknowns = Array.from({ length: 5 }, (_, i) => ({
      kind: "mapped",
      key: `old-key-${i}`,
      originFingerprint: ALICE,
      payloadDigest: "{}",
      name: `현장 X-${i}`,
    }));
    window.sessionStorage.setItem(
      "ksi-wizard-site-registration-only",
      JSON.stringify({
        siteId: "",
        name: "현장 A",
        aoi: [
          { latDeg: 37.5, lonDeg: 127 },
          { latDeg: 37.51, lonDeg: 127 },
          { latDeg: 37.51, lonDeg: 127.01 },
          { latDeg: 37.5, lonDeg: 127.01 },
        ],
        crs: "EPSG:5186",
        verticalDatum: "KNGeoid2018",
        transformVersion: "1.0.0",
        egressChoice: "unset",
        jurisdiction: "",
        aiEgressAllowed: false,
        originFingerprint: ALICE,
        priorUnknowns: unknowns,
      }),
    );
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    // 시드된 초안이 수화될 때까지 기다렸다가 이동한다.
    await screen.findByDisplayValue("현장 A");
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });

    // 6번째 키는 보내기 전 차단된다 — 조용히 버리지 않는다.
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText(/새로 보내기 전에 현장 목록에서/)).toBeTruthy();
    expect(requestMock).not.toHaveBeenCalled();

    // 명시적 정리 뒤 같은 입력으로 등록된다.
    const dismissButtons = screen.getAllByRole("button", { name: "기록 지우기" });
    expect(dismissButtons).toHaveLength(5);
    fireEvent.click(dismissButtons[0]!);
    const issued = "site-12345678-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    expect(screen.getByText(/확인되지 않은 이전 요청이 4건 있습니다/)).toBeTruthy();

    // 성공 후 이동해도 미해결 4건은 남는다.
    fireEvent.click(screen.getByRole("button", { name: "현장 브리핑으로 이동" }));
    expect(mocked.push).toHaveBeenCalledWith("/sites/site-12345678-1234-1234-1234-123456789012");
    const afterNav = JSON.parse(
      window.sessionStorage.getItem("ksi-wizard-site-registration-only") ?? "{}",
    ) as { name?: string; bootstrapRequestId?: string; priorUnknowns?: unknown[] };
    expect(afterNav.name ?? "").toBe("");
    expect(afterNav.bootstrapRequestId).toBeUndefined();
    expect(afterNav.priorUnknowns).toHaveLength(4);

    // remount 뒤에도 미해결 목록이 유지되고 입력은 비어 있다.
    // 입력이 비어 있으므로 확인 단계로 가려면 다시 입력해야 한다(실제 흐름).
    requestMock.mockClear();
    cleanup();
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    expect(screen.queryByDisplayValue("현장 A")).toBeNull();
    fireEvent.change(await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장"), {
      target: { value: "새 현장" },
    });
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "범위 채우기" }));
    fireEvent.change(screen.getByPlaceholderText("EPSG:5186"), { target: { value: "EPSG:5186" } });
    fireEvent.change(screen.getByPlaceholderText("KNGeoid2018"), { target: { value: "KNGeoid2018" } });
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });
    // 확인 단계에서 미해결 4건이 그대로 안내되고, 보내지 않은 채로 남아 있다.
    expect(screen.getAllByRole("button", { name: "기록 지우기" })).toHaveLength(4);
    expect(requestMock).not.toHaveBeenCalled();
  });

  it("이동 정리 저장 실패는 이동하지 않고 경고한다", async () => {
    await goToConfirmMapped(ALICE);
    const issued = "site-12345678-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.", { selector: "p" })).toBeTruthy();

    const setItem = vi.spyOn(Storage.prototype, "setItem");
    setItem.mockImplementationOnce(() => {
      throw new Error("quota exceeded");
    });
    fireEvent.click(screen.getByRole("button", { name: "현장 브리핑으로 이동" }));
    expect(await screen.findByText(/이동 전 정리를 브라우저에 저장하지 못했습니다/)).toBeTruthy();
    expect(mocked.push).not.toHaveBeenCalled();
    expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
    setItem.mockRestore();
  });

  it("legacy도 지문이 없으면 POST하지 않는다", async () => {
    render(<SiteRegistrationOnlyWizard mode="LEGACY_SITE_ID" accountFingerprint={null} />);
    expect(await screen.findByText(/현재 계정을 확인할 수 없습니다/)).toBeTruthy();
    expect(screen.queryByPlaceholderText("SITE-2026-001")).toBeNull();
    expect(requestMock).not.toHaveBeenCalled();
  });

  it("legacy 401 뒤에도 이전 불명은 실패로 덮지 않는다", async () => {
    await goToConfirmLegacy(ALICE);
    requestMock.mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText(/등록 결과를 확인하지 못했습니다/)).toBeTruthy();

    requestMock.mockResolvedValueOnce(jsonResponse({ message: "세션이 만료되었습니다." }, 401));
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(await screen.findByText(/이전 요청의 결과는 여전히/)).toBeTruthy();
    expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
  });
});

describe("현장 등록 계정 게이트·상세 비공개·라이브 확인", () => {
  function seedDraft(overrides: Record<string, unknown> = {}): void {
    window.sessionStorage.setItem(
      "ksi-wizard-site-registration-only",
      JSON.stringify({
        siteId: "",
        name: "현장 A",
        aoi: [
          { latDeg: 37.5, lonDeg: 127 },
          { latDeg: 37.51, lonDeg: 127 },
          { latDeg: 37.51, lonDeg: 127.01 },
          { latDeg: 37.5, lonDeg: 127.01 },
        ],
        crs: "EPSG:5186",
        verticalDatum: "KNGeoid2018",
        transformVersion: "1.0.0",
        egressChoice: "unset",
        jurisdiction: "",
        aiEgressAllowed: false,
        ...overrides,
      }),
    );
  }

  it("저장 신원 있고 페이지 신원 없으면 표시·전송을 막는다", async () => {
    seedDraft({ originFingerprint: ALICE, bootstrapRequestId: "33333333-2222-4333-8444-555555555555" });
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={null} />);
    expect(await screen.findByText(/현재 계정을 확인할 수 없습니다/)).toBeTruthy();
    expect(screen.queryByDisplayValue("현장 A")).toBeNull();
    expect(screen.queryByRole("button", { name: "다음" })).toBeNull();
    expect(requestMock).not.toHaveBeenCalled();
  });

  it("원래 주체가 없는 항목은 상세·지우기를 공개하지 않는다", async () => {
    seedDraft({
      originFingerprint: ALICE,
      priorUnknowns: [
        { kind: "mapped", key: "old-key-9", payloadDigest: "{}", name: "현장 X-9" },
      ],
    });
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    await screen.findByDisplayValue("현장 A");
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });
    // 건수는 안내하되 이름·지우기는 공개하지 않는다.
    expect(screen.getByText(/확인되지 않은 이전 요청이 1건 있습니다/)).toBeTruthy();
    expect(screen.getByText(/이름 비공개/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "기록 지우기" })).toBeNull();
  });

  it("첫 POST 전 입력부터 바인딩되어 B 재진입에 표시되지 않는다", async () => {
    await goToConfirmMapped(ALICE);
    // POST 없이 입력만 한 초안 — 지문이 함께 저장된다.
    const stored = JSON.parse(
      window.sessionStorage.getItem("ksi-wizard-site-registration-only") ?? "{}",
    ) as { originFingerprint?: string };
    expect(stored.originFingerprint).toBe(ALICE);

    cleanup();
    requestMock.mockClear();
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={BOB} />);
    expect(await screen.findByText("다른 계정의 입력입니다")).toBeTruthy();
    expect(screen.queryByDisplayValue("현장 A")).toBeNull();
    expect(screen.queryByRole("button", { name: "현장 등록" })).toBeNull();
    expect(requestMock).not.toHaveBeenCalled();
  });

  it("B 방문이 A 영수증을 지우지 않아 A 복귀 시 복원된다", async () => {
    await goToConfirmMapped(ALICE);
    const issued = "site-12345678-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();

    cleanup();
    requestMock.mockClear();
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={BOB} />);
    await waitFor(() => {
      expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
    });
    // B에게 보여주지 않되 원본 영수증은 보존한다.
    const kept = JSON.parse(
      window.sessionStorage.getItem("ksi-wizard-site-registration-only:success") ?? "null",
    ) as { siteId?: string } | null;
    expect(kept?.siteId).toBe(issued);

    cleanup();
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    expect(screen.getByText(issued)).toBeTruthy();
  });

  it("B는 A 기록을 지울 수 없다 (삭제 수단 없음·원본 보존)", async () => {
    seedDraft({
      originFingerprint: ALICE,
      priorUnknowns: [
        { kind: "mapped", key: "old-key-1", originFingerprint: ALICE, payloadDigest: "{}", name: "현장 X-1" },
      ],
    });
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={BOB} />);
    expect(await screen.findByText("다른 계정의 입력입니다")).toBeTruthy();
    expect(screen.queryByDisplayValue("현장 A")).toBeNull();
    // 타 계정에게는 지우기 수단 자체를 내지 않는다.
    expect(screen.queryByRole("button", { name: "기록 지우기" })).toBeNull();
    expect(screen.queryByRole("button", { name: /지우|새로 시작/ })).toBeNull();
    // B의 재진입 뒤에도 A 원본·기록이 그대로 있다.
    const draft = JSON.parse(
      window.sessionStorage.getItem("ksi-wizard-site-registration-only") ?? "{}",
    ) as { name?: unknown; originFingerprint?: unknown; priorUnknowns?: Array<Record<string, unknown>> };
    expect(draft.name).toBe("현장 A");
    expect(draft.originFingerprint).toBe(ALICE);
    expect(draft.priorUnknowns).toHaveLength(1);
    expect(draft.priorUnknowns?.[0]).toMatchObject({ key: "old-key-1", originFingerprint: ALICE });
  });

  it("A 응답 유실→B 시도→A 복귀에서 같은 본문·키·지문이 복구된다", async () => {
    await goToConfirmMapped(ALICE);
    requestMock.mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText(/등록 결과를 확인하지 못했습니다/)).toBeTruthy();
    const unknownKey = sentBody(0).bootstrapRequestId as string;

    // B가 봐도 A 원본은 그대로다 — 표시는 가리고 전송은 막는다.
    const callsBeforeRemount = requestMock.mock.calls.length;
    cleanup();
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={BOB} />);
    expect(await screen.findByText("다른 계정의 입력입니다")).toBeTruthy();
    expect(screen.queryByDisplayValue("현장 A")).toBeNull();
    expect(requestMock.mock.calls.length).toBe(callsBeforeRemount);

    // A 복귀 — 입력·키·지문이 그대로 복구되어 같은 키로 재시도된다.
    cleanup();
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    expect(await screen.findByDisplayValue("현장 A")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });
    const issued = "site-12345678-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.", { selector: "p" })).toBeTruthy();
    const lastCall = requestMock.mock.calls.length - 1;
    expect(sentBody(lastCall).bootstrapRequestId).toBe(unknownKey);
    expect(sentHeaders(lastCall).get("x-ksi-continuity-fingerprint")).toBe(ALICE);
  });

  it("live 확인이 다른 계정을 알리면 새로고침 없이 게이트가 뜬다", async () => {
    seedDraft({ originFingerprint: ALICE, bootstrapRequestId: "44444444-2222-4333-8444-555555555555" });
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    await screen.findByDisplayValue("현장 A");
    currentIdentity = BOB;
    window.dispatchEvent(new Event("focus"));
    expect(await screen.findByText("다른 계정의 입력입니다")).toBeTruthy();
    expect(screen.queryByDisplayValue("현장 A")).toBeNull();
    expect(requestMock).not.toHaveBeenCalled();
  });

  it("live 확인 실패는 상세를 숨기고 변이를 막는다", async () => {
    seedDraft({ originFingerprint: ALICE });
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    await screen.findByDisplayValue("현장 A");
    currentIdentity = null;
    window.dispatchEvent(new Event("focus"));
    expect(await screen.findByText(/현재 계정을 확인할 수 없습니다/)).toBeTruthy();
    expect(screen.queryByDisplayValue("현장 A")).toBeNull();
    expect(requestMock).not.toHaveBeenCalled();
  });

  it("저장 실패는 무변이·경고다 (제출·영수증)", async () => {
    await goToConfirmMapped(ALICE);
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    setItem.mockImplementationOnce(() => {
      throw new Error("quota exceeded");
    });
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText(/등록 요청 정보를 저장하지 못해/)).toBeTruthy();
    expect(requestMock).not.toHaveBeenCalled();
    setItem.mockRestore();


    // 영수증 저장 실패는 성공을 유지하되 화면 유지를 고지한다.
    // (제출 draft 저장이 먼저 성공해야 성공까지 가므로, 영수증 키에만 실패를 건다.)
    cleanup();
    window.sessionStorage.clear();
    await goToConfirmMapped(ALICE);
    const realSetItem = window.sessionStorage.setItem.bind(window.sessionStorage);
    const setItem3 = vi.spyOn(Storage.prototype, "setItem");
    setItem3.mockImplementation(((key: string, value: string) => {
      if (String(key).endsWith(":success")) throw new Error("quota exceeded");
      return realSetItem(key as string, value as string);
    }) as typeof Storage.prototype.setItem);
    const issued = "site-12345678-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    expect(screen.getByText(/이 확인은 이 화면에서만 유지됩니다/)).toBeTruthy();
    setItem3.mockRestore();
  });
});


describe("동일 키 충돌 기록의 신원 결속 (저장→복원)", () => {
  const COLLISION_KEY = "33333333-2222-4333-8444-555555555555";
  const VALID_DRAFT: Record<string, unknown> = {
    siteId: "",
    name: "현장 A",
    aoi: [
      { latDeg: 37.5, lonDeg: 127 },
      { latDeg: 37.51, lonDeg: 127 },
      { latDeg: 37.51, lonDeg: 127.01 },
      { latDeg: 37.5, lonDeg: 127.01 },
    ],
    crs: "EPSG:5186",
    verticalDatum: "KNGeoid2018",
    transformVersion: "1.0.0",
    egressChoice: "unset",
    jurisdiction: "",
    aiEgressAllowed: false,
    bootstrapRequestId: COLLISION_KEY,
    originFingerprint: ALICE,
  };

  function readDraft(): Record<string, unknown> {
    return JSON.parse(window.sessionStorage.getItem("ksi-wizard-site-registration-only") ?? "{}") as Record<
      string,
      unknown
    >;
  }

  it("같은 키의 A/B 기록이 둘 다 보존되고 서로 귀속되지 않는다", async () => {
    window.sessionStorage.setItem(
      "ksi-wizard-site-registration-only",
      JSON.stringify({
        ...VALID_DRAFT,
        priorUnknowns: [
          { kind: "mapped", key: COLLISION_KEY, originFingerprint: ALICE, payloadDigest: '{"v":1}', name: "현장 A" },
          { kind: "mapped", key: COLLISION_KEY, originFingerprint: BOB, payloadDigest: '{"v":1}', name: "현장 B" },
        ],
      }),
    );
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    await screen.findByDisplayValue("현장 A");
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });

    // A 항목은 이름·지우기 공개, B 항목은 이름 비공개·지우기 없음.
    // (확인 화면 요약에도 같은 이름이 나와 2건이다.)
    expect(screen.getAllByText("현장 A")).toHaveLength(2);
    expect(screen.getByText(/이름 비공개/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "기록 지우기" })).toHaveLength(1);
    expect(screen.queryByText("현장 B")).toBeNull();

    // 저장소에도 둘 다 그대로 있다.
    const draft = readDraft();
    expect((draft.priorUnknowns as Array<Record<string, unknown>>).filter((e) => e.key === COLLISION_KEY)).toHaveLength(2);
  });

  it("A의 지우기·성공은 B 기록을 건드리지 않는다", async () => {
    window.sessionStorage.setItem(
      "ksi-wizard-site-registration-only",
      JSON.stringify({
        ...VALID_DRAFT,
        priorUnknowns: [
          { kind: "mapped", key: COLLISION_KEY, originFingerprint: ALICE, payloadDigest: '{"v":1}', name: "현장 A" },
          { kind: "mapped", key: COLLISION_KEY, originFingerprint: BOB, payloadDigest: '{"v":1}', name: "현장 B" },
        ],
      }),
    );
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    await screen.findByDisplayValue("현장 A");
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });

    // A 항목만 지운다 — B 항목은 남는다 (확인 화면 요약의 이름은 그대로).
    fireEvent.click(screen.getByRole("button", { name: "기록 지우기" }));
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "기록 지우기" })).toBeNull();
    });
    expect(screen.getByText(/이름 비공개/)).toBeTruthy();
    const afterDismiss = readDraft().priorUnknowns as Array<Record<string, unknown>>;
    expect(afterDismiss).toHaveLength(1);
    expect(afterDismiss[0]).toMatchObject({ key: COLLISION_KEY, originFingerprint: BOB });
  });

  it("성공은 자기 원본 항목만 해소하고 타 주체 항목을 남긴다", async () => {
    window.sessionStorage.setItem(
      "ksi-wizard-site-registration-only",
      JSON.stringify({
        ...VALID_DRAFT,
        priorUnknowns: [
          { kind: "mapped", key: COLLISION_KEY, originFingerprint: ALICE, payloadDigest: realDigest("현장 A"), name: "현장 A" },
          { kind: "mapped", key: COLLISION_KEY, originFingerprint: BOB, payloadDigest: '{"v":1}', name: "현장 B" },
        ],
      }),
    );
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    await screen.findByDisplayValue("현장 A");
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });

    const issued = "site-12345678-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    const afterSuccess = readDraft().priorUnknowns as Array<Record<string, unknown>>;
    expect(afterSuccess).toHaveLength(1);
    expect(afterSuccess[0]).toMatchObject({ key: COLLISION_KEY, originFingerprint: BOB });
    // B 항목이 A 성공으로 귀속되지 않는다 — 이름 비공개 유지.
    expect(screen.getByText(/이름 비공개/)).toBeTruthy();
    expect(screen.queryByText("현장 B")).toBeNull();
  });

  it("성공 영수증 기록 시점에 본인 항목만 이미 해소되어 동기 이탈해도 남는다", async () => {
    window.sessionStorage.setItem("ksi-wizard-site-registration-only", JSON.stringify({ ...VALID_DRAFT, priorUnknowns: [
      { kind: "mapped", key: COLLISION_KEY, originFingerprint: ALICE, payloadDigest: realDigest("현장 A"), name: "현장 A" },
      { kind: "mapped", key: COLLISION_KEY, originFingerprint: BOB, payloadDigest: '{"v":1}', name: "현장 B" },
    ] }));
    const view = render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    await screen.findByDisplayValue("현장 A");
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });
    let atReceipt: unknown = null;
    const original = Storage.prototype.setItem;
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(function(this: Storage, key, value) {
      if (key === "ksi-wizard-site-registration-only:success") atReceipt = readDraft().priorUnknowns;
      original.call(this, key, value);
      if (key === "ksi-wizard-site-registration-only:success") view.unmount();
    });
    try {
      requestMock.mockResolvedValueOnce(jsonResponse(echoSite("site-12345678-1234-1234-1234-123456789012", "현장 A"), 201));
      fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
      await waitFor(() => expect(atReceipt).not.toBeNull());
      expect(atReceipt).toEqual([expect.objectContaining({ key: COLLISION_KEY, originFingerprint: BOB })]);
      expect(readDraft().priorUnknowns).toEqual([expect.objectContaining({ key: COLLISION_KEY, originFingerprint: BOB })]);
    } finally { spy.mockRestore(); }
  });

  it("성공 직후 unmount와 재진입에서도 타 주체 기록만 남는다", async () => {
    window.sessionStorage.setItem("ksi-wizard-site-registration-only", JSON.stringify({ ...VALID_DRAFT, priorUnknowns: [
      { kind: "mapped", key: COLLISION_KEY, originFingerprint: ALICE, payloadDigest: realDigest("현장 A"), name: "현장 A" },
      { kind: "mapped", key: COLLISION_KEY, originFingerprint: BOB, payloadDigest: '{"v":1}', name: "현장 B" },
    ] }));
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    await screen.findByDisplayValue("현장 A");
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite("site-12345678-1234-1234-1234-123456789012", "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    await screen.findByText("현장이 등록되었습니다.");
    cleanup();
    expect(readDraft().priorUnknowns).toEqual([expect.objectContaining({ originFingerprint: BOB, key: COLLISION_KEY })]);
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    await screen.findByText("현장이 등록되었습니다.");
    expect(readDraft().priorUnknowns).toEqual([expect.objectContaining({ originFingerprint: BOB, key: COLLISION_KEY })]);
    expect(screen.queryByText("현장 B")).toBeNull();
  });

  it.each(["draft", "receipt", "receipt-readback"])("확정 성공 뒤 %s 저장 실패는 원래 두 항목을 백업에 남기고 재전송을 막는다", async (failure) => {
    window.sessionStorage.setItem("ksi-wizard-site-registration-only", JSON.stringify({ ...VALID_DRAFT, priorUnknowns: [
      { kind: "mapped", key: COLLISION_KEY, originFingerprint: ALICE, payloadDigest: realDigest("현장 A"), name: "현장 A" },
      { kind: "mapped", key: COLLISION_KEY, originFingerprint: BOB, payloadDigest: '{"v":1}', name: "현장 B" },
    ] }));
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    await screen.findByDisplayValue("현장 A");
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });
    let resolve: (response: Response) => void = () => {};
    requestMock.mockImplementationOnce(() => new Promise<Response>((r) => { resolve = r; }));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    const prepared = window.sessionStorage.getItem("ksi-wizard-site-registration-only");
    const original = Storage.prototype.setItem;
    const originalGet = Storage.prototype.getItem;
    let receiptWritten = false;
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(function(this: Storage, key, value) {
      if ((failure === "draft" && key === "ksi-wizard-site-registration-only") || (failure === "receipt" && key === "ksi-wizard-site-registration-only:success")) throw new DOMException("quota", "QuotaExceededError");
      original.call(this, key, value);
      if (key === "ksi-wizard-site-registration-only:success") receiptWritten = true;
    });
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(function(this: Storage, key) {
      if (failure === "receipt-readback" && receiptWritten && key === "ksi-wizard-site-registration-only:success") return "mismatch";
      return originalGet.call(this, key);
    });
    try {
      await act(async () => resolve(jsonResponse(echoSite("site-12345678-1234-1234-1234-123456789012", "현장 A"), 201)));
      expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
      expect(screen.getByText(/초안 또는 영수증 저장·정리를 확인하지 못했습니다/)).toBeTruthy();
      expect(screen.getByText(/남은 백업은 자동으로 복구하거나 삭제하지 않습니다/)).toBeTruthy();
      expect(screen.queryByText(/요청 결과가 확정되는 것은 아닙니다/)).toBeNull();
      expect(screen.getByRole("link", { name: "별도 탭에서 새로 시작하기" }).getAttribute("rel")).toContain("noopener");
      expect((screen.getByRole("button", { name: "현장 브리핑으로 이동" }) as HTMLButtonElement).disabled).toBe(true);
      expect(window.sessionStorage.getItem("ksi-wizard-site-registration-only:success-draft-backup")).toBe(prepared);
      const backup = JSON.parse(prepared!) as { priorUnknowns: Array<{ originFingerprint: string }> };
      expect(backup.priorUnknowns.map((entry) => entry.originFingerprint)).toEqual([ALICE, BOB]);
      fireEvent.click(screen.getByRole("button", { name: "이전" }));
      expect(requestMock).toHaveBeenCalledTimes(1);
      cleanup();
    } finally { spy.mockRestore(); get.mockRestore(); }
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    expect(await screen.findByRole("heading", { name: "지도 입력을 안전하게 복구할 수 없습니다" })).toBeTruthy();
    expect(window.sessionStorage.getItem("ksi-wizard-site-registration-only:success-draft-backup")).toBe(prepared);
    expect(requestMock).toHaveBeenCalledTimes(1);
  });

  it("같은 키의 A/B 기록은 remount 뒤에도 보존되고 서로 귀속되지 않는다", async () => {
    window.sessionStorage.setItem(
      "ksi-wizard-site-registration-only",
      JSON.stringify({
        ...VALID_DRAFT,
        originFingerprint: ALICE,
        priorUnknowns: [
          { kind: "mapped", key: COLLISION_KEY, originFingerprint: ALICE, payloadDigest: '{"v":1}', name: "현장 A" },
          { kind: "mapped", key: COLLISION_KEY, originFingerprint: BOB, payloadDigest: '{"v":1}', name: "현장 B" },
        ],
      }),
    );
    cleanup();
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={BOB} />);
    expect(await screen.findByText("다른 계정의 입력입니다")).toBeTruthy();
    // B에게는 A 항목이 보이지 않고 지울 수도 없으며, B 자신의 항목만 보인다.
    expect(screen.queryByText("현장 A")).toBeNull();
    expect(screen.getByText("현장 B")).toBeTruthy();
    expect(screen.queryAllByRole("button", { name: "기록 지우기" })).toHaveLength(1);
    // remount 뒤에도 두 기록이 그대로 있다 — 어느 쪽도 귀속·삭제되지 않았다.
    cleanup();
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={BOB} />);
    await screen.findByText("다른 계정의 입력입니다");
    const draft = readDraft();
    expect((draft.priorUnknowns ?? []) as Array<Record<string, unknown>>).toHaveLength(2);
  });

  it("응답 역전(A 요청·B 확인 뒤 도착)은 성공 화면을 내지 않고 불명으로 둔다", async () => {
    let resolvePost: ((value: Response) => void) | null = null;
    requestMock.mockImplementation(async () => new Promise<Response>((resolve) => { resolvePost = resolve; }));
    await goToConfirmMapped(ALICE);
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    // POST가 진행 중인 동안 B 확인이 도착한다.
    await waitFor(() => {
      expect(requestMock.mock.calls.some(([url]) => String(url).includes("/api/sites"))).toBe(true);
    });
    currentIdentity = BOB;
    window.dispatchEvent(new Event("focus"));
    await screen.findByText("다른 계정의 입력입니다");

    const issued = "site-12345678-1234-1234-1234-123456789012";
    resolvePost!(jsonResponse(echoSite(issued, "현장 A"), 201));
    // A 응답이 와도 성공으로 단정하지 않는다 — 불명 안내 + B에게 A 이름 비공개.
    expect(await screen.findByText(/등록 결과를 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
    expect(screen.queryByDisplayValue("현장 A")).toBeNull();
    const draft = readDraft();
    expect(
      ((draft.priorUnknowns ?? []) as Array<Record<string, unknown>>).some(
        (entry) => entry.key !== undefined && entry.originFingerprint === ALICE,
      ),
    ).toBe(true);
  });

  it("6건 이상 기록과 훼손 항목을 저장 그대로 보존하고 정상으로 둔갑시키지 않는다", async () => {
    const valid = Array.from({ length: 6 }, (_, i) => ({
      kind: "mapped",
      key: `old-key-${i}`,
      originFingerprint: ALICE,
      payloadDigest: "{}",
      name: `현장 X-${i}`,
    }));
    const brokenNullOrigin = { kind: "mapped", key: "broken-1", originFingerprint: null, payloadDigest: "{}", name: "깨진 항목" };
    const brokenShape = { kind: "mapped", key: 42, name: "형식 깨짐" };
    const missingKind = { key: "broken-3", originFingerprint: ALICE, payloadDigest: "{}", name: "주체 없음" };
    const rawUnknowns = [...valid, brokenNullOrigin, brokenShape, missingKind];
    window.sessionStorage.setItem(
      "ksi-wizard-site-registration-only",
      JSON.stringify({ ...VALID_DRAFT, bootstrapRequestId: undefined, originFingerprint: ALICE, priorUnknowns: rawUnknowns }),
    );
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    await screen.findByDisplayValue("현장 A");

    // 수화만으로 원문을 재직렬화하지 않는다.
    expect((readDraft().priorUnknowns as unknown[])).toEqual(rawUnknowns);
    fireEvent.change(screen.getByDisplayValue("현장 A"), { target: { value: "현장 A 수정" } });
    await waitFor(() => expect(readDraft().name).toBe("현장 A 수정"));
    // 실제 편집 후 격리와 초과 유효 항목 모두 보존된다.
    const draft = readDraft() as { priorUnknowns?: unknown[]; quarantinedUnknowns?: unknown[] };
    expect(draft.priorUnknowns).toHaveLength(6);
    expect(draft.quarantinedUnknowns).toEqual([brokenNullOrigin, brokenShape, missingKind]);

    // 확인 단계에서 유효 6건은 보이고, 격리분은 개수만 보인다.
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });
    expect(screen.getByText(/확인되지 않은 이전 요청이 6건 있습니다/)).toBeTruthy();
    expect(screen.getByText(/읽을 수 없는 이전 기록이 3건 보존되어 있습니다/)).toBeTruthy();
    expect(screen.queryByText("깨진 항목")).toBeNull();
    expect(screen.queryByText("형식 깨짐")).toBeNull();
    // 격리분에는 지우기 버튼이 없다.
    expect(screen.getAllByRole("button", { name: "기록 지우기" })).toHaveLength(6);
  });

  it("정상 4건과 손상 1건도 상한이며 수화·편집·재진입에서 원문을 보존한다", async () => {
    const valid = Array.from({ length: 4 }, (_, i) => ({ kind: "mapped", key: `private-${i}`, originFingerprint: BOB, payloadDigest: `digest-${i}`, name: `private-${i}` }));
    const damaged = { kind: "mapped", key: "damaged", originFingerprint: null, future: { preserve: true } };
    const raw = JSON.stringify({ ...VALID_DRAFT, bootstrapRequestId: undefined, priorUnknowns: [...valid, damaged] });
    sessionStorage.setItem("ksi-wizard-site-registration-only", raw);
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    await screen.findByDisplayValue("현장 A");
    expect(sessionStorage.getItem("ksi-wizard-site-registration-only")).toBe(raw);
    fireEvent.change(screen.getByDisplayValue("현장 A"), { target: { value: "편집" } });
    await waitFor(() => expect(readDraft().name).toBe("편집"));
    cleanup();
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={ALICE} />);
    await screen.findByDisplayValue("편집");
    expect(readDraft().priorUnknowns).toEqual(valid);
    expect(readDraft().quarantinedUnknowns).toEqual([damaged]);
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });
    expect(screen.queryByText("private-0")).toBeNull();
    expect(screen.getByText(/읽을 수 없는 이전 기록이 1건/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText(/새로 보내기 전에 현장 목록에서/)).toBeTruthy();
    expect(requestMock).not.toHaveBeenCalled();
    expect(readDraft().priorUnknowns).toEqual(valid);
    expect(readDraft().quarantinedUnknowns).toEqual([damaged]);
  });

  it("레거시 같은 ID·다른 내용의 두 불명은 결속별로 보존되고 같은 키 재시도로 해소된다", async () => {
    await goToConfirmLegacy(ALICE);
    // 첫 요청 X: 미확인.
    requestMock.mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText(/등록 결과를 확인하지 못했습니다/)).toBeTruthy();

    // 같은 siteId로 내용을 바꿔 다시 시도 → 두 번째 불명 Y. X는 지워지지 않는다.
    fireEvent.click(screen.getByRole("button", { name: "이전" }));
    fireEvent.click(screen.getByRole("button", { name: "이전" }));
    fireEvent.change(await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장"), {
      target: { value: "현장 B" },
    });
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });
    requestMock.mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText(/등록 결과를 확인하지 못했습니다/)).toBeTruthy();

    // remount 뒤에도 두 결속이 그대로 보존된다(같은 siteId, 다른 내용).
    const beforeRemount = readDraft().priorUnknowns as Array<Record<string, unknown>>;
    expect(beforeRemount).toHaveLength(2);
    cleanup();
    render(<SiteRegistrationOnlyWizard mode="LEGACY_SITE_ID" accountFingerprint={ALICE} />);
    await screen.findByDisplayValue("현장 B");
    const afterRemount = readDraft().priorUnknowns as Array<Record<string, unknown>>;
    expect(afterRemount).toHaveLength(2);

    // 같은 키·같은 내용(Y)으로 재시도하면 Y만 해소되고 X는 남는다.
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });
    // legacy: 서버 발급이 아니라 요청한 siteId 그대로 돌려받아야 성공이다.
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite("site-A", "현장 B"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.", { selector: "p" })).toBeTruthy();
    const afterSuccess = readDraft().priorUnknowns as Array<Record<string, unknown>>;
    expect(afterSuccess).toHaveLength(1);
    expect(afterSuccess[0]).toMatchObject({ key: "site-A", name: "현장 A" });
  });
});


describe("동일 인스턴스 영수증 계정 복귀", () => {
  const receipt = JSON.stringify({ mode: "MAPPED_BOOTSTRAP", siteId: "site-receipt-a", name: "A 영수증 현장", fingerprint: ALICE });
  const key = "ksi-wizard-site-registration-only:success";
  it("B에서 숨기고 같은 인스턴스 A 복귀 때만 복원하며 다시 B로 바뀌면 숨긴다", async () => {
    sessionStorage.setItem(key, receipt);
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={BOB} />);
    await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장");
    expect(screen.queryByText("A 영수증 현장")).toBeNull();
    currentIdentity = ALICE;
    await act(async () => window.dispatchEvent(new Event("focus")));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    expect(screen.getByText("A 영수증 현장")).toBeTruthy();
    expect(screen.getByText("site-receipt-a")).toBeTruthy();
    currentIdentity = BOB;
    await act(async () => window.dispatchEvent(new Event("focus")));
    await waitFor(() => expect(screen.queryByText("A 영수증 현장")).toBeNull());
    expect(screen.queryByText("site-receipt-a")).toBeNull();
    expect(sessionStorage.getItem(key)).toBe(receipt);
    expect(requestMock).not.toHaveBeenCalled();
  });
  it("legacy 빈 B 진입도 자동 생성 초안 없이 A 영수증을 같은 인스턴스에서 복원한다", async () => {
    const legacyReceipt = JSON.stringify({ mode: "LEGACY_SITE_ID", siteId: "site-receipt-a", name: "A 영수증 현장", fingerprint: ALICE });
    sessionStorage.setItem(key, legacyReceipt);
    render(<SiteRegistrationOnlyWizard mode="LEGACY_SITE_ID" accountFingerprint={BOB} />);
    await screen.findByPlaceholderText("SITE-2026-001");
    expect(sessionStorage.getItem("ksi-wizard-site-registration-only")).toBeNull();
    expect(screen.queryByText("A 영수증 현장")).toBeNull();
    currentIdentity = ALICE;
    await act(async () => window.dispatchEvent(new Event("focus")));
    expect(await screen.findByText("A 영수증 현장")).toBeTruthy();
    expect(screen.getByText("site-receipt-a")).toBeTruthy();
    expect(sessionStorage.getItem(key)).toBe(legacyReceipt);
  });
  it("B가 편집한 초안을 A 복귀시 영수증 화면으로 덮지 않는다", async () => {
    sessionStorage.setItem(key, receipt);
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={BOB} />);
    fireEvent.change(await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장"), { target: { value: "B 작업 중" } });
    await waitFor(() => expect(JSON.parse(sessionStorage.getItem("ksi-wizard-site-registration-only")!).name).toBe("B 작업 중"));
    const before = sessionStorage.getItem("ksi-wizard-site-registration-only");
    currentIdentity = ALICE;
    await act(async () => window.dispatchEvent(new Event("focus")));
    expect(await screen.findByText("다른 계정의 입력입니다")).toBeTruthy();
    expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
    expect(screen.queryByText("A 영수증 현장")).toBeNull();
    expect(sessionStorage.getItem("ksi-wizard-site-registration-only")).toBe(before);
    currentIdentity = BOB;
    await act(async () => window.dispatchEvent(new Event("focus")));
    expect(await screen.findByDisplayValue("B 작업 중")).toBeTruthy();
    expect(sessionStorage.getItem(key)).toBe(receipt);
  });
});

describe("손상된 영수증 원문 보존", () => {
  it.each([undefined, "UNRECOGNIZED"])("mode %s 영수증은 등록 시 삭제하거나 덮어쓰지 않는다", async (mode) => {
    const raw = JSON.stringify({ mode, siteId: "old-receipt-id", name: "old receipt", fingerprint: ALICE });
    const key = "ksi-wizard-site-registration-only:success";
    sessionStorage.setItem(key, raw);
    await goToConfirmMapped(ALICE);
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite("site-12345678-1234-1234-1234-123456789012", "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    expect(sessionStorage.getItem(key)).toBe(raw);
    expect(screen.getByText(/이 확인은 이 화면에서만 유지됩니다/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "이전" }));
    expect(sessionStorage.getItem(key)).toBe(raw);
  });
});

it("같은 계정의 다른 mode 영수증도 삭제하거나 새 영수증으로 교체하지 않는다", async () => {
  const raw = JSON.stringify({ mode: "LEGACY_SITE_ID", siteId: "old-legacy", name: "이전 영수증", fingerprint: ALICE });
  const key = "ksi-wizard-site-registration-only:success";
  sessionStorage.setItem(key, raw);
  await goToConfirmMapped(ALICE);
  requestMock.mockResolvedValueOnce(jsonResponse(echoSite("site-12345678-1234-1234-1234-123456789012", "현장 A"), 201));
  fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
  expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
  expect(screen.getByText(/이 확인은 이 화면에서만 유지됩니다/)).toBeTruthy();
  expect(sessionStorage.getItem(key)).toBe(raw);
  fireEvent.click(screen.getByRole("button", { name: "이전" }));
  expect(sessionStorage.getItem(key)).toBe(raw);
});
