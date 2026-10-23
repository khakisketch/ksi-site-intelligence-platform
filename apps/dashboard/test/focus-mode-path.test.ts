import { describe, expect, it } from "vitest";

import { isFocusModePath } from "@/components/nav/focus-mode-path";

describe("집중 모드 경로", () => {
  it.each(["/design-preview/materials", "/design-preview/materials/"])(
    "%s 는 무대 집중 셸을 쓴다",
    (pathname) => {
      expect(isFocusModePath(pathname)).toBe(true);
    },
  );

  it("한 세그먼트 현장의 자료 경로만 집중 모드다", () => {
    expect(isFocusModePath("/sites/floreat-01/spatial-assets")).toBe(true);
    expect(isFocusModePath("/sites/floreat-01/spatial-assets/")).toBe(true);
  });

  it("정확한 현장 경로의 작업공간만 집중 모드다", () => {
    expect(isFocusModePath("/sites/floreat-01")).toBe(true);
    expect(isFocusModePath("/sites/floreat-01/")).toBe(true);
  });

  it("분석·로그인·중첩 하위 경로는 끌어들이지 않는다", () => {
    expect(isFocusModePath("/sites/new")).toBe(false);
    expect(isFocusModePath("/sites/new/")).toBe(false);
    expect(isFocusModePath("/sites/floreat-01/analysis")).toBe(false);
    expect(isFocusModePath("/sites/floreat-01/work-areas")).toBe(false);
    expect(isFocusModePath("/sites/floreat-01/observations")).toBe(false);
    expect(isFocusModePath("/sites/floreat-01/observations/new")).toBe(false);
    expect(isFocusModePath("/sites/floreat-01/spatial-data-requests")).toBe(false);
    expect(isFocusModePath("/sites/floreat-01/spatial-assets/extra")).toBe(false);
    expect(isFocusModePath("/sites/floreat-01/spatial-assets/extra/deep")).toBe(false);
    expect(isFocusModePath("/design-preview/materials/extra")).toBe(false);
    expect(isFocusModePath("/design-preview/other")).toBe(false);
    expect(isFocusModePath("/sites/floreat-01/spatial-data-requests")).toBe(false);
    expect(isFocusModePath("/login")).toBe(false);
    expect(isFocusModePath("/")).toBe(false);
    expect(isFocusModePath("/sites")).toBe(false);
    expect(isFocusModePath("/field")).toBe(false);
  });

  it("경로를 모르면 평소 화면을 쓴다", () => {
    expect(isFocusModePath(null)).toBe(false);
    expect(isFocusModePath(undefined)).toBe(false);
    expect(isFocusModePath("")).toBe(false);
  });
});
