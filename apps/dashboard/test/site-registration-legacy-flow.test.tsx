/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";

const mocked = vi.hoisted(() => ({ push: vi.fn() }));

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

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const FINGERPRINT = "v1-" + "b".repeat(64);

function renderWizard() {
  return render(<SiteRegistrationOnlyWizard mode="LEGACY_SITE_ID" accountFingerprint={FINGERPRINT} />);
}

function fullEchoSite(overrides: Record<string, unknown> = {}): unknown {
  return {
    site: {
      siteId: "site-A",
      name: "현장 A",
      siteFrame: {
        crs: "EPSG:5186",
        verticalDatum: "KNGeoid2018",
        unit: "meter",
        transformVersion: "1.0.0",
      },
      aoi: {
        vertices: [
          { latDeg: 37.5, lonDeg: 127 },
          { latDeg: 37.51, lonDeg: 127 },
          { latDeg: 37.51, lonDeg: 127.01 },
          { latDeg: 37.5, lonDeg: 127.01 },
        ],
      },
      dataResidency: null,
      aiEgressAllowed: false,
      ...overrides,
    },
  };
}

async function goToConfirm() {
  fireEvent.change(await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장"), {
    target: { value: "현장 A" },
  });
  const siteIdInput = screen.getByPlaceholderText("SITE-2026-001");
  fireEvent.change(siteIdInput, { target: { value: "site-A" } });
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

describe("레거시 현장 등록 409·불명 (사용자 이벤트)", () => {
  it("타인 ID 첫 409는 실패이며 자동 성공·이동이 없다", async () => {
    renderWizard();
    await goToConfirm();
    requestMock.mockResolvedValueOnce(
      jsonResponse({ message: "이미 등록된 현장 ID입니다.", code: "DUPLICATE_SITE_ID" }, 409),
    );
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText(/이미 등록된 현장 ID입니다/)).toBeTruthy();
    expect(mocked.push).not.toHaveBeenCalled();
  });

  it("2xx 관측 뒤 같은 ID의 409도 자동 성공하지 않는다 (계정 미검증)", async () => {
    renderWizard();
    await goToConfirm();
    requestMock.mockResolvedValueOnce(jsonResponse(fullEchoSite(), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    await screen.findByText("현장이 등록되었습니다.");

    fireEvent.click(screen.getByRole("button", { name: "이전" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });
    requestMock.mockResolvedValueOnce(
      jsonResponse({ message: "이미 등록된 현장 ID입니다.", code: "DUPLICATE_SITE_ID" }, 409),
    );
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText(/자동으로 들어가지 않았습니다/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "현장 목록에서 직접 확인하기" })).toBeTruthy();
    // 자동 성공 경로(2번째 push)가 열리지 않는다
    await waitFor(() => {
      expect(mocked.push).toHaveBeenCalledTimes(0);
    });
  });

  it("body가 바뀌면 바뀜을 밝히고 성공이 아니다", async () => {
    renderWizard();
    await goToConfirm();
    requestMock.mockResolvedValueOnce(jsonResponse(fullEchoSite(), 201));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    await screen.findByText("현장이 등록되었습니다.");

    fireEvent.click(screen.getByRole("button", { name: "이전" }));
    fireEvent.click(screen.getByRole("button", { name: "이전" }));
    fireEvent.change(await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장"), {
      target: { value: "바뀐 이름" },
    });
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await screen.findByRole("button", { name: "현장 등록" });
    requestMock.mockResolvedValueOnce(
      jsonResponse({ message: "이미 등록된 현장 ID입니다.", code: "DUPLICATE_SITE_ID" }, 409),
    );
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText(/바뀐 내용/)).toBeTruthy();
    expect(mocked.push).not.toHaveBeenCalled();
  });

  it("code 있는 불명 5xx는 unknown이며 다음 409도 확인 필요다", async () => {
    renderWizard();
    await goToConfirm();
    requestMock.mockResolvedValueOnce(
      jsonResponse({ message: "점검 중", code: "STORE_UNAVAILABLE" }, 503),
    );
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText(/결과를 확인하지 못했습니다/)).toBeTruthy();

    requestMock.mockResolvedValueOnce(
      jsonResponse({ message: "이미 등록된 현장 ID입니다.", code: "DUPLICATE_SITE_ID" }, 409),
    );
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(await screen.findByText(/알 수 없어 자동으로/)).toBeTruthy();
    expect(mocked.push).not.toHaveBeenCalled();
  });

  it("불명 뒤 4xx는 확정 실패이면서 이전 불명을 살린다", async () => {
    renderWizard();
    await goToConfirm();
    requestMock.mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(await screen.findByText(/결과를 확인하지 못했습니다/)).toBeTruthy();

    requestMock.mockResolvedValueOnce(
      jsonResponse({ message: "입력값이 올바르지 않습니다.", code: "INVALID_SITE" }, 422),
    );
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    const err = await screen.findByText(/입력값이 올바르지 않습니다/);
    expect(err).toBeTruthy();
    expect(screen.getByText(/이전 요청의 결과는 여전히/)).toBeTruthy();

    // 그 뒤 409는 남의 ID 확정이 아니라 확인 필요다
    requestMock.mockResolvedValueOnce(
      jsonResponse({ message: "이미 등록된 현장 ID입니다.", code: "DUPLICATE_SITE_ID" }, 409),
    );
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(await screen.findByText(/알 수 없어 자동으로/)).toBeTruthy();
    expect(mocked.push).not.toHaveBeenCalled();
  });
});
