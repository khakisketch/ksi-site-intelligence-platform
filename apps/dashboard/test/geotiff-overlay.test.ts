import { describe, expect, it } from "vitest";

import {
  MAX_RASTER_RENDER_EDGE,
  MAX_RASTER_RENDER_PIXELS,
  rasterRenderDimensions,
  resolveGeoTiffCrs,
} from "@/lib/geo/geotiff-overlay";

describe("GeoTIFF browser overlay boundary", () => {
  it("uses the embedded projected CRS rather than a Site default", () => {
    expect(resolveGeoTiffCrs({ ProjectedCSTypeGeoKey: 5186 })).toBe("EPSG:5186");
    expect(resolveGeoTiffCrs({ GeographicTypeGeoKey: 4326 })).toBe("EPSG:4326");
  });

  it("fails closed when a GeoTIFF has no supported EPSG code", () => {
    expect(() => resolveGeoTiffCrs(null)).toThrow("좌표 기준");
    expect(() => resolveGeoTiffCrs({ ProjectedCSTypeGeoKey: 32652 })).toThrow(
      "지원하지 않는",
    );
  });

  it("caps only browser render resolution, not the source artifact", () => {
    const dimensions = rasterRenderDimensions(12_000, 8_000);
    expect(dimensions.width).toBeLessThanOrEqual(MAX_RASTER_RENDER_EDGE);
    expect(dimensions.height).toBeLessThanOrEqual(MAX_RASTER_RENDER_EDGE);
    expect(dimensions.width * dimensions.height).toBeLessThanOrEqual(MAX_RASTER_RENDER_PIXELS);
    expect(dimensions.width).toBeGreaterThan(0);
    expect(dimensions.height).toBeGreaterThan(0);
  });
});
