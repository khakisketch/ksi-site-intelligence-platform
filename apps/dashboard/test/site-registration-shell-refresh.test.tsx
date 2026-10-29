/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
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

vi.mock("@/components/nav/AccountDisplayBoundary", () => ({useAccountDisplayLock: () => ({locked: () => false, generation: () => 0})}));
import { SiteListProvider, useSidebarSites } from "@/components/nav/SiteListContext";
function Summary() { const sites = useSidebarSites(); return <div data-testid="summary">{sites.map(s => s.name).join(',')}</div>; }
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

async function goToConfirmMapped() {
  render(<SiteListProvider sites={[]} fingerprint={FINGERPRINT}><Summary/><SiteRegistrationOnlyWizard mode="MAPPED_BOOTSTRAP" accountFingerprint={FINGERPRINT}/></SiteListProvider>);
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

it("successful mapped registration refreshes only on explicit briefing click", async () => {
 const issued="site-12345678-1234-1234-1234-123456789012";
 requestMock.mockImplementation(async (input: RequestInfo | URL) => String(input)==="/api/sites" ? jsonResponse(echoSite(issued,"현장 A"),201) : jsonResponse({fingerprint:FINGERPRINT,sites:[{siteId:issued,name:"현장 A",status:"UNMAPPED"}]},200));
 await goToConfirmMapped(); fireEvent.click(screen.getByRole("button",{name:"현장 등록"}));
 await screen.findByText("현장이 등록되었습니다.");
 expect(requestMock.mock.calls.filter(x=>String(x[0])==="/api/shell-sites")).toHaveLength(0);
 fireEvent.click(screen.getByRole("button",{name:"현장 브리핑으로 이동"}));
 await waitFor(()=>expect(screen.getByTestId("summary").textContent).toBe("현장 A"));
 expect(mocked.push).toHaveBeenCalledWith(`/sites/${issued}`);
});
