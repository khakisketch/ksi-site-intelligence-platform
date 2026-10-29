/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";

const mocked = vi.hoisted(() => ({ push: vi.fn() }));

const FINGERPRINT = "v1-" + "a".repeat(64);

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

const AOI = [
  { latDeg: 37.5, lonDeg: 127 },
  { latDeg: 37.51, lonDeg: 127 },
  { latDeg: 37.51, lonDeg: 127.01 },
  { latDeg: 37.5, lonDeg: 127.01 },
];

function echoSite(siteId: string, name: string, overrides: Record<string, unknown> = {}): unknown {
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
      aoi: { vertices: structuredClone(AOI) },
      dataResidency: null,
      aiEgressAllowed: false,
      ...overrides,
    },
  };
}

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function goToConfirmLegacy() {
  render(<SiteRegistrationOnlyWizard mode="LEGACY_SITE_ID" accountFingerprint={FINGERPRINT} />);
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

async function goToConfirmMapped() {
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={FINGERPRINT} />);
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

const requestMock = vi.fn();

beforeEach(() => {
  window.sessionStorage.clear();
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
    String(input) === "/api/account-identity"
      ? Promise.resolve(jsonResponse({ fingerprint: FINGERPRINT }, 200))
      : requestMock(input, init),
  ));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});

describe("현장 등록 성공 결속 (사용자 이벤트)", () => {
  it("원본과 완전히 결속된 2xx만 성공이며 ID·다음 행동이 보인다", async () => {
    await goToConfirmLegacy();
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite("site-A", "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));

    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    expect(screen.getByText("site-A")).toBeTruthy();
    expect(screen.getByText("현장 목록에서 직접 확인하기")).toBeTruthy();
    expect(mocked.push).not.toHaveBeenCalled();

    // 확인된 등록으로 브리핑에 들어간다.
    fireEvent.click(screen.getByRole("button", { name: "현장 브리핑으로 이동" }));
    expect(mocked.push).toHaveBeenCalledWith("/sites/site-A");
  });

  it("2xx라도 이름이 다르면 성공이 아니라 확인 필요다", async () => {
    await goToConfirmLegacy();
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite("site-A", "다른 현장"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));

    expect(await screen.findByText(/등록 결과를 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
    expect(mocked.push).not.toHaveBeenCalled();
  });

  it("2xx 불완전 본문({})은 성공이 아니라 확인 필요다", async () => {
    await goToConfirmLegacy();
    requestMock.mockResolvedValueOnce(jsonResponse({}, 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));

    expect(await screen.findByText(/등록 결과를 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
    expect(mocked.push).not.toHaveBeenCalled();
  });

  it("2xx 깨진 JSON은 성공이 아니라 확인 필요다", async () => {
    await goToConfirmLegacy();
    requestMock.mockResolvedValueOnce(
      new Response("not json", { status: 201, headers: { "Content-Type": "application/json" } }),
    );
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));

    expect(await screen.findByText(/등록 결과를 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
    expect(mocked.push).not.toHaveBeenCalled();
  });

  it("mapped 2xx는 발급 ID+원본 결속으로 성공한다", async () => {
    await goToConfirmMapped();
    const issued = "site-12345678-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite(issued, "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));

    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    expect(screen.getByText(issued)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "현장 브리핑으로 이동" }));
    expect(mocked.push).toHaveBeenCalledWith(`/sites/${issued}`);
  });

  it("mapped 2xx라도 원본이 다르면 성공이 아니다", async () => {
    await goToConfirmMapped();
    const issued = "site-12345678-1234-1234-1234-123456789012";
    requestMock.mockResolvedValueOnce(
      jsonResponse(echoSite(issued, "바뀐 이름"), 201),
    );
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));

    expect(await screen.findByText(/등록 결과를 확인하지 못했습니다/)).toBeTruthy();
    expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
    expect(mocked.push).not.toHaveBeenCalled();
  });

  it("mapped 네트워크 실패는 확정 실패가 아니라 같은 키 재시도 안내다", async () => {
    await goToConfirmMapped();
    requestMock.mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));

    expect(await screen.findByText(/등록 결과를 확인하지 못했습니다/)).toBeTruthy();
    expect(await screen.findByText(/중복 등록이 되지 않습니다/)).toBeTruthy();
    expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
  });
});

