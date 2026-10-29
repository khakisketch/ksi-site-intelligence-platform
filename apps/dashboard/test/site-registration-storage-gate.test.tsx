/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SiteRegistrationStorageGate } from "@/app/sites/new/SiteRegistrationStorageGate";

afterEach(() => cleanup());

describe("현장 초안 저장소 안내", () => {
  it("확인 중에는 기존 입력이나 등록 행동을 보여주지 않는다", () => {
    render(<SiteRegistrationStorageGate status="loading" />);
    expect(screen.getByRole("status").textContent).toMatch(/확인하고 있습니다/);
    expect(screen.queryByRole("button", { name: /등록|다음/ })).toBeNull();
  });

  it("원문을 덮지 않고 이전 요청 확인을 안내한다", () => {
    render(<SiteRegistrationStorageGate status="unreadable" />);
    expect(screen.getByRole("heading", { name: "저장된 현장 초안을 읽을 수 없습니다" })).toBeTruthy();
    expect(screen.getByText(/원본을 덮어쓰지 않았으며/)).toBeTruthy();
    const link = screen.getByRole("link", { name: "별도 탭에서 현장 목록 확인하기" });
    expect(link.getAttribute("href")).toBe("/sites");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("저장소를 읽지 못하면 기록의 유무를 추측하지 않는다", () => {
    render(<SiteRegistrationStorageGate status="unavailable" />);
    expect(screen.getByText(/이전 초안이 있는지 확인할 수 없습니다/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /등록|다음/ })).toBeNull();
  });
});
