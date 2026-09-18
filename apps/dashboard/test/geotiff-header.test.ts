import { describe, expect, it } from "vitest";

import { type GeoTiffRawHeader, recognizeGeoTiffHeader, slotMismatch } from "@/lib/geo/geotiff-header";

const base: GeoTiffRawHeader = {
  width: 100,
  height: 80,
  samplesPerPixel: 1,
  bitsPerSample: 32,
  sampleFormat: 3,
  geoKeys: { ProjectedCSTypeGeoKey: 5186 },
  software: null,
  dateTime: null,
  pixelSize: [0.05, 0.05],
};

describe("recognizeGeoTiffHeader", () => {
  it("declares the embedded EPSG code, projected before geographic", () => {
    expect(recognizeGeoTiffHeader(base).declaredCrs).toBe("EPSG:5186");
    expect(recognizeGeoTiffHeader({ ...base, geoKeys: { GeographicTypeGeoKey: 4326 } }).declaredCrs).toBe("EPSG:4326");
    // A declaration is not limited to the CRSs the browser overlay can render.
    expect(recognizeGeoTiffHeader({ ...base, geoKeys: { ProjectedCSTypeGeoKey: 32652 } }).declaredCrs).toBe("EPSG:32652");
  });

  it("declares no CRS when the header has none or a user-defined code", () => {
    expect(recognizeGeoTiffHeader({ ...base, geoKeys: null }).declaredCrs).toBeNull();
    expect(recognizeGeoTiffHeader({ ...base, geoKeys: { ProjectedCSTypeGeoKey: 32767 } }).declaredCrs).toBeNull();
    expect(recognizeGeoTiffHeader({ ...base, geoKeys: { ProjectedCSTypeGeoKey: 0 } }).declaredCrs).toBeNull();
  });

  it("hints DSM for one float band and ortho for 8-bit RGB(A)", () => {
    expect(recognizeGeoTiffHeader(base).kindHint).toBe("dsm");
    expect(recognizeGeoTiffHeader({ ...base, samplesPerPixel: 3, bitsPerSample: 8, sampleFormat: 1 }).kindHint).toBe("ortho");
    expect(recognizeGeoTiffHeader({ ...base, samplesPerPixel: 4, bitsPerSample: 8, sampleFormat: 1 }).kindHint).toBe("ortho");
    expect(recognizeGeoTiffHeader({ ...base, samplesPerPixel: 2, bitsPerSample: 16, sampleFormat: 1 }).kindHint).toBeNull();
  });

  it("splits the Software tag into producer name and version", () => {
    expect(recognizeGeoTiffHeader({ ...base, software: "Pix4Dmapper 4.8.4" }).producer).toEqual({ name: "Pix4Dmapper", version: "4.8.4" });
    expect(recognizeGeoTiffHeader({ ...base, software: "ODM v3.5.6" }).producer).toEqual({ name: "ODM", version: "3.5.6" });
    expect(recognizeGeoTiffHeader({ ...base, software: "GDAL/OGR" }).producer).toEqual({ name: "GDAL/OGR", version: null });
    expect(recognizeGeoTiffHeader({ ...base, software: "   " }).producer).toBeNull();
    expect(recognizeGeoTiffHeader({ ...base, software: "x".repeat(256) }).producer).toBeNull();
  });

  it("keeps the TIFF DateTime as a neutral reference, never as a capture interval", () => {
    // ODM 3.5.6 writes the photo date with an offset; other producers often write the file time.
    expect(recognizeGeoTiffHeader({ ...base, dateTime: "2018:01:24 16:17:21+00:00" }).headerDateTime).toBe("2018-01-24 16:17:21 UTC+00:00");
    expect(recognizeGeoTiffHeader({ ...base, dateTime: "2026:09:15 10:20:30" }).headerDateTime).toBe("2026-09-15 10:20:30");
    expect(recognizeGeoTiffHeader({ ...base, dateTime: "2026:09:15 10:20:30Z" }).headerDateTime).toBe("2026-09-15 10:20:30 UTC");
    const recognized = recognizeGeoTiffHeader({ ...base, dateTime: "2026:09:15 10:20:30" });
    expect(recognized).not.toHaveProperty("captureStartedAt");
    expect(recognizeGeoTiffHeader({ ...base, dateTime: "yesterday" }).headerDateTime).toBeNull();
  });
});

describe("slotMismatch", () => {
  it("warns only when the header clearly suggests the other slot", () => {
    expect(slotMismatch("ortho", "dsm")).toBe(true);
    expect(slotMismatch("dsm", "ortho")).toBe(true);
    expect(slotMismatch("ortho", "ortho")).toBe(false);
    expect(slotMismatch("dsm", null)).toBe(false);
  });
});
