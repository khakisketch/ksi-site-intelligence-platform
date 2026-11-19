/** @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { UploadMap } from "@/app/sites/[siteId]/upload/UploadMap";

afterEach(cleanup);

describe("UploadMap", () => {
  it("discloses that area overlap cannot be shown when the area CRS is unsupported", () => {
    render(<UploadMap
      area={null}
      areaName="Bulgarian survey area"
      footprints={[{ key: "ortho", label: "정사영상", ring: [[23.533, 42.651], [23.537, 42.651], [23.537, 42.654], [23.533, 42.654]] }]}
      unmappedFiles={[]}
    />);

    expect(screen.getByRole("img").getAttribute("aria-label")).toBe("올릴 파일 정사영상의 범위");
    expect(screen.getByRole("status").textContent).toContain("파일 범위와 겹치는지 표시하지 않습니다");
    expect(document.querySelectorAll("svg polygon")).toHaveLength(1);
  });
});
