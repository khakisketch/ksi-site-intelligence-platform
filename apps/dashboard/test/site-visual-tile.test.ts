/** @vitest-environment jsdom */
import { createElement } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  buildSiteVisualTileDescriptor,
  extractVisualRing,
  pickVisualTileArea,
  planeUnitForVisualCrs,
  sanitizeSiteVisualTileDescriptor,
  SITE_VISUAL_TILE_ITEMS_PER_AREA,
  SITE_VISUAL_TILE_MAX_AREAS,
  SITE_VISUAL_TILE_MAX_FACTS,
  SITE_VISUAL_TILE_MAX_VERTICES,
  toVisualTileFacts,
  visualTileAccessibleName,
  visualTileCountLine,
  visualTileFactLine,
  type SiteVisualTileAssetFact,
  type SiteVisualTileDescriptor,
} from "@/lib/site-visual-tile";
import { SiteVisualTile } from "@/components/site/SiteVisualTile";

afterEach(() => {
  cleanup();
});

function ring4(): Array<[number, number]> {
  return [
    [0, 0],
    [4, 0],
    [4, 3],
    [0, 3],
  ];
}

function fact(overrides: Partial<SiteVisualTileAssetFact> = {}): SiteVisualTileAssetFact {
  return {
    kind: "ortho",
    captureStartedAt: "2021-08-17T00:00:00Z",
    captureEndedAt: "2021-08-17T00:10:00Z",
    captureDate: null,
    lifecycleState: "SEALED",
    ...overrides,
  };
}

function catalogItem(overrides: Record<string, unknown> = {}) {
  return {
    siteId: "site-1",
    workAreaId: "area-1",
    kind: "ortho",
    lifecycleState: "SEALED",
    declared: {
      captureStartedAt: "2021-08-17T00:00:00Z",
      captureEndedAt: "2021-08-17T00:10:00Z",
      captureDate: null,
    },
    ...overrides,
  };
}

function validTile(overrides: Partial<SiteVisualTileDescriptor> = {}): SiteVisualTileDescriptor {
  const base = buildSiteVisualTileDescriptor({
    siteId: "site-1",
    area: {
      workAreaId: "area-1",
      workAreaName: "Floreat common-extent",
      crs: "EPSG:7850",
      ring: ring4(),
    },
    facts: [
      fact({ kind: "ortho" }),
      fact({ kind: "dsm", captureStartedAt: "2022-08-24T00:00:00Z", captureEndedAt: "2022-08-24T00:10:00Z" }),
    ],
    scannedAssetCount: 2,
    hasMoreAssets: false,
  });
  return { ...base, ...overrides };
}

describe("visual tile bounds", () => {
  it("stays within the preview path fan-out", () => {
    expect(SITE_VISUAL_TILE_MAX_AREAS).toBeLessThanOrEqual(6);
    expect(SITE_VISUAL_TILE_ITEMS_PER_AREA).toBeLessThanOrEqual(50);
    expect(SITE_VISUAL_TILE_MAX_FACTS).toBeLessThanOrEqual(8);
  });
});

