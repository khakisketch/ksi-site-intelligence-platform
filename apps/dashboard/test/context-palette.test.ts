import { describe, expect, it } from "vitest";
import { contextPaletteItems } from "@/components/console/context-palette";
import { filterPaletteItems } from "@/components/console/palette-items";

const items = [{ key: "site:one", label: "남측 현장", group: "현장", href: "/sites/site-1", keywords: "opaque-source-1", hint: "현장 자료와 작업 보기" }];

describe("current Site task vocabulary", () => {
  it("offers human tasks only for a known authorized Site, not a pathname guess", () => {
    expect(contextPaletteItems(items, "/sites/site-1").map((i) => i.label)).toEqual(["분석·검토", "자료", "구역 자료 준비"]);
    expect(contextPaletteItems(items, "/sites/site-1/analysis")[0].href).toBe("/sites/site-1/analysis");
    expect(contextPaletteItems(items, "/sites/site-10")).toEqual([]);
    expect(contextPaletteItems([], "/sites/site-1")).toEqual([]);
    expect(contextPaletteItems(items, "/")).toEqual([]);
  });
  it("finds operator words and original identities without printing them as a hint", () => {
    expect(filterPaletteItems(contextPaletteItems(items, "/sites/site-1"), "사진")[0].label).toBe("자료");
    expect(filterPaletteItems(items, "opaque-source-1")).toEqual(items);
    expect(items[0].hint).not.toContain("opaque-source-1");
  });
});
