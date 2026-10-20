import { describe, expect, it } from "vitest";

import {
  decodeReceiptPreview,
  SpatialDataPreviewError,
} from "@/lib/spatial-data-preview";

/**
 * 작은 실제 float32 GeoTIFF를 손으로 지어 디코딩한다 — geotiff 목이 아니다.
 * GDAL NoData 태그(42113)와 한 스트립 비압축 래스터만 쓴다. 마스크가 있으면
 * TIFF 6.0 관례의 두 번째 IFD(NewSubfileType 4 + PhotometricInterpretation 4 +
 * 단일 1비트 밴드, 행 바이트 패딩)로 연결한다.
 */
function buildFloatTiff(
  width: number,
  height: number,
  values: number[],
  noData: string | null,
  mask?: { bits: number[]; width: number; height: number },
  bands: { samples?: number; bits?: number; format?: number; photo?: number } = {},
): ArrayBuffer {
  const samples = bands.samples ?? 1;
  const bits = bands.bits ?? 32;
  const format = bands.format ?? 3;
  const photo = bands.photo ?? 1;
  const bytesPerSample = bits / 8;
  const align4 = (value: number): number => value + (((4 - (value % 4)) % 4));
  const encoder = new TextEncoder();
  const nodataBytes = noData !== null ? encoder.encode(`${noData}\0`) : null;
  // 다중값 SHORT 태그(BitsPerSample·SampleFormat)는 IFD 밖에 두고 오프셋으로 가리킨다.
  const shortArrays: Array<{ tag: number; values: number[] }> = [];
  if (samples > 1) {
    shortArrays.push({ tag: 258, values: Array(samples).fill(bits) });
    shortArrays.push({ tag: 339, values: Array(samples).fill(format) });
  }
  const mainEntries: Array<[number, number, number, number]> = [
    [256, 4, 1, width],
    [257, 4, 1, height],
    [258, 3, samples, bits],
    [259, 3, 1, 1],
    [262, 3, 1, photo],
    [273, 4, 1, 0],
    [277, 3, 1, samples],
    [278, 4, 1, height],
    [279, 4, 1, width * height * samples * bytesPerSample],
    [339, 3, samples, format],
  ];
  if (nodataBytes) mainEntries.push([42113, 2, nodataBytes.length, 0]);
  mainEntries.sort((a, b) => a[0] - b[0]);

  let maskEntries: Array<[number, number, number, number]> = [];
  let maskDataBytes: Uint8Array | null = null;
  if (mask) {
    const rowBytes = Math.ceil(mask.width / 8);
    maskDataBytes = new Uint8Array(rowBytes * mask.height);
    for (let row = 0; row < mask.height; row += 1) {
      let byte = 0;
      for (let col = 0; col < mask.width; col += 1) {
        if (mask.bits[row * mask.width + col] !== 0) byte |= 0x80 >> (col % 8);
        if (col % 8 === 7 || col === mask.width - 1) {
          maskDataBytes[row * rowBytes + Math.floor(col / 8)] = byte;
          byte = 0;
        }
      }
    }
    maskEntries = [
      [254, 4, 1, 4],
      [256, 4, 1, mask.width],
      [257, 4, 1, mask.height],
      [258, 3, 1, 1],
      [259, 3, 1, 1],
      [262, 3, 1, 4],
      [273, 4, 1, 0],
      [277, 3, 1, 1],
      [278, 4, 1, mask.height],
      [279, 4, 1, maskDataBytes.byteLength],
    ];
    maskEntries.sort((a, b) => a[0] - b[0]);
  }

  const mainCount = mainEntries.length;
  const maskCount = maskEntries.length;
  const ifdOffset = 8;
  let cursor = align4(ifdOffset + 2 + 12 * mainCount + 4);
  let nodataOffset = 0;
  if (nodataBytes) {
    nodataOffset = cursor;
    cursor = align4(cursor + nodataBytes.byteLength);
  }
  const imageOffset = cursor;
  cursor = align4(cursor + width * height * samples * bytesPerSample);
  let maskDataOffset = 0;
  if (maskDataBytes) {
    maskDataOffset = cursor;
    cursor += maskDataBytes.byteLength;
  }
  let maskIfdOffset = 0;
  if (maskEntries.length > 0) {
    maskIfdOffset = cursor;
    cursor += 2 + 12 * maskCount + 4;
  }
  const shortArrayOffsets = new Map<number, number>();
  for (const { tag, values: arrayValues } of shortArrays) {
    shortArrayOffsets.set(tag, cursor);
    cursor += arrayValues.length * 2;
  }

  const buffer = new ArrayBuffer(cursor);
  const view = new DataView(buffer);
  view.setUint8(0, 0x49);
  view.setUint8(1, 0x49);
  view.setUint16(2, 42, true);
  view.setUint32(4, ifdOffset, true);
  const writeIfd = (
    base: number,
    entries: Array<[number, number, number, number]>,
    next: number,
    values: (tag: number, fallback: number) => number,
  ): void => {
    view.setUint16(base, entries.length, true);
    entries.forEach(([tag, type, tagCount, fallback], index) => {
      const offset = base + 2 + index * 12;
      view.setUint16(offset, tag, true);
      view.setUint16(offset + 2, type, true);
      view.setUint32(offset + 4, tagCount, true);
      view.setUint32(offset + 8, values(tag, fallback), true);
    });
    view.setUint32(base + 2 + 12 * entries.length, next, true);
  };
  writeIfd(ifdOffset, mainEntries, maskIfdOffset, (tag, fallback) => {
    if (tag === 273) return imageOffset;
    if (tag === 42113) return nodataOffset;
    if (shortArrayOffsets.has(tag)) return shortArrayOffsets.get(tag)!;
    return fallback;
  });
  for (const { tag, values: arrayValues } of shortArrays) {
    const base = shortArrayOffsets.get(tag)!;
    arrayValues.forEach((value, index) => view.setUint16(base + index * 2, value, true));
  }
  if (nodataBytes) new Uint8Array(buffer, nodataOffset, nodataBytes.byteLength).set(nodataBytes);
  if (bytesPerSample === 4) {
    new Float32Array(buffer, imageOffset, width * height * samples).set(values);
  } else {
    new Uint8Array(buffer, imageOffset, width * height * samples).set(values);
  }
  if (maskDataBytes) {
    new Uint8Array(buffer, maskDataOffset, maskDataBytes.byteLength).set(maskDataBytes);
    writeIfd(maskIfdOffset, maskEntries, 0, (tag) => (tag === 273 ? maskDataOffset : maskEntries.find(([t]) => t === tag)![3]));
  }
  return buffer;
}