describe("성공 뒤 새로고침·권한 실패 경계", () => {
  it("새로고침으로 마법사가 다시 마운트돼도 확인 화면·다음 행동이 복원된다", async () => {
    await goToConfirmLegacy();
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite("site-A", "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();

    // 권한·조회 실패로 완성 화면이 unmount됐다가 같은 탭에서 다시 마운트된 상황을
    // 재현한다 — 네트워크 없이 같은 계정 지문으로 복원되어야 한다.
    cleanup();
    requestMock.mockClear();
    render(<SiteRegistrationOnlyWizard mode="LEGACY_SITE_ID" accountFingerprint={FINGERPRINT} />);

    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    expect(screen.getByText("site-A")).toBeTruthy();
    expect(screen.getByRole("link", { name: "현장 목록에서 직접 확인하기" })).toBeTruthy();
    expect(requestMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "현장 브리핑으로 이동" }));
    expect(mocked.push).toHaveBeenCalledWith("/sites/site-A");
  });

  it("확인 화면에서 이전으로 돌아가면 복원이 지워진다", async () => {
    await goToConfirmLegacy();
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite("site-A", "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "이전" }));
    await screen.findByRole("button", { name: "다음" });

    cleanup();
    render(<SiteRegistrationOnlyWizard mode="LEGACY_SITE_ID" accountFingerprint={FINGERPRINT} />);
    await waitFor(() => {
      expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
    });
  });
});

describe("동일 계정의 영수증과 편집 초안 충돌", () => {
  it("지문이 없는 이전 형식 영수증을 다른 저장 초안의 성공으로 추측하지 않는다", async () => {
    const key = "ksi-wizard-site-registration-only";
    const draft = JSON.stringify({ name: "현재 작성 중인 현장", siteId: "", aoi: [], originFingerprint: FINGERPRINT });
    const receipt = JSON.stringify({ mode: "MAPPED_BOOTSTRAP", siteId: "older-site", name: "이전 현장", fingerprint: FINGERPRINT });
    sessionStorage.setItem(key, draft);
    sessionStorage.setItem(`${key}:success`, receipt);
    render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={FINGERPRINT} />);
    expect(await screen.findByDisplayValue("현재 작성 중인 현장")).toBeTruthy();
    expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
    expect(sessionStorage.getItem(key)).toBe(draft);
    expect(sessionStorage.getItem(`${key}:success`)).toBe(receipt);
  });

  it("성공 후 영수증 삭제가 실패하고 수정·재마운트해도 수정 초안을 보여준다", async () => {
    await goToConfirmLegacy();
    requestMock.mockResolvedValueOnce(jsonResponse(echoSite("site-A", "현장 A"), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    const originalReceipt = sessionStorage.getItem("ksi-wizard-site-registration-only:success");
    const remove = vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new Error("blocked"); });
    fireEvent.click(screen.getByRole("button", { name: "이전" }));
    fireEvent.click(screen.getByRole("button", { name: "이전" }));
    fireEvent.change(screen.getByDisplayValue("현장 A"), { target: { value: "다시 작성 중" } });
    await waitFor(() => expect(JSON.parse(sessionStorage.getItem("ksi-wizard-site-registration-only")!).name).toBe("다시 작성 중"));
    remove.mockRestore();
    cleanup();
    render(<SiteRegistrationOnlyWizard mode="LEGACY_SITE_ID" accountFingerprint={FINGERPRINT} />);
    expect(await screen.findByDisplayValue("다시 작성 중")).toBeTruthy();
    expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
    expect(sessionStorage.getItem("ksi-wizard-site-registration-only:success")).toBe(originalReceipt);
  });
});

it("mapped 등록의 결속된 영수증은 동일 초안 재마운트에서 복원된다", async () => {
  await goToConfirmMapped();
  const id = "site-12345678-1234-1234-1234-123456789012";
  requestMock.mockResolvedValueOnce(jsonResponse(echoSite(id, "현장 A"), 201));
  fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
  expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
  cleanup();
  const outside = document.createElement("button"); document.body.appendChild(outside); outside.focus();
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={FINGERPRINT} />);
  expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
  expect(screen.getByText(id)).toBeTruthy();
  expect(document.activeElement).toBe(outside);
  outside.remove();
});

it("충돌된 구 영수증은 포커스 재확인 후에도 현재 초안을 가리지 않는다", async () => {
  const key = "ksi-wizard-site-registration-only";
  const draft = JSON.stringify({ name: "보존할 편집", siteId: "", aoi: [], originFingerprint: FINGERPRINT });
  const receipt = JSON.stringify({ mode: "MAPPED_BOOTSTRAP", siteId: "old-site", name: "이전 현장", fingerprint: FINGERPRINT });
  sessionStorage.setItem(key, draft);
  sessionStorage.setItem(`${key}:success`, receipt);
  render(<SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={FINGERPRINT} />);
  await screen.findByDisplayValue("보존할 편집");
  fireEvent.focus(window);
  expect(await screen.findByDisplayValue("보존할 편집")).toBeTruthy();
  expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
  expect(sessionStorage.getItem(key)).toBe(draft);
  expect(sessionStorage.getItem(`${key}:success`)).toBe(receipt);
});

