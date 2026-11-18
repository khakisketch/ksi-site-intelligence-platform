/** @vitest-environment jsdom */
// geotiff.js 의 fromBlob 은 브라우저 FileReader 로 범위를 읽는다. node 환경에는
// FileReader 가 없으므로 실제 Blob 읽기 경로는 jsdom 에서 확인한다.
import { writeArrayBuffer } from "geotiff";
import { describe, expect, it } from "vitest";

import { NotGeoTiffError, readGeoTiffHeader, recognizeGeoTiffHeader } from "@/lib/geo/geotiff-header";
import { preflightGeoTiff } from "@/lib/geo/geotiff-preflight";

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
    expect(header.boundingBox?.[0]).toBeCloseTo(200000);
    expect(header.boundingBox?.[2]).toBeCloseTo(200000.2);
    expect(header.boundingBox?.[1]).toBeCloseTo(549999.85);
    expect(header.boundingBox?.[3]).toBeCloseTo(550000);
  });

  it("rejects bytes that are not a TIFF", async () => {
    await expect(readGeoTiffHeader(new Blob([new TextEncoder().encode("not a tiff at all")]))).rejects.toBeInstanceOf(NotGeoTiffError);
  });
});

// 압축·색 방식·NoData 태그처럼 writeArrayBuffer 가 쓰지 못하는 태그를 직접 가진 최소 TIFF(1×1, 리틀엔디언)를 만든다.
// 이 시험은 화소를 디코드하지 않는다. 점검이 읽는 것은 첫 IFD 뿐이다.
type TagValue = { tag: number; type: 2 | 3 | 4 | 12; values: number[] | string };
const TYPE_SIZE = { 2: 1, 3: 2, 4: 4, 12: 8 } as const;

function buildTiff(tags: TagValue[]): Blob {
  const sorted = [...tags].sort((a, b) => a.tag - b.tag);
  const encode = (entry: TagValue): Uint8Array => {
    if (entry.type === 2) return new TextEncoder().encode(`${entry.values as string}\0`);
    const values = entry.values as number[];
    const bytes = new Uint8Array(values.length * TYPE_SIZE[entry.type]);
    const view = new DataView(bytes.buffer);
    values.forEach((value, index) => {
      if (entry.type === 3) view.setUint16(index * 2, value, true);
      else if (entry.type === 4) view.setUint32(index * 4, value, true);
      else view.setFloat64(index * 8, value, true);
    });
    return bytes;
  };
  const encoded = sorted.map(encode);
  const ifdSize = 2 + sorted.length * 12 + 4;
  let extra = 8 + ifdSize;
  const out = new Uint8Array(extra + encoded.reduce((sum, bytes) => sum + (bytes.length > 4 ? bytes.length + (bytes.length % 2) : 0), 0) + 16);
  const view = new DataView(out.buffer);
  out.set([0x49, 0x49], 0);
  view.setUint16(2, 42, true);
  view.setUint32(4, 8, true);
  view.setUint16(8, sorted.length, true);
  sorted.forEach((entry, index) => {
    const at = 10 + index * 12;
    const bytes = encoded[index];
    const count = entry.type === 2 ? bytes.length : (entry.values as number[]).length;
    view.setUint16(at, entry.tag, true);
    view.setUint16(at + 2, entry.type, true);
    view.setUint32(at + 4, count, true);
    if (bytes.length <= 4) out.set(bytes, at + 8);
    else {
      view.setUint32(at + 8, extra, true);
      out.set(bytes, extra);
      extra += bytes.length + (bytes.length % 2);
    }
  });
  return new Blob([out]);
}

function geoKeyDirectory(keys: Array<[number, number]>): number[] {
  return [1, 1, 0, keys.length, ...keys.flatMap(([key, value]) => [key, 0, 1, value])];
}

