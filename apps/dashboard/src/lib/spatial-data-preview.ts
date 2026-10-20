import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex } from "@noble/hashes/utils.js";

/**
 * 준비된 출력 미리보기의 브라우저 표시 상한 — Core의 외부 검증·원본 한도를
 * 바꾸지 않는 표시 전용 cap이다(외부 정사영상 표시와 같은 64 MiB).
 */
export const SPATIAL_DATA_PREVIEW_MAX_BYTES = 64 * 1024 * 1024;

/** 브라우저에서 디코딩하는 출력 픽셀 수 상한 — 유한 창 출력을 전제로 한다. */
export const SPATIAL_DATA_PREVIEW_MAX_PIXELS = 1024 * 1024;

/** 미리보기 디코딩이 스캔하는 내부 IFD 수 상한 — 실제 산출물(본체+마스크)을 넉넉히 담는다. */
export const MAX_PREVIEW_IFD_COUNT = 8;

const RECEIPT_DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/;

/** 준비 파일 BFF의 상대 경로 모양 — 페이지가 만드는 실제 작업 경로만 받는다. */
const FILE_ROUTE_PATTERN = /^\/api\/sites\/[^/\\?#\s\x00-\x1f\x7f@]+\/work-areas\/[^/\\?#\s\x00-\x1f\x7f@]+\/spatial-data-requests\/[^/\\?#\s\x00-\x1f\x7f@]+\/file$/;

const SAME_ORIGIN_BASE = "https://console.local";

/**
 * 같은 세션 BFF 읽기의 유한 대기 한도 — Core·워커 마감값을 바꾸지 않는
 * 브라우저 표시 전용 한도다.
 */
export const SPATIAL_DATA_PREVIEW_FETCH_TIMEOUT_MS = 60_000;

export type SpatialDataPreviewFailureKind =
  | "HTTP"
  | "NETWORK"
  | "CANCELLED"
  | "TIMEOUT"
  | "TOO_LARGE"
  | "SIZE_MISMATCH"
  | "HASH_MISMATCH"
  | "BAD_RECEIPT"
  | "UNSUPPORTED";

/** 영수증 대조 전에 실패하는 수신 오류 — 화면은 kind/status/code로만 문구를 고른다. */
export class SpatialDataPreviewError extends Error {
  readonly kind: SpatialDataPreviewFailureKind;
  readonly status: number | null;
  readonly code: string | null;
  readonly serverMessage: string | null;

  constructor(
    kind: SpatialDataPreviewFailureKind,
    message: string,
    options: { status?: number | null; code?: string | null; serverMessage?: string | null } = {},
  ) {
    super(message);
    this.name = "SpatialDataPreviewError";
    this.kind = kind;
    this.status = options.status ?? null;
    this.code = options.code ?? null;
    this.serverMessage = options.serverMessage ?? null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/**
 * 브라우저에 그릴 수 있는 디코딩 결과 — 원본 픽셀의 표시용 매핑이며
 * 정량값이 아니다.
 */
export interface DecodedReceiptPreview {
  width: number;
  height: number;
  /** false면 단일 밴드 상대 음영이다. */
  color: boolean;
  pixels: Uint8ClampedArray<ArrayBuffer>;
}

function matchesNoData(value: number, noData: number | null): boolean {
  if (noData === null) return false;
  if (Number.isNaN(noData)) return Number.isNaN(value);
  return value === noData;
}

function firstTagNumber(value: unknown): number | null {
  const candidate = Array.isArray(value) ? value[0] : value;
  return typeof candidate === "number" && Number.isFinite(candidate) ? candidate : null;
}

/**
 * TIFF 내부 마스크(IFD)를 찾아 읽는다. 판정 기준은 TIFF 6.0 마스크 관례다:
 * NewSubfileType 비트 2(값 4) + PhotometricInterpretation 4(투명 마스크) +
 * 단일 밴드 + 본체와 같은 픽셀 크기. geotiff 3.0.5는 별도 마스크 API를
 * 제공하지 않으므로, 이 IFD 스캔이 마스크의 유일한 근거다 — 0값 추측이나
 * 알파 추정은 하지 않는다.
 *
 * 마스크가 없으면 null이다. 마스크로 보이는 IFD가 둘 이상이거나, 크기가
 * 다르거나, 읽기에 실패하면 그리지 않고 거부한다(부분 렌더 없음).
 */
async function readInternalMask(
  tiff: import("geotiff").GeoTIFF,
  width: number,
  height: number,
): Promise<ArrayLike<number> | null> {
  const unsupported = (message: string) => new SpatialDataPreviewError("UNSUPPORTED", message);
  let count: number;
  try {
    count = await tiff.getImageCount();
  } catch {
    throw unsupported("준비된 출력의 내부 구조를 확인하지 못해 표시하지 않습니다. 일반 다운로드는 그대로 받을 수 있습니다.");
  }
  if (!Number.isSafeInteger(count) || count < 1 || count > MAX_PREVIEW_IFD_COUNT) {
    throw unsupported("준비된 출력의 내부 구조가 브라우저 표시 한계를 넘어 표시하지 않습니다. 일반 다운로드는 그대로 받을 수 있습니다.");
  }
  let mask: ArrayLike<number> | null = null;
  for (let index = 1; index < count; index += 1) {
    let candidate: Awaited<ReturnType<import("geotiff").GeoTIFF["getImage"]>>;
    try {
      candidate = await tiff.getImage(index);
    } catch {
      throw unsupported("준비된 출력의 내부 구조를 확인하지 못해 표시하지 않습니다. 일반 다운로드는 그대로 받을 수 있습니다.");
    }
    const directory = candidate.getFileDirectory();
    const subfile = firstTagNumber(directory.getValue("NewSubfileType"));
    const photometric = firstTagNumber(directory.getValue("PhotometricInterpretation"));
    if (subfile === null || (subfile & 4) !== 4 || photometric !== 4) continue;
    if (mask !== null) {
      throw unsupported("준비된 출력에 마스크가 둘 이상 있어 표시하지 않습니다. 일반 다운로드는 그대로 받을 수 있습니다.");
    }
    if (candidate.getSamplesPerPixel() !== 1) {
      throw unsupported("준비된 출력의 마스크 형식을 해석하지 못해 표시하지 않습니다. 일반 다운로드는 그대로 받을 수 있습니다.");
    }
    if (candidate.getWidth() !== width || candidate.getHeight() !== height) {
      throw unsupported("준비된 출력의 마스크 크기가 출력 크기와 달라 표시하지 않습니다. 일반 다운로드는 그대로 받을 수 있습니다.");
    }
    let rasters: ArrayLike<number>;
    try {
      rasters = (await candidate.readRasters({ interleave: true })) as unknown as ArrayLike<number>;
    } catch {
      throw unsupported("준비된 출력의 마스크를 읽지 못해 표시하지 않습니다. 일반 다운로드는 그대로 받을 수 있습니다.");
    }
    if (!rasters || rasters.length !== width * height) {
      throw unsupported("준비된 출력의 마스크를 읽지 못해 표시하지 않습니다. 일반 다운로드는 그대로 받을 수 있습니다.");
    }
    mask = rasters;
  }
  return mask;
}

function toDisplayPixels(
  rasters: ArrayLike<number>,
  width: number,
  height: number,
  samples: number,
  bits: number,
  noData: number | null,
  mask: ArrayLike<number> | null,
): Uint8ClampedArray<ArrayBuffer> {
  const count = width * height;
  const pixels = new Uint8ClampedArray(count * 4);
  const maskedOut = (index: number): boolean => mask !== null && mask[index] === 0;
  if (samples === 1) {
    // 단일 밴드는 GDAL NoData와 내부 마스크 제외를 함께 적용해 늘이기(stretch)한다.
    // 제외 픽셀은 투명으로 두며, min/max 계산에도 쓰지 않는다. 유효 0은 그대로 둔다.
    let min = Number.POSITIVE_INFINITY;
    let max = Number.NEGATIVE_INFINITY;
    let valid = 0;
    for (let i = 0; i < count; i += 1) {
      const value = rasters[i];
      if (!Number.isFinite(value) || matchesNoData(value, noData) || maskedOut(i)) continue;
      valid += 1;
      if (value < min) min = value;
      if (value > max) max = value;
    }
    if (valid === 0) {
      throw new SpatialDataPreviewError(
        "UNSUPPORTED",
        "선택한 창의 모든 픽셀이 NoData 또는 마스크 제외라 표시할 내용이 없습니다. 일반 다운로드는 그대로 받을 수 있습니다.",
      );
    }
    const span = max - min;
    for (let i = 0; i < count; i += 1) {
      const value = rasters[i];
      const offset = i * 4;
      if (!Number.isFinite(value) || matchesNoData(value, noData) || maskedOut(i)) {
        pixels[offset] = 0;
        pixels[offset + 1] = 0;
        pixels[offset + 2] = 0;
        pixels[offset + 3] = 0;
        continue;
      }
      const gray = span === 0 ? 128 : Math.round(((value - min) / span) * 255);
      pixels[offset] = gray;
      pixels[offset + 1] = gray;
      pixels[offset + 2] = gray;
      pixels[offset + 3] = 255;
    }
    return pixels;
  }
  const shift = bits === 8 ? 0 : bits === 16 ? 8 : -1;
  if (shift < 0) {
    throw new SpatialDataPreviewError("UNSUPPORTED", "준비된 출력 형식을 브라우저에서 해석하지 못했습니다. 일반 다운로드는 그대로 받을 수 있습니다.");
  }
  for (let i = 0; i < count; i += 1) {
    const offset = i * 4;
    if (maskedOut(i)) {
      pixels[offset] = 0;
      pixels[offset + 1] = 0;
      pixels[offset + 2] = 0;
      pixels[offset + 3] = 0;
      continue;
    }
    pixels[offset] = (rasters[i * samples] as number) >> shift;
    pixels[offset + 1] = (rasters[i * samples + 1] as number) >> shift;
    pixels[offset + 2] = (rasters[i * samples + 2] as number) >> shift;
    pixels[offset + 3] = samples === 4 ? ((rasters[i * samples + 3] as number) >> shift) : 255;
  }
  return pixels;
}

/**
 * 영수증에 묶인 바이트를 브라우저 표시용 픽셀로 푼다.
 *
 * - 호출 전에 fetchVerifiedReceiptBytes로 크기·해시를 대조했어야 한다.
 * - 단일 밴드는 GDAL NoData와 TIFF 내부 마스크 제외를 함께 적용해 투명
 *   처리하고 늘이기에서 제외한다. 마스크는 TIFF 6.0 관례 IFD(NewSubfileType
 *   비트 2 + PhotometricInterpretation 4 + 단일 밴드 + 동일 크기)로만
 *   판정하며, geotiff 3.0.5에 별도 마스크 API가 없으므로 0값 추측이나
 *   알파 추정은 하지 않는다. 4밴드의 전달 알파는 그대로 살린다.
 * - 좌표 재해석·보정·정량 계산을 하지 않는다.
 */
export async function decodeReceiptPreview(
  buffer: ArrayBuffer,
  expected: { width: number; height: number },
): Promise<DecodedReceiptPreview> {
  const undecodable = () => new SpatialDataPreviewError(
    "UNSUPPORTED",
    "준비된 출력 형식을 브라우저에서 해석하지 못했습니다. 일반 다운로드는 그대로 받을 수 있습니다.",
  );
  let fromArrayBuffer: (typeof import("geotiff"))["fromArrayBuffer"];
  try {
    ({ fromArrayBuffer } = await import("geotiff"));
  } catch {
    throw undecodable();
  }
  let tiff: Awaited<ReturnType<typeof fromArrayBuffer>>;
  try {
    tiff = await fromArrayBuffer(buffer.slice(0));
  } catch {
    throw undecodable();
  }
  let image: Awaited<ReturnType<typeof tiff.getImage>>;
  try {
    image = await tiff.getImage(0);
  } catch {
    throw undecodable();
  }
  const width = image.getWidth();
  const height = image.getHeight();
  if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width <= 0 || height <= 0) {
    throw undecodable();
  }
  if (width !== expected.width || height !== expected.height) {
    throw new SpatialDataPreviewError("BAD_RECEIPT", "준비 기록의 픽셀 크기와 받은 바이트가 달라 표시하지 않습니다. 아래 다운로드로 받으세요.");
  }
  if (width * height > SPATIAL_DATA_PREVIEW_MAX_PIXELS) {
    throw new SpatialDataPreviewError("TOO_LARGE", "준비된 출력이 브라우저 표시 한계를 넘어 미리보기를 표시하지 않습니다. 아래 다운로드로 받으세요.");
  }
  const samples = image.getSamplesPerPixel();
  if (samples !== 1 && samples !== 3 && samples !== 4) {
    throw undecodable();
  }
  const bits = image.getBitsPerSample(0);
  let rasters: ArrayLike<number>;
  try {
    rasters = (await image.readRasters({ interleave: true })) as unknown as ArrayLike<number>;
  } catch {
    throw undecodable();
  }
  if (!rasters || rasters.length !== width * height * samples) {
    throw undecodable();
  }
  let noData: number | null = null;
  try {
    noData = image.getGDALNoData();
  } catch {
    noData = null;
  }
  const mask = await readInternalMask(tiff, width, height);
  return {
    width,
    height,
    color: samples !== 1,
    pixels: toDisplayPixels(rasters, width, height, samples, bits, noData, mask),
  };
}

/**
 * 같은 세션의 준비 파일 BFF에서 바이트를 받아 Core 준비 기록과 대조한다.
 *
 * 권한·현재성 검사는 BFF→Core가 매번 다시 수행하므로, 여기서는 같은 세션의
 * 상대 경로만 받는다(외부 URL·자격증명 헤더를 다루지 않는다). 표시용 디코딩은
 * 크기·전체 SHA-256이 영수증과 정확히 일치할 때만 허용된다.
 */
/**
 * Fetches only a current Core-issued receipt's bytes through the same-session
 * guarded file BFF. The BFF rechecks auth/rights/currentness on every call;
 * this function adds the browser-side identity/size/hash gate before decode.
 *
 * The href must be the exact guarded file route the page built — absolute
 * URLs, protocol-relative URLs, backslashes, query/fragment smuggling, and
 * redirects are rejected before any fetch. A finite read deadline applies;
 * a user cancel stays CANCELLED and is distinct from TIMEOUT.
 */
export async function fetchVerifiedReceiptBytes(
  fileHref: string,
  expected: { outputSha256: string; outputSizeBytes: number },
  signal?: AbortSignal,
  options: { timeoutMs?: number } = {},
): Promise<ArrayBuffer> {
  if (typeof fileHref !== "string" || fileHref.length > 2048 || !FILE_ROUTE_PATTERN.test(fileHref)) {
    throw new SpatialDataPreviewError("BAD_RECEIPT", "준비된 파일 경로가 올바르지 않아 표시하지 않습니다.");
  }
  try {
    const parsed = new URL(fileHref, SAME_ORIGIN_BASE);
    if (parsed.origin !== SAME_ORIGIN_BASE || parsed.pathname !== fileHref) {
      throw new SpatialDataPreviewError("BAD_RECEIPT", "준비된 파일 경로가 올바르지 않아 표시하지 않습니다.");
    }
  } catch (error) {
    if (error instanceof SpatialDataPreviewError) throw error;
    throw new SpatialDataPreviewError("BAD_RECEIPT", "준비된 파일 경로가 올바르지 않아 표시하지 않습니다.");
  }
  if (!RECEIPT_DIGEST_PATTERN.test(expected.outputSha256)) {
    throw new SpatialDataPreviewError("BAD_RECEIPT", "출력 확인값 형식을 확인할 수 없어 표시하지 않습니다.");
  }
  if (
    !Number.isSafeInteger(expected.outputSizeBytes)
    || expected.outputSizeBytes < 1
  ) {
    throw new SpatialDataPreviewError("BAD_RECEIPT", "출력 크기 기록을 확인할 수 없어 표시하지 않습니다.");
  }
  if (expected.outputSizeBytes > SPATIAL_DATA_PREVIEW_MAX_BYTES) {
    throw new SpatialDataPreviewError("TOO_LARGE", "준비된 출력이 브라우저 표시 한계를 넘어 미리보기를 표시하지 않습니다.");
  }
  if (signal?.aborted) {
    throw new SpatialDataPreviewError("CANCELLED", "불러오기를 취소했습니다.");
  }

  const timeoutMs = options.timeoutMs ?? SPATIAL_DATA_PREVIEW_FETCH_TIMEOUT_MS;
  const deadline = Number.isSafeInteger(timeoutMs) && timeoutMs > 0
    ? timeoutMs
    : SPATIAL_DATA_PREVIEW_FETCH_TIMEOUT_MS;
  const combined = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    combined.abort();
  }, deadline);
  const onExternalAbort = () => combined.abort();
  signal?.addEventListener("abort", onExternalAbort, { once: true });

  let response: Response;
  try {
    response = await fetch(fileHref, {
      method: "GET",
      cache: "no-store",
      redirect: "error",
      signal: combined.signal,
    });
  } catch (error) {
    if (error instanceof SpatialDataPreviewError) throw error;
    if (timedOut) {
      throw new SpatialDataPreviewError("TIMEOUT", "준비된 파일을 받을 수 있는 시간을 넘겨 중단했습니다. 아래 다운로드로 받으세요.");
    }
    const aborted = signal?.aborted
      || combined.signal.aborted
      || (error instanceof DOMException && error.name === "AbortError");
    throw new SpatialDataPreviewError(
      aborted ? "CANCELLED" : "NETWORK",
      aborted ? "불러오기를 취소했습니다." : "준비된 파일을 받지 못했습니다. 현재 상태를 다시 확인하세요.",
    );
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onExternalAbort);
  }
  if (response.redirected || response.type === "opaqueredirect") {
    throw new SpatialDataPreviewError("NETWORK", "준비된 파일 경로가 바뀌어 표시하지 않습니다.");
  }
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new SpatialDataPreviewError("HTTP", "준비된 파일을 받지 못했습니다.", {
      status: response.status,
      code: isRecord(body) && typeof body.code === "string" ? body.code : null,
      serverMessage: isRecord(body) && typeof body.message === "string" ? body.message : null,
    });
  }
  if (!response.body) {
    throw new SpatialDataPreviewError("NETWORK", "준비된 파일 바이트를 받을 수 없습니다.");
  }

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  const hasher = sha256.create();
  let total = 0;
  let complete = false;
  const cancelReader = () => {
    try {
      void reader.cancel().catch(() => undefined);
    } catch {
      // 이미 닫혀 있다 — 1차 실패를 유지한다.
    }
  };
  const onAbort = () => cancelReader();
  combined.signal.addEventListener("abort", onAbort, { once: true });
  const timedOutError = () => new SpatialDataPreviewError(
    "TIMEOUT",
    "준비된 파일을 받을 수 있는 시간을 넘겨 중단했습니다. 아래 다운로드로 받으세요.",
  );
  try {
    while (true) {
      if (timedOut) throw timedOutError();
      if (combined.signal.aborted) throw new SpatialDataPreviewError("CANCELLED", "불러오기를 취소했습니다.");
      let result: ReadableStreamReadResult<Uint8Array>;
      try {
        result = await reader.read();
      } catch {
        if (timedOut) throw timedOutError();
        if (combined.signal.aborted) throw new SpatialDataPreviewError("CANCELLED", "불러오기를 취소했습니다.");
        throw new SpatialDataPreviewError("NETWORK", "준비된 파일 바이트를 읽을 수 없습니다.");
      }
      if (timedOut) throw timedOutError();
      if (combined.signal.aborted) throw new SpatialDataPreviewError("CANCELLED", "불러오기를 취소했습니다.");
      if (result.done) {
        complete = true;
        break;
      }
      total += result.value.byteLength;
      if (total > expected.outputSizeBytes || total > SPATIAL_DATA_PREVIEW_MAX_BYTES) {
        throw new SpatialDataPreviewError(
          "SIZE_MISMATCH",
          "받은 바이트가 Core 준비 기록과 달라 화면에 표시하지 않습니다.",
        );
      }
      chunks.push(result.value);
      hasher.update(result.value);
    }
  } finally {
    combined.signal.removeEventListener("abort", onAbort);
    if (!complete) cancelReader();
    reader.releaseLock();
  }
  if (total !== expected.outputSizeBytes) {
    throw new SpatialDataPreviewError("SIZE_MISMATCH", "받은 바이트가 Core 준비 기록과 달라 화면에 표시하지 않습니다.");
  }
  if (`sha256:${bytesToHex(hasher.digest())}` !== expected.outputSha256.toLowerCase()) {
    throw new SpatialDataPreviewError("HASH_MISMATCH", "받은 바이트가 Core 준비 기록과 달라 화면에 표시하지 않습니다.");
  }
  const result = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return result.buffer;
}
