/** @vitest-environment jsdom */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

// 첫 등록 동의 문구 전용 — 값·기본값·전송 계약은 바꾸지 않고 사람이 읽는
// 설명(외부 클라우드 3지선다 + 분리된 AI 동의 + 확인 화면 요약)만 다룬다.
const WIZARD = readFileSync(
  join(process.cwd(), "src/app/sites/new/SiteRegistrationOnlyWizard.tsx"),
  "utf8",
);

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const FINGERPRINT = "v1-" + "c".repeat(64);

beforeEach(() => {
  window.sessionStorage.clear();
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) =>
      String(input) === "/api/account-identity"
        ? Promise.resolve(jsonResponse({ fingerprint: FINGERPRINT }, 200))
        : Promise.reject(new Error(`unexpected fetch: ${String(input)}`)),
    ),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});

describe("registration consent clarity (copy contract)", () => {
  it("외부 클라우드 3지선다마다 결과를 함께 말한다", () => {
    expect(WIZARD).toContain("외부 클라우드 처리 동의");
    expect(WIZARD).toContain("벤더 클라우드 처리 작업을 발급할 수 없습니다.");
    expect(WIZARD).toContain("등록 후 변경할 수 없습니다. 허용 또는 불허를 고르면 처리 기준 관할이 필요합니다.");
  });

  it("AI 동의는 별도 묶음이며 기본값·원본 제외를 함께 말한다", () => {
    expect(WIZARD).toContain("KSI AI 활용 동의 (선택 사항)");
    expect(WIZARD).toContain("기본값은 허용하지 않음입니다.");
    expect(WIZARD).toContain("이 등록 과정에서는 고객 원본 사진을 요청하지 않습니다.");
    expect(WIZARD).toContain("동의만으로 AI가 실행되지는 않습니다.");
    expect(WIZARD).not.toContain("구조화된 현장 결과만 KSI AI가 읽습니다");
  });

  it("확인 화면에서 외부 클라우드·관할·AI 범위를 요약한다", () => {
    expect(WIZARD).toContain("외부 클라우드");
    expect(WIZARD).toContain("처리 기준 관할");
    expect(WIZARD).toContain("미정 — 벤더 클라우드 처리 작업 발급 불가");
    expect(WIZARD).toContain("허용 — 실제 접근에는 별도 설정과 권한이 필요");
    expect(WIZARD).toContain("허용하지 않음(기본값)");
  });

  it("기본값·미선언 fail-closed 전송 계약을 그대로 둔다", () => {
    expect(WIZARD).toContain('egressChoice: "unset"');
    expect(WIZARD).toContain("aiEgressAllowed: false");
    expect(WIZARD).toContain("buildDataResidencyInput(");
    expect(WIZARD).toContain("aiEgressAllowed: form.aiEgressAllowed");
    // 미선언(unset)은 키 자체를 생략해 서버가 반출 불가로 처리한다.
    expect(WIZARD).toContain("dataResidency,");
  });
});

describe("registration consent clarity (rendered step 0)", () => {
  it("기본 3지선다·관할 없음·AI 미선택으로 시작한다", async () => {
    render(
      <SiteRegistrationOnlyWizard mode="LEGACY_SITE_ID" accountFingerprint={FINGERPRINT} />,
    );
    const group = await screen.findByRole("group", { name: "외부 클라우드 처리 동의" });
    expect(group).toBeTruthy();
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(3);
    expect((radios[0] as HTMLInputElement).checked).toBe(true);
    expect(screen.getByRole("radio", { name: /미정 \(기본값 — 등록 후 변경 불가\)/ })).toBeTruthy();
    expect(screen.getByRole("radio", { name: /아니오 — 외부 클라우드 처리를 허용하지 않음/ })).toBeTruthy();
    expect(screen.getByRole("group", { name: "KSI AI 활용 동의 (선택 사항)" }).textContent).toContain("외부 클라우드 처리 선택과 별개");
    expect(screen.getByText(/다음 단계의 OpenStreetMap 타일 요청/).textContent).toContain("접속 IP");
    expect(screen.getByText(/다음 단계의 OpenStreetMap 타일 요청/).textContent).toContain("클라우드 처리 선택 및 AI 동의와 별개");
    expect(screen.queryByText(/미정이면 외부로 보내지 않습니다/)).toBeNull();
    // unset 기본값이므로 관할 입력은 아직 없다.
    expect(screen.queryByPlaceholderText("KR")).toBeNull();
    const ai = screen.getByRole("checkbox", {
      name: /외부 AI의 현장 정보 접근을 허용/,
    });
    expect((ai as HTMLInputElement).checked).toBe(false);
  });

  it("허용을 고르면 관할 입력이 열리고 확인 화면에 함께 보인다", async () => {
    render(
      <SiteRegistrationOnlyWizard mode="LEGACY_SITE_ID" accountFingerprint={FINGERPRINT} />,
    );
    fireEvent.click(
      await screen.findByRole("radio", { name: /외부\/벤더 클라우드 처리를 허용합니다/ }),
    );
    const jurisdiction = await screen.findByPlaceholderText("KR");
    fireEvent.change(jurisdiction, { target: { value: "KR" } });
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: /외부 AI의 현장 정보 접근을 허용/,
      }),
    );

    fireEvent.change(await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장"), {
      target: { value: "현장 A" },
    });
    fireEvent.change(screen.getByPlaceholderText("SITE-2026-001"), {
      target: { value: "site-A" },
    });
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "범위 채우기" }));
    fireEvent.change(screen.getByPlaceholderText("EPSG:5186"), {
      target: { value: "EPSG:5186" },
    });
    fireEvent.change(screen.getByPlaceholderText("KNGeoid2018"), {
      target: { value: "KNGeoid2018" },
    });
    fireEvent.click(screen.getByRole("button", { name: "다음" }));

    expect(await screen.findByText("등록 내용을 확인하세요")).toBeTruthy();
    expect(screen.getByText("허용")).toBeTruthy();
    expect(screen.getByText("KR")).toBeTruthy();
    expect(screen.getByText("허용 — 실제 접근에는 별도 설정과 권한이 필요")).toBeTruthy();
  });

  it.each([
    ["unset", "미정 — 벤더 클라우드 처리 작업 발급 불가, 등록 후 변경 불가"],
    ["deny", "허용하지 않음 — 벤더 클라우드 처리 작업 발급 불가"],
  ])("%s 선택의 확인 요약은 처리 작업에만 한정한다", async (choice, summary) => {
    render(<SiteRegistrationOnlyWizard mode="LEGACY_SITE_ID" accountFingerprint={FINGERPRINT} />);
    if (choice === "deny") {
      fireEvent.click(await screen.findByRole("radio", { name: /아니오 — 외부 클라우드 처리를 허용하지 않음/ }));
      fireEvent.change(screen.getByPlaceholderText("KR"), { target: { value: "KR" } });
    }
    fireEvent.change(await screen.findByPlaceholderText("예: OO산업단지 3공구 신축공사 현장"), { target: { value: "현장 A" } });
    fireEvent.change(screen.getByPlaceholderText("SITE-2026-001"), { target: { value: "site-A" } });
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    fireEvent.click(screen.getByRole("button", { name: "범위 채우기" }));
    fireEvent.change(screen.getByPlaceholderText("EPSG:5186"), { target: { value: "EPSG:5186" } });
    fireEvent.change(screen.getByPlaceholderText("KNGeoid2018"), { target: { value: "KNGeoid2018" } });
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    expect(await screen.findByText(summary)).toBeTruthy();
    expect(screen.getByText("허용하지 않음(기본값)")).toBeTruthy();
  });
});
