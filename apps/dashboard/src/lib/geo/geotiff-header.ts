import { fromBlob } from "geotiff";

/**
 * AX-3: 등록 폼이 파일을 고르는 순간 GeoTIFF 헤더만 읽어 신고값을 미리 채운다.
 *
 * 여기서 읽은 값은 전부 "고객 신고"다. 측정 사실은 봉인 뒤 Core 검사만 만든다
 * (EXT-VAL-02). 그래서 이 모듈은 신고할 수 있는 것(CRS·생산 소프트웨어)과
 * 참고로만 보여줄 것(헤더 날짜·픽셀 크기·종류 추정)을 구분해서 돌려준다.
 * TIFF DateTime 의 뜻은 소프트웨어마다 다르다(ODM 3.5.6 은 사진 촬영일, 다른
 * 도구는 흔히 파일 생성 시각). 한 시점이고 뜻도 헤더로 알 수 없으므로 촬영
 * 구간(시작·종료)으로 옮기지 않는다.
 */

export type ArtifactSlot = "ortho" | "dsm";

/**
 * 올리기 전 점검용 파일 구조 사실. 첫 IFD 에서만 읽는다. 값이 없으면 `null`/기본값이며,
 * 이 필드 자체가 없는 헤더(옛 호출·시험)는 "모름"으로 취급해 어떤 점검도 만들지 않는다.
 */
export type GeoTiffLayout = {
  /** TIFF Compression (태그 259, 없으면 1). */
  compression: number;
  /** TIFF Predictor (태그 317, 없으면 1). */
  predictor: number;
  /** TIFF PhotometricInterpretation (태그 262). */
  photometric: number | null;
  /** TIFF PlanarConfiguration (태그 284, 없으면 1 = 픽셀 교차). */
  planarConfiguration: number;
  /** TIFF ExtraSamples (태그 338). */
  extraSamples: number[];
  /** GDAL_NODATA 태그(42113)가 있는가. */
  hasNoDataTag: boolean;
  /** GDAL_METADATA 에 적힌 첫 밴드의 scale/offset. 없으면 null. */
  scale: number | null;
  offset: number | null;
  /** 타이포인트+픽셀 크기 또는 변환 행렬이 있는가. */
  georeferenced: boolean;
  modelType: number | null;
  projLinearUnits: number | null;
  verticalCsType: number | null;
  verticalUnits: number | null;
};

export type GeoTiffRawHeader = {
  width: number;
  height: number;
  samplesPerPixel: number;
  bitsPerSample: number;
  /** TIFF SampleFormat: 1 unsigned int, 2 signed int, 3 IEEE float. */
  sampleFormat: number;
  geoKeys: Record<string, unknown> | null;
  software: string | null;
  dateTime: string | null;
  pixelSize: [number, number] | null;
  layout?: GeoTiffLayout;
};

export type GeoTiffRecognition = {
  declaredCrs: string | null;
  producer: { name: string; version: string | null } | null;
  kindHint: ArtifactSlot | null;
  headerDateTime: string | null;
  width: number;
  height: number;
  pixelSize: [number, number] | null;
};

export class NotGeoTiffError extends Error {
  constructor() {
    super("GeoTIFF 헤더를 읽지 못했습니다");
    this.name = "NotGeoTiffError";
  }
}

// 등록 BFF 의 boundedText 와 같은 상한이다. 넘으면 신고로 옮기지 않는다.
const MAX_DECLARED_TEXT = 255;
// GeoTIFF 사용자 정의(32767)와 미정의(0)는 EPSG 코드가 아니다.
const USER_DEFINED_GEOKEY = 32767;

function positiveInteger(value: unknown): number | null {
  const number = Array.isArray(value) ? value[0] : value;
  return typeof number === "number" && Number.isSafeInteger(number) && number > 0 ? number : null;
}

function embeddedEpsg(geoKeys: Record<string, unknown> | null): string | null {
  const code = positiveInteger(geoKeys?.ProjectedCSTypeGeoKey) ?? positiveInteger(geoKeys?.GeographicTypeGeoKey);
  return code === null || code === USER_DEFINED_GEOKEY ? null : `EPSG:${code}`;
}

function producerFrom(software: string | null): GeoTiffRecognition["producer"] {
  const text = software?.trim() ?? "";
  if (text.length === 0 || text.length > MAX_DECLARED_TEXT) return null;
  const match = /^(.*?\S)\s+v?(\d[\w.+-]*)$/.exec(text);
  return match ? { name: match[1], version: match[2] } : { name: text, version: null };
}

function kindHintFrom(header: GeoTiffRawHeader): ArtifactSlot | null {
  if (header.samplesPerPixel === 1 && header.sampleFormat === 3) return "dsm";
  if ((header.samplesPerPixel === 3 || header.samplesPerPixel === 4) && header.bitsPerSample === 8 && header.sampleFormat === 1) {
    return "ortho";
  }
  return null;
}

