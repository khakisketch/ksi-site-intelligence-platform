import {
  fromArrayBuffer,
  type GeoTIFFImage,
  type TypedArray,
  type TypedArrayWithDimensions,
} from "geotiff";

import { formatCountKo } from "@/lib/number-format";

import { proj4, registerKoreaProjections } from "./proj4-defs";

/** Leaflet ImageOverlay가 받는 `[south, west] → [north, east]` 경계다. */
export type Wgs84RasterBounds = [[number, number], [number, number]];

export interface RasterImageOverlay {
  imageUrl: string;
  bounds: Wgs84RasterBounds;
  width: number;
  height: number;
}

export interface DiffRasterOverlay extends RasterImageOverlay {
  maxAbsM: number;
}

type Rgba = readonly [number, number, number, number];

// 브라우저가 원본 정사영상을 그대로 전부 풀면 수백 MB를 점유할 수 있다. 화면에
// 보이는 해상도까지만 읽고, 분석 수치나 원본 artifact 자체를 바꾸지 않는다.
export const MAX_RASTER_RENDER_EDGE = 2_048;
export const MAX_RASTER_RENDER_PIXELS = 4_194_304;
// 차분 지도는 화면이 "최대 높이차"를 말하므로, 최고값을 축소본에서 추정하지
// 않는다. 이보다 큰 격자는 server-side tile artifact가 생기기 전까지 열람을
// 거부한다. 틀린 최대값을 표시하는 것보다 명시적으로 막는 편이 안전하다.
export const MAX_DIFF_ANALYSIS_PIXELS = 32_000_000;

const SUPPORTED_EPSG = new Set([4326, 3857, 5179, 5185, 5186, 5187, 5188]);
const EPSILON = 1e-12;

function asNumberArray(value: unknown): number[] | null {
  const arrayLike = Array.isArray(value)
    ? value
    : ArrayBuffer.isView(value) && !(value instanceof DataView)
      ? (value as unknown as ArrayLike<number>)
      : null;
  if (!arrayLike) return null;
  const values = Array.from(arrayLike, Number);
  return values.every(Number.isFinite) ? values : null;
}

function asFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const values = asNumberArray(value);
  return values && values.length > 0 ? values[0] : null;
}

/** GeoTIFF GeoKey에서 제품이 지원하는 평면 좌표계를 명시적으로 고른다. */
export function resolveGeoTiffCrs(geoKeys: Record<string, unknown> | null): string {
  const projected = asFiniteNumber(geoKeys?.ProjectedCSTypeGeoKey);
  const geographic = asFiniteNumber(geoKeys?.GeographicTypeGeoKey);
  const epsg = projected ?? geographic;

  if (epsg === null) {
    throw new Error("GeoTIFF 좌표 기준(EPSG)을 찾지 못했습니다");
  }
  if (!SUPPORTED_EPSG.has(epsg)) {
    throw new Error(`지원하지 않는 GeoTIFF 좌표 기준(EPSG:${epsg})입니다`);
  }
  return `EPSG:${epsg}`;
}

/**
 * Leaflet ImageOverlay는 축과 평행한 사각형만 표현한다. 회전 GeoTIFF를 단순한
 * bbox로 늘리면 실제 위치와 다른 그림이 되므로 지원하지 않는다.
 */
function assertNorthUp(image: GeoTIFFImage): void {
  const transform = image.fileDirectory.getValue("ModelTransformation");
  if (!transform) return;
  const values = asNumberArray(transform);
  if (!values || values.length < 16) {
    throw new Error("GeoTIFF 공간 변환 정보를 읽지 못했습니다");
  }
  if (Math.abs(values[1]) > EPSILON || Math.abs(values[4]) > EPSILON) {
    throw new Error("회전된 GeoTIFF는 현재 지도에서 열람할 수 없습니다");
  }
}

function assertFiniteSourceBounds(bounds: readonly number[]): [number, number, number, number] {
  if (
    bounds.length !== 4 ||
    !bounds.every(Number.isFinite) ||
    !(bounds[0] < bounds[2]) ||
    !(bounds[1] < bounds[3])
  ) {
    throw new Error("GeoTIFF 공간 범위가 유효하지 않습니다");
  }
  return [bounds[0], bounds[1], bounds[2], bounds[3]];
}

