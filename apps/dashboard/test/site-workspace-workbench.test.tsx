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
    fireEvent.click(screen.getByRole("button", { name: "작업공간 목록 열기" }));
    expect(container.querySelector("#workbench-catalog")).toBeTruthy();
    expect(screen.getByText("실제 화면")).toBeTruthy();
  });

  it("opens info without touching the URL and closes with the close button", () => {
    const { container } = frame();
    const before = window.location.href;
    const panel = container.querySelector("#workspace-inspector")!;
    // 닫힘 상태에서는 틀만 마운트되고 본문은 두지 않는다.
    expect(panel.getAttribute("style")).toMatch(/display:\s*none/);
    expect(screen.queryByText("선택 자료 정보")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "정보" }));
    expect(panel.getAttribute("style")).not.toMatch(/display:\s*none/);
    expect(screen.getByText("선택 자료 정보")).toBeTruthy();
    expect(window.location.href).toBe(before);
    fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    expect(panel.getAttribute("style")).toMatch(/display:\s*none/);
    expect(screen.queryByText("선택 자료 정보")).toBeNull();
    // 포커스는 정보 트리거로 돌아간다.
    expect(document.activeElement?.getAttribute("data-workbench-info-trigger")).not.toBeNull();
  });

  it("closes with Escape", () => {
    const { container } = frame();
    fireEvent.click(screen.getByRole("button", { name: "정보" }));
    const panel = container.querySelector("#workspace-inspector")!;
    expect(screen.getByText("선택 자료 정보")).toBeTruthy();
    fireEvent.keyDown(panel, { key: "Escape" });
    expect(panel.getAttribute("style")).toMatch(/display:\s*none/);
    expect(screen.queryByText("선택 자료 정보")).toBeNull();
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

  it("adds an 영역 toggle beside 자료 and 등록 진행, and the area list opens only when chosen", () => {
    frame({
      intake: <p>등록 진행 내용</p>,
      areas: <p>영역 목록 내용</p>,
      areasLabel: "영역 3",
      initialPanel: "materials",
    });
    const group = screen.getByRole("group", { name: "자료 패널 보기" });
    expect(Array.from(group.querySelectorAll("button")).map((button) => button.textContent)).toEqual(["자료", "등록 진행", "영역 3"]);
    expect(screen.getByText("구역 선택")).toBeTruthy();
    expect(screen.queryByText("영역 목록 내용")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "영역 3" }));
    expect(screen.getByText("영역 목록 내용")).toBeTruthy();
    expect(screen.queryByText("구역 선택")).toBeNull();
    expect(screen.getByRole("button", { name: "영역 3" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "자료" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("starts with the area tab open when initialPanel is areas", () => {
    frame({ intake: <p>등록 진행 내용</p>, areas: <p>영역 목록 내용</p>, initialPanel: "areas" });
    expect(screen.getByText("영역 목록 내용")).toBeTruthy();
    expect(screen.getByRole("button", { name: "영역" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("swaps the stage for the area map on wide screens only while the tab is open, without unmounting the stage", () => {
    frame({
      intake: <p>등록 진행 내용</p>,
      areas: <p>영역 목록 내용</p>,
      areasStage: <p>영역 지도 자리</p>,
      initialPanel: "materials",
    });
    const stageWrapper = () => screen.getByText("실제 화면").parentElement!.parentElement!;
    expect(screen.queryByText("영역 지도 자리")).toBeNull();
    expect(stageWrapper().className).toContain("contents");
    fireEvent.click(screen.getByRole("button", { name: "영역" }));
    expect(screen.getByText("영역 지도 자리").parentElement!.className).toContain("lg:block");
    expect(screen.getByText("실제 화면")).toBeTruthy();
    expect(stageWrapper().className).toContain("lg:hidden");
    expect(document.getElementById("workspace-visual-a-layer-controls")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "자료" }));
    expect(screen.queryByText("영역 지도 자리")).toBeNull();
    expect(stageWrapper().className).toContain("contents");
  });

  it("keeps the old toggle (자료 / 등록 진행) when no area tab is given", () => {
    frame({ intake: <p>등록 진행 내용</p>, initialPanel: "materials" });
    const group = screen.getByRole("group", { name: "자료 패널 보기" });
    expect(Array.from(group.querySelectorAll("button")).map((button) => button.textContent)).toEqual(["자료", "등록 진행"]);
  });
});
