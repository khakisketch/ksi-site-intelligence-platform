import { describe, expect, it } from "vitest";

import { assignSlots, isTiffName } from "@/lib/external-file-routing";

const c = (name: string, hint: "dsm" | "ortho" | null, readable = true) => ({ name, hint, readable });

describe("assignSlots", () => {
  it("정사영상과 DSM 을 헤더 단서로 각 칸에 나눈다(입력 순서와 무관)", () => {
    expect(assignSlots([c("a_dsm.tif", "dsm"), c("b_ortho.tif", "ortho")])).toEqual({ assigned: { dsm: 0, ortho: 1 }, skipped: [] });
    expect(assignSlots([c("b_ortho.tif", "ortho"), c("a_dsm.tif", "dsm")]).assigned).toEqual({ ortho: 0, dsm: 1 });
  });

  it("파일 이름이 아니라 헤더로만 정한다", () => {
    // 이름은 dsm 이지만 헤더는 정사영상이다.
    expect(assignSlots([c("my_dsm.tif", "ortho")]).assigned).toEqual({ ortho: 0 });
  });

  it("칸을 알 수 없는 파일은 옮기지 않고 직접 고르라고 안내한다", () => {
    const result = assignSlots([c("mystery.tif", null)]);
    expect(result.assigned).toEqual({});
    expect(result.skipped).toHaveLength(1);
    expect(result.skipped[0].reason).toContain("직접 선택");
  });

  it("같은 칸으로 보이는 파일이 둘이면 먼저 고른 것만 넣고 나머지를 알린다", () => {
    const result = assignSlots([c("one.tif", "dsm"), c("two.tif", "dsm")]);
    expect(result.assigned).toEqual({ dsm: 0 });
    expect(result.skipped).toEqual([expect.objectContaining({ index: 1, name: "two.tif", reason: expect.stringContaining("DSM로 보이는 파일이 둘 이상") })]);
  });

  it("TIFF 가 아니거나 헤더를 읽지 못한 파일은 이유와 함께 건너뛴다", () => {
    const result = assignSlots([c("photo.jpg", null), c("broken.tif", null, false), c("ok.tif", "ortho")]);
    expect(result.assigned).toEqual({ ortho: 2 });
    expect(result.skipped.map((s) => s.name)).toEqual(["photo.jpg", "broken.tif"]);
    expect(result.skipped[0].reason).toContain("GeoTIFF");
    expect(result.skipped[1].reason).toContain("헤더를 읽지 못했습니다");
  });

  it("빈 입력은 아무것도 하지 않는다", () => {
    expect(assignSlots([])).toEqual({ assigned: {}, skipped: [] });
  });

  it("확장자는 대소문자를 가리지 않는다", () => {
    expect(isTiffName("A.TIF")).toBe(true);
    expect(isTiffName("a.tiff")).toBe(true);
    expect(isTiffName("a.tif.zip")).toBe(false);
    expect(isTiffName("tif")).toBe(false);
  });
});