describe("제출 포커스와 중복 방지", () => {
  it("요청 중 제출 포커스를 유지하고 후속 활성화는 무시한다", async () => {
    let resolve!: (response: Response) => void;
    requestMock.mockImplementation(() => new Promise<Response>((done) => { resolve = done; }));
    await goToConfirmMapped();
    const submit = screen.getByRole("button", { name: "현장 등록" }) as HTMLButtonElement;
    submit.focus();
    fireEvent.click(submit);
    const pending = await screen.findByRole("button", { name: "처리 중…" });
    expect(pending).toBe(submit);
    expect(submit.disabled).toBe(false);
    expect(submit.getAttribute("aria-disabled")).toBe("true");
    expect(document.activeElement).toBe(submit);
    fireEvent.click(submit);
    fireEvent.keyDown(submit, { key: "Enter" }); fireEvent.keyUp(submit, { key: "Enter" });
    fireEvent.keyDown(submit, { key: " " }); fireEvent.keyUp(submit, { key: " " });
    expect(requestMock).toHaveBeenCalledTimes(1);
    resolve(jsonResponse(echoSite("site-A", "현장 A"), 201));
    expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
    expect(document.activeElement).toBe(submit);
    expect(mocked.push).not.toHaveBeenCalled();
  });
});

describe("대기 이후의 포커스", () => {
  it.each(["success", "unknown", "failure"])("사용자가 다른 곳으로 옮긴 뒤 %s 응답이 포커스를 가져가지 않는다", async (outcome) => {
    let resolve!: (response: Response) => void;
    requestMock.mockImplementation(() => new Promise<Response>((done) => { resolve = done; }));
    await goToConfirmMapped();
    const submit = screen.getByRole("button", { name: "현장 등록" });
    submit.focus();
    fireEvent.click(submit);
    await screen.findByText("현장을 등록하는 중입니다…");
    const other = document.createElement("button"); other.textContent = "다른 작업"; document.body.appendChild(other); other.focus();
    resolve(outcome === "success" ? jsonResponse(echoSite("site-A", "현장 A"), 201) : outcome === "unknown" ? jsonResponse({}, 201) : jsonResponse({ message: "거부됨" }, 403));
    if (outcome === "success") await screen.findByText("현장이 등록되었습니다.");
    else await screen.findByText(/처리 중 문제가 발생했습니다/);
    expect(document.activeElement).toBe(other);
    expect(mocked.push).not.toHaveBeenCalled();
    if (outcome !== "success") expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
    other.remove();
  });
});

it("state commit 전 동기 중복 클릭도 하나의 요청만 보낸다", async () => {
  let resolve!: (response: Response) => void;
  requestMock.mockImplementation(() => new Promise<Response>((done) => { resolve = done; }));
  await goToConfirmMapped();
  const submit = screen.getByRole("button", { name: "현장 등록" });
  act(() => { submit.click(); submit.click(); });
  expect(requestMock).toHaveBeenCalledTimes(1);
  resolve(jsonResponse(echoSite("site-A", "현장 A"), 201));
  expect(await screen.findByText("현장이 등록되었습니다.")).toBeTruthy();
});

it("계정 확인이 무효화된 동안 늦은 응답은 성공을 노출하거나 포커스를 가져가지 않는다", async () => {
  let resolve!: (response: Response) => void;
  requestMock.mockImplementation(() => new Promise<Response>((done) => { resolve = done; }));
  await goToConfirmMapped();
  const submit = screen.getByRole("button", { name: "현장 등록" }); submit.focus(); fireEvent.click(submit);
  await screen.findByText("현장을 등록하는 중입니다…");
  fireEvent.blur(window);
  const other = document.createElement("button"); document.body.appendChild(other); other.focus();
  resolve(jsonResponse(echoSite("site-A", "현장 A"), 201));
  await waitFor(() => expect(requestMock).toHaveBeenCalledTimes(1));
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  expect(screen.queryByText("현장이 등록되었습니다.")).toBeNull();
  expect(document.activeElement).toBe(other);
  expect(mocked.push).not.toHaveBeenCalled(); other.remove();
});