function pixelAt(pixels: Uint8ClampedArray<ArrayBuffer>, index: number): [number, number, number, number] {
  const offset = index * 4;
  return [pixels[offset], pixels[offset + 1], pixels[offset + 2], pixels[offset + 3]];
}

describe("decodeReceiptPreview with a real small float GeoTIFF", () => {
  it("excludes NoData from the stretch, keeps valid zeros opaque, and blanks NoData", async () => {
    const buffer = buildFloatTiff(2, 2, [0, -10000, 5, 10], "-10000");
    const decoded = await decodeReceiptPreview(buffer, { width: 2, height: 2 });
    expect(decoded.color).toBe(false);
    // 유효 0은 검은색 불투명 — NoData가 아니다.
    expect(pixelAt(decoded.pixels, 0)).toEqual([0, 0, 0, 255]);
    // NoData 픽셀은 투명이며 늘이기에 쓰이지 않는다(min 0, max 10).
    expect(pixelAt(decoded.pixels, 1)).toEqual([0, 0, 0, 0]);
    expect(pixelAt(decoded.pixels, 2)).toEqual([128, 128, 128, 255]);
    expect(pixelAt(decoded.pixels, 3)).toEqual([255, 255, 255, 255]);
  });

  it("reports an all-NoData window as empty instead of a zero height", async () => {
    const buffer = buildFloatTiff(2, 2, [-10000, -10000, -10000, -10000], "-10000");
    const failure = await decodeReceiptPreview(buffer, { width: 2, height: 2 }).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(SpatialDataPreviewError);
    expect((failure as SpatialDataPreviewError).kind).toBe("UNSUPPORTED");
    expect((failure as Error).message).toMatch(/NoData/);
  });

  it("lets a NaN NoData pass through without breaking valid pixels", async () => {
    const buffer = buildFloatTiff(2, 2, [0, Number.NaN, 5, 10], "nan");
    const decoded = await decodeReceiptPreview(buffer, { width: 2, height: 2 });
    expect(pixelAt(decoded.pixels, 0)).toEqual([0, 0, 0, 255]);
    expect(pixelAt(decoded.pixels, 1)).toEqual([0, 0, 0, 0]);
    expect(pixelAt(decoded.pixels, 2)).toEqual([128, 128, 128, 255]);
    expect(pixelAt(decoded.pixels, 3)).toEqual([255, 255, 255, 255]);
  });

  it("ignores masked-out finite pixels in the stretch and blanks them, even valid zero", async () => {
    // 유효 픽셀 0, 5, 10, 7, 3 — 마스크 제외 20(유한)과 0(유효 0)은 늘이기 밖이다.
    const buffer = buildFloatTiff(
      4, 2,
      [0, -10000, 5, 10, 7, 20, 0, 3],
      "-10000",
      { bits: [1, 0, 1, 1, 1, 0, 0, 1], width: 4, height: 2 },
    );
    const decoded = await decodeReceiptPreview(buffer, { width: 4, height: 2 });
    expect(decoded.color).toBe(false);
    // 마스크 제외 20이 max에 들어갔다면 idx3은 128이 된다 — 255여야 제외 증거다.
    expect(pixelAt(decoded.pixels, 0)).toEqual([0, 0, 0, 255]);
    expect(pixelAt(decoded.pixels, 1)).toEqual([0, 0, 0, 0]);
    expect(pixelAt(decoded.pixels, 2)).toEqual([128, 128, 128, 255]);
    expect(pixelAt(decoded.pixels, 3)).toEqual([255, 255, 255, 255]);
    expect(pixelAt(decoded.pixels, 4)).toEqual([179, 179, 179, 255]);
    expect(pixelAt(decoded.pixels, 5)).toEqual([0, 0, 0, 0]);
    // 마스크된 유한 0은 투명 — 0을 보고 유효하다고 추정하지 않는다.
    expect(pixelAt(decoded.pixels, 6)).toEqual([0, 0, 0, 0]);
    expect(pixelAt(decoded.pixels, 7)).toEqual([77, 77, 77, 255]);
  });

  it("reports a fully masked window as empty instead of stretching the excluded pixels", async () => {
    const buffer = buildFloatTiff(
      2, 2,
      [1, 2, 3, 4],
      null,
      { bits: [0, 0, 0, 0], width: 2, height: 2 },
    );
    const failure = await decodeReceiptPreview(buffer, { width: 2, height: 2 }).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(SpatialDataPreviewError);
    expect((failure as SpatialDataPreviewError).kind).toBe("UNSUPPORTED");
    expect((failure as Error).message).toMatch(/마스크 제외/);
  });

  it("refuses a mask whose size differs from the output instead of sampling it", async () => {
    const buffer = buildFloatTiff(
      4, 2,
      [0, 1, 2, 3, 4, 5, 6, 7],
      null,
      { bits: [1, 1, 1, 1], width: 2, height: 2 },
    );
    const failure = await decodeReceiptPreview(buffer, { width: 4, height: 2 }).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(SpatialDataPreviewError);
    expect((failure as SpatialDataPreviewError).kind).toBe("UNSUPPORTED");
    expect((failure as Error).message).toMatch(/마스크 크기/);
  });

  it("blanks masked-out color pixels without touching valid colors", async () => {
    const buffer = buildFloatTiff(
      2, 1,
      [255, 0, 0, 0, 255, 0],
      null,
      { bits: [1, 0], width: 2, height: 1 },
      { samples: 3, bits: 8, format: 1, photo: 2 },
    );
    const decoded = await decodeReceiptPreview(buffer, { width: 2, height: 1 });
    expect(decoded.color).toBe(true);
    expect(pixelAt(decoded.pixels, 0)).toEqual([255, 0, 0, 255]);
    expect(pixelAt(decoded.pixels, 1)).toEqual([0, 0, 0, 0]);
  });

  it("refuses bytes whose pixel size differs from the receipt", async () => {
    const buffer = buildFloatTiff(2, 2, [0, 1, 2, 3], null);
    const failure = await decodeReceiptPreview(buffer, { width: 4, height: 4 }).catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(SpatialDataPreviewError);
    expect((failure as SpatialDataPreviewError).kind).toBe("BAD_RECEIPT");
  });
});