/** source CRS의 네 모서리를 WGS84로 바꿔 Leaflet의 지리 경계를 만든다. */
function imageBoundsInWgs84(image: GeoTIFFImage): Wgs84RasterBounds {
  assertNorthUp(image);
  const sourceCrs = resolveGeoTiffCrs(image.getGeoKeys() as Record<string, unknown> | null);
  const [minX, minY, maxX, maxY] = assertFiniteSourceBounds(image.getBoundingBox());

  registerKoreaProjections();
  const corners = [
    proj4(sourceCrs, "EPSG:4326", [minX, minY]),
    proj4(sourceCrs, "EPSG:4326", [minX, maxY]),
    proj4(sourceCrs, "EPSG:4326", [maxX, minY]),
    proj4(sourceCrs, "EPSG:4326", [maxX, maxY]),
  ];
  const longitudes = corners.map(([longitude]) => longitude);
  const latitudes = corners.map(([, latitude]) => latitude);
  const west = Math.min(...longitudes);
  const east = Math.max(...longitudes);
  const south = Math.min(...latitudes);
  const north = Math.max(...latitudes);

  if (
    ![west, east, south, north].every(Number.isFinite) ||
    west < -180 ||
    east > 180 ||
    south < -90 ||
    north > 90 ||
    !(west < east) ||
    !(south < north)
  ) {
    throw new Error("GeoTIFF 좌표를 WGS84로 변환하지 못했습니다");
  }
  return [
    [south, west],
    [north, east],
  ];
}

export function rasterRenderDimensions(
  sourceWidth: number,
  sourceHeight: number,
): { width: number; height: number } {
  if (!Number.isSafeInteger(sourceWidth) || !Number.isSafeInteger(sourceHeight)) {
    throw new Error("GeoTIFF 화소 크기가 유효하지 않습니다");
  }
  if (sourceWidth <= 0 || sourceHeight <= 0) {
    throw new Error("GeoTIFF 화소 크기가 0입니다");
  }
  const scale = Math.min(
    1,
    MAX_RASTER_RENDER_EDGE / sourceWidth,
    MAX_RASTER_RENDER_EDGE / sourceHeight,
    Math.sqrt(MAX_RASTER_RENDER_PIXELS / (sourceWidth * sourceHeight)),
  );
  return {
    width: Math.max(1, Math.floor(sourceWidth * scale)),
    height: Math.max(1, Math.floor(sourceHeight * scale)),
  };
}

function rgbaObjectUrl(width: number, height: number, rgba: Uint8ClampedArray): Promise<string> {
  if (rgba.length !== width * height * 4) {
    throw new Error("GeoTIFF 화면 버퍼 크기가 맞지 않습니다");
  }
  if (typeof document === "undefined") {
    throw new Error("GeoTIFF 지도는 브라우저에서만 열 수 있습니다");
  }
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("GeoTIFF 지도 캔버스를 만들지 못했습니다");
  // `Uint8ClampedArray.from` 은 SharedArrayBuffer view 가능성이 있는 입력을
  // 독립 ArrayBuffer로 복사해 DOM ImageData의 타입·수명 경계를 만족시킨다.
  context.putImageData(new ImageData(Uint8ClampedArray.from(rgba), width, height), 0, 0);
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error("GeoTIFF 지도 이미지를 만들지 못했습니다"));
        return;
      }
      resolve(URL.createObjectURL(blob));
    }, "image/png");
  });
}

function byteForChannel(value: number, values: TypedArray, bitDepth: number): number {
  if (!Number.isFinite(value)) return 0;
  // `readRGB`가 비-RGB photometric을 변환한 경우는 Uint8Array다. 원본 bit
  // depth(예: grayscale 16-bit)를 다시 적용하면 모두 검게 되므로 그대로 둔다.
  if (values instanceof Uint8Array) return Math.max(0, Math.min(255, value));
  const max = bitDepth > 0 && bitDepth <= 32 ? 2 ** bitDepth - 1 : 255;
  return Math.max(0, Math.min(255, Math.round((value / max) * 255)));
}

function rgbToRgba(values: TypedArrayWithDimensions, bitDepth: number): Uint8ClampedArray {
  const pixelCount = values.width * values.height;
  if (values.length !== pixelCount * 3) {
    throw new Error("지원하지 않는 GeoTIFF 색상 밴드 구성입니다");
  }
  const rgba = new Uint8ClampedArray(pixelCount * 4);
  for (let pixel = 0; pixel < pixelCount; pixel += 1) {
    const input = pixel * 3;
    const output = pixel * 4;
    rgba[output] = byteForChannel(values[input], values, bitDepth);
    rgba[output + 1] = byteForChannel(values[input + 1], values, bitDepth);
    rgba[output + 2] = byteForChannel(values[input + 2], values, bitDepth);
    rgba[output + 3] = 255;
  }
  return rgba;
}

function isNoData(value: number, noData: number | null): boolean {
  return noData !== null && value === noData;
}

