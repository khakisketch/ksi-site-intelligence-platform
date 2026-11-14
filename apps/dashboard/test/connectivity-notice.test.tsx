/** @vitest-environment jsdom */
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConnectivityNotice } from "@/components/nav/ConnectivityNotice";

function setOnline(value: boolean) {
  Object.defineProperty(window.navigator, "onLine", { value, configurable: true });
  act(() => {
    window.dispatchEvent(new Event(value ? "online" : "offline"));
  });
}

describe("ConnectivityNotice", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    setOnline(true);
  });

  it("온라인일 때는 아무것도 그리지 않는다", () => {
    setOnline(true);
    const { container } = render(<ConnectivityNotice />);
    expect(container.firstChild).toBeNull();
  });

  it("오프라인이면 이유와 다음 행동을 함께 알린다", () => {
    setOnline(true);
    render(<ConnectivityNotice />);
    expect(screen.queryByRole("alert")).toBeNull();
    setOnline(false);
    const notice = screen.getByRole("alert");
    expect(notice.textContent).toContain("연결이 끊겼습니다");
    expect(notice.textContent).toContain("이 탭에 그대로 있습니다");
  });

  it("연결이 돌아오면 자동으로 사라진다", () => {
    setOnline(false);
    render(<ConnectivityNotice />);
    expect(screen.getByRole("alert")).toBeTruthy();
    setOnline(true);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
