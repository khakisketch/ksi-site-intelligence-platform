/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FilePickerField } from "@/components/ui/FilePickerField";

afterEach(cleanup);

describe("FilePickerField", () => {
  it("선택 전에는 안내 문구, 선택 후에는 파일명을 보여준다", () => {
    const { rerender } = render(
      <FilePickerField label="정사영상 (필수)" ariaLabel="정사영상 GeoTIFF" onSelect={() => {}} />,
    );
    expect(screen.getByText("선택된 파일 없음")).toBeTruthy();
    rerender(
      <FilePickerField
        label="정사영상 (필수)"
        ariaLabel="정사영상 GeoTIFF"
        onSelect={() => {}}
        selectedFileName="ortho.tif"
      />,
    );
    expect(screen.getByText("ortho.tif")).toBeTruthy();
    expect(screen.queryByText("선택된 파일 없음")).toBeNull();
  });

  it("파일을 고르면 File 을 콜백으로 전달하고, 취소(null)도 그대로 전한다", () => {
    const onSelect = vi.fn();
    render(<FilePickerField label="정사영상 (필수)" ariaLabel="정사영상 GeoTIFF" onSelect={onSelect} />);
    const input = screen.getByLabelText("정사영상 GeoTIFF") as HTMLInputElement;
    const file = new File(["tif"], "ortho.tif", { type: "image/tiff" });
    fireEvent.change(input, { target: { files: [file] } });
    expect(onSelect).toHaveBeenCalledWith(file);
    fireEvent.change(input, { target: { files: null } });
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it("disabled 는 입력을 막는다", () => {
    render(
      <FilePickerField
        label="DSM (선택)"
        ariaLabel="DSM GeoTIFF"
        disabled
        onSelect={() => {}}
      />,
    );
    const input = screen.getByLabelText("DSM GeoTIFF") as HTMLInputElement;
    expect(input.disabled).toBe(true);
  });

  it("입력은 sr-only 로 남는다 — 브라우저 로케일 chrome 을 화면에 내보내지 않는다", () => {
    render(<FilePickerField label="독립 검사점 CSV" ariaLabel="독립 검사점 CSV" onSelect={() => {}} />);
    const input = screen.getByLabelText("독립 검사점 CSV");
    expect(input.className).toContain("sr-only");
    expect(screen.getByText("파일 선택")).toBeTruthy();
  });
});
