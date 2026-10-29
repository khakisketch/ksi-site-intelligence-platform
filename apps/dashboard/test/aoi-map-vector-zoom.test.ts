import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const source = readFileSync(join(process.cwd(), "src/components/map/AoiPolygonMapInner.tsx"), "utf8");

describe("small registered geometry display", () => {
  it("allows vector fitting beyond background resolution without requesting unsupported tiles", () => {
    // The F-03 20cm polygon became a 0px-wide line at zoom 18. The browser
    // evidence checks actual visible bounds; the read-only, initial, restore
    // and external-value fitting paths are exercised in aoi-draw-lifecycle.
    // Count-free assertions here cover the distinct map and tile zoom limits.
    expect(source).toContain("maxNativeZoom={19}");
    expect(source.match(/maxZoom=\{26\}/g)).toHaveLength(2);
  });
});
