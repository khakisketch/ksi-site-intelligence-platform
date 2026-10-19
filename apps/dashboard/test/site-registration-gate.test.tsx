/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({
  availability: vi.fn(),
  refresh: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: mocked.refresh }) }));
vi.mock("@/lib/core-api/permissions", () => ({
  getSiteRegistrationAvailability: mocked.availability,
}));
vi.mock("@/app/sites/new/SiteRegistrationOnlyWizard", () => ({
  SiteRegistrationOnlyWizard: ({ mode }: { mode: string }) => (
    <div data-testid="registration-wizard">{mode}</div>
  ),
}));

import NewSitePage from "@/app/sites/new/page";
import { RegisterSiteAction } from "@/app/sites/RegisterSiteAction";
import { SiteOnboarding } from "@/app/sites/SiteOnboarding";

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("RegisterSiteAction", () => {
  it("허용이면 등록 링크를 그대로 둔다", () => {
    render(<RegisterSiteAction availability={{ status: "allowed", mode: "MAPPED_BOOTSTRAP" }} />);
    const link = screen.getByRole("link", { name: "현장 등록" });
    expect(link.getAttribute("href")).toBe("/sites/new");
  });

  it("확정 거부면 클릭해야 사유가 열리고 링크는 없다", () => {
    render(<RegisterSiteAction availability={{ status: "denied" }} />);
    expect(screen.queryByRole("link", { name: "현장 등록" })).toBeNull();
    const trigger = screen.getByRole("button", { name: "현장 등록" });
    expect((trigger as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(trigger);
    expect(
      screen.getByText("현재 계정으로는 현장을 등록할 수 없습니다. 관리자에게 문의하세요."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "권한 다시 확인" })).toBeNull();
  });

  it("미확인이면 재시도 문구와 함께 권한 다시 확인을 둔다", () => {
    render(<RegisterSiteAction availability={{ status: "unavailable" }} />);
    fireEvent.click(screen.getByRole("button", { name: "현장 등록" }));
    expect(
      screen.getByText("등록 권한을 확인하지 못했습니다. 잠시 후 다시 확인하세요."),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "권한 다시 확인" }));
    expect(mocked.refresh).toHaveBeenCalledTimes(1);
  });
});

describe("NewSitePage", () => {
  it("허용이면 모드를 그대로 마법사에 넘긴다", async () => {
    mocked.availability.mockResolvedValue({ status: "allowed", mode: "MAPPED_BOOTSTRAP" });
    render(await NewSitePage());
    expect(screen.getByTestId("registration-wizard").textContent).toBe("MAPPED_BOOTSTRAP");
  });

  it("확정 거부면 기존 거부 화면을 보이고 마법사는 열지 않는다", async () => {
    mocked.availability.mockResolvedValue({ status: "denied" });
    render(await NewSitePage());
    expect(screen.getByText("현장 등록 권한이 없습니다")).toBeTruthy();
    expect(screen.queryByTestId("registration-wizard")).toBeNull();
  });

  it("미확인이면 거부로 속이지 않고 재시도 가능한 오류로 보인다", async () => {
    mocked.availability.mockResolvedValue({ status: "unavailable" });
    render(await NewSitePage());
    expect(
      screen.getByText("등록 권한을 확인하지 못했습니다. 잠시 후 다시 확인하세요."),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "다시 시도" })).toBeTruthy();
    expect(screen.queryByTestId("registration-wizard")).toBeNull();
    expect(screen.queryByText("현장 등록 권한이 없습니다")).toBeNull();
  });
});

describe("SiteOnboarding", () => {
  it("허용이면 첫 현장 등록 링크를 둔다", () => {
    render(<SiteOnboarding availability={{ status: "allowed", mode: "LEGACY_SITE_ID" }} />);
    const link = screen.getByRole("link", { name: "첫 현장 등록하기" });
    expect(link.getAttribute("href")).toBe("/sites/new");
  });

  it("확정 거부면 거부 사유를 클릭형으로 보이고 링크는 없다", () => {
    render(<SiteOnboarding availability={{ status: "denied" }} />);
    expect(screen.queryByRole("link", { name: "첫 현장 등록하기" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "첫 현장 등록하기" }));
    expect(
      screen.getByText("현재 계정으로는 현장을 등록할 수 없습니다. 관리자에게 문의하세요."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "권한 다시 확인" })).toBeNull();
  });

  it("미확인을 거부로 속이지 않고 재시도형으로 보인다", () => {
    render(<SiteOnboarding availability={{ status: "unavailable" }} />);
    fireEvent.click(screen.getByRole("button", { name: "첫 현장 등록하기" }));
    expect(
      screen.getByText("등록 권한을 확인하지 못했습니다. 잠시 후 다시 확인하세요."),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "권한 다시 확인" }));
    expect(mocked.refresh).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/권한이 있는 계정만|권한을 가진 계정만/)).toBeNull();
  });
});