function scalarRgba(
  values: TypedArrayWithDimensions,
  noData: number | null,
  colorFor: (value: number | null) => Rgba,
): Uint8ClampedArray {
  const pixelCount = values.width * values.height;
  if (values.length !== pixelCount) {
    throw new Error("차분 GeoTIFF는 1개 높이 밴드여야 합니다");
  }
  const rgba = new Uint8ClampedArray(pixelCount * 4);
  for (let pixel = 0; pixel < pixelCount; pixel += 1) {
    const rawValue = values[pixel];
    const value = Number.isFinite(rawValue) && !isNoData(rawValue, noData) ? rawValue : null;
    const [red, green, blue, alpha] = colorFor(value);
    const output = pixel * 4;
    rgba[output] = red;
    rgba[output + 1] = green;
    rgba[output + 2] = blue;
    rgba[output + 3] = alpha;
  }
  return rgba;
}

async function openGeoTiff(arrayBuffer: ArrayBuffer): Promise<{
  image: GeoTIFFImage;
  bounds: Wgs84RasterBounds;
}> {
  const tiff = await fromArrayBuffer(arrayBuffer);
  const image = await tiff.getImage();
  return { image, bounds: imageBoundsInWgs84(image) };
}

/** 정사영상은 화면 해상도로만 읽어 이미지 overlay로 만든다. */
export async function createOrthophotoOverlay(arrayBuffer: ArrayBuffer): Promise<RasterImageOverlay> {
  const { image, bounds } = await openGeoTiff(arrayBuffer);
  const { width, height } = rasterRenderDimensions(image.getWidth(), image.getHeight());
  const values = await image.readRGB({
    interleave: true,
    width,
    height,
    resampleMethod: "bilinear",
  });
  const rgba = rgbToRgba(values, image.getBitsPerSample(0));
  return {
    imageUrl: await rgbaObjectUrl(width, height, rgba),
    bounds,
    width,
    height,
  };
}

async function maxAggregatedAbs(
  image: GeoTIFFImage,
  thresholdM: number,
  noData: number | null,
): Promise<number> {
  const width = image.getWidth();
  const height = image.getHeight();
  const pixels = width * height;
  if (pixels > MAX_DIFF_ANALYSIS_PIXELS) {
    throw new Error(
      `차분 GeoTIFF가 너무 큽니다(${formatCountKo(pixels)} 셀). 타일 산출물로 다시 생성하세요`,
    );
  }

  let max = 0;
  // 한 번에 전량을 풀지 않고 1M 셀씩 읽어, 최대값은 원본 격자에서 보존한다.
  const rowsPerChunk = Math.max(1, Math.floor(1_000_000 / width));
  for (let top = 0; top < height; top += rowsPerChunk) {
    const bottom = Math.min(height, top + rowsPerChunk);
    const values = await image.readRasters({
      window: [0, top, width, bottom],
      samples: [0],
      interleave: true,
    });
    for (const rawValue of values) {
      if (!Number.isFinite(rawValue) || isNoData(rawValue, noData)) continue;
      const magnitude = Math.abs(rawValue);
      if (magnitude >= thresholdM && magnitude > max) max = magnitude;
    }
  }
  return max;
}

/**
 * 저장된 차분 래스터에서 원본 최대값을 읽고, 화면용 축소본만 만들어 색칠한다.
 * `colorFor`는 그 뒤에 호출되어 기존의 3상태 판정/팔레트를 그대로 사용한다.
 */
export async function createDiffRasterOverlay(
  arrayBuffer: ArrayBuffer,
  thresholdM: number,
  colorFor: (value: number | null, maxAbsM: number) => Rgba,
): Promise<DiffRasterOverlay> {
  const { image, bounds } = await openGeoTiff(arrayBuffer);
  if (image.getSamplesPerPixel() !== 1) {
    throw new Error("차분 GeoTIFF는 1개 높이 밴드여야 합니다");
  }
  const noData = image.getGDALNoData();
  const maxAbsM = await maxAggregatedAbs(image, thresholdM, noData);
  const { width, height } = rasterRenderDimensions(image.getWidth(), image.getHeight());
  const values = await image.readRasters({
    samples: [0],
    interleave: true,
    width,
    height,
    resampleMethod: "nearest",
  });
  const rgba = scalarRgba(values, noData, (value) => colorFor(value, maxAbsM));
  return {
    imageUrl: await rgbaObjectUrl(width, height, rgba),
    bounds,
    width,
    height,
    maxAbsM,
  };
}

export function revokeRasterObjectUrl(url: string | null): void {
  if (url) URL.revokeObjectURL(url);
}
