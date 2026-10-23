/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SiteWorkspaceWorkbench } from "@/app/sites/[siteId]/SiteWorkspaceWorkbench";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function frame(extra: Record<string, unknown> = {}) {
  const { ...rest } = extra;
  return render(
    <SiteWorkspaceWorkbench
      contextControls={<span>구역 · 검증 구역</span>}
      catalogLabel="작업공간 목록"
      catalog={<p>구역 선택</p>}
      stage={
        <div>
          <p>실제 화면</p>
          <div id="workspace-visual-a-layer-controls" />
          <div id="workspace-visual-b-layer-controls" />
        </div>
      }
      inspector={<p>선택 자료 정보</p>}
      inspectorId="workspace-inspector"
      inspectorLabel="작업공간 정보"
      {...rest}
    />,
  );
}

describe("workspace workbench overlay", () => {
  it("keeps the catalog closed until asked so the stage never resizes", () => {
    const { container } = frame();
    expect(container.querySelector("#workbench-catalog")).toBeNull();
    expect(screen.getByText("실제 화면")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "목록" }));
    expect(container.querySelector("#workbench-catalog")).toBeTruthy();
    expect(screen.getByText("실제 화면")).toBeTruthy();
  });

  it("opens info without touching the URL and closes with the close button", () => {
    const { container } = frame();
    const before = window.location.href;
    fireEvent.click(screen.getByRole("button", { name: "정보" }));
    expect(container.querySelector("#workspace-inspector")).toBeTruthy();
    expect(window.location.href).toBe(before);
    fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    expect(container.querySelector("#workspace-inspector")).toBeNull();
    // 포커스는 정보 트리거로 돌아간다.
    expect(document.activeElement?.getAttribute("data-workbench-info-trigger")).not.toBeNull();
  });

  it("closes with Escape", () => {
    const { container } = frame();
    fireEvent.click(screen.getByRole("button", { name: "정보" }));
    expect(container.querySelector("#workspace-inspector")).toBeTruthy();
    const panel = container.querySelector("#workspace-inspector")!;
    fireEvent.keyDown(panel, { key: "Escape" });
    expect(container.querySelector("#workspace-inspector")).toBeNull();
    expect(document.activeElement?.getAttribute("data-workbench-info-trigger")).not.toBeNull();
  });

  it("keeps portal targets mounted in the stage for pair layer controls", () => {
    frame();
    expect(document.getElementById("workspace-visual-a-layer-controls")).toBeTruthy();
    expect(document.getElementById("workspace-visual-b-layer-controls")).toBeTruthy();
  });

  it("never issues prepare requests from the frame itself", () => {
    const { container } = frame();
    expect(container.innerHTML).not.toMatch(/PREPARE|prepare/i);
    expect(container.querySelector("form[action*='spatial-data-requests']")).toBeNull();
  });
});