describe("extractVisualRing", () => {
  it("accepts a closed 4-vertex ring and keeps the exact registered numbers", () => {
    const polygon = {
      type: "Polygon",
      coordinates: [[[0, 0], [4, 0], [4, 3], [0, 3], [0, 0]]],
    };
    expect(extractVisualRing(polygon)).toEqual(ring4());
  });

  it("rejects invented or unusable shapes instead of drawing them", () => {
    // MultiPolygon — never approximate.
    expect(extractVisualRing({ type: "MultiPolygon", coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 0]]]] })).toBeNull();
    // Holes — the outer boundary alone is a different claim.
    expect(
      extractVisualRing({
        type: "Polygon",
        coordinates: [
          [[0, 0], [4, 0], [4, 3], [0, 0]],
          [[1, 1], [2, 1], [2, 2], [1, 1]],
        ],
      }),
    ).toBeNull();
    // Too few distinct vertices, non-finite, non-polygon, collapsed to a point.
    expect(extractVisualRing({ type: "Polygon", coordinates: [[[0, 0], [1, 1], [0, 0]]] })).toBeNull();
    expect(
      extractVisualRing({ type: "Polygon", coordinates: [[[0, NaN], [1, 0], [1, 1], [0, NaN]]] }),
    ).toBeNull();
    expect(extractVisualRing({ type: "Point", coordinates: [0, 0] })).toBeNull();
    expect(extractVisualRing({ type: "Polygon", coordinates: [[[2, 2], [2, 2], [2, 2], [2, 2]]] })).toBeNull();
    expect(extractVisualRing(null)).toBeNull();
  });

  it("rejects oversized rings instead of truncating them silently", () => {
    const long = Array.from({ length: SITE_VISUAL_TILE_MAX_VERTICES + 2 }, (_, index) => [index, index % 2]);
    expect(extractVisualRing({ type: "Polygon", coordinates: [long] })).toBeNull();
  });
});

describe("pickVisualTileArea", () => {
  function area(overrides: Record<string, unknown> = {}) {
    return {
      workAreaId: "area-1",
      name: "Floreat common-extent",
      polygon: { type: "Polygon", coordinates: [[[0, 0], [4, 0], [4, 3], [0, 0]]] },
      crs: "EPSG:7850",
      status: "ACTIVE",
      ...overrides,
    };
  }

  it("picks the first ACTIVE drawable area in Core order", () => {
    const picked = pickVisualTileArea([
      area({ workAreaId: "archived", status: "ARCHIVED" }),
      area({ workAreaId: "undrawable", polygon: { type: "Point", coordinates: [0, 0] } }),
      area({ workAreaId: "area-2", name: "두 번째 구역" }),
      area({ workAreaId: "area-3" }),
    ]);
    expect(picked?.workAreaId).toBe("area-2");
    expect(picked?.workAreaName).toBe("두 번째 구역");
    expect(picked?.ring).toEqual([
      [0, 0],
      [4, 0],
      [4, 3],
    ]);
  });

  it("returns null when there is no drawable ACTIVE geometry — never an invented shape", () => {
    expect(pickVisualTileArea([])).toBeNull();
    expect(pickVisualTileArea([area({ status: "ARCHIVED" })])).toBeNull();
    expect(pickVisualTileArea([area({ polygon: { type: "Point", coordinates: [0, 0] } })])).toBeNull();
    expect(pickVisualTileArea([area({ workAreaId: "area/evil" })])).toBeNull();
    expect(pickVisualTileArea([area({ crs: "  " })])).toBeNull();
  });
});

describe("visual CRS honesty", () => {
  it("asserts a unit only for known coordinate systems", () => {
    expect(planeUnitForVisualCrs("EPSG:5186")).toBe("meters");
    expect(planeUnitForVisualCrs("EPSG:4326")).toBe("degrees");
    // Floreat sample CRS and anything unknown assert no unit.
    expect(planeUnitForVisualCrs("EPSG:7850")).toBe("unknown");
    expect(planeUnitForVisualCrs("EPSG:9999")).toBe("unknown");
  });
});

describe("toVisualTileFacts", () => {
  it("keeps Core order and surfaces at most 8 facts", () => {
    const assets = Array.from({ length: 20 }, (_, index) =>
      catalogItem({ kind: index % 2 === 0 ? "ortho" : "dsm" }),
    );
    const result = toVisualTileFacts("site-1", "area-1", assets);
    expect(result?.surfaced).toHaveLength(8);
    expect(result?.scanned).toBe(20);
    expect(result?.surfaced[0]?.kind).toBe("ortho");
    expect(result?.surfaced[1]?.kind).toBe("dsm");
  });

  it("returns null when there are no records — a tile without facts is not composed", () => {
    expect(toVisualTileFacts("site-1", "area-1", [])).toBeNull();
    expect(
      toVisualTileFacts("site-1", "area-1", [catalogItem({ siteId: "site-9" })]),
    ).toBeNull();
  });

  it("skips foreign-scope items instead of counting them", () => {
    const result = toVisualTileFacts("site-1", "area-1", [
      catalogItem(),
      catalogItem({ siteId: "site-9" }),
      catalogItem({ workAreaId: "area-9" }),
    ]);
    expect(result?.scanned).toBe(1);
  });
});

