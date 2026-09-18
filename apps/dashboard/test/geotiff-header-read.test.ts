/** @vitest-environment jsdom */
// geotiff.js 의 fromBlob 은 브라우저 FileReader 로 범위를 읽는다. node 환경에는
// FileReader 가 없으므로 실제 Blob 읽기 경로는 jsdom 에서 확인한다.
import { writeArrayBuffer } from "geotiff";
import { describe, expect, it } from "vitest";

import { NotGeoTiffError, readGeoTiffHeader, recognizeGeoTiffHeader } from "@/lib/geo/geotiff-header";

describe("readGeoTiffHeader", () => {
  it("reads bands, sample format and geokeys from a real GeoTIFF blob", async () => {
    const bytes = writeArrayBuffer(new Float32Array(4 * 3).fill(12.5), {
      width: 4,
      height: 3,
      ModelPixelScale: [0.05, 0.05, 0],
      ModelTiepoint: [0, 0, 0, 200000, 550000, 0],
      GeographicTypeGeoKey: 4326,
      ProjectedCSTypeGeoKey: 5186,
      GTModelTypeGeoKey: 1,
    });
    const header = await readGeoTiffHeader(new Blob([bytes]));
    expect(header).toMatchObject({ width: 4, height: 3, samplesPerPixel: 1, bitsPerSample: 32, sampleFormat: 3 });
    expect(recognizeGeoTiffHeader(header)).toMatchObject({ declaredCrs: "EPSG:5186", kindHint: "dsm" });
    expect(header.pixelSize?.[0]).toBeCloseTo(0.05);
  });

  it("rejects bytes that are not a TIFF", async () => {
    await expect(readGeoTiffHeader(new Blob([new TextEncoder().encode("not a tiff at all")]))).rejects.toBeInstanceOf(NotGeoTiffError);
  });
});