const BASE_TAGS: TagValue[] = [
  { tag: 256, type: 4, values: [1] }, { tag: 257, type: 4, values: [1] },
  { tag: 258, type: 3, values: [8, 8, 8] }, { tag: 259, type: 3, values: [7] }, { tag: 262, type: 3, values: [6] },
  { tag: 273, type: 4, values: [200] }, { tag: 277, type: 3, values: [3] }, { tag: 278, type: 4, values: [1] },
  { tag: 279, type: 4, values: [3] }, { tag: 284, type: 3, values: [1] },
  { tag: 33550, type: 12, values: [0.03, 0.03, 0] }, { tag: 33922, type: 12, values: [0, 0, 0, 500000, 4000000, 0] },
  { tag: 34735, type: 3, values: geoKeyDirectory([[1024, 1], [3072, 32652]]) },
];

describe("readGeoTiffHeader 구조 사실과 올리기 전 점검", () => {
  it("JPEG(YCbCr) RGB 정사영상의 압축·색 방식·위치 정보를 읽고 문제 없다고 본다", async () => {
    const header = await readGeoTiffHeader(buildTiff(BASE_TAGS));
    expect(header.layout).toMatchObject({ compression: 7, photometric: 6, planarConfiguration: 1, hasNoDataTag: false, georeferenced: true, modelType: 1 });
    expect(preflightGeoTiff("ortho", header, 1000)).toEqual([]);
  });

  it("NoData 태그와 알파 밴드(JPEG)가 있는 정사영상은 거부 조건을 모두 알려 준다", async () => {
    const tags = BASE_TAGS.filter((t) => ![258, 277].includes(t.tag)).concat([
      { tag: 258, type: 3, values: [8, 8, 8, 8] }, { tag: 277, type: 3, values: [4] }, { tag: 338, type: 3, values: [2] },
      { tag: 42113, type: 2, values: "0" },
    ]);
    const header = await readGeoTiffHeader(buildTiff(tags));
    expect(header.layout).toMatchObject({ hasNoDataTag: true, extraSamples: [2] });
    expect(preflightGeoTiff("ortho", header, 1000).map((f) => f.code)).toEqual(expect.arrayContaining(["ORTHO_NODATA", "ORTHO_JPEG", "ORTHO_ALPHA_BINARY"]));
  });

  it("DSM 배율은 GDAL_METADATA 에서 읽고, 위치 태그가 없으면 위치 없음으로 본다", async () => {
    const metadata = '<GDALMetadata><Item name="SCALE" sample="0" role="scale">0.01</Item><Item name="OFFSET" sample="0" role="offset">0</Item></GDALMetadata>';
    const tags: TagValue[] = [
      { tag: 256, type: 4, values: [1] }, { tag: 257, type: 4, values: [1] }, { tag: 258, type: 3, values: [32] },
      { tag: 259, type: 3, values: [8] }, { tag: 262, type: 3, values: [1] }, { tag: 273, type: 4, values: [200] },
      { tag: 277, type: 3, values: [1] }, { tag: 278, type: 4, values: [1] }, { tag: 279, type: 4, values: [4] },
      { tag: 339, type: 3, values: [3] }, { tag: 42112, type: 2, values: metadata },
    ];
    const header = await readGeoTiffHeader(buildTiff(tags));
    expect(header.layout).toMatchObject({ scale: 0.01, offset: 0, georeferenced: false });
    expect(preflightGeoTiff("dsm", header, 1000).map((f) => f.code)).toEqual(expect.arrayContaining(["DSM_SCALE_OFFSET", "NO_GEOREFERENCE"]));
  });

  it("실제 writeArrayBuffer 파일에서 수직 기준 키를 읽는다", async () => {
    const bytes = writeArrayBuffer(new Float32Array(12).fill(1), {
      width: 4, height: 3, ModelPixelScale: [1, 1, 0], ModelTiepoint: [0, 0, 0, 200000, 550000, 0],
      ProjectedCSTypeGeoKey: 5186, GTModelTypeGeoKey: 1,
      ...({ VerticalCSTypeGeoKey: 5703 } as object), // 타입 정의에는 없지만 라이터가 GeoKey 로 기록한다
    });
    const header = await readGeoTiffHeader(new Blob([bytes]));
    expect(header.layout).toMatchObject({ verticalCsType: 5703, georeferenced: true });
    expect(preflightGeoTiff("dsm", header, 1000)).toEqual([]);
  });
});