describe("visual tile fact wording", () => {
  it("names the over-limit remainder honestly instead of truncating silently", () => {
    const tile = validTile({ scannedAssetCount: 20 });
    expect(visualTileFactLine(tile)).toContain("외 19건");
    expect(visualTileCountLine(tile)).toContain("등록 자료 20건");
    expect(visualTileCountLine(tile)).toContain("Floreat common-extent");
  });

  it("never claims an exact total when the catalog is truncated", () => {
    const tile = validTile({ scannedAssetCount: 50, hasMoreAssets: true });
    expect(visualTileFactLine(tile)).toContain("외 더 있음");
    expect(visualTileCountLine(tile)).toContain("50건 이상");
  });

  it("uses operator language without technical dumps", () => {
    const tile = validTile();
    expect(visualTileFactLine(tile)).toContain("정사영상");
    expect(visualTileFactLine(tile)).toContain("2021");
    const serialized = JSON.stringify(tile);
    expect(serialized).not.toMatch(/\.tif|\.laz|\.las/i);
  });

  it("carries honesty in the accessible name and names the real records", () => {
    const name = visualTileAccessibleName(validTile());
    expect(name).toContain("사진 아님");
    expect(name).toContain("Floreat common-extent");
    expect(name).toContain("정사영상");
    expect(name).not.toMatch(/미리보기|전체 현장|최신/);
  });
});

