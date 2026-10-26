/** @vitest-environment jsdom */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";

import { AssetRequestDialog } from "@/app/sites/[siteId]/spatial-assets/AssetRequestDialog";

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

afterEach(() => cleanup());

describe("asset request dialog", () => {
  it("keeps the request form out of the panel until the user asks for it", () => {
    render(<AssetRequestDialog><p>픽셀 창 폼</p></AssetRequestDialog>);
    expect(screen.queryByText("픽셀 창 폼")).toBeNull();
  });

  it("opens the form in a native dialog, focuses the close action, and restores focus", () => {
    render(<AssetRequestDialog><p>픽셀 창 폼</p></AssetRequestDialog>);
    const trigger = screen.getByRole("button", { name: "이 자료 새로 준비 요청" });
    fireEvent.click(trigger);
    expect(screen.getByText("픽셀 창 폼")).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "닫기" }));
    fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    expect(screen.queryByText("픽셀 창 폼")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("treats a canceled native dialog as a close without submitting", () => {
    render(<AssetRequestDialog><p>픽셀 창 폼</p></AssetRequestDialog>);
    fireEvent.click(screen.getByRole("button", { name: "이 자료 새로 준비 요청" }));
    const dialog = screen.getByRole("dialog");
    act(() => {
      dialog.dispatchEvent(new Event("cancel", { cancelable: true }));
    });
    expect(screen.queryByText("픽셀 창 폼")).toBeNull();
  });
});