function headerDateTimeFrom(dateTime: string | null): string | null {
  const match = /^(\d{4}):(\d{2}):(\d{2}) (\d{2}:\d{2}:\d{2})(Z|[+-]\d{2}:\d{2})?$/.exec(dateTime?.trim() ?? "");
  if (!match) return null;
  const zone = match[5] === undefined ? "" : match[5] === "Z" ? " UTC" : ` UTC${match[5]}`;
  return `${match[1]}-${match[2]}-${match[3]} ${match[4]}${zone}`;
}

export function recognizeGeoTiffHeader(header: GeoTiffRawHeader): GeoTiffRecognition {
  return {
    declaredCrs: embeddedEpsg(header.geoKeys),
    producer: producerFrom(header.software),
    kindHint: kindHintFrom(header),
    headerDateTime: headerDateTimeFrom(header.dateTime),
    width: header.width,
    height: header.height,
    pixelSize: header.pixelSize,
  };
}

/** 헤더가 다른 칸을 분명히 가리킬 때만 경고한다. 칸은 사람이 바꾼다. */
export function slotMismatch(slot: ArtifactSlot, hint: ArtifactSlot | null): boolean {
  return hint !== null && hint !== slot;
}

function numberOrNull(value: unknown): number | null {
  const number = Array.isArray(value) ? value[0] : value;
  return typeof number === "number" && Number.isFinite(number) ? number : null;
}

function nonEmpty(value: unknown): boolean {
  return value !== null && value !== undefined && (typeof value !== "object" || (value as { length?: number }).length !== 0);
}

/** GDAL_METADATA XML 에서 role="scale"/"offset" 항목의 첫 값을 읽는다. 없으면 null. */
function gdalScaleOffset(xml: string | null, role: "scale" | "offset"): number | null {
  if (xml === null) return null;
  const match = new RegExp(`<Item\\b[^>]*\\brole="${role}"[^>]*>([^<]*)</Item>`, "i").exec(xml);
  if (!match) return null;
  const value = Number(match[1].trim());
  return Number.isFinite(value) ? value : null;
}

function textTag(value: unknown): string | null {
  return typeof value === "string" ? value.replace(/\0+$/, "") : null;
}

/** 파일 전체를 올리지 않고 첫 IFD 와 GeoKey 만 읽는다(fromBlob 은 범위 읽기). */
export async function readGeoTiffHeader(blob: Blob, signal?: AbortSignal): Promise<GeoTiffRawHeader> {
  let image;
  try {
    const tiff = await fromBlob(blob, signal);
    image = await tiff.getImage(0);
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new NotGeoTiffError();
  }
  const directory = image.getFileDirectory();
  const [software, dateTime] = await Promise.all([
    directory.loadValue("Software").catch(() => undefined),
    directory.loadValue("DateTime").catch(() => undefined),
  ]);
  let pixelSize: [number, number] | null = null;
  try {
    const [x, y] = image.getResolution();
    if (Number.isFinite(x) && Number.isFinite(y)) pixelSize = [Math.abs(x), Math.abs(y)];
  } catch {
    pixelSize = null;
  }
  const load = (name: Parameters<typeof directory.loadValue>[0]) => directory.loadValue(name).catch(() => undefined) as Promise<unknown>;
  const [compression, predictor, photometric, planar, extra, noData, gdalMetadata, tiePoint, pixelScale, transformation] = await Promise.all([
    load("Compression"), load("Predictor"), load("PhotometricInterpretation"), load("PlanarConfiguration"),
    load("ExtraSamples"), load("GDAL_NODATA"), load("GDAL_METADATA"), load("ModelTiepoint"), load("ModelPixelScale"), load("ModelTransformation"),
  ]);
  const geoKeys = image.getGeoKeys();
  const metadataText = textTag(gdalMetadata);
  const layout: GeoTiffLayout = {
    compression: numberOrNull(compression) ?? 1,
    predictor: numberOrNull(predictor) ?? 1,
    photometric: numberOrNull(photometric),
    planarConfiguration: numberOrNull(planar) ?? 1,
    extraSamples: Array.from((extra as ArrayLike<number> | undefined) ?? []),
    hasNoDataTag: nonEmpty(noData),
    scale: gdalScaleOffset(metadataText, "scale"),
    offset: gdalScaleOffset(metadataText, "offset"),
    georeferenced: nonEmpty(transformation) || (nonEmpty(tiePoint) && nonEmpty(pixelScale)),
    modelType: numberOrNull(geoKeys?.GTModelTypeGeoKey),
    projLinearUnits: numberOrNull(geoKeys?.ProjLinearUnitsGeoKey),
    verticalCsType: numberOrNull(geoKeys?.VerticalCSTypeGeoKey),
    verticalUnits: numberOrNull(geoKeys?.VerticalUnitsGeoKey),
  };
  return {
    width: image.getWidth(),
    height: image.getHeight(),
    samplesPerPixel: image.getSamplesPerPixel(),
    bitsPerSample: image.getBitsPerSample(0),
    sampleFormat: image.getSampleFormat(0),
    geoKeys,
    software: textTag(software),
    dateTime: textTag(dateTime),
    pixelSize,
    layout,
  };
}