describe("visual tile descriptor binding validation", () => {
  function validRaw(): Record<string, unknown> {
    return JSON.parse(JSON.stringify(validTile()));
  }

  it("accepts the locally built shape", () => {
    const checked = sanitizeSiteVisualTileDescriptor(validRaw(), "site-1");
    expect(checked?.workAreaId).toBe("area-1");
    expect(checked?.vertexCount).toBe(4);
    expect(checked?.siteHref).toBe("/sites/site-1?workAreaId=area-1");
  });

  it("rejects foreign site, area, and shape", () => {
    const base = validRaw();
    expect(sanitizeSiteVisualTileDescriptor({ ...base, siteId: "site-9" }, "site-1")).toBeNull();
    expect(sanitizeSiteVisualTileDescriptor({ ...base, workAreaId: "area-9" }, "site-1")).toBeNull();
    expect(sanitizeSiteVisualTileDescriptor({ ...base, ring: [[0, 0], [1, 1]] }, "site-1")).toBeNull();
    expect(
      sanitizeSiteVisualTileDescriptor({ ...base, ring: [[[0, 0], [1, 0], [1, 1]]] }, "site-1"),
    ).toBeNull();
    expect(sanitizeSiteVisualTileDescriptor({ ...base, vertexCount: 99 }, "site-1")).toBeNull();
    expect(sanitizeSiteVisualTileDescriptor({ ...base, facts: [] }, "site-1")).toBeNull();
    expect(sanitizeSiteVisualTileDescriptor({ ...base, facts: Array.from({ length: 9 }, () => fact()) }, "site-1")).toBeNull();
    expect(sanitizeSiteVisualTileDescriptor({ ...base, hasMoreAssets: "yes" }, "site-1")).toBeNull();
    expect(sanitizeSiteVisualTileDescriptor(null, "site-1")).toBeNull();
    expect(sanitizeSiteVisualTileDescriptor([], "site-1")).toBeNull();
  });

  it("rejects swapped URLs instead of trusting provided strings", () => {
    const base = validRaw();
    expect(
      sanitizeSiteVisualTileDescriptor({ ...base, siteHref: "/sites/site-9?workAreaId=area-9" }, "site-1"),
    ).toBeNull();
    expect(
      sanitizeSiteVisualTileDescriptor({ ...base, siteHref: "https://evil.invalid/x" }, "site-1"),
    ).toBeNull();
  });

  it("rebuilds the site href from validated ids", () => {
    const checked = sanitizeSiteVisualTileDescriptor(validRaw(), "site-1")!;
    expect(checked.siteHref).toBe("/sites/site-1?workAreaId=area-1");
  });

  it("exposes no byte paths, hashes, keys, or revision/technical facts", () => {
    const tile = validTile();
    expect(Object.keys(tile).sort()).toEqual(
      ["available", "crs", "facts", "hasMoreAssets", "ring", "scannedAssetCount", "siteHref", "siteId", "vertexCount", "workAreaId", "workAreaName"],
    );
    const serialized = JSON.stringify(tile);
    expect(serialized).not.toMatch(/signed|presigned|objectKey|sha256|digest|token|secret|fileHref|dataAccess|revision|gsd/i);
    expect(serialized).not.toMatch(/^https?:\/\//);
  });
});

describe("SiteVisualTile rendering", () => {
  it("card reads as a deliberate diagram tile, never a photo", () => {
    render(createElement(SiteVisualTile, { tile: validTile(), size: "card" }));

    const link = screen.getByRole("link", { name: /사진 아님/ });
    expect(link.getAttribute("href")).toBe("/sites/site-1?workAreaId=area-1");
    // Visible honesty copy plus the real records shown.
    expect(screen.getByText("범위 도식 · 사진 아님")).toBeTruthy();
    expect(link.textContent).toContain("Floreat common-extent");
    expect(link.textContent).toContain("정사영상");
    // No version/GSD/hash/file-name technical dumps on the tile.
    expect(link.textContent).not.toMatch(/버전|GSD|sha256|ks[ao]-v1|\.tif/i);
    // Flat vector only — no photo-like imagery or gradients.
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("svg polygon")).toBeTruthy();
    expect(link.innerHTML).not.toMatch(/gradient|linear-to|hillshade/i);
    expect(link.querySelector("input,button,select,textarea,details")).toBeNull();
  });

  it("row carries the same honesty in a compact cue", () => {
    render(createElement(SiteVisualTile, { tile: validTile(), size: "row" }));

    const link = screen.getByRole("link", { name: /사진 아님/ });
    expect(link.getAttribute("href")).toBe("/sites/site-1?workAreaId=area-1");
    expect(link.getAttribute("aria-label")).toContain("Floreat common-extent");
    expect(screen.getByText("도식")).toBeTruthy();
    expect(document.querySelector("img")).toBeNull();
  });

  it("announces truncated holdings honestly on the tile", () => {
    render(
      createElement(SiteVisualTile, {
        tile: validTile({ scannedAssetCount: 50, hasMoreAssets: true }),
        size: "card",
      }),
    );
    expect(screen.getByText(/외 더 있음/)).toBeTruthy();
    expect(screen.getByText(/50건 이상/)).toBeTruthy();
  });

  it("keeps the caption inside the tile so identity and action stay on screen", () => {
    // 회귀: 캡션이 절대 위치로 카드 밖에 새면, 모바일에서 현장 이름·상태·
    // 다음 행동이 화면 아래로 밀려난다. 캡션은 흐름 안에 있어야 한다.
    render(createElement(SiteVisualTile, { tile: validTile(), size: "card" }));

    const figure = document.querySelector("figure")!;
    const caption = document.querySelector("figcaption")!;
    // 절대 위치가 아니라 흐름(flex) 안의 마지막 항목이다.
    expect(caption.className).not.toMatch(/absolute/);
    expect(caption.className).toMatch(/shrink-0/);
    expect(figure.className).toMatch(/flex/);
    expect(figure.className).toMatch(/flex-col/);
    // 도식 영역은 남은 자리를 받고, 캡션이 두꺼워지면 도식이 줄어든다.
    const diagram = figure.firstElementChild as HTMLElement;
    expect(diagram.className).toMatch(/flex-1/);
    expect(diagram.className).toMatch(/min-h-0/);
  });
});
