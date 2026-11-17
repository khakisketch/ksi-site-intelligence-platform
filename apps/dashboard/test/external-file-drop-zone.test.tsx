/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExternalFileDropZone } from "@/app/field/ExternalFileDropZone";

afterEach(cleanup);

describe("ExternalFileDropZone", () => {
  it("끌어 놓은 파일들을 그대로 넘긴다", () => {
    const onFiles = vi.fn();
    render(<ExternalFileDropZone disabled={false} onFiles={onFiles} />);
    const files = [new File(["a"], "a.tif"), new File(["b"], "b.tif")];
    fireEvent.drop(screen.getByTestId("external-file-drop-zone"), { dataTransfer: { files } });
    expect(onFiles).toHaveBeenCalledWith(files);
  });

  it("여러 파일 선택 입력으로도 같은 동작을 한다(키보드·보조기기)", () => {
    const onFiles = vi.fn();
    render(<ExternalFileDropZone disabled={false} onFiles={onFiles} />);
    const input = screen.getByLabelText("정사영상·DSM 파일 한 번에 선택") as HTMLInputElement;
    expect(input.multiple).toBe(true);
    expect(input.accept).toBe(".tif,.tiff");
    const files = [new File(["a"], "a.tif")];
    fireEvent.change(input, { target: { files } });
    expect(onFiles).toHaveBeenCalledWith(files);
  });

  it("잠겨 있으면 끌어 놓아도 선택해도 아무것도 넘기지 않는다", () => {
    const onFiles = vi.fn();
    render(<ExternalFileDropZone disabled onFiles={onFiles} />);
    fireEvent.drop(screen.getByTestId("external-file-drop-zone"), { dataTransfer: { files: [new File(["a"], "a.tif")] } });
    expect(onFiles).not.toHaveBeenCalled();
    expect((screen.getByLabelText("정사영상·DSM 파일 한 번에 선택") as HTMLInputElement).disabled).toBe(true);
  });

  it("파일 없는 끌어 놓기는 무시하고, 끌어 올린 동안만 강조한다", () => {
    const onFiles = vi.fn();
    render(<ExternalFileDropZone disabled={false} onFiles={onFiles} />);
    const zone = screen.getByTestId("external-file-drop-zone");
    fireEvent.dragOver(zone, { dataTransfer: { files: [] } });
    expect(zone.className).toContain("border-accent");
    fireEvent.drop(zone, { dataTransfer: { files: [] } });
    expect(onFiles).not.toHaveBeenCalled();
    expect(zone.className).not.toContain("border-accent");
  });

  it("끌기가 브라우저 기본 동작(파일 열기)으로 새지 않는다", () => {
    render(<ExternalFileDropZone disabled={false} onFiles={() => undefined} />);
    const zone = screen.getByTestId("external-file-drop-zone");
    const event = new Event("drop", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "dataTransfer", { value: { files: [new File(["a"], "a.tif")] } });
    zone.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });
});
